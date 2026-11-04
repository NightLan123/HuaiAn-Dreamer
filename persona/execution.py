"""Durable execution/outbox journal, independent of persona transaction rollback.

OneBot cannot provide a database transaction. Mark DISPATCHING before the remote
call, persist its receipt before persona commit, and never resend an unknown send.
Draft/recovery plans are private application data, not exported debug transcripts.
"""
from __future__ import annotations
import copy, hashlib, json, math, os, sqlite3, threading, time
from .common import now,dumps,uid
from .provider import ProviderError

class DeliveryFailure(ProviderError):
    def __init__(self,status,identifier):
        self.code=status
        super().__init__('发送结果未确认，请核对 QQ 回执；不会自动重发' if status=='DELIVERY_UNKNOWN' else 'QQ 接口明确报告发送失败',{'code':status,'outbox_id':identifier})

class ExecutionJournal:
    def __init__(self,directory):
        self.path=directory/'execution.sqlite3';self.lock=threading.RLock()
        self.db=sqlite3.connect(self.path,check_same_thread=False);self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        try:os.chmod(self.path,0o600)
        except OSError:pass
        with self.db:
            self.db.executescript('''CREATE TABLE IF NOT EXISTS permissions(id TEXT PRIMARY KEY,payload TEXT);
            CREATE TABLE IF NOT EXISTS send_sources(event_id TEXT PRIMARY KEY, outbox_id TEXT);
            CREATE TABLE IF NOT EXISTS inbound(id TEXT PRIMARY KEY, scope TEXT, payload TEXT, received_at REAL);
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, payload TEXT, updated_at REAL);
            CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, dedupe TEXT UNIQUE, status TEXT, payload TEXT, plan TEXT, receipt TEXT, created_at REAL, updated_at REAL);''')
            # An interrupted remote call may already have delivered its message.
            for row in self.db.execute("SELECT id,payload,receipt FROM outbox WHERE status='DISPATCHING'").fetchall():
                payload=json.loads(row['payload']);receipt=json.loads(row['receipt'])
                # 2.4 explicitly records whether the next remote call began.
                # Older H2 lacks this bit: retain the conservative UNKNOWN state.
                status='DELIVERY_UNKNOWN'
                if payload.get('messages') and len(receipt.get('sent',[]))==len(payload['messages']):
                    status='ACKNOWLEDGED'
                    receipt.update(message_id=receipt['sent'][0]['message_id'],message_ids=[v['message_id'] for v in receipt['sent']],received_at=receipt['sent'][-1]['received_at'],in_flight=False)
                    self.db.execute('UPDATE outbox SET receipt=? WHERE id=?',(dumps(receipt),row['id']))
                elif receipt.get('in_flight') is False and receipt.get('sent'):
                    status='ACKNOWLEDGED' if len(receipt['sent'])==len(payload.get('messages',[])) else 'DELIVERY_INTERRUPTED'
                self.db.execute('UPDATE outbox SET status=?,updated_at=? WHERE id=?',(status,now(),row['id']))
            self.db.execute("UPDATE outbox SET status='CANCELLED',updated_at=? WHERE status='PREPARED'",(now(),))
    def start(self,persona_id,session_id,input_event_ids,scope):
        identifier=uid();r={'turn_id':identifier,'trace_id':uid(),'persona_id':persona_id,'session_id':session_id,'input_event_ids':list(input_event_ids),'scope':scope,'started_at':now(),'status':'RUNNING','stages':[],'validation':[],'candidate_status':'NOT_GENERATED','delivery_status':'NOT_ATTEMPTED','memory_commit_status':'NOT_COMMITTED','schema_version':'execution/1'}
        self.save(r);return r
    def save(self,run):
        with self.lock,self.db:self.db.execute('INSERT OR REPLACE INTO runs VALUES (?,?,?)',(run['turn_id'],dumps(run),now()))
    def get(self,identifier):
        with self.lock:r=self.db.execute('SELECT payload FROM runs WHERE id=?',(identifier,)).fetchone()
        return json.loads(r[0]) if r else None
    def recent(self,limit=60):
        with self.lock:rows=self.db.execute('SELECT payload FROM runs ORDER BY updated_at DESC LIMIT ?',(limit,)).fetchall()
        return [json.loads(r[0]) for r in rows]
    def prepare(self,run,payload,plan):
        dedupe=hashlib.sha256(dumps([run['persona_id'],run['scope'],run['input_event_ids'] or [run['turn_id']]]).encode()).hexdigest()
        with self.lock,self.db:
            for event_id in run['input_event_ids']:
                old_source=self.db.execute('SELECT o.id,o.status FROM outbox o JOIN send_sources s ON s.outbox_id=o.id WHERE s.event_id=?',(event_id,)).fetchone()
                if old_source and old_source['status'] not in ('DELIVERY_FAILED','CANCELLED'):raise DeliveryFailure('DELIVERY_UNKNOWN',old_source['id'])
            old=self.db.execute('SELECT id,status FROM outbox WHERE dedupe=?',(dedupe,)).fetchone()
            if old:
                if old['status'] not in ('DELIVERY_FAILED','CANCELLED'):raise DeliveryFailure('DELIVERY_UNKNOWN',old['id'])
                self.db.execute('UPDATE outbox SET dedupe=? WHERE id=?',(dedupe+':closed:'+old['id'],old['id']))
            identifier=run['turn_id'];t=now();self.db.execute('INSERT INTO outbox VALUES (?,?,?,?,?,?,?,?)',(identifier,dedupe,'PREPARED',dumps(payload),dumps(plan),'{}',t,t))
            self.db.executemany('INSERT OR REPLACE INTO send_sources VALUES (?,?)',[(v,identifier) for v in run['input_event_ids']])
        run.update(outbox_id=identifier,delivery_status='PREPARED');self.save(run);return identifier
    def transition(self,identifier,status,receipt=None):
        with self.lock,self.db:
            self.db.execute('UPDATE outbox SET status=?,receipt=COALESCE(?,receipt),updated_at=? WHERE id=?',(status,dumps(receipt) if receipt is not None else None,now(),identifier))
    def dispatch(self,identifier,send):
        with self.lock:
            row=self.db.execute('SELECT * FROM outbox WHERE id=?',(identifier,)).fetchone()
            if not row or row['status']!='PREPARED':raise DeliveryFailure('DELIVERY_UNKNOWN',identifier)
            self.transition(identifier,'DISPATCHING')
        try:response=send(json.loads(row['payload']))
        except Exception as ex:
            self.transition(identifier,'DELIVERY_UNKNOWN',{'exception_type':type(ex).__name__,'received_at':now()})
            raise DeliveryFailure('DELIVERY_UNKNOWN',identifier) from ex
        response=response if isinstance(response,dict) else {}
        data=response.get('data') if isinstance(response.get('data'),dict) else {}
        receipt={'retcode':response.get('retcode'),'status':response.get('status'),'message_id':data.get('message_id'),'received_at':now()}
        if type(receipt['retcode']) is int and receipt['retcode'] not in (0,1) and receipt['status']=='failed':
            self.transition(identifier,'DELIVERY_FAILED',receipt);raise DeliveryFailure('DELIVERY_FAILED',identifier)
        if type(receipt['retcode']) is not int or receipt['retcode']!=0 or receipt['status']!='ok' or type(receipt['message_id']) not in (str,int) or not str(receipt['message_id']):
            self.transition(identifier,'DELIVERY_UNKNOWN',receipt);raise DeliveryFailure('DELIVERY_UNKNOWN',identifier)
        self.transition(identifier,'ACKNOWLEDGED',receipt)
        return receipt
    def dispatch_sequence(self,identifier,send,pre_send=None,on_ack=None,spacing=.12):
        """Receipt-before-history-before-next-send. Never replay an unknown step."""
        with self.lock:
            row=self.db.execute('SELECT * FROM outbox WHERE id=?',(identifier,)).fetchone()
            if not row or row['status']!='PREPARED':raise DeliveryFailure('DELIVERY_UNKNOWN',identifier)
            payload=json.loads(row['payload']);messages=payload.get('messages')
            if not isinstance(messages,list) or not 1<=len(messages)<=4 or any(not isinstance(x,list) or not x for x in messages):raise ValueError('多气泡发送协议无效')
        sent=[];steps=[{'index':i,'status':'READY'} for i in range(len(messages))]
        def record(status,**extra):
            receipt={'status':'ok' if status=='ACKNOWLEDGED' else status,'retcode':0 if status=='ACKNOWLEDGED' else None,
                     'sent':copy.deepcopy(sent),'steps':copy.deepcopy(steps),'total':len(messages),
                     'message_ids':[s['message_id'] for s in sent],'message_id':sent[0]['message_id'] if sent else None,
                     'received_at':sent[-1]['received_at'] if sent else None,**extra}
            self.transition(identifier,status,receipt);return receipt
        for index,segments in enumerate(messages):
            if index and spacing:time.sleep(min(.35,max(0.,spacing)))
            try:
                if pre_send:pre_send(index)
            except Exception as ex:
                for s in steps[index:]:s['status']='CANCELLED'
                receipt=record('DELIVERY_INTERRUPTED' if sent else 'CANCELLED',in_flight=False,stop_reason=getattr(ex,'code','new_input_or_permission_change'))
                if sent:return receipt
                raise
            steps[index]['status']='DISPATCHING'
            record('DISPATCHING',in_flight=True,unknown_index=index)
            try:response=send({**{k:v for k,v in payload.items() if k!='messages'},'message':segments})
            except Exception as ex:
                steps[index]['status']='UNKNOWN'
                for s in steps[index+1:]:s['status']='CANCELLED'
                record('DELIVERY_UNKNOWN',in_flight=True,unknown_index=index,exception_type=type(ex).__name__)
                raise DeliveryFailure('DELIVERY_UNKNOWN',identifier) from ex
            response=response if isinstance(response,dict) else {};data=response.get('data') if isinstance(response.get('data'),dict) else {}
            receipt={'index':index,'retcode':response.get('retcode'),'status':response.get('status'),'message_id':data.get('message_id'),'received_at':now()}
            ok=type(receipt['retcode']) is int and receipt['retcode']==0 and receipt['status']=='ok' and type(receipt['message_id']) in (str,int) and bool(str(receipt['message_id']))
            if not ok:
                failed=type(receipt['retcode']) is int and receipt['retcode'] not in (0,1) and receipt['status']=='failed'
                steps[index]['status']='FAILED' if failed else 'UNKNOWN'
                for s in steps[index+1:]:s['status']='CANCELLED'
                status=('DELIVERY_PARTIAL' if sent else 'DELIVERY_FAILED') if failed else 'DELIVERY_UNKNOWN'
                record(status,in_flight=not failed,unknown_index=None if failed else index,failed_receipt=receipt)
                raise DeliveryFailure(status,identifier)
            sent.append(receipt);steps[index].update(status='SENT_ACK',message_id=receipt['message_id'])
            record('DISPATCHING',in_flight=False)
            try:
                if on_ack:on_ack(index,receipt)
            except Exception:
                for s in steps[index+1:]:s['status']='CANCELLED'
                record('ACKNOWLEDGED' if len(sent)==len(messages) else 'DELIVERY_INTERRUPTED',in_flight=False,stop_reason='prefix_commit_pending')
                raise
        return record('ACKNOWLEDGED',in_flight=False)

    def delivery(self,identifier):
        """Private recovery view. Only acknowledged text may reach history/learning."""
        with self.lock:row=self.db.execute('SELECT * FROM outbox WHERE id=?',(identifier,)).fetchone()
        if not row:return None
        out=dict(row);out.update({k:json.loads(out[k]) for k in ('payload','plan','receipt')})
        return out

    def partial_committed(self,identifier):
        with self.lock,self.db:
            self.db.execute("UPDATE outbox SET status='PARTIAL_COMMITTED',plan='{}',payload='{}',updated_at=? WHERE id=? AND status IN ('DELIVERY_INTERRUPTED','DELIVERY_PARTIAL')",(now(),identifier))
    def committed(self,identifier):
        with self.lock,self.db:
            self.db.execute("UPDATE outbox SET status='COMMITTED',plan='{}',payload='{}',updated_at=? WHERE id=? AND status='ACKNOWLEDGED'",(now(),identifier))
    def recoverable(self):
        with self.lock:rows=self.db.execute("SELECT * FROM outbox WHERE status IN ('ACKNOWLEDGED','DELIVERY_INTERRUPTED','DELIVERY_PARTIAL','DELIVERY_UNKNOWN') ORDER BY created_at").fetchall()
        result=[{**dict(r),'plan':json.loads(r['plan']),'receipt':json.loads(r['receipt'])} for r in rows]
        return [r for r in result if r['status']=='ACKNOWLEDGED' or r['receipt'].get('sent') and r['plan']]
    def outbox(self,identifier=None):
        with self.lock:
            rows=self.db.execute('SELECT id,status,receipt,created_at,updated_at FROM outbox'+(' WHERE id=?' if identifier else ' ORDER BY created_at DESC LIMIT 100'),(identifier,) if identifier else ()).fetchall()
        return [{**dict(r),'receipt':json.loads(r['receipt'])} for r in rows]
    def acknowledge(self,identifier,lookup):
        """Reconciliation is read-only remotely; require exact sender/scope/content."""
        with self.lock:row=self.db.execute('SELECT * FROM outbox WHERE id=?',(identifier,)).fetchone()
        if not row or row['status']!='DELIVERY_UNKNOWN':raise ValueError('只能核对发送结果未知的记录')
        payload=json.loads(row['payload']);result=lookup()
        if not isinstance(result,dict) or not isinstance(result.get('data'),dict):raise ValueError('回执内容无效，仍保留未知状态')
        data=result['data']
        old_receipt=json.loads(row['receipt']);index=old_receipt.get('unknown_index',len(old_receipt.get('sent',[])))
        batch=payload.get('messages');target=payload.get('target',{});sent=batch[index] if isinstance(batch,list) and type(index) is int and 0<=index<len(batch) else payload.get('message',[])
        from .media import segments
        actual=segments(data.get('message',[]))
        if result.get('retcode')!=0 or str((data.get('sender') or {}).get('user_id'))!=str(payload.get('bot')) or any(str(data.get(k))!=str(v) for k,v in target.items()) or actual!=sent or not data.get('message_id'):raise ValueError('回执缺少可验证的发送者、目标或完整消息，仍保留未知状态，不重发')
        receipt={'status':'ok','retcode':0,'message_id':data['message_id'],'received_at':now(),'reconciled':True}
        if isinstance(batch,list):
            if not sent or any(str(v['message_id'])==str(data['message_id']) for v in old_receipt.get('sent',[])):raise ValueError('回执不是未知的下一条消息')
            receipts=old_receipt.get('sent',[])+[{**receipt,'index':index}]
            steps=[{'index':i,'status':'SENT_ACK' if i<len(receipts) else 'CANCELLED',**({'message_id':receipts[i]['message_id']} if i<len(receipts) else {})} for i in range(len(batch))]
            receipt={**receipt,'message_id':receipts[0]['message_id'],'message_ids':[r['message_id'] for r in receipts],'sent':receipts,'steps':steps,'total':len(batch),'in_flight':False,'stop_reason':'reconciled_without_resend'}
            # The unsent suffix is never resumed even if a previously unknown ACK is found.
            self.transition(identifier,'DELIVERY_INTERRUPTED',receipt)
        else:self.transition(identifier,'ACKNOWLEDGED',receipt)
        return receipt
    def permission(self,scope,person,withdraw=False):
        key=hashlib.sha256((scope+'|'+person).encode()).hexdigest()
        with self.lock,self.db:
            if withdraw:self.db.execute('INSERT OR REPLACE INTO permissions VALUES (?,?)',(key,dumps({'withdrawn':True,'at':now()})))
            return bool(self.db.execute('SELECT id FROM permissions WHERE id=?',(key,)).fetchone())
    def restore_permission(self,scope,person):
        key=hashlib.sha256((scope+'|'+person).encode()).hexdigest()
        with self.lock,self.db:self.db.execute('DELETE FROM permissions WHERE id=?',(key,))
    def source_status(self,event_id):
        with self.lock:r=self.db.execute('SELECT o.status FROM outbox o JOIN send_sources s ON s.outbox_id=o.id WHERE s.event_id=?',(event_id,)).fetchone()
        return r[0] if r else None
    def receive(self,run,text):
        with self.lock,self.db:self.db.execute('INSERT OR IGNORE INTO inbound VALUES (?,?,?,?)',(run['turn_id'],run['scope'],dumps({'session_id':run['session_id'],'text':text}),now()))
    def snapshot(self):
        with self.lock:return {table:[dict(r) for r in self.db.execute('SELECT * FROM '+table)] for table in ('runs','outbox','inbound','send_sources','permissions')}
    def merge_snapshot(self,snapshot):
        # External sends cannot be rolled back. Keep all existing dedupe tombstones;
        # imported recovery plans are never executable, even from an older backup.
        validate_snapshot(snapshot)
        with self.lock,self.db:
            self.db.execute("UPDATE outbox SET status='RECOVERY_REVIEW' WHERE status IN ('ACKNOWLEDGED','PREPARED','DISPATCHING')")
            for table,rows in snapshot.items():
                columns=[r[1] for r in self.db.execute('PRAGMA table_info('+table+')')]
                for original in rows:
                    row=copy.deepcopy(original)
                    if table=='outbox':
                        row['plan']='{}'
                        if row['status'] not in ('COMMITTED','DELIVERY_FAILED','CANCELLED'):row['status']='RECOVERY_REVIEW'
                    self.db.execute('INSERT OR IGNORE INTO '+table+' ('+','.join(columns)+') VALUES ('+','.join('?'*len(columns))+')',[row[k] for k in columns])
    def erase(self):
        # Erasure removes private content but keeps opaque delivery tombstones to
        # stop an old external event from being replayed as a new send.
        with self.lock,self.db:
            self.db.execute('PRAGMA secure_delete=ON');self.db.execute('DELETE FROM runs');self.db.execute('DELETE FROM inbound')
            self.db.execute("UPDATE outbox SET payload='{}',plan='{}',receipt='{}',status='ERASED'")
        self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)');self.db.execute('VACUUM');self.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    def close(self):
        with self.lock:self.db.close()

