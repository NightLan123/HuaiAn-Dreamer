"""Local trainable psychological memory module; no third language model.
Context encoder -> 64-dimensional bottleneck -> feature, state, style and action decoders.
Trains on imported speech and interaction feedback; a chronological/source hash holdout
is excluded from gradient updates. Retrieval retains source text, never reconstructs facts.
"""
from __future__ import annotations
import hashlib, math, re, copy
import numpy as np
from .common import atomic_json, clamp
from .psychology import TRAITS, VALUES, STATE_KEYS, STYLE_KEYS, ACTIONS, style_vector

SEMANTIC_KEYS=('social','task','autobiographical','general_knowledge','current_information','ambiguity','hostility','closeness','disengagement','urgency','novelty','goal_congruence','agency','certainty','value_conflict','needs_answer','complexity')
LEX=128; DIM=LEX+len(SEMANTIC_KEYS)+len(TRAITS)+len(VALUES)+4+3+8+4+5; LATENT=64
SHAPES={'E':(LATENT,DIM),'eb':(LATENT,), 'D':(DIM,LATENT),'db':(DIM,),
        'S':(4,LATENT),'sb':(4,), 'Y':(8,LATENT),'yb':(8,), 'A':(len(ACTIONS),LATENT),'ab':(len(ACTIONS),)}


def lexical(text):
    text=''.join(str(text).lower().split())[:10000];x=np.zeros(LEX)
    tokens=re.findall('[a-z0-9_]{2,}|[\u3400-\u9fff]',text)+[text[i:i+2] for i in range(len(text)-1)]
    for t in tokens:
        h=hashlib.blake2b(t.encode(),digest_size=8).digest();x[int.from_bytes(h[:4],'little')%LEX]+=1 if h[4]&1 else -1
    return x/(np.linalg.norm(x)+1e-9)


def vector(text,understanding=None,profile=None,state=None,relation=None,activity=None):
    u=understanding or {};p=profile or {};s=state or {};r=relation or {}
    sem=u.get('semantic',u)
    return np.concatenate((lexical(text),[clamp(sem.get(k,0)) for k in SEMANTIC_KEYS],
        [p.get('traits',{}).get(k,{}).get('value',.5) for k in TRAITS],
        [p.get('values',{}).get(k,{}).get('value',.5) for k in VALUES],
        [s.get(k,0 if k=='valence' else .5) for k in STATE_KEYS],
        [r.get(k,.5) for k in ('trust','familiarity','affection')],p.get('style',{}).get('vector',[0]*8),
        [(activity or {}).get('mood',{}).get(k,0 if k=='valence' else .5) for k in STATE_KEYS],
        [(activity or {}).get('dispositions',{}).get(k,.5) for k in TRAITS])).astype(float)


def softmax(a):
    a=np.exp(a-a.max(axis=-1,keepdims=True));return a/a.sum(axis=-1,keepdims=True)


