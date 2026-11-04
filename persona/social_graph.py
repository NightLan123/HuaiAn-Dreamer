"""Evidence-bearing directed relation claims with explicit context access.

Stored as a separate versioned namespace in SQLite's existing meta table so old
backups keep all graph entities. Presence/co-membership never implies friendship.
"""
from __future__ import annotations
import copy, math
from .common import now, uid
from .registry import digest

SCHEMA='social-graph/1'
RELATIONS=('friend','family','colleague','acquaintance','conflict','other')

def empty():return {'schema':SCHEMA,'version':0,'people':{},'contexts':{},'memberships':[],'relation_claims':[],'events':[]}

def validate(state):
    if state is None:return
    if not isinstance(state,dict) or state.get('schema')!=SCHEMA or type(state.get('version')) is not int:raise ValueError('人际网络版本无效')
    if not all(isinstance(state.get(k),dict) for k in ('people','contexts')) or not all(isinstance(state.get(k),list) for k in ('memberships','relation_claims','events')):raise ValueError('人际网络结构无效')
    ids=set()
    for r in state['memberships']:
        if not isinstance(r,dict) or r.get('person_id') not in state['people'] or r.get('context_id') not in state['contexts'] or not isinstance(r.get('evidence_ids'),list):raise ValueError('群体来源或身份引用无效')
        if 'identity' in r:
            identity=r['identity']
            if not isinstance(identity,dict) or not isinstance(identity.get('alias'),str) or not identity['alias'] or len(identity['alias'])>100 or identity.get('status') not in ('owner_annotated','disputed'):raise ValueError('范围身份核验格式无效')
            v=identity.get('uncertainty')
            if type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1:raise ValueError('身份不确定性无效')
            if not isinstance(identity.get('evidence'),list) or not identity['evidence'] or any(not isinstance(e,dict) or e.get('scope')!=r['context_id'] or not all(isinstance(e.get(k),str) and e[k] for k in ('source_key','record_id','quote')) for e in identity['evidence']):raise ValueError('范围身份缺少同范围原文')
    for r in state['relation_claims']:
        if not isinstance(r,dict) or r.get('subject_person_id') not in state['people'] or r.get('object_person_id') not in state['people'] or r.get('scope_id') not in state['contexts']:raise ValueError('关系来源或身份引用无效')
        if r.get('id') in ids or not isinstance(r.get('id'),str) or r.get('relation_type') not in RELATIONS or r.get('knowledge_type') not in ('self_report','third_party_report','observed','inferred','confirmed') or r.get('status') not in ('unverified','confirmed','disputed','retracted'):raise ValueError('关系陈述类型或状态无效')
        ids.add(r['id'])
        if not isinstance(r.get('evidence'),list) or not r['evidence'] or any(not isinstance(e,dict) or not isinstance(e.get('quote'),str) or not e['quote'].strip() or not isinstance(e.get('record_id'),str) or e.get('scope')!=r['scope_id'] for e in r['evidence']):raise ValueError('关系陈述缺少同范围原文')
        if type(r.get('confidence')) not in (int,float) or not math.isfinite(r['confidence']) or not 0<=r['confidence']<=1:raise ValueError('关系置信度无效')

