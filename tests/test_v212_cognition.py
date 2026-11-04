"""Behavioral regression fixtures for turn taking, group observation and memory."""
import copy, json, threading, unittest
from unittest.mock import patch
from pathlib import Path
from test_v212 import Base,PatchProvider
from persona.common import now,atomic_json
from persona.qq import QQBridge,parse_event
from persona.turn_taking import StaleTurn
from persona.packages import validate_pack,apply_pack
from persona.erasure import erase_scope,erase_preview

class CognitionBase(Base):
    def row(self):return self.r.store.rows("SELECT * FROM inbox WHERE status='pending' ORDER BY created_at LIMIT 1")[0]
    def remote(self,url,payload=None,*args,**kw):
        if url.endswith('/get_login_info'):return {'retcode':0,'data':{'user_id':999}}
        self.sent.append(payload);return {'retcode':0,'status':'ok','data':{'message_id':77}}
    def process(self):
        self.sent=[]
        with patch('persona.qq.request_json',side_effect=self.remote):self.r.bridge.process(self.row())
        return self.sent
    def receive(self,text,mid=1,user='123'):
        self.r.bridge.receive(self.event(user=user,mid=mid,message=[{'type':'text','data':{'text':text}}]))
    def control(self,action='REPLY',attention='ENGAGE',wait=2):
        class P(PatchProvider):
            def complete(self,messages,structured=False,controller=False):
                if '[TURN_TAKING_V212]' in messages[0]['content']:return {'action':action,'attention':attention,'wait_seconds':wait,'reason':'fixture'}
                return super().complete(messages,structured,controller)
        self.r.engine.pmm_provider_factory=P

