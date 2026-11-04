"""Exercise an actual archived runtime, trained weights, restart and old exports.

python tests/upgrade_trait_affect_v230.py --old-root /path/to/v221
Only temporary synthetic data is used. No cloud API or QQ connection is opened.
"""
import argparse,copy,json,os,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from persona.server import Runtime
from persona.common import VERSION
from persona.registry import digest,pack_features
from persona.packages import export_continuity,validate_pack

OLD_SCRIPT=r'''
import json,sys
from pathlib import Path
import numpy as np
old=Path(sys.argv[1]);sys.path.insert(0,str(old))
from persona.server import Runtime
from persona.common import VERSION,now
from persona.psychology import apply_distillation
from persona.registry_pmm import DIM
from persona.registry import CONTRACT,ORDER
from persona.packages import export_continuity
assert VERSION in ('2.2.1','2.2.2','2.2.3')
r=Runtime(sys.argv[2],old)
try:
    first=r.store.meta('identity')['id']
    r.subjects.edit_character(r.engine,{'name':'旧版合成主体','initial_personality':'慢热','seed':'已有设定不重建'})
    r.configure({'api_key':'SYNTHETIC_GENERAL_KEY','model':'fixture-general','pmm':{'api':{'api_key':'SYNTHETIC_PMM_KEY','model':'fixture-pmm','thinking_mode':'low'}},'qq':{'self_id':'9988'}})
    for scope in ('private:qq:123','group:qq:456'):
        sid=r.store.session('qq:123',scope,'合成历史')
        with r.store.lock,r.store.db:
            r.store.db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)',(sid+'u',sid,'user','合成原文',now(),'old-turn'))
            r.store.db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)',(sid+'a',sid,'assistant','合成回复',now(),'old-turn'))
    r.engine.boundaries.edit({'topic':'已有明确边界','domain':'autonomy'})
    r.create_persona({'name':'第二个旧主体'});second=r.store.meta('identity')['id']
    packs={};snapshots={}
    for index,ident in enumerate((first,second)):
        r.switch(ident);r.configure({'pmm':{'mode':'learned'}});e=r.engine;st=r.store
        record={'id':'old-source','speaker':'target','text':'旧版训练用的真实形状合成例子','context':'合成上下文','source':'imported','scope':'private:qq:123','timestamp':now()-86400,'event_id':'old-event','batch_id':'old-batch'}
        updates=[{'feature_id':k,'estimate':v,'confidence':.7,'evidence':[{'record_id':record['id'],'quote':record['text']}]} for k,v in [('hexaco.e.anxiety',.7),('affect.appraisal.novelty',.8),('affect.regulation.cognitive_change',.6),('affect.label.anger',.5)]]
        profile,_=apply_distillation(e.profile(),{'construct_updates':updates,'examples':[{'record_id':record['id'],'action':'reply','function':'回应'}]},[record],'imported')
        x=e.input_vector(record['text'],{},profile);target=[None]*len(ORDER);target[ORDER.index('hexaco.e.anxiety')]=.7
        e.model.add('old-trained-style',x,linguistic=[.2,.3,.4,.5],psychology_target=target,source='imported_style');e.model.fit(3)
        pending=e.queue_sample([],'old-pending',x,linguistic=[.3,.2,.5,.4],source='human_feedback',group_id='old-group')
        assert e.model.steps>0
        with st.lock,st.db:
            st.setmeta('pmm_profile',profile);st.setmeta('pmm_checkpoint',e.model.export());st.setmeta('pmm_training_records',pending)
            st.setmeta('pmm_activity',{'emotion':{'valence':-.5,'arousal':.7,'stress':.6,'engagement':.4},'mood':{'valence':-.2,'arousal':.4,'stress':.2,'engagement':.5},'updated_at':now()-100 if index==0 else 0})
            st.setmeta('pmm_memory_codes',{'old-memory':{'social':.7,'hostility':.1}})
            st.db.execute('INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('old-memory','合成偏好','preference','private:qq:123','qq:123',.7,.6,'active','old-turn','原文',now(),now(),1,'合成'))
            st.db.execute('INSERT INTO relations VALUES (?,?,?,?)',('qq:123','合成对象',json.dumps({'trust':.7,'affection':.4,'familiarity':.2,'interactions':5}),now()))
        snapshots[ident]=r.snapshot();packs[ident]=export_continuity(e)
    r.switch(first)
    result={'version':VERSION,'active':first,'snapshots':snapshots,'packs':packs,'config':r.config.get(),'catalog':r.subjects.catalog}
finally:r.close()
Path(sys.argv[3]).write_text(json.dumps(result,ensure_ascii=False))
'''

