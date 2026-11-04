"""Patch regressions use deterministic fixtures, never live vendor credentials."""
import copy, io, json, tempfile, threading, unittest, urllib.error
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from persona.common import Config, DEFAULT_CONFIG
from persona.provider import Provider, ProviderError
from persona.thinking import apply_thinking
from persona.psychology import profile_condition, validate_profile
from persona.packages import validate_pack
from persona.engine import Engine
from persona.storage import Store
import test_v2 as v2
from test_providers_v04 import NativeFixture
from fixtures import TEXT


def cfg(**kw):
    c=copy.deepcopy(DEFAULT_CONFIG);c.update(provider='chat_completions',base_url='https://api.deepseek.com/chat/completions',model='deepseek-flash',api_key='PRIVATE_KEY');c.update(kw);return c

def answer(text='{"ok":true}',**kw):return {'choices':[{'message':{'content':text,**kw},'finish_reason':'stop'}],'usage':{'completion_tokens':15,'completion_tokens_details':{'reasoning_tokens':8}}}

class ThinkingTests(unittest.TestCase):
    def request(self,c):
        with patch('persona.provider.request_json',return_value=answer()) as req:
            client=Provider(c);client.test();return req.call_args.args[1],client
    def test_deepseek_auto_defaults_off_and_preserves_model(self):
        b,c=self.request(cfg());self.assertEqual(b['thinking'],{'type':'disabled'});self.assertEqual(b['model'],'deepseek-flash');self.assertNotIn('reasoning_effort',b);self.assertEqual(c.calls[0]['thinking']['effective'],'off')
    def test_deepseek_off_low_high_are_actual_request_fields(self):
        for mode in ('off','low','high'):
            b,c=self.request(cfg(thinking_mode=mode));self.assertEqual(b['thinking']['type'],'disabled' if mode=='off' else 'enabled')
            if mode!='off':self.assertEqual(b['reasoning_effort'],mode);self.assertNotIn('temperature',b)
    def test_existing_extra_reasoning_is_preserved_in_auto_and_default(self):
        for mode in ('auto','default'):
            b,_=self.request(cfg(thinking_mode=mode,extra_body={'thinking':{'type':'enabled'},'reasoning_effort':'high'}));self.assertEqual(b['reasoning_effort'],'high');self.assertEqual(b['thinking']['type'],'enabled')
    def test_conflicting_controls_fail_before_http(self):
        with patch('persona.provider.request_json') as req:
            with self.assertRaisesRegex(ProviderError,'重复'):Provider(cfg(thinking_mode='off',extra_body={'reasoning_effort':'high'})).test()
            req.assert_not_called()
    def test_deepseek_wrong_token_field_or_stream_options_fail_locally(self):
        for change in ({'token_field':'max_completion_tokens'},{'extra_body':{'stream_options':{'include_usage':True}}}):
            with self.subTest(change=change),patch('persona.provider.request_json') as req:
                with self.assertRaises(ProviderError):Provider(cfg(**change)).test()
                req.assert_not_called()
    def test_unknown_proxy_not_guessed_but_explicit_adapter_works(self):
        with patch('persona.provider.request_json') as req:
            with self.assertRaisesRegex(ProviderError,'无法确认'):Provider(cfg(base_url='https://proxy.example/v1',thinking_mode='low')).test()
            req.assert_not_called()
        b,_=self.request(cfg(base_url='https://proxy.example/v1',thinking_mode='low',thinking_adapter='deepseek'));self.assertEqual(b['reasoning_effort'],'low')
    def test_non_deepseek_default_does_not_invent_thinking_parameters(self):
        b,_=self.request(cfg(base_url='https://proxy.example/v1'));self.assertNotIn('thinking',b);self.assertNotIn('reasoning_effort',b)
    def test_openai_responses_and_chat_use_different_shapes(self):
        p={'max_tokens':4096,'temperature':.5}
        b,_=apply_thinking(p,cfg(provider='responses',thinking_adapter='openai',thinking_mode='low',model='gpt-5.2'));self.assertEqual(b['reasoning'],{'effort':'low'});self.assertNotIn('temperature',b)
        b,_=apply_thinking(p,cfg(thinking_adapter='openai',thinking_mode='off',model='gpt-5.2'));self.assertEqual(b['reasoning_effort'],'none');self.assertEqual(b['max_completion_tokens'],4096);self.assertNotIn('max_tokens',b)
    def test_non_disableable_models_never_silently_map_off_to_low(self):
        cases=[('openai','responses','gpt-5'),('openai','responses','gpt-6.1-sol'),('openai','responses','o3'),('anthropic','anthropic','claude-opus-5-5'),('gemini','gemini','gemini-2.5-pro')]
        for adapter,proto,model in cases:
            with self.subTest(model=model),self.assertRaises(ValueError):apply_thinking({'max_tokens':20000},cfg(thinking_adapter=adapter,provider=proto,model=model,thinking_mode='off'))
    def test_claude_adaptive_manual_and_budget_limits(self):
        b,_=apply_thinking({'max_tokens':16000},cfg(provider='anthropic',thinking_adapter='anthropic',model='claude-sonnet-4-6',thinking_mode='low'));self.assertEqual(b['thinking'],{'type':'adaptive'});self.assertEqual(b['output_config']['effort'],'low')
        b,_=apply_thinking({'max_tokens':16000},cfg(provider='anthropic',thinking_adapter='anthropic',model='claude-haiku-4-5',thinking_mode='high'));self.assertEqual(b['thinking']['budget_tokens'],8192)
        with self.assertRaises(ValueError):apply_thinking({'max_tokens':4096},cfg(provider='anthropic',thinking_adapter='anthropic',model='claude-haiku-4-5',thinking_mode='high'))
    def test_gemini_preserves_json_and_maps_model_versions(self):
        for model,mode,key,value in [('gemini-2.5-flash','off','thinkingBudget',0),('gemini-2.5-pro','low','thinkingBudget',1024),('gemini-3-flash-preview','high','thinkingLevel','HIGH')]:
            b,_=apply_thinking({'generationConfig':{'responseMimeType':'application/json','maxOutputTokens':4096}},cfg(provider='gemini',thinking_adapter='gemini',thinking_mode=mode,model=model));self.assertEqual(b['generationConfig']['thinkingConfig'][key],value);self.assertEqual(b['generationConfig']['responseMimeType'],'application/json')
    def test_ollama_checks_actual_capabilities_before_setting_levels(self):
        c=cfg(provider='ollama',base_url='http://127.0.0.1:11434',model='gpt-oss',thinking_mode='low')
        with patch('persona.provider.request_json',side_effect=[{'thinking':{'values':['low','high']}},{'message':{'content':'ok'}}]) as req:
            self.assertEqual(Provider(c).complete([{'role':'user','content':'hi'}]),'ok');self.assertEqual(req.call_args_list[0].args[0],'http://127.0.0.1:11434/api/show');self.assertEqual(req.call_args_list[1].args[1]['think'],'low')
        c['thinking_mode']='off'
        with patch('persona.provider.request_json',return_value={'thinking':{'values':['low','high']}}) as req:
            with self.assertRaises(ProviderError):Provider(c).test()
            self.assertEqual(req.call_count,1)
    def test_configuration_fields_are_independent_and_persist(self):
        with tempfile.TemporaryDirectory() as d:
            c=Config(d);c.update({'thinking_mode':'off','thinking_adapter':'deepseek','pmm':{'api':{'thinking_mode':'low','thinking_adapter':'openai'}}})
            got=Config(d).get();self.assertEqual(got['thinking_mode'],'off');self.assertEqual(got['pmm']['api']['thinking_mode'],'low');self.assertEqual(got['pmm']['api']['thinking_adapter'],'openai')
    def test_invalid_thinking_mode_is_atomic(self):
        with tempfile.TemporaryDirectory() as d:
            c=Config(d);before=c.get()
            for field in ('thinking_mode','thinking_adapter'):
                with self.assertRaises(ValueError):c.update({field:'bad'})
                self.assertEqual(c.get(),before)
    def test_model_list_uses_id_not_display_name(self):
        with patch('persona.provider.request_json',return_value={'data':[{'id':'deepseek-flash','name':'DeepSeek-V4.1-Flash'}]}):self.assertEqual(Provider(cfg()).models(),['deepseek-flash'])

