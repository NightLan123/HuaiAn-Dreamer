"""CBM fixtures: engineering acceptance only; no live model or QQ claims."""
import copy,json,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from persona import expression_plan as xp,pragmatics as pg
from persona.execution import ExecutionJournal,DeliveryFailure
from persona.psychology import parse_records
from persona.packages import export_continuity,validate_pack
from persona.pmm_interface import digest
from persona.common import now
from test_v212 import Base,PatchProvider,ROOT


def plan(text,action='reply',proposal=None):
    return xp.decide_expression(text,{'semantic':{}}, {'action':action,'decision_id':'d','reason':'need'}, {'sources':['event'],'scope':'private:qq:1','version':2}, {'familiarity':.5},7,3,pg.summary(None),proposal)

class Plans(unittest.TestCase):
    def test_fixed_six_cases_keep_local_goal_and_obligation(self):
        cases=[('最近有点想玩胡闹厨房','tentative_interest',True,'minimal'),('要不要一起玩胡闹厨房？','invitation',False,'minimal'),('我打算今晚八点开胡闹厨房，你来吗','invitation',False,'minimal'),('我打工累死了','complaint',False,'minimal'),('这游戏怎么联机？','question',False,'complete'),('我先去忙了','closing',False,'minimal')]
        for text,act,ask,sufficient in cases:
            with self.subTest(text=text):
                p=plan(text);self.assertEqual(p['previous_act'],act);self.assertEqual(p['allow_follow_up_question'],ask);self.assertEqual(p['sufficiency_target'],sufficient);self.assertIsNone(p['message_plan']['target_bubbles']);self.assertTrue(p['yield_after_current_reply']);self.assertFalse(p['timing']['automatic_followup'])
    def test_remove_unneeded_followups_without_rewriting_whole_response(self):
        cases=[('最近有点想玩胡闹厨房',['可以啊。','你想玩几关？'],['可以啊。']),('要不要一起玩胡闹厨房？',['可以啊。你想玩？'],['可以啊。']),('我打工累死了',['先歇歇。今天几点上班？'],['先歇歇。']),('我先去忙了',['好。','什么时候回来？'],['好。'])]
        for text,parts,expected in cases:
            with self.subTest(text=text):self.assertEqual(xp.trim_excess(parts,plan(text))[0],expected)
    def test_necessary_explanation_not_cut_for_brevity(self):
        p=plan('这游戏怎么联机？');parts=['打开联机菜单。','一方建房，另一方输入房间码。']
        parsed,_=xp.parse_message_parts(json.dumps({'message_parts':[{'step_id':str(i),'text':t} for i,t in enumerate(parts)]}),p)
        self.assertEqual(parsed,['\n'.join(parts)]);self.assertEqual(xp.trim_excess(parsed,p)[0],parsed)
    def test_1_to_4_bubbles_and_legacy_marker_are_real_units(self):
        for n in range(1,5):
            parts=[f'独立信息{i}。' for i in range(n)]
            for raw in (xp.BREAK.join(parts),json.dumps({'message_parts':[{'step_id':str(i),'text':t} for i,t in enumerate(parts)]})):
                self.assertEqual(xp.parse_message_parts(raw,plan('刚才看到个有趣的东西'))[0],parts)
    def test_malformed_protocol_never_becomes_chat_content(self):
        for raw in ('{"message_parts":','[[QQ_MSG_BREAK]]尾巴','a'+xp.BREAK*2+'b',json.dumps([{'step_id':'x','text':'a'},{'step_id':'x','text':'b'}])):
            with self.subTest(raw=raw),self.assertRaises(ValueError):xp.parse_message_parts(raw,plan('test'))
    def test_grounded_model_plan_overrides_act_not_frozen_action(self):
        p=plan('周末见吧',proposal={'evidence_quote':'周末见','previous_act':'invitation','strategy':'CASUAL_BURST','local_goal':'回应邀请'})
        self.assertEqual(p['basis']['model_type'],'API_PMM_STRUCTURED');self.assertEqual(p['candidate_strategy'],'CASUAL_BURST')
        q=plan('周末见吧','decline',{'evidence_quote':'周末见','strategy':'NO_ACTION','selected_action':'reply'})
        self.assertEqual(q['selected_action'],'DECLINE');self.assertEqual(q['message_plan']['max_bubbles'],1)
    def test_unfounded_plan_and_need_are_not_accepted(self):
        p=plan('你好',proposal={'evidence_quote':'not in input','strategy':'CLARIFY_IF_NEEDED','follow_up_need':'ask more'})
        self.assertIn('ungrounded_proposal_ignored',p['basis']['warnings']);self.assertFalse(p['allow_follow_up_question'])
        p=plan('你好',proposal={'evidence_quote':'你好','strategy':'CLARIFY_IF_NEEDED','follow_up_need':'时间'})
        self.assertEqual(p['candidate_strategy'],'RESPOND_AND_YIELD')
    def test_whole_reply_is_not_deleted_into_silence(self):
        parts,check=xp.trim_excess(['你想玩？'],plan('要不要一起玩胡闹厨房？'))
        self.assertEqual(check['status'],'needs_repair');self.assertTrue(parts)
    def test_pragmatic_check_requires_exact_suffix(self):
        v={'sufficient':True,'unnecessary_followup':True,'premature_progression':False,'redundant_question':False,'drop_suffix_from':2,'quote':'什么时候？'}
        self.assertEqual(xp.pragmatic_check(v,'好。什么时候？')['drop_suffix_from'],2)
        with self.assertRaises(ValueError):xp.pragmatic_check({**v,'quote':'假的'},'好。什么时候？')
    def test_unknown_scores_are_unknown_not_imputed(self):
        self.assertTrue(all(v is None for v in plan('你好')['evaluation'].values()))

