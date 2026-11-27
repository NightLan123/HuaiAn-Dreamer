"""Deterministic, source-preserving author-material catalog and local selection.

Categories are retrieval hints, not new psychological facts. No language model,
store, network or generated reply is consulted. Unknown material stays stored
and searchable. Original text is never rewritten into inferred memories.
"""
from __future__ import annotations
import copy
import hashlib
import json
import re

SCHEMA = 'persona-catalog/2.8.2/1'
CATEGORIES = ('identity_background', 'personality_values', 'experiences', 'key_events',
              'relationships', 'expression', 'boundaries', 'unclassified')
LABELS = {
    '身份': 'identity_background', '背景': 'identity_background', '身份背景': 'identity_background',
    '身份与背景': 'identity_background', '基本信息': 'identity_background',
    '性格': 'personality_values', '人格': 'personality_values', '价值观': 'personality_values',
    '性格与价值观': 'personality_values', '经历': 'experiences', '个人经历': 'experiences',
    '主要事件': 'key_events', '关键事件': 'key_events', '重要事件': 'key_events',
    '关系': 'relationships', '人际关系': 'relationships', '表达': 'expression',
    '表达习惯': 'expression', '语言风格': 'expression', '边界': 'boundaries',
    '禁忌': 'boundaries', '边界与禁忌': 'boundaries', '待归类': 'unclassified',
}
_HEAD = re.compile(r'^\s*(?:#{1,6}\s*)?(?:【|\[)?(' + '|'.join(sorted(LABELS, key=len, reverse=True)) + r')(?:】|\])?\s*[:：]\s*')
_HINTS = {
    'identity_background': r'出生|长大|故乡|家乡|来自|居住|住在|职业|身份|\d+\s*岁|是(?:一位|一名|个|位|名)|名叫|名字是|就读',
    'personality_values': r'性格|个性|脾气|为人|慢热|开朗|温和|内向|外向|谨慎|耐心|诚实|重视|珍惜|信奉|相信|价值观|喜欢|讨厌|在意|追求|不善|冷静|认真',
    'experiences': r'曾经|曾在|曾到|曾与|曾和|过去|小时候|童年|大学时|毕业|经历|参加过|去过|做过|救过|失去|搬到|\d{4}年',
    'key_events': r'关键事件|重大|重要转折|转折|从此|因此|那以后|离别|离世|事故|决定性|改变了|终生|永远记得',
    'relationships': r'朋友|好友|旧友|亲友|同伴|伙伴|父亲|母亲|姐姐|哥哥|弟弟|妹妹|老师|导师|同事|恋人|伴侣|家人|闺蜜|兄弟|姐妹|认识|关系',
    'expression': r'说话|语气|口吻|自称|称呼|表达|措辞|口头禅|语言风格|回答时|回复时|交流时|聊天时',
    'boundaries': r'不公开|不透露|不得|禁止|禁忌|底线|绝不|不能泄露|不允许|不要泄露|不分享.*(?:隐私|住址|密码)|拒绝.*(?:泄露|公开)',
}
_CAUSAL = re.compile(r'^(?:因此|所以|从此|那以后|此后|后来|为此|这让|这使|这件事|那件事|离别后|受此|因为|由于|她因此|他因此|它因此)')
_NEW_CLAUSE = re.compile(r'^(?:性格|个性|为人|脾气|平时|说话|自称|曾经|曾在|出生|职业|喜欢|讨厌|重视|信奉|擅长|经历|身份|关系|边界|关键事件|主要事件)')
_TIME_LITERAL = re.compile(r'\d{4}年(?:\d{1,2}月(?:\d{1,2}[日号])?)?|\d{4}-\d{1,2}-\d{1,2}|童年|小时候|幼年|少年时期|青年时期|大学时|中学时|成年后|毕业后|退休后')
_STOP = {'你好','您好','早上','晚上','今天','现在','请问','请说','说说','讲讲','介绍','一下','关于','什么','怎么','怎样','如何','时候','你的','自己','这个','那个','哪些','以前','过去','曾经','经历','事件','背景','性格','价值','关系','表达','习惯','人物','角色','事情','当前','问题','回答','需要','可以','一下','共有','还有','我们','你们','他们','成为'}

