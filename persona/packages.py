"""Connection-free persona state packages, validated before any live mutation."""
from __future__ import annotations
import copy,json,math,re,tempfile,sqlite3
from .storage import Store,BASE_STATE
from .common import now,dumps,SCHEMA,uid
from .psychology import validate_profile,STATE_KEYS
from .pmm_interface import load_numeric
from .learned_pmm import LearnedPMM
from .registry_pmm import RegistryPMM,DIM as FULL_DIM
from .registry import ensure_profile,extend_vector,CONTRACT
from .relationships import validate as validate_dyads

FORMAT='persona-package/2.3'
COMPATIBLE_FORMATS=('persona-package/2.0','persona-package/2.1',FORMAT)
META_KEYS=('pmm281_affect','pmm281_affect_models','pmm28_models','pmm28_samples','pmm28_estimator','learning_evidence','learning_policy','learning_center','learning_observed_sources','social_graph','pmm_pragmatics','pmm_affect','identity','state','pmm_profile','pmm_activity','pmm_interlocutors','pmm_memory_codes','pmm_expression','pmm_synthesis','pmm_training_records','api_retrieval','pmm_checkpoint','pmm_dyads','consolidation_queue','memory_pending','memory_traces','cognitive_head','cognitive_feedback','memory_open_events','boundary_model','claim_memory')


