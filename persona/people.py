"""Scoped identity evidence on existing social-graph memberships and profiles."""
import copy
from .common import now
from .registry import digest
from . import relationships as dy

class People:
    def __init__(self,engine):self.e=engine;self.st=engine.store
    def query(self,scope,person=None):
        if not isinstance(scope,str) or not scope or scope=='*':raise ValueError('必须明确选择会话范围')
        g=self.e.social_graph.state();members=[m for m in g['memberships'] if m['context_id']==scope]
        observed=self.st.rows("SELECT DISTINCT json_extract(payload,'$.person') AS person FROM events WHERE kind IN ('turn','expression_partial') AND json_extract(payload,'$.scope')=?",(scope,))
        ids={r['person'] for r in observed if r['person']}|{m['person_id'] for m in members}|{s['person'] for s in self.st.sessions() if s['scope']==scope}
        sources=self.e.evidence.state()['sources'];others=self.st.meta('pmm_interlocutors') or {};dyads=self.st.meta('pmm_dyads') or {};rows=[]
        for pid in sorted(ids):
            if person is not None and pid!=person:continue
            member=next((m for m in members if m['person_id']==pid),{});annotation=member.get('identity',{})
            evidence=[{**copy.deepcopy(r),'source_key':k} for k,r in sources.items() if r['scope']==scope and r['person']==pid]
            direct=bool(self.st.rows("SELECT id FROM events WHERE kind IN ('turn','expression_partial') AND json_extract(payload,'$.scope')=? AND json_extract(payload,'$.person')=? AND COALESCE(json_extract(payload,'$.turn_context.direct_interaction'),1)=1 LIMIT 1",(scope,pid)))
            k=self.e.other_key(scope,pid);p=others.get(k)
            rows.append({'entity_id':k,'person_id':pid,'scope':scope,'entity_type':'interlocutor' if direct else 'third_party',
                'alias':annotation.get('alias',pid),'identity_status':annotation.get('status','platform_identifier' if pid.startswith('qq:') else 'local_identifier_unverified'),
                'uncertainty':annotation.get('uncertainty',.25 if pid.startswith('qq:') else 1.),'identity_evidence':copy.deepcopy(annotation.get('evidence',[])),
                'profile':copy.deepcopy(p),'relationship':dy.ensure(dyads[k]) if k in dyads else None,'sources':evidence[-50:],
                'source_count':len(evidence),'direct_interaction':direct,'scope_access':'exact_scope_only'})
        return {'version':g['version'],'scope':scope,'self':{'entity_type':'agent_self','persona_id':self.st.meta('identity')['id']},'people':rows,
            'identity_rule':'昵称不自动合并；同一标识跨会话的私密资料各自隔离；第三方出现不代表认识 AI'}
    def edit(self,body):
        with self.e.lock,self.st.lock,self.st.db:
            g=self.e.social_graph.state()
            if body.get('expected_version')!=g['version']:raise ValueError('人物证据版本已变化，请刷新')
            scope=body.get('scope');pid=body.get('person');alias=str(body.get('alias','')).strip();op=body.get('op','annotate')
            if pid==self.st.meta('identity')['id'] or pid=='agent_self':raise ValueError('AI 自身不能作为他人身份')
            source=self.e.evidence.state()['sources'].get(body.get('source_key'))
            if not source or source['scope']!=scope or source['source_type']=='generated':raise ValueError('身份证据须来自本范围原始真人记录')
            if op not in ('annotate','dispute') or not alias or len(alias)>100:raise ValueError('请填写本范围昵称与有效核验操作')
            q=body.get('quote')
            if not isinstance(q,str) or not q.strip() or q not in source['text']:raise ValueError('身份依据必须逐字引用原文')
            self.e.social_graph._person(g,pid);self.e.social_graph._context(g,scope)
            m=next((m for m in g['memberships'] if m['person_id']==pid and m['context_id']==scope),None)
            if m is None:
                # An explicit owner-assigned local reference for a mentioned
                # third party, not platform identity resolution or a friendship.
                m={'person_id':pid,'context_id':scope,'since':now(),'until':None,'evidence_ids':[],'status':'mentioned_third_party'};g['memberships'].append(m)
            previous=copy.deepcopy(m.get('identity'));ev={'source_key':body['source_key'],'record_id':source['record_id'],'scope':scope,'person':source['person'],'quote':q,'knowledge_type':'owner_annotation','at':now()}
            m['identity']={'alias':alias,'status':'disputed' if op=='dispute' else 'owner_annotated','uncertainty':.75 if op=='dispute' else .25,'evidence':(previous or {}).get('evidence',[])+[ev]}
            g['version']+=1;g['events'].append({'id':digest([pid,scope,g['version']]),'kind':'identity_'+op,'person_id':pid,'scope':scope,'before':previous,'after':copy.deepcopy(m['identity']),'at':now()})
            self.st.setmeta('social_graph',g);return self.query(scope,pid)
    def relation_edit(self,body):
        with self.e.lock,self.st.lock,self.st.db:
            k=dy.key(body.get('person',''),body.get('scope',''));ds=self.st.meta('pmm_dyads') or {}
            if k not in ds:raise ValueError('当前人物与范围不存在关系档案')
            old=ds[k];ds[k]=dy.revise(old,body);self.st.setmeta('pmm_dyads',ds)
            self.st.event('relationship_schema_revised',{'key':k,'before_version':dy.ensure(old)['schema_revision'],'after_version':ds[k]['schema_revision'],'reason':body.get('reason')})
            return {'ok':True,'relationship':ds[k]}
    def context(self,scope,person):
        # Neither all identities nor global aliases are exposed to model prompts.
        rows=self.query(scope,person)['people']
        return {'self':{'type':'agent_self','id':self.st.meta('identity')['id']},'scope':scope,
            'interlocutor':{k:rows[0][k] for k in ('entity_id','person_id','alias','identity_status','uncertainty','entity_type')} if rows else {'person_id':person,'entity_type':'interlocutor','identity_status':'unknown'},
            'third_parties':[{k:r[k] for k in ('person_id','alias','identity_status','uncertainty')} for r in self.query(scope)['people'] if r['entity_type']=='third_party'],
            'rule':'仅本会话范围；记录的身份和推断不是已确认的现实身份'}
