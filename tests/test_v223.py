"""Audit regressions: synthetic records, local HTTP and deterministic providers only."""
import copy,json,tempfile,unittest,urllib.error,hashlib
from pathlib import Path
from unittest.mock import patch
from persona.common import Config,DEFAULT_CONFIG
from persona.provider import Provider,ProviderError
from persona.psychology import parse_records,validate_profile
from persona.thinking import apply_thinking
from test_v212 import Base,PatchProvider
import test_v212


class ConfigAuditTests(Base):
    def test_retrieval_numeric_settings_reject_strings_floats_and_booleans(self):
        before=self.r.config.get()
        for key in ('retrieval_k','max_retrieval_rounds'):
            for value in ('1',1.5,True):
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):self.r.configure({key:value})
                self.assertEqual(self.r.config.get(),before)
        for body in ({'timeout':'120'},{'timeout':None},{'temperature':'0.65'},{'temperature':True},{'pmm':{'timeout':'120'}},{'pmm':{'api':{'timeout':'120'}}}):
            with self.subTest(body=body),self.assertRaises(ValueError):self.r.configure(body)
            self.assertEqual(self.r.config.get(),before)
    def test_plain_number_private_recipient_is_normalized_without_widening_qq(self):
        self.enable();before=self.r.config.get()['qq']
        self.r.configure({'social':{'enabled':True,'recipients':['123']}})
        self.assertEqual(self.r.config.get()['social']['recipients'],['private:qq:123'])
        self.assertEqual(self.r.config.get()['qq'],before)
    def test_ambiguous_plain_number_never_guesses_a_channel(self):
        self.enable();before=self.r.config.get()
        with self.assertRaises(ValueError):self.r.configure({'social':{'private_enabled':True,'group_enabled':True,'recipients':['123']}})
        self.assertEqual(self.r.config.get(),before)
    def test_inactive_social_draft_can_be_saved_before_qq_setup(self):
        self.r.configure({'social':{'enabled':False,'recipients':['123']}})
        self.assertFalse(self.r.config.get()['qq']['enabled'])
        self.assertEqual(self.r.config.get()['social']['recipients'],['private:qq:123'])
        self.assertTrue(self.r.engine.social.status()['activation_missing'])
    def test_activation_lists_missing_fields_and_keeps_settings_atomic(self):
        before=self.r.config.get()
        with self.assertRaises(ValueError) as err:self.r.configure({'social':{'enabled':True,'recipients':['123']}})
        self.assertIn('/qq/self_id',err.exception.failed_fields)
        self.assertIn('/qq/allowed_users',err.exception.failed_fields)
        self.assertEqual(self.r.config.get(),before)
    def test_disabling_qq_also_disables_auto_contact_and_revocation_removes_recipient(self):
        self.enable();self.r.configure({'social':{'enabled':True,'recipients':['123']}})
        self.r.configure({'qq':{'enabled':False}});self.assertFalse(self.r.config.get()['social']['enabled'])
        self.r.configure({'qq':{'allowed_users':[]}});self.assertEqual(self.r.config.get()['social']['recipients'],[])
    def test_typed_group_recipient_is_never_sent_to_a_private_number(self):
        self.r.configure({'qq':{'enabled':True,'self_id':'999','allowed_groups':['123']},'social':{'group_enabled':True,'private_enabled':False,'recipients':['123'],'enabled':True}})
        self.assertEqual(self.r.config.get()['social']['recipients'],['group:qq:123'])
        self.assertEqual(self.r.config.get()['qq']['allowed_users'],[])


