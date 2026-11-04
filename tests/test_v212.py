"""v2.1.2 regressions. Deterministic model fixtures and local HTTP only; no live accounts."""
import base64, copy, io, json, tempfile, threading, time, unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from persona.server import Runtime
from persona.common import DEFAULT_CONFIG,Config,atomic_json,now
from persona.provider import Provider,ProviderError,media_messages
from persona.qq import parse_event,QQBridge
from persona.media import MediaGateway,download,image_info,segments,legacy_media_archive
from persona.social import quiet
from persona.packages import validate_pack
from fixtures import response,TEXT

ROOT=Path(__file__).resolve().parents[1]

class PatchProvider:
    seen=[];social_action='SEND';batch_started=None;batch_release=None;bad_batch=False;critical=False
    def __init__(self,c):self.config=c;self.calls=[];self.stage=''
    def complete(self,messages,structured=False,controller=False):
        system=messages[0]['content'];self.seen.append(copy.deepcopy(messages));self.calls.append({'stage':system.splitlines()[0],'model':self.config.get('model'),'duration_ms':1})
        if '[TURN_TAKING_V212]' in system:return {'attention':'ENGAGE','action':'REPLY','wait_seconds':0,'reason':'测试夹具'}
        if '[MEMORY_GIST_V212]' in system:
            records=json.loads(messages[-1]['content'])['records'];r=records[0]
            return {'items':[{'summary':'对方谈到自己的偏好。','conclusion':'','emotion':'','uncertainty':'仅为测试归纳','layer':'gist','evidence':[{'record_id':r['id'],'quote':r['text']}]}]}
        if '[CONSOLIDATE_V212]' in system:
            if self.batch_started:self.batch_started.set();self.batch_release.wait(3)
            if self.bad_batch:return {'items':[]}
            turns=json.loads(messages[-1]['content'])['turns'];return {'items':[{'turn_id':r['turn_id'],'feedback':response([{'role':'system','content':'[FEEDBACK_V3]'},{'role':'user','content':json.dumps(r)}],True)} for r in turns]}
        if '[VISION_V212]' in system:return {'description':'测试图中有蓝色方块。','uncertainties':['测试夹具，不是真实视觉评估']}
        if '[SOCIAL_DECISION_V212]' in system:
            ctx=json.loads(messages[-1]['content']);r=ctx['records'][0]
            return {'action':self.social_action,'reason':'依据真实记录的测试决策','topic':'安静的聊天','evidence':[{'record_id':r['id'],'quote':r['text']}]}
        if '[SOCIAL_REALIZE_V212]' in system:return '想起你说喜欢安静，今天过得怎么样？'
        r=response(messages,structured)
        if '[UNDERSTAND_V3]' in system and self.critical:r['major_event']=True
        if '[API_PMM_PREPARE_V2]' in system and '[FAST_DECISION_V212]' in system:
            r['direct_assessment']={'views':[{'id':'v0','summary':'合并事件评估','utilities':r['action_prior']}],'supported_memory_evidence':[],'retrieval_queries':[]}
        return r
    def test(self):return {'ok':True,'model':self.config.get('model')}

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.r=Runtime(self.tmp.name,ROOT)
        self.r.configure({'cognition':{'mode':'baseline'},'model':'general-fixture','api_key':'GENERAL_SECRET','pmm':{'mode':'api','api':{'model':'pmm-fixture','api_key':'PMM_SECRET'}}})
        self.fixture();PatchProvider.seen=[];PatchProvider.social_action='SEND';PatchProvider.batch_started=None;PatchProvider.batch_release=None;PatchProvider.bad_batch=False;PatchProvider.critical=False
    def fixture(self):
        self.r.engine.provider_factory=PatchProvider;self.r.engine.pmm_provider_factory=PatchProvider
    def tearDown(self):self.r.close();self.tmp.cleanup()
    def session(self,number='123',group=False):return self.r.store.session('qq:'+number,('group:qq:' if group else 'private:qq:')+number)
    def event(self,user='123',bot='999',mid=1,message=None):return {'post_type':'message','message_type':'private','user_id':int(user),'self_id':int(bot),'message_id':mid,'sender':{'nickname':'测试'},'message':message or [{'type':'text','data':{'text':TEXT}}]}
    def enable(self,user='123',bot='999'):
        self.r.configure({'qq':{'enabled':True,'self_id':bot,'allowed_users':[user]}})
    def turn(self,text=TEXT,sid=None):return self.r.engine.turn(sid or self.session(),text)

