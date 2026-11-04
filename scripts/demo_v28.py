"""Eight reproducible engineering scenarios. NEVER empirical human/Qwen data."""
import argparse,copy,json,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from persona.server import Runtime
from persona import traits
from persona.pmm_contracts import BLOCK_IDS
from persona.pmm_coordinator import PMMCoordinator
from persona.pmm_experiments import from_turn
from persona.registry import digest
from persona.trait_estimator import predict,linear_gaussian
from test_v212 import PatchProvider
from test_v28_stage4 import dataset,import_fixture
from test_v28_longitudinal import scale_data

def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')

def register(co,row,prefix):
    row=copy.deepcopy(row);e=co.engine
    text='SYNTHETIC ENGINEERING FIXTURE; NOT A HUMAN MEASUREMENT: '+prefix
    raw={'id':prefix,'event_id':row['event_id'],'speaker':'fixture-reviewer','scope':row['scope'],'source':'imported',
         'text':text,'timestamp':row['timestamp'],'measurement_subject_id':row['subject_id']}
    with e.store.lock,e.store.db:r=e.evidence.register([raw],'v28-engineering-demo')[0]
    row.update(event_id=r['origin_event_id'],evidence_refs=[r['origin_record_key']],quotes={r['origin_record_key']:text})
    return row