class DiagnosticsTests(unittest.TestCase):
    def test_success_metadata_excludes_prompts_keys_and_reasoning(self):
        client=Provider(cfg(extra_body={'metadata':{'secret_prompt':'SECRET_PROMPT'}}))
        with patch('persona.provider.request_json',return_value=answer('你好',reasoning_content='PRIVATE_REASONING')):self.assertEqual(client.complete([{'role':'user','content':'SECRET_PROMPT'}]),'你好')
        data=json.dumps(client.calls)
        for private in ('PRIVATE_KEY','SECRET_PROMPT','PRIVATE_REASONING'):self.assertNotIn(private,data)
        self.assertEqual(client.calls[0]['reasoning_chars'],17);self.assertGreaterEqual(client.calls[0]['duration_ms'],0)
    def test_reasoning_only_is_not_final_answer(self):
        client=Provider(cfg())
        with patch('persona.provider.request_json',return_value=answer('',reasoning_content='private')):
            with self.assertRaisesRegex(ProviderError,'缺少最终正文'):client.test()
        self.assertEqual(client.calls[0]['status'],'error')
    def test_http_400_keeps_real_parameter_but_not_remote_echo(self):
        body={'error':{'type':'invalid_request_error','param':'reasoning_effort','message':'reasoning_effort unsupported PRIVATE_KEY SECRET_PROMPT','code':'unsupported_value'}}
        error=urllib.error.HTTPError('https://example',400,'bad',{},io.BytesIO(json.dumps(body).encode()))
        with patch('urllib.request.OpenerDirector.open',side_effect=error):
            client=Provider(cfg())
            with self.assertRaises(ProviderError) as caught:client.test()
        detail=caught.exception.details['call'];self.assertEqual(detail['response']['http_status'],400);self.assertEqual(detail['response']['param'],'reasoning_effort');self.assertIn('request_options',detail)
        data=json.dumps(detail)+str(caught.exception)
        for private in ('PRIVATE_KEY','SECRET_PROMPT'):self.assertNotIn(private,data)
    def test_network_failure_has_duration_and_actual_options(self):
        client=Provider(cfg(thinking_mode='low'))
        with patch('persona.provider.request_json',side_effect=ProviderError('timeout')):
            with self.assertRaises(ProviderError) as caught:client.test()
        self.assertEqual(caught.exception.details['call']['request_options']['reasoning_effort'],'low');self.assertIn('duration_ms',caught.exception.details['call'])
    def test_invalid_json_repair_is_bounded_and_diagnosed(self):
        with patch('persona.provider.request_json',return_value=answer('invalid')) as req:
            with self.assertRaises(ProviderError) as caught:Provider(cfg()).test()
        self.assertEqual(req.call_count,2);self.assertEqual(len(caught.exception.details['calls']),2)

