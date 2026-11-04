"""Explicit, broad local erasure. Never invoked by an LLM memory operation."""
import copy, json, os, re
from pathlib import Path
from .common import uid, now, atomic_json
from .storage import BASE_STATE
from .psychology import empty_profile
from .registry import ensure_profile
from .pmm_interface import create_pmm

def upgrade_copies(engine):
    """Plan removal of this identity's automatic copies, never another identity's DB."""
    root=Path(getattr(engine.config,'shared_root',engine.store.directory))
    identity=engine.profile()['id'];files=[];updates=[]
    def descendants(path):
        if path.is_symlink():raise ValueError('备份包含符号链接，停止删除；请先检查备份路径')
        if path.is_file():return [path]
        found=[]
        if path.exists():
            for directory,dirs,names in os.walk(path,followlinks=False):
                for name in dirs+names:
                    p=Path(directory)/name
                    if p.is_symlink():raise ValueError('备份包含符号链接，停止删除；请先检查备份路径')
                found.extend(Path(directory)/name for name in names)
        return found
    def core_copies(path):
        descendants(path) # Reject links before opening catalogs or removing files.
        catalog=path/'index.json'
        if not catalog.exists():return
        rows=json.loads(catalog.read_text('utf-8'))
        if not isinstance(rows,list) or any(not isinstance(r,dict) or not re.fullmatch('[a-f0-9]{32}',str(r.get('id',''))) for r in rows):raise ValueError('备份共享核心目录损坏，停止删除')
        removed=[r for r in rows if r.get('source_identity')==identity]
        files.extend(path/(r['id']+'.json') for r in removed)
        if removed:updates.append((catalog,[r for r in rows if r not in removed]))
    backup_root=root/'backups'
    if backup_root.is_symlink():raise ValueError('备份目录是符号链接，停止删除')
    for backup in sorted(backup_root.glob('pre-*')):
        if not backup.is_dir():continue
        descendants(backup)
        manifest=backup/'recovery_manifest.json';catalog=backup/'personas.json'
        report=json.loads(manifest.read_text('utf-8')) if manifest.exists() else {}
        mapping=report.get('before',{}).get('catalog') or (json.loads(catalog.read_text('utf-8')) if catalog.exists() else {})
        if not isinstance(mapping,dict) or not re.fullmatch('[a-f0-9]{32}',str(mapping.get('default',''))):
            raise ValueError('升级备份缺少可确认的人格归属，停止删除；请检查恢复清单')
        if identity not in [r.get('id') for r in mapping.get('items',[]) if isinstance(r,dict)]:continue
        relative=Path('.') if mapping['default']==identity else Path('subjects')/identity
        for base in (backup/relative,backup/'sqlite_snapshots'/relative):
            # The root of an upgrade includes other subjects and shared files.
            for stem in ('subject.sqlite3','execution.sqlite3'):
                for suffix in ('','-wal','-shm'):files.extend(descendants(base/(stem+suffix)))
            files.extend(descendants(base/'versions'))
            for old in (base/'backups').glob('before_restore_*.json'):files.extend(descendants(old))
        core_copies(backup/'shared_cores')
        if manifest.exists():
            report['status']='partially_erased';report['erased_personas']=sorted(set(report.get('erased_personas',[])+[identity]))
            report['erasure_note']='所列人格的自动数据库/执行快照/版本副本已删除；不得将此备份作为完整恢复点。其他人格副本保留。'
            updates.append((manifest,report))
    return files,updates

def erase_preview(engine,scope):
    if not isinstance(scope,str) or scope=='self' or not scope or len(scope)>200:raise ValueError('请选择具体会话范围；不支持用此入口删除 self')
    st=engine.store
    return {'scope':scope,'messages':st.rows('SELECT COUNT(*) n FROM messages WHERE session_id IN (SELECT id FROM sessions WHERE scope=?)',(scope,))[0]['n'],
            'memories':st.rows('SELECT COUNT(*) n FROM memories WHERE scope=?',(scope,))[0]['n'],
            'impact':'删除该范围的本地原始对话、QQ 收件记录、记忆与旁观记录；为移除已混入的学习影响，重置当前人格全部学习状态、对象关系、训练参数和操作历史，并删除当前人格的本地权重/人格版本、恢复备份以及历次升级备份中的该人格完整数据库和执行快照。保留其他人格的副本；这些升级备份不再能作为完整恢复点。保留手工角色设定、无证据引用的手工边界，以及其他范围的在线原始对话和记忆。',
            'limits':'已手动导出的文件、其他人格已复制的参数、外部模型服务与 QQ 平台记录不在此操作范围内。',
            'confirmation':'ERASE:'+scope}

