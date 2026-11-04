"""Equations A/B: masked construct-specific low-rank reaction network.

JSON checkpoints and NumPy inference keep Legacy startup independent of Torch.
Torch uses the identical parameter names and algebra for genuine training.
No stochastic state draw, observed label, or trait update is produced here.
"""
from __future__ import annotations
import copy
import numpy as np
from .registry import digest
from .pmm_contracts import BLOCK_IDS, BLOCK_CONTRACT, validate_blocks, TraitInference, result
from .psychology import ACTIONS, STATE_KEYS

FORMAT = 'trait-dynamics/2.8.1'
DH, DQ, DR, DM, DA, RANK = 16, 11, 8, 6, 8, 4
SHAPES = {'A_l': (DH,RANK), 'A_r': (RANK,DH), 'A_diag': (DH,),
          'B': (DH,DQ), 'R': (DH,DR), 'M': (DH,DM), 'bias': (DH,),
          'Lambda': (25,), 'H_H': (25,DH), 'state_bias': (25,),
          'action': (len(ACTIONS),DH+DA+19+DR), 'action_bias': (len(ACTIONS),)}
for _b, _ids in BLOCK_IDS.items():
    _n=len(_ids)
    for _k in ('enc_value','enc_mask','enc_uncertainty','enc_missing','enc_unknown_u'):
        SHAPES[f'{_b}_{_k}']=(_n,)
    for _k,_shape in {'W_l':(DH,RANK),'W_r':(RANK,_n),'C_l':(DH,RANK),
                      'C_r':(RANK,_n),'U_l':(_n,RANK),'U_r':(RANK,DQ)}.items():
        SHAPES[f'{_b}_{_k}']=_shape
SHAPES['affect_context_h']=(DH,16)  # extra columns of Bq; old B columns stay intact
ADAPTER_SHAPES={'a_left':(DH,RANK),'a_right':(RANK,DH),'a_bias':(DH,)}

def checked_array(value, shape, name):
    a=np.asarray(value,dtype=np.float64)
    if a.shape!=shape or not np.isfinite(a).all() or np.abs(a).max(initial=0)>1e4:
        raise ValueError('Invalid finite shape/range: '+name)
    return a

def initial_checkpoint(subject_id, seed=280, *, include_affect_context=True):
    if not isinstance(subject_id,str) or not subject_id:raise ValueError('Adapter subject required')
    rng=np.random.default_rng(seed)
    p={k:rng.normal(0,.08,s).tolist() for k,s in SHAPES.items() if include_affect_context or k!='affect_context_h'}
    p['A_diag']=[.25]*DH;p['bias']=[0.]*DH;p['state_bias']=[0.]*25
    p['Lambda']=[0.]*25  # latent scale link disabled until independently fitted
    p['action_bias']=[0.]*len(ACTIONS)
    for b,ids in BLOCK_IDS.items():
        p[b+'_enc_value']=[1.]*len(ids)
    a={k:rng.normal(0,.02,s).tolist() for k,s in ADAPTER_SHAPES.items()}
    a['a_bias']=[0.]*DH
    out={'format':FORMAT,'subject_id':subject_id,'contract':copy.deepcopy(BLOCK_CONTRACT),
         'revision':0,'steps':0,'parameters':p,'adapter':a,'temperature':1.,
         'scale':{'kind':'engineering_latent','measurement_protocol':None,'calibrated':False},
         'process_covariance':(np.eye(25)*.01).tolist(),
         'calibration':{'status':'uncalibrated','report_id':None},
         'origin':{'kind':'seeded_engineering_initialization','seed':seed},'training':None}
    return seal(out)

def seal(checkpoint):
    out=copy.deepcopy(checkpoint);out.pop('sha256',None);out['sha256']=digest(out);return out

