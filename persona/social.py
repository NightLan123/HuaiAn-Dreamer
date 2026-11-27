"""Opt-in proactive contact: opportunities -> PMM decision -> bounded delivery -> feedback."""
from __future__ import annotations
import copy, datetime, json, re, threading, time
from zoneinfo import ZoneInfo
from .common import now, uid, dumps, ConfigError
from .provider import ProviderError,request_json
from .api_pmm import APIPMM
from .psychology import profile_condition,context_profile
from . import relationships as dy

DECIDE='''[SOCIAL_DECISION_V212]
这是主动联系决策，机会不等于必须发消息。结合此主体人格、当前模拟情绪、表达欲与未完成表达动机(expressive_drive)、情境关系、兴趣证据、历史联系与真实反馈决定 SEND 或 NO_ACTION。
默认 NO_ACTION；没有合适话题、关系不适合、对方可能不愿被打扰时保持沉默，不制造紧迫感或索取回应。
只使用给定会话的真实原文或记忆，不跨联系人透露内容，不把假设、AI自己的回复当用户兴趣事实，不虚构刚刚做过的事。
输出JSON {"action":"NO_ACTION或SEND","reason":"简短依据","topic":"有来源的轻量话题","evidence":[{"record_id":"提供的id","quote":"逐字引文"}]}。
SEND 必须至少一条来自用户或已记录用户信息的匹配证据，遵守self.boundaries；不要输出思维链。
'''
REALIZE='''[SOCIAL_REALIZE_V212]
根据给定的同一AI人格、语言风格、关系和已核对话题，写一条自然的主动消息。只输出实际文字，最多180字符。
不把主动联系说成用户刚刚提出的问题，不虚构见闻或承诺，不催促、不内疚施压。角色设定不是真实人生经历。只使用当前会话的证据。
'''

def normalize_recipients(values,s):
    """Accept old scoped addresses; plain numbers require one explicit channel."""
    if not isinstance(values,list):raise ConfigError('主动联系对象必须是号码列表',['/social/recipients'])
    result=[]
    for value in values:
        if not isinstance(value,str):raise ConfigError('主动联系号码必须是文本',['/social/recipients'])
        value=value.strip()
        if re.fullmatch(r'[0-9]+',value):
            channels=[k for k in ('private','group') if s.get(k+'_enabled') is True]
            if len(channels)!=1:raise ConfigError('号码无法确定是私聊还是群聊，请分别填写私聊 QQ 号和群号',['/social/recipients'])
            value=channels[0]+':qq:'+value
        result.append(value)
    return result

def readiness(c):
    """Explain activation prerequisites without enabling a connection or widening access."""
    s=c['social'];q=c['qq'];missing=[]
    if not q['enabled']:missing.append({'field':'/qq/enabled','message':'先到“QQ 连接”启用并保存 QQ 自动回复'})
    if not q.get('self_id'):missing.append({'field':'/qq/self_id','message':'填写并保存机器人自己的 QQ 号'})
    if not s['recipients']:missing.append({'field':'/social/recipients','message':'至少填写一个明确授权的私聊 QQ 号或群号'})
    for scope in s['recipients']:
        private=scope.startswith('private:');field='allowed_users' if private else 'allowed_groups'
        if scope.rsplit(':',1)[-1] not in list(map(str,q[field])):
            missing.append({'field':'/qq/'+field,'message':'主动联系的'+('私聊号码' if private else '群号')+'须先加入 QQ 连接页对应的允许名单'})
        if not s['private_enabled' if private else 'group_enabled']:
            missing.append({'field':'/social/'+('private_enabled' if private else 'group_enabled'),'message':'所填对象的'+('私聊' if private else '群聊')+'主动联系开关尚未开启'})
    return missing

