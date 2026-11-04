"""Learned-PMM/2: frozen/shared core theta + identity-specific residual adapter delta.
Real NumPy backpropagation; state transition, perspective gating and linguistic heads.
No claim of pretrained semantic understanding or free-form neural language generation.
"""
from __future__ import annotations
import copy,hashlib,json
import numpy as np
from .pmm import PMM,DIM,LATENT,SHAPES,LEX,SEMANTIC_KEYS,softmax
from .psychology import STATE_KEYS,STYLE_KEYS,ACTIONS,TRAITS,VALUES
from .common import uid,clamp

MODEL_ID='learned-pmm-v2';RANK=8;STATE_START=LEX+len(SEMANTIC_KEYS)+len(TRAITS)+len(VALUES)
EXTRA_SHAPES={'T':(4,4),'G':(3,LATENT),'gb':(3,),'L':(4,LATENT),'lb':(4,),'P':(30,LATENT),'pb':(30,)}
ADAPTER_SHAPES={'U':(LATENT,RANK),'V':(RANK,LATENT),**{k:SHAPES[k] for k in ('S','sb','Y','yb','A','ab')},**EXTRA_SHAPES}
LINGUISTIC_KEYS=('self_reference','hedging','politeness','negation')


def hash_json(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def linguistic_vector(text):
    text=str(text).lower()
    groups=(('我','本人',' i ',' my '),('也许','可能','大概','或许','perhaps','maybe'),('请','谢谢','麻烦','please','thanks'),('不','没','别','不是','not ','never','no '))
    return [min(1.,sum(text.count(w) for w in words)/2) for words in groups]

def checked_params(data,shapes):
    if not isinstance(data,dict) or set(data)!=set(shapes):raise ValueError('Learned-PMM 参数字段不匹配')
    result={}
    for k,shape in shapes.items():
        x=np.asarray(data[k],dtype=float)
        if x.shape!=shape or not np.isfinite(x).all() or (np.abs(x)>100).any():raise ValueError('Learned-PMM 参数形状或数值无效')
        result[k]=x
    return result


class LearnedPMM(PMM):
    backend='local'
    def __init__(self,payload=None,identity='',config=None):
        self.identity=identity;self.connection=copy.deepcopy(config or {})
        super().__init__()
        self.core_extra={k:np.zeros(shape) for k,shape in EXTRA_SHAPES.items()}
        self.core_steps=0;self.adapter_steps=0;self.core_origin='cold_start'
        self.adapter_id=uid();self.adapter_revision=0
        self.adapter={k:np.zeros(shape) for k,shape in ADAPTER_SHAPES.items()}
        self.adapter['V']=np.random.default_rng(4821).normal(0,.04,(RANK,LATENT))
        if payload is not None:
            if payload.get('format')=='pmm/3':
                PMM.import_data(self,payload,save=False);self.core_steps=self.steps;self.core_origin='migrated_v03_v04'
            else:self.load(payload)
    def core(self):
        return {'format':'pmm-core/2','dimension':DIM,'latent':LATENT,'parameters':{k:getattr(self,k).tolist() for k in SHAPES},'extra':{k:v.tolist() for k,v in self.core_extra.items()}}
    def core_hash(self):return hash_json(self.core())
    def export_adapter(self):
        return {'format':'personal-adapter/2','id':self.adapter_id,'identity_id':self.identity,'core_sha256':self.core_hash(),'rank':RANK,'revision':self.adapter_revision,'steps':self.adapter_steps,'parameters':{k:v.tolist() for k,v in self.adapter.items()}}
    def load_adapter(self,obj):
        if not isinstance(obj,dict) or obj.get('format')!='personal-adapter/2' or obj.get('core_sha256')!=self.core_hash() or obj.get('rank')!=RANK:raise ValueError('Adapter 与当前共享核心版本不匹配')
        if self.identity and obj.get('identity_id')!=self.identity:raise ValueError('Adapter 不属于当前人格，请使用人格包载入完整主体')
        import re
        if not re.fullmatch('[a-f0-9]{32}',str(obj.get('id',''))):raise ValueError('Adapter 标识无效')
        params=checked_params(obj.get('parameters'),ADAPTER_SHAPES)
        for k in ('revision','steps'):
            if type(obj.get(k)) is not int or obj[k]<0:raise ValueError('Adapter 训练计数无效')
        self.adapter=params;self.adapter_id=obj['id'];self.adapter_revision=obj['revision'];self.adapter_steps=obj['steps']
    def load(self,obj):
        if not isinstance(obj,dict) or obj.get('format')!='learned-pmm/2':raise ValueError('Learned-PMM 检查点版本无效')
        core=obj.get('core',{})
        if core.get('format')!='pmm-core/2' or core.get('dimension')!=DIM or core.get('latent')!=LATENT:raise ValueError('共享核心结构无效')
        params=checked_params(core.get('parameters'),SHAPES);extra=checked_params(core.get('extra'),EXTRA_SHAPES)
        base=PMM().export();base.update(parameters={k:v.tolist() for k,v in params.items()},samples=obj.get('samples',[]),steps=obj.get('steps',0),learned_samples=obj.get('learned_samples',0),metrics=obj.get('metrics',{}),retrieval_weights=obj.get('retrieval_weights'),retrieval_labels=obj.get('retrieval_labels',0))
        PMM.import_data(self,base,save=False);self.core_extra=extra
        if obj.get('core_sha256')!=self.core_hash():raise ValueError('共享核心摘要不匹配')
        for row in self.samples:
            for field,n in (('perspective',3),('linguistic',4),('projection',30)):
                a=row.get(field)
                if a is not None:
                    x=np.asarray(a,dtype=float)
                    if x.shape!=(n,) or not np.isfinite(x).all() or (x<(-.25 if field=='projection' else 0)).any() or (x>(.25 if field=='projection' else 1)).any():raise ValueError('额外监督标签无效')
                    if field=='perspective' and abs(x.sum()-1)>1e-6:raise ValueError('视角监督标签未归一化')
        self.core_steps=obj.get('core_steps',0);self.core_origin=str(obj.get('core_origin','imported'))[:80]
        if type(self.core_steps) is not int or self.core_steps<0:raise ValueError('核心计数无效')
        if not self.identity:self.identity=obj.get('adapter',{}).get('identity_id','')
        self.load_adapter(obj.get('adapter'));self.steps=self.core_steps+self.adapter_steps
        if obj.get('steps')!=self.steps:raise ValueError('核心与 Adapter 更新计数不一致')
    def export(self):
        return {'format':'learned-pmm/2','core':self.core(),'core_sha256':self.core_hash(),'core_steps':self.core_steps,'core_origin':self.core_origin,
                'adapter':self.export_adapter(),'steps':self.steps,'learned_samples':self.learned_samples,'samples':copy.deepcopy(self.samples),'metrics':copy.deepcopy(self.metrics),'retrieval_weights':self.rank.tolist(),'retrieval_labels':self.rank_labels}
    def fork(self):return LearnedPMM(self.export(),self.identity,self.connection)
    def _latent(self,x):
        x=np.asarray(x);z0=np.tanh(x@self.E.T+self.eb);h=np.tanh(z0@self.adapter['V'].T)
        raw=z0+h@self.adapter['U'].T;return z0,h,raw,np.clip(raw,-1,1)
    def encode(self,x):return self._latent(x)[-1]
    def encode_many(self,vectors):return self.encode(np.asarray(vectors)) if len(vectors) else np.empty((0,LATENT))
    def effective(self,k):return (self.core_extra[k] if k in EXTRA_SHAPES else getattr(self,k))+self.adapter[k]
    def _heads(self,z,previous):
        return (z@self.effective('S').T+self.effective('sb')+previous@self.effective('T').T,
                z@self.effective('Y').T+self.effective('yb'),softmax(z@self.effective('A').T+self.effective('ab')),
                softmax(z@self.effective('G').T+self.effective('gb')),z@self.effective('L').T+self.effective('lb'),z@self.effective('P').T+self.effective('pb'))
    def decode(self,x,memory_vectors=None):
        x=np.asarray(x);z=self.encode(x);weights=[]
        if memory_vectors:
            bank=self.encode_many(memory_vectors);sim=bank@z/(np.linalg.norm(bank,axis=1)*np.linalg.norm(z)+1e-9);w=softmax(sim*3);weights=w.tolist();z=.8*z+.2*(w@bank)
        state,style,actions,views,language,projection=self._heads(z,x[STATE_START:STATE_START+4]);recon=self.D@z+self.db;start=LEX+len(SEMANTIC_KEYS)
        personality={'traits':{k:float(np.clip(recon[start+i],0,1)) for i,k in enumerate(TRAITS)},'values':{k:float(np.clip(recon[start+len(TRAITS)+i],0,1)) for i,k in enumerate(VALUES)}}
        influence=min(.35,self.learned_samples/200) if self.steps else 0.
        return {'latent':z.round(5).tolist(),'state':{k:float(np.clip(state[i],-1 if i==0 else 0,1)) for i,k in enumerate(STATE_KEYS)},'style':np.clip(style,0,1).tolist(),
                'action_probabilities':dict(zip(ACTIONS,actions.tolist())),'perspective_weights':views.tolist(),'perspective_offsets':np.clip(projection,-.25,.25).reshape(3,10).tolist(),'linguistic':dict(zip(LINGUISTIC_KEYS,np.clip(language,0,1).tolist())),
                'personality':personality,'memory_semantic':{k:float(np.clip(recon[LEX+i],0,1)) for i,k in enumerate(SEMANTIC_KEYS)},'memory_read_weights':weights,
                'influence':influence,'reconstruction_error':float(np.mean((recon-x)**2)),'mode':'learned','core_sha256':self.core_hash(),'adapter_id':self.adapter_id}
    def add(self,identifier,x,state=None,style=None,action=None,source='weak_llm',group_id=None,perspective=None,linguistic=None,projection=None):
        targets={}
        for key,value,n in (('perspective',perspective,3),('linguistic',linguistic,4),('projection',projection,30)):
            if value is None:targets[key]=None;continue
            a=np.asarray(value,dtype=float)
            if a.shape!=(n,) or not np.isfinite(a).all() or (a<(-.25 if key=='projection' else 0)).any() or (a>(.25 if key=='projection' else 1)).any():raise ValueError('训练监督维度或范围无效')
            if key=='perspective' and abs(a.sum()-1)>1e-6:raise ValueError('视角标签须归一化')
            targets[key]=a.tolist()
        ok=super().add(identifier,x,state,style,action,source,group_id)
        if ok:self.samples[-1].update(targets)
        return ok
    def _extra_batch(self,rows):
        mg=np.array([s.get('perspective') is not None for s in rows])[:,None];ml=np.array([s.get('linguistic') is not None for s in rows])[:,None]
        mp=np.array([s.get('projection') is not None for s in rows])[:,None]
        return mg,ml,np.array([s.get('perspective') or [0]*3 for s in rows]),np.array([s.get('linguistic') or [0]*4 for s in rows]),mp,np.array([s.get('projection') or [0]*30 for s in rows])
    def fit(self,epochs=12,target='adapter'):
        if target not in ('adapter','core'):raise ValueError('训练目标应为 adapter 或 core')
        if type(epochs) is not int or not 1<=epochs<=150:raise ValueError('训练轮数应为 1–150')
        rows=[s for s in self.samples if not s['heldout']]
        if not rows:return self.info()
        x,ms,my,ma,ts,ty,ta=self._batch(rows);mg,ml,tg,tl,mp,tp=self._extra_batch(rows);previous=x[:,STATE_START:STATE_START+4];n=len(rows)
        before=self.evaluate(rows)
        for _ in range(epochs):
            z0,h,raw,z=self._latent(x);ss,yy,aa,gg,ll,pp=self._heads(z,previous);rx=z@self.D.T+self.db
            er=2*(rx-x)/DIM;es=(ss-ts)*ms/2;ey=(yy-ty)*my/4;ea=(aa-ta)*ma*.3;eg=(gg-tg)*mg*.2;el=(ll-tl)*ml/2;ep=(pp-tp)*mp/15
            dz=(er@self.D+es@self.effective('S')+ey@self.effective('Y')+ea@self.effective('A')+eg@self.effective('G')+el@self.effective('L')+ep@self.effective('P'))*(np.abs(raw)<1)
            dh=(dz@self.adapter['U'])*(1-h*h);dz0=(dz+dh@self.adapter['V'])*(1-z0*z0)
            grads={'S':es.T@z/n,'sb':es.mean(0),'Y':ey.T@z/n,'yb':ey.mean(0),'A':ea.T@z/n,'ab':ea.mean(0),'T':es.T@previous/n,'G':eg.T@z/n,'gb':eg.mean(0),'L':el.T@z/n,'lb':el.mean(0),'P':ep.T@z/n,'pb':ep.mean(0)}
            if target=='adapter':
                grads.update(U=dz.T@h/n,V=dh.T@z0/n)
                for k,g in grads.items():self.adapter[k]-=.08*np.clip(g,-1,1)
                self.adapter_steps+=1
            else:
                for k,g in grads.items():
                    if k in EXTRA_SHAPES:self.core_extra[k]-=.08*np.clip(g,-1,1)
                    else:setattr(self,k,getattr(self,k)-.08*np.clip(g,-1,1))
                for k,g in {'E':dz0.T@x/n,'eb':dz0.mean(0),'D':er.T@z/n,'db':er.mean(0)}.items():setattr(self,k,getattr(self,k)-.08*np.clip(g,-1,1))
                self.core_steps+=1
        self.steps=self.core_steps+self.adapter_steps
        if target=='adapter':self.adapter_revision+=1
        self.metrics={'train':self.evaluate(rows),'heldout':self.evaluate([s for s in self.samples if s['heldout']]),'before':before,'target':target}
        return self.info()
    def evaluate(self,rows):
        if not rows:return {'n':0,'state_mse':None,'style_mse':None,'action_accuracy':None,'reconstruction_mse':None,'perspective_cross_entropy':None,'linguistic_mse':None,'projection_mse':None}
        x,ms,my,ma,ts,ty,ta=self._batch(rows);mg,ml,tg,tl,mp,tp=self._extra_batch(rows);z=self.encode(x);s,y,a,g,l,p=self._heads(z,x[:,STATE_START:STATE_START+4])
        mse=lambda pred,t,mask,d:float((((pred-t)**2)*mask).sum()/(mask.sum()*d)) if mask.any() else None
        return {'n':len(rows),'state_mse':mse(s,ts,ms,4),'style_mse':mse(y,ty,my,8),'action_accuracy':float(((a.argmax(1)==ta.argmax(1))*ma[:,0]).sum()/ma.sum()) if ma.any() else None,
                'reconstruction_mse':float(np.mean((z@self.D.T+self.db-x)**2)),'perspective_cross_entropy':float(-(tg*np.log(g+1e-9)*mg).sum()/mg.sum()) if mg.any() else None,'linguistic_mse':mse(l,tl,ml,4),'projection_mse':mse(p,tp,mp,30)}
    def info(self):
        return {'architecture':f'{DIM} → {LATENT} + rank-{RANK} Adapter → 状态转移 / 风格 / 行动 / 视角 / 语用',
                'mode':'learned','backend':self.backend,'model_id':MODEL_ID,'core_sha256':self.core_hash(),'adapter_id':self.adapter_id,'adapter_revision':self.adapter_revision,
                'core_steps':self.core_steps,'adapter_steps':self.adapter_steps,'steps':self.steps,'samples':len(self.samples),'learned_samples':self.learned_samples,
                'train_samples':sum(not s['heldout'] for s in self.samples),'heldout_samples':sum(s['heldout'] for s in self.samples),'metrics':copy.deepcopy(self.metrics),'retrieval_labels':self.rank_labels,
                'status':'尚未训练' if not self.steps else '已有参数学习，需验证泛化','checkpoint_sha256':hash_json(self.export()),
                'note':'默认增量训练仅更新个体 Adapter，核心 θ 保持不变；独立核心训练产生新版本。语用头预测可测表达特征，最终自然语言由 General LLM 实现。'}
    def test(self):
        value=self.decode(np.zeros(DIM))
        if not np.isfinite(value['style']).all():raise ValueError('Learned-PMM 解码失败')
        return {'ok':True,'message':'Learned-PMM 编码、状态转移与表达解码正常；未改写权重','backend':self.backend,'model':MODEL_ID,'identity_id':self.identity,'checkpoint_sha256':hash_json(self.export())}
