"""Persona packages are separate from provider configuration and private conversation archives."""
from __future__ import annotations
import copy, json, re
from pathlib import Path
from .common import atomic_json, uid, now
from .storage import Store
from .psychology import empty_profile, validate_profile, style_stats
from .pmm import PMM
from .pmm_interface import load_numeric,create_pmm
from .registry import filter_evidence
from .packages import FORMAT,COMPATIBLE_FORMATS,export_continuity,validate_pack,apply_pack
from .versions import VersionFiles

class Subjects:
    def __init__(self,directory):
        self.root=Path(directory);self.root.mkdir(parents=True,exist_ok=True);self.path=self.root/'personas.json'
        from .data_guard import catalog_for
        recovered,reconstructed=catalog_for(self.root)
        if reconstructed:self.catalog=recovered;self.save()
        if self.path.exists():
            self.catalog=json.loads(self.path.read_text('utf8'))
            if not isinstance(self.catalog,dict):raise ValueError('人格目录无效')
            for item in self.catalog['items']:
                if not re.fullmatch('[0-9a-f]{32}',item['id']):raise ValueError('人格标识无效')
            if self.catalog['active'] not in [i['id'] for i in self.catalog['items']]:raise ValueError('当前人格不存在')
        else:
            st=Store(self.root);identity=st.meta('identity')['id'];p=st.meta('pmm_profile');st.close()
            self.catalog={'default':identity,'active':identity,'items':[{'id':identity,'name':p['name'] if p else '未央'}]};self.save()
    def save(self):atomic_json(self.path,self.catalog)
    def directory(self,identifier):
        if identifier not in [i['id'] for i in self.catalog['items']]:raise ValueError('没有这个人格')
        return self.root if identifier==self.catalog['default'] else self.root/'subjects'/identifier
    def active_store(self):return Store(self.directory(self.catalog['active']),create=False)
    def activate(self,identifier):
        self.directory(identifier);self.catalog['active']=identifier;self.save()
    def create(self,name,seed='',pack=None,character=None):
        if not isinstance(name,str) or not 1<=len(name.strip())<=60:raise ValueError('名称应为 1–60 个字符')
        if not isinstance(seed,str) or len(seed)>8000:raise ValueError('初始描述过长')
        if pack is not None:
            if not isinstance(pack,dict):raise ValueError('人格包应为 JSON 对象')
            if pack.get('format') not in ('persona-package/3',*COMPATIBLE_FORMATS):raise ValueError('请选择 v0.3 / v0.4 / v2.0 人格包；完整快照请使用恢复入口')
            p=validate_profile(pack.get('profile'))
            if pack['format'] in COMPATIBLE_FORMATS:
                validated=validate_pack(pack);checkpoint=validated[0]['pmm_checkpoint']
            else:
                if not isinstance(pack.get('pmm'),dict):raise ValueError('人格包缺少 PMM 参数')
                checkpoint=load_numeric(pack['pmm'],p['id']).export()
                from .boundaries import validate_state
                validate_state(pack.get('boundary_model'))
            identifier=p['id']
            if identifier in [i['id'] for i in self.catalog['items']]:raise ValueError('此人格已存在，请切换到该人格后使用“应用同主体人格包”；恢复全部历史可使用主体备份')
        else:identifier=uid();p=empty_profile(identifier,name.strip(),seed);checkpoint=PMM().export()
        if not pack and character is not None:p['character']=copy.deepcopy(character);validate_profile(p)
        directory=self.root/'subjects'/identifier
        if directory.exists():raise ValueError('此人格的数据目录已存在，请保留原数据并检查人格目录')
        st=Store(directory)
        try:
            with st.lock,st.db:
                identity=st.meta('identity');identity['id']=identifier;st.setmeta('identity',identity)
                st.setmeta('pmm_profile',p);st.setmeta('pmm_checkpoint',checkpoint)
                if pack and pack['format'] in COMPATIBLE_FORMATS:apply_pack(st,validated)
                elif pack and pack.get('boundary_model'):st.setmeta('boundary_model',pack['boundary_model'])
                st.event('persona_created',{'from_package':bool(pack),'profile_id':identifier})
            self.catalog['items'].append({'id':identifier,'name':p['name']});self.save()
        finally:st.close()
        return identifier
    def edit_character(self,engine,body):
        with engine.lock:
            before=engine.profile();p=copy.deepcopy(before)
            if body.get('expected_revision',p['revision'])!=p['revision']:raise ValueError('人格已更新，请重新打开角色设置后保存')
            for key in ('name','seed'):
                if key in body:
                    if not isinstance(body[key],str):raise ValueError('角色设置必须是文本')
                    p[key]=body[key].strip()
            character=copy.deepcopy(p.get('character',{'self_reference':'我','initial_personality':''}))
            for key in ('self_reference','initial_personality'):
                if key in body:character[key]=body[key]
            p['character']=character;validate_profile(p)
            if p==before:return {'ok':True,'changed':False,'profile':p}
            backup=self.save_revision(engine,'编辑角色设定前自动备份')
            p['revision']+=1;p['updated_at']=now()
            p['trait_profile']['version']+=1;p['trait_profile']['updated_at']=p['updated_at']
            old_catalog=copy.deepcopy(self.catalog)
            for item in self.catalog['items']:
                if item['id']==p['id']:item['name']=p['name']
            try:
                self.save()
                with engine.store.lock,engine.store.db:
                    engine.store.setmeta('pmm_profile',p)
                    engine.store.event('character_updated',{'revision':p['revision'],'checkpoint_id':backup['id'],
                        'before':{k:before.get(k) for k in ('name','seed','character')},'after':{k:p[k] for k in ('name','seed','character')}})
            except Exception:
                self.catalog=old_catalog;self.save();raise
            return {'ok':True,'changed':True,'profile':p,'checkpoint_id':backup['id']}

    def export_pack(self,engine,scope='continuity'):
        with engine.lock:
            if scope=='continuity':return export_continuity(engine)
            if scope=='template':return self._export_pack(engine)
            raise ValueError('导出范围无效')
    def _export_pack(self,engine):
        p=copy.deepcopy(engine.profile())
        # Portable target persona only: live dialogue and interlocutor models stay in full backups.
        p['source_records']=[r for r in p['source_records'] if r.get('source')=='imported' and not r.get('scope')]
        for record in p['source_records']:
            record['context']='';record.pop('context_record_id',None)
        ids={r['id'] for r in p['source_records']};human_ids={r['id'] for r in p['source_records'] if r.get('source')=='human'}
        p['observations']=[o for o in p['observations'] if o.get('source')=='imported']
        p['patterns']=[o for o in p['patterns'] if o.get('source')!='generated']
        for field in ('beliefs','patterns','boundaries','observations'):
            p[field]=[item for item in p[field] if all(e.get('record_id') in ids for e in item.get('evidence',[]))]
        p['examples']=[e for e in p['examples'] if e['record_id'] in ids]
        for example in p['examples']:
            example['input']=''
        p['style']=style_stats(p['source_records'])
        for domain in ('traits','values'):
            for v in p[domain].values():v['evidence']=[i for i in v['evidence'] if i in ids]
        p['psychology']=filter_evidence(p['psychology'],ids)
        from .traits import filter_template
        filter_template(p,ids)
        checkpoint=engine.model.export()
        # No live raw records; omit online replay vectors too. Learned parameters are portable.
        checkpoint['samples']=[s for s in checkpoint['samples'] if s.get('source')=='imported_style']
        checkpoint['metrics']={}
        from .boundaries import empty
        boundary=empty();boundary['boundaries']=[{**copy.deepcopy(b),'evidence_ids':[],'counterevidence_ids':[],'current_activation':0,'scope':'*','recipient':'*'} for b in engine.boundaries.state()['boundaries'] if b['origin']=='owner_seed' and b['status']=='confirmed' and b['scope']=='*' and b['recipient']=='*']
        return {'format':'persona-package/3','exported_at':now(),'profile':p,'pmm':checkpoint,'boundary_model':boundary,
                'contents':'包含人格与风格、启用边界、PMM 参数和明确导入的无会话范围证据（已移除相邻上下文）。不含人工校正文或带会话范围的原始样本、API 密钥、QQ 白名单、实时私聊记录或交谈对象模型。参数仍可能包含历史学习影响；完整延续历史请导出主体备份。'}

    def revision_files(self,engine):return VersionFiles(engine.store.directory/'versions'/'personas')
    def save_revision(self,engine,label='手动人格检查点'):
        with engine.lock:return self.revision_files(engine).put(export_continuity(engine),label,identity_id=engine.profile()['id'])
    def apply_current(self,engine,pack):
        with engine.lock:
            validated=validate_pack(pack);meta=validated[0]
            if meta['identity']['id']!=engine.profile()['id']:raise ValueError('请选择当前主体的人格包；其他人格请使用载入人格包')
            candidate=create_pmm(engine.config.get(),meta['pmm_checkpoint'],engine.profile()['id'])
            meta['pmm_checkpoint']=candidate.export()
            self.save_revision(engine,'应用人格包前自动备份')
            engine.journal.merge_snapshot({})
            old_catalog=copy.deepcopy(self.catalog)
            for item in self.catalog['items']:
                if item['id']==meta['identity']['id']:item['name']=meta['pmm_profile']['name']
            try:
                self.save()
                with engine.store.lock,engine.store.db:apply_pack(engine.store,validated)
            except Exception:
                self.catalog=old_catalog;self.save();raise
            engine.model=candidate
            return {'ok':True,'message':'人格状态已恢复，现有对话历史保留；后续互动从恢复的心理状态继续。'}
    def rollback(self,engine,identifier):
        pack,_=self.revision_files(engine).read(identifier);return self.apply_current(engine,pack)