class ConnectionTests(Base):
    def test_persona_connections_are_independent_and_switch_restores(self):
        first=self.r.store.meta('identity')['id'];self.enable()
        self.r.create_persona({'name':'第二位'});self.fixture();second=self.r.store.meta('identity')['id']
        self.assertFalse(self.r.config.get()['qq']['enabled']);self.assertNotEqual(first,second)
        self.r.configure({'model':'second','pmm':{'api':{'model':'second-pmm'}}});self.r.switch(first)
        self.assertEqual(self.r.config.get()['model'],'general-fixture');self.assertEqual(self.r.config.get()['pmm']['api']['model'],'pmm-fixture');self.assertTrue(self.r.config.get()['qq']['enabled'])
        self.r.switch(second);self.assertEqual(self.r.config.get()['model'],'second')
    def test_preset_crud_apply_test_and_redaction(self):
        rows=self.r.preset_action({'op':'save','kind':'general','name':'接口甲'})['presets'];i=rows[0]['id'];self.assertNotIn('GENERAL_SECRET',json.dumps(rows))
        self.r.preset_action({'op':'copy','id':i,'name':'副本'});self.r.preset_action({'op':'rename','id':i,'name':'改名'})
        self.r.configure({'model':'changed'});self.r.preset_action({'op':'apply','id':i});self.assertEqual(self.r.config.get()['model'],'general-fixture')
        self.r.configure({'model':'local-edit'});self.assertEqual(self.r.presets.get(i)['value']['model'],'general-fixture')
        with patch('persona.connections.Provider',PatchProvider):self.assertEqual(self.r.preset_action({'op':'test','id':i})['model'],'general-fixture')
        self.assertEqual(self.r.config.get()['model'],'local-edit');self.r.preset_action({'op':'delete','id':i});self.assertEqual(len(self.r.presets.list()),1)
    def test_qq_preset_cannot_silently_enable_contact(self):
        self.enable();p=self.r.preset_action({'op':'save','kind':'qq','name':'账号甲'})['presets'][0]
        self.r.preset_action({'op':'apply','id':p['id']});self.assertFalse(self.r.config.get()['qq']['enabled'])
    def test_overlapping_routes_rejected_and_distinct_bots_allowed(self):
        self.enable();self.r.create_persona({'name':'second'})
        with self.assertRaises(ValueError):self.enable()
        self.enable(bot='888');self.assertEqual(self.r.config.get()['qq']['self_id'],'888')
    def test_multiple_enabled_routes_require_explicit_bot_ids(self):
        self.r.configure({'qq':{'enabled':True,'allowed_users':['123']}});self.r.create_persona({'name':'second'})
        with self.assertRaises(ValueError):self.enable(user='456')
    def test_routing_is_independent_of_active_ui_and_global_dedupe(self):
        self.enable();first=self.r.store.meta('identity')['id'];token=self.r.config.get()['qq']['inbound_token'];ev=self.event();raw=json.dumps(ev).encode()
        self.r.create_persona({'name':'second'});second=self.r.store.meta('identity')['id']
        result=self.r.route_event(raw,{'Authorization':'Bearer '+token},{})
        self.assertTrue(result['accepted']);self.assertEqual(self.r.store.rows('SELECT * FROM inbox'),[])
        self.assertEqual(len(self.r.context(first)[0].rows('SELECT * FROM inbox')),1)
        self.r.switch(first);self.r.configure({'qq':{'enabled':False}});self.r.switch(second);self.enable();new_token=self.r.config.get()['qq']['inbound_token']
        result=self.r.route_event(raw,{'Authorization':'Bearer '+new_token},{})
        self.assertTrue(result['duplicate']);self.assertFalse(result['accepted']);self.assertEqual(self.r.store.rows('SELECT * FROM inbox'),[])
    def test_auth_and_wrong_self_id_block_before_routing(self):
        self.enable();raw=json.dumps(self.event(bot='888')).encode();token=self.r.config.get()['qq']['inbound_token']
        with self.assertRaises(PermissionError):self.r.route_event(raw,{'Authorization':'Bearer '+token},{})
        with self.assertRaises(PermissionError):self.r.route_event(json.dumps(self.event()).encode(),{}, {})
    def test_outbound_bot_mismatch_does_not_send(self):
        self.enable();self.r.bridge.receive(self.event());row=self.r.store.rows('SELECT * FROM inbox')[0]
        with patch('persona.qq.request_json',return_value={'retcode':0,'data':{'user_id':888}}) as remote:self.r.bridge.process(row)
        self.assertEqual(remote.call_count,1);self.assertTrue(remote.call_args.args[0].endswith('/get_login_info'));self.assertEqual(self.r.bridge.status()['recent'][0]['status'],'failed')
    def test_qq_token_does_not_follow_host_change(self):
        self.r.configure({'qq':{'api_token':'PRIVATE'}});self.r.configure({'qq':{'api_url':'https://other.example','api_token':None}});self.assertEqual(self.r.config.get()['qq']['api_token'],'')
    def test_export_excludes_presets_credentials_and_bindings(self):
        self.r.preset_action({'op':'save','kind':'pmm','name':'PMM'});text=json.dumps(self.r.subjects.export_pack(self.r.engine))+json.dumps(self.r.state())+json.dumps(self.r.snapshot())
        for value in ('GENERAL_SECRET','PMM_SECRET'):self.assertNotIn(value,text)
        self.assertNotIn('connection_presets',self.r.subjects.export_pack(self.r.engine))
    def test_legacy_migration_preserves_only_active_qq_route(self):
        from persona.subjects import Subjects
        with tempfile.TemporaryDirectory() as temp:
            subjects=Subjects(temp);first=subjects.catalog['active'];second=subjects.create('other');subjects.activate(second)
            Config(temp).update({'qq':{'enabled':True,'allowed_users':['123']},'model':'legacy'})
            r=Runtime(temp,ROOT)
            try:
                self.assertTrue(r.config.get()['qq']['enabled']);self.assertEqual(r.config.get()['model'],'legacy')
                self.assertFalse(r.context(first)[1].get()['qq']['enabled']);self.assertTrue((Path(temp)/'backups'/'pre_v212_connections.json').exists())
            finally:r.close()

