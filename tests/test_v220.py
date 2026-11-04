"""2.2 mechanisms: deterministic contract tests, not psychological validity evidence."""
import argparse, copy, hashlib, io, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from test_v212 import Base, PatchProvider, ROOT
from persona.common import now,VERSION
from persona.cognition import FIELDS,DIM,AppraisalHead,action_policy,features,validate_appraisal
from persona.qq import QQBridge
from persona.packages import export_continuity,validate_pack,apply_pack
from persona.support import report
from scripts.export_sources import build,files
import launcher

EST={'turn_complete':.99,'addressed':.99,'personal_relevance':.9,'relationship_salience':.6,'novelty':.6,'emotional_salience':.4,'uncertainty':.03,'conflict':.03,'consequence':.05,'event_boundary':.1}
def appraisal(records,est=None):
    r=records[0]
    return {'estimates':{**EST,**(est or {})},'evidence':[{'record_id':r['id'],'quote':r['text'],'fields':['turn_complete','addressed']}],'summary':'deterministic appraisal fixture'}

class AdaptiveBase(Base):
    def setUp(self):
        super().setUp();self.r.configure({'cognition':{'mode':'adaptive'}})
        self.enable();self.sent=[];self.est={};self.audit_seen=[];self.realize=[];self.prompt_inputs=[];self.bad=False;outer=self
        class P(PatchProvider):
            def complete(self,messages,structured=False,controller=False):
                system=messages[0]['content']
                if '[COGNITIVE_' in system:
                    ctx=json.loads(messages[-1]['content']);outer.prompt_inputs.append((system,ctx))
                    result=appraisal(ctx['records'],outer.est)
                    if outer.bad:result['evidence'][0]['quote']='fabricated quote'
                    return result
                if '[REALIZE_V3]' in system:
                    outer.audit_seen.append(outer.r.engine.cognition.status()['recent']);outer.realize.append(system)
                return super().complete(messages,structured,controller)
        self.provider=P;self.r.engine.provider_factory=P;self.r.engine.pmm_provider_factory=P
    def receive(self,text='测试片段',mid=1):return self.r.bridge.receive(self.event(mid=mid,message=[{'type':'text','data':{'text':text}}]))
    def row(self):return self.r.store.rows("SELECT * FROM inbox WHERE status='pending' ORDER BY created_at LIMIT 1")[0]
    def remote(self,url,payload=None,*args,**kwargs):
        if url.endswith('/get_login_info'):return {'retcode':0,'data':{'user_id':999}}
        self.sent.append(payload);return {'retcode':0,'status':'ok','data':{'message_id':77}}
    def process(self):
        with patch('persona.qq.request_json',side_effect=self.remote):self.r.bridge.process(self.row())
    def records(self):return self.r.engine.cognition.status()['recent']

