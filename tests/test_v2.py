"""V2 integration and numerical invariants. Fixtures are never production responses."""
import copy,json,tempfile,threading,unittest,uuid,urllib.request,time
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import numpy as np
from persona.common import Config,PROVIDER_FIELDS
from persona.server import Runtime,Handler
from persona.engine import Engine
from persona.storage import Store
from persona.api_pmm import APIPMM
from persona.provider import ProviderError
from persona.psychology import parse_records,STATE_KEYS,VALUES
from persona.pmm import vector
from persona.learned_pmm import LearnedPMM,linguistic_vector,MODEL_ID
from persona.pmm_interface import LocalPMM,RemotePMM,digest,execute_request
from persona.pmm_service import make_server
from persona.packages import validate_pack
from fixtures import response,TEXT
from test_providers_v04 import NativeFixture

ROOT=Path(__file__).resolve().parents[1]
CHAT='\n'.join(f'甲：开场{i}\n乙：请说，我可能有自己的想法{i}' for i in range(16))

class GeneralFixture:
    calls=[]
    def __init__(self,c):self.config=c
    def complete(self,messages,structured=False):
        type(self).calls.append({'model':self.config['model'],'stage':messages[0]['content'].split(']')[0]+']'})
        return response(messages,structured)
class PsychologicalFixture(GeneralFixture):calls=[]

class RuntimeCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.r=Runtime(self.tmp.name,ROOT)
        self.r.configure({'model':'general-fixture','api_key':'GENERAL_SECRET','pmm':{'api':{'model':'psych-fixture','api_key':'PSYCH_SECRET','extra_headers':{'X-Private':'HEADER_SECRET'}}}})
        self.fixtures();self.sid=self.r.store.session()
    def fixtures(self):
        self.r.engine.provider_factory=GeneralFixture;self.r.engine.pmm_provider_factory=PsychologicalFixture
        GeneralFixture.calls=[];PsychologicalFixture.calls=[]
    def tearDown(self):
        self.r.bridge.stop.set()
        if self.r.bridge.thread.is_alive():self.r.bridge.thread.join(3)
        self.r.close_pmm();self.r.store.close();self.tmp.cleanup()
    def distill(self):return self.r.engine.import_records([r for r in parse_records(CHAT) if r['speaker']=='乙'])
    def turn(self,text=TEXT):return self.r.engine.turn(self.sid,text)

