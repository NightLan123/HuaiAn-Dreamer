"""Durable, scoped background consolidation. Network calls never hold the turn lock."""
from __future__ import annotations
import copy, threading, time
from .common import now, dumps, uid
from .provider import ProviderError
from .psychology import apply_distillation, style_vector, STATE_KEYS, TRAITS, VALUES
from .registry import FIELDS, CONTRACT, pack_features
from . import relationships as dy
from .api_pmm import APIPMM
from . import learning as learn, traits

BATCH='''[CONSOLIDATE_V212]
分批整理已经真实发生的对话，不生成或发送新消息。输出JSON {"items":[{"turn_id":"给定ID","feedback":{...}}]}。
items必须恰好覆盖输入的全部turn_id；每条反馈遵循后附FEEDBACK合约，每条证据仅来自该轮对应user_record/self_record。
整理长期记忆、对方偏好、关系和语言观察；不能把用户人格写进AI自身，不能把AI生成回复变成长期人格真值。
不能把后台计算时间当原事件时间；不重写当前情绪，不虚构用户反馈。语言蒸馏只接受导入或人工校正的目标语言示范，AI自己的回复只作观测。
'''

def validate_queue(rows):
    if not isinstance(rows,list) or len(rows)>2000:raise ValueError('后台队列无效或超过 2000 项')
    ids=set()
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get('id'),str) or row['id'] in ids:raise ValueError('后台任务标识无效')
        ids.add(row['id'])
        if row.get('status') not in ('pending','processing','failed'):raise ValueError('后台任务状态无效')
        for field in ('user_record','self_record'):
            r=row.get(field)
            if not isinstance(r,dict) or not isinstance(r.get('text'),str) or len(r['text'])>20000 or r.get('id')!=row['id']+(':u' if field=='user_record' else ':a'):raise ValueError('后台任务原文无效')
        if not isinstance(row.get('session'),dict) or not all(isinstance(row['session'].get(k),str) for k in ('scope','person')):raise ValueError('后台任务作用域无效')
        if not isinstance(row.get('memories'),list) or not isinstance(row.get('decision'),dict) or row['decision'].get('action') not in ('reply','unknown','clarify','disagree','decline','silence'):raise ValueError('后台任务上下文无效')
        if not isinstance(row.get('created_at'),(int,float)):raise ValueError('后台任务时间无效')
        import math
        x=row.get('training_x')
        if not isinstance(x,list) or len(x) not in (184,370) or not all(type(v) in (int,float) and math.isfinite(v) for v in x):raise ValueError('后台任务编码向量无效')
        if not math.isfinite(row['created_at']) or not isinstance(row.get('understanding',{}).get('semantic'),dict):raise ValueError('后台任务语义或时间无效')
    return rows

