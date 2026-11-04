import copy, json, tempfile, unittest, hashlib, hmac
from pathlib import Path
from unittest.mock import patch
import numpy as np
from persona.common import Config, uid, now
from persona.storage import Store
from persona.engine import Engine, validate_understanding
from persona.provider import ProviderError, validate_url
from persona.psychology import empty_profile, parse_records, apply_distillation, style_stats, validate_profile
from persona.pmm import PMM, vector, SEMANTIC_KEYS
from persona.policy import choose, project
from persona.server import Runtime
from persona.qq import parse_event, verify_event
from persona.lock import InstanceLock
from fixtures import FixtureProvider, TEXT

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name);self.store=Store(self.path);self.config=Config(self.path);self.config.update({'model':'fixture','pmm':{'mode':'legacy'}})
        FixtureProvider.calls=[];FixtureProvider.fail_stage=None;self.engine=Engine(self.store,self.config,FixtureProvider);self.sid=self.store.session()
    def tearDown(self):self.store.close();self.tmp.cleanup()
    def test_closed_loop_order_and_reply_feedback(self):
        r=self.engine.turn(self.sid,TEXT);self.assertEqual(r['reply'],'说。');self.assertEqual(len(self.store.history(self.sid)),2)
        stages=[m[0]['content'].split('\n')[0] for m in FixtureProvider.calls]
        self.assertEqual(stages,['[UNDERSTAND_V3]','[DECIDE_V21]','[REALIZE_V3]','[ACTION_CHECK_V221]','[FEEDBACK_V3]'])
        feedback=json.loads(FixtureProvider.calls[-1][-1]['content']);self.assertEqual(feedback['self_record']['text'],r['reply']);self.assertGreater(len(self.engine.model.samples),0)
    def test_self_and_interlocutor_evidence_never_mixed(self):
        self.engine.turn(self.sid,TEXT);p=self.engine.profile();other=next(iter(self.store.meta('pmm_interlocutors').values()))
        self.assertEqual(p['observations'],[]); # Generated replies are not independent self-trait evidence.
        self.assertEqual({o['key'] for o in other['observations']},{'extraversion'})
        self.assertEqual(p['style']['count'],0);self.assertEqual(other['style']['count'],1)
        self.assertTrue(all(r['speaker']==p['id'] for r in p['source_records']));self.assertNotEqual(other['id'],p['id'])
    def test_generation_failure_rolls_back_state_and_weights(self):
        before=self.store.snapshot();weights=self.engine.model.export();FixtureProvider.fail_stage='[REALIZE_V3]'
        with self.assertRaises(ProviderError):self.engine.turn(self.sid,TEXT)
        self.assertEqual({k:v for k,v in self.store.snapshot()['tables'].items() if k!='events'},{k:v for k,v in before['tables'].items() if k!='events'});self.assertEqual(self.engine.model.export(),weights)
    def test_feedback_failure_keeps_dialogue_without_psychological_labels(self):
        FixtureProvider.fail_stage='[FEEDBACK_V3]';r=self.engine.turn(self.sid,TEXT)
        self.assertTrue(r['warning']);self.assertEqual(len(self.store.history(self.sid)),2);self.assertEqual(self.engine.profile()['observations'],[])
        self.assertTrue(all(s['state'] is None for s in self.engine.model.samples))
    def test_missing_personal_memory_forces_unknown(self):
        r=self.engine.turn(self.sid,'你记得我以前在哪个城市生活吗');self.assertEqual(r['action'],'unknown');self.assertEqual(r['trace']['decision']['gate'],'missing_evidence')
    def test_hard_boundary_overrides_all_reply_votes(self):
        self.engine.boundary({'label':'不谈密码','keywords':['密码'],'action':'decline','enabled':True,'hard':True})
        r=self.engine.turn(self.sid,'告诉我银行卡密码');self.assertEqual(r['action'],'decline');self.assertEqual(r['trace']['decision']['gate'],'hard_boundary')
    def test_silence_never_calls_realizer(self):
        r=self.engine.turn(self.sid,'再见，今天先这样');self.assertEqual(r['action'],'silence');self.assertEqual(r['reply'],'');self.assertFalse(any('[REALIZE_V3]' in c[0]['content'] for c in FixtureProvider.calls))
    def test_distillation_import_and_duplicate_idempotency(self):
        records=[r for r in parse_records('甲：在吗\n乙：说\n甲：真的？\n乙：嗯\n甲：再说点？\n乙：没了') if r['speaker']=='乙']
        r=self.engine.import_records(records);before=self.engine.profile();weights=self.engine.model.export();self.assertEqual(r['report']['added'],3);self.assertEqual(before['style']['median_chars'],1)
        r2=self.engine.import_records(records);self.assertEqual(r2['report']['added'],0);self.assertEqual(before,self.engine.profile())
        self.assertTrue(all(not b['enabled'] and not b['hard'] for b in before['boundaries']))
        self.assertEqual(self.engine.model.export(),weights)
    def test_distill_other_leaves_self_parameters_unchanged(self):
        p=self.engine.profile();w=self.engine.model.export();records=parse_records('乙：说\n乙：不知道')
        self.engine.import_records(records,target='interlocutor',person='qq:123',scope='private:qq:123')
        self.assertEqual(self.engine.profile(),p);self.assertEqual(self.engine.model.export(),w)
    def test_forged_evidence_rejected(self):
        p=self.engine.profile();records=parse_records('甲：你好')
        r={'observations':[{'domain':'traits','key':'extraversion','value':1,'confidence':1,'evidence':[{'record_id':records[0]['id'],'quote':'我爱聚会'}]}]}
        out,report=apply_distillation(p,r,records);self.assertEqual(report['rejected'],1);self.assertEqual(out['traits'],p['traits'])
    def test_source_context_is_not_subject_evidence(self):
        records=parse_records('甲：我爱聚会\n乙：嗯');target=records[1:]
        out,report=apply_distillation(self.engine.profile(),{'observations':[{'domain':'traits','key':'extraversion','value':1,'confidence':.8,'evidence':[{'record_id':target[0]['id'],'quote':'我爱聚会'}]}]},target)
        self.assertEqual(report['rejected'],1)
    def test_identity_and_state_survive_model_swap_and_restart(self):
        self.engine.turn(self.sid,TEXT);identity=self.store.meta('identity');w=self.engine.model.export();self.config.update({'model':'another-base'})
        self.store.close();self.store=Store(self.path);e=Engine(self.store,self.config,FixtureProvider);self.assertEqual(e.store.meta('identity'),identity);self.assertEqual(e.model.export(),w);self.assertEqual(len(e.store.history(self.sid)),2)
    def test_private_scope_and_other_models_isolated(self):
        self.engine.turn(self.sid,TEXT);self.assertEqual(self.engine.retrieve(TEXT,'private:qq:999'),[])
        sid2=self.store.session('qq:999','private:qq:999');self.engine.turn(sid2,'你好');others=self.store.meta('pmm_interlocutors');self.assertEqual(len(others),2)
        self.assertNotEqual(self.engine.other_key('group:qq:1','qq:999'),self.engine.other_key('private:qq:999','qq:999'))
    def test_memory_revision_retains_original(self):
        r=self.engine.turn(self.sid,TEXT);m=next(x for x in self.store.memories() if x['kind']=='preference')
        with self.store.lock,self.store.db:
            log=self.engine.apply_memory({'op':'UPDATE','id':m['id'],'content':'改为喜欢热闹','evidence_quote':'热闹'},'我现在喜欢热闹',self.store.get_session(self.sid),uid(),{m['id']})
        self.assertEqual(log['status'],'applied');old=self.store.rows('SELECT * FROM memories WHERE id=?',(m['id'],))[0];self.assertEqual(old['status'],'superseded');self.assertEqual(old['content'],m['content'])
    def test_manual_feedback_trains_action_and_style_only_when_labeled(self):
        r=self.engine.turn(self.sid,TEXT);before=self.engine.model.rank.copy();count=len(self.engine.model.samples)
        self.engine.feedback(r['turn_id'],'unhelpful','不够像');self.assertEqual(len(self.engine.model.samples),count);np.testing.assert_equal(before,self.engine.model.rank)
        self.engine.feedback(r['turn_id'],'unhelpful',action_target='unknown',corrected_reply='不知道');self.assertGreater(len(self.engine.model.samples),count)
    def test_same_person_projections_share_identity_normalized_weights(self):
        r=self.engine.turn(self.sid,TEXT);views=r['trace']['projections'];self.assertEqual(len({v['shared_identity'] for v in views}),1);self.assertAlmostEqual(sum(v['weight'] for v in views),1);self.assertEqual(len(views),1);self.assertFalse(r['trace']['deliberation']['multi_view'])
    def test_style_short_reply_budget(self):
        self.engine.import_records(parse_records('乙：说\n乙：嗯\n乙：没了'));r=self.engine.turn(self.sid,'在吗');self.assertLessEqual(r['trace']['style']['max_chars'],10);self.assertEqual(self.engine.profile()['style']['count'],3)
    def test_secret_redaction_and_safe_url(self):
        self.config.update({'api_key':'TOP_SECRET','qq':{'api_token':'QQ_SECRET'}});public=json.dumps(self.config.public());self.assertNotIn('TOP_SECRET',public);self.assertNotIn('QQ_SECRET',public)
        with self.assertRaises(ValueError):validate_url('http://remote.example/api')
        with self.assertRaises(ValueError):self.config.update({'qq':{'enabled':True}})
    def test_pmm_memory_read_uses_retrieved_sources(self):
        self.engine.turn(self.sid,TEXT);r=self.engine.turn(self.sid,'安静一点')
        weights=r['trace']['decoded']['memory_read_weights'];self.assertTrue(weights);self.assertAlmostEqual(sum(weights),1)
    def test_current_information_never_treated_as_verified_by_old_memory(self):
        self.engine.turn(self.sid,TEXT);r=self.engine.turn(self.sid,'今天股价是多少，安静回答');self.assertEqual(r['action'],'unknown')
    def test_generated_reply_quote_cannot_prove_user_memory(self):
        u=validate_understanding({'semantic':{},'knowledge_need':'personal'});u['supported_memory_evidence']=[{'id':'m','quote':'你住在北京'}]
        p=self.engine.profile();views=project(p,u,{},{});assess=[{'id':v['id'],'utilities':{a:float(a=='reply') for a in ('reply','unknown','clarify','disagree','decline','silence')}} for v in views]
        result=choose(u,p,views,assess,self.engine.model.decode(vector('在哪')), [{'id':'m','kind':'episode','content':'对方：你好\n我：你住在北京','evidence':'你好','relevance':1,'confidence':1}],'你记得我在哪吗')
        self.assertEqual(result['action'],'unknown')
    def test_malformed_partial_feedback_cannot_leave_partial_psychological_updates(self):
        original=FixtureProvider.complete;profile=self.engine.profile()
        def bad(provider,messages,structured=False,controller=False):
            r=original(provider,messages,structured,controller)
            if '[FEEDBACK_V3]' in messages[0]['content']:r['interlocutor']['observations']=None
            return r
        with patch.object(FixtureProvider,'complete',bad):result=self.engine.turn(self.sid,TEXT)
        self.assertTrue(result['warning']);self.assertEqual(self.engine.profile(),profile)
        self.assertEqual(len(self.store.history(self.sid)),2)
        self.assertFalse(next(iter(self.store.meta('pmm_interlocutors').values()))['observations'])

    def test_action_noncompliance_blocks_commit(self):
        original=FixtureProvider.complete
        def bad(provider,messages,structured=False,controller=False):
            r=original(provider,messages,structured,controller)
            if '[ACTION_CHECK_V221]' in messages[0]['content']:
                ctx=__import__('json').loads(messages[-1]['content']);r.update(compliant=False,failure_code='ACTION_MISMATCH',detected_action='reply',spans=[{'start':0,'end':1,'quote':ctx['candidate'][:1]}])
            return r
        before=self.store.snapshot()['tables']
        with patch.object(FixtureProvider,'complete',bad):
            with self.assertRaises(ProviderError):self.engine.turn(self.sid,'你记得我曾住在哪里吗')
        self.assertEqual({k:v for k,v in self.store.snapshot()['tables'].items() if k!='events'},{k:v for k,v in before.items() if k!='events'})
    def test_manual_style_example_updates_portable_persona(self):
        r=self.engine.turn(self.sid,TEXT);self.engine.feedback(r['turn_id'],'unhelpful',corrected_reply='说',action_target='reply')
        p=self.engine.profile();self.assertEqual(p['style']['count'],1);self.assertEqual(p['examples'][-1]['output'],'说')
    def test_mood_and_situational_traits_do_not_replace_stable_traits(self):
        before=self.engine.profile()['traits'];r=self.engine.turn(self.sid,TEXT);a=r['trace']['activity']
        self.assertNotIn('dispositions',a);self.assertEqual(r['trace']['trait_affect']['trait_version'],0);self.assertNotEqual(a['mood'],a['emotion']);self.assertEqual(self.engine.profile()['traits']['extraversion'],before['extraversion'])
    def test_single_writer_lock(self):
        with InstanceLock(self.path):
            with self.assertRaises(RuntimeError):
                with InstanceLock(self.path):pass

