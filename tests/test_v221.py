"""ERROR/BRM fault injection and mechanism tests; no live QQ or psychological validity claim."""
import copy,json,math,tempfile,unittest,hashlib
from pathlib import Path
from unittest.mock import patch
import numpy as np
from test_v212 import Base,PatchProvider,ROOT
from persona.common import now,dumps
from persona.engine import Engine
from persona.server import Runtime
from persona.psychology import ACTIONS
from persona.validation import assessment,candidate_check,validated_call,ValidationFailure
from persona.provider import ProviderError
from persona.execution import ExecutionJournal,DeliveryFailure,public_trace,metrics,validate_snapshot
from persona.boundaries import BoundaryHead,Boundaries,SOCIAL_ACTIONS,features,empty,validate_state,validate_claims,api_appraisal,cues
from persona.packages import export_continuity,validate_pack

VIEWS=[{'id':'v0'}]
def assessed():return {'views':[{'id':'v0','utilities':{a:.5 for a in ACTIONS}}]}

class Contracts(unittest.TestCase):
    def test_single_and_multi_use_distinct_contracts(self):
        self.assertEqual(assessment(assessed(),VIEWS)['_validation']['schema_version'],'action-assessment/single/1')
        two=assessed();two['views'].append({'id':'v1','utilities':{a:.4 for a in ACTIONS}})
        self.assertEqual(assessment(two,[*VIEWS,{'id':'v1'}])['_validation']['schema_version'],'action-assessment/multi/1')
    def test_missing_null_nan_enum_and_duplicates_have_exact_paths(self):
        changes=[(lambda v:v['views'][0]['utilities'].pop('reply'),'/views/0/utilities/reply'),(lambda v:v['views'][0]['utilities'].update(reply=None),'/views/0/utilities/reply'),(lambda v:v['views'][0]['utilities'].update(reply=float('nan')),'/views/0/utilities/reply'),(lambda v:v['views'][0]['utilities'].update(reply=True),'/views/0/utilities/reply'),(lambda v:v['views'][0]['utilities'].update(answer=.4),'/views/0/utilities'),(lambda v:v['views'].append(copy.deepcopy(v['views'][0])),'/views/1/id')]
        for mutate,path in changes:
            v=assessed();mutate(v)
            with self.subTest(path=path),self.assertRaises(ValidationFailure) as caught:assessment(v,VIEWS)
            self.assertIn(path,[r['path'] for r in caught.exception.details['issues']])
    def test_safe_alias_does_not_invent_values(self):
        v=assessed();v['views'][0]['utility']=v['views'][0].pop('utilities');r=assessment(v,VIEWS)
        self.assertTrue(r['_validation']['normalizations']);self.assertNotIn('utilities',v['views'][0]);self.assertEqual(r['views'][0]['utilities'],v['views'][0]['utility'])
    def test_max_one_repair_and_client_configuration_restored(self):
        class Bad:
            config={'json_repair':True};calls=0
            def complete(self,*a,**k):self.calls+=1;return {'views':[]}
        c=Bad();records=[]
        with self.assertRaises(ValidationFailure):validated_call(c,[],lambda x:assessment(x,VIEWS),records)
        self.assertEqual(c.calls,2);self.assertTrue(c.config['json_repair']);self.assertEqual(records[-1]['status'],'invalid');self.assertNotIn('previous_output',dumps(records))
    def test_http_200_invalid_json_is_not_success_or_silence(self):
        class ParseError:
            config={};calls=0
            def complete(self,*a,**k):self.calls+=1;raise ProviderError('JSON invalid',{'code':'INVALID_JSON','http_status':200})
        c=ParseError();records=[]
        with self.assertRaises(ValidationFailure) as caught:validated_call(c,[],lambda x:x,records)
        self.assertEqual(caught.exception.code,'VALIDATION_FAILED');self.assertEqual(c.calls,2);self.assertEqual(records[0]['issues'][0]['path'],'/')
    def test_freeze_revision_and_exact_evidence_span(self):
        d={'decision_id':'d','decision_revision':1,'action':'decline'};v={'decision_id':'d','decision_revision':1,'expected_action':'decline','detected_action':'reply','compliant':False,'failure_code':'ACTION_MISMATCH','spans':[{'start':0,'end':2,'quote':'好的'}]}
        self.assertFalse(candidate_check(v,d,'好的，我答应')['compliant'])
        for change in ({'decision_revision':True},{'decision_id':'other'},{'spans':[{'start':0,'end':2,'quote':'不行'}]}):
            with self.assertRaises(ValidationFailure):candidate_check({**v,**change},d,'好的，我答应')

class JournalTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name);self.j=ExecutionJournal(self.path)
    def tearDown(self):self.j.close();self.tmp.cleanup()
    def prepare(self,ids=None):
        run=self.j.start('p','s',ids or ['event1'],'private:qq:1');i=self.j.prepare(run,{'bot':'9','target':{'user_id':1},'message':[{'type':'text','data':{'text':'hello'}}]},{});return run,i
    def test_dispatch_mark_precedes_remote_call_and_real_receipt_required(self):
        r,i=self.prepare()
        def send(_):self.assertEqual(self.j.outbox(i)[0]['status'],'DISPATCHING');return {'retcode':0,'status':'ok','data':{'message_id':17}}
        self.assertEqual(self.j.dispatch(i,send)['message_id'],17);self.assertEqual(self.j.outbox(i)[0]['status'],'ACKNOWLEDGED')
    def test_async_missing_or_malformed_receipt_is_unknown(self):
        for n,response in enumerate(({'retcode':0,'status':'async','data':{}},{'retcode':0,'status':'ok','data':{}},None,{'retcode':None,'status':'failed','data':[]},{'retcode':True,'status':'ok','data':{'message_id':17}},{'retcode':1,'status':'failed','data':{}})):
            r,i=self.prepare(['e'+str(n)])
            with self.assertRaises(DeliveryFailure) as caught:self.j.dispatch(i,lambda _:response)
            self.assertEqual(caught.exception.code,'DELIVERY_UNKNOWN')
    def test_timeout_after_external_delivery_never_resends_in_changed_window(self):
        r,i=self.prepare();sent=[]
        def send(_):sent.append(1);raise TimeoutError('ACK lost after platform delivery')
        with self.assertRaises(DeliveryFailure):self.j.dispatch(i,send)
        run=self.j.start('p','s',['event1','new-event'],'private:qq:1')
        with self.assertRaises(DeliveryFailure):self.j.prepare(run,{},{} )
        with self.assertRaises(DeliveryFailure):self.j.dispatch(i,send)
        self.assertEqual(sent,[1])
    def test_known_failure_allows_explicit_fresh_attempt(self):
        r,i=self.prepare()
        with self.assertRaises(DeliveryFailure) as c:self.j.dispatch(i,lambda _: {'retcode':1200,'status':'failed','data':{}})
        self.assertEqual(c.exception.code,'DELIVERY_FAILED');other,j=self.prepare();self.assertNotEqual(i,j)
    def test_restart_and_backup_never_execute_ambiguous_plans(self):
        r,i=self.prepare();self.j.transition(i,'DISPATCHING');self.j.close();self.j=ExecutionJournal(self.path)
        self.assertEqual(self.j.outbox(i)[0]['status'],'DELIVERY_UNKNOWN');self.assertFalse(self.j.recoverable())
        snapshot=self.j.snapshot();validate_snapshot(snapshot);self.j.merge_snapshot(snapshot)
        with self.assertRaises(DeliveryFailure):self.prepare()
    def test_reconciliation_requires_sender_target_and_exact_message(self):
        r,i=self.prepare();self.j.transition(i,'DELIVERY_UNKNOWN')
        message={'retcode':0,'data':{'message_id':55,'sender':{'user_id':9},'message':[{'type':'text','data':{'text':'hello'}}]}}
        with self.assertRaises(ValueError):self.j.acknowledge(i,lambda:message)
        message['data']['user_id']=1;self.assertEqual(self.j.acknowledge(i,lambda:message)['message_id'],55)
        self.assertEqual(self.j.outbox(i)[0]['status'],'ACKNOWLEDGED')
    def test_debug_export_drops_raw_content_and_preserves_field_paths(self):
        r=self.j.start('p','s',['secretQQID'],'scope');r.update(error={'exception_type':'E','frames':[],'details':{'code':'VALIDATION_FAILED','secret':'password','body':'private message'}},calls=[{'model':'m','response':{'message':'key=SECRET'},'prompt':'private','http_status':200}]);s=dumps(public_trace(r))
        for word in ('password','private','SECRET','secretQQID'):self.assertNotIn(word,s)
        self.assertIn('http_status',s)
    def test_erasure_keeps_opaque_tombstone_and_permission(self):
        r,i=self.prepare();self.j.permission('s','p',True);self.j.erase()
        self.assertTrue(self.j.permission('s','p'));self.assertEqual(self.j.source_status('event1'),'ERASED');self.assertEqual(self.j.outbox(i)[0]['receipt'],{})
        with self.assertRaises(DeliveryFailure):self.prepare()
    def test_metrics_require_confirmed_ack_and_label_the_clock(self):
        r=[{'timing':{'first_ack_ms':v},'delivery_status':'COMMITTED'} for v in (100,200,300)]+[{'timing':{'first_ack_ms':999},'delivery_status':'DELIVERY_UNKNOWN'}]
        m=metrics(r);self.assertEqual(m['acknowledged_samples'],3);self.assertEqual(m['p50_first_ack_ms'],200);self.assertEqual(m['p95_first_ack_ms'],290);self.assertIsNone(m['user_receipt_time'])
        r.extend([{'timing':{'first_ack_ms':900},'delivery_status':'COMMITTED','input_event_ids':['social-opportunity:1']},{'timing':{'first_ack_ms':float('nan')},'delivery_status':'COMMITTED'}]);m=metrics(r)
        self.assertEqual(m['acknowledged_samples'],3);self.assertEqual(m['p95_first_ack_ms'],290);self.assertEqual(m['proactive']['acknowledged_samples'],1);self.assertEqual(m['proactive']['p50_opportunity_to_ack_ms'],900)

