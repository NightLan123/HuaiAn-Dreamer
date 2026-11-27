from __future__ import annotations
import copy, json, os, time, threading, secrets, urllib.parse, http.cookies, mimetypes,hashlib
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from .common import VERSION, dumps, uid, now, atomic_json
from .storage import Store
from .common import Config,PROVIDER_FIELDS
from .engine import Engine
from .provider import Provider, ProviderError
from .qq import QQBridge,verify_event
from .pmm import PMM
from .pmm_interface import create_pmm, MODEL_ID,load_numeric
from .registry_pmm import MODEL_ID as LEARNED_ID
from .packages import validate_metadata
from .presets import PRESETS
from .subjects import Subjects
from .connections import Presets, patch as preset_patch, check_routes
from .psychology import parse_records, validate_profile, empty_profile, STATE_KEYS, TRAITS

class Runtime:
    def __init__(self,data_dir,root,host='127.0.0.1',port=8765,preview=False,*,headless=False):
        from .data_guard import prepare_upgrade,complete_upgrade
        self.upgrade=prepare_upgrade(data_dir);self.startup_ready=False
        self.root=Path(root);self.subjects=Subjects(data_dir);self.contexts={};self.presets=Presets(data_dir);self.bridges_started=False
        import sqlite3
        self.routing=sqlite3.connect(self.subjects.root/'qq_routes.sqlite3',check_same_thread=False)
        self.routing.execute('CREATE TABLE IF NOT EXISTS routes (event_key TEXT PRIMARY KEY,persona_id TEXT NOT NULL,created_at REAL)');self.routing.commit()
        self.migrate_connections()
        self.store,self.config,self.engine,self.bridge=self.context(self.subjects.catalog['active'])
        self.jobs={};self.job_lock=threading.RLock();self.token=secrets.token_urlsafe(32)
        from .scheduler import Scheduler
        self.scheduler=Scheduler(self)
        self.reloading=False;self.host=host;self.port=port;self.preview=preview;self.http=None
        self.build_id=None if headless else hashlib.sha256(VERSION.encode()+b''.join((self.root/'web'/p).read_bytes() for p in ('index.html','app.js','style.css'))).hexdigest()
        # Migrate every identity before marking an upgrade complete, without starting QQ.
        for item in self.subjects.available():self.context(item['id'])
        try:complete_upgrade(data_dir,self.upgrade)
        except Exception:
            for st,cfg,engine,bridge in self.contexts.values():engine.journal.close();st.close()
            self.routing.close();raise
        self.startup_ready=True
        self.engine.recover_delivered()
        self.pmm_process=None;self.pmm_start_error=''
        if self.config.get()['pmm'].get('managed') and self.config.get()['pmm']['mode']!='api':
            try:self.start_pmm()
            except (ValueError,ProviderError):self.pmm_start_error='本机 PMM 服务启动失败，请在双模型设置中重新启动或检查连接。'
    def migrate_connections(self):
        marker=self.subjects.root/'connection_migration_v212.json'
        if marker.exists():return
        legacy=Config(self.subjects.root).get();active=self.subjects.catalog['active']
        atomic_json(self.subjects.root/'backups'/'pre_v212_connections.json',legacy)
        for item in self.subjects.catalog['items']:
            directory=self.subjects.directory(item['id']);path=directory/'config.json'
            if item['id']!=self.subjects.catalog['default'] and path.exists():continue
            c=copy.deepcopy(legacy)
            if item['id']!=active:c['qq']['enabled']=False;c['qq']['inbound_token']=uid()+uid()
            atomic_json(path,c)
        atomic_json(marker,{'version':1,'migrated_at':now(),'qq_owner':active})
    def context(self,identifier):
        self.subjects.require_available(identifier)
        if identifier not in self.contexts:
            directory=self.subjects.directory(identifier)
            cfg=Config(directory);cfg.shared_root=self.subjects.root;st=Store(directory,create=False)
            try:engine=Engine(st,cfg,defer_recovery=not self.startup_ready)
            except Exception:st.close();raise
            self.contexts[identifier]=(st,cfg,engine,QQBridge(engine))
        return self.contexts[identifier]
    def start_bridges(self):
        if self.preview:return
        configs={item['id']:Config(self.subjects.directory(item['id'])).get() for item in self.subjects.available()}
        check_routes(configs)
        self.bridges_started=True
        for identifier in configs:
            bridge=self.context(identifier)[3]
            if not bridge.thread.is_alive() and not bridge.stop.is_set():bridge.start()
        self.scheduler.start()
    def all_busy(self):
        return any(ctx[3].busy or ctx[2].consolidation.status()['running'] or ctx[2].social.status()['running'] or ctx[2].memory_lifecycle.status()['running'] or ctx[2].learning.status()['running'] or bool(ctx[2].learning.experiences.thread and ctx[2].learning.experiences.thread.is_alive()) or bool(ctx[2].motive_generation.thread and ctx[2].motive_generation.thread.is_alive()) for ctx in self.contexts.values()) or any(j['status'] in ('queued','running') for j in self.jobs.values())
    def route_event(self,raw,headers,query,identifier=None):
        event=json.loads(raw)
        if not isinstance(event,dict):raise ValueError('QQ 事件应为对象')
        if identifier:self.subjects.require_available(identifier)
        ids=[identifier] if identifier else [item['id'] for item in self.subjects.available()]
        verified=[];matches=[]
        from .qq import parse_event
        for ident in ids:
            st,cfg,engine,bridge=self.context(ident);c=cfg.get()
            if not verify_event(raw,headers,query,c):continue
            if c['qq'].get('self_id') and c['qq']['self_id']!=str(event.get('self_id','')):continue
            verified.append(bridge)
            if parse_event(event,c):matches.append(bridge)
        if not verified:raise PermissionError('事件验证失败或机器人 QQ 号不匹配')
        if len(matches)>1:raise ValueError('QQ 路由冲突，未交给任何人格')
        if matches:
            bridge=matches[0];parsed=parse_event(event,bridge.config.get());ident=bridge.store.meta('identity')['id']
            with self.job_lock,self.routing:
                self.routing.execute('INSERT OR IGNORE INTO routes VALUES (?,?,?)',(parsed['key'],ident,now()))
                owner=self.routing.execute('SELECT persona_id FROM routes WHERE event_key=?',(parsed['key'],)).fetchone()[0]
                if owner!=ident:return {'accepted':False,'duplicate':True,'reason':'此 QQ 消息已分配给另一个人格，不重复处理'}
                return bridge.receive(event)
        if len(verified)==1:return verified[0].receive(event)
        return {'accepted':False,'reason':'没有匹配此消息的启用人格或白名单'}
    def preset_action(self,body):
        op=body.get('op','save')
        if op=='apply':
            row=self.presets.get(body['id']);value=copy.deepcopy(row['value'])
            # Merely applying a saved QQ connection never enables contact.
            if row['kind']=='qq':value['enabled']=False
            result=self.configure(preset_patch(row['kind'],value))
            with self.store.lock,self.store.db:
                bindings=self.store.meta('connection_bindings') or {}
                bindings[row['kind']]={'preset_id':row['id'],'name':row['name'],'copied_at':now()}
                self.store.setmeta('connection_bindings',bindings)
            return {'config':result,'presets':self.presets.list()}
        if op=='test':return self.presets.test(body['id'],self.config.get(),self.engine.journal,self.engine.profile()['id'])
        return {'presets':self.presets.mutate(body,self.config.get())}

    def state(self):
        errors={}
        def optional(name,fn,fallback):
            try:return fn()
            except Exception as exc:
                from .support import exception_frames
                diagnostic={'request_id':uid(),'component':name,**exception_frames(exc)}
                print('Local component failed:',dumps(diagnostic),flush=True)
                errors[name]={'code':'LOCAL_COMPONENT_FAILED','message':'此模块读取失败，其他本地页面可继续使用','request_id':diagnostic['request_id']}
                return fallback
        result={'version':VERSION,'build_id':self.build_id,'identity':self.store.meta('identity'),'state':self.store.meta('state'),
                'config':self.config.public(),'connection_presets':optional('presets',self.presets.list,[]),'connection_bindings':self.store.meta('connection_bindings') or {},'presets':PRESETS,'pmm_start_error':self.pmm_start_error,'sessions':self.store.sessions(),'model':optional('model',self.engine.model_info,{'mode':self.engine.mode(),'status':'本地模型信息读取失败','architecture':'暂不可用','metrics':{},'steps':None,'train_samples':None,'heldout_samples':None}),
                'memory_count':len(self.store.memories()),'data_dir':str(self.store.directory),
                'boundary_model':optional('boundaries',self.engine.boundaries.status,None),'cognition':optional('cognition',self.engine.cognition.status,None),'memory_lifecycle':optional('memory',self.engine.memory_lifecycle.status,None),'group_attention':optional('groups',self.engine.group_attention.status,None),'consolidation':optional('consolidation',self.engine.consolidation.status,None),'csrf':self.token,'reloading':self.reloading,'active_jobs':[j for j in self.jobs.values() if j['status'] in ('queued','running')],'profile':self.engine.profile(),
                'psychology_registry':__import__('persona.registry',fromlist=['FIELDS']).FIELDS,'dyads':self.store.meta('pmm_dyads') or {},'expression':self.store.meta('pmm_expression'),'synthesis':self.store.meta('pmm_synthesis'),'activity':self.engine.activity(),'personas':self.subjects.catalog_view(),'interlocutors':self.store.meta('pmm_interlocutors') or {}}
        from .capabilities import report
        result['capabilities']=report(self.config.get(),result['model'])
        from .traits import DISPOSITION_REGISTRY,snapshot
        result['trait_snapshot']=snapshot(result['profile']);result['disposition_registry']=DISPOSITION_REGISTRY
        result['affect_state']=self.engine.affect_state()
        from . import expression_drive as ed
        result['expressive_drive']=optional('expressive_drive',lambda:ed.status_summary(self.store,result['profile']),None)
        from .affect import CATALOG,label_details
        result['emotion_catalog']=CATALOG;result['emotion_details']=label_details(self.store.meta('pmm_affect'))
        result['learning_center']=optional('learning',self.engine.learning.status,None)
        result['evidence_trace']=optional('evidence',self.engine.evidence.trace,None)
        result['trait_review']=self.engine.review_traits(False)
        from .pragmatics import status as pragmatic_status
        result['pragmatics']=optional('pragmatics',lambda:pragmatic_status(self.store.meta('pmm_pragmatics')),None)
        from .joint_expression import timeline
        result['de_turns']=optional('de_turns',lambda:timeline(self.engine),None)
        from .ui3_projection import build_ui3_overview
        result['ui3_overview']=optional('ui3_overview',lambda:build_ui3_overview(self,result),None)
        result.update(component_errors=errors,data_status={'root':str(self.subjects.root.resolve()),'upgrade_kind':self.upgrade['kind'],'backup':self.upgrade.get('backup')});return result
    def task(self,kind,worker,sid=''):
        if self.reloading:raise ValueError('程序正在应用更新，请稍后重试')
        with self.job_lock:
            active=[j for j in self.jobs.values() if j['status'] in ('queued','running')]
            if any(not (kind=='chat' and j['kind']=='learning' or kind=='learning' and j['kind']=='chat') for j in active):raise ValueError('还有任务正在处理，请等待完成')
            task_store=self.store
            jid=uid();self.jobs[jid]={'id':jid,'kind':kind,'status':'queued','phase':'等待处理','session_id':sid,'created_at':now(),'started_at':now(),'persona_id':task_store.meta('identity')['id']}
        def run():
            try:
                self.jobs[jid]['status']='running'
                result=worker(lambda phase:self.jobs[jid].update(phase=phase))
                self.jobs[jid].update(status='done',result=result,phase='完成')
                with task_store.lock,task_store.db:task_store.event('task_completed',{'job_id':jid,'kind':kind})
            except Exception as ex:
                message=str(ex) if isinstance(ex,(ValueError,ProviderError)) else '处理失败；请查看终端错误类型'
                from .support import exception_frames
                diagnostic=exception_frames(ex)
                if not isinstance(ex,(ValueError,ProviderError)):print('Task failed:',dumps(diagnostic),flush=True)
                with task_store.lock,task_store.db:task_store.event('task_failed',{'job_id':jid,'exception_type':diagnostic['type'],'frames':diagnostic['frames'],'task':kind})
                self.jobs[jid].update(status='error',error=message,diagnostics=getattr(ex,'details',{}))
            with self.job_lock:
                old=[k for k,v in self.jobs.items() if v['status'] not in ('queued','running')]
                for k in old[:-100]:self.jobs.pop(k,None)
        thread=threading.Thread(target=run,daemon=True)
        if kind in ('learning','distill'):self.engine.learning.thread=thread
        thread.start()
        return {'job_id':jid}
    def submit(self,sid,text,client_event_id=None):
        engine=self.engine
        if client_event_id is not None and (not isinstance(client_event_id,str) or not 1<=len(client_event_id)<=128):raise ValueError('本机输入事件 ID 无效')
        if client_event_id is None:return self.task('chat',lambda progress:engine.turn(sid,text,progress=progress),sid)
        return self.task('chat',lambda progress:engine.turn(sid,text,progress=progress,turn_context={'sources':['web:'+sid+':'+client_event_id]}),sid)
    def ensure_idle(self):
        if self.reloading or self.bridge.busy or self.engine.consolidation.status()['running'] or self.engine.social.status()['running'] or self.engine.memory_lifecycle.status()['running'] or self.engine.learning.status()['running'] or bool(self.engine.learning.experiences.thread and self.engine.learning.experiences.thread.is_alive()) or bool(self.engine.motive_generation.thread and self.engine.motive_generation.thread.is_alive()) or any(j['status'] in ('queued','running') for j in self.jobs.values()):raise ValueError('请等当前对话或蒸馏完成后再修改连接、权重或切换人格')
    def pause_bridge(self):
        bridge=self.bridge
        if not bridge.lifecycle.acquire(blocking=False):raise ValueError('QQ 正在处理消息，请稍后再操作')
        try:bridge.stop.set()
        finally:bridge.lifecycle.release()
        if bridge.thread.is_alive():bridge.thread.join(timeout=2)
        if bridge.thread.is_alive():raise ValueError('QQ 尚未停止，请稍后再操作')
    def switch(self,identifier):
        with self.job_lock:
            # Jobs capture their engine; switching the UI never reroutes queued QQ events.
            if any(j['status'] in ('queued','running') for j in self.jobs.values()):raise ValueError('请等当前管理任务完成后再切换')
            target=self.context(identifier)
            self.subjects.activate(identifier)
            self.store,self.config,self.engine,self.bridge=target
            if self.bridges_started and not self.bridge.thread.is_alive() and not self.bridge.stop.is_set():self.bridge.start()
            return self.state()
    def create_persona(self,body):
        with self.job_lock:
            self.ensure_idle();pack=body.get('package')
            if isinstance(pack,dict):
                checkpoint=pack.get('learning',{}).get('checkpoint') if pack.get('format') in ('persona-package/2.0','persona-package/2.1','persona-package/2.3') else pack.get('pmm')
                create_pmm(self.config.get(),checkpoint,pack.get('profile',{}).get('id',''))
            identifier=self.subjects.create(body.get('name','导入人格'),body.get('seed',''),pack,body.get('character'))
            c=copy.deepcopy(self.config.get());c['qq']['enabled']=False;c['qq']['self_id']='';c['qq']['inbound_token']=uid()+uid();c['qq']['allowed_users']=[];c['qq']['allowed_groups']=[]
            if 'social' in c:c['social']['enabled']=False;c['social']['recipients']=[]
            atomic_json(self.subjects.directory(identifier)/'config.json',c)
            return self.switch(identifier)
    def archive_persona(self,body,restore=False):
        with self.job_lock:
            if body.get('expected_active')!=self.subjects.catalog['active']:raise ValueError('当前角色已变化，请重新打开角色管理')
            if self.reloading or self.all_busy():raise ValueError('请等当前对话或后台整理结束后再管理回收站')
            identifier=body.get('id');ctx=self.contexts.get(identifier)
            if restore:
                if ctx and ctx[3].thread.is_alive():raise ValueError('该角色的连接正在停止，请稍后再恢复')
                configs={r['id']:Config(self.subjects.directory(r['id'])).get() for r in self.subjects.available()}
                configs[identifier]=Config(self.subjects.directory(identifier)).get()
                check_routes(configs)
                result=self.subjects.set_archived(identifier,False)
                if ctx:self.contexts[identifier]=(*ctx[:3],QQBridge(ctx[2]))
                return result
            if not ctx:return self.subjects.set_archived(identifier,True,body.get('confirm_name'))
            bridge=ctx[3];engine=ctx[2]
            if not bridge.lifecycle.acquire(blocking=False):raise ValueError('该角色正在处理消息，请稍后再删除')
            try:
                if not engine.lock.acquire(blocking=False):raise ValueError('该角色正在处理任务，请稍后再删除')
                try:
                    result=self.subjects.set_archived(identifier,True,body.get('confirm_name'))
                    bridge.stop.set()
                finally:engine.lock.release()
            finally:bridge.lifecycle.release()
            if bridge.thread.is_alive():bridge.thread.join(timeout=2)
            return result
    def clone_persona(self,body):
        with self.job_lock:
            self.ensure_idle()
            name=body.get('name','')
            if not isinstance(name,str) or not 1<=len(name.strip())<=60:raise ValueError('名称应为 1–60 个字符')
            from .registry_pmm import RegistryPMM
            pack=self.subjects.export_pack(self.engine,'template');source=self.engine.profile()['id'];identifier=uid()
            # Only known canonical fields transfer. Legacy archives may contain private summaries.
            profile={k:v for k,v in pack['profile'].items() if k in empty_profile(identifier,name)}
            profile.update(id=identifier,name=name.strip(),revision=0,updated_at=now(),distillation_runs=[])
            if pack['profile'].get('trait_profile'):
                profile['trait_profile']=copy.deepcopy(pack['profile']['trait_profile'])
                profile['trait_profile'].update(persona_id=identifier,version=0,promotion_history=[])
            pack.update(profile=profile,pmm=RegistryPMM(identity=identifier).export())
            created=self.subjects.create(name.strip(),pack=pack)
            # Fresh connections and parameters: copying a template grants no contact permission.
            cfg=Config(self.subjects.directory(created));cfg.update({'persona_name':name.strip()})
            st=self.context(created)[0]
            with st.lock,st.db:st.event('template_cloned',{'source_identity':source,'new_identity':created,'weights_reset':True,'connections_reset':True})
            return self.switch(created)
    def snapshot(self):
        with self.engine.lock:
            snap=self.store.snapshot();snap['model']=self.engine.model.export();snap['config']=self.config.public()
            snap['config'].pop('has_api_key',None);snap['config'].pop('has_extra_headers',None);snap['config'].pop('extra_header_names',None)
            snap['config']['pmm'].pop('has_api_key',None);snap['config']['pmm']['managed']=False
            for k in ('has_api_token','has_inbound_token','has_hmac_secret'):snap['config']['qq'].pop(k,None)
            snap['config']['qq']['enabled']=False
            snap['execution']=self.engine.journal.snapshot()
            return snap
    def restore(self,snapshot):
        import tempfile, math
        with self.job_lock:
            self.ensure_idle()
            from .execution import validate_snapshot
            validate_snapshot(snapshot.get('execution',{}))
            checkpoint=snapshot.get('model')
            if not isinstance(checkpoint,dict) or checkpoint.get('format') not in ('pmm/3','learned-pmm/2','learned-pmm/2.1',1,2):raise ValueError('备份缺少兼容的模型参数')
            model=None
            # Validate the complete database and every new payload before any live mutation.
            with tempfile.TemporaryDirectory() as temp:
                probe=Store(temp)
                try:probe.restore(snapshot);meta={r['key']:json.loads(r['value']) for r in probe.rows('SELECT * FROM meta')}
                finally:probe.close()
            identity=meta['identity']['id'];model=load_numeric(checkpoint,identity) if checkpoint['format'] in ('pmm/3','learned-pmm/2','learned-pmm/2.1') else load_numeric(None,identity);profile=meta.get('pmm_profile')
            if profile:
                validate_profile(profile)
                if profile['id']!=identity:raise ValueError('备份中的人格与主体标识不匹配')
            else:
                profile=empty_profile(identity,snapshot.get('config',{}).get('persona_name','未央'),snapshot.get('config',{}).get('persona_seed',''))
                profile['legacy_v02']={k:meta['state'][k] for k in ('traits','values','self_summary')}
            others=meta.get('pmm_interlocutors') or {}
            if not isinstance(others,dict):raise ValueError('对象模型格式无效')
            for key,item in others.items():
                validate_profile(item)
                if item['id']!=key:raise ValueError('对象模型标识不匹配')
            activity=meta.get('pmm_activity')
            if activity:
                for field in ('emotion','mood'):
                    if set(activity.get(field,{}))!=set(STATE_KEYS):raise ValueError('情绪状态维度无效')
                    for key,val in activity[field].items():
                        if not isinstance(val,(int,float)) or not math.isfinite(val) or not (-1 if key=='valence' else 0)<=val<=1:raise ValueError('情绪状态数值无效')
                if not isinstance(activity.get('updated_at'),(int,float)) or not math.isfinite(activity['updated_at']):raise ValueError('情绪更新时间无效')
            candidate=self.config.get();patch={k:v for k,v in snapshot.get('config',{}).items() if k in ('persona_name','persona_seed','retrieval_k','online_learning','max_retrieval_rounds')}
            candidate.update(patch);self.config.validate(candidate)
            validation_meta={**meta,'pmm_profile':profile,'pmm_checkpoint':model.export()};validate_metadata(validation_meta)
            model=create_pmm(candidate,model.export(),identity)
            if identity!=self.store.meta('identity')['id']:
                if identity not in [i['id'] for i in self.subjects.catalog['items']]:self.subjects.create(profile['name'],pack={'format':'persona-package/3','profile':profile,'pmm':model.export()})
                self.switch(identity)
            self.pause_bridge()
            try:
                with self.engine.lock:
                    atomic_json(self.store.directory/'backups'/f'before_restore_{int(now())}.json',self.snapshot())
                    self.engine.journal.merge_snapshot(snapshot.get('execution',{}))
                    self.store.restore(snapshot)
                    with self.store.lock,self.store.db:
                        self.store.setmeta('pmm_checkpoint',model.export());self.store.setmeta('pmm_profile',profile)
                    self.engine.journal.close();self.engine=Engine(self.store,self.config)
                    if patch:self.config.update(patch)
            finally:
                self.bridge=QQBridge(self.engine);self.contexts[self.store.meta('identity')['id']]=(self.store,self.config,self.engine,self.bridge);self.bridge.start()
            return {'ok':True,'identity':self.store.meta('identity'),'migrated_v02':checkpoint['format'] not in ('pmm/3','learned-pmm/2','learned-pmm/2.1')}
    def configure(self,body):
        from .common import config_shape
        config_shape(body,partial=True)
        with self.job_lock:
            self.ensure_idle()
            with self.engine.lock:
                body=copy.deepcopy(body)
                if body.get('qq',{}).get('enabled') is False:body.setdefault('social',{})['enabled']=False
                old=self.config.get();candidate_config=self.config.update(body,commit=False)
                mode=candidate_config['pmm']['mode']
                if mode=='learned':candidate_config['pmm']['model']=LEARNED_ID
                elif mode=='legacy' and candidate_config['pmm']['backend']=='local':candidate_config['pmm']['model']=MODEL_ID
                if candidate_config==old:return self.config.public()
                configs={item['id']:Config(self.subjects.directory(item['id'])).get() for item in self.subjects.available()}
                configs[self.store.meta('identity')['id']]=candidate_config;check_routes(configs)
                candidate=create_pmm(candidate_config,self.engine.model.export(),self.store.meta('identity')['id'])
                if mode!=old['pmm']['mode']:self.engine.save_weight_version('切换 PMM 模式前自动备份')
                atomic_json(self.config.path,candidate_config)
                try:
                    with self.store.lock,self.store.db:
                        self.store.setmeta('pmm_checkpoint',candidate.export())
                        self.store.event('config_updated',{'keys':[k for k in body if k not in ('api_key','extra_headers','qq')],'identity_id':self.store.meta('identity')['id'],'pmm_mode':mode})
                except Exception:
                    atomic_json(self.config.path,old);raise
                self.engine.model=candidate
                return self.config.public()

    def test_connection(self,role):
        started=time.monotonic()
        try:
            if role=='pmm':result=self.engine.test_pmm()
            else:
                from .token_ledger import bind_factory
                client=bind_factory(Provider,self.engine.journal,self.engine.profile()['id'],'General')(self.config.get())
                client.trace_context={'component_role':'General','task_name':'connection_test','trigger_reason':'explicit_connection_test'}
                result=client.test()
            result['duration_ms']=round((time.monotonic()-started)*1000)
            with self.store.lock,self.store.db:self.store.event('connection_test',{'role':role,'ok':True,**result})
            return result
        except ProviderError as ex:
            with self.store.lock,self.store.db:self.store.event('connection_test',{'role':role,'ok':False,'duration_ms':round((time.monotonic()-started)*1000),'error':str(ex),'diagnostics':ex.details})
            raise

    def copy_general_to_pmm(self):
        c=self.config.get()
        return self.configure({'pmm':{'api':{k:c[k] for k in PROVIDER_FIELDS}}})

    def start_pmm(self):
        import subprocess,sys,socket
        from .provider import request_json
        self.ensure_idle();c=self.config.get()['pmm']
        if c['mode']=='api':raise ValueError('API-PMM 使用独立大模型连接；如需本机训练服务，请先选择 Learned-PMM')
        model_id=LEARNED_ID if c['mode']=='learned' else MODEL_ID;key=c['api_key'] or secrets.token_urlsafe(32)
        parsed=urllib.parse.urlsplit(c['base_url'])
        port=parsed.port or 8766 if parsed.hostname in ('127.0.0.1','localhost') else 8766
        base=f'http://127.0.0.1:{port}'
        try:
            h=request_json(base+'/health',token=key,timeout=1)
            if h.get('contract')=='pmm-http/1':
                self.configure({'pmm':{'backend':'http','base_url':base,'api_key':key,'model':model_id,'managed':True}})
                self.pmm_start_error='';return self.engine.model.test()
        except (ValueError,ProviderError):pass
        self.close_pmm()
        # Find a free loopback port. The child owns the final bind; failure is explicit.
        with socket.socket() as probe:
            try:probe.bind(('127.0.0.1',port))
            except OSError:probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        env=os.environ.copy();env['PERSONA_PMM_API_KEY']=key;env['OPENBLAS_NUM_THREADS']='1'
        proc=subprocess.Popen([sys.executable,str(self.root/'run_pmm_service.py'),'--port',str(port),'--parent-stdin'],cwd=self.root,env=env,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.pmm_process=proc
        try:
            ready=False
            for _ in range(40):
                if proc.poll() is not None:raise ProviderError('PMM 子进程启动失败；可在终端运行 run_pmm_service.py 查看错误')
                try:
                    h=request_json(base+'/health',token=key,timeout=1)
                    if h.get('contract')=='pmm-http/1':ready=True;break
                except ProviderError:pass
                time.sleep(.1)
            if not ready:raise ProviderError('PMM 服务未在启动期限内就绪')
            self.configure({'pmm':{'backend':'http','base_url':base,'api_key':key,'model':model_id,'managed':True}})
            result=self.engine.model.test();self.pmm_start_error='';return result
        except Exception:self.close_pmm();raise

    def close_pmm(self):
        proc=self.pmm_process
        if proc and proc.poll() is None:
            if proc.stdin:proc.stdin.close()
            try:proc.wait(timeout=3)
            except __import__('subprocess').TimeoutExpired:proc.kill();proc.wait(timeout=3)
        self.pmm_process=None

    def close(self):
        self.scheduler.close()
        for ctx in self.contexts.values():ctx[3].stop.set()
        for ctx in self.contexts.values():
            if ctx[3].thread.is_alive():ctx[3].thread.join()
            for thread in (ctx[2].consolidation.thread,ctx[2].social.thread,ctx[2].memory_lifecycle.thread,ctx[2].learning.thread,ctx[2].learning.experiences.thread,ctx[2].motive_generation.thread):
                if thread and thread.is_alive():thread.join()
        self.close_pmm()
        for ctx in self.contexts.values():ctx[2].journal.close();ctx[0].close()
        self.routing.close()

    def reload(self):
        if self.reloading:return {'ok':True}
        self.reloading=True
        self.scheduler.stop.set()
        def drain():
            for ctx in self.contexts.values():ctx[3].stop.set()
            while True:
                with self.job_lock:pending=any(j['status'] in ('queued','running') for j in self.jobs.values())
                if not self.all_busy() and not pending:break
                time.sleep(.2)
            self.http.shutdown()
        threading.Thread(target=drain,daemon=True).start()
        return {'ok':True}

class Handler(BaseHTTPRequestHandler):
    server_version='PersonaDialogue';sys_version=''
    def log_message(self,*args):pass  # URLs can contain a QQ verification token.
    @property
    def app(self):return self.server.app
    def host_ok(self):
        host=self.headers.get('Host','').split(':')[0].lower()
        return host in ('127.0.0.1','localhost','terminal.local')
    def auth(self):
        try:
            c=http.cookies.SimpleCookie(self.headers.get('Cookie',''))
            return secrets.compare_digest(c.get(self.cookie_name).value,self.app.token)
        except (AttributeError,KeyError):return False
    @property
    def cookie_name(self):return 'persona_session_'+str(self.app.port)
    def cookie(self):return f'{self.cookie_name}={self.app.token}; HttpOnly; SameSite=Strict; Path=/'
    def origin_ok(self):
        origin=self.headers.get('Origin')
        return self.headers.get('Sec-Fetch-Site')!='cross-site' and (not origin or origin in (f'http://127.0.0.1:{self.app.port}',f'http://localhost:{self.app.port}',f'http://terminal.local:{self.app.port}',*(['http://terminal.local:4173'] if self.app.preview else [])))
    def failure(self,exc,status=500):
        from .support import exception_frames
        diagnostic={'request_id':getattr(self,'request_id',uid()),'method':self.command,'route':urllib.parse.urlsplit(self.path).path,**exception_frames(exc)}
        print('Request failed:',dumps(diagnostic),flush=True)
        return self.send({'error':str(exc) if isinstance(exc,ValueError) else '本地服务读取或保存失败，请复制诊断编号','code':'INVALID_REQUEST' if status==400 else 'LOCAL_SERVICE_ERROR','request_id':diagnostic['request_id'],'failed_fields':getattr(exc,'failed_fields',[])},status)
    def send(self,data,status=200,ctype='application/json; charset=utf-8',extra=None):
        if not getattr(self,'request_id',None):self.request_id=uid()
        if isinstance(data,dict) and status>=400:data={**data,'message':data.get('message',data.get('error','请求失败')),'failed_fields':data.get('failed_fields',[]),'request_id':self.request_id,'code':data.get('code',{401:'SESSION_EXPIRED',403:'ACCESS_DENIED',404:'NOT_FOUND',500:'LOCAL_SERVICE_ERROR'}.get(status,'INVALID_REQUEST'))}
        raw=dumps(data).encode() if not isinstance(data,bytes) else data
        self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Request-ID',self.request_id);self.send_header('X-App-Version',VERSION);self.send_header('X-App-Build',self.app.build_id)
        self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        for k,v in (extra or {}).items():self.send_header(k,v)
        self.end_headers()
        try:self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
    def do_GET(self):
        self.request_id=uid()
        if not self.host_ok():return self.send({'error':'非法 Host'},403)
        u=urllib.parse.urlsplit(self.path);path=u.path;qs=urllib.parse.parse_qs(u.query)
        if path=='/api/health':return self.send({'ok':True,'version':VERSION,'build_id':self.app.build_id,'local_only':True})
        if path=='/api/bootstrap':
            if not self.origin_ok():return self.send({'error':'来源不匹配','code':'ORIGIN_MISMATCH'},403)
            return self.send({'version':VERSION,'build_id':self.app.build_id,'csrf':self.app.token},extra={'Set-Cookie':self.cookie()})
        if path in ('/','/ui-shell','/ui-shell/','/ui-shell/index.html','/index.html') and qs.get('ui',['shell'])[0]!='legacy':
            p=self.app.root/'ui-shell'/'index.html'
            if p.exists():
                raw=p.read_bytes().replace(b'__APP_BUILD__',self.app.build_id.encode())
                return self.send(raw,ctype='text/html; charset=utf-8',extra={'Set-Cookie':self.cookie()})
        if path.startswith(('/src/','/public/')):
            ui_root=(self.app.root/'ui-shell').resolve()
            target=(ui_root/path.lstrip('/')).resolve()
            if str(target).startswith(str(ui_root)) and target.is_file():
                ctype=mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
                if ctype.startswith('text/') or ctype in ('application/javascript','application/json'):ctype+='; charset=utf-8'
                return self.send(target.read_bytes(),ctype=ctype)
        if path in ('/','/legacy','/app.js','/style.css','/favicon.svg'):
            name='index.html' if path in ('/','/legacy') else path[1:];p=self.app.root/'web'/name
            if not p.exists():return self.send({'error':'资源不存在'},404)
            extra={'Set-Cookie':self.cookie()} if path in ('/','/legacy') else {}
            raw=p.read_bytes().replace(b'__APP_BUILD__',self.app.build_id.encode()) if path in ('/','/legacy') else p.read_bytes()
            ctype={'/':'text/html; charset=utf-8','/legacy':'text/html; charset=utf-8','/app.js':'text/javascript; charset=utf-8','/style.css':'text/css; charset=utf-8','/favicon.svg':'image/svg+xml'}[path]
            return self.send(raw,ctype=ctype,extra=extra)
        if not self.auth():return self.send({'error':'请从程序首页打开管理界面'},401)
        # Jobs retain their own persona and engine. Progress reads must remain
        # available while another request waits for an export or a model call.
        if path.startswith('/api/jobs/'):
            job=self.app.jobs.get(path.rsplit('/',1)[-1])
            return self.send(dict(job) if job else {'error':'任务不存在'},200 if job else 404)
        try:
            with self.app.job_lock:
                if path=='/api/research/workspace':
                    state=self.app.store.meta('pmm283_research_drive') or {}
                    return self.send({'revision':state.get('revision',0),'sessions':self.app.store.sessions(),
                        'motives':[m for row in state.get('streams',{}).values() for m in row.get('motives',{}).values()],
                        'sampling':self.app.engine.affect_sampling.status()})
                if path=='/api/notifications':
                    from .notifications import page
                    return self.send(page(self.app.store,qs.get('offset',['0'])[0],qs.get('limit',['50'])[0]))
                if path=='/api/affect/samples':
                    from .research_operations import samples
                    return self.send(samples(self.app.store,qs.get('stream_key',[None])[0],qs.get('from',[None])[0],qs.get('to',[None])[0],qs.get('limit',['200'])[0],qs.get('offset',['0'])[0]))
                if path=='/api/affect/sampling':return self.send(self.app.engine.affect_sampling.status())
                if path=='/api/scheduler':
                    return self.send(self.app.scheduler.status(self.app.store.meta('identity')['id']))
                if path=='/api/pmm283/motives/history':
                    from .motive_history import history
                    return self.send(history(self.app.store,qs.get('scope',[None])[0],qs.get('person',[None])[0],
                        qs.get('motive_id',[None])[0],qs.get('cursor',[None])[0],qs.get('limit',['50'])[0]))
                if path=='/api/pmm283/expressive-drive':
                    from . import expression_drive as ed
                    scope=qs.get('scope',[None])[0]
                    if scope:return self.send(self.app.engine.expressive_drive_state(scope,qs.get('person',[scope])[0],qs.get('session_id',[None])[0]))
                    return self.send(ed.status_summary(self.app.store,self.app.engine.profile()))
                if path=='/api/pmm281/status':
                    from .pmm_workspace import status
                    return self.send(status(self.app.engine))
                if path in ('/api/pmm28/status','/api/pmm28/traces','/api/pmm28/longitudinal'):
                    from .pmm_coordinator import PMMCoordinator
                    co=PMMCoordinator(self.app.engine)
                    if path.endswith('/longitudinal'):return self.send(self.app.store.meta('pmm28_estimator') or {'revision':0,'protocols':{},'transitions':{},'proposals':{}})
                    return self.send(co.status() if path.endswith('/status') else {'traces':co.traces(scope=qs.get('scope',[None])[0])})
                if path=='/api/support':
                    from .support import report
                    return self.send(dumps(report(self.app)).encode(),extra={'Content-Disposition':'attachment; filename=HuaiAn_Dreamer_Diagnostics.json'})
                if path in ('/api/source','/api/source-index'):
                    from scripts.export_sources import build
                    result=build(self.app.root);key='source' if path=='/api/source' else 'index';name='HuaiAn_Dreamer_Source.md' if key=='source' else 'HuaiAn_Dreamer_Code_Index.md'
                    return self.send(result[key].encode(),ctype='text/plain; charset=utf-8',extra={'Content-Disposition':'attachment; filename='+name})
                if path=='/api/pmm282/history':
                    from .runtime_history import history
                    return self.send(history(self.app.engine,qs.get('turn_id',[None])[0],int(qs.get('limit',['100'])[0]),
                        int(qs.get('offset',['0'])[0]),qs.get('date_from',[None])[0],qs.get('date_to',[None])[0]))
                if path=='/api/persona/views':
                    service=self.app.engine.persona_views;profile=self.app.engine.profile()
                    selected=qs.get('version_id',[None])[0]
                    if selected:
                        view=service.get(profile,selected)
                        view={**view,'id':view['version_id'],'version':view['sequence']}
                        return self.send({'view':view,'is_current':selected==service.current(profile)['version_id']})
                    listing=service.list(profile)
                    return self.send({'current_id':listing['current_version_id'],
                        'versions':[{**v,'id':v['version_id'],'version':v['sequence']} for v in listing['items']]})
                if path=='/api/token-ledger':
                    if 'limit' in qs or 'offset' in qs or 'date_from' in qs or 'date_to' in qs:
                        from .runtime_history import calls_page
                        return self.send(calls_page(self.app.engine,qs.get('limit',['50'])[0],qs.get('offset',['0'])[0],
                            qs.get('turn_id',[None])[0],qs.get('date_from',[None])[0],qs.get('date_to',[None])[0],
                            {f:qs[f][0] for f in ('component_role','model','phase_id') if f in qs}))
                    from .runtime_history import calls_view,summary_view
                    rows=calls_view(self.app.engine,qs.get('turn_id',[None])[0])
                    for field in ('component_role','model','phase_id'):
                        if field in qs:rows=[r for r in rows if r.get(field)==qs[field][0]]
                    return self.send({'schema':'token-ledger/2.8.2','calls':rows,'summary':summary_view(rows)})
                if path=='/api/token-prices':
                    from .token_prices import TokenPrices
                    return self.send(TokenPrices(self.app.store).get())
                if path in ('/api/execution','/api/execution/export'):
                    from .execution import public_trace,metrics
                    runs=self.app.engine.journal.recent(2000 if path.endswith('/export') else 60)
                    if path.endswith('/export'):
                        content='\n'.join(dumps(public_trace(r)) for r in runs)+'\n'+dumps({'summary':metrics(runs)})+'\n'
                        return self.send(content.encode(),ctype='application/x-ndjson; charset=utf-8',extra={'Content-Disposition':'attachment; filename=HuaiAn_Execution_Trace.jsonl'})
                    return self.send({'runs':[public_trace(r) for r in runs],'outbox':self.app.engine.journal.outbox(),'metrics':metrics(runs)})
                if path=='/api/claims':return self.send(self.app.engine.claims.recent(qs.get('scope',['private:web:owner'])[0]))
                if path=='/api/boundaries':return self.send(self.app.engine.boundaries.status())
                if path=='/api/boundaries/history':return self.send(self.app.engine.boundaries.history(int(qs.get('offset',['0'])[0]),int(qs.get('limit',['10'])[0]),qs.get('q',[''])[0],qs.get('scope',[''])[0],qs.get('boundary_id',[''])[0]))
                if path=='/api/learning':return self.send(self.app.engine.learning.status(int(qs.get('offset',['0'])[0])))
                if path=='/api/learning/job':return self.send(self.app.engine.learning.detail(qs.get('id',[''])[0]))
                if path=='/api/learning/activities':return self.send(self.app.engine.learning.activities(int(qs.get('offset',['0'])[0])))
                if path=='/api/social-graph':return self.send(self.app.engine.social_graph.query(qs.get('scope',[]),qs.get('person',[None])[0]))
                if path=='/api/cognition':return self.send(self.app.engine.cognition.status())
                if path=='/api/ui3/overview':
                    from .ui3_projection import build_ui3_overview
                    return self.send(build_ui3_overview(self.app))
                if path=='/api/state':return self.send(self.app.state())
                if path=='/api/messages':
                    offset=int(qs.get('offset',['0'])[0])
                    if not 0<=offset<=100_000_000:raise ValueError('历史分页位置无效')
                    return self.send(self.app.store.history(qs.get('session',[''])[0],2000,offset))
                if path=='/api/memories':return self.send(self.app.engine.memory_lifecycle.describe(self.app.store.memories(all_status=True)))
                if path=='/api/memory/sources':
                    return self.send(self.app.engine.memory_lifecycle.sources(qs.get('id',[''])[0]))
                if path=='/api/memory/erase-preview':
                    from .erasure import erase_preview
                    return self.send(erase_preview(self.app.engine,qs.get('scope',[''])[0]))
                if path=='/api/events':return self.send(self.app.store.recent_events(max(1,min(120,int(qs.get('limit',[120])[0]))),max(0,int(qs.get('offset',[0])[0]))))
                if path=='/api/events/export':
                    rows=self.app.store.rows('SELECT * FROM events ORDER BY created_at,id')
                    for row in rows:row['payload']=json.loads(row['payload'])
                    return self.send(dumps({'format':'persona-operation-history/1','events':rows}).encode(),extra={'Content-Disposition':'attachment; filename="persona_operation_history.json"'})
                if path=='/api/media' or path.startswith('/api/media/'):
                    return self.send({'error':'内置图片素材功能已移除；旧文件保留，QQ 图片收件设置位于 QQ 设置。','code':'FEATURE_REMOVED'},410)
                if path=='/api/export/legacy-media':
                    from .media import legacy_media_archive
                    return self.send(legacy_media_archive(self.app.engine),ctype='application/zip',extra={'Content-Disposition':'attachment; filename="legacy_media_archive.zip"'})
                if path=='/api/social':return self.send(self.app.engine.social.status())
                if path=='/api/connection-presets':return self.send(self.app.presets.list())
                if path=='/api/qq/status':return self.send(self.app.bridge.status())
                if path=='/api/relations':
                    rows=self.app.store.rows('SELECT * FROM relations ORDER BY updated_at DESC')
                    for r in rows:r['data']=json.loads(r['data'])
                    return self.send(rows)
                if path=='/api/inbox':
                    rows=self.app.store.rows('SELECT id,status,result,created_at FROM inbox ORDER BY created_at DESC LIMIT 60')
                    for r in rows:r['result']=json.loads(r['result'])
                    return self.send(rows)
                if path=='/api/psychology/registry':
                    from .registry import REGISTRY,CONTRACT,FIELDS
                    return self.send({'registry':REGISTRY,'contract':CONTRACT,'fields':FIELDS})
                if path=='/api/pmm/versions':return self.send(self.app.engine.pmm_versions())
                if path=='/api/persona/revisions':return self.send(self.app.subjects.revision_files(self.app.engine).list())
                if path=='/api/pmm/core/export':return self.send(self.app.engine.export_core())
                if path=='/api/pmm/adapter/export':return self.send(self.app.engine.export_adapter())
                if path=='/api/pmm/export':return self.send(dumps(self.app.engine.export_weights()).encode(),extra={'Content-Disposition':'attachment; filename="pmm_weights.json"'})
                if path=='/api/people':return self.send(self.app.engine.people.query(qs.get('scope',[''])[0],qs.get('person',[None])[0]))
                if path=='/api/formation/interactions':return self.send(self.app.engine.formation.interactions(qs.get('scope',[''])[0],qs.get('person',[''])[0]))
                if path=='/api/evidence':return self.send(self.app.engine.evidence.trace(qs.get('scope',[None])[0],qs.get('person',[None])[0],qs.get('event_id',[None])[0],int(qs.get('offset',['0'])[0]),int(qs.get('limit',['20'])[0])))
                if path=='/api/de/turns':
                    from .joint_expression import timeline
                    return self.send(timeline(self.app.engine,int(qs.get('offset',['0'])[0]),int(qs.get('limit',['12'])[0])))
                if path=='/api/affect':
                    from .affect import label_details
                    affect=self.app.engine.affect_state()
                    return self.send({'persona_id':self.app.store.meta('identity')['id'],'affect_state':affect,'emotion_details':label_details(affect)})
                if path=='/api/persona/export':
                    if qs.get('persona_id',[self.app.subjects.catalog['active']])[0]!=self.app.subjects.catalog['active']:raise ValueError('当前角色已变化，请重新选择导出')
                    self.app.ensure_idle()
                    return self.send(dumps(self.app.subjects.export_pack(self.app.engine,qs.get('scope',['continuity'])[0])).encode(),extra={'Content-Disposition':'attachment; filename="persona_package.json"'})
                if path=='/api/export':return self.send(dumps(self.app.snapshot()).encode(),extra={'Content-Disposition':'attachment; filename="persona_snapshot.json"'})
                return self.send({'error':'接口不存在'},404)
        except Exception as ex:return self.failure(ex,400 if isinstance(ex,ValueError) else 500)
    def do_POST(self):
        self.request_id=uid()
        if not self.host_ok():return self.send({'error':'非法 Host'},403)
        u=urllib.parse.urlsplit(self.path);path=u.path;qs=urllib.parse.parse_qs(u.query)
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:return self.send({'error':'请求长度错误'},400)
        limit=25_000_000 if path in ('/api/restore','/api/persona/import','/api/persona/apply','/api/pmm/import','/api/pmm/core/import','/api/pmm/adapter/import') else 3_000_000
        if not 0<length<=limit:return self.send({'error':'请求体为空或过大'},413)
        raw=self.rfile.read(length)
        if path=='/onebot/events' or path.startswith('/onebot/events/'):
            try:
                with self.app.job_lock:return self.send(self.app.route_event(raw,self.headers,qs,path.rsplit('/',1)[-1] if path.startswith('/onebot/events/') else None))
            except PermissionError:return self.send({'error':'事件验证失败或机器人 QQ 号不匹配'},401)
            except (ValueError,TypeError,AttributeError):return self.send({'error':'事件格式或人格路由无效'},400)
        if not self.auth() or not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),self.app.token):return self.send({'error':'管理会话已过期，请重新连接后再次保存；本次未执行','code':'SESSION_EXPIRED'},403)
        if self.headers.get('X-App-Client-Version',VERSION)!=VERSION:return self.send({'error':'页面与后端版本不一致，请重新打开程序首页','code':'FRONTEND_VERSION_MISMATCH'},409)
        origin=self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{self.app.port}',f'http://localhost:{self.app.port}',f'http://terminal.local:{self.app.port}',*(['http://terminal.local:4173'] if self.app.preview else [])):
            return self.send({'error':'来源不匹配'},403)
        try:
            body=json.loads(raw)
            if not isinstance(body,dict):raise ValueError('请求格式应为对象')
            app=self.app
            with app.job_lock:
                if path=='/api/research/expressive-drive-compare':
                    from .pmm_experiments import expressive_from_turn
                    return self.send(expressive_from_turn(app.engine,body))
                if path=='/api/research/export':
                    if body.get('persona_id')!=app.store.meta('identity')['id']:raise ValueError('主体已切换，请刷新后操作')
                    from .research_export import export
                    return self.send(export(app.engine,app.root,body))
                if path in ('/api/notifications/read','/api/pmm283/motives/research','/api/affect/sampling/settings'):
                    if body.get('persona_id')!=app.store.meta('identity')['id']:raise ValueError('主体已切换，请刷新后操作')
                    if path=='/api/notifications/read':
                        from .notifications import mark_read
                        return self.send(mark_read(app.store,body.get('ids')))
                    if path=='/api/affect/sampling/settings':return self.send(app.engine.affect_sampling.configure(body))
                    from .research_operations import edit_motive
                    return self.send(edit_motive(app.engine,body))
                if path=='/api/memory-reflection/settings':
                    if body.get('persona_id')!=app.store.meta('identity')['id']:raise ValueError('主体已切换，请刷新后操作')
                    return self.send(app.engine.motive_generation.configure(body))
                if path.startswith('/api/learning/'):
                    if body.get('persona_id')!=app.store.meta('identity')['id']:raise ValueError('主体已切换，请刷新后操作')
                    learning=app.engine.learning
                    if path=='/api/learning/policy':return self.send(learning.save_policy(body))
                    if path=='/api/learning/experiences/control':return self.send(learning.experiences.control(body.get('action')))
                    if path=='/api/learning/preview':return self.send(learning.preview(body))
                    if path=='/api/learning/create':return self.send(learning.create(body))
                    if path=='/api/learning/run':return self.send(app.task('learning',lambda progress:learning.run(body.get('id'),progress)))
                    if path=='/api/learning/control':return self.send(learning.control(body.get('id'),body.get('action'),body))
                if path=='/api/social-graph/edit':
                    if body.get('persona_id')!=app.store.meta('identity')['id']:raise ValueError('主体已切换，请刷新后操作')
                    return self.send(app.engine.social_graph.edit(body))
                if path=='/api/research/decision-compare':
                    if body.get('persona_id')!=app.store.meta('identity')['id']:raise ValueError('主体已切换，请刷新')
                    from .decision_evaluation import from_turn
                    return self.send(from_turn(app.engine,body))
                if path in ('/api/people/edit','/api/relationships/revise','/api/formation/annotate','/api/formation/withdraw'):
                    if body.get('persona_id')!=app.store.meta('identity')['id']:raise ValueError('主体已切换，请刷新')
                    action={'/api/people/edit':app.engine.people.edit,'/api/relationships/revise':app.engine.people.relation_edit,'/api/formation/annotate':app.engine.formation.annotate,'/api/formation/withdraw':app.engine.formation.withdraw}[path]
                    return self.send(action(body))
                if path in ('/api/traits/disposition','/api/traits/review','/api/affect/parameters'):
                    app.ensure_idle()
                    if body.get('persona_id')!=app.store.meta('identity')['id']:raise ValueError('主体已切换，请刷新后再修改')
                    if path=='/api/traits/disposition':return self.send(app.engine.edit_disposition(body))
                    if path=='/api/traits/review':return self.send(app.engine.review_traits(body.get('apply') is True))
                    return self.send(app.engine.edit_affect_parameters(body))
                if path in ('/api/pragmatics/annotate','/api/pragmatics/target','/api/pragmatics/review'):
                    app.ensure_idle();return self.send(app.engine.language_review(path.rsplit('/',1)[1],body))
                if path=='/api/import/preview':
                    records=parse_records(body['content'],body.get('format','auto'))
                    speakers={}
                    for record in records:speakers[record['speaker']]=speakers.get(record['speaker'],0)+1
                    return self.send({'count':len(records),'speakers':speakers,'preview':records[:8]})
                if path=='/api/distill':
                    records=[r for r in parse_records(body['content'],body.get('format','auto')) if r['speaker']==body.get('speaker')]
                    if not records:raise ValueError('没有选中说话人的消息')
                    return self.send(app.task('distill',lambda progress:app.engine.import_records(records,body.get('target','self'),body.get('person','web:owner'),body.get('scope','private:web:owner'),progress)))
                if path=='/api/pmm/api/copy-general':return self.send(app.copy_general_to_pmm())
                if path=='/api/consolidation/run':return self.send(app.task('consolidation',lambda progress:app.engine.consolidation.run(retry=body.get('retry') is True,progress=progress,manual=True)))
                if path=='/api/persona/synthesize':return self.send(app.task('synthesize',app.engine.synthesize))
                if path=='/api/pmm/core/train':return self.send(app.task('core_train',lambda progress:app.engine.train_core(body.get('epochs',30),progress)))
                if path in ('/api/persona/checkpoint','/api/persona/rollback','/api/persona/apply','/api/pmm/version/save','/api/pmm/version/activate','/api/pmm/core/import','/api/pmm/core/activate','/api/pmm/adapter/import'):
                    app.ensure_idle()
                    if path=='/api/persona/checkpoint':return self.send(app.subjects.save_revision(app.engine,body.get('label','手动人格检查点')))
                    if path=='/api/persona/rollback':return self.send(app.subjects.rollback(app.engine,body['id']))
                    if path=='/api/persona/apply':return self.send(app.subjects.apply_current(app.engine,body))
                    if path=='/api/pmm/version/save':return self.send(app.engine.save_weight_version(body.get('label','手动参数检查点')))
                    if path=='/api/pmm/version/activate':return self.send(app.engine.activate_weight_version(body['id']))
                    if path=='/api/pmm/core/import':return self.send(app.engine.register_core(body))
                    if path=='/api/pmm/core/activate':return self.send(app.engine.activate_core(body['id']))
                    if path=='/api/pmm/adapter/import':return self.send(app.engine.import_adapter(body))
                if path=='/api/persona/views/delete':
                    app.ensure_idle()
                    service=app.engine.persona_views;profile=app.engine.profile()
                    if body.get('subject_id') and body['subject_id']!=profile['id']:raise ValueError('角色已切换，请刷新人设版本列表')
                    service.delete(profile,body.get('version_ids',[]));listing=service.list(profile)
                    return self.send({'current_id':listing['current_version_id'],
                        'versions':[{**v,'id':v['version_id'],'version':v['sequence']} for v in listing['items']]})
                if path=='/api/token-prices':
                    from .token_prices import TokenPrices
                    if body.get('subject_id') and body['subject_id']!=app.engine.profile()['id']:raise ValueError('角色已切换，请刷新价格配置')
                    return self.send(TokenPrices(app.store).set(body))
                if path=='/api/persona/settings':
                    app.ensure_idle();return self.send(app.subjects.edit_character(app.engine,body))
                if path=='/api/persona/new':return self.send(app.create_persona(body))
                if path=='/api/persona/clone':return self.send(app.clone_persona(body))
                if path=='/api/persona/import':return self.send(app.create_persona({'package':body}))
                if path=='/api/persona/activate':return self.send(app.switch(body['id']))
                if path=='/api/persona/delete':return self.send(app.archive_persona(body))
                if path=='/api/persona/restore':return self.send(app.archive_persona(body,restore=True))
                if path=='/api/boundaries/edit':return self.send(app.engine.boundaries.edit(body))
                if path=='/api/boundaries/calibrate':return self.send(app.engine.boundaries.calibrate(body))
                if path=='/api/boundary':return self.send(app.engine.boundary(body))
                if path=='/api/config':return self.send(app.configure(body))
                if path=='/api/pmm283/expressive-drive/advance':
                    app.ensure_idle()
                    scope=body.get('scope','private:web:owner')
                    return self.send(app.engine.advance_expressive_drive_idle(scope,body.get('person'),body.get('session_id'),body.get('at'),body.get('commit',True) is True))
                if path=='/api/social/preview':return self.send(app.task('social_preview',lambda progress:app.engine.social.evaluate(body['scope'],send=False)))
                if path=='/api/social/unblock':return self.send(app.engine.social.unblock(body['scope']))
                if path=='/api/connection-presets':return self.send(app.preset_action(body))
                if path=='/api/media' or path.startswith('/api/media/'):
                    return self.send({'error':'内置图片素材功能已移除，本次未修改任何资料。','code':'FEATURE_REMOVED'},410)
                if path=='/api/pmm/test':return self.send(app.test_connection('pmm'))
                if path=='/api/pmm/start':return self.send(app.start_pmm())
                if path=='/api/pmm/models':
                    c=app.config.get()['pmm']
                    if c['mode']=='api':return self.send({'models':Provider(c['api']).models()})
                    if c['backend']=='local':return self.send({'models':[LEARNED_ID if c['mode']=='learned' else MODEL_ID]})
                    from .provider import request_json
                    base=c['base_url'].removesuffix('/v1/pmm/execute')
                    r=request_json(base+'/v1/models',token=c['api_key'],timeout=20)
                    return self.send({'models':[v['id'] for v in r.get('data',[])]})
                if path=='/api/pmm/import':
                    app.ensure_idle();return self.send(app.engine.import_weights(body))
                if path=='/api/pmm28/ablation':
                    from .pmm_experiments import from_turn
                    return self.send(from_turn(app.engine,body))
                if path=='/api/pmm281/connection':
                    from .pmm_connections import probe
                    app.ensure_idle();return self.send(probe(app.engine,body.get('role'),body.get('operation','invoke')))
                if path=='/api/pmm281/preview':
                    from .pmm_workspace import preview
                    return self.send(app.task('pmm281_preview',lambda progress:preview(app.engine,body)))
                if path=='/api/pmm281/emotion/models':
                    from .affect_learning import AffectLearning
                    service=AffectLearning(app.engine)
                    if body.get('op') in ('train','calibrate'):return self.send(app.task('affect_train',lambda progress:service.action(body)))
                    app.ensure_idle();return self.send(service.action(body))
                if path=='/api/pmm28/longitudinal':
                    from .pmm_coordinator import PMMCoordinator
                    app.ensure_idle();return self.send(PMMCoordinator(app.engine).longitudinal_action(body))
                if path in ('/api/pmm28/samples','/api/pmm28/models'):
                    from .pmm_coordinator import PMMCoordinator
                    co=PMMCoordinator(app.engine)
                    if path.endswith('/samples'):
                        app.ensure_idle();return self.send(co.review_samples(body))
                    if body.get('op')=='train':return self.send(app.task('pmm28_train',lambda progress:co.model_action(body)))
                    app.ensure_idle();return self.send(co.model_action(body))
                if path=='/api/pmm/train':return self.send(app.task('pmm_train',lambda progress:app.engine.train_pmm(body.get('epochs',30),progress)))
                if path=='/api/session':return self.send({'id':app.store.session()})
                if path=='/api/chat':
                    if app.store.get_session(body['session_id'])['scope']!='private:web:owner':raise ValueError('QQ 记录仅供查看，请在 QQ 中继续对话或新建本机对话')
                    return self.send(app.submit(body['session_id'],body['text'],body.get('client_event_id')))
                if path=='/api/test-model':return self.send(app.test_connection('general'))
                if path=='/api/models':return self.send({'models':Provider(app.config.get()).models()})
                if path=='/api/qq/test':return self.send(app.bridge.test())
                if path=='/api/qq/setup':
                    q=app.config.get()['qq']
                    return self.send({'event_url':f"http://127.0.0.1:{app.port}/onebot/events/{app.store.meta('identity')['id']}?token="+urllib.parse.quote(q['inbound_token']),
                                      'hint':'若配置 HMAC Secret，则以 X-Signature 验证为准。'})
                if path=='/api/qq/retry-failed':return self.send(app.bridge.retry_failed(body.get('id')))
                if path=='/api/execution/recover':
                    app.ensure_idle();return self.send({'recovered':app.engine.recover_delivered()})
                if path=='/api/execution/reconcile':
                    app.ensure_idle();q=app.config.get()['qq']
                    from .provider import request_json
                    receipt=app.engine.journal.acknowledge(body.get('outbox_id',body.get('id')),lambda:request_json(q['api_url'].rstrip('/')+'/get_msg',{'message_id':body.get('message_id')},q['api_token'],timeout=20))
                    return self.send({'receipt':receipt,'recovered':app.engine.recover_delivered()})
                if path=='/api/cognition/feedback':return self.send(app.engine.cognition.feedback(body.get('id'),body.get('targets')))
                if path=='/api/qq/retry-appraisal':return self.send(app.bridge.turn_taking.retry(body.get('id')))
                if path=='/api/memory/consolidate':return self.send(app.task('memory_gist',lambda progress:app.engine.memory_lifecycle.run(retry=body.get('retry') is True,progress=progress,manual=True)))
                if path=='/api/memory/erase':
                    from .erasure import erase_scope
                    with app.job_lock:
                        app.ensure_idle()
                        with app.bridge.lifecycle:return self.send(erase_scope(app.engine,body.get('scope'),body.get('confirmation')))
                if path=='/api/memory':
                    with app.engine.lock:app.store.edit_memory(body['id'],body['op'],body.get('content',''))
                    return self.send({'ok':True})
                if path=='/api/feedback':return self.send(app.engine.feedback(body['turn_id'],body['rating'],body.get('note',''),body.get('state_target'),body.get('memory_feedback'),body.get('action_target'),body.get('corrected_reply'),body.get('perspective_target')))
                if path=='/api/restore':return self.send(app.restore(body))
                if path=='/api/reload':
                    self.send({'ok':True})
                    app.reload()
                    return
                return self.send({'error':'接口不存在'},404)
        except (ValueError,KeyError,TypeError,ProviderError) as ex:
            return self.send({'error':str(ex) if not isinstance(ex,KeyError) else '请求缺少字段','diagnostics':getattr(ex,'details',{}),'failed_fields':getattr(ex,'failed_fields',[])},400)
        except Exception as ex:
            return self.failure(ex)

def serve(directory,root,port=8765,preview=False,open_browser=False,remember_directory=False):
    host='0.0.0.0' if preview else '127.0.0.1'
    runtime=Runtime(directory,root,host,port,preview)
    server=None
    try:
        server=ThreadingHTTPServer((host,port),Handler);server.app=runtime;runtime.http=server;runtime.port=server.server_port
        if remember_directory:
            from .data_guard import remember_data_directory
            remember_data_directory(directory)
        runtime.start_bridges()
        print(f'Persona Dialogue {VERSION} | http://127.0.0.1:{runtime.port}',flush=True)
        print('Data directory:',directory,flush=True)
        if open_browser:
            import webbrowser
            webbrowser.open(f'http://127.0.0.1:{runtime.port}')
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:
        if server is not None:server.server_close()
        runtime.close()
    return 75 if runtime.reloading else 0
