"""Run an archived v2.2.1 build, or v2.2.2 build, then open its synthetic data in the current version.

Usage: python tests/upgrade_v221_smoke.py --old-root /path/to/unmodified/v221
Requires the separately retained original source; never uses production data.
"""
import argparse,hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from persona.server import Runtime
from persona.common import VERSION

OLD_SCRIPT=r'''
import json,sys
from pathlib import Path
old=Path(sys.argv[1]);sys.path.insert(0,str(old))
from persona.server import Runtime
from persona.common import VERSION,now
assert VERSION in ('2.2.1','2.2.2')
r=Runtime(sys.argv[2],old)
try:
    first=r.store.meta('identity')['id']
    r.subjects.edit_character(r.engine,{'name':'v221 原主体','initial_personality':'合成的慢热设定','seed':'已有设定不重建'})
    r.configure({'api_key':'SYNTHETIC_GENERAL_KEY','model':'fixture-general','pmm':{'api':{'api_key':'SYNTHETIC_PMM_KEY','model':'fixture-pmm','thinking_mode':'low'}},'qq':{'self_id':'9988'}})
    for scope in ('private:qq:123','group:qq:456'):
        sid=r.store.session('qq:123',scope,'v221 合成历史')
        with r.store.lock,r.store.db:
            r.store.db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)',(sid+'u',sid,'user','v221 合成原文',now(),'old-turn'))
            r.store.db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)',(sid+'a',sid,'assistant','v221 合成回复',now(),'old-turn'))
    with r.store.lock,r.store.db:
        r.store.setmeta('pmm_checkpoint',r.engine.model.export())
        r.store.db.execute('INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('old-memory','v221 合成偏好','preference','private:qq:123','qq:123',.7,.6,'active','old-turn','原文',now(),now(),1,'合成'))
        r.store.db.execute('INSERT INTO relations VALUES (?,?,?,?)',('qq:123','合成对象',json.dumps({'trust':.7,'interactions':5}),now()))
    r.engine.boundaries.edit({'topic':'v221 已有边界','domain':'autonomy'})
    r.create_persona({'name':'v221 第二主体'});second=r.store.meta('identity')['id']
    with r.store.lock,r.store.db:r.store.setmeta('pmm_checkpoint',r.engine.model.export())
    r.switch(first)
    snapshots={item['id']:r.context(item['id'])[0].snapshot() for item in r.subjects.catalog['items']}
    result={'version':VERSION,'active':first,'snapshots':snapshots,'config':r.config.get(),'catalog':r.subjects.catalog}
finally:r.close()
Path(sys.argv[3]).write_text(json.dumps(result,ensure_ascii=False))
'''

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--old-root',type=Path,required=True);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='actual-v221-upgrade-') as temporary:
        data=Path(temporary)/'data';expected_file=Path(temporary)/'expected.json'
        subprocess.run([sys.executable,'-c',OLD_SCRIPT,str(args.old_root.resolve()),str(data),str(expected_file)],check=True,env={**os.environ,'OPENBLAS_NUM_THREADS':'1'})
        before=json.loads(expected_file.read_text());r=Runtime(data,ROOT)
        try:
            assert r.subjects.catalog==before['catalog'];assert r.config.get()==before['config']
            for ident,old in before['snapshots'].items():
                new=r.context(ident)[0].snapshot()
                for table in ('sessions','messages','memories','relations'):assert old['tables'][table]==new['tables'][table],table
                old_meta={v['key']:json.loads(v['value']) for v in old['tables']['meta']};new_meta={v['key']:json.loads(v['value']) for v in new['tables']['meta']}
                for key in ('identity','state','pmm_profile','pmm_checkpoint','pmm_interlocutors','boundary_model'):
                    if key in old_meta:assert new_meta[key]==old_meta[key],key
            manifest=json.loads((data/'upgrade_state.json').read_text())
            assert manifest['status']=='complete';assert manifest['before']==manifest['after']
            summary={'from':before['version'],'to':VERSION,'fixture':'synthetic records created by the archived '+before['version']+' runtime','subjects':len(before['snapshots']),'sessions':2,'messages':4,'memories':1,'relations':1,'same_identity_and_catalog':True,'profile_state_checkpoint_boundaries_unchanged':True,'general_pmm_thinking_qq_config_unchanged':True,'before_after_rows_and_hashes_equal':True,'standalone_sqlite_snapshots':len(r.upgrade['sqlite_snapshots']),'real_user_database_used':False}
        finally:r.close()
        second=Runtime(data,ROOT)
        try:assert second.upgrade['kind']=='existing';assert second.store.meta('identity')['id']==before['active'];summary['second_launch_idempotent']=True
        finally:second.close()
        print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