class APIModeTests(RuntimeCase):
    def test_separate_loop_without_numeric_inference_or_training(self):
        before=digest(self.r.engine.model.export())
        with patch.object(LocalPMM,'encode',side_effect=AssertionError('numeric encoder')),patch.object(LocalPMM,'decode',side_effect=AssertionError('numeric decoder')),patch.object(LocalPMM,'fit',side_effect=AssertionError('gradient training')):
            result=self.turn()
        self.assertEqual(result['reply'],'说。');self.assertEqual(result['trace']['pmm_mode'],'api')
        self.assertEqual([c['stage'] for c in GeneralFixture.calls],['[UNDERSTAND_V3]','[REALIZE_V3]','[ACTION_CHECK_V221]'])
        self.assertEqual([c['stage'] for c in PsychologicalFixture.calls],['[API_PMM_PREPARE_V2]','[DECIDE_V21]','[FEEDBACK_V3]'])
        self.assertTrue(all(c['model']=='psych-fixture' for c in PsychologicalFixture.calls));self.assertEqual(before,digest(self.r.engine.model.export()))
        self.assertEqual(self.r.store.meta('state')['turn_count'],1);self.assertGreater(len(self.r.store.memories()),0)
        self.assertEqual(self.r.store.relation('web:owner')['interactions'],1);self.assertEqual(self.r.engine.model_info()['pending_samples'],2)
        self.assertEqual(self.r.store.meta('pmm_expression')['count'],1)
        own=self.r.engine.profile();other=next(iter(self.r.store.meta('pmm_interlocutors').values()))
        self.assertTrue(all(r['text']=='说。' for r in own['source_records']));self.assertTrue(any(r['text']==TEXT for r in other['source_records']))
    def test_distill_and_corrections_accumulate_then_migrate_to_real_learning(self):
        report=self.distill();self.assertEqual(report['report']['added'],16);self.assertEqual(len(GeneralFixture.calls),0)
        self.assertTrue(all(c['stage']=='[DISTILL_V3]' for c in PsychologicalFixture.calls));self.assertEqual(self.r.engine.model.steps,0)
        result=self.turn();self.r.engine.feedback(result['turn_id'],'unhelpful',corrected_reply='请说',action_target='reply',perspective_target='v0')
        self.assertEqual(self.r.engine.model.steps,0);pending=self.r.store.meta('pmm_training_records');self.assertGreater(len(pending),16)
        identity=self.r.store.meta('identity');profile=self.r.engine.profile();history=self.r.store.history(self.sid);memories=self.r.store.memories()
        with self.assertRaises(ValueError):self.r.engine.train_pmm(2)
        self.r.configure({'pmm':{'mode':'learned'}});core=self.r.engine.model.core_hash();self.r.engine.train_pmm(5)
        self.assertEqual(core,self.r.engine.model.core_hash());self.assertGreater(self.r.engine.model.adapter_steps,0);self.assertEqual(self.r.store.meta('pmm_training_records'),[])
        self.assertTrue(any(s.get('psychology_target') is not None for s in self.r.engine.model.samples));self.assertTrue(any(s.get('linguistic') is not None for s in self.r.engine.model.samples))
        checkpoint=self.r.engine.model.export();self.r.configure({'pmm':{'mode':'api'}});self.assertEqual(checkpoint,self.r.engine.model.export())
        self.r.configure({'pmm':{'mode':'learned'}});self.assertEqual(checkpoint,self.r.engine.model.export())
        self.assertEqual(identity,self.r.store.meta('identity'));self.assertEqual(profile,self.r.engine.profile());self.assertEqual(history,self.r.store.history(self.sid));self.assertEqual(memories,self.r.store.memories())
        self.assertEqual(Engine(self.r.store,self.r.config).model.export(),checkpoint)
    def test_invalid_appraisal_evidence_aborts_without_partial_turn(self):
        before=self.r.snapshot()
        class Bad(PsychologicalFixture):
            def complete(self,messages,structured=False):
                r=response(messages,structured)
                if '[API_PMM_PREPARE_V2]' in messages[0]['content']:r['evidence_quote']='不存在的引文'
                return r
        self.r.engine.pmm_provider_factory=Bad
        with self.assertRaises(ProviderError):self.turn()
        self.assertEqual({k:v for k,v in self.r.store.snapshot()['tables'].items() if k!='events'},{k:v for k,v in before['tables'].items() if k!='events'});self.assertEqual(self.r.engine.model.export(),before['model'])
    def test_memory_focus_cannot_reference_other_scope(self):
        self.turn();scope='private:other';other_sid=self.r.store.session('other',scope)
        self.r.engine.turn(other_sid,'私密的另一段经历');foreign={m['id'] for m in self.r.store.memories(scope)}
        class Bad(PsychologicalFixture):
            def complete(self,messages,structured=False):
                r=response(messages,structured)
                if '[API_PMM_PREPARE_V2]' in messages[0]['content']:r['memory_focus']=[{'id':next(iter(foreign)),'quote':'私密的另一段经历','weight':1}]
                return r
        self.r.engine.pmm_provider_factory=Bad;result=self.turn()
        self.assertEqual(result['trace']['decoded']['memory_focus'],{});self.assertEqual(result['trace']['decoded']['rejected_memory_claims'],1)
    def test_human_invalid_labels_fail_before_queue_or_profile_changes(self):
        result=self.turn();before=self.r.store.snapshot()['tables']
        with self.assertRaises(ValueError):self.r.engine.feedback(result['turn_id'],'unhelpful',state_target={'stress':float('nan')},corrected_reply='新示范')
        self.assertEqual(before,self.r.store.snapshot()['tables'])
    def test_synthesis_keeps_source_quotes_and_rejects_invented_evidence(self):
        self.distill();before=self.r.engine.profile();result=self.r.engine.synthesize()
        self.assertEqual(len(result['statements']),1);self.assertEqual(before,self.r.engine.profile())
        class Bad(PsychologicalFixture):
            def complete(self,messages,structured=False):
                r=response(messages,structured);r['statements'][0]['evidence'][0]['quote']='编造引文';return r
        self.r.engine.pmm_provider_factory=Bad;out=self.r.engine.synthesize();self.assertEqual(out['statements'],[]);self.assertEqual(out['rejected'],1)
    def test_connection_secret_redaction_and_independent_host_change(self):
        text=json.dumps(self.r.state())+json.dumps(self.r.snapshot())+json.dumps(self.r.subjects.export_pack(self.r.engine))
        for secret in ('GENERAL_SECRET','PSYCH_SECRET','HEADER_SECRET'):self.assertNotIn(secret,text)
        self.r.configure({'pmm':{'api':{'base_url':'https://api.example.com/v1','api_key':None,'extra_headers':None}}})
        c=self.r.config.get();self.assertEqual(c['api_key'],'GENERAL_SECRET');self.assertEqual(c['pmm']['api']['api_key'],'');self.assertEqual(c['pmm']['api']['extra_headers'],{})
        self.r.copy_general_to_pmm();c=self.r.config.get();self.assertEqual(c['pmm']['api'],{k:c[k] for k in PROVIDER_FIELDS})
    def test_failed_mode_switch_keeps_configuration_and_parameters(self):
        self.r.configure({'pmm':{'mode':'learned'}});before=self.r.config.get();checkpoint=self.r.engine.model.export()
        with self.assertRaises(ValueError):self.r.configure({'pmm':{'mode':'legacy'}})
        self.assertEqual(before,self.r.config.get());self.assertEqual(checkpoint,self.r.engine.model.export())

