"""Stage I gate: actual SQLite/tasks, source identity and failure recovery."""
import copy,json,unittest
from unittest.mock import patch
from test_v212 import Base,ROOT
import test_v250 as prior_learning
import test_trait_affect_v230 as prior_traits
from persona import traits,evidence
from persona.server import Runtime
from persona.packages import export_continuity,validate_pack,apply_pack
from persona.registry import digest

class EvidenceCases(Base):
    policy=prior_learning.LearningCases.policy;records=prior_learning.LearningCases.records;body=prior_learning.LearningCases.body;create=prior_learning.LearningCases.create
    def test_automatic_then_manual_cannot_repeat_other_evidence(self):
        e=self.r.engine;self.policy('other',mode='automatic');out=self.turn();e.consolidation.run();before=copy.deepcopy(e.store.meta('pmm_interlocutors'))
        b={'source':'history','target':'other','person':'qq:123','scopes':['private:qq:123'],'intent':'apply'}
        self.assertEqual(e.learning.preview(b)['source_count'],0)
        j=self.create({**b,'reanalyse':True});e.learning.run(j['id']);self.assertEqual(before,e.store.meta('pmm_interlocutors'));self.assertTrue(e.learning.detail(j['id'])['batches'][0]['duplicate_only'])
    def test_manual_then_automatic_does_not_reapply(self):
        e=self.r.engine;self.policy('other',mode='automatic');out=self.turn()
        b={'source':'history','target':'other','person':'qq:123','scopes':['private:qq:123'],'intent':'apply'}
        j=self.create(b);e.learning.run(j['id']);before=copy.deepcopy(e.store.meta('pmm_interlocutors'));e.consolidation.run();self.assertEqual(before,e.store.meta('pmm_interlocutors'))
    def test_two_proposed_jobs_only_one_can_commit(self):
        e=self.r.engine;a=self.create();b=self.create();e.learning.run(a['id']);e.learning.run(b['id']);e.learning.control(a['id'],'approve');before=e.profile();e.learning.control(b['id'],'approve');self.assertEqual(e.profile(),before)
    def test_post_write_failure_rolls_back_sources_receipts_and_model(self):
        e=self.r.engine;j=self.create(self.body(intent='apply',train_weights=True));before=e.evidence.state();weights=e.model.export();original=e.learning._apply
        def fail(*a,**kw):original(*a,**kw);raise ValueError('after-write fault')
        with patch.object(e.learning,'_apply',side_effect=fail),self.assertRaises(ValueError):e.learning.run(j['id'])
        self.assertEqual(before,e.evidence.state());self.assertEqual(weights,e.model.export());e.learning.control(j['id'],'resume');e.learning.run(j['id']);self.assertEqual(len(e.profile()['source_records']),3)
    def test_source_mutation_and_cross_scope_alias_are_rejected(self):
        e=self.r.engine;sid=self.session();out=self.turn(sid=sid);r={'id':out['turn_id']+':u','text':out['trace']['trait_affect']['appraisal']['evidence_quote'],'scope':'private:qq:123','person':'qq:123'}
        r['text']=e.store.history(sid)[0]['content'];good=e.evidence.normalize(r)
        with self.assertRaises(ValueError):e.evidence.normalize({**r,'scope':'private:qq:other'})
        with self.assertRaises(ValueError):e.evidence.normalize({**r,'text':r['text']+'改写'})
        self.assertEqual(good['origin_event_id'],e.evidence.normalize({**r,'event_id':out['turn_id']})['origin_event_id'])
    def test_memory_reenqueue_after_completion_has_no_new_task(self):
        e=self.r.engine;self.turn();pending=e.store.meta('memory_pending');self.assertTrue(pending);e.memory_lifecycle.run(manual=True);before=e.store.memories(all_status=True)
        with e.store.lock,e.store.db:
            for p in pending:e.memory_lifecycle.enqueue(p['records'],p['scope'],p['person'],p['thread'],p['source'])
        self.assertEqual(e.store.meta('memory_pending'),[]);self.assertEqual(e.store.memories(all_status=True),before)
    def test_trace_connects_event_appraisal_memory_and_revision(self):
        e=self.r.engine;out=self.turn();e.memory_lifecycle.run(manual=True);trace=e.evidence.trace(scope='private:qq:123');self.assertTrue(trace['sources']);rows=trace['revisions'];self.assertTrue(any(r['links'].get('appraisal_id') for r in rows));self.assertTrue(any(r['links'].get('memory_ids') for r in rows));self.assertTrue(all(r['source_keys'] for r in rows))
    def test_platform_raw_and_turn_record_share_one_event(self):
        e=self.r.engine;sid=self.session();out=e.turn(sid,'我喜欢安静。',turn_context={'sources':['platform-11'],'raw_records':[{'id':'platform-11','text':'我喜欢安静。','source':'observed'}]})
        sources=e.evidence.state()['sources'].values();ids={r['record_id']:r['event_id'] for r in sources};self.assertEqual(ids['platform-11'],ids[out['turn_id']+':u'])
    def test_restart_and_continuity_preserve_receipts(self):
        e=self.r.engine;j=self.create(self.body(intent='apply'));e.learning.run(j['id']);before=e.evidence.state();pack=export_continuity(e);meta,_,_=validate_pack(pack);self.assertEqual(meta['learning_evidence'],before)
        self.r.close();self.r=Runtime(self.tmp.name,ROOT);self.fixture();self.assertEqual(self.r.engine.evidence.state(),before);self.assertEqual(self.r.engine.learning.preview(self.body())['source_count'],0)
    def test_invalid_provenance_import_is_atomic(self):
        e=self.r.engine;j=self.create(self.body(intent='apply'));e.learning.run(j['id']);pack=export_continuity(e);before=e.evidence.state();next(iter(pack['learning_evidence']['sources'].values()))['text']='伪造'
        with self.assertRaises(ValueError):validate_pack(pack)
        self.assertEqual(before,e.evidence.state())
    def test_old_metadata_migration_does_not_change_trained_state(self):
        e=self.r.engine;j=self.create(self.body(intent='apply'));e.learning.run(j['id']);before=e.profile();weights=e.model.export();e.store.setmeta('learning_evidence',None);e.evidence=evidence.Evidence(e);first=e.evidence.state();e.evidence=evidence.Evidence(e)
        self.assertEqual(e.profile(),before);self.assertEqual(e.model.export(),weights);self.assertEqual(first,e.evidence.state());self.assertEqual(e.learning.preview(self.body())['source_count'],0)