def validate_checkpoint(checkpoint, subject_id):
    if not isinstance(checkpoint,dict) or checkpoint.get('format')!=FORMAT or checkpoint.get('subject_id')!=subject_id:
        raise ValueError('Network format or adapter subject mismatch')
    if checkpoint.get('contract')!=BLOCK_CONTRACT or seal(checkpoint)['sha256']!=checkpoint.get('sha256'):
        raise ValueError('Network contract/digest mismatch')
    for k in ('revision','steps'):
        if type(checkpoint.get(k)) is not int or checkpoint[k]<0:raise ValueError('Invalid network revision')
    for group,shapes in (('parameters',SHAPES),('adapter',ADAPTER_SHAPES)):
        allowed=[set(shapes)]
        if group=='parameters':allowed.append(set(shapes)-{'affect_context_h'})
        if set(checkpoint.get(group,{})) not in allowed:raise ValueError('Network parameters incomplete')
        for k,shape in shapes.items():
            if k in checkpoint[group]:checked_array(checkpoint[group][k],shape,k)
    from .pmm_contracts import finite
    finite(checkpoint.get('temperature',1.),'action calibration temperature',.25,8.)
    c=checked_array(checkpoint.get('process_covariance'),(25,25),'process covariance')
    if not np.allclose(c,c.T,atol=1e-10) or np.linalg.eigvalsh(c).min() < -1e-10:
        raise ValueError('Invalid process covariance')
    scale=checkpoint.get('scale',{})
    if scale.get('kind') not in ('engineering_latent','linear_validated') or type(scale.get('calibrated')) is not bool:
        raise ValueError('Invalid latent scale')
    if scale['kind']=='linear_validated':
        if not scale.get('calibrated') or not scale.get('measurement_protocol') or not scale.get('validation_ref'):
            raise ValueError('Missing scale calibration evidence')
        checked_array(scale.get('slope'),(25,),'scale slope');checked_array(scale.get('intercept'),(25,),'scale intercept')
        mask=checked_array(scale.get('mask'),(25,),'scale mask')
        if not np.isin(mask,[0.,1.]).all() or not mask.any():raise ValueError('Explicit calibrated facet mask required')
        ids=[k for k,m in zip(BLOCK_IDS['H'],mask) if m]
        if ids!=scale.get('construct_ids') or not scale.get('protocol_id'):raise ValueError('Calibrated facet identity mismatch')
        from .trait_estimator import covariance
        covariance(scale.get('measurement_covariance'),len(ids),'measurement covariance')
        if any(abs(s)<1e-6 for s,m in zip(scale['slope'],mask) if m):raise ValueError('Singular latent link')
    elif scale.get('calibrated'):raise ValueError('Engineering scale is not a measurement')
    return checkpoint

def bind_measurement_scale(checkpoint,protocol):
    """Bind only identified facets; caller must verify original protocol evidence.

    This creates an untrained candidate, never a behavioral publication.
    """
    validate_checkpoint(checkpoint,checkpoint['subject_id'])
    if not protocol.get('validated') or protocol.get('engineering_only'):raise ValueError('Independent validated measurement scale required')
    ids=protocol['construct_ids'];n=len(ids)
    if not ids or len(set(ids))!=n or any(k not in BLOCK_IDS['H'] for k in ids):raise ValueError('HEXACO scale identity required')
    if len(protocol['slope'])!=n or len(protocol['intercept'])!=n:raise ValueError('Scale shape mismatch')
    ordered=[k for k in BLOCK_IDS['H'] if k in ids];indices=[ids.index(k) for k in ordered]
    slope=[0.]*25;intercept=[0.]*25;mask=[0]*25
    for k,s,b in zip(ids,protocol['slope'],protocol['intercept']):
        j=BLOCK_IDS['H'].index(k);slope[j]=s;intercept[j]=b;mask[j]=1
    measurement=np.asarray(protocol['measurement_covariance'])[np.ix_(indices,indices)].tolist()
    out=copy.deepcopy(checkpoint)
    out['scale']={'kind':'linear_validated','calibrated':True,'measurement_protocol':protocol['scale_id'],
                  'protocol_id':protocol['id'],'validation_ref':protocol['id'],'construct_ids':ordered,'mask':mask,
                  'slope':slope,'intercept':intercept,'measurement_covariance':measurement}
    out['revision']+=1;out['training']=None;out['calibration']={'status':'uncalibrated','report_id':None}
    out['origin']={'kind':'independent_scale_binding','parent_sha256':checkpoint['sha256'],'protocol_id':protocol['id']}
    out=seal(out);validate_checkpoint(out,out['subject_id']);return out