class ProspectiveTests(AdaptiveBase):
    def test_default_new_and_old_configs_enable_adaptive(self):
        from persona.common import Config
        with tempfile.TemporaryDirectory() as d:
            c=Config(d);self.assertEqual(c.get()['cognition']['mode'],'adaptive')
            raw=c.get();raw.pop('cognition');c.path.write_text(json.dumps(raw));self.assertEqual(c.get()['cognition']['mode'],'adaptive')
    def test_reply_audit_exists_before_realize_and_links_to_commit(self):
        self.receive();self.process();self.assertEqual(len(self.sent),1)
        self.assertTrue(self.audit_seen[0][0]['before_generation']);audit=self.records()[0]
        turns=[r['payload'] for r in self.r.store.recent_events() if r['kind']=='turn']
        self.assertEqual(turns[0]['decision']['cognitive_id'],audit['id'])
        self.assertEqual(turns[0]['turn_context']['raw_records'][0]['text'],'测试片段')
        self.assertEqual(self.r.store.meta('memory_pending')[0]['records'][0]['id'],audit['source_ids'][0])
    def test_semantic_incompletion_waits_without_generation(self):
        self.est={'turn_complete':.03};self.receive('还有一件事');self.process()
        self.assertEqual(self.records()[0]['decision']['action'],'WAIT');self.assertFalse(self.sent);self.assertFalse(self.realize)
        self.assertEqual(self.row()['status'],'pending')
    def test_elapsed_wait_never_forces_reply_and_new_input_resumes(self):
        self.est={'turn_complete':.01};self.receive();row=self.row();b=self.r.bridge.turn_taking.snapshot(row)
        with self.r.store.lock,self.r.store.db:
            bs=self.r.store.meta('turn_buffers');bs[b['key']]['first']=now()-20;self.r.store.setmeta('turn_buffers',bs)
        self.process();rows=self.r.store.rows('SELECT * FROM inbox');self.assertEqual(rows[0]['status'],'awaiting_input');self.assertFalse(self.sent)
        self.est={};self.receive('我说完了',2);self.assertEqual(len(self.row()['payload'])>0,True);self.process()
        self.assertEqual(len(self.sent),1);self.assertEqual(len(self.r.store.rows("SELECT * FROM inbox WHERE status='sent'")),2)
    def test_invalid_evidence_is_audited_and_retry_safe(self):
        self.bad=True;self.receive();identifier=self.row()['id'];self.process()
        self.assertEqual(self.records()[0]['status'],'failed');self.assertFalse(self.sent)
        self.assertEqual(self.r.bridge.turn_taking.retry(identifier)['queued'],1);self.bad=False;self.process();self.assertEqual(len(self.sent),1)
        with self.assertRaises(ValueError):self.r.bridge.turn_taking.retry(identifier)
    def test_waiting_sources_survive_restart(self):
        self.bad=True;self.receive();self.process();identifier=self.r.store.rows('SELECT id FROM inbox')[0]['id']
        other=QQBridge(self.r.engine);self.assertTrue(any(identifier in b['ids'] for b in self.r.store.meta('turn_buffers').values()))
        self.assertEqual(other.turn_taking.retry(identifier)['queued'],1)
    def test_clarification_reaches_generation(self):
        self.est={'uncertainty':.95,'conflict':.1,'consequence':.1};self.receive('那个是指谁');self.process()
        self.assertEqual(self.records()[0]['decision']['action'],'CLARIFY');self.assertEqual(len(self.sent),1)
        self.assertEqual(json.loads(self.realize[0].split('\n条件：',1)[1])['decision']['action'],'clarify')
    def test_failure_does_not_change_personality_or_relationship(self):
        p=copy.deepcopy(self.r.engine.profile());d=self.r.store.meta('pmm_dyads');self.bad=True;self.receive();self.process()
        self.assertEqual(p,self.r.engine.profile());self.assertEqual(d,self.r.store.meta('pmm_dyads'));self.assertEqual(self.r.store.meta('state')['turn_count'],0)
    def test_api_and_numeric_have_different_inputs_and_real_update(self):
        self.r.configure({'pmm':{'mode':'learned'}});self.receive();self.process();audit=self.records()[0]
        self.assertEqual(audit['mechanism'],'learned');self.assertIn('numeric_head_digest',audit);self.assertIn('numeric_action_prior',audit)
        prompt,ctx=self.prompt_inputs[0];self.assertIn('COGNITIVE_CUES',prompt);self.assertNotIn('self',ctx);self.assertNotIn('relationship',ctx)
        # Find a train split identifier with a real recorded input vector.
        full=json.loads(self.r.store.rows("SELECT payload FROM events WHERE kind='cognitive_decision'")[0]['payload'])
        old=AppraisalHead().export()
        result=self.r.engine.cognition.feedback(full['id'],{'turn_complete':0})
        new=self.r.store.meta('cognitive_head')
        if result['heldout']:self.assertEqual(new['weights'],old['weights'])
        else:self.assertNotEqual(new['weights'],old['weights'])
        self.assertFalse(self.r.engine.cognition.status()['calibrated'])
    def test_api_feedback_does_not_claim_numeric_weight_update(self):
        self.receive();self.process();r=self.r.engine.cognition.feedback(self.records()[0]['id'],{'turn_complete':.8})
        self.assertFalse(r['numeric_updated']);self.assertIsNone(self.r.store.meta('cognitive_head'))
        self.receive('继续',2);self.process();self.assertEqual(self.prompt_inputs[-1][1]['human_calibration'][0]['targets']['turn_complete'],.8)
    def test_group_every_n_sampling_is_inactive_and_budget_remains(self):
        self.r.configure({'qq':{'allowed_groups':['321']},'group_attention':{'enabled':True,'sample_every':50,'per_minute':2}})
        p={'scope':'group:qq:321','thread':''};records=[{'id':'a','text':'不包含关键词'}]
        self.assertTrue(self.r.engine.group_attention.reserve(p,records));self.assertTrue(self.r.engine.group_attention.reserve(p,records));self.assertFalse(self.r.engine.group_attention.reserve(p,records))
    def test_unmentioned_permission_still_blocks_send(self):
        self.r.configure({'qq':{'allowed_groups':['321']},'group_attention':{'enabled':True,'allow_unmentioned_reply':False}})
        ev=self.event();ev.update(message_type='group',group_id=321);self.r.bridge.receive(ev);self.process()
        self.assertFalse(self.sent);self.assertNotIn(self.records()[0]['decision']['action'],('REPLY','CLARIFY'))
        self.assertEqual(self.r.engine.group_attention.status()['people'][0]['direct_interactions'],0)
    def test_superseded_input_cannot_commit_old_decision(self):
        outer=self;provider=self.provider
        class Later(provider):
            once=False
            def complete(self,messages,*args,**kw):
                if '[REALIZE_V3]' in messages[0]['content'] and not self.once:Later.once=True;outer.receive('新补充',2)
                return super().complete(messages,*args,**kw)
        self.r.engine.provider_factory=Later;self.receive();self.process();self.assertFalse(self.sent);self.assertFalse(self.r.store.history(self.r.store.sessions()[0]['id']))
        self.process();self.assertEqual(len(self.sent),1)
    def test_continuity_and_snapshot_keep_validated_cognition(self):
        self.receive();self.process();self.r.engine.cognition.feedback(self.records()[0]['id'],{'conflict':.2})
        pack=export_continuity(self.r.engine);v=validate_pack(pack);self.assertEqual(v[0]['cognitive_feedback'][0]['targets'],{'conflict':.2})
        bad=copy.deepcopy(pack);bad['cognitive_state']['head']={'format':'cognitive-head/1','weights':[[1]]}
        with self.assertRaises(ValueError):validate_pack(bad)
        snap=self.r.snapshot();meta=next(r for r in snap['tables']['meta'] if r['key']=='cognitive_feedback');meta['value']='[{"id":"bad"}]'
        with self.assertRaises(ValueError):self.r.store.restore(snap)

