"""Independent shared-core and per-identity adapter/checkpoint versioning."""
from __future__ import annotations
import copy,json,re
from pathlib import Path
from .common import atomic_json,uid,now
from .learned_pmm import LearnedPMM,checked_params,EXTRA_SHAPES,hash_json
from .pmm import DIM,LATENT,SHAPES
from .registry_pmm import RegistryPMM,SHAPES as FULL_SHAPES,EXTRA_SHAPES as FULL_EXTRA,DIM as FULL_DIM
from .registry import CONTRACT,N
from .pmm_interface import create_pmm,load_numeric,digest


def from_core(core,identity):
    if isinstance(core,dict) and core.get('format')=='pmm-core/2.1':
        if core.get('dimension')!=FULL_DIM or core.get('latent')!=LATENT or core.get('registry_contract')!=CONTRACT:raise ValueError('心理核心注册表不兼容')
        model=RegistryPMM(identity=identity)
        for k,v in checked_params(core.get('parameters'),FULL_SHAPES).items():setattr(model,k,v)
        model.core_extra=checked_params(core.get('extra'),FULL_EXTRA);model.core_feature_steps=model.check_counts(core.get('feature_steps'));model.core_origin='shared_core'
        model.core_steps=int(max(model.core_feature_steps));model.steps=model.core_steps
        return model
    if not isinstance(core,dict) or core.get('format')!='pmm-core/2' or core.get('dimension')!=DIM or core.get('latent')!=LATENT:raise ValueError('共享核心格式不兼容')
    parameters=checked_params(core.get('parameters'),SHAPES);extra=checked_params(core.get('extra'),EXTRA_SHAPES)
    model=LearnedPMM(identity=identity)
    for k,v in parameters.items():setattr(model,k,v)
    model.core_extra=extra;model.core_origin='shared_core';return model


class VersionFiles:
    def __init__(self,path):self.path=Path(path);self.catalog=self.path/'index.json'
    def list(self):return json.loads(self.catalog.read_text('utf8')) if self.catalog.exists() else []
    def put(self,payload,label,**metadata):
        identifier=uid();entry={'id':identifier,'label':str(label).strip()[:100] or '未命名版本','created_at':now(),'sha256':hash_json(payload),**metadata}
        atomic_json(self.path/(identifier+'.json'),payload);atomic_json(self.catalog,[entry,*self.list()][:30]);return entry
    def read(self,identifier):
        if not isinstance(identifier,str) or not re.fullmatch('[0-9a-f]{32}',identifier):raise ValueError('版本标识无效')
        entry=next((v for v in self.list() if v['id']==identifier),None)
        if entry is None:raise ValueError('版本不存在')
        payload=json.loads((self.path/(identifier+'.json')).read_text('utf8'))
        if hash_json(payload)!=entry['sha256']:raise ValueError('版本文件校验失败')
        return payload,entry


