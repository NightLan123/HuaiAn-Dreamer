"""Event-scoped affect dynamics and committed expression, separate from traits.

Transitions are transparent, uncalibrated engineering hypotheses. They describe
simulated states, not sentience, clinical findings, or questionnaire scores.
"""
from __future__ import annotations
import copy, math
from .common import now, clamp
from .registry import STATE_IDS, APPRAISAL_IDS, REGULATION_IDS, BY_ID, number, digest
from .traits import snapshot as trait_snapshot

SCHEMA='trait-affect/1'
AXES=('valence','arousal','dominance','stress','engagement')
LEGACY_LABELS=tuple(k.rsplit('.',1)[-1] for k in STATE_IDS if k.startswith('affect.label.'))
EXTRA_LABELS=('anxiety','relief','calmness','amusement','disappointment','boredom','loneliness','affection','awkwardness','awe','envy','nostalgia')
LABELS=(*LEGACY_LABELS,*EXTRA_LABELS)
CATALOG={'version':'emotion-catalog/2','labels':dict(zip(LABELS,('喜悦','悲伤','愤怒','恐惧','厌恶','惊讶','兴趣','羞耻','内疚','感激','自豪','挫败','焦虑','宽慰','平静','逗乐','失望','无聊','孤独感','亲近感','尴尬','敬畏','羡慕','怀旧'))),'calibrated':False,'legacy_registry_unchanged':True}
TAU={'joy':3600,'sadness':7200,'anger':1800,'fear':2400,'disgust':1800,'surprise':300,'interest':3600,'shame':3600,'guilt':7200,'gratitude':7200,'pride':7200,'frustration':2400}
TAU.update(anxiety=5400,relief=1800,calmness=7200,amusement=1200,disappointment=5400,boredom=3600,loneliness=14400,affection=10800,awkwardness=1800,awe=3600,envy=5400,nostalgia=7200)

def default_parameters(identity):
    return {'version':'time-dynamics/1','persona_id':identity,'source_type':'uncalibrated',
        'baseline_ref':'engineering-prior/1','baseline':{'valence':0.,'arousal':.25,'dominance':None,'stress':.15,'engagement':.65},
        'emotion_tau_seconds':7200.,'mood_tau_seconds':172800.,'label_tau_seconds':copy.deepcopy(TAU),
        'reactivity':.35,'sensitivity_interval':[.15,.6],
        'note':'个体可编辑的工程参数；未将 HEXACO 或 PA/NA 换算为 VA 基线，不是人类心理定律'}

def empty(identity,at=None):
    at=now() if at is None else at
    return {'schema':SCHEMA,'emotion_catalog':CATALOG['version'],'persona_id':identity,'scope':'agent_self','transition_params':default_parameters(identity),
        'emotion':{'entity':'EmotionState','persona_id':identity,**{k:None for k in AXES},
            'categorical_activations':{k:None for k in LABELS},'event_id':None,'appraisal_id':None,
            'onset_at':None,'last_updated':at,'confidence':0.,'state_revision':0,'source_type':'unknown'},
        'mood':{'entity':'MoodState','persona_id':identity,'baseline_ref':'engineering-prior/1',
            'valence':None,'arousal':None,'dominance':None,'updated_at':at,'uncertainty':1.,'transition_params_version':'time-dynamics/1','source_type':'unknown'},
        'appraisals':[],'regulation_actions':[],'expressions':[],'trajectory':[],'migration':None}

