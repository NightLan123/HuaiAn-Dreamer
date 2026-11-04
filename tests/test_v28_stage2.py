"""Equation checks, not claims about the direction of human trait effects."""
import copy, unittest
import numpy as np
from persona.psychology import empty_profile
from persona.pmm_contracts import construct_blocks, BLOCK_IDS
from persona.trait_dynamics import (initial_checkpoint,seal,TraitDynamics,torch_model,
    SHAPES,ADAPTER_SHAPES,DH,DQ,DR,DM,DA,checked_inputs,latent_H,algebra)

def inputs(subject='a'):
    return {'blocks':construct_blocks(empty_profile(subject,'test')),'q':[0.]*DQ,
            'r':[0.]*DR,'m':[0.]*DM,'affect':[0.]*DA,'h_prev':[0.]*DH}

def known(x,block,index,value,u=.1):
    r=x['blocks'][block];r['values'][index]=value;r['mask'][index]=1;r['uncertainty'][index]=u
    r['sources'][index]={'source_type':'synthetic_fixture','evidence_refs':['controlled']}

class Equations(unittest.TestCase):
    def test_manual_weights_exact_A_B(self):
        ck=initial_checkpoint('a');p={k:np.zeros(s) for k,s in SHAPES.items()};a={k:np.zeros(s) for k,s in ADAPTER_SHAPES.items()}
        x=inputs();known(x,'H',0,.4,0.);x['q'][0]=.3;x['h_prev'][0]=.1
        p['A_diag'][0]=.2;p['B'][0,0]=.5;p['bias'][0]=.01
        p['H_enc_value'][0]=1.;p['H_W_l'][0,0]=2;p['H_W_r'][0,0]=.5
        p['H_C_l'][0,0]=1.;p['H_C_r'][0,0]=1.;p['H_U_l'][0,0]=1.;p['H_U_r'][0,0]=2.
        p['H_H'][0,0]=2.;p['Lambda'][0]=.5;p['action'][0,0]=1.
        ck['parameters']={k:v.tolist() for k,v in p.items()};ck['adapter']={k:v.tolist() for k,v in a.items()};ck=seal(ck)
        out=TraitDynamics(ck,'a').forward(x);h=np.tanh(.2*.1+.5*.3+.4+.4*2*.3+.01)
        self.assertAlmostEqual(out['latent'][0],h,places=12)
        self.assertAlmostEqual(out['state_prediction'][0],.5*.4+2*h,places=12)
        self.assertAlmostEqual(out['action_probabilities']['reply'],np.exp(h)/(np.exp(h)+5),places=12)
        self.assertFalse(out['prediction_is_observation'])

    def test_numpy_torch_identical(self):
        ck=initial_checkpoint('a');x=inputs()
        for b in BLOCK_IDS:known(x,b,0,.7)
        x['q'][0]=.8;x['r'][1]=.2;x['h_prev'][1]=.3
        n=TraitDynamics(ck,'a').forward(x);t=torch_model(ck,'a')(x)
        np.testing.assert_allclose(n['latent'],t['h'].detach().numpy(),rtol=1e-12,atol=1e-12)
        np.testing.assert_allclose(n['state_prediction'],t['state'].detach().numpy(),rtol=1e-12,atol=1e-12)
        np.testing.assert_allclose(list(n['action_probabilities'].values()),t['action'].detach().numpy(),rtol=1e-12,atol=1e-12)

    def test_real_shared_and_adapter_gradients_finite_difference(self):
        import torch
        ck=initial_checkpoint('a');x=inputs();known(x,'H',0,.7);x['q'][0]=.6;x['h_prev'][0]=.3
        net=torch_model(ck,'a');loss=-torch.log(net(x)['action'][0])+net(x)['state'][0]**2
        loss.backward()
        for group,k,index in [('core','B',(0,0)),('core','H_C_l',(0,0)),('adapter','a_left',(0,0)),('adapter','a_bias',(0,))]:
            par=getattr(net,group)[k];analytic=par.grad[index].item();v=par[index].item();eps=1e-6
            with torch.no_grad():par[index]=v+eps
            y=net(x);plus=(-torch.log(y['action'][0])+y['state'][0]**2).item()
            with torch.no_grad():par[index]=v-eps
            y=net(x);minus=(-torch.log(y['action'][0])+y['state'][0]**2).item()
            with torch.no_grad():par[index]=v
            self.assertNotEqual(analytic,0.);self.assertAlmostEqual(analytic,(plus-minus)/(2*eps),places=7)

    def test_torch_gradcheck_interaction_and_recurrence(self):
        import torch
        ck=initial_checkpoint('a');x=inputs();known(x,'H',0,.6);x['q'][0]=.2;x['h_prev'][0]=.4
        xx=checked_inputs(x);xx['latent_H']=latent_H(ck,xx)
        def tensors(v):return {k:tensors(z) for k,z in v.items()} if isinstance(v,dict) else torch.tensor(v,dtype=torch.float64)
        xx=tensors(xx);p=tensors(ck['parameters']);a=tensors(ck['adapter'])
        def fn(b,ab):
            pp={**p,'B':b};aa={**a,'a_bias':ab};return algebra(pp,aa,xx,torch)['state']
        self.assertTrue(torch.autograd.gradcheck(fn,(p['B'].requires_grad_(),a['a_bias'].requires_grad_()),eps=1e-6,atol=1e-5))

    def test_all_blocks_influence_and_single_facet_intervention(self):
        ck=initial_checkpoint('a');model=TraitDynamics(ck,'a');base=inputs();before=model.forward(base)
        for b in BLOCK_IDS:
            x=copy.deepcopy(base);known(x,b,0,.8);after=model.forward(x)
            self.assertGreater(np.linalg.norm(np.array(after['latent'])-before['latent']),1e-9,b)
            self.assertNotEqual(after['construct_paths'][b],before['construct_paths'][b])
        a=inputs();known(a,'H',0,.2);b=copy.deepcopy(a);known(b,'H',0,.8)
        self.assertNotEqual(model.forward(a)['state_prediction'],model.forward(b)['state_prediction'])

    def test_unknown_vs_known_zero_and_uncertainty(self):
        m=TraitDynamics(initial_checkpoint('a'),'a');a=inputs();b=copy.deepcopy(a);known(b,'H',0,0.)
        self.assertNotEqual(m.forward(a)['latent'],m.forward(b)['latent'])
        c=copy.deepcopy(b);c['blocks']['H']['uncertainty'][0]=None
        self.assertNotEqual(m.forward(b)['latent'],m.forward(c)['latent'])
        self.assertIsNone(a['blocks']['H']['values'][0])

    def test_shape_finiteness_digest_and_subject_rejected(self):
        ck=initial_checkpoint('a')
        with self.assertRaises(ValueError):TraitDynamics(ck,'b')
        bad=copy.deepcopy(ck);bad['parameters']['B'][0][0]+=1.
        with self.assertRaises(ValueError):TraitDynamics(bad,'a')
        for v in ([0.], [float('nan')]*DQ):
            x=inputs();x['q']=v
            with self.assertRaises(ValueError):TraitDynamics(ck,'a').forward(x)
    def test_value_relative_center_retains_mask(self):
        x=inputs();known(x,'V',0,.2);known(x,'V',1,.8)
        p=checked_inputs(x)['blocks']['V'];self.assertAlmostEqual(p['value'][0],-.3)
        self.assertAlmostEqual(p['value'][1],.3);self.assertEqual(p['mask'].sum(),2)
    def test_json_roundtrip_reproducible(self):
        import json
        ck=initial_checkpoint('a');x=inputs()
        self.assertEqual(TraitDynamics(ck,'a').forward(x),TraitDynamics(json.loads(json.dumps(ck)),'a').forward(x))

if __name__=='__main__':unittest.main()