def validate_metadata(meta):
    from .affect_runtime import validate_metadata as validate_affect_v2
    validate_affect_v2(meta)
    from .pmm_trainer import validate_metadata as validate_pmm28
    validate_pmm28(meta)
    from .evidence import validate as validate_evidence
    validate_evidence(meta.get('learning_evidence'))
    from .learning import validate_policy,validate_state as validate_learning,validate_observed
    if meta.get('learning_policy') is not None:validate_policy(meta['learning_policy'])
    validate_learning(meta.get('learning_center'))
    validate_observed(meta.get('learning_observed_sources'))
    from .social_graph import validate as validate_graph
    validate_graph(meta.get('social_graph'))
    from .pragmatics import validate as validate_pragmatics
    validate_pragmatics(meta.get('pmm_pragmatics'))
    from .boundaries import validate_state,validate_claims
    validate_state(meta.get('boundary_model'));validate_claims(meta.get('claim_memory'))
    from .consolidation import validate_queue
    validate_queue(meta.get('consolidation_queue') or [])
    from .memory_lifecycle import validate_memory_state
    validate_memory_state({'pending':meta.get('memory_pending') or [],'traces':meta.get('memory_traces') or {},'open_events':meta.get('memory_open_events') or {}})
    from .cognition import AppraisalHead,validate_feedback_state
    AppraisalHead(meta.get('cognitive_head'));validate_feedback_state(meta.get('cognitive_feedback') or [])
    from .affect import validate as validate_affect
    validate_affect(meta.get('pmm_affect'),meta['identity']['id'])
    identity=meta['identity']['id'];p=validate_profile(meta['pmm_profile']);meta['pmm_profile']=p
    validate_dyads(meta.get('pmm_dyads') or {})
    if p['id']!=identity:raise ValueError('人格与主体标识不匹配')
    load_numeric(meta['pmm_checkpoint'],identity)
    others=meta.get('pmm_interlocutors') or {}
    if not isinstance(others,dict):raise ValueError('对象模型应为对象')
    for key,item in others.items():
        item=validate_profile(item);others[key]=item
        for feature in item['psychology']['features'].values():feature['scope']='model_of_other'
        if item['id']!=key:raise ValueError('对象模型标识不匹配')
    activity=meta.get('pmm_activity')
    if activity:
        for field in ('emotion','mood'):
            if not isinstance(activity.get(field),dict) or set(activity[field])!=set(STATE_KEYS):raise ValueError('心理状态维度无效')
            for key,val in activity[field].items():
                if type(val) not in (int,float) or not math.isfinite(val) or not (-1 if key=='valence' else 0)<=val<=1:raise ValueError('心理状态数值无效')
        if type(activity.get('updated_at')) not in (int,float) or not math.isfinite(activity['updated_at']):raise ValueError('心理状态时间无效')
    pending=meta.get('pmm_training_records') or []
    if not isinstance(pending,list) or len(pending)>1024:raise ValueError('训练队列无效')
    probe=RegistryPMM(identity=identity)
    for row in pending:
        if not isinstance(row,dict) or not isinstance(row.get('labels'),dict):raise ValueError('训练样本无效')
        if len(row.get('x',[]))==FULL_DIM and row.get('registry_contract')!=CONTRACT:raise ValueError('训练队列注册表不兼容')
        try:probe.add(row['id'],extend_vector(row['x']) if len(row['x'])==184 else row['x'],**row['labels'])
        except (KeyError,TypeError,ValueError):raise ValueError('待训练样本字段或数值无效') from None
    codes=meta.get('pmm_memory_codes') or {}
    if not isinstance(codes,dict) or not all(isinstance(v,dict) for v in codes.values()):raise ValueError('记忆编码无效')
    for values in codes.values():
        for value in values.values():
            if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:raise ValueError('记忆编码数值无效')
    expression=meta.get('pmm_expression')
    if expression:
        if type(expression.get('count')) is not int or expression['count']<0 or not isinstance(expression.get('action_counts'),dict):raise ValueError('表达统计无效')
        v=expression.get('style_observed_mean')
        if not isinstance(v,list) or len(v)!=8 or any(type(x) not in (int,float) or not math.isfinite(x) or not 0<=x<=1 for x in v):raise ValueError('表达统计向量无效')
        if any(type(v) is not int or v<0 for v in expression['action_counts'].values()):raise ValueError('表达行动计数无效')
    ranking=meta.get('api_retrieval')
    if ranking:
        w=ranking.get('weights')
        if not isinstance(w,list) or len(w)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in w) or abs(sum(w)-1)>1e-6:raise ValueError('API 检索权重无效')
        if type(ranking.get('labels')) is not int or ranking['labels']<0:raise ValueError('API 检索计数无效')
    synthesis=meta.get('pmm_synthesis')
    if synthesis:
        if not isinstance(synthesis,dict) or not isinstance(synthesis.get('statements'),list) or not isinstance(synthesis.get('uncertainties'),list):raise ValueError('人格整理格式无效')
        sources={r['id']:r for r in p['source_records']}
        for row in synthesis['statements']:
            if not isinstance(row,dict) or not isinstance(row.get('evidence'),list) or not row['evidence']:raise ValueError('人格整理缺少证据')
            for e in row['evidence']:
                if not isinstance(e,dict) or e.get('record_id') not in sources or not isinstance(e.get('quote'),str) or not e['quote'].strip() or e['quote'] not in sources[e['record_id']]['text']:raise ValueError('人格整理证据不匹配')
    return meta