def validate(data,identity):
    if data is None:return
    if not isinstance(data,dict) or data.get('schema')!=SCHEMA or data.get('persona_id')!=identity or data.get('scope')!='agent_self':raise ValueError('情绪状态主体、作用域或协议不匹配')
    params=data.get('transition_params');validate_parameters(params,identity)
    for field,keys,timekey in (('emotion',AXES,'last_updated'),('mood',('valence','arousal','dominance'),'updated_at')):
        entity=data.get(field)
        if not isinstance(entity,dict) or entity.get('persona_id')!=identity:raise ValueError('情绪/心境实体缺失或主体不匹配')
        for k in keys:
            if k not in entity:raise ValueError('情绪维度缺失')
            if entity[k] is not None:number(entity[k],-1 if k=='valence' else 0)
        if entity.get(timekey) is not None:number(entity[timekey],0,1e13)
    e=data['emotion']
    if set(e.get('categorical_activations',{})) not in (set(LEGACY_LABELS),set(LABELS)):raise ValueError('具体情绪标签缺失')
    for v in e['categorical_activations'].values():
        if v is not None:number(v)
    if type(e.get('state_revision')) is not int or e['state_revision']<0:raise ValueError('情绪版本无效')
    number(e.get('confidence'));number(data['mood'].get('uncertainty'))
    for k in ('appraisals','regulation_actions','expressions','trajectory'):
        if not isinstance(data.get(k),list):raise ValueError('情绪轨迹/操作日志无效')
        for r in data[k]:
            if not isinstance(r,dict) or r.get('persona_id',identity)!=identity:raise ValueError('情绪记录跨主体')
            if r.get('origin')=='legacy_registry':
                expected=APPRAISAL_IDS if k=='appraisals' else REGULATION_IDS if k=='regulation_actions' else ()
                if r.get('feature_id') not in expected or not isinstance(r.get('legacy_record'),dict):raise ValueError('历史情绪记录类型不匹配')
                number(r['legacy_record'].get('estimate'));continue
            number(r.get('at'),0,1e13)
            if k=='appraisals':
                checks=r.get('checks')
                if not isinstance(checks,dict) or set(checks)-set(APPRAISAL_IDS):raise ValueError('事件评价日志字段无效')
                for value in checks.values():number(value)
                if not isinstance(r.get('event_id'),str):raise ValueError('评价缺少事件标识')
            elif k=='regulation_actions':
                if r.get('strategy') not in ('none','cognitive_reappraisal','expressive_suppression') or r.get('applied') is not True:raise ValueError('当次调节执行记录无效')
                number(r.get('expression_multiplier'));number(r.get('internal_effect'))
            elif k=='expressions':
                if r.get('status')!='committed' or r.get('dialogue_action') not in ('reply','unknown','clarify','disagree','decline','silence'):raise ValueError('实际表达记录无效')
                number(r.get('intensity'))
                if not isinstance(r.get('observed_style'),list) or len(r['observed_style'])!=8:raise ValueError('实际表达风格维度无效')
                for value in r['observed_style']:number(value)
                if type(r.get('actual_message_count')) is not int or r['actual_message_count']<0:raise ValueError('实际消息数量无效')
            elif k=='trajectory':
                validate({**data,'emotion':r.get('emotion'),'mood':r.get('mood'),'appraisals':[],'regulation_actions':[],'expressions':[],'trajectory':[]},identity)

def validate_parameters(p,identity):
    if not isinstance(p,dict) or p.get('persona_id')!=identity or p.get('version')!='time-dynamics/1':raise ValueError('情绪转移参数版本不兼容')
    if set(p.get('baseline',{}))!=set(AXES) or set(p.get('label_tau_seconds',{})) not in (set(LEGACY_LABELS),set(LABELS)):raise ValueError('情绪基线或持续时间字段缺失')
    for k,v in p['baseline'].items():
        if v is not None:number(v,-1 if k=='valence' else 0)
    number(p.get('emotion_tau_seconds'),10,604800);number(p.get('mood_tau_seconds'),60,2592000);number(p.get('reactivity'),0,1)
    for v in p['label_tau_seconds'].values():number(v,10,604800)
    if p.get('source_type') not in ('uncalibrated','owner_seed'):raise ValueError('情绪参数须注明工程先验或主人设定')