def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf8')).hexdigest()

def _path_part(value):
    return str(value).replace('~', '~0').replace('/', '~1')

def _spans(text):
    """Sentence breaks and unambiguous new-clause commas, outside quotations."""
    start = 0; quote = None; stack = []
    pairs = {'“': '”', '‘': '’', '「': '」', '『': '』', '(': ')', '（': '）', '[': ']', '【': '】'}
    for i, char in enumerate(text):
        if char in ('"', "'"):
            if i == 0 or text[i-1] != '\\': quote = None if quote == char else char if quote is None else quote
        elif quote is None:
            if stack and char == stack[-1]: stack.pop()
            elif char in pairs: stack.append(pairs[char])
        if quote or stack: continue
        remainder = text[i+1:].lstrip()
        boundary = char in '。！？；;\n' or char in '，,' and _NEW_CLAUSE.match(remainder) and not _CAUSAL.match(remainder)
        if boundary:
            yield start, i+1
            start = i+1
    if start < len(text): yield start, len(text)

def _classify(text, heading=None, hint=None):
    categories = {category for category, pattern in _HINTS.items() if re.search(pattern, text, re.I)}
    if heading:
        categories.add(heading)
        method = 'explicit_heading_and_lexical_hints'
    elif categories:
        method = 'local_lexical_hints'
    elif hint:
        categories.add(hint); method = 'source_field'
    else:
        categories.add('unclassified'); method = 'unclassified'
    categories.discard('unclassified') if len(categories) > 1 else None
    return [category for category in CATEGORIES if category in categories], method