def pack_blocks(blocks):
    validate_blocks(blocks);out={}
    for b,row in blocks.items():
        m=np.asarray(row['mask'],dtype=float)
        values=np.asarray([0. if v is None else v for v in row['values']],dtype=float)
        if b=='V' and m.sum():values=np.where(m,values-values.sum()/m.sum(),0.)
        u=np.asarray([0. if v is None else v for v in row['uncertainty']],dtype=float)
        uk=np.asarray([int(v is not None) for v in row['uncertainty']],dtype=float)
        out[b]={'value':values,'mask':m,'u':u,'uk':uk}
    return out

def checked_inputs(inputs):
    if not isinstance(inputs,dict):raise ValueError('Network inputs required')
    out={k:checked_array(inputs.get(k),shape,k) for k,shape in
         {'q':(DQ,),'r':(DR,),'m':(DM,),'affect':(DA,),'h_prev':(DH,)}.items()}
    out['affect_context']=checked_array(inputs.get('affect_context',[0.]*16),(16,),'affect_context')
    out['blocks']=pack_blocks(inputs['blocks']);return out

def algebra(p,a,x,xp):
    """Same operations in NumPy and Torch. Equations A and B, no implicit broadcast."""
    z={}
    for b,v in x['blocks'].items():
        # Each coordinate retains its original construct ID. Missingness has its
        # own trainable encoding, distinct from a true observed numeric zero.
        z[b]=(p[b+'_enc_value']*v['value']*v['mask'] + p[b+'_enc_mask']*v['mask']
              + p[b+'_enc_uncertainty']*v['u']*v['mask']*v['uk']
              + p[b+'_enc_missing']*(1-v['mask'])
              + p[b+'_enc_unknown_u']*v['mask']*(1-v['uk']))
    # Equation A. Rank-four core and subject-bound recurrence adapter.
    recurrence=p['A_l']@(p['A_r']@x['h_prev'])+p['A_diag']*x['h_prev']
    adapter=a['a_left']@(a['a_right']@x['h_prev'])+a['a_bias']
    pre=recurrence+adapter+p['B']@x['q']+p['R']@x['r']+p['M']@x['m']+p['bias']
    if 'affect_context_h' in p:pre=pre+p['affect_context_h']@x['affect_context']
    paths={}
    for b,zb in z.items():
        direct=p[b+'_W_l']@(p[b+'_W_r']@zb)
        conditioned=p[b+'_C_l']@(p[b+'_C_r']@(zb*(p[b+'_U_l']@(p[b+'_U_r']@x['q']))))
        paths[b]=direct+conditioned;pre=pre+paths[b]
    h=xp.tanh(pre)
    # Equation B. An explicit scale layer prepares latent_H before this function.
    state=p['Lambda']*x['latent_H']+p['H_H']@h+p['state_bias']
    head=xp.concatenate((h,x['affect'],z['V'],x['r']))
    logits=(p['action']@head+p['action_bias'])/x.get('temperature',1.)
    ex=xp.exp(logits-xp.max(logits));prob=ex/xp.sum(ex)
    return {'h':h,'state':state,'action':prob,'logits':logits,'paths':paths,'encoded':z}

