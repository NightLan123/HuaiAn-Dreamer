import copy,json,unittest
from unittest.mock import patch
import numpy as np
from test_v212 import Base,PatchProvider
from test_v28_stage2 import inputs,known
from persona.pmm_coordinator import PMMCoordinator,CoordinatedDecision
from persona.pmm_contracts import TurnContext,BLOCK_IDS
from persona.trait_dynamics import initial_checkpoint
from persona.pmm_experiments import ablate,intervention,from_turn
from persona.registry import digest

class ActivePipeline(Base):
    def test_active_uncalibrated_runs_network_but_no_random_policy(self):
        self.r.configure({'pmm28':{'mode':'active'}});out=self.turn();t=out['trace']['pmm28']
        self.assertIn('components',t,t);self.assertTrue(t['components']['neural']['executed'])
        self.assertFalse(t['components']['neural']['payload']['formal_eligible'])
        self.assertFalse(t['components']['decision']['payload']['formal_contribution'])
        self.assertFalse(t['policy_comparison']['action_changed'])
        self.assertEqual(t['long_term']['status'],'not_ready')
    def test_internal_api_timeout_does_not_kill_turn_or_retry_twice(self):
        class Broken(PatchProvider):
            attempts=0
            def complete(self,messages,*args,**kwargs):
                Broken.attempts+=1;raise TimeoutError('controlled transport timeout')
        self.r.configure({'pmm28':{'mode':'active'}});self.r.engine.pmm_provider_factory=Broken
        out=self.turn();t=out['trace']['pmm28'];self.assertTrue(out['reply']);self.assertIn('components',t,t)
        self.assertEqual(t['components']['reasoner']['status'],'failed');self.assertTrue(t['components']['neural']['executed'])
        self.assertEqual(Broken.attempts,1);self.assertEqual(t['external_sends'],0)
        self.assertEqual(t['components']['neural']['payload']['inputs']['q'],[0.]*11)
    def test_learned_mode_still_calls_independent_API(self):
        self.r.configure({'pmm':{'mode':'learned'},'pmm28':{'mode':'active'}})
        out=self.turn();t=out['trace']['pmm28'];self.assertIn('components',t,t)
        r=t['components']['reasoner'];self.assertEqual(r['status'],'ok',r)
        self.assertEqual(r['provenance']['execution'],'independent_api_request')
        self.assertEqual(r['payload']['provider']['model'],'pmm-fixture')
    def test_legacy_promotion_blocked_only_in_active(self):
        self.r.configure({'pmm28':{'mode':'active'}})
        with self.assertRaises(ValueError):self.r.engine.review_traits(True)
        self.r.configure({'pmm28':{'mode':'legacy'}});self.r.engine.review_traits(True)
    def test_negative_event_does_not_modify_stable_priors(self):
        self.r.configure({'pmm28':{'mode':'active'}});before=copy.deepcopy(self.r.engine.profile()['trait_profile'])
        out=self.turn('我很生气，你刚才完全没理解我。')
        self.assertEqual(before,self.r.engine.profile()['trait_profile']);self.assertTrue(out['trace']['pmm28']['components']['affect']['executed'])
    def test_six_ablations_and_exact_checkpoint_without_state_writes(self):
        out=self.turn();before=digest(self.r.store.snapshot()['tables'])
        report=from_turn(self.r.engine,{'subject_id':self.r.engine.profile()['id'],'turn_id':out['turn_id'],'feature_id':BLOCK_IDS['H'][0]})
        self.assertEqual(len(report['cases']),6);self.assertEqual(before,digest(self.r.store.snapshot()['tables']))
        self.assertEqual(report['external_requests'],0);self.assertGreater(report['intervention']['max_abs_delta'],0.)
    def test_diagnostics_scope_and_legacy_rollback_keeps_messages(self):
        self.r.configure({'pmm28':{'mode':'active'}});out=self.turn();sid=out['trace']['session_id']
        old=self.r.store.history(sid);self.r.configure({'pmm28':{'mode':'legacy'}})
        self.assertEqual(old,self.r.store.history(sid));self.assertNotIn('pmm28',self.turn(sid=sid)['trace'])
    def test_unverified_longterm_commit_setting_still_cannot_write(self):
        self.r.configure({'pmm28':{'mode':'active','long_term_mode':'validated_commit'}})
        before=digest(self.r.engine.profile());co=PMMCoordinator(self.r.engine)
        with self.assertRaises(ValueError):co.longitudinal_action({'op':'commit','subject_id':self.r.engine.profile()['id'],'expected_revision':0,'proposal_id':'not-reviewed'})
        self.assertEqual(before,digest(self.r.engine.profile()))
    def test_internal_provider_initialization_failure_keeps_turn(self):
        def broken(config):raise ConnectionError('fixture')
        self.r.configure({'pmm28':{'mode':'active'}});self.r.engine.pmm_provider_factory=broken
        out=self.turn();t=out['trace']['pmm28']
        self.assertTrue(out['reply']);self.assertTrue(t['components']['neural']['executed'])
        self.assertEqual(t['components']['reasoner']['status'],'failed')
    def test_late_internal_assessment_failure_uses_original_general_role(self):
        class LaterBroken(PatchProvider):
            def complete(self,messages,*args,**kwargs):
                if '[API_PMM_PREPARE_V2]' not in messages[0]['content']:raise TimeoutError('fixture')
                return super().complete(messages,*args,**kwargs)
        self.r.configure({'pmm28':{'mode':'active'},'performance':{'mode':'full'},'deliberation':{'mode':'off'}})
        self.r.engine.pmm_provider_factory=LaterBroken
        out=self.turn();t=out['trace']['pmm28'];self.assertTrue(out['reply'])
        self.assertEqual(t['components']['reasoner']['status'],'ok')
        self.assertEqual(t['post_reasoner_failures'][0]['stage'],'action_assessment')
        self.assertFalse(t['components']['decision']['payload']['formal_contribution'])
    def test_late_review_failure_uses_deterministic_review(self):
        class ReviewBroken(PatchProvider):
            def complete(self,messages,*args,**kwargs):
                from persona.deliberation import REVIEW
                if messages[0]['content']==REVIEW:raise TimeoutError('fixture')
                return super().complete(messages,*args,**kwargs)
        self.r.configure({'pmm28':{'mode':'active'},'deliberation':{'mode':'always'}})
        profile=self.r.engine.profile();field=profile['psychology']['features']['value.self_direction_thought']
        field.update(estimate=.9,posterior_uncertainty=.1,source_type='owner_seed')
        with self.r.store.lock,self.r.store.db:self.r.store.setmeta('pmm_profile',profile)
        self.r.engine.pmm_provider_factory=ReviewBroken
        out=self.turn();t=out['trace']['pmm28'];self.assertTrue(out['reply'])
        self.assertEqual(t['post_reasoner_failures'][0]['stage'],'deliberation_review')
    def test_internal_deadline_includes_schema_repairs(self):
        from persona.api_pmm import BudgetedProvider
        p=PatchProvider(self.r.config.get()['pmm']['api']);bounded=BudgetedProvider(p,1.)
        bounded.deadline=0.
        with self.assertRaises(TimeoutError):bounded.complete([])
        self.assertEqual(p.calls,[])

