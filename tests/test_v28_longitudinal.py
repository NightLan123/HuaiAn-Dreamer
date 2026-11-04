"""Scale math plus actual SQLite transaction plumbing. No empirical data claims."""
import copy,unittest
import numpy as np
from unittest.mock import patch
from test_v212 import Base
from persona.trait_estimator import fit_measurement_scale
from persona.pmm_contracts import BLOCK_IDS
from persona.pmm_longitudinal import empty,validate,transition_rows
from persona.pmm_coordinator import PMMCoordinator
from persona.registry import digest
HID=BLOCK_IDS['H'][0]

def scale_data():
    rows=[];plan={}
    for name,t in [('train',100.),('validation',10000.),('test',20000.)]:
        subjects=[name+'a',name+'b'];plan[name]={'subjects':subjects,'start':t,'end':t+100.}
        for j,subject in enumerate(subjects):
            for i in range(4):
                x=.1+.2*i;context=.1+.15*i;noise=.005*(1 if (i+j)%2 else -1)
                rows.append({'subject_id':subject,'event_id':subject+str(i),'timestamp':t+i,'source_kind':'controlled_fixture',
                             'reviewed':True,'evidence_refs':['fixture:'+subject+str(i)],'engineering_fixture':True,
                             'canonical':[x],'latent':[2*x+1+noise],'context':[context],'state':[.3+.5*context+noise]})
    return rows,plan

class CalibrationMath(unittest.TestCase):
    def test_independent_scale_fit_does_not_certify_fixture(self):
        rows,plan=scale_data();model=fit_measurement_scale(rows,[HID],plan,'synthetic-latent')
        self.assertAlmostEqual(model['slope'][0],2.,places=8);self.assertAlmostEqual(model['intercept'][0],1.,places=8)
        self.assertFalse(model['validated']);self.assertTrue(model['engineering_only'])
        self.assertLess(model['metrics']['test']['scale_mse'],model['metrics']['test']['baseline_mse'])
        self.assertGreater(model['context_covariance'][0][0],0.)
    def test_scale_unidentifiable_and_leaking_data_rejected(self):
        rows,plan=scale_data()
        for r in rows:r['canonical']=[.5]
        with self.assertRaises(ValueError):fit_measurement_scale(rows,[HID],plan,'x')
        rows,plan=scale_data();plan['test']['subjects'].append(plan['train']['subjects'][0])
        with self.assertRaises(ValueError):fit_measurement_scale(rows,[HID],plan,'x')
    def test_duplicate_calibration_events_not_extra_evidence(self):
        rows,plan=scale_data();a=fit_measurement_scale(rows,[HID],plan,'x');b=fit_measurement_scale(rows+rows,[HID],plan,'x')
        self.assertEqual(a,b)

class CanonicalCommit(Base):
    def seeded_proposal(self):
        owner=self.r.engine.profile()['id'];co=PMMCoordinator(self.r.engine);sources=[]
        for i in range(4):
            record={'id':'controlled-'+str(i),'speaker':'controlled-reviewer','scope':'private:web:owner','source':'human',
                    'text':'Explicit synthetic observation '+str(i),'timestamp':float(100+i*86400),'event_id':'event-'+str(i),'measurement_subject_id':owner}
            with self.r.store.lock,self.r.store.db:r=self.r.engine.evidence.register([record],'controlled-transaction-test')[0]
            sources.append({'subject_id':owner,'scope':r['scope'],'event_id':r['origin_event_id'],'timestamp':record['timestamp'],
                            'evidence_refs':[r['origin_record_key']],'quotes':{r['origin_record_key']:record['text']}})
        profile=self.r.engine.profile();state=empty(owner);protocol={'id':'injected-protocol','construct_ids':[HID],'scale_id':'unit',
                 'slope':[1.],'intercept':[0.],'validated':True};transition={'id':'injected-transition','validated':True}
        proposal={'subject_id':owner,'scope':'private:web:owner','prior_revision':profile['revision'],'profile_digest':digest(profile),
                  'protocol_id':protocol['id'],'transition_id':transition['id'],'engineering_only':False,
                  'source_rows':sources,'payload':{'proposal_id':'controlled-transaction','construct_ids':[HID],'scale_id':'unit',
                    'posterior':{'mu':[.63],'P':[[.01]],'updated':True},'G_validated':True,
                    'state_summary':{'ready':True,'event_ids':[s['event_id'] for s in sources[1:3]]},'measurement':sources[-1]}}
        state['protocols'][protocol['id']]={'model':protocol};state['transitions'][transition['id']]={'model':transition};state['proposals'][proposal['payload']['proposal_id']]=proposal
        with self.r.store.lock,self.r.store.db:self.r.store.setmeta('pmm28_estimator',state)
        # This injects the VALIDATION SERVICE only to test commit wiring. These
        # fixtures are never stored in shipped runtime data or accepted by the
        # real calibration gate, which requires reproducible independent rows.
        return owner,co,state,protocol,transition

    def test_actual_CAS_commit_idempotence_and_next_round_reads_canonical_trait(self):
        owner,co,state,p,t=self.seeded_proposal();self.r.configure({'pmm28':{'mode':'active','long_term_mode':'validated_commit'}})
        with patch('persona.pmm_longitudinal.calibration_live',side_effect=lambda co,entry,kind:p if kind=='protocol' else t):
            out=co.longitudinal_action({'op':'commit','subject_id':owner,'expected_revision':0,'proposal_id':'controlled-transaction'})
            duplicate=co.longitudinal_action({'op':'commit','subject_id':owner,'expected_revision':0,'proposal_id':'controlled-transaction'})
        self.assertTrue(out['committed']);self.assertTrue(duplicate['duplicate'])
        profile=self.r.engine.profile();self.assertEqual(profile['psychology']['features'][HID]['estimate'],.63)
        self.assertEqual(profile['trait_profile']['promotion_history'][-1]['method'],'pmm-D-E/2.8')
        turn=self.turn();blocks=turn['trace']['pmm28']['components']['neural']['payload']['blocks']
        self.assertEqual(blocks['H']['values'][0],.63)
        from persona.packages import validate_pack,export_continuity
        validate_pack(export_continuity(self.r.engine))
        self.assertEqual(len(self.r.store.rows("SELECT * FROM events WHERE kind='pmm28_trait_revision'")),1)
    def test_profile_CAS_conflict_preserves_state(self):
        owner,co,state,p,t=self.seeded_proposal();self.r.configure({'pmm28':{'mode':'active','long_term_mode':'validated_commit'}})
        profile=self.r.engine.profile();profile['revision']+=1
        with self.r.store.lock,self.r.store.db:self.r.store.setmeta('pmm_profile',profile)
        with patch('persona.pmm_longitudinal.calibration_live',side_effect=lambda co,entry,kind:p if kind=='protocol' else t):
            with self.assertRaises(ValueError):co.longitudinal_action({'op':'commit','subject_id':owner,'expected_revision':0,'proposal_id':'controlled-transaction'})
        self.assertEqual(self.r.engine.profile(),profile)
    def test_real_gate_rejects_forged_validated_flag(self):
        owner,co,state,p,t=self.seeded_proposal();self.r.configure({'pmm28':{'mode':'active','long_term_mode':'validated_commit'}})
        before=digest(self.r.engine.profile())
        with self.assertRaises((ValueError,KeyError)):co.longitudinal_action({'op':'commit','subject_id':owner,'expected_revision':0,'proposal_id':'controlled-transaction'})
        self.assertEqual(before,digest(self.r.engine.profile()))

if __name__=='__main__':unittest.main()