def migrate(store):
    """Idempotent additive transaction. Legacy caches/checkpoints remain untouched."""
    identity=store.meta('identity')['id'];existing=store.meta('pmm_affect')
    if existing is not None:
        validate(existing,identity)
        if existing.get('emotion_catalog')!=CATALOG['version']:
            upgraded=upgrade_catalog(existing)
            with store.lock,store.db:
                store.setmeta('pmm_affect_pre_catalog_v2',existing);store.setmeta('pmm_affect',upgraded)
                store.event('emotion_catalog_migrated',{'to':CATALOG['version'],'new_labels_unknown':True,'registry_unchanged':True})
            return upgraded
        return existing
    a=empty(identity);p=store.meta('pmm_profile') or {};old=store.meta('pmm_activity')
    if not old:
        st=store.meta('state') or {};old={'emotion':st.get('short',{}),'mood':{},'updated_at':st.get('updated_at')}
    stamp=old.get('updated_at');valid_stamp=type(stamp) in (int,float) and math.isfinite(stamp) and stamp>0
    if valid_stamp:
        for field in ('emotion','mood'):
            for k in AXES if field=='emotion' else ('valence','arousal','dominance'):
                value=old.get(field,{}).get(k)
                if value is not None:
                    try:number(value,-1 if k=='valence' else 0)
                    except ValueError:continue
                    a[field][k]=value
            a[field]['last_updated' if field=='emotion' else 'updated_at']=stamp
            a[field]['source_type']='legacy_engineering'
        a['emotion']['confidence']=.15;a['mood']['uncertainty']=.85
    features=p.get('psychology',{}).get('features',{})
    for k,f in features.items():
        if k in APPRAISAL_IDS or k in REGULATION_IDS:
            if f.get('estimate') is not None:
                dest='appraisals' if k in APPRAISAL_IDS else 'regulation_actions'
                a[dest].append({'id':'legacy:'+k,'persona_id':identity,'feature_id':k,'legacy_record':copy.deepcopy(f),
                    'origin':'legacy_registry','status':'historical_unverified_operation' if dest=='regulation_actions' else 'historical_appraisal','applied':False})
        # Old label timestamps belong to their source observation, not the upgrade.
        elif k in STATE_IDS and f.get('estimate') is not None and f.get('updated_at'):
            a.setdefault('legacy_affect_observations',[]).append({'feature_id':k,'record':copy.deepcopy(f)})
    protected=('pmm_profile','pmm_checkpoint','pmm_training_records','pmm_memory_codes','pmm_interlocutors','pmm_dyads')
    a['migration']={'version':'additive-affect-migration/1','at':now(),'legacy_timestamp_known':valid_stamp,
        'old_activity_sha256':digest(old),'preserved_meta_sha256':{k:digest(store.meta(k)) for k in protected},
        'note':'旧四维值仅作历史工程初值；无时间戳值原样保存在兼容档案，不转换为正式量表'}
    with store.lock,store.db:
        store.setmeta('pmm_affect',a);store.event('trait_affect_migrated',a['migration'])
    return a

def upgrade_catalog(data):
    out=copy.deepcopy(data);out['emotion_catalog']=CATALOG['version']
    for k in EXTRA_LABELS:
        out['emotion']['categorical_activations'].setdefault(k,None)
        out['transition_params']['label_tau_seconds'].setdefault(k,TAU[k])
    return out

def label_details(data,at=None):
    projected=advance(data,at);e=projected['emotion'];details=[]
    for k in LABELS:
        last=next((r for r in reversed(data.get('appraisals',[])) if k in r.get('label_updates',{})),None)
        value=e['categorical_activations'].get(k);stamp=last.get('at') if last else None
        details.append({'id':k,'name':CATALOG['labels'][k],'intensity':value,'unknown':value is None,
            'confidence':last.get('label_confidence') if last else None,'source_event_id':last.get('event_id') if last else None,
            'scope':last.get('scope') if last else None,'quote':last.get('evidence_quote') if last else None,'last_triggered_at':stamp,
            'stale':value is not None and (stamp is None or (now() if at is None else at)-stamp>3*projected['transition_params']['label_tau_seconds'][k]),
            'time_constant':projected['transition_params']['label_tau_seconds'][k],'source':'provider_proposal' if last and last.get('method','').startswith('provider') else 'engineering_prior' if last else 'unknown'})
    return details

def condition_sources(snapshot):
    fields={**snapshot['hexaco_facets'],**snapshot['affective_disposition']}
    keys=('hexaco.e.anxiety','hexaco.a.patience','erq.expressive_suppression','erq.cognitive_reappraisal',
          'beq.negative_expressivity','beq.positive_expressivity','beq.impulse_strength')
    return {k:{'estimate':fields[k].get('estimate'),'source_type':fields[k].get('source_type','unknown'),
        'fallback_used':fields[k].get('estimate') is None,'evidence_ids':fields[k].get('evidence_ids',[])} for k in keys}

