"""Stage II independent assertions over real state and local transactions.
Synthetic externally scored experiences; no psychological validity inference.
"""
import copy,json,unittest
from unittest.mock import patch
from test_v212 import Base,ROOT,PatchProvider
from persona.common import now
from persona.registry import digest
from persona import traits,relationships as dy
from persona.server import Runtime
from persona.packages import export_continuity,validate_pack,apply_pack
import test_v250 as old

class FormationCases(Base):
    policy=old.LearningCases.policy
    def episodes(self,n=3):
        out=[]
        for i in range(n):
            sid=self.session('123',group=i%2==1);t=self.turn('请先确认我的意思。'+str(i),sid=sid)
            # Fixture clock: real committed turns, backdated only by this test.
            with self.r.store.lock,self.r.store.db:self.r.store.db.execute('UPDATE messages SET created_at=? WHERE turn_id=?',(now()-400000+i*50000,t['turn_id']))
            out.append(t['turn_id'])
        return out
    def body(self,turn,feature='hexaco.c.prudence',value=.7,note='你在多次处理类似问题时会先核对依据。'):
        return {'experience_turn_id':turn,'feature_id':feature,'estimate':value,'confidence':.7,'timeframe':'habitual' if feature.startswith(('beq.','erq.')) else 'generally' if feature.startswith('panas.') else 'sustained','note':note,'expected_version':self.r.engine.profile()['trait_profile']['version']}
    def test_three_independent_experiences_promote_with_raw_before_after(self):
        e=self.r.engine;turns=self.episodes();before=copy.deepcopy(e.store.meta('pmm_affect'))
        for t in turns:r=e.formation.annotate(self.body(t))
        self.assertEqual(r['promoted'],1);p=e.profile();f=p['psychology']['features']['hexaco.c.prudence'];self.assertAlmostEqual(f['estimate'],.7);h=p['trait_profile']['promotion_history'][-1]
        self.assertEqual(len(h['event_ids']),3);self.assertIsNone(h['before']['estimate']);self.assertEqual(len(h['source_evidence']),3);self.assertEqual(before,e.store.meta('pmm_affect'))
        self.assertTrue(any(r['domain']=='self_experience' and r['after'].get('changes') for r in e.evidence.trace()['revisions']))
        queued=[s for s in e.store.meta('pmm_training_records') if s['labels'].get('source')=='trait_promotion']
        self.assertEqual(len(queued),3);self.assertEqual(len({s['labels']['group_id'] for s in queued}),3)
        self.r.configure({'pmm':{'mode':'learned'}});e=self.r.engine
        candidate=e.model.fork();e.ingest_samples(candidate,queued);candidate.fit(1);self.assertGreater(candidate.steps,e.model.steps);validate_pack(export_continuity(e))
    def test_many_ratings_of_one_experience_cannot_promote(self):
        e=self.r.engine;t=self.episodes(1)[0]
        for i in range(5):e.formation.annotate(self.body(t,note='你先核对依据。不同评价'+str(i)))
        self.assertIsNone(e.profile()['psychology']['features']['hexaco.c.prudence']['estimate']);r=e.review_traits(False)['candidates'][0];self.assertEqual(r['independent_events'],1)
    def test_repeating_owner_annotation_and_restart_does_not_relearn(self):
        e=self.r.engine;turns=self.episodes()
        for t in turns:e.formation.annotate(self.body(t))
        before=e.profile();e.formation.annotate(self.body(turns[0]));self.assertEqual(before,e.profile())
        self.r.close();self.r=Runtime(self.tmp.name,ROOT);self.fixture();e=self.r.engine;e.formation.annotate(self.body(turns[0]));self.assertEqual(before,e.profile())
    def test_new_revision_needs_three_fresh_events_not_one(self):
        e=self.r.engine;turns=self.episodes(6)
        for t in turns[:3]:e.formation.annotate(self.body(t))
        version=e.profile()['trait_profile']['version'];e.formation.annotate(self.body(turns[3],value=.8));self.assertEqual(e.profile()['trait_profile']['version'],version)
        for t in turns[4:]:e.formation.annotate(self.body(t,value=.8))
        self.assertEqual(e.profile()['trait_profile']['version'],version+1);self.assertAlmostEqual(e.profile()['psychology']['features']['hexaco.c.prudence']['estimate'],.7+.03*e.learning.status()['policy']['domains']['self']['strength'])
    def test_counterevidence_blocks_promotion(self):
        e=self.r.engine
        for t,v in zip(self.episodes(),(.1,.9,.2)):e.formation.annotate(self.body(t,value=v))
        self.assertIsNone(e.profile()['psychology']['features']['hexaco.c.prudence']['estimate']);self.assertGreater(e.review_traits(False)['candidates'][0]['counterevidence_spread'],.4)
    def test_dispositions_learn_without_affect_write(self):
        e=self.r.engine;ts=self.episodes();aff=copy.deepcopy(e.store.meta('pmm_affect'))
        for t in ts:e.formation.annotate(self.body(t,'erq.cognitive_reappraisal'))
        self.assertAlmostEqual(e.profile()['trait_profile']['dispositions']['erq.cognitive_reappraisal']['estimate'],.7);self.assertEqual(aff,e.store.meta('pmm_affect'));validate_pack(export_continuity(e))
    def test_current_emotion_and_wrong_timeframe_rejected(self):
        e=self.r.engine;t=self.episodes(1)[0];before=e.profile()
        with self.assertRaises(ValueError):e.formation.annotate(self.body(t,'affect.state.anger'))
        with self.assertRaises(ValueError):e.formation.annotate({**self.body(t,'erq.expressive_suppression'),'timeframe':'now'})
        self.assertEqual(before,e.profile())
    def test_generated_or_wrong_subject_and_scope_rejected(self):
        e=self.r.engine;t=self.episodes(1)[0];s={'scope':'private:qq:123','person':'qq:123'}
        record={'id':'fake','text':'我有耐心','scope':s['scope'],'person':s['person'],'source':'generated','timestamp':now()}
        row={**self.body(t),'target_entity':'agent_self','evidence_kind':'external_feedback','evidence':[{'record_id':'fake','quote':record['text']}]}
        _,r=e.formation.collect(e.profile(),[row],[record],s);self.assertEqual(r['accepted'],0)
        record['source']='observed'
        _,r=e.formation.collect(e.profile(),[{**row,'target_entity':'interlocutor'}],[record],s);self.assertEqual(r['accepted'],0)
        _,r=e.formation.collect(e.profile(),[row],[{**record,'scope':'other'}],s);self.assertEqual(r['accepted'],0)
    def test_withdraw_deactivates_derived_prior_keeps_history(self):
        e=self.r.engine
        for t in self.episodes():e.formation.annotate(self.body(t))
        p=e.profile();rid=p['psychology']['features']['hexaco.c.prudence']['evidence_ids'][0];r=e.formation.withdraw({'record_id':rid,'expected_version':p['trait_profile']['version'],'reason':'原评价不可靠'})
        self.assertEqual(r['invalidated'],1);self.assertIsNone(e.profile()['psychology']['features']['hexaco.c.prudence']['estimate']);self.assertEqual(e.review_traits(True)['promoted'],0);validate_pack(export_continuity(e))
        self.assertFalse(any(s['labels'].get('source')=='trait_promotion' for s in e.store.meta('pmm_training_records')))
    def test_owner_seed_protected(self):
        e=self.r.engine;e.edit_disposition({'feature_id':'hexaco.c.prudence','expected_version':0,'estimate':.4})
        for t in self.episodes():e.formation.annotate(self.body(t))
        self.assertEqual(e.profile()['psychology']['features']['hexaco.c.prudence']['estimate'],.4)
    def test_failed_commit_is_atomic(self):
        e=self.r.engine;t=self.episodes(1)[0];p=e.profile();ev=e.evidence.state();original=e.store.event
        def fail(k,*a):
            if k=='self_experience_evaluated':raise ValueError('after writes')
            return original(k,*a)
        with patch.object(e.store,'event',side_effect=fail),self.assertRaises(ValueError):e.formation.annotate(self.body(t))
        self.assertEqual(p,e.profile());self.assertEqual(ev,e.evidence.state());e.formation.annotate(self.body(t));self.assertEqual(len(e.profile()['psychology']['observations']),1)
    def test_policy_zero_and_stale_version_rejected(self):
        e=self.r.engine;t=self.episodes(1)[0];self.policy('self',strength=0)
        with self.assertRaises(ValueError):e.formation.annotate(self.body(t))
        self.policy('self',strength=1)
        with self.assertRaises(ValueError):e.formation.annotate({**self.body(t),'expected_version':99})
    def test_background_external_feedback_uses_same_gate_and_dedup(self):
        e=self.r.engine;turns=self.episodes()
        while e.consolidation.status()['pending']:e.consolidation.run()
        class External(PatchProvider):
            def complete(self,messages,**kw):
                result=super().complete(messages,**kw)
                if '[CONSOLIDATE_V212]' in messages[0]['content']:
                    payload=json.loads(messages[-1]['content'])
                    for r,item in zip(payload['turns'],result['items']):
                        ur=r['user_record'];target=ur['text'].split(':')[-1]
                        if not ur['text'].startswith('你上次会核对:'):continue
                        assert target in {x['turn_id'] for x in r['prior_interactions']}
                        item['feedback']['self_experience_updates']=[{'target_entity':'agent_self','evidence_kind':'external_feedback','experience_turn_id':target,'feature_id':'hexaco.c.prudence','estimate':.7,'confidence':.7,'timeframe':'sustained','evidence':[{'record_id':ur['id'],'quote':ur['text']}]}]
                return result
        e.pmm_provider_factory=External
        for i,t in enumerate(turns):self.turn('你上次会核对:'+t,sid=self.session(group=i%2==1));e.consolidation.run()
        p=e.profile();self.assertIsNotNone(p['psychology']['features']['hexaco.c.prudence']['estimate']);self.assertEqual(len(p['trait_profile']['promotion_history']),1)
        for t in turns:e.formation.annotate(self.body(t,note='同一真实经历的人工重复评价'))
        self.assertEqual(e.profile()['trait_profile']['version'],p['trait_profile']['version'])
    def test_later_or_other_person_experience_cannot_be_referenced(self):
        e=self.r.engine;t=self.episodes(1)[0];raw={'id':'feedback','source':'observed','scope':'private:qq:123','speaker':'qq:123','text':'你很谨慎','timestamp':1}
        row={**self.body(t),'target_entity':'agent_self','evidence_kind':'external_feedback','evidence':[{'record_id':'feedback','quote':raw['text']}]}
        _,r=e.formation.collect(e.profile(),[row],[raw],{'scope':raw['scope'],'person':'qq:123'});self.assertEqual(r['accepted'],0)
        raw['timestamp']=now();raw['speaker']='qq:other'
        _,r=e.formation.collect(e.profile(),[row],[raw],{'scope':raw['scope'],'person':'qq:other'});self.assertEqual(r['accepted'],0)
    def test_distinct_grounded_contexts_in_one_private_scope(self):
        e=self.r.engine;sid=self.session();turns=[]
        for i in range(3):
            out=self.turn('请帮我核对'+('学习任务' if i%2==0 else '争议意见'),sid=sid);turns.append(out['turn_id'])
            with e.store.lock,e.store.db:e.store.db.execute('UPDATE messages SET created_at=? WHERE turn_id=?',(now()-200000+i*50000,out['turn_id']))
        for i,t in enumerate(turns):e.formation.annotate({**self.body(t),'context_label':'学习' if i%2==0 else '分歧','context_quote':'学习任务' if i%2==0 else '争议意见'})
        self.assertIsNotNone(e.profile()['psychology']['features']['hexaco.c.prudence']['estimate']);self.assertEqual(e.profile()['trait_profile']['promotion_history'][-1]['contexts'],2)
    def test_context_label_requires_original_input_quote(self):
        e=self.r.engine;t=self.episodes(1)[0]
        with self.assertRaises(ValueError):e.formation.annotate({**self.body(t),'context_label':'新情境','context_quote':'不存在于原经历的句子'})

