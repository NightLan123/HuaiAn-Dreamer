"""Fixed-condition evaluation of the same PMM appraisal/policy functions.

No alternative memory/personality model and no state writes. Frozen model
assessments isolate the local contribution; this is not a cloud-LLM causal trial.
"""
from __future__ import annotations
import copy,json
from . import traits as tr, relationships as dy, affect as af
from .registry import LONG_IDS,digest,number
from .psychology import empty_profile,ACTIONS
from .common import clamp

RULE='pmm-person-relational-conditions/1'
def conditions(profile,u,relation):
    ts=tr.snapshot(profile);appraisal=dy.cognition(ts,u,relation);s=u['semantic'];features={k:{**r,'uncertainty':r['posterior_uncertainty']} for k,r in ts['operative_personality'].items()}
    def value(k):
        f=features.get(k)
        return (f['estimate']-.5)*2*(1-(f['uncertainty'] if f['uncertainty'] is not None else 1)) if f else 0.
    d=relation['dyad'];trust=(d['trust']-.5)*2*(1-d.get('uncertainties',{}).get('trust',{}).get('estimate',.5)) if d['trust'] is not None else 0.
    h=s.get('hostility',0);social=s.get('social',0);ambiguity=s.get('ambiguity',0)
    terms={group:{a:0. for a in ACTIONS} for group in ('personality','relationship','regulation')}
    terms['personality'].update(reply=(.08*value('social.communion')+.08*value('hexaco.x.sociability'))*social,clarify=.18*value('hexaco.c.prudence')*ambiguity,disagree=-.18*value('hexaco.a.patience')*h)
    terms['relationship'].update(reply=.12*trust*social,clarify=-.06*trust*social,disagree=-.08*trust*h)
    reg=ts['affective_disposition']['erq.cognitive_reappraisal'];r=0. if reg['estimate'] is None else (reg['estimate']-.5)*2*(1-(reg['uncertainty'] if reg['uncertainty'] is not None else 1))
    terms['regulation'].update(clarify=.08*r*h,disagree=-.1*r*h)
    return {'schema':RULE,'trait_version':ts['trait_version'],'trait_digest':ts['trait_digest'],'relationship_version':d.get('schema_revision',0),
        'relationship_digest':digest(d),'person':d['other_id'],'scope':d['context_id'],'appraisal':appraisal,'terms':terms,
        'regulation_source':{'feature_id':'erq.cognitive_reappraisal',**reg},'personality_inputs':features,
        'model':'explicit_bounded_engineering_coefficients','calibrated':False,
        'source_use':{k:'contributes_to_scores' if any(abs(v)>1e-12 for v in rows.values()) else 'read_with_zero_score_effect' for k,rows in terms.items()}}

def with_affect(condition,activity,u):
    """Current affect changes evaluation/action, never the stable trait store."""
    c=copy.deepcopy(condition);e=activity.get('emotion') or {};s=u.get('semantic') or {}
    stress=e.get('stress');valence=e.get('valence');social=s.get('social',0);hostility=s.get('hostility',0)
    terms={a:0. for a in ACTIONS}
    if type(valence) in (int,float):terms['reply']=.08*clamp(valence,-1,1)*social
    if type(stress) in (int,float):
        terms['clarify']=.06*clamp(stress)*s.get('ambiguity',0)
        terms['disagree']=.06*clamp(stress)*hostility
    c['terms']['emotion']=terms;c['emotion_inputs']={k:e.get(k) for k in ('valence','arousal','stress','engagement')}
    c['source_use']['emotion']='contributes_to_scores' if any(terms.values()) else 'read_with_zero_score_effect'
    return c

def compact_profile(p):
    q=empty_profile(p['id'],p['name']);q.update({k:copy.deepcopy(p[k]) for k in ('seed','character','revision','updated_at') if k in p})
    q['psychology']['features']=copy.deepcopy(p['psychology']['features'])
    q['psychology']['evidence_records']=[{k:copy.deepcopy(r[k]) for k in ('id','source','role','withdrawn','evidence_kind') if k in r} for r in p.get('source_records',[])+p['psychology'].get('evidence_records',[])]
    q['trait_profile']={**copy.deepcopy(p['trait_profile']),'disposition_observations':[],'promotion_history':[]}
    for f in q['trait_profile']['dispositions'].values():f['evidence']=[{'record_id':e['record_id']} for e in f.get('evidence',[])]
    q['boundaries']=[{k:copy.deepcopy(v) for k,v in b.items() if k!='evidence'} for b in p['boundaries']]
    return q

def capture(profile,u,relation,affect,proposal,event,at,views,assessment,decoded,memories,decision,model_digest):
    state=copy.deepcopy(affect)
    for key in ('appraisals','regulation_actions','expressions','trajectory'):state[key]=[]
    result={'schema':'pmm-controlled-input/1','profile':compact_profile(profile),'understanding':copy.deepcopy(u),'relationship':copy.deepcopy(relation),
        'affect_before':state,'affect_proposal':copy.deepcopy(proposal),'event':copy.deepcopy(event),'at':at,'views':copy.deepcopy(views),
        'assessment':copy.deepcopy(assessment),'decoded':{k:copy.deepcopy(decoded[k]) for k in ('influence','action_probabilities')},
        'memories':copy.deepcopy(memories),'actual_decision':copy.deepcopy(decision),'model_digest':model_digest}
    result['input_digest']=digest(result);return result