def compile_catalog(source):
    """Compile only existing author/reviewed source; no inferred events or facts."""
    if not isinstance(source, dict): raise ValueError('人设分类来源必须是对象')
    entries = []; by_text = {}; groups = {}
    def add(text, path, start, end, categories, method, *, scope='', source_type='owner_setting',
            identity_core=False, group=None, representation='text'):
        # Text is stored once per evidence class and scope, with all occurrences
        # retained as offsets. Different people/scopes are not interchangeable.
        key = (text, scope, source_type, representation, path if representation == 'reference' else '')
        origin = {'source_path': path, 'start': start, 'end': end}
        if key in by_text:
            row = by_text[key]
            if origin not in row['origins']: row['origins'].append(origin)
            row['categories'] = [category for category in CATEGORIES if category in set(row['categories']) | set(categories)]
            row['identity_core'] = row['identity_core'] or identity_core
        else:
            row = {'id': 'role-' + _digest([source.get('profile_id'), *key])[:24], 'text': text,
                   'source_path': path, 'start': start, 'end': end, 'origins': [origin],
                   'source_type': source_type, 'scope': scope, 'categories': categories,
                   'classification': {'method': method, 'semantic_model_confirmed': False},
                   'identity_core': identity_core, 'representation': representation,
                   'time': {'source_literals': list(dict.fromkeys(_TIME_LITERAL.findall(text))), 'interpretation': 'source_text_only'} if _TIME_LITERAL.search(text) else None,
                   'epistemic_status': 'author_setting' if source_type == 'owner_setting' else 'reviewed_source'}
            entries.append(row); by_text[key] = row
        if group: groups.setdefault(group, []).append(row['id'])
        return row
    def authored(text, path, hint=None, scope='', group=None, identity_core=False):
        if not isinstance(text, str) or not text.strip(): return
        heading = None; heading_label = None; previous = None
        for start, end in _spans(text):
            while start < end and text[start].isspace(): start += 1
            while end > start and text[end-1].isspace(): end -= 1
            if start == end: continue
            match = _HEAD.match(text[start:end])
            if match:
                heading_label = match.group(1); heading = LABELS[heading_label]; start += match.end()
                # Header labels are structural metadata, not extra facts.
                if start == end: continue
            value = text[start:end]
            categories, method = _classify(value, heading, hint)
            explicit_identity = heading_label in ('身份', '基本信息') and len(value) <= 100 and bool(re.search(r'是|职业|年龄|性别|名叫|名字|岁', value))
            minimal = identity_core or (explicit_identity or bool(re.search(r'身份|职业|是(?:一名|一位|个|名|位)|名叫|名字是|\d+岁', value))) and 'identity_background' in categories and not any(c in categories for c in ('experiences','key_events','relationships'))
            row = add(value, path, start, end, categories, method, scope=scope, identity_core=minimal, group=group)
            if previous and _CAUSAL.match(value):
                row.setdefault('context_ids', []).append(previous['id'])
            previous = row
    authored(source.get('name', ''), '/name', 'identity_background', identity_core=True)
    character = source.get('character') or {}
    authored(character.get('self_reference', ''), '/character/self_reference', 'expression', identity_core=True)
    authored(source.get('seed', ''), '/seed')
    authored(character.get('initial_personality', ''), '/character/initial_personality', 'personality_values')
    materials = source.get('owner_material') or {}
    for index, row in enumerate(materials.get('beliefs', [])):
        if not isinstance(row, dict): continue
        authored(row.get('text', ''), f'/owner_material/beliefs/{index}/text', 'personality_values', row.get('scope') or '')
    for index, row in enumerate(materials.get('patterns', [])):
        if not isinstance(row, dict): continue
        group = 'pattern-' + str(index)
        for field in ('text', 'situation', 'response'):
            authored(row.get(field, ''), f'/owner_material/patterns/{index}/{field}', 'expression', row.get('scope') or '', group=group)
    for index, row in enumerate(source.get('boundaries', [])):
        if not isinstance(row, dict) or row.get('enabled') is False: continue
        scope = row.get('scope') or ''
        authored(row.get('label', ''), f'/boundaries/{index}/label', 'boundaries', scope)
        for quote_index, quote in enumerate(row.get('forbidden_quotes', [])):
            authored(quote, f'/boundaries/{index}/forbidden_quotes/{quote_index}', 'boundaries', scope)
    for key in sorted(source.get('stable_personality') or {}):
        add('', '/stable_personality/' + _path_part(key), 0, 0, ['personality_values'], 'existing_typed_source',
            source_type='confirmed_personality_reference', representation='reference')
    for index, row in enumerate(source.get('reviewed_tendencies', [])):
        if isinstance(row, dict):
            add('', f'/reviewed_tendencies/{index}', 0, 0, ['expression'], 'existing_typed_source',
                scope=row.get('scope') or '', source_type='owner_reviewed', representation='reference')
    for identifiers in groups.values():
        identifiers = list(dict.fromkeys(identifiers))
        for row in entries:
            if row['id'] in identifiers: row['related_entry_ids'] = [i for i in identifiers if i != row['id']]
    for index,note in enumerate(source.get('role_development',[])):
        categories={'experiences':['experiences','key_events'],'relationships':['relationships'],
            'preferences':['personality_values'],'values':['personality_values'],'behavior':['expression']}.get(note.get('category'),['personality_values','experiences'])
        row=add(note['text'],f'/role_development/{index}/text',0,len(note['text']),categories,
            'evidenced_slow_development',scope=note['scope'],source_type='experience_reflection')
        row.update(weight=note['weight'],confidence=note['confidence'],development_id=note['id'],
            epistemic_status=note.get('epistemic_status','inferred_role_tendency_not_biographical_fact'))
        if note.get('category'):row['role_domain']=note['category']
    return {'schema': SCHEMA, 'source_digest': _digest(source), 'entries': entries,
            'categories': {category: [row['id'] for row in entries if category in row['categories']] for category in CATEGORIES},
            'identity_names': [source.get('name', '')],
            'classification_policy': 'local_explicit_headings_and_lexical_hints; no_inferred_facts; unclassified_retained',
            'unclassified_count': sum('unclassified' in row['categories'] for row in entries)}

