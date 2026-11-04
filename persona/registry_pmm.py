"""Masked registry encoder and 93 evidence-supervised output heads.
Legacy parameters occupy an unchanged prefix; migration zero-initializes new paths.
"""
from __future__ import annotations
import copy, re
import numpy as np
from .pmm import PMM,DIM as LEGACY_DIM,LATENT,SHAPES as OLD_SHAPES,LEX,SEMANTIC_KEYS,softmax
from .learned_pmm import LearnedPMM,RANK,STATE_START,LINGUISTIC_KEYS,EXTRA_SHAPES as OLD_EXTRA,checked_params,hash_json
from .psychology import STATE_KEYS,STYLE_KEYS,ACTIONS,TRAITS,VALUES
from .common import uid,clamp
from .registry import CONTRACT,ORDER,N,BY_ID,KINDS,TEMPORALITY

MODEL_ID='learned-pmm-v21';DIM=LEGACY_DIM+N*2
LOSS_GROUPS={kind:[i for i,k in enumerate(ORDER) if KINDS[k]==kind] for kind in dict.fromkeys(KINDS.values())}
SHAPES={**OLD_SHAPES,'E':(LATENT,DIM),'D':(DIM,LATENT),'db':(DIM,)}
EXTRA_SHAPES={**OLD_EXTRA,'F':(N,LATENT),'fb':(N,),'W':(N+1,LATENT),'wb':(N+1,)}
ADAPTER_SHAPES={'C':(LATENT,N*2),'U':(LATENT,RANK),'V':(RANK,LATENT),**{k:SHAPES[k] for k in ('S','sb','Y','yb','A','ab')},**EXTRA_SHAPES}

def checked_vector(x):
    a=np.asarray(x,dtype=float)
    if a.shape!=(DIM,) or not np.isfinite(a).all() or (np.abs(a)>4).any():raise ValueError('Registry-PMM 需要 370 维版本化输入；旧向量须显式迁移')
    values=a[LEGACY_DIM:LEGACY_DIM+N];mask=a[LEGACY_DIM+N:]
    if not np.isin(mask,[0.,1.]).all() or (values<0).any() or (values>1).any() or (values[mask==0]!=0).any():raise ValueError('心理输入值与缺失掩码不一致')
    return a

def checked_target(t):
    if t is None:return None
    if not isinstance(t,list) or len(t)!=N:raise ValueError('心理监督须按注册表提供全部字段，未知为 null')
    for v in t:
        if v is not None and (type(v) not in (int,float) or not np.isfinite(v) or not 0<=v<=1):raise ValueError('心理监督目标须归一化到 0..1 或 null')
    return copy.deepcopy(t)

def target_batch(rows):
    targets=[s.get('psychology_target') or [None]*N for s in rows]
    tf=np.array([[v if v is not None else 0. for v in t] for t in targets])
    mf=np.array([[float(v is not None) for v in t] for t in targets])
    for j,row in enumerate(rows):
        context=row.get('training_context')
        if context:
            validate_training_context(context)
            # Current-event supervision cannot silently label long-term traits.
            if context['target_entity']=='event_state':
                for i,k in enumerate(ORDER):
                    if TEMPORALITY[k]=='long':mf[j,i]=0
    return tf,mf

def validate_training_context(value):
    if not isinstance(value,dict) or value.get('schema')!='typed-supervision/1' or value.get('target_entity') not in ('event_state','trait_promotion','imported_history'):raise ValueError('训练目标时间类型无效')
    if not isinstance(value.get('event_id'),str) or not isinstance(value.get('scope'),str):raise ValueError('训练来源事件或范围缺失')
    if type(value.get('at')) not in (int,float) or not np.isfinite(value['at']) or value['at']<0:raise ValueError('训练来源时间无效')