def advance(data,at=None):
    """Closed-form continuous E and low-pass M; polling never changes the result."""
    out=upgrade_catalog(data);at=now() if at is None else at;p=out['transition_params'];e=out['emotion'];m=out['mood']
    number(at,0,1e13)
    last=e['last_updated'];elapsed=max(0,at-last) if last is not None else 0
    if not elapsed:return out
    te=p['emotion_tau_seconds'];tm=p['mood_tau_seconds'];ee=math.exp(-elapsed/te);em=math.exp(-elapsed/tm)
    for k in AXES:
        old=e[k];base=p['baseline'][k]
        if old is None:continue
        # A missing dominance baseline stays unknown; decay confidence, not to .5.
        if base is None:continue
        e[k]=base+(old-base)*ee
        if k in ('valence','arousal','dominance') and m[k] is not None:
            coupling=(elapsed/tm*em) if abs(te-tm)<1e-6 else te/(te-tm)*(ee-em)
            m[k]=base+(m[k]-base)*em+(old-base)*coupling
    for k,v in e['categorical_activations'].items():
        if v is not None:e['categorical_activations'][k]=v*math.exp(-elapsed/p['label_tau_seconds'][k])
    e['confidence']*=ee;m['uncertainty']=1-(1-m['uncertainty'])*em
    e['last_updated']=max(last or at,at);m['updated_at']=max(m['updated_at'] or at,at)
    out['as_of']=at
    return out

def compatibility(data):
    """Four numeric encoder columns only; never displayed as measured scores."""
    p=data['transition_params'];e=data['emotion'];m=data['mood']
    fallback={'valence':0.,'arousal':.25,'stress':.15,'engagement':.65}
    def val(src,k):return src[k] if src.get(k) is not None else p['baseline'].get(k) if p['baseline'].get(k) is not None else fallback[k]
    return {'emotion':{k:val(e,k) for k in fallback},'mood':{k:val(m,k) for k in fallback},'updated_at':e['last_updated'] or 0,
        'compatibility_view':'legacy_four_channel_encoder/1','measurement':False,
        'emotion_state':copy.deepcopy(e),'mood_state':copy.deepcopy(m),'transition_parameters':copy.deepcopy(p)}

def _known(snapshot,k,default=.5):
    group='value_priorities' if k.startswith('value.') else 'hexaco_facets'
    v=snapshot[group].get(k,{}).get('estimate')
    return default if v is None else v

def _habit(snapshot,k,default):
    v=snapshot['affective_disposition'][k]['estimate']
    return default if v is None else v

def validate_proposal(proposal,text):
    if proposal is None:return None
    if not isinstance(proposal,dict) or proposal.get('schema')!=SCHEMA:raise ValueError('不支持的分层情绪合约 unsupported_feature')
    if proposal.get('subject')!='agent_self':raise ValueError('对方的情绪不能写入 AI 自身')
    quote=proposal.get('evidence_quote')
    if not isinstance(quote,str) or not quote.strip() or quote not in text:raise ValueError('分层情绪缺少当前事件证据')
    allowed={'schema','subject','evidence_quote','appraisal_checks','emotion_proposal','regulation_proposal'}
    if set(proposal)-allowed:raise ValueError('情绪合约不能携带人格写入字段')
    checks=proposal.get('appraisal_checks',{})
    if not isinstance(checks,dict) or set(checks)-set(APPRAISAL_IDS):raise ValueError('事件评价字段不匹配')
    for v in checks.values():
        if v is not None:number(v)
    em=proposal.get('emotion_proposal',{})
    if not isinstance(em,dict) or set(em)-set(AXES)-{'categorical_activations','confidence'}:raise ValueError('即时情绪字段不匹配')
    for k,v in em.items():
        if k=='categorical_activations':
            if not isinstance(v,dict) or set(v)-set(LABELS):raise ValueError('具体情绪标签不匹配')
            for n in v.values():
                if n is not None:number(n)
        elif v is not None:number(v,-1 if k=='valence' else 0)
    if proposal.get('regulation_proposal') not in (None,'none','cognitive_reappraisal','expressive_suppression'):raise ValueError('调节操作未受支持')
    return copy.deepcopy(proposal)

