"""Actual loopback Ollama/OpenAI-compatible HTTP; no cloud model claims."""
import copy,json,tempfile,threading,time,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from persona.common import Config
from persona.provider import Provider
from persona.server import Runtime
from persona.pmm_connections import connection,probe
from persona.pmm_workspace import status,preview
from persona.registry import digest
from test_v281_runtime import Provider281
ROOT=Path(__file__).resolve().parents[1]

class Endpoint:
    def __init__(self):
        self.requests=[];self.fail=False;self.delay=0
        outer=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def send(self,value,code=200):
                raw=json.dumps(value,ensure_ascii=False).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers()
                try:self.wfile.write(raw)
                except (BrokenPipeError,ConnectionResetError):pass
            def do_GET(self):
                outer.requests.append({'path':self.path,'method':'GET'})
                return self.send({'models':[{'name':'local-fixture'}]} if self.path.endswith('/api/tags') else {'data':[{'id':'cloud-shape-fixture'}]})
            def do_POST(self):
                b=json.loads(self.rfile.read(int(self.headers['Content-Length'])));outer.requests.append({'path':self.path,'body':b,'authorization':self.headers.get('Authorization')})
                if self.path.endswith('/api/show'):return self.send({'capabilities':['completion','thinking'],'thinking':{'values':[True,False]}})
                if outer.delay:time.sleep(outer.delay)
                if outer.fail:return self.send({'error':{'message':'controlled upstream failure'}},503)
                messages=b['messages'];system=messages[0].get('content','')
                if not any(mark in system for mark in ('[PMM_','[UNDERSTAND','[REALIZE','[ACTION_CHECK','[FEEDBACK','[MEMORY','[CONSOLIDATE')):answer={'ok':True}
                else:answer=Provider281({'model':b['model']}).complete(messages,structured=True)
                content=answer if isinstance(answer,str) else json.dumps(answer,ensure_ascii=False)
                if self.path.endswith('/api/chat'):return self.send({'message':{'role':'assistant','content':content},'done':True,'done_reason':'stop','prompt_eval_count':1,'eval_count':1})
                return self.send({'choices':[{'message':{'role':'assistant','content':content},'finish_reason':'stop'}],'usage':{'prompt_tokens':1,'completion_tokens':1}})
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
    def close(self):self.server.shutdown();self.server.server_close();self.thread.join()

