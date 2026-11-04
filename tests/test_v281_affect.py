"""Independent math, lifecycle and training checks for stage I (no cloud LLM)."""
import copy,json,math,tempfile,unittest
from pathlib import Path
import numpy as np
from persona.affect_dynamics_v2 import *
from persona.affect_response import *
from persona import affect_runtime as ar
from persona.affect_training import train,validate_dataset,predict_mean,torch_prediction,release_gate,calibrate
from persona.psychology import empty_profile
from persona.registry import ensure_profile
from persona.storage import Store

def profile(owner='a'):
    return ensure_profile(empty_profile(owner,'测试人格'))

def event(i='e',scope='private:test',person='person',session='session'):
    return {'id':i,'text':'我今天完成了计划。','scope':scope,'person':person,'session_id':session}

def packet(ev,goal=.8,reappraisal=None):
    return appraisal_packet({'affect.appraisal.goal_conduciveness':goal,'affect.appraisal.goal_relevance':.8},ev,[ev['id']],ev['text'],reappraisal)

def dataset(owner='a',count=36):
    model=initial_model(owner);truth=copy.deepcopy(model);truth['parameters']['mu_b'][0]=.5;truth=seal(truth);rows=[];rng=np.random.default_rng(12)
    for i in range(count):
        r={'subject_id':owner,'scope':'study','event_id':str(i),'at':100000+i*2000,'split':'train' if i<count//2 else 'validation' if i<3*count//4 else 'test',
           'delta_seconds':float(1800+i%5*200),'blocks':construct_blocks(profile(owner)),
           'appraisal':{},'fast_before':rng.normal(0,.2,5).tolist(),'mood_before':rng.normal(0,.2,3).tolist(),
           'fast_after':[None]*5,'mood_after':[None]*3,'labels':[None]*24,'measurement_variance':.001,
           'source':{'kind':'synthetic','evidence_id':'synthetic:'+str(i)}}
        mean,var,_=predict_mean(truth,r)
        # Exact known means are intentional engineering supervision; no claim
        # that this deterministic fixture calibrates the stochastic variance.
        r['fast_after']=mean[:5].tolist();r['mood_after']=mean[5:].tolist();rows.append(r)
    return {'format':'affect-supervision/2.8.1','engineering_only':True,'rows':rows,'known_parameters':truth['parameters']}

class Math(unittest.TestCase):
    def test_scalar_analytic_and_zero(self):
        m,v=ou_moments(2.,.3,.2,.4,3.)
        self.assertAlmostEqual(float(m),.3+math.exp(-.6)*1.7,14)
        self.assertAlmostEqual(float(v),.16/.4*(1-math.exp(-1.2)),14)
        a,b=ou_moments([2.],[.3],[.2],[.4],0);self.assertEqual(a.tolist(),[2.]);self.assertEqual(b.tolist(),[0.])
    def test_small_kappa_limit_and_large_time(self):
        _,v=ou_moments(1,0,[0,1e-20],.3,100)
        np.testing.assert_allclose(v,[9,9],rtol=1e-14)
        m,v=ou_moments(9,.2,.3,.4,1e10);self.assertEqual(float(m),.2);self.assertAlmostEqual(float(v),.16/.6)
    def test_block_moments_against_independent_quadrature(self):
        for ke,km,dt in [(.2,.1,3),(.2,.2,3),(.2,.200000001,3),(.0001,.000001,10000)]:
            mean,cov=coupled_moments(.7,-.3,.2,.1,ke,km,.3,.1,.02,dt)
            nodes,weights=np.polynomial.legendre.leggauss(120);s=(nodes+1)*dt/2
            f=np.exp(-ke*s);g=np.exp(-km*s)
            h=.02*(f-g)/(km-ke) if abs(km-ke)>1e-8 else .02*s*g
            expected=np.array([[np.sum(weights*.09*f*f),np.sum(weights*.09*f*h)],[np.sum(weights*.09*f*h),np.sum(weights*(.09*h*h+.01*g*g))]])*dt/2
            np.testing.assert_allclose(cov,expected,rtol=2e-8,atol=1e-11)
            self.assertGreaterEqual(np.linalg.eigvalsh(cov).min(),0)
    def test_block_semigroup(self):
        args=(.8,-.4,.1,.2,.03,.002,.02,.005,.001)
        total,q=coupled_moments(*args,800)
        mid,q1=coupled_moments(*args,300);end,q2=coupled_moments(*mid,*args[2:],500)
        f=np.array([[math.exp(-.03*500),0],[.001*(math.exp(-.03*500)-math.exp(-.002*500))/(.002-.03),math.exp(-.002*500)]])
        np.testing.assert_allclose(total,end,atol=1e-12);np.testing.assert_allclose(q,f@q1@f.T+q2,rtol=1e-12)
    def test_links_roundtrip_boundaries_and_missing(self):
        x=[-.9,.2,.7,.8,.1];values=dict(zip(AXES,x));latent,mask,precision=inverse(values)
        np.testing.assert_allclose(list(link(latent).values()),x,atol=1e-14)
        latent,mask,precision=inverse({'valence':1,'arousal':0});self.assertEqual(mask,[1,1,0,0,0]);self.assertEqual(precision['boundary_approximations'],['valence','arousal'])
        self.assertTrue(np.isfinite(latent).all());self.assertIsNone(precision['original'].get('stress'))
    def test_timezones_and_invalid_time(self):
        self.assertEqual(seconds('2026-11-03T08:00:00+08:00'),seconds('2026-11-03T00:00:00Z'))
        for bad in ('2026-11-03T00:00:00',float('nan'),-1):
            with self.assertRaises(ValueError):seconds(bad)
    def test_traits_are_trainable_not_fixed_laws(self):
        ck=initial_model('a');b=construct_blocks(profile());first=parameters(ck,b)
        b['H']['values'][0]=.8;b['H']['mask'][0]=1;b['H']['uncertainty'][0]=.1
        self.assertEqual(first,parameters(ck,b))
        ck['parameters']['mu_W'][0][0]=.2;ck['parameters']['kappa_W'][0][0]=.3;ck=seal(ck)
        self.assertNotEqual(parameters(ck,b)['mu'][0],first['mu'][0]);self.assertGreater(parameters(ck,b)['kappa'][0],0)
    def test_default_turn_term_zero_and_unvalidated_rejected(self):
        p=parameters(initial_model('a'),construct_blocks(profile()));self.assertEqual(p['kappa_n'],[0]*8)
        a=propagate([0]*5,[0]*3,p,0,np.random.default_rng(2),1);b=propagate([0]*5,[0]*3,p,0,np.random.default_rng(2),500)
        np.testing.assert_array_equal(a[0],b[0]);p['kappa_n'][0]=.1
        with self.assertRaises(ValueError):propagate([0]*5,[0]*3,p,0,np.random.default_rng(2),1)

