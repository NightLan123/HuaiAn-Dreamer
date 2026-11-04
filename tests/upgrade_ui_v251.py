"""Upgrade an actual 2.5.0 runtime; trained synthetic identities and retired assets."""
import argparse,io,json,os,subprocess,sys,tempfile,zipfile,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from upgrade_trait_affect_v230 import OLD_SCRIPT,metadata
from persona.server import Runtime
from persona.media import legacy_media_archive
from persona.packages import validate_pack,export_continuity

def hashes(path):return {str(p.relative_to(path)):hashlib.sha256(p.read_bytes()).hexdigest() for p in path.rglob('*') if p.is_file()}
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--old-root',type=Path,required=True);args=parser.parse_args()
    old_script=OLD_SCRIPT.replace("assert VERSION in ('2.2.1','2.2.2','2.2.3')","assert VERSION=='2.5.0'")
    seed='''        from persona.media import Assets
        from PIL import Image
        import io,base64
        raw=io.BytesIO();Image.new('RGB',(8,8),'blue').save(raw,'PNG')
        r.configure({'media':{'send':True}})
        a=Assets(e).mutate({'name':'旧图片','base64':base64.b64encode(raw.getvalue()).decode(),'tags':['蓝色'],'scopes':['private:qq:123']})[-1]
        Assets(e).record_usage([a['id']],'private:qq:123','old-turn',55)
        Assets(e).preferences({'op':'feedback','turn_id':'old-turn','asset_id':a['id'],'rating':'like'})
        from persona import pragmatics as pg
        with st.lock,st.db:st.setmeta('pmm_pragmatics',pg.rebuild(st.meta('pmm_pragmatics'),profile['source_records']))
'''
    old_script=old_script.replace('        snapshots[ident]=r.snapshot();',seed+'        snapshots[ident]=r.snapshot();')
    with tempfile.TemporaryDirectory(prefix='ui-upgrade-') as d:
        base=Path(d);data=base/'旧版 人格';expected=base/'old.json'
        subprocess.run([sys.executable,'-c',old_script,str(args.old_root.resolve()),str(data),str(expected)],check=True,env={**os.environ,'OPENBLAS_NUM_THREADS':'1'})
        before=json.loads(expected.read_text());files={str(p.relative_to(data)):hashes(p) for p in data.rglob('media_assets')};runtime=Runtime(data,ROOT)
        try:
            assert runtime.config.get()==before['config'];assert runtime.subjects.catalog==before['catalog']
            backup=Path(runtime.upgrade['backup'])
            for path,original in files.items():assert hashes(data/path)==original;assert hashes(backup/path)==original
            for ident,snapshot in before['snapshots'].items():
                st,_,engine,_=runtime.context(ident);current=st.snapshot()
                for table in ('sessions','messages','memories','relations'):assert current['tables'][table]==snapshot['tables'][table],table
                old=metadata(snapshot);new=metadata(current)
                for key in old:assert new[key]==old[key],key
                assert engine.model.export()==old['pmm_checkpoint'];validate_pack(export_continuity(engine))
                with zipfile.ZipFile(io.BytesIO(legacy_media_archive(engine))) as archive:
                    for file in (st.directory/'media_assets').iterdir():assert archive.read('media_assets/'+file.name)==file.read_bytes()
                    history=json.loads(archive.read('history.json'));assert history['media_usage']==old['media_usage'];assert history['media_feedback']==old['media_feedback']
                candidate=engine.model.fork();engine.ingest_samples(candidate,st.meta('pmm_training_records'));candidate.fit(2);assert candidate.steps>engine.model.steps
        finally:runtime.close()
        runtime=Runtime(data,ROOT)
        try:
            assert runtime.upgrade['kind']=='existing'
            for path,original in files.items():assert hashes(data/path)==original
            runtime.restore(before['snapshots'][before['active']]);assert runtime.store.meta('media_usage')==metadata(before['snapshots'][before['active']])['media_usage']
            assert runtime.engine.model.export()==metadata(before['snapshots'][before['active']])['pmm_checkpoint']
        finally:runtime.close()
        print(json.dumps({'from':'2.5.0','to':'2.5.1','fixture':'two synthetic trained identities in actual archived runtime','all_old_metadata_unchanged':True,'old_tables_unchanged':True,'config_preserved':True,'asset_files_preserved':True,'automatic_backup_contains_original_assets':True,'read_only_asset_export_exact':True,'continued_training':True,'snapshot_restore':True,'restart_idempotent':True,'production_database':False},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
