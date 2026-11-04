"""The second model's explicit port: local execution or authenticated PMM HTTP/1.
The caller owns the checkpoint. Remote workers are stateless; a failed request cannot
advance a hidden remote personality while the local conversation rolls back.
"""
from __future__ import annotations
import copy, hashlib, json, re, uuid
from typing import Protocol
import numpy as np
from .pmm import PMM, DIM, LATENT, SEMANTIC_KEYS
from .learned_pmm import LearnedPMM, MODEL_ID as LEARNED_ID
from .registry_pmm import RegistryPMM,MODEL_ID as REGISTRY_ID,DIM as REGISTRY_DIM,checked_vector
from .registry import CONTRACT as REGISTRY_CONTRACT,ORDER,BY_ID
from .psychology import STATE_KEYS, STYLE_KEYS, TRAITS, VALUES, ACTIONS
from .provider import ProviderError, request_json, validate_url

CONTRACT='pmm-http/1'
MODEL_ID='pmm-mlp-v3'
MAX_BYTES=32_000_000
OPERATIONS=('encode','decode','train','rank_feedback','inspect')


def digest(checkpoint):
    return hashlib.sha256(json.dumps(checkpoint,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


class PMMPort(Protocol):
    """Implementations must preserve the checkpoint contract and caller's identity."""
    def encode_many(self, vectors): ...
    def decode(self, x, memory_vectors=None): ...
    def add(self, identifier, x, **labels): ...
    def fit(self, epochs=12): ...
    def rank_feedback(self, components, relevant): ...
    def export(self): ...
    def info(self): ...
    def fork(self): ...
    def test(self): ...


def finite_array(value, shape, bound=4):
    x=np.asarray(value,dtype=float)
    if x.shape!=shape or not np.isfinite(x).all() or (np.abs(x)>bound).any():raise ValueError('PMM 数值、维度或范围不正确')
    return x


def validate_decoded(d,count):
    if not isinstance(d,dict):raise ValueError('PMM 解码结果不是对象')
    finite_array(d['latent'],(LATENT,),1.0001)
    for domain,keys in (('state',STATE_KEYS),('action_probabilities',ACTIONS),('memory_semantic',SEMANTIC_KEYS)):
        if set(d[domain])!=set(keys):raise ValueError('PMM 解码字段不完整')
        for key,n in d[domain].items():
            if isinstance(n,bool) or not isinstance(n,(int,float)) or not np.isfinite(n) or not (-1 if domain=='state' and key=='valence' else 0)<=n<=1:raise ValueError('PMM 解码数值越界')
    if abs(sum(d['action_probabilities'].values())-1)>1e-5:raise ValueError('PMM 行动概率未归一化')
    for domain,keys in (('traits',TRAITS),('values',VALUES)):
        v=d['personality'][domain]
        if set(v)!=set(keys) or any(not isinstance(n,(int,float)) or not np.isfinite(n) or not 0<=n<=1 for n in v.values()):raise ValueError('PMM 人格解码无效')
    a=finite_array(d['style'],(len(STYLE_KEYS),),1)
    if (a<0).any():raise ValueError('PMM 风格解码无效')
    weights=finite_array(d['memory_read_weights'],(count,),1)
    if (weights<0).any() or (count and abs(weights.sum()-1)>1e-5):raise ValueError('PMM 记忆读取权重无效')
    if not 0<=float(d['influence'])<=.35 or not np.isfinite(d['reconstruction_error']) or d['reconstruction_error']<0:raise ValueError('PMM 解码状态无效')
    if d.get('mode')=='learned':
        from .learned_pmm import LINGUISTIC_KEYS
        w=finite_array(d['perspective_weights'],(3,),1)
        if (w<0).any() or abs(w.sum()-1)>1e-5:raise ValueError('视角权重无效')
        finite_array(d['perspective_offsets'],(3,10),.25)
        if set(d['linguistic'])!=set(LINGUISTIC_KEYS):raise ValueError('语言解码字段无效')
        lang=finite_array([d['linguistic'][k] for k in LINGUISTIC_KEYS],(4,),1)
        if (lang<0).any():raise ValueError('语言解码值无效')
    if 'psychology_prediction' in d:
        if d.get('registry_contract')!=REGISTRY_CONTRACT or set(d['psychology_prediction'])!=set(ORDER):raise ValueError('心理预测注册表不兼容')
        weights=d.get('registry_view_weights',{})
        if set(weights)!=set(('__baseline__',*ORDER)):raise ValueError('动态视角权重字段不完整')
        vals=finite_array(list(weights.values()),(len(ORDER)+1,),1)
        if (vals<0).any() or abs(vals.sum()-1)>1e-5:raise ValueError('动态视角权重无效')
        for k,n in d['psychology_prediction'].items():
            if n is not None and (type(n) not in (int,float) or not np.isfinite(n) or not BY_ID[k]['minimum']<=n<=1):raise ValueError('心理预测值无效')
    return d


class LocalPMM(PMM):
    backend='local'
    def __init__(self,payload=None,identity='',config=None):
        super().__init__(payload=payload);self.identity=identity;self.connection=copy.deepcopy(config or {})
    def encode_many(self,vectors):return np.stack([self.encode(v) for v in vectors]) if len(vectors) else np.empty((0,LATENT))
    def fork(self):return LocalPMM(self.export(),self.identity,self.connection)
    def info(self):return {**super().info(),'backend':'local','model_id':MODEL_ID,'contract':CONTRACT,'checkpoint_sha256':digest(self.export())}
    def test(self):
        validate_decoded(self.decode(np.zeros(DIM)),0)
        return {'ok':True,'message':'PMM 本地编解码正常，权重与训练数据保持不变','backend':self.backend,'model':MODEL_ID,'identity_id':self.identity,'checkpoint_sha256':digest(self.export())}


class RemotePMM:
    backend='http'
    def __init__(self,payload=None,identity='',config=None):
        self.connection=copy.deepcopy(config or {});self.identity=identity
        self._checkpoint=load_numeric(payload,identity) # validation / replay staging only, no local inference or gradients
    def __getattr__(self,name):
        if name in ('samples','rank','steps','metrics','learned_samples','rank_labels','dimension'):return getattr(self._checkpoint,name)
        raise AttributeError(name)
    def export(self):return self._checkpoint.export()
    def fork(self):return RemotePMM(self.export(),self.identity,self.connection)
    def _rpc(self,operation,arguments):
        c=self.connection;checkpoint=self.export();request_id=uuid.uuid4().hex
        body={'contract':CONTRACT,'request_id':request_id,'identity_id':self.identity,'model':c['model'],
              'checkpoint_sha256':digest(checkpoint),'checkpoint':checkpoint,'operation':operation,'arguments':arguments}
        base=validate_url(c['base_url'])
        if base.endswith('/v1/pmm/execute'):base=base[:-len('/v1/pmm/execute')]
        r=request_json(base+'/v1/pmm/execute',body,c.get('api_key',''),c.get('timeout',120),max_bytes=MAX_BYTES)
        if any(r.get(k)!=body[k] for k in ('contract','request_id','identity_id','model','checkpoint_sha256')):
            raise ProviderError('PMM 响应身份、请求或权重版本不匹配；本轮未提交')
        if operation in ('train','rank_feedback'):
            try:
                new=load_numeric(r['checkpoint'],self.identity)
                if digest(new.export())!=r.get('next_checkpoint_sha256'):raise ValueError()
                if new.steps<self.steps or new.learned_samples<self.learned_samples:raise ValueError()
                if new.samples!=self.samples:raise ValueError()
                if isinstance(new,LearnedPMM):
                    old=self._checkpoint
                    if not isinstance(old,LearnedPMM):raise ValueError()
                    if operation=='rank_feedback' or arguments.get('target','adapter')=='adapter':
                        if new.core_hash()!=old.core_hash() or new.core_steps!=old.core_steps:raise ValueError()
                    elif new.export_adapter()['parameters']!=old.export_adapter()['parameters'] or new.adapter_steps!=old.adapter_steps:raise ValueError()
            except (ValueError,KeyError,TypeError):raise ProviderError('PMM 返回的权重未通过完整性检查；本轮未提交') from None
            self._checkpoint=new
        return r.get('result')
    def encode_many(self,vectors):
        if not len(vectors):return np.empty((0,LATENT))
        output=[]
        dimension=getattr(self._checkpoint,'dimension',DIM)
        for start in range(0,len(vectors),512):
            batch=[finite_array(v,(dimension,)).tolist() for v in vectors[start:start+512]]
            result=self._rpc('encode',{'vectors':batch})
            try:output.extend(finite_array(result,(len(batch),LATENT),1.0001))
            except (ValueError,TypeError):raise ProviderError('PMM 编码响应维度无效') from None
        return np.asarray(output)
    def encode(self,x):return self.encode_many([x])[0]
    def decode(self,x,memory_vectors=None):
        dimension=getattr(self._checkpoint,'dimension',DIM)
        bank=[] if memory_vectors is None else memory_vectors
        result=self._rpc('decode',{'x':finite_array(x,(dimension,)).tolist(),'memory_vectors':[finite_array(v,(dimension,)).tolist() for v in bank]})
        try:
            if isinstance(self._checkpoint,LearnedPMM) and (result.get('mode')!='learned' or result.get('core_sha256')!=self._checkpoint.core_hash() or result.get('adapter_id')!=self._checkpoint.adapter_id):raise ValueError('Learned-PMM 解码身份不一致')
            if isinstance(self._checkpoint,RegistryPMM) and result.get('registry_contract')!=REGISTRY_CONTRACT:raise ValueError('心理注册表不匹配')
            return validate_decoded(result,len(bank))
        except (ValueError,KeyError,TypeError):raise ProviderError('PMM 解码响应未通过校验') from None
    def add(self,*args,**kwargs):return self._checkpoint.add(*args,**kwargs)
    def fit(self,epochs=12,target='adapter'):
        self._rpc('train',{'epochs':int(epochs),'target':target});return self.info()
    def rank_feedback(self,components,relevant):self._rpc('rank_feedback',{'components':list(components),'relevant':bool(relevant)})
    def info(self):
        return {**self._checkpoint.info(),'backend':'http','model_id':self.connection['model'],'contract':CONTRACT,'checkpoint_sha256':digest(self.export()),
                'note':'独立 PMM HTTP 服务执行编解码与梯度训练；主体与检查点由当前程序事务保存。'}
    def test(self):
        dimension=getattr(self._checkpoint,'dimension',DIM)
        self.encode_many([np.zeros(dimension)]);self.decode(np.zeros(dimension))
        return {'ok':True,'message':'PMM HTTP 鉴权、编码与解码通过；未训练或改写当前主体','backend':'http','model':self.connection['model'],'identity_id':self.identity,'checkpoint_sha256':digest(self.export())}


def load_numeric(payload,identity='',config=None):
    if isinstance(payload,dict) and payload.get('format')=='learned-pmm/2.1':return RegistryPMM(payload,identity,config)
    if isinstance(payload,dict) and payload.get('format')=='learned-pmm/2':return LearnedPMM(payload,identity,config)
    return LocalPMM(payload,identity,config)


def create_pmm(config,payload,identity):
    c=copy.deepcopy(config.get('pmm',{'mode':'legacy','backend':'local','model':MODEL_ID}));mode=c.get('mode','legacy')
    if mode=='api':return load_numeric(payload,identity) # preserved inactive checkpoint; never executes in API-PMM loop
    if mode=='learned':
        numeric=RegistryPMM(payload,identity,c);c['model']=REGISTRY_ID
        return RemotePMM(numeric.export(),identity,c) if c['backend']=='http' else numeric
    if isinstance(payload,dict) and payload.get('format') in ('learned-pmm/2','learned-pmm/2.1'):raise ValueError('当前权重属于 Learned-PMM，请选择训练模式或 API 模式')
    if c['backend']=='local' and c['model']!=MODEL_ID:raise ValueError('旧版模型标识应为 pmm-mlp-v3')
    return (RemotePMM if c['backend']=='http' else LocalPMM)(payload,identity,c)


def execute_request(body):
    """Server side, pure request -> response. Nothing is persisted or shared by identity."""
    if not isinstance(body,dict) or body.get('contract')!=CONTRACT:raise ValueError('PMM 合约版本不匹配')
    if body.get('model') not in (MODEL_ID,LEARNED_ID,REGISTRY_ID):raise ValueError('服务未装载此 PMM 模型')
    for key in ('request_id','identity_id'):
        if not re.fullmatch('[a-f0-9]{32}',str(body.get(key,''))):raise ValueError('请求或主体标识无效')
    payload=body.get('checkpoint')
    if not isinstance(payload,dict) or digest(payload)!=body.get('checkpoint_sha256'):raise ValueError('PMM 输入权重摘要不匹配')
    model=load_numeric(payload,body['identity_id'])
    expected=REGISTRY_ID if isinstance(model,RegistryPMM) else LEARNED_ID if isinstance(model,LearnedPMM) else MODEL_ID
    if body['model']!=expected:raise ValueError('模型标识与检查点不匹配')
    dimension=getattr(model,'dimension',DIM)
    op=body.get('operation');a=body.get('arguments',{})
    if not isinstance(a,dict):raise ValueError('PMM 参数必须是对象')
    if op=='encode':
        vectors=a.get('vectors')
        if not isinstance(vectors,list) or not 1<=len(vectors)<=512:raise ValueError('单批编码应为 1–512 个向量')
        result=[model.encode(finite_array(v,(dimension,))).tolist() for v in vectors]
    elif op=='decode':
        bank=a.get('memory_vectors',[])
        if not isinstance(bank,list) or len(bank)>40:raise ValueError('PMM 记忆读取最多 40 条')
        result=model.decode(finite_array(a.get('x'),(dimension,)),[finite_array(v,(dimension,)) for v in bank])
    elif op=='train':
        epochs=a.get('epochs',12)
        if type(epochs) is not int or not 1<=epochs<=150:raise ValueError('训练轮数应为 1–150')
        if isinstance(model,LearnedPMM):model.fit(epochs,a.get('target','adapter'))
        else:model.fit(epochs)
        result=model.info()
    elif op=='rank_feedback':
        components=finite_array(a.get('components'),(4,),1)
        if (components<0).any() or not isinstance(a.get('relevant'),bool):raise ValueError('检索监督标签无效')
        model.rank_feedback(components,a['relevant']);result=model.info()
    elif op=='inspect':result=model.info()
    else:raise ValueError('未知 PMM 操作')
    response={k:body[k] for k in ('contract','request_id','identity_id','model','checkpoint_sha256')};response['result']=result
    if op in ('train','rank_feedback'):
        response['checkpoint']=model.export();response['next_checkpoint_sha256']=digest(response['checkpoint'])
    return response
