"""Actual E-A/D/F/G gradient training, chronological splits and release records.

Training is optional; NumPy forward, migrations and all saved states work
without Torch. Synthetic trajectories exercise engineering, never publication.
"""
from __future__ import annotations
import copy,math
import numpy as np
from .registry import digest,APPRAISAL_IDS
from .affect import LABELS
from .affect_response import (seal,validate_model,parameters,SHAPES,trait_inputs,masked,jump_inputs)
from .affect_dynamics_v2 import seconds,coupled_moments,ou_moments

DATA_FORMAT='affect-supervision/2.8.1'

def validate_dataset(dataset):
    if not isinstance(dataset,dict) or dataset.get('format')!=DATA_FORMAT or type(dataset.get('engineering_only')) is not bool:raise ValueError('情绪训练数据协议错误')
    rows=dataset.get('rows');seen=set();windows={};subjects={k:set() for k in ('train','validation','test')};groups={k:[] for k in subjects}
    if not isinstance(rows,list) or not rows:raise ValueError('缺少情绪训练行')
    for r in rows:
        split=r.get('split');owner=r.get('subject_id');key=(owner,r.get('scope'),r.get('event_id'))
        if split not in groups or not all(isinstance(v,str) and v for v in key) or key in seen:raise ValueError('重复情绪证据或数据分割错误')
        seen.add(key);subjects[split].add(owner);stamp=seconds(r.get('at'));windows.setdefault(split,[]).append(stamp)
        dt=r.get('delta_seconds')
        if type(dt) not in (float,int) or not math.isfinite(dt) or not 0<dt<=stamp:raise ValueError('参数训练需要有效的正真实时间间隔')
        measurement=r.get('measurement_variance',1e-4)
        if type(measurement) not in (int,float) or not math.isfinite(measurement) or measurement<=0:raise ValueError('测量误差方差必须为正')
        trait_inputs(r['blocks']);checks=r.get('appraisal',{})
        if set(checks)-set(APPRAISAL_IDS) or any(v is not None and (type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1) for v in checks.values()):raise ValueError('训练评价输入无效')
        for field,n,nullable in [('fast_before',5,False),('mood_before',3,False),('fast_after',5,True),('mood_after',3,True),('labels',len(LABELS),True)]:
            values=r.get(field)
            if not isinstance(values,list) or len(values)!=n:raise ValueError('训练状态形状错误: '+field)
            for v in values:
                if v is None and nullable:continue
                if type(v) not in (int,float) or not math.isfinite(v):raise ValueError('训练值无效')
                if field=='labels' and v not in (0,1):raise ValueError('标签需为独立二元监督或未知')
        if all(v is None for v in r['fast_after']+r['mood_after']+r['labels']) and r.get('regulation_label') is None:raise ValueError('此行没有监督目标')
        if r.get('regulation_label') not in (None,0,1,2):raise ValueError('策略监督无效')
        source=r.get('source',{})
        if source.get('kind') not in ('synthetic','independent_measurement') or not source.get('evidence_id'):raise ValueError('缺少独立观测来源')
        if not dataset['engineering_only']:
            if source.get('kind')!='independent_measurement' or source.get('parameter_training') is not True or source.get('reviewed') is not True or not source.get('measurement_protocol'):raise ValueError('真实监督缺少测量来源/参数使用许可')
        groups[split].append(r)
    if any(not v for v in groups.values()):raise ValueError('训练、验证与测试集都必须存在')
    if max(windows['train'])>=min(windows['validation']) or max(windows['validation'])>=min(windows['test']):raise ValueError('情绪分割必须按未来时间隔离')
    return groups

def _x(row):
    packet={'checks':{k:row['appraisal'].get(k) for k in APPRAISAL_IDS}}
    return packet,jump_inputs(packet,row['blocks'],row.get('relation',{}),row['mood_before'],row['fast_before'])

def predict_mean(model,row):
    pars=parameters(model,row['blocks']);e=np.asarray(row['fast_before']);m=np.asarray(row['mood_before']);dt=row['delta_seconds']
    mean,var=ou_moments(e,pars['mu'][:5],pars['kappa'][:5],pars['sigma'][:5],dt);mmean=[];mvar=[]
    for i in range(3):
        v,cov=coupled_moments(e[i],m[i],pars['mu'][i],pars['mu'][i+5],pars['kappa'][i],pars['kappa'][i+5],pars['sigma'][i],pars['sigma'][i+5],pars['coupling'][i],dt)
        mmean.append(v[1]);mvar.append(cov[1,1])
    packet={'checks':{k:row['appraisal'].get(k) for k in APPRAISAL_IDS}}
    x=jump_inputs(packet,row['blocks'],row.get('relation',{}),mmean,mean)
    if any(v is not None for v in packet['checks'].values()):mean=mean+np.asarray(model['parameters']['jump_W'])@x+np.asarray(model['parameters']['jump_b'])
    q=masked(list(packet['checks'].values()));logits=np.asarray(model['parameters']['label_W'])@np.r_[mean,q,np.zeros(16)]+model['parameters']['label_b']
    return np.r_[mean,mmean],np.r_[var,mvar]+float(row.get('measurement_variance',1e-4)),np.exp(-np.logaddexp(0.,-logits))