class PersonaPatchTests(v2.RuntimeCase):
    def test_edit_preserves_identity_evidence_relationships_weights_and_history(self):
        self.turn();before=self.r.snapshot()['tables'];profile=self.r.engine.profile();weights=self.r.engine.model.export();dyads=self.r.store.meta('pmm_dyads')
        result=self.r.subjects.edit_character(self.r.engine,{'name':'小岚','self_reference':'咱','initial_personality':'谨慎，简短表达','seed':'好奇，诚实','expected_revision':profile['revision']})
        new=self.r.engine.profile();self.assertEqual(new['name'],'小岚');self.assertEqual(new['character']['self_reference'],'咱');self.assertEqual(profile['psychology'],new['psychology']);self.assertEqual(profile['source_records'],new['source_records'])
        after=self.r.snapshot()['tables']
        for table in ('messages','sessions','memories','relations'):self.assertEqual(before[table],after[table])
        self.assertEqual(dyads,self.r.store.meta('pmm_dyads'));self.assertEqual(weights,self.r.engine.model.export());self.assertTrue(result['checkpoint_id']);self.assertEqual(Engine(self.r.store,self.r.config).profile()['character'],new['character'])
    def test_character_reaches_both_model_conditions(self):
        self.r.subjects.edit_character(self.r.engine,{'name':'小岚','self_reference':'咱','initial_personality':'直率'});captured=[]
        class Capture(v2.GeneralFixture):
            def complete(self,messages,structured=False):captured.append(messages);return super().complete(messages,structured)
        self.r.engine.provider_factory=Capture;self.r.engine.pmm_provider_factory=Capture;self.turn()
        for marker in ('[API_PMM_PREPARE_V2]','[REALIZE_V3]'):
            relevant=next(m for m in captured if marker in m[0]['content'])
            for value in ('小岚','咱','直率'):self.assertIn(value,json.dumps(relevant,ensure_ascii=False))
    def test_character_pack_roundtrip_and_rollback(self):
        before=self.r.engine.profile();r=self.r.subjects.edit_character(self.r.engine,{'self_reference':'咱','initial_personality':'慢热'})
        pack=self.r.subjects.export_pack(self.r.engine);meta,_,_=validate_pack(pack);self.assertEqual(meta['pmm_profile']['character']['self_reference'],'咱')
        self.r.subjects.rollback(self.r.engine,r['checkpoint_id']);self.assertEqual(self.r.engine.profile(),before)
    def test_old_profile_without_character_still_valid(self):
        p=self.r.engine.profile();p.pop('character',None);validate_profile(p);self.assertEqual(profile_condition(p)['character']['self_reference'],'我')
    def test_stale_or_invalid_character_edit_writes_nothing(self):
        before=self.r.snapshot()['tables']
        for body in ({'expected_revision':999},{'self_reference':''},{'name':''},{'initial_personality':'x'*4001}):
            with self.assertRaises(ValueError):self.r.subjects.edit_character(self.r.engine,body)
            self.assertEqual(self.r.snapshot()['tables'],before)
    def test_noop_config_creates_no_update(self):
        before=self.r.store.recent_events(100);self.r.configure({'model':self.r.config.get()['model']});self.assertEqual(before,self.r.store.recent_events(100))
    def test_failed_turn_logs_diagnostic_but_no_personality_change(self):
        before=self.r.snapshot()['tables']
        class Fail(v2.GeneralFixture):
            def complete(self,*args,**kw):raise ProviderError('fixture failure',{'fixture':True})
        self.r.engine.provider_factory=Fail
        with self.assertRaises(ProviderError):self.turn()
        after=self.r.snapshot()['tables'];self.assertEqual({k:v for k,v in before.items() if k!='events'},{k:v for k,v in after.items() if k!='events'})
        event=self.r.store.recent_events()[0];self.assertEqual(event['kind'],'turn_failed');self.assertIn('timing',event['payload']);self.assertIn('1 / 6',event['payload']['phase'])
    def test_qq_filter_duplicate_and_sent_timing(self):
        self.r.configure({'qq':{'enabled':True,'allowed_users':['123']}})
        event={'post_type':'message','message_type':'private','user_id':123,'self_id':999,'message_id':'1','message':[{'type':'text','data':{'text':TEXT}}]}
        self.assertIn('白名单',self.r.bridge.receive({**event,'user_id':456})['reason']);self.assertTrue(self.r.bridge.receive(event)['accepted']);self.assertTrue(self.r.bridge.receive(event)['duplicate'])
        with patch('persona.qq.request_json',return_value={'retcode':0,'status':'ok','data':{'message_id':77}}):self.r.bridge.process(self.r.store.rows('SELECT * FROM inbox')[0])
        status=self.r.bridge.status();self.assertEqual(status['recent'][0]['status'],'sent');self.assertIn('qq_total_ms',status['recent'][0]['result']['timing']);self.assertNotIn('payload',status['recent'][0])
    def test_event_pagination_preserves_individual_records(self):
        with self.r.store.lock,self.r.store.db:
            for i in range(150):self.r.store.event('config_updated',{'i':i})
        a=self.r.store.recent_events(120);b=self.r.store.recent_events(120,120);self.assertFalse(set(x['id'] for x in a)&set(x['id'] for x in b));self.assertGreaterEqual(len(a)+len(b),150)

