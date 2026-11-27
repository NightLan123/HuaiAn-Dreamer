"""Frozen-condition six-component ablations. No API calls, writes or sends."""
from __future__ import annotations
import copy,json
import numpy as np
from .trait_dynamics import TraitDynamics,initial_checkpoint
from .pmm_contracts import BLOCK_IDS
from .registry import digest
from .psychology import ACTIONS

def ablate(checkpoint,subject_id,inputs):
    model=TraitDynamics(checkpoint,subject_id);baseline=model.forward(inputs);rows=[]
    for component in ('api','neural','affect','memory','relationship','value'):
        x=copy.deepcopy(inputs)
        if component=='api':x['q']=[0.]*len(x['q'])
        elif component=='affect':
            x['affect']=[0.]*len(x['affect'])
            if 'affect_context' in x:x['affect_context']=[0.]*len(x['affect_context'])
        elif component=='memory':x['m']=[0.]*len(x['m'])
        elif component=='relationship':x['r']=[0.]*len(x['r'])
        elif component=='value':
            v=x['blocks']['V'];n=len(v['ids']);v.update(values=[None]*n,mask=[0]*n,uncertainty=[None]*n,sources=[{'source_type':'ablation_missing','evidence_refs':[]} for _ in range(n)])
        if component=='neural':
            rows.append({'component':component,'executed_neural':False,'output':None,'prediction_delta':None,
                         'meaning':'remove_neural_contribution_use_existing_policy','no_difference_claimed':True});continue
        output=model.forward(x);delta=np.asarray(list(output['action_probabilities'].values()))-list(baseline['action_probabilities'].values())
        rows.append({'component':component,'executed_neural':True,'output':output,
                     'prediction_delta':delta.tolist(),'max_abs_delta':float(np.max(np.abs(delta))),
                     'no_observable_difference':bool(np.max(np.abs(delta))<1e-10),
                     'latent_l2_delta':float(np.linalg.norm(np.asarray(output['latent'])-baseline['latent']))})
    return {'schema':'pmm-ablation/2.8','checkpoint_sha256':checkpoint['sha256'],'input_digest':digest(inputs),
            'baseline':baseline,'cases':rows,'measurement':'engineering_prediction_only',
            'interpretation':'fixed inputs; recurrent history held fixed; not a live provider trial or psychological causal effect',
            'persistent_writes':0,'external_requests':0,'external_sends':0}

def intervention(checkpoint,subject_id,inputs,feature_id,before,after):
    if feature_id not in BLOCK_IDS['H']:raise ValueError('Fixed-condition intervention requires one HEXACO facet')
    for v in (before,after):
        if type(v) not in (int,float) or not np.isfinite(v) or not 0<=v<=1:raise ValueError('Intervention outside canonical range')
    variants=[];index=BLOCK_IDS['H'].index(feature_id);model=TraitDynamics(checkpoint,subject_id)
    for value in (before,after):
        x=copy.deepcopy(inputs);h=x['blocks']['H'];h['values'][index]=value;h['mask'][index]=1;h['uncertainty'][index]=0.
        h['sources'][index]={'source_type':'controlled_intervention_not_measurement','evidence_refs':[]}
        variants.append(model.forward(x))
    delta=np.asarray(variants[1]['state_prediction'])-variants[0]['state_prediction']
    return {'feature_id':feature_id,'before':before,'after':after,'outputs':variants,'state_delta':delta.tolist(),
            'max_abs_delta':float(np.max(np.abs(delta))),'no_observable_difference':bool(np.max(np.abs(delta))<1e-10),
            'direction_hypothesis':'not_preregistered_no_human_direction_claim','persistent_writes':0}