def evaluate(data,snapshot,understanding,event,relation,memories,proposal=None,at=None):
    """Pure transaction draft: trait -> appraisal -> state -> regulation.

    Provider suggestions are scoped proposals. Only this function can change the
    draft state, and the caller commits it after an actual action/receipt.
    """
    at=now() if at is None else at
    if data['persona_id']!=snapshot['persona_id'] or snapshot['scope']!='agent_self':raise ValueError('情绪转移主体不匹配')
    number(at,0,1e13)
    if any(not isinstance(event.get(k),str) or not event[k].strip() for k in ('id','text','scope','person')):raise ValueError('情绪更新需要可定位的当前输入事件')
    content_digest=digest([event['scope'],event['person'],event['text']]);event_key=digest([data['persona_id'],event['scope'],event['id']])
    prior=next((r for r in reversed(data['appraisals']) if r.get('event_key')==event_key),None)
    if prior:
        if prior['content_digest']!=content_digest:raise ValueError('同一输入事件 ID 对应不同证据，未再次更新状态')
        trajectory=next(r for r in reversed(data['trajectory']) if r.get('event_key')==event_key)
        regulation=next(r for r in reversed(data['regulation_actions']) if r.get('appraisal_id')==prior['id'])
        return copy.deepcopy(data),{'trait_snapshot':snapshot,'appraisal':copy.deepcopy(prior),'regulation_action':copy.deepcopy(regulation),
            'emotion_before':copy.deepcopy(prior['emotion_before']),'mood_before':copy.deepcopy(prior['mood_before']),
            'emotion_state':copy.deepcopy(trajectory['emotion']),'mood_state':copy.deepcopy(trajectory['mood']),
            'transition_params':copy.deepcopy(data['transition_params']),'replayed':True}
    received_at=at;at=max(at,data['emotion']['last_updated'] or at)
    out=advance(data,at);p=out['transition_params'];sem=understanding['semantic'];before=copy.deepcopy(out['emotion']);mood_before=copy.deepcopy(out['mood'])
    proposal=validate_proposal(proposal,event['text'])
    compat=compatibility(out);old=compat['emotion'];h=sem.get('hostility',0);nov=sem.get('novelty',0);goal=sem.get('goal_congruence',.5)
    # These coefficients are explicitly uncalibrated, bounded interactions, not
    # direct equivalences between Emotionality and today's fear or VA.
    anxiety=_known(snapshot,'hexaco.e.anxiety');patience=_known(snapshot,'hexaco.a.patience')
    trust=relation.get('trust',.5);trust=.5 if trust is None else trust
    relevance=clamp(.4*sem.get('social',0)+.35*sem.get('value_conflict',0)+.25*sem.get('urgency',0))
    perceived_threat=clamp(h*(.75+.3*anxiety+.15*(1-trust)))
    control=clamp(sem.get('agency',.5)*(.8+.2*patience))
    checks={'affect.appraisal.novelty':nov,'affect.appraisal.goal_relevance':relevance,
        'affect.appraisal.goal_conduciveness':goal,'affect.appraisal.urgency':sem.get('urgency',0),
        'affect.appraisal.control':control,'affect.appraisal.internal_norm_compatibility':1-sem.get('value_conflict',0)}
    if proposal:checks.update({k:v for k,v in proposal.get('appraisal_checks',{}).items() if v is not None})
    aid=event_key[:32];appraisal={'id':aid,'event_key':event_key,'content_digest':content_digest,
        'original_event_ids':list(event.get('source_event_ids') or [event['id']]),'emotion_before':before,'mood_before':mood_before,
        'clock':{'received_at':received_at,'effective_at':at,'elapsed_seconds':max(0,at-(data['emotion']['last_updated'] or at)),
            'basis':'elapsed_wall_seconds','event_sequence':before['state_revision']+1,'simulated_seconds_per_turn':None},
        'evidence_provenance':{'event':'observed_input','appraisal':'model_inference' if proposal else 'bounded_engineering_appraisal_of_model_semantics',
            'parameters':p['source_type'],'trait_inputs':condition_sources(snapshot),'calibrated':False},'entity':'EventAppraisal','persona_id':data['persona_id'],'scope':event['scope'],
        'person_id':event['person'],'event_id':event['id'],'at':at,'trait_version':snapshot['trait_version'],'trait_digest':snapshot['trait_digest'],
        'checks':checks,'threat_estimate':perceived_threat,'memory_ids':[m['id'] for m in memories],
        'relationship_context':{'trust':trust,'familiarity':relation.get('familiarity')},
        'method':'provider_proposal_plus_bounded_transition/1' if proposal else 'uncalibrated_trait_appraisal/1',
        'evidence_quote':proposal['evidence_quote'] if proposal else event['text'][:300]}
    pleasant=checks['affect.appraisal.goal_conduciveness'];negative=clamp(.7*perceived_threat+.3*(1-pleasant)*relevance)
    target={'valence':clamp(2*(pleasant-.5)*max(.2,relevance)-perceived_threat,-1,1),
        'arousal':clamp(.15+.5*perceived_threat+.25*nov+.2*relevance),
        'dominance':checks['affect.appraisal.control'] if sem.get('certainty',0)>.25 else None,
        'stress':clamp(negative*(1-.25*control)), 'engagement':clamp(.4+.3*sem.get('social',0)+.2*nov-.25*perceived_threat)}
    labels={k:None for k in LABELS}
    labels.update(anger=clamp(perceived_threat*(.65+.3*(1-patience))),fear=clamp(negative*(1-control)*(.6+.4*anxiety)),
        frustration=clamp((1-pleasant)*relevance),joy=clamp((pleasant-.5)*2*(1-perceived_threat)),interest=nov,surprise=nov*.5)
    em_proposal=proposal.get('emotion_proposal',{}) if proposal else {}
    for k in AXES:
        if k in em_proposal:target[k]=em_proposal[k]
    labels.update(em_proposal.get('categorical_activations',{}))
    # Autobiographic nostalgia needs an actual scoped memory; a generated story
    # or someone else's episode cannot fabricate an AI life history.
    if labels.get('nostalgia') is not None and labels['nostalgia']>0 and not any(m.get('kind')=='episode' and m.get('scope') in ('self',event['scope']) and m.get('evidence') and m.get('source_turn') and not str(m.get('id','')).startswith('learn:') and ('\n我：' in m.get('content','') or '\n我（确认已发）：' in m.get('content','')) for m in memories):
        labels['nostalgia']=None;appraisal['rejected_labels']={'nostalgia':'缺少可核对的本主体经历来源'}
    appraisal['label_updates']={k:v for k,v in labels.items() if v is not None}
    appraisal['label_confidence']=min(.75,em_proposal.get('confidence') or .35)
    e=out['emotion']
    # Trait only modulates the response to an observed event. No independent
    # trait-to-emotion label or drift from an absent event is introduced.
    sensitivity=clamp(1+.2*(anxiety-.5)*perceived_threat-.15*(patience-.5)*relevance,.8,1.2)
    react=clamp(p['reactivity']*sensitivity)
    appraisal['reactivity']={'base':p['reactivity'],'event_multiplier':sensitivity,'effective':react,'source':'bounded_engineering_interaction','calibrated':False}
    e.update(event_id=event['id'],appraisal_id=aid,onset_at=at,last_updated=at,
        state_revision=e['state_revision']+1,confidence=min(.75,em_proposal.get('confidence') or .35),source_type='model_inference' if proposal else 'uncalibrated_engineering')
    for k,v in target.items():
        previous=e.get(k)
        initial=p['baseline'][k] if previous is None else previous
        e[k]=None if v is None else v if initial is None else clamp(initial+react*(v-initial),-1 if k=='valence' else 0,1)
    for k,v in labels.items():
        previous=e['categorical_activations'][k]
        if v is not None:e['categorical_activations'][k]=react*v if previous is None else clamp(previous+react*(v-previous))
    # Initialize previously unknown mood to an explicitly labelled engineering
    # baseline, then evolve it by wall time only. No per-message .96/.04 smoothing.
    for k in ('valence','arousal','dominance'):
        if out['mood'][k] is None:out['mood'][k]=p['baseline'][k]
    out['mood'].update(updated_at=at,source_type='uncalibrated_engineering',baseline_ref=p['baseline_ref'])
    reappraise=_habit(snapshot,'erq.cognitive_reappraisal',0.);suppress=_habit(snapshot,'erq.expressive_suppression',0.)
    proposed=proposal.get('regulation_proposal') if proposal else None
    strategy='none'
    if (e['valence'] or 0)<0 or (e['stress'] or 0)>.35:
        if proposed=='expressive_suppression' or suppress>max(.5,reappraise):strategy='expressive_suppression'
        elif proposed=='cognitive_reappraisal' or reappraise>.5:strategy='cognitive_reappraisal'
    regulation={'id':digest([event_key,'regulation'])[:32],'entity':'RegulationOperation','persona_id':data['persona_id'],'event_id':event['id'],'appraisal_id':aid,
        'scope':event['scope'],'strategy':strategy,'trait_version':snapshot['trait_version'],'at':at,'applied':True,
        'internal_effect':0.,'expression_multiplier':1.,'method':'uncalibrated_habit_policy/1'}
    if strategy=='expressive_suppression':
        regulation['expression_multiplier']=1-.8*max(.5,suppress)
    elif strategy=='cognitive_reappraisal':
        gain=.2*max(.5,reappraise)*control;regulation['internal_effect']=gain
        if e['valence'] is not None and e['valence']<0:e['valence']*=1-gain
        if e['stress'] is not None:e['stress']*=1-gain
        for k in ('anger','fear','frustration'):
            if e['categorical_activations'][k] is not None:e['categorical_activations'][k]*=1-gain
    out['appraisals'].append(appraisal);out['regulation_actions'].append(regulation)
    out['trajectory'].append({'event_key':event_key,'persona_id':data['persona_id'],'at':at,'event_id':event['id'],'scope':event['scope'],
        'trait_version':snapshot['trait_version'],'emotion_revision':e['state_revision'],
        'emotion':copy.deepcopy(e),'mood':copy.deepcopy(out['mood'])})
    return out,{'trait_snapshot':snapshot,'appraisal':appraisal,'regulation_action':regulation,'emotion_before':before,'mood_before':mood_before,'replayed':False,
        'emotion_state':copy.deepcopy(e),'mood_state':copy.deepcopy(out['mood']),'transition_params':copy.deepcopy(p)}