class PerformanceTests(Base):
    def test_fast_turn_uses_four_requests_with_pre_send_check_and_durable_feedback_queue(self):
        out=self.turn();markers=[m[0]['content'].splitlines()[0] for m in PatchProvider.seen]
        self.assertEqual(len(markers),4);self.assertTrue(out['trace']['consolidation_deferred']);self.assertEqual(out['state']['turn_count'],1)
        self.assertEqual(len(self.r.store.meta('consolidation_queue')),1);self.assertTrue(self.r.store.memories());self.assertEqual(len(self.r.store.history(out['trace']['session_id'])),2)
    def test_web_synchronous_and_qq_full_mode_background_feedback(self):
        sid=self.r.store.session();out=self.turn(sid=sid);self.assertFalse(out['trace']['consolidation_deferred'])
        self.r.configure({'performance':{'mode':'full'}});out=self.turn();self.assertTrue(out['trace']['consolidation_deferred'])
    def test_qq_correction_and_sensitive_actions_queue_feedback_after_send(self):
        PatchProvider.critical=True;out=self.turn();self.assertTrue(out['trace']['consolidation_deferred']);PatchProvider.critical=False
        out=self.turn('今天股价是多少');self.assertEqual(out['action'],'unknown');self.assertTrue(out['trace']['consolidation_deferred'])
    def test_qq_always_deliberation_still_defers_learning(self):
        self.r.configure({'deliberation':{'mode':'always'}});out=self.turn();self.assertTrue(out['trace']['consolidation_deferred']);self.assertEqual(out['trace']['deliberation']['mode'],'always')
    def test_batch_commit_keeps_latest_emotion_and_counts_once(self):
        sid=self.session();self.turn(sid=sid);self.turn(sid=sid);before=copy.deepcopy(self.r.store.meta('pmm_affect'));dyads=copy.deepcopy(self.r.store.meta('pmm_dyads'));count=self.r.store.meta('state')['turn_count']
        r=self.r.engine.consolidation.run();self.assertEqual(r['processed'],2);self.assertEqual(self.r.store.meta('consolidation_queue'),[]);self.assertEqual(self.r.store.meta('pmm_affect'),before);self.assertEqual(self.r.store.meta('state')['turn_count'],count)
        self.assertEqual([d['interactions'] for d in self.r.store.meta('pmm_dyads').values()],[d['interactions'] for d in dyads.values()]);self.assertTrue(any(m['kind']=='preference' for m in self.r.store.memories()))
        self.assertEqual(self.r.engine.consolidation.run()['processed'],0)
    def test_failed_batch_preserves_raw_records_and_explicit_retry(self):
        self.turn();PatchProvider.bad_batch=True;old=self.r.engine.profile();memories=self.r.store.memories()
        with self.assertRaises(ProviderError):self.r.engine.consolidation.run()
        self.assertEqual(self.r.engine.profile(),old);self.assertEqual(memories,self.r.store.memories());self.assertEqual(self.r.store.meta('consolidation_queue')[0]['status'],'failed');self.assertFalse(self.r.engine.consolidation.due())
        PatchProvider.bad_batch=False;self.assertEqual(self.r.engine.consolidation.run(retry=True)['processed'],1)
    def test_batch_separates_people_and_contexts(self):
        self.turn(sid=self.session('123'));self.turn(sid=self.session('456'));r=self.r.engine.consolidation.run();self.assertEqual(r['processed'],1);self.assertEqual(len(self.r.store.meta('consolidation_queue')),1);self.assertEqual(self.r.store.meta('consolidation_queue')[0]['session']['person'],'qq:456')
    def test_background_network_does_not_block_new_turn(self):
        self.turn();PatchProvider.batch_started=threading.Event();PatchProvider.batch_release=threading.Event();errors=[]
        def run():
            try:self.r.engine.consolidation.run()
            except Exception as ex:errors.append(ex)
        thread=threading.Thread(target=run);thread.start();self.assertTrue(PatchProvider.batch_started.wait(2))
        self.turn('第二条真实输入');PatchProvider.batch_release.set();thread.join(3);self.assertFalse(thread.is_alive());self.assertEqual(errors,[]);self.assertEqual(self.r.store.meta('state')['turn_count'],2);self.assertEqual(len(self.r.store.meta('consolidation_queue')),1)
    def test_idle_and_count_triggers(self):
        sid=self.session();self.turn(sid=sid);self.assertFalse(self.r.engine.consolidation.due())
        with patch('persona.consolidation.now',return_value=now()+91):self.assertTrue(self.r.engine.consolidation.due())
        for _ in range(5):self.turn(sid=sid)
        self.assertTrue(self.r.engine.consolidation.due())
    def test_pending_consolidation_roundtrips_without_credentials(self):
        self.turn();pack=self.r.subjects.export_pack(self.r.engine);meta,_,_=validate_pack(pack);self.assertEqual(len(meta['consolidation_queue']),1);self.assertNotIn('GENERAL_SECRET',json.dumps(pack))
    def test_generated_language_is_never_a_positive_style_target(self):
        self.turn();self.r.engine.consolidation.run();p=self.r.engine.profile();self.assertEqual(p['style']['count'],0);self.assertEqual(p['examples'],[])

