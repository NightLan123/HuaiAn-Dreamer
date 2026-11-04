import copy, unittest
import numpy as np
from persona.trait_estimator import (predict,linear_gaussian,ordinal_logit,
    adjusted_state_summary,LongTermEstimator,covariance)
from persona.pmm_contracts import TurnContext, BLOCK_IDS

HID=BLOCK_IDS['H'][0]
def ctx():return TurnContext('a','private:a','proposal',200000.,0,turn_id='t',person_id='other')
def protocol():return {'id':'synthetic-protocol','scale_id':'controlled-latent','validated':True,'independent_context_calibration':True,'construct_ids':[HID],'engineering_fixture':True}
def states():
    return [{'event_id':'s'+str(i),'subject_id':'a','scope':'private:a','timestamp':float(10+i*86400),
             'kind':'independent_state_measurement','reviewed':True,'evidence_refs':['source'+str(i)],
             'protocol_id':'synthetic-protocol','latent_observed':[.6],'context_expected':[.4],
             'measurement_covariance':[[.04]],'context_covariance':[[.01]],'engineering_fixture':True} for i in range(2)]

class EstimateMath(unittest.TestCase):
    def test_manual_D_and_disabled_G(self):
        d=predict([.4],[[.1]],[.2],[[.04]],G=[[.5]],Q=[[.01]],g_validated=True)
        self.assertAlmostEqual(d['mu'][0],.5);self.assertAlmostEqual(d['P'][0][0],.12)
        off=predict([.4],[[.1]],[100.],[[999.]],G=[[.5]],g_validated=False)
        self.assertEqual(off['mu'],[.4]);self.assertEqual(off['P'],[[.1]]);self.assertFalse(off['G_enabled'])
    def test_manual_E_Joseph(self):
        x=linear_gaussian([.4],[[.2]],[.8],[[1.]],[[.1]])
        self.assertAlmostEqual(x['gain'][0][0],2/3);self.assertAlmostEqual(x['mu'][0],2/3)
        self.assertAlmostEqual(x['P'][0][0],1/15);self.assertEqual(x['jitter_added'],0.)
    def test_precision_and_missing(self):
        a=linear_gaussian([.4],[[.2]],[.8],[[1.]],[[.01]])
        b=linear_gaussian([.4],[[.2]],[.8],[[1.]],[[1.]])
        self.assertLess(a['P'][0][0],b['P'][0][0]);self.assertGreater(a['mu'][0],b['mu'][0])
        x=linear_gaussian([.4,.5],np.eye(2),[.8,None],np.eye(2),np.eye(2)*.1)
        self.assertEqual(x['mu'][1],.5);self.assertEqual(x['observed'],[0])
        self.assertFalse(linear_gaussian([.4],[[.2]],[None],[[1.]],[[.1]])['updated'])
    def test_invalid_covariance_and_conditioning(self):
        for P in ([[1,2],[2,1]],[[1,1],[0,1]],[[1,0],[0,float('nan')]]):
            with self.assertRaises(ValueError):covariance(P,2,'P')
        with self.assertRaises(ValueError):linear_gaussian([0.,0.],[[0.,0.],[0.,0.]],[0.,0.],np.eye(2),[[1.,0.],[0.,1e-20]])
    def test_correlated_error_cross_terms(self):
        x=predict([0.],[[1.]],[0.],[[1.]],G=[[.5]],g_validated=True,cross_cov=[[.2]],independent_errors=False)
        self.assertAlmostEqual(x['P'][0][0],1.45)
        with self.assertRaises(ValueError):predict([0.],[[1.]],[0.],[[1.]],independent_errors=False)
        with self.assertRaises(ValueError):predict([0.],[[1.]],[0.],[[1.]],cross_cov=[[2.]])
    def test_ordinal_is_probability_update_and_reports_approximation(self):
        a=ordinal_logit([0.],[[1.]],0,[1.],[-.5,.5]);b=ordinal_logit([0.],[[1.]],2,[1.],[-.5,.5])
        self.assertLess(a['mu'][0],0.);self.assertGreater(b['mu'][0],0.)
        self.assertAlmostEqual(a['mu'][0],-b['mu'][0],places=10)
        self.assertLess(b['P'][0][0],1.);self.assertIn('ADF',b['approximation'])
        c=ordinal_logit([0.],[[1.]],2,[1.],[-.5,.5],points=96)
        self.assertAlmostEqual(c['mu'][0],b['mu'][0],places=6)
    def test_independent_time_states_no_prediction_subtraction(self):
        s=states();r=adjusted_state_summary(s,subject_id='a',scope='private:a',construct_ids=[HID],protocol=protocol())
        self.assertTrue(r['ready']);self.assertAlmostEqual(r['zeta'][0],.2);self.assertAlmostEqual(r['Omega'][0][0],.025)
        duplicate=adjusted_state_summary(s+s,subject_id='a',scope='private:a',construct_ids=[HID],protocol=protocol())
        self.assertEqual(r['zeta'],duplicate['zeta']);self.assertEqual(r['Omega'],duplicate['Omega']);self.assertEqual(len(duplicate['rejected']),2)
        s[1]['kind']='neural_prediction'
        self.assertFalse(adjusted_state_summary(s,subject_id='a',scope='private:a',construct_ids=[HID],protocol=protocol())['ready'])
    def test_time_withdrawal_subject_protocol_guards(self):
        for update in ({'withdrawn':True},{'timestamp':11.},{'protocol_id':'other'}):
            s=states();s[1].update(update)
            self.assertFalse(adjusted_state_summary(s,subject_id='a',scope='private:a',construct_ids=[HID],protocol=protocol())['ready'])
        s=states();s[0]['subject_id']='b'
        with self.assertRaises(ValueError):adjusted_state_summary(s,subject_id='a',scope='private:a',construct_ids=[HID],protocol=protocol())
    def test_candidate_only_and_no_data(self):
        estimator=LongTermEstimator();c=ctx()
        self.assertEqual(estimator.estimate(c)['status'],'not_ready')
        prior={'mu':[.4],'P':[[.2]],'construct_ids':[HID],'scale_id':'controlled-latent'}
        y={'subject_id':'a','scope':'private:a','scale_id':'controlled-latent','event_id':'measure',
           'reviewed':True,'source_kind':'independent_questionnaire','evidence_refs':['actual-synthetic-measurement'],
           'model':'linear_gaussian','y':[.8],'H':[[1.]],'R':[[.1]],'engineering_fixture':True}
        out=estimator.estimate(c,prior=prior,samples=states(),measurement=y,protocol=protocol(),construct_ids=[HID])
        self.assertTrue(out['payload']['candidate_only']);self.assertFalse(out['payload']['committed'])
        self.assertFalse(out['payload']['prediction']['G_enabled']);self.assertAlmostEqual(out['payload']['posterior']['mu'][0],2/3)
        for source in ('generated','unreviewed_qwen','trait_promotion'):
            y['source_kind']=source
            with self.assertRaises(ValueError):estimator.estimate(c,prior=prior,measurement=y,protocol=protocol(),construct_ids=[HID])
    def test_other_constructs_need_their_own_estimator(self):
        out=LongTermEstimator().estimate(ctx(),construct_ids=[BLOCK_IDS['D'][0]])
        self.assertEqual(out['status'],'not_ready');self.assertFalse(out['executed'])

if __name__=='__main__':unittest.main()
