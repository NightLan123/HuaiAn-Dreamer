"""Bounded, versioned role retrieval. No model calls or profile mutations.

A requests semantic facets, while source spans remain local and authoritative.
Lexical hints are a labelled fallback, never the only retrieval route.
"""
import copy
import re

FACETS={
 'occupation':('职业、工作、公司及作息','工作|上班|下班|公司|职业|岗位|运营|通勤|同事|班上|工资|失业','工作|上班|下班|公司|周末|周五|放假|休假|加班|职业|班上|工资|失业'),
 'education':('教育、专业、毕业','毕业|大学|本科|专业|读书|学校|就读','毕业|大学|专业|学校|读书|学历'),
 'identity':('姓名、年龄与角色身份','岁|名字|本名|身份|性别','几岁|多大|年龄|名字|你是谁|男生|女生'),
 'home':('居住、家乡与生活背景','居住|住在|家乡|故乡|搬家|长大|出生','住哪|哪里人|家乡|故乡|搬家|住在'),
 'relationships':('家庭、朋友与关系经历','朋友|家人|父亲|母亲|恋人|伴侣|认识|同事','朋友|家人|父亲|母亲|恋人|伴侣|认识'),
 'preferences':('兴趣、喜好与个人价值','喜欢|讨厌|爱好|兴趣|重视|珍惜|信奉','喜欢|讨厌|爱好|兴趣|重视|珍惜'),
 'experiences':('过去经历与重要事件','经历|曾经|过去|小时候|参加过|失去|改变|从此','经历|曾经|过去|小时候|参加过|改变|发生过'),
}
REQUEST_INSTRUCTION='''\n[ROLE_RETRIEVAL_V1] 判断当前输入是否需要角色资料，与事件重要性独立。问放假/作息也可能需要职业；简单问候不需要履历。role_index 只是可检索目录，不是角色事实。返回 role_request:{needed:boolean,facets:[目录中的键],queries:[简短检索词],reason:一句需求说明}，没有需求时 needed=false。不要臆测未返回的资料。已提供的 role_context 表示本轮检索结果；依据其中同版本条目评价与回应。'''

def facets(text,query=False):
    return [k for k,(_,source,cue) in FACETS.items() if re.search(cue if query else source,str(text),re.I)]

def entry_facets(row):
    result=facets(row.get('text',''))
    domain={'values':'preferences','behavior':'preferences'}.get(row.get('role_domain'),row.get('role_domain'))
    if domain in FACETS:result=list(dict.fromkeys(result+[domain]))
    return result

def normalize_request(value):
    if value is None:return None
    if not isinstance(value,dict) or type(value.get('needed')) is not bool:raise ValueError('role_request.needed must be boolean')
    fs=value.get('facets',[]);qs=value.get('queries',[])
    if not isinstance(fs,list) or len(fs)>8 or any(not isinstance(f,str) or f not in FACETS for f in fs):raise ValueError('role_request.facets invalid')
    if not isinstance(qs,list) or len(qs)>3 or any(not isinstance(q,str) or len(q)>100 for q in qs):raise ValueError('role_request.queries invalid')
    return {'needed':value['needed'],'facets':list(dict.fromkeys(fs)) if value['needed'] else [],
            'queries':qs if value['needed'] else [],'reason':str(value.get('reason',''))[:180]}

def index(view):
    rows=view.get('role_catalog',{}).get('entries',[])
    scope=view.get('view_scope','')
    allowed=[r for r in rows if r.get('scope') in ('','*',None,scope)]
    return {'version_id':view.get('version_id'),'facets':{k:{'meaning':v[0],'available':sum(k in entry_facets(r) for r in allowed)} for k,v in FACETS.items()},
            'unknown_allowed':True}