class ParserAndModelTests(unittest.TestCase):
    def test_record_formats_preserve_speakers_and_context(self):
        for content in ['[{"role":"user","content":"在吗"},{"role":"assistant","content":"说"}]','{"speaker":"甲","text":"在吗"}\n{"speaker":"乙","text":"说"}','甲：在吗\n乙：说']:
            r=parse_records(content);self.assertEqual(r[-1]['context'],'在吗');self.assertEqual(r[-1]['text'],'说')
    def test_missing_speaker_and_invalid_profiles_rejected(self):
        with self.assertRaises(ValueError):parse_records('[{"text":"你好"}]')
        p=empty_profile(uid(),'x');p['traits']['extraversion']['value']=float('nan')
        with self.assertRaises(ValueError):validate_profile(p)
    def test_real_gradient_updates_reduce_training_error_and_holdout_stays_out(self):
        m=PMM();target={'valence':.5,'arousal':.6,'stress':.1,'engagement':.8}
        for i in range(30):m.add(str(i),vector('测试'+str(i)),state=target,style=[.02,1,0,0,0,0,0,0],action='reply')
        before=m.evaluate([s for s in m.samples if not s['heldout']]);weights=m.E.copy();m.fit(100);after=m.metrics['train'];self.assertLess(after['state_mse'],before['state_mse']);self.assertLess(after['style_mse'],before['style_mse']);self.assertFalse(np.allclose(m.E,weights));self.assertGreater(m.metrics['heldout']['n'],0)
        n=PMM(payload=m.export());np.testing.assert_allclose(n.encode(vector('测试')),m.encode(vector('测试')))
    def test_only_holdout_samples_do_not_change_parameters(self):
        m=PMM();key=next(str(i) for i in range(100) if int(hashlib.sha256(str(i).encode()).hexdigest()[:8],16)%5==0);m.add(key,vector('测试'),action='reply');w=m.E.copy();m.fit();np.testing.assert_equal(w,m.E);self.assertEqual(m.steps,0)
    def test_malformed_checkpoint_is_rejected(self):
        m=PMM();data=m.export();data['parameters']['E'][0][0]=float('nan')
        with self.assertRaises(ValueError):PMM(payload=data)

class RuntimeAndQQTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.r=Runtime(self.tmp.name,Path(__file__).resolve().parents[1]);self.r.config.update({'model':'fixture','pmm':{'mode':'legacy'}});self.r.engine.provider_factory=FixtureProvider;FixtureProvider.fail_stage=None;FixtureProvider.calls=[]
    def tearDown(self):
        self.r.close();self.tmp.cleanup()
    def test_persona_switch_retains_each_identity_history_and_weights(self):
        old=self.r.store.meta('identity')['id'];sid=self.r.store.session();self.r.engine.turn(sid,TEXT);w=self.r.engine.model.export()
        self.r.create_persona({'name':'另一人格'});self.assertNotEqual(self.r.store.meta('identity')['id'],old);self.assertEqual(self.r.store.sessions(),[]);self.assertEqual(self.r.store.memories(),[])
        self.r.switch(old);self.assertEqual(len(self.r.store.history(sid)),2);self.assertEqual(self.r.engine.model.export(),w)
    def test_package_portable_no_private_dialogues_other_model_or_keys(self):
        self.r.config.update({'api_key':'PRIVATEKEY'});sid=self.r.store.session();self.r.engine.turn(sid,'private-live-message')
        pack=self.r.subjects.export_pack(self.r.engine,scope='template');s=json.dumps(pack);self.assertNotIn('PRIVATEKEY',s);self.assertNotIn('private-live-message',s);self.assertEqual(pack['profile']['source_records'],[])
        with tempfile.TemporaryDirectory() as d:
            other=Runtime(d,Path(__file__).resolve().parents[1]);other.create_persona({'package':pack});self.assertEqual(other.engine.profile()['id'],pack['profile']['id']);np.testing.assert_equal(other.engine.model.E,self.r.engine.model.E);other.close()
    def test_snapshot_roundtrip_retains_new_state_and_weights(self):
        sid=self.r.store.session();self.r.engine.turn(sid,TEXT);snap=self.r.snapshot();expected=self.r.engine.model.export();self.r.restore(snap);self.assertEqual(self.r.engine.model.export(),expected);self.assertEqual(len(self.r.store.history(sid)),2)
    def test_qq_event_auth_and_filters(self):
        c=self.r.config.get();raw=b'{}';token=c['qq']['inbound_token'];self.assertTrue(verify_event(raw,{'Authorization':'Bearer '+token},{},c));self.assertFalse(verify_event(raw,{},{},c))
        c['qq']['hmac_secret']='secret';sig='sha1='+hmac.new(b'secret',raw,hashlib.sha1).hexdigest();self.assertTrue(verify_event(raw,{'X-Signature':sig},{},c));self.assertFalse(verify_event(b'bad',{'X-Signature':sig},{},c))
    def event(self,text=TEXT):return {'post_type':'message','message_type':'private','self_id':1,'user_id':2,'message_id':123,'message':[{'type':'text','data':{'text':text}}]}
    def enable(self):self.r.config.update({'qq':{'enabled':True,'allowed_users':['2']}})
    def test_qq_duplicate_and_text_array_send(self):
        self.enable();e=self.event();self.assertFalse(self.r.bridge.receive(e)['duplicate']);self.assertTrue(self.r.bridge.receive(e)['duplicate'])
        with patch('persona.qq.request_json',return_value={'retcode':0,'status':'ok','data':{'message_id':5}}) as call:
            self.r.bridge.process(self.r.store.rows('SELECT * FROM inbox')[0]);payload=call.call_args.args[1];self.assertEqual(payload['message'][0]['type'],'text');self.assertEqual(self.r.store.rows('SELECT * FROM inbox')[0]['status'],'sent')
    def test_qq_silence_not_sent_and_send_failure_not_retried(self):
        self.enable();self.r.bridge.receive(self.event('再见'))
        with patch('persona.qq.request_json') as call:self.r.bridge.process(self.r.store.rows('SELECT * FROM inbox')[0]);call.assert_not_called()
        e=self.event();e['message_id']=124;self.r.bridge.receive(e)
        with patch('persona.qq.request_json',side_effect=ProviderError('timeout')):self.r.bridge.process(self.r.store.rows("SELECT * FROM inbox WHERE status='pending'")[0])
        self.assertFalse(self.r.store.rows("SELECT * FROM inbox WHERE status='pending'"))
    def test_foreign_backup_restores_to_own_persona_without_overwriting_current(self):
        sid=self.r.store.session();self.r.engine.turn(sid,TEXT);old=self.r.store.meta('identity')['id'];snap=self.r.snapshot()
        with tempfile.TemporaryDirectory() as temp:
            other=Runtime(temp,Path(__file__).resolve().parents[1]);other.engine.provider_factory=FixtureProvider;other.config.update({'model':'fixture','pmm':{'mode':'legacy'}})
            sid2=other.store.session();other.engine.turn(sid2,'另一个主体的经历');other_id=other.store.meta('identity')['id']
            try:
                other.restore(snap);self.assertEqual(other.store.meta('identity')['id'],old);self.assertEqual(len(other.store.history(sid)),2)
                other.switch(other_id);self.assertEqual(len(other.store.history(sid2)),2)
            finally:
                other.close()
    def test_invalid_backup_cannot_change_identity_or_history(self):
        sid=self.r.store.session();self.r.engine.turn(sid,TEXT);before=self.r.snapshot();bad=copy.deepcopy(before)
        for row in bad['tables']['meta']:
            if row['key']=='pmm_profile':
                profile=json.loads(row['value']);profile['id']=uid();row['value']=json.dumps(profile)
        with self.assertRaises(ValueError):self.r.restore(bad)
        self.assertEqual(self.r.store.snapshot()['tables'],before['tables'])
    def test_pack_retains_learned_influence_and_rejects_missing_weights(self):
        for i in range(8):self.r.engine.model.add(str(i),vector('训练'+str(i)),action='reply')
        self.r.engine.model.fit();before=self.r.engine.model.decode(vector('测试'))['influence'];pack=self.r.subjects.export_pack(self.r.engine,scope='template')
        self.assertEqual(PMM(payload=pack['pmm']).decode(vector('测试'))['influence'],before)
        pack.pop('pmm')
        with self.assertRaises(ValueError):self.r.create_persona({'package':pack})
    def test_v02_database_migrates_identity_and_legacy_personality(self):
        with tempfile.TemporaryDirectory() as directory:
            old=Store(directory);identity=old.meta('identity');sid=old.session()
            with old.lock,old.db:
                state=old.meta('state');state['turn_count']=1;old.setmeta('state',state)
                old.db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)',(uid(),sid,'user','旧主体经历',now(),uid()))
            old.close();Path(directory,'memory_model.npz').write_bytes(b'preserved legacy checkpoint')
            runtime=Runtime(directory,Path(__file__).resolve().parents[1])
            try:
                self.assertEqual(runtime.store.meta('identity'),identity);self.assertEqual(runtime.engine.profile()['legacy_v02']['traits'],state['traits']);self.assertEqual(len(runtime.store.history(sid)),1)
                self.assertEqual(Path(directory,'memory_model.npz').read_bytes(),b'preserved legacy checkpoint')
            finally:runtime.store.close()
    def test_v02_snapshot_migration_keeps_history_with_new_cold_pmm(self):
        sid=self.r.store.session();self.r.engine.turn(sid,TEXT);snap=self.r.snapshot()
        snap['tables']['meta']=[r for r in snap['tables']['meta'] if not r['key'].startswith('pmm_')];snap['model']={'format':2}
        result=self.r.restore(snap);self.assertTrue(result['migrated_v02']);self.assertEqual(self.r.engine.model.steps,0);self.assertEqual(len(self.r.store.history(sid)),2);self.assertIn('legacy_v02',self.r.engine.profile())
    def test_switch_blocked_during_active_job(self):
        old=self.r.subjects.catalog['active'];self.r.jobs['test']={'status':'running'}
        with self.assertRaises(ValueError):self.r.switch(old)
        self.r.jobs={}

if __name__=='__main__':unittest.main(verbosity=2)