class ErrorFlowTests(Base):
    def remote(self,url,payload=None,*a,**k):
        if url.endswith('/get_login_info'):return {'retcode':0,'data':{'user_id':999}}
        self.sent.append(payload);return {'retcode':0,'status':'ok','data':{'message_id':91}}
    def process(self):
        with patch('persona.qq.request_json',side_effect=self.remote):self.r.bridge.process(self.r.store.rows("SELECT * FROM inbox WHERE status='pending' LIMIT 1")[0])
    def setUp(self):super().setUp();self.enable();self.sent=[]
    def test_failure_fixture_single_path_repairs_once_then_blocks(self):
        class Bad(PatchProvider):
            def complete(self,messages,structured=False,controller=False):
                if '[DECIDE_V21]' in messages[0]['content']:return {'views':[{'id':'v0','utilities':{a:.4 for a in ACTIONS if a!='reply'}}]}
                r=super().complete(messages,structured,controller)
                if '[API_PMM_PREPARE_V2]' in messages[0]['content']:r['direct_assessment']=copy.deepcopy(r['direct_assessment']);r['direct_assessment']['views'][0]['utilities'].pop('reply')
                return r
        self.r.engine.pmm_provider_factory=Bad;self.r.bridge.receive(self.event());self.process()
        run=self.r.engine.journal.recent()[0];self.assertEqual(run['status'],'VALIDATION_FAILED');self.assertEqual(run['validation'][-1]['issues'][0]['path'],'/views/0/utilities/reply');self.assertFalse(self.sent);self.assertFalse(self.r.store.memories());self.assertEqual(self.r.store.meta('state')['turn_count'],0)
    def test_candidate_mismatch_limited_regeneration_no_ghost_memory(self):
        outer=self;checks=[]
        self.r.engine.boundary({'label':'不讨论安静','keywords':['安静'],'action':'decline','hard':True,'enabled':True})
        class Bad(PatchProvider):
            def complete(self,messages,structured=False,controller=False):
                if '[REALIZE_V3]' in messages[0]['content'] and '[CANDIDATE_REPAIR_V221]' not in str(messages):return '可以'*12+'。'
                if '[ACTION_CHECK_V221]' in messages[0]['content']:
                    c=json.loads(messages[-1]['content']);checks.append(c);return {'decision_id':c['decision_id'],'decision_revision':1,'expected_action':c['expected_action'],'detected_action':'reply','compliant':False,'failure_code':'ACTION_MISMATCH','spans':[{'start':0,'end':1,'quote':c['candidate'][:1]}]}
                if '[CANDIDATE_REPAIR_V221]' in str(messages):return '另一候选'
                return super().complete(messages,structured,controller)
        self.r.engine.provider_factory=Bad;self.r.bridge.receive(self.event());self.process()
        self.assertEqual(len(checks),2);self.assertEqual(len(checks[0]['candidate']),25);self.assertEqual(checks[0]['expected_action'],'decline');self.assertEqual(checks[0]['decision_id'],checks[1]['decision_id']);self.assertFalse(self.sent);self.assertFalse(self.r.store.memories());self.assertEqual(self.r.engine.journal.recent()[0]['status'],'VALIDATION_FAILED')
    def test_receipt_survives_commit_crash_and_restart_recovers_once(self):
        self.r.bridge.receive(self.event())
        with patch.object(self.r.engine,'commit_plan',side_effect=RuntimeError('injected database failure')):self.process()
        self.assertEqual(len(self.sent),1);self.assertEqual(self.r.bridge.status()['recent'][0]['status'],'sent_postprocess_pending');self.assertEqual(self.r.store.meta('state')['turn_count'],0)
        self.r.close();self.r=Runtime(self.tmp.name,ROOT);self.fixture()
        self.assertEqual(self.r.store.meta('state')['turn_count'],1);self.assertEqual(len(self.r.store.rows('SELECT * FROM messages')),2);self.assertEqual(self.r.engine.journal.outbox()[0]['status'],'COMMITTED');self.assertEqual(self.r.engine.recover_delivered(),[])
        with self.assertRaises(ValueError):self.r.bridge.retry_failed(self.r.store.rows('SELECT id FROM inbox')[0]['id'])
    def test_crash_after_local_commit_is_idempotent(self):
        self.r.bridge.receive(self.event());original=self.r.engine.journal.committed
        with patch.object(self.r.engine.journal,'committed',side_effect=RuntimeError('crash after SQL commit')):self.process()
        self.assertEqual(self.r.store.meta('state')['turn_count'],1);self.assertEqual(len(self.sent),1)
        self.r.engine.recover_delivered();self.assertEqual(self.r.store.meta('state')['turn_count'],1);self.assertEqual(len(self.r.store.meta('consolidation_queue')),1)
    def test_background_failure_keeps_sent_fact_then_retry_only_learning(self):
        self.r.bridge.receive(self.event());self.process();PatchProvider.bad_batch=True
        with self.assertRaises(ProviderError):self.r.engine.consolidation.run()
        run=self.r.engine.journal.recent()[0];self.assertEqual(run['delivery_status'],'COMMITTED');self.assertEqual(run['learning_status'],'FAILED');self.assertEqual(self.r.bridge.status()['recent'][0]['status'],'sent')
        PatchProvider.bad_batch=False;self.r.engine.consolidation.run(retry=True);self.assertEqual(len(self.sent),1);self.assertEqual(self.r.engine.journal.recent()[0]['learning_status'],'COMPLETED')
    def test_manual_retry_only_definitely_unsent_and_preserves_input(self):
        self.r.bridge.receive(self.event());old=self.remote
        def failed(url,*args,**kwargs):return old(url,*args,**kwargs) if url.endswith('/get_login_info') else {'status':'failed','retcode':1400,'data':{}}
        self.remote=failed;self.process();identifier=self.r.store.rows('SELECT id FROM inbox')[0]['id'];self.assertEqual(self.r.bridge.status()['recent'][0]['status'],'delivery_failed')
        self.r.bridge.retry_failed(identifier);self.remote=old;self.process();self.assertEqual(len(self.sent),1);self.assertEqual(self.r.store.meta('state')['turn_count'],1)
    def test_web_received_input_is_durable_even_model_fails(self):
        class Bad(PatchProvider):
            def complete(self,*a,**k):raise ProviderError('fail')
        self.r.engine.provider_factory=Bad
        with self.assertRaises(ProviderError):self.r.engine.turn(self.r.store.session(),'input retained')
        rows=self.r.engine.journal.snapshot()['inbound'];self.assertIn('input retained',rows[0]['payload']);self.assertNotIn('input retained',dumps(public_trace(self.r.engine.journal.recent()[0])))
    def test_ack_backup_restore_does_not_replay_old_pending_window(self):
        self.r.bridge.receive(self.event());snap=self.r.snapshot();self.process();self.assertEqual(len(self.sent),1)
        self.r.restore(snap);self.fixture();self.process();self.assertEqual(len(self.sent),1);self.assertEqual(self.r.bridge.status()['recent'][0]['status'],'delivery_unknown')

