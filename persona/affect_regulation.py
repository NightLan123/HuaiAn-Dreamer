"""E-G: policy, auditable reappraisal, and expression-only suppression."""
from __future__ import annotations
import copy
import numpy as np
from .registry import APPRAISAL_IDS,digest
from .affect_response import masked,trait_inputs,appraisal_packet

STRATEGIES=('none','reappraisal','suppression')

def choose(model,fast,packet,blocks,goal,rng,requested=None):
    q=masked([packet['checks'][k] for k in APPRAISAL_IDS]);d=trait_inputs(blocks,('D',))
    x=np.r_[fast,q,d,[goal.get('relevance',0.),goal.get('urgency',0.)]]
    logits=np.asarray(model['parameters']['reg_W'])@x+np.asarray(model['parameters']['reg_b']);weights=np.exp(logits-logits.max());weights/=weights.sum()
    if requested is not None and requested not in STRATEGIES:raise ValueError('未知情绪调节策略')
    selected=requested or STRATEGIES[int(rng.choice(3,p=weights))]
    candidate=packet.get('reappraisal_candidate');adopted=False;effective=copy.deepcopy(packet);reason='not_requested'
    if selected=='reappraisal':
        reason='no_grounded_reappraisal_candidate'
        if candidate is not None:
            if not isinstance(candidate,dict) or candidate.get('event_facts_sha256')!=digest(packet['event_facts']):raise ValueError('重评候选不能修改原始事实')
            effective=appraisal_packet(candidate.get('checks',{}),{'id':packet['event_facts']['event_id'],**packet['event_facts']},packet['evidence_ids'],packet['quote'])
            adopted=True;reason='grounded_candidate_adopted_jump_recomputed'
    return effective,{'strategy':selected,'probabilities':dict(zip(STRATEGIES,map(float,weights))),
        'policy_calibration':model['calibration'].get('components',{}).get('regulation','unvalidated'),
        'requested_by':'explicit_test_or_owner' if requested else 'learned_policy_sample','reappraisal_applied':adopted,
        'candidate':copy.deepcopy(candidate),'reason':reason,'before_checks':packet['checks'],'after_checks':effective['checks'],
        'event_facts_sha256':digest(packet['event_facts']),'executed':selected=='suppression' or adopted,
        'effect_evidence':None,'outcome':'not_observed','policy_input':x.tolist()}

def expression(fast_observed,regulation,blocks):
    ids=blocks['D']['ids'];values=blocks['D']['values']
    negative=(fast_observed.get('valence') or 0)<0
    key='beq.negative_expressivity' if negative else 'beq.positive_expressivity'
    v=values[ids.index(key)];habit=.5 if v is None else v
    gain=.35 if regulation['strategy']=='suppression' else 1.
    return {'strategy':regulation['strategy'],'expression_multiplier':gain,'intensity':float(gain*(.25+.5*habit)*(.35+.65*fast_observed['arousal'])),
        'internal_state_changed_by_suppression':False,'habit_source':key,'habit_known':v is not None,'effect_calibration':'unvalidated_expression_control','status':'planned'}
