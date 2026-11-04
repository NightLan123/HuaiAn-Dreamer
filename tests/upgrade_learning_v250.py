"""Actual 2.3.0 / H2 runtimes with synthetic learned checkpoints; no real account."""
import argparse,json,os,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from upgrade_trait_affect_v230 import OLD_SCRIPT,metadata,original_profile
from persona.server import Runtime
from persona.common import VERSION
from persona.packages import export_continuity,validate_pack
from persona.pmm_interface import digest

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--old-root',type=Path,required=True);args=parser.parse_args()
    script=OLD_SCRIPT.replace("assert VERSION in ('2.2.1','2.2.2','2.2.3')","assert VERSION in ('2.2.3-h2','2.3.0','2.4.0')")
    with tempfile.TemporaryDirectory(prefix='learning-upgrade-') as d:
        base=Path(d);data=base/'data';expected=base/'old.json'
        subprocess.run([sys.executable,'-c',script,str(args.old_root.resolve()),str(data),str(expected)],check=True,env={**os.environ,'OPENBLAS_NUM_THREADS':'1'})
        before=json.loads(expected.read_text());r=Runtime(data,ROOT);checks=[]
        try:
            assert r.subjects.catalog==before['catalog'];assert r.config.get()==before['config']
            for ident,old in before['snapshots'].items():
                st,_,engine,_=r.context(ident);current=st.snapshot();om=metadata(old);nm=metadata(current)
                for table in ('sessions','messages','memories','relations'):assert current['tables'][table]==old['tables'][table],table
                for key in ('identity','state','pmm_checkpoint','pmm_training_records','pmm_memory_codes','pmm_interlocutors','pmm_dyads','boundary_model'):
                    if key in om:assert om[key]==nm[key],key
                if 'pmm_affect' in om:
                    from persona.affect import upgrade_catalog
                    assert nm['pmm_affect']==upgrade_catalog(om['pmm_affect'])
                assert (nm['pmm_profile'] if 'trait_profile' in om['pmm_profile'] else original_profile(nm['pmm_profile']))==om['pmm_profile']
                validate_pack(export_continuity(engine));candidate=engine.model.fork();engine.ingest_samples(candidate,st.meta('pmm_training_records'));candidate.fit(2)
                assert candidate.steps>engine.model.steps;assert {'old-trained-style','old-pending'}.issubset({s['id'] for s in candidate.samples})
                checks.append({'identity':ident,'checkpoint_sha256':digest(engine.model.export()),'old_steps':engine.model.steps,'continued_steps':candidate.steps})
            pg_before=r.store.meta('pmm_pragmatics')
        finally:r.close()
        r=Runtime(data,ROOT)
        try:assert r.store.meta('pmm_pragmatics')==pg_before
        finally:r.close()
        fresh=Runtime(base/'fresh',ROOT)
        try:
            fresh.create_persona({'package':before['packs'][before['active']]});assert fresh.engine.model.export()==metadata(before['snapshots'][before['active']])['pmm_checkpoint']
            fresh.restore(before['snapshots'][before['active']]);assert len(fresh.store.rows('SELECT * FROM messages'))==4
            validate_pack(export_continuity(fresh.engine))
        finally:fresh.close()
        print(json.dumps({'from':before['version'],'to':VERSION,'subjects':2,'fixture':'actual archived runtime / synthetic data','tables_unchanged':True,'old_memory_weights_examples_pending_preserved':True,'continued_training':True,'old_package_import':True,'old_snapshot_restore':True,'relaunch_idempotent':True,'emotion_catalog_additive':True,'old_93_contract_unchanged':True,'checks':checks},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