class BoundaryTests(Base):
    def seed(self,**kw):
        out=self.r.engine.boundaries.edit({'topic':'私事只在了解来意后谈','domain':'disclosure','stable_sensitivity':.8,**kw});return out['boundaries'][-1]
    def cue(self,b,request=1):return {'boundary_id':b['boundary_id'],'relevance':1.,'request':request,'pressure':0.,'uncertainty':.1,'quote':'请告诉我你的私事'}
    def estimate(self,b,relation=None,stress=.1,request=1):
        self.r.configure({'pmm':{'mode':'learned'}});rel={'trust':.5,'familiarity':0,'affection':.5,'interactions':0,**(relation or {})};activity={'emotion':{'valence':0,'stress':stress}}
        return self.r.engine.boundaries.estimate([b],[self.cue(b,request)],{},'请告诉我你的私事',activity,rel,self.r.engine.profile(),'private:qq:123','qq:123')[0]
    def report(self,b=None,polarity='support'):
        return {'boundary_id':b['boundary_id'] if b else '', 'domain':'disclosure','topic':'私事只在了解来意后谈','target':'self','polarity':polarity,'quote':'我希望你不要随意透露自己的私事','interpretation':'此交谈对象的实际反馈，不泛化为所有人','alternative_explanations':['可能只针对这次交谈'],'uncertainty':.3}
    def absorb(self,report,event='e1',source='observed',about=True,person='qq:123',scope='private:qq:123',at=None):
        e=self.r.engine;r={'id':event+':u','text':report['quote'],'source':source}
        with e.store.lock,e.store.db:return e.boundaries.absorb([report],r,{'person':person,'scope':scope},event,at or now(),{'about_ai':about,'quote':report['quote']})
    def test_same_question_changes_with_relation_emotion_and_seed(self):
        b=self.seed();stranger=self.estimate(b);familiar=self.estimate(b,{'familiarity':.5,'interactions':15});close=self.estimate(b,{'familiarity':.95,'trust':.9,'affection':.9,'interactions':100});upset=self.estimate(b,stress=.9)
        self.assertGreater(stranger['activation'],familiar['activation']);self.assertGreater(familiar['activation'],close['activation']);self.assertGreater(upset['activation'],stranger['activation']);weak=copy.deepcopy(b);weak['stable_sensitivity']=.1;self.assertLess(self.estimate(weak)['activation'],stranger['activation']);self.assertEqual(self.r.engine.boundaries.state()['boundaries'][0]['stable_sensitivity'],.8)
    def test_mention_only_does_not_trigger_and_paraphrase_uses_evidence(self):
        b=self.seed();r=self.estimate(b,request=0);self.assertEqual(r['activation'],0)
        for text in ('请告诉我你的私事','可以分享一点私人经历吗'):
            c={**self.cue(b),'quote':text};self.assertEqual(cues({'boundary_cues':[c]},[b],text)[0]['request'],1)
    def test_pressure_and_uncertainty_change_legal_expression(self):
        b=self.seed();r=self.estimate(b);base=r['training_x'];head=BoundaryHead();press=base[:];press[4]=1
        self.assertGreater(head.predict(press)[3],head.predict(base)[3])
        decision={'action':'reply','gate':'weighted_policy','scores':{},'knowledge':{}};u={'semantic':{'disengagement':0}}
        out=self.r.engine.boundaries.policy(decision,[r],u,[]);self.assertIn(out['boundary']['action'],SOCIAL_ACTIONS);self.assertNotIn('correct_claim',out['boundary']['allowed_actions']);self.assertNotIn('no_action',out['boundary']['allowed_actions'])
    def test_personal_boundary_cannot_override_knowledge_gate(self):
        b=self.seed();r=self.estimate(b);d={'action':'unknown','gate':'missing_evidence'};self.assertEqual(self.r.engine.boundaries.policy(d,[r],{'semantic':{}},[]),d)
    def test_generated_replies_and_others_privacy_do_not_become_self_evidence(self):
        r=self.report()
        for i in range(100):self.absorb(r,'generated'+str(i),source='generated')
        self.absorb(r,about=False);self.assertEqual(self.r.engine.boundaries.state()['boundaries'],[])
    def test_candidate_event_dedup_counterevidence_and_owner_confirmation(self):
        r=self.report();self.assertEqual(self.absorb(r)['accepted'],1);b=self.r.engine.boundaries.state()['boundaries'][0]
        for _ in range(10):self.absorb(r)
        s=self.r.engine.boundaries.state();self.assertEqual(len(s['evidence']),1);self.assertEqual(s['boundaries'][0]['status'],'provisional');self.assertEqual(s['boundaries'][0]['authority_level'],'soft')
        prior=s['boundaries'][0]['stable_sensitivity'];self.absorb(self.report(b,'counter'),'e2');s=self.r.engine.boundaries.state();self.assertLess(s['boundaries'][0]['stable_sensitivity'],prior);self.assertEqual(len(s['boundaries'][0]['counterevidence_ids']),1)
        self.r.engine.boundaries.edit({'op':'confirm','boundary_id':b['boundary_id']});self.assertEqual(self.r.engine.boundaries.state()['boundaries'][0]['status'],'confirmed');self.r.engine.boundaries.edit({'op':'revoke','boundary_id':b['boundary_id']});self.assertFalse(self.r.engine.boundaries.applicable('private:qq:123','qq:123'))
    def test_scoped_boundary_never_creates_relationship_or_crosses_group(self):
        self.absorb(self.report(),scope='group:qq:10');s=self.r.engine.boundaries.state();b=s['boundaries'][0];self.r.engine.boundaries.edit({'op':'confirm','boundary_id':b['boundary_id']});self.assertFalse(self.r.engine.boundaries.applicable('group:qq:11','qq:123'));self.assertFalse(self.r.engine.boundaries.applicable('group:qq:10','qq:999'));self.assertFalse(self.r.store.meta('pmm_dyads'))
    def test_owner_strength_not_silently_overwritten_by_inferred_feedback(self):
        b=self.seed();self.absorb(self.report(b,'counter'),'e2');r=self.r.engine.boundaries.state()['boundaries'][0];self.assertEqual(r['stable_sensitivity'],.8);self.assertIn('suggested_sensitivity',r)
        with self.assertRaises(ValueError):self.r.engine.boundaries.edit({'boundary_id':'external:truth','op':'revoke'})
    def test_numeric_head_trains_real_weights_and_holdout_is_excluded(self):
        b=self.seed();r=self.estimate(b);e=self.r.engine;s=e.boundaries.state();train_id=next(str(i) for i in range(100) if int(hashlib.sha256(str(i).encode()).hexdigest()[:8],16)%5!=0);held_id=next(str(i) for i in range(100) if int(hashlib.sha256(str(i).encode()).hexdigest()[:8],16)%5==0)
        with e.store.lock,e.store.db:
            s['recent']=[{'turn_id':v,'at':now(),'rows':[r]} for v in (train_id,held_id)];e.store.setmeta('boundary_model',s)
        old=BoundaryHead().export()['weights'];res=e.boundaries.calibrate({'turn_id':train_id,'boundary_id':b['boundary_id'],'activation':.1,'action':'ask_intent'});self.assertTrue(res['numeric_updated']);new=e.boundaries.state()['numeric_head']['weights'];self.assertNotEqual(old,new)
        res=e.boundaries.calibrate({'turn_id':held_id,'boundary_id':b['boundary_id'],'activation':.2});self.assertTrue(res['heldout']);self.assertEqual(new,e.boundaries.state()['numeric_head']['weights']);self.assertEqual(res['metrics']['heldout_samples'],1);self.assertIsNotNone(res['metrics']['ablation']['without_relation']['brier'])
        with self.assertRaises(ValueError):e.boundaries.calibrate({'turn_id':train_id,'boundary_id':b['boundary_id'],'activation':.4})
    def test_bad_boundary_schema_or_checkpoint_rejected_before_restore(self):
        b=self.seed();s=self.r.engine.boundaries.state();validate_state(s);bad=copy.deepcopy(s);bad['boundaries'][0]['authority_level']='hard'
        with self.assertRaises(ValueError):validate_state(bad)
        pack=export_continuity(self.r.engine);pack['boundary_model']=bad
        with self.assertRaises(ValueError):validate_pack(pack)
        with self.assertRaises(ValidationFailure):api_appraisal({'boundary_appraisal':[{'boundary_id':b['boundary_id'],'activation':float('nan'),'uncertainty':.1,'quote':'input','utilities':{a:.5 for a in SOCIAL_ACTIONS}}]},[b],'input')
    def test_claim_memory_records_saying_not_external_fact_or_boundary(self):
        e=self.r.engine;r={'id':'a','text':'我上次去过那里','source':'generated'}
        with e.store.lock,e.store.db:e.claims.observe([{'quote':r['text'],'intent':'陈述','truth_status':'unverified','corrects':''}],r,'private:qq:123','t1')
        claim=e.claims.recent('private:qq:123')[0];self.assertFalse(claim['external_fact']);self.assertEqual(e.boundaries.state()['evidence'],[]);self.assertEqual(e.claims.recent('private:qq:456'),[]);validate_claims([claim])
        bad={**claim,'truth_status':'verified','external_fact':True}
        with self.assertRaises(ValueError):validate_claims([bad])
    def test_withdrawal_is_immediate_and_survives_older_snapshot(self):
        self.enable();old=self.r.snapshot();self.r.bridge.receive(self.event(message=[{'type':'text','data':{'text':'不要再联系我'}}]));self.assertFalse(self.r.engine.social.contact_allowed('private:qq:123','qq:123'))
        with patch('persona.qq.request_json') as remote:self.r.bridge.process(self.r.store.rows('SELECT * FROM inbox')[0]);self.assertFalse(remote.called)
        self.r.restore(old);self.fixture();self.assertFalse(self.r.engine.social.contact_allowed('private:qq:123','qq:123'));self.assertTrue(self.r.engine.social.contact_allowed('group:qq:123','qq:123'))