class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name);self.owner=self.store.meta('identity')['id'];self.profile=profile(self.owner)
        from persona import affect
        affect.migrate(self.store);self.base=ar.migrate(self.store);self.model=ar.model_for(self.store)
    def tearDown(self):self.store.close();self.tmp.cleanup()
    def draft(self,base=None,ev=None,at=10000,strategy='none',model=None,proposal=None):
        ev=ev or event();return ar.draft(base or self.base,model or self.model,self.profile,ev,at,proposal or packet(ev),{},strategy=strategy)
    def test_replay_idempotency_and_rng(self):
        a,r=self.draft();b,s=self.draft();self.assertEqual(a,b);self.assertEqual(r,s)
        a2,r2=self.draft(a,at=20000);self.assertEqual(a2,a);self.assertFalse(r2['updated']);self.assertEqual(r['rng_after'],r2['rng_after'])
        other=event();other['text']='不同原文'
        with self.assertRaises(ValueError):self.draft(a,other)
    def test_restart_atomicity_and_compare_swap(self):
        a,r=self.draft();ar.commit(self.store,0,a);self.store.close();self.store=Store(self.tmp.name)
        self.assertEqual(ar.migrate(self.store),a)
        with self.assertRaises(ValueError):ar.commit(self.store,0,a)
        before=self.store.meta(ar.KEY)
        with self.assertRaises(RuntimeError):
            with self.store.lock,self.store.db:
                self.store.setmeta(ar.KEY,self.base);raise RuntimeError('controlled rollback')
        self.assertEqual(self.store.meta(ar.KEY),before)
    def test_scope_person_session_isolation(self):
        a,_=self.draft();key=next(iter(a['streams']));original=copy.deepcopy(a['streams'][key])
        for ev in (event('e2',scope='group:test'),event('e2',person='other'),event('e2',session='another')):a,_=self.draft(a,ev)
        self.assertEqual(len(a['streams']),4);self.assertEqual(a['streams'][key],original)
        with self.assertRaises(ValueError):ar.validate(a,'other-subject')
    def test_clock_rollback_long_offline_and_no_trait_write(self):
        prior=copy.deepcopy(self.profile);a,r=self.draft();b,s=self.draft(a,event('e2'),9999)
        self.assertEqual(s['delta_seconds'],0);self.assertEqual(s['clock_status'],'rollback_no_time_reversal')
        _,long=self.draft(b,event('e3'),1e10);self.assertEqual(long['clock_status'],'long_offline_exact');self.assertTrue(np.isfinite(long['fast_state_latent']).all());self.assertEqual(self.profile,prior)
    def test_no_evidence_means_no_jump_and_unknown_labels(self):
        ev=event();empty=appraisal_packet({},ev)
        _,r=self.draft(proposal=empty);self.assertFalse(r['jump_applied']);self.assertEqual(r['jump'],[0]*5)
        self.assertTrue(all(v is None for v in r['emotion_labels'].values()));self.assertEqual(len(r['emotion_labels']),24)
        self.assertAlmostEqual(sum(r['label_activations'].values()),12)
    def test_suppression_does_not_change_internal_state(self):
        a,r=self.draft(strategy='none');b,s=self.draft(strategy='suppression')
        self.assertEqual(r['fast_state_latent'],s['fast_state_latent']);self.assertEqual(r['slow_mood_latent'],s['slow_mood_latent'])
        self.assertLess(s['expression_plan']['intensity'],r['expression_plan']['intensity'])
    def test_reappraisal_recomputes_one_jump_facts_unchanged(self):
        ev=event();q=packet(ev,.1);candidate={'event_facts_sha256':digest(q['event_facts']),'checks':{'affect.appraisal.goal_conduciveness':.9}}
        q['reappraisal_candidate']=candidate;_,r=self.draft(proposal=q,strategy='reappraisal')
        self.assertTrue(r['regulation']['reappraisal_applied']);np.testing.assert_allclose(np.asarray(r['pre_jump_fast'])+r['jump'],r['fast_state_latent'])
        self.assertEqual(r['appraisal']['event_facts'],q['event_facts']);self.assertGreater(r['reappraisal_jump_difference'][0],0)
        q['reappraisal_candidate']['event_facts_sha256']='false'
        with self.assertRaises(ValueError):self.draft(proposal=q,strategy='reappraisal')
    def test_migration_and_version_switch_preserve_state(self):
        legacy=self.store.meta('pmm_affect');self.assertEqual(digest(legacy),self.base['migration']['old_sha256'])
        self.assertEqual(ar.migrate(self.store),self.base);a,r=self.draft();new=copy.deepcopy(self.model);new['parameters']['mu_b'][0]=.1;new=seal(new)
        _,s=self.draft(a,event('e2'),10000,model=new);self.assertEqual(s['before_fast'],r['fast_state_latent']);self.assertTrue(s['model_switch']['state_preserved'])
        self.assertEqual(self.store.meta('pmm_affect'),legacy)
    def test_legacy_view_valid_and_full_snapshot_restorable(self):
        a,r=self.draft();view,trace=ar.legacy_view(self.store.meta('pmm_affect'),r,self.profile)
        from persona.affect import validate
        validate(view,self.owner);ar.commit(self.store,0,a)
        snap=self.store.snapshot();self.store.restore(snap);self.assertEqual(self.store.meta(ar.KEY),a)
        bad=copy.deepcopy(snap)
        row=next(x for x in bad['tables']['meta'] if x['key']==ar.KEY);v=json.loads(row['value']);next(iter(v['streams'].values()))['fast']=[None];row['value']=json.dumps(v)
        with self.assertRaises(ValueError):self.store.restore(bad)
        self.assertEqual(self.store.meta(ar.KEY),a)

