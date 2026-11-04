"""Loopback integration tests. Never contact a real model service or QQ account."""
import copy, json, os, socket, subprocess, sys, tempfile, threading, time, unittest, urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from persona.common import DEFAULT_CONFIG
from persona.provider import Provider
from fixtures import response, TEXT

class ModelFixture(BaseHTTPRequestHandler):
    calls=[]
    def log_message(self,*args):pass
    def reply(self,obj):
        b=json.dumps(obj,ensure_ascii=False).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    def do_GET(self):
        self.reply({'models':[{'name':'fixture'}]} if self.path=='/api/tags' else {'data':[{'id':'fixture'}]})
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));self.calls.append((self.path,body,self.headers.get('Authorization')))
        structured=body.get('format')=='json' or 'response_format' in body
        if structured:
            value=response(body['messages'],structured=True)
            text=json.dumps(value,ensure_ascii=False)
        else:text=response(body['messages'])
        self.reply({'message':{'content':text}} if self.path=='/api/chat' else {'choices':[{'message':{'content':text}}]})

class TransportTests(unittest.TestCase):
    def setUp(self):
        ModelFixture.calls=[];self.server=ThreadingHTTPServer(('127.0.0.1',0),ModelFixture);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.base='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):self.server.shutdown();self.server.server_close()
    def test_ollama_and_chat_completions_live_http_contracts(self):
        for kind,suffix in [('ollama',''),('chat_completions','/v1')]:
            c=copy.deepcopy(DEFAULT_CONFIG);c.update(provider=kind,base_url=self.base+suffix,model='fixture',api_key='fixture-key')
            p=Provider(c);self.assertEqual(p.models(),['fixture']);self.assertTrue(p.test()['ok'])
            text=p.complete([{'role':'user','content':TEXT}]);self.assertIn('协议测试',text)
        self.assertEqual({x[0] for x in ModelFixture.calls},{'/api/chat','/v1/chat/completions'})
        self.assertTrue(all(x[2]=='Bearer fixture-key' for x in ModelFixture.calls))
    def test_launcher_hot_reload_retains_identity_history_and_model(self):
        root=Path(__file__).resolve().parents[1]
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        base='http://127.0.0.1:'+str(port)
        with tempfile.TemporaryDirectory() as directory:
            child=subprocess.Popen([sys.executable,str(root/'run.py'),'--data-dir',directory,'--port',str(port),'--no-browser'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            headers={}
            def get(path):
                with urllib.request.urlopen(urllib.request.Request(base+path,headers=headers),timeout=2) as r:return json.load(r)
            def post(path,data):
                with urllib.request.urlopen(urllib.request.Request(base+path,data=json.dumps(data).encode(),headers={**headers,'Content-Type':'application/json'}),timeout=5) as r:return json.load(r)
            def connect():
                for _ in range(100):
                    try:
                        with urllib.request.urlopen(base+'/',timeout=1) as r:headers['Cookie']=r.headers['Set-Cookie'].split(';')[0]
                        state=get('/api/state');headers['X-CSRF-Token']=state['csrf'];return state
                    except Exception:time.sleep(.06)
                self.fail('Launcher did not become ready')
            try:
                state=connect();subject=state['identity']['id'];post('/api/config',{'base_url':self.base,'model':'fixture','pmm281':{'mode':'compatibility'},'pmm':{'mode':'legacy'}})
                sid=post('/api/session',{})['id'];job=post('/api/chat',{'session_id':sid,'text':TEXT})['job_id']
                for _ in range(100):
                    r=get('/api/jobs/'+job)
                    if r['status'] in ('done','error'):break
                    time.sleep(.03)
                self.assertEqual(r['status'],'done',r);self.assertGreater(get('/api/state')['model']['samples'],0)
                pmm=post('/api/pmm/start',{});self.assertTrue(pmm['ok'])
                checkpoint=get('/api/state')['model']['checkpoint_sha256']
                old_csrf=headers['X-CSRF-Token'];post('/api/reload',{})
                for _ in range(100):
                    time.sleep(.05)
                    try:
                        state=connect()
                        if state['csrf']!=old_csrf:break
                    except Exception:continue
                self.assertNotEqual(state['csrf'],old_csrf);self.assertEqual(state['model']['backend'],'http');self.assertEqual(state['model']['checkpoint_sha256'],checkpoint)
                self.assertTrue(post('/api/pmm/test',{})['ok']);self.assertEqual(state['identity']['id'],subject)
                self.assertEqual(state['state']['turn_count'],1);self.assertEqual(state['config']['model'],'fixture')
                self.assertEqual(len(get('/api/messages?session='+sid)),2);self.assertGreater(state['model']['samples'],0)
            finally:
                # Stop the launcher and its worker together on Unix; on Windows terminate the parent tree.
                if os.name=='nt':subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True)
                else:
                    import signal
                    # Send SIGINT to the supervisor, whose KeyboardInterrupt handler terminates its child.
                    child.send_signal(signal.SIGINT)
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:child.kill();child.wait()
                if child.stdout:child.stdout.close()
if __name__=='__main__':unittest.main(verbosity=2)
