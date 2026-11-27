"""Read-before-write data discovery, integrity checks and upgrade snapshots."""
from __future__ import annotations
import datetime,hashlib,json,os,re,shutil,sqlite3,threading
from pathlib import Path
from .common import VERSION,SCHEMA,atomic_json,uid

class DataGuardError(RuntimeError):
    pass

def inspect_database(path):
    path=Path(path).resolve()
    if not path.is_file():raise DataGuardError(f'原主体数据库不存在：{path}；已停止，未创建空库。')
    try:
        db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
        try:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise DataGuardError('数据库完整性检查失败，已停止写入：'+str(path))
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            required={'meta','sessions','messages','memories','events','relations'}
            if not required<=tables:raise DataGuardError('旧库缺少必要表，不能当作新主体初始化：'+str(path))
            meta={k:json.loads(v) for k,v in db.execute('SELECT key,value FROM meta')}
            identity=meta.get('identity',{})
            if not isinstance(identity,dict) or not re.fullmatch('[a-f0-9]{32}',str(identity.get('id',''))) or identity.get('schema')!=SCHEMA:raise DataGuardError('旧库主体标识或 schema 不兼容：'+str(path))
            if not isinstance(meta.get('state'),dict):raise DataGuardError('旧库心理状态缺失，拒绝重新初始化：'+str(path))
            profile=meta.get('pmm_profile')
            if 'pmm_profile' in meta and (not isinstance(profile,dict) or profile.get('id')!=identity['id']):raise DataGuardError('人格缺失或与数据库主体 ID 不一致：'+str(path))
            orphans=db.execute('SELECT COUNT(*) FROM messages m LEFT JOIN sessions s ON m.session_id=s.id WHERE s.id IS NULL').fetchone()[0]
            if orphans:raise DataGuardError('存在无法关联会话的消息，保留原库并停止迁移：'+str(path))
            counts={t:db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in sorted(required)}
            # Compare content, not just row counts; no plaintext enters the report.
            fingerprints={}
            for table in ('sessions','messages','memories','relations'):
                digest=hashlib.sha256()
                for record in db.execute('SELECT * FROM '+table+' ORDER BY id'):
                    digest.update(json.dumps(record,ensure_ascii=False,separators=(',',':')).encode('utf-8'));digest.update(b'\n')
                fingerprints[table]=digest.hexdigest()
            meta_sha={k:hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest() for k,v in meta.items()}
            protected={}
            for key in ('pmm_profile','pmm_checkpoint','pmm_training_records','pmm_memory_codes','pmm_dyads'):
                if key not in meta:continue
                value=json.loads(json.dumps(meta[key]))
                if key=='pmm_profile':value.pop('trait_profile',None)
                protected[key]=hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
            return {'preserved_payload_sha256':protected,'checkpoint_format':(meta.get('pmm_checkpoint') or {}).get('format'),'id':identity['id'],'name':(profile or {}).get('name','未央'),'schema':identity['schema'],'counts':counts,'content_sha256':fingerprints,'meta_sha256':meta_sha,'orphan_messages':orphans,'meta':meta,'path':path}
        finally:db.close()
    except (sqlite3.Error,ValueError,TypeError) as exc:raise DataGuardError('旧库读取失败（'+type(exc).__name__+'），未重建：'+str(path)) from exc

def catalog_for(root):
    """Reconstruct only a complete, unambiguous catalog from existing databases."""
    root=Path(root);path=root/'personas.json';database=root/'subject.sqlite3'
    if not path.exists():
        if not database.exists():
            if any((root/n).exists() for n in ('config.json','subjects','subject.sqlite3-wal','subject.sqlite3-shm','connection_migration_v212.json','upgrade_state.json')):raise DataGuardError('检测到旧数据痕迹但主库缺失，停止空主体初始化：'+str(root))
            return None,False
        first=inspect_database(database);items=[{'id':first['id'],'name':first['name']}]
        for p in sorted((root/'subjects').glob('*')):
            if p.is_dir():
                row=inspect_database(p/'subject.sqlite3')
                if p.name!=row['id']:raise DataGuardError('子目录与人格 ID 不一致：'+str(p))
                items.append({'id':row['id'],'name':row['name']})
        if len({x['id'] for x in items})!=len(items):raise DataGuardError('旧库存在重复人格 ID，不能自动合并。')
        return {'default':first['id'],'active':first['id'],'items':items},True
    try:catalog=json.loads(path.read_text('utf-8'))
    except (ValueError,OSError) as exc:raise DataGuardError('人格目录无法解析，停止写入并保留原文件：'+str(path)) from exc
    if not isinstance(catalog,dict) or not isinstance(catalog.get('items'),list) or not catalog['items']:raise DataGuardError('人格目录为空或格式错误，拒绝重建。')
    ids=[i.get('id') if isinstance(i,dict) else None for i in catalog['items']]
    if any(not isinstance(i,str) or not re.fullmatch('[a-f0-9]{32}',i) for i in ids) or len(set(ids))!=len(ids) or catalog.get('active') not in ids or catalog.get('default') not in ids:raise DataGuardError('人格目录标识、默认主体或当前主体无效。')
    for identifier in ids:
        directory=root if identifier==catalog['default'] else root/'subjects'/identifier
        if inspect_database(directory/'subject.sqlite3')['id']!=identifier:raise DataGuardError('人格目录与数据库 ID 不一致：'+str(directory))
    return catalog,False