class TurnTests(CognitionBase):
    def test_split_messages_merge_once_and_keep_raw(self):
        self.enable();self.receive('我大学时玩过一阵子',1);self.receive('现在偶尔也玩',2);sent=self.process()
        self.assertEqual(len(sent),1);self.assertEqual(self.r.store.meta('state')['turn_count'],1)
        self.assertIn('我大学时玩过一阵子\n现在偶尔也玩',self.r.store.history(self.r.store.sessions()[0]['id'])[0]['content'])
        rows=self.r.store.rows('SELECT * FROM inbox');self.assertEqual(len(rows),2);self.assertTrue(all(r['status']=='sent' for r in rows));self.assertTrue(all(json.loads(r['result'])['merged_count']==2 for r in rows))
    def test_generation_invalidated_by_new_fragment_without_commit_or_send(self):
        self.enable();self.receive('前半句',1);bridge=self.r.bridge;outer=self
        class P(PatchProvider):
            added=False
            def complete(self,messages,structured=False,controller=False):
                if '[REALIZE_V3]' in messages[0]['content'] and not P.added:P.added=True;outer.receive('后半句',2)
                return super().complete(messages,structured,controller)
        self.r.engine.provider_factory=P
        self.assertEqual(self.process(),[]);self.assertEqual(self.r.store.meta('state')['turn_count'],0);self.assertEqual(self.r.store.rows('SELECT * FROM messages'),[]);self.assertEqual(self.r.store.memories(),[])
        self.assertEqual(len(self.process()),1);self.assertEqual(self.r.store.meta('state')['turn_count'],1)
    def test_new_input_during_final_bot_check_also_invalidates(self):
        self.enable();self.receive('第一段');once=[]
        def check(url,*args,**kw):
            if url.endswith('/get_login_info'):once.append(True);self.receive('补充段',2);return {'retcode':0,'data':{'user_id':999}}
            self.fail('Superseded reply reached send endpoint')
        with patch('persona.qq.request_json',side_effect=check):self.r.bridge.process(self.row())
        self.assertEqual(len(once),1);self.assertEqual(self.r.store.meta('state')['turn_count'],0)
    def test_wait_is_persistent_and_bounded(self):
        self.enable();self.control('WAIT',wait=99);self.receive('还没说完')
        self.assertEqual(self.process(),[]);self.assertEqual(self.row()['status'],'pending')
        b=self.r.bridge.turn_taking.snapshot(self.row());self.assertLessEqual(b['due'],b['first']+12);self.assertFalse(self.r.bridge.turn_taking.ready(self.row()))
        with self.r.store.lock,self.r.store.db:
            bs=self.r.store.meta('turn_buffers');bs[b['key']]['first']=now()-13;self.r.store.setmeta('turn_buffers',bs)
        self.assertEqual(self.process(),[]);self.assertEqual(self.r.store.rows('SELECT status FROM inbox')[0]['status'],'awaiting_input')
    def test_no_action_never_enters_generation_or_learning(self):
        self.enable();self.control('NO_ACTION');self.receive('不用回复了');self.assertEqual(self.process(),[])
        self.assertEqual(self.r.store.meta('state')['turn_count'],0);self.assertEqual(self.r.store.rows('SELECT * FROM inbox')[0]['status'],'silent')
    def test_different_senders_and_explicit_threads_are_isolated(self):
        self.enable();self.r.configure({'qq':{'allowed_users':['123','456']}});self.receive('甲',1);self.receive('乙',2,'456')
        self.assertEqual(len([b for b in self.r.store.meta('turn_buffers').values() if b['ids']]),2)
        ev=self.event(mid=3,message=[{'type':'reply','data':{'id':'thread2'}},{'type':'text','data':{'text':'另一个话题'}}]);self.r.bridge.receive(ev)
        self.assertEqual(len([b for b in self.r.store.meta('turn_buffers').values() if b['ids']]),3)
    def test_duplicate_does_not_advance_version_and_terminal_cannot_resend(self):
        self.enable();self.receive('一条');row=self.row();b=self.r.bridge.turn_taking.snapshot(row);self.receive('一条');self.assertTrue(self.r.bridge.turn_taking.valid(b));self.process()
        with patch('persona.qq.request_json') as remote:self.r.bridge.process(row);remote.assert_not_called()
    def test_restart_does_not_replay_ambiguous_processing(self):
        self.enable();self.receive('一条');row=self.row();self.r.store.inbox_update(row['id'],'interrupted',{'message':'already dispatched maybe'})
        bridge=QQBridge(self.r.engine);self.assertTrue(all(not b['ids'] for b in self.r.store.meta('turn_buffers').values()))
        bridge.receive(self.event(mid=2));self.assertEqual(sum(len(b['ids']) for b in self.r.store.meta('turn_buffers').values()),1)
    def test_failed_send_has_no_committed_assistant_or_memory(self):
        self.enable();self.receive('一条')
        with patch('persona.qq.request_json',side_effect=ValueError('transport failure')):self.r.bridge.process(self.row())
        self.assertEqual(self.r.store.meta('state')['turn_count'],0);self.assertFalse(self.r.store.rows('SELECT * FROM messages'));self.assertEqual(self.r.store.rows('SELECT * FROM inbox')[0]['status'],'failed')
    def test_oversized_aggregate_is_held_without_truncation(self):
        self.enable();self.receive('甲'*9000,1);self.receive('乙'*9000,2);self.assertEqual(self.process(),[])
        self.assertTrue(all(r['status']=='held' for r in self.r.store.rows('SELECT * FROM inbox')));self.assertEqual(len(self.r.store.rows('SELECT * FROM inbox')),2)