class IndependentSupport(unittest.TestCase):
    def test_duplicate_hypotheses_do_not_reweight_or_repromote(self):
        p=prior_traits.TypingAndTraitTests().evidence_profile();obs=p['psychology']['observations'];obs[0]['estimate']=.6;obs[1]['estimate']=.8;obs[2]['estimate']=.7
        expected,_=traits.review(p,True);p['psychology']['observations'] += [{**copy.deepcopy(obs[0]),'id':'repeat-'+str(i)} for i in range(20)]
        got,_=traits.review(p,True);k='hexaco.e.anxiety';self.assertEqual(expected['psychology']['features'][k]['estimate'],got['psychology']['features'][k]['estimate'])
        got['psychology']['observations'].append({**copy.deepcopy(obs[0]),'id':'new-analysis'});_,report=traits.review(got,True);self.assertEqual(report['promoted'],0)
    def test_v26_legacy_promotion_does_not_repeat_on_new_event_hash(self):
        p,_=traits.review(prior_traits.TypingAndTraitTests().evidence_profile(),True);h=p['trait_profile']['promotion_history'][0];h.pop('event_ids');h['evidence_signature']='legacy-observation-id-hash';before=copy.deepcopy(p);after,report=traits.review(p,True);self.assertEqual(report['promoted'],0);self.assertEqual(after,before)

if __name__=='__main__':unittest.main()