class PackageTests(RuntimeCase):
    def test_continuity_roundtrip_includes_state_relations_evidence_pending_and_no_keys(self):
        self.distill();self.turn();self.r.engine.synthesize();pack=self.r.subjects.export_pack(self.r.engine)
        meta,memories,relations=validate_pack(pack);self.assertTrue(memories);self.assertTrue(relations);self.assertTrue(meta['pmm_training_records'])
        with tempfile.TemporaryDirectory() as directory:
            other=Runtime(directory,ROOT)
            try:
                other.create_persona({'package':pack});actual=other.subjects.export_pack(other.engine)
                for field in ('identity','profile','state','activity','expression','synthesis','memories','relationships','interlocutors','memory_codes','learning'):self.assertEqual(actual[field],pack[field])
                self.assertEqual(other.store.sessions(),[]);self.assertEqual(other.config.get()['api_key'],'')
                other.configure({'pmm':{'mode':'learned'}});other.engine.train_pmm(3);self.assertGreater(other.engine.model.adapter_steps,0)
            finally:
                other.bridge.stop.set()
                if other.bridge.thread.is_alive():other.bridge.thread.join(3)
                other.store.close()
    def test_template_is_separate_from_full_continuity(self):
        self.turn('private-live-message');template=self.r.subjects.export_pack(self.r.engine,scope='template')
        self.assertNotIn('private-live-message',json.dumps(template));self.assertNotIn('interlocutors',template)
        self.assertIn('private-live-message',json.dumps(self.r.subjects.export_pack(self.r.engine)))
    def test_persona_rollback_restores_state_while_preserving_chat_history(self):
        self.turn();entry=self.r.subjects.save_revision(self.r.engine,'one');one=self.r.subjects.export_pack(self.r.engine)
        self.turn('第二次互动');history=self.r.store.history(self.sid);two=self.r.subjects.export_pack(self.r.engine)
        self.r.subjects.rollback(self.r.engine,entry['id']);self.assertEqual(self.r.store.meta('state'),one['state']);self.assertEqual(self.r.store.history(self.sid),history)
        auto=self.r.subjects.revision_files(self.r.engine).list()[0];self.r.subjects.rollback(self.r.engine,auto['id']);self.assertEqual(self.r.store.meta('state'),two['state'])
    def test_invalid_package_is_atomic_and_foreign_identity_cannot_apply(self):
        self.turn();pack=self.r.subjects.export_pack(self.r.engine);before=self.r.store.snapshot()['tables']
        for field in ('identity','pending','memory'):
            bad=copy.deepcopy(pack)
            if field=='identity':bad['identity']['id']=uuid.uuid4().hex
            elif field=='pending':bad['learning']['pending'][0]['x']=[0]
            else:bad['memories'][0]['confidence']=2
            with self.subTest(field=field),self.assertRaises(ValueError):self.r.subjects.apply_current(self.r.engine,bad)
            self.assertEqual(before,self.r.store.snapshot()['tables'])
    def test_learned_package_adapter_identity_is_checked(self):
        self.r.configure({'pmm':{'mode':'learned'}});pack=self.r.subjects.export_pack(self.r.engine);pack['learning']['checkpoint']['adapter']['identity_id']=uuid.uuid4().hex
        with self.assertRaises(ValueError):validate_pack(pack)
    def test_full_snapshot_restores_learned_weights_and_pending_metadata(self):
        self.distill();self.r.configure({'pmm':{'mode':'learned'}});self.r.engine.train_pmm(3);self.turn();snap=self.r.snapshot()
        expected=self.r.engine.model.export();self.r.restore(snap);self.assertEqual(self.r.engine.model.export(),expected);self.assertEqual(len(self.r.store.history(self.sid)),2)