def latent_H(checkpoint,x):
    h=x['blocks']['H'];scale=checkpoint['scale']
    # Packed zero is merely a masked placeholder; output explicitly reports
    # which latent traits were observed. This never creates questionnaire scores.
    if scale['kind']=='linear_validated':
        return (np.asarray(scale['slope'])*h['value']+np.asarray(scale['intercept']))*h['mask']*np.asarray(scale['mask'])
    return h['value']*h['mask']

class TraitDynamics:
    version=FORMAT
    def __init__(self, checkpoint, subject_id):
        self.checkpoint=copy.deepcopy(validate_checkpoint(checkpoint,subject_id));self.subject_id=subject_id
        self.p={k:np.asarray(v,dtype=float) for k,v in checkpoint['parameters'].items()}
        self.a={k:np.asarray(v,dtype=float) for k,v in checkpoint['adapter'].items()}
    def forward(self,inputs):
        x=checked_inputs(inputs);x['latent_H']=latent_H(self.checkpoint,x);x['temperature']=self.checkpoint.get('temperature',1.)
        y=algebra(self.p,self.a,x,np)
        if any(not np.isfinite(y[k]).all() for k in ('h','state','action')):raise ValueError('Nonfinite neural prediction')
        return {'latent':y['h'].tolist(),'state_prediction':y['state'].tolist(),
                'action_probabilities':dict(zip(ACTIONS,y['action'].tolist())),
                'construct_paths':{b:v.tolist() for b,v in y['paths'].items()},
                'encoded_blocks':{b:v.tolist() for b,v in y['encoded'].items()},
                'prior_mask':inputs['blocks']['H']['mask'],
                'process_covariance':copy.deepcopy(self.checkpoint['process_covariance']),
                'measurement_uncertainty':({'construct_ids':self.checkpoint['scale']['construct_ids'],'covariance':self.checkpoint['scale']['measurement_covariance']} if self.checkpoint['scale']['calibrated'] else None),
                'calibrated_state_mask':copy.deepcopy(self.checkpoint['scale'].get('mask',[0]*25)),
                'scale':copy.deepcopy(self.checkpoint['scale']),
                'prediction_is_observation':False,'checkpoint_sha256':self.checkpoint['sha256']}