class Demonstrations(unittest.TestCase):
    def test_same_parent_quote_does_not_destroy_physical_burst_adjacency(self):
        rows=[{'id':str(i),'speaker':'other' if i==0 else 'target','text':'在吗' if i==0 else '在','timestamp':1700000000+i,'scope':'s','conversation_id':'c',**({'reply_to':'0'} if i else {})} for i in range(5)]
        data=pg.rebuild(None,parse_records(json.dumps(rows))[1:])
        self.assertEqual(pg.summary(data)['bubble_distribution'],{'4':1})

    def records(self):
        return parse_records(json.dumps([{'id':str(i),'speaker':'other' if i==0 else 'target','text':'要不要一起去？' if i==0 else '好啊','timestamp':1700000000+i,'scope':'private:qq:1','conversation_id':'c'} for i in range(5)]))
    def test_four_bubbles_are_one_independent_episode(self):
        p=pg.rebuild(None,self.records()[1:]);s=pg.summary(p)
        self.assertEqual(s['effective_episodes'],1);self.assertEqual(s['bubble_distribution'],{'4':1});self.assertEqual(s['fields']['burst_propensity']['support'],1)
    def test_duplicates_and_self_output_do_not_become_style_truth(self):
        records=self.records()[1:];p=pg.rebuild(None,records+records+[{'id':str(i),'source':'generated'} for i in range(100)])
        self.assertEqual(pg.summary(p)['effective_episodes'],1);self.assertEqual(pg.rebuild(p,records)['version'],p['version'])
    def test_no_timestamp_means_no_rhythm_training(self):
        records=self.records()[1:]
        for r in records:r['timestamp']=''
        s=pg.summary(pg.rebuild(None,records));self.assertEqual(s['untimed_records'],4);self.assertEqual(s['effective_episodes'],0);self.assertIsNone(s['fields']['burst_propensity']['estimate'])
    def test_interleaved_speaker_is_not_a_continuous_burst(self):
        records=self.records();records[2]['context_record_id']='unseen_other_message';records[2]['previous_record_id']='unseen_other_message';records[2]['context']='对方打断了'
        self.assertEqual(pg.summary(pg.rebuild(None,records[1:]))['effective_episodes'],2)
    def test_scope_isolation_and_no_fabricated_semantic_labels(self):
        p=pg.rebuild(None,self.records()[1:]);s=pg.summary(p,'private:qq:2')
        self.assertEqual(s['effective_episodes'],0);self.assertIsNone(pg.summary(p)['fields']['topic_progression_tendency']['estimate'])
    def test_three_sources_remain_separate(self):
        p=pg.rebuild(None,self.records()[1:]);p=pg.observe(p,'t',plan('hi'),['嗯'],[],'LOCAL_COMMITTED');p=pg.feedback(p,'t','unhelpful','多余追问')
        pg.validate(p);s=pg.status(p);self.assertEqual(s['profile']['effective_episodes'],1);self.assertEqual(s['human_feedback_count'],1);self.assertEqual(s['observed_ai_episodes'],1);self.assertIsNone(s['evaluation']['naturalness'])