def inspect_root(root):
    catalog,reconstructed=catalog_for(root)
    if catalog is None:return None
    records=[]
    for item in catalog['items']:
        directory=Path(root) if item['id']==catalog['default'] else Path(root)/'subjects'/item['id']
        row=inspect_database(directory/'subject.sqlite3')
        # Validate legacy/new model representations without changing the live database.
        from .psychology import validate_profile
        from .registry import ensure_profile
        from .pmm_interface import load_numeric
        from .boundaries import validate_state,validate_claims
        if row['meta'].get('pmm_profile'):validate_profile(ensure_profile(row['meta']['pmm_profile']))
        for other in (row['meta'].get('pmm_interlocutors') or {}).values():validate_profile(ensure_profile(other,'model_of_other'))
        if 'pmm_checkpoint' in row['meta']:
            checkpoint=row['meta']['pmm_checkpoint']
            if not isinstance(checkpoint,dict) or checkpoint.get('format') not in ('pmm/3','learned-pmm/2','learned-pmm/2.1'):raise DataGuardError('已有数值权重为空或格式无效，停止初始化：'+str(directory))
            try:load_numeric(checkpoint,row['id'])
            except (ValueError,KeyError,TypeError) as exc:raise DataGuardError('已有数值权重校验失败，停止初始化：'+str(directory)) from exc
        from .affect import validate as validate_affect
        validate_affect(row['meta'].get('pmm_affect'),row['id'])
        from .affect_runtime import validate_metadata as validate_affect_v2
        validate_affect_v2(row['meta'])
        from .expression_drive import validate_metadata as validate_expression_drive
        validate_expression_drive(row['meta'])
        validate_state(row['meta'].get('boundary_model'));validate_claims(row['meta'].get('claim_memory'))
        if (directory/'config.json').exists():
            from .common import Config
            probe=object.__new__(Config);probe.path=directory/'config.json';probe.lock=threading.RLock();probe.get()
            row['config_sha256']=hashlib.sha256(probe.path.read_bytes()).hexdigest()
        records.append({k:v for k,v in row.items() if k not in ('meta','path')})
    return {'catalog':catalog,'catalog_reconstructed':reconstructed,'connection_migrated':(Path(root)/'connection_migration_v212.json').exists(),'subjects':records}

def prepare_upgrade(root):
    root=Path(root).resolve();before=inspect_root(root)
    if before is None:return {'kind':'new_install','version':VERSION,'subjects':[]}
    marker=root/'upgrade_state.json'
    if marker.exists():
        try:old=json.loads(marker.read_text('utf-8'))
        except (ValueError,OSError):raise DataGuardError('升级状态文件损坏，保留原数据并停止写入。')
        if old.get('version')==VERSION and old.get('status')=='complete' and not before['catalog_reconstructed']:return {'kind':'existing','version':VERSION,'subjects':before['subjects']}
    stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uid()[:8]
    backup=root/'backups'/('pre-'+VERSION+'-'+stamp);backup.mkdir(parents=True,exist_ok=False)
    for p in list(root.iterdir()):
        if p.name in ('backups','runtime.lock'):continue
        if p.is_symlink():raise DataGuardError('数据目录包含链接，停止自动迁移：'+str(p))
        if p.is_dir():shutil.copytree(p,backup/p.name,symlinks=True)
        else:shutil.copy2(p,backup/p.name)
    # Keep raw DB/WAL/SHM together, and produce separate standalone SQLite snapshots.
    # Never open a copied main DB beside stale WAL/SHM files.
    snapshots=[]
    for copied in list(backup.rglob('*.sqlite3')):
        if copied.is_symlink():raise DataGuardError('SQLite 数据库为链接，停止自动迁移：'+str(copied))
        relative=copied.relative_to(backup);snapshot=backup/'sqlite_snapshots'/relative
        snapshot.parent.mkdir(parents=True,exist_ok=True)
        source=sqlite3.connect((root/relative).as_uri()+'?mode=ro',uri=True)
        target=sqlite3.connect(snapshot)
        try:
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise DataGuardError('升级快照完整性检查失败，未开始迁移。')
        finally:target.close();source.close()
        snapshots.append({'path':str(Path('sqlite_snapshots')/relative),'sha256':hashlib.sha256(snapshot.read_bytes()).hexdigest()})
    report={'kind':'upgrade','version':VERSION,'status':'prepared','backup':str(backup),'before':before,'subjects':before['subjects']}
    report['sqlite_snapshots']=snapshots
    atomic_json(backup/'recovery_manifest.json',report)
    return report