class HeadTests(unittest.TestCase):
    def test_evidence_and_finite_numbers_required(self):
        records=[{'id':'r','text':'原文'}]
        for mutation in ('nan','missing','source','quote','field','bool'):
            a=appraisal(records)
            if mutation=='nan':a['estimates']['conflict']=float('nan')
            if mutation=='missing':a['estimates'].pop('uncertainty')
            if mutation=='source':a['evidence'][0]['record_id']='other'
            if mutation=='quote':a['evidence'][0]['quote']='不存在'
            if mutation=='field':a['evidence'][0]['fields']=['fake']
            if mutation=='bool':a['estimates']['conflict']=True
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):validate_appraisal(a,records)
    def test_same_cues_change_with_known_personality(self):
        from persona.registry import empty_state,ORDER
        profile={'psychology':empty_state()};profile2=copy.deepcopy(profile)
        profile2['psychology']['features']['hexaco.x.sociability']['estimate']=1
        activity={'emotion':{'valence':0,'arousal':.2,'stress':.1,'engagement':.5}};h=AppraisalHead()
        a=h.predict(features(EST,profile,activity,{},0));b=h.predict(features(EST,profile2,activity,{},0));self.assertGreater(b['personal_relevance'],a['personal_relevance'])
        profile2['psychology']['features']['affect.vad.valence']['estimate']=-1
        self.assertLessEqual(max(abs(features(EST,profile2,activity,{},0))),1)
    def test_human_targets_change_weights_and_heldout_never_trains(self):
        h=AppraisalHead();x=np.zeros(DIM);x[0]=1
        train=next(str(i) for i in range(100) if int(hashlib.sha256(str(i).encode()).hexdigest()[:8],16)%5!=0)
        held=next(str(i) for i in range(100) if int(hashlib.sha256(str(i).encode()).hexdigest()[:8],16)%5==0)
        before=h.predict(x)['turn_complete'];self.assertFalse(h.learn(train,x,{'turn_complete':0}));self.assertLess(h.predict(x)['turn_complete'],before)
        weights=h.weights.copy();steps=h.steps;self.assertTrue(h.learn(held,x,{'turn_complete':1}));np.testing.assert_array_equal(weights,h.weights);self.assertEqual(h.steps,steps);self.assertEqual(h.metrics()['heldout']['labels'],1)
    def test_actions_depend_on_completion_and_uncertainty(self):
        self.assertEqual(action_policy(EST,0,True)['action'],'REPLY')
        self.assertEqual(action_policy({**EST,'turn_complete':0},0,True)['action'],'WAIT')
        self.assertEqual(action_policy({**EST,'uncertainty':1},0,True)['action'],'CLARIFY')
        self.assertNotIn(action_policy(EST,0,False)['action'],('REPLY','CLARIFY'))