def metadata(snapshot):return {v['key']:json.loads(v['value']) for v in snapshot['tables']['meta']}
def original_profile(profile):return {k:v for k,v in profile.items() if k!='trait_profile'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--old-root',type=Path,required=True);args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='trait-affect-upgrade-') as temporary:
        base=Path(temporary);data=base/'data';expected=base/'expected.json'
        subprocess.run([sys.executable,'-c',OLD_SCRIPT,str(args.old_root.resolve()),str(data),str(expected)],check=True,env={**os.environ,'OPENBLAS_NUM_THREADS':'1'})
        before=json.loads(expected.read_text());r=Runtime(data,ROOT);states={};checks=[]
        try:
            assert r.subjects.catalog==before['catalog'];assert r.config.get()==before['config']
            for ident,old in before['snapshots'].items():
                store,_,engine,_=r.context(ident);new=store.snapshot();om=metadata(old);nm=metadata(new)
                for table in ('sessions','messages','memories','relations'):assert old['tables'][table]==new['tables'][table],table
                assert original_profile(nm['pmm_profile'])==om['pmm_profile'],'legacy profile fields'
                assert om['pmm_profile']['examples'],'fixture contains a real stored language example'
                ov,mask=pack_features(om['pmm_profile']['psychology']);nv,nmask=pack_features(nm['pmm_profile']['psychology'])
                assert ov==nv and mask==nmask,'93 estimates and unknown mask'
                for key in ('identity','state','pmm_checkpoint','pmm_training_records','pmm_memory_codes','pmm_activity','pmm_interlocutors','pmm_dyads','boundary_model'):
                    if key in om:assert nm[key]==om[key],key
                assert engine.model.export()==om['pmm_checkpoint']
                a=nm['pmm_affect'];states[ident]=a
                known=om['pmm_activity']['updated_at']>0
                assert a['migration']['legacy_timestamp_known']==known
                assert a['emotion']['source_type']==('legacy_engineering' if known else 'unknown')
                if not known:assert a['emotion']['valence'] is None
                assert a['appraisals'][0]['legacy_record']==om['pmm_profile']['psychology']['features']['affect.appraisal.novelty']
                assert a['regulation_actions'][0]['applied'] is False
                validate_pack(export_continuity(engine))
                checks.append({'identity':ident,'checkpoint_sha256':digest(nm['pmm_checkpoint']),'pending_sha256':digest(nm['pmm_training_records']),'trained_steps':engine.model.steps,'legacy_timestamp_known':known})
            assert json.loads((data/'upgrade_state.json').read_text())['status']=='complete'
            backups=len(r.upgrade['sqlite_snapshots'])
        finally:r.close()
        r=Runtime(data,ROOT)
        try:
            assert r.upgrade['kind']=='existing'
            for ident,a in states.items():assert r.context(ident)[0].meta('pmm_affect')==a
            e=r.engine;original=e.model.export();candidate=e.model.fork();e.ingest_samples(candidate,r.store.meta('pmm_training_records'));candidate.fit(2)
            assert candidate.steps>original['steps'];assert {'old-trained-style','old-pending'}.issubset({s['id'] for s in candidate.samples})
        finally:r.close()
        # Actual old export and complete snapshot are accepted by a clean new build.
        fresh=Runtime(base/'imported',ROOT)
        try:
            fresh.create_persona({'name':'导入旧连续包','package':before['packs'][before['active']]})
            assert fresh.engine.profile()['id']==before['active']
            assert fresh.engine.model.export()==metadata(before['snapshots'][before['active']])['pmm_checkpoint']
            assert len(fresh.store.memories(all_status=True))==1
            fresh.restore(before['snapshots'][before['active']])
            assert len(fresh.store.rows('SELECT * FROM messages'))==4
            assert fresh.engine.model.export()==metadata(before['snapshots'][before['active']])['pmm_checkpoint']
        finally:fresh.close()
        print(json.dumps({'from':before['version'],'to':VERSION,'fixture':'archived runtime; synthetic trained data','subjects':2,'same_identity_catalog_config':True,'old_93_values_unknown_masks_and_evidence_unchanged':True,'checkpoint_pending_memory_codes_and_rows_unchanged':True,'old_examples_preserved':True,'continued_training_passed':True,'old_package_import_passed':True,'old_full_snapshot_restore_passed':True,'second_launch_idempotent':True,'legacy_missing_timestamp_stays_unknown':True,'historical_appraisals_and_operations_preserved':True,'standalone_sqlite_snapshots':backups,'real_user_database_used':False,'checks':checks},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
