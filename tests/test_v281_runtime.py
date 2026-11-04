"""Actual Engine/SQLite path. LLM responses below are explicit test fixtures."""
import copy,json,unittest
from unittest.mock import patch
import numpy as np
from test_v212 import Base,PatchProvider
from persona.registry import digest
from persona import affect_runtime as ar
from persona.trait_dynamics import initial_checkpoint,seal,TraitDynamics

class Provider281(PatchProvider):
    fail_a=False;fail_b=False
    def complete(self,messages,structured=False,controller=False):
        system=messages[0]['content']
        if '[PMM_A_EVENT_V281]' in system:
            self.seen.append(copy.deepcopy(messages));self.calls.append({'stage':'A','model':self.config['model'],'duration_ms':1})
            if self.fail_a:raise TimeoutError('synthetic A timeout')
            x=json.loads(messages[-1]['content']);text=x['input']
            return {'facts':[{'quote':text,'kind':'reported'}],'appraisal_checks':{'affect.appraisal.goal_conduciveness':.25,'affect.appraisal.control':.7,'affect.appraisal.goal_relevance':.8},'evidence_quote':text,
                'reappraisal_checks':None,'action_prior':{'reply':.6,'unknown':.05,'clarify':.15,'disagree':.1,'decline':.05,'silence':.05},'language_condition':'测试夹具的事件摘要','uncertainties':[],'retrieval_queries':[],'memory_focus':[]}
        if '[PMM_B_DELIBERATION_V281]' in system:
            self.seen.append(copy.deepcopy(messages));self.calls.append({'stage':'B','model':self.config['model'],'duration_ms':1})
            if self.fail_b:raise TimeoutError('synthetic B timeout')
            x=json.loads(messages[-1]['content']);v=x['emotion']['emotion']['valence'];m=x['emotion']['mood']['valence']
            return {'views':[{'id':p['id'],'summary':'依据传入快情绪与慢心境的受控测试','utilities':{'reply':max(0,min(1,.6+.2*v+.1*m)),'unknown':.1,'clarify':.2,'disagree':max(0,min(1,.3-.2*v-.1*m)),'decline':.1,'silence':.05}} for p in x['projections']],
                'supported_memory_evidence':[],'retrieval_queries':[]}
        return super().complete(messages,structured,controller)

