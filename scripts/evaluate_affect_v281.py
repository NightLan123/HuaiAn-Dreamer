"""Controlled Engine/SQLite experiment; LLM is a declared deterministic fixture."""
import copy,json,sys,tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_v281_runtime import Provider281
from persona.server import Runtime
from persona import affect_runtime as ar
from persona.registry import digest

def experiment(destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        rt=Runtime(folder,ROOT)
        try:
            rt.configure({'model':'fixture-general','pmm':{'api':{'model':'fixture-A'}},'pmm281':{'mode':'full','b_policy':'always'},'cognition':{'mode':'baseline'}})
            rt.engine.provider_factory=rt.engine.pmm_provider_factory=Provider281
            sid=rt.store.session('qq:123','private:qq:123');snapshot=rt.store.snapshot();owner=rt.engine.profile()['id'];t0=1804200000.
            event={'id':'seed','text':'seed','scope':'private:qq:123','person':'qq:123','session_id':sid}
            model=ar.model_for(rt.store);rows=[];profiles={}
            for name,value in [('persona_low',.2),('persona_high',.8)]:
                p=rt.engine.profile()
                for field in p['psychology']['features']:
                    if field.startswith('hexaco.'):p['psychology']['features'][field].update(estimate=value,posterior_uncertainty=.4,source_type='manual_prior')
                profiles[name]=p
            cases=[(p,dt,None) for p in profiles for dt in (60,86400)]+[('persona_low',60,'fast_intervention'),('persona_low',60,'suppression'),('persona_low',60,'none')]
            from persona.affect_runtime import draft as real_draft
            for name,dt,intervention in cases:
                rt.store.restore(copy.deepcopy(snapshot));p=profiles[name]
                base=rt.store.meta(ar.KEY);row=ar.initial_stream(base,event,model,t0)
                row.update(fast=[.7,.2,-.1,.4,.3],mood=[.2,.1,.1],last_at=t0,rng_state=np.random.default_rng(281).bit_generator.state)
                if intervention=='fast_intervention':row['fast'][0]=-.7
                base['streams'][ar.stream_key(owner,event)]=row
                with rt.store.lock,rt.store.db:rt.store.setmeta(ar.KEY,base);rt.store.setmeta('pmm_profile',p)
                def fixed_strategy(*args,**kwargs):
                    kwargs['strategy']=intervention if intervention in ('suppression','none') else 'none'
                    return real_draft(*args,**kwargs)
                with patch('persona.execution.now',return_value=t0+dt),patch('persona.affect_runtime.draft',side_effect=fixed_strategy):out=rt.engine.turn(sid,'这件事情对我很重要，我想和你讨论。')
                co=out['trace']['pmm28']['components'];em=co['affect']['payload']['dynamics_v2'];ne=co['neural']['payload']
                rows.append({'persona':name,'seconds':dt,'intervention':intervention,'personality_sha256':digest(p),'emotion_model':model['sha256'],
                    'neural_model':co['neural']['model_versions'],'fast':em['affect_observed'],'mood':em['mood_observed'],'jump':em['jump'],
                    'latent_h':ne['latent'],'neural_action_candidates':ne['action_probabilities'],'formal_neural':ne['formal_eligible'],
                    'decision':out['trace']['decision'],'expression':em['expression_plan'],'delta_seconds':em['delta_seconds']})
                if len(rows)==1:(destination/'component_trace.json').write_text(json.dumps(out['trace']['pmm28'],ensure_ascii=False,indent=2))
            assert rows[0]['fast']!=rows[1]['fast'] and rows[0]['mood']!=rows[1]['mood']
            assert rows[0]['latent_h']!=rows[2]['latent_h']
            assert rows[0]['latent_h']!=rows[4]['latent_h']
            assert rows[5]['fast']==rows[6]['fast'] and rows[5]['expression']!=rows[6]['expression']
            assert all(not r['formal_neural'] for r in rows)
            result={'kind':'controlled_engine_experiment','transport':'deterministic_fixture_not_live_model','rng_seed':281,'cases':rows,
                'conclusion':'实际 Engine 前向和事务通过；人格/时间/情绪干预改变网络条件，抑制只改变表达。未标定神经候选不自动主导行动；最终行动可保持相同。','psychological_validity':False}
            (destination/'controlled_experiment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));return result
        finally:rt.close()
if __name__=='__main__':
    result=experiment(sys.argv[1] if len(sys.argv)>1 else ROOT/'reports/v281/stage2');print(json.dumps({'cases':len(result['cases']),'passed':True}))