class Consolidation:
    def __init__(self,engine):
        self.engine=engine;self.lock=threading.Lock();self.thread=None
        with engine.store.lock,engine.store.db:
            rows=engine.store.meta('consolidation_queue') or []
            for row in rows:
                if row['status']=='processing':row.update(status='pending',error='上次整理中断，等待重新计算；尚未提交')
            engine.store.setmeta('consolidation_queue',rows)
            if not engine.store.meta('consolidation_generation'):engine.store.setmeta('consolidation_generation',uid())
    def status(self):
        rows=self.engine.store.meta('consolidation_queue') or []
        return {'running':bool(self.thread and self.thread.is_alive()),'pending':sum(r['status']=='pending' for r in rows),'failed':sum(r['status']=='failed' for r in rows),
                'working_chars':sum(len(r['user_record']['text'])+len(r['self_record']['text']) for r in rows),'last':self.engine.store.meta('consolidation_last')}
    def due(self):
        rows=[r for r in self.engine.store.meta('consolidation_queue') or [] if r['status']=='pending'];c=self.engine.config.get()['performance']
        rows=[r for r in rows if self.eligible(r)]
        if not rows:return False
        if self.engine.store.meta('consolidation_urgent'):return True
        # Idle is measured from the latest foreground activity, including synchronous turns.
        last=max([self.engine.store.meta('state')['updated_at']]+[r['created_at'] for r in rows])
        return len(rows)>=c['batch_turns'] or now()-last>=c['idle_seconds'] or sum(len(r['user_record']['text'])+len(r['self_record']['text']) for r in rows)>=c['work_chars']
    def poll(self):
        if self.due() and not (self.thread and self.thread.is_alive()):
            self.thread=threading.Thread(target=self._auto,daemon=True,name='persona-consolidation');self.thread.start()
    def _auto(self):
        try:self.run()
        except Exception:pass # Failure is durably recorded by run, not silently discarded.
    def eligible(self,row,manual=False):
        s=row['session']
        return any(learn.permission(self.engine,d,s['scope'],s['person'],manual=manual,observed_only=not s.get('direct_interaction',True))['allowed'] for d in ('self','other','relationship','memory'))
    def run(self,retry=False,progress=lambda _:None,manual=False):
        if not self.lock.acquire(blocking=False):raise ValueError('后台整理已在运行')
        ids=set();started=time.monotonic()
        try:
            e=self.engine;st=e.store
            with e.lock:
                queue=st.meta('consolidation_queue') or []
                if retry:
                    for r in queue:
                        if r['status']=='failed':r.update(status='pending',error='')
                pending=[r for r in queue if r['status']=='pending' and self.eligible(r,manual)]
                if not pending:return {'ok':True,'processed':0,'message':'无符合当前学习策略的待处理任务；没有更新人格或权重','policy_blocked':sum(r['status']=='pending' for r in queue)}
                first=pending[0]['session'];batch=copy.deepcopy([r for r in pending if r['session']['scope']==first['scope'] and r['session']['person']==first['person']][:e.config.get()['performance']['batch_turns']])
                ids={r['id'] for r in batch};captured=e.config.get();generation=st.meta('consolidation_generation')
                for row in queue:
                    if row['id'] in ids:row.update(status='processing',error='')
                with st.lock,st.db:st.setmeta('consolidation_queue',queue)
            progress('后台整理原文证据；当前对话可继续')
            from .engine import FEEDBACK,validate_feedback,memory_context
            client=APIPMM(captured,e.pmm_provider_factory).provider if captured['pmm']['mode']=='api' else e.provider_factory(captured)
            client.trace_context={'turn_ids':sorted(ids),'trace_ids':[(e.journal.get(v) or {}).get('trace_id') for v in sorted(ids)]};client.stage='后台长期学习'
            payload=[{'turn_id':r['id'],'user_record':r['user_record'],'self_record':r['self_record'],'prior_interactions':e.formation.interactions(r['session']['scope'],r['session']['person'],before=r['created_at']),'decision':r['decision'],'memories':memory_context(r['memories']),'boundary_feedback':r['understanding'].get('boundary_feedback',{}),'boundary_states':r.get('boundary_states',[]),'claim_memory':e.claims.recent(r['session']['scope'])} for r in batch]
            request={'turns':payload,'traits':TRAITS,'values':VALUES,'construct_registry':FIELDS,'disposition_registry':traits.DISPOSITION_REGISTRY}
            if captured['pmm281']['mode']=='full':
                from .prompt_compiler import feedback as compile_feedback
                request=compile_feedback(request)
            response=client.complete([{'role':'system','content':BATCH+'\n'+FEEDBACK},{'role':'user','content':dumps(request)}],structured=True)
            items=response.get('items') if isinstance(response,dict) else None
            if not isinstance(items,list) or len(items)!=len(ids) or any(not isinstance(i,dict) for i in items) or {i.get('turn_id') for i in items}!=ids:raise ProviderError('批量整理没有完整对应原始轮次，未提交任何更新')
            reports={i['turn_id']:validate_feedback(i.get('feedback')) for i in items}
            with e.lock:
                queue=st.meta('consolidation_queue') or []
                if st.meta('consolidation_generation')!=generation:raise ValueError('人格状态已恢复，本次旧后台结果未应用')
                if {r['id'] for r in queue if r['status']=='processing'} & ids != ids:raise ValueError('队列已恢复或替换，本次后台结果未应用')
                if captured['pmm']!=e.config.get()['pmm']:raise ValueError('PMM 连接已改变，请手动重试后台整理')
                p=e.profile();others=st.meta('pmm_interlocutors') or {};dyads=st.meta('pmm_dyads') or {};codes=st.meta('pmm_memory_codes') or {};pending_samples=st.meta('pmm_training_records') or [];candidate=e.model.fork()
                logs=[];audits=[];weights_before=__import__('persona.registry',fromlist=['digest']).digest(e.model.export())
                with st.lock,st.db:
                    for row in batch:
                        f=reports[row['id']]
                        if not row['session'].get('direct_interaction',True):f={k:v for k,v in f.items() if k not in ('relationship_updates','relation_delta')}
                        ur=row['user_record'];sr=row['self_record'];session=row['session'];person=session['person'];scope=session['scope'];key=e.other_key(scope,person)
                        from .psychology import empty_profile
                        from .registry import ensure_profile
                        other=ensure_profile(others.get(key,empty_profile(key,person)),'model_of_other')
                        # Generated self language remains observation, not a style target or stable truth.
                        ur=e.evidence.normalize(ur,scope,person);sr=e.evidence.normalize(sr,scope,sr['speaker'])
                        e.evidence.register([ur,sr],'consolidation')
                        self_before=copy.deepcopy(p);other_before=copy.deepcopy(other)
                        self_report,self_gate=learn.live_report(e,'self',f.get('self_observations',{}),session,manual=manual)
                        other_report,other_gate=learn.live_report(e,'other',f.get('interlocutor',{}),session,manual=manual)
                        other_duplicate=e.evidence.processed('other',ur)
                        if other_duplicate:other_report={}
                        p,_=apply_distillation(p,self_report,[sr] if sr['text'] and self_gate['allowed'] else [],source='generated')
                        other,_=apply_distillation(other,other_report,[ur] if other_gate['allowed'] and not other_duplicate else [],source='observed')
                        if e.config.get()['pmm28']['mode']!='active' and other_gate['allowed'] and not other_duplicate and (manual or other_gate['mode']=='automatic'):other,_=traits.review(other,True,strength=other_gate['strength'])
                        if other_gate['allowed'] and not other_duplicate:e.evidence.complete('other',[ur],row['id'],{'revision':other_before['revision'],'traits':other_before['trait_profile']['version']},{'revision':other['revision'],'traits':other['trait_profile']['version']},'consolidation')
                        if f.get('self_experience_updates'):
                            formation_before=copy.deepcopy(p)
                            p,formation_report=e.formation.collect(p,f['self_experience_updates'],[ur],session,manual=manual)
                            pending_samples=e.formation.queue_promotions(formation_before,p,formation_report,pending_samples)
                            logs.append({'turn_id':row['id'],'self_formation':formation_report})
                        others[key]=other
                        relation_gate=learn.permission(e,'relationship',scope,person,manual=manual,observed_only=not session.get('direct_interaction',True))
                        if not relation_gate['allowed'] or (not manual and relation_gate['mode']!='automatic'):f={**f,'relationship_updates':[]}
                        memory_gate=learn.permission(e,'memory',scope,person,manual=manual,observed_only=not session.get('direct_interaction',True))
                        if not memory_gate['allowed'] or (not manual and memory_gate['mode']!='automatic'):f={**f,'memory_ops':[]}
                        if e.evidence.processed('relationship',ur):f={**f,'relationship_updates':[]}
                        if e.evidence.processed('memory',ur):f={**f,'memory_ops':[]}
                        d=dyads.get(key,dy.empty(person,scope));relation_before=copy.deepcopy(d);d,report=dy.update(d,f,ur['text'],row['id'],row['decision']['action'],style_vector(sr['text']),count_interaction=False,strength=relation_gate['strength'] if relation_gate['allowed'] else 0.);dyads[key]=d
                        changes=[]
                        for op in f.get('memory_ops',[])[:10]:
                            log=e.apply_memory(op,ur['text'],session,row['id'],visible_ids={m['id'] for m in row['memories']});changes.append(log)
                            if log['status']=='applied':codes[log['id']]=row['understanding']['semantic']
                        if f.get('relationship_updates'):e.evidence.complete('relationship',[ur],row['id'],{'digest':__import__('persona.registry',fromlist=['digest']).digest(relation_before)},{'digest':__import__('persona.registry',fromlist=['digest']).digest(d),'accepted':report},'consolidation')
                        if f.get('memory_ops'):e.evidence.complete('memory',[ur],row['id'],{}, {'changes':changes},'consolidation',{'memory_ids':[r['id'] for r in changes if r.get('status')=='applied']})
                        # Actual language, appraisal and evidenced hypotheses stay available for later training.
                        if captured['pmm']['mode']!='legacy' and learn.train_allowed(e,session,manual=manual):
                            target={k:f['self_appraisal'][k] for k in STATE_KEYS};vv,mm=pack_features(p['psychology'])
                            targets=[v if known and {ur['id'],sr['id']}.intersection(p['psychology']['features'][k]['evidence_ids']) else None for k,v,known in zip(CONTRACT['feature_order'],vv,mm)]
                            pending_samples=e.queue_sample(pending_samples,row['id'],row['training_x'],state=target,psychology_target=targets,source='weak_background_feedback',group_id=row['id'],training_context={'schema':'typed-supervision/1','target_entity':'event_state','event_id':row['id'],'scope':scope,'at':row['created_at']})
                        boundary_report=e.boundaries.absorb(f.get('boundary_evidence',[]) if self_gate['allowed'] and (manual or self_gate['mode']=='automatic') else [],ur,session,row['id'],row['created_at'],row['understanding'].get('boundary_feedback'))
                        e.claims.observe(f.get('claims',[]),sr,scope,row['id'])
                        logs.append({'boundary_update':boundary_report,'turn_id':row['id'],'memory_changes':changes,'relationship_update':report})
                        audits.append((row['id'],session,self_before,copy.deepcopy(p),other_before,copy.deepcopy(other),{'self':self_gate,'other':other_gate,'relationship':relation_gate,'memory':memory_gate}))
                    if captured['pmm']['mode']=='learned' and captured['online_learning'] and any(learn.train_allowed(e,r['session'],manual=manual) for r in batch):
                        e.ingest_samples(candidate,pending_samples);candidate.fit(epochs=8);pending_samples=[]
                    for args in audits:e.learning.audit_live(*args,weights_before,__import__('persona.registry',fromlist=['digest']).digest(candidate.export()),source='consolidation')
                    for k,v in [('pmm_profile',p),('pmm_interlocutors',others),('pmm_dyads',dyads),('pmm_memory_codes',codes),('pmm_training_records',pending_samples),('pmm_checkpoint',candidate.export()),('consolidation_queue',[r for r in queue if r['id'] not in ids])]:st.setmeta(k,v)
                    if not any(r['status']=='pending' for r in queue if r['id'] not in ids):st.setmeta('consolidation_urgent',False)
                    result={'ok':True,'processed':len(batch),'turn_ids':sorted(ids),'scope':first['scope'],'duration_ms':round((time.monotonic()-started)*1000),'at':now(),'updates':logs,'calls':getattr(client,'calls',[])}
                    st.setmeta('consolidation_last',result);st.event('consolidation',result)
                e.model=candidate
                for identifier in ids:
                    run=e.journal.get(identifier)
                    if run:run.update(learning_status='COMPLETED',calls=run.get('calls',[])+getattr(client,'calls',[]));e.journal.save(run)
                return result
        except Exception as ex:
            if ids:
                with self.engine.lock,self.engine.store.lock,self.engine.store.db:
                    st=self.engine.store;queue=st.meta('consolidation_queue') or []
                    for row in queue:
                        if row['id'] in ids and st.meta('consolidation_generation')==generation:row.update(status='failed',error=str(ex) if isinstance(ex,(ValueError,ProviderError)) else '后台整理失败，原始记录保留')
                    result={'ok':False,'at':now(),'turn_ids':sorted(ids),'error':str(ex) if isinstance(ex,(ValueError,ProviderError)) else '后台整理失败','duration_ms':round((time.monotonic()-started)*1000)}
                    st.setmeta('consolidation_queue',queue);st.setmeta('consolidation_last',result);st.event('consolidation',result)
                    for identifier in ids:
                        run=self.engine.journal.get(identifier)
                        if run:run.update(learning_status='FAILED',background_error=type(ex).__name__,calls=run.get('calls',[])+getattr(locals().get('client'),'calls',[]));self.engine.journal.save(run)
            raise
        finally:self.lock.release()