def metrics(model,rows):
    nll=[];mse=[];briers=[];std=[];strategy=[]
    for r in rows:
        mean,var,prob=predict_mean(model,r)
        for j,y in enumerate(r['fast_after']+r['mood_after']):
            if y is not None:
                nll.append(.5*(math.log(2*math.pi*var[j])+(y-mean[j])**2/var[j]));mse.append((y-mean[j])**2);std.append((y-mean[j])**2/var[j])
        for y,p in zip(r['labels'],prob):
            if y is not None:briers.append((y-p)**2)
        if r.get('regulation_label') is not None:
            ps=parameters(model,r['blocks']);pre,_=ou_moments(r['fast_before'],ps['mu'][:5],ps['kappa'][:5],ps['sigma'][:5],r['delta_seconds'])
            rx=np.r_[pre,masked([r['appraisal'].get(k) for k in APPRAISAL_IDS]),trait_inputs(r['blocks'],('D',)),[r.get('goal',{}).get('relevance',0.),r.get('goal',{}).get('urgency',0.)]]
            logits=np.asarray(model['parameters']['reg_W'])@rx+model['parameters']['reg_b'];strategy.append(float(np.logaddexp.reduce(logits)-logits[r['regulation_label']]))
    return {'rows':len(rows),'state_nll':float(np.mean(nll)) if nll else None,'state_mse':float(np.mean(mse)) if mse else None,
        'standardized_error':float(np.mean(std)) if std else None,'label_brier':float(np.mean(briers)) if briers else None,
        'state_observations':len(nll),'label_observations':len(briers),'strategy_ce':float(np.mean(strategy)) if strategy else None,'strategy_observations':len(strategy)}

def torch_prediction(p,row,torch):
    T=lambda v:torch.as_tensor(v,dtype=torch.float64)
    x=T(trait_inputs(row['blocks']));mu=p['mu_W']@x+p['mu_b'];k=torch.nn.functional.softplus(p['kappa_W']@x+p['kappa_b'])+1e-12;s=torch.nn.functional.softplus(p['sigma_W']@x+p['sigma_b'])
    dt=row['delta_seconds'];e=T(row['fast_before']);m=T(row['mood_before']);fe=torch.exp(-k[:5]*dt);fm=torch.exp(-k[5:]*dt)
    pre=mu[:5]+fe*(e-mu[:5]);diff=k[5:]-k[:3]
    close=diff.abs()<1e-4*torch.maximum(torch.maximum(k[:3],k[5:]),T([1/dt]*3))
    safe=torch.where(close,torch.ones_like(diff),diff)
    cross=torch.where(close,fm*dt*(1+diff*dt/2+(diff*dt)**2/6+(diff*dt)**3/24),(fe[:3]-fm)/safe)
    mm=mu[5:]+fm*(m-mu[5:])+p['coupling']*cross*(e[:3]-mu[:3])
    packet={'checks':{key:row['appraisal'].get(key) for key in APPRAISAL_IDS}};q=T(masked(list(packet['checks'].values())))
    jx=torch.cat((q,T(trait_inputs(row['blocks'],('H','V','D'))),T(masked([row.get('relation',{}).get(key) for key in ('trust','familiarity','affection')])),mm,pre))
    after=pre+p['jump_W']@jx+p['jump_b'] if any(v is not None for v in packet['checks'].values()) else pre
    logits=p['label_W']@torch.cat((after,q,T([0.]*16)))+p['label_b']
    # Composite Gaussian marginal likelihood. OU propagation uses full block
    # covariance; this training objective does not assert conditional independence.
    I=lambda rate:-torch.expm1(-rate*dt)/rate
    variance=s*s*I(2*k)
    forced=(I(2*k[:3])-2*I(k[:3]+k[5:])+I(2*k[5:]))/(safe*safe)
    def moment(n,rate):
        z=rate*dt;small=z<.5;zs=torch.where(small,z,torch.zeros_like(z));term=torch.ones_like(z);total=term/(n+1)
        for j in range(1,30):term=term*(-zs/j);total=total+term/(n+j+1)
        value=-torch.expm1(-z)/rate
        for j in range(1,n+1):value=j/rate*value-dt**j*torch.exp(-z)/rate
        return torch.where(small,dt**(n+1)*total,value)
    if bool(close.any()):
        coeff=[diff**n/math.factorial(n+1) for n in range(5)]
        moments={n:moment(n,2*k[5:]) for n in range(2,11)}
        equal=sum(a*b*moments[i+j+2] for i,a in enumerate(coeff) for j,b in enumerate(coeff))
        forced=torch.where(close,equal,forced)
    vm=variance[5:]+p['coupling']**2*s[:3]**2*forced
    vr=torch.cat((variance[:5],vm))+float(row.get('measurement_variance',1e-4))
    rx=torch.cat((pre,q,T(trait_inputs(row['blocks'],('D',))),T([row.get('goal',{}).get('relevance',0.),row.get('goal',{}).get('urgency',0.)])))
    return torch.cat((after,mm)),vr,logits,p['reg_W']@rx+p['reg_b']

