"""Run archived 2.5.1 itself; check trained subjects, old exports and restored state."""
import argparse,json,os,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from upgrade_trait_affect_v230 import OLD_SCRIPT,metadata
from persona.server import Runtime
from persona.packages import validate_pack,export_continuity
from persona.registry import digest
from persona.common import VERSION

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--old-root',type=Path,required=True);args=parser.parse_args()
    script=OLD_SCRIPT.replace("assert VERSION in ('2.2.1','2.2.2','2.2.3')","assert VERSION=='2.5.1'")
    seed="""        from persona import pragmatics as pg
        pg_old=pg.rebuild(st.meta('pmm_pragmatics'),profile['source_records'])
        pg_old=pg.annotate(pg_old,pg_old['demonstrations'][0]['id'],'topic_progression_tendency',.4,'旧版人工标注')
        with st.lock,st.db:st.setmeta('pmm_pragmatics',pg_old)
"""
    script=script.replace('        snapshots[ident]=r.snapshot();',seed+'        snapshots[ident]=r.snapshot();')
    with tempfile.TemporaryDirectory(prefix='huai-an-de-upgrade-') as tmp:
        base=Path(tmp);data=base/'训练旧主体';original=base/'expected.json';checks=[]
        subprocess.run([sys.executable,'-c',script,str(args.old_root.resolve()),str(data),str(original)],check=True,env={**os.environ,'OPENBLAS_NUM_THREADS':'1'})
        before=json.loads(original.read_text());r=Runtime(data,ROOT);after={}
        try:
            assert r.config.get()==before['config'] and r.subjects.catalog==before['catalog'];assert Path(r.upgrade['backup']).exists()
            for ident,snap in before['snapshots'].items():
                st,_,e,_=r.context(ident);new=st.snapshot();om=metadata(snap);nm=metadata(new)
                for table in ('sessions','messages','memories','relations'):assert new['tables'][table]==snap['tables'][table],table
                for key,value in om.items():
                    if key!='pmm_pragmatics':assert nm[key]==value,key
                old=om['pmm_pragmatics'];p=nm['pmm_pragmatics'];assert old['annotations']==p['annotations'];assert old['observed_ai']==p['observed_ai'];assert old['human_feedback']==p['human_feedback'];assert p['lexical_demonstrations'][0]['source_event_ids']==old['demonstrations'][0]['source_event_ids'];assert p['version']==old['version']+1
                assert e.model.export()==om['pmm_checkpoint'];model=e.model.fork();e.ingest_samples(model,st.meta('pmm_training_records'));model.fit(2);assert model.steps>e.model.steps;assert {'old-trained-style','old-pending'}.issubset({s['id'] for s in model.samples});validate_pack(export_continuity(e))
                checks.append({'checkpoint_sha256':digest(om['pmm_checkpoint']),'steps_before':e.model.steps,'steps_after':model.steps,'examples':len(om['pmm_profile']['examples']),'memories':len(new['tables']['memories']),'old_language_version':old['version'],'new_language_version':p['version']});after[ident]=p
        finally:r.close()
        r=Runtime(data,ROOT)
        try:
            assert r.upgrade['kind']=='existing'
            for ident,p in after.items():assert r.context(ident)[0].meta('pmm_pragmatics')==p
        finally:r.close()
        fresh=Runtime(base/'fresh',ROOT)
        try:
            ident=before['active'];snap=before['snapshots'][ident];fresh.create_persona({'name':'旧包迁移','package':before['packs'][ident]});assert fresh.engine.model.export()==metadata(snap)['pmm_checkpoint'];assert fresh.store.meta('pmm_pragmatics')['annotations']==after[ident]['annotations'];fresh.restore(snap);assert fresh.engine.model.export()==metadata(snap)['pmm_checkpoint'];assert fresh.store.meta('pmm_profile')==metadata(snap)['pmm_profile'];assert len(fresh.store.rows('SELECT * FROM messages'))==4
        finally:fresh.close()
        print(json.dumps({'from':'2.5.1','to':VERSION,'old_runtime_executed':True,'subjects':2,'tables_config_weights_original_samples_unchanged':True,'old_package_import':True,'old_snapshot_restore':True,'restart_idempotent':True,'continued_training':True,'language_annotation_evidence_preserved':True,'production_database':False,'checks':checks},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
