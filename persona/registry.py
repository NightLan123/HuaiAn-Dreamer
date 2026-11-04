"""Canonical 2.1 constructs. Unknown values stay null; packed zeros require mask=0.

The bundled source registry is immutable. Numeric scales below are engineering
operationalizations, not questionnaire scores. Predictions never become evidence.
"""
from __future__ import annotations
import copy, hashlib, json, math
from pathlib import Path
from .common import now, uid

REGISTRY = json.loads(Path(__file__).with_name('construct_registry.json').read_text('utf8'))
SCHEMA = REGISTRY['state_schema_version']
ENCODER = 'registry-masked/1'
def digest(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
# Additive type metadata must not invalidate the existing 93-column checkpoint.
REGISTRY_HASH = digest({k:v for k,v in REGISTRY.items() if k not in ('feature_temporality','construct_kind','typing_contract_version')})

def _fields():
    c=REGISTRY['constructs']; h=c['hexaco_pi_r']; a=c['affect']
    groups=[('HEXACO', [f for d in h['domains'] for f in d['facets']]+h['interstitial_facets']),
            ('价值', [f for d in c['schwartz_refined_values']['higher_order'] for f in d['values']]),
            ('VAD',a['vad']),('情绪标签',a['emotion_families']),
            ('事件评价',[f for g in a['appraisal_groups'] for f in g['checks']]),
            ('调节策略',a['regulation']),('人际倾向',c['interpersonal']['circumplex']),
            ('语言身份',c['linguistic_identity']['style_features'])]
    return [{**f,'group':group,'minimum':-1 if f['id']=='affect.vad.valence' else 0,'maximum':1} for group,fs in groups for f in fs]
FIELDS=_fields(); ORDER=tuple(f['id'] for f in FIELDS); N=len(ORDER)
KINDS=REGISTRY['construct_kind']; TEMPORALITY=REGISTRY['feature_temporality']
for f in FIELDS:f.update(construct_kind=KINDS[f['id']],feature_temporality=TEMPORALITY[f['id']])
BY_ID={f['id']:f for f in FIELDS}
LONG_IDS=tuple(k for k in ORDER if TEMPORALITY[k]=='long')
STATE_IDS=tuple(k for k in ORDER if KINDS[k]=='emotion_state')
APPRAISAL_IDS=tuple(k for k in ORDER if KINDS[k]=='event_appraisal')
REGULATION_IDS=tuple(k for k in ORDER if KINDS[k]=='regulation_operation')
CONTRACT={'registry_hash':REGISTRY_HASH,'encoder_version':ENCODER,'state_schema_version':SCHEMA,'feature_order':list(ORDER)}

def empty_state(scope='agent_self'):
    return {**copy.deepcopy(CONTRACT),'schema_version':SCHEMA,'features':{
        k:{'feature_id':k,'estimate':None,'posterior_uncertainty':None,'evidence_ids':[],'evidence_count':0,
           'scope':scope,'source_type':'unknown','updated_at':None,'method_version':'unobserved/1',
           'schema_version':SCHEMA,'conflict':False} for k in ORDER},'observations':[],'evidence_records':[],
        'decay':{'last_event_timestamp':None,'baseline_reference':None,'time_constant_or_policy':{'affect_hours':2,'uncertainty_increases':True}},'migrations':[]}

def ensure_profile(profile,scope='agent_self'):
    p=copy.deepcopy(profile)
    if 'psychology' not in p:
        p['psychology']=empty_state(scope)
        p['psychology']['migrations'].append({'from':p.get('format'),'to':SCHEMA,'method':'preserve_legacy_no_facet_imputation/1','at':now(),
            'note':'旧五因素与十价值保留为 legacy 视图；不拆分为伪造的 HEXACO / 19 价值。'})
    from .traits import ensure_traits
    return ensure_traits(p,scope)

def number(value,low=0,high=1):
    if type(value) not in (int,float) or not math.isfinite(value) or not low<=value<=high:raise ValueError('心理字段数值越界')
    return float(value)

def validate_state(state,records,scope=None):
    if not isinstance(state,dict) or any(state.get(k)!=v for k,v in CONTRACT.items()):raise ValueError('心理字段注册表、顺序或编码版本不匹配；需要显式迁移')
    if state.get('schema_version')!=SCHEMA or set(state.get('features',{}))!=set(ORDER):raise ValueError('完整心理字段缺失')
    evidence_records=state.get('evidence_records',[])
    if not isinstance(evidence_records,list) or any(not isinstance(r,dict) or not all(isinstance(r.get(k),str) for k in ('id','speaker','text')) for r in evidence_records):raise ValueError('心理事件证据无效')
    byid={r['id']:r for r in records}
    for r in evidence_records:
        if r['id'] in byid and byid[r['id']]['text']!=r['text']:raise ValueError('心理证据ID内容冲突')
        byid[r['id']]=r
    observations=state.get('observations')
    if not isinstance(observations,list):raise ValueError('心理证据列表无效')
    for o in observations:
        if not isinstance(o,dict) or o.get('feature_id') not in BY_ID:raise ValueError('心理观察字段无效')
        spec=BY_ID[o['feature_id']];number(o.get('estimate'),spec['minimum']);number(o.get('confidence'))
        if not isinstance(o.get('evidence'),list) or not o['evidence']:raise ValueError('心理观察缺少证据')
        for ev in o['evidence']:
            r=byid.get(ev.get('record_id')) if isinstance(ev,dict) else None
            if not r or not isinstance(ev.get('quote'),str) or not ev['quote'].strip() or ev['quote'] not in r['text']:raise ValueError('心理观察证据不匹配')
    for k,f in state['features'].items():
        if not isinstance(f,dict) or f.get('feature_id')!=k or f.get('schema_version')!=SCHEMA:raise ValueError('心理字段记录无效')
        if f.get('scope') not in ('agent_self','model_of_other','relation','group') or (scope and f['scope']!=scope):raise ValueError('心理字段主体范围无效')
        ids=f.get('evidence_ids')
        if not isinstance(ids,list) or len(ids)!=len(set(ids)) or set(ids)-set(byid) or f.get('evidence_count')!=len(ids):raise ValueError('心理字段证据计数无效')
        if f.get('estimate') is None:
            if f.get('posterior_uncertainty') is not None or ids:raise ValueError('未知字段不能伪造置信度或证据')
        else:
            number(f['estimate'],BY_ID[k]['minimum']);number(f.get('posterior_uncertainty'))
            if not ids or not any(o['feature_id']==k for o in observations):raise ValueError('已知字段必须有来源观察')
        if f.get('updated_at') is not None:number(f['updated_at'],0,1e13)
        if not isinstance(f.get('method_version'),str) or not isinstance(f.get('source_type'),str):raise ValueError('心理字段测量方式无效')
    decay=state.get('decay')
    if not isinstance(decay,dict) or not isinstance(decay.get('time_constant_or_policy'),dict):raise ValueError('情绪衰减策略缺失')
    number(decay['time_constant_or_policy'].get('affect_hours'),.01,8760)
    return state

def _observe(state,rows,records,source='imported',allowed=None):
    out=copy.deepcopy(state);byid={r['id']:r for r in records};accepted=0;rejected=0
    if not isinstance(rows,list):raise ValueError('心理更新应为列表')
    for row in rows[:N*2]:
        try:
            k=row['feature_id'];spec=BY_ID[k]
            if allowed is not None and k not in allowed:raise ValueError('写入实体类型不匹配')
            v=number(row['estimate'],spec['minimum']);c=min(.75,number(row.get('confidence',.4)))
            evidence=[]
            for e in row.get('evidence',[]):
                r=byid.get(e.get('record_id'));q=e.get('quote')
                if r and isinstance(q,str) and q.strip() and q in r['text']:evidence.append({'record_id':r['id'],'quote':q[:2000]})
            if not evidence or c<=0:raise ValueError('无有效证据')
            # Generated language is expression observation, never a stable personality label.
            if source=='generated' and k in LONG_IDS:raise ValueError('生成内容不是稳定人格证据')
            c=min(c,.15 if source=='generated' else .5 if source=='observed' else .75)
            signature=(k,tuple((e['record_id'],e['quote']) for e in evidence))
            if any((o['feature_id'],tuple((e['record_id'],e['quote']) for e in o['evidence']))==signature for o in out['observations']):continue
            observation={'id':uid(),'feature_id':k,'estimate':v,'confidence':c,'evidence':evidence,'source':source,'timestamp':now(),'method_version':'typed-evidence/1','construct_kind':KINDS[k]}
            out['observations'].append(observation)
            known={r['id'] for r in out['evidence_records']}
            out['evidence_records'].extend(copy.deepcopy(byid[e['record_id']]) for e in evidence if e['record_id'] not in known and not known.add(e['record_id']))
            # Long-term candidates require a separate promotion task. Repeated mood
            # observations or model-generated statements cannot edit the trait prior.
            if k in LONG_IDS:
                observation['status']='candidate';accepted+=1;continue
            obs=[o for o in out['observations'] if o['feature_id']==k]
            ids=sorted({e['record_id'] for o in obs for e in o['evidence']});weights=sum(o['confidence'] for o in obs)
            mean=sum(o['confidence']*o['estimate'] for o in obs)/max(weights,1e-9)
            spread=max(o['estimate'] for o in obs)-min(o['estimate'] for o in obs);old=out['features'][k]
            mean=v
            old.update(estimate=mean,posterior_uncertainty=1-min(.85,weights/(weights+2))*max(.05,1-spread/2),
                evidence_ids=ids,evidence_count=len(ids),source_type='model_generated' if source=='generated' else 'inferred',updated_at=now(),method_version='evidence-inference/1',conflict=spread>.4)
            accepted+=1
        except (KeyError,TypeError,ValueError):rejected+=1
    if accepted:out['decay']['last_event_timestamp']=now()
    return out,{'accepted':accepted,'rejected':rejected}

def update_trait_evidence(state,rows,records,source='imported'):
    return _observe(state,rows,records,source,LONG_IDS)

def update_affect_state(state,rows,records,source='observed'):
    return _observe(state,rows,records,source,STATE_IDS)

def update_event_appraisal(state,rows,records,source='observed'):
    return _observe(state,rows,records,source,APPRAISAL_IDS)

def record_regulation_action(state,rows,records,source='observed'):
    return _observe(state,rows,records,source,REGULATION_IDS)

def update_state(state,rows,records,source='imported'):
    """Version-2.1 record reader/import router; never treats 93 columns as traits.

    Dynamic imported observations remain historical evidence. Live events are
    committed to affect.py's entities, not this compatibility feature cache.
    """
    if not isinstance(rows,list):raise ValueError('心理更新应为列表')
    out=copy.deepcopy(state);totals={'accepted':0,'rejected':0}
    for ids,fn in ((LONG_IDS,update_trait_evidence),(STATE_IDS,update_affect_state),(APPRAISAL_IDS,update_event_appraisal),(REGULATION_IDS,record_regulation_action)):
        selected=[r for r in rows if isinstance(r,dict) and r.get('feature_id') in ids]
        out,report=fn(out,selected,records,source)
        for k in totals:totals[k]+=report[k]
    totals['rejected']+=sum(not isinstance(r,dict) or r.get('feature_id') not in BY_ID for r in rows)
    return out,totals

def state_view(state,at=None):
    out=copy.deepcopy(state);at=now() if at is None else at
    hours=out['decay']['time_constant_or_policy']['affect_hours']
    for k,f in out['features'].items():
        if KINDS[k] in ('event_appraisal','regulation_operation'):
            f['historical_only']=True;f['stale']=True;continue
        if KINDS[k]!='emotion_state' or f['estimate'] is None:continue
        duration={'surprise':300,'anger':1800,'fear':2400,'sadness':7200}.get(k.rsplit('.',1)[-1],hours*3600)
        age=max(0,at-(f['updated_at'] or at));keep=math.exp(-age/duration) if f['updated_at'] else 0.
        f['posterior_uncertainty']=1-(1-f['posterior_uncertainty'])*keep
        f['stale']=keep<.1  # without an evidenced baseline do not invent a neutral affect
    return out

def compact(state):
    s=state_view(state)
    return {'schema_version':SCHEMA,'registry_hash':REGISTRY_HASH,'known':{k:{n:f[n] for n in ('estimate','posterior_uncertainty','evidence_ids','source_type','conflict')} for k,f in s['features'].items() if f['estimate'] is not None},'unknown_fields':[k for k,f in s['features'].items() if f['estimate'] is None]}

def pack_features(state):
    values=[];mask=[]
    for k in ORDER:
        f=state['features'][k];v=f['estimate'];valid=v is not None and not f.get('stale',False)
        values.append((v+1)/2 if valid and BY_ID[k]['minimum']==-1 else v if valid else 0.)
        mask.append(float(valid))
    return values,mask

def extend_vector(base,state=None):
    import numpy as np
    values,mask=pack_features(state_view(state)) if state else ([0.]*N,[0.]*N)
    return np.concatenate((base,values,mask))

def coverage(state):
    return {group:{'registered':sum(f['group']==group for f in FIELDS),'known':sum(f['group']==group and state['features'][f['id']]['estimate'] is not None for f in FIELDS)} for group in dict.fromkeys(f['group'] for f in FIELDS)}

def filter_evidence(state,record_ids):
    s=copy.deepcopy(state);s['observations']=[o for o in s['observations'] if all(e['record_id'] in record_ids for e in o['evidence'])]
    s['evidence_records']=[r for r in s.get('evidence_records',[]) if r['id'] in record_ids]
    for k,f in s['features'].items():
        if not set(f['evidence_ids'])<=record_ids:s['features'][k]=empty_state(f['scope'])['features'][k]
    return s