def public_trace(run):
    """Default support view excludes raw messages, prompts, media and QQ addresses."""
    allowed=('turn_id','trace_id','persona_id','session_id','decision_id','decision_revision','selected_action','status','started_at','ended_at','stages','validation','candidate_status','pre_send_status','delivery_status','memory_commit_status','outbox_id','qq_message_id','error','calls','schema_version','timing','candidate_digest','candidate_chars','candidate_check','action_state','regenerations','learning_status','background_error','cognitive_id')
    result={k:copy.deepcopy(run[k]) for k in allowed if k in run}
    result['calls']=[safe_call(v) for v in result.get('calls',[])]
    if 'error' in result:
        error=result['error'];result['error']={'exception_type':error.get('exception_type'),'frames':error.get('frames',[]),'details':safe_details(error.get('details',{}))}
    result['input_event_refs']=[hashlib.sha256(v.encode()).hexdigest()[:16] for v in run.get('input_event_ids',[])]
    if run.get('interaction_plan'):
        p=run['interaction_plan'];result['expression_summary']={k:copy.deepcopy(p.get(k)) for k in ('schema','candidate_strategy','sufficiency_target','allow_follow_up_question','message_plan','yield_after_current_reply','evaluation')}
        result['expression_summary']['generated_bubbles']=p.get('realization',{}).get('generated_bubbles')
    if run.get('qq_message_ids'):result['qq_message_ids']=copy.deepcopy(run['qq_message_ids'])
    return result