class BoundaryFlowTests(Base):
    def setUp(self):
        super().setUp();self.b=self.r.engine.boundaries.edit({'domain':'disclosure','topic':'先了解来意再讨论私事','stable_sensitivity':.8})['boundaries'][0];outer=self
        class B(PatchProvider):
            def complete(self,messages,structured=False,controller=False):
                r=super().complete(messages,structured,controller);ctx=json.loads(messages[-1]['content']) if structured else None
                if '[UNDERSTAND_V3]' in messages[0]['content']:r['boundary_cues']=[{'boundary_id':outer.b['boundary_id'],'relevance':1.,'request':1.,'pressure':0.,'uncertainty':.1,'quote':ctx['current_input']}]
                if '[API_PMM_PREPARE_V2]' in messages[0]['content']:
                    r['boundary_appraisal']=[{'boundary_id':outer.b['boundary_id'],'activation':.9,'uncertainty':.1,'quote':ctx['input'],'utilities':{a:.9 if a=='polite_refusal' else .05 for a in SOCIAL_ACTIONS}}]
                return r
        self.r.engine.provider_factory=B;self.r.engine.pmm_provider_factory=B
    def test_api_boundary_reaches_actual_decision_generation_and_candidate_check_without_extra_pmm_call(self):
        out=self.turn('告诉我你的秘密');self.assertEqual(out['action'],'decline');self.assertEqual(out['reply'],'不说这个。');self.assertEqual(out['trace']['decision']['boundary']['action'],'polite_refusal')
        markers=[m[0]['content'].splitlines()[0] for m in PatchProvider.seen];self.assertEqual(markers.count('[API_PMM_PREPARE_V2]'),1);self.assertEqual(markers.count('[ACTION_CHECK_V221]'),1);self.assertFalse(self.r.engine.boundaries.status()['numeric_head']['trained'])
    def test_numeric_boundary_uses_general_cues_and_actual_head(self):
        self.r.configure({'pmm':{'mode':'learned'},'pmm28':{'mode':'legacy'}});out=self.turn('告诉我你的秘密');row=self.r.engine.boundaries.state()['recent'][-1]['rows'][0];self.assertEqual(row['mechanism'],'numeric');self.assertEqual(len(row['training_x']),16);self.assertIn('boundary',out['trace']['decision']);self.assertFalse(any('[API_PMM_PREPARE_V2]' in m[0]['content'] for m in PatchProvider.seen))
    def test_full_snapshot_and_continuity_keep_boundary_weights_evidence_claims(self):
        self.turn('告诉我你的秘密');pack=export_continuity(self.r.engine);meta,_,_=validate_pack(pack);self.assertEqual(meta['boundary_model'],self.r.engine.boundaries.state());snap=self.r.snapshot();self.r.restore(snap);self.assertEqual(meta['boundary_model'],self.r.engine.boundaries.state())