def longitudinal_demo(co):
    owner=co.engine.profile()['id'];hid=BLOCK_IDS['H'][0];scope='study:fixture';rows,plan=scale_data()
    rows=[register(co,{**r,'scope':scope},'scale-'+str(i)) for i,r in enumerate(rows)]
    calibration=co.longitudinal_action({'op':'calibrate_scale','subject_id':owner,'expected_revision':0,
        'construct_ids':[hid],'split_plan':plan,'scale_id':'synthetic-latent','rows':rows})
    protocol=calibration['model'];pairs=[];transition_plan={}
    for fold,t in [('train',1000000.),('validation',2000000.),('test',3000000.)]:
        subjects=[fold+'-G-a',fold+'-G-b'];transition_plan[fold]={'subjects':subjects,'start':t,'end':t+300000.}
        for subject in subjects:
            bindings=[]
            for i in range(4):
                bindings.append(register(co,{'subject_id':subject,'scope':scope,'event_id':subject+str(i),
                    'timestamp':t+i*86400.,'reviewed':True,'engineering_fixture':True,'source_kind':'controlled_fixture'},subject+'-'+str(i)))
            states=[]
            for binding in bindings[1:3]:
                states.append({**binding,'kind':'independent_state_measurement','context':[.3],'latent_observed':[.65],
                               'measurement_covariance':[[.04]]})
            pairs.append({'subject_id':subject,'scope':scope,'before_event_id':bindings[0]['event_id'],
                'after_event_id':bindings[-1]['event_id'],'before_time':bindings[0]['timestamp'],'after_time':bindings[-1]['timestamp'],
                'before':[.8],'after':[.85],'state_observations':states,'source_kind':'controlled_fixture',
                'reviewed':True,'engineering_fixture':True,'evidence_bindings':bindings,
                'evidence_refs':[k for b in bindings for k in b['evidence_refs']]})
    transition=co.longitudinal_action({'op':'train_transition','subject_id':owner,'expected_revision':1,
        'protocol_id':protocol['id'],'construct_ids':[hid],'split_plan':transition_plan,'rows':pairs})['model']
    observed=[]
    for i in range(4):
        observed.append(register(co,{'subject_id':owner,'scope':scope,'event_id':'estimate-'+str(i),'timestamp':5000000.+i*86400.,
                                     'reviewed':True,'engineering_fixture':True,'source_kind':'controlled_fixture'},'estimate-'+str(i)))
    prior={**observed[0],'construct_ids':[hid],'scale_id':'synthetic-latent','mu':[1.8],'P':[[.2]]}
    samples=[{**r,'kind':'independent_state_measurement','context':[.3],'latent_observed':[.65],
              'measurement_covariance':[[.04]]} for r in observed[1:3]]
    measurement={**observed[-1],'scale_id':'synthetic-latent','model':'linear_gaussian','y':[2.],'H':[[1.]],'R':[[.1]]}
    body={'op':'estimate','subject_id':owner,'expected_revision':2,'scope':scope,'protocol_id':protocol['id'],
          'transition_id':transition['id'],'prior':prior,'samples':samples,'measurement':measurement}
    before=digest(co.engine.profile());result=co.longitudinal_action(body)
    assert before==digest(co.engine.profile()) and result['proposal']['engineering_only']
    assert not result['proposal']['payload']['G_validated'] and result['proposal']['payload']['posterior']['updated']
    return {'dataset':'controlled_synthetic_only','calibration_rows':rows,'calibration_plan':plan,'measurement_calibration':protocol,
            'transition_rows':pairs,'transition_plan':transition_plan,'G_candidate':transition,'estimate_request':body,
            'stored_proposal':result['proposal'],'canonical_profile_unchanged':True,
            'formula_D_handcheck':predict([.4],[[.1]],[.2],[[.04]],G=[[.5]],Q=[[.01]],g_validated=True),
            'formula_E_handcheck':linear_gaussian([.4],[[.2]],[.8],[[1.]],[[.1]]),
            'handcheck_interpretation':'specified coefficients only, not a validated transition model'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'examples/v28_demo');args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='huai-an-v28-demo-') as temp:
        r=Runtime(temp,ROOT)
        try:
            r.configure({'cognition':{'mode':'baseline'},'model':'synthetic-General-transport','pmm':{'mode':'api','api':{'model':'synthetic-Reasoner-transport'}},'pmm28':{'mode':'active'}})
            r.engine.provider_factory=PatchProvider;r.engine.pmm_provider_factory=PatchProvider
            owner=r.engine.profile()['id'];profile=r.engine.profile()
            for b in BLOCK_IDS:
                for i,k in enumerate(BLOCK_IDS[b][:2]):
                    profile=traits.edit_disposition(profile,{'feature_id':k,'estimate':.3+.4*i,'expected_version':profile['trait_profile']['version'],'timeframe':'generally','note':'SYNTHETIC OWNER SETTING'})
            with r.store.lock,r.store.db:r.store.setmeta('pmm_profile',profile)
            sid=r.store.session('qq:fixture','private:qq:fixture')
            before=copy.deepcopy(r.engine.profile()['trait_profile'])
            normal=r.engine.turn(sid,'合成场景：我喜欢安静地读书。',turn_context={'sources':['demo-event-1']})
            trace=normal['trace']['pmm28'];assert trace['components']['neural']['executed']
            write(args.output/'normal_trace.json',{'transport':'explicit_synthetic_fixture_not_live_Qwen','trace':trace})
            ablation=from_turn(r.engine,{'subject_id':owner,'turn_id':normal['turn_id'],'feature_id':BLOCK_IDS['H'][0]})
            write(args.output/'ablations.json',ablation)
            negative=r.engine.turn(sid,'合成场景：我很生气，你完全没有理解我。')
            unchanged=before==r.engine.profile()['trait_profile'];assert unchanged
            class Timeout(PatchProvider):
                def complete(self,*args,**kwargs):raise TimeoutError('explicit fixture transport timeout')
            r.engine.pmm_provider_factory=Timeout;failed=r.engine.turn(sid,'合成超时场景')
            assert failed['trace']['pmm28']['components']['reasoner']['status']=='failed' and failed['reply']
            write(args.output/'api_failure_trace.json',{'transport':'injected_timeout','trace':failed['trace']['pmm28']})
            r.engine.pmm_provider_factory=PatchProvider;co=PMMCoordinator(r.engine)
            rows,plan=dataset(owner);import_fixture(co,owner,rows)
            trained=co.model_action({'op':'train','subject_id':owner,'expected_revision':0,'job_id':'demo-training','split_plan':plan,'epochs':15,'learning_rate':.1,'structural_candidates':[0.]})
            catalog=r.store.meta('pmm28_models');key=trained['candidate']
            write(args.output/'candidate_checkpoint.json',catalog['versions'][key]);write(args.output/'training_report.json',trained['report'])
            write(args.output/'training_dataset.json',{'engineering_only':True,'samples':catalog['datasets'][key]});write(args.output/'split_plan.json',plan)
            long=longitudinal_demo(co);write(args.output/'longitudinal_audit.json',long)
            samples=r.store.meta('pmm28_samples');count=len(samples['rows']);co.review_samples({'subject_id':owner,'expected_revision':samples['revision'],'samples':list(samples['rows'].values())})
            assert len(r.store.meta('pmm28_samples')['rows'])==count
            selected=next(iter(samples['rows']));co.review_samples({'op':'withdraw','subject_id':owner,'expected_revision':2,'key':selected,'reason':'controlled demo withdrawal'})
            blocked=False
            try:co.model_action({'op':'train','subject_id':owner,'expected_revision':1,'job_id':'withdrawn-training','split_plan':plan,'sample_keys':[selected],'epochs':1})
            except ValueError:blocked=True
            assert blocked
            history=copy.deepcopy(r.store.history(sid));duplicate=r.engine.turn(sid,'合成场景：我喜欢安静地读书。',turn_context={'sources':['demo-event-1']})
            assert duplicate['replayed'] and history==r.store.history(sid)
            r.create_persona({'name':'Synthetic B'});assert r.store.meta('pmm28_models') is None and r.store.meta('pmm28_samples') is None
            r.switch(owner);r.configure({'pmm28':{'mode':'legacy'}});assert history==r.store.history(sid)
            summary={'version':'2.8','engineering_fixture_only':True,'live_model_calls':0,'live_qq_sends':0,'psychological_validity_established':False,
                'scenarios':{'1_same_turn':{'same_turn_id':trace['turn_id'],'api_adapter_executed':trace['components']['reasoner']['executed'],'neural_executed':True},
                    '2_intervention':ablation['intervention'],'3_API_failure_reply_preserved':True,
                    '4_uncalibrated_formal_contribution':trace['components']['decision']['payload']['formal_contribution'],
                    '5_negative_event_stable_personality_unchanged':unchanged,
                    '6_synthetic_longitudinal_candidate':{'posterior':long['stored_proposal']['payload']['posterior'],'G_validated':False,'formal_commit':False},
                    '7_withdrawal_blocks_training_and_duplicate_no_write':True,'8_two_subjects_and_legacy_history_preserved':True},
                'publication':'candidate only; synthetic models rejected by real publication gate'}
            write(args.output/'summary.json',summary)
            print(json.dumps({'output':str(args.output),'scenarios':8,'result':'passed_engineering_only','real_Qwen_QQ':False,'trained_candidate_sha256':key},ensure_ascii=False))
        finally:r.close()

if __name__=='__main__':main()
