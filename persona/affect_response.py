"""E-A/D/F parameter networks, portable NumPy weights and masked evidence."""
from __future__ import annotations
import copy
import numpy as np
from .registry import APPRAISAL_IDS,digest
from .affect import AXES,LABELS,default_parameters
from .affect_dynamics_v2 import inverse
from .pmm_contracts import BLOCK_IDS,construct_blocks,validate_blocks

FORMAT='affect-network/2.8.1'
THETA_SIZE=2*(len(BLOCK_IDS['H'])+len(BLOCK_IDS['D']))
Q_SIZE=2*len(APPRAISAL_IDS)
J_SIZE=Q_SIZE+2*sum(len(BLOCK_IDS[k]) for k in ('H','V','D'))+6+3+5
REG_SIZE=5+Q_SIZE+2*len(BLOCK_IDS['D'])+2
SHAPES={**{k+'_W':(8,THETA_SIZE) for k in ('mu','kappa','sigma')},**{k+'_b':(8,) for k in ('mu','kappa','sigma')},
        'coupling':(3,),'jump_W':(5,J_SIZE),'jump_b':(5,),
        'label_W':(len(LABELS),5+Q_SIZE+16),'label_b':(len(LABELS),),
        'reg_W':(3,REG_SIZE),'reg_b':(3,)}

def seal(value):
    out=copy.deepcopy(value);out.pop('sha256',None);out['sha256']=digest(out);return out

def initial_model(subject_id,legacy=None):
    legacy=legacy or default_parameters(subject_id);p={k:np.zeros(s).tolist() for k,s in SHAPES.items()}
    base=dict(legacy['baseline']);base['dominance']=base.get('dominance') if base.get('dominance') is not None else .5
    mu=inverse(base)[0];p['mu_b']=mu+mu[:3]
    k=np.r_[[1/legacy['emotion_tau_seconds']]*5,[1/legacy['mood_tau_seconds']]*3]
    p['kappa_b']=np.log(np.expm1(k-1e-12)).tolist();p['sigma_b']=np.log(np.expm1([.002]*5+[.0002]*3)).tolist()
    p['coupling']=[1/legacy['mood_tau_seconds']]*3
    # Transparent migration seed, not a learned trait-to-emotion law. All
    # personality-conditioned matrices start at zero; training learns them.
    w=np.zeros(SHAPES['jump_W']);ids=list(APPRAISAL_IDS)
    for axis,key,gain in [(0,'goal_conduciveness',.25),(1,'urgency',.2),(2,'control',.2),(3,'goal_conduciveness',-.15),(4,'goal_relevance',.2)]:
        w[axis,ids.index('affect.appraisal.'+key)]=gain
    p['jump_W']=w.tolist();p['reg_b']=[1.,0.,0.]
    return seal({'format':FORMAT,'subject_id':subject_id,'steps':0,'parameters':p,'kappa_n':[0.]*8,'turn_term_validated':False,
        'calibration':{'status':'unvalidated','labels':[False]*len(LABELS),'components':{}},
        'origin':{'kind':'explicit_migration_engineering_seed','legacy_parameters':copy.deepcopy(legacy),'trait_coefficients':'zero_until_trained'},'training':None})

def validate_model(model,subject_id):
    if not isinstance(model,dict) or model.get('format')!=FORMAT or model.get('subject_id')!=subject_id or model.get('sha256')!=seal(model)['sha256']:raise ValueError('情绪模型主体/格式/摘要错误')
    if set(model.get('parameters',{}))!=set(SHAPES):raise ValueError('情绪模型参数不完整')
    for k,shape in SHAPES.items():
        a=np.asarray(model['parameters'][k],float)
        if a.shape!=shape or not np.isfinite(a).all() or np.abs(a).max(initial=0)>1e6:raise ValueError('情绪模型形状/有限性错误: '+k)
    if type(model.get('steps')) is not int or model['steps']<0:raise ValueError('训练步数无效')
    labels=model.get('calibration',{}).get('labels')
    if not isinstance(labels,list) or len(labels)!=len(LABELS) or any(type(x) is not bool for x in labels):raise ValueError('情绪标签标定掩码错误')
    n=np.asarray(model.get('kappa_n'),float)
    if n.shape!=(8,) or not np.isfinite(n).all() or (n<0).any() or (n.any() and not model.get('turn_term_validated')):raise ValueError('轮次参数缺少独立验证')
    return model

