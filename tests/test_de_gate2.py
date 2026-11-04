"""Gate II: full local dialogue/receipts, isolated D/E interventions, no cloud calls."""
import copy,json,random,shutil,tempfile,unittest,sys,os
from pathlib import Path
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from persona.server import Runtime
from persona import affect as af,pragmatics as pg,language_learning as ll,joint_expression as jx,expression_plan as xp
from persona.psychology import parse_records
from persona.registry import digest
from fixtures import FixtureProvider,response
import test_cbm_v240 as legacy

TEXT='要不要一起去？你带伞，我带水。';SCOPE='private:web:owner';CLOCK=1790000000.;SEED=260
class ControlledProvider(FixtureProvider):
    """Fixed, transparent observation instrument, not a measured real LLM."""
    def __init__(self,c):self.config=c;self.calls=[]
    def complete(self,messages,structured=False,controller=False):
        head=messages[0]['content'];self.calls.append({'stage':head.splitlines()[0],'duration_ms':0})
        if '[REALIZE_V3]' in head:
            c=json.loads(head.split('\n条件：',1)[1]);p=c['interaction_plan'];tone=c['expression_plan']['delivery_tone']
            first={'warm':'好啊！','steady':'好。','restrained':'嗯，可以。'}[tone];second='伞我来带。'
            bits=[first,second] if p['candidate_strategy']=='CASUAL_BURST' else [first+second]
            return json.dumps({'message_parts':[{'step_id':'p'+str(i),'text':x,'purpose':'回应邀请' if i==0 else '确认分工','depends_on':'current_input'} for i,x in enumerate(bits)]},ensure_ascii=False)
        result=response(messages,structured)
        if any(x in head for x in ('[ASSESS_V3]','[ASSESS_V21]','[DECIDE_V21]')):
            result['interaction_plan']={'previous_act':'invitation','evidence_quote':'你带伞，我带水','local_goal':'接受邀请并确认携带物品','strategy':'RESPOND_AND_YIELD','split_reason':'接受邀请与确认谁带伞是两个独立内容','sufficiency_target':'minimal'}
        return result

def seeded(base):
    r=Runtime(base,ROOT)
    try:
        r.engine.provider_factory=ControlledProvider;r.engine.pmm_provider_factory=ControlledProvider
        r.configure({'pmm':{'mode':'learned'},'deliberation':{'mode':'off'}})
        raw=[]
        for n in (1,2):
            raw += [dict(id=f'q{n}',speaker='同伴',text='要不要一起去？',timestamp=CLOCK-900+n*60),dict(id=f'a{n}',speaker='示范者',text='可以去。',timestamp=CLOCK-899+n*60),dict(id=f'b{n}',speaker='示范者',text='东西我带。',timestamp=CLOCK-898+n*60)]
        rs=[a for a in parse_records(json.dumps([{**x,'scope':SCOPE,'conversation_id':'source-room'} for x in raw])) if a['speaker']=='示范者'];r.engine.import_records(rs)
        for d in r.store.meta('pmm_pragmatics')['demonstrations']:
            r.engine.language_review('annotate',{'persona_id':r.engine.profile()['id'],'episode_id':d['id'],'field':'burst_propensity','value':1.,'note':'人工示范分别回应邀请、确认分工；有原文及相邻时间。'})
        p=r.store.meta('pmm_pragmatics');item=ll.candidates(p)[0];out=r.engine.language_review('review',{'persona_id':r.engine.profile()['id'],'candidate_id':item['id'],'evidence_digest':item['evidence_digest'],'expected_version':p['version'],'action':'apply','note':'核对两次独立邀请和相邻发送时间'});assert out['ok']
        a=af.empty(r.engine.profile()['id'],CLOCK-120);a['emotion'].update(valence=-.85,arousal=.70,stress=.60,engagement=.70,source_type='uncalibrated_engineering',confidence=.50);a['mood'].update(valence=-.2,arousal=.35,source_type='uncalibrated_engineering')
        with r.store.lock,r.store.db:r.store.setmeta('pmm_affect',a)
        r.store.session(title='固定空上下文')
        return {'source_event_ids':[x['id'] for x in rs],'candidate_id':item['id'],'before_after':out['changed_fields'],'language_version':out['version'],'checkpoint':digest(r.engine.model.export())}
    finally:r.close()