class PeopleCases(Base):
    def test_same_id_scoped_profiles_alias_and_evidence_isolated(self):
        e=self.r.engine;self.turn('本私聊的名字是秘密甲',sid=self.session());self.turn('本群的名字是公开乙',sid=self.session(group=True))
        scope='private:qq:123';src=next((k,r) for k,r in e.evidence.state()['sources'].items() if r['scope']==scope and r['source_type']!='generated')
        e.people.edit({'scope':scope,'person':'qq:123','alias':'秘密甲','source_key':src[0],'quote':src[1]['text'],'expected_version':e.social_graph.state()['version']})
        private=e.people.context(scope,'qq:123');group=e.people.context('group:qq:123','qq:123');self.assertEqual(private['interlocutor']['alias'],'秘密甲');self.assertNotIn('秘密甲',json.dumps(group,ensure_ascii=False));self.assertNotEqual(private['interlocutor']['entity_id'],group['interlocutor']['entity_id'])
    def test_third_party_distinct_from_ai_and_interlocutor(self):
        e=self.r.engine;self.turn('小王今天也在。');scope='private:qq:123';src=next(iter(e.evidence.state()['sources'].items()))
        body={'scope':scope,'person':'local:wang','alias':'小王','source_key':src[0],'quote':'小王','expected_version':e.social_graph.state()['version']}
        e.people.edit(body);r=e.people.query(scope,'local:wang')['people'][0];self.assertEqual(r['entity_type'],'third_party');self.assertIsNone(r['relationship']);self.assertIsNone(r['profile'])
        with self.assertRaises(ValueError):e.people.edit({**body,'person':e.profile()['id'],'expected_version':e.social_graph.state()['version']})
    def test_wrong_scope_identity_evidence_rejected(self):
        e=self.r.engine;self.turn('小王在这里');k,r=next(iter(e.evidence.state()['sources'].items()))
        with self.assertRaises(ValueError):e.people.edit({'scope':'group:other','person':'x','alias':'王','source_key':k,'quote':'小王','expected_version':e.social_graph.state()['version']})
    def test_malformed_scoped_identity_pack_is_rejected(self):
        e=self.r.engine;self.turn('小王在这里');k,r=next(iter(e.evidence.state()['sources'].items()))
        e.people.edit({'scope':'private:qq:123','person':'local:w','alias':'小王','source_key':k,'quote':'小王','expected_version':e.social_graph.state()['version']})
        pack=export_continuity(e);next(m for m in pack['social_graph']['memberships'] if m.get('identity'))['identity']['evidence'][0]['scope']='other'
        with self.assertRaises(ValueError):validate_pack(pack)

