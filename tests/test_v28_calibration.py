"""Partial-scale network binding. Injected protocols test algebra, not validity."""
import copy,unittest
import numpy as np
from persona.trait_dynamics import initial_checkpoint,bind_measurement_scale,TraitDynamics,torch_model,checked_inputs,latent_H
from persona.pmm_contracts import BLOCK_IDS
from persona.pmm_trainer import fit
from test_v28_stage2 import inputs,known
from test_v28_stage4 import dataset
from test_v212 import Base
from persona.pmm_coordinator import PMMCoordinator

def protocol():
    return {'id':'injected-unit-protocol','scale_id':'unit-scale','construct_ids':[BLOCK_IDS['H'][0]],
            'slope':[2.],'intercept':[1.],'measurement_covariance':[[.04]],'validated':True,'engineering_only':False}

class PartialScale(unittest.TestCase):
    def test_independent_labels_also_require_explicit_parameter_permission(self):
        from persona.trait_estimator import fit_measurement_scale
        from persona.pmm_trainer import fit_transition
        from test_v28_longitudinal import scale_data
        rows,plan=scale_data()
        for r in rows:r.update(source_kind='independent_observer',engineering_fixture=False,scope='private:study')
        with self.assertRaisesRegex(ValueError,'No permission'):fit_measurement_scale(rows,[BLOCK_IDS['H'][0]],plan,'scale')
        with self.assertRaisesRegex(ValueError,'No permission'):fit_transition(rows,[BLOCK_IDS['H'][0]],plan)
    def test_partial_scale_identity_and_numpy_torch_match(self):
        cp=bind_measurement_scale(initial_checkpoint('owner'),protocol());x=inputs();known(x,'H',0,.3);known(x,'H',1,.9)
        z=latent_H(cp,checked_inputs(x));self.assertEqual(z[0],1.6);self.assertEqual(z[1],0.)
        a=TraitDynamics(cp,'owner').forward(x);b=torch_model(cp,'owner')(x)
        np.testing.assert_allclose(a['state_prediction'],b['state'].detach().numpy(),atol=1e-12)
        self.assertEqual(a['calibrated_state_mask'],[1]+[0]*24)
        self.assertEqual(a['measurement_uncertainty']['covariance'],[[.04]])
    def test_state_training_uses_only_calibrated_facets(self):
        cp=bind_measurement_scale(initial_checkpoint('owner'),protocol());rows,plan=dataset()
        for r in rows:r.update(task='state_reaction',scale_id='unit-scale',labels={'state':[.4]+[None]*24})
        candidate,report,_=fit(cp,rows,plan,owner_id='owner',epochs=3,structural_candidates=(0.,))
        self.assertNotEqual(candidate['parameters'],cp['parameters']);self.assertTrue(report['engineering_only'])
        rows[0]['labels']['state'][1]=.3
        with self.assertRaisesRegex(ValueError,'without independent scale'):fit(cp,rows,plan,owner_id='owner',epochs=1)
    def test_engineering_or_unvalidated_scale_cannot_be_bound(self):
        for p in ({**protocol(),'engineering_only':True},{**protocol(),'validated':False}):
            with self.assertRaises(ValueError):bind_measurement_scale(initial_checkpoint('owner'),p)
    def test_value_circle_is_soft_trainable_structure_not_hard_values(self):
        from persona.trait_dynamics import seal
        from persona.pmm_trainer import structural_loss
        cp=initial_checkpoint('owner')
        for k,v in cp['parameters'].items():cp['parameters'][k]=np.zeros_like(v).tolist()
        cp['parameters']['V_W_l']=np.eye(16,4).tolist()
        cp['parameters']['V_W_r']=[[1.]*19]+[[0.]*19 for _ in range(3)]
        smooth=torch_model(seal(cp),'owner');rough=copy.deepcopy(cp)
        rough['parameters']['V_W_r'][0]=[(-1.)**i for i in range(19)]
        rough=torch_model(seal(rough),'owner')
        self.assertGreater(float(structural_loss(rough).detach()),float(structural_loss(smooth).detach()))
        structural_loss(rough).backward();self.assertGreater(float(rough.core['V_W_r'].grad.abs().sum()),0.)

class BindingGate(Base):
    def test_arbitrary_validated_flag_cannot_create_scale_candidate(self):
        owner=self.r.engine.profile()['id'];co=PMMCoordinator(self.r.engine)
        from persona.pmm_longitudinal import empty
        state=empty(owner);state['protocols'][protocol()['id']]={'model':protocol(),'rows':[]}
        with self.r.store.lock,self.r.store.db:self.r.store.setmeta('pmm28_estimator',state)
        with self.assertRaises(ValueError):co.model_action({'op':'bind_scale','subject_id':owner,'expected_revision':0,'protocol_id':protocol()['id']})
        self.assertIsNone(self.r.store.meta('pmm28_models'))

if __name__=='__main__':unittest.main()