class BurstProvider(PatchProvider):
    count=3
    def complete(self,messages,structured=False,controller=False):
        if '[REALIZE_V3]' in messages[0]['content']:
            self.calls.append({'stage':'[REALIZE_V3]','duration_ms':1})
            return json.dumps({'message_parts':[{'step_id':f's{i+1}','text':f'独立补充内容{i+1}。'} for i in range(self.count)]},ensure_ascii=False)
        return super().complete(messages,structured,controller)

class Delivery(Base):
    def setUp(self):
        super().setUp();self.enable();self.sent=[];self.hook=None;BurstProvider.count=3
        self.r.engine.provider_factory=BurstProvider;self.r.engine.pmm_provider_factory=BurstProvider
    def remote(self,url,payload=None,*args,**kwargs):
        if url.endswith('/get_login_info'):return {'retcode':0,'data':{'user_id':999}}
        self.sent.append(payload)
        if self.hook:self.hook(len(self.sent))
        return {'retcode':0,'status':'ok','data':{'message_id':90+len(self.sent)}}
    def process(self):
        self.r.bridge.receive(self.event())
        with patch('persona.qq.request_json',side_effect=self.remote):self.r.bridge.process(self.r.store.rows("SELECT * FROM inbox WHERE status='pending' LIMIT 1")[0])
    def assistant(self):return self.r.store.rows("SELECT * FROM messages WHERE role='assistant' ORDER BY created_at")
    def test_full_burst_has_three_history_rows_one_episode_one_training_group(self):
        self.process();self.assertEqual(len(self.sent),3);self.assertEqual(len(self.assistant()),3)
        self.assertEqual(self.r.store.meta('state')['turn_count'],1);self.assertEqual(len(self.r.store.meta('consolidation_queue')),1)
        self.assertEqual(self.r.engine.affect_state()['expressions'][-1]['actual_message_count'],3)
        run=self.r.engine.journal.recent()[0];self.assertEqual(run['qq_message_ids'],[91,92,93]);self.assertEqual(run['status'],'COMPLETED')
        self.assertEqual(len([m for m in self.r.store.memories() if m['kind']=='episode']),1)
    def test_each_ack_is_visible_before_next_remote_send(self):
        def hook(index):
            if index>1:self.assertEqual(len(self.assistant()),index-1)
        self.hook=hook;self.process();self.assertEqual(len(self.sent),3)
    def test_real_inbound_thread_interrupts_unsent_suffix_no_lock_deadlock(self):
        def hook(index):
            if index!=1:return
            worker=threading.Thread(target=lambda:self.r.bridge.receive(self.event(mid=2,message=[{'type':'text','data':{'text':'等一下，改天再说'}}])))
            worker.start();worker.join(2);self.assertFalse(worker.is_alive(),'store lock blocked inbound')
        self.hook=hook;before=digest(self.r.engine.model.export());self.process()
        self.assertEqual(len(self.sent),1);self.assertEqual(len(self.assistant()),1);self.assertEqual(digest(self.r.engine.model.export()),before)
        self.assertEqual(self.r.engine.journal.outbox()[0]['status'],'PARTIAL_COMMITTED')
        self.assertEqual(self.r.store.rows("SELECT COUNT(*) n FROM inbox WHERE status='pending'")[0]['n'],1)
        self.assertNotIn('独立补充内容2',json.dumps(self.r.store.memories(),ensure_ascii=False));queue=self.r.store.meta('consolidation_queue');self.assertEqual(len(queue),1);self.assertEqual(queue[0]['self_record']['text'],'独立补充内容1。');self.assertTrue(queue[0]['acknowledged_prefix_only'])
    def test_second_timeout_preserves_prefix_and_reconciliation_never_sends_tail(self):
        def hook(index):
            if index==2:raise TimeoutError('unknown after remote accepted')
        self.hook=hook;self.process();self.assertEqual(len(self.assistant()),1);j=self.r.engine.journal;row=j.outbox()[0];self.assertEqual(row['status'],'DELIVERY_UNKNOWN')
        ident=row['id'];record=j.delivery(ident);target=record['payload']['target'];message=record['payload']['messages'][1]
        j.acknowledge(ident,lambda:{'retcode':0,'data':{**target,'message':message,'message_id':92,'sender':{'user_id':999}}})
        self.r.engine.recover_delivered();self.assertEqual(len(self.sent),2);self.assertEqual(len(self.assistant()),2);self.assertEqual(self.r.store.meta('state')['turn_count'],1)
        self.assertEqual(j.outbox()[0]['status'],'PARTIAL_COMMITTED');self.assertEqual(len(self.r.store.meta('pmm_pragmatics')['observed_ai']),1)
        self.r.engine.recover_delivered();self.assertEqual(len(self.assistant()),2)
        with self.assertRaises(ValueError):self.r.bridge.retry_failed(self.r.store.rows('SELECT id FROM inbox')[0]['id'])
    def test_last_prefix_commit_crash_recovers_full_ack_once(self):
        original=self.r.engine.commit_prefix
        def crash(plan,index,receipt):
            if index==2:raise RuntimeError('disk interruption')
            original(plan,index,receipt)
        with patch.object(self.r.engine,'commit_prefix',side_effect=crash):self.process()
        self.assertEqual(len(self.sent),3);self.assertEqual(len(self.assistant()),2)
        self.r.engine.recover_delivered();self.assertEqual(len(self.assistant()),3);self.assertEqual(self.r.store.meta('state')['turn_count'],1);self.assertEqual([r['content'] for r in self.assistant()],['独立补充内容1。','独立补充内容2。','独立补充内容3。'])
        self.r.engine.recover_delivered();self.assertEqual(len(self.assistant()),3)
    def test_failed_second_call_is_distinct_from_natural_interrupt(self):
        original=self.remote
        def remote(url,payload=None,*a,**k):
            if len(self.sent)==1 and url.endswith('send_private_msg'):return {'retcode':1400,'status':'failed','data':{}}
            return original(url,payload,*a,**k)
        self.remote=remote;self.process();self.assertEqual(len(self.assistant()),1);self.assertEqual(self.r.engine.journal.recent()[0]['status'],'DELIVERY_PARTIAL')
    def test_new_state_does_not_overwrite_trained_traits_or_checkpoint(self):
        before=digest(self.r.engine.profile()['trait_profile']);self.process()
        self.assertEqual(before,digest(self.r.engine.profile()['trait_profile']));p=export_continuity(self.r.engine);validate_pack(p);self.assertIn('pragmatics',p)
    def test_model_call_budget_does_not_grow_per_bubble(self):
        BurstProvider.count=1;self.process();calls=len(self.r.engine.journal.recent()[0]['calls'])
        self.r.bridge.receive(self.event(mid=9))
        BurstProvider.count=4
        with patch('persona.qq.request_json',side_effect=self.remote):self.r.bridge.process(self.r.store.rows("SELECT * FROM inbox WHERE status='pending' LIMIT 1")[0])
        self.assertEqual(len(self.r.engine.journal.recent()[0]['calls']),calls)