class ParameterTests(RuntimeCase):
    def test_shared_core_train_publish_switch_and_adapter_pair_rollback(self):
        self.distill();self.r.configure({'pmm':{'mode':'learned'}});self.r.engine.train_pmm(8)
        before=self.r.engine.model.export();identity=self.r.store.meta('identity');profile=self.r.engine.profile();self.turn();before=self.r.engine.model.export()
        old=self.r.engine.register_core(self.r.engine.export_core(),'原核心',self.r.engine.model.core_steps)
        result=self.r.engine.train_core(5);self.assertFalse(result['activated']);self.assertEqual(before,self.r.engine.model.export())
        self.r.engine.activate_core(result['version']['id']);self.assertNotEqual(self.r.engine.model.core_hash(),before['core_sha256']);self.assertEqual(self.r.engine.model.adapter_steps,0)
        self.r.engine.activate_core(old['id']);self.assertEqual(self.r.engine.model.export_adapter(),before['adapter'])
        self.assertEqual(identity,self.r.store.meta('identity'));self.assertEqual(len(self.r.store.history(self.sid)),2)
    def test_adapter_export_import_and_parameter_revert_keep_psychological_state(self):
        self.distill();self.r.configure({'pmm':{'mode':'learned'}});self.r.engine.train_pmm(5)
        before=self.r.engine.model.export();version=self.r.engine.save_weight_version();state=self.r.store.meta('state');adapter=self.r.engine.export_adapter()
        self.r.engine.train_pmm(5);self.assertNotEqual(before,self.r.engine.model.export());self.r.engine.import_adapter(adapter)
        self.assertEqual(self.r.engine.export_adapter(),adapter);self.r.engine.activate_weight_version(version['id']);self.assertEqual(before,self.r.engine.model.export());self.assertEqual(state,self.r.store.meta('state'))
        bad=copy.deepcopy(adapter);bad['identity_id']=uuid.uuid4().hex
        with self.assertRaises(ValueError):self.r.engine.import_adapter(bad)
    def test_core_directory_is_shared_but_adapters_are_per_person(self):
        self.r.configure({'pmm':{'mode':'learned'}});entry=self.r.engine.register_core(self.r.engine.export_core(),'共享');original=self.r.engine.model.adapter_id
        self.r.create_persona({'name':'另一个人'});self.assertIn(entry['id'],[v['id'] for v in self.r.engine.pmm_versions()['cores']]);self.assertNotEqual(original,self.r.engine.model.adapter_id)

class NumericalTests(unittest.TestCase):
    def model(self):
        m=LearnedPMM(identity=uuid.uuid4().hex)
        for i in range(40):
            x=vector('问候'+str(i));x[160:164]=[.2,.3,.2,.6]
            m.add('v2:'+str(i),x,state=dict(zip(STATE_KEYS,[.3,.4,.1,.8])),style=[.1,.8,.2,.1,.1,.2,.1,.3],action='reply',perspective=[.2,.6,.2],linguistic=[.1,.5,.8,.2],projection=[.1]*30,source='human_correction')
        return m
    def test_actual_gradients_reduce_losses_without_mutating_core_or_holdout(self):
        m=self.model();core=m.core_hash();a=m.export_adapter();rows=[s for s in m.samples if not s['heldout']];before=m.evaluate(rows);held=copy.deepcopy([s for s in m.samples if s['heldout']])
        m.fit(70);after=m.evaluate(rows);self.assertEqual(core,m.core_hash());self.assertNotEqual(a['parameters'],m.export_adapter()['parameters'])
        for key in ('state_mse','style_mse','linguistic_mse','projection_mse','perspective_cross_entropy'):self.assertLess(after[key],before[key])
        self.assertEqual(held,[s for s in m.samples if s['heldout']]);self.assertEqual(m.export(),LearnedPMM(m.export(),m.identity).export())
        self.assertFalse(np.array_equal(m.adapter['U'],np.zeros_like(m.adapter['U'])))
    def test_heldout_targets_have_no_effect_on_gradients(self):
        a=self.model();b=a.fork();n=0
        for row in b.samples:
            if row['heldout']:row['style']=[1]*8;row['projection']=[-.2]*30;row['perspective']=[1,0,0];n+=1
        self.assertGreater(n,0);a.fit(12);b.fit(12);self.assertEqual(a.core(),b.core());self.assertEqual(a.export_adapter(),b.export_adapter())
    def test_core_update_does_not_update_delta_and_invalid_counts_reject(self):
        m=self.model();adapter=m.export_adapter();core=m.core_hash();m.fit(5,target='core');self.assertNotEqual(core,m.core_hash());self.assertEqual(adapter['parameters'],m.export_adapter()['parameters']);self.assertEqual(m.adapter_steps,0)
        bad=m.export();bad['steps']+=1
        with self.assertRaises(ValueError):LearnedPMM(bad,m.identity)
    def test_incremental_replay_retains_old_samples_and_auditable_sources(self):
        m=self.model();ids={s['id'] for s in m.samples};m.fit(4)
        for i in range(6):m.add('new:'+str(i),vector('新的问题'+str(i)),style=[.1]*8,source='imported_style')
        m.fit(4);self.assertTrue(ids<={s['id'] for s in m.samples});self.assertEqual(m.adapter_steps,8)

