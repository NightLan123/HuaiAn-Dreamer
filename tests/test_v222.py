"""P0 recovery: real loopback HTTP, persisted upgrade fixtures and failure injection."""
import copy,hashlib,http.cookiejar,json,sqlite3,tempfile,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from persona.server import Runtime,Handler
from persona.storage import Store
from persona.common import atomic_json,now,VERSION
from persona.data_guard import DataGuardError,inspect_database,inspect_root,resolve_data_directory,remember_data_directory,prepare_upgrade,complete_upgrade

ROOT=Path(__file__).resolve().parents[1]

def populate(directory):
    r=Runtime(directory,ROOT);first=r.engine.profile()['id']
    r.subjects.edit_character(r.engine,{'name':'原来的槐安','initial_personality':'保留已有偏好','seed':'这是既有主体'})
    r.configure({'api_key':'SYNTHETIC_SECRET','model':'offline-fixture','qq':{'self_id':'9988'},'pmm':{'api':{'model':'offline-pmm','thinking_mode':'low'}}})
    for group in (False,True):
        sid=r.store.session('qq:123','group:qq:456' if group else 'private:qq:123','原群聊' if group else '原私聊')
        with r.store.lock,r.store.db:
            r.store.db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)',(sid+'-u',sid,'user','合成历史原文',now(),'fixture-turn'))
            r.store.db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)',(sid+'-a',sid,'assistant','合成历史回复',now(),'fixture-turn'))
            r.store.setmeta('pmm_checkpoint',r.engine.model.export())
    r.engine.boundaries.edit({'topic':'尊重自主','domain':'autonomy'})
    with r.store.lock,r.store.db:
        r.store.db.execute('INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('fixture-memory','合成的已保存偏好','preference','private:qq:123','qq:123',.7,.6,'active','fixture-turn','合成原文',now(),now(),1,'测试数据'))
        r.store.db.execute('INSERT INTO relations VALUES (?,?,?,?)',('qq:123','合成关系',json.dumps({'trust':.7,'familiarity':.4,'affection':.5,'interactions':7}),now()))
    r.create_persona({'name':'第二个原主体'});second=r.engine.profile()['id'];r.switch(first)
    before={i['id']:r.context(i['id'])[0].snapshot() for i in r.subjects.catalog['items']};config=r.config.get();r.close()
    (Path(directory)/'upgrade_state.json').unlink() # 2.2.1 schema has no upgrade marker.
    return first,second,before,config

class DataRecoveryTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_automatic_upgrade_preserves_personas_history_weights_and_connections(self):
        first,second,before,config=populate(self.path);r=Runtime(self.path,ROOT)
        try:
            self.assertEqual(r.subjects.catalog['active'],first);self.assertEqual(r.config.get(),config)
            self.assertTrue(Path(r.upgrade['backup']).is_dir())
            for ident,snapshot in before.items():
                st=r.context(ident)[0];current=st.snapshot()
                for table in ('sessions','messages','memories','relations'):self.assertEqual(snapshot['tables'][table],current['tables'][table])
                old={v['key']:json.loads(v['value']) for v in snapshot['tables']['meta']}
                for name in ('identity','state','pmm_profile','pmm_checkpoint','boundary_model','pmm_interlocutors'):
                    if name in old:self.assertEqual(old[name],st.meta(name))
            self.assertEqual(r.engine.profile()['name'],'原来的槐安')
        finally:r.close()
        backups=len(list((self.path/'backups').glob('pre-'+VERSION+'-*')));r=Runtime(self.path,ROOT);r.close()
        self.assertEqual(backups,len(list((self.path/'backups').glob('pre-'+VERSION+'-*'))))
    def test_missing_catalog_recovers_all_existing_subjects_without_replacing_records(self):
        first,second,before,_=populate(self.path);r=Runtime(self.path,ROOT);r.close();(self.path/'personas.json').unlink();r=Runtime(self.path,ROOT)
        try:
            self.assertEqual({x['id'] for x in r.subjects.catalog['items']},{first,second});self.assertEqual(r.store.snapshot()['tables']['messages'],before[first]['tables']['messages'])
            self.assertEqual(r.upgrade['kind'],'upgrade');self.assertTrue(json.loads((self.path/'upgrade_state.json').read_text())['catalog_reconstructed'])
        finally:r.close()
    def test_missing_database_in_catalog_never_creates_empty_subject(self):
        first,second,_,_=populate(self.path);db=self.path/'subjects'/second/'subject.sqlite3';db.unlink()
        with self.assertRaises(DataGuardError):Runtime(self.path,ROOT)
        self.assertFalse(db.exists())
    def test_config_only_directory_is_not_treated_as_new_install(self):
        (self.path/'config.json').write_text('{}')
        with self.assertRaises(DataGuardError):Runtime(self.path,ROOT)
        self.assertFalse((self.path/'subject.sqlite3').exists())
    def test_corrupt_catalog_is_not_overwritten(self):
        populate(self.path);p=self.path/'personas.json';p.write_text('{broken')
        before=(self.path/'subject.sqlite3').read_bytes()
        with self.assertRaises(DataGuardError):Runtime(self.path,ROOT)
        self.assertEqual(p.read_text(),'{broken');self.assertEqual((self.path/'subject.sqlite3').read_bytes(),before)
    def test_corrupt_database_or_missing_identity_cannot_be_initialized(self):
        p=self.path/'subject.sqlite3';p.write_bytes(b'not sqlite')
        with self.assertRaises(DataGuardError):Store(self.path)
        self.assertEqual(p.read_bytes(),b'not sqlite');p.unlink()
        with sqlite3.connect(p) as db:db.execute('CREATE TABLE meta(key TEXT,value TEXT)')
        before=p.read_bytes()
        with self.assertRaises(DataGuardError):Store(self.path)
        self.assertEqual(p.read_bytes(),before)
    def test_orphan_messages_stop_upgrade_without_dropping_history(self):
        populate(self.path)
        with sqlite3.connect(self.path/'subject.sqlite3') as db:db.execute("UPDATE messages SET session_id='missing' WHERE role='user'")
        with self.assertRaises(DataGuardError):Runtime(self.path,ROOT)
        with sqlite3.connect(self.path/'subject.sqlite3') as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM messages').fetchone()[0],4)
    def test_invalid_checkpoint_detected_before_profile_or_config_changes(self):
        populate(self.path)
        with sqlite3.connect(self.path/'subject.sqlite3') as db:db.execute("UPDATE meta SET value='{}' WHERE key='pmm_checkpoint'")
        # An empty checkpoint is invalid existing data, never equivalent to no checkpoint.
        before=(self.path/'config.json').read_bytes()
        before_db=(self.path/'subject.sqlite3').read_bytes()
        with self.assertRaises(DataGuardError):Runtime(self.path,ROOT)
        self.assertEqual((self.path/'config.json').read_bytes(),before)
        self.assertEqual((self.path/'subject.sqlite3').read_bytes(),before_db)
        self.assertFalse(list((self.path/'backups').glob('pre-'+VERSION+'-*')))
    def test_empty_existing_profile_is_not_replaced_by_a_new_personality(self):
        populate(self.path)
        with sqlite3.connect(self.path/'subject.sqlite3') as db:db.execute("UPDATE meta SET value='{}' WHERE key='pmm_profile'")
        before=(self.path/'subject.sqlite3').read_bytes()
        with self.assertRaises(DataGuardError):Runtime(self.path,ROOT)
        self.assertEqual((self.path/'subject.sqlite3').read_bytes(),before)
    def test_upgrade_checks_history_content_even_when_counts_are_unchanged(self):
        populate(self.path);report=prepare_upgrade(self.path)
        with sqlite3.connect(self.path/'subject.sqlite3') as db:db.execute("UPDATE messages SET content='unexpected rewrite' WHERE role='user'")
        with self.assertRaises(DataGuardError):complete_upgrade(self.path,report)
        self.assertFalse((self.path/'upgrade_state.json').exists())
        snap=Path(report['backup'])/'sqlite_snapshots'/'subject.sqlite3'
        with sqlite3.connect(snap) as db:self.assertEqual(db.execute("SELECT content FROM messages WHERE role='user' LIMIT 1").fetchone()[0],'合成历史原文')
    def test_snapshot_contains_committed_wal_and_independent_execution_database(self):
        populate(self.path)
        db=sqlite3.connect(self.path/'subject.sqlite3');db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA wal_autocheckpoint=0')
        try:
            db.execute("UPDATE messages SET content='committed in WAL' WHERE role='user'");db.commit()
            self.assertTrue((self.path/'subject.sqlite3-wal').exists())
            report=prepare_upgrade(self.path);backup=Path(report['backup'])
            self.assertTrue((backup/'subject.sqlite3-wal').exists());self.assertTrue((backup/'subject.sqlite3-shm').exists())
            snapshot=backup/'sqlite_snapshots'/'subject.sqlite3'
            self.assertFalse(snapshot.with_name(snapshot.name+'-wal').exists())
            with sqlite3.connect(snapshot) as check:
                self.assertEqual(check.execute('PRAGMA integrity_check').fetchone()[0],'ok')
                self.assertEqual(check.execute("SELECT content FROM messages WHERE role='user' LIMIT 1").fetchone()[0],'committed in WAL')
            self.assertTrue((backup/'sqlite_snapshots'/'execution.sqlite3').exists())
            self.assertTrue(report['before']['subjects'][0]['content_sha256']['messages'])
        finally:db.close()
    def test_known_old_location_is_reused_across_new_program_directories(self):
        home=self.path/'home';home.mkdir();app=self.path/'HuaiAn_v222';app.mkdir();old=home/'.persona_dialogue';populate(old)
        self.assertEqual(resolve_data_directory(app_root=app,home=home),old.resolve())
        remember_data_directory(old,home);self.assertEqual(resolve_data_directory(app_root=app,home=home),old.resolve())
        populate(app/'data');self.assertEqual(resolve_data_directory(app_root=app,home=home),old.resolve())
        with self.assertRaises(DataGuardError):resolve_data_directory(self.path/'typo',app,home)
        self.assertFalse((self.path/'typo').exists())
    def test_ambiguous_locations_are_not_silently_merged(self):
        home=self.path/'home';home.mkdir();app=self.path/'HuaiAn_v222';app.mkdir();populate(home/'.persona_dialogue');populate(app/'data')
        with self.assertRaises(DataGuardError):resolve_data_directory(app_root=app,home=home)
    def test_data_inside_previous_code_directory_is_found_without_cwd_dependency(self):
        home=self.path/'home';home.mkdir();app=self.path/'HuaiAn_v222';app.mkdir();old=self.path/'HuaiAn_v221'/'data';populate(old)
        self.assertEqual(resolve_data_directory(app_root=app,home=home),old.resolve())

class HTTPRecoveryTests(unittest.TestCase):
    from test_api import APITests
    setUp=APITests.setUp;tearDown=APITests.tearDown;request=APITests.request
    def test_history_pagination_reaches_older_messages_without_changing_ids(self):
        sid=self.app.store.session()
        rows=[(f'm-{i:05}',sid,'user',f'合成历史 {i}',1,'old-turn') for i in range(2010)]
        with self.app.store.lock,self.app.store.db:self.app.store.db.executemany('INSERT INTO messages VALUES (?,?,?,?,?,?)',rows)
        first=self.request('/api/messages?session='+sid);second=self.request('/api/messages?session='+sid+'&offset=2000')
        self.assertEqual(len(first),2000);self.assertEqual(len(second),10)
        self.assertEqual([r['id'] for r in second+first],[r[0] for r in rows])
        with self.assertRaises(urllib.error.HTTPError) as err:self.request('/api/messages?session='+sid+'&offset=-1')
        self.assertEqual(err.exception.code,400)
    def test_bootstrap_has_a_separate_csrf_token_without_loading_optional_components(self):
        with patch.object(self.app.engine.boundaries,'status',side_effect=RuntimeError('private body')):
            b=self.request('/api/bootstrap');self.assertEqual(b['csrf'],self.app.token)
            s=self.request('/api/state');self.assertTrue(s['profile']['id']);self.assertIn('boundaries',s['component_errors']);self.assertNotIn('private body',json.dumps(s))
    def test_local_view_and_edit_work_when_all_external_network_calls_fail(self):
        with patch('persona.provider.request_json',side_effect=RuntimeError('offline')) as network:
            state=self.request('/api/state');self.request('/api/persona/settings',{'name':'离线编辑保留'})
            b=self.request('/api/boundaries/edit',{'topic':'自主讨论深度','domain':'autonomy'});bid=b['boundaries'][0]['boundary_id']
            self.request('/api/boundaries/edit',{'boundary_id':bid,'topic':'修改后的倾向'})
            sid=self.request('/api/session',{})['id'];self.assertEqual(self.request('/api/messages?session='+sid),[])
            self.assertEqual(self.request('/api/state')['profile']['name'],'离线编辑保留');network.assert_not_called()
    def test_error_response_identifies_route_status_and_request_without_private_exception_text(self):
        with patch.object(self.app.store,'recent_events',side_effect=RuntimeError('SYNTHETIC_PRIVATE_DATA')):
            with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/events')
            self.assertEqual(caught.exception.code,500);body=json.load(caught.exception)
            self.assertEqual(body['code'],'LOCAL_SERVICE_ERROR');self.assertTrue(body['request_id']);self.assertNotIn('SYNTHETIC_PRIVATE_DATA',json.dumps(body))
        self.assertTrue(self.request('/api/state')['profile'])
    def test_bootstrap_rejects_cross_site_and_post_rejects_mismatched_frontend(self):
        for headers in ({'Origin':'https://other.invalid'},{'Sec-Fetch-Site':'cross-site'}):
            with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/bootstrap',headers=headers)
            self.assertEqual(caught.exception.code,403)
        before=len(self.app.store.sessions())
        with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/session',{}, {'X-App-Client-Version':'2.2.1'})
        self.assertEqual(caught.exception.code,409);self.assertEqual(len(self.app.store.sessions()),before)
    def test_restarted_session_can_be_reconnected_without_retrying_mutations(self):
        self.app.token='new-token-after-restart'
        with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/session',{})
        self.assertEqual(json.load(caught.exception)['code'],'SESSION_EXPIRED');self.assertFalse(self.app.store.sessions())
        with urllib.request.urlopen(self.base+'/api/bootstrap') as response:
            self.headers['Cookie']=response.headers['Set-Cookie'].split(';')[0];self.headers['X-CSRF-Token']=json.load(response)['csrf']
        self.assertTrue(self.request('/api/session',{})['id'])
    def test_cookie_names_are_port_specific_and_assets_have_explicit_mime_and_build(self):
        self.assertIn('persona_session_'+str(self.app.port)+'=',self.headers['Cookie'])
        for asset,mime in [('/app.js','text/javascript'),('/style.css','text/css'),('/','text/html')]:
            with urllib.request.urlopen(self.base+asset) as response:
                self.assertTrue(response.headers['Content-Type'].startswith(mime));self.assertEqual(response.headers['X-App-Version'],VERSION);self.assertEqual(response.headers['X-App-Build'],self.app.build_id)

if __name__=='__main__':unittest.main(verbosity=2)