class JournalRestart(unittest.TestCase):
    def test_crash_between_ack_and_next_send_is_known_interruption(self):
        with tempfile.TemporaryDirectory() as d:
            j=ExecutionJournal(Path(d));r=j.start('p','s',['e'],'scope');i=j.prepare(r,{'messages':[[{'type':'text','data':{'text':'1'}}],[{'type':'text','data':{'text':'2'}}]]},{'x':1})
            j.transition(i,'DISPATCHING',{'sent':[{'index':0,'message_id':1,'received_at':now()}],'in_flight':False});j.close();j=ExecutionJournal(Path(d))
            self.assertEqual(j.outbox()[0]['status'],'DELIVERY_INTERRUPTED');self.assertEqual(len(j.recoverable()),1);j.close()
    def test_h2_unknown_prefix_is_recoverable_without_resending(self):
        with tempfile.TemporaryDirectory() as d:
            j=ExecutionJournal(Path(d));r=j.start('p','s',['e'],'scope');i=j.prepare(r,{'messages':[[{'type':'text'}],[{'type':'text'}]]},{'x':1})
            j.transition(i,'DELIVERY_PARTIAL',{'sent':[{'index':0,'message_id':1,'received_at':now()}],'interrupted_at':1});j.close();j=ExecutionJournal(Path(d))
            self.assertEqual(j.recoverable()[0]['status'],'DELIVERY_PARTIAL');j.close()