class MemoryTests(AdaptiveBase):
    def enqueue(self,text,identifier,boundary=.1,thread='topic'):
        with self.r.store.lock,self.r.store.db:self.r.engine.memory_lifecycle.enqueue([{'id':identifier,'text':text}],'private:qq:123','qq:123',thread,appraisal={**EST,'event_boundary':boundary},cognitive_id='test-audit')
    def test_event_boundaries_segment_consolidation_batches(self):
        self.enqueue('我喜欢安静','a');self.enqueue('现在也喜欢安静','b',.1);self.enqueue('另一个事件开始','c',.9)
        rows=self.r.store.meta('memory_pending');self.assertEqual(rows[0]['event_id'],rows[1]['event_id']);self.assertNotEqual(rows[0]['event_id'],rows[2]['event_id'])
        result=self.r.engine.memory_lifecycle.run();self.assertEqual(result['processed'],2);self.assertEqual(len(self.r.store.meta('memory_pending')),1)
        state=export_continuity(self.r.engine);self.assertTrue(state['memory_state']['open_events']);validate_pack(state)
    def test_reconsolidation_preserves_conflicting_old_text_and_sources(self):
        self.enqueue('我喜欢安静','a');oldid=self.r.engine.memory_lifecycle.run()['saved'][0];old=self.r.store.rows('SELECT * FROM memories WHERE id=?',(oldid,))[0]
        self.enqueue('我现在不喜欢安静了','b',.9);provider=self.provider
        class Links(provider):
            def complete(self,messages,structured=False,controller=False):
                value=super().complete(messages,structured,controller)
                if '[MEMORY_GIST_V212]' in messages[0]['content']:
                    ctx=json.loads(messages[-1]['content']);assert any(m['id']==oldid for m in ctx['previous_memories'])
                    value['items'][0]['links']=[{'memory_id':oldid,'relation':'contradicts'}]
                return value
        self.r.engine.pmm_provider_factory=Links
        # The old gist fixture is generic; provide a deterministic contextual candidate.
        with patch.object(self.r.engine,'retrieve',return_value=[{**old,'relevance':.9}]):newid=self.r.engine.memory_lifecycle.run()['saved'][0]
        self.assertEqual(old['content'],self.r.store.rows('SELECT * FROM memories WHERE id=?',(oldid,))[0]['content'])
        traces=self.r.store.meta('memory_traces');self.assertEqual(traces[oldid]['links'][0]['memory_id'],newid);self.assertEqual(traces[newid]['links'][0]['memory_id'],oldid)
        self.assertEqual(self.r.engine.memory_lifecycle.sources(newid)['records'][0]['source_text'],'我现在不喜欢安静了');self.assertGreaterEqual(traces[oldid]['uncertainty'],.75)
    def test_cross_scope_link_rejected_before_write(self):
        self.enqueue('原始内容','a');provider=self.provider
        class Bad(provider):
            def complete(self,messages,structured=False,controller=False):
                value=super().complete(messages,structured,controller)
                if '[MEMORY_GIST_V212]' in messages[0]['content']:value['items'][0]['links']=[{'memory_id':'another-scope','relation':'updates'}]
                return value
        self.r.engine.pmm_provider_factory=Bad
        with self.assertRaises(ValueError):self.r.engine.memory_lifecycle.run()
        self.assertEqual(self.r.store.memories(),[]);self.assertEqual(self.r.store.meta('memory_pending')[0]['status'],'failed')
    def test_contextual_activation_depends_on_salience_not_fixed_half_life(self):
        self.enqueue('原始内容','a');mid=self.r.engine.memory_lifecycle.run()['saved'][0];m=self.r.store.memories()[0];traces=self.r.store.meta('memory_traces')
        a=copy.deepcopy(traces);b=copy.deepcopy(traces);a[mid]['salience']=0;b[mid]['salience']=1
        low=self.r.engine.memory_lifecycle.strength(m,t=now()+90*86400,traces=a);high=self.r.engine.memory_lifecycle.strength(m,t=now()+90*86400,traces=b)
        self.assertGreater(high['retrieval_strength'],low['retrieval_strength']);self.assertIsNone(high['half_life_days'])
        low2=self.r.engine.memory_lifecycle.strength(m,t=now()+90*86400,traces=a,half_life=365)
        self.assertAlmostEqual(low2['retrieval_strength'],low['retrieval_strength'],places=6)
    def test_only_evidence_selected_memories_are_rehearsed(self):
        sid=self.session();session=self.r.store.get_session(sid)
        with self.r.store.lock,self.r.store.db:mid=self.r.engine.add_memory('安静是对方偏好','fact',session,'raw','安静',1,.8)
        provider=self.provider
        class Unused(provider):
            def complete(self,messages,structured=False,controller=False):
                value=super().complete(messages,structured,controller)
                if '[API_PMM_PREPARE_V2]' in messages[0]['content']:
                    value['memory_focus']=[]
                    if value.get('direct_assessment'):value['direct_assessment']['supported_memory_evidence']=[]
                if any(k in messages[0]['content'] for k in ('[ASSESS_V21]','[DECIDE_V21]')):value['supported_memory_evidence']=[]
                return value
        self.r.engine.pmm_provider_factory=Unused;self.r.engine.provider_factory=Unused
        self.r.engine.turn(sid,'我喜欢安静');self.assertEqual(self.r.store.meta('memory_traces')[mid]['accesses'],0)
    def test_context_matching_changes_retrieval_order(self):
        sid=self.session();session=self.r.store.get_session(sid)
        with self.r.store.lock,self.r.store.db:
            a=self.r.engine.add_memory('安静','gist',session,'a','安静',1,.5);b=self.r.engine.add_memory('安静','gist',session,'b','安静',1,.5)
            base={'storage_strength':.5,'last_access':now(),'accesses':0,'sources':[],'salience':.5,'uncertainty':.5}
            self.r.store.setmeta('memory_traces',{a:{**base,'context':{'emotional_salience':0,'conflict':0,'consequence':0}},b:{**base,'context':{'emotional_salience':1,'conflict':1,'consequence':1}}})
        u={'semantic':{},'keywords':['安静'],'cognitive_appraisal':{'emotional_salience':1,'conflict':1,'consequence':1}}
        self.assertEqual(self.r.engine.retrieve('安静',session['scope'],understanding=u)[0]['id'],b)

