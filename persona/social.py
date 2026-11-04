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
这是主动联系决策，机会不等于必须发消息。结合此主体人格、当前模拟情绪、情境关系、兴趣证据、历史联系与真实反馈决定 SEND 或 NO_ACTION。
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
            r.update(last_input_at=now(),last_event_key=parsed['key'],person=parsed['person'],unanswered=0)
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
            st.event('contact_withdrawn',{'scope':scope,'person':person,'source':'external_request'})
    def contact_allowed(self,scope,person):return not self.engine.journal.permission(scope,person) and not (self.engine.store.meta('contact_permissions') or {}).get(scope+'|'+person,{}).get('withdrawn')
    def status(self):
        c=self.engine.config.get()
        return {'running':bool(self.thread and self.thread.is_alive()),'contacts':self.engine.store.meta('social_contacts') or {},'attempts':(self.engine.store.meta('social_attempts') or [])[-50:],'config':c['social'],'activation_missing':readiness(c)}
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
        for scope in self.engine.config.get()['social']['recipients']:
            if not self.gate(scope):
                self.thread=threading.Thread(target=self._auto,args=(scope,),daemon=True,name='persona-social');self.thread.start();return
    def _auto(self,scope):
        try:self.evaluate(scope,send=True)
        except Exception:pass # evaluate writes explicit failure audit records.
    def evaluate(self,scope,send=False):
        if not self.lock.acquire(blocking=False):raise ValueError('主动社交评估正在运行')
        e=self.engine;st=e.store;attempt=None;run=None;started=time.monotonic()
        try:
            with e.lock:
                reason=self.gate(scope,preview=not send)
                if reason:return {'action':'NO_ACTION','reason':reason,'sent':False}
                cfg=e.config.get();profile=e.profile();contacts=st.meta('social_contacts') or {};contact=copy.deepcopy(contacts[scope]);session_rows=st.rows('SELECT * FROM sessions WHERE scope=? ORDER BY created_at DESC LIMIT 1',(scope,))
                if not session_rows:return {'action':'NO_ACTION','reason':'没有可延续的真实会话','sent':False}
                session=session_rows[0];hist=st.history(session['id'],12);records=[{'id':r['id'],'text':r['content'][:2000]} for r in hist if r['role']=='user']
                memories=e.retrieve(' '.join(r['text'] for r in records[-2:]),scope,4)
                records += [{'id':m['id'],'text':m['evidence'][:2000]} for m in memories if m['kind'] not in ('hypothesis','self_observation') and m['evidence']]
                relations=[dy.policy_relation(v) for v in (st.meta('pmm_dyads') or {}).values() if v['context_id']==scope][-20:]
                context={'self':profile_condition(context_profile(profile,scope)),'emotion':e.activity(),'relationships':relations,'records':records,'history':[{'role':r['role'],'content':r['content'][:2000]} for r in hist], 'feedback':contact,'budget':cfg['social']['daily_budget']}
                if e.mode()!='api':
                    relation=relations[-1] if relations else {'trust':.5,'affection':.5,'familiarity':0,'interactions':0}
                    decoded=e.model.decode(e.input_vector(' '.join(r['text'] for r in records[-2:]),{},profile,e.activity()['emotion'],relation,e.activity()),[])
                    context['numeric_pmm_condition']={k:decoded[k] for k in ('state','style','action_probabilities','influence')}
                if send:
                    contacts[scope]['last_evaluated_at']=now()
                    with st.lock,st.db:st.setmeta('social_contacts',contacts)
            run=e.journal.start(profile['id'],session['id'],['social-opportunity:'+str(contact.get('last_event_key') or session['id'])],scope) if send else None
            context['boundary_context']=e.boundaries.context(scope,session['person']);context['claim_memory']=e.claims.recent(scope)
            client=APIPMM(cfg,e.pmm_provider_factory).provider if cfg['pmm']['mode']=='api' else e.provider_factory(cfg)
            if run:client.trace_context={k:run[k] for k in ('turn_id','trace_id','session_id','persona_id')}
            result=client.complete([{'role':'system','content':DECIDE},{'role':'user','content':dumps(context)}],structured=True)
            if not isinstance(result,dict) or result.get('action') not in ('NO_ACTION','SEND'):raise ProviderError('主动社交决策无效')
            result={k:result.get(k) for k in ('action','reason','topic','evidence')};result['reason']=str(result['reason'] or '')[:500];result['topic']=str(result['topic'] or '')[:1000]
            sources={r['id']:r['text'] for r in records};evidence=result['evidence']
            valid=[r for r in evidence if isinstance(r,dict) and r.get('record_id') in sources and isinstance(r.get('quote'),str) and r['quote'].strip() and r['quote'] in sources[r['record_id']]] if isinstance(evidence,list) else []
            result['evidence']=valid
            if result['action']=='SEND' and not valid:result.update(action='NO_ACTION',reason='话题缺少可核对的真实来源')
            if any(b.get('enabled') and b.get('hard') and any(k.lower() in result['topic'].lower() for k in b.get('keywords',[]) if k) for b in profile['boundaries']):result.update(action='NO_ACTION',reason='话题触及启用的硬边界')
            with st.lock,st.db:st.event('social_decision',{'scope':scope,'preview':not send,**result,'duration_ms':round((time.monotonic()-started)*1000)})
            if result['action']=='NO_ACTION' or not send:
                if run:run.update(status='NO_ACTION',action_state='NO_ACTION',ended_at=now(),calls=getattr(client,'calls',[]));e.journal.save(run)
                return {**result,'sent':False,'preview':not send}
            general=e.provider_factory(cfg);decision={'decision_id':uid(),'decision_revision':1,'action':'reply'}
            run.update(decision_id=decision['decision_id'],decision_revision=1,selected_action='reply',action_state='REPLY');e.journal.save(run)
            general.trace_context={k:run[k] for k in ('turn_id','trace_id','session_id','persona_id','decision_id','decision_revision')}
            reply=general.complete([{'role':'system','content':REALIZE},{'role':'user','content':dumps({**context,'decision':result})}])
            if not isinstance(reply,str) or not reply.strip() or len(reply)>400:raise ProviderError('主动消息为空或过长，未发送')
            if any(b.get('enabled') and b.get('hard') and any(k.lower() in reply.lower() for k in b.get('keywords',[]) if k) for b in profile['boundaries']):raise ProviderError('主动消息触及启用的硬边界，未发送')
            from .validation import ACTION_CHECK_PROMPT,candidate_check,validated_call,safe_check,ValidationFailure
            for regeneration in range(2):
                if any(b.get('enabled') and b.get('hard') and any(k.lower() in reply.lower() for k in b.get('keywords',[]) if k) for b in profile['boundaries']):raise ProviderError('主动消息触及启用的硬边界，未发送')
                checked=validated_call(general,[{'role':'system','content':ACTION_CHECK_PROMPT},{'role':'user','content':dumps({'decision_id':decision['decision_id'],'decision_revision':1,'expected_action':'reply','candidate':reply,'evidence_context':records,'boundary_context':context['boundary_context'],'actual_tool_receipts':[]})}],lambda v:candidate_check(v,decision,reply),run['validation'])
                run.update(candidate_check=safe_check(checked),regenerations=regeneration,candidate_chars=len(reply));e.journal.save(run)
                if checked['compliant']:break
                if regeneration:raise ValidationFailure('candidate-action-check/1','social_candidate',[{'path':'/candidate','expected':'reply within permissions','actual_type':'string','reason':checked['failure_code']}])
                reply=general.complete([{'role':'system','content':REALIZE},{'role':'user','content':dumps({**context,'decision':result,'repair':checked})}])
                if not isinstance(reply,str) or not reply.strip() or len(reply)>400:raise ValueError('修复后的主动消息无效')
            run.update(candidate_status='VALIDATED',calls=getattr(client,'calls',[])+getattr(general,'calls',[]));e.journal.save(run)
            with e.lock,st.lock:
                current=e.config.get();latest=(st.meta('social_contacts') or {}).get(scope,{})
                if current!=cfg or latest.get('last_input_at')!=contact.get('last_input_at') or latest.get('blocked') or e.profile()['revision']!=profile['revision'] or quiet(current['social'],now()) or not self.contact_allowed(scope,session['person']) or e.journal.permission(scope+':proactive',session['person']) or e.boundaries.context(scope,session['person'])!=context['boundary_context']:
                    run.update(status='CANCELLED',ended_at=now());e.journal.save(run)
                    return {'action':'NO_ACTION','reason':'生成期间配置、人格或对话已变化，取消发送','sent':False}
                # Reserve before delivery: an ambiguous transport result never triggers an automatic resend.
                attempt={'id':run['turn_id'],'scope':scope,'at':now(),'status':'sending','reply':reply,'decision':result}
                with st.lock,st.db:
                    attempts=st.meta('social_attempts') or [];attempts.append(attempt);st.setmeta('social_attempts',attempts)
                    contacts=st.meta('social_contacts') or {};contacts[scope].update(last_attempt=attempt['at'],last_sent_at=attempt['at'],unanswered=contacts[scope].get('unanswered',0)+1);st.setmeta('social_contacts',contacts)
                from .qq import verify_bot
                verify_bot(cfg['qq'])
                private=scope.startswith('private:');dest={'user_id' if private else 'group_id':int(scope.rsplit(':',1)[-1])}
                run['pre_send_status']='VALID';e.journal.save(run)
                envelope={'bot':cfg['qq'].get('self_id'),'target':dest,'action':'send_private_msg' if private else 'send_group_msg','message':[{'type':'text','data':{'text':reply}}]}
                plan={'format':'social-commit/1','turn_id':run['turn_id'],'session_id':session['id'],'scope':scope,'reply':reply,'at':now()}
                identifier=e.journal.prepare(run,envelope,plan)
                receipt=e.journal.dispatch(identifier,lambda v:request_json(cfg['qq']['api_url'].rstrip('/')+'/'+v['action'],{**v['target'],'message':v['message']},cfg['qq']['api_token'],20))
                run.update(delivery_status='ACKNOWLEDGED',qq_message_id=receipt['message_id']);run['timing']={'first_ack_ms':round((time.monotonic()-started)*1000)};e.journal.save(run)
                e.commit_social(plan);run.update(status='COMPLETED',delivery_status='COMMITTED',memory_commit_status='COMMITTED',learning_status='AWAITING_EXTERNAL_FEEDBACK',ended_at=now());e.journal.save(run)
                return {**result,'sent':True,'status':'sent','reply':reply}
        except Exception as ex:
            with st.lock,st.db:
                if attempt:
                    attempts=st.meta('social_attempts') or []
                    for a in attempts:
                        if a['id']==attempt['id']:a['status']='sent_postprocess_pending' if run and run.get('delivery_status')=='ACKNOWLEDGED' else 'failed' if getattr(ex,'code',None) in ('VALIDATION_FAILED','DELIVERY_FAILED') else 'uncertain'
                    st.setmeta('social_attempts',attempts)
                if run:
                    run.update(status='POSTPROCESS_FAILED' if run.get('delivery_status')=='ACKNOWLEDGED' else getattr(ex,'code','FAILED'),ended_at=now(),error={'exception_type':type(ex).__name__,'details':getattr(ex,'details',{})})
                    if getattr(ex,'code',None) in ('DELIVERY_UNKNOWN','DELIVERY_FAILED'):run['delivery_status']=ex.code
                    e.journal.save(run)
                st.event('social_failed',{'scope':scope,'error':str(ex) if isinstance(ex,(ValueError,ProviderError)) else '主动社交处理失败','attempt_id':attempt['id'] if attempt else None})
            raise
        finally:self.lock.release()
    def unblock(self,scope):
        st=self.engine.store
        with self.engine.lock,st.lock,st.db:
            rows=st.meta('social_contacts') or {}
            if scope not in rows:raise ValueError('联系对象不存在')
            if scope.startswith('private:') and (self.engine.journal.permission(scope,'qq:'+scope.rsplit(':',1)[-1]) or self.engine.journal.permission(scope+':proactive','qq:'+scope.rsplit(':',1)[-1])):raise ValueError('对方已明确撤回联系许可；需其本人发来“可以继续联系我”恢复，主人解除暂停不能覆盖撤回')
            rows[scope]['blocked']=False;rows[scope]['unblocked_by']='owner';st.setmeta('social_contacts',rows);st.event('social_unblocked',{'scope':scope})
        return {'ok':True}
