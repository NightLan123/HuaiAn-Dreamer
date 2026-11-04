"""Behavior, corruption and migration regression; all data is synthetic."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from persona import affect as af,traits as tr
from persona.registry import ORDER,N,CONTRACT,KINDS,LONG_IDS,STATE_IDS,APPRAISAL_IDS,REGULATION_IDS,empty_state,update_state,validate_state,digest,pack_features
from persona.psychology import empty_profile,apply_distillation,validate_profile,profile_condition
from persona.registry_pmm import RegistryPMM,DIM,target_batch,grouped_error
from persona.server import Runtime
from persona.packages import export_continuity,validate_pack
from tests.fixtures import FixtureProvider,response

ROOT=Path(__file__).resolve().parents[1]
IDENTITY='a'*32

def persona():return tr.ensure_traits(empty_profile(IDENTITY,'合成主体'))
def seed(p,k,v):return tr.edit_disposition(p,{'feature_id':k,'estimate':v,'expected_version':p['trait_profile']['version'],'timeframe':'generally' if k.startswith('panas.') else 'habitual'})
def event(i=0,scope='private:web:owner'):return {'id':str(i),'text':'合成的争执事件','person':'other','scope':scope}
def understanding(hostility=1.):return {'semantic':{'hostility':hostility,'goal_congruence':.2 if hostility else .8,'social':.8,'agency':.4,'certainty':.8,'urgency':.5,'novelty':.2,'value_conflict':.5}}
def evolve(p=None,at=1000,data=None,i=0):
    p=p or persona();return af.evaluate(data or af.empty(p['id'],at),tr.snapshot(p),understanding(),event(i),{'trust':.3},[],at=at)

class TypingAndTraitTests(unittest.TestCase):
    def test_old_contract_and_column_order_unchanged(self):
        self.assertEqual(N,93);self.assertEqual(CONTRACT['registry_hash'],'45f01f24d7735c169b618ccaf6c7c5f3cca4e42af15ff02212fc5f91165a7894')
        self.assertEqual(len(LONG_IDS),61);self.assertEqual(len(STATE_IDS),15);self.assertEqual(len(APPRAISAL_IDS),12);self.assertEqual(len(REGULATION_IDS),5)
    def test_new_habits_separate_from_93_encoder(self):
        self.assertEqual(len(tr.DISPOSITIONS),7);self.assertTrue(set(tr.DISPOSITIONS).isdisjoint(ORDER));self.assertTrue(all(f['estimate'] is None for f in persona()['trait_profile']['dispositions'].values()))
    def test_generated_or_current_emotion_never_becomes_trait(self):
        p=persona();before=tr.snapshot(p)
        r={'id':'g','speaker':IDENTITY,'text':'我很生气','context':'','source':'generated'}
        p,_=apply_distillation(p,{'construct_updates':[{'feature_id':'hexaco.e.anxiety','estimate':1.,'confidence':.7,'evidence':[{'record_id':'g','quote':r['text']}]}]},[r],'generated')
        self.assertEqual(before,tr.snapshot(p))
    def test_one_import_stays_candidate_without_changing_known_mask(self):
        p=persona();r={'id':'r','speaker':'target','text':'我通常这样','context':'','source':'imported'}
        row={'feature_id':'hexaco.e.anxiety','estimate':.9,'confidence':.7,'evidence':[{'record_id':'r','quote':r['text']}]}
        p,_=apply_distillation(p,{'construct_updates':[row]},[r]);self.assertIsNone(p['psychology']['features'][row['feature_id']]['estimate'])
        self.assertEqual(p['psychology']['observations'][-1]['status'],'candidate');validate_profile(p)
    def evidence_profile(self,contradiction=False):
        p=persona()
        for i in range(3):
            r={'id':f'r{i}','speaker':'target','text':f'合成稳定倾向{i}','context':'','source':'imported','event_id':f'e{i}','batch_id':f'b{i}','scope':f'context:{i%2}','timestamp':100000+i*86400}
            row={'feature_id':'hexaco.e.anxiety','estimate':.1 if contradiction and i==2 else .8,'confidence':.7,'evidence':[{'record_id':r['id'],'quote':r['text']}]}
            p,_=apply_distillation(p,{'construct_updates':[row]},[r])
        return p
    def test_separate_promotion_cross_context_time_and_replay(self):
        p=self.evidence_profile();unchanged,r=tr.review(p,False);self.assertEqual(p,unchanged);self.assertEqual(r['promoted'],0)
        p,r=tr.review(p,True);self.assertEqual(r['promoted'],1);self.assertEqual(p['trait_profile']['version'],1);self.assertAlmostEqual(p['psychology']['features']['hexaco.e.anxiety']['estimate'],.8)
        again,r=tr.review(p,True);self.assertEqual(r['promoted'],0);self.assertEqual(p,again);validate_profile(p)
    def test_counterevidence_blocks_promotion(self):
        p,r=tr.review(self.evidence_profile(True),True);self.assertEqual(r['promoted'],0);self.assertTrue(any('反例' in x for x in r['candidates'][0]['reasons']))
    def test_owner_setting_cannot_be_overwritten_by_imported_evidence(self):
        p=self.evidence_profile();p=seed(p,'hexaco.e.anxiety',.2);p,r=tr.review(p,True);self.assertEqual(r['promoted'],0);self.assertEqual(p['psychology']['features']['hexaco.e.anxiety']['estimate'],.2)
    def test_same_event_many_quotes_not_independent(self):
        p=self.evidence_profile()
        for r in p['source_records']+p['psychology']['evidence_records']:r.update(scope='one',event_id='one',batch_id='one')
        _,report=tr.review(p,True);self.assertEqual(report['promoted'],0)
    def test_future_timestamps_cannot_satisfy_long_term_evidence(self):
        p=self.evidence_profile()
        for r in p['source_records']+p['psychology']['evidence_records']:r['timestamp']=1e12
        _,report=tr.review(p,True);self.assertEqual(report['promoted'],0)
    def test_cleared_owner_settings_are_not_repromoted_as_observations(self):
        p=persona()
        for v in (.7,.8,.9,None):p=seed(p,'hexaco.e.anxiety',v)
        p,report=tr.review(p,True);self.assertEqual(report['promoted'],0);self.assertFalse(report['candidates'])
    def test_unknown_restore_and_stale_owner_edit(self):
        p=seed(persona(),'erq.expressive_suppression',.8);old=p['trait_profile']['version']
        with self.assertRaises(ValueError):tr.edit_disposition(p,{'feature_id':'erq.expressive_suppression','estimate':.2,'expected_version':old-1})
        p=seed(p,'erq.expressive_suppression',None);self.assertIsNone(p['trait_profile']['dispositions']['erq.expressive_suppression']['estimate'])
    def test_panas_requires_general_timeframe(self):
        with self.assertRaises(ValueError):tr.edit_disposition(persona(),{'feature_id':'panas.positive_affect','estimate':.8,'expected_version':0,'timeframe':'right_now'})
        p=seed(persona(),'panas.positive_affect',.8);self.assertEqual(p['trait_profile']['dispositions']['panas.positive_affect']['source_type'],'owner_seed')
    def test_questionnaire_metadata_cannot_be_faked_by_tag_alone(self):
        with self.assertRaises(ValueError):tr.edit_disposition(persona(),{'feature_id':'erq.cognitive_reappraisal','estimate':.8,'expected_version':0,'source_type':'questionnaire'})
    def test_formal_measurement_keeps_instrument_version_frame(self):
        m={'instrument':'ERQ','version':'authorized_fixture','scoring_method':'external documented scoring','normalization':'fixture documented 0..1 conversion','timeframe':'habitual','respondent':'fixture human','respondent_type':'self_report','authorized':True}
        p=tr.edit_disposition(persona(),{'feature_id':'erq.cognitive_reappraisal','estimate':.8,'expected_version':0,'source_type':'questionnaire','measurement':m})
        self.assertEqual(p['trait_profile']['dispositions']['erq.cognitive_reappraisal']['measurement'],m);validate_profile(p)
    def test_legacy_big_five_and_ten_values_read_only(self):
        p=persona();before=copy.deepcopy(p['traits']);r={'id':'old','text':'我喜欢热闹','speaker':'target','context':'','source':'imported'}
        p,_=apply_distillation(p,{'observations':[{'domain':'traits','key':'extraversion','value':1,'confidence':1,'evidence':[{'record_id':'old','quote':r['text']}]}]},[r]);self.assertEqual(p['traits'],before)
        condition=profile_condition(p);self.assertNotIn('traits',condition);self.assertNotIn('values',condition)
    def test_historical_appraisal_and_operation_are_not_live_traits(self):
        p=persona();r={'id':'x','text':'事件','speaker':'target','context':''}
        for k in (APPRAISAL_IDS[0],REGULATION_IDS[0]):p['psychology'],_=update_state(p['psychology'],[{'feature_id':k,'estimate':.8,'confidence':.5,'evidence':[{'record_id':'x','quote':'事件'}]}],[r])
        self.assertEqual(profile_condition(p)['psychology']['known'],{})

class AffectDynamicsTests(unittest.TestCase):
    def test_ten_angry_events_raise_state_leave_traits_and_values_unchanged(self):
        p=seed(seed(persona(),'hexaco.e.anxiety',.8),'beq.negative_expressivity',.7);prior=copy.deepcopy(p);a=af.empty(p['id'],1000)
        for i in range(10):a,t=evolve(p,1000+i*10,a,i)
        self.assertGreater(a['emotion']['categorical_activations']['anger'],.5);self.assertEqual(p,prior);self.assertEqual(t['trait_snapshot'],tr.snapshot(prior))
    def test_two_personalities_two_emotions_change_appraisal_expression(self):
        a=seed(seed(persona(),'hexaco.e.anxiety',.1),'beq.negative_expressivity',.1)
        b=seed(seed(persona(),'hexaco.e.anxiety',.9),'beq.negative_expressivity',.9)
        results=[]
        for p in (a,b):
            for hostility in (0,1):
                affect,t=af.evaluate(af.empty(p['id'],1000),tr.snapshot(p),understanding(hostility),event(),{'trust':.3},[],at=1000)
                expression=af.expression_plan(tr.snapshot(p),affect,{'action':'reply'},{});results.append((t['appraisal']['threat_estimate'],affect['emotion']['valence'],expression['intensity']))
        self.assertNotEqual(results[1][0],results[3][0]);self.assertNotEqual(results[1][2],results[3][2]);self.assertNotEqual(results[0][1],results[1][1]);self.assertEqual(a['trait_profile']['version'],2)
    def test_suppression_reduces_expression_not_internal_negative_emotion(self):
        p=seed(persona(),'erq.expressive_suppression',0.);q=seed(persona(),'erq.expressive_suppression',1.)
        a,_=evolve(p);b,t=evolve(q)
        self.assertEqual(a['emotion']['valence'],b['emotion']['valence']);self.assertEqual(a['emotion']['stress'],b['emotion']['stress'])
        self.assertEqual(t['regulation_action']['strategy'],'expressive_suppression')
        ea=af.expression_plan(tr.snapshot(p),a,{'action':'reply'},{});eb=af.expression_plan(tr.snapshot(q),b,{'action':'reply'},{});self.assertLess(eb['intensity'],ea['intensity'])
    def test_reappraisal_changes_internal_state_only_when_executed(self):
        p=seed(persona(),'erq.cognitive_reappraisal',1.);a,t=evolve(p)
        self.assertEqual(t['regulation_action']['strategy'],'cognitive_reappraisal');self.assertGreater(t['regulation_action']['internal_effect'],0)
    def test_ten_seconds_vs_five_hours_and_polling_semigroup(self):
        a,_=evolve();short=af.advance(a,1010);long=af.advance(a,19000)
        self.assertGreater(abs(short['emotion']['valence']),abs(long['emotion']['valence']))
        split=af.advance(af.advance(a,8000),19000)
        for k in ('valence','arousal'):self.assertAlmostEqual(split['mood'][k],long['mood'][k],places=12)
        self.assertEqual(long['emotion']['state_revision'],a['emotion']['state_revision'])
    def test_same_timestamp_many_events_does_not_per_event_smooth_mood(self):
        a,_=evolve();m=copy.deepcopy(a['mood'])
        for i in range(10):a,_=evolve(at=1000,data=a,i=i+1)
        self.assertEqual(a['mood'],m)
    def test_unknown_dominance_and_labels_are_not_filled_with_half(self):
        a=af.empty(IDENTITY,1000);b=af.advance(a,19000)
        self.assertIsNone(b['emotion']['dominance']);self.assertTrue(all(v is None for v in b['emotion']['categorical_activations'].values()));self.assertIsNone(b['mood']['valence'])
    def test_different_labels_have_different_lifetimes(self):
        a,_=evolve();a['emotion']['categorical_activations'].update(surprise=1.,sadness=1.)
        b=af.advance(a,4600);self.assertLess(b['emotion']['categorical_activations']['surprise'],b['emotion']['categorical_activations']['sadness'])
    def test_wrong_subject_and_trait_write_in_proposal_rejected(self):
        p={'schema':af.SCHEMA,'subject':'model_of_other','evidence_quote':event()['text']}
        with self.assertRaises(ValueError):af.validate_proposal(p,event()['text'])
        p['subject']='agent_self';p['hexaco.e.anxiety']=1
        with self.assertRaises(ValueError):af.validate_proposal(p,event()['text'])
    def test_panas_does_not_convert_to_va_baseline(self):
        p=seed(persona(),'panas.positive_affect',1.);a,_=evolve(p);self.assertEqual(a['transition_params'],af.default_parameters(IDENTITY))
    def test_expression_requires_committed_receipt_and_is_idempotent(self):
        p=persona();a,_=evolve(p);plan=af.expression_plan(tr.snapshot(p),a,{'action':'reply'},{'scope':'test'})
        self.assertFalse(a['expressions']);b=af.commit_expression(a,plan,'turn',1000,'回复','qq_acknowledged');c=af.commit_expression(b,plan,'turn',1000,'回复','qq_acknowledged')
        self.assertEqual(b,c);self.assertEqual(len(c['expressions']),1)

class RuntimeAndTrainingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.r=Runtime(self.temp.name,ROOT);self.r.engine.provider_factory=FixtureProvider;self.r.engine.pmm_provider_factory=FixtureProvider
    def tearDown(self):self.r.close();self.temp.cleanup()
    def test_pre_action_state_and_expression_are_sent_to_language_model(self):
        calls=[]
        class Capture(FixtureProvider):
            def complete(self,messages,**kw):calls.append(copy.deepcopy(messages));return response(messages,kw.get('structured',False))
        self.r.engine.provider_factory=Capture;result=self.r.engine.turn(self.r.store.session(),'合成输入')
        realize=next(m[0]['content'] for m in calls if '[REALIZE_V3]' in m[0]['content']);condition=json.loads(realize.split('\n条件：')[1]);trace=result['trace']['trait_affect']
        self.assertEqual(condition['expression_plan']['linked_emotion_revision'],trace['emotion_revision']);self.assertEqual(condition['trait_prior']['trait_version'],trace['trait_version']);self.assertEqual(trace['expression_state']['status'],'committed')
    def test_failed_delivery_keeps_personality_and_affect_uncommitted(self):
        before=self.r.engine.affect_state(at=1000);raw=self.r.store.meta('pmm_affect');prior=self.r.engine.profile()
        def fail(_):raise RuntimeError('synthetic send failed')
        with self.assertRaises(RuntimeError):self.r.engine.turn(self.r.store.session(),'事件',delivery=fail)
        self.assertEqual(self.r.store.meta('pmm_affect'),raw);self.assertEqual(self.r.engine.profile(),prior)
    def test_qq_scope_alone_is_not_a_send_receipt(self):
        result=self.r.engine.turn(self.r.store.session('qq:123','private:qq:123'),'合成输入')
        self.assertEqual(result['trace']['trait_affect']['expression_state']['delivery'],'local_commit')
    def test_real_journal_ack_is_used_for_committed_expression(self):
        e=self.r.engine
        def deliver(payload):
            identifier=e.journal.prepare(payload['execution'],{'text':payload['reply']},payload['commit_plan'])
            e.journal.dispatch(identifier,lambda _:{'status':'ok','retcode':0,'data':{'message_id':'synthetic-receipt'}})
        result=e.turn(self.r.store.session('qq:123','private:qq:123'),'合成输入',delivery=deliver)
        self.assertEqual(result['trace']['trait_affect']['expression_state']['delivery'],'qq_acknowledged')
        self.assertEqual(e.journal.outbox(result['turn_id'])[0]['status'],'COMMITTED')
    def test_separate_promotion_produces_typed_labels_without_erasing_old_queue(self):
        p=TypingAndTraitTests().evidence_profile();p['id']=self.r.engine.profile()['id'];p['trait_profile']['persona_id']=p['id']
        x=np.zeros(DIM);pending=self.r.engine.queue_sample([],'original-pending',x,linguistic=[.2,.3,.4,.5])
        with self.r.store.lock,self.r.store.db:self.r.store.setmeta('pmm_profile',p);self.r.store.setmeta('pmm_training_records',pending)
        report=self.r.engine.review_traits(True);after=self.r.store.meta('pmm_training_records')
        self.assertEqual(report['promoted'],1);self.assertEqual(after[0],pending[0]);self.assertEqual(len(after),4)
        self.assertTrue(all(s['labels']['training_context']['target_entity']=='trait_promotion' for s in after[1:]))
    def test_full_queue_stops_promotion_before_live_changes(self):
        p=TypingAndTraitTests().evidence_profile();p['id']=self.r.engine.profile()['id'];p['trait_profile']['persona_id']=p['id']
        sample=self.r.engine.queue_sample([],'old',np.zeros(DIM),linguistic=[.2,.3,.4,.5])[0]
        pending=[{**sample,'id':f'old-{i}'} for i in range(1024)]
        with self.r.store.lock,self.r.store.db:self.r.store.setmeta('pmm_profile',p);self.r.store.setmeta('pmm_training_records',pending)
        with self.assertRaisesRegex(ValueError,'原样本全部保留'):self.r.engine.review_traits(True)
        self.assertEqual(self.r.store.meta('pmm_training_records'),pending);self.assertEqual(self.r.engine.profile(),p)
    def test_owner_habit_survives_explicit_scope_erasure_without_old_evidence(self):
        from persona.erasure import erase_scope
        self.r.engine.edit_disposition({'feature_id':'erq.cognitive_reappraisal','estimate':.8,'expected_version':0})
        self.r.store.session('qq:123','private:qq:123')
        erase_scope(self.r.engine,'private:qq:123','ERASE:private:qq:123')
        self.assertEqual(self.r.engine.profile()['trait_profile']['dispositions']['erq.cognitive_reappraisal']['estimate'],.8)
        self.assertFalse(self.r.engine.profile()['trait_profile']['disposition_observations'])
    def test_old_api_explicitly_degrades_new_api_uses_typed_contract(self):
        self.r.config.update({'pmm':{'mode':'api'}})
        old=self.r.engine.turn(self.r.store.session(),'旧协议');self.assertEqual(old['trace']['trait_affect']['provider_contract'],'legacy_prepare_v2_degraded')
        class Typed(FixtureProvider):
            def complete(self,messages,**kw):
                out=response(messages,kw.get('structured',False))
                if '[API_PMM_PREPARE_V2]' in messages[0]['content']:
                    text=json.loads(messages[-1]['content'])['input'];out['layered_affect']={'schema':af.SCHEMA,'subject':'agent_self','evidence_quote':text,'appraisal_checks':{},'emotion_proposal':{'valence':-.8,'arousal':.8,'dominance':None,'categorical_activations':{'anger':.9}},'regulation_proposal':'none'}
                return out
        self.r.engine.pmm_provider_factory=Typed;new=self.r.engine.turn(self.r.store.session(),'新协议');self.assertEqual(new['trace']['trait_affect']['provider_contract'],af.SCHEMA)
        self.assertGreater(new['trace']['trait_affect']['emotion_state']['categorical_activations']['anger'],0)
    def test_bad_layered_api_output_gets_one_visible_repair_and_no_commit(self):
        from persona.validation import ValidationFailure
        self.r.config.update({'pmm':{'mode':'api'}});calls=[];before=self.r.store.meta('pmm_affect')
        class Invalid(FixtureProvider):
            def complete(self,messages,**kw):
                original=messages[:2];out=response(original,kw.get('structured',False))
                if '[API_PMM_PREPARE_V2]' in original[0]['content']:
                    calls.append(original);out['layered_affect']={'schema':af.SCHEMA,'subject':'model_of_other','evidence_quote':'合成输入'}
                return out
        self.r.engine.pmm_provider_factory=Invalid
        with self.assertRaises(ValidationFailure) as caught:self.r.engine.turn(self.r.store.session(),'合成输入')
        self.assertEqual(len(calls),2);self.assertEqual(caught.exception.details['diagnostics']['issues'][0]['path'],'/layered_affect')
        self.assertEqual(self.r.store.meta('pmm_affect'),before)
    def test_restart_preserves_time_and_typed_state(self):
        self.r.engine.turn(self.r.store.session(),'事件');before=self.r.store.meta('pmm_affect');self.r.close();self.r=Runtime(self.temp.name,ROOT)
        self.assertEqual(before,self.r.store.meta('pmm_affect'))
    def test_continuity_pack_roundtrip_and_bad_entity_abort(self):
        self.r.engine.turn(self.r.store.session(),'事件');pack=export_continuity(self.r.engine);meta,_,_=validate_pack(pack)
        self.assertEqual(meta['pmm_affect'],pack['affect_state']);pack['affect_state']['persona_id']='b'*32
        with self.assertRaises(ValueError):validate_pack(pack)
    def test_bad_expression_or_trajectory_cannot_enter_restore(self):
        self.r.engine.turn(self.r.store.session(),'事件');pack=export_continuity(self.r.engine)
        bad=copy.deepcopy(pack);bad['affect_state']['expressions'][0]['observed_style']=[float('nan')]*8
        with self.assertRaises(ValueError):validate_pack(bad)
        bad=copy.deepcopy(pack);bad['affect_state']['trajectory'][0]['emotion']['persona_id']='b'*32
        with self.assertRaises(ValueError):validate_pack(bad)
    def test_old_pack_reimport_migrates_own_state_not_current_future(self):
        old=export_continuity(self.r.engine);old['format']='persona-package/2.1';old.pop('affect_state');old['profile'].pop('trait_profile',None)
        self.r.engine.turn(self.r.store.session(),'后续事件');self.r.subjects.apply_current(self.r.engine,old)
        self.assertEqual(self.r.store.meta('pmm_affect')['emotion']['state_revision'],0);self.assertEqual(self.r.store.meta('state')['turn_count'],0)
    def test_training_preserves_old_samples_and_reports_new_habits_unsupported(self):
        model=RegistryPMM(identity=IDENTITY);x=np.zeros(DIM);model.add('old-language',x,linguistic=[.2,.3,.4,.5],source='imported_style');model.fit(2)
        old=model.export();new=RegistryPMM(copy.deepcopy(old),IDENTITY);self.assertEqual(old,new.export())
        new.fit(1);self.assertEqual(new.samples,old['samples']);self.assertGreater(new.steps,old['steps']);self.assertEqual(new.info()['new_disposition_training_steps'],0)
    def test_event_state_training_masks_accidental_long_term_labels(self):
        target=[None]*N;target[ORDER.index('hexaco.e.anxiety')]=1.;target[ORDER.index('affect.label.anger')]=.9
        row={'psychology_target':target,'training_context':{'schema':'typed-supervision/1','target_entity':'event_state','event_id':'e','scope':'private:test','at':1000}}
        _,mask=target_batch([row]);self.assertEqual(mask[0,ORDER.index('hexaco.e.anxiety')],0);self.assertEqual(mask[0,ORDER.index('affect.label.anger')],1)
    def test_loss_groups_are_independently_normalized(self):
        prediction=np.ones((1,N));target=np.zeros((1,N));mask=np.ones((1,N));err=grouped_error(prediction,target,mask)
        self.assertAlmostEqual(err[0,[i for i,k in enumerate(ORDER) if KINDS[k]=='trait']].sum(),2.)
        self.assertAlmostEqual(err[0,[i for i,k in enumerate(ORDER) if KINDS[k]=='emotion_state']].sum(),2.)
    def test_foreign_profile_does_not_change_self(self):
        before=tr.snapshot(self.r.engine.profile());sid=self.r.store.session('other','group:qq:123');self.r.engine.turn(sid,'对方的情绪')
        self.assertEqual(before,tr.snapshot(self.r.engine.profile()));self.assertTrue(all(v['trait_profile']['scope']=='model_of_other' for v in self.r.store.meta('pmm_interlocutors').values()))

if __name__=='__main__':unittest.main()