def expression_plan(snapshot,affect,decision,context):
    e=affect['emotion'];reg=affect['regulation_actions'][-1] if affect['regulation_actions'] else {'strategy':'none','expression_multiplier':1.}
    negative=(e['valence'] or 0)<0
    habit=_habit(snapshot,'beq.negative_expressivity' if negative else 'beq.positive_expressivity',.5)
    impulse=_habit(snapshot,'beq.impulse_strength',.5)
    intensity=clamp((.25+.5*habit)*(.35+.65*(e['arousal'] or 0))*(.8+.4*impulse)*reg['expression_multiplier'])
    return {'schema':'expression-plan/1','persona_id':snapshot['persona_id'],'dialogue_action':decision['action'],
        'expression_strategy':reg['strategy'],'disclosure_decision':decision.get('boundary',{}),
        'intensity':intensity,'timing':'after_validated_decision','sentence_segmentation':'single_message',
        'social_context':context,'linked_emotion_revision':e['state_revision'],'linked_trait_version':snapshot['trait_version'],
        'linked_trait_digest':snapshot['trait_digest'],'internal_emotion_is_not_expression':True,
        'measurement':'uncalibrated_engineering','status':'planned'}

def commit_expression(affect,plan,turn_id,at,reply,delivery='local_commit',message_count=None):
    out=copy.deepcopy(affect)
    from .psychology import style_vector
    entry={**copy.deepcopy(plan),'entity':'ExpressionState','turn_id':turn_id,'at':at,
           'status':'committed','delivery':delivery,'sent':bool(reply),'actual_message_count':int(bool(reply)) if message_count is None else message_count,
           'observed_style':style_vector(reply),'text_sha256':digest(reply)}
    index=next((i for i,r in enumerate(out['expressions']) if r.get('turn_id')==turn_id),None)
    if index is None:out['expressions'].append(entry)
    elif message_count is not None:out['expressions'][index]=entry
    return out

