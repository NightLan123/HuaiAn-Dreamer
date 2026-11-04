"""Equation C, independent data audit, candidate-only optimization and calibration.

Nothing here changes the published model or the canonical personality. A review
attests traceable annotation, not scientific truth. Synthetic data stays marked.
"""
from __future__ import annotations
import copy, math
import numpy as np
from .registry import digest
from .pmm_contracts import finite
from .psychology import ACTIONS
from .trait_dynamics import (FORMAT,SHAPES,ADAPTER_SHAPES,initial_checkpoint,validate_checkpoint,
    seal,torch_model,TraitDynamics,checked_inputs)

VERSION='reaction-training/2.8.1'
SAMPLE_SCHEMA='pmm-supervision/2.8'
ALLOWED_SOURCES=('independent_questionnaire','independent_observer','human_choice','verified_outcome','controlled_fixture')

def sample_key(row):return digest([row['subject_id'],row['scope'],row['event_id'],row['task']])

def validate_sample(row):
    if not isinstance(row,dict) or row.get('schema')!=SAMPLE_SCHEMA:raise ValueError('Supervision schema mismatch')
    for key in ('subject_id','owner_id','scope','event_id','protocol_id','reviewer'):
        if not isinstance(row.get(key),str) or not row[key].strip():raise ValueError('Missing supervision '+key)
    finite(row.get('timestamp'),'sample time',0);finite(row.get('weight'),'sample weight',.001,100.)
    if row.get('task') not in ('state_reaction','action_choice'):raise ValueError('Static/long-term trait labels cannot train the reaction head')
    if row.get('source_kind') not in ALLOWED_SOURCES or row.get('reviewed') is not True:
        raise ValueError('Generated replies, model self-ratings, unverified API or Legacy promotions are not valid labels')
    if type(row.get('engineering_fixture')) is not bool or row['source_kind']=='controlled_fixture' and not row['engineering_fixture']:
        raise ValueError('Synthetic data must be explicitly marked')
    if not isinstance(row.get('evidence_refs'),list) or not row['evidence_refs'] or any(not isinstance(k,str) or not k for k in row['evidence_refs']):
        raise ValueError('Raw evidence references required')
    permissions=row.get('permissions',{})
    if permissions.get('parameter_training') is not True or row['scope'] not in permissions.get('scopes',[]):
        raise ValueError('No permission for this training scope')
    if row.get('withdrawn'):raise ValueError('Withdrawn sample')
    checked_inputs(row['inputs'])
    labels=row.get('labels',{})
    if row['task']=='state_reaction':
        state=labels.get('state')
        if not isinstance(state,list) or len(state)!=25 or not any(v is not None for v in state):raise ValueError('Masked 25-state label required')
        for v in state:
            if v is not None:finite(v,'state label',-100.,100.)
        if not isinstance(row.get('scale_id'),str) or not row['scale_id']:raise ValueError('Measurement scale required')
    else:
        if labels.get('action') not in ACTIONS:raise ValueError('Independent action label missing')
    if row.get('key',sample_key(row))!=sample_key(row):raise ValueError('Sample event key mismatch')
    digest(row)
    return row

def audit_dataset(rows,owner_id,source_resolver=None):
    if not isinstance(rows,list) or not 1<=len(rows)<=10000:raise ValueError('Dataset must contain 1..10000 rows')
    accepted={};duplicates=[]
    for original in rows:
        r=copy.deepcopy(validate_sample(original))
        if r['owner_id']!=owner_id:raise ValueError('Dataset owner mismatch')
        if source_resolver is not None:source_resolver(r)
        key=sample_key(r);r['key']=key
        if key in accepted:
            if digest(accepted[key])!=digest(r):raise ValueError('Conflicting labels for the same independent event/task')
            duplicates.append(key);continue
        accepted[key]=r
    result=list(accepted.values())
    return result,{'version':VERSION,'input_count':len(rows),'unique_samples':len(result),
                   'independent_events':len({(r['subject_id'],r['event_id']) for r in result}),
                   'duplicate_keys':duplicates,'dataset_sha256':digest(result),
                   'engineering_only':any(r['engineering_fixture'] for r in result)}