def run_one(base,path,use_d,use_e,*,positive=False,low_d=False,mode='learned'):
    shutil.copytree(base,path);r=Runtime(path,ROOT)
    try:
        random.seed(SEED);np.random.seed(SEED);r.engine.provider_factory=ControlledProvider;r.engine.pmm_provider_factory=ControlledProvider;r.configure({'pmm':{'mode':mode}})
        protected=digest(r.engine.profile()['trait_profile']);p=copy.deepcopy(r.store.meta('pmm_pragmatics'))
        if positive:
            a=r.store.meta('pmm_affect');a['emotion']['valence']=.85
            with r.store.lock,r.store.db:r.store.setmeta('pmm_affect',a)
        if low_d:
            for d in p['demonstrations']:r.engine.language_review('annotate',{'persona_id':r.engine.profile()['id'],'episode_id':d['id'],'field':'burst_propensity','value':0.,'note':'第二组独立评价：相同场合更愿意合并内容'})
            p=r.store.meta('pmm_pragmatics');c=ll.candidates(p)[0];r.engine.language_review('review',{'persona_id':r.engine.profile()['id'],'expected_version':p['version'],'candidate_id':c['id'],'evidence_digest':c['evidence_digest'],'action':'apply','note':'对照条件：相同话语行为'});p=r.store.meta('pmm_pragmatics')
        real=jx.conditions;sid=r.store.sessions()[0]['id'];base_weights=digest(r.engine.model.export())
        with patch.object(jx,'conditions',side_effect=lambda *args,**kw:real(*args,**kw,use_d=use_d,use_e=use_e)),patch('persona.execution.now',return_value=CLOCK):
            out=r.engine.turn(sid,TEXT,turn_context={'sources':['frozen-input-001']})
        trace=jx.timeline(r.engine)['rows'][0];j=trace['joint'];assert protected==digest(r.engine.profile()['trait_profile']);assert p['version']==r.store.meta('pmm_pragmatics')['version'];assert out['reply_parts']==[a['content'] for a in r.store.rows("SELECT content FROM messages WHERE role='assistant' AND turn_id=? ORDER BY created_at,id",(out['turn_id'],))]
        return {'D':use_d,'E':use_e,'model_mode':mode,'checkpoint_before':base_weights,'input_event_ids':j['event']['original_ids'],'frozen_action':j['frozen_action'],
            'strategy':j['strategy_after'],'tone':j['tone'],'planned':trace['planned_bubbles'],'confirmed':trace['actual_confirmed'],'parts':out['reply_parts'],
            'channel_usage':{u['condition']:u['status'] for u in j['usage']},'candidate_scores':j['scores'],'emotion':j['event_change']['emotion']['valence'],
            'language_version':j['language_version'],'effective_language_evidence':j['language_evidence'],'trait_version':j['trait_version'],
            'actual_expression_count':r.store.meta('pmm_affect')['expressions'][-1]['actual_message_count']}
    finally:r.close()

def experiment():
    with tempfile.TemporaryDirectory() as d:
        parent=Path(d);base=parent/'template';facts=seeded(base);cases={}
        for name,flags in [('baseline',(False,False)),('D_only',(True,False)),('E_only',(False,True)),('D_plus_E',(True,True))]:
            trial=run_one(base,parent/(name+'_a'),*flags);repeat=run_one(base,parent/(name+'_b'),*flags);assert trial==repeat,name;cases[name]=trial
        changed_d=run_one(base,parent/'changedD',True,True,low_d=True);changed_e=run_one(base,parent/'changedE',True,True,positive=True);api=run_one(base,parent/'api',True,True,mode='api');b=cases['D_plus_E']
        assert cases['baseline']['parts']!=cases['D_only']['parts'] and cases['baseline']['parts']!=cases['E_only']['parts'];assert cases['D_only']['strategy']==b['strategy']!=cases['E_only']['strategy'];assert cases['E_only']['tone']==b['tone']!=cases['D_only']['tone'];assert changed_d['strategy']!=b['strategy'] and changed_d['emotion']==b['emotion'];assert changed_e['tone']!=b['tone'] and changed_e['strategy']==b['strategy'] and changed_e['effective_language_evidence']==b['effective_language_evidence'];assert api['planned']==api['confirmed']==api['actual_expression_count'];assert all(r['planned']==r['confirmed']==r['actual_expression_count'] and r['frozen_action']=='reply' for r in cases.values());assert all(r['checkpoint_before']==facts['checkpoint'] for r in cases.values());assert len({r['trait_version'] for r in cases.values()})==1
        return {'fixture':'production dialogue pipeline and SQLite local commit; deterministic conditional renderer, no cloud/QQ','scope':'ablation of the new D/E input to the expression policy, not a claim about an LLM hidden state','input':TEXT,'clock':CLOCK,'seed':SEED,'same_model_checkpoint_per_case':True,'repeats_per_cell':2,'pairs_exactly_repeated':True,'source':facts,'cells':cases,'different_language_same_emotion':changed_d,'different_emotion_same_language':changed_e,'api_pmm_protocol_case':api}