class LearnedHTTPTests(unittest.TestCase):
    def setUp(self):
        self.http=make_server('127.0.0.1',0,'v2-test-key-long-enough');threading.Thread(target=self.http.serve_forever,daemon=True).start();self.local=NumericalTests().model()
        self.remote=RemotePMM(self.local.export(),self.local.identity,{'model':MODEL_ID,'base_url':'http://127.0.0.1:'+str(self.http.server_port),'api_key':'v2-test-key-long-enough','timeout':10})
    def tearDown(self):self.http.shutdown();self.http.server_close()
    def test_http_adapter_and_core_training_match_local_exactly(self):
        self.local.fit(5);self.remote.fit(5);self.assertEqual(self.local.export(),self.remote.export())
        self.assertEqual(self.local.decode(vector(TEXT)),self.remote.decode(vector(TEXT)))
        self.local.fit(3,target='core');self.remote.fit(3,target='core');self.assertEqual(self.local.export(),self.remote.export())
    def test_bad_projection_and_unauthorized_core_change_are_rejected(self):
        def bad_projection(body):
            r=execute_request(body)
            if body['operation']=='decode':r['result']['perspective_offsets'][0][0]=2
            return r
        with patch('persona.pmm_service.execute_request',side_effect=bad_projection),self.assertRaises(ProviderError):self.remote.decode(vector(TEXT))
        before=self.remote.export()
        def bad_training(body):
            b=copy.deepcopy(body);b['arguments']['target']='core';return execute_request(b)
        with patch('persona.pmm_service.execute_request',side_effect=bad_training),self.assertRaises(ProviderError):self.remote.fit(3)
        self.assertEqual(before,self.remote.export())

class DualProtocolTests(unittest.TestCase):
    def test_two_separate_real_http_services_route_all_calls_and_keys(self):
        servers=[]
        for kind in ('responses','anthropic'):
            server=ThreadingHTTPServer(('127.0.0.1',0),NativeFixture);server.kind=kind;server.requests=[];threading.Thread(target=server.serve_forever,daemon=True).start();servers.append(server)
        try:
            with tempfile.TemporaryDirectory() as directory:
                config=Config(directory);config.update({'provider':'responses','model':'general','base_url':'http://127.0.0.1:'+str(servers[0].server_port),'api_key':'general-key','pmm':{'api':{'provider':'anthropic','model':'psych','base_url':'http://127.0.0.1:'+str(servers[1].server_port),'api_key':'psych-key'}}})
                store=Store(directory)
                try:
                    engine=Engine(store,config);self.assertTrue(engine.test_pmm()['ok']);servers[1].requests=[]
                    result=engine.turn(store.session(),TEXT);self.assertEqual(result['reply'],'说。');self.assertEqual(len(servers[0].requests),3);self.assertEqual(len(servers[1].requests),3)
                    for i,(model,key) in enumerate((('general','general-key'),('psych','psych-key'))):
                        for _,body,headers in servers[i].requests:self.assertEqual(body['model'],model);self.assertIn(key,' '.join(headers.values()));self.assertNotIn(('psych-key','general-key')[i],' '.join(headers.values()))
                    self.assertEqual(len(result['trace']['api_calls']),3);self.assertEqual(len(result['trace']['pmm_api_calls']),3)
                finally:store.close()
        finally:
            for server in servers:server.shutdown();server.server_close()