class GroupTests(CognitionBase):
    def setup_group(self,reply=False):
        self.r.configure({'qq':{'enabled':True,'self_id':'999','allowed_groups':['321']},'group_attention':{'enabled':True,'allow_unmentioned_reply':reply,'sample_every':1}})
    def group_event(self,text,mid=1,user='123',at=False,thread=None):
        msg=[{'type':'text','data':{'text':text}}]
        if at:msg.insert(0,{'type':'at','data':{'qq':'999'}})
        if thread:msg.insert(0,{'type':'reply','data':{'id':thread}})
        ev=self.event(mid=mid,user=user,message=msg);ev.update(message_type='group',group_id=321);return ev
    def test_observation_keeps_stranger_and_does_not_feed_social_contact(self):
        self.setup_group();self.control('NO_ACTION','ATTEND');ev=self.group_event('我很喜欢下棋');self.assertTrue(self.r.bridge.receive(ev)['accepted']);self.assertEqual(self.process(),[])
        self.assertEqual(self.r.store.meta('state')['turn_count'],0);self.assertFalse(self.r.store.meta('pmm_dyads'));self.assertFalse(self.r.store.meta('social_contacts'))
        p=self.r.engine.group_attention.status()['people'][0];self.assertEqual(p['direct_interactions'],0);self.assertIn('陌生人',p['relationship']);self.assertTrue(self.r.engine.memory_lifecycle.status()['pending'])
    def test_model_cannot_override_unmentioned_reply_permission(self):
        self.setup_group();self.control('REPLY','ENGAGE');self.r.bridge.receive(self.group_event('来聊聊'));self.assertEqual(self.process(),[])
        self.assertEqual(self.r.store.meta('state')['turn_count'],0)
    def test_uninvited_engagement_does_not_create_mutual_familiarity(self):
        self.setup_group(True);self.r.bridge.receive(self.group_event('来聊聊'));self.assertEqual(len(self.process()),1)
        self.assertTrue(all(d['interactions']==0 and d['familiarity']==0 and d['trust'] is None for d in self.r.store.meta('pmm_dyads').values()))
        self.r.engine.consolidation.run();self.assertTrue(all(d['interactions']==0 for d in self.r.store.meta('pmm_dyads').values()))
    def test_addressed_interaction_counts_once_and_bypasses_passive_budget(self):
        self.setup_group();self.r.configure({'group_attention':{'per_minute':1}})
        self.r.bridge.receive(self.group_event('旁观',1));self.process();self.r.bridge.receive(self.group_event('问你呢',2,at=True));self.assertEqual(len(self.process()),1)
        self.assertEqual(list(self.r.store.meta('pmm_dyads').values())[0]['interactions'],1)
    def test_attention_budget_and_thread_context(self):
        self.setup_group();self.r.configure({'group_attention':{'per_minute':1}});self.control('NO_ACTION','ATTEND')
        first=self.group_event('第一条',1,thread='10');self.r.bridge.receive(first);self.process();self.r.bridge.receive(self.group_event('第二条',2,thread='20'));self.process()
        obs=self.r.store.meta('group_observations')['group:qq:321'];self.assertEqual(len(obs),1)
        p=parse_event(self.group_event('查询',3,thread='20'),self.r.config.get());self.assertEqual(self.r.engine.group_attention.context(p),[])
    def test_group_off_preserves_mention_only_behavior(self):
        self.r.configure({'qq':{'enabled':True,'allowed_groups':['321']}});self.assertFalse(self.r.bridge.receive(self.group_event('旁观'))['accepted'])