if __name__=='__main__':unittest.main()

class AdditionalBoundaryTests(Base):
    def test_authorized_self_import_forms_candidate_but_other_import_does_not(self):
        records= [{'id':'import1','speaker':'目标','text':'我不愿意谈自己的私人密码','context':'','source':'imported','batch_id':'batch1'}]
        self.r.engine.import_records(records,target='interlocutor');self.assertFalse(self.r.engine.boundaries.state()['boundaries'])
        self.r.engine.import_records(records,target='self');s=self.r.engine.boundaries.state();self.assertTrue(s['boundaries']);self.assertEqual(s['boundaries'][0]['status'],'provisional');self.assertEqual(s['evidence'][0]['source'],'authorized_import');validate_state(s)
    def test_numeric_activation_head_does_not_learn_from_its_own_output(self):
        h=BoundaryHead();x=[.5]*16;x[0]=1;x[-1]=.99;h.train(x,{0:.1});self.assertEqual(h.w[0,-1],0);a=h.predict(x)[0];x[-1]=0;self.assertEqual(h.predict(x)[0],a)
    def test_provisional_affects_only_soft_context_not_permissions(self):
        b=self.r.engine.boundaries.edit({'topic':'请先询问来意','stable_sensitivity':.8})['boundaries'][0];s=self.r.engine.boundaries.state();s['boundaries'][0].update(status='provisional',origin='evidence_distilled',uncertainty=.8)
        with self.r.store.lock,self.r.store.db:self.r.store.setmeta('boundary_model',s)
        self.assertEqual(self.r.engine.boundaries.applicable('private:web:owner','web:owner')[0]['status'],'provisional');self.assertEqual(self.r.engine.boundaries.status()['external_constraints'][0]['authority_level'],'hard')
    def test_template_keeps_owner_seeds_without_private_evidence_or_numeric_replay(self):
        self.r.engine.boundaries.edit({'topic':'自主决定讨论深度','domain':'autonomy'});self.r.engine.boundaries.edit({'topic':'这位对象的私事','scope':'private:qq:123','recipient':'qq:123'})
        p=self.r.subjects.export_pack(self.r.engine,'template');b=p['boundary_model'];self.assertEqual(len(b['boundaries']),1);self.assertFalse(b['evidence']);self.assertIsNone(b['numeric_head']);validate_state(b)
    def test_semantic_contact_withdrawal_preempts_wait(self):
        self.enable();self.r.configure({'cognition':{'mode':'adaptive'}})
        from fixtures import response
        class Withdraw(PatchProvider):
            def complete(self,messages,structured=False,controller=False):
                if '[COGNITIVE_' in messages[0]['content']:
                    c=json.loads(messages[-1]['content']);r=c['records'][0];out=response(messages,structured);out['estimates']['turn_complete']=.01;out['contact_withdrawal']={'stop':True,'record_id':r['id'],'quote':r['text']};return out
                return super().complete(messages,structured,controller)
        self.r.engine.pmm_provider_factory=Withdraw;self.r.bridge.receive(self.event(message=[{'type':'text','data':{'text':'以后请停止与我交流'}}]))
        with patch('persona.qq.request_json') as remote:self.r.bridge.process(self.r.store.rows('SELECT * FROM inbox')[0]);self.assertFalse(remote.called)
        self.assertEqual(self.r.bridge.status()['recent'][0]['status'],'permission_withdrawn');self.assertEqual(self.r.engine.journal.recent()[0]['status'],'PERMISSION_WITHDRAWN')