def torch_model(checkpoint,subject_id):
    """Lazily import the optional training dependency; no pickle deserialization."""
    import torch
    validate_checkpoint(checkpoint,subject_id)
    class ReactionNetwork(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.core=torch.nn.ParameterDict({k:torch.nn.Parameter(torch.tensor(v,dtype=torch.float64)) for k,v in checkpoint['parameters'].items()})
            if 'affect_context_h' not in self.core:self.core['affect_context_h']=torch.nn.Parameter(torch.zeros((DH,16),dtype=torch.float64))
            self.adapter=torch.nn.ParameterDict({k:torch.nn.Parameter(torch.tensor(v,dtype=torch.float64)) for k,v in checkpoint['adapter'].items()})
        def forward(self,inputs):
            x=checked_inputs(inputs);x['latent_H']=latent_H(checkpoint,x);x['temperature']=checkpoint.get('temperature',1.)
            def tensor(v):
                return {k:tensor(w) for k,w in v.items()} if isinstance(v,dict) else torch.as_tensor(v,dtype=torch.float64)
            return algebra(self.core,self.adapter,tensor(x),torch)
        def checkpoint(self,steps=0):
            out=copy.deepcopy(checkpoint)
            out['parameters']={k:v.detach().cpu().tolist() for k,v in self.core.items()}
            out['adapter']={k:v.detach().cpu().tolist() for k,v in self.adapter.items()}
            out['steps']+=steps;out['revision']+=1
            out['calibration']={'status':'uncalibrated','report_id':None}
            return seal(out)
    return ReactionNetwork()

def runtime_inputs(blocks,reasoner,affect,relationship,memory,h_prev=None):
    rp=reasoner['payload'];ok=reasoner['status']=='ok';q=[0.]*DQ
    if ok:
        q=[float(rp['appraisal'][k]) for k in STATE_KEYS]+[float(rp['action_probabilities'][k]) for k in ACTIONS]+[1.]
    d=relationship['payload']['dyad'];known=[d.get(k) for k in ('trust','familiarity','affiliation')]
    r=[0. if v is None else float(v) for v in known]+[min(1.,d.get('interactions',0)/100.)]+[float(v is not None) for v in known]+[min(1.,len(d.get('schemata',[]))/20.)]
    rows=memory['payload']['records'];conf=[float(v['confidence']) for v in rows if v.get('confidence') is not None]
    m=[min(len(rows)/16.,1.),sum(conf)/max(1,len(conf)),float(bool(conf)),
       sum(float(v.get('relevance',0)) for v in rows)/max(1,len(rows)),
       sum(v.get('kind')=='hypothesis' for v in rows)/max(1,len(rows)),float(bool(rows))]
    em=affect['payload']['state']['emotion'];vs=[em.get(k) for k in STATE_KEYS]
    av=[0. if v is None else float(v) for v in vs]+[float(v is not None) for v in vs]
    v2=affect['payload'].get('dynamics_v2');context=[0.]*16
    if v2:
        values=[v2['affect_observed'][k] for k in ('valence','arousal','dominance','stress','engagement')]+[v2['mood_observed'][k] for k in ('valence','arousal','dominance')]
        context=[0. if v is None else float(v) for v in values]+[float(v is not None) for v in values]
    return {'blocks':copy.deepcopy(blocks),'q':q,'r':r,'m':m,'affect':av,'affect_context':context,'h_prev':list(h_prev) if h_prev is not None else [0.]*DH}

class NeuralDynamicsPort:
    version=FORMAT
    def __init__(self,engine):self.engine=engine
    def predict(self,ctx,*,blocks,reasoner,affect,relationship,memory,**unused):
        from .pmm_trainer import published_gate
        catalog=self.engine.store.meta('pmm28_models') or {}
        checkpoint=catalog.get('versions',{}).get(catalog.get('published'))
        eligible,gate=published_gate(self.engine,catalog)
        if checkpoint is None:checkpoint=initial_checkpoint(ctx.subject_id)
        try:model=TraitDynamics(checkpoint,ctx.subject_id)
        except (ValueError,KeyError,TypeError):
            checkpoint=initial_checkpoint(ctx.subject_id);model=TraitDynamics(checkpoint,ctx.subject_id)
            eligible=False;gate='invalid_network_checkpoint_using_uncalibrated_shadow'
        previous=None
        rows=self.engine.store.rows("SELECT payload FROM events WHERE kind='turn' ORDER BY rowid DESC LIMIT 100")
        import json
        for row in rows:
            trace=json.loads(row['payload']).get('pmm28',{})
            if trace.get('scope')==ctx.scope and trace.get('person_id')==ctx.person_id and trace.get('subject_id')==ctx.subject_id and (not unused.get('session_id') or trace.get('session_id')==unused['session_id']):
                old=trace.get('components',{}).get('neural',{}).get('payload',{})
                if old.get('checkpoint_sha256')==checkpoint['sha256']:previous=old.get('latent')
                break
        inputs=runtime_inputs(blocks,reasoner,affect,relationship,memory,previous)
        output=model.forward(inputs)
        output.update(blocks=blocks,inputs=inputs,calibration='held_out_behavior_validated' if eligible else 'uncalibrated',formal_eligible=eligible,release_gate=gate,
                      q_provenance='independent_api_grounded_appraisal' if reasoner['status']=='ok' else 'missing_internal_api',
                      previous_state_scope={'subject_id':ctx.subject_id,'scope':ctx.scope,'person_id':ctx.person_id},
                      value_normalization='observed_relative_mean; mask retained; no normed questionnaire score')
        return result(TraitInference,ctx,self.version,output,status='ok' if eligible else 'uncalibrated',
                      execution='actual_numpy_equations_A_B',kind='prediction_not_observation')
