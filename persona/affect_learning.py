"""Persisted emotion training jobs and release operations; no online trait write."""
from __future__ import annotations
import copy
from .registry import digest
from .affect_runtime import MODELS,migrate
from .affect_training import validate_dataset,train,calibrate,publish,release_gate

def bind_sources(store,dataset,bind=False):
    dataset=copy.deepcopy(dataset);validate_dataset(dataset)
    if dataset['engineering_only']:return dataset
    records={r['id']:r for r in (store.meta('pmm_profile') or {}).get('source_records',[])}
    for row in dataset['rows']:
        source=row['source'];record=records.get(source.get('record_id'));quote=source.get('quote')
        if not record or record.get('source') not in ('human','imported','observed') or record.get('withdrawn') or record.get('scope') not in (None,'self',row['scope']):raise ValueError('情绪监督原始资料不存在、被撤回或跨范围')
        if not isinstance(quote,str) or not quote.strip() or quote not in record.get('text',''):raise ValueError('情绪监督缺少原文匹配')
        if bind:source['bound_source_sha256']=digest(record)
        elif source.get('bound_source_sha256')!=digest(record):raise ValueError('情绪监督原始资料已变化')
    return dataset

class AffectLearning:
    def __init__(self,engine):self.engine=engine;migrate(engine.store)
    def status(self):
        cat=self.engine.store.meta(MODELS)
        return {'subject_id':cat['subject_id'],'revision':cat['revision'],'active':cat['active'],'seed':cat['seed'],
            'versions':[{'version':k,'steps':v['steps'],'training':v['training'],'calibration':v['calibration'],
                'published':k==cat['active'],'frozen':k in cat.get('frozen',[]),'revoked':k in cat.get('revoked',[]),
                'report':cat['reports'].get(k)} for k,v in cat['versions'].items()],
            'datasets':[{'id':k,'rows':len(v['rows']),'engineering_only':v['engineering_only'],'withdrawn':k in cat.get('withdrawn_datasets',[])} for k,v in cat['datasets'].items()],
            'audit':cat['audit'][-30:]}
    def action(self,body):
        st=self.engine.store
        with self.engine.lock,st.lock:
            cat=copy.deepcopy(st.meta(MODELS));revision=cat['revision'];owner=st.meta('identity')['id']
            if body.get('subject_id')!=owner or body.get('expected_revision')!=revision:raise ValueError('情绪训练主体或版本冲突')
            op=body.get('op');version=body.get('version') or cat.get('active') or cat['seed'];created=None
            if op=='import':
                data=bind_sources(st,body['dataset'],True);key=digest(data);cat['datasets'][key]=data;created=key
            elif op=='train':
                if version in cat.get('frozen',[]):raise ValueError('此版本已冻结；先复制为候选或选择其他版本')
                data=cat['datasets'][body['dataset_id']];bind_sources(st,data)
                model,report=train(cat['versions'][version],data,body.get('epochs',30),body.get('lr',.001),body.get('component','all'))
                created=model['sha256'];cat['versions'][created]=model;cat['reports'][created]=report
            elif op=='calibrate':
                report=cat['reports'][version];data=cat['datasets'][report['dataset_sha256']];bind_sources(st,data)
                model,report=calibrate(cat['versions'][version],data,report);created=model['sha256'];cat['versions'][created]=model;cat['reports'][created]=report
            elif op in ('publish','rollback'):
                if version in cat.get('revoked',[]):raise ValueError('此模型版本已撤销')
                if op=='rollback' and not any(a.get('operation')=='publish' and a.get('version')==version for a in cat['audit']):raise ValueError('只能回退到曾正式发布的情绪模型')
                report=cat['reports'].get(version)
                if report:bind_sources(st,cat['datasets'][report['dataset_sha256']])
                cat=publish(cat,version);cat['revision']=revision
            elif op in ('freeze','unfreeze','revoke'):
                if version not in cat['versions']:raise ValueError('情绪模型不存在')
                key='revoked' if op=='revoke' else 'frozen';values=set(cat.get(key,[]))
                values.discard(version) if op=='unfreeze' else values.add(version);cat[key]=sorted(values)
                if op=='revoke' and cat['active']==version:cat['active']=None
            elif op=='withdraw_dataset':
                key=body['dataset_id']
                if key not in cat['datasets']:raise ValueError('数据集不存在')
                cat.setdefault('withdrawn_datasets',[]).append(key)
                affected=[v for v,r in cat['reports'].items() if r['dataset_sha256']==key]
                cat['revoked']=sorted(set(cat.get('revoked',[]))|set(affected))
                if cat['active'] in affected:cat['active']=None
            else:raise ValueError('未知情绪训练操作')
            if op in ('train','calibrate') and (body.get('dataset_id') in cat.get('withdrawn_datasets',[]) or (op=='calibrate' and cat['reports'][version]['dataset_sha256'] in cat.get('withdrawn_datasets',[]))):raise ValueError('数据集已撤回')
            cat['revision']=revision+1;cat['audit'].append({'op':op,'version':version,'created':created,'revision':cat['revision']})
            from .affect_runtime import validate_metadata
            validate_metadata({'identity':{'id':owner},MODELS:cat})
            with st.db:st.setmeta(MODELS,cat);st.event('affect_training_operation',cat['audit'][-1])
            return {'created':created,**self.status()}