class Routes221(unittest.TestCase):
    from test_api import APITests
    setUp=APITests.setUp;tearDown=APITests.tearDown;request=APITests.request
    def test_boundary_edit_revoke_and_metrics_routes(self):
        r=self.request('/api/boundaries/edit',{'topic':'尊重自主','domain':'autonomy'});bid=r['boundaries'][0]['boundary_id'];self.assertEqual(self.request('/api/boundaries')['boundaries'][0]['status'],'confirmed');self.assertEqual(self.request('/api/boundaries/edit',{'op':'revoke','boundary_id':bid})['boundaries'][0]['status'],'revoked');self.assertEqual(self.request('/api/claims'),[])
    def test_execution_jsonl_export_and_retry_guards(self):
        import urllib.request,urllib.error
        run=self.app.engine.journal.start('p','s',['private-id'],'s');run['error']={'exception_type':'Fixture','details':{'secret':'DO_NOT_EXPORT'}};self.app.engine.journal.save(run)
        with urllib.request.urlopen(urllib.request.Request(self.base+'/api/execution/export',headers=self.headers)) as r:data=r.read().decode()
        self.assertNotIn('DO_NOT_EXPORT',data);self.assertNotIn('private-id',data);self.assertTrue(json.loads(data.splitlines()[-1])['summary']);self.assertEqual(self.request('/api/execution/recover',{})['recovered'],[])
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/qq/retry-failed',{'id':'none'})
    def test_receipt_route_uses_outbox_id_from_ui(self):
        j=self.app.engine.journal;r=j.start('p','s',['ev'],'group:qq:1');i=j.prepare(r,{'bot':'9','target':{'group_id':1},'message':[{'type':'text','data':{'text':'ok'}}]},{});j.transition(i,'DELIVERY_UNKNOWN')
        result={'retcode':0,'data':{'message_id':7,'group_id':1,'sender':{'user_id':9},'message':[{'type':'text','data':{'text':'ok'}}]}}
        with patch('persona.provider.request_json',return_value=result):response=self.request('/api/execution/reconcile',{'outbox_id':i,'message_id':7})
        self.assertEqual(response['receipt']['message_id'],7);self.assertEqual(j.outbox(i)[0]['status'],'ACKNOWLEDGED')