def split_dataset(rows,plan,*,target,owner_id):
    """Explicit participant allocation AND non-overlapping time windows.

    Core validation never applies a person's private adapter to a different
    participant. A personal-adapter experiment uses within-person future windows
    and is explicitly NOT a subject-held-out validation or publishable by itself.
    """
    names=('train','validation','test')
    if not isinstance(plan,dict) or set(plan)!=set(names):raise ValueError('Three explicit split partitions required')
    for name in names:
        part=plan[name]
        if not isinstance(part.get('subjects'),list) or not part['subjects']:raise ValueError('Split subjects required')
        for k in ('start','end'):finite(part.get(k),'split time',0)
        if part['start']>=part['end']:raise ValueError('Invalid split window')
    if plan['train']['end']>=plan['validation']['start'] or plan['validation']['end']>=plan['test']['start']:
        raise ValueError('Train/validation/test time windows overlap')
    subjects=[set(plan[k]['subjects']) for k in names]
    if target=='core' and any(subjects[i]&subjects[j] for i in range(3) for j in range(i)):
        raise ValueError('Shared-core subject leakage across splits')
    if target=='adapter' and any(s!={owner_id} for s in subjects):raise ValueError('Personal adapter can only use its owner')
    output={k:[] for k in names};events={}
    for r in rows:
        candidates=[k for k in names if r['subject_id'] in plan[k]['subjects'] and plan[k]['start']<=r['timestamp']<=plan[k]['end']]
        if len(candidates)!=1:raise ValueError('Every sample must have exactly one declared subject/time partition')
        name=candidates[0];key=(r['subject_id'],r['event_id'])
        if key in events and events[key]!=name:raise ValueError('Independent event leaked between folds')
        events[key]=name;output[name].append(r)
        permission='shared_core' if target=='core' else 'personal_adapter'
        if r['permissions'].get(permission) is not True:raise ValueError('Training target not authorized')
    if any(not v for v in output.values()):raise ValueError('Every split requires valid samples')
    return output

def structural_loss(net):
    """Soft value-circle hypothesis, with strength selected on validation data.

    Adjacent values may share response parameters; no equality or causal
    direction is imposed. Lambda=0 remains a valid validation candidate.
    """
    from .deliberation import VALUE_CIRCLE
    from .pmm_contracts import BLOCK_IDS
    ridge=sum((v*v).mean() for k,v in net.core.items() if '_W_' in k or '_C_' in k)
    indices=[BLOCK_IDS['V'].index('value.'+name) for name in VALUE_CIRCLE]
    circle=0.
    for name in ('W','C'):
        columns=(net.core['V_'+name+'_l']@net.core['V_'+name+'_r'])[:,indices]
        circle=circle+((columns-columns.roll(1,dims=1))**2).mean()
    rows=(net.core['V_U_l']@net.core['V_U_r'])[indices,:]
    return ridge+circle+((rows-rows.roll(1,dims=0))**2).mean()

def masked_loss(net,rows,lambda_struct=0.):
    """Equation C: normalize by SUM(valid masks * weights), never raw row count."""
    import torch
    numerator=torch.zeros((),dtype=torch.float64);denominator=0.
    for r in rows:
        y=net(r['inputs']);w=r['weight']
        if r['task']=='action_choice':
            numerator=numerator-w*torch.log(y['action'][ACTIONS.index(r['labels']['action'])].clamp_min(1e-12));denominator+=w
        else:
            labels=r['labels']['state'];mask=torch.tensor([v is not None for v in labels],dtype=torch.bool)
            target=torch.tensor([0. if v is None else v for v in labels],dtype=torch.float64)
            numerator=numerator+w*((y['state'][mask]-target[mask])**2).sum();denominator+=w*int(mask.sum())
    if denominator<=0:raise ValueError('No valid supervision')
    return numerator/denominator+lambda_struct*structural_loss(net)

