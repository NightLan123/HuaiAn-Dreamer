"""Real local HTTP requests; no browser, third-party network, model or QQ account."""
import copy,json,tempfile,threading,time,unittest,urllib.request,urllib.error,re
from pathlib import Path
from http.server import ThreadingHTTPServer
from html.parser import HTMLParser
from persona.server import Runtime,Handler
from fixtures import FixtureProvider,TEXT

class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(__file__).resolve().parents[1]
        self.app=Runtime(self.tmp.name,self.root);self.app.config.update({'model':'fixture','pmm':{'mode':'legacy'}});self.app.engine.provider_factory=FixtureProvider;FixtureProvider.fail_stage=None
        self.http=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.http.app=self.app;self.app.http=self.http;self.app.port=self.http.server_port
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start();self.base='http://127.0.0.1:'+str(self.http.server_port);self.headers={}
        with urllib.request.urlopen(self.base+'/') as res:self.headers['Cookie']=res.headers['Set-Cookie'].split(';')[0]
        self.headers['X-CSRF-Token']=self.request('/api/state')['csrf']
    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.app.close();self.tmp.cleanup()
    def request(self,path,body=None,headers=None):
        h={**self.headers,**(headers or {})}
        if body is not None:h['Content-Type']='application/json'
        with urllib.request.urlopen(urllib.request.Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=h),timeout=10) as r:return json.load(r)
    def job(self,job):
        for _ in range(100):
            out=self.request('/api/jobs/'+job['job_id'])
            if out['status'] in ('done','error'):
                self.assertEqual(out['status'],'done',out);return out['result']
            time.sleep(.02)
        self.fail('Local job did not complete')
    def test_import_preview_distillation_chat_and_export(self):
        content='甲：在吗\n乙：说\n甲：还在吗\n乙：在\n甲：有什么想法\n乙：没'
        p=self.request('/api/import/preview',{'content':content});self.assertEqual(p['speakers']['乙'],3)
        r=self.job(self.request('/api/distill',{'content':content,'speaker':'乙','target':'self'}));self.assertEqual(r['report']['added'],3)
        sid=self.request('/api/session',{})['id'];r=self.job(self.request('/api/chat',{'session_id':sid,'text':TEXT}));self.assertEqual(r['reply'],'说。')
        package=self.request('/api/persona/export');self.assertEqual(package['profile']['style']['count'],3);self.assertNotIn('api_key',package)
    def test_csrf_origin_host_and_qq_readonly(self):
        for headers in [{'X-CSRF-Token':''},{'Origin':'https://evil.example'},{'Host':'evil.example'}]:
            with self.assertRaises(urllib.error.HTTPError) as err:self.request('/api/session',{},headers)
            self.assertEqual(err.exception.code,403)
        sid=self.app.store.session('qq:123','private:qq:123')
        with self.assertRaises(urllib.error.HTTPError) as err:self.request('/api/chat',{'session_id':sid,'text':'你好'})
        self.assertEqual(err.exception.code,400)
    def test_invalid_package_keeps_current_persona(self):
        before=self.request('/api/state')['identity'];p=self.request('/api/persona/export?scope=template');p['pmm']['parameters']['E']=[[1]]
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/persona/import',p)
        self.assertEqual(before,self.request('/api/state')['identity'])
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/persona/import',{})
        self.assertEqual(before,self.request('/api/state')['identity'])
    def test_dual_model_configuration_remote_start_train_and_weights_api(self):
        before=self.request('/api/state');identity=before['identity']['id'];weights=before['model']['checkpoint_sha256']
        result=self.request('/api/pmm/start',{});self.assertTrue(result['ok']);self.assertEqual(result['backend'],'http')
        after=self.request('/api/state');self.assertEqual(after['identity']['id'],identity);self.assertEqual(after['model']['checkpoint_sha256'],weights)
        self.assertTrue(after['config']['pmm']['has_api_key']);self.assertNotIn('api_key',after['config']['pmm']);self.assertGreater(self.app.pmm_process.pid,0)
        self.assertTrue(self.request('/api/pmm/test',{})['ok']);self.assertIn('pmm-mlp-v3',self.request('/api/pmm/models',{})['models'])
        sid=self.request('/api/session',{})['id'];turn=self.job(self.request('/api/chat',{'session_id':sid,'text':TEXT}));self.assertEqual(turn['trace']['pmm_backend'],'http')
        # Ensure at least one training sample regardless of the random turn ID's holdout group.
        from persona.pmm import vector
        self.app.engine.model.add('train-fixed',vector('训练'),action='reply',source='human_correction',group_id='train-fixed')
        result=self.job(self.request('/api/pmm/train',{'epochs':2}));self.assertGreater(result['model']['steps'],0)
        exported=self.request('/api/pmm/export');self.assertEqual(exported['identity_id'],identity)
        self.assertTrue(self.request('/api/pmm/import',exported)['ok'])
        self.request('/api/config',{'pmm':{'backend':'local','managed':False}});self.assertEqual(self.request('/api/state')['model']['backend'],'local')
        self.assertEqual(self.request('/api/state')['model']['checkpoint_sha256'],exported['checkpoint_sha256'])

    def test_config_changes_blocked_during_inflight_turn(self):
        before=self.app.config.get();self.app.jobs['busy']={'id':'busy','status':'running'}
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/config',{'model':'changed'})
        self.assertEqual(self.app.config.get(),before);self.app.jobs.clear()

    def test_static_frontend_references_have_real_elements(self):
        class Parser(HTMLParser):
            def __init__(self):super().__init__();self.ids=[]
            def handle_starttag(self,tag,attrs):
                for k,v in attrs:
                    if k=='id':self.ids.append(v)
        parser=Parser();parser.feed((self.root/'web/index.html').read_text());self.assertEqual(len(parser.ids),len(set(parser.ids)))
        js=(self.root/'web/app.js').read_text();refs=set(re.findall(r"\$\('([^']+)'\)",js));self.assertFalse(refs-set(parser.ids))
        for asset in ('/','/app.js','/style.css','/favicon.svg'):
            with urllib.request.urlopen(self.base+asset) as res:self.assertEqual(res.status,200);self.assertGreater(len(res.read()),0)

if __name__=='__main__':unittest.main(verbosity=2)