class SocialOutboxTests(Base):
    from test_v212 import SocialTests
    ready=SocialTests.ready
    def test_async_social_receipt_does_not_record_an_assistant_message(self):
        sid=self.ready();before=self.r.store.history(sid)
        with patch('persona.qq.request_json',return_value={'retcode':0,'data':{'user_id':999}}),patch('persona.social.request_json',return_value={'retcode':0,'status':'async','data':{}}),self.assertRaises(DeliveryFailure):self.r.engine.social.evaluate('private:qq:123',send=True)
        self.assertEqual(self.r.store.history(sid),before);self.assertEqual(self.r.engine.journal.recent()[0]['delivery_status'],'DELIVERY_UNKNOWN')
    def test_social_receipt_commit_failure_recovers_without_recreating_user(self):
        sid=self.ready();before=self.r.store.history(sid)
        with patch('persona.qq.request_json',return_value={'retcode':0,'data':{'user_id':999}}),patch('persona.social.request_json',return_value={'retcode':0,'status':'ok','data':{'message_id':88}}) as send,patch.object(self.r.engine,'commit_social',side_effect=RuntimeError('commit failed')),self.assertRaises(RuntimeError):self.r.engine.social.evaluate('private:qq:123',send=True)
        self.assertEqual(send.call_count,1);self.assertEqual(self.r.store.history(sid),before);self.r.engine.recover_delivered();self.assertEqual(len(self.r.store.history(sid)),len(before)+1);self.assertEqual(self.r.store.history(sid)[-1]['role'],'assistant');self.assertEqual(self.r.engine.recover_delivered(),[])
    def test_only_new_actual_recipient_consent_can_restore_withdrawn_permission(self):
        self.enable();self.r.bridge.receive(self.event(message=[{'type':'text','data':{'text':'不要再联系我'}}]))
        with self.assertRaises(ValueError):self.r.engine.social.unblock('private:qq:123')
        self.r.bridge.receive(self.event(mid=2,message=[{'type':'text','data':{'text':'可以继续联系我'}}]));self.assertTrue(self.r.engine.social.contact_allowed('private:qq:123','qq:123'))
    def test_baseline_controller_failure_is_not_forced_reply(self):
        self.enable()
        class Bad(PatchProvider):
            def complete(self,messages,structured=False,controller=False):
                if '[TURN_TAKING_V212]' in messages[0]['content']:raise ProviderError('controller failed')
                return super().complete(messages,structured,controller)
        self.r.engine.pmm_provider_factory=Bad;self.r.bridge.receive(self.event())
        with patch('persona.qq.request_json') as send:self.r.bridge.process(self.r.store.rows('SELECT * FROM inbox')[0]);self.assertFalse(send.called)
        self.assertEqual(self.r.engine.journal.recent()[0]['status'],'VALIDATION_FAILED')
