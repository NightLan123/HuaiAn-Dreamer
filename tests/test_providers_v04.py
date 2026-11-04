"""Protocol fixtures are explicit local test servers, never substitute app responses."""
import copy,json,tempfile,threading,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from persona.provider import Provider,ProviderError,endpoint,parse_object,request_json
from persona.common import DEFAULT_CONFIG,Config
from persona.engine import Engine
from persona.storage import Store
from fixtures import response,TEXT

class NativeFixture(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,obj,status=200):
        raw=json.dumps(obj,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        self.server.requests.append((self.path,None,dict(self.headers)))
        if self.server.kind=='gemini':self.reply({'models':[{'name':'models/fixture','supportedGenerationMethods':['generateContent']},{'name':'models/embedding','supportedGenerationMethods':['embedContent']}]})
        elif self.server.kind=='ollama':self.reply({'models':[{'name':'fixture'}]})
        else:self.reply({'data':[{'id':'fixture'}]})
    def do_POST(self):
        b=json.loads(self.rfile.read(int(self.headers['Content-Length'])));p=self.server.kind;self.server.requests.append((self.path,b,dict(self.headers)))
        if p in ('ollama','chat_completions','azure_chat'):messages=b['messages']
        elif p=='responses':messages=[{'role':'system','content':b['instructions']},*b['input']]
        elif p=='anthropic':messages=[{'role':'system','content':b['system']},*b['messages']]
        else:messages=[{'role':'system','content':b['systemInstruction']['parts'][0]['text']},*[{'role':'assistant' if m['role']=='model' else 'user','content':m['parts'][0]['text']} for m in b['contents']]]
        structured=any(tag in messages[0]['content'] for tag in ('[ACTION_CHECK_V221]','[DECIDE_V21]','[ASSESS_V21]','[PMM_REVIEW_V21]','[UNDERSTAND_V3]','[ASSESS_V3]','[FEEDBACK_V3]','[DISTILL_V3]','[API_PMM_PREPARE_V2]','[API_PMM_SYNTHESIS_V2]')) or 'connection test' in str(messages)
        value=response(messages,structured);text=json.dumps(value,ensure_ascii=False) if structured else value
        if p=='ollama':r={'message':{'content':text},'done':True,'done_reason':'stop'}
        elif p in ('chat_completions','azure_chat'):r={'choices':[{'message':{'content':text},'finish_reason':'stop'}],'usage':{'completion_tokens':8}}
        elif p=='responses':r={'status':'completed','output':[{'type':'reasoning','summary':[]},{'type':'message','role':'assistant','content':[{'type':'output_text','text':text}]}]}
        elif p=='anthropic':r={'stop_reason':'end_turn','content':[{'type':'thinking','thinking':'not visible'},{'type':'text','text':text}]}
        else:r={'candidates':[{'finishReason':'STOP','content':{'parts':[{'thought':True,'text':'not visible'},{'text':text}]}}]}
        self.reply(r)

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(('127.0.0.1',0),NativeFixture);self.server.requests=[]
        threading.Thread(target=self.server.serve_forever,daemon=True).start();self.base='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):self.server.shutdown();self.server.server_close()
    def config(self,p):
        self.server.kind=p;c=copy.deepcopy(DEFAULT_CONFIG);c['pmm']['mode']='legacy';c.update(provider=p,base_url=self.base,model='fixture',api_key='fixture-llm-key',send_temperature=False);return c
    def test_native_request_shapes_auth_model_lists_and_json(self):
        for p in ('chat_completions','responses','anthropic','gemini','ollama','azure_chat'):
            with self.subTest(protocol=p):
                c=self.config(p);client=Provider(c)
                if p!='azure_chat':self.assertEqual(client.models(),['fixture'])
                else:
                    with self.assertRaises(ProviderError):client.models()
                self.assertTrue(client.test()['ok']);path,b,h=self.server.requests[-1];h={k.lower():v for k,v in h.items()}
                auth={'anthropic':'x-api-key','gemini':'x-goog-api-key','azure_chat':'api-key'}.get(p,'authorization')
                self.assertEqual(h[auth],('Bearer ' if auth=='authorization' else '')+'fixture-llm-key')
                self.assertNotIn('temperature',b)
                if p=='responses':self.assertEqual(path,'/v1/responses');self.assertFalse(b['store']);self.assertEqual(b['text']['format']['type'],'json_object')
                if p=='anthropic':self.assertEqual(path,'/v1/messages');self.assertIn('system',b);self.assertNotIn('response_format',b);self.assertIn('max_tokens',b);self.assertEqual(h['anthropic-version'],'2023-06-01')
                if p=='gemini':self.assertEqual(path,'/v1beta/models/fixture:generateContent');self.assertEqual(b['generationConfig']['responseMimeType'],'application/json');self.assertNotIn('key=',path)
                if p=='azure_chat':self.assertIn('/openai/deployments/fixture/chat/completions?api-version=',path)
    def test_all_six_protocols_execute_the_full_dialogue_loop(self):
        for p in ('chat_completions','responses','anthropic','gemini','ollama','azure_chat'):
            with self.subTest(protocol=p),tempfile.TemporaryDirectory() as directory:
                c=Config(directory);c.update(self.config(p));store=Store(directory)
                try:
                    engine=Engine(store,c);result=engine.turn(store.session(),TEXT)
                    self.assertEqual(result['reply'],'说。');self.assertEqual(result['trace']['llm_protocol'],p)
                    self.assertEqual(len(result['trace']['api_calls']),5);self.assertEqual(store.meta('state')['turn_count'],1)
                finally:store.close()
    def test_full_endpoints_and_azure_v1_are_not_duplicated(self):
        cases=[('responses','/v1/responses'),('chat_completions','/v1/chat/completions'),('anthropic','/v1/messages'),('ollama','/api/chat'),('gemini','/v1beta/models/old:generateContent'),('azure_chat','/openai/v1')]
        for p,suffix in cases:
            c=self.config(p);c['base_url']=self.base+suffix;client=Provider(c);self.assertTrue(client.test()['ok'])
            path=self.server.requests[-1][0]
            self.assertNotIn('/v1/v1',path);self.assertEqual(path.count('chat/completions'),1 if p in ('chat_completions','azure_chat') else 0)
            if p=='gemini':self.assertNotIn('/old:',path)
            if p=='azure_chat':self.assertEqual(path,'/openai/v1/chat/completions')
    def test_root_level_full_endpoint_is_used_exactly(self):
        c=self.config('chat_completions');c['base_url']=self.base+'/chat/completions'
        client=Provider(c);self.assertTrue(client.test()['ok']);self.assertEqual(self.server.requests[-1][0],'/chat/completions')
        client.models();self.assertEqual(self.server.requests[-1][0],'/models')

    def test_reasoning_fields_and_extra_headers_survive_without_temperature(self):
        c=self.config('chat_completions');c.update(token_field='max_completion_tokens',extra_body={'reasoning_effort':'low'},extra_headers={'X-Project-Id':'project'})
        Provider(c).test();_,b,h=self.server.requests[-1];self.assertIn('max_completion_tokens',b);self.assertNotIn('max_tokens',b);self.assertNotIn('temperature',b);self.assertEqual(b['reasoning_effort'],'low');self.assertEqual(h['X-Project-Id'],'project')
    def test_json_repair_is_one_call_and_never_returns_fabricated_state(self):
        c=self.config('chat_completions');client=Provider(c)
        def wrap(text):return {'choices':[{'message':{'content':text},'finish_reason':'stop'}]}
        with patch('persona.provider.request_json',side_effect=[wrap('bad json'),wrap('{"ok":true}')]) as req:
            self.assertTrue(client.test()['ok']);self.assertEqual(req.call_count,2)
        with patch('persona.provider.request_json',side_effect=[wrap('bad'),wrap('still bad')]) as req:
            with self.assertRaises(ProviderError):client.test()
            self.assertEqual(req.call_count,2)
    def test_truncation_refusal_and_safety_fail_without_json_repair(self):
        cases=[('chat_completions',{'choices':[{'message':{'content':'partial'},'finish_reason':'length'}]}),('responses',{'status':'incomplete','output':[]}),('anthropic',{'stop_reason':'max_tokens','content':[{'type':'text','text':'partial'}]}),('gemini',{'candidates':[{'finishReason':'SAFETY','content':{'parts':[]}}]}),('ollama',{'message':{'content':'partial'},'done_reason':'length'})]
        for p,r in cases:
            with self.subTest(protocol=p),patch('persona.provider.request_json',return_value=r) as req:
                with self.assertRaises(ProviderError):Provider(self.config(p)).test()
                self.assertEqual(req.call_count,1)
    def test_content_blocks_and_reasoning_are_not_mixed_into_reply(self):
        cases=[('chat_completions',{'choices':[{'message':{'content':[{'type':'text','text':'你好'}],'reasoning_content':'秘密推理'}}]}),('responses',{'output':[{'type':'reasoning','summary':[{'text':'秘密推理'}]},{'type':'message','content':[{'type':'output_text','text':'你好'}]}]}),('anthropic',{'content':[{'type':'thinking','thinking':'秘密推理'},{'type':'text','text':'你好'}]}),('gemini',{'candidates':[{'content':{'parts':[{'thought':True,'text':'秘密推理'},{'text':'你好'}]}}]})]
        for p,r in cases:
            with self.subTest(protocol=p),patch('persona.provider.request_json',return_value=r):self.assertEqual(Provider(self.config(p)).complete([{'role':'user','content':'hi'}]),'你好')
    def test_nonfinite_or_nonobject_json_is_rejected(self):
        for raw in ('[]','null','{"a":NaN}','{"a":Infinity}'):
            with self.assertRaises(ProviderError):parse_object(raw)

class ConfigurationTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.config=Config(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_legacy_config_gets_independent_default_pmm_without_losing_key(self):
        c=copy.deepcopy(DEFAULT_CONFIG);c.pop('pmm');c['api_key']='legacy';self.config.path.write_text(json.dumps(c))
        current=self.config.get();self.assertEqual(current['api_key'],'legacy');self.assertEqual(current['pmm']['backend'],'local');self.assertEqual(current['pmm']['api_key'],'')
    def test_both_keys_and_custom_headers_are_redacted(self):
        self.config.update({'api_key':'large-secret','extra_headers':{'X-Private':'header-secret'},'pmm':{'api_key':'small-secret'}})
        public=json.dumps(self.config.public());self.assertNotIn('large-secret',public);self.assertNotIn('small-secret',public);self.assertNotIn('header-secret',public)
        self.assertTrue(self.config.public()['pmm']['has_api_key'])
    def test_changing_provider_host_cannot_reuse_old_secret(self):
        self.config.update({'api_key':'old','extra_headers':{'X-Private':'old'}});self.config.update({'base_url':'https://new.example/v1','api_key':None,'extra_headers':None})
        self.assertEqual(self.config.get()['api_key'],'');self.assertEqual(self.config.get()['extra_headers'],{})
        self.config.update({'pmm':{'api_key':'old'}});self.config.update({'pmm':{'base_url':'https://pmm.example','api_key':None}});self.assertEqual(self.config.get()['pmm']['api_key'],'')
    def test_core_overrides_header_injection_and_bad_model_rejected(self):
        for patch_ in ({'extra_body':{'messages':[]}},{'extra_headers':{'Host':'evil'}},{'extra_headers':{'X-Extra':'abc\r\nAuthorization: secret'}},{'pmm':{'backend':'local','model':'unknown'}}):
            with self.assertRaises(ValueError):self.config.update(patch_)

if __name__=='__main__':unittest.main()