def masked(values):
    return np.array([0. if v is None else (2*v-1) for v in values]+[float(v is not None) for v in values])

def trait_inputs(blocks,keys=('H','D')):
    validate_blocks(blocks)
    return np.concatenate([masked(blocks[k]['values']) for k in keys])

def appraisal_packet(checks,event,evidence_ids=(),quote=None,reappraisal=None):
    if not isinstance(checks,dict) or set(checks)-set(APPRAISAL_IDS):raise ValueError('评价字段未注册')
    if any(v is not None and (type(v) not in (int,float) or not np.isfinite(v) or not 0<=v<=1) for v in checks.values()):raise ValueError('评价必须为 0..1 或未知')
    if any(v is not None for v in checks.values()) and (not isinstance(quote,str) or not quote.strip() or quote not in event['text']):raise ValueError('评价缺少当前事件原文')
    return {'checks':{k:checks.get(k) for k in APPRAISAL_IDS},'mask':{k:checks.get(k) is not None for k in APPRAISAL_IDS},
        'event_facts':{'event_id':event['id'],'text':event['text'],'scope':event['scope'],'person':event['person']},
        'evidence_ids':list(evidence_ids),'quote':quote,'kind':'model_appraisal_not_fact','reappraisal_candidate':copy.deepcopy(reappraisal)}

def parameters(model,blocks):
    p={k:np.asarray(v,float) for k,v in model['parameters'].items()};x=trait_inputs(blocks)
    return {'mu':(p['mu_W']@x+p['mu_b']).tolist(),'kappa':(np.logaddexp(0,p['kappa_W']@x+p['kappa_b'])+1e-12).tolist(),
        'sigma':np.logaddexp(0,p['sigma_W']@x+p['sigma_b']).tolist(),'coupling':p['coupling'].tolist(),
        'kappa_n':model['kappa_n'],'turn_term_validated':model['turn_term_validated'],'source_version':model['sha256'],'calibration_status':model['calibration']['status']}

def jump_inputs(packet,blocks,relation,mood,fast):
    q=masked([packet['checks'][k] for k in APPRAISAL_IDS]);r=masked([relation.get(k) for k in ('trust','familiarity','affection')])
    return np.r_[q,trait_inputs(blocks,('H','V','D')),r,mood,fast]

def label_readout(model,after,packet,h=None):
    p=model['parameters'];q=masked([packet['checks'][k] for k in APPRAISAL_IDS]);h=np.zeros(16) if h is None else np.asarray(h,float)
    if h.shape!=(16,) or not np.isfinite(h).all():raise ValueError('标签心理状态 h 维度无效')
    logits=np.asarray(p['label_W'])@np.r_[after,q,h]+np.asarray(p['label_b']);scores=np.exp(-np.logaddexp(0.,-logits))
    valid=model['calibration']['labels'];labels={k:float(v) if ok else None for k,v,ok in zip(LABELS,scores,valid)}
    return {'emotion_labels':labels,
        'label_activations':dict(zip(LABELS,map(float,scores))),'label_calibration_mask':dict(zip(LABELS,valid)),
        'label_status':'calibrated_partial' if any(valid) else 'uncalibrated','h_used':h.tolist()}

def response(model,packet,blocks,relation,mood,fast,h=None):
    p=model['parameters'];x=jump_inputs(packet,blocks,relation,mood,fast)
    supported=any(packet['mask'].values())
    jump=np.asarray(p['jump_W'])@x+np.asarray(p['jump_b']) if supported else np.zeros(5)
    after=np.asarray(fast)+jump
    return after,{'jump':jump.tolist(),'jump_applied':supported,'jump_input':x.tolist(),**label_readout(model,after,packet,h),'appraisal':copy.deepcopy(packet)}
