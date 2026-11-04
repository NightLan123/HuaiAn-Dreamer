"""2.5 contract, job lifecycle, scoped knowledge and additive migration regressions.
Local deterministic providers only; no claims of psychological validation.
"""
import copy, hashlib, json, threading, unittest
from unittest.mock import patch
from test_v212 import Base, PatchProvider
from persona import learning, affect, relationships
from persona.common import now
from persona.registry import CONTRACT, digest
from persona.boundaries import api_appraisal, SOCIAL_ACTIONS, resolve_api_appraisal
from persona.validation import ValidationFailure
from persona.packages import export_continuity, validate_pack
from persona.psychology import apply_distillation

class LearningCases(Base):
    def policy(self,domain=None,**changes):
        p=self.r.engine.learning.status()['policy']
        if domain:p['domains'][domain].update(changes)
        else:p.update(changes)
        return self.r.engine.learning.save_policy({'expected_version':p['version'],'policy':p})
    def records(self,n=3):
        return [{'id':'human-'+str(i),'speaker':'示范者','text':'我通常先听完，再慢慢回答。'+str(i),'context':'朋友询问 '+str(i%2),'timestamp':now()-172800+i*50000,'source':'imported','batch_id':'event-'+str(i)} for i in range(n)]
    def body(self,**kw):return {'source':'import','target':'self','scopes':['self:imported'],'records':self.records(),'intent':'review',**kw}
    def create(self,body=None):
        body=body or self.body();p=self.r.engine.learning.preview(body)
        return self.r.engine.learning.create({**body,'authorized':True,'source_digest':p['source_digest'],'policy_version':p['policy_version']})
    def test_preview_does_not_mutate_and_stale_preview_rejected(self):
        e=self.r.engine;b=self.body();before=e.store.snapshot()['tables'];p=e.learning.preview(b);self.assertEqual(p['source_count'],3);self.assertEqual(before,e.store.snapshot()['tables'])
        b['records'][0]['text']='原文变了'
        with self.assertRaises(ValueError):e.learning.create({**b,**{k:p[k] for k in ('source_digest','policy_version')},'authorized':True})
        self.assertEqual(e.learning.status()['total_jobs'],0)
    def test_review_has_no_effect_until_approved_and_duplicate_is_noop(self):
        e=self.r.engine;before=e.profile();weights=e.model.export();j=self.create();r=e.learning.run(j['id']);self.assertEqual(r['status'],'awaiting_review');self.assertEqual(before,e.profile());self.assertEqual(weights,e.model.export())
        e.learning.control(j['id'],'approve');after=e.profile();self.assertEqual(len(after['source_records']),3);self.assertEqual(weights,e.model.export());self.assertEqual(e.learning.preview(self.body())['source_count'],0)
        with self.assertRaises(ValueError):e.learning.control(j['id'],'approve')
        self.assertEqual(after,e.profile());validate_pack(export_continuity(e))
    def test_review_rollback_restores_profile_and_preserves_job_sources(self):
        e=self.r.engine;before=e.profile();j=self.create(self.body(intent='apply'));e.learning.run(j['id']);self.assertNotEqual(before,e.profile());e.learning.control(j['id'],'rollback');self.assertEqual(before,e.profile());self.assertEqual(len(e.learning.detail(j['id'])['evidence']),3);validate_pack(export_continuity(e))
    def test_rollback_refuses_newer_profile_edit(self):
        e=self.r.engine;j=self.create(self.body(intent='apply'));e.learning.run(j['id']);p=e.profile();p['revision']+=1
        with e.store.lock,e.store.db:e.store.setmeta('pmm_profile',p)
        with self.assertRaises(ValueError):e.learning.control(j['id'],'rollback')
        self.assertEqual(e.profile()['revision'],p['revision'])
    def test_budget_pause_resume_and_restart_no_duplicate(self):
        e=self.r.engine;p=learning.policy(e);p['budget'].update(batch_records=1,max_calls=1);self.policy(budget=p['budget']);j=self.create(self.body(intent='apply'));r=e.learning.run(j['id']);self.assertEqual((r['status'],r['cursor']),('budget_paused',1))
        e.learning=learning.Learning(e);e.learning.control(j['id'],'resume',{'extend_budget':True});r=e.learning.run(j['id']);self.assertEqual(r['cursor'],2)
        e.learning.control(j['id'],'resume',{'extend_budget':True});r=e.learning.run(j['id']);self.assertEqual(r['status'],'completed');self.assertEqual(len(e.profile()['source_records']),3);self.assertEqual(len({r['id'] for r in e.profile()['source_records']}),3);validate_pack(export_continuity(e))
    def test_restart_running_becomes_paused(self):
        e=self.r.engine;j=self.create();s=e.learning.state();s['jobs'][0]['status']='running';e.store.setmeta('learning_center',s);e.learning=learning.Learning(e);self.assertEqual(e.learning.detail(j['id'])['status'],'paused')
    def blocked(self,action):
        e=self.r.engine;j=self.create(self.body(intent='apply'));before=e.profile();entered=threading.Event();release=threading.Event();errors=[]
        class P(PatchProvider):
            def complete(self,*a,**kw):entered.set();release.wait(5);return super().complete(*a,**kw)
        e.pmm_provider_factory=P
        def work():
            try:e.learning.run(j['id'])
            except Exception as ex:errors.append(ex)
        t=threading.Thread(target=work);t.start();self.assertTrue(entered.wait(2));action(j);release.set();t.join(5);self.assertFalse(t.is_alive());self.assertEqual(before,e.profile());return j,errors
    def test_cancel_inflight_does_not_apply(self):
        j,errors=self.blocked(lambda j:self.r.engine.learning.control(j['id'],'cancel'));self.assertFalse(errors);self.assertEqual(self.r.engine.learning.detail(j['id'])['status'],'cancelled')
    def test_policy_change_inflight_rejects_result(self):
        j,errors=self.blocked(lambda j:self.policy('self',strength=0));self.assertTrue(errors);self.assertEqual(self.r.engine.learning.detail(j['id'])['cursor'],0)
    def test_failed_batch_restores_live_model_and_db(self):
        e=self.r.engine;self.r.configure({'pmm':{'mode':'legacy'}});j=self.create(self.body(intent='apply',train_weights=True));before=e.profile();weights=e.model.export();original=e.learning._apply
        def fail(*a,**kw):original(*a,**kw);raise ValueError('injected post-training failure')
        with patch.object(e.learning,'_apply',side_effect=fail),self.assertRaises(ValueError):e.learning.run(j['id'])
        self.assertEqual(weights,e.model.export());self.assertEqual(before,e.profile());self.assertEqual(e.learning.detail(j['id'])['cursor'],0)
    def test_all_zero_allows_chat_but_blocks_longterm_and_weights(self):
        e=self.r.engine;p=learning.policy(e)
        for r in p['domains'].values():r['strength']=0
        self.policy(domains=p['domains']);before=e.profile();weights=e.model.export();turn=self.turn();self.assertEqual(before,e.profile());self.assertEqual(weights,e.model.export());self.assertEqual(self.r.store.memories(),[])
        self.assertEqual(e.learning.preview(self.body())['source_count'],0)
        with self.assertRaises(ValueError):e.train_pmm()
        with self.assertRaises(ValueError):e.feedback(turn['turn_id'],'helpful',corrected_reply='人工改写')
    def test_manual_mode_does_not_autolearn_but_explicit_job_works(self):
        self.policy('self',mode='manual');e=self.r.engine;before=e.profile();self.turn();self.assertEqual(before,e.profile());j=self.create(self.body(intent='apply'));e.learning.run(j['id']);self.assertEqual(len(e.profile()['source_records']),3)
    def test_self_import_respects_separate_language_zero(self):
        self.policy('language',strength=0);e=self.r.engine;before=e.profile();w=e.model.export();e.import_records(self.records(1));self.assertEqual(e.profile()['style'],before['style']);self.assertEqual(e.profile()['examples'],before['examples']);self.assertEqual(e.model.export(),w);self.assertEqual(len(e.profile()['source_records']),1)
    def test_duplicate_id_with_changed_text_rejected(self):
        e=self.r.engine;b=self.body(intent='apply');j=self.create(b);e.learning.run(j['id']);b['records'][0]['text']='这是另一个原文'
        with self.assertRaises(ValueError):e.learning.preview(b)
    def test_history_language_can_learn_previously_saved_self_sources(self):
        self.policy('language',strength=0);e=self.r.engine;e.import_records(self.records(1));self.assertEqual(e.profile()['style']['count'],0);self.policy('language',strength=1)
        j=self.create({'source':'history','target':'language','scopes':['self:imported'],'intent':'apply','train_weights':True});e.learning.run(j['id']);self.assertEqual(e.profile()['style']['count'],1);self.assertEqual(len(e.profile()['examples']),1);self.assertTrue(any(s['id']=='import:human-0' for s in e.store.meta('pmm_training_records')))
    def test_graph_provider_never_receives_other_private_scope_people(self):
        e=self.r.engine;self.r.store.session('qq:private','private:qq:private');self.r.store.session('qq:visible','group:1');captured=[]
        class P:
            def complete(self,messages,**kwargs):captured.append(json.loads(messages[-1]['content']));return {'claims':[]}
        e.learning._extract(P(),'social_graph',[{'id':'r','text':'你好','person':'qq:visible','scope':'group:1'}]);self.assertEqual(captured[0]['known_people'],['qq:visible'])
    def test_group_observation_requires_scope_and_person(self):
        e=self.r.engine;r={'id':'g1','text':'我喜欢下棋'};person={'scope':'group:qq:7','person':'qq:1'};e.learning.observe_group(person,[r]);self.assertFalse(e.store.meta('learning_observed_sources'))
        self.policy('other',allow_group_observation=True,scopes=['group:qq:7'],people=['qq:1']);e.learning.observe_group(person,[r]);e.learning.observe_group(person,[r]);self.assertEqual(len(e.store.meta('learning_observed_sources')['group:qq:7']),1)
        b={'source':'history','target':'other','scopes':['group:qq:7'],'person':'qq:1','include_observations':True};self.assertEqual(e.learning.preview(b)['source_count'],1);self.policy('other',people=['qq:2']);self.assertEqual(e.learning.preview(b)['source_count'],0)
    def test_other_model_never_writes_self_or_weights(self):
        e=self.r.engine;before=e.profile();w=e.model.export();j=self.create(self.body(target='other',person='qq:1',scopes=['group:qq:7'],intent='apply'));e.learning.run(j['id']);self.assertEqual(before,e.profile());self.assertEqual(w,e.model.export());self.assertIn(e.other_key('group:qq:7','qq:1'),e.store.meta('pmm_interlocutors'))
    def test_history_limits_session_and_days(self):
        e=self.r.engine;s=self.r.store.session('qq:1','group:qq:7');s2=self.r.store.session('qq:2','group:qq:7')
        with self.r.store.lock,self.r.store.db:
            for i in range(5):self.r.store.db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)',(str(i),s,'user','原文'+str(i),now()-(5-i)*86400,'event'+str(i)))
            self.r.store.db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)',('other',s2,'user','另一个人',now(),'other'))
            self.r.store.db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)',('ai',s,'assistant','生成输出',now(),'ai'))
        b={'source':'history','target':'other','person':'qq:1','scopes':['group:qq:7']};self.assertEqual(e.learning.preview(b)['source_count'],5);self.assertEqual(e.learning.preview({**b,'limit':2})['source_count'],2);self.assertEqual(e.learning.preview({**b,'days':2.5})['source_count'],2);self.assertEqual(e.learning.preview({**b,'session_id':s2})['source_count'],0)
    def test_generated_replies_never_form_trait_observations(self):
        e=self.r.engine;p=e.profile();before=copy.deepcopy(p['psychology']['features'])
        for i in range(30):
            r={'id':'ai'+str(i),'text':'我很外向','speaker':p['id'],'context':'','source':'generated'};p,_=apply_distillation(p,{'observations':[{'domain':'traits','key':'extraversion','value':1,'confidence':1,'evidence':[{'record_id':r['id'],'quote':r['text']}]}]},[r],source='generated')
        self.assertEqual(p['observations'],[]);self.assertEqual(before,p['psychology']['features'])
    def test_analysis_does_not_change_profile_and_synthesis_has_no_generated_truth(self):
        e=self.r.engine;self.turn();before=e.profile();w=e.model.export();report=e.synthesize();self.assertEqual(report['statements'],[]);self.assertFalse(report['profile_updated']);self.assertEqual(before,e.profile());self.assertEqual(w,e.model.export());j=self.create(self.body(intent='analysis'));self.assertEqual(e.learning.run(j['id'])['status'],'analysis_complete');self.assertEqual(before,e.profile())
    def test_reanalysis_does_not_multiply_independent_trait_events(self):
        e=self.r.engine;j=self.create(self.body(intent='apply'));e.learning.run(j['id']);before=e.profile();j=self.create(self.body(intent='apply',reanalyse=True));e.learning.run(j['id']);after=e.profile();self.assertEqual(len(before['psychology']['observations']),len(after['psychology']['observations']));self.assertEqual(len(before['source_records']),len(after['source_records']))
    def test_pack_rejects_rollback_metadata_injection(self):
        e=self.r.engine;j=self.create(self.body(intent='apply'));e.learning.run(j['id']);p=export_continuity(e);p['learning_center']['jobs'][0]['rollback'][0]['writes'][0]['key']='identity'
        with self.assertRaises(ValueError):validate_pack(p)
    def test_review_revalidates_current_zero_strength(self):
        e=self.r.engine;j=self.create();e.learning.run(j['id']);before=e.profile();self.policy('self',strength=0)
        with self.assertRaises(ValueError):e.learning.control(j['id'],'approve')
        self.assertEqual(before,e.profile())
    def test_rejected_sources_are_not_reoffered_by_automatic_scan(self):
        e=self.r.engine;j=self.create();e.learning.run(j['id']);e.learning.control(j['id'],'reject');self.assertEqual(e.learning.preview(self.body())['source_count'],0);self.assertEqual(e.learning.preview(self.body(reanalyse=True))['source_count'],3)

