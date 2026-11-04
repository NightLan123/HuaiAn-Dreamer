"""Stage III: actual Engine turns plus frozen same-PMM component ablations."""
import copy,json,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from test_v212 import Base,ROOT,PatchProvider
from persona.server import Runtime
from persona.common import now
from persona.psychology import ACTIONS
from persona.registry import digest
from persona import decision_evaluation as de,relationships as dy,traits
import test_v27_stage2 as phase2

TEXT='这件事你为什么不先听我解释？';CLOCK=now()+20
class ControlledProvider(PatchProvider):
    """Known fixed observation/utility protocol; no real model performance claim."""
    def complete(self,messages,**kw):
        result=super().complete(messages,**kw);head=messages[0]['content']
        if '[UNDERSTAND_V3]' in head:result['semantic'].update(social=.8,hostility=.7,ambiguity=.4,goal_congruence=.3,agency=.4,certainty=.7)
        if '[API_PMM_PREPARE_V2]' in head:result['action_prior']={a:(.5 if a in ('reply','clarify','disagree') else 0.) for a in ACTIONS}
        if any(x in head for x in ('[ASSESS_V3]','[ASSESS_V21]','[DECIDE_V21]')):
            for v in result['views']:v['utilities']={'reply':.50,'clarify':.49,'disagree':.52,'unknown':0.,'decline':.01,'silence':0.}
        return result

def runtime_comparison(mode='api'):
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);base=root/'base';r=Runtime(base,ROOT)
        r.configure({'pmm':{'mode':mode},'online_learning':False,'deliberation':{'mode':'off'},'cognition':{'mode':'baseline'}})
        sid=r.store.session();identity=r.engine.profile()['id'];r.close();rows={};counterfactual=None;component_comparisons={}
        variants={'baseline':{},'patient_low':{'trait':('hexaco.a.patience',.2)},'patient_high':{'trait':('hexaco.a.patience',.8)},
            'trust_low':{'trust':.2},'trust_high':{'trust':.8},'reappraise_low':{'trait':('erq.cognitive_reappraisal',.2)},
            'reappraise_high':{'trait':('erq.cognitive_reappraisal',.8)},'unmapped_facet':{'trait':('hexaco.o.aesthetic_appreciation',.8)}}
        for name,change in variants.items():
            path=root/name;shutil.copytree(base,path);r=Runtime(path,ROOT);e=r.engine;e.provider_factory=ControlledProvider;e.pmm_provider_factory=ControlledProvider
            try:
                if 'trait' in change:
                    k,v=change['trait'];e.edit_disposition({'feature_id':k,'estimate':v,'expected_version':0})
                if 'trust' in change:
                    d=dy.ensure(dy.empty('web:owner','private:web:owner'));d['trust']=change['trust'];d['schema_revision']=1;d['uncertainties']['trust']={'estimate':.5,'source':'synthetic_fixed_condition'}
                    e.store.setmeta('pmm_dyads',{dy.key('web:owner','private:web:owner'):d})
                weights=digest(e.model.export());prior=traits.snapshot(e.profile())
                with patch('time.time',return_value=CLOCK):out=e.turn(sid,TEXT)
                t=out['trace'];c=t['decision_conditions']
                rows[name]={'action':out['action'],'scores':t['decision']['scores'],'appraisal':c['appraisal']['estimates'],'contributions':t['decision']['condition_contributions'],
                    'regulation':t['trait_affect']['regulation_action']['strategy'],'trait_version_read':c['trait_version'],'trait_digest_read':c['trait_digest'],
                    'prior_matches_read':c['trait_digest']==prior['trait_digest'],'relationship_version_read':c['relationship_version'],
                    'model_digest':weights,'input':TEXT,'scope':c['scope'],'person':c['person'],'time':CLOCK,'gate':t['decision']['gate']}
                if name in ('patient_high','trust_high','reappraise_high'):
                    body={'turn_id':out['turn_id'],'feature_id':'erq.cognitive_reappraisal' if name=='reappraise_high' else 'hexaco.a.patience'}
                    before=e.store.snapshot()['tables'];comparison=de.from_turn(e,body);again=de.from_turn(e,body)
                    assert comparison==again and before==e.store.snapshot()['tables']
                    component_comparisons[name]=comparison
                    if name=='patient_high':counterfactual=comparison
            finally:r.close()
        return {'mode':mode,'conditions':rows,'fixed_component_comparison':counterfactual,'component_comparisons':component_comparisons,'provider':'deterministic_protocol_fixture','psychological_validity':False}

class ActualPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.results={mode:runtime_comparison(mode) for mode in ('api','learned')}
    def test_personality_next_turn_changes_appraisal_and_action(self):
        for x in self.results.values():
            a=x['conditions']['patient_low'];b=x['conditions']['patient_high'];self.assertNotEqual(a['appraisal'],b['appraisal']);self.assertNotEqual(a['action'],b['action']);self.assertTrue(a['prior_matches_read'] and b['prior_matches_read'])
    def test_relationship_next_turn_consumed_in_same_policy(self):
        for x in self.results.values():
            a=x['conditions']['trust_low'];b=x['conditions']['trust_high'];self.assertNotEqual(a['action'],b['action']);self.assertEqual(a['relationship_version_read'],1);self.assertNotEqual(a['contributions']['relationship'],b['contributions']['relationship'])
    def test_regulation_contributes_and_existing_emotion_strategy_reads_it(self):
        for x in self.results.values():
            a=x['conditions']['reappraise_low'];b=x['conditions']['reappraise_high'];self.assertNotEqual(a['action'],b['action']);self.assertNotEqual(a['regulation'],b['regulation'])
    def test_model_weights_time_identity_object_context_fixed(self):
        for x in self.results.values():
            for k in ('model_digest','input','scope','person','time'):self.assertEqual(len({r[k] for r in x['conditions'].values()}),1,k)
    def test_inactive_facet_reports_no_effect(self):
        for x in self.results.values():
            a=x['conditions']['baseline'];b=x['conditions']['unmapped_facet'];self.assertEqual(a['action'],b['action']);self.assertEqual(a['scores'],b['scores']);self.assertEqual(a['appraisal'],b['appraisal'])
    def test_repeatable_local_ablations_reproduce_actual_baseline(self):
        for x in self.results.values():
            c=x['fixed_component_comparison'];self.assertTrue(c['reproduces_actual_base_action']);self.assertEqual(c['rows']['baseline']['decision']['scores'],x['conditions']['patient_high']['scores']);self.assertTrue(any('未观察到' in r['finding'] for r in c['comparisons']))
            for condition,component in (('patient_high','personality'),('trust_high','relationship'),('reappraise_high','regulation')):
                c=x['component_comparisons'][condition];base=c['rows']['baseline'];removed=c['rows']['without_'+component]
                self.assertTrue(c['reproduces_actual_base_action'])
                self.assertEqual(base['decision']['scores'],x['conditions'][condition]['scores'])
                self.assertEqual(base['regulation'],x['conditions'][condition]['regulation'])
                self.assertTrue(any(abs(v)>1e-9 for v in base['contributions'][component].values()))
                self.assertTrue(all(abs(v)<1e-9 for v in removed['contributions'][component].values()))
                self.assertNotEqual(base['decision']['action'],removed['decision']['action'])
                if component=='regulation':self.assertNotEqual(base['regulation'],removed['regulation'])

class RuntimeProof(Base):
    episodes=phase2.FormationCases.episodes;body=phase2.FormationCases.body
    def test_newly_learned_traits_and_habits_read_in_next_pmm_turn(self):
        e=self.r.engine;ts=self.episodes()
        for k in ('hexaco.c.prudence','erq.cognitive_reappraisal'):
            for t in ts:e.formation.annotate(self.body(t,k))
        p=e.profile();e.provider_factory=ControlledProvider;e.pmm_provider_factory=ControlledProvider;out=self.turn(TEXT);c=out['trace']['decision_conditions']
        self.assertEqual(c['trait_version'],p['trait_profile']['version']);self.assertEqual(c['trait_digest'],traits.snapshot(p)['trait_digest']);self.assertNotEqual(c['terms']['personality']['clarify'],0);self.assertNotEqual(c['terms']['regulation']['clarify'],0)
    def test_scoped_conditions_never_include_other_private_sources(self):
        e=self.r.engine;self.turn('PRIVATE_UNIQUE_SECRET_甲',sid=self.session('999'));self.turn(TEXT,sid=self.session('123'))
        latest=PatchProvider.seen[-20:];scoped=[m for m in latest if any(TEXT in str(v.get('content','')) for v in m)]
        self.assertTrue(scoped);self.assertNotIn('PRIVATE_UNIQUE_SECRET_甲',json.dumps(scoped,ensure_ascii=False))
    def test_hard_constraint_and_no_action_gates_survive_conditions(self):
        e=self.r.engine;e.edit_disposition({'feature_id':'hexaco.a.patience','estimate':.9,'expected_version':0});out=self.turn('今天股价是多少？')
        self.assertEqual(out['action'],'unknown');c=de.from_turn(e,{'turn_id':out['turn_id']});self.assertTrue(all(r['decision']['action']=='unknown' for r in c['rows'].values()))
    def test_relation_schema_reaches_understanding_and_following_decision(self):
        e=self.r.engine;scope='private:qq:123';d,_=dy.update(dy.empty('qq:123',scope),{'relationship_updates':[{'field':'norm','statement':'先确认再回答','quote':'先确认再回答','knowledge_type':'reported'}]},'先确认再回答','schema-event','reply',[],False);e.store.setmeta('pmm_dyads',{dy.key('qq:123',scope):d})
        out=self.turn(TEXT);u=next(json.loads(m[-1]['content']) for m in PatchProvider.seen if '[UNDERSTAND_V3]' in m[0]['content']);self.assertEqual(u['relationship_schema']['dyad']['schemata'][0]['statement'],'先确认再回答');self.assertEqual(out['trace']['decision_conditions']['relationship_version'],1)
    def test_corrupt_replay_and_legacy_turn_refused_without_writes(self):
        e=self.r.engine;out=self.turn();f=out['trace']['decision_inputs'];before=e.store.snapshot()['tables'];f['at']+=1
        with self.assertRaises(ValueError):de.compare(f)
        with self.assertRaises(ValueError):de.compare(None)
        self.assertEqual(before,e.store.snapshot()['tables'])

if __name__=='__main__':unittest.main()