def metrics(runs):
    latencies=[];proactive=[]
    for r in runs:
        t=r.get('timing',{}).get('first_ack_ms')
        if type(t) in (int,float) and math.isfinite(t) and t>=0 and r.get('delivery_status') in ('ACKNOWLEDGED','COMMITTED'):
            bucket=proactive if any(v.startswith('social-opportunity:') for v in r.get('input_event_ids',[])) else latencies
            bucket.append(t)
    def percentile(values,p):
        if not values:return None
        ordered=sorted(values);pos=(len(ordered)-1)*p;lo=int(pos);hi=min(lo+1,len(ordered)-1);return ordered[lo]+(ordered[hi]-ordered[lo])*(pos-lo)
    return {'acknowledged_samples':len(latencies),'p50_first_ack_ms':percentile(latencies,.5),'p95_first_ack_ms':percentile(latencies,.95),'proactive':{'acknowledged_samples':len(proactive),'p50_opportunity_to_ack_ms':percentile(proactive,.5),'p95_opportunity_to_ack_ms':percentile(proactive,.95)},'failed_runs':sum(r.get('status') in ('VALIDATION_FAILED','DELIVERY_FAILED','DELIVERY_UNKNOWN','FAILED') for r in runs),'runs':len(runs),'user_receipt_time':None,'stage_clock':'monotonic','first_ack_clock':'wall time from inbound window to acknowledgement; includes debounce and inference; excludes proactive opportunities','clock_meaning':'应用接收到 OneBot 有 message_id 的成功回执；不是用户客户端真实收信时间'}