class MemoryTests(CognitionBase):
    def test_gist_has_exact_sources_preserves_raw_and_roundtrips(self):
        sid=self.session();out=self.turn('这是需要保留的完整原话。',sid);before=self.r.store.history(sid)
        r=self.r.engine.memory_lifecycle.run();self.assertEqual(r['processed'],1);m=next(m for m in self.r.store.memories() if m['kind']=='gist')
        src=self.r.engine.memory_lifecycle.sources(m['id']);self.assertEqual(src['records'][0]['source_text'],'这是需要保留的完整原话。');self.assertEqual(before,self.r.store.history(sid))
        pack=self.r.subjects.export_pack(self.r.engine);validated=validate_pack(pack);self.assertEqual(validated[0]['memory_traces'][m['id']]['sources'][0]['source_text'],'这是需要保留的完整原话。')
    def test_fabricated_evidence_fails_atomically_and_retains_queue(self):
        self.turn();before=self.r.store.memories()
        class P(PatchProvider):
            def complete(self,messages,structured=False,controller=False):
                out=super().complete(messages,structured,controller)
                if '[MEMORY_GIST_V212]' in messages[0]['content']:out['items'][0]['evidence'][0]['quote']='不存在的证据'
                return out
        self.r.engine.pmm_provider_factory=P
        with self.assertRaises(ValueError):self.r.engine.memory_lifecycle.run()
        self.assertEqual(before,self.r.store.memories());self.assertEqual(self.r.engine.memory_lifecycle.status()['failed'],1)
        self.r.engine.pmm_provider_factory=PatchProvider;self.assertEqual(self.r.engine.memory_lifecycle.run(retry=True)['processed'],1)
    def test_batch_isolates_scope_speaker_and_thread(self):
        self.turn('甲',self.session('123'));self.turn('乙',self.session('456'));self.r.engine.memory_lifecycle.run()
        queue=self.r.store.meta('memory_pending');self.assertEqual(len(queue),1);self.assertEqual(queue[0]['scope'],'private:qq:456')
        call=next(m for m in PatchProvider.seen if '[MEMORY_GIST_V212]' in m[0]['content']);self.assertNotIn('乙',call[-1]['content'])
    def test_decay_affects_retrieval_not_storage_or_deletion(self):
        self.turn();m=self.r.store.memories()[0];life=self.r.engine.memory_lifecycle;a=life.strength(m,m['created_at']);b=life.strength(m,m['created_at']+86400*365)
        self.assertLess(b['retrieval_strength'],a['retrieval_strength']);self.assertEqual(a['storage_strength'],b['storage_strength']);self.assertEqual(self.r.store.memories()[0]['status'],'active')
        with self.r.store.lock,self.r.store.db:life.touch([{**m,'relevance':1}])
        self.assertGreater(life.strength(m)['storage_strength'],a['storage_strength']);self.assertEqual(life.strength(m)['accesses'],1)
    def test_irrelevant_candidates_do_not_rehearse(self):
        self.turn();m=self.r.store.memories()[0]
        with self.r.store.lock,self.r.store.db:self.r.engine.memory_lifecycle.touch([{**m,'relevance':0}])
        self.assertEqual(self.r.engine.memory_lifecycle.strength(m)['accesses'],0)
    def test_source_scope_and_observed_group_survive_gist(self):
        policy=self.r.engine.learning.status()['policy'];policy['domains']['memory'].update(allow_group_observation=True,scopes=['group:qq:321'],people=['qq:123'])
        self.r.engine.learning.save_policy({'policy':policy,'expected_version':policy['version']})
        with self.r.store.lock,self.r.store.db:self.r.engine.memory_lifecycle.enqueue([{'id':'qq:one','text':'我喜欢下棋'}],'group:qq:321','qq:123','t','observed_group')
        self.r.engine.memory_lifecycle.run();m=self.r.store.memories()[0];self.assertEqual(m['scope'],'group:qq:321');self.assertEqual(self.r.engine.memory_lifecycle.strength(m)['source_type'],'observed_group');self.assertFalse(self.r.store.meta('pmm_dyads'))
    def test_restore_during_network_rejects_old_gist(self):
        self.turn();snapshot=self.r.store.snapshot();started=threading.Event();release=threading.Event();errors=[]
        class P(PatchProvider):
            def complete(self,messages,structured=False,controller=False):
                if '[MEMORY_GIST_V212]' in messages[0]['content']:started.set();release.wait(3)
                return super().complete(messages,structured,controller)
        self.r.engine.pmm_provider_factory=P
        def worker():
            try:self.r.engine.memory_lifecycle.run()
            except ValueError as ex:errors.append(ex)
        t=threading.Thread(target=worker);t.start();self.assertTrue(started.wait(2));self.r.store.restore(snapshot);release.set();t.join(3)
        self.assertTrue(errors);self.assertFalse(any(m['kind']=='gist' for m in self.r.store.memories()));self.assertEqual(self.r.engine.memory_lifecycle.status()['pending'],1)
    def test_invalid_continuity_memory_state_rejected(self):
        self.turn();p=self.r.subjects.export_pack(self.r.engine);p['memory_state']['pending'][0]['records'][0]['text']=3
        with self.assertRaises(ValueError):validate_pack(p)
    def test_explicit_erasure_removes_raw_derived_versions_and_resets_learning(self):
        self.enable();self.receive('ERASE_SECRET_ABC');self.process();self.r.engine.memory_lifecycle.run();self.turn('保留另一范围的原话',self.session('456'))
        self.r.subjects.save_revision(self.r.engine,'before');self.r.engine.save_weight_version('before')
        atomic_json(self.r.store.directory/'backups'/'before_restore_1.json',self.r.snapshot())
        with self.assertRaises(ValueError):erase_scope(self.r.engine,'private:qq:123','wrong')
        self.assertIn('ERASE_SECRET_ABC',json.dumps(self.r.snapshot()))
        result=erase_scope(self.r.engine,'private:qq:123','ERASE:private:qq:123');self.assertTrue(result['learning_reset'])
        self.assertNotIn('ERASE_SECRET_ABC',json.dumps(self.r.snapshot()));self.assertEqual(self.r.store.rows('SELECT * FROM inbox'),[]);self.assertEqual(self.r.store.meta('state')['turn_count'],0)
        self.assertTrue(self.r.store.rows('SELECT * FROM messages'));self.assertEqual(self.r.subjects.revision_files(self.r.engine).list(),[]);self.assertEqual(self.r.engine.weight_files().list(),[])
        self.assertFalse((self.r.store.directory/'backups'/'before_restore_1.json').exists());validate_pack(self.r.subjects.export_pack(self.r.engine))
    def test_new_settings_invalid_values_are_rejected(self):
        for patchvalue in [{'turn_taking':{'max_wait_seconds':99}},{'group_attention':{'per_minute':.5}},{'group_attention':{'allow_unmentioned_reply':True}},{'memory':{'half_life_days':float('nan')}}]:
            with self.assertRaises(ValueError):self.r.config.update(patchvalue)

