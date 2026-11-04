"""v2.1 behavioral contracts. Generated semantic responses are explicit fixtures.
Numerical gradients, SQLite transactions, migrations and HTTP are real.
"""
import copy,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from persona import registry as rg,deliberation as dl,relationships as dy
from persona.psychology import empty_profile,apply_distillation,validate_profile,parse_records
from persona.pmm import vector,DIM as OLD_DIM
from persona.learned_pmm import LearnedPMM
from persona.registry_pmm import RegistryPMM,DIM,MODEL_ID,checked_vector
from persona.pmm_interface import RemotePMM,execute_request,digest
from persona.pmm_service import make_server
from persona.common import Config
from persona.server import Runtime
from persona.packages import validate_pack
from persona.provider import ProviderError
from fixtures import response,TEXT

ROOT=Path(__file__).resolve().parents[1]
IDENTITY='1'*32

def evidence_profile(features=None,seed_long=True):
    p=empty_profile(IDENTITY,'测试人物');record={'id':'record-a','speaker':'目标','text':'我珍惜自主和公平，也会主动表达关怀。','context':'取舍情境','source':'imported','batch_id':'a'}
    fields=features or list(rg.ORDER)
    rows=[{'feature_id':k,'estimate':.8,'confidence':.7,'evidence':[{'record_id':record['id'],'quote':record['text']}]} for k in fields]
    p,_=apply_distillation(p,{'construct_updates':rows},[record])
    # Test known priors explicitly; one imported sentence is only a candidate now.
    if seed_long:
        from persona.traits import edit_disposition
        for k in fields:
            if k in rg.LONG_IDS:p=edit_disposition(p,{'feature_id':k,'estimate':.8,'expected_version':p['trait_profile']['version']})
    return p

