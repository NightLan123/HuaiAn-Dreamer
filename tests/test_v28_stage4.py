import copy,json,unittest
import numpy as np
from persona.trait_dynamics import initial_checkpoint,TraitDynamics,torch_model
from persona.pmm_trainer import (fit,audit_dataset,split_dataset,validate_sample,masked_loss,
    publication_eligibility,fit_transition,validate_metadata)
from persona.pmm_coordinator import PMMCoordinator
from persona.registry import digest
from test_v28_stage2 import inputs,known
from test_v212 import Base

def dataset(owner='owner',adapter=False):
    rows=[];plan={}
    for fold,offset in [('train',100),('validation',1000),('test',10000)]:
        subjects=[owner] if adapter else [fold+'A',fold+'B']
        plan[fold]={'subjects':subjects,'start':offset,'end':offset+100}
        for subject in subjects:
            for i in range(3):
                x=inputs(owner);known(x,'H',0,.3+.1*i);x['q'][0]=.2;x['h_prev'][0]=.2
                rows.append({'schema':'pmm-supervision/2.8','subject_id':subject,'owner_id':owner,'scope':'study:consented',
                    'event_id':subject+str(offset+i),'timestamp':float(offset+i),'protocol_id':'controlled-fixture-v1',
                    'source_kind':'controlled_fixture','reviewed':True,'reviewer':'test-harness','engineering_fixture':True,
                    'permissions':{'parameter_training':True,'shared_core':True,'personal_adapter':True,'scopes':['study:consented']},
                    'evidence_refs':['synthetic-source-'+subject+str(i)],'task':'action_choice','weight':1.,
                    'inputs':x,'labels':{'action':'reply'}})
    return rows,plan

def import_fixture(co,owner,rows):
    imported=[]
    for index,r in enumerate(rows):
        row=copy.deepcopy(r)
        row['record']={'id':'measurement-'+str(index),'event_id':r['event_id'],'text':'Controlled action: reply.',
                       'speaker':'test-harness','scope':r['scope'],'source':'human','timestamp':r['timestamp'],
                       'measurement_subject_id':r['subject_id']}
        row['quote']='Controlled action: reply.';imported.append(row)
    return co.review_samples({'subject_id':owner,'expected_revision':0,'samples':imported})

class TrainingMath(unittest.TestCase):
    def test_actual_training_changes_weights_improves_loss_keeps_parent(self):
        ck=initial_checkpoint('owner');before=copy.deepcopy(ck);rows,plan=dataset()
        candidate,report,_=fit(ck,rows,plan,owner_id='owner',epochs=15,learning_rate=.1,structural_candidates=(0.,))
        self.assertEqual(before,ck);self.assertNotEqual(candidate['parameters'],ck['parameters'])
        self.assertLess(report['after']['train']['loss'],report['before']['train']['loss'])
        self.assertGreater(report['gradient_norms']['0.0'],0.)
        self.assertTrue(report['subject_held_out']);self.assertFalse(report['test_used_for_selection'])
        self.assertEqual(TraitDynamics(candidate,'owner').forward(rows[0]['inputs']),TraitDynamics(json.loads(json.dumps(candidate)),'owner').forward(rows[0]['inputs']))
    def test_adapter_gradients_change_only_own_adapter(self):
        ck=initial_checkpoint('owner');rows,plan=dataset(adapter=True)
        candidate,report,_=fit(ck,rows,plan,owner_id='owner',target='adapter',epochs=5,learning_rate=.1,structural_candidates=(0.,))
        self.assertEqual(ck['parameters'],candidate['parameters']);self.assertNotEqual(ck['adapter'],candidate['adapter'])
        self.assertFalse(report['subject_held_out']);self.assertIn('not_publishable',report['personal_adapter_limitation'])
    def test_resume_SGD_matches_continuous(self):
        ck=initial_checkpoint('owner');rows,plan=dataset()
        a,_,_=fit(ck,rows,plan,owner_id='owner',epochs=2,structural_candidates=(0.,))
        b,_,_=fit(a,rows,plan,owner_id='owner',epochs=2,structural_candidates=(0.,))
        c,_,_=fit(ck,rows,plan,owner_id='owner',epochs=4,structural_candidates=(0.,))
        for key in c['parameters']:np.testing.assert_allclose(b['parameters'][key],c['parameters'][key],atol=1e-12)
    def test_C_mask_normalization_not_number_of_fields(self):
        import torch
        row=dataset()[0][0];row['task']='state_reaction';row['scale_id']='engineering_latent';row['labels']={'state':[.3]+[None]*24}
        net=torch_model(initial_checkpoint('owner'),'owner');pred=net(row['inputs'])['state'][0]
        self.assertAlmostEqual(float(masked_loss(net,[row]).detach()),float(((pred-.3)**2).detach()),places=12)
        b=copy.deepcopy(row);b['weight']=3.
        self.assertAlmostEqual(float(masked_loss(net,[row,b]).detach()),float(((pred-.3)**2).detach()),places=12)
    def test_no_generated_promoted_or_unreviewed_labels(self):
        base=dataset()[0][0]
        for source in ('generated','model_self_rating','trait_promotion','unverified_qwen'):
            row={**base,'source_kind':source}
            with self.assertRaises(ValueError):validate_sample(row)
        with self.assertRaises(ValueError):validate_sample({**base,'task':'long_term_trait'})
        with self.assertRaises(ValueError):validate_sample({**base,'reviewed':False})
    def test_dedupe_and_group_time_leakage(self):
        rows,plan=dataset();out,audit=audit_dataset(rows+rows,'owner')
        self.assertEqual(len(out),len(rows));self.assertEqual(audit['independent_events'],len(rows))
        bad=copy.deepcopy(rows[0]);bad['labels']['action']='decline'
        with self.assertRaises(ValueError):audit_dataset(rows+[bad],'owner')
        p=copy.deepcopy(plan);p['validation']['subjects'].append(p['train']['subjects'][0])
        with self.assertRaises(ValueError):split_dataset(rows,p,target='core',owner_id='owner')
        p=copy.deepcopy(plan);p['validation']['start']=p['train']['end']
        with self.assertRaises(ValueError):split_dataset(rows,p,target='core',owner_id='owner')
    def test_fixture_cannot_publish_even_after_good_training(self):
        rows,plan=dataset();candidate,report,rows=fit(initial_checkpoint('owner'),rows,plan,owner_id='owner',epochs=3,structural_candidates=(0.,))
        ready,reason=publication_eligibility(candidate,report,rows,'owner',lambda row:None)
        self.assertFalse(ready);self.assertIn('synthetic',reason)
    def test_real_state_requires_calibrated_scale(self):
        rows,plan=dataset()
        for r in rows:r.update(task='state_reaction',scale_id='engineering_latent',source_kind='independent_observer',engineering_fixture=False,labels={'state':[.2]+[None]*24})
        with self.assertRaises(ValueError):fit(initial_checkpoint('owner'),rows,plan,owner_id='owner',epochs=1)
    def test_longitudinal_G_trained_but_fixture_stays_disabled(self):
        from persona.pmm_contracts import BLOCK_IDS
        rows,plan=dataset();pairs=[]
        for r in rows:
            pairs.append({'subject_id':r['subject_id'],'before_event_id':r['event_id']+'b','after_event_id':r['event_id']+'a',
                'before_time':r['timestamp'],'after_time':r['timestamp']+10,'before':[.3],'after':[.4],
                'zeta':[.2],'source_kind':'controlled_fixture','reviewed':True,'evidence_refs':r['evidence_refs'],'engineering_fixture':True})
        model=fit_transition(pairs,[BLOCK_IDS['H'][0]],plan,ridge=.001)
        self.assertGreater(model['G'][0][0],.4);self.assertLess(model['errors']['test']['mse'],model['errors']['test']['persistence_mse'])
        self.assertFalse(model['validated']);self.assertIsNone(model['validation_ref'])

