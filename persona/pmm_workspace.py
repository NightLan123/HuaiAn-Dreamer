"""Read-only PMM status and an isolated single-turn execution workspace."""
from __future__ import annotations
import copy,json,tempfile
from pathlib import Path
from . import affect_runtime as ar
from . import expression_drive as ed
from .pmm_connections import receipt,PROBE_CONTRACT

def status(engine):
    from .affect_learning import AffectLearning
    from .pmm_coordinator import PMMCoordinator, appraisal_use
    config=engine.config.get();co=PMMCoordinator(engine);traces=co.traces();connections={}
    probes=[json.loads(x['payload']) for x in engine.store.rows("SELECT payload FROM events WHERE kind='pmm281_connection_test' ORDER BY rowid DESC LIMIT 80")]
    for role in ('A','B'):
        current=receipt(config,role)
        matching=[x for x in probes if x.get('role')==role and x.get('configuration_sha256')==current['configuration_sha256']]
        last=next((x for x in matching if x.get('operation')=='invoke' and x.get('task_contract')==PROBE_CONTRACT[role]),None)
        actual=None
        for t in traces:
            node=t.get('components',{}).get('reasoner' if role=='A' else 'negotiation',{})
            con=node.get('connection',{})
            if (node.get('executed') or node.get('status')=='failed') and con.get('configuration_sha256')==current['configuration_sha256']:
                data=node.get('payload') or {}
                use=appraisal_use(node) if role=='A' else {}
                error=data.get('reappraisal_failure') or data.get('error') or (node if role=='B' and node.get('status')=='failed' else {})
                if not isinstance(error,dict):error={}
                public_error={key:error[key] for key in ('failure_code','failure_category','failure_reason','http_status','contract_path','contract_reason','contract_issues','error_type','repair_skipped') if key in error}
                actual={'at':t.get('timestamp'),'status':'failed' if use.get('last_attempt')=='failed' else node.get('status'),
                    'effective_evaluation_status':use.get('source'),'evaluation_use':use or None,
                    'retained_valid_result':use.get('source')=='retained_previous_valid_evidence','failure':public_error,
                    'elapsed_ms':node.get('elapsed_ms'),'provider':current['provider'],'model':current['model'],'service':current['service']};break
        use_turn=actual and (not last or (actual.get('at') or 0)>=last['at']);latest=actual if use_turn else last
        value='unconfigured' if not current['model'] else 'saved_not_tested'
        if current['model'] and not latest and matching and matching[0].get('operation') in ('models','connect'):
            value='connected_only' if matching[0].get('ok') else 'connection_failed'
        if latest and current['model']:
            value=('last_call_succeeded' if actual['status']=='ok' else 'last_call_failed') if use_turn else ('tested' if last['ok'] else 'failed')
        connections[role]={**current,'configured':bool(current['model']),'last_test':last,'last_probe':matching[0] if matching else None,'last_turn_call':actual,'latest':latest,'status':value}

    state=engine.store.meta(ar.KEY);streams=[]
    for key,row in state['streams'].items():
        history=[v['result'] for v in row['events'].values()]
        streams.append({'key':key,**row['identity'],'revision':row['revision'],'last_at':row['last_at'],'model_version':row['model_version'],'history':history[-80:]})
    return {'schema':'pmm-workspace/2.8.1','subject_id':state['subject_id'],'mode':config['pmm281']['mode'],'connections':connections,
        'affect':{'revision':state['revision'],'streams':streams},'expressive_drive':ed.status_summary(engine.store,engine.profile()),
        'emotion_training':AffectLearning(engine).status(),
        'neural_training':co.status(),'traces':traces,'default_engine':'NumPy forward / optional PyTorch training'}

def preview(engine,body):
    """No bridge/scheduler starts; all turns, learning and journal writes use a copy."""
    from .storage import Store
    from .common import Config,atomic_json
    from .engine import Engine
    text=body.get('text','')
    if not isinstance(text,str) or not 1<=len(text.strip())<=16000:raise ValueError('请输入 1–16000 字符的测试事件')
    with engine.lock,engine.store.lock:
        snap=engine.store.snapshot();cfg=engine.config.get();owner=engine.store.meta('identity')['id']
    if body.get('subject_id')!=owner:raise ValueError('当前主体已变化')
    with tempfile.TemporaryDirectory(prefix='huaian-pmm-preview-') as directory:
        cfg=copy.deepcopy(cfg);cfg['qq']['enabled']=False;cfg['social']['enabled']=False;cfg['pmm']['managed']=False
        atomic_json(Path(directory)/'config.json',cfg);store=Store(directory);store.restore(snap);config=Config(directory);work=None
        try:
            work=Engine(store,config);work.provider_factory=engine.provider_factory;work.pmm_provider_factory=engine.pmm_provider_factory
            sid=body.get('session_id')
            if sid:store.get_session(sid)
            else:sid=store.session()
            result=work.turn(sid,text)
            return {'isolated':True,'external_messages_sent':0,'production_state_writes':0,'reply':result['reply'],'trace':result['trace'],
                'simulation_kind':'actual_providers_and_numeric_computation_in_temporary_database'}
        finally:
            if work:work.journal.close()
            store.close()