class RegistryTests(unittest.TestCase):
    def test_exact_source_registry_93_fields_and_unknown_is_not_neutral(self):
        state=rg.empty_state();self.assertEqual(rg.N,93);self.assertEqual(len(set(rg.ORDER)),93)
        self.assertEqual([v['registered'] for v in rg.coverage(state).values()],[25,19,3,12,12,5,2,15])
        self.assertTrue(all(f['estimate'] is None for f in state['features'].values()))
        v,m=rg.pack_features(state);self.assertEqual(sum(v),0);self.assertEqual(sum(m),0)
        rg.validate_state(state,[])
    def test_all_fields_can_be_distilled_validated_and_packed_with_evidence(self):
        p=evidence_profile();validate_profile(p);v,m=rg.pack_features(p['psychology']);self.assertEqual(sum(m),93)
        self.assertEqual(len(p['psychology']['observations']),93+len(rg.LONG_IDS));self.assertTrue(all(f['evidence_count']==1 for f in p['psychology']['features'].values()))
        self.assertEqual(v[rg.ORDER.index('affect.vad.valence')],.9)
    def test_forged_context_quote_and_unregistered_fields_are_rejected(self):
        p=empty_profile(IDENTITY,'甲');rec=parse_records('乙：我喜欢诚实\n甲：嗯')[1:]
        out,report=apply_distillation(p,{'construct_updates':[{'feature_id':'hexaco.h.sincerity','estimate':1,'confidence':.7,'evidence':[{'record_id':rec[0]['id'],'quote':'我喜欢诚实'}]},{'feature_id':'invented','estimate':1,'confidence':.7,'evidence':[]}]},rec)
        self.assertEqual(report['rejected'],2);self.assertTrue(all(f['estimate'] is None for f in out['psychology']['features'].values()))
    def test_conflicts_remain_as_observations_and_uncertainty(self):
        p=evidence_profile(['hexaco.h.sincerity'],seed_long=False);r={'id':'record-b','speaker':'目标','text':'相反的表述','context':'另一个场景','source':'imported'}
        p,_=apply_distillation(p,{'construct_updates':[{'feature_id':'hexaco.h.sincerity','estimate':.1,'confidence':.7,'evidence':[{'record_id':r['id'],'quote':r['text']}]}]},[r])
        f=p['psychology']['features']['hexaco.h.sincerity'];self.assertIsNone(f['estimate']);self.assertEqual(f['evidence_count'],0);self.assertEqual(len(p['psychology']['observations']),2);self.assertEqual({o['estimate'] for o in p['psychology']['observations']},{.8,.1})
    def test_generated_response_cannot_create_stable_hexaco_or_values(self):
        p=empty_profile(IDENTITY,'甲');r={'id':'gen','speaker':IDENTITY,'text':'我重视公平','context':'','source':'generated'}
        p,report=apply_distillation(p,{'construct_updates':[{'feature_id':'hexaco.h.fairness','estimate':1,'confidence':1,'evidence':[{'record_id':'gen','quote':r['text']}]}]},[r],source='generated')
        self.assertEqual(report['rejected'],1);self.assertIsNone(p['psychology']['features']['hexaco.h.fairness']['estimate'])
    def test_registry_reorder_hash_and_missing_record_fail_closed(self):
        original=evidence_profile()
        for change in ('order','hash','source'):
            p=copy.deepcopy(original)
            if change=='order':p['psychology']['feature_order'].reverse()
            elif change=='hash':p['psychology']['registry_hash']='wrong'
            else:p['psychology']['features'][rg.ORDER[0]]['evidence_ids']=['missing']
            with self.subTest(change=change),self.assertRaises(ValueError):validate_profile(p)
    def test_affect_uncertainty_decays_without_inventing_a_baseline(self):
        p=evidence_profile(['affect.vad.dominance']);before=p['psychology'];f=before['features']['affect.vad.dominance']
        view=rg.state_view(before,at=f['updated_at']+86400);after=view['features']['affect.vad.dominance']
        self.assertEqual(after['estimate'],f['estimate']);self.assertGreater(after['posterior_uncertainty'],f['posterior_uncertainty']);self.assertTrue(after['stale']);self.assertEqual(sum(rg.pack_features(view)[1]),0)
    def test_old_five_factor_profile_preserved_without_fake_facet_imputation(self):
        p=empty_profile(IDENTITY,'甲');p.pop('psychology');p['traits']['extraversion']['value']=.9
        migrated=rg.ensure_profile(p);self.assertEqual(migrated['traits'],p['traits']);self.assertTrue(all(f['estimate'] is None for f in migrated['psychology']['features'].values()));self.assertEqual(migrated['id'],IDENTITY)