class PMM:
    def __init__(self,path=None,payload=None):
        from pathlib import Path
        self.path=Path(path) if path else None
        self.steps=0;self.learned_samples=0;self.samples=[];self.metrics={};self.rank=np.array([.35,.45,.12,.08]);self.rank_labels=0
        rng=np.random.default_rng(20261023)
        for k,shape in SHAPES.items():setattr(self,k,np.zeros(shape))
        self.E=rng.normal(0,.06,SHAPES['E']);self.D=self.E.T.copy()
        self.sb=np.array([0,.25,.15,.65]);self.yb=np.array([.15,0,0,0,0,0,0,.2])
        if payload is not None:self.import_data(payload,save=False)
        elif self.path and self.path.exists():
            import json
            self.import_data(json.loads(self.path.read_text('utf8')),save=False)
    def encode(self,x):return np.tanh(self.E@np.asarray(x)+self.eb)
    def decode(self,x,memory_vectors=None):
        x=np.asarray(x);z=self.encode(x);read_weights=[]
        if memory_vectors:
            bank=np.stack([self.encode(v) for v in memory_vectors]);similarity=bank@z/(np.linalg.norm(bank,axis=1)*np.linalg.norm(z)+1e-9)
            weights=softmax(similarity*3);read_weights=weights.tolist()
            # Read sources through the same learned encoder, then decode the active memory state.
            z=.8*z+.2*(weights@bank)
        out=self.S@z+self.sb;sty=np.clip(self.Y@z+self.yb,0,1);reconstruction=self.D@z+self.db
        start=LEX+len(SEMANTIC_KEYS);decoded_traits={k:float(np.clip(reconstruction[start+i],0,1)) for i,k in enumerate(TRAITS)}
        start+=len(TRAITS);decoded_values={k:float(np.clip(reconstruction[start+i],0,1)) for i,k in enumerate(VALUES)}
        # This is a bounded influence factor, not an accuracy/confidence probability.
        weight=min(.35,self.learned_samples/200)
        return {'latent':z.round(5).tolist(),'state':{k:float(np.clip(out[i],-1 if i==0 else 0,1)) for i,k in enumerate(STATE_KEYS)},
                'style':sty.tolist(),'action_probabilities':dict(zip(ACTIONS,softmax(self.A@z+self.ab).tolist())),
                'personality':{'traits':decoded_traits,'values':decoded_values},'memory_semantic':{k:float(np.clip(reconstruction[LEX+i],0,1)) for i,k in enumerate(SEMANTIC_KEYS)},
                'memory_read_weights':read_weights,'influence':weight,'reconstruction_error':float(np.mean((reconstruction-x)**2))}
    def add(self,identifier,x,state=None,style=None,action=None,source='weak_llm',group_id=None):
        if any(s['id']==identifier for s in self.samples):return False
        xx=np.asarray(x,dtype=float)
        if xx.shape!=(DIM,) or not np.isfinite(xx).all():raise ValueError('PMM 输入向量无效')
        if state is not None:state=[clamp(state[k],-1 if k=='valence' else 0,1) for k in STATE_KEYS]
        if style is not None:
            style=[clamp(v) for v in style]
            if len(style)!=8:raise ValueError('风格监督维数不匹配')
        heldout=int(hashlib.sha256((group_id or identifier.removesuffix(':episode')).encode()).hexdigest()[:8],16)%5==0
        self.samples.append({'id':identifier,'x':xx.tolist(),'state':state,'style':style,
                             'action':action if action in ACTIONS else None,'source':source,'heldout':heldout})
        self.learned_samples+=int(not heldout);self.samples=self.samples[-512:];return True
    def _batch(self,rows):
        x=np.array([s['x'] for s in rows]);ms=np.array([s['state'] is not None for s in rows])[:,None]
        my=np.array([s['style'] is not None for s in rows])[:,None];ma=np.array([s['action'] is not None for s in rows])[:,None]
        ts=np.array([s['state'] or [0]*4 for s in rows]);ty=np.array([s['style'] or [0]*8 for s in rows]);ta=np.zeros((len(rows),len(ACTIONS)))
        for i,s in enumerate(rows):
            if s['action'] in ACTIONS:ta[i,ACTIONS.index(s['action'])]=1
        return x,ms,my,ma,ts,ty,ta
    def fit(self,epochs=12):
        rows=[s for s in self.samples if not s['heldout']]
        if not rows:return self.info()
        x,ms,my,ma,ts,ty,ta=self._batch(rows);n=len(x)
        for _ in range(max(1,min(150,int(epochs)))):
            z=np.tanh(x@self.E.T+self.eb);rx=z@self.D.T+self.db;ss=z@self.S.T+self.sb;yy=z@self.Y.T+self.yb;aa=softmax(z@self.A.T+self.ab)
            er=2*(rx-x)/DIM;es=(ss-ts)*ms/2;ey=(yy-ty)*my/4;ea=(aa-ta)*ma*.3
            dz=(er@self.D+es@self.S+ey@self.Y+ea@self.A)*(1-z*z)
            grads={'E':dz.T@x/n,'eb':dz.mean(0),'D':er.T@z/n,'db':er.mean(0),
                   'S':es.T@z/n,'sb':es.mean(0),'Y':ey.T@z/n,'yb':ey.mean(0),'A':ea.T@z/n,'ab':ea.mean(0)}
            for k,g in grads.items():setattr(self,k,getattr(self,k)-.08*np.clip(g,-1,1))
            self.steps+=1
        self.metrics={'train':self.evaluate(rows),'heldout':self.evaluate([s for s in self.samples if s['heldout']])}
        self.save();return self.info()
    def evaluate(self,rows):
        if not rows:return {'n':0,'state_mse':None,'style_mse':None,'action_accuracy':None,'reconstruction_mse':None}
        x,ms,my,ma,ts,ty,ta=self._batch(rows);z=np.tanh(x@self.E.T+self.eb)
        s=z@self.S.T+self.sb;y=z@self.Y.T+self.yb;a=softmax(z@self.A.T+self.ab)
        return {'n':len(rows),'state_mse':float(((s-ts)**2*ms).sum()/max(1,ms.sum()*4)) if ms.any() else None,
                'style_mse':float(((y-ty)**2*my).sum()/max(1,my.sum()*8)) if my.any() else None,
                'action_accuracy':float(((a.argmax(1)==ta.argmax(1))*ma[:,0]).sum()/ma.sum()) if ma.any() else None,
                'reconstruction_mse':float(np.mean((z@self.D.T+self.db-x)**2))}
    def rank_feedback(self,components,relevant):
        c=np.array(components);pred=float(c@self.rank);self.rank+=.08*(int(relevant)-pred)*c
        self.rank=np.maximum(self.rank,.02);self.rank/=self.rank.sum();self.rank_labels+=1;self.save()
    def export(self):
        return {'format':'pmm/3','dimension':DIM,'latent':LATENT,'parameters':{k:getattr(self,k).tolist() for k in SHAPES},
                'steps':self.steps,'learned_samples':self.learned_samples,'samples':copy.deepcopy(self.samples),'metrics':copy.deepcopy(self.metrics),
                'retrieval_weights':self.rank.tolist(),'retrieval_labels':self.rank_labels}
    def import_data(self,obj,save=True):
        if not isinstance(obj,dict) or obj.get('format')!='pmm/3' or obj.get('dimension')!=DIM or obj.get('latent')!=LATENT:raise ValueError('PMM 参数版本不匹配')
        params={}
        for k,shape in SHAPES.items():
            a=np.array(obj.get('parameters',{}).get(k),dtype=float)
            if a.shape!=shape or not np.isfinite(a).all() or (np.abs(a)>100).any():raise ValueError('PMM 参数无效')
            params[k]=a
        samples=obj.get('samples',[])
        if not isinstance(samples,list) or len(samples)>512:raise ValueError('PMM 回放样本过多')
        for s in samples:
            if not isinstance(s,dict) or not isinstance(s.get('id'),str) or not isinstance(s.get('heldout'),bool):raise ValueError('PMM 样本格式无效')
            a=np.asarray(s.get('x'),dtype=float)
            if a.shape!=(DIM,) or not np.isfinite(a).all() or (np.abs(a)>4).any():raise ValueError('PMM 样本向量无效')
            for field,n in [('state',4),('style',8)]:
                a=np.asarray(s[field],dtype=float) if s.get(field) is not None else None
                if a is not None and (a.shape!=(n,) or not np.isfinite(a).all()):raise ValueError('PMM 样本标签无效')
                if a is not None and ((a>1).any() or (a < (np.array([-1,0,0,0]) if field=='state' else 0)).any()):raise ValueError('PMM 样本标签范围无效')
            if s.get('action') not in (*ACTIONS,None):raise ValueError('PMM 行为标签无效')
        rank=np.array(obj.get('retrieval_weights'),dtype=float)
        if rank.shape!=(4,) or not np.isfinite(rank).all() or (rank<0).any() or abs(rank.sum()-1)>1e-6:raise ValueError('检索权重无效')
        steps=int(obj.get('steps',0));labels=int(obj.get('retrieval_labels',0))
        if min(steps,labels)<0:raise ValueError('训练计数无效')
        learned_samples=int(obj.get('learned_samples',sum(not s['heldout'] for s in samples)))
        if learned_samples<sum(not s['heldout'] for s in samples):raise ValueError('训练样本计数无效')
        self.__dict__.update(params);self.steps=steps;self.learned_samples=learned_samples;self.samples=copy.deepcopy(samples);self.metrics=copy.deepcopy(obj.get('metrics',{}));self.rank=rank;self.rank_labels=labels
        if save:self.save()
    def save(self):
        if self.path:atomic_json(self.path,self.export())
    def info(self):
        return {'architecture':f'{DIM} → {LATENT} → 记忆特征 / 情绪 / 风格 / 行动', 'steps':self.steps,'samples':len(self.samples),
                'learned_samples':self.learned_samples,'train_samples':sum(not s['heldout'] for s in self.samples),'heldout_samples':sum(s['heldout'] for s in self.samples),
                'metrics':self.metrics,'retrieval_labels':self.rank_labels,
                'status':'尚未训练' if not self.steps else '已有训练，需验证泛化',
                'note':'本地 NumPy 编解码器；语言理解来自配置的大模型，文本记忆由来源索引取回。没有预训练人格权重。'}