class LiveTransportPatchTests(unittest.TestCase):
    def test_two_http_services_send_independent_thinking_and_timing(self):
        servers=[]
        try:
            for _ in range(2):
                server=ThreadingHTTPServer(('127.0.0.1',0),NativeFixture);server.kind='chat_completions';server.requests=[];threading.Thread(target=server.serve_forever,daemon=True).start();servers.append(server)
            with tempfile.TemporaryDirectory() as d:
                c=Config(d);a,b=servers
                c.update({'provider':'chat_completions','base_url':f'http://127.0.0.1:{a.server_port}','model':'general-fixture','thinking_adapter':'deepseek','thinking_mode':'off','pmm':{'api':{'provider':'chat_completions','base_url':f'http://127.0.0.1:{b.server_port}','model':'psych-fixture','thinking_adapter':'deepseek','thinking_mode':'low'}}})
                st=Store(d)
                try:
                    r=Engine(st,c).turn(st.session(),TEXT);self.assertEqual(r['reply'],'说。');self.assertTrue(a.requests);self.assertTrue(b.requests)
                    self.assertTrue(all(req[1]['thinking']['type']=='disabled' for req in a.requests));self.assertTrue(all(req[1]['reasoning_effort']=='low' for req in b.requests))
                    t=r['trace']['timing'];self.assertGreater(t['total_ms'],0);self.assertGreaterEqual(t['total_ms'],t['general_api_ms']);self.assertEqual(len(t['stages']),8);self.assertTrue(all(x['stage']!='model_request' for x in r['trace']['api_calls']))
                finally:st.close()
        finally:
            for server in servers:server.shutdown();server.server_close()