class NumericTests(unittest.TestCase):
    def model(self):
        m=RegistryPMM(identity=IDENTITY)
        for i in range(25):
            x=rg.extend_vector(vector('场景'+str(i)));t=[None]*93;t[0]=.8;t[78]=.2
            pref=[0.] *94;pref[1]=1.
            m.add('test-'+str(i),x,psychology_target=t,view_preference=pref,style=[.1]*8,action='reply')
        return m
    def test_migration_preserves_old_trained_decoding_for_unknown_extensions(self):
        old=LearnedPMM(identity=IDENTITY)
        for i in range(10):old.add('old-'+str(i),vector('消息'+str(i)),style=[.3]*8,action='reply')
        old.fit(5);saved=copy.deepcopy(old.export());new=RegistryPMM(saved,IDENTITY)
        x=vector('检查');a=old.decode(x);b=new.decode(rg.extend_vector(x))
        for k in ('state','style','action_probabilities','personality','linguistic','perspective_offsets'):
            self.assertEqual(a[k],b[k],k)
        np.testing.assert_array_equal(new.E[:,:184],old.E);self.assertTrue(np.all(new.E[:,184:]==0));self.assertEqual(saved,old.export());self.assertEqual(new.migration['source_sha256'],digest(saved))
    def test_masked_gradients_train_known_heads_and_leave_unknown_heads_unchanged(self):
        m=self.model();core=m.core_hash();before=m.evaluate([s for s in m.samples if not s['heldout']]);unknown=m.adapter['F'][1].copy();m.fit(30)
        self.assertEqual(core,m.core_hash());self.assertLess(m.metrics['train']['psychology_masked_mse'],before['psychology_masked_mse']);self.assertLess(m.metrics['train']['dynamic_view_cross_entropy'],before['dynamic_view_cross_entropy']);np.testing.assert_array_equal(unknown,m.adapter['F'][1])
        d=m.decode(rg.extend_vector(vector('场景')));self.assertIsNone(d['psychology_prediction'][rg.ORDER[1]]);self.assertIsNotNone(d['psychology_prediction'][rg.ORDER[0]])
        self.assertEqual(m.fork().export(),m.export())
    def test_heldout_canonical_labels_do_not_change_any_gradient(self):
        a=self.model();b=a.fork();changed=0
        for s in b.samples:
            if s['heldout']:s['psychology_target']=[1.] *93;s['view_preference']=[1.]+[0.]*93;changed+=1
        self.assertGreater(changed,0);a.fit(8);b.fit(8);self.assertEqual(a.core(),b.core());self.assertEqual(a.export_adapter(),b.export_adapter())
    def test_core_training_does_not_update_personal_delta(self):
        m=self.model();adapter=copy.deepcopy(m.export_adapter());old=m.core_hash();m.fit(8,target='core')
        self.assertNotEqual(old,m.core_hash());self.assertEqual(adapter['parameters'],m.export_adapter()['parameters']);self.assertEqual(adapter['feature_steps'],m.export_adapter()['feature_steps'])
    def test_input_shape_mask_unknown_payload_and_checkpoint_order_are_checked(self):
        for x in (np.zeros(184),np.ones(370),np.r_[np.zeros(184),np.ones(93),np.zeros(93)],np.r_[np.zeros(277),np.ones(92),.3]):
            if len(x)==370 and np.all(x==1):continue  # known ones are valid
            with self.assertRaises(ValueError):checked_vector(x)
        m=self.model();p=m.export();p['registry_contract']['feature_order'].reverse()
        with self.assertRaises(ValueError):RegistryPMM(p,IDENTITY)
    def test_full_registry_input_affects_learned_response_and_reconstruction_is_masked(self):
        m=RegistryPMM(identity=IDENTITY);state=evidence_profile(['style.directness'])['psychology'];known=rg.extend_vector(vector('same'),state);unknown=rg.extend_vector(vector('same'))
        for i in range(24):m.add('conditional-'+str(i),known if i%2 else unknown,action='decline' if i%2 else 'reply')
        core=m.core_hash();m.fit(150,target='adapter');self.assertEqual(core,m.core_hash());a=m.decode(known);b=m.decode(unknown)
        self.assertGreater(abs(a['action_probabilities']['decline']-b['action_probabilities']['decline']),.01)