class MediaTests(Base):
    def png(self):
        b=io.BytesIO();Image.new('RGB',(8,8),'blue').save(b,'PNG');return b.getvalue()
    def asset(self,scopes=None,kind='image'):
        # Fixture written as an old installation, never through a retired API.
        from persona.common import uid
        self.r.configure({'media':{'send':True}})
        root=self.r.store.directory/'media_assets';root.mkdir(exist_ok=True)
        path=root/'catalog.json';rows=json.loads(path.read_text()) if path.exists() else []
        row={'id':uid(),'name':'测试蓝图','kind':kind,'face_id':'66','tags':['蓝色'],'scopes':scopes or ['private:qq:123'],**image_info(self.png(),False)}
        rows.append(row);atomic_json(path,rows)
        if kind=='image':(root/(row['id']+'.bin')).write_bytes(self.png())
        return row
    def test_pure_mixed_cq_and_face_parsing(self):
        self.enable();image={'type':'image','data':{'url':'https://gchat.qpic.cn/a'}}
        p=parse_event(self.event(message=[image]),self.r.config.get());self.assertEqual(len(p['media']),1);self.assertTrue(p['text'])
        p=parse_event(self.event(message='看[CQ:image,file=a,url=https://gchat.qpic.cn/a?x=1&#44;2]'),self.r.config.get());self.assertEqual(p['media'][0]['data']['url'],'https://gchat.qpic.cn/a?x=1,2')
        p=parse_event(self.event(message=[{'type':'face','data':{'id':66}}]),self.r.config.get());self.assertIn('66',p['text'])
    def test_group_image_still_requires_mention_and_whitelist(self):
        self.r.configure({'qq':{'enabled':True,'self_id':'999','allowed_groups':['321']}});ev=self.event(message=[{'type':'image','data':{'file':'x'}}]);ev.update(message_type='group',group_id=321)
        self.assertIsNone(parse_event(ev,self.r.config.get()));ev['message'].insert(0,{'type':'at','data':{'qq':'999'}});self.assertIsNotNone(parse_event(ev,self.r.config.get()))
    def test_gif_samples_actual_distinct_frames_and_detects_bytes(self):
        frames=[Image.new('RGB',(5,5),color) for color in ('red','blue','green','yellow','purple','black')];b=io.BytesIO();frames[0].save(b,'GIF',save_all=True,append_images=frames[1:],duration=100,loop=0)
        info=image_info(b.getvalue());self.assertEqual(info['total_frames'],6);self.assertEqual(len(info['frames']),4);self.assertEqual(info['format'],'GIF')
        with self.assertRaises(ValueError):image_info(b'fake image')
    def test_download_blocks_private_urls_and_unlisted_hosts(self):
        for url in ('file:///etc/passwd','http://127.0.0.1/a','https://evil.example/a','https://x:q@gchat.qpic.cn/a'):
            with self.subTest(url=url),self.assertRaises(ValueError):download(url,['gchat.qpic.cn'])
        with patch('persona.media.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]),self.assertRaises(ValueError):download('https://gchat.qpic.cn/a',['gchat.qpic.cn'])
    def test_actual_image_bytes_reach_vision_and_text_bypasses(self):
        self.enable();ev=self.event(message=[{'type':'image','data':{'url':'https://gchat.qpic.cn/a'}}]);p=parse_event(ev,self.r.config.get())
        with patch('persona.media.download',return_value=self.png()):result=MediaGateway(self.r.engine).inspect(p,ev)
        self.assertEqual(result['status'],'OK');self.assertEqual(len(result['images']),1);self.assertTrue(any(isinstance(m[-1]['content'],list) and any(b.get('type')=='image_url' for b in m[-1]['content']) for m in PatchProvider.seen))
        count=len(PatchProvider.seen);plain=self.event();self.assertIsNone(MediaGateway(self.r.engine).inspect(parse_event(plain,self.r.config.get()),plain));self.assertEqual(count,len(PatchProvider.seen))
    def test_failure_and_partial_media_are_explicit(self):
        self.enable();ev=self.event(message=[{'type':'image','data':{'url':'https://gchat.qpic.cn/a'}}]);p=parse_event(ev,self.r.config.get())
        with patch('persona.media.download',side_effect=ValueError('expired')):r=MediaGateway(self.r.engine).inspect(p,ev)
        self.assertEqual(r['status'],'IMAGE_UNAVAILABLE');self.assertFalse(PatchProvider.seen)
        ev['message']*=2;p=parse_event(ev,self.r.config.get())
        with patch('persona.media.download',side_effect=[self.png(),ValueError('expired')]):r=MediaGateway(self.r.engine).inspect(p,ev)
        self.assertEqual(r['status'],'PARTIAL')
    def test_quoted_image_cannot_cross_private_or_group_scope(self):
        self.enable();ev=self.event(message=[{'type':'reply','data':{'id':'9'}}]);p=parse_event(ev,self.r.config.get())
        quoted={'retcode':0,'data':{'message_type':'private','sender':{'user_id':456},'message':[{'type':'image','data':{'url':'https://gchat.qpic.cn/private'}}]}}
        with patch('persona.media.request_json',return_value=quoted),patch('persona.media.download') as fetch:r=MediaGateway(self.r.engine).inspect(p,ev)
        self.assertEqual(r['status'],'IMAGE_UNAVAILABLE');fetch.assert_not_called()
        quoted['data']['sender']['user_id']=123
        with patch('persona.media.request_json',return_value=quoted),patch('persona.media.download',return_value=self.png()):r=MediaGateway(self.r.engine).inspect(p,ev)
        self.assertEqual(r['status'],'OK')
    def test_media_protocols_encode_native_image_blocks(self):
        url='data:image/png;base64,'+base64.b64encode(self.png()).decode();msg=[{'role':'user','content':[{'type':'text','text':'图'},{'type':'image_url','image_url':{'url':url}}]}]
        for proto in ('ollama','responses','anthropic','gemini','chat_completions','azure_chat'):
            r=media_messages(msg,proto)[0]
            if proto=='ollama':self.assertEqual(len(r['images']),1);self.assertEqual(r['content'],'图')
            elif proto=='responses':self.assertEqual(r['content'][1]['type'],'input_image')
            elif proto=='anthropic':self.assertEqual(r['content'][1]['source']['media_type'],'image/png')
            elif proto=='gemini':self.assertIn('inlineData',r['content'][1])
            else:self.assertEqual(r['content'][1]['type'],'image_url')
    def test_retired_assets_export_original_bytes_without_mutation(self):
        import zipfile
        a=self.asset();self.asset(kind='face');root=self.r.store.directory/'media_assets';before={p.name:p.read_bytes() for p in root.iterdir()}
        with zipfile.ZipFile(io.BytesIO(legacy_media_archive(self.r.engine))) as archive:
            self.assertEqual(archive.read('media_assets/'+a['id']+'.bin'),self.png())
            self.assertEqual(archive.read('media_assets/catalog.json'),before['catalog.json'])
        self.assertEqual({p.name:p.read_bytes() for p in root.iterdir()},before)
    def test_retired_usage_and_feedback_remain_in_full_backup(self):
        a=self.asset();usage=[{'asset_id':a['id'],'scope':'private:qq:123','message_id':55}];feedback=[{**usage[0],'rating':'like'}]
        with self.r.store.lock,self.r.store.db:
            self.r.store.setmeta('media_usage',usage);self.r.store.setmeta('media_feedback',feedback)
        self.r.restore(self.r.snapshot())
        self.assertEqual(self.r.store.meta('media_usage'),usage);self.assertEqual(self.r.store.meta('media_feedback'),feedback)
        self.assertTrue((self.r.store.directory/'media_assets'/('catalog.json')).exists())
    def test_visual_description_is_not_inserted_as_user_evidence(self):
        self.enable();sid=self.session();out=self.r.engine.turn(sid,'[收到图片]',media_context={'status':'OK','description':'仅视觉模型知道的XYZ描述'})
        self.assertNotIn('XYZ',self.r.store.history(sid)[0]['content']);self.assertTrue(all('XYZ' not in m['evidence'] for m in self.r.store.memories()));self.assertIn('XYZ',out['trace']['visual_observation']['description'])
    def test_retired_gallery_has_no_executable_class(self):
        import persona.media as media
        self.asset();self.assertFalse(hasattr(media,'Assets'));self.assertTrue(callable(media.MediaGateway))

class SocialTests(Base):
    def ready(self):
        self.enable();sid=self.session();self.turn(sid=sid);self.r.engine.social.receive(parse_event(self.event(),self.r.config.get()))
        self.r.configure({'social':{'enabled':True,'recipients':['private:qq:123'],'quiet_start':'00:00','quiet_end':'00:00','idle_minutes':10,'cooldown_minutes':10}})
        rows=self.r.store.meta('social_contacts');rows['private:qq:123']['last_input_at']=now()-700
        with self.r.store.lock,self.r.store.db:self.r.store.setmeta('social_contacts',rows)
        return sid
    def test_default_off_never_calls_model_or_sends(self):
        self.assertFalse(self.r.config.get()['social']['enabled']);self.r.engine.social.poll();self.assertEqual(PatchProvider.seen,[])
    def test_authorization_and_whitelist_both_required(self):
        with self.assertRaises(ValueError):self.r.configure({'social':{'enabled':True,'recipients':['private:qq:123']}})
        self.ready();self.assertTrue(self.r.engine.social.gate('private:qq:456'))
    def test_quiet_hours_include_midnight_and_timezone(self):
        s=copy.deepcopy(DEFAULT_CONFIG['social']);import datetime
        stamp=lambda h:datetime.datetime(2026,10,26,h,tzinfo=__import__('zoneinfo').ZoneInfo('Asia/Shanghai')).timestamp()
        self.assertTrue(quiet(s,stamp(23)));self.assertTrue(quiet(s,stamp(7)));self.assertFalse(quiet(s,stamp(8)));self.assertFalse(quiet(s,stamp(15)))
    def test_preview_uses_persona_decision_but_never_sends(self):
        self.ready();before=self.r.store.meta('social_attempts')
        with patch('persona.social.request_json') as remote:r=self.r.engine.social.evaluate('private:qq:123')
        self.assertEqual(r['action'],'SEND');self.assertFalse(r['sent']);remote.assert_not_called();self.assertEqual(before,self.r.store.meta('social_attempts'))
    def test_no_action_is_first_class_result(self):
        self.ready();PatchProvider.social_action='NO_ACTION'
        with patch('persona.social.request_json') as remote:r=self.r.engine.social.evaluate('private:qq:123',send=True)
        self.assertEqual(r['action'],'NO_ACTION');remote.assert_not_called();self.assertIsNone(self.r.store.meta('social_attempts'))
    def test_delivery_is_assistant_only_and_stops_after_unanswered(self):
        sid=self.ready();before=self.r.store.meta('state')['turn_count'];n=len(self.r.store.history(sid))
        with patch('persona.qq.request_json',return_value={'retcode':0,'data':{'user_id':999}}),patch('persona.social.request_json',return_value={'retcode':0,'status':'ok','data':{'message_id':55}}):r=self.r.engine.social.evaluate('private:qq:123',send=True)
        self.assertTrue(r['sent']);hist=self.r.store.history(sid);self.assertEqual(len(hist),n+1);self.assertEqual(hist[-1]['role'],'assistant');self.assertEqual(self.r.store.meta('state')['turn_count'],before);self.assertIn('未回复',self.r.engine.social.gate('private:qq:123'))
    def test_unknown_send_result_is_not_retried(self):
        self.ready()
        with patch('persona.qq.request_json',return_value={'retcode':0,'data':{'user_id':999}}),patch('persona.social.request_json',side_effect=ProviderError('timeout')),self.assertRaises(ProviderError):self.r.engine.social.evaluate('private:qq:123',send=True)
        self.assertEqual(self.r.store.meta('social_attempts')[0]['status'],'uncertain');self.assertTrue(self.r.engine.social.gate('private:qq:123'))
    def test_reply_feedback_resets_count_but_not_stop_request(self):
        self.ready();rows=self.r.store.meta('social_contacts');rows['private:qq:123']['unanswered']=1
        with self.r.store.lock,self.r.store.db:self.r.store.setmeta('social_contacts',rows)
        p=parse_event(self.event(mid=2,message=[{'type':'text','data':{'text':'不要主动联系我'}}]),self.r.config.get());self.r.engine.social.receive(p);r=self.r.store.meta('social_contacts')['private:qq:123'];self.assertEqual(r['unanswered'],0);self.assertTrue(r['blocked']);self.assertIn('停止',self.r.engine.social.gate('private:qq:123'))
    def test_no_cross_session_evidence_in_social_prompt(self):
        self.ready();sid=self.session('456');self.turn('另一个人的秘密',sid);self.r.engine.social.evaluate('private:qq:123');ctx=next(json.loads(m[-1]['content']) for m in PatchProvider.seen if '[SOCIAL_DECISION_V212]' in m[0]['content']);self.assertNotIn('另一个人的秘密',json.dumps(ctx,ensure_ascii=False))
    def test_new_inbound_message_during_generation_cancels_send(self):
        self.ready();engine=self.r.engine
        class Incoming(PatchProvider):
            def complete(self,messages,structured=False,controller=False):
                r=super().complete(messages,structured,controller)
                if '[SOCIAL_REALIZE_V212]' in messages[0]['content']:engine.social.receive({'scope':'private:qq:123','person':'qq:123','text':'刚刚回来','key':'new'})
                return r
        engine.provider_factory=Incoming
        with patch('persona.social.request_json') as send:r=engine.social.evaluate('private:qq:123',send=True)
        self.assertFalse(r['sent']);send.assert_not_called();self.assertIn('变化',r['reason'])


class AdditionalIntegrityTests(Base):
    def test_recovered_queue_rejects_stale_background_result(self):
        self.turn();pack=self.r.subjects.export_pack(self.r.engine);PatchProvider.batch_started=threading.Event();PatchProvider.batch_release=threading.Event();errors=[]
        def run():
            try:self.r.engine.consolidation.run()
            except Exception as ex:errors.append(ex)
        thread=threading.Thread(target=run);thread.start();self.assertTrue(PatchProvider.batch_started.wait(2))
        self.r.subjects.apply_current(self.r.engine,pack);profile=self.r.engine.profile();PatchProvider.batch_release.set();thread.join(3)
        self.assertEqual(len(errors),1);self.assertEqual(self.r.engine.profile(),profile);self.assertEqual(self.r.store.meta('consolidation_queue')[0]['status'],'pending')
    def test_interrupted_queue_recovers_after_process_restart(self):
        self.turn();rows=self.r.store.meta('consolidation_queue');rows[0]['status']='processing'
        with self.r.store.lock,self.r.store.db:self.r.store.setmeta('consolidation_queue',rows)
        self.r.close();self.r=Runtime(self.tmp.name,ROOT);self.fixture();self.assertEqual(self.r.store.meta('consolidation_queue')[0]['status'],'pending');self.assertEqual(self.r.engine.consolidation.run()['processed'],1)
    def test_critical_event_triggers_pending_batch(self):
        self.turn();self.assertFalse(self.r.engine.consolidation.due());PatchProvider.critical=True;self.turn('请更正你刚才的判断');self.assertTrue(self.r.engine.consolidation.due())
    def test_queue_malformed_input_is_rejected_before_package_write(self):
        self.turn();p=self.r.subjects.export_pack(self.r.engine);p['consolidation_queue'][0]['training_x']=[0]
        before=self.r.store.snapshot()['tables']
        with self.assertRaises(ValueError):self.r.subjects.apply_current(self.r.engine,p)
        self.assertEqual(before,self.r.store.snapshot()['tables'])
    def test_stopping_qq_also_disables_proactive_contact(self):
        self.enable();self.r.configure({'social':{'enabled':True,'recipients':['private:qq:123']}});self.r.configure({'qq':{'enabled':False}});self.assertFalse(self.r.config.get()['social']['enabled'])
    def test_two_personas_process_their_own_queues_while_ui_switches(self):
        self.enable();first=self.r.store.meta('identity')['id'];self.r.bridge.receive(self.event());first_ctx=self.r.context(first)
        self.r.create_persona({'name':'Second'});self.fixture();second=self.r.store.meta('identity')['id'];self.enable(user='456',bot='888');self.r.bridge.receive(self.event(user='456',bot='888'))
        second_ctx=self.r.context(second);sent=[]
        def remote(url,payload=None,token='',timeout=20,**kwargs):
            if url.endswith('/get_login_info'):return {'retcode':0,'data':{'user_id':999 if threading.current_thread().name=='first' else 888}}
            sent.append(payload['user_id']);return {'retcode':0,'status':'ok','data':{'message_id':len(sent)}}
        with patch('persona.qq.request_json',side_effect=remote):
            threads=[threading.Thread(name=name,target=ctx[3].process,args=(ctx[0].rows('SELECT * FROM inbox')[0],)) for name,ctx in [('first',first_ctx),('second',second_ctx)]]
            for t in threads:t.start()
            self.r.switch(first)
            for t in threads:t.join(3)
        self.assertCountEqual(sent,[123,456]);self.assertEqual(first_ctx[0].meta('state')['turn_count'],1);self.assertEqual(second_ctx[0].meta('state')['turn_count'],1)
        self.assertEqual(first_ctx[0].sessions()[0]['scope'],'private:qq:123');self.assertEqual(second_ctx[0].sessions()[0]['scope'],'private:qq:456')
    def test_learned_pmm_still_uses_shared_core_directory(self):
        self.r.configure({'pmm':{'mode':'learned'}});item=self.r.engine.register_core(self.r.engine.export_core());self.r.create_persona({'name':'Second'});self.assertIn(item['id'],[v['id'] for v in self.r.engine.pmm_versions()['cores']])

class MediaFlowTests(Base):
    png=MediaTests.png
    asset=MediaTests.asset
    def test_old_gallery_and_provider_media_actions_cannot_send_images(self):
        a=self.asset();self.enable();engine=self.r.engine
        class Select(PatchProvider):
            def complete(self,messages,structured=False,controller=False):
                r=super().complete(messages,structured,controller)
                if '[API_PMM_PREPARE_V2]' in messages[0]['content']:
                    context=json.loads(messages[-1]['content']);assert set(context['media'])=={'visual_observation'}
                    assert 'M3_MEDIA_V212' not in messages[0]['content'];r['media_actions']=[{'type':'image','asset_id':a['id']}]
                return r
        engine.pmm_provider_factory=Select;self.r.bridge.receive(self.event());sent=[]
        def remote(url,payload=None,*args,**kwargs):
            if url.endswith('/get_login_info'):return {'retcode':0,'data':{'user_id':999}}
            sent.append(payload);return {'retcode':0,'status':'ok','data':{'message_id':55}}
        with patch('persona.qq.request_json',side_effect=remote):self.r.bridge.process(self.r.store.rows('SELECT * FROM inbox')[0])
        self.assertEqual([m['type'] for m in sent[0]['message']],['text']);self.assertFalse(self.r.store.meta('media_usage'));self.assertEqual(self.r.bridge.status()['recent'][0]['status'],'sent')
    def test_qq_image_only_failure_still_replies_without_inventing_vision(self):
        self.enable();ev=self.event(message=[{'type':'image','data':{'url':'https://gchat.qpic.cn/missing'}}]);self.r.bridge.receive(ev)
        def remote(url,*args,**kwargs):return {'retcode':0,'data':{'user_id':999,'message_id':77},'status':'ok'}
        with patch('persona.qq.request_json',side_effect=remote),patch('persona.media.download',side_effect=ValueError('expired')):self.r.bridge.process(self.r.store.rows('SELECT * FROM inbox')[0])
        trace=next(e['payload'] for e in self.r.store.recent_events(30) if e['kind']=='turn');self.assertEqual(trace['decision']['gate'],'image_unavailable');self.assertEqual(trace['reply'],'不知道。')
    def test_same_group_cached_quote_works_without_get_msg_group_extension(self):
        self.r.configure({'qq':{'enabled':True,'self_id':'999','allowed_groups':['321']}})
        original=self.event(mid=5,message=[{'type':'at','data':{'qq':'999'}},{'type':'image','data':{'url':'https://gchat.qpic.cn/a'}}]);original.update(message_type='group',group_id=321);self.r.bridge.receive(original)
        reply=self.event(mid=6,message=[{'type':'at','data':{'qq':'999'}},{'type':'reply','data':{'id':'5'}}]);reply.update(message_type='group',group_id=321);parsed=parse_event(reply,self.r.config.get())
        with patch('persona.media.download',return_value=self.png()),patch('persona.media.request_json') as api:r=MediaGateway(self.r.engine).inspect(parsed,reply)
        self.assertEqual(r['status'],'OK');api.assert_not_called()

class NativeVisionTransportTests(unittest.TestCase):
    def test_six_protocols_send_images_over_real_loopback_http(self):
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        received=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));received.append((self.path,body));text=json.dumps({'description':'本地 HTTP 夹具','uncertainties':[]})
                if self.path.endswith('/api/chat'):out={'message':{'content':text}}
                elif self.path.endswith('/responses'):out={'output':[{'type':'message','content':[{'type':'output_text','text':text}]}]}
                elif self.path.endswith('/messages'):out={'content':[{'type':'text','text':text}]}
                elif ':generateContent' in self.path:out={'candidates':[{'content':{'parts':[{'text':text}]},'finishReason':'STOP'}]}
                else:out={'choices':[{'message':{'content':text},'finish_reason':'stop'}]}
                raw=json.dumps(out).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            b=io.BytesIO();Image.new('RGB',(4,4),'blue').save(b,'PNG');data=base64.b64encode(b.getvalue()).decode();messages=[{'role':'system','content':'Describe image as JSON'},{'role':'user','content':[{'type':'text','text':'看图'},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+data}}]}]
            for proto in ('chat_completions','responses','anthropic','gemini','ollama','azure_chat'):
                c=copy.deepcopy(DEFAULT_CONFIG);c.update(provider=proto,base_url='http://127.0.0.1:'+str(server.server_port),model='vision-fixture',api_key='LOCAL_ONLY',thinking_mode='default')
                p=Provider(c);r=p.complete(messages,structured=True);self.assertIn('description',r);body=received[-1][1];self.assertIn(data,json.dumps(body));self.assertNotIn(data,json.dumps(p.calls));self.assertNotIn('LOCAL_ONLY',json.dumps(p.calls))
                if proto=='responses':self.assertEqual(body['input'][0]['content'][1]['type'],'input_image')
                if proto=='gemini':self.assertEqual(body['contents'][0]['parts'][1]['inlineData']['mimeType'],'image/png')
                if proto=='anthropic':self.assertEqual(body['messages'][0]['content'][1]['source']['type'],'base64')
                if proto=='ollama':self.assertEqual(body['messages'][1]['images'],[data])
        finally:server.shutdown();server.server_close();thread.join(2)