def export_continuity(engine):
    meta={k:engine.store.meta(k) for k in META_KEYS};meta['pmm_checkpoint']=engine.model.export()
    # Carry the full ledger through the existing validated boundary container.
    # The receiving runtime archives these rows before trimming its hot cache.
    if meta.get('boundary_model'):
        meta['boundary_model']=copy.deepcopy(meta['boundary_model'])
        rows=engine.store.rows("SELECT payload FROM events WHERE kind='boundary_appraisal' ORDER BY created_at,id")
        if rows:meta['boundary_model']['recent']=[json.loads(r['payload']) for r in rows]
    return {'format':FORMAT,'scope':'continuity','exported_at':now(),'identity':meta['identity'],'profile':meta['pmm_profile'],
            'pmm281':{k:meta.get(k) for k in ('pmm281_affect','pmm281_affect_models')},
            'pmm28':{k:meta.get(k) for k in ('pmm28_models','pmm28_samples','pmm28_estimator')},
            'learning_evidence':meta['learning_evidence'],'learning_center':meta['learning_center'],'learning_policy':meta['learning_policy'],'learning_observed_sources':meta['learning_observed_sources'],'social_graph':meta['social_graph'],
            'state':meta['state'],'pragmatics':meta['pmm_pragmatics'],'affect_state':meta['pmm_affect'],'trait_affect_contract':'trait-affect/1','activity':meta['pmm_activity'],'expression':meta['pmm_expression'],'synthesis':meta['pmm_synthesis'],
            'memories':engine.store.memories(all_status=True),'relationships':engine.store.rows('SELECT * FROM relations'),
            'psychology_contract':copy.deepcopy(CONTRACT),'dyads':meta['pmm_dyads'] or {},'interlocutors':meta['pmm_interlocutors'] or {},'memory_codes':meta['pmm_memory_codes'] or {},
            'learning':{'checkpoint':meta['pmm_checkpoint'],'pending':meta['pmm_training_records'] or [],'retrieval':meta['api_retrieval']},
            'memory_state':{'pending':meta['memory_pending'] or [],'traces':meta['memory_traces'] or {},'open_events':meta['memory_open_events'] or {}},
            'cognitive_state':{'head':meta['cognitive_head'],'feedback':meta['cognitive_feedback'] or []},
            'consolidation_queue':meta['consolidation_queue'] or [],'boundary_model':meta['boundary_model'],'claim_memory':meta['claim_memory'] or [],
            'contents':'同一主体的人格证据、原始语言样本、情绪/心境、关系、含私密原文的记忆与对象模型、待训练样本、可选核心/Adapter；不含 API 连接、密钥或完整会话表。'}