def metrics(checkpoint,rows,owner_id):
    model=TraitDynamics(checkpoint,owner_id);total=0.;weight=0.;correct=0;actions=0;bins=[[] for _ in range(5)];brier=0.;counts={k:0 for k in ACTIONS}
    for r in rows:
        y=model.forward(r['inputs']);w=r['weight']
        if r['task']=='action_choice':
            probs=y['action_probabilities'];total-=w*math.log(max(1e-12,probs[r['labels']['action']]));weight+=w
            actions+=1;hit=max(probs,key=probs.get)==r['labels']['action'];correct+=hit;confidence=max(probs.values());bins[min(4,int(confidence*5))].append((confidence,float(hit)));counts[r['labels']['action']]+=1
            brier+=sum((p-float(k==r['labels']['action']))**2 for k,p in probs.items())
        else:
            for observed,predicted in zip(r['labels']['state'],y['state_prediction']):
                if observed is not None:total+=w*(predicted-observed)**2;weight+=w
    return {'loss':total/weight if weight else None,'valid_weight':weight,'action_accuracy':correct/actions if actions else None,
            'action_samples':actions,'samples':len(rows),'subjects':len({r['subject_id'] for r in rows}),
            'action_counts':counts,'action_classes':sum(v>0 for v in counts.values()),'majority_accuracy':max(counts.values())/actions if actions else None,
            'brier':brier/actions if actions else None,'ece':sum(len(b)/max(1,actions)*abs(sum(v[0] for v in b)/len(b)-sum(v[1] for v in b)/len(b)) for b in bins if b) if actions else None}

