"""Versioned read-only projections of the existing role, with deletable history.

The profile and its reviewed learning evidence remain authoritative. History is
never searched to choose a generator/checker view: current() recompiles from the
current stored profile when necessary, including after an author rollback.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math

from .common import now, uid

KEY = 'pmm_persona_views'
SCHEMA = 'persona-view/2.8.2'
CATALOG_SCHEMA = 'persona-view-history/2.8.2'
COMPILER = 'persona-view-compiler/2.8.2/3'
LEGACY_COMPILERS = ('persona-view-compiler/2.8.2/1', 'persona-view-compiler/2.8.2/2')
_OWNER = {'manual', 'owner', 'owner_seed', 'owner_authored'}


def _scope_allowed(row, scope):
    return row.get('scope','') in ('','*',scope)


def _scope_source(source, scope):
    """Apply explicit scopes after the existing record-evidence filter."""
    result=copy.deepcopy(source)
    result['boundaries']=[row for row in result['boundaries'] if _scope_allowed(row,scope)]
    result['reviewed_tendencies']=[row for row in result['reviewed_tendencies'] if _scope_allowed(row,scope)]
    if 'role_development' in result:result['role_development']=[row for row in result['role_development'] if _scope_allowed(row,scope)]
    for field in ('beliefs','patterns'):
        result['owner_material'][field]=[row for row in result['owner_material'][field] if _scope_allowed(row,scope)]
    return result


def _digest(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return 'sha256:' + hashlib.sha256(raw.encode('utf8')).hexdigest()


def _revision(profile):
    value = profile.get('revision', 0)
    if type(value) is not int or value < 0:
        raise ValueError('角色资料修订号无效')
    return value


def _source(profile, reviewed):
    """Only author material and evidenced/approved stable material are compiled.

    Aggregate style is descriptive source statistics, not a psychological fact.
    Raw demonstrations, generated replies, short affect and latent weights are
    deliberately not copied into a reusable role view.
    """
    if not isinstance(profile, dict) or not isinstance(profile.get('id'), str) or not profile['id']:
        raise ValueError('角色资料缺少主体标识')
    character = profile.get('character') or {'self_reference': '我', 'initial_personality': ''}
    if not isinstance(character, dict):
        raise ValueError('角色设定必须是对象')
    for value in (profile.get('name'), profile.get('seed', ''),
                  character.get('self_reference', '我'), character.get('initial_personality', '')):
        if not isinstance(value, str):
            raise ValueError('角色设定必须是文本')
    boundaries = []
    for row in profile.get('boundaries', []):
        if not isinstance(row, dict) or not row.get('enabled'):
            continue
        boundaries.append({k: copy.deepcopy(row[k]) for k in
            ('id', 'label', 'keywords', 'action', 'enabled', 'hard', 'forbidden_quotes', 'source', 'scope') if k in row})
    boundaries.sort(key=lambda row: str(row.get('id', '')))
    style = profile.get('style') or {}
    statistics = {k: copy.deepcopy(style[k]) for k in ('count', 'median_chars', 'p90_chars', 'vector') if k in style}
    for key in ('count', 'median_chars', 'p90_chars'):
        value = statistics.get(key, 0)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise ValueError('角色表达统计无效')
    owner_material = {}
    for field in ('beliefs', 'patterns'):
        owner_material[field] = [{k: copy.deepcopy(row[k]) for k in
            ('id', 'text', 'situation', 'response', 'source', 'scope') if k in row}
            for row in profile.get(field, []) if isinstance(row, dict) and row.get('source') in _OWNER]
    from .known_personality import operative_personality
    result={'profile_id': profile['id'], 'name': profile['name'], 'seed': profile.get('seed', ''),
        'stable_personality':operative_personality(profile),
        'character': {k: character.get(k, '我' if k == 'self_reference' else '')
                      for k in ('self_reference', 'initial_personality')},
        'boundaries': boundaries, 'style_statistics': statistics,
        'owner_material': owner_material, 'reviewed_tendencies': copy.deepcopy(reviewed)}
    from .role_development import active
    notes=active(profile)
    if notes:result['role_development']=notes
    return result


def _compiled(source, version_id, sequence, source_revision, compiled_at, compiler=None):
    # Old snapshots must be rebuilt with their own exact compiler, not upgraded
    # in place during validation. New current snapshots use the latest version.
    compiler=compiler or (COMPILER if 'stable_personality' in source else LEGACY_COMPILERS[0])
    if compiler not in (*LEGACY_COMPILERS,COMPILER):
        raise ValueError('不支持的人设JSON编译器版本')
    if compiler==LEGACY_COMPILERS[0] and 'stable_personality' in source or compiler==LEGACY_COMPILERS[1] and 'stable_personality' not in source:
        raise ValueError('历史人设JSON来源与编译器版本不匹配')
    digest = _digest(source)
    reviewed = source['reviewed_tendencies']
    learned_revision = _digest({'reviewed':reviewed,'stable_personality':source['stable_personality']}) if 'stable_personality' in source else _digest(reviewed)
    common = {'schema': SCHEMA, 'version_id': version_id, 'profile_id': source['profile_id'],
        'source_profile_revision': source_revision, 'profile_revision': source_revision,
        'source_digest': digest, 'learned_revision': learned_revision, 'compiler_version': compiler}
    character = copy.deepcopy(source['character'])
    style = copy.deepcopy(source['style_statistics'])
    style['provenance'] = 'independent_source_statistics_not_calibrated'
    style['status'] = 'observed' if style.get('count', 0) else 'no_independent_observations'
    generator = {**common, 'id': source['profile_id'], 'name': source['name'], 'seed': source['seed'],
        'character': character, 'style': style, 'boundaries': copy.deepcopy(source['boundaries']),
        'beliefs': copy.deepcopy(source['owner_material']['beliefs']),
        'patterns': copy.deepcopy(source['owner_material']['patterns']),
        'reviewed_tendencies': [copy.deepcopy(row) for row in reviewed if not row.get('scope')]}
    checker = {**common, 'id': source['profile_id'], 'name': source['name'],
        'character': copy.deepcopy(character), 'seed': source['seed'],
        'boundaries': copy.deepcopy(source['boundaries']),
        'reviewed_tendencies': copy.deepcopy(generator['reviewed_tendencies'])}
    if 'stable_personality' in source:
        generator['stable_personality']=copy.deepcopy(source['stable_personality'])
        checker['stable_personality']=copy.deepcopy(source['stable_personality'])
    result={'schema': SCHEMA, 'version_id': version_id, 'id': version_id,
        'sequence': sequence, 'version': sequence, 'profile_id': source['profile_id'],
        'source_profile_revision': source_revision, 'source_revision': source_revision,
        'source_digest': digest, 'compiled_at': compiled_at, 'compiler_version': compiler,
        'learned_revision': learned_revision,
        'identity': {'name': source['name'], 'self_reference': character['self_reference']},
        'author_settings': {'seed': source['seed'], 'initial_personality': character['initial_personality'],
                            'provenance': 'existing_owner_profile'},
        'behavioral_tendencies': copy.deepcopy(reviewed),
        'hard_boundaries': [copy.deepcopy(row) for row in source['boundaries'] if row.get('hard')],
        'source_payload': copy.deepcopy(source), 'generator_view': generator, 'checker_view': checker}
    if compiler==COMPILER:
        from .persona_catalog import compile_catalog
        result['role_catalog']=compile_catalog(source)
        result['author_settings']={'source_ref':'source_payload',
            'source_paths':['/seed','/character/initial_personality'],
            'provenance':'existing_owner_profile'}
        # Only one classified document is persisted. Runtime hydration selects
        # the applicable scope; old compiler snapshots retain their exact shape.
        for view in (generator,checker):
            for key in ('seed','beliefs','patterns'):
                view.pop(key,None)
            view['character']={'self_reference':character['self_reference']}
            view['catalog_ref']={'version_id':version_id,'source_digest':digest}
            view['boundaries']=[copy.deepcopy(row) for row in source['boundaries'] if _scope_allowed(row,'')]
            view['reviewed_tendencies']=[copy.deepcopy(row) for row in source['reviewed_tendencies'] if _scope_allowed(row,'')]
    return result


def validate(catalog, profile_id=None):
    """Validate optional metadata on old snapshots/packages without changing it."""
    if catalog is None:
        return None
    if not isinstance(catalog, dict) or catalog.get('schema') != CATALOG_SCHEMA:
        raise ValueError('人设JSON版本目录无效')
    owner = catalog.get('profile_id')
    if not isinstance(owner, str) or not owner or profile_id is not None and owner != profile_id:
        raise ValueError('人设JSON版本所属角色不匹配')
    items = catalog.get('items')
    if not isinstance(items, list) or len(items) > 10000:
        raise ValueError('人设JSON版本记录无效')
    ids, sequences = set(), set()
    for item in items:
        if not isinstance(item, dict) or item.get('schema') != SCHEMA or item.get('profile_id') != owner:
            raise ValueError('人设JSON版本内容无效')
        identifier, sequence, revision = item.get('version_id'), item.get('sequence'), item.get('source_profile_revision')
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            raise ValueError('人设JSON版本标识无效')
        if type(sequence) is not int or sequence < 1 or sequence in sequences or type(revision) is not int or revision < 0:
            raise ValueError('人设JSON版本序号无效')
        stamp = item.get('compiled_at')
        if type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp <= 0:
            raise ValueError('人设JSON编译时间无效')
        source = item.get('source_payload')
        if not isinstance(source, dict) or source.get('profile_id') != owner:
            raise ValueError('人设JSON来源无效')
        try:
            expected = _compiled(source, identifier, sequence, revision, stamp, compiler=item.get('compiler_version'))
        except (KeyError, TypeError, ValueError, OverflowError) as ex:
            raise ValueError('人设JSON来源或编译结果无效') from ex
        if item != expected:
            raise ValueError('人设JSON版本与同源编译结果不一致')
        ids.add(identifier); sequences.add(sequence)
    current = catalog.get('current_version_id')
    if items and current not in ids or not items and current is not None:
        raise ValueError('人设JSON当前版本引用无效')
    next_sequence = catalog.get('next_sequence')
    if type(next_sequence) is not int or next_sequence <= max(sequences, default=0):
        raise ValueError('人设JSON下一版本序号无效')
    if type(catalog.get('deleted_count', 0)) is not int or catalog.get('deleted_count', 0) < 0:
        raise ValueError('人设JSON删除统计无效')
    return catalog


class PersonaViews:
    def __init__(self, store):
        self.store = store
        self._validated_catalog_digest = None
        self._runtime_catalogs = {}
        self._runtime_version = None

    def _runtime_catalog(self, active, source, scope):
        """Cache classification, not selection, for this version and source scope."""
        if self._runtime_version != active['version_id']:
            self._runtime_catalogs.clear()
            self._runtime_version=active['version_id']
        digest=_digest(source)
        key=(active['version_id'],scope,digest)
        if key not in self._runtime_catalogs:
            if digest==active['source_digest']:
                value=active['role_catalog']
            else:
                from .persona_catalog import compile_catalog
                value=compile_catalog(source)
            if len(self._runtime_catalogs)>=32:
                self._runtime_catalogs.pop(next(iter(self._runtime_catalogs)))
            self._runtime_catalogs[key]=copy.deepcopy(value)
        return copy.deepcopy(self._runtime_catalogs[key])

    def _reviewed(self, requested=None):
        state = self.store.meta('pmm_pragmatics')
        if not state:
            active = []
        else:
            from . import pragmatics, language_learning
            pragmatics.validate(state)
            active = language_learning.applied(state)
        normalized = []
        for row in active:
            normalized.append({k: copy.deepcopy(row[k]) for k in
                ('id', 'field', 'scope', 'prior_speech_act', 'estimate', 'effective_events',
                 'evidence_digest', 'learning_strength', 'source_event_ids') if k in row} |
                {'source': 'owner_reviewed_learning', 'certainty': 'tendency'})
        normalized.sort(key=lambda row: (row.get('scope', ''), row.get('id', '')))
        if requested is not None:
            # An optional caller filter cannot invent a second reviewed truth.
            if not isinstance(requested, list):
                raise ValueError('已审核习惯筛选必须是列表')
            allowed = {row['id'] for row in normalized}
            requested_ids = {row.get('id') for row in requested if isinstance(row, dict)}
            if len(requested_ids) != len(requested) or not requested_ids <= allowed:
                raise ValueError('调用方不能注入未存储、未审核的人设变化')
            # Compilation stays canonical; selection belongs to PromptCompiler.
        return normalized

    def _authoritative(self, profile, reviewed=None):
        saved = self.store.meta('pmm_profile')
        identity = self.store.meta('identity') or {}
        if not isinstance(saved, dict) or saved.get('id') != identity.get('id'):
            raise ValueError('当前角色资料缺失或身份不一致')
        if not isinstance(profile, dict) or profile.get('id') != saved['id']:
            raise ValueError('当前角色已变化，请重新读取人设')
        learning = self._reviewed(reviewed)
        source = _source(saved, learning)
        if _digest(_source(profile, learning)) != _digest(source):
            raise ValueError('角色资料已更新，拒绝使用历史资料作为当前人设')
        _revision(saved)
        return saved, source

    def current(self, profile, reviewed=None):
        with self.store.lock, self.store.db:
            saved, source = self._authoritative(profile, reviewed)
            catalog = self.store.meta(KEY)
            catalog_digest = _digest(catalog)
            if catalog_digest != self._validated_catalog_digest:
                validate(catalog, saved['id'])
                self._validated_catalog_digest = catalog_digest
            if catalog is None:
                catalog = {'schema': CATALOG_SCHEMA, 'profile_id': saved['id'], 'items': [],
                    'current_version_id': None, 'next_sequence': 1, 'deleted_count': 0}
            active = next((row for row in catalog['items'] if row['version_id'] == catalog['current_version_id']), None)
            if active is None or active['source_digest'] != _digest(source) or active.get('compiler_version') != COMPILER:
                if len(catalog['items']) >= 10000:
                    raise ValueError('人设JSON历史达到上限，请先删除不需要的历史记录')
                active = _compiled(source, uid(), catalog['next_sequence'], _revision(saved), now())
                catalog['items'].append(active); catalog['current_version_id'] = active['version_id']
                catalog['next_sequence'] += 1
                self.store.setmeta(KEY, catalog)
                self._validated_catalog_digest = _digest(catalog)
                self.store.event('persona_view_compiled', {'version_id': active['version_id'],
                    'sequence': active['sequence'], 'source_digest': active['source_digest']})
            result = copy.deepcopy(active)
            # A routine observation can increment the source profile revision
            # without changing the reusable authored/reviewed view. Preserve its
            # compiled revision and separately report this call's observed one.
            result.update(is_current=True, can_delete=False, profile_revision=_revision(saved),
                          observed_profile_revision=_revision(saved))
            for key in ('generator_view', 'checker_view'):
                result[key]['profile_revision'] = _revision(saved)
            from .psychology import context_profile
            global_source=_scope_source(_source(context_profile(saved,'__persona_global_projection__'),
                                  active['behavioral_tendencies']),'')
            runtime_catalog=self._runtime_catalog(active,global_source,'')
            for key in ('generator_view','checker_view'):
                result[key]['role_catalog']=copy.deepcopy(runtime_catalog)
                result[key]['boundaries']=copy.deepcopy(global_source['boundaries'])
                result[key]['reviewed_tendencies']=copy.deepcopy(global_source['reviewed_tendencies'])
                result[key]['stable_personality']=copy.deepcopy(global_source.get('stable_personality',{}))
                result[key].update(view_scope='',projection='global_filtered_runtime')
            return result

    def list(self, profile):
        with self.store.lock:
            active = self.current(profile)
            catalog = self.store.meta(KEY)
            rows = []
            for item in sorted(catalog['items'], key=lambda row: row['sequence'], reverse=True):
                current = item['version_id'] == active['version_id']
                rows.append({key: copy.deepcopy(item[key]) for key in
                    ('id', 'version_id', 'version', 'sequence', 'profile_id', 'source_profile_revision',
                     'source_digest', 'compiled_at', 'compiler_version', 'learned_revision', 'identity')} |
                    {'is_current': current, 'can_delete': not current})
            return {'schema': CATALOG_SCHEMA, 'profile_id': active['profile_id'],
                    'current_version_id': active['version_id'], 'current_id': active['version_id'],
                    'items': rows, 'versions': copy.deepcopy(rows), 'deleted_count': catalog['deleted_count']}

    def scoped_views(self, profile, scope):
        """Return current-version runtime projections for one conversation.

        The owner history remains a complete source snapshot. Private derived
        text still follows the existing context_profile evidence filter before
        either generator or checker sees it; browsing does not activate history.
        """
        if not isinstance(scope, str) or not scope or len(scope) > 240:
            raise ValueError('人设运行视图需要明确的会话范围')
        from .psychology import context_profile
        with self.store.lock:
            active = self.current(profile)
            scoped = context_profile(profile, scope)
            source = _scope_source(_source(scoped,active['behavioral_tendencies']),scope)
            reviewed = source['reviewed_tendencies']
            scoped_catalog=self._runtime_catalog(active,source,scope)
            active['role_catalog']=copy.deepcopy(scoped_catalog)
            for key in ('generator_view', 'checker_view'):
                view = active[key]
                view['boundaries'] = copy.deepcopy(source['boundaries'])
                view['reviewed_tendencies'] = copy.deepcopy(reviewed)
                view['stable_personality']=copy.deepcopy(source.get('stable_personality',{}))
                view['role_catalog']=copy.deepcopy(scoped_catalog)
                view.update(view_scope=scope, projection='scope_filtered_runtime')
            return active

    def get(self, profile, version_id):
        with self.store.lock:
            active = self.current(profile)
            item = next((row for row in self.store.meta(KEY)['items'] if row['version_id'] == version_id), None)
            if item is None:
                raise ValueError('人设JSON版本不存在或已删除')
            result = copy.deepcopy(item); current = version_id == active['version_id']
            result.update(is_current=current, can_delete=not current, usage='current' if current else 'history_read_only')
            if current:
                # Owner API returns the stored one-catalog snapshot. Model
                # hydration belongs only to current()/scoped_views().
                result.update(profile_revision=active['profile_revision'],
                              observed_profile_revision=active['observed_profile_revision'])
            return result

    def delete(self, profile, version_ids):
        if not isinstance(version_ids, list) or not all(isinstance(value, str) and value for value in version_ids) or len(set(version_ids)) != len(version_ids):
            raise ValueError('请选择不重复的人设JSON历史版本')
        with self.store.lock, self.store.db:
            active = self.current(profile)
            catalog = self.store.meta(KEY)
            ids = set(version_ids); known = {item['version_id'] for item in catalog['items']}
            if active['version_id'] in ids:
                raise ValueError('当前有效人设JSON不能作为历史记录删除')
            if not ids <= known:
                raise ValueError('人设JSON版本不存在或已删除')
            if ids:
                catalog['items'] = [item for item in catalog['items'] if item['version_id'] not in ids]
                catalog['deleted_count'] += len(ids); self.store.setmeta(KEY, catalog)
                self._validated_catalog_digest = _digest(catalog)
                self.store.event('persona_view_history_deleted', {'version_ids': version_ids,
                    'current_version_id': active['version_id']})
            return {'ok': True, 'deleted': version_ids, 'current_version_id': active['version_id'],
                    'current_id': active['version_id'], 'remaining': len(catalog['items'])}