class Training(unittest.TestCase):
    def test_nearly_equal_rates_numpy_torch(self):
        import torch
        m=initial_model('a');m['parameters']['kappa_b'][5:]=m['parameters']['kappa_b'][:3];m=seal(m)
        r=dataset(count=12)['rows'][0];r['delta_seconds']=.1
        p={k:torch.tensor(v,dtype=torch.float64) for k,v in m['parameters'].items()};a,b,_,_=torch_prediction(p,r,torch);x,y,_=predict_mean(m,r)
        np.testing.assert_allclose(a.numpy(),x,atol=1e-13);np.testing.assert_allclose(b.numpy(),y,atol=1e-13)
    def test_numpy_torch_means_variances_and_gradients(self):
        import torch
        m=initial_model('a');r=dataset(count=12)['rows'][0];p={k:torch.tensor(v,dtype=torch.float64,requires_grad=True) for k,v in m['parameters'].items()}
        means,var,labels,reg=torch_prediction(p,r,torch);n,v,l=predict_mean(m,r)
        np.testing.assert_allclose(means.detach().numpy(),n,rtol=1e-12,atol=1e-12);np.testing.assert_allclose(var.detach().numpy(),v,rtol=1e-12)
        loss=means[0]+var[0]+labels[0]+reg[0];loss.backward()
        for key in ('mu_b','kappa_b','sigma_b','label_b','reg_b'):
            analytic=p[key].grad[0].item();eps=1e-6;base=p[key].detach()[0].item()
            def value(delta):
                with torch.no_grad():p[key][0]=base+delta
                a,b,c,d=torch_prediction(p,r,torch);return (a[0]+b[0]+c[0]+d[0]).item()
            numeric=(value(eps)-value(-eps))/(2*eps)
            self.assertAlmostEqual(analytic,numeric,places=7)
            with torch.no_grad():p[key][0]=base
    def test_real_training_resume_and_synthetic_release_refusal(self):
        d=dataset(count=12);m=initial_model('a');a,report=train(m,d,4,.01,'parameters');b,_=train(m,d,2,.01,'parameters');b=json.loads(json.dumps(b));b,_=train(b,d,2,.01,'parameters')
        self.assertEqual(a['parameters'],b['parameters']);self.assertNotEqual(a['parameters'],m['parameters']);self.assertEqual(a['steps'],4)
        self.assertLess(report['after']['train']['state_mse'],report['before']['train']['state_mse'])
        cat={'versions':{a['sha256']:a},'reports':{a['sha256']:report},'datasets':{digest(d):d}}
        self.assertFalse(release_gate(cat,a['sha256'])[0])
        with self.assertRaises(ValueError):calibrate(a,d,report)
    def test_invalid_splits_duplicate_and_self_report_rejected(self):
        d=dataset(count=12);bad=copy.deepcopy(d);bad['rows'][4]['event_id']=bad['rows'][0]['event_id']
        with self.assertRaises(ValueError):validate_dataset(bad)
        bad=copy.deepcopy(d);bad['rows'][-1]['at']=1
        with self.assertRaises(ValueError):validate_dataset(bad)
        bad=copy.deepcopy(d);bad['engineering_only']=False
        with self.assertRaises(ValueError):validate_dataset(bad)
    def test_multilabel_and_strategy_heads_really_train(self):
        d=dataset(count=12)
        for r in d['rows']:r['labels'][0]=1;r['regulation_label']=2
        m=initial_model('a');labels,r=train(m,d,3,.01,'labels');reg,_=train(m,d,3,.01,'regulation')
        self.assertGreater(labels['parameters']['label_b'][0],0);self.assertGreater(reg['parameters']['reg_b'][2],0)
        self.assertEqual(labels['parameters']['mu_W'],m['parameters']['mu_W']);self.assertTrue(all(x is False for x in labels['calibration']['labels']))