class RichFixture:
    calls=[];conflict=False;request_more=False;fail_review=False
    def __init__(self,c):self.config=c
    def complete(self,messages,structured=False):
        stage=messages[0]['content'].split(']')[0]+']';ctx=json.loads(messages[-1]['content']) if structured else None
        type(self).calls.append((self.config['model'],stage,copy.deepcopy(ctx)))
        out=response(messages,structured)
        if stage=='[UNDERSTAND_V3]' and self.conflict:out['semantic'].update(value_conflict=.9,complexity=.8,ambiguity=.7)
        if stage=='[API_PMM_PREPARE_V2]':out['self_event_updates']=[{'feature_id':'affect.vad.dominance','estimate':.7,'confidence':.5,'evidence':[{'record_id':'current_event','quote':ctx['input']}]}]
        if stage=='[PMM_REVIEW_V21]':
            if self.fail_review:return {'weights':[{'id':'forged','weight':1}]}
            if self.request_more:out['retrieval_queries']=['自主']
        if stage=='[FEEDBACK_V3]':
            u=ctx['user_record'];out['interlocutor']['construct_updates']=[{'feature_id':'style.humor','estimate':.9,'confidence':.5,'evidence':[{'record_id':u['id'],'quote':u['text']}]}]
            out['relationship_updates']=[{'field':'humor_tolerance','estimate':.9,'quote':u['text']}]
        return out

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.r=Runtime(self.tmp.name,ROOT);self.r.configure({'model':'general','pmm':{'api':{'model':'psych'}}});self.bind();self.sid=self.r.store.session()
    def bind(self):
        self.r.engine.provider_factory=RichFixture;self.r.engine.pmm_provider_factory=RichFixture
        RichFixture.calls=[];RichFixture.conflict=False;RichFixture.request_more=False;RichFixture.fail_review=False
    def tearDown(self):
        self.r.bridge.stop.set()
        if self.r.bridge.thread.is_alive():self.r.bridge.thread.join(3)
        self.r.close_pmm();self.r.store.close();self.tmp.cleanup()
    def seed(self,fields=None):
        p=evidence_profile(fields);p['id']=self.r.engine.profile()['id'];p['trait_profile']['persona_id']=p['id'];self.r.store.setmeta('pmm_profile',p)
    def turn(self,text=TEXT,sid=None):return self.r.engine.turn(sid or self.sid,text)
    def test_off_keeps_pmm_full_fields_memory_and_feedback_without_multi_calls(self):
        self.r.configure({'deliberation':{'mode':'off'}});self.seed();r=self.turn();stages=[s for _,s,_ in RichFixture.calls]
        self.assertNotIn('[ASSESS_V21]',stages);self.assertNotIn('[PMM_REVIEW_V21]',stages);self.assertIn('[API_PMM_PREPARE_V2]',stages);self.assertIn('[DECIDE_V21]',stages);self.assertIn('[FEEDBACK_V3]',stages)
        self.assertFalse(r['trace']['deliberation']['multi_view']);self.assertEqual(len(self.r.store.history(self.sid)),2);self.assertTrue(self.r.store.memories());self.assertEqual(len(self.r.engine.profile()['psychology']['features']),93)
        self.assertTrue(any(model=='psych' and stage=='[DECIDE_V21]' for model,stage,_ in RichFixture.calls))
    def test_auto_records_trigger_scores_and_only_runs_on_substantive_conflict(self):
        self.seed();a=self.turn();self.assertFalse(a['trace']['deliberation']['activated']);RichFixture.conflict=True;b=self.turn()
        self.assertTrue(b['trace']['deliberation']['multi_view']);self.assertEqual(b['trace']['deliberation']['scores']['value_conflict'],.9);self.assertEqual(b['trace']['deliberation']['rule_version'],dl.RULE_VERSION)
    def test_always_dynamic_candidate_counts_and_bidirectional_logs(self):
        self.seed();self.r.configure({'deliberation':{'mode':'always','max_perspectives':4,'max_rounds':2}});RichFixture.request_more=True;r=self.turn();trace=r['trace']['deliberation']
        self.assertTrue(trace['multi_view']);self.assertEqual(len(trace['rounds']),2);self.assertEqual(len(r['trace']['projections']),4)
        self.assertTrue(all(v['source_features'] and v['evidence_ids'] for v in trace['rounds'][0]['candidates'][1:]));self.assertEqual(sum(s=='[PMM_REVIEW_V21]' for _,s,_ in RichFixture.calls),2)
        self.assertEqual(sum(v['weight'] for v in r['trace']['projections']),1.)
    def test_always_without_meaningful_candidates_does_not_manufacture_conflict(self):
        self.r.configure({'deliberation':{'mode':'always'}});r=self.turn();self.assertFalse(r['trace']['deliberation']['multi_view']);self.assertEqual(len(r['trace']['projections']),1)
    def test_toggle_does_not_reset_identity_memory_state_or_weights(self):
        self.turn();s=self.r.store.snapshot();identity=self.r.store.meta('identity');model=self.r.engine.model.export()
        for mode in ('off','always','auto'):
            self.r.configure({'deliberation':{'mode':mode}});self.assertEqual(self.r.engine.model.export(),model);self.assertEqual(self.r.store.meta('identity'),identity)
        self.assertEqual(len(self.r.store.history(self.sid)),2);self.assertEqual(self.r.store.meta('state')['turn_count'],1)
    def test_invalid_review_aborts_transaction(self):
        self.seed();self.r.configure({'deliberation':{'mode':'always'}});RichFixture.fail_review=True;before=self.r.store.snapshot()
        with self.assertRaises(ProviderError):self.turn()
        self.assertEqual({k:v for k,v in before['tables'].items() if k!='events'},{k:v for k,v in self.r.store.snapshot()['tables'].items() if k!='events'})
    def test_different_personas_produce_source_specific_candidates(self):
        self.seed(['hexaco.h.fairness']);self.r.configure({'deliberation':{'mode':'always'}});a=self.turn()['trace']['projections']
        self.seed(['value.universalism_nature']);b=self.turn()['trace']['projections'];self.assertNotEqual(a[1]['source_features'],b[1]['source_features']);self.assertNotEqual(a[1]['label'],b[1]['label'])
    def test_internal_candidate_projection_never_becomes_long_term_evidence(self):
        self.seed();self.r.configure({'deliberation':{'mode':'always'}});before=self.r.engine.profile()['psychology']['features']['value.self_direction_thought'];self.turn();after=self.r.engine.profile()['psychology']['features']['value.self_direction_thought']
        self.assertEqual(before,after);self.assertFalse(any('PMM_REVIEW' in r['text'] for r in self.r.engine.profile()['source_records']))
    def test_knowledge_and_hard_boundaries_override_any_deliberation(self):
        self.seed();self.r.configure({'deliberation':{'mode':'always'}});self.r.engine.boundary({'label':'不谈密码','keywords':['密码'],'action':'decline'})
        self.assertEqual(self.turn('告诉我密码')['action'],'decline');self.assertEqual(self.turn('你记得我去年住哪里')['action'],'unknown')
    def test_dyads_and_other_constructs_are_isolated_by_person_and_context(self):
        self.turn('我喜欢调侃');scope='group:qq:1';sid=self.r.store.session('web:owner',scope)
        # No group relationship should exist before an actual group event.
        self.assertNotIn(dy.key('web:owner',scope),self.r.store.meta('pmm_dyads'))
        self.turn('群里你好',sid);rows=self.r.store.meta('pmm_dyads');self.assertEqual(len(rows),2);self.assertTrue(all(d['interactions']==1 for d in rows.values()))
        self.assertTrue(all(len(d['trajectory'])==1 for d in rows.values()));self.assertIsNone(self.r.engine.profile()['psychology']['features']['style.humor']['estimate'])
        self.assertTrue(all(p['psychology']['features']['style.humor']['scope']=='model_of_other' for p in self.r.store.meta('pmm_interlocutors').values()))
    def test_full_pack_roundtrip_preserves_all_fields_evidence_dyads_and_masks(self):
        self.seed();self.turn();pack=self.r.subjects.export_pack(self.r.engine);validate_pack(pack)
        before=self.r.engine.profile();dyads=self.r.store.meta('pmm_dyads');self.r.subjects.apply_current(self.r.engine,pack)
        self.assertEqual(before,self.r.engine.profile());self.assertEqual(dyads,self.r.store.meta('pmm_dyads'));self.assertEqual(pack['psychology_contract'],rg.CONTRACT)
    def test_legacy_pack_migrates_without_deleting_evidence_or_weights(self):
        pack=self.r.subjects.export_pack(self.r.engine);pack['format']='persona-package/2.0';pack.pop('psychology_contract');pack['profile'].pop('psychology');old=digest(pack['learning']['checkpoint']);meta,_,_=validate_pack(pack)
        self.assertEqual(digest(meta['pmm_checkpoint']),old);self.assertEqual(meta['pmm_profile']['psychology']['schema_version'],'2.1.0')
    def test_learned_mode_consumes_full_registry_and_human_dynamic_view_labels(self):
        self.seed();self.r.configure({'pmm':{'mode':'learned'},'deliberation':{'mode':'always'}});r=self.turn();self.assertEqual(len(r['trace']['training_x']),370)
        self.r.engine.feedback(r['turn_id'],'helpful',perspective_target='v1');self.assertTrue(any(s.get('view_preference') is not None for s in self.r.engine.model.samples));self.assertEqual(self.r.engine.model.info()['model_id'],MODEL_ID)
    def test_invalid_registry_pack_is_atomic(self):
        pack=self.r.subjects.export_pack(self.r.engine);pack['psychology_contract']['feature_order'].reverse();before=self.r.store.snapshot()
        with self.assertRaises(ValueError):self.r.subjects.apply_current(self.r.engine,pack)
        self.assertEqual(before['tables'],self.r.store.snapshot()['tables'])
    def test_template_drops_private_construct_evidence_and_dyads(self):
        self.turn();pack=self.r.subjects.export_pack(self.r.engine,'template');validate_profile(pack['profile'])
        self.assertNotIn('dyads',pack);self.assertEqual(pack['profile']['psychology']['evidence_records'],[]);self.assertTrue(all(f['estimate'] is None for f in pack['profile']['psychology']['features'].values()))

    def test_api_and_learned_all_modes_use_real_control_flow(self):
        self.seed()
        for engine in ('api','learned'):
            self.r.configure({'pmm':{'mode':engine},'online_learning':False})
            for mode in ('off','auto','always'):
                self.r.configure({'deliberation':{'mode':mode,'enabled':True}});RichFixture.calls=[];RichFixture.conflict=False
                out=self.turn();stages=[s for _,s,_ in RichFixture.calls]
                self.assertEqual('[ASSESS_V21]' in stages,mode=='always')
                self.assertEqual('[PMM_REVIEW_V21]' in stages,mode=='always' and engine=='api')
                self.assertEqual(out['trace']['pmm_mode'],engine)
        self.r.configure({'deliberation':{'mode':'always','enabled':False}})
        RichFixture.calls=[];out=self.turn();self.assertFalse(out['trace']['deliberation']['multi_view'])

    def test_pending_registry_contract_is_validated(self):
        self.turn();pack=self.r.subjects.export_pack(self.r.engine);pack['learning']['pending'][0]['registry_contract']['registry_hash']='bad'
        with self.assertRaises(ValueError):validate_pack(pack)

    def test_invalid_deliberation_settings_are_atomic(self):
        before=self.r.config.get()
        for change in ({'mode':'unknown'},{'enabled':0},{'max_rounds':0},{'max_perspectives':8}):
            with self.assertRaises(ValueError):self.r.configure({'deliberation':change})
            self.assertEqual(before,self.r.config.get())


class HTTPTests(unittest.TestCase):
    def test_registry_local_remote_parity_real_masked_training_and_contract_rejection(self):
        server=make_server('127.0.0.1',0,'v21-test-key-long-enough');threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            a=RegistryPMM(identity=IDENTITY);x=rg.extend_vector(vector(TEXT));target=[None]*93;target[0]=.8
            for i in range(16):a.add('h'+str(i),x,psychology_target=target)
            b=RemotePMM(a.export(),IDENTITY,{'model':MODEL_ID,'base_url':'http://127.0.0.1:'+str(server.server_port),'api_key':'v21-test-key-long-enough','timeout':10})
            self.assertTrue(b.test()['ok']);self.assertEqual(a.decode(x),b.decode(x));a.fit(8);b.fit(8);self.assertEqual(a.export(),b.export())
            before=b.export()
            def tamper(body):
                result=execute_request(body)
                if body['operation']=='decode':result['result']['registry_contract']['registry_hash']='wrong'
                return result
            with patch('persona.pmm_service.execute_request',side_effect=tamper),self.assertRaises(ProviderError):b.decode(x)
            self.assertEqual(before,b.export())
        finally:server.shutdown();server.server_close()