def fit(checkpoint,rows,plan,*,owner_id,target='core',epochs=20,learning_rate=.01,
        structural_candidates=(0.,.0001),source_resolver=None):
    """Train candidates and choose regularization using validation only.

    Independent test is evaluated once after selection, never used for fitting.
    Full-batch SGD without momentum makes resume from JSON exact and inspectable.
    """
    try:import torch
    except ImportError:raise ValueError('新版训练需要 PyTorch；请按 requirements-learning.txt 安装可选训练依赖。Legacy 与 NumPy 推断仍可用。') from None
    validate_checkpoint(checkpoint,owner_id)
    if target not in ('core','adapter'):raise ValueError('Target must be core or personal adapter')
    if type(epochs) is not int or not 1<=epochs<=1000:raise ValueError('Epoch budget outside 1..1000')
    finite(learning_rate,'learning rate',1e-6,1.)
    if not 1<=len(structural_candidates)<=5:raise ValueError('Bounded structural search required')
    for v in structural_candidates:finite(v,'structural regularization',0.,1.)
    audited,audit=audit_dataset(rows,owner_id,source_resolver);parts=split_dataset(audited,plan,target=target,owner_id=owner_id)
    base=copy.deepcopy(checkpoint);base['temperature']=1.;base=seal(base)
    if target=='core':base['adapter']={k:np.zeros(s).tolist() for k,s in ADAPTER_SHAPES.items()};base=seal(base)
    for r in audited:
        if r['task']=='state_reaction':
            expected=base['scale'].get('measurement_protocol') or 'engineering_latent'
            if r['scale_id']!=expected:raise ValueError('State labels and network use different measurement scales')
            if base['scale']['kind']=='engineering_latent' and not r['engineering_fixture']:
                raise ValueError('Real state labels require an independently calibrated latent scale')
            if base['scale']['kind']=='linear_validated' and any(v is not None and not m for v,m in zip(r['labels']['state'],base['scale']['mask'])):
                raise ValueError('State labels include a facet without independent scale calibration')
    before={k:metrics(base,v,owner_id) for k,v in parts.items()};runs=[];gradient_norms={}
    for lam in structural_candidates:
        net=torch_model(base,owner_id)
        for par in net.core.values():par.requires_grad_(target=='core')
        for par in net.adapter.values():par.requires_grad_(target=='adapter')
        params=[p for p in net.parameters() if p.requires_grad];optimizer=torch.optim.SGD(params,lr=learning_rate)
        history=[]
        for step in range(epochs):
            optimizer.zero_grad();loss=masked_loss(net,parts['train'],lam if target=='core' else 0.)
            if not torch.isfinite(loss):raise ValueError('Nonfinite training loss; candidate discarded')
            loss.backward()
            grad=float(torch.sqrt(sum((p.grad*p.grad).sum() for p in params if p.grad is not None)))
            if not math.isfinite(grad):raise ValueError('Nonfinite gradient; candidate discarded')
            gradient_norms[str(lam)]=grad;torch.nn.utils.clip_grad_norm_(params,5.);optimizer.step();history.append(float(loss.detach()))
        candidate=net.checkpoint(epochs);validation=metrics(candidate,parts['validation'],owner_id)
        runs.append({'lambda_struct':lam,'candidate':candidate,'validation':validation,'history':history})
    best=min(runs,key=lambda r:r['validation']['loss']);candidate=best['candidate']
    temperature_search=[]
    for temp in (.5,1.,2.,4.):
        probe=seal({**candidate,'temperature':temp});temperature_search.append((metrics(probe,parts['validation'],owner_id)['loss'],temp))
    candidate=seal({**candidate,'temperature':min(temperature_search)[1]})
    after={k:metrics(candidate,v,owner_id) for k,v in parts.items()}
    report={'schema':'pmm-calibration/2.8','trainer_version':VERSION,'target':target,'dataset':audit,
            'split_plan':copy.deepcopy(plan),'subject_held_out':target=='core','time_held_out':True,
            'personal_adapter_limitation':None if target=='core' else 'within_person_future_validation_not_cross_subject; not_publishable_alone; requires_published_core_validation',
            'before':before,'after':after,'gradient_norms':gradient_norms,'epochs':epochs,
            'learning_rate':learning_rate,'temperature':candidate['temperature'],'temperature_selection':'validation_only_grid_0.5_1_2_4','selected_lambda':best['lambda_struct'],
            'structural_prior':'block_ridge_plus_adjacent_value_circle_soft_hypothesis; lambda_selected_on_validation_including_zero',
            'validation_search':[{'lambda_struct':r['lambda_struct'],'loss':r['validation']['loss']} for r in runs],
            'loss_history':best['history'],'engineering_only':audit['engineering_only'],
            'parent_sha256':checkpoint['sha256'],'scientific_validity':'not_established',
            'permissions_review_required':True,'optimizer':'full_batch_SGD_no_momentum',
            'test_used_for_selection':False}
    candidate['training']={'version':VERSION,'target':target,'dataset_sha256':audit['dataset_sha256'],
                           'sample_keys':[r['key'] for r in audited],'source_refs':sorted({e for r in audited for e in r['evidence_refs']}),
                           'engineering_only':audit['engineering_only'],'parent_sha256':checkpoint['sha256']}
    candidate=seal(candidate);report['checkpoint_sha256']=candidate['sha256'];report['id']=digest(report)
    return candidate,report,audited