def evaluate_case(frozen,intervention=None):
    from .policy import choose
    f=copy.deepcopy(frozen);p=f['profile'];rel=f['relationship'];intervention=intervention or {};kind=intervention.get('ablate')
    if kind=='personality':
        for k in LONG_IDS:p['psychology']['features'][k].update(estimate=None,posterior_uncertainty=None)
        p['seed']='';p['character']={}
    elif kind=='relationship':rel=dy.policy_relation(dy.empty(rel['dyad']['other_id'],rel['dyad']['context_id']))
    elif kind=='regulation':
        for v in p['trait_profile']['dispositions'].values():v.update(estimate=None,uncertainty=None,source_type='unknown')
    if 'feature_id' in intervention:
        k=intervention['feature_id'];v=number(intervention['estimate'])
        if k in LONG_IDS:
            p=tr.edit_canonical(p,{'feature_id':k,'estimate':v,'expected_version':p['trait_profile']['version'],'note':'仅离线反事实，不提交'})
        elif k in tr.DISPOSITIONS:p['trait_profile']['dispositions'][k].update(estimate=v,uncertainty=0.,source_type='owner_seed')
        else:raise ValueError('实验只能干预注册的长期人格或情绪倾向')
    u=f['understanding'];c=conditions(p,u,rel);u['decision_conditions']=c
    state,layer=af.evaluate(f['affect_before'],tr.snapshot(p),u,f['event'],rel,f['memories'],f['affect_proposal'],at=f['at'])
    c=with_affect(c,af.compatibility(state),u);u['decision_conditions']=c
    decision=choose(u,p,f['views'],f['assessment']['views'],f['decoded'],f['memories'],f['event']['text'])
    actual=f['actual_decision'];locked=actual['gate']!='weighted_policy'
    if locked:decision.update(action=actual['action'],gate=actual['gate'],reason='固定现有知识/边界/执行门控；本次不重新评估该门控')
    expression=af.expression_plan(tr.snapshot(p),state,decision,{'scope':f['event']['scope'],'person_id':f['event']['person']})
    return {'intervention':intervention,'appraisal':c['appraisal']['estimates'],'decision':{k:decision[k] for k in ('action','scores','gate')},
        'contributions':c['terms'],'source_use':c['source_use'],'emotion':{k:state['emotion'][k] for k in ('valence','arousal','stress')},
        'regulation':layer['regulation_action']['strategy'],'expression_intensity':expression['intensity'],'gate_held_fixed':locked}

def compare(frozen,feature_id='hexaco.a.patience',low=.2,high=.8):
    if not isinstance(frozen,dict) or frozen.get('schema')!='pmm-controlled-input/1':raise ValueError('此历史回合没有 2.7 固定条件记录；请在升级后完成一轮对话')
    signature=frozen.get('input_digest');body={k:v for k,v in frozen.items() if k!='input_digest'}
    if signature!=digest(body):raise ValueError('固定条件记录摘要不匹配')
    cases=[('baseline',{}),('without_personality',{'ablate':'personality'}),('without_relationship',{'ablate':'relationship'}),('without_regulation',{'ablate':'regulation'}),('low',{'feature_id':feature_id,'estimate':number(low)}),('high',{'feature_id':feature_id,'estimate':number(high)})]
    rows={k:evaluate_case(frozen,v) for k,v in cases};base=rows['baseline'];comparisons=[]
    for name,case in rows.items():
        if name=='baseline':continue
        delta={a:case['decision']['scores'][a]-base['decision']['scores'][a] for a in ACTIONS};changed=case['decision']['action']!=base['decision']['action']
        magnitude=max(abs(v) for v in delta.values())
        comparisons.append({'condition':name,'action_changed':changed,'score_delta':delta,'max_absolute_score_change':magnitude,
            'appraisal_changed':case['appraisal']!=base['appraisal'],'expression_change':case['expression_intensity']-base['expression_intensity'],
            'finding':'行动发生变化' if changed else '行动相同，存在局部评分差异' if magnitude>1e-9 else '未观察到局部行动评分差异'})
    return {'schema':'pmm-controlled-comparison/1','input_digest':signature,'model_digest':frozen['model_digest'],'event':frozen['event'],
        'fixed':{'time':frozen['at'],'person':frozen['event']['person'],'scope':frozen['event']['scope'],'base_understanding':True,'model_assessment':True,'memory':True,'view_weights':True,'initial_affect':True},
        'rows':rows,'comparisons':comparisons,'reproduces_actual_base_action':base['decision']['action']==frozen['actual_decision']['action'],
        'interpretation':'同一 PMM 代码的局部条件干预；外部模型理解/效用评估和门控固定，不重发消息，不写回人格或情绪。数值差异不等于心理学效度或真实大模型因果验证。'}

def from_turn(engine,body):
    rows=engine.store.rows("SELECT payload FROM events WHERE kind='turn' AND json_extract(payload,'$.turn_id')=? LIMIT 1",(body.get('turn_id'),))
    if not rows:raise ValueError('找不到已完成回合')
    trace=json.loads(rows[0]['payload'])
    return compare(trace.get('decision_inputs'),body.get('feature_id','hexaco.a.patience'),body.get('low',.2),body.get('high',.8))
