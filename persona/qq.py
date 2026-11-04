from __future__ import annotations
import threading, json, hmac, hashlib, re, time
from .provider import request_json, ProviderError
from .common import now
from .media import segments, MediaGateway


def verify_bot(q):
    if not q.get('self_id'):return
    result=request_json(q['api_url'].rstrip('/')+'/get_login_info',{},q['api_token'],15)
    if result.get('retcode')!=0 or str((result.get('data') or {}).get('user_id'))!=q['self_id']:raise ProviderError('QQ 发送账号与当前人格绑定账号不一致，已阻止发送')

def verify_event(raw,headers,query,config):
    q=config['qq'];secret=q.get('hmac_secret','');token=q.get('inbound_token','')
    sig=headers.get('X-Signature','')
    if secret:
        expected='sha1='+hmac.new(secret.encode(),raw,hashlib.sha1).hexdigest()
        return hmac.compare_digest(sig,expected)
    provided=headers.get('Authorization','').removeprefix('Bearer ').strip() or query.get('token',[''])[0]
    return bool(token and hmac.compare_digest(provided,token))

def parse_event(e,c):
    q=c['qq']
    if not q['enabled'] or e.get('post_type')!='message':return None
    user=str(e.get('user_id',''));bot=str(e.get('self_id',''));group=str(e.get('group_id',''))
    if q.get('self_id') and bot!=q['self_id']:return None
    if not user.isdigit() or not bot.isdigit() or user==bot or e.get('message_id') is None:return None
    mtype=e.get('message_type')
    if mtype=='private':
        if user not in [str(i) for i in q['allowed_users']]:return None
        scope='private:qq:'+user;dest={'user_id':int(user)}
    elif mtype=='group':
        if group not in [str(i) for i in q['allowed_groups']]:return None
        scope='group:qq:'+group;dest={'group_id':int(group)}
    else:return None
    msg=segments(e.get('message',[]));mentioned=False;text='';media=[]
    for seg in msg:
        if seg.get('type')=='at' and str(seg['data'].get('qq'))==bot:mentioned=True
        if seg.get('type')=='text':text+=str(seg['data'].get('text',''))
        if seg.get('type') in ('image','reply'):media.append(seg)
        if seg.get('type')=='face':text+='[QQ表情 '+str(seg['data'].get('id',''))[:10]+']'
    if mtype=='group' and q['group_mention_only'] and not mentioned and not c['group_attention']['enabled']:return None
    if not text.strip() and not media:return None
    if len(text)>16000:return None
    has_text=bool(text.strip())
    if not has_text:text='[收到图片或引用图片]'
    key=':'.join((bot,mtype,group or user,str(e['message_id'])))
    name=str(e.get('sender',{}).get('card') or e.get('sender',{}).get('nickname') or user)[:60]
    return {'key':key,'scope':scope,'person':'qq:'+user,'text':f'{name}（QQ {user}）：{text.strip()}' if mtype=='group' else text.strip(),
            'bot':bot,'addressed':mtype=='private' or mentioned,'thread':next((str(v['data'].get('id','')) for v in media if v['type']=='reply'),''),'destination':dest,'name':name,'message_type':mtype,'media':media,'has_text':has_text}

