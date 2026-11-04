"""Cross-module acceptance for history, expression, boundary gates and mode isolation."""
import json,unittest
from unittest.mock import patch
from test_v212 import Base
from test_v281_runtime import Provider281
from persona import affect_runtime as ar
from persona.registry import digest
class Integrated281(Base):
    def fixture(self):self.r.engine.pmm_provider_factory=self.r.engine.provider_factory=Provider281
    def setUp(self):super().setUp();Provider281.seen=[];Provider281.fail_a=Provider281.fail_b=False
    def test_two_scopes_keep_owner_history_without_private_prompt_reuse(self):
        a=self.turn('甲私密原文',self.session('123'));b=self.turn('乙私密原文',self.session('456'));archive=self.r.store.meta('pmm_affect')
        for key in ('appraisals','regulation_actions','expressions','trajectory'):self.assertEqual(len(archive[key]),2,key)
        self.assertEqual(archive['appraisals'][0]['evidence_quote'],'甲私密原文');self.assertEqual(archive['appraisals'][1]['evidence_quote'],'乙私密原文')
        last=[m for m in Provider281.seen if '[PMM_A_' in m[0]['content']][-1];self.assertNotIn('甲私密原文',last[-1]['content']);self.assertIn('乙私密原文',last[-1]['content'])
        self.assertNotIn(None,archive['appraisals'][1]['emotion_before'].values());self.assertEqual(self.r.store.meta(ar.KEY)['revision'],2)
    def test_hard_boundary_overrides_model_preferences(self):
        self.r.configure({'pmm281':{'b_policy':'always'}});p=self.r.engine.profile();p['boundaries']=[{'id':'chosen-boundary','enabled':True,'hard':True,'keywords':['合成禁词'],'label':'实验边界','action':'decline'}]
        with self.r.store.lock,self.r.store.db:self.r.store.setmeta('pmm_profile',p)
        o=self.turn('讨论合成禁词');d=o['trace']['decision'];self.assertEqual((d['action'],d['gate']),('decline','hard_boundary'));self.assertFalse(o['trace']['pmm28']['components']['decision']['payload']['formal_contribution'])
    def test_legacy_deliberation_switch_does_not_disable_full_B(self):
        self.r.configure({'pmm281':{'b_policy':'auto'},'deliberation':{'enabled':False,'mode':'off'}})
        from persona import deliberation as dl
        real_trigger=dl.trigger
        def conflict(c,u,decoded,relation):u['semantic']['value_conflict']=.9;return real_trigger(c,u,decoded,relation)
        with patch('persona.deliberation.trigger',side_effect=conflict):out=self.turn()
        self.assertEqual(out['trace']['pmm28']['components']['negotiation']['status'],'ok')
    def test_full_component_failure_leaves_prior_v2_revision_intact(self):
        self.turn();before=self.r.store.meta(ar.KEY)
        with patch('persona.affect_runtime.draft',side_effect=ValueError('controlled failure')):out=self.turn()
        self.assertEqual(out['trace']['pmm28']['fallback'],'compatibility_on_component_failure');self.assertEqual(before,self.r.store.meta(ar.KEY));self.assertTrue(out['reply']);self.assertIn('frames',out['trace']['pmm28']['error'])
    def test_qq_three_acknowledgements_commit_one_emotion(self):
        from test_cbm_v240 import Delivery,BurstProvider
        f=Delivery('test_full_burst_has_three_history_rows_one_episode_one_training_group');f.setUp()
        try:
            class FullBurst(Provider281,BurstProvider):pass
            f.r.engine.provider_factory=f.r.engine.pmm_provider_factory=FullBurst
            f.test_full_burst_has_three_history_rows_one_episode_one_training_group()
            self.assertEqual(f.r.store.meta(ar.KEY)['revision'],1)
        finally:f.tearDown()
    def test_partial_qq_reconciliation_does_not_reapply_jump(self):
        from test_cbm_v240 import Delivery,BurstProvider
        f=Delivery('test_second_timeout_preserves_prefix_and_reconciliation_never_sends_tail');f.setUp()
        try:
            class FullBurst(Provider281,BurstProvider):pass
            f.r.engine.provider_factory=f.r.engine.pmm_provider_factory=FullBurst
            f.test_second_timeout_preserves_prefix_and_reconciliation_never_sends_tail()
            self.assertEqual(f.r.store.meta(ar.KEY)['revision'],1)
        finally:f.tearDown()
    def test_old_seed_trace_and_extended_context_ablation(self):
        import numpy as np
        from persona.trait_dynamics import initial_checkpoint,TraitDynamics
        from persona.pmm_experiments import ablate
        from test_v28_stage2 import inputs
        owner=self.r.engine.profile()['id'];old=initial_checkpoint(owner,include_affect_context=False);new=initial_checkpoint(owner);self.assertNotIn('affect_context_h',old['parameters'])
        x=inputs();x['affect_context']=[.6]*8+[1.]*8;r=ablate(new,owner,x);case=next(c for c in r['cases'] if c['component']=='affect');self.assertGreater(case['latent_l2_delta'],0)
        base=TraitDynamics(old,owner).forward(x);x['affect_context']=[0.]*16;self.assertEqual(base,TraitDynamics(old,owner).forward(x))
