"""Execute archived 2.6 itself; synthetic trained subjects only."""
import argparse,json,os,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from upgrade_trait_affect_v230 import OLD_SCRIPT,metadata
from persona.server import Runtime
from persona.packages import validate_pack,export_continuity
from persona.registry import digest

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',default='final');parser.add_argument('--old-root',type=Path,required=True);args=parser.parse_args()
    script=OLD_SCRIPT.replace("assert VERSION in ('2.2.1','2.2.2','2.2.3')","assert VERSION=='2.6'")
    # The shared legacy fixture writes profile rows directly. Finalize its
    # derived language cache with the archived runtime, as its import API does.
    script=script.replace('        snapshots[ident]=r.snapshot();',"        from persona import pragmatics as pg\n        with st.lock,st.db:st.setmeta('pmm_pragmatics',pg.rebuild(st.meta('pmm_pragmatics'),profile['source_records']))\n        snapshots[ident]=r.snapshot();")
    with tempfile.TemporaryDirectory(prefix='huai-an-27-upgrade-') as tmp:
        base=Path(tmp);data=base/'旧训练资料';expected=base/'expected.json'
        subprocess.run([sys.executable,'-c',script,str(args.old_root.resolve()),str(data),str(expected)],check=True,env={**os.environ,'OPENBLAS_NUM_THREADS':'1'})
        before=json.loads(expected.read_text());r=Runtime(data,ROOT);checks=[];indices={}
        try:
            assert r.config.get()==before['config'] and r.subjects.catalog==before['catalog']
            for ident,snap in before['snapshots'].items():
                st,_,e,_=r.context(ident);after=st.snapshot();om=metadata(snap);nm=metadata(after)
                for table in ('sessions','messages','memories','relations'):assert after['tables'][table]==snap['tables'][table],table
                for key,value in om.items():assert nm[key]==value,key
                assert e.model.export()==om['pmm_checkpoint'];indices[ident]=e.evidence.state()
                model=e.model.fork();e.ingest_samples(model,st.meta('pmm_training_records'));model.fit(2);assert model.steps>e.model.steps
                validate_pack(export_continuity(e));checks.append({'checkpoint_sha256':digest(e.model.export()),'steps_before':e.model.steps,'steps_after':model.steps,'old_metadata_exact':True})
        finally:r.close()
        r=Runtime(data,ROOT)
        try:
            for ident,idx in indices.items():assert r.context(ident)[2].evidence.state()==idx
        finally:r.close()
        fresh=Runtime(base/'fresh',ROOT)
        try:
            ident=before['active'];snap=before['snapshots'][ident];fresh.create_persona({'name':'旧包迁移','package':before['packs'][ident]});assert fresh.engine.model.export()==metadata(snap)['pmm_checkpoint'];fresh.restore(snap);assert fresh.engine.model.export()==metadata(snap)['pmm_checkpoint'];assert fresh.engine.profile()==metadata(snap)['pmm_profile']
        finally:fresh.close()
        print(json.dumps({'from':'2.6','phase':args.phase,'to':__import__('persona.common',fromlist=['VERSION']).VERSION,'archived_runtime_executed':True,'subjects':2,'old_metadata_and_tables_unchanged':True,'new_evidence_index_only':True,'restart_idempotent':True,'old_package_import':True,'old_snapshot_restore':True,'continued_training':True,'production_database':False,'checks':checks},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