class RelationshipCases(unittest.TestCase):
    def test_role_norm_expectation_trace_dedupe_and_retraction(self):
        d=dy.empty('person','scope');text='你是我的学习伙伴；回答前先确认；我希望你有疑问时问我。'
        updates=[{'field':k,'statement':q,'quote':q,'knowledge_type':'reported','confidence':.7} for k,q in [('role','你是我的学习伙伴'),('norm','回答前先确认'),('expectation','我希望你有疑问时问我')]]
        d,r=dy.update(d,{'relationship_updates':updates},text,'e1','reply',[],False);self.assertEqual(r['accepted'],3);self.assertEqual(d['schema_revision'],1);self.assertEqual(d['interactions'],0)
        again,_=dy.update(d,{'relationship_updates':updates},text,'e1','reply',[],False);self.assertEqual(again['schemata'],d['schemata']);self.assertEqual(again['schema_revision'],1)
        d=dy.revise(d,{'expected_version':1,'id':d['schemata'][0]['id'],'op':'dispute','reason':'尚未确认'});self.assertEqual(d['schema_revision'],2);self.assertGreaterEqual(d['schemata'][0]['uncertainty'],.75);self.assertEqual(len(dy.policy_relation(d)['dyad']['schemata']),2);dy.validate({dy.key('person','scope'):d})
    def test_inference_cannot_masquerade_as_report_or_foreign_scope(self):
        d,r=dy.update(dy.empty('p','s'),{'relationship_updates':[{'field':'role','statement':'亲密好友','quote':'你好','knowledge_type':'reported'}]},'你好','e','reply',[],False);self.assertEqual(r['accepted'],0)
        d,r=dy.update(d,{'relationship_updates':[{'field':'role','statement':'可能是伙伴','quote':'你好','knowledge_type':'inferred'}]},'你好','e','reply',[],False);self.assertEqual(r['accepted'],1);d['schemata'][0]['evidence'][0]['scope']='other'
        with self.assertRaises(ValueError):dy.validate({dy.key('p','s'):d})
    def test_personality_changes_relational_appraisal_without_writes(self):
        from persona.psychology import empty_profile
        p=empty_profile('me','Me');p=traits.edit_disposition(p,{'feature_id':'hexaco.a.patience','estimate':.1,'expected_version':0});q=traits.edit_disposition(p,{'feature_id':'hexaco.a.patience','estimate':.9,'expected_version':1})
        u={'semantic':{'hostility':.7,'social':.7,'ambiguity':.3}};d=dy.policy_relation(dy.empty('p','s'));before=copy.deepcopy(d)
        a=dy.cognition(traits.snapshot(p),u,d);b=dy.cognition(traits.snapshot(q),u,d);self.assertNotEqual(a['estimates']['threat'],b['estimates']['threat']);self.assertEqual(d,before)

if __name__=='__main__':unittest.main()
