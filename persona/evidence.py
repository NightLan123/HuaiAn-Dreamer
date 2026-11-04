"""Shared provenance and processing receipts for existing PMM state.

This is an index of source records, tasks and state revisions. It owns no
personality estimates, retrievable memories or alternate decision process.
All writes participate in the caller's existing SQLite transaction.
"""
from __future__ import annotations
import copy
from .common import now
from .registry import digest

SCHEMA='learning-evidence/1'

def empty():
    return {'schema':SCHEMA,'version':0,'sources':{},'receipts':{},'revisions':[]}

def identity(record,scope=None,person=None):
    scope=scope if scope is not None else record.get('authorization_scope',record.get('scope','')) or 'self:imported'
    person=person if person is not None else record.get('person') or record.get('speaker','')
    raw=record.get('event_id') or record.get('source_event_id') or record.get('batch_id') or record['id'].removesuffix(':u').removesuffix(':a')
    return digest([scope,person,str(raw)])

def validate(value):
    if value is None:return
    if not isinstance(value,dict) or value.get('schema')!=SCHEMA or type(value.get('version')) is not int or value['version']<0:raise ValueError('统一证据索引版本无效')
    for name in ('sources','receipts'):
        if not isinstance(value.get(name),dict) or len(value[name])>200000:raise ValueError('证据索引格式或容量无效')
    if not isinstance(value.get('revisions'),list) or len(value['revisions'])>200000:raise ValueError('状态修订索引无效')
    for key,r in value['sources'].items():
        if not isinstance(r,dict) or not all(isinstance(r.get(k),str) for k in ('record_id','text','scope','person','event_id','content_digest')):raise ValueError('证据源字段无效')
        if key!=digest([r['scope'],r['person'],r['record_id']]) or digest(r['text'])!=r['content_digest']:raise ValueError('证据源摘要或身份不匹配')
    for key,r in value['receipts'].items():
        if not isinstance(r,dict) or not all(isinstance(r.get(k),str) for k in ('domain','event_id','task_id')) or not isinstance(r.get('source_keys'),list):raise ValueError('学习回执无效')
        if key!=digest([r['domain'],r['event_id']]) or any(k not in value['sources'] for k in r['source_keys']):raise ValueError('学习回执缺少原始来源')
        if any(value['sources'][k]['event_id']!=r['event_id'] for k in r['source_keys']):raise ValueError('学习回执混入其他事件')
    for r in value['revisions']:
        if not isinstance(r,dict) or not isinstance(r.get('source_keys'),list) or any(k not in value['sources'] for k in r['source_keys']):raise ValueError('状态修订来源无效')