class PersistedTraining(unittest.TestCase):
    def test_catalog_training_freeze_withdrawal_and_restart(self):
        from persona.server import Runtime
        from persona.affect_learning import AffectLearning
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            app=Runtime(temp,root)
            try:
                service=AffectLearning(app.engine);owner=service.status()['subject_id'];data=dataset(owner,count=12)
                def act(op,**kw):return service.action({'op':op,'subject_id':owner,'expected_revision':service.status()['revision'],**kw})
                imported=act('import',dataset=data)['created'];result=act('train',dataset_id=imported,component='parameters',epochs=2,lr=.01);version=result['created']
                self.assertIsNone(result['active']);self.assertTrue(version);act('freeze',version=version)
                with self.assertRaises(ValueError):act('train',version=version,dataset_id=imported,epochs=1)
                act('unfreeze',version=version)
                with self.assertRaises(ValueError):act('publish',version=version)
                before=app.store.meta(ar.MODELS);app.close();app=Runtime(temp,root);service=AffectLearning(app.engine)
                self.assertEqual(before,app.store.meta(ar.MODELS));act('withdraw_dataset',dataset_id=imported)
                with self.assertRaises(ValueError):act('train',dataset_id=imported,epochs=1)
                from persona.packages import export_continuity,validate_pack
                pack=export_continuity(app.engine);meta,_,_=validate_pack(pack);self.assertEqual(meta[ar.MODELS],app.store.meta(ar.MODELS))
            finally:app.close()
    def test_actual_training_cli_and_lock(self):
        import subprocess,sys
        from persona.server import Runtime
        from persona.lock import InstanceLock
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)/'data';app=Runtime(directory,root);owner=app.store.meta('identity')['id'];app.close()
            data=Path(temp)/'data.json';data.write_text(json.dumps(dataset(owner,count=12)))
            command=[sys.executable,str(root/'scripts/train_affect_v281.py'),'--data-dir',str(directory),'--dataset',str(data),'--component','parameters','--epochs','1','--output',str(Path(temp)/'output')]
            with InstanceLock(directory):
                blocked=subprocess.run(command,capture_output=True,text=True,timeout=30);self.assertNotEqual(blocked.returncode,0)
            completed=subprocess.run(command,capture_output=True,text=True,timeout=30);self.assertEqual(completed.returncode,0,completed.stderr)
            self.assertEqual(json.loads((Path(temp)/'output/candidate.json').read_text())['steps'],1)
            self.assertFalse(json.loads(completed.stdout)['published'])

if __name__=='__main__':unittest.main()