class PMMVersions:
    def weight_files(self):return VersionFiles(self.store.directory/'versions'/'weights')
    def core_files(self):return VersionFiles(getattr(self.config,'shared_root',self.config.path.parent)/'shared_cores')
    def pmm_versions(self):
        return {'weights':self.weight_files().list(),'cores':self.core_files().list(),'model':self.model_info()}
    def save_weight_version(self,label='手动检查点'):
        with self.lock:
            p=self.model.export();m=load_numeric(p,self.profile()['id'])
            return self.weight_files().put({'identity_id':self.profile()['id'],'checkpoint':p},label,core_sha256=m.core_hash() if isinstance(m,LearnedPMM) else None,adapter_id=m.adapter_id if isinstance(m,LearnedPMM) else None,steps=m.steps)
    def install_numeric(self,candidate,event):
        # The caller validates a complete candidate before committing any live data.
        port=create_pmm(self.config.get(),candidate.export(),self.profile()['id'])
        with self.store.lock,self.store.db:self.store.setmeta('pmm_checkpoint',port.export());self.store.event(event,{'checkpoint_sha256':digest(port.export())})
        self.model=port;return {'ok':True,'model':self.model_info()}
    def activate_weight_version(self,identifier):
        with self.lock:
            payload,_=self.weight_files().read(identifier)
            if payload['identity_id']!=self.profile()['id']:raise ValueError('版本不属于当前人格')
            candidate=load_numeric(payload['checkpoint'],self.profile()['id'])
            create_pmm(self.config.get(),candidate.export(),self.profile()['id'])
            self.save_weight_version('回退前自动备份');return self.install_numeric(candidate,'pmm_version_activated')
    def learned_model(self):
        model=load_numeric(self.model.export(),self.profile()['id'])
        if not isinstance(model,LearnedPMM):raise ValueError('请先切换 Learned-PMM，建立核心与个体 Adapter')
        return model
    def export_core(self):
        with self.lock:return self.learned_model().core()
    def register_core(self,core,label='导入核心',steps=0):
        with self.lock:
            model=from_core(core,self.profile()['id']);sha=model.core_hash()
            existing=next((e for e in self.core_files().list() if e['core_sha256']==sha),None)
            return existing or self.core_files().put(core,label,core_sha256=sha,core_steps=steps,source_identity=self.profile()['id'])
    def train_core(self,epochs=30,progress=lambda _:None):
        with self.lock:
            from .learning import weights_enabled
            if not weights_enabled(self):raise ValueError('学习策略关闭了自身和语言参数更新；请先调整学习强度')
            if self.mode()!='learned':raise ValueError('共享核心训练需要 Learned-PMM 模式')
            if type(epochs) is not int or not 1<=epochs<=150:raise ValueError('训练轮数应为 1–150')
            current=self.learned_model();neutral=from_core(current.core(),self.profile()['id'])
            neutral.samples=copy.deepcopy(current.samples);neutral.learned_samples=current.learned_samples;neutral.core_steps=current.core_steps;neutral.steps=current.core_steps
            self.ingest_samples(neutral,self.store.meta('pmm_training_records') or [])
            if not any(not s['heldout'] for s in neutral.samples):raise ValueError('还没有可用于核心训练的样本')
            progress('冻结空白 Adapter，独立训练共享核心；当前人格继续保留原版本')
            candidate=create_pmm(self.config.get(),neutral.export(),self.profile()['id']);candidate.fit(epochs,target='core')
            trained=load_numeric(candidate.export(),self.profile()['id']);entry=self.register_core(trained.core(),'核心训练 · '+self.profile()['name'],trained.core_steps)
            with self.store.lock,self.store.db:self.store.event('core_version_trained',{'version':entry,'metrics':trained.metrics})
            return {'ok':True,'version':entry,'metrics':trained.metrics,'activated':False,'message':'新核心已加入共享目录；选择该版本后才会用于当前人格。训练来源仅为当前主体的样本。'}
    def activate_core(self,identifier):
        with self.lock:
            current=self.learned_model();core,entry=self.core_files().read(identifier);candidate=from_core(core,self.profile()['id']);reused=False
            if candidate.core_hash()==current.core_hash():return {'ok':True,'model':self.model_info(),'message':'已经使用此核心'}
            for row in self.weight_files().list():
                if row.get('core_sha256')==candidate.core_hash():
                    payload,_=self.weight_files().read(row['id']);previous=load_numeric(payload['checkpoint'],self.profile()['id']);candidate.load_adapter(previous.export_adapter());reused=True;break
            if isinstance(candidate,RegistryPMM)!=isinstance(current,RegistryPMM):raise ValueError('跨编码器核心切换需先迁移完整检查点，不能混用回放向量')
            candidate.samples=copy.deepcopy(current.samples);candidate.learned_samples=current.learned_samples;candidate.rank=current.rank.copy();candidate.rank_labels=current.rank_labels
            candidate.core_steps=entry.get('core_steps',0);candidate.steps=candidate.core_steps+candidate.adapter_steps
            self.register_core(current.core(),'切换前核心 · '+self.profile()['name'],current.core_steps)
            self.save_weight_version('切换核心前自动备份');result=self.install_numeric(candidate,'pmm_core_activated');result['adapter_reused']=reused
            result['message']='已恢复该核心对应的个体 Adapter' if reused else '新核心已启用，并创建匹配的空白 Adapter；原配对已保存，可随时回退'
            return result
    def export_adapter(self):
        with self.lock:return self.learned_model().export_adapter()
    def import_adapter(self,payload):
        with self.lock:
            candidate=self.learned_model();candidate.load_adapter(payload);candidate.steps=candidate.core_steps+candidate.adapter_steps
            candidate.metrics={}
            self.save_weight_version('导入 Adapter 前自动备份');return self.install_numeric(candidate,'pmm_adapter_imported')