def publication_eligibility(checkpoint,report,rows,owner_id,source_resolver):
    """Revalidate evidence and held-out metrics; never trust a UI 'calibrated' flag."""
    validate_checkpoint(checkpoint,owner_id)
    if not isinstance(report,dict) or report.get('checkpoint_sha256')!=checkpoint['sha256']:
        return False,'missing_bound_validation_report'
    if report.get('id')!=digest({k:v for k,v in report.items() if k!='id'}):return False,'validation_report_digest_mismatch'
    audited,audit=audit_dataset(rows,owner_id,source_resolver)
    if audit['dataset_sha256']!=report['dataset']['dataset_sha256']:return False,'dataset_changed'
    if report['engineering_only'] or audit['engineering_only']:return False,'synthetic_engineering_data_not_publishable'
    target=report.get('target')
    if target not in ('core','adapter') or target=='core' and not report.get('subject_held_out'):return False,'missing_subject_held_out_core_validation'
    parts=split_dataset(audited,report['split_plan'],target=target,owner_id=owner_id)
    if not checkpoint.get('training') or checkpoint['steps']<=0:return False,'untrained'
    # These are explicit conservative release rules, not psychological proof.
    for name in ('validation','test'):
        actual=metrics(checkpoint,parts[name],owner_id);before=report['before'][name]
        if actual['subjects']<(2 if target=='core' else 1) or actual['action_samples']<24 or actual['action_classes']<2:return False,'insufficient_independent_behavioral_validation'
        if actual['ece']>.2 or actual['action_accuracy']<=actual['majority_accuracy']:return False,'behavioral_calibration_or_majority_baseline_not_met'
        if actual['loss']>before['loss']+1e-9 or actual['action_accuracy'] is None or actual['action_accuracy']<.5:
            return False,'behavioral_validation_did_not_meet_release_rule'
        if abs(actual['loss']-report['after'][name]['loss'])>1e-10:return False,'validation_metrics_not_reproducible'
    return True,'held_out_behavioral_engineering_gate_passed_not_psychological_validation'

def fit_transition(rows,construct_ids,plan,*,ridge=.01):
    """Estimate diagonal G from independent before/after longitudinal measurements.

    HEXACO only. Different constructs do not inherit this G or its error model.
    Test error against persistence; fixture models remain engineering-only.
    """
    from .pmm_contracts import BLOCK_IDS
    from .trait_estimator import vector
    ids=list(construct_ids);n=len(ids);finite(ridge,'transition ridge',0.,10.)
    if not ids or len(set(ids))!=n or any(k not in BLOCK_IDS['H'] for k in ids):raise ValueError('HEXACO transition IDs required')
    if not rows:raise ValueError('Independent longitudinal data required')
    if len({r.get('scale_id') for r in rows})>1:raise ValueError('Transition measurement scales differ')
    seen=set();clean=[]
    for r in rows:
        if r.get('source_kind') not in ('independent_questionnaire','independent_observer','controlled_fixture') or not r.get('reviewed') or r.get('withdrawn'):
            raise ValueError('No independent transition measurements')
        permissions=r.get('permissions',{})
        if not r.get('engineering_fixture') and (permissions.get('parameter_training') is not True or r.get('scope') not in permissions.get('scopes',[])):
            raise ValueError('No permission for longitudinal training in this scope')
        if not r.get('evidence_refs') or r.get('before_event_id')==r.get('after_event_id'):raise ValueError('Separate before/after evidence required')
        if r.get('before_time',0)>=r.get('after_time',0):raise ValueError('Longitudinal chronology invalid')
        key=(r['subject_id'],r['before_event_id'],r['after_event_id'])
        if key in seen:continue
        seen.add(key);clean.append(r)
        for k in ('before','after','zeta'):vector(r[k],n,k)
        if r['source_kind']=='controlled_fixture' and not r.get('engineering_fixture'):raise ValueError('Fixture marker missing')
    # A pair cannot straddle windows and participants are disjoint across folds.
    sets=[set(plan[k]['subjects']) for k in ('train','validation','test')]
    if any(sets[i]&sets[j] for i in range(3) for j in range(i)):raise ValueError('Transition subject leakage')
    if plan['train']['end']>=plan['validation']['start'] or plan['validation']['end']>=plan['test']['start']:raise ValueError('Transition time leakage')
    folds={k:[r for r in clean if r['subject_id'] in p['subjects'] and p['start']<=r['before_time']<r['after_time']<=p['end']] for k,p in plan.items()}
    if sum(map(len,folds.values()))!=len(clean) or any(len(v)<2 for v in folds.values()):raise ValueError('Insufficient disjoint longitudinal folds')
    x=np.array([r['zeta'] for r in folds['train']]);y=np.array([np.array(r['after'])-r['before'] for r in folds['train']])
    g=(x*y).sum(0)/((x*x).sum(0)+ridge);errors={}
    for k,rs in folds.items():
        xx=np.array([r['zeta'] for r in rs]);yy=np.array([np.array(r['after'])-r['before'] for r in rs])
        errors[k]={'mse':float(np.mean((yy-xx*g)**2)),'persistence_mse':float(np.mean(yy**2)),'subjects':len({r['subject_id'] for r in rs})}
    residual=y-x*g;Q=np.diag(np.mean(residual**2,axis=0))
    engineering=any(r.get('engineering_fixture',False) for r in clean)
    validated=not engineering and all(errors[k]['subjects']>=2 and errors[k]['mse']<errors[k]['persistence_mse'] for k in ('validation','test'))
    model={'format':'longitudinal-transition/2.8','scale_id':clean[0].get('scale_id'),'construct_ids':ids,'F':np.eye(n).tolist(),'G':np.diag(g).tolist(),
           'b':[0.]*n,'Q':Q.tolist(),'independent_errors':True,'validated':validated,'engineering_only':engineering,
           'errors':errors,'split_plan':copy.deepcopy(plan),'evidence_refs':sorted({e for r in clean for e in r['evidence_refs']}),
           'dataset_sha256':digest(clean),'prior':'diagonal_ridge','ridge':ridge,'scientific_validity':'not_established'}
    model['id']=digest(model);model['validation_ref']=model['id'] if validated else None;return model