def grouped_error(prediction,target,mask):
    out=np.zeros_like(prediction)
    for kind,indices in LOSS_GROUPS.items():
        mm=mask[:,indices]
        # Independently normalized objectives: 25 traits do not outweigh 3 VAD
        # channels simply by field count. Missing values never become zeros.
        weight=.25 if kind in ('event_appraisal','regulation_operation') else 1.
        out[:,indices]=weight*2*(prediction[:,indices]-target[:,indices])*mm/np.maximum(1,mm.sum(1,keepdims=True))
    return out

def grouped_metrics(prediction,target,mask):
    result={}
    for kind,indices in LOSS_GROUPS.items():
        m=mask[:,indices];count=int(m.sum())
        result[kind]={'labels':count,'mse':float((((prediction[:,indices]-target[:,indices])**2)*m).sum()/count) if count else None}
    return result

class RegistryPMM(LearnedPMM):
    dimension=DIM
    def __init__(self,payload=None,identity='',config=None):
        self.identity=identity;self.connection=copy.deepcopy(config or {})
        if isinstance(payload,dict) and payload.get('format')=='learned-pmm/2.1':
            self.load(payload);return
        old=LearnedPMM(payload,identity,config);self.__dict__.update(copy.deepcopy(old.__dict__))
        self.E=np.pad(self.E,((0,0),(0,N*2)));self.D=np.pad(self.D,((0,N*2),(0,0)));self.db=np.pad(self.db,(0,N*2))
        for k in ('F','fb','W','wb'):
            self.core_extra[k]=np.zeros(EXTRA_SHAPES[k]);self.adapter[k]=np.zeros(EXTRA_SHAPES[k])
        self.adapter['C']=np.zeros((LATENT,N*2))
        self.core_feature_steps=np.zeros(N,dtype=int);self.adapter_feature_steps=np.zeros(N,dtype=int)
        for s in self.samples:s['x']+= [0.]*(N*2);s['psychology_target']=None
        self.migration={'method':'legacy-prefix-zero-extension/1','from':payload.get('format') if payload else None,'source_sha256':hash_json(payload) if payload else None,'source_dimension':LEGACY_DIM,'target_dimension':DIM}
    def core(self):
        return {'format':'pmm-core/2.1','dimension':DIM,'latent':LATENT,'registry_contract':copy.deepcopy(CONTRACT),
                'parameters':{k:getattr(self,k).tolist() for k in SHAPES},'extra':{k:v.tolist() for k,v in self.core_extra.items()},'feature_steps':self.core_feature_steps.tolist()}
    def export_adapter(self):
        return {'format':'personal-adapter/2.1','id':self.adapter_id,'identity_id':self.identity,'core_sha256':self.core_hash(),'rank':RANK,
                'registry_contract':copy.deepcopy(CONTRACT),'revision':self.adapter_revision,'steps':self.adapter_steps,
                'feature_steps':self.adapter_feature_steps.tolist(),'parameters':{k:v.tolist() for k,v in self.adapter.items()}}
    def load_adapter(self,obj):
        if not isinstance(obj,dict) or obj.get('format')!='personal-adapter/2.1' or obj.get('core_sha256')!=self.core_hash() or obj.get('registry_contract')!=CONTRACT or obj.get('rank')!=RANK:raise ValueError('Adapter 核心或注册表版本不兼容；请迁移完整旧检查点')
        if obj.get('identity_id')!=self.identity or not re.fullmatch('[a-f0-9]{32}',str(obj.get('id',''))):raise ValueError('Adapter 主体标识不一致')
        params=checked_params(obj.get('parameters'),ADAPTER_SHAPES)
        if any(type(obj.get(k)) is not int or obj[k]<0 for k in ('revision','steps')):raise ValueError('Adapter 计数无效')
        counts=self.check_counts(obj.get('feature_steps'))
        self.adapter=params;self.adapter_id=obj['id'];self.adapter_revision=obj['revision'];self.adapter_steps=obj['steps'];self.adapter_feature_steps=counts
    @staticmethod
    def check_counts(values):
        if not isinstance(values,list) or len(values)!=N or any(type(v) is not int or v<0 for v in values):raise ValueError('心理字段训练计数无效')
        return np.array(values,dtype=int)
    def load(self,obj):
        if obj.get('format')!='learned-pmm/2.1' or obj.get('registry_contract')!=CONTRACT:raise ValueError('检查点心理字段合约不兼容')
        core=obj.get('core',{})
        if core.get('format')!='pmm-core/2.1' or core.get('dimension')!=DIM or core.get('latent')!=LATENT or core.get('registry_contract')!=CONTRACT:raise ValueError('心理核心字段或维度不匹配')
        params=checked_params(core.get('parameters'),SHAPES);extra=checked_params(core.get('extra'),EXTRA_SHAPES)
        samples=copy.deepcopy(obj.get('samples',[]))
        for s in samples:
            checked_vector(s['x']);checked_target(s.get('psychology_target'))
            if s.get('training_context'):validate_training_context(s['training_context'])
            vp=s.get('view_preference')
            if vp is not None:
                a=np.asarray(vp,dtype=float)
                if a.shape!=(N+1,) or not np.isfinite(a).all() or (a<0).any() or abs(a.sum()-1)>1e-6:raise ValueError('动态视角监督无效')
        # Reuse strict legacy scalar/replay validation without reinterpreting its feature prefix.
        legacy=copy.deepcopy(obj);legacy['format']='learned-pmm/2'
        legacy['core']={'format':'pmm-core/2','dimension':LEGACY_DIM,'latent':LATENT,'parameters':{k:v.tolist() for k,v in params.items()},'extra':{k:extra[k].tolist() for k in OLD_EXTRA}}
        legacy['core']['parameters'].update(E=params['E'][:,:LEGACY_DIM].tolist(),D=params['D'][:LEGACY_DIM].tolist(),db=params['db'][:LEGACY_DIM].tolist())
        legacy['core_sha256']=hash_json(legacy['core']);legacy['adapter']['format']='personal-adapter/2';legacy['adapter']['core_sha256']=legacy['core_sha256']
        legacy['adapter']['parameters']={k:v for k,v in legacy['adapter']['parameters'].items() if k not in ('F','fb','W','wb','C')}
        for s in legacy['samples']:s['x']=s['x'][:LEGACY_DIM]
        old=LearnedPMM(legacy,self.identity,self.connection);self.__dict__.update(copy.deepcopy(old.__dict__))
        self.__dict__.update(params);self.core_extra=extra;self.core_feature_steps=self.check_counts(core.get('feature_steps'))
        if obj.get('core_sha256')!=self.core_hash():raise ValueError('心理核心校验摘要不匹配')
        self.load_adapter(obj.get('adapter'));self.samples=samples;self.migration=copy.deepcopy(obj.get('migration',{}))
        if (self.core_feature_steps>self.core_steps).any() or (self.adapter_feature_steps>self.adapter_steps).any():raise ValueError('字段训练计数超过模型计数')
    def export(self):
        obj=LearnedPMM.export(self);obj.update(format='learned-pmm/2.1',registry_contract=copy.deepcopy(CONTRACT),migration=copy.deepcopy(self.migration));return obj
    def fork(self):return RegistryPMM(self.export(),self.identity,self.connection)
    def _latent(self,x):
        x=np.asarray(x,dtype=float)
        if x.ndim not in (1,2):raise ValueError('输入数组秩无效')
        for row in x if x.ndim==2 else [x]:checked_vector(row)
        z0=np.tanh(x@self.E.T+self.eb+x[...,LEGACY_DIM:]@self.adapter['C'].T);h=np.tanh(z0@self.adapter['V'].T)
        raw=z0+h@self.adapter['U'].T;return z0,h,raw,np.clip(raw,-1,1)
    def encode(self,x):return self._latent(x)[-1]
    def encode_many(self,vectors):return self.encode(np.asarray(vectors)) if len(vectors) else np.empty((0,LATENT))
    def effective(self,k):return (self.core_extra[k] if k in EXTRA_SHAPES else getattr(self,k))+self.adapter[k]
    def _heads(self,z,previous):
        return (z@self.effective('S').T+self.effective('sb')+previous@self.effective('T').T,
                z@self.effective('Y').T+self.effective('yb'),softmax(z@self.effective('A').T+self.effective('ab')),
                softmax(z@self.effective('G').T+self.effective('gb')),z@self.effective('L').T+self.effective('lb'),z@self.effective('P').T+self.effective('pb'),z@self.effective('F').T+self.effective('fb'),softmax(z@self.effective('W').T+self.effective('wb')))
    def decode(self,x,memory_vectors=None):
        x=checked_vector(x);z=self.encode(x);weights=[]
        if memory_vectors:
            bank=self.encode_many(memory_vectors);sim=bank@z/(np.linalg.norm(bank,axis=1)*np.linalg.norm(z)+1e-9);w=softmax(sim*3);weights=w.tolist();z=.8*z+.2*(w@bank)
        state,style,actions,views,language,projection,psych,vw=self._heads(z,x[STATE_START:STATE_START+4]);recon=self.D@z+self.db;start=LEX+len(SEMANTIC_KEYS)
        personality={'traits':{k:float(np.clip(recon[start+i],0,1)) for i,k in enumerate(TRAITS)},'values':{k:float(np.clip(recon[start+len(TRAITS)+i],0,1)) for i,k in enumerate(VALUES)}}
        influence=min(.35,self.learned_samples/200) if self.steps else 0.
        return {'latent':z.round(5).tolist(),'state':{k:float(np.clip(state[i],-1 if i==0 else 0,1)) for i,k in enumerate(STATE_KEYS)},'style':np.clip(style,0,1).tolist(),
                'action_probabilities':dict(zip(ACTIONS,actions.tolist())),'perspective_weights':views.tolist(),'perspective_offsets':np.clip(projection,-.25,.25).reshape(3,10).tolist(),'linguistic':dict(zip(LINGUISTIC_KEYS,np.clip(language,0,1).tolist())),
                'personality':personality,'memory_semantic':{k:float(np.clip(recon[LEX+i],0,1)) for i,k in enumerate(SEMANTIC_KEYS)},'memory_read_weights':weights,
                'influence':influence,'reconstruction_error':float(np.mean((recon-x)**2)),'mode':'learned','core_sha256':self.core_hash(),'adapter_id':self.adapter_id,'registry_view_weights':dict(zip(('__baseline__',*ORDER),vw.tolist())),'registry_contract':copy.deepcopy(CONTRACT),'psychology_prediction':{k:(float(np.clip(psych[i],0,1))*2-1 if BY_ID[k]['minimum']==-1 else float(np.clip(psych[i],0,1))) if self.core_feature_steps[i]+self.adapter_feature_steps[i]>0 else None for i,k in enumerate(ORDER)}}
    def add(self,identifier,x,state=None,style=None,action=None,source='weak_llm',group_id=None,perspective=None,linguistic=None,projection=None,psychology_target=None,view_preference=None,training_context=None):
        if training_context is not None:validate_training_context(training_context)
        targets={}
        for key,value,n in (('perspective',perspective,3),('linguistic',linguistic,4),('projection',projection,30)):
            if value is None:targets[key]=None;continue
            a=np.asarray(value,dtype=float)
            if a.shape!=(n,) or not np.isfinite(a).all() or (a<(-.25 if key=='projection' else 0)).any() or (a>(.25 if key=='projection' else 1)).any():raise ValueError('训练监督维度或范围无效')
            if key=='perspective' and abs(a.sum()-1)>1e-6:raise ValueError('视角标签须归一化')
            targets[key]=a.tolist()
        xx=checked_vector(x)
        pt=checked_target(psychology_target)
        vp=None
        if view_preference is not None:
            vp=np.asarray(view_preference,dtype=float)
            if vp.shape!=(N+1,) or not np.isfinite(vp).all() or (vp<0).any() or (vp>1).any() or abs(vp.sum()-1)>1e-6:raise ValueError('动态视角监督分布无效')
            vp=vp.tolist()
        ok=LearnedPMM.add(self,identifier,xx[:LEGACY_DIM],state,style,action,source,group_id,perspective,linguistic,projection)
        if ok:
            self.samples[-1].update(targets,x=xx.tolist(),psychology_target=pt,view_preference=vp)
            if training_context is not None:self.samples[-1]['training_context']=copy.deepcopy(training_context)
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
        tf,mf=target_batch(rows);rm=np.ones_like(x);rm[:,LEGACY_DIM:LEGACY_DIM+N]=x[:,LEGACY_DIM+N:];active=mf.sum(0)>0
        tv=np.array([s.get('view_preference') or [0.]*(N+1) for s in rows]);mv=np.array([s.get('view_preference') is not None for s in rows])[:,None]
        for _ in range(epochs):
            z0,h,raw,z=self._latent(x);ss,yy,aa,gg,ll,pp,ff,vv=self._heads(z,previous);rx=z@self.D.T+self.db
            ew=(vv-tv)*mv*.3;er=2*(rx-x)*rm/DIM;ef=grouped_error(ff,tf,mf);es=(ss-ts)*ms/2;ey=(yy-ty)*my/4;ea=(aa-ta)*ma*.3;eg=(gg-tg)*mg*.2;el=(ll-tl)*ml/2;ep=(pp-tp)*mp/15
            dz=(er@self.D+es@self.effective('S')+ey@self.effective('Y')+ea@self.effective('A')+eg@self.effective('G')+el@self.effective('L')+ep@self.effective('P')+ef@self.effective('F')+ew@self.effective('W'))*(np.abs(raw)<1)
            dh=(dz@self.adapter['U'])*(1-h*h);dz0=(dz+dh@self.adapter['V'])*(1-z0*z0)
            grads={'S':es.T@z/n,'sb':es.mean(0),'Y':ey.T@z/n,'yb':ey.mean(0),'A':ea.T@z/n,'ab':ea.mean(0),'T':es.T@previous/n,'G':eg.T@z/n,'gb':eg.mean(0),'L':el.T@z/n,'lb':el.mean(0),'P':ep.T@z/n,'pb':ep.mean(0),'F':ef.T@z/n,'fb':ef.mean(0),'W':ew.T@z/n,'wb':ew.mean(0)}
            if target=='adapter':
                grads.update(U=dz.T@h/n,V=dh.T@z0/n,C=dz0.T@x[:,LEGACY_DIM:]/n)
                for k,g in grads.items():self.adapter[k]-=.08*np.clip(g,-1,1)
                self.adapter_steps+=1;self.adapter_feature_steps+=active
            else:
                for k,g in grads.items():
                    if k in EXTRA_SHAPES:self.core_extra[k]-=.08*np.clip(g,-1,1)
                    else:setattr(self,k,getattr(self,k)-.08*np.clip(g,-1,1))
                for k,g in {'E':dz0.T@x/n,'eb':dz0.mean(0),'D':er.T@z/n,'db':er.mean(0)}.items():setattr(self,k,getattr(self,k)-.08*np.clip(g,-1,1))
                self.core_steps+=1;self.core_feature_steps+=active
        self.steps=self.core_steps+self.adapter_steps
        if target=='adapter':self.adapter_revision+=1
        self.metrics={'train':self.evaluate(rows),'heldout':self.evaluate([s for s in self.samples if s['heldout']]),'before':before,'target':target}
        return self.info()
    def evaluate(self,rows):
        if not rows:return {'n':0,'state_mse':None,'style_mse':None,'action_accuracy':None,'reconstruction_mse':None,'perspective_cross_entropy':None,'linguistic_mse':None,'projection_mse':None,'psychology_masked_mse':None,'psychology_labels':0}
        x,ms,my,ma,ts,ty,ta=self._batch(rows);mg,ml,tg,tl,mp,tp=self._extra_batch(rows);z=self.encode(x);s,y,a,g,l,p,f,vw=self._heads(z,x[:,STATE_START:STATE_START+4])
        tf,mf=target_batch(rows);rm=np.ones_like(x);rm[:,LEGACY_DIM:LEGACY_DIM+N]=x[:,LEGACY_DIM+N:]
        tv=np.array([s.get('view_preference') or [0.]*(N+1) for s in rows]);mv=np.array([s.get('view_preference') is not None for s in rows])[:,None]
        mse=lambda pred,t,mask,d:float((((pred-t)**2)*mask).sum()/(mask.sum()*d)) if mask.any() else None
        return {'n':len(rows),'state_mse':mse(s,ts,ms,4),'style_mse':mse(y,ty,my,8),'action_accuracy':float(((a.argmax(1)==ta.argmax(1))*ma[:,0]).sum()/ma.sum()) if ma.any() else None,
                'reconstruction_mse':float((((z@self.D.T+self.db-x)**2)*rm).sum()/max(1,rm.sum())),'perspective_cross_entropy':float(-(tg*np.log(g+1e-9)*mg).sum()/mg.sum()) if mg.any() else None,'linguistic_mse':mse(l,tl,ml,4),'projection_mse':mse(p,tp,mp,30),'psychology_masked_mse':float((((f-tf)**2)*mf).sum()/mf.sum()) if mf.any() else None,'psychology_labels':int(mf.sum()),'typed_losses':grouped_metrics(f,tf,mf),'legacy_untyped_samples':sum(not row.get('training_context') for row in rows),'dynamic_view_cross_entropy':float(-(tv*np.log(vw+1e-9)*mv).sum()/mv.sum()) if mv.any() else None}
    def info(self):
        info=LearnedPMM.info(self)
        info.update(model_id=MODEL_ID,architecture=f'{DIM} (184 legacy + {N} values + {N} masks) → 64 + rank-8 Adapter → 93 masked constructs / state / language / action',
            registry_contract=copy.deepcopy(CONTRACT),feature_count=N,trained_features=int(((self.core_feature_steps+self.adapter_feature_steps)>0).sum()),
            migration=copy.deepcopy(self.migration),note='新字段未知为 null；训练损失排除缺失标签。迁移保留旧前缀权重，新增输入路径初始化为零。神经预测不自动写成人格事实。')
        info.update(typed_supervision='typed-supervision/1',loss_groups=list(LOSS_GROUPS),
            unsupported_features=['BEQ_ERQ_PANAS_neural_encoder'],new_disposition_training_steps=0,
            compatibility_mode='legacy93_parameters_with_typed_runtime',
            note='旧93列、核心和Adapter原样兼容；按特质、价值、行为、状态、评价与操作独立掩码/损失训练。BEQ/ERQ/PANAS由显式运行时策略读取，旧神经网络未训练这些新字段。预测不写入长期人格。')
        return info
    def test(self):
        self.decode(np.zeros(DIM))
        return {'ok':True,'message':'完整心理注册表与缺失掩码编解码正常，未更新权重','backend':self.backend,'model':MODEL_ID,'registry_contract':copy.deepcopy(CONTRACT),'checkpoint_sha256':hash_json(self.export())}


def cooperative_blocks(profile):
    """2.8 adapter, independent of the immutable 370-column Legacy contract."""
    from .pmm_contracts import construct_blocks
    return construct_blocks(profile)