class Decisions(unittest.TestCase):
    def assessment(self,action,eligible=True):
        probabilities={k:.04 for k in ('reply','unknown','clarify','disagree','decline','silence')};probabilities[action]=.8
        x=inputs();known(x,'H',0,.7)
        return {'status':'ok','payload':{'action_probabilities':probabilities,'formal_eligible':eligible,'blocks':x['blocks'],'calibration':'controlled_gate_fixture'}}
    def test_validated_signal_reaches_policy_scores_and_hard_gate_survives(self):
        # Unit injection tests policy plumbing only, NOT a publishable calibration.
        from persona.policy import choose
        from persona.psychology import empty_profile
        c=TurnContext('a','private:a','e',1.,0,turn_id='t',person_id='p')
        r=self.assessment('disagree');n=self.assessment('disagree')
        d=CoordinatedDecision().decide(c,reasoner=r,neural=n,mode='active')['payload']
        self.assertTrue(d['formal_contribution']);self.assertGreater(d['score_terms']['disagree'],0.)
        u={'semantic':{},'knowledge_need':'none','pmm28_decision':{'schema':'coordinated-policy/2.8',**d}}
        p=empty_profile('a','test');views=[{'id':'v','weight':1.,'label':'unit'}];ass=[{'id':'v','utilities':{'reply':.5,'disagree':.49}}]
        decoded={'influence':0.,'action_probabilities':{}}
        self.assertEqual(choose(u,p,views,ass,decoded,[],'event')['action'],'disagree')
        p['boundaries']=[{'id':'b','enabled':True,'hard':True,'action':'decline','keywords':['event'],'label':'test'}]
        self.assertEqual(choose(u,p,views,ass,decoded,[],'event')['action'],'decline')
    def test_disagreement_is_not_average(self):
        c=TurnContext('a','private:a','e',1.,0,turn_id='t',person_id='p')
        d=CoordinatedDecision().decide(c,reasoner=self.assessment('reply'),neural=self.assessment('decline'),mode='active')['payload']
        self.assertTrue(d['disagreement']);self.assertEqual(d['score_terms']['clarify'],.08)
        self.assertEqual(d['score_terms']['reply'],0.);self.assertEqual(d['score_terms']['decline'],0.)
    def test_ablations_reproducible_and_zero_effect_reported(self):
        x=inputs();a=ablate(initial_checkpoint('a'),'a',x);b=ablate(initial_checkpoint('a'),'a',x)
        self.assertEqual(a,b);self.assertEqual(len(a['cases']),6)
        self.assertTrue(next(r for r in a['cases'] if r['component']=='api')['no_observable_difference'])
        self.assertFalse(next(r for r in a['cases'] if r['component']=='neural')['executed_neural'])

if __name__=='__main__':unittest.main()