def train(model,dataset,epochs=30,lr=.001,component='all'):
    import torch
    validate_model(model,model['subject_id']);groups=validate_dataset(dataset)
    if type(epochs) is not int or not 1<=epochs<=2000 or not math.isfinite(lr) or not 0<lr<=.1:raise ValueError('训练步数或学习率无效')
    prefixes={'parameters':('mu_','kappa_','sigma_','coupling'),'response':('jump_',),'labels':('label_',),'regulation':('reg_',),'all':('',)}
    if component not in prefixes:raise ValueError('训练组件无效')
    params={k:torch.tensor(v,dtype=torch.float64,requires_grad=any(k.startswith(p) for p in prefixes[component])) for k,v in model['parameters'].items()}
    optim=torch.optim.SGD([{'params':[p],'lr':lr*1e-6 if k=='coupling' else lr} for k,p in params.items() if p.requires_grad],lr=lr);losses=[]
    before={k:metrics(model,v) for k,v in groups.items()}
    for _ in range(epochs):
        optim.zero_grad();terms=[]
        for row in groups['train']:
            mean,var,labels,reg=torch_prediction(params,row,torch)
            observed=row['fast_after']+row['mood_after'];mask=[i for i,v in enumerate(observed) if v is not None]
            if mask and component in ('parameters','response','all'):
                target=torch.tensor([observed[i] for i in mask],dtype=torch.float64)
                terms.append(.5*(torch.log(2*math.pi*var[mask])+(target-mean[mask])**2/var[mask]).mean())
            mask=[i for i,v in enumerate(row['labels']) if v is not None]
            if mask and component in ('labels','all'):terms.append(torch.nn.functional.binary_cross_entropy_with_logits(labels[mask],torch.tensor([row['labels'][i] for i in mask],dtype=torch.float64)))
            if row.get('regulation_label') is not None and component in ('regulation','all'):terms.append(torch.nn.functional.cross_entropy(reg[None,:],torch.tensor([row['regulation_label']])))
        if not terms:raise ValueError('所选组件没有有效监督')
        loss=torch.stack(terms).mean()
        if not torch.isfinite(loss):raise ValueError('情绪损失非有限，候选未写入')
        loss.backward();torch.nn.utils.clip_grad_norm_([p for p in params.values() if p.requires_grad],5.);optim.step();losses.append(float(loss.detach()))
    out=copy.deepcopy(model);out['parameters']={k:v.detach().numpy().tolist() for k,v in params.items()};out['steps']+=epochs
    out['calibration']={'status':'unvalidated','labels':[False]*len(LABELS),'components':{}}
    out['training']={'dataset_sha256':digest(dataset),'engineering_only':dataset['engineering_only'],'component':component,'epochs':epochs,'lr':lr,'optimizer':'SGD_no_momentum','parent':model['sha256']};out=seal(out)
    validate_model(out,out['subject_id']);after={k:metrics(out,v) for k,v in groups.items()}
    report=seal({'model_sha256':out['sha256'],'dataset_sha256':digest(dataset),'engineering_only':dataset['engineering_only'],
        'component':component,'losses':losses,'before':before,'after':after,'steps':out['steps'],
        'scope':'actual_gradient_and_held_out_engineering_metrics_not_psychological_validity',
        'objective':'masked_composite_OU_marginal_NLL_plus_multilabel_BCE_plus_strategy_CE'})
    return out,report