class DeliveryTests(unittest.TestCase):
    def test_cmd_bootstrap_is_ascii_crlf_and_self_wraps(self):
        for name in ('Start_HuaiAn.cmd','start_windows.bat','Check_Environment.cmd','start_pmm_windows.bat'):
            data=(ROOT/name).read_bytes();data.decode('ascii');self.assertNotIn(b'\n',data.replace(b'\r\n',b''));self.assertIn(b'cmd.exe" /d /k',data);self.assertIn(b'chcp 65001',data);self.assertIn(b'launcher.py',data);self.assertIn(b'DisableDelayedExpansion',data)
    def test_launcher_captures_unicode_child_failure_and_exit_code(self):
        with tempfile.TemporaryDirectory(prefix='槐安 空格 ') as d:
            root=Path(d);child=root/'故障 子程序.py';child.write_text("import sys\nprint('中文故障线索')\nprint('stderr detail',file=sys.stderr)\nsys.exit(7)\n")
            log=launcher.StartupLog(root/'启动.log')
            try:
                with patch('sys.stdout',io.StringIO()):code=launcher.run_logged([sys.executable,child],log,cwd=root)
            finally:log.close()
            self.assertEqual(code,7);self.assertIn('中文故障线索',(root/'启动.log').read_text());self.assertIn('stderr detail',(root/'启动.log').read_text())
    def test_existing_broken_venv_reports_recovery_not_false_success(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);python=launcher.python_path(root);python.parent.mkdir(parents=True);python.write_text('')
            with patch('launcher.run_logged',return_value=2),patch('sys.stdout',io.StringIO()):code=launcher.bootstrap(argparse.Namespace(check=True,arguments=[]),root)
            self.assertEqual(code,2);self.assertIn('.venv',(root/'logs/startup.log').read_text())
    def test_source_export_includes_real_code_with_verifiable_lines_and_hash(self):
        result=build(ROOT);self.assertGreater(len(result['manifest']),50);lines=result['source'].splitlines()
        for row in result['manifest']:
            raw=(ROOT/row['path']).read_bytes();self.assertEqual(hashlib.sha256(raw).hexdigest(),row['sha256'])
            self.assertEqual(lines[row['source_start_line']-1:row['source_end_line']],raw.decode().splitlines())
        self.assertEqual(result['sha256'],hashlib.sha256(result['source'].encode()).hexdigest())
    def test_source_export_excludes_runtime_data_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as d,tempfile.TemporaryDirectory() as external:
            root=Path(d);(root/'persona').mkdir();(root/'web').mkdir();(root/'logs').mkdir();(root/'data').mkdir()
            for name in ('config.json','logs/error.txt','data/secret.py'): (root/name).write_text('ACTUAL_SECRET')
            (root/'run.py').write_text('print(1)');(Path(external)/'outside.py').write_text('ACTUAL_SECRET');(root/'persona/escape.py').symlink_to(Path(external)/'outside.py')
            result=build(root);self.assertNotIn('ACTUAL_SECRET',result['source']);self.assertEqual([r['path'] for r in result['manifest']],['run.py'])