class ConfigHttpAudit(unittest.TestCase):
    from test_api import APITests
    setUp=APITests.setUp;tearDown=APITests.tearDown;request=APITests.request
    def test_malformed_sections_are_400_not_internal_errors_and_do_not_write(self):
        before=self.app.config.path.read_bytes()
        for body in ({'qq':None},{'pmm':[]},{'pmm':{'api':None}},{'social':False},{'extra_body':[]},{'temperature':None},{'qq':{'allowed_users':None}}):
            with self.subTest(body=body),self.assertRaises(urllib.error.HTTPError) as err:self.request('/api/config',body)
            self.assertEqual(err.exception.code,400)
            self.assertEqual(json.load(err.exception)['code'],'INVALID_REQUEST')
            self.assertEqual(self.app.config.path.read_bytes(),before)
    def test_activation_errors_include_concrete_fields(self):
        with self.assertRaises(urllib.error.HTTPError) as err:self.request('/api/config',{'social':{'enabled':True,'recipients':['123']}})
        out=json.load(err.exception);self.assertIn('/qq/enabled',out['failed_fields']);self.assertTrue(out['request_id'])


class PrivacyAuditTests(Base):
    def test_other_person_import_cannot_merge_distinct_scopes(self):
        records=parse_records(json.dumps([{'speaker':'A','text':'PRIVATE_OTHER','scope':'group:qq:1','id':'1'}]))
        before=self.r.store.meta('pmm_interlocutors');PatchProvider.seen=[]
        with self.assertRaises(ValueError):self.r.engine.import_records(records,target='interlocutor',person='qq:123',scope='group:qq:2')
        self.assertEqual(self.r.store.meta('pmm_interlocutors'),before);self.assertEqual(PatchProvider.seen,[])
    def correction(self):
        sid=self.session('123');turn=self.turn('A_PRIVATE_CONTEXT_4827',sid=sid)
        self.r.engine.feedback(turn['turn_id'],'unhelpful',corrected_reply='PRIVATE_7391')
        return sid
    def test_human_private_example_stays_out_of_both_models_in_another_scope(self):
        self.correction();PatchProvider.seen=[];self.turn('另一位的普通话题',sid=self.session('456'))
        seen=json.dumps(PatchProvider.seen)
        self.assertNotIn('A_PRIVATE_CONTEXT_4827',seen);self.assertNotIn('PRIVATE_7391',seen)
        markers=[m[0]['content'] for m in PatchProvider.seen]
        self.assertTrue(any('[API_PMM_PREPARE_V2]' in x for x in markers));self.assertTrue(any('[REALIZE_V3]' in x for x in markers))
    def test_human_example_remains_available_in_its_authorized_scope(self):
        sid=self.correction();PatchProvider.seen=[];self.turn('后续问题',sid=sid)
        self.assertIn('PRIVATE_7391',json.dumps(PatchProvider.seen))
    def test_legacy_unscoped_correction_is_retained_locally_but_not_broadcast(self):
        self.correction();p=self.r.engine.profile()
        for r in p['source_records']:
            if r['source']=='human':r.pop('scope',None)
        with self.r.store.lock,self.r.store.db:self.r.store.setmeta('pmm_profile',p)
        PatchProvider.seen=[];self.turn('other',sid=self.session('456'))
        self.assertNotIn('PRIVATE_7391',json.dumps(PatchProvider.seen))
        self.assertIn('PRIVATE_7391',json.dumps(self.r.engine.profile()))
    def test_template_does_not_export_private_correction_text_or_context(self):
        self.correction();pack=self.r.subjects.export_pack(self.r.engine,'template');validate_profile(pack['profile'])
        self.assertNotIn('PRIVATE_7391',json.dumps(pack));self.assertNotIn('A_PRIVATE_CONTEXT_4827',json.dumps(pack))
    def test_scoped_imports_are_not_global_language_examples(self):
        records=parse_records(json.dumps([{'speaker':'target','text':'IMPORTED_SCOPE_ONLY','scope':'private:qq:123','id':'100'}]))
        self.r.engine.import_records(records)
        PatchProvider.seen=[];self.turn('other',sid=self.session('456'))
        self.assertNotIn('IMPORTED_SCOPE_ONLY',json.dumps(PatchProvider.seen))
        self.assertNotIn('IMPORTED_SCOPE_ONLY',json.dumps(self.r.subjects.export_pack(self.r.engine,'template')))