def complete_upgrade(root,report):
    if report['kind'] not in ('upgrade','new_install'):return
    after=inspect_root(root)
    if report['kind']=='upgrade':
        old={r['id']:r for r in report['subjects']};new={r['id']:r for r in after['subjects']}
        if set(old)!=set(new):raise DataGuardError('升级前后主体集合不一致，停止启动；请查看自动备份。')
        for ident in old:
            for key,value in old[ident].get('preserved_payload_sha256',{}).items():
                if key=='pmm_checkpoint' and old[ident].get('checkpoint_format')!=new[ident].get('checkpoint_format'):continue
                if new[ident].get('preserved_payload_sha256',{}).get(key)!=value:raise DataGuardError('升级改变了已有学习数据，停止启动并保留备份：'+key)
            if report.get('before',{}).get('connection_migrated') and old[ident].get('config_sha256') and old[ident].get('config_sha256')!=new[ident].get('config_sha256'):raise DataGuardError('升级改变了已有连接配置，停止启动并保留备份')
            for table in ('sessions','messages','memories','relations'):
                if old[ident]['counts'][table]!=new[ident]['counts'][table]:raise DataGuardError('升级记录数发生异常变化，停止启动：'+table)
                if old[ident]['content_sha256'][table]!=new[ident]['content_sha256'][table]:raise DataGuardError('升级内容摘要发生异常变化，停止启动：'+table)
    atomic_json(Path(root)/'upgrade_state.json',{'version':VERSION,'status':'complete','before':report.get('subjects',[]),'after':after['subjects'],'backup':report.get('backup'),'catalog_reconstructed':report.get('before',{}).get('catalog_reconstructed',False)})

def has_data(path):return any((Path(path)/n).exists() for n in ('config.json','personas.json','subject.sqlite3','subjects','upgrade_state.json'))

def resolve_data_directory(requested=None,app_root=None,home=None,allow_new=False):
    home=Path(home or os.environ.get('HUAIAN_DATA_HOME') or Path.home());app_root=Path(app_root or Path.cwd());default=home/'.persona_dialogue'
    pointer=home/'.huai_an_dreamer'/'data-location.json';candidates=[]
    if pointer.exists() and requested is None:
        try:
            saved=Path(json.loads(pointer.read_text('utf-8'))['path']).expanduser().resolve()
            if not has_data(saved):raise DataGuardError('已登记的数据目录不可用，停止新建：'+str(saved))
            inspect_root(saved);return saved
        except (ValueError,KeyError,TypeError) as exc:raise DataGuardError('数据位置登记损坏，未创建新库。') from exc
    roots=[default,app_root,app_root/'data',app_root/'.persona_dialogue',app_root/'persona_data']
    for folder in sorted(app_root.parent.iterdir())[:200]:
        if folder.is_dir() and folder!=app_root and folder.name.lower().startswith(('huai','persona_dialogue')):roots.extend([folder,folder/'data',folder/'.persona_dialogue',folder/'persona_data'])
    for path in roots:
        if has_data(path):candidates.append(path.resolve())
    candidates=list(dict.fromkeys(candidates))
    if requested is not None:
        chosen=Path(requested).expanduser().resolve()
        if not has_data(chosen) and (candidates or chosen.exists() and any(chosen.iterdir())) and not allow_new:raise DataGuardError('指定目录没有原主体数据，已停止空库初始化。请核对数据目录：'+str(chosen))
    elif len(candidates)>1:
        raise DataGuardError('发现多处独立数据目录，不能猜测或合并。请明确指定 --data-dir：\n'+'\n'.join(map(str,candidates)))
    else:chosen=candidates[0] if candidates else default.resolve()
    if has_data(chosen):inspect_root(chosen)
    return chosen

def remember_data_directory(directory,home=None):
    atomic_json(Path(home or os.environ.get('HUAIAN_DATA_HOME') or Path.home())/'.huai_an_dreamer'/'data-location.json',{'path':str(Path(directory).resolve()),'version':VERSION})