class Connections(unittest.TestCase):
    def setUp(self):
        Provider281.fail_a=Provider281.fail_b=False;Provider281.seen=[]
        self.tmp=tempfile.TemporaryDirectory();self.r=Runtime(self.tmp.name,ROOT);self.a=Endpoint();self.b=Endpoint()
        self.r.configure({'provider':'ollama','base_url':self.a.url,'model':'general-http','pmm':{'api':{'provider':'ollama','base_url':self.a.url,'model':'A-http','max_output_tokens':4096,'timeout':30}},
            'pmm281':{'mode':'full','b_policy':'always','b_share_a':False,'b_api':{'provider':'chat_completions','base_url':self.b.url+'/v1','model':'B-http','api_key':'SECRET_B_TEST','timeout':10,'max_output_tokens':1024,'thinking_mode':'default'}},'cognition':{'mode':'baseline'}})
    def tearDown(self):self.r.close();self.a.close();self.b.close();self.tmp.cleanup()
    def test_independent_configs_and_secret_retention(self):
        self.r.configure({'pmm281':{'b_api':{'model':'changed','api_key':None}}});c=self.r.config.get();self.assertEqual(c['pmm281']['b_api']['api_key'],'SECRET_B_TEST')
        self.assertNotIn('SECRET_B_TEST',json.dumps(self.r.config.public()));self.assertEqual(c['pmm']['api']['model'],'A-http')
        self.r.configure({'pmm281':{'b_api':{'base_url':self.a.url}}});self.assertEqual(self.r.config.get()['pmm281']['b_api']['api_key'],'')
    def test_share_connection_but_independent_budget_and_options(self):
        self.r.configure({'pmm281':{'b_share_a':True,'b_api':{'thinking_mode':'off'}}});cfg=self.r.config.get();a=connection(cfg,'A');b=connection(cfg,'B')
        self.assertEqual(a['model'],b['model']);self.assertEqual(b['timeout'],10);self.assertEqual(b['max_output_tokens'],1024);self.assertEqual(b['thinking_mode'],'off');self.assertEqual(a['max_output_tokens'],4096)
        self.assertTrue(probe(self.r.engine,'B')['ok']);body=self.a.requests[-1]['body'];self.assertIn('[PMM_B_',body['messages'][0]['content']);self.assertEqual(body['options']['num_predict'],1024)
    def test_models_connect_invoke_two_protocols(self):
        for role in ('A','B'):
            for op in ('models','connect','invoke'):
                r=probe(self.r.engine,role,op);self.assertTrue(r['ok'],r)
        self.assertTrue(any(x['path']=='/api/chat' for x in self.a.requests));self.assertTrue(any(x['path']=='/v1/chat/completions' for x in self.b.requests))
        self.assertEqual(self.r.store.meta('pmm281_affect')['revision'],0)
        s=status(self.r.engine);self.assertEqual(s['connections']['A']['status'],'tested');self.assertNotIn('SECRET_B_TEST',json.dumps(s))
    def test_real_http_full_round_and_state_receipts(self):
        out=self.r.engine.turn(self.r.store.session(), '今天想聊一聊。');co=out['trace']['pmm28']['components'];self.assertEqual(co['reasoner']['status'],'ok');self.assertEqual(co['negotiation']['status'],'ok')
        self.assertEqual(co['negotiation']['connection']['model'],'B-http');self.assertEqual(co['reasoner']['connection']['model'],'A-http')
        self.assertEqual(status(self.r.engine)['connections']['B']['status'],'last_call_succeeded')
    def test_B_http_failure_does_not_reinvoke_A_or_duplicate(self):
        self.b.fail=True;sid=self.r.store.session();out=self.r.engine.turn(sid,'服务故障测试。');co=out['trace']['pmm28']['components']
        self.assertEqual(co['reasoner']['status'],'ok');self.assertEqual(co['negotiation']['status'],'failed');self.assertEqual(len(self.r.store.history(sid)),2)
        self.assertEqual(sum('[PMM_A_' in x.get('body',{}).get('messages',[{}])[0].get('content','') for x in self.a.requests),1)
    def test_preview_uses_real_http_and_preserves_entire_database(self):
        before=self.r.store.snapshot();owner=self.r.engine.profile()['id']
        result=preview(self.r.engine,{'subject_id':owner,'text':'整轮隔离测试。'})
        after=self.r.store.snapshot();self.assertEqual(before['tables'],after['tables']);self.assertEqual(before['qq_inbox'],after['qq_inbox'])
        self.assertTrue(result['isolated']);self.assertEqual(result['external_messages_sent'],0);self.assertEqual(result['trace']['pmm28']['components']['negotiation']['status'],'ok')
    def test_last_connection_result_invalidated_by_settings(self):
        self.assertTrue(probe(self.r.engine,'A')['ok']);self.r.configure({'pmm':{'api':{'model':'new-model'}}})
        self.assertEqual(status(self.r.engine)['connections']['A']['status'],'saved_not_tested')
    def test_failed_probe_no_false_online(self):
        self.b.fail=True;r=probe(self.r.engine,'B');self.assertFalse(r['ok']);self.assertEqual(status(self.r.engine)['connections']['B']['status'],'failed')
    def test_actual_socket_timeout_is_bounded(self):
        self.b.delay=.3;c=connection(self.r.config.get(),'B');c['timeout']=.04
        from persona.pmm_negotiator import Negotiator
        with patch('persona.pmm_connections.connection',return_value=c):
            n=Negotiator(self.r.config.get(),Provider);start=time.monotonic()
            with self.assertRaises(Exception):n.assess({'projections':[{'id':'v0'}],'memories':[],'emotion':{'emotion':{'valence':0},'mood':{'valence':0}}},[{'id':'v0','weight':1}],[])
            self.assertLess(time.monotonic()-start,.25)
        self.assertTrue(probe(self.r.engine,'A')['ok'])

if __name__=='__main__':unittest.main()
