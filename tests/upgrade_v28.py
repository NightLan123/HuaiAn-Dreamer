"""Run actual archived 2.7 -> 2.8 -> original 2.7, on synthetic trained data."""
import argparse,copy,json,os,shutil,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from upgrade_trait_affect_v230 import OLD_SCRIPT,metadata
from persona.server import Runtime
from persona.packages import export_continuity,validate_pack
from persona.registry import digest
from test_v212 import PatchProvider

ROLLBACK=r'''
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from persona.server import Runtime
from persona.common import VERSION
assert VERSION=='2.7'
r=Runtime(sys.argv[2],Path(sys.argv[1]));expected=json.loads(Path(sys.argv[3]).read_text())
try:
 for ident,prior in expected.items():
  st,_,e,_=r.context(ident)
  assert e.model.export()==prior['checkpoint']
  for sid,rows in prior['history'].items():assert st.history(sid,10000)==rows
  assert st.meta('pmm28_models')==prior['models']
finally:r.close()
print('original_2_7_rollback_read_success')
'''

def main():
    p=argparse.ArgumentParser();p.add_argument('--old-root',type=Path,required=True);args=p.parse_args()
    script=OLD_SCRIPT.replace("assert VERSION in ('2.2.1','2.2.2','2.2.3')","assert VERSION=='2.7'")
    script=script.replace('        snapshots[ident]=r.snapshot();',"        from persona import pragmatics as pg\n        with st.lock,st.db:st.setmeta('pmm_pragmatics',pg.rebuild(st.meta('pmm_pragmatics'),profile['source_records']))\n        snapshots[ident]=r.snapshot();")
    with tempfile.TemporaryDirectory(prefix='huai-an-v28-upgrade-') as temp:
        base=Path(temp);data=base/'旧训练资料';expected=base/'before.json'
        env={**os.environ,'OPENBLAS_NUM_THREADS':'1'}
        subprocess.run([sys.executable,'-c',script,str(args.old_root.resolve()),str(data),str(expected)],check=True,env=env,cwd=base)
        before=json.loads(expected.read_text());shutil.copytree(data,base/'pre-v28-backup')
        r=Runtime(data,ROOT);checks=[];rollback={}
        try:
            current=r.config.get();new=current.pop('pmm28');assert current==before['config'];assert new['mode']=='shadow'
            assert r.subjects.catalog==before['catalog']
            for ident,snap in before['snapshots'].items():
                st,_,e,_=r.context(ident);after=st.snapshot();om=metadata(snap);nm=metadata(after)
                for table in snap['tables']:
                    if table!='meta':assert after['tables'][table]==snap['tables'][table],table
                for key,value in om.items():assert nm[key]==value,key
                assert e.model.export()==om['pmm_checkpoint']
                model=e.model.fork();e.ingest_samples(model,st.meta('pmm_training_records'));model.fit(2)
                assert model.steps==e.model.steps+2
                validate_pack(export_continuity(e));checks.append({'identity':ident,'steps_before':e.model.steps,'continued_steps':model.steps,'checkpoint_sha256':digest(e.model.export()),'all_old_metadata_exact':True})
            r.switch(before['active']);r.configure({'pmm28':{'mode':'active'}})
            r.engine.provider_factory=PatchProvider;r.engine.pmm_provider_factory=PatchProvider
            sid=r.store.session();out=r.engine.turn(sid,'合成的 2.8 升级后交互')
            assert out['trace']['pmm28']['components']['neural']['executed']
            from persona.pmm_coordinator import PMMCoordinator
            from test_v28_stage4 import dataset,import_fixture
            co=PMMCoordinator(r.engine);rows,plan=dataset(before['active']);import_fixture(co,before['active'],rows)
            trained=co.model_action({'op':'train','subject_id':before['active'],'expected_revision':0,'job_id':'upgrade-fixture','split_plan':plan,'epochs':1,'structural_candidates':[0.]})
            validate_pack(export_continuity(r.engine));catalog=r.store.meta('pmm28_models')
            r.configure({'pmm28':{'mode':'legacy'}})
            for ident in before['snapshots']:
                st,_,e,_=r.context(ident);rollback[ident]={'checkpoint':e.model.export(),'history':{s['id']:st.history(s['id'],10000) for s in st.sessions()},'models':st.meta('pmm28_models')}
        finally:r.close()
        r=Runtime(data,ROOT)
        try:assert r.store.meta('pmm28_models')==catalog;assert r.config.get()['pmm28']['mode']=='legacy'
        finally:r.close()
        rollback_file=base/'rollback.json';rollback_file.write_text(json.dumps(rollback))
        # A COPY isolates destructive possibilities of old software. The new
        # acknowledged messages, not the pre-upgrade backup, are checked here.
        rollback_data=base/'旧程序回退检查';shutil.copytree(data,rollback_data)
        proc=subprocess.run([sys.executable,'-c',ROLLBACK,str(args.old_root.resolve()),str(rollback_data),str(rollback_file)],capture_output=True,text=True,env=env,cwd=base)
        if proc.returncode:raise RuntimeError(proc.stdout+proc.stderr)
        fresh=Runtime(base/'fresh',ROOT)
        try:
            ident=before['active'];snap=before['snapshots'][ident]
            fresh.create_persona({'name':'旧包迁移','package':before['packs'][ident]});assert fresh.engine.model.export()==metadata(snap)['pmm_checkpoint']
            fresh.restore(snap);assert fresh.engine.profile()==metadata(snap)['pmm_profile'];assert fresh.engine.model.export()==metadata(snap)['pmm_checkpoint']
        finally:fresh.close()
        print(json.dumps({'from':'2.7','to':'2.8','actual_archived_runtime_executed':True,'subjects':2,'pre_upgrade_backup':True,
            'all_old_metadata_and_tables_exact_before_new_interaction':True,'old_pack_import':True,'old_snapshot_restore':True,
            'continued_legacy_training':True,'new_candidate_restart_exact':True,'original_2_7_reads_newly_confirmed_messages':True,
            'rollback_preserves_new_metadata':True,'production_database':False,'checks':checks},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
