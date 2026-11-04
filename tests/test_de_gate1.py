"""Gate I: dated/undated human material, independent feedback and reproducible clocks."""
import copy,json,tempfile,unittest
from pathlib import Path
from persona import pragmatics as pg,language_learning as ll,affect as af,traits as tr
from persona.psychology import parse_records,empty_profile
from persona.server import Runtime
from persona.packages import export_continuity,validate_pack
from fixtures import FixtureProvider
ROOT=Path(__file__).resolve().parents[1]

def records():
    rows=[{'id':'q','speaker':'另一人','text':'要不要一起去？','timestamp':1000}]+[{'id':str(i),'speaker':'示范者','text':v,'timestamp':1001+i} for i,v in enumerate(['行啊','我带水','也带伞','门口见'])]
    rows += [{'id':'u1','speaker':'示范者','text':'我想……还是明天吧。','timestamp':''},{'id':'u2','speaker':'另一人','text':'好'},{'id':'u3','speaker':'示范者','text':'谢谢！'}]
    return [r for r in parse_records(json.dumps([{**r,'scope':'s','conversation_id':'c'} for r in rows])) if r['speaker']=='示范者']

def observed(p,tid):return pg.observe(p,tid,{'scope':'s','person_id':'p','previous_act':'invitation'},['嗯'],[],'LOCAL_COMMITTED')
def feedback_pair():
    p=pg.empty()
    for i in ('a','b'):
        p=ll.feedback_target(observed(p,i),i,'yield_after_acknowledgement',.85,'独立评价：接受邀请后就让轮',pg.LABELS)
    return p

def apply(p,gate=lambda s,p:{'allowed':True,'reasons':[]}):
    c=ll.candidates(p)[0];return ll.review(p,{'action':'apply','expected_version':p['version'],'candidate_id':c['id'],'evidence_digest':c['evidence_digest'],'note':'检查原始事件与情境'},gate)

def evolve(p=None,data=None,at=1000):
    p=p or tr.ensure_traits(empty_profile('a'*32,'实验'));data=data or af.empty(p['id'],900)
    return af.evaluate(data,tr.snapshot(p),{'semantic':{'hostility':.8,'social':.8,'urgency':.5,'agency':.6,'goal_congruence':.2,'certainty':1}},
        {'id':'in1','text':'这件事让我有些为难。','scope':'s','person':'p','source_event_ids':['source-message']},{'trust':.5},[],at=at)

class Language(unittest.TestCase):
    def test_two_paths_no_invented_intervals(self):
        p=pg.rebuild(None,records());pg.validate(p);s=pg.summary(p,'s');t=s['text_style'];self.assertEqual(s['bubble_distribution'],{'4':1});self.assertEqual(p['demonstrations'][0]['gaps_seconds'],[1.,1.,1.]);self.assertEqual(t['untimed_events'],2);self.assertEqual(t['effective_events'],3);self.assertGreater(t['mean_sentence_characters'],0);self.assertGreater(t['ellipsis_rate'],0)
        for x in p['lexical_demonstrations']:
            self.assertTrue(x['source_event_ids']);self.assertTrue(x['content_sha256']);self.assertEqual(x['authorization_scope'],'s');self.assertNotIn('gaps_seconds',x)
    def test_unlinked_dates_not_a_burst_naive_date_untimed(self):
        self.assertIsNone(pg.timestamp('2026-10-30T22:00:00'));self.assertIsNotNone(pg.timestamp('2026-10-30T22:00:00+08:00'))
        rs=records()[:2];rs[1].pop('previous_record_id');rs[1].pop('context_record_id');p=pg.rebuild(None,rs);self.assertEqual(pg.summary(p)['bubble_distribution'],{'1':2})
    def test_source_scope_and_reimport(self):
        rs=records();p=pg.rebuild(None,rs+[{**rs[0],'id':'generated','source':'generated'},{**rs[1],'id':'denied','language_authorized':False}]);self.assertEqual(pg.rebuild(p,rs+rs),p);self.assertEqual(pg.summary(p,'different')['text_style']['effective_events'],0)
        self.assertEqual(parse_records('[{"role":"assistant","content":"机器说的话"}]')[0]['source'],'generated')
    def test_no_owner_evidence_means_no_target(self):
        p=pg.feedback(observed(pg.empty(),'a'),'a','unhelpful','有点奇怪');self.assertEqual(ll.candidates(p),[]);self.assertTrue(ll.unusable_feedback(p));self.assertFalse(ll.applied(p))
    def test_review_threshold_and_idempotence(self):
        p=ll.feedback_target(observed(pg.empty(),'a'),'a','yield_after_acknowledgement',.85,'合成评价',pg.LABELS)
        same,result=apply(p);self.assertFalse(result['ok']);self.assertEqual(same,p);self.assertIn('insufficient_independent_events',result['reasons'])
        p=feedback_pair();again=ll.feedback_target(p,'a','yield_after_acknowledgement',.85,'独立评价：接受邀请后就让轮',pg.LABELS);self.assertEqual(again,p)
        new,r=apply(p);self.assertTrue(r['ok']);self.assertIsNone(r['changed_fields'][0]['before']);self.assertEqual(r['changed_fields'][0]['after'],.85);self.assertEqual(new['version'],p['version']+1);self.assertEqual(len(ll.applied(new,'s','invitation')),1);self.assertFalse(ll.applied(new,'other','invitation'));self.assertEqual(apply(new)[0],new)
    def test_changed_evidence_or_disabled_policy_blocks_application(self):
        p,r=apply(feedback_pair());p=ll.feedback_target(p,'a','yield_after_acknowledgement',.1,'反例',pg.LABELS);self.assertFalse(ll.applied(p));self.assertIn('conflicting_evidence_requires_more_review',apply(p)[1]['reasons'])
        p=feedback_pair();self.assertEqual(apply(p,lambda s,p:{'allowed':False,'reasons':['scope_not_authorized']})[0],p)
    def test_repeated_label_same_episode_does_not_reach_threshold(self):
        p=pg.rebuild(None,records());e=p['demonstrations'][0]['id']
        for i in range(4):p=pg.annotate(p,e,'burst_propensity',1.,'四条是同一事件')
        self.assertEqual(ll.candidates(p)[0]['effective_events'],1);self.assertFalse(apply(p)[1]['ok']);u=next(r for r in p['lexical_demonstrations'] if r['at'] is None)
        with self.assertRaises(ValueError):pg.annotate(p,u['id'],'burst_propensity',1.,'不可推断')