def from_turn(engine,body):
    owner=engine.profile()['id']
    if body.get('subject_id')!=owner:raise ValueError('当前主体已变化')
    rows=engine.store.rows("SELECT payload FROM events WHERE kind='turn' AND json_extract(payload,'$.turn_id')=? LIMIT 1",(body.get('turn_id'),))
    if not rows:raise ValueError('没有此已提交回合')
    event=json.loads(rows[0]['payload']);trace=event.get('pmm28',{});neural=trace.get('components',{}).get('neural',{}).get('payload',{})
    if not neural.get('inputs'):raise ValueError('该回合没有可复算的新版输入')
    key=neural['checkpoint_sha256'];catalog=engine.store.meta('pmm28_models') or {};ck=catalog.get('versions',{}).get(key)
    if ck is None:
        ck=initial_checkpoint(owner)
        if ck['sha256']!=key:ck=initial_checkpoint(owner,include_affect_context=False)
        if ck['sha256']!=key:raise ValueError('原回合检查点缺失，不能以当前权重替代')
    output=ablate(ck,owner,neural['inputs'])
    if body.get('feature_id'):output['intervention']=intervention(ck,owner,neural['inputs'],body['feature_id'],body.get('before',.2),body.get('after',.8))
    output.update(turn_id=trace['turn_id'],scope=trace['scope'],formal_calibration=neural['calibration'],
                  actual_policy_comparison=trace.get('policy_comparison'),actual_decision=trace.get('official_decision'))
    return output


def expressive_from_turn(engine, body):
    """Inspect four frozen ED links. Never regenerate language or update state."""
    from .policy import choose
    from .expression_plan import decide_expression
    owner=engine.profile()['id']
    if body.get('persona_id')!=owner:raise ValueError('当前主体已变化')
    rows=engine.store.rows("SELECT payload FROM events WHERE kind IN ('turn','expression_partial') AND json_extract(payload,'$.turn_id')=? LIMIT 1",(body.get('turn_id'),))
    if not rows:raise ValueError('此回合没有已提交记录')
    trace=json.loads(rows[0]['payload']);f=copy.deepcopy(trace.get('decision_inputs'))
    if not f or f.get('input_digest')!=digest({k:v for k,v in f.items() if k!='input_digest'}):raise ValueError('缺少完整固定条件，不能以当前状态替代')
    drive=copy.deepcopy(trace.get('expressive_drive') or {})
    if not drive:raise ValueError('此回合未保留表达欲条件')
    u=copy.deepcopy(f['understanding']);base=choose(u,f['profile'],f['views'],f['assessment']['views'],f['decoded'],f['memories'],f['event']['text'])
    without=copy.deepcopy(u);without.pop('expressive_drive_policy',None)
    ablated=choose(without,f['profile'],f['views'],f['assessment']['views'],f['decoded'],f['memories'],f['event']['text'])
    plan=trace.get('interaction_plan') or {};context=trace.get('turn_context') or {}
    def expression(enabled):
        candidate=copy.deepcopy(trace['decision']);language=copy.deepcopy(trace.get('understanding') or {})
        if not enabled:language.pop('expressive_drive_policy',None);candidate.pop('expressive_drive',None)
        return decide_expression(f['event']['text'],language,candidate,context,f['relationship'],plan.get('trait_ref'),plan.get('affect_ref'),plan.get('pragmatic_condition') or {},expressive_drive=drive if enabled else None)
    turn=context.get('cognitive_decision') or {};turn_scores=turn.get('scores');terms=(turn.get('expressive_drive') or {}).get('score_deltas')
    turn_case={'status':'available','saved_scores':turn_scores,'without_ed_scores':{k:v-terms.get(k,0) for k,v in turn_scores.items()},
               'note':'Only the saved additive link is removed; no new permission or response is inferred.'} if turn_scores and terms else {'status':'unavailable','reason':'turn_score_snapshot_missing'}
    proactive=drive.get('proactive_eligible')
    return {'schema':'expressive-drive-link-experiment/1','turn_id':trace['turn_id'],'input_digest':f['input_digest'],
        'fixed':{'time':f['at'],'profile':True,'emotion':True,'scope':f['event']['scope'],'language_model_outputs':True,'permissions':True},
        'turn_taking':turn_case,
        'action':{'baseline':base,'without_ed_link':ablated,'baseline_reproduces_actual':base['action']==trace['decision']['action']},
        'expression':{'baseline':expression(True),'without_ed_link':expression(False),'stage':'initial_strategy_before_joint_refinement'},
        'proactive':{'status':'available','saved_eligible':proactive,'with_ed_initiation_disabled':False,'permission_granted':False} if proactive is not None else {'status':'unavailable','reason':'this_turn_has_no_proactive_snapshot'},
        'model_calls':0,'sent':False,'state_written':False,
        'interpretation':'Local link interventions under frozen evidence, not a full language-generation trial or validated psychological causality.'}