class Evidence:
    def __init__(self,engine):
        self.e=engine;self.st=engine.store
        validate(self.st.meta('learning_evidence'))
        if self.st.meta('learning_evidence') is None:
            with self.st.lock,self.st.db:
                self.st.setmeta('learning_evidence',empty())
                # Preserve old state; index only existing raw evidence and known
                # successful tasks. Unknown historic processing stays unknown.
                for target,p in [('self',engine.profile()),*[("other",p) for p in (self.st.meta('pmm_interlocutors') or {}).values()]]:
                    records=[r for r in p.get('source_records',[]) if r.get('source')!='generated']
                    if records:self.complete(target,records,'migration:existing-profile',{}, {},'legacy_applied_unknown_time')
                for job in (self.st.meta('learning_center') or {}).get('jobs',[]):
                    for b in job.get('batches',[]):
                        if b.get('status')=='applied' and job.get('status')!='rolled_back':self.complete(job['target'],b['records'],job['id'],{}, {},'migration:learning-center')
                self.st.event('evidence_index_migrated',{'schema':SCHEMA,'existing_states_unchanged':True})

    def state(self):return self.st.meta('learning_evidence') or empty()

    def normalize(self,r,scope=None,person=None):
        x=copy.deepcopy(r)
        x['scope']=scope if scope is not None else x.get('authorization_scope',x.get('scope','')) or 'self:imported'
        x['person']=person if person is not None else x.get('person') or x.get('speaker','')
        if not isinstance(x.get('id'),str) or not isinstance(x.get('text'),str) or not x['scope'] or not x['person']:raise ValueError('统一证据需要原文 ID、人物及会话范围')
        # History message IDs and turn:u references must resolve to the same
        # real turn, never depend on which background path happened to run.
        rows=self.st.rows('SELECT m.turn_id,m.content,s.scope FROM messages m JOIN sessions s ON s.id=m.session_id WHERE m.id=? AND m.role=\'user\'',(x['id'],))
        if rows:
            if rows[0]['scope']!=x['scope'] or rows[0]['content']!=x['text']:raise ValueError('原始消息与声明的范围或内容不同')
            origin=self.st.rows("SELECT json_extract(payload,'$.person') AS person FROM events WHERE kind IN ('turn','expression_partial') AND json_extract(payload,'$.turn_id')=? LIMIT 1",(rows[0]['turn_id'],))
            if origin and origin[0]['person'] and origin[0]['person']!=x['person']:raise ValueError('原始回合的人物与声明不一致')
            x['event_id']=rows[0]['turn_id']
        x['origin_event_id']=identity(x);x['origin_record_key']=digest([x['scope'],x['person'],x['id']])
        old=self.state()['sources'].get(x['origin_record_key'])
        if old and (old['content_digest']!=digest(x['text']) or old['event_id']!=x['origin_event_id']):raise ValueError('同一原始证据 ID 的内容或事件已改变；请保留原文并显式建立修订')
        return x

    def register(self,records,path):
        value=self.state();out=[];changed=False
        for record in records:
            r=self.normalize(record);key=r['origin_record_key'];out.append(r)
            if key not in value['sources']:
                if len(value['sources'])>=200000:raise ValueError('来源索引已达容量上限，请先导出；未删除历史证据')
                value['sources'][key]={'record_id':r['id'],'event_id':r['origin_event_id'],'original_event_id':r.get('event_id') or r.get('batch_id'),
                    'text':r['text'],'content_digest':digest(r['text']),'scope':r['scope'],'person':r['person'],
                    'source_type':r.get('source','observed'),'direct_interaction':r.get('direct_interaction'),
                    'subject_entity':r.get('subject_entity'),'experience_turn_id':r.get('experience_turn_id'),'experience_event_key':r.get('experience_event_key'),'occurred_at':r.get('timestamp'),'first_path':path,'source_locator':{'record_id':r['id'],'session_id':r.get('session_id')}}
                if r.get('measurement_subject_id'):value['sources'][key]['measurement_subject_id']=r['measurement_subject_id']
                changed=True
        if changed:value['version']+=1;self.st.setmeta('learning_evidence',value)
        return out

    def processed(self,domain,r):
        r=self.normalize(r);receipt=self.state()['receipts'].get(digest([domain,r['origin_event_id']]))
        return bool(receipt and not receipt.get('revoked'))

    def fresh(self,domain,records):return [r for r in records if not self.processed(domain,r)]

    def complete(self,domain,records,task_id,before,after,path,links=None):
        if not records:return None
        rs=self.register(records,path);value=self.state();keys=sorted({r['origin_record_key'] for r in rs});events={r['origin_event_id'] for r in rs}
        for event in events:
            k=digest([domain,event]);prior=value['receipts'].get(k)
            if prior and not prior.get('revoked'):continue
            if prior is None and len(value['receipts'])>=200000:raise ValueError('学习回执已达容量上限；原状态未提交')
            value['receipts'][k]={'domain':domain,'event_id':event,'task_id':task_id,'source_keys':[r['origin_record_key'] for r in rs if r['origin_event_id']==event],'path':path,'at':now(),'revoked':False}
        signature=digest([task_id,domain,keys,digest(before),digest(after),links or {}])
        if not any(r['id']==signature for r in value['revisions']):
            if len(value['revisions'])>=200000:raise ValueError('修订索引已达容量上限；原状态未提交')
            value['revisions'].append({'id':signature,'task_id':task_id,'domain':domain,'source_keys':keys,'event_ids':sorted(events),
                'before':copy.deepcopy(before),'after':copy.deepcopy(after),'changed':before!=after,'path':path,'links':copy.deepcopy(links or {}),'at':now()})
            value['version']+=1
        self.st.setmeta('learning_evidence',value);return signature

    def revoke(self,task_id):
        value=self.state()
        for r in value['receipts'].values():
            if r['task_id']==task_id:r['revoked']=True
        for r in value['revisions']:
            if r['task_id']==task_id:r['rolled_back']=True
        value['version']+=1;self.st.setmeta('learning_evidence',value)

    def trace(self,scope=None,person=None,event_id=None,offset=0,limit=20):
        value=self.state();sources={k:r for k,r in value['sources'].items() if (scope is None or r['scope']==scope) and (person is None or r['person']==person) and (event_id is None or r['event_id']==event_id)}
        rows=[r for r in value['revisions'] if set(r['source_keys'])&sources.keys()]
        rows.sort(key=lambda r:(r['at'],r['id']),reverse=True);offset=max(0,int(offset));limit=max(1,min(50,int(limit)));page=rows[offset:offset+limit]
        # A scoped caller receives no other source fragments from a mixed task.
        page=[{**r,'source_keys':[k for k in r['source_keys'] if k in sources],
            **({'before':None,'after':None,'links':{},'mixed_scope_details_redacted':True} if set(r['source_keys'])-sources.keys() else {})} for r in page]
        selected={k for r in page for k in r['source_keys']}
        return {'schema':SCHEMA,'version':value['version'],'total':len(rows),'offset':offset,'limit':limit,'revisions':page,'sources':{k:sources[k] for k in selected}}

    def validate_supervision_sources(self,row):
        """2.8 labels refer to this existing index, never a second evidence store."""
        value=self.state();sources=value['sources'];profile=self.e.profile()
        withdrawn={r['id'] for r in profile.get('source_records',[])+profile['psychology'].get('evidence_records',[]) if r.get('withdrawn')}
        for key in row.get('evidence_refs',[]):
            r=sources.get(key);quote=row.get('quotes',{}).get(key)
            if not r or r.get('withdrawn') or r['record_id'] in withdrawn:
                raise ValueError('Training source missing or withdrawn')
            if r['source_type'] not in ('human','observed','imported'):
                raise ValueError('Generated source cannot supervise new PMM')
            if row.get('timestamp') is not None and r.get('occurred_at')!=row['timestamp']:raise ValueError('Supervision timestamp differs from raw source')
            if r['scope']!=row['scope'] or r['event_id']!=row['event_id']:
                raise ValueError('Supervision event/scope differs from raw source')
            if r.get('measurement_subject_id')!=row['subject_id']:
                raise ValueError('Measurement subject differs from raw annotation')
            if not isinstance(quote,str) or not quote.strip() or quote not in r['text']:
                raise ValueError('Supervision must quote the original source')
            if any(receipt.get('revoked') and key in receipt['source_keys'] for receipt in value['receipts'].values()):
                raise ValueError('Revoked provenance cannot train or publish')
        if not row.get('evidence_refs'):raise ValueError('Raw supervision evidence required')

    def mark_source_withdrawn(self,record_id,reason):
        value=self.state();changed=False
        for row in value['sources'].values():
            if row['record_id']==record_id:
                row['withdrawn']=True;row['withdrawal_reason']=str(reason)[:1000];changed=True
        if changed:value['version']+=1;self.st.setmeta('learning_evidence',value)
