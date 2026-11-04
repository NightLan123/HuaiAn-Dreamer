"""Real Engine/SQLite runs with explicitly synthetic API transport fixtures."""
import copy, json, unittest
from unittest.mock import patch
from test_v212 import Base, PatchProvider
from persona.pmm_contracts import construct_blocks, validate_blocks, BLOCK_IDS, TurnContext
from persona.pmm_coordinator import PMMCoordinator

class Contracts(Base):
    def test_unknown_is_not_imputed_and_all_blocks_present(self):
        blocks=construct_blocks(self.r.engine.profile())
        self.assertEqual([len(BLOCK_IDS[b]) for b in ('H','V','I','L','D')],[25,19,2,15,7])
        self.assertTrue(all(x is None for row in blocks.values() for x in row['values']))
        blocks['H']['values'][0]=.5
        with self.assertRaises(ValueError):validate_blocks(blocks)
    def test_context_rejects_invalid_revision_or_nan(self):
        with self.assertRaises(ValueError):TurnContext('a','private:a','event',float('nan'),0,turn_id='t',person_id='p')
        with self.assertRaises(ValueError):TurnContext('a','private:a','event',1.,-1,turn_id='t',person_id='p')
    def test_mode_and_budget_validation(self):
        for body in ({'mode':'bad'},{'long_term_mode':'auto'},{'reasoner_timeout':float('nan')}):
            with self.assertRaises(ValueError):self.r.configure({'pmm28':body})

class Coordinator(Base):
    def test_same_turn_two_paths_no_extra_reply_or_api_call(self):
        output=self.turn();trace=output['trace']['pmm28']
        self.assertIn('components',trace,trace)
        c=trace['components'];self.assertTrue(c['neural']['executed']);self.assertEqual(c['reasoner']['status'],'ok')
        self.assertEqual(c['reasoner']['provenance']['execution'],'same_turn_legacy_prepare_cache')
        for value in c.values():self.assertEqual(value['event_id'],trace['event_id'])
        self.assertEqual(len(PatchProvider.seen),4)
        self.assertEqual(len(self.r.store.history(output['trace']['session_id'])),2)
        self.assertEqual(trace['formal_state_writes'],0);self.assertEqual(trace['external_sends'],0)
        self.assertFalse(c['decision']['payload']['formal_contribution'])
        traces=PMMCoordinator(self.r.engine).traces()
        self.assertEqual(traces[0]['turn_id'],output['turn_id'])
    def test_legacy_does_not_execute_new_path(self):
        self.r.configure({'pmm28':{'mode':'legacy'}})
        with patch('persona.pmm_coordinator.PMMCoordinator.run',side_effect=AssertionError('must not run')):
            output=self.turn()
        self.assertNotIn('pmm28',output['trace'])
    def test_shadow_failure_keeps_legacy_and_no_trait_write(self):
        before=self.r.engine.profile()['trait_profile']['version']
        with patch('persona.pmm_coordinator.InternalAPIReasoner.analyze',side_effect=TimeoutError):
            output=self.turn()
        self.assertEqual(output['trace']['pmm28']['fallback'],'legacy')
        self.assertEqual(self.r.engine.profile()['trait_profile']['version'],before)
        self.assertTrue(output['reply'])
    def test_identity_and_scope_separate(self):
        a=self.turn(sid=self.session('123'))['trace']['pmm28']
        b=self.turn(sid=self.session('456'))['trace']['pmm28']
        self.assertNotEqual(a['scope'],b['scope']);self.assertNotEqual(a['person_id'],b['person_id'])
        for t in (a,b):
            r=t['components']['relationship']['payload'];self.assertEqual(r['other_id'],t['person_id'])
            self.assertEqual(r['scope'],t['scope']);self.assertEqual(r['self_id'],t['subject_id'])
        self.assertEqual(len(PMMCoordinator(self.r.engine).traces(scope=a['scope'])),1)

if __name__=='__main__':unittest.main()