class ImportAuditTests(unittest.TestCase):
    def test_interleaved_groups_preserve_provenance_without_cross_group_context(self):
        rows=[{'speaker':'A','text':'GROUP_1_PRIVATE','group_id':1,'id':1,'timestamp':'2026-01-01'},
              {'speaker':'B','text':'GROUP_2_PRIVATE','group_id':2,'id':2},
              {'speaker':'C','text':'answer','group_id':1,'id':3,'reply_to':'1'}]
        r=parse_records(json.dumps(rows))
        self.assertEqual(r[1]['context'],'');self.assertEqual(r[2]['context'],'GROUP_1_PRIVATE')
        self.assertEqual(r[0]['scope'],'group:qq:1');self.assertEqual(r[0]['timestamp'],'2026-01-01');self.assertEqual(r[2]['context_record_id'],r[0]['id'])
    def test_cross_scope_reply_reference_is_not_resolved(self):
        r=parse_records(json.dumps([{'speaker':'A','text':'secret','scope':'group:qq:1','id':'1'},{'speaker':'B','text':'answer','scope':'group:qq:2','reply_to':'1','id':'2'}]))
        self.assertEqual(r[1]['context'],'')
    def test_source_id_deduplication_survives_export_batch_boundaries(self):
        row={'speaker':'A','text':'same','scope':'group:qq:1','id':1}
        first=parse_records(json.dumps([row]));again=parse_records(json.dumps([{'speaker':'B','text':'previous','scope':'group:qq:1','id':2},row]))
        self.assertEqual(first[0]['id'],again[-1]['id'])
        self.assertEqual(len(parse_records(json.dumps([row,row]))),1)
    def test_conflicting_message_identity_rejected(self):
        row={'speaker':'A','text':'same','scope':'group:qq:1','id':1}
        with self.assertRaises(ValueError):parse_records(json.dumps([row,{**row,'text':'changed'}]))


class ThinkingAuditTests(unittest.TestCase):
    def cfg(self,**kw):
        c=copy.deepcopy(DEFAULT_CONFIG);c.update(model='deepseek-flash',base_url='https://api.deepseek.com',provider='responses');c.update(kw);return c
    def test_deepseek_native_protocols_use_their_actual_thinking_shape(self):
        for proto in ('chat_completions','responses','anthropic'):
            for mode in ('off','low','high'):
                body,info=apply_thinking({'max_tokens':16000},self.cfg(provider=proto,thinking_mode=mode))
                self.assertEqual(info['adapter'],'deepseek')
                if proto=='responses':self.assertEqual(body['reasoning']['effort'],'none' if mode=='off' else mode)
                else:
                    self.assertEqual(body['thinking']['type'],'disabled' if mode=='off' else 'enabled')
                    if mode!='off':self.assertEqual(body['output_config']['effort'] if proto=='anthropic' else body['reasoning_effort'],mode)
    def test_ollama_boolean_enable_is_distinct_from_low_high(self):
        c=self.cfg(provider='ollama',base_url='http://127.0.0.1:11434',model='qwen3',thinking_mode='on')
        with patch('persona.provider.request_json',side_effect=[{'thinking':{'values':[False,True]}},{'message':{'content':'ok'}}]) as req:
            self.assertEqual(Provider(c).complete([{'role':'user','content':'hi'}]),'ok');self.assertIs(req.call_args.args[1]['think'],True)
        c['thinking_mode']='low'
        with patch('persona.provider.request_json',return_value={'thinking':{'values':[False,True]}}) as req:
            with self.assertRaises(ProviderError):Provider(c).complete([{'role':'user','content':'hi'}])
            self.assertEqual(req.call_count,1)
    def test_non_ollama_boolean_enable_does_not_guess_an_effort(self):
        with self.assertRaises(ValueError):apply_thinking({},self.cfg(thinking_mode='on'))
    def test_deepseek_additional_controls_still_conflict(self):
        for proto,extra in [('responses',{'reasoning':{'effort':'high'}}),('anthropic',{'output_config':{'effort':'high'}})]:
            with self.assertRaises(ValueError):apply_thinking({},self.cfg(provider=proto,thinking_mode='off',extra_body=extra))
    def test_deepseek_endpoints_and_final_text_are_protocol_specific(self):
        cases=[('chat_completions','/chat/completions',{'choices':[{'finish_reason':'stop','message':{'content':'ok','reasoning_content':'PRIVATE_REASONING'}}]}),
               ('responses','/responses',{'status':'completed','output':[{'type':'reasoning','summary':[{'text':'PRIVATE_REASONING'}]},{'type':'message','content':[{'type':'output_text','text':'ok'}]}]}),
               ('anthropic','/anthropic/v1/messages',{'stop_reason':'end_turn','content':[{'type':'thinking','thinking':'PRIVATE_REASONING'},{'type':'text','text':'ok'}]})]
        for proto,url,result in cases:
            provider=Provider(self.cfg(provider=proto,thinking_mode='high'))
            with self.subTest(protocol=proto),patch('persona.provider.request_json',return_value=result) as req:
                self.assertEqual(provider.complete([{'role':'user','content':'hi'}]),'ok')
                self.assertEqual(req.call_args.args[0],'https://api.deepseek.com'+url)
                self.assertNotIn('PRIVATE_REASONING',json.dumps(provider.calls));self.assertEqual(provider._url('models'),'https://api.deepseek.com/models')