class Persistence(Base):
    def test_real_database_candidate_idempotence_freeze_revoke_and_package(self):
        from persona.packages import export_continuity,validate_pack
        owner=self.r.engine.profile()['id'];co=PMMCoordinator(self.r.engine);rows,plan=dataset(owner)
        old=digest(self.r.engine.model.export());import_fixture(co,owner,rows)
        body={'op':'train','subject_id':owner,'expected_revision':0,'job_id':'controlled-training','split_plan':plan,
              'epochs':3,'structural_candidates':[0.]}
        result=co.model_action(body);key=result['candidate']
        self.assertIsNone(self.r.store.meta('pmm28_models')['published']);self.assertEqual(old,digest(self.r.engine.model.export()))
        self.assertTrue(co.model_action(body)['duplicate'])
        co.model_action({'op':'freeze','subject_id':owner,'expected_revision':1,'version':key})
        with self.assertRaises(ValueError):co.model_action({'op':'publish','subject_id':owner,'expected_revision':2,'version':key})
        pack=export_continuity(self.r.engine);validated=validate_pack(pack)
        self.assertEqual(validated[0]['pmm28_models']['versions'][key],self.r.store.meta('pmm28_models')['versions'][key])
        co.model_action({'op':'revoke','subject_id':owner,'expected_revision':2,'version':key})
        self.assertIn(key,self.r.store.meta('pmm28_models')['revoked'])
    def test_withdrawn_source_blocks_new_training_and_wrong_subject(self):
        owner=self.r.engine.profile()['id'];co=PMMCoordinator(self.r.engine);rows,plan=dataset(owner);import_fixture(co,owner,rows)
        data=self.r.store.meta('pmm28_samples');key=next(iter(data['rows']))
        co.review_samples({'op':'withdraw','subject_id':owner,'expected_revision':1,'key':key,'reason':'controlled withdrawal test'})
        with self.assertRaises(ValueError):co.model_action({'op':'train','subject_id':owner,'expected_revision':0,'job_id':'x','split_plan':plan,'sample_keys':[key],'epochs':1})
        valid=co.model_action({'op':'train','subject_id':owner,'expected_revision':0,'job_id':'valid-remainder','split_plan':plan,'epochs':1,'structural_candidates':[0.]})
        self.assertNotIn(key,self.r.store.meta('pmm28_models')['versions'][valid['candidate']]['training']['sample_keys'])
        with self.assertRaises(ValueError):co.review_samples({'subject_id':'other','expected_revision':2,'samples':rows})
    def test_stale_catalog_CAS_and_identity_import(self):
        owner=self.r.engine.profile()['id'];co=PMMCoordinator(self.r.engine)
        with self.assertRaises(ValueError):co.model_action({'op':'train','subject_id':owner,'expected_revision':10,'job_id':'x'})
        from persona.pmm_trainer import empty_catalog
        cat=empty_catalog('other')
        with self.assertRaises(ValueError):validate_metadata({'identity':{'id':owner},'pmm28_models':cat})

if __name__=='__main__':unittest.main()