class Dynamics(unittest.TestCase):
    def test_same_event_and_time_reproduce_full_state_and_record(self):
        p=tr.ensure_traits(empty_profile('a'*32,'实验'));a=af.empty(p['id'],900);one=evolve(p,a);two=evolve(p,a);self.assertEqual(one,two)
        state,trace=one;again,t=evolve(p,state,1100);self.assertEqual(state,again);self.assertTrue(t['replayed']);self.assertEqual(len(again['appraisals']),1);self.assertEqual(trace['appraisal']['clock']['elapsed_seconds'],100)
    def test_clock_only_and_rollback_do_not_make_events(self):
        p=tr.ensure_traits(empty_profile('a'*32,'实验'));a,_=evolve(p);d=af.advance(a,8100);self.assertEqual(d['appraisals'],a['appraisals']);self.assertEqual(d['trajectory'],a['trajectory']);self.assertNotEqual(d['emotion']['arousal'],a['emotion']['arousal']);self.assertEqual(af.advance(a,800)['emotion'],a['emotion'])
        self.assertNotEqual(d['mood']['valence'],a['mood']['valence']);self.assertEqual(d['emotion']['state_revision'],a['emotion']['state_revision'])
    def test_condition_sources_and_no_trait_writeback(self):
        p=tr.ensure_traits(empty_profile('a'*32,'实验'));q=tr.edit_disposition(p,{'feature_id':'hexaco.e.anxiety','estimate':.9,'expected_version':0});saved=copy.deepcopy(q);a,t=evolve(q);b,other=evolve(p);self.assertEqual(q,saved);self.assertNotEqual(t['appraisal']['reactivity']['effective'],other['appraisal']['reactivity']['effective']);src=t['appraisal']['evidence_provenance'];self.assertEqual(src['trait_inputs']['hexaco.e.anxiety']['source_type'],'owner_seed');self.assertTrue(src['trait_inputs']['erq.expressive_suppression']['fallback_used']);self.assertFalse(src['calibrated'])
    def test_runtime_permissions_independence_and_restart(self):
        with tempfile.TemporaryDirectory() as d:
            r=Runtime(d,ROOT)
            try:
                ident=r.engine.profile()['id'];before=(r.engine.profile(),r.store.meta('pmm_affect'),r.engine.model.export());p=feedback_pair()
                with r.store.lock,r.store.db:r.store.setmeta('pmm_pragmatics',p)
                c=ll.candidates(p)[0];body={'persona_id':ident,'expected_version':p['version'],'candidate_id':c['id'],'evidence_digest':c['evidence_digest'],'action':'apply','note':'检查来源'}
                self.assertTrue(r.engine.language_review('review',body)['ok']);self.assertEqual(before,(r.engine.profile(),r.store.meta('pmm_affect'),r.engine.model.export()));validate_pack(export_continuity(r.engine))
                with self.assertRaises(ValueError):r.engine.language_review('review',body)
            finally:r.close()
            r=Runtime(d,ROOT)
            try:self.assertEqual(ll.applied(r.store.meta('pmm_pragmatics'))[0]['estimate'],.85)
            finally:r.close()
