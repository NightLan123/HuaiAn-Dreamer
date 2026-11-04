"""Exercise the exact archived 2.8 source, legacy trained weights and automatic rollback copy."""
import hashlib,json,os,shutil,subprocess,sys,tempfile,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from upgrade_trait_affect_v230 import OLD_SCRIPT,metadata
from persona.server import Runtime
from persona.registry import digest
from persona.packages import export_continuity,validate_pack
from test_v281_runtime import Provider281
ARCHIVE=ROOT/'legacy/HuaiAn_Dreamer_v2.8.zip'

def main():
    archive_sha=hashlib.sha256(ARCHIVE.read_bytes()).hexdigest();assert archive_sha=='7d93a26b4d2bfc58cb4bd7e19306c126128f86f17e3f48256fd67b2e6febbdee'
    with tempfile.TemporaryDirectory(prefix='huaian-281-migration-') as tmp:
        work=Path(tmp);data=work/'旧训练数据';expected=work/'old.json';old=work/'HuaiAn_Dreamer_v2.8'
        with zipfile.ZipFile(ARCHIVE) as z:z.extractall(work)
        script=OLD_SCRIPT.replace("assert VERSION in ('2.2.1','2.2.2','2.2.3')","assert VERSION=='2.8'")
        extra='''        from persona import pragmatics as pg
        from persona.pmm_coordinator import PMMCoordinator
        sys.path.insert(0,str(old/'tests'))
        from test_v28_stage4 import dataset,import_fixture
        co=PMMCoordinator(e);rows,plan=dataset(ident);import_fixture(co,ident,rows)
        co.model_action({'op':'train','subject_id':ident,'expected_revision':0,'job_id':'old-model','split_plan':plan,'epochs':1,'structural_candidates':[0.]})
        with st.lock,st.db:st.setmeta('pmm_pragmatics',pg.rebuild(st.meta('pmm_pragmatics'),e.profile()['source_records']))
'''
        script=script.replace('        snapshots[ident]=r.snapshot();',extra+'        snapshots[ident]=r.snapshot();')
        env={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'}
        subprocess.run([sys.executable,'-c',script,str(old),str(data),str(expected)],cwd=work,env=env,check=True)
        before=json.loads(expected.read_text());app=Runtime(data,ROOT);check=[]
        try:
            assert app.upgrade['kind']=='upgrade';backup=Path(app.upgrade['backup']);assert all(hashlib.sha256((backup/r['path']).read_bytes()).hexdigest()==r['sha256'] for r in app.upgrade['sqlite_snapshots'])
            assert before['catalog']==app.subjects.catalog
            for ident,old_snap in before['snapshots'].items():
                st,cfg,en,_=app.context(ident);new=st.snapshot();om=metadata(old_snap);nm=metadata(new)
                for k,v in om.items():assert nm[k]==v,k
                for table in ('messages','sessions','memories','relations'):assert new['tables'][table]==old_snap['tables'][table],table
                assert all(x in new['tables']['events'] for x in old_snap['tables']['events'])
                assert cfg.get()['pmm281']['mode']=='full';assert nm['pmm281_affect']['migration']['old_sha256']==digest(om['pmm_affect'])
                candidate=en.model.fork();en.ingest_samples(candidate,st.meta('pmm_training_records'));candidate.fit(2);assert candidate.steps==en.model.steps+2
                validate_pack(before['packs'][ident]);validate_pack(export_continuity(en))
                check.append({'subject':ident,'old_weight_sha256':digest(en.model.export()),'old_weight_steps':en.model.steps,'continued_steps_on_fork':candidate.steps,'legacy_2_8_neural_versions':len(nm['pmm28_models']['versions']),'old_metadata_keys_exact':len(om),'old_examples':len(en.profile()['examples'])})
            owner=before['active'];app.switch(owner);app.configure({'pmm281':{'mode':'full','b_policy':'always'}});app.engine.pmm_provider_factory=app.engine.provider_factory=Provider281
            sid=app.store.session();out=app.engine.turn(sid,'迁移后的合成事件',turn_context={'sources':['synthetic-upgrade-event']});assert out['trace']['pmm28']['components']['neural']['executed']
            after=app.store.meta('pmm281_affect');assert after['revision']==1;newpack=export_continuity(app.engine)
            mode=app.config.get()['pmm']['mode'];app.configure({'pmm281':{'mode':'compatibility'}});assert app.config.get()['pmm']['mode']==mode
        finally:app.close()
        app=Runtime(data,ROOT)
        try:
            assert app.store.meta('pmm281_affect')==after;app.configure({'pmm281':{'mode':'full'}});app.engine.pmm_provider_factory=app.engine.provider_factory=Provider281
            replay=app.engine.turn(sid,'迁移后的合成事件',turn_context={'sources':['synthetic-upgrade-event']});assert app.store.meta('pmm281_affect')==after;assert replay['turn_id']==out['turn_id']
        finally:app.close()
        for label,pack in [('old',before['packs'][owner]),('new',newpack)]:
            fresh=Runtime(work/('import-'+label),ROOT)
            try:
                fresh.create_persona({'package':pack});assert fresh.engine.profile()['id']==owner
                assert fresh.engine.profile()['examples']==pack['profile']['examples'];assert fresh.engine.model.export()==pack['learning']['checkpoint']
                assert fresh.store.meta('pmm281_affect')['revision']==(0 if label=='old' else 1)
            finally:fresh.close()
        rollback=work/'rollback-data';shutil.copytree(backup,rollback,ignore=shutil.ignore_patterns('recovery_manifest.json','sqlite_snapshots'))
        rollback_code="""import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]);from persona.server import Runtime
from persona.common import VERSION
assert VERSION=='2.8';r=Runtime(sys.argv[2],Path(sys.argv[1]));old=json.loads(Path(sys.argv[3]).read_text())
try:
 for ident,s in old['snapshots'].items():
  st,c,e,_=r.context(ident);m={v['key']:json.loads(v['value']) for v in s['tables']['meta']};assert e.model.export()==m['pmm_checkpoint'];assert st.meta('pmm28_models')==m['pmm28_models'];assert st.snapshot()['tables']['messages']==s['tables']['messages']
finally:r.close()
"""
        subprocess.run([sys.executable,'-c',rollback_code,str(old),str(rollback),str(expected)],cwd=work,env=env,check=True)
        print(json.dumps({'from':'2.8','to':'2.8.1','verified_archive':archive_sha,'synthetic_databases':2,'real_user_database_used':False,'old_and_new_persona_packs_imported':True,'automatic_backup_hashes_verified':True,'actual_archived_rollback_read':True,'restart_and_duplicate_input':True,'subjects':check},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
