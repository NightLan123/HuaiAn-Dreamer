"""Cross-module regressions; synthetic providers/data, real SQLite and threads."""
import copy,json,threading,unittest,subprocess,sys,os
from pathlib import Path
from unittest.mock import patch
import numpy as np
from test_v212 import Base,PatchProvider,ROOT
from test_v28_stage4 import dataset,import_fixture
from persona.server import Runtime
from persona.pmm_coordinator import PMMCoordinator,ExistingMemoryEvidence
from persona.pmm_contracts import TurnContext
from persona.registry import digest

class Regression(Base):
    def test_disabled_long_term_module_is_not_executed(self):
        self.r.configure({'pmm28':{'mode':'active','long_term_mode':'disabled'}})
        with patch('persona.trait_estimator.LongTermEstimator.estimate',side_effect=AssertionError('must not estimate')):out=self.turn()
        long=out['trace']['pmm28']['long_term'];self.assertEqual(long['status'],'disabled');self.assertFalse(long['executed'])
        self.assertEqual(long['payload']['stable_trait_version_read'],self.r.engine.profile()['trait_profile']['version'])
    def test_default_shadow_survives_actual_internal_HTTP_connection_refused(self):
        import socket
        from persona.provider import Provider
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        self.r.configure({'pmm':{'api':{'provider':'chat_completions','base_url':'http://127.0.0.1:'+str(port)+'/v1','model':'no-server-fixture'}}})
        self.r.engine.pmm_provider_factory=Provider
        out=self.turn();t=out['trace']['pmm28'];self.assertEqual(t['mode'],'shadow');self.assertTrue(out['reply'])
        self.assertEqual(t['components']['reasoner']['status'],'failed');self.assertTrue(t['components']['neural']['executed'])
        self.assertFalse(t['components']['decision']['payload']['formal_contribution'])
    def train(self,job='job',expected=0,parent=None):
        owner=self.r.engine.profile()['id'];co=PMMCoordinator(self.r.engine);rows,plan=dataset(owner)
        if self.r.store.meta('pmm28_samples') is None:import_fixture(co,owner,rows)
        out=co.model_action({'op':'train','subject_id':owner,'expected_revision':expected,'job_id':job,'split_plan':plan,'version':parent,'epochs':2,'structural_candidates':[0.]})
        return co,out
    def test_restart_keeps_candidate_and_same_scope_recurrent_state(self):
        co,trained=self.train();sid=self.session();first=self.turn(sid=sid)['trace']['pmm28']
        catalog=self.r.store.meta('pmm28_models');history=self.r.store.history(sid)
        self.r.close();self.r=Runtime(self.tmp.name,ROOT);self.fixture()
        self.assertEqual(catalog,self.r.store.meta('pmm28_models'));self.assertEqual(history,self.r.store.history(sid))
        second=self.turn(sid=sid)['trace']['pmm28']
        self.assertEqual(second['components']['neural']['payload']['inputs']['h_prev'],first['components']['neural']['payload']['latent'])
        isolated=self.turn(sid=self.session('456'))['trace']['pmm28']
        self.assertEqual(isolated['components']['neural']['payload']['inputs']['h_prev'],[0.]*16)
    def test_private_memory_not_sent_to_other_scope_reasoner(self):
        owner=self.r.engine.profile()['id'];self.r.configure({'pmm':{'mode':'learned'},'pmm28':{'mode':'active'}})
        with self.r.store.lock,self.r.store.db:
            self.r.store.db.execute('INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('sensitive','PRIVATE_SENTINEL_A','preference','private:qq:123','qq:123',.9,.9,'active','fixture','PRIVATE_SENTINEL_A',1.,1.,1,'fixture'))
        PatchProvider.seen=[];out=self.turn(sid=self.session('456'));t=out['trace']['pmm28']
        self.assertNotIn('PRIVATE_SENTINEL_A',json.dumps(PatchProvider.seen));self.assertNotIn('PRIVATE_SENTINEL_A',json.dumps(t))
        self.assertEqual(t['components']['reasoner']['status'],'ok')
        ctx=TurnContext(owner,'private:qq:456','e',1.,0,turn_id='t',person_id='qq:456')
        with self.assertRaises(ValueError):ExistingMemoryEvidence().retrieve(ctx,memories=[{'scope':'private:qq:123'}])
        self.assertEqual(ExistingMemoryEvidence().retrieve(ctx,memories=[{'scope':'self'}])['status'],'ok')
    def test_two_personas_keep_adapter_catalog_labels_and_history_isolated(self):
        a=self.r.engine.profile()['id'];co,res=self.train();cp=self.r.store.meta('pmm28_models')['versions'][res['candidate']]
        self.turn();a_state=digest(self.r.store.snapshot()['tables'])
        self.r.create_persona({'name':'B'});self.fixture();b=self.r.engine.profile()['id']
        self.assertNotEqual(a,b);self.assertIsNone(self.r.store.meta('pmm28_models'));self.assertIsNone(self.r.store.meta('pmm28_samples'))
        from persona.trait_dynamics import TraitDynamics
        with self.assertRaises(ValueError):TraitDynamics(cp,b)
        with self.assertRaises(ValueError):PMMCoordinator(self.r.engine).model_action({'op':'train','subject_id':a,'expected_revision':0,'job_id':'foreign'})
        self.r.switch(a);self.fixture();self.assertEqual(a_state,digest(self.r.store.snapshot()['tables']))
    def test_concurrent_stale_training_commits_only_one_candidate(self):
        owner=self.r.engine.profile()['id'];co=PMMCoordinator(self.r.engine);rows,plan=dataset(owner);import_fixture(co,owner,rows)
        outcomes=[];barrier=threading.Barrier(2)
        def worker(i):
            barrier.wait()
            try:outcomes.append(co.model_action({'op':'train','subject_id':owner,'expected_revision':0,'job_id':str(i),'split_plan':plan,'epochs':1,'structural_candidates':[0.]}))
            except ValueError as ex:outcomes.append(str(ex))
        threads=[threading.Thread(target=worker,args=(i,)) for i in range(2)]
        for t in threads:t.start()
        for t in threads:t.join(20);self.assertFalse(t.is_alive())
        self.assertEqual(sum(isinstance(r,dict) for r in outcomes),1);self.assertEqual(self.r.store.meta('pmm28_models')['revision'],1)
    def test_active_duplicate_input_ids_cannot_commit_twice(self):
        self.r.configure({'pmm28':{'mode':'active'}});sid=self.session()
        first=self.r.engine.turn(sid,'真实形状的合成事件',turn_context={'sources':['qq-test-1']})
        before=copy.deepcopy(self.r.store.history(sid))
        second=self.r.engine.turn(sid,'真实形状的合成事件',turn_context={'sources':['qq-test-1']})
        self.assertEqual(before,self.r.store.history(sid));self.assertEqual(second['turn_id'],first['turn_id'])
    def test_new_component_failure_falls_back_without_second_commit(self):
        self.r.configure({'pmm28':{'mode':'active'}})
        for port in ('ExistingMemoryEvidence.retrieve','ExistingAffect.advance','ExistingRelationship.evaluate','CoordinatedDecision.decide'):
            before=self.r.store.meta('state')['turn_count']
            with patch('persona.pmm_coordinator.'+port,side_effect=ValueError('controlled port failure')):out=self.turn()
            self.assertTrue(out['reply']);self.assertEqual(out['trace']['pmm28']['fallback'],'legacy')
            self.assertEqual(self.r.store.meta('state')['turn_count'],before+1)
    def test_publication_revoke_rollback_transactions_with_explicit_gate_injection(self):
        # Engineering-only candidates are NEVER accepted by the real gate.
        co,a=self.train('a');co,b=self.train('b',1,a['candidate']);owner=self.r.engine.profile()['id'];rev=2
        self.assertNotEqual(a['candidate'],b['candidate'])
        for key in (a['candidate'],b['candidate']):
            co.model_action({'op':'freeze','subject_id':owner,'expected_revision':rev,'version':key});rev+=1
        with self.assertRaises(ValueError):co.model_action({'op':'publish','subject_id':owner,'expected_revision':rev,'version':a['candidate']})
        with patch('persona.pmm_trainer.publication_eligibility',return_value=(True,'injected_transaction_test')),patch('persona.pmm_trainer.published_gate',return_value=(True,'injected_transaction_test')):
            for key in (a['candidate'],b['candidate']):
                co.model_action({'op':'publish','subject_id':owner,'expected_revision':rev,'version':key});rev+=1
            co.model_action({'op':'rollback','subject_id':owner,'expected_revision':rev,'version':a['candidate']});rev+=1
        self.assertEqual(self.r.store.meta('pmm28_models')['published'],a['candidate'])
        co.model_action({'op':'revoke','subject_id':owner,'expected_revision':rev,'version':a['candidate']})
        self.assertIsNone(self.r.store.meta('pmm28_models')['published'])
    def test_training_cli_respects_runtime_lock_and_creates_candidate(self):
        owner=self.r.engine.profile()['id'];co=PMMCoordinator(self.r.engine);rows,plan=dataset(owner);import_fixture(co,owner,rows)
        split=Path(self.tmp.name)/'plan.json';split.write_text(json.dumps(plan));out=Path(self.tmp.name)/'candidate-export'
        self.r.close()
        args=[sys.executable,str(ROOT/'scripts/train_pmm28.py'),'--data-dir',self.tmp.name,'--subject-id',owner,'--split-plan',str(split),'--epochs','1','--output',str(out)]
        from persona.lock import InstanceLock
        try:
            with InstanceLock(self.tmp.name):
                blocked=subprocess.run(args,capture_output=True,text=True,timeout=30)
                self.assertNotEqual(blocked.returncode,0);self.assertFalse(out.exists())
            trained=subprocess.run(args,capture_output=True,text=True,timeout=40)
            self.assertEqual(trained.returncode,0,trained.stderr)
            info=json.loads(trained.stdout);self.assertFalse(info['published']);self.assertTrue((out/'candidate.json').is_file())
        finally:self.r=Runtime(self.tmp.name,ROOT);self.fixture()
        self.assertIsNone(self.r.store.meta('pmm28_models')['published'])

if __name__=='__main__':unittest.main()