def safe_call(call):
    fields=('call_id','turn_ids','trace_ids','turn_id','trace_id','decision_id','decision_revision','stage','protocol','model','structured','status','duration_ms','http_status','thinking','thinking_mode','usage','finish_reason','cached','attempt','retry_count','started_at','ended_at','output_chars')
    out={k:copy.deepcopy(v) for k,v in call.items() if k in fields}
    if 'response' in call:out['provider_error_type']=type(call['response']).__name__
    return out

def safe_details(d):
    if not isinstance(d,dict):return {}
    keys=('code','schema_version','validator','issues','expected_view_ids','received_view_ids','action_enum','received_utility_keys','repair_attempts','expected_action','detected_action','evidence_spans','outbox_id')
    return {k:copy.deepcopy(d[k]) for k in keys if k in d}

def validate_snapshot(s):
    if not isinstance(s,dict) or set(s)-{'runs','outbox','inbound','send_sources','permissions'}:raise ValueError('执行备份表无效')
    cols={'permissions':{'id','payload'},'send_sources':{'event_id','outbox_id'},'runs':{'id','payload','updated_at'},'outbox':{'id','dedupe','status','payload','plan','receipt','created_at','updated_at'},'inbound':{'id','scope','payload','received_at'}}
    for table,rows in s.items():
        if not isinstance(rows,list) or len(rows)>100000:raise ValueError('执行备份条数无效')
        seen=set()
        for r in rows:
            key='event_id' if table=='send_sources' else 'id'
            if not isinstance(r,dict) or set(r)!=cols[table] or not isinstance(r[key],str) or r[key] in seen:raise ValueError('执行备份结构无效')
            seen.add(r[key])
            for k in ('payload','plan','receipt'):
                if k in r and (not isinstance(r[k],str) or not isinstance(json.loads(r[k]),dict)):raise ValueError('执行备份内容无效')
            if table=='outbox' and (not isinstance(r['dedupe'],str) or not isinstance(r['status'],str)):raise ValueError('Outbox 标识无效')
    return s