class Runtime281(Base):
    def fixture(self):
        self.r.engine.provider_factory=Provider281;self.r.engine.pmm_provider_factory=Provider281
    def setUp(self):
        super().setUp();Provider281.seen=[];Provider281.fail_a=False;Provider281.fail_b=False
        self.r.configure({'pmm281':{'mode':'full','b_policy':'always'}})
    def components(self,out):
        trace=out['trace']['pmm28'];self.assertIn('components',trace,trace);return trace['components']
    def test_default_full_real_forward_no_legacy_parallel(self):
        with patch('persona.affect.evaluate',side_effect=AssertionError('old affect must not run')):
            out=self.turn()
        co=self.components(out);e=co['affect']['payload']['dynamics_v2'];self.assertEqual(out['trace']['pmm28']['mode'],'full')
        self.assertNotIn('policy_comparison',out['trace']['pmm28']);self.assertEqual(co['reasoner']['status'],'ok');self.assertEqual(co['negotiation']['status'],'ok')
        self.assertEqual(co['neural']['payload']['inputs']['affect_context'][:5],list(e['affect_observed'].values()))
        self.assertEqual(co['neural']['payload']['inputs']['affect_context'][5:8],list(e['mood_observed'].values()))
        self.assertEqual(e['label_h_t'],co['neural']['payload']['latent']);self.assertEqual(len(e['emotion_labels']),24)
        self.assertEqual(self.r.store.meta(ar.KEY)['revision'],1);self.assertFalse(e['trait_written'])
        realize=next(m for m in Provider281.seen if '[REALIZE_V3]' in m[0]['content'])
        self.assertIn(e['affect_model_version'],realize[0]['content']);self.assertIn('regulation_v2',realize[0]['content'])
    def test_polling_does_not_resample_or_advance(self):
        out=self.turn();before=self.r.store.meta(ar.KEY);one=self.r.engine.affect_state();two=self.r.engine.affect_state(1e10)
        self.assertEqual(one,two);self.assertEqual(before,self.r.store.meta(ar.KEY))
    def test_on_demand_B_skipped_with_reason(self):
        self.r.configure({'pmm281':{'b_policy':'auto'}});out=self.turn();b=self.components(out)['negotiation']
        self.assertFalse(b['executed']);self.assertEqual(b['reason'],'on_demand_no_conflict_or_risk')
        self.assertFalse(any('[PMM_B_DELIBERATION_V281]' in m[0]['content'] for m in Provider281.seen))
    def test_failed_A_no_fake_appraisal_but_time_calculation(self):
        Provider281.fail_a=True;out=self.turn();co=self.components(out)
        self.assertEqual(co['reasoner']['status'],'failed');self.assertFalse(co['affect']['payload']['dynamics_v2']['jump_applied'])
        self.assertTrue(co['neural']['executed']);self.assertEqual(len(self.r.store.history(out['trace']['session_id'])),2)
    def test_failed_B_keeps_one_reply_and_commits_once(self):
        Provider281.fail_b=True;out=self.turn();co=self.components(out);self.assertEqual(co['negotiation']['status'],'failed')
        self.assertTrue(out['reply']);self.assertEqual(self.r.store.meta(ar.KEY)['revision'],1)
        sid=out['trace']['session_id'];self.assertEqual(len(self.r.store.history(sid)),2)
    def test_private_streams_and_neural_history_do_not_mix(self):
        s1=self.session('123');s2=self.session('123');a=self.turn('这是甲会话的私密安排。',s1);b=self.turn('普通问候。',s2)
        ca=self.components(a);cb=self.components(b);self.assertEqual(cb['neural']['payload']['inputs']['h_prev'],[0.]*16)
        self.assertEqual(len(self.r.store.meta(ar.KEY)['streams']),2)
        last_a=[m for m in Provider281.seen if '[PMM_A_EVENT_V281]' in m[0]['content']][-1]
        # The existing memory permission scope is shared for same person; emotion
        # snapshots remain session-local and never copy the other stream's latent.
        self.assertEqual(cb['affect']['payload']['dynamics_v2']['state_revision'],1)
    def test_next_turn_and_restart_use_committed_state(self):
        sid=self.session();a=self.turn(sid=sid);ea=self.components(a)['affect']['payload']['dynamics_v2']
        self.r.close()
        from persona.server import Runtime
        from pathlib import Path
        self.r=Runtime(self.tmp.name,Path(__file__).resolve().parents[1]);self.fixture()
        b=self.turn(sid=sid);eb=self.components(b)['affect']['payload']['dynamics_v2']
        self.assertEqual(eb['before_fast'],ea['fast_state_latent']);self.assertEqual(eb['state_revision'],2)
        self.assertGreaterEqual(eb['delta_seconds'],0)
    def test_explicit_compatibility_and_switch_back_preserve_new_state(self):
        self.turn();old=copy.deepcopy(self.r.store.meta(ar.KEY));self.r.configure({'pmm281':{'mode':'compatibility'}})
        out=self.turn();self.assertNotIn('pmm28',out['trace']);self.assertEqual(old,self.r.store.meta(ar.KEY))
        self.r.configure({'pmm281':{'mode':'full'}});self.assertEqual(self.r.config.get()['pmm']['api']['model'],'pmm-fixture');self.assertIn('components',self.turn()['trace']['pmm28'])
    def test_two_subjects_do_not_share_model_or_state(self):
        self.turn();first=self.r.store.meta('identity')['id'];saved=copy.deepcopy(self.r.store.meta(ar.KEY))
        self.r.create_persona({'name':'第二主体'});self.fixture();self.assertNotEqual(self.r.store.meta('identity')['id'],first)
        self.assertEqual(self.r.store.meta(ar.KEY)['revision'],0);self.r.switch(first);self.fixture();self.assertEqual(saved,self.r.store.meta(ar.KEY))
    def test_untrained_neural_probabilities_do_not_override_boundaries(self):
        out=self.turn();c=self.components(out);self.assertFalse(c['neural']['payload']['formal_eligible']);self.assertFalse(c['decision']['payload']['formal_contribution'])
    def test_duplicate_source_has_one_state_commit_and_reply(self):
        sid=self.session();context={'sources':['fixture-source-281']}
        a=self.r.engine.turn(sid,'一个事件',turn_context=context);before=self.r.store.meta(ar.KEY)
        b=self.r.engine.turn(sid,'一个事件',turn_context=context)
        self.assertEqual(before,self.r.store.meta(ar.KEY));self.assertEqual(len(self.r.store.history(sid)),2)
        self.assertEqual(a['reply'],b['reply']);self.assertEqual(a['trace']['pmm28']['formal_state_writes'],1)
    def test_pre_attention_uses_current_scope_only(self):
        sid=self.session();self.turn(sid=sid)
        local=self.r.engine.activity('private:qq:123','qq:123',sid)
        other=self.r.engine.activity('private:qq:999','qq:999','other-session')
        self.assertNotEqual(local['emotion'],other['emotion'])
        self.assertEqual(self.r.store.meta(ar.KEY)['revision'],1)

class NeuralContext(unittest.TestCase):
    def test_old_weights_exactly_preserved_missing_extension(self):
        from test_v28_stage2 import inputs
        m=initial_checkpoint('a');m['parameters'].pop('affect_context_h');m=seal(m);n=TraitDynamics(m,'a');x=inputs();a=n.forward(x);x['affect_context']=[.5]*16;b=n.forward(x)
        self.assertEqual(a,b)
    def test_fast_mood_intervention_reaches_h_and_action(self):
        from test_v28_stage2 import inputs
        m=initial_checkpoint('a');n=TraitDynamics(m,'a');x=inputs();before=n.forward(x);x['affect_context']=[.4]*8+[1.]*8;after=n.forward(x)
        self.assertNotEqual(before['latent'],after['latent']);self.assertNotEqual(before['action_probabilities'],after['action_probabilities'])

if __name__=='__main__':unittest.main()