class SocialGraph:
    def __init__(self,engine):self.e=engine;self.st=engine.store;validate(self.st.meta('social_graph'))
    def state(self):return copy.deepcopy(self.st.meta('social_graph') or empty())
    def _person(self,state,person):
        if not isinstance(person,str) or not person or len(person)>200:raise ValueError('必须提供稳定人物标识，不能仅按昵称合并')
        if person not in state['people']:state['people'][person]={'person_id':person,'identity_source':'platform_id' if person.startswith('qq:') else 'explicit_local_id','alias':person,'confidence':1.,'created_at':now()}
    def _context(self,state,scope):
        if not isinstance(scope,str) or not scope or scope=='*' or len(scope)>200:raise ValueError('图谱必须属于明确会话范围')
        state['contexts'].setdefault(scope,{'context_id':scope,'type':'group' if scope.startswith('group:') else 'private','scope':scope,'created_at':now()})
    def observe_membership(self,scope,person,records):
        state=self.state();self._person(state,person);self._context(state,scope)
        membership=next((r for r in state['memberships'] if r['person_id']==person and r['context_id']==scope),None)
        if not membership:
            membership={'person_id':person,'context_id':scope,'since':now(),'until':None,'evidence_ids':[],'status':'observed_presence','relation_meaning':'仅表示在此范围出现过，不证明好友或正式成员身份'};state['memberships'].append(membership)
        added=[r['id'] for r in records if r['id'] not in membership['evidence_ids']]
        membership['evidence_ids'].extend(added)
        if added:state['version']+=1;state['events'].append({'id':uid(),'kind':'presence','scope':scope,'person_id':person,'source_ids':added,'at':now()})
        validate(state);self.st.setmeta('social_graph',state)
    def apply_claims(self,claims,records,job_id,strength=1.):
        if not isinstance(claims,list):raise ValueError('关系陈述必须是列表')
        state=self.state();byid={r['id']:r for r in records};accepted=[];rejected=[]
        authorized_people={r['person'] for r in self.st.sessions()}|{r['person'] for r in records}|set(state['people'])
        for row in claims[:300]:
            r=byid.get(row.get('record_id')) if isinstance(row,dict) else None
            if not r:rejected.append('unknown_source');continue
            q=row.get('quote');subject=row.get('subject');obj=row.get('object');kind=row.get('knowledge_type');relation=row.get('relation_type');confidence=row.get('confidence');polarity=row.get('polarity','support')
            if not isinstance(q,str) or not q.strip() or q not in r['text']:rejected.append('ungrounded_quote');continue
            if subject not in authorized_people or obj not in authorized_people or subject==obj or relation not in RELATIONS or polarity not in ('support','counter'):rejected.append('unknown_identity_or_relation');continue
            # Only actors explicitly visible in this context can become graph
            # endpoints. A shared nickname never unlocks another private scope.
            visible={v['person'] for v in self.st.sessions() if v['scope']==r['scope']}|{v['person'] for v in records if v['scope']==r['scope']}|{m['person_id'] for m in state['memberships'] if m['context_id']==r['scope']}
            if subject not in visible or obj not in visible:rejected.append('endpoint_not_visible_in_scope');continue
            if kind not in ('self_report','third_party_report') or kind=='self_report' and r['person']!=subject:rejected.append('invalid_report_authority');continue
            if type(confidence) not in (int,float) or not math.isfinite(confidence) or not 0<=confidence<=1:rejected.append('invalid_confidence');continue
            identifier='claim:'+digest([r['scope'],r['id'],subject,obj,relation,polarity])[:32]
            if any(c['id']==identifier for c in state['relation_claims']):continue
            self._person(state,subject);self._person(state,obj);self._context(state,r['scope'])
            evidence={'record_id':r['id'],'speaker':r['person'],'quote':q,'scope':r['scope'],'source':'human_statement','event_id':r.get('event_id') or r['id']}
            claim={'id':identifier,'subject_person_id':subject,'object_person_id':obj,'relation_type':relation,'directed':True,'knowledge_type':kind,
                'scope_id':r['scope'],'valid_time':r.get('timestamp'),'recorded_time':now(),'evidence':[evidence],'evidence_ids':[r['id']],
                'confidence':min(.75,confidence)*strength,'uncertainty':max(.25,1-min(.75,confidence)*strength),'status':'unverified','polarity':polarity,'version':1,'job_id':job_id}
            conflict=[c for c in state['relation_claims'] if c['subject_person_id']==subject and c['object_person_id']==obj and c['relation_type']==relation and c['scope_id']==r['scope'] and c['status']!='retracted' and c.get('polarity','support')!=polarity]
            if conflict:
                claim.update(status='disputed',uncertainty=max(.65,claim['uncertainty']),conflicts_with=[c['id'] for c in conflict])
                for c in conflict:c.update(status='disputed',uncertainty=max(.65,c['uncertainty']),version=c['version']+1)
            state['relation_claims'].append(claim);accepted.append(identifier)
            state['events'].append({'id':uid(),'kind':'claim_created','claim_id':identifier,'at':now(),'job_id':job_id,'scope':r['scope']})
        if accepted:state['version']+=1
        validate(state);self.st.setmeta('social_graph',state)
        return {'accepted':len(accepted),'accepted_ids':accepted,'rejected':len(rejected),'rejection_reasons':rejected,'confirmed':0}
    def query(self,scopes,person=None):
        if not isinstance(scopes,list) or not scopes or any(not isinstance(s,str) or not s or s=='*' for s in scopes):raise ValueError('请明确选择允许查询的范围；跨群查询须逐个选择')
        state=self.state();contexts={k:v for k,v in state['contexts'].items() if k in scopes};members=[r for r in state['memberships'] if r['context_id'] in scopes]
        claims=[r for r in state['relation_claims'] if r['scope_id'] in scopes and (not person or person in (r['subject_person_id'],r['object_person_id']))]
        people={r['person_id'] for r in members}|{v for r in claims for v in (r['subject_person_id'],r['object_person_id'])}
        intersections=[]
        for p in sorted(people):
            shared=sorted({r['context_id'] for r in members if r['person_id']==p})
            if len(shared)>1:intersections.append({'person_id':p,'contexts':shared,'meaning':'共同出现的桥接人物；不推断其他成员相识'})
        return {'schema':SCHEMA,'version':state['version'],'people':[state['people'][p] for p in sorted(people)],'contexts':list(contexts.values()),'memberships':members,'relation_claims':claims,'intersections':intersections,'available_scopes':sorted(state['contexts']),'context_access':'explicit_query_scopes_only'}
    def edit(self,body):
        with self.e.lock,self.st.lock,self.st.db:
            state=self.state()
            if body.get('expected_version')!=state['version']:raise ValueError('人际网络版本已改变，请刷新')
            row=next((r for r in state['relation_claims'] if r['id']==body.get('id')),None)
            if not row:raise ValueError('关系陈述不存在')
            op=body.get('op');reason=str(body.get('reason','')).strip()
            if op not in ('confirm','retract','dispute') or not reason:raise ValueError('请填写关系核验/撤回理由')
            before=copy.deepcopy(row);row.update(status={'confirm':'confirmed','retract':'retracted','dispute':'disputed'}[op],version=row['version']+1)
            # Confirmation is an explicit owner's annotation, not model certainty.
            row['owner_review']={'at':now(),'reason':reason[:1000],'source':'owner_annotation'}
            state['events'].append({'id':uid(),'kind':op,'claim_id':row['id'],'before':before,'after':copy.deepcopy(row),'at':now(),'scope':row['scope_id']});state['version']+=1
            validate(state);self.st.setmeta('social_graph',state);return self.query([row['scope_id']])
    def context(self,scope,person):
        r=self.query([scope],person)
        return {'scope':scope,'claims':[{k:copy.deepcopy(c[k]) for k in ('subject_person_id','object_person_id','relation_type','knowledge_type','status','confidence','uncertainty','evidence')} for c in r['relation_claims'] if c['status']!='retracted'][-20:],
            'interpretation':'陈述和转述不等于关系事实；不推断互认，不据此制造亲密或共同经历。仅当前会话范围。'}