class BoundaryCases(Base):
    def seed(self):return self.r.engine.boundaries.edit({'topic':'个人私事','domain':'disclosure','stable_sensitivity':.8})['boundaries'][0]
    def appraisal(self,b,quote='请问你的私事'):return {'boundary_id':b['boundary_id'],'activation':.8,'uncertainty':.2,'quote':quote,'utilities':{a:.5 for a in SOCIAL_ACTIONS}}
    def test_lossless_object_normalization_does_not_edit_evidence(self):
        b=self.seed();row=self.appraisal(b);original=copy.deepcopy(row);r=api_appraisal({'boundary_appraisal':row},[b],row['quote']);self.assertEqual(r['boundary_appraisal'],[row]);self.assertEqual(row,original)
        self.assertEqual(api_appraisal({'boundary_appraisal':{b['boundary_id']:row}},[b],row['quote'])['boundary_appraisal'],[row])
        with self.assertRaises(ValidationFailure):api_appraisal({'boundary_appraisal':self.appraisal(b,'换个说法')},[b],row['quote'])
    def test_broken_boundary_repair_does_not_crash_valid_chat(self):
        b=self.seed();bad=self.appraisal(b,'伪造引用');calls=[]
        class P(PatchProvider):
            def complete(self,messages,*a,**kw):
                system=messages[0]['content'];calls.append(system.splitlines()[0])
                if '[BOUNDARY_APPRAISAL_REPAIR_V250]' in system:return {'boundary_appraisal':[bad]}
                r=super().complete(messages,*a,**kw)
                if '[API_PMM_PREPARE_V2]' in system:r['boundary_appraisal']=[bad]
                return r
        self.r.engine.provider_factory=P;self.r.engine.pmm_provider_factory=P;r=self.turn('请问你的私事');self.assertTrue(r['reply']);self.assertEqual(sum('[BOUNDARY_APPRAISAL_REPAIR_V250]' in c for c in calls),1);row=self.r.engine.boundaries.state()['recent'][-1]['rows'][0];self.assertIsNone(row['activation']);self.assertEqual(row['status'],'unavailable')
        with self.assertRaises(ValueError):self.r.engine.boundaries.calibrate({'turn_id':r['turn_id'],'boundary_id':b['boundary_id'],'activation':.5})
    def test_history_beyond_cache_paginates_searches_and_calibrates(self):
        self.r.configure({'pmm':{'mode':'learned'}});b=self.seed();e=self.r.engine;row=e.boundaries.estimate([b],[],{},'test',{'emotion':{'stress':.1,'valence':0}},{'trust':.5,'familiarity':0,'affection':.5,'interactions':0},e.profile(),'private:qq:123','qq:123')[0]
        for i in range(107):
            with e.store.lock,e.store.db:e.boundaries.record('hist-'+str(i),[row])
        self.assertEqual(len(e.boundaries.state()['recent']),100);self.assertEqual(e.boundaries.history()['total'],107);self.assertEqual(len(e.boundaries.history(offset=100)['items']),7);self.assertEqual(e.boundaries.history(query='hist-0')['total'],1)
        receipt=e.boundaries.calibrate({'turn_id':'hist-0','boundary_id':b['boundary_id'],'activation':.1});self.assertIn('prediction_before',receipt);self.assertEqual(receipt['numeric_updated'],not receipt['heldout'])
        pack=export_continuity(e);self.assertEqual(len(pack['boundary_model']['recent']),107);validate_pack(pack)
        self.r.subjects.apply_current(e,pack);self.assertEqual(e.boundaries.history()['total'],107)
    def test_archive_is_reversible_and_preserves_evidence_references(self):
        b=self.seed();e=self.r.engine
        with self.assertRaises(ValueError):e.boundaries.edit({'op':'archive','boundary_id':b['boundary_id']})
        e.boundaries.edit({'op':'revoke','boundary_id':b['boundary_id']});e.boundaries.edit({'op':'archive','boundary_id':b['boundary_id']});self.assertTrue(e.boundaries.state()['boundaries'][0]['archived']);self.assertEqual(e.boundaries.applicable('private:qq:123','qq:123'),[])
        e.boundaries.edit({'op':'restore','boundary_id':b['boundary_id']});self.assertEqual(e.boundaries.state()['boundaries'][0]['status'],'revoked');self.assertFalse(e.boundaries.state()['boundaries'][0]['archived'])