class CognitionHTTPTests(unittest.TestCase):
    from test_api import APITests as _API
    setUp=_API.setUp
    tearDown=_API.tearDown
    request=_API.request
    job=_API.job
    def test_forms_gist_sources_and_explicit_erasure_over_real_http(self):
        import urllib.parse,urllib.error
        self.app.config.update({'pmm':{'mode':'api','api':{'model':'fixture'}}})
        self.app.engine.provider_factory=PatchProvider;self.app.engine.pmm_provider_factory=PatchProvider
        self.request('/api/config',{'turn_taking':{'debounce_seconds':2},'memory':{'half_life_days':40},'group_attention':{'enabled':True,'watched_terms':['下棋']}})
        state=self.request('/api/state');self.assertEqual(state['config']['turn_taking']['debounce_seconds'],2);self.assertIn('memory_lifecycle',state)
        sid=self.app.store.session();self.app.engine.turn(sid,'HTTP 私密测试原文')
        self.assertEqual(self.job(self.request('/api/memory/consolidate',{'retry':True}))['processed'],1)
        memories=self.request('/api/memories');m=next(m for m in memories if m['kind']=='gist');self.assertIn('retrieval_strength',m['memory_strength'])
        self.assertEqual(self.request('/api/memory/sources?id='+m['id'])['records'][0]['source_text'],'HTTP 私密测试原文')
        p=self.request('/api/memory/erase-preview?scope='+urllib.parse.quote(m['scope']));self.assertEqual(p['messages'],2)
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/memory/erase',{'scope':m['scope'],'confirmation':'wrong'})
        self.request('/api/memory/erase',{'scope':m['scope'],'confirmation':p['confirmation']});self.assertEqual(self.request('/api/memories'),[])

class PersistenceAndCostTests(CognitionBase):
    def test_raw_qq_backup_retains_fragments_and_never_replays_processing(self):
        self.enable();self.receive('原片段甲',1);self.receive('原片段乙',2);rows=self.r.store.rows('SELECT * FROM inbox')
        self.r.store.inbox_update(rows[0]['id'],'processing',{'phase':'可能已发出'})
        snap=self.r.store.snapshot();self.assertEqual(len(snap['qq_inbox']),2);self.r.store.restore(snap)
        bridge=QQBridge(self.r.engine);restored=self.r.store.rows('SELECT * FROM inbox');self.assertEqual(restored[0]['status'],'interrupted')
        self.assertIn('原片段甲',restored[0]['payload']);self.assertEqual(sum(len(b['ids']) for b in self.r.store.meta('turn_buffers').values()),1)
    def test_legacy_snapshot_without_raw_inbox_still_restores(self):
        self.turn();snap=self.r.store.snapshot();snap.pop('qq_inbox');self.r.store.restore(snap)
        self.assertEqual(self.r.store.meta('state')['turn_count'],1);self.assertEqual(self.r.store.rows('SELECT * FROM inbox'),[])
    def test_large_memory_list_reads_strength_metadata_once(self):
        self.turn();memory=self.r.store.memories()[0];rows=[{**memory,'id':str(i)} for i in range(500)]
        with patch.object(self.r.store,'meta',wraps=self.r.store.meta) as read:
            described=self.r.engine.memory_lifecycle.describe(rows)
        self.assertEqual(len(described),500);self.assertEqual(sum(c.args==('memory_traces',) for c in read.call_args_list),1)

if __name__=='__main__':unittest.main()