def empty_catalog(owner_id):
    return {'schema':'pmm-model-catalog/2.8','subject_id':owner_id,'revision':0,'versions':{},'reports':{},
            'datasets':{},'published':None,'frozen':[],'revoked':[],'jobs':{},'audit':[]}

def validate_catalog(value,owner_id):
    if value is None:return
    if not isinstance(value,dict) or value.get('schema')!='pmm-model-catalog/2.8' or value.get('subject_id')!=owner_id:raise ValueError('2.8 model catalog identity mismatch')
    if type(value.get('revision')) is not int or value['revision']<0:raise ValueError('2.8 model catalog revision invalid')
    for name in ('versions','reports','datasets','jobs'):
        if not isinstance(value.get(name),dict) or len(value[name])>1000:raise ValueError('2.8 catalog invalid or too large')
    for key,ck in value['versions'].items():
        validate_checkpoint(ck,owner_id)
        if key!=ck['sha256']:raise ValueError('Checkpoint key mismatch')
    for name in ('frozen','revoked'):
        if not isinstance(value.get(name),list) or any(k not in value['versions'] for k in value[name]):raise ValueError('Catalog version reference missing')
    if value.get('published') is not None and value['published'] not in value['versions']:raise ValueError('Published version missing')
    if not isinstance(value.get('audit'),list):raise ValueError('Catalog audit missing')

def validate_metadata(meta):
    owner=meta['identity']['id'];validate_catalog(meta.get('pmm28_models'),owner)
    from .pmm_longitudinal import validate as validate_estimator
    validate_estimator(meta.get('pmm28_estimator'),owner)
    data=meta.get('pmm28_samples')
    if data is not None:
        if not isinstance(data,dict) or data.get('schema')!='pmm-dataset/2.8' or data.get('subject_id')!=owner or type(data.get('revision')) is not int or data['revision']<0 or not isinstance(data.get('rows'),dict) or len(data['rows'])>10000:
            raise ValueError('2.8 sample metadata invalid')
        for key,row in data['rows'].items():
            checked={**row,'withdrawn':False};validate_sample(checked)
            if row['owner_id']!=owner or sample_key(row)!=key:raise ValueError('2.8 sample identity mismatch')
    cat=meta.get('pmm28_models')
    if cat:
        for key,report in cat['reports'].items():
            if key not in cat['versions'] or report.get('checkpoint_sha256')!=key or report.get('id')!=digest({k:v for k,v in report.items() if k!='id'}):raise ValueError('2.8 model report identity mismatch')
            rows,audit=audit_dataset(cat['datasets'].get(key),owner)
            if audit['dataset_sha256']!=report.get('dataset',{}).get('dataset_sha256'):raise ValueError('2.8 dataset digest mismatch')