if __name__=='__main__':unittest.main(verbosity=2)

class V2RouteTests(RuntimeCase):
    def setUp(self):
        super().setUp();self.http=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.http.app=self.r;self.r.http=self.http;self.r.port=self.http.server_port
        threading.Thread(target=self.http.serve_forever,daemon=True).start();self.base='http://127.0.0.1:'+str(self.http.server_port)
        with urllib.request.urlopen(self.base+'/') as r:cookie=r.headers['Set-Cookie'].split(';')[0]
        self.headers={'Cookie':cookie,'X-CSRF-Token':self.r.token,'Content-Type':'application/json'}
    def tearDown(self):self.http.shutdown();self.http.server_close();super().tearDown()
    def request(self,path,body=None):
        req=urllib.request.Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=self.headers)
        with urllib.request.urlopen(req,timeout=15) as r:return json.load(r)
    def job(self,result):
        for _ in range(150):
            r=self.request('/api/jobs/'+result['job_id'])
            if r['status'] in ('done','error'):self.assertEqual(r['status'],'done',r);return r['result']
            time.sleep(.03)
        self.fail('job timeout')
    def test_api_pmm_package_synthesis_and_persona_revision_routes(self):
        self.job(self.request('/api/distill',{'content':CHAT,'speaker':'乙','target':'self'}))
        self.job(self.request('/api/chat',{'session_id':self.sid,'text':TEXT}));self.job(self.request('/api/persona/synthesize',{}))
        self.assertTrue(self.request('/api/state')['synthesis']['statements'])
        p=self.request('/api/persona/export');self.assertEqual(p['format'],'persona-package/2.3');self.assertTrue(self.request('/api/persona/apply',p)['ok'])
        revision=self.request('/api/persona/checkpoint',{'label':'HTTP checkpoint'});self.assertTrue(self.request('/api/persona/rollback',{'id':revision['id']})['ok'])
        self.assertGreater(len(self.request('/api/persona/revisions')),0)
        self.request('/api/pmm/api/copy-general',{});self.assertEqual(self.r.config.get()['pmm']['api']['api_key'],'GENERAL_SECRET')
    def test_core_adapter_and_weight_version_routes(self):
        self.distill();self.request('/api/config',{'pmm':{'mode':'learned'}})
        self.job(self.request('/api/pmm/train',{'epochs':3}));v=self.request('/api/pmm/version/save',{'label':'saved'})
        adapter=self.request('/api/pmm/adapter/export');self.assertTrue(self.request('/api/pmm/adapter/import',adapter)['ok'])
        core=self.request('/api/pmm/core/export');entry=self.request('/api/pmm/core/import',core);self.assertIn(entry['id'],[x['id'] for x in self.request('/api/pmm/versions')['cores']])
        trained=self.job(self.request('/api/pmm/core/train',{'epochs':3}));self.assertFalse(trained['activated'])
        self.assertTrue(self.request('/api/pmm/core/activate',{'id':trained['version']['id']})['ok'])
        self.assertTrue(self.request('/api/pmm/version/activate',{'id':v['id']})['ok']);self.assertEqual(self.request('/api/pmm/adapter/export'),adapter)

class AllAPIPMMProtocols(unittest.TestCase):
    def test_api_pmm_supports_six_native_transports_in_full_loops(self):
        general=ThreadingHTTPServer(('127.0.0.1',0),NativeFixture);general.kind='responses';general.requests=[]
        psych=ThreadingHTTPServer(('127.0.0.1',0),NativeFixture);psych.requests=[]
        for server in (general,psych):threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            for kind in ('ollama','chat_completions','responses','anthropic','gemini','azure_chat'):
                with self.subTest(kind=kind),tempfile.TemporaryDirectory() as directory:
                    psych.kind=kind;psych.requests=[];config=Config(directory)
                    config.update({'provider':'responses','model':'general','base_url':'http://127.0.0.1:'+str(general.server_port),'pmm':{'api':{'provider':kind,'model':'psych','base_url':'http://127.0.0.1:'+str(psych.server_port),'api_key':'psych-key'}}})
                    store=Store(directory)
                    try:
                        result=Engine(store,config).turn(store.session(),TEXT);self.assertEqual(result['reply'],'说。');self.assertEqual(len(psych.requests),3)
                        self.assertTrue(all(c['protocol']==kind for c in result['trace']['pmm_api_calls']))
                    finally:store.close()
        finally:
            for server in (general,psych):server.shutdown();server.server_close()
