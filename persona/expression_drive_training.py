"""Offline candidate fitting for existing ED matrices. No runtime activation."""
import copy
import math
import numpy as np
from .registry import digest
from . import expression_drive as ed

INPUTS = ('theta', 'emotion', 'mood', 'appraisal', 'relationship', 'context', 'residual')
MATRICES = ('W_theta', 'W_e', 'W_m', 'W_q', 'W_r', 'W_c', 'W_u')
SIZES = tuple(ed.SHAPES[k][1] for k in MATRICES)


def validate_dataset(dataset):
    if not isinstance(dataset, dict) or dataset.get('schema') != 'expressive-drive-dataset/1': raise ValueError('表达欲数据协议无效')
    if type(dataset.get('engineering_only')) is not bool or not dataset.get('measurement_protocol'): raise ValueError('缺少数据用途或测量协议')
    rows = dataset.get('rows')
    if not isinstance(rows, list) or not rows or len(rows) > 100000: raise ValueError('数据条数无效')
    groups = {k:[] for k in ('train', 'validation', 'test')}; ownership = {}; ids=set();sources={}
    for row in rows:
        split=row.get('split'); group=row.get('event_group'); identifier=row.get('id')
        if split not in groups or not isinstance(group,str) or not group or not isinstance(identifier,str) or not identifier or identifier in ids: raise ValueError('样本或独立事件分组无效')
        ids.add(identifier)
        if group in ownership and ownership[group]!=split: raise ValueError('同一事件不得跨训练、验证或测试集')
        ownership[group]=split
        at=row.get('at')
        if type(at) not in (int,float) or not math.isfinite(at): raise ValueError('样本时间无效')
        if not isinstance(row.get('inputs'),dict) or set(row['inputs'])!=set(INPUTS): raise ValueError('必须提供现有七类计算输入')
        for key,n in zip(INPUTS,SIZES):
            values=row['inputs'][key]
            if not isinstance(values,list) or len(values)!=n or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>2 for v in values): raise ValueError('输入形状或数值无效：'+key)
        mask=row.get('theta_mask')
        if not isinstance(mask,list) or len(mask)!=ed.N_THETA or any(type(v) is not int or v not in (0,1) for v in mask): raise ValueError('人格缺失掩码无效')
        if any(not m and x!=0 for x,m in zip(row['inputs']['theta'],mask)): raise ValueError('未知人格只能以掩码配合零贡献表示')
        target=row.get('targets')
        if not isinstance(target,list) or len(target)!=3 or all(v is None for v in target) or any(v is not None and (type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1) for v in target): raise ValueError('目标应为激活、紧迫、持续三项；未知留 null')
        src=row.get('source') or {}; ref=src.get('evidence_id')
        if not isinstance(ref,str) or not ref or src.get('kind') not in ('synthetic','independent_observation'): raise ValueError('禁止使用模型自评或生成文本作为监督真值')
        if ref in sources and sources[ref]!=split: raise ValueError('同一来源不得跨数据分割')
        sources[ref]=split
        if not dataset['engineering_only'] and (src.get('kind')!='independent_observation' or src.get('parameter_training') is not True or src.get('reviewed') is not True): raise ValueError('独立数据缺少训练许可或人工复核')
        groups[split].append(row)
    if any(not rows for rows in groups.values()): raise ValueError('必须保留独立训练、验证和测试集')
    if max(r['at'] for r in groups['train'])>=min(r['at'] for r in groups['validation']) or max(r['at'] for r in groups['validation'])>=min(r['at'] for r in groups['test']): raise ValueError('数据分割必须按时间隔离')
    return groups


def _arrays(rows):
    x=np.asarray([[v for key in INPUTS for v in r['inputs'][key]]+[1.] for r in rows],float)
    mask=np.asarray([[v is not None for v in r['targets']] for r in rows],float)
    y=np.asarray([[0. if v is None else v for v in r['targets']] for r in rows],float)
    return x,y,mask


def _metrics(weights, rows):
    x,y,mask=_arrays(rows);p=ed._sigmoid(x@weights.T)
    return {'labels':int(mask.sum()),'mse':float((((p-y)**2)*mask).sum()/mask.sum()),
            'independent_event_groups':len({r['event_group'] for r in rows})}


def train_candidate(model, dataset, epochs=50, learning_rate=.01):
    ed.validate_model(model,model['subject_id']); groups=validate_dataset(dataset)
    if type(epochs) is not int or not 1<=epochs<=500 or type(learning_rate) not in (int,float) or not .00001<=learning_rate<=.05: raise ValueError('训练步数或学习率超出范围')
    params=model['parameters'];weights=np.concatenate([np.asarray(params[k],float) for k in MATRICES]+[np.asarray(params['b0'],float)[:,None]],axis=1)
    original=weights.copy();x,y,mask=_arrays(groups['train']);best=weights.copy();best_loss=_metrics(weights,groups['validation'])['mse'];best_epoch=0
    for epoch in range(epochs):
        p=ed._sigmoid(x@weights.T);gradient=(2*(p-y)*p*(1-p)*mask).T@x/max(1,mask.sum())
        gradient+=.001*(weights-original);weights-=learning_rate*np.clip(gradient,-1,1)
        if not np.isfinite(weights).all():raise ValueError('候选训练未得到有限参数')
        loss=_metrics(weights,groups['validation'])['mse']
        if loss<best_loss:best_loss=loss;best=weights.copy();best_epoch=epoch+1
    candidate=copy.deepcopy(model);offset=0
    for key,n in zip(MATRICES,SIZES):candidate['parameters'][key]=best[:,offset:offset+n].tolist();offset+=n
    candidate['parameters']['b0']=best[:,-1].tolist();candidate['revision']+=1;candidate['steps']=model.get('steps',0)+best_epoch
    candidate['calibration']={'status':'candidate_only_not_validated','psychometric_claim':False,'dataset_sha256':digest(dataset),
        'engineering_only':dataset['engineering_only'],'note':'Independent release protocol and review still required; never activated by fitting.'}
    candidate=ed.seal_model(candidate);ed.validate_model(candidate,model['subject_id'])
    return {'schema':'expressive-drive-training-candidate/1','candidate':candidate,'parent_sha256':model['sha256'],
        'dataset_sha256':digest(dataset),'selected_epoch':best_epoch,
        'baseline':{k:_metrics(original,v) for k,v in groups.items()},'metrics':{k:_metrics(best,v) for k,v in groups.items()},
        'release_eligible':False,'runtime_activated':False,'profile_written':False,
        'release_blockers':['independent_measurement_protocol_and_release_review_required'],
        'interpretation':'Fits explicit proxy targets for the existing ED logits. These labels are not personality truth or proof of psychological causality.'}