def validate_pack(pack):
    if not isinstance(pack,dict) or pack.get('format') not in COMPATIBLE_FORMATS:raise ValueError('需要 v2.0 / v2.1 / v2.3 连续人格包')
    if pack['format'] in ('persona-package/2.1',FORMAT) and pack.get('psychology_contract')!=CONTRACT:raise ValueError('人格包字段注册表不匹配')
    identity=pack.get('identity',{});learning=pack.get('learning',{})
    if not isinstance(identity,dict) or not re.fullmatch('[0-9a-f]{32}',str(identity.get('id',''))) or identity.get('schema')!=SCHEMA:raise ValueError('人格包主体标识无效')
    if not isinstance(learning,dict):raise ValueError('人格包学习部分无效')
    checkpoint=learning.get('checkpoint')
    if checkpoint is None:checkpoint=RegistryPMM(identity=identity['id']).export()
    meta={'pmm_pragmatics':pack.get('pragmatics'),'pmm_affect':pack.get('affect_state'),'identity':identity,'pmm_profile':pack.get('profile'),'state':pack.get('state',copy.deepcopy(BASE_STATE)),
          'consolidation_queue':pack.get('consolidation_queue',[]),'pmm_dyads':pack.get('dyads',{}),'pmm_activity':pack.get('activity'),'pmm_expression':pack.get('expression'),'pmm_synthesis':pack.get('synthesis'),
          'pmm_interlocutors':pack.get('interlocutors',{}),'pmm_memory_codes':pack.get('memory_codes',{}),
          'pmm_training_records':learning.get('pending',[]),'api_retrieval':learning.get('retrieval'),'pmm_checkpoint':checkpoint}
    extra=pack.get('pmm28',{})
    emotion=pack.get('pmm281',{})
    if not isinstance(emotion,dict) or set(emotion)-{'pmm281_affect','pmm281_affect_models'}:raise ValueError('2.8.1 情绪分区无效')
    meta.update({k:emotion.get(k) for k in ('pmm281_affect','pmm281_affect_models')})
    if not isinstance(extra,dict) or set(extra)-{'pmm28_models','pmm28_samples','pmm28_estimator'}:raise ValueError('2.8 人格包分区无效')
    meta.update({k:extra.get(k) for k in ('pmm28_models','pmm28_samples','pmm28_estimator')})
    meta.update(boundary_model=pack.get('boundary_model'),claim_memory=pack.get('claim_memory',[]))
    meta.update({k:pack.get(k) for k in ('learning_evidence','learning_center','learning_policy','learning_observed_sources','social_graph')})
    cognition=pack.get('cognitive_state',{})
    if not isinstance(cognition,dict):raise ValueError('认知连续状态无效')
    meta.update(cognitive_head=cognition.get('head'),cognitive_feedback=cognition.get('feedback',[]))
    memory=pack.get('memory_state',{})
    from .memory_lifecycle import validate_memory_state
    validate_memory_state(memory)
    meta.update(memory_pending=memory.get('pending',[]),memory_traces=memory.get('traces',{}),memory_open_events=memory.get('open_events',{}))
    try:validate_metadata(meta)
    except (KeyError,TypeError,AttributeError):raise ValueError('人格包心理数据字段不完整') from None
    memories=pack.get('memories',[]);relations=pack.get('relationships',[])
    if not isinstance(memories,list) or len(memories)>50000 or not isinstance(relations,list):raise ValueError('人格包记忆或关系无效')
    for m in memories:
        if not isinstance(m,dict):raise ValueError('记忆条目无效')
        for field in ('id','content','kind','scope','person','status','source_turn','evidence','interpretation'):
            if not isinstance(m.get(field),str) or len(m[field])>16000:raise ValueError('记忆文本字段无效')
        if not m['id'] or not m['scope'] or m['status'] not in ('active','deleted','superseded','merged'):raise ValueError('记忆标识或状态无效')
        for field in ('confidence','importance'):
            v=m.get(field)
            if type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1:raise ValueError('记忆分值无效')
        for field in ('created_at','updated_at'):
            if type(m.get(field)) not in (int,float) or not math.isfinite(m[field]):raise ValueError('记忆时间无效')
        if type(m.get('revision')) is not int or m['revision']<0:raise ValueError('记忆修订版本无效')
    snap={'format':'persona-dialogue','schema':SCHEMA,'tables':{t:[] for t in Store.TABLES}}
    snap['tables'].update(meta=[{'key':k,'value':dumps(v)} for k,v in meta.items()],memories=memories,relations=relations)
    with tempfile.TemporaryDirectory() as directory:
        probe=Store(directory)
        try:probe.restore(snap)
        except (TypeError,KeyError,ValueError,sqlite3.Error):raise ValueError('人格包数据库结构或状态无效') from None
        finally:probe.close()
    return copy.deepcopy(meta),copy.deepcopy(memories),copy.deepcopy(relations)


def apply_pack(store,validated):
    meta,memories,relations=validated
    meta=copy.deepcopy(meta)
    for row in meta.get('consolidation_queue') or []:
        if row['status']=='processing':row['status']='pending'
    for row in meta.get('memory_pending') or []:
        if row['status']=='processing':row['status']='pending'
    store.setmeta('consolidation_generation',uid())
    # The caller owns the outer transaction when creating a new subject.
    for key,value in meta.items():store.setmeta(key,value)
    for table,rows in (('memories',memories),('relations',relations)):
        columns=[r[1] for r in store.db.execute('PRAGMA table_info('+table+')')]
        store.db.execute('DELETE FROM '+table)
        for row in rows:store.db.execute('INSERT INTO '+table+' VALUES ('+','.join('?'*len(columns))+')',[row[k] for k in columns])
    from .affect import migrate
    migrate(store)
    from .affect_runtime import migrate as migrate_affect_v2
    migrate_affect_v2(store)
    store.event('persona_package_applied',{'identity_id':meta['identity']['id'],'history_preserved':True})