def erase_scope(engine,scope,confirmation):
    preview=erase_preview(engine,scope)
    if confirmation!=preview['confirmation']:raise ValueError('删除确认内容不匹配，未删除数据')
    e=engine;st=e.store
    with e.lock,st.lock:
        if any(x.status()['running'] for x in (e.consolidation,e.memory_lifecycle,e.social,e.learning)):raise ValueError('请等待后台任务完成后删除')
        from .boundaries import empty
        retained_boundaries=empty();retained_boundaries['boundaries']=[{**copy.deepcopy(b),'evidence_ids':[],'counterevidence_ids':[],'current_activation':0} for b in e.boundaries.state()['boundaries'] if b['origin']=='owner_seed' and b['scope']!=scope]
        old=e.profile();identity=st.meta('identity');cfg=e.config.get()
        p=empty_profile(old['id'],old['name'],old['seed']);p['character']=copy.deepcopy(old.get('character',{}))
        p['boundaries']=[copy.deepcopy(b) for b in old['boundaries'] if b.get('source')=='owner_rule' and not b.get('evidence')]
        p=ensure_profile(p)
        # Owner settings are explicit priors, not learned traces of the erased scope.
        from .traits import edit_disposition
        for key,field in {**old['psychology']['features'],**old['trait_profile']['dispositions']}.items():
            if field.get('source_type')=='owner_seed' and field.get('estimate') is not None:
                p=edit_disposition(p,{'feature_id':key,'estimate':field['estimate'],'expected_version':p['trait_profile']['version'],'timeframe':'generally' if key.startswith('panas.') else 'habitual'})
        candidate=create_pmm(cfg,None,old['id'])
        remaining={m['id'] for m in st.memories(all_status=True) if m['scope']!=scope}
        traces={k:v for k,v in (st.meta('memory_traces') or {}).items() if k in remaining}
        codes={k:v for k,v in (st.meta('pmm_memory_codes') or {}).items() if k in remaining}
        observations={k:v for k,v in (st.meta('group_observations') or {}).items() if k!=scope}
        buffers={k:v for k,v in (st.meta('turn_buffers') or {}).items() if v['scope']!=scope}
        inbox=[]
        for row in st.rows('SELECT id,payload FROM inbox'):
            ev=json.loads(row['payload']);target=('group:qq:'+str(ev.get('group_id'))) if ev.get('message_type')=='group' else 'private:qq:'+str(ev.get('user_id'))
            if target==scope:inbox.append(row['id'])
        # Plan all automatic copies before touching live data. Configuration-only copies remain.
        files,backup_updates=upgrade_copies(e)
        for directory in (st.directory/'versions',):
            if directory.exists():files.extend(f for f in directory.rglob('*') if f.is_file())
        backup=st.directory/'backups'
        if backup.exists():files.extend(backup.glob('before_restore_*.json'))
        # Cores trained from this persona can retain its samples' influence.
        cores=e.core_files();catalog=cores.list();removed=[r for r in catalog if r.get('source_identity')==old['id']]
        files.extend(cores.path/(r['id']+'.json') for r in removed)
        # Stop before modifying the DB if a known auto-copy cannot be removed.
        for f in files:
            if f.exists():f.unlink()
        for path,value in backup_updates:atomic_json(path,value)
        if catalog:atomic_json(cores.catalog,[r for r in catalog if r not in removed])
        with st.db:
            st.db.execute('PRAGMA secure_delete=ON')
            st.db.execute('DELETE FROM messages WHERE session_id IN (SELECT id FROM sessions WHERE scope=?)',(scope,))
            st.db.execute('DELETE FROM sessions WHERE scope=?',(scope,));st.db.execute('DELETE FROM memories WHERE scope=?',(scope,))
            st.db.executemany('DELETE FROM inbox WHERE id=?',[(i,) for i in inbox])
            for table in ('events','relations','meta'):st.db.execute('DELETE FROM '+table)
            for key,value in {'identity':identity,'boundary_model':retained_boundaries,'claim_memory':[],'state':copy.deepcopy(BASE_STATE),'pmm_profile':p,'pmm_checkpoint':candidate.export(),'pmm_interlocutors':{},'pmm_dyads':{},'pmm_training_records':[],
                              'pmm_memory_codes':codes,'memory_traces':traces,'memory_pending':[],'consolidation_queue':[],'consolidation_generation':uid(),'group_observations':observations,'turn_buffers':buffers}.items():st.setmeta(key,value)
            st.event('scope_erased',{'scope':scope,'at':now(),'learning_reset':True,'deleted_auto_files':len(files)})
        e.journal.erase()
        e.model=candidate
        # Logical deletion plus SQLite free-page/WAL cleanup, not a forensic disk wipe.
        st.db.execute('PRAGMA wal_checkpoint(TRUNCATE)');st.db.execute('VACUUM');st.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        return {'ok':True,**preview,'deleted_auto_files':len(files),'learning_reset':True}