def retrieve(view,query,request=None,*,candidate=''):
    from .persona_catalog import select_catalog
    scope=view.get('view_scope','');catalog=view.get('role_catalog') or {}
    req=normalize_request(request)
    wanted=(req['facets'] if req else facets(query,True))
    prior=view.get('role_context') or {}
    inherited=prior.get('requested_facets',[]) if candidate and prior.get('version_id')==view.get('version_id') else []
    wanted=list(dict.fromkeys(wanted+facets(candidate,True)+inherited))
    queries=(req or {}).get('queries',[])
    selected=select_catalog(catalog,query=' '.join([query,*queries,candidate]),purpose='role_retrieval',policy={'scope':scope})
    topical={k for k,rs in selected['selection']['reasons'].items() if 'topic_overlap' in rs or 'explicit_category_request' in rs}
    lookup={r['id']:r for r in catalog.get('entries',[]) if r.get('scope') in ('','*',None,scope) and r.get('representation')=='text'}
    matches=[r for r in lookup.values() if set(wanted)&set(entry_facets(r)) or r['id'] in topical and (req is None or req['needed'] or candidate)]
    matches.sort(key=lambda r:(not bool(set(wanted)&set(entry_facets(r))),r.get('source_type')!='owner_setting'))
    ids=[];chars=0;limited=False
    if prior.get('version_id')==view.get('version_id'):
        ids=[i for i in prior.get('entry_ids',[]) if i in lookup]
        chars=sum(len(lookup[i]['text']) for i in ids)
    for r in matches:
        related_ids={r['id']};pending=[r['id']]
        while pending:
            related_row=lookup[pending.pop()]
            for i in related_row.get('context_ids',[])+related_row.get('related_entry_ids',[]):
                if i in lookup and i not in related_ids:related_ids.add(i);pending.append(i)
        group=[row for i,row in lookup.items() if i in related_ids and i not in ids]
        cost=sum(len(x['text']) for x in group)
        if len(ids)+len(group)>10 or chars+cost>3000:limited=True;continue
        ids.extend(x['id'] for x in group);chars+=cost
    return {'schema':'role-context/1','version_id':view.get('version_id'),'entry_ids':ids,
        'requested_facets':wanted,'requested':bool(wanted or (req or {}).get('needed')),
        'status':'available' if ids else 'not_found' if wanted or (req or {}).get('needed') else 'not_needed',
        'source':'A_semantic_request' if req else 'local_topic_fallback','limited':limited,
        'reason':(req or {}).get('reason',''),'candidate_review':bool(candidate)}

def bind(persona,context):
    if context.get('version_id')!=persona['version_id']:raise ValueError('Role retrieval version mismatch')
    for key in ('generator_view','checker_view'):persona[key]['role_context']=copy.deepcopy(context)

def bound_selection(view,selected):
    """Preserve requested facts and boundaries, bound routine style material."""
    catalog=view['role_catalog'];ctx=view.get('role_context') or {};scope=view.get('view_scope','')
    pins=set(ctx.get('entry_ids',[])) if ctx.get('version_id')==view.get('version_id') else set()
    allowed=[r for r in catalog.get('entries',[]) if r.get('scope') in ('','*',None,scope)]
    lookup={r['id']:r for r in allowed}
    original=selected['selection']['reasons'];mandatory={r['id'] for r in allowed if r['id'] in pins or r.get('identity_core') or 'boundaries' in r['categories']}
    selected_ids=set(mandatory);soft_chars=0
    for r in selected['entries']:
        if r['id'] in selected_ids:continue
        # Facts are requested explicitly, not displaced by thirty style rows.
        group={r['id']};pending=[r['id']]
        while pending:
            row=lookup[pending.pop()]
            for related in row.get('context_ids',[])+row.get('related_entry_ids',[]):
                if related in lookup and related not in group:group.add(related);pending.append(related)
        cost=sum(len(lookup[i]['text']) for i in group-selected_ids)
        limit=1400 if 'topic_overlap' in original.get(r['id'],[]) else 700 if 'current_role_behavior' in original.get(r['id'],[]) else 0
        if limit and soft_chars+cost<=limit:selected_ids.update(group);soft_chars+=cost
    result=copy.deepcopy(selected);result['entries']=[r for r in allowed if r['id'] in selected_ids]
    result['selection'].update(included_ids=[r['id'] for r in result['entries']],omitted_ids=[r['id'] for r in catalog.get('entries',[]) if r['id'] not in selected_ids],
        reasons={r['id']:(['role_request'] if r['id'] in pins else original.get(r['id'],['minimal_identity'])) for r in result['entries']},
        included_categories=sorted({c for r in result['entries'] for c in r['categories']}))
    return result

def candidate_review(view,text,candidate):
    ctx=retrieve(view,text,candidate=candidate)
    # Review role-directed replies and first-person biographical claims. Short
    # greetings need no semantic request; regex detects need, never convicts.
    first_person=bool(re.search(r'我|咱|本人|\bI\b|my\b',candidate,re.I))
    directed=bool(re.search(r'你|您|your|you',text,re.I))
    semantic_request=bool((view.get('role_context') or {}).get('requested'))
    required=bool((ctx['requested_facets'] or semantic_request) and (directed or first_person or semantic_request))
    return ctx,{'status':'required' if required else 'not_required','required':required,
        'facets':ctx['requested_facets'],'evidence_status':ctx['status'],
        'limited':ctx['limited'],'version_id':ctx['version_id'],'entry_ids':ctx['entry_ids']}