class Learning:
    version=VERSION
    def __init__(self,engine):self.engine=engine
    def source_resolver(self,row):
        self.engine.evidence.validate_supervision_sources(row)
    def train(self,**inputs):
        validate_network_scale(self.engine,inputs['checkpoint'])
        return fit(owner_id=self.engine.profile()['id'],source_resolver=self.source_resolver,**inputs)

def validate_network_scale(engine,checkpoint):
    if checkpoint['scale']['kind']!='linear_validated':return
    from types import SimpleNamespace
    from .pmm_longitudinal import calibration_live
    from .trait_dynamics import bind_measurement_scale
    entry=(engine.store.meta('pmm28_estimator') or {}).get('protocols',{}).get(checkpoint['scale'].get('protocol_id'))
    protocol=calibration_live(SimpleNamespace(engine=engine),entry,'protocol')
    expected=bind_measurement_scale(initial_checkpoint(engine.profile()['id']),protocol)['scale']
    if checkpoint['scale']!=expected:raise ValueError('Network scale does not match live independently calibrated protocol')

def published_gate(engine,catalog,version=None,_seen=None):
    """Re-evaluate release after restart, source withdrawal or catalog changes."""
    owner=engine.profile()['id'];key=version or catalog.get('published');seen=set(_seen or ())
    if key in seen or len(seen)>16:return False,'cyclic_or_excessive_validation_chain'
    seen.add(key)
    if not key:return False,'no_published_validated_network'
    try:
        validate_catalog(catalog,owner)
        if key in catalog['revoked'] or key not in catalog['frozen']:return False,'published_version_revoked_or_unfrozen'
        checkpoint=catalog['versions'][key];report=catalog['reports'].get(key)
        validate_network_scale(engine,checkpoint)
        parent=catalog['versions'].get((checkpoint.get('training') or {}).get('parent_sha256'))
        if parent is None:return False,'missing_auditable_training_parent'
        rows=catalog['datasets'].get(key,[])
        ready,reason=publication_eligibility(checkpoint,report,rows,owner,Learning(engine).source_resolver)
        if not ready:return ready,reason
        # A forged imported "before" metric cannot certify an arbitrary model.
        from .trait_dynamics import ADAPTER_SHAPES
        target=report['target']
        if target=='adapter':
            parent_key=parent['sha256']
            if not any(a.get('version')==parent_key and a.get('op')=='publish' for a in catalog['audit']):return False,'adapter_parent_not_previously_published'
            ready,reason=published_gate(engine,catalog,parent_key,seen)
            if not ready:return False,'adapter_core_validation_failed:'+reason
            if parent['parameters']!=checkpoint['parameters']:return False,'adapter_training_modified_shared_core'
        base=copy.deepcopy(parent);base['temperature']=1.
        if target=='core':base['adapter']={k:np.zeros(s).tolist() for k,s in ADAPTER_SHAPES.items()}
        base=seal(base)
        folds=split_dataset(rows,report['split_plan'],target=target,owner_id=owner)
        for name,part in folds.items():
            if metrics(base,part,owner)!=report['before'][name]:return False,'parent_metrics_not_reproducible'
        return True,reason
    except (ValueError,KeyError,TypeError):return False,'model_or_evidence_validation_failed'