def _tokens(text, names=()):
    text = str(text).lower()
    for name in names:
        if name: text = text.replace(name.lower(), '')
    result = {word for word in re.findall(r'[a-z][a-z0-9_-]{2,}', text) if word not in {'the','and','you','your','what','how','about','please','role'}}
    for phrase in re.findall(r'[\u3400-\u9fff]+', text):
        for width in (2,3):
            for i in range(len(phrase)-width+1):
                token = phrase[i:i+width]
                if not any(stop in token for stop in _STOP): result.add(token)
    return result

def select_catalog(catalog, query='', purpose='generator', policy=None):
    """Pick local source entries; never send all history or unknown text by default."""
    if not isinstance(catalog, dict) or catalog.get('schema') != SCHEMA: raise ValueError('人设分类目录格式无效')
    policy = policy if isinstance(policy, dict) else {}
    text = str(query or '')
    if not text:
        text = '\n'.join(str(policy[k]) for k in ('content_goal','task_handling','goal') if isinstance(policy.get(k),str))
    names = catalog.get('identity_names', [])
    query_tokens = _tokens(text, names)
    scope = policy.get('scope') or ''
    rows = catalog.get('entries') or []; included = {}; reasons = {}; omitted_reasons = {}
    permitted = {row['id']: row for row in rows if row.get('scope') in ('','*',None,scope) and row.get('representation') == 'text'}
    topic_scores = {key:len(query_tokens & _tokens(row['text'], names)) for key,row in permitted.items()}
    requested = set()
    if re.search(r'你|您|角色|人物|自己|自我|我的|全部|完整|所有', text):
        for label, category in LABELS.items():
            if label in text: requested.add(category)
        if re.search(r'童年|过去|以前|生平', text): requested.add('experiences')
    def include(row, reason):
        included[row['id']] = row
        reasons.setdefault(row['id'], [])
        if reason not in reasons[row['id']]: reasons[row['id']].append(reason)
    topical = [row for row in permitted.values() if topic_scores[row['id']] > 0]
    topical_categories = {c for row in topical for c in row['categories']}
    for key,row in permitted.items():
        categories = set(row['categories'])
        contextual = bool(categories & {'experiences','key_events','relationships','unclassified'})
        pattern = row['source_path'].startswith('/owner_material/patterns/')
        if row.get('identity_core'): include(row,'minimal_identity')
        if 'boundaries' in categories: include(row,'active_boundary')
        if not contextual and not pattern and categories & {'personality_values','expression'}:
            include(row,'current_role_behavior')
        if topic_scores[key]: include(row,'topic_overlap')
        if categories & (requested - topical_categories): include(row,'explicit_category_request')
    # A situation/response pair and explicitly causal adjacent source fragments
    # are evidence units; selecting only half would alter their meaning.
    queue = list(included.values())
    while queue:
        row=queue.pop()
        for related in row.get('related_entry_ids',[]) + row.get('context_ids',[]):
            if related in permitted and related not in included:
                include(permitted[related], 'linked_source_context');queue.append(permitted[related])
    selected = [copy.deepcopy(row) for row in rows if row['id'] in included]
    for row in rows:
        if row['id'] not in included:
            omitted_reasons[row['id']] = 'scope_mismatch' if row.get('scope') not in ('','*',None,scope) else 'typed_source_supplied_separately' if row.get('representation')=='reference' else 'not_current_topic'
    return {'entries': selected,
            'selection': {'method':'local_categories_and_lexical_overlap/1','purpose':purpose,
                'included_ids':[row['id'] for row in selected],
                'omitted_ids':[row['id'] for row in rows if row['id'] not in included],
                'included_categories':[category for category in CATEGORIES if any(category in row['categories'] for row in selected)],
                'reasons':reasons,'omitted_reasons':omitted_reasons,
                'no_inferred_facts':True,'unknown_material_preserved':True}}