def release_gate(catalog,version):
    model=catalog.get('versions',{}).get(version);report=catalog.get('reports',{}).get(version)
    if not model or not report or model.get('steps',0)<=0:return False,'未训练或缺少独立报告'
    if model.get('calibration',{}).get('status') not in ('validated','validated_partial'):return False,'尚未执行独立校准'
    if version in catalog.get('revoked',[]):return False,'模型已撤销'
    if seal(report)['sha256']!=report.get('sha256') or report['model_sha256']!=version:return False,'报告与权重不一致'
    dataset=catalog.get('datasets',{}).get(report['dataset_sha256'])
    if not dataset or digest(dataset)!=report['dataset_sha256']:return False,'缺少原始监督'
    if report['dataset_sha256'] in catalog.get('withdrawn_datasets',[]):return False,'监督来源已撤回'
    groups=validate_dataset(dataset)
    if dataset['engineering_only'] or report['engineering_only']:return False,'合成数据仅供工程验证'
    if model['training']['dataset_sha256']!=report['dataset_sha256']:return False,'模型训练来源不一致'
    if any(len(groups[k])<8 for k in ('validation','test')):return False,'独立验证与测试样本不足'
    # Validation selects label heads. The untouched test window must also
    # substantiate every probability exposed to the user (no test-time selection).
    enabled=[j for j,flag in enumerate(model['calibration']['labels']) if flag]
    if enabled:
        preds=[(r['labels'],predict_mean(model,r)[2]) for r in groups['test']]
        for j in enabled:
            outcomes=[(y[j],p[j]) for y,p in preds if y[j] is not None]
            if len(outcomes)<8 or {y for y,_ in outcomes}!={0,1} or np.mean([(y-p)**2 for y,p in outcomes])>=.25:return False,'已选标签缺少独立未来窗口支持'
    for split in ('validation','test'):
        actual=metrics(model,groups[split]);recorded=report['after'][split]
        if actual!=recorded:return False,'报告指标不能由模型重算'
        component=report['component']
        if component in ('parameters','response','all'):
            if actual['state_nll'] is None or report['before'][split]['state_nll'] is None or actual['state_nll']>=report['before'][split]['state_nll']:return False,'未来状态预测未改善'
            if not .25<=actual['standardized_error']<=4:return False,'状态不确定性未校准'
        if component=='labels':
            if not any(model['calibration']['labels']) or actual['label_brier'] is None or actual['label_brier']>=report['before'][split]['label_brier']:return False,'未来标签预测未改善'
        if component=='regulation':
            if actual['strategy_ce'] is None or actual['strategy_ce']>=report['before'][split]['strategy_ce']:return False,'未来策略预测未改善'
    return True,'已通过独立未来状态工程校准；不代表心理学效度'

def calibrate(model,dataset,report):
    """Create a separately identified calibrated candidate, never auto-publish."""
    groups=validate_dataset(dataset)
    if dataset['engineering_only']:raise ValueError('合成轨迹不能作为正式校准')
    if report['model_sha256']!=model['sha256'] or report['dataset_sha256']!=digest(dataset):raise ValueError('校准资料与训练模型不一致')
    out=copy.deepcopy(model);labels=[]
    for j in range(len(LABELS)):
        observed=[(r['labels'][j],predict_mean(model,r)[2][j]) for r in groups['validation'] if r['labels'][j] is not None]
        labels.append(len(observed)>=8 and {y for y,_ in observed}=={0,1} and np.mean([(y-p)**2 for y,p in observed])<.25)
    component=report['component'];components={'dynamics':'unvalidated','response':'unvalidated','labels':'validated_partial' if any(labels) else 'unvalidated','regulation':'unvalidated'}
    if component in ('parameters','all'):components['dynamics']='held_out_marginal_calibration'
    if component in ('response','all'):components['response']='held_out_state_prediction'
    if component=='regulation':components['regulation']='held_out_strategy_supervision_not_guaranteed_success'
    out['calibration']={'status':'validated_partial','labels':labels,'components':components,
        'dataset_sha256':digest(dataset),'parent_model':model['sha256'],'protocols':sorted({r['source']['measurement_protocol'] for r in dataset['rows']})}
    out=seal(out);r=copy.deepcopy(report);r.update(model_sha256=out['sha256'],calibration_parent=model['sha256']);r=seal(r)
    cat={'versions':{out['sha256']:out},'reports':{out['sha256']:r},'datasets':{digest(dataset):dataset}}
    ok,reason=release_gate(cat,out['sha256'])
    if not ok:raise ValueError(reason)
    return out,r

def publish(catalog,version):
    ok,reason=release_gate(catalog,version)
    if not ok:raise ValueError(reason)
    out=copy.deepcopy(catalog);out['active']=version;out['revision']+=1
    # Publication is catalog metadata. Immutable weight identity is never edited.
    out['audit'].append({'operation':'publish','version':version,'reason':reason,'revision':out['revision']});return out