def validate_social(c):
    s=c['social']
    for key in ('enabled','private_enabled','group_enabled'):
        if type(s.get(key)) is not bool:raise ValueError('主动社交开关无效')
    for key,lo,hi in [('idle_minutes',10,10080),('cooldown_minutes',10,10080),('daily_budget',1,20),('unanswered_limit',1,3)]:
        if type(s.get(key)) is not int or not lo<=s[key]<=hi:raise ValueError('主动社交频率超出范围')
    if not isinstance(s.get('recipients'),list) or len(s['recipients'])>100 or not all(isinstance(x,str) and re.fullmatch(r'(private|group):qq:[0-9]+',x) for x in s['recipients']):raise ConfigError('主动联系地址无效；请分别填写私聊 QQ 号和群号',['/social/recipients'])
    if len(set(s['recipients']))!=len(s['recipients']):raise ValueError('主动联系对象重复')
    for key in ('quiet_start','quiet_end'):
        if not isinstance(s.get(key),str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',s[key]):raise ValueError('免打扰时间格式应为 HH:MM')
    try:ZoneInfo(s.get('timezone',''))
    except (ValueError,KeyError):raise ValueError('主动社交时区无效') from None
    for field in ('allowed_users','allowed_groups'):
        if not isinstance(c['qq'].get(field),list):raise ConfigError('QQ 白名单必须是号码列表',['/qq/'+field])
    if s['enabled']:
        missing=readiness(c)
        if missing:raise ConfigError('启用主动联系还需：'+'；'.join(dict.fromkeys(v['message'] for v in missing)),[v['field'] for v in missing])

def quiet(s,t):
    clock=datetime.datetime.fromtimestamp(t,ZoneInfo(s['timezone'])).strftime('%H:%M');a,b=s['quiet_start'],s['quiet_end']
    return False if a==b else a<=clock<b if a<b else clock>=a or clock<b

class Social:
    def __init__(self,engine):
        self.engine=engine;self.lock=threading.Lock();self.thread=None;self.last_poll=0
        with engine.store.lock,engine.store.db:
            attempts=engine.store.meta('social_attempts') or []
            changed=False
            for a in attempts:
                if a.get('status')=='sending':a.update(status='uncertain',note='上次发送中断，不自动重试');changed=True
            if changed:engine.store.setmeta('social_attempts',attempts)
    def receive(self,parsed):
        st=self.engine.store
        with st.lock,st.db:
            contacts=st.meta('social_contacts') or {};scope=parsed['scope'];r=contacts.get(scope,{})
            if r.get('unanswered',0):
                st.event('social_feedback',{'scope':scope,'kind':'reply_received','last_outbound':r.get('last_attempt'),'latency_seconds':max(0,now()-r.get('last_sent_at',now())),'interpretation':'收到新消息，不等同于积极情绪或喜欢主动联系'})
            r.update(last_input_at=now(),last_event_key=parsed['key'],last_input_text=parsed.get('text','')[:1000],person=parsed['person'],unanswered=0)
            if re.fullmatch(r'\s*(?:请)?(?:不要主动联系我|别主动联系我|别再找我|不要再找我|stop messaging me|do not message me)[。.!！ ]*',parsed['text'],re.I):
                self.engine.journal.permission(scope+':proactive',parsed['person'],True);r.update(blocked=True,block_quote=parsed['text'][:1000]);st.event('social_feedback',{'scope':scope,'kind':'stop_request','quote':parsed['text'][:1000]})
            contacts[scope]=r;st.setmeta('social_contacts',contacts)
            if re.fullmatch(r'\s*(?:可以继续联系我|你可以继续联系我|可以恢复联系|you may message me again)[。.!！ ]*',parsed['text'],re.I):
                self.engine.journal.restore_permission(scope,parsed['person']);self.engine.journal.restore_permission(scope+':proactive',parsed['person']);permissions=st.meta('contact_permissions') or {};permissions.pop(scope+'|'+parsed['person'],None);st.setmeta('contact_permissions',permissions);r['blocked']=False;contacts[scope]=r;st.setmeta('social_contacts',contacts)
            if re.fullmatch(r'\s*(?:请)?(?:不要再联系我|别再联系我|不要再找我|别再找我|不要给我发消息|别给我发消息|stop messaging me|do not message me)[。.!！ ]*',parsed['text'],re.I):self.withdraw(scope,parsed['person'],parsed['text'])
    def withdraw(self,scope,person,quote):
        st=self.engine.store
        self.engine.journal.permission(scope,person,withdraw=True)
        with st.lock,st.db:
            blocked=st.meta('contact_permissions') or {};blocked[scope+'|'+person]={'withdrawn':True,'quote':quote[:1000],'at':now()};st.setmeta('contact_permissions',blocked)
            contacts=st.meta('social_contacts') or {};r=contacts.get(scope,{});r.update(blocked=scope.startswith('private:'),block_quote=quote[:1000]);contacts[scope]=r;st.setmeta('social_contacts',contacts)
            from . import expression_drive as ed
            drive_state=st.meta(ed.KEY)
            if drive_state is not None:
                updated_drive,_=ed.apply_delivery_outcome(drive_state,scope,person,'abandoned',at=now(),reason='contact_withdrawn')
                updated_drive['revision']+=1
                st.setmeta(ed.KEY,updated_drive)
            st.event('contact_withdrawn',{'scope':scope,'person':person,'source':'external_request'})
    def contact_allowed(self,scope,person):return not self.engine.journal.permission(scope,person) and not (self.engine.store.meta('contact_permissions') or {}).get(scope+'|'+person,{}).get('withdrawn')
    def status(self):
        c=self.engine.config.get()
        from . import expression_drive as ed
        return {'running':bool(self.thread and self.thread.is_alive()),'contacts':self.engine.store.meta('social_contacts') or {},'attempts':(self.engine.store.meta('social_attempts') or [])[-50:],'config':c['social'],'activation_missing':readiness(c),
                'expressive_drive':ed.status_summary(self.engine.store,self.engine.profile())}
    def gate(self,scope,t=None,preview=False):
        t=now() if t is None else t;c=self.engine.config.get();s=c['social'];contacts=self.engine.store.meta('social_contacts') or {};contact=contacts.get(scope,{})
        if not preview and not s['enabled']:return '自动主动联系已关闭'
        if not c['qq']['enabled']:return 'QQ 自动连接未启用'
        if scope not in s['recipients']:return '此对象未获主动联系授权'
        private=scope.startswith('private:');field='allowed_users' if private else 'allowed_groups'
        if scope.rsplit(':',1)[-1] not in list(map(str,c['qq'][field])):return '对象不在 QQ 白名单'
        if not s['private_enabled' if private else 'group_enabled']:return '私聊或群聊主动开关未开启'
        if quiet(s,t):return '处于免打扰时间'
        if contact.get('blocked') or (scope.startswith('private:') and (not self.contact_allowed(scope,'qq:'+scope.rsplit(':',1)[-1]) or self.engine.journal.permission(scope+':proactive','qq:'+scope.rsplit(':',1)[-1]))):return '对方已要求停止主动联系'
        if not contact.get('last_input_at'):return '尚无此对象的真实入站互动'
        if t-contact['last_input_at']<s['idle_minutes']*60:return '距离最近交流太近'
        if contact.get('unanswered',0)>=s['unanswered_limit']:return '达到未回复次数上限'
        if t-contact.get('last_attempt',0)<s['cooldown_minutes']*60:return '仍在主动联系冷却时间内'
        if t-contact.get('last_evaluated_at',0)<s['idle_minutes']*60:return '刚刚评估过，等待下次机会'
        day=datetime.datetime.fromtimestamp(t,ZoneInfo(s['timezone'])).date()
        attempts=self.engine.store.meta('social_attempts') or []
        count=sum(datetime.datetime.fromtimestamp(a['at'],ZoneInfo(s['timezone'])).date()==day for a in attempts)
        if count>=s['daily_budget']:return '当前人格的每日主动联系预算已用完'
        return ''
    def poll(self):
        if now()-self.last_poll<15:return
        self.last_poll=now()
        if self.thread and self.thread.is_alive():return
        candidates=[]
        for scope in self.engine.config.get()['social']['recipients']:
            if not self.gate(scope):
                try:
                    ev=self.engine.advance_expressive_drive_idle(scope,commit=True)
                    if not ev.get('proactive_eligible') or not ev.get('has_concrete_motive'):
                        continue
                    score=float(ev.get('proactive_motive_score',0.))+0.15*float(ev.get('urgency',0.))
                except Exception:
                    continue
                candidates.append((score,scope))
        if candidates:
            candidates.sort(key=lambda item:item[0],reverse=True)
            chosen=candidates[0][1]
            self.thread=threading.Thread(target=self._auto,args=(chosen,),daemon=True,name='persona-social');self.thread.start();return
    def _auto(self,scope):
        try:self.evaluate(scope,send=True)
        except Exception:pass # evaluate writes explicit failure audit records.
    def evaluate(self,scope,send=False):
        if not self.lock.acquire(blocking=False):raise ValueError('主动社交评估正在运行')
        e=self.engine;st=e.store;attempt=None;run=None;clients=[];started=time.monotonic();ledger_context=None
        try:
            with e.lock:
                reason=self.gate(scope,preview=not send)
                if reason:return {'action':'NO_ACTION','reason':reason,'sent':False}
                cfg=e.config.get();profile=e.profile();contacts=st.meta('social_contacts') or {};contact=copy.deepcopy(contacts[scope]);session_rows=st.rows('SELECT * FROM sessions WHERE scope=? ORDER BY created_at DESC LIMIT 1',(scope,))
                if not session_rows:return {'action':'NO_ACTION','reason':'没有可延续的真实会话','sent':False}
                session=session_rows[0];hist=st.history(session['id'],16);records=[{'id':r['id'],'text':r['content'][:2000],'turn_id':r.get('turn_id'),'created_at':r.get('created_at')} for r in hist if r['role']=='user']
                relations=[dy.policy_relation(v) for v in (st.meta('pmm_dyads') or {}).values() if v['context_id']==scope][-20:]
                from . import expression_drive as ed
                act_view=e.activity(scope,session['person'],session['id'])
                _,drive_eval=ed.evaluate_proactive(
                    st,profile,scope,person=session['person'],session_id=session['id'],at=now(),
                    affect_view=act_view,relation=relations[-1] if relations else {},recent_records=records,session_history=hist,commit=send
                )
                selected_motive=copy.deepcopy(drive_eval.get('active_motive')) if isinstance(drive_eval.get('active_motive'),dict) else None
                selected_motive_id=selected_motive.get('motive_id') if selected_motive else None
                from .motive_generation import candidate_current
                if not candidate_current(e,selected_motive):
                    return {'action':'NO_ACTION','reason':'候选来源或会话已经变化，暂不联系','sent':False}
                role_query='\n'.join(r['text'] for r in records[-2:])
                motive_anchor=((drive_eval.get('active_motive') or {}).get('content_anchor') or {})
                if isinstance(motive_anchor.get('topic'),str) and motive_anchor['topic'].strip():
                    role_query=(role_query+'\n'+motive_anchor['topic'].strip()).strip()
                memories=e.retrieve(role_query,scope,4)
                records += [{'id':m['id'],'text':m['evidence'][:2000]} for m in memories if m['kind'] not in ('hypothesis','self_observation') and m['evidence']]
                if (selected_motive or {}).get('origin')=='memory_reflection':
                    for source in selected_motive.get('source_evidence',[]):
                        if source['ref'] not in {r['id'] for r in records}:records.append({'id':source['ref'],'text':source['quote']})
                from .prompt_compiler import emotion_view
                persona_view=e.persona_views.scoped_views(profile,scope)
                from .prompt_compiler import runtime_persona
                persona_view['generator_view']=runtime_persona(persona_view['generator_view'],query=role_query,purpose='generator')
                persona_view['checker_view']=runtime_persona(persona_view['checker_view'],query=role_query,purpose='checker')
                context={'self':copy.deepcopy(persona_view['generator_view']),'persona_view_revision':persona_view['version_id'],
                    'emotion':emotion_view(act_view),'expressive_drive':{k:copy.deepcopy(drive_eval[k]) for k in ('activation','urgency','persistence','expressive_intent','has_concrete_motive','proactive_motive_score','general_initiation_tendency','general_tendency_not_sufficient_alone','proactive_eligible','ineligible_reason','active_motive','intended_expression','unfinished_motives','regulation_strategy') if k in drive_eval},
                    'relationships':relations,'records':records,
                    'history':[{'role':r['role'],'content':r['content'][:2000]} for r in hist], 'feedback':contact,'budget':cfg['social']['daily_budget']}
                if e.mode()!='api':
                    relation=relations[-1] if relations else {'trust':.5,'affection':.5,'familiarity':0,'interactions':0}
                    decoded=e.model.decode(e.input_vector(' '.join(r['text'] for r in records[-2:]),{},profile,act_view['emotion'],relation,act_view),[])
                    context['numeric_pmm_condition']={k:decoded[k] for k in ('state','style')}
                if send:
                    contacts[scope]['last_evaluated_at']=now()
                    with st.lock,st.db:st.setmeta('social_contacts',contacts)
            run=e.journal.start(profile['id'],session['id'],['social-opportunity:'+str(contact.get('last_event_key') or session['id'])],scope) if send else None
            if run:
                from . import token_ledger
                ledger_context=token_ledger.begin(e.journal,run)
                run['persona_version_id']=persona_view['version_id']
                run['attempt_id']=run['turn_id']
                run['motive_id']=selected_motive_id
                run['expressive_drive']=copy.deepcopy(context['expressive_drive'])
                e.journal.save(run)
            context['boundary_context']=e.boundaries.context(scope,session['person']);context['claim_memory']=e.claims.recent(scope)
            client=APIPMM(cfg,e.pmm_provider_factory).provider if cfg['pmm']['mode']=='api' else e.provider_factory(cfg)
            clients.append(client)
            if run:client.trace_context={**{k:run[k] for k in ('turn_id','trace_id','session_id','persona_id')},'persona_view_revision':persona_view['version_id'],'component_role':'PMM-A' if cfg['pmm']['mode']=='api' else 'General'}
            result=client.complete([{'role':'system','content':DECIDE},{'role':'user','content':dumps(context)}],structured=True)
            if not isinstance(result,dict) or result.get('action') not in ('NO_ACTION','SEND'):raise ProviderError('主动社交决策无效')
            result={k:result.get(k) for k in ('action','reason','topic','evidence')};result['reason']=str(result['reason'] or '')[:500];result['topic']=str(result['topic'] or '')[:1000]
            sources={r['id']:r['text'] for r in records};evidence=result['evidence']
            valid=[r for r in evidence if isinstance(r,dict) and r.get('record_id') in sources and isinstance(r.get('quote'),str) and r['quote'].strip() and r['quote'] in sources[r['record_id']]] if isinstance(evidence,list) else []
            result['evidence']=valid
            result['expressive_drive']={k:copy.deepcopy(drive_eval[k]) for k in ('activation','urgency','persistence','expressive_intent','has_concrete_motive','proactive_motive_score','general_initiation_tendency','proactive_eligible','ineligible_reason','active_motive','intended_expression') if k in drive_eval}
            if result['action']=='SEND' and not valid:result.update(action='NO_ACTION',reason='话题缺少可核对的真实来源')
            if result['action']=='SEND' and not drive_eval.get('proactive_eligible',False):
                result.update(action='NO_ACTION',reason='当前缺少具体未完成表达目标或处于表达抑制状态，不单凭人格基线发起主动联系')
            if any(b.get('enabled') and b.get('hard') and any(k.lower() in result['topic'].lower() for k in b.get('keywords',[]) if k) for b in profile['boundaries']):result.update(action='NO_ACTION',reason='话题触及启用的硬边界')
            with st.lock,st.db:st.event('social_decision',{'scope':scope,'preview':not send,**result,'duration_ms':round((time.monotonic()-started)*1000)})
            if result['action']=='NO_ACTION' or not send:
                if send:
                    _,deferred_motive,ar_fb=ed.apply_proactive_outcome(
                        st,profile,scope,session['person'],'deferred',
                        at=now(),reason=result['reason'],
                        turn_id=run['turn_id'] if run else None,
                        attempt_id=run['turn_id'] if run else None,
                        target_motive_id=selected_motive_id,
                        motive_id_explicit=True,
                        relation=relations[-1] if relations else None
                    )
                    if deferred_motive:
                        result['expressive_drive']['active_motive']=deferred_motive
                        result['expressive_drive']['status']=deferred_motive['status']
                    if ar_fb:
                        result['expressive_drive']['emotion_feedback']=ar_fb
                if run:run.update(status='NO_ACTION',action_state='NO_ACTION',ended_at=now(),calls=getattr(client,'calls',[]));e.journal.save(run)
                return {**result,'sent':False,'preview':not send}
            general=e.provider_factory(cfg);decision={'decision_id':uid(),'decision_revision':1,'action':'reply'}
            clients.append(general)
            run.update(decision_id=decision['decision_id'],decision_revision=1,selected_action='reply',action_state='REPLY');e.journal.save(run)
            general.trace_context={**{k:run[k] for k in ('turn_id','trace_id','session_id','persona_id','decision_id','decision_revision')},'persona_view_revision':persona_view['version_id'],'component_role':'General'}
            reply=general.complete([{'role':'system','content':REALIZE},{'role':'user','content':dumps({**context,'decision':result})}])
            from .validation import ACTION_CHECK_PROMPT,candidate_check,inspect_candidate,safe_check,InspectionFailure
            for regeneration in range(2):
                run.setdefault('candidate_archive',[]).append({'attempt':regeneration,'text':reply if isinstance(reply,str) else None})
                run.update(candidate_status='GENERATED',regenerations=regeneration,candidate_chars=len(reply) if isinstance(reply,str) else 0)
                e.journal.save(run)
                hard=[copy.deepcopy(b) for b in profile['boundaries'] if b.get('enabled') and b.get('hard')]
                relevant=[b for b in hard if any(isinstance(k,str) and k.strip() and k.lower() in (str(reply)+'\n'+result['topic']).lower() for k in b.get('keywords',[]))]
                check_context={'input':result['topic'],'actual_tool_receipts':[],'evidence_context':valid,
                    'hard_constraints':hard,'high_risk':bool(relevant),'permission_verified':False,
                    'persona':copy.deepcopy(persona_view['checker_view'])}
                checked=inspect_candidate(decision,reply,check_context)
                if regeneration and len(run.get('candidate_archive',[]))>1 and reply==run['candidate_archive'][-2].get('text') and (run.get('candidate_inspection') or {}).get('disposition')=='REPAIR_CANDIDATE':
                    checked.update(compliant=False,disposition='REPAIR_CANDIDATE',checker_required=False,trigger_reason='unchanged_previously_verified_violation')
                checked.update(decision_id=decision['decision_id'],decision_revision=1,expected_action='reply',
                    detected_action='reply',spans=[],failure_code='NONE',checker_status='local_only')
                if isinstance(reply,str) and len(reply)>400:
                    checked['local_checks'].append({'code':'SOCIAL_TEXT_LENGTH','status':'failed','max_chars':400})
                    checked.update(compliant=False,disposition='REPAIR_CANDIDATE',checker_required=False)
                if checked.get('checker_required'):
                    # Use only the candidate, cited topic and relevant constraints.
                    # The existing full social context is not duplicated for review.
                    checker_context={'decision_id':decision['decision_id'],'decision_revision':1,'expected_action':'reply',
                        'candidate':reply,'input':result['topic'],'actual_tool_receipts':[],'hard_constraints':relevant,
                        'evidence_context':valid,'trigger_reason':checked['trigger_reason'],
                        'persona':copy.deepcopy(persona_view['checker_view']),'persona_view_revision':persona_view['version_id']}
                    checker_context['suspected_issues']=checked.get('suspected_issues',[])
                    original=getattr(general,'config',None)
                    try:
                        if isinstance(original,dict):general.config={**original,'json_repair':False}
                        value=general.complete([{'role':'system','content':ACTION_CHECK_PROMPT},{'role':'user','content':dumps(checker_context)}],structured=True)
                        checked=candidate_check(value,decision,reply,check_context)
                    except (ProviderError,TimeoutError,ConnectionError,ValueError,TypeError,KeyError) as ex:
                        hard_review=checked.get('hard_review_required',True)
                        checked.update(compliant=not hard_review,disposition='CHECKER_UNAVAILABLE' if hard_review else 'SEND_WITH_NOTE',checker_status='unavailable',
                            failure_code='CHECKER_UNAVAILABLE',checker_error=type(ex).__name__)
                    finally:
                        if isinstance(original,dict):general.config=original
                run['candidate_inspection']=safe_check(checked);run['candidate_check']=run['candidate_inspection']
                run.setdefault('inspections',[]).append(copy.deepcopy(run['candidate_inspection']))
                run['calls']=[call for provider in clients for call in getattr(provider,'calls',[])]
                e.journal.save(run)
                if checked.get('compliant') and checked['disposition'] in ('SEND','SEND_WITH_NOTE'):break
                if checked['disposition'] in ('CHECKER_UNAVAILABLE','HOLD_HARD_CONSTRAINT'):
                    run['candidate_status']=checked['disposition'];e.journal.save(run)
                    raise InspectionFailure(checked['disposition'],{'candidate_inspection':safe_check(checked)})
                if regeneration:
                    run['candidate_status']='CANDIDATE_REPAIR_REQUIRED';e.journal.save(run)
                    raise InspectionFailure('CANDIDATE_REPAIR_REQUIRED',{'candidate_inspection':safe_check(checked)})
                repair={'input':result['topic'],'candidate':reply,'repair':safe_check(checked),'evidence_context':valid,
                    'hard_constraints':relevant,'actual_tool_receipts':[],'persona':copy.deepcopy(persona_view['generator_view']),
                    'persona_view_revision':persona_view['version_id']}
                reply=general.complete([{'role':'system','content':REALIZE},
                    {'role':'user','content':'[SOCIAL_CANDIDATE_REPAIR_V282] 仅修正已证实的问题，保持有来源的主动话题。\n'+dumps(repair)}])
            run.update(candidate_status='VALIDATED',calls=getattr(client,'calls',[])+getattr(general,'calls',[]));e.journal.save(run)
            with e.lock,st.lock:
                current=e.config.get();latest=(st.meta('social_contacts') or {}).get(scope,{})
                if not candidate_current(e,selected_motive) or current!=cfg or latest.get('last_input_at')!=contact.get('last_input_at') or latest.get('blocked') or e.profile()['revision']!=profile['revision'] or quiet(current['social'],now()) or not self.contact_allowed(scope,session['person']) or e.journal.permission(scope+':proactive',session['person']) or e.boundaries.context(scope,session['person'])!=context['boundary_context']:
                    run.update(status='CANCELLED',ended_at=now());e.journal.save(run)
                    return {'action':'NO_ACTION','reason':'生成期间配置、人格或对话已变化，取消发送','sent':False}
                # Reserve before delivery: an ambiguous transport result never triggers an automatic resend.
                attempt_id=run['turn_id']
                attempt={'id':attempt_id,'turn_id':run['turn_id'],'attempt_id':attempt_id,'motive_id':selected_motive_id,'scope':scope,'person':session['person'],'at':now(),'status':'sending','reply':reply,'decision':result}
                with st.lock,st.db:
                    attempts=st.meta('social_attempts') or [];attempts.append(attempt);st.setmeta('social_attempts',attempts)
                    contacts=st.meta('social_contacts') or {};contacts[scope].update(last_attempt=attempt['at'],last_sent_at=attempt['at'],unanswered=contacts[scope].get('unanswered',0)+1);st.setmeta('social_contacts',contacts)
                    if selected_motive_id:
                        ed_base=st.meta(ed.KEY)
                        if ed_base is not None:
                            ed_bound=ed.bind_proactive_send_plan(ed_base,profile['id'],scope,session['person'],motive_id=selected_motive_id,turn_id=run['turn_id'],attempt_id=attempt_id,at=attempt['at'])
                            st.setmeta(ed.KEY,ed_bound)
                from .qq import verify_bot
                verify_bot(cfg['qq'])
                private=scope.startswith('private:');dest={'user_id' if private else 'group_id':int(scope.rsplit(':',1)[-1])}
                run['pre_send_status']='VALID';e.journal.save(run)
                envelope={'bot':cfg['qq'].get('self_id'),'target':dest,'action':'send_private_msg' if private else 'send_group_msg','message':[{'type':'text','data':{'text':reply}}]}
                motive_src_ids=list(selected_motive.get('source_event_ids') or [ev.get('ref') for ev in selected_motive.get('source_evidence',[]) if isinstance(ev,dict) and ev.get('ref')]) if selected_motive else []
                plan={'format':'social-commit/1','turn_id':run['turn_id'],'attempt_id':attempt_id,'persona_id':profile['id'],'session_id':session['id'],'scope':scope,'person':session['person'],'reply':reply,'at':now(),'message_row_id':run['turn_id']+':a:0','source_event_ids':motive_src_ids or [r['id'] for r in records[:4]],'motive_id':selected_motive_id}
                identifier=e.journal.prepare(run,envelope,plan)
                receipt=e.journal.dispatch(identifier,lambda v:request_json(cfg['qq']['api_url'].rstrip('/')+'/'+v['action'],{**v['target'],'message':v['message']},cfg['qq']['api_token'],20))
                bound_receipt={**receipt,'turn_id':run['turn_id'],'attempt_id':attempt_id,'motive_id':selected_motive_id}
                e.journal.transition(identifier,'ACKNOWLEDGED',bound_receipt)
                plan['delivery_receipt']=bound_receipt;run['proactive_commit_plan']=copy.deepcopy(plan)
                run.update(delivery_status='ACKNOWLEDGED',qq_message_id=receipt['message_id'],delivery_receipt=bound_receipt);run['timing']={'first_ack_ms':round((time.monotonic()-started)*1000)};e.journal.save(run)
                commit_out=e.commit_social(plan)
                if isinstance(commit_out,dict) and commit_out.get('motive'):
                    result['expressive_drive']['active_motive']=commit_out['motive']
                    result['expressive_drive']['status']=commit_out['motive']['status']
                run.update(status='COMPLETED',delivery_status='COMMITTED',memory_commit_status='COMMITTED',learning_status='AWAITING_EXTERNAL_FEEDBACK',ended_at=now());e.journal.save(run)
                return {**result,'sent':True,'status':'sent','reply':reply}
        except Exception as ex:
            with st.lock,st.db:
                if attempt:
                    attempts=st.meta('social_attempts') or []
                    for a in attempts:
                        if a['id']==attempt['id']:a['status']='sent_postprocess_pending' if run and run.get('delivery_status')=='ACKNOWLEDGED' else 'failed' if getattr(ex,'code',None) in ('VALIDATION_FAILED','DELIVERY_FAILED') else 'uncertain'
                    st.setmeta('social_attempts',attempts)
                if run:
                    run.update(status='POSTPROCESS_FAILED' if run.get('delivery_status')=='ACKNOWLEDGED' else getattr(ex,'code','FAILED'),ended_at=now(),error={'exception_type':type(ex).__name__,'details':getattr(ex,'details',{})},calls=[call for provider in clients for call in getattr(provider,'calls',[])])
                    if getattr(ex,'code',None) in ('DELIVERY_UNKNOWN','DELIVERY_FAILED'):run['delivery_status']=ex.code
                    e.journal.save(run)
                st.event('social_failed',{'scope':scope,'error':str(ex) if isinstance(ex,(ValueError,ProviderError)) else '主动社交处理失败','attempt_id':attempt['id'] if attempt else None})
            if send and 'session' in locals() and not (run and run.get('delivery_status')=='ACKNOWLEDGED'):
                try:
                    from . import expression_drive as ed
                    ed.apply_proactive_outcome(
                        st,profile,scope,session['person'],'failed',
                        at=now(),reason=type(ex).__name__,
                        turn_id=run['turn_id'] if run else None,
                        attempt_id=run['turn_id'] if run else None,
                        target_motive_id=selected_motive_id if 'selected_motive_id' in locals() else None,
                        motive_id_explicit=True,
                        relation=relations[-1] if 'relations' in locals() and relations else None
                    )
                except Exception:
                    pass
            raise
        finally:
            if ledger_context is not None:token_ledger.end(ledger_context)
            self.lock.release()
    def unblock(self,scope):
        st=self.engine.store
        with self.engine.lock,st.lock,st.db:
            rows=st.meta('social_contacts') or {}
            if scope not in rows:raise ValueError('联系对象不存在')
            if scope.startswith('private:') and (self.engine.journal.permission(scope,'qq:'+scope.rsplit(':',1)[-1]) or self.engine.journal.permission(scope+':proactive','qq:'+scope.rsplit(':',1)[-1])):raise ValueError('对方已明确撤回联系许可；需其本人发来“可以继续联系我”恢复，主人解除暂停不能覆盖撤回')
            rows[scope]['blocked']=False;rows[scope]['unblocked_by']='owner';st.setmeta('social_contacts',rows);st.event('social_unblocked',{'scope':scope})
        return {'ok':True}