class ExtendedContracts(unittest.TestCase):
    def test_ask_then_yield_never_sends_a_prearranged_answer(self):
        p=plan('最近有点想去看看');parts,_=xp.trim_excess(['想去看看？','那我们就定下来吧。'],p)
        self.assertEqual(parts,['想去看看？'])
    def test_future_dependency_requires_a_new_real_input(self):
        raw=json.dumps({'message_parts':[{'step_id':'a','text':'现在吗？','depends_on':'current_input'},{'step_id':'b','text':'那就现在。','depends_on':'user_reply'}]})
        self.assertEqual(xp.parse_message_parts(raw,plan('时间不确定','clarify'))[0],['现在吗？'])
    def test_conditioned_demonstrations_can_prefer_a_single_coherent_message(self):
        pgc={'fields':{'burst_propensity':{'effective_episodes':8,'estimate':0.}}}
        p=xp.decide_expression('你好',{'semantic':{}},{'action':'reply','decision_id':'d'}, {},{'familiarity':.2},1,1,pgc)
        self.assertEqual(p['message_plan']['max_bubbles'],1);self.assertIn('八个',p['split_reason'])
    def test_annotations_are_independent_and_revisions_not_extra_samples(self):
        records=Demonstrations().records()[1:];p=pg.rebuild(None,records);eid=p['demonstrations'][0]['id']
        p=pg.annotate(p,eid,'topic_progression_tendency',.8,'确有话题推进');p=pg.annotate(p,eid,'topic_progression_tendency',.6,'修订')
        self.assertEqual(pg.summary(p)['fields']['topic_progression_tendency']['effective_episodes'],1);pg.validate(p)
        with self.assertRaises(ValueError):pg.annotate(p,'generated-ai-turn','topic_progression_tendency',.5,'拒绝自举')
    def test_resegmented_annotation_archived_instead_of_silently_reused(self):
        records=Demonstrations().records()[1:];p=pg.rebuild(None,records[:2]);p=pg.annotate(p,p['demonstrations'][0]['id'],'ellipsis_and_understatement',.8,'原始两条示范')
        p=pg.rebuild(p,records);pg.validate(p);self.assertEqual(len(p['archived_annotations']),1);self.assertFalse(p['annotations'])
    def test_counterevidence_sampling_interval_and_unknown_validity_confidence(self):
        s=pg.ratio([{'question':False},{'question':True}],'question');self.assertEqual(s['estimate'],.5);self.assertEqual(s['counterevidence'],1);self.assertIsNone(s['confidence']);self.assertLess(s['sampling_interval'][0],.5)
    def test_social_distance_is_context_not_a_bubble_quota(self):
        outputs=[]
        for familiarity in (0,.9):
            p=xp.decide_expression('你好',{}, {'action':'reply','decision_id':'d'}, {},{'familiarity':familiarity},1,2,pg.summary(None));outputs.append(p)
        self.assertNotEqual(outputs[0]['interaction_state']['social_distance'],outputs[1]['interaction_state']['social_distance']);self.assertIsNone(outputs[1]['message_plan']['target_bubbles'])
    def test_affect_reference_never_changes_trait_reference(self):
        a=plan('你好');b=copy.deepcopy(a);b['affect_ref']=999
        self.assertEqual(a['trait_ref'],b['trait_ref']);self.assertNotEqual(a['affect_ref'],b['affect_ref'])

class LegacyReceiptRecovery(Base):
    process=Delivery.process
    remote=Delivery.remote
    assistant=Delivery.assistant
    def setUp(self):
        super().setUp();self.enable();self.sent=[];self.hook=None;BurstProvider.count=3
        self.r.engine.provider_factory=BurstProvider;self.r.engine.pmm_provider_factory=BurstProvider
    def test_h2_partial_plan_without_new_affect_restores_only_actual_prefix(self):
        def hook(index):
            if index==2:raise TimeoutError('unknown')
        self.hook=hook
        with patch.object(self.r.engine,'commit_partial_delivery',side_effect=RuntimeError('crash before partial local commit')):self.process()
        j=self.r.engine.journal;row=j.delivery(j.outbox()[0]['id']);old=copy.deepcopy(row['plan']);old.pop('interaction_plan');old['metadata'].pop('pmm_affect');old['trace'].pop('trait_affect')
        with j.lock,j.db:j.db.execute('UPDATE outbox SET plan=? WHERE id=?',(json.dumps(old),row['id']))
        before=digest(self.r.engine.model.export());self.r.engine.recover_delivered()
        self.assertEqual(len(self.assistant()),1);self.assertEqual(digest(self.r.engine.model.export()),before);self.assertEqual(self.r.store.meta('state')['turn_count'],1)

if __name__=='__main__':unittest.main()