class JointCases(unittest.TestCase):
    def test_factorial_and_independent_interventions(self):
        result=experiment()
        if os.environ.get('DE_EXPERIMENT_REPORT'):Path(os.environ['DE_EXPERIMENT_REPORT']).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    def test_no_purpose_no_burst_and_no_questions_from_emotion(self):
        from test_de_gate1 import feedback_pair,apply,evolve
        p,_=apply(feedback_pair());a,t=evolve();text='你好';event={'id':'e','scope':'s','person':'p','text':text};s=pg.for_planner(p,'s','unknown');c=jx.conditions(s,a,t['trait_snapshot'],event,'unknown')
        for action in ('reply','decline','unknown','silence'):
            decision={'action':action,'decision_id':'d','gate':'weighted_policy' if action=='reply' else 'hard_boundary'};plan=xp.decide_expression(text,{},decision,{'scope':'s'},{},0,1,s);expr=af.expression_plan(t['trait_snapshot'],a,decision,{})
            value=jx.refine(plan,c,expr,decision,{});self.assertEqual(value['selected_action'],action.upper());self.assertFalse(value['allow_follow_up_question']);self.assertFalse(value['joint_decision']['grounded_split_purpose']);self.assertFalse(any(r['strategy']=='CASUAL_BURST' for r in value['joint_decision']['scores']))
            if action=='silence':self.assertEqual(value['joint_decision']['tone'],'no_action')
    def test_partial_qq_reconciles_prefix_without_duplicate_state_or_feedback(self):
        f=legacy.Delivery('test_full_burst_has_three_history_rows_one_episode_one_training_group');f.setUp()
        try:
            def hook(i):
                if i==2:raise TimeoutError('模拟第二条回执未知')
            f.hook=hook;f.process();engine=f.r.engine;r=jx.timeline(engine)['rows'][0];self.assertEqual((r['planned_bubbles'],r['actual_confirmed'],r['receipt_ids']),(3,1,[91]));self.assertEqual(r['delivery'],'DELIVERY_UNKNOWN');self.assertTrue(r['affect_committed']);self.assertEqual(len(r['joint']['event']['original_ids']),1)
            identifier=r['turn_id'];box=engine.journal.delivery(identifier);target=box['payload']['target'];msg=box['payload']['messages'][1]
            f.r.engine.language_review('target',{'persona_id':engine.profile()['id'],'turn_id':identifier,'field':'burst_propensity','value':.1,'note':'只评实际确认的前缀'})
            engine.journal.acknowledge(identifier,lambda:{'retcode':0,'data':{**target,'message':msg,'message_id':92,'sender':{'user_id':999}}});engine.recover_delivered();engine.recover_delivered();r=jx.timeline(engine)['rows'][0]
            self.assertEqual((r['planned_bubbles'],r['actual_confirmed'],r['receipt_ids']),(3,2,[91,92]));self.assertEqual(len(r['feedback']),1);self.assertEqual(len(f.sent),2);self.assertEqual(len(f.r.store.meta('pmm_affect')['appraisals']),1);self.assertEqual(f.r.store.meta('pmm_affect')['expressions'][-1]['actual_message_count'],2);self.assertEqual(f.r.store.meta('state')['turn_count'],1)
        finally:f.tearDown()
    def test_old_observation_keeps_unknown_instead_of_manufactured_trace(self):
        with tempfile.TemporaryDirectory() as d:
            r=Runtime(d,ROOT)
            try:
                p=pg.observe(pg.empty(),'historical',{},['旧消息'],[],'LOCAL_COMMITTED');r.store.setmeta('pmm_pragmatics',p);row=jx.timeline(r.engine)['rows'][0];self.assertTrue(row['historical_without_joint_trace']);self.assertIsNone(row['planned_bubbles']);self.assertEqual(row['actual_confirmed'],1)
            finally:r.close()
if __name__=='__main__':print(json.dumps(experiment(),ensure_ascii=False,indent=2))