if __name__=='__main__':unittest.main()

import test_api as api_tests
class PatchHTTPTests(unittest.TestCase):
    setUp=api_tests.APITests.setUp
    tearDown=api_tests.APITests.tearDown
    request=api_tests.APITests.request
    def test_character_endpoint_is_revision_checked_and_idle_guarded(self):
        before=self.request('/api/state');revision=before['profile']['revision']
        r=self.request('/api/persona/settings',{'name':'林','self_reference':'我','initial_personality':'谨慎','expected_revision':revision})
        self.assertTrue(r['changed']);after=self.request('/api/state');self.assertEqual(after['profile']['name'],'林');self.assertEqual(before['identity'],after['identity'])
        self.app.jobs['busy']={'status':'running'}
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/persona/settings',{'name':'不应保存'})
        self.assertEqual(self.app.engine.profile()['name'],'林')
    def test_thinking_settings_and_copy_general_endpoint(self):
        self.request('/api/config',{'thinking_mode':'off','thinking_adapter':'deepseek','pmm':{'api':{'thinking_mode':'low','thinking_adapter':'openai'}}})
        c=self.request('/api/state')['config'];self.assertEqual(c['thinking_mode'],'off');self.assertEqual(c['pmm']['api']['thinking_mode'],'low')
        self.request('/api/pmm/api/copy-general',{});self.assertEqual(self.request('/api/state')['config']['pmm']['api']['thinking_mode'],'off')
    def test_diagnostic_error_reaches_http_client_and_event_log(self):
        self.request('/api/config',{'provider':'chat_completions','base_url':'https://api.deepseek.com/chat/completions','model':'deepseek-flash','thinking_mode':'low'})
        with patch('persona.provider.request_json',side_effect=ProviderError('fixture 400',{'http_status':400,'param':'reasoning_effort'})):
            with self.assertRaises(urllib.error.HTTPError) as caught:self.request('/api/test-model',{})
        body=json.load(caught.exception);self.assertEqual(body['diagnostics']['call']['response']['http_status'],400)
        e=self.request('/api/events')[0];self.assertEqual(e['kind'],'connection_test');self.assertFalse(e['payload']['ok'])
    def test_paginated_history_export_and_qq_status_endpoints(self):
        with self.app.store.lock,self.app.store.db:
            for i in range(130):self.app.store.event('config_updated',{'i':i})
        self.assertEqual(len(self.request('/api/events?limit=120')),120);self.assertGreater(len(self.request('/api/events?offset=120')),0)
        export=self.request('/api/events/export');self.assertGreaterEqual(len(export['events']),130)
        q=self.request('/api/qq/status');self.assertFalse(q['enabled']);self.assertNotIn('api_token',json.dumps(q));self.assertNotIn('inbound_token',json.dumps(q))
