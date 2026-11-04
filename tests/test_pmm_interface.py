import copy,json,tempfile,threading,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import numpy as np
from persona.common import Config
from persona.engine import Engine
from persona.storage import Store
from persona.provider import ProviderError,request_json
from persona.pmm import PMM,vector
from persona.pmm_interface import LocalPMM,RemotePMM,execute_request,digest,CONTRACT,MODEL_ID
from persona.pmm_service import make_server
from persona.server import Runtime
from persona.psychology import parse_records
from fixtures import FixtureProvider,TEXT

class PMMInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.config=Config(self.tmp.name);self.store=Store(self.tmp.name)
        self.key='independent-pmm-secret';self.http=make_server('127.0.0.1',0,self.key);threading.Thread(target=self.http.serve_forever,daemon=True).start()
        self.connection={'mode':'legacy','backend':'http','base_url':'http://127.0.0.1:'+str(self.http.server_port),'api_key':self.key,'model':MODEL_ID,'timeout':10}
        self.config.update({'model':'fixture','pmm':self.connection});FixtureProvider.fail_stage=None
        self.engine=Engine(self.store,self.config,FixtureProvider);self.sid=self.store.session()
    def tearDown(self):self.http.shutdown();self.http.server_close();self.store.close();self.tmp.cleanup()
    def test_authenticated_health_list_and_inference_do_not_update_weights(self):
        with self.assertRaises(ProviderError):request_json(self.connection['base_url']+'/health',token='wrong')
        r=request_json(self.connection['base_url']+'/health',token=self.key);self.assertTrue(r['stateless'])
        models=request_json(self.connection['base_url']+'/v1/models',token=self.key);self.assertEqual(models['data'][0]['id'],MODEL_ID)
        before=digest(self.engine.model.export());self.assertTrue(self.engine.model.test()['ok']);self.assertEqual(before,digest(self.engine.model.export()))
    def test_remote_and_local_encoders_decoders_and_training_are_equivalent(self):
        local=LocalPMM(identity=self.store.meta('identity')['id']);remote=self.engine.model
        for i in range(8):
            labels={'style':[.02,1,0,0,0,0,0,.2],'action':'reply','source':'human_correction'}
            for m in (local,remote):m.add('same:'+str(i),vector('输入'+str(i)),**labels)
        self.assertEqual(local.export(),remote.export())
        local.fit(5);remote.fit(5);self.assertEqual(local.export(),remote.export())
        xs=[vector('你好'),vector('记忆')];np.testing.assert_allclose(local.encode_many(xs),remote.encode_many(xs),atol=1e-12)
        self.assertEqual(local.decode(xs[0],[xs[1]]),remote.decode(xs[0],[xs[1]]))
        local.rank_feedback([.1,.2,.3,.4],True);remote.rank_feedback([.1,.2,.3,.4],True);self.assertEqual(local.export(),remote.export())
    def test_remote_does_not_silently_run_local_inference(self):
        self.engine.model._checkpoint.encode=lambda *_:(_ for _ in ()).throw(AssertionError('local encode must not run'))
        self.engine.model._checkpoint.fit=lambda *_:(_ for _ in ()).throw(AssertionError('local fit must not run'))
        self.assertTrue(self.engine.model.test()['ok'])
    def test_full_dialogue_and_actual_reply_return_to_remote_training(self):
        operations=[]
        def record(body):operations.append(body['operation']);return execute_request(body)
        with patch('persona.pmm_service.execute_request',side_effect=record):result=self.engine.turn(self.sid,TEXT)
        self.assertEqual(result['reply'],'说。');self.assertEqual(result['trace']['pmm_backend'],'http')
        self.assertIn('encode',operations);self.assertIn('decode',operations);self.assertIn('train',operations)
        self.assertTrue(any(s['source']=='generated_episode' for s in self.engine.model.samples))
        self.assertEqual(self.store.meta('pmm_checkpoint'),self.engine.model.export())
    def test_remote_training_failure_rolls_back_whole_turn(self):
        checkpoint=self.engine.model.export();state=self.store.meta('state')
        def fail(body):
            if body['operation']=='train':raise ValueError('worker rejected')
            return execute_request(body)
        with patch('persona.pmm_service.execute_request',side_effect=fail):
            with self.assertRaises(ProviderError):self.engine.turn(self.sid,TEXT)
        self.assertEqual(checkpoint,self.engine.model.export());self.assertEqual(state,self.store.meta('state'));self.assertEqual(self.store.history(self.sid),[])
    def test_wrong_identity_or_hash_response_cannot_be_applied(self):
        def corrupt(body):r=execute_request(body);r['identity_id']=uuid.uuid4().hex;return r
        with patch('persona.pmm_service.execute_request',side_effect=corrupt):
            with self.assertRaises(ProviderError):self.engine.model.test()
        self.assertEqual(self.store.meta('state')['turn_count'],0)
    def test_remote_invalid_decoded_values_fail(self):
        def corrupt(body):
            r=execute_request(body)
            if body['operation']=='decode':r['result']['state']['stress']=5
            return r
        with patch('persona.pmm_service.execute_request',side_effect=corrupt):
            with self.assertRaises(ProviderError):self.engine.model.test()
    def test_switching_backend_preserves_identity_history_and_exact_weights(self):
        self.engine.turn(self.sid,TEXT);before=self.engine.model.export();identity=self.store.meta('identity');history=self.store.history(self.sid)
        self.config.update({'pmm':{'backend':'local'}});self.engine.reconnect_pmm();self.assertEqual(self.engine.model.backend,'local')
        self.assertEqual(before,self.engine.model.export());self.config.update({'pmm':{'backend':'http'}});self.engine.reconnect_pmm()
        self.assertEqual(before,self.engine.model.export());self.assertEqual(identity,self.store.meta('identity'));self.assertEqual(history,self.store.history(self.sid))
    def test_historical_distillation_and_human_feedback_train_remote_model(self):
        records=parse_records('甲：在吗\n乙：说\n甲：还在吗\n乙：在\n甲：什么想法\n乙：没')
        r=self.engine.import_records([x for x in records if x['speaker']=='乙']);self.assertEqual(r['report']['added'],3)
        self.assertGreater(self.engine.model.steps,0);turn=self.engine.turn(self.sid,TEXT);before=self.engine.model.steps
        self.engine.feedback(turn['turn_id'],'unhelpful',corrected_reply='说',action_target='reply');self.assertGreater(self.engine.model.steps,before)
        self.assertEqual(self.engine.profile()['style']['count'],4)
    def test_foreign_weights_rejected_and_same_subject_import_is_reversible(self):
        package=self.engine.export_weights();bad=copy.deepcopy(package);bad['identity_id']=uuid.uuid4().hex
        with self.assertRaises(ValueError):self.engine.import_weights(bad)
        self.engine.turn(self.sid,TEXT);current=self.engine.model.export();self.engine.import_weights(package)
        self.assertEqual(package['checkpoint'],self.engine.model.export());self.assertEqual(current,self.store.meta('pmm_checkpoint_previous'))
    def test_backup_does_not_export_second_key_and_restore_keeps_both_connections(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=Runtime(tmp,Path(__file__).resolve().parents[1]);app.configure({'api_key':'llm-secret','extra_headers':{'X-Test':'header-secret'},'pmm':self.connection})
            try:
                snap=app.snapshot();text=json.dumps(snap);self.assertNotIn('llm-secret',text);self.assertNotIn('header-secret',text);self.assertNotIn(self.key,text)
                before=app.config.get();app.restore(snap);self.assertEqual(before,app.config.get())
            finally:
                app.bridge.stop.set()
                if app.bridge.thread.is_alive():app.bridge.thread.join(3)
                app.close_pmm();app.store.close()
    def test_unknown_operation_and_excess_vector_budget_are_rejected(self):
        cp=self.engine.model.export();body={'contract':CONTRACT,'model':MODEL_ID,'request_id':uuid.uuid4().hex,'identity_id':self.store.meta('identity')['id'],'checkpoint':cp,'checkpoint_sha256':digest(cp),'operation':'delete','arguments':{}}
        with self.assertRaises(ValueError):execute_request(body)
        body.update(operation='encode',arguments={'vectors':[vector('').tolist()]*513})
        with self.assertRaises(ValueError):execute_request(body)

if __name__=='__main__':unittest.main()