class ReliabilityCases(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.r=Runtime(self.temp.name,ROOT);self.r.engine.provider_factory=ControlledProvider;self.r.engine.pmm_provider_factory=ControlledProvider
    def tearDown(self):self.r.close();self.temp.cleanup()
    def durable_snapshot(self):
        # The export envelope has a new creation time on every read; all stored
        # tables, their timestamps and the durable inbox must remain identical.
        snapshot=self.r.store.snapshot();snapshot.pop('exported_at');return snapshot
    def test_same_input_returns_same_turn_without_new_state_or_sends(self):
        sid=self.r.store.session();e=self.r.engine;out=e.turn(sid,TEXT,turn_context={'sources':['one-real-input']});snap=self.durable_snapshot();delivery=[]
        again=e.turn(sid,TEXT,turn_context={'sources':['one-real-input']},delivery=lambda v:delivery.append(v));self.assertEqual(again['turn_id'],out['turn_id']);self.assertTrue(again['replayed']);self.assertEqual(self.durable_snapshot(),snap);self.assertFalse(delivery)
        with self.assertRaises(ValueError):e.turn(sid,TEXT+'有变动',turn_context={'sources':['one-real-input']})
    def test_same_human_correction_not_trained_twice(self):
        e=self.r.engine;out=e.turn(self.r.store.session(),TEXT);e.feedback(out['turn_id'],'unhelpful','请克制些',corrected_reply='可以，伞我带。');snapshot=self.durable_snapshot();weights=e.model.export();again=e.feedback(out['turn_id'],'unhelpful','请克制些',corrected_reply='可以，伞我带。');self.assertTrue(again['replayed']);self.assertEqual(self.durable_snapshot(),snapshot);self.assertEqual(e.model.export(),weights);self.assertTrue(ll.candidates(self.r.store.meta('pmm_pragmatics')))
    def test_owner_feedback_strength_and_immutable_approval_evidence(self):
        from test_de_gate1 import feedback_pair,apply
        p=feedback_pair();q,r=apply(p,lambda s,p:{'allowed':True,'reasons':[],'strength':.2});self.assertEqual(q['applied_tendencies'][0]['learning_strength'],.2);old=copy.deepcopy(q['review_history']);q=ll.feedback_target(q,'a','yield_after_acknowledgement',.1,'反例修订',pg.LABELS);self.assertEqual(q['review_history'],old);self.assertEqual(old[-1]['evidence'][0]['value'],.85);self.assertFalse(ll.applied(q))
    def test_no_unreviewed_annotations_in_model_conditions(self):
        from test_de_gate1 import records
        p=pg.rebuild(None,records());eid=p['demonstrations'][0]['id'];p=pg.annotate(p,eid,'topic_progression_tendency',1.,'只标注，尚未审核');self.assertEqual(pg.summary(p,'s','invitation')['fields']['topic_progression_tendency']['estimate'],1.);self.assertIsNone(pg.for_planner(p,'s','invitation')['fields']['topic_progression_tendency']['estimate'])
    def test_corrupted_single_event_application_cannot_enter_import(self):
        from test_de_gate1 import feedback_pair,apply
        p,_=apply(feedback_pair());p['human_feedback']=p['human_feedback'][:1];c=ll.candidates(p)[0];p['applied_tendencies'][0].update({k:c[k] for k in ('evidence_digest','estimate','effective_events')});p['review_history'][0]['evidence_digest']=c['evidence_digest']
        with self.assertRaises(ValueError):pg.validate(p)
    def test_partial_actual_contents_not_unsent_draft(self):
        f=legacy.Delivery('test_full_burst_has_three_history_rows_one_episode_one_training_group');f.setUp()
        try:
            def hook(i):
                if i==2:raise TimeoutError('无回执')
            f.hook=hook;f.process();row=jx.timeline(f.r.engine)['rows'][0];self.assertEqual(row['actual_parts'],['独立补充内容1。']);self.assertEqual(row['actual_confirmed'],1);self.assertEqual(row['planned_bubbles'],3)
        finally:f.tearDown()
    def test_public_diagnostic_does_not_leak_joint_input_or_feedback(self):
        from persona.execution import public_trace
        self.r.engine.turn(self.r.store.session(),TEXT);run=self.r.engine.journal.recent()[0];raw=json.dumps(public_trace(run),ensure_ascii=False);self.assertNotIn(TEXT,raw);self.assertNotIn('joint_decision',raw)
    def test_untimed_declared_event_fragments_count_once_keep_all_words(self):
        rs=[{'id':str(i),'event_id':'one-original-event','batch_id':str(i),'scope':'s','speaker':'p','source':'imported','context':'','text':v} for i,v in enumerate(['原文甲','原文乙'])];s=pg.summary(pg.rebuild(None,rs));self.assertEqual(s['text_style']['effective_events'],1);self.assertIn('甲',s['text_style']['lexical_units']);self.assertIn('乙',s['text_style']['lexical_units']);self.assertIsNone(s['fields']['burst_propensity']['estimate'])