class GraphAndAffectCases(Base):
    def test_same_person_cross_group_presence_never_creates_friendships(self):
        g=self.r.engine.social_graph
        for scope,person in [('group:1','qq:1'),('group:1','qq:2'),('group:2','qq:1'),('group:2','qq:3')]:g.observe_membership(scope,person,[{'id':scope+person}])
        r=g.query(['group:1','group:2']);self.assertEqual(len(r['people']),3);self.assertEqual(r['intersections'][0]['person_id'],'qq:1');self.assertEqual(r['relation_claims'],[]);self.assertNotIn('qq:3',json.dumps(g.context('group:1','qq:1')))
    def test_relation_claim_is_scoped_unverified_and_counterevidence_disputes(self):
        g=self.r.engine.social_graph
        for person in ('qq:1','qq:2'):g.observe_membership('group:1',person,[{'id':'seen'+person}])
        r={'id':'r1','text':'我和他是朋友','person':'qq:1','scope':'group:1'};claim={'record_id':'r1','subject':'qq:1','object':'qq:2','quote':r['text'],'relation_type':'friend','knowledge_type':'self_report','confidence':.95}
        g.apply_claims([claim],[r],'job');self.assertEqual(g.query(['group:1'])['relation_claims'][0]['status'],'unverified');self.assertEqual(g.query(['group:2'])['relation_claims'],[])
        r2={**r,'id':'r2','text':'我们不是朋友'};g.apply_claims([{**claim,'record_id':'r2','quote':r2['text'],'polarity':'counter'}],[r2],'job2');self.assertTrue(all(c['status']=='disputed' for c in g.query(['group:1'])['relation_claims']));validate_pack(export_continuity(self.r.engine))
    def test_counter_claim_cannot_name_invisible_private_actor(self):
        g=self.r.engine.social_graph;self.r.store.session('qq:99','private:qq:99');g.observe_membership('group:1','qq:1',[{'id':'one'}]);r={'id':'r','text':'他是朋友','person':'qq:1','scope':'group:1'}
        out=g.apply_claims([{'record_id':'r','subject':'qq:1','object':'qq:99','quote':r['text'],'relation_type':'friend','knowledge_type':'self_report','confidence':.5}],[r],'job');self.assertEqual(out['accepted'],0)
    def test_interaction_count_does_not_raise_familiarity(self):
        d=relationships.empty('qq:1','private:qq:1')
        for i in range(100):d,_=relationships.update(d,{},'你好',str(i),'reply',[])
        self.assertEqual(d['familiarity'],0);self.assertEqual(d['interactions'],100)
    def test_catalog_migration_preserves_old_labels_weights_and_93_contract(self):
        e=self.r.engine;old=e.affect_state();old.pop('emotion_catalog',None)
        for k in affect.EXTRA_LABELS:old['emotion']['categorical_activations'].pop(k);old['transition_params']['label_tau_seconds'].pop(k)
        old['emotion']['categorical_activations']['anger']=.47;e.store.setmeta('pmm_affect',old);w=e.model.export();profile=e.profile();a=affect.migrate(e.store)
        self.assertEqual(a['emotion']['categorical_activations']['anger'],.47);self.assertEqual(len(a['emotion']['categorical_activations']),24);self.assertTrue(all(a['emotion']['categorical_activations'][k] is None for k in affect.EXTRA_LABELS));self.assertEqual(w,e.model.export());self.assertEqual(profile,e.profile());self.assertEqual(len(CONTRACT['feature_order']),93);self.assertEqual(a,affect.migrate(e.store));affect.validate(a,profile['id'])
    def test_affect_poll_does_not_change_saved_state_or_trait(self):
        e=self.r.engine;self.turn();before=e.store.meta('pmm_affect');profile=e.profile();details=affect.label_details(before,now()+7200);self.assertEqual(len(details),24);self.assertEqual(before,e.store.meta('pmm_affect'));self.assertEqual(profile,e.profile())