class PatchHTTPTests(unittest.TestCase):
    from test_api import APITests as _API
    setUp=_API.setUp
    tearDown=_API.tearDown
    request=_API.request
    job=_API.job
    def test_configuration_presets_and_retired_gallery_endpoints(self):
        import urllib.error
        c=self.request('/api/config',{'performance':{'mode':'balanced','batch_turns':7},'media':{'receive':True}});self.assertEqual(c['performance']['batch_turns'],7)
        self.request('/api/connection-presets',{'op':'save','kind':'general','name':'HTTP preset'});self.assertEqual(len(self.request('/api/connection-presets')),1)
        for path in ('/api/media','/api/media/preferences','/api/media/image/old'):
            for body in (None,{'op':'delete','id':'old'}):
                with self.assertRaises(urllib.error.HTTPError) as error:self.request(path,body)
                self.assertEqual(error.exception.code,410);self.assertEqual(json.load(error.exception)['code'],'FEATURE_REMOVED')
        self.assertFalse((self.app.store.directory/'media_assets').exists())
        self.assertFalse(self.request('/api/social')['config']['enabled']);self.assertEqual(self.job(self.request('/api/social/preview',{'scope':'private:qq:123'}))['action'],'NO_ACTION')
        self.assertEqual(self.job(self.request('/api/consolidation/run',{'retry':True}))['processed'],0)
    def test_invalid_route_and_social_config_rejected_without_side_effects(self):
        import urllib.error
        before=self.request('/api/state')['config']
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/config',{'social':{'enabled':True,'recipients':['private:qq:123']}})
        self.assertEqual(before,self.request('/api/state')['config'])
        with self.assertRaises(urllib.error.HTTPError):self.request('/onebot/events/not-a-persona',{'post_type':'message'})

if __name__=='__main__':unittest.main()