class CompletionFailureAudit(unittest.TestCase):
    def test_finish_causes_are_distinct_and_never_return_partial_or_reasoning_text(self):
        cases=[('chat_completions',{'choices':[{'finish_reason':'length','message':{'content':'PARTIAL_PRIVATE'}}]},'OUTPUT_LIMIT'),
               ('chat_completions',{'choices':[{'finish_reason':'content_filter','message':{}}]},'CONTENT_FILTER'),
               ('chat_completions',{'choices':[{'finish_reason':'tool_calls','message':{'content':'PARTIAL_PRIVATE'}}]},'UNSUPPORTED_TOOL_CALL'),
               ('chat_completions',{'choices':[{'finish_reason':'stop','message':{'reasoning_content':'PRIVATE_REASONING'}}]},'REASONING_ONLY'),
               ('responses',{'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},'output':[]},'OUTPUT_LIMIT'),
               ('responses',{'status':'incomplete','incomplete_details':{'reason':'content_filter'},'output':[]},'CONTENT_FILTER'),
               ('anthropic',{'stop_reason':'max_tokens','content':[]},'OUTPUT_LIMIT'),
               ('anthropic',{'stop_reason':'refusal','content':[]},'MODEL_REFUSAL'),
               ('gemini',{'candidates':[{'finishReason':'MAX_TOKENS'}]},'OUTPUT_LIMIT'),
               ('gemini',{'promptFeedback':{'blockReason':'SAFETY'}},'CONTENT_FILTER'),
               ('ollama',{'done':False,'message':{}},'INCOMPLETE_RESPONSE')]
        for proto,result,code in cases:
            c=copy.deepcopy(DEFAULT_CONFIG);c.update(provider=proto,model='fixture',thinking_mode='default')
            with self.subTest(protocol=proto,code=code),patch('persona.provider.request_json',return_value=result),self.assertRaises(ProviderError) as err:
                Provider(c).complete([{'role':'user','content':'hi'}])
            detail=err.exception.details['call'];self.assertEqual(detail['response']['code'],code)
            self.assertEqual(detail['status'],'error');self.assertNotIn('PRIVATE',json.dumps(detail))
            self.assertIn('request_options',detail)


class RetrievalAudit(Base):
    def setup_provider(self,repeated=False):
        counter=[]
        class P(PatchProvider):
            def complete(self,messages,structured=False,controller=False):
                result=super().complete(messages,structured,controller)
                if '[API_PMM_PREPARE_V2]' in messages[0]['content']:
                    counter.append(1);result['retrieval_queries']=['query-'+str(1 if repeated else len(counter))]
                return result
        self.r.engine.pmm_provider_factory=P
        self.r.configure({'deliberation':{'mode':'off'},'performance':{'mode':'full'}})
        return counter
    def test_zero_one_two_retrieval_rounds_are_obeyed(self):
        for count in (0,1,2):
            counter=self.setup_provider();self.r.configure({'max_retrieval_rounds':count})
            turn=self.turn();self.assertEqual(len(counter),count+1)
            self.assertEqual(len(self.r.engine.journal.get(turn['turn_id'])['retrieval_rounds']),count)
    def test_repeating_query_does_not_consume_extra_network_calls(self):
        counter=self.setup_provider(repeated=True);self.r.configure({'max_retrieval_rounds':2})
        self.turn();self.assertEqual(len(counter),2)


class ErasureUpgradeAudit(unittest.TestCase):
    def check_erasure(self,erase_default):
        from persona.server import Runtime
        from persona.erasure import erase_scope
        from test_v222 import populate,ROOT
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);first,second,_,_=populate(root);r=Runtime(root,ROOT)
            try:
                backup=Path(r.upgrade['backup']);own=first if erase_default else second;other=second if erase_default else first
                r.switch(own)
                own_relative=Path('.') if own==first else Path('subjects')/own
                other_relative=Path('.') if other==first else Path('subjects')/other
                # Both raw and standalone snapshots must be removed only for this identity.
                other_files=[backup/other_relative/'subject.sqlite3',backup/'sqlite_snapshots'/other_relative/'subject.sqlite3']
                before=[hashlib.sha256(p.read_bytes()).hexdigest() for p in other_files]
                erase_scope(r.engine,'private:qq:123','ERASE:private:qq:123')
                for parent in (backup/own_relative,backup/'sqlite_snapshots'/own_relative):
                    self.assertFalse((parent/'subject.sqlite3').exists());self.assertFalse((parent/'execution.sqlite3').exists())
                self.assertEqual([hashlib.sha256(p.read_bytes()).hexdigest() for p in other_files],before)
                manifest=json.loads((backup/'recovery_manifest.json').read_text());self.assertEqual(manifest['status'],'partially_erased');self.assertIn(own,manifest['erased_personas'])
                self.assertEqual(len(r.context(other)[0].rows('SELECT * FROM messages')),4 if other==first else 0)
            finally:r.close()
    def test_default_persona_erasure_preserves_other_persona_backup(self):self.check_erasure(True)
    def test_secondary_persona_erasure_preserves_default_persona_backup(self):self.check_erasure(False)
    def test_unattributable_backup_stops_before_live_database_change(self):
        from persona.server import Runtime
        from persona.erasure import erase_scope
        from test_v222 import ROOT
        with tempfile.TemporaryDirectory() as directory:
            r=Runtime(directory,ROOT)
            try:
                p=Path(directory)/'backups'/'pre-unknown';p.mkdir();(p/'subject.sqlite3').write_bytes(b'unknown')
                before=r.snapshot()
                with self.assertRaises(ValueError):erase_scope(r.engine,'private:qq:123','ERASE:private:qq:123')
                after=r.snapshot();self.assertEqual(after['tables'],before['tables']);self.assertEqual(after['execution'],before['execution'])
            finally:r.close()


class SocialCandidateAudit(Base):
    ready=test_v212.SocialTests.ready
    def test_repaired_candidate_must_pass_hard_boundary_again(self):
        self.ready();p=self.r.engine.profile();p['boundaries'].append({'id':'owner-hard','label':'合成限制','keywords':['FORBIDDEN_MARKER'],'action':'decline','enabled':True,'hard':True,'evidence':[],'source':'human','confidence':1})
        with self.r.store.lock,self.r.store.db:self.r.store.setmeta('pmm_profile',p)
        class RepairProvider(PatchProvider):
            def complete(self,messages,structured=False,controller=False):
                if '[SOCIAL_REALIZE_V212]' in messages[0]['content'] and 'repair' in json.loads(messages[-1]['content']):return 'FORBIDDEN_MARKER'
                return super().complete(messages,structured,controller)
        self.r.engine.provider_factory=RepairProvider
        with patch('persona.validation.validated_call',side_effect=[{'compliant':False,'failure_code':'ACTION_MISMATCH','detected_action':'unknown','spans':[]},{'compliant':True}]),patch('persona.qq.verify_bot'),patch('persona.social.request_json',return_value={'retcode':0,'status':'ok','data':{'message_id':'99'}}) as send:
            with self.assertRaises(ProviderError):self.r.engine.social.evaluate('private:qq:123',send=True)
            send.assert_not_called();self.assertEqual(self.r.engine.journal.outbox(),[])


class TemplateCloneAudit(Base):
    def test_capability_report_separates_api_state_and_real_training(self):
        report=self.r.state()['capabilities'];self.assertTrue(report['state_updates_enabled']);self.assertFalse(report['parameter_training_available'])
        self.assertEqual(report['modules']['pmm_condition']['mechanisms'],['api_inference'])
        self.assertEqual(report['modules']['video_audio_understanding']['mechanisms'],['not_implemented'])
        self.r.configure({'pmm':{'mode':'learned'}});report=self.r.state()['capabilities']
        self.assertTrue(report['parameter_training_available']);self.assertEqual(report['modules']['pmm_condition']['trained_steps'],0)
        self.assertFalse(report['psychological_validity_established']);self.assertFalse(report['mock_fallback'])
    def test_clone_has_new_identity_and_no_private_records_relationships_credentials_or_weights(self):
        source=self.r.engine.profile()['id'];self.enable();turn=self.turn('CLONE_PRIVATE_CONTEXT')
        self.r.engine.feedback(turn['turn_id'],'unhelpful',corrected_reply='CLONE_SECRET')
        records=parse_records('A: allowed template expression');self.r.engine.import_records(records)
        self.r.engine.boundaries.edit({'topic':'尊重自主','domain':'autonomy'})
        old=self.r.store.snapshot()['tables'];new=self.r.clone_persona({'name':'独立副本'})
        self.assertNotEqual(source,new['identity']['id']);self.assertEqual(new['profile']['id'],new['identity']['id'])
        self.assertIn('allowed template expression',json.dumps(new['profile']))
        self.assertNotIn('CLONE_SECRET',json.dumps(new));self.assertNotIn('CLONE_PRIVATE_CONTEXT',json.dumps(new))
        self.assertEqual(new['sessions'],[]);self.assertEqual(new['dyads'],{});self.assertEqual(new['interlocutors'],{})
        self.assertEqual(self.r.engine.model.export()['samples'],[]);self.assertFalse(new['config']['qq']['enabled'])
        self.assertEqual(self.r.config.get()['api_key'],'');self.assertEqual(self.r.config.get()['pmm']['api']['api_key'],'')
        self.assertEqual(self.r.config.get()['qq']['allowed_users'],[])
        self.assertEqual(self.r.context(source)[0].snapshot()['tables'],old)
        self.r.switch(source);self.assertEqual(self.r.engine.profile()['id'],source)
    def test_invalid_clone_name_does_not_create_a_subject(self):
        before=copy.deepcopy(self.r.subjects.catalog)
        with self.assertRaises(ValueError):self.r.clone_persona({'name':''})
        self.assertEqual(self.r.subjects.catalog,before)


if __name__=='__main__':unittest.main(verbosity=2)