class SupportTests(AdaptiveBase):
    def test_support_export_omits_secrets_and_raw_messages(self):
        self.receive('UNIQUE_PRIVATE_MESSAGE');self.bad=True;self.process();r=report(self.r);text=json.dumps(r)
        for secret in ('GENERAL_SECRET','PMM_SECRET','UNIQUE_PRIVATE_MESSAGE','inbound_token','api_key','source_ids'):self.assertNotIn(secret,text)
        self.assertIn('failures',r);self.assertEqual(r['failures'][0]['exception_type'],'ValueError');self.assertTrue(r['failures'][0]['frames'])

class InterfaceTests(unittest.TestCase):
    from test_api import APITests as _A
    setUp=_A.setUp;tearDown=_A.tearDown;request=_A.request
    def test_source_and_diagnostic_download_endpoints(self):
        import urllib.request
        support=self.request('/api/support');self.assertEqual(support['version'],VERSION)
        for route,filename in [('/api/source','HuaiAn_Dreamer_Source.md'),('/api/source-index','HuaiAn_Dreamer_Code_Index.md')]:
            with urllib.request.urlopen(urllib.request.Request(self.base+route,headers=self.headers)) as r:
                self.assertIn(filename,r.headers['Content-Disposition']);text=r.read().decode();self.assertIn('槐安梦客',text);self.assertIn('persona/cognition.py',text)
    def test_invalid_annotations_and_sent_retries_are_rejected(self):
        import urllib.error
        for route,data in [('/api/cognition/feedback',{'id':'missing','targets':{'turn_complete':1}}),('/api/qq/retry-appraisal',{'id':'sent'})]:
            with self.assertRaises(urllib.error.HTTPError) as error:self.request(route,data)
            self.assertEqual(error.exception.code,400)
        self.assertIn('recent',self.request('/api/cognition'))

class UIContractTests(unittest.TestCase):
    def test_flat_pages_and_live_js_bindings(self):
        result=subprocess.run(['node',str(ROOT/'tests/test_ui_v220.js')],capture_output=True,text=True,timeout=20,env={**os.environ,'TEST_PYTHON':sys.executable})
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