def encoder_state(profile,affect):
    """Same 93 columns; independent typed dynamic values from this turn only."""
    out=copy.deepcopy(profile['psychology'])
    for k in (*STATE_IDS,*APPRAISAL_IDS,*REGULATION_IDS):
        f=out['features'][k];f.update(estimate=None,posterior_uncertainty=None,evidence_ids=[],evidence_count=0,stale=False)
    if affect is None:return out
    e=affect['emotion'];checks=affect['appraisals'][-1].get('checks',{}) if affect['appraisals'] else {}
    for k in STATE_IDS:
        v=e.get(k.rsplit('.',1)[-1]) if '.vad.' in k else e['categorical_activations'].get(k.rsplit('.',1)[-1])
        out['features'][k].update(estimate=v,posterior_uncertainty=1-e['confidence'] if v is not None else None,updated_at=e['last_updated'])
    # These ephemeral inputs are valid only for the current event, never a trait.
    for k,v in checks.items():out['features'][k].update(estimate=v,posterior_uncertainty=.65,updated_at=e['last_updated'])
    if affect['regulation_actions']:
        strategy=affect['regulation_actions'][-1].get('strategy')
        k={'cognitive_reappraisal':'affect.regulation.cognitive_change','expressive_suppression':'affect.regulation.response_modulation'}.get(strategy)
        if k:out['features'][k].update(estimate=1.,posterior_uncertainty=0.,updated_at=e['last_updated'])
    return out