class QQBridge:
    def __init__(self,engine):
        self.engine=engine;self.store=engine.store;self.config=engine.config;self.stop=threading.Event()
        from .turn_taking import TurnTaking
        self.turn_taking=TurnTaking(self)
        self.lifecycle=threading.Lock();self.busy=False;self.thread=threading.Thread(target=self.loop,daemon=True,name='qq-inbox')
    def start(self):self.thread.start()
    def receive(self,event):
        parsed=parse_event(event,self.config.get())
        q=self.config.get()['qq']
        reason='已入队'
        if not parsed:
            if not q['enabled']:reason='自动回复已关闭'
            elif event.get('post_type')!='message':reason='收到心跳或非消息事件，无需回复'
            elif str(event.get('user_id'))==str(event.get('self_id')):reason='机器人自己的消息，不回复'
            elif event.get('message_type')=='private' and str(event.get('user_id')) not in list(map(str,q['allowed_users'])):reason='私聊用户不在白名单'
            elif event.get('message_type')=='group' and str(event.get('group_id')) not in list(map(str,q['allowed_groups'])):reason='群不在白名单'
            elif event.get('message_type')=='group' and q['group_mention_only']:reason='未匹配有效 @ 机器人的文本（或文本为空 / 过长）'
            else:reason='无有效文本、身份字段不全或消息过长'
        result={'accepted':bool(parsed),'reason':reason}
        if parsed:
            with self.store.lock,self.store.db:
                added=self.store.add_inbox(parsed['key'],event);result['duplicate']=not added
                if not added:result['reason']='重复事件，已去重'
                else:
                    self.turn_taking.accept(parsed)
                    if parsed['addressed']:self.engine.social.receive(parsed)
        with self.store.lock,self.store.db:self.store.setmeta('qq_last_receipt',{'at':now(),**result})
        return result
    def process(self,row):
        # Use one stable persona state from appraisal through the commit gate.
        with self.engine.lock:return self._process(row)
    def _process(self,row):
        from .turn_taking import StaleTurn
        live=self.store.rows('SELECT status FROM inbox WHERE id=?',(row['id'],))
        if not live or live[0]['status']!='pending':return
        started=time.monotonic();stage='准备';turn_id=None;b=self.turn_taking.snapshot(row)
        if not b:
            self.store.inbox_update(row['id'],'skipped',{'message':'当前设置不允许此消息'});return
        records=[];parsed=[];raw=[];vision=None;sent={};result=None
        def update(status,data):
            for i in b['ids']:self.store.inbox_update(i,status,data)
        def progress(phase):
            nonlocal stage
            stage=phase;update('processing',{'phase':phase,'elapsed_ms':round((time.monotonic()-started)*1000),'merged_count':len(b['ids'])})
        try:
            for i in b['ids']:
                rows=self.store.rows('SELECT * FROM inbox WHERE id=?',(i,))
                if not rows:raise StaleTurn('原消息已删除')
                e=json.loads(rows[0]['payload']);p=parse_event(e,self.config.get())
                if not p:raise StaleTurn('连接或白名单改变')
                raw.append(e);parsed.append(p);records.append({'id':'qq:'+i,'text':p['text']})
            p=parsed[0]
            if not self.engine.social.contact_allowed(p['scope'],p['person']):self.turn_taking.finish(b,'permission_withdrawn',{'message':'对方已撤回联系许可'});return
            p={**p,'thread':b['thread'],'addressed':any(v['addressed'] for v in parsed)}
            text='\n'.join(r['text'] for r in records)
            if len(text)>16000 or len(records)>100:
                self.turn_taking.finish(b,'held',{'message':'连续消息超过本轮处理上限；原文完整保留，请分批重发','merged_count':len(records)});return
            run=self.engine.journal.start(self.store.meta('identity')['id'],'qq-thread:'+b['key'],b['ids'],p['scope']);turn_id=run['turn_id'];b['execution_turn_id']=turn_id
            decision=self.turn_taking.decide(p,b,records)
            run=self.engine.journal.get(turn_id)
            run.update(cognitive_id=decision.get('cognitive_id'),action_state=decision['action'],status=decision['action'] if decision['action'] in ('WAIT','NO_ACTION','VALIDATION_FAILED','PERMISSION_WITHDRAWN') else 'RUNNING');self.engine.journal.save(run)
            if not self.turn_taking.valid(b):raise StaleTurn('判断时收到后续消息')
            with self.store.lock,self.store.db:self.store.event('turn_taking',{'scope':p['scope'],'person':p['person'],'thread':b['thread'],'version':b['version'],'source_ids':b['ids'],**decision})
            if decision['action']=='PERMISSION_WITHDRAWN':self.turn_taking.finish(b,'permission_withdrawn',{'message':decision['reason']});return
            if decision['action']=='VALIDATION_FAILED':self.turn_taking.pause(b,decision);return
            if decision['action']=='WAIT':
                if decision.get('await_input'):self.turn_taking.pause(b,decision)
                else:self.turn_taking.defer(b,decision['wait_seconds'])
                return
            if p['message_type']=='group':self.engine.group_attention.observe(p,b,records,decision)
            if decision['action']=='NO_ACTION':
                if decision.get('await_input'):self.turn_taking.pause(b,decision);return
                if p['message_type']=='private' and decision['attention']!='SKIM':
                    with self.store.lock,self.store.db:self.engine.memory_lifecycle.enqueue(records,p['scope'],p['person'],b['thread'],appraisal=decision.get('estimates'),cognitive_id=decision.get('cognitive_id'))
                self.turn_taking.finish(b,'silent',{'reason':decision['reason'],'attention':decision['attention'],'merged_count':len(records)});return
            progress('聚合消息完成')
            session_map=self.store.meta('qq_thread_sessions') or {};sid=session_map.get(b['key'])
            if not sid or not self.store.rows('SELECT id FROM sessions WHERE id=?',(sid,)):
                sid=self.store.session(p['person'],p['scope'],'QQ · '+p['name']);session_map[b['key']]=sid
                with self.store.lock,self.store.db:self.store.setmeta('qq_thread_sessions',session_map)
            descriptions=[]
            for part,event in zip(parsed,raw):
                if part.get('media'):
                    progress('读取 QQ 图片');v=MediaGateway(self.engine).inspect(part,event)
                    if v:descriptions.append(v)
            if descriptions:
                good=[v for v in descriptions if v['status']!='IMAGE_UNAVAILABLE']
                vision={**descriptions[0],'status':'OK' if len(good)==len(descriptions) else 'PARTIAL' if good else 'IMAGE_UNAVAILABLE','description':'\n'.join(v.get('description','') for v in descriptions),'parts':descriptions,'requires_unavailable_reply':not any(x['has_text'] for x in parsed)}
            # The store lock is released during transport so inbound events can
            # invalidate only the unsent suffix; confirmed prefixes are durable.
            # Once OneBot accepts a send, it cannot be recalled by this program.
            def deliver(out):
                if out['action']=='silence':return
                cfg=self.config.get()
                if not self.engine.social.contact_allowed(p['scope'],p['person']):
                    from .turn_taking import ContactWithdrawn
                    raise ContactWithdrawn('对方已撤回联系许可')
                if not all(parse_event(e,cfg) for e in raw):raise StaleTurn('发送前连接或白名单改变')
                q=cfg['qq']
                progress('5 / 6 · 发送 QQ 并等待真实回执');send_started=time.monotonic()
                action='send_group_msg' if p['message_type']=='group' else 'send_private_msg'
                parts=out.get('reply_parts') or [out['reply']]
                if not 1<=len(parts)<=4 or any(not isinstance(v,str) or not v.strip() for v in parts):raise ValueError('QQ 分段协议无效')
                batch=[[{'type':'text','data':{'text':part}}] for part in parts]
                journal=self.engine.journal;run=out['execution']
                envelope={'bot':p['bot'],'target':p['destination'],'action':action}
                if len(batch)>1:envelope['messages']=batch
                else:envelope['message']=batch[0]
                outbox_id=journal.prepare(run,envelope,out['commit_plan'])
                def send(envelope):return request_json(q['api_url'].rstrip('/')+'/'+envelope['action'],{**envelope['target'],'message':envelope['message']},q['api_token'],timeout=20)
                def before_bubble(index):
                    if not self.turn_taking.valid(b):raise StaleTurn('收到新输入，停止未发送部分')
                    current=self.config.get()
                    if not all(parse_event(e,current) for e in raw) or current['qq']['api_url']!=q['api_url'] or current['qq']['self_id']!=q['self_id']:raise StaleTurn('发送权限或连接已改变')
                    if not self.engine.social.contact_allowed(p['scope'],p['person']):
                        from .turn_taking import ContactWithdrawn
                        raise ContactWithdrawn('对方撤回联系许可')
                def acknowledged(index,receipt):
                    self.engine.commit_prefix(out['commit_plan'],index,receipt)
                    run.setdefault('qq_message_ids',[]).append(receipt['message_id'])
                    run.setdefault('timing',{}).setdefault('first_ack_ms',max(0,round((receipt['received_at']-b['first'])*1000)))
                    run.update(memory_commit_status='PREFIX_COMMITTED',qq_message_id=run['qq_message_ids'][0]);journal.save(run)
                try:
                    before_bubble(0)
                    receipt=journal.dispatch_sequence(outbox_id,send,before_bubble,acknowledged) if len(batch)>1 else journal.dispatch(outbox_id,send)
                except Exception as ex:
                    run.update(delivery_status=getattr(ex,'code','DELIVERY_UNKNOWN'));journal.save(run);raise
                interrupted=receipt.get('status')=='DELIVERY_INTERRUPTED'
                run.update(delivery_status='DELIVERY_INTERRUPTED' if interrupted else 'ACKNOWLEDGED',qq_message_id=receipt['message_id'],qq_message_ids=receipt.get('message_ids',[receipt['message_id']]))
                run.setdefault('timing',{}).setdefault('first_ack_ms',max(0,round((receipt['received_at']-b['first'])*1000)));journal.save(run)
                sent.update(status='sent_interrupted' if interrupted else 'sent',message_id=receipt['message_id'],message_ids=receipt.get('message_ids',[receipt['message_id']]),outbox_id=outbox_id,qq_send_ms=round((time.monotonic()-send_started)*1000))
            result=self.engine.turn(sid,text,progress=progress,person_override=p['person'],media_context=vision,valid=lambda:self.turn_taking.valid(b),delivery=deliver,precommit=lambda:verify_bot(self.config.get()['qq']),turn_context={'execution_turn_id':turn_id,'thread':b['thread'],'sources':b['ids'],'version':b['version'],'direct_interaction':p['addressed'],'observations':self.engine.group_attention.context(p),'cognitive_decision':decision,'raw_records':records})
            turn_id=result['turn_id']
            self.turn_taking.finish(b,sent.get('status','silent'),{**sent,'turn_id':turn_id,'vision':vision,'merged_count':len(records),'timing':{**result['trace'].get('timing',{}),'turn_control_ms':decision.get('duration_ms',0),'qq_send_ms':sent.get('qq_send_ms',0),'qq_total_ms':round((time.monotonic()-started)*1000)}})
        except StaleTurn as ex:
            # These old IDs remain in the newer window, so all original fragments survive.
            update('pending',{'phase':'后续消息已到达，重新聚合','superseded_version':b['version']})
            if self.turn_taking.valid(b):self.turn_taking.finish(b,'not_sent',{'message':str(ex)})
        except Exception as ex:
            message=str(ex) if isinstance(ex,(ProviderError,ValueError)) else '处理失败，请检查程序日志与连接设置'
            from .support import exception_frames
            diagnostic=exception_frames(ex)
            with self.store.lock,self.store.db:self.store.event('qq_failed',{'exception_type':diagnostic['type'],'frames':diagnostic['frames'],'phase':stage})
            code=getattr(ex,'code','FAILED');status='sent_postprocess_pending' if sent.get('status') in ('sent','sent_interrupted') else {'PERMISSION_WITHDRAWN':'permission_withdrawn','DELIVERY_UNKNOWN':'delivery_unknown','DELIVERY_FAILED':'delivery_failed','DELIVERY_PARTIAL':'delivery_partial','VALIDATION_FAILED':'validation_failed'}.get(code,'failed')
            self.turn_taking.finish(b,status,{'message':message,'phase':stage,'turn_id':turn_id,'duration_ms':round((time.monotonic()-started)*1000),'diagnostics':getattr(ex,'details',{}),'delivery_may_have_occurred':bool(sent) or code=='DELIVERY_UNKNOWN'})
    def loop(self):
        while not self.stop.is_set():
            rows=[]
            with self.lifecycle:
                if self.stop.is_set():break
                pending=self.store.rows("SELECT * FROM inbox WHERE status='pending' ORDER BY created_at LIMIT 200")
                rows=next(([r] for r in pending if self.turn_taking.ready(r)),[])
                if rows:
                    self.busy=True
                    try:self.process(rows[0])
                    finally:self.busy=False
            if not rows:
                self.engine.recover_delivered()
                self.engine.consolidation.poll()
                self.engine.learning.poll()
                self.engine.memory_lifecycle.poll()
                self.engine.social.poll()
                self.stop.wait(.5)
    def status(self):
        c=self.config.get();q=c['qq']
        rows=self.store.rows('SELECT id,status,result,created_at FROM inbox ORDER BY created_at DESC LIMIT 30')
        for row in rows:row['result']=json.loads(row['result'])
        return {'enabled':q['enabled'],'event_auth_configured':bool(q['inbound_token'] or q['hmac_secret']),
                'allowed_users_count':len(q['allowed_users']),'allowed_groups_count':len(q['allowed_groups']),
                'general_configured':bool(c['model']),'pmm_configured':c['pmm']['mode']!='api' or bool(c['pmm']['api']['model']),
                'last_receipt':self.store.meta('qq_last_receipt'),'busy':self.busy,'recent':rows}

    def retry_failed(self,identifier):
        with self.engine.lock,self.store.lock,self.store.db:
            found=self.store.rows('SELECT * FROM inbox WHERE id=?',(identifier,))
            if not found or found[0]['status'] not in ('failed','validation_failed','delivery_failed','not_sent'):raise ValueError('仅能手动重试确定没有发送的失败；未知回执须先核对')
            row=found[0];result=json.loads(row['result']);turn_id=(result.get('diagnostics') or {}).get('turn_id') or result.get('turn_id');run=self.engine.journal.get(turn_id) if turn_id else None
            ids=(run or {}).get('input_event_ids') or [identifier]
            for source in ids:
                if self.engine.journal.source_status(source) not in (None,'CANCELLED','DELIVERY_FAILED'):raise ValueError('此原始事件已有发送记录或未知结果，禁止重发')
            parsed=[]
            for source in ids:
                rr=self.store.rows('SELECT * FROM inbox WHERE id=?',(source,))
                if not rr or rr[0]['status'] not in ('failed','validation_failed','delivery_failed','not_sent'):raise ValueError('合并窗口中的消息状态已变化')
                p=parse_event(json.loads(rr[0]['payload']),self.config.get())
                if not p:raise ValueError('当前连接或白名单不允许重试')
                parsed.append(p)
            if any(b.get('ids') and b['scope']==parsed[0]['scope'] and b['person']==parsed[0]['person'] for b in (self.store.meta('turn_buffers') or {}).values()):raise ValueError('有新的消息正在处理，请先完成当前窗口')
            for p in parsed:
                self.store.db.execute("UPDATE inbox SET status='pending' WHERE id=?",(p['key'],));self.turn_taking.accept(p)
            return {'ok':True,'queued':len(ids)}

    def test(self):
        q=self.config.get()['qq'];r=request_json(q['api_url'].rstrip('/')+'/get_login_info',{},q['api_token'],20)
        if r.get('retcode')!=0:raise ProviderError('QQ 接口未通过登录检查')
        d=r.get('data') or {}
        if q.get('self_id') and str(d.get('user_id'))!=q['self_id']:raise ProviderError('登录账号与绑定的机器人 QQ 号不同')
        return {'ok':True,'nickname':d.get('nickname',''),'user_id':d.get('user_id','')}
