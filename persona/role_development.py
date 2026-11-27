"""Current memory-derived role material, with legacy snapshots retained.

New writes originate in memory_role_changes; numerical promotion prose is no
longer generated or selected. Original authored identity stays authoritative.
"""
import copy
from .registry import number


def active(profile,scope=None):
    records={r['id']:r for r in profile.get('psychology',{}).get('evidence_records',[])}
    out=[]
    for row in profile.get('role_development',[]):
        if row.get('status')!='active' or scope is not None and row.get('scope')!=scope:continue
        from .memory_role_changes import METHOD
        if row.get('method')!=METHOD or row.get('locked'):continue
        refs=row.get('evidence') or []
        if not refs or any(e['record_id'] not in records or records[e['record_id']].get('withdrawn') for e in refs):continue
        out.append(copy.deepcopy(row))
    return out


def validate(profile):
    notes=profile.get('role_development',[])
    if not isinstance(notes,list):raise ValueError('经历人设补充必须为列表')
    records={r['id']:r for r in profile.get('psychology',{}).get('evidence_records',[])}
    ids=set()
    for row in notes:
        if not isinstance(row,dict) or not isinstance(row.get('id'),str) or row['id'] in ids:raise ValueError('经历人设补充标识无效')
        ids.add(row['id'])
        if row.get('source_type')!='experience_reflection' or row.get('status') not in ('active','superseded','pending','rejected'):raise ValueError('经历人设补充来源无效')
        if not isinstance(row.get('text'),str) or not 1<=len(row['text'])<=400 or not isinstance(row.get('scope'),str) or not row['scope']:raise ValueError('经历人设补充内容或范围无效')
        from .memory_role_changes import METHOD,CATEGORIES
        modern=row.get('method')==METHOD
        number(row.get('weight'),0,.05 if modern else .15);number(row.get('confidence'),0,1 if modern else .5)
        if modern:
            if row.get('category') not in CATEGORIES or row.get('significance')!='major' or row.get('author_conflict') is not False:raise ValueError('记忆人设变化类别或条件无效')
            if row['status']=='pending' and row['weight']!=0:raise ValueError('未确认人设候选不能生效')
            for key in ('source_memory_ids','major_memory_ids'):
                if not isinstance(row.get(key),list) or not row[key] or any(not isinstance(x,str) for x in row[key]):raise ValueError('记忆人设变化缺少来源')
        refs=row.get('evidence')
        if not isinstance(refs,list) or not refs:raise ValueError('经历人设补充缺少证据')
        for e in refs:
            r=records.get(e.get('record_id'),{}) if isinstance(e,dict) else {}
            if r.get('evidence_kind')!='experienced_event' or r.get('scope')!=row['scope'] or not isinstance(e.get('quote'),str) or not e['quote'] or e['quote'] not in r.get('text',''):raise ValueError('经历人设补充证据无效')
