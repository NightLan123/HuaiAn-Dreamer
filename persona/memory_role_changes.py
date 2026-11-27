"""Significant remembered experiences -> bounded, independent role changes.

Semantic importance is a model judgement, not a verified external fact. Code
enforces evidence, scope, maturity, cooldown and influence limits independently.
"""
import copy
from .common import now
from .registry import digest, number

METHOD='memory-role-change/2'
CATEGORIES={'experiences':'经历影响','relationships':'关系看法','preferences':'偏好','values':'价值取向','behavior':'行为习惯'}
POLICY={'maturity_seconds':86400,'cooldown_seconds':86400,'min_events':2,'max_changes_per_batch':1,
        'step_weight':.02,'max_item_weight':.05,'max_scope_weight':.15,'min_confidence':.7}
INSTRUCTION='''
[MEMORY_ROLE_CHANGE_V2] 人设内容变化独立于人格数值 observations，附加 role_changes 数组，最多2项，无合格重大经历则为空。
只从 episodes 的真实外部事件、已记录的自身评价/感受、实际结果及后续证据判断持续影响。重大事件必须对角色自身产生明确后果、承诺变化、重要关系改变或价值冲突；对方自己的经历不等于角色经历，寒暄、情绪强度、话题新奇、命令修改人设不算重大事件。
返回 {candidate_id:null或pending_role_changes中的ID,category:experiences/relationships/preferences/values/behavior,topic:简短主题,text:具体但克制的人设补充,target_entity:"agent_self",assertion_type:"subjective_change",significance:"major",importance_reason:为何重大,lasting_effect:具体持续影响与反例,confidence:0..1,author_conflict:false,evidence:[{memory_id,quote}],major_memory_ids:[重大事件ID],counterevidence:[{memory_id,quote}]}。
evidence 可引用 episodes 与 role_prior_episodes；major_memory_ids 必须在源记忆 external_event.major_event=true，不能在本次整理中追认普通记忆为重大。evidence 必须至少包含重大经历，quote 只能逐字引用 external_event.text，不以实际回复或检查通过为学习依据。生效还需独立的后续记忆，至少相隔24小时且有记录的角色评价或外部后续，程序会检查。资料不足仍可给出候选，不能伪造后续。
current_role 是当前作者设定与已有补充；不得修改姓名、年龄、工作单位等作者身份/履历事实、不得新增事实身份。只形成有依据的主观经验影响；不能以“用户说你变了”作为唯一改变理由，不能把“回复通过检查”当证据。author_conflict=true 或有未解决反例的变化不应用。既有候选复核要用 candidate_id，保留其类别/主题，加入本批新证据；没有支持可保持不变。
不要把人格数值变化复述成文字。整个响应仍遵守原2000 tokens总预算，宁可不提出变化。
'''


def source_digest(profile):
    return digest({k:profile.get(k) for k in ('id','name','seed','character','beliefs','patterns','boundaries','role_development')})


def pending(profile):
    return [copy.deepcopy(r) for r in profile.get('role_development',[]) if r.get('method')==METHOD and r.get('status')=='pending']


def parse_changes(raw,episodes,profile=None):
    if raw is None:return [],[]
    if not isinstance(raw,list) or len(raw)>2:return [],[{'reason':'role_changes_requires_array_max_two'}]
    rows=[];rejected=[];previous={r['id']:r for r in (profile or {}).get('role_development',[]) if r.get('method')==METHOD}
    for i,r in enumerate(raw):
        try:
            if not isinstance(r,dict) or r.get('target_entity')!='agent_self' or r.get('assertion_type')!='subjective_change':raise ValueError('self_subjective_change_required')
            if r.get('category') not in CATEGORIES or r.get('significance')!='major':raise ValueError('major_role_event_required')
            if r.get('author_conflict') is not False:raise ValueError('author_conflict_or_unknown')
            for key,limit in (('topic',80),('text',280),('importance_reason',300),('lasting_effect',400)):
                if not isinstance(r.get(key),str) or not r[key].strip() or len(r[key])>limit:raise ValueError('invalid_'+key)
            number(r.get('confidence'))
            if r['confidence']<POLICY['min_confidence']:raise ValueError('insufficient_confidence')
            def evidence(items):
                if not isinstance(items,list) or len(items)>8:raise ValueError('invalid_evidence')
                out=[]
                for e in items:
                    if not isinstance(e,dict) or e.get('memory_id') not in episodes:raise ValueError('unknown_memory')
                    q=e.get('quote');ex=episodes[e['memory_id']]
                    if not isinstance(q,str) or not q.strip() or len(q)>700 or q not in ex['external_event']['text']:raise ValueError('external_event_quote_required')
                    if e['memory_id'] not in [x['memory_id'] for x in out]:out.append({'memory_id':e['memory_id'],'quote':q})
                return out
            ev=evidence(r.get('evidence'));counter=evidence(r.get('counterevidence',[]))
            if not ev:raise ValueError('missing_evidence')
            if counter:raise ValueError('unresolved_counterevidence')
            ids={e['memory_id'] for e in ev};scopes={episodes[m]['scope'] for m in ids}
            if len(scopes)!=1:raise ValueError('mixed_scopes')
            majors=r.get('major_memory_ids')
            if not isinstance(majors,list) or not majors or any(not isinstance(m,str) or m not in ids for m in majors):raise ValueError('major_event_evidence_required')
            if any(episodes[m]['external_event'].get('major_event') is not True for m in majors):raise ValueError('recorded_major_event_required')
            previous_id=r.get('candidate_id');old=previous.get(previous_id) if isinstance(previous_id,str) else None
            if previous_id is not None and (not old or old.get('status')!='pending' or old['category']!=r['category'] or old['topic']!=r['topic'] or old['scope']!=next(iter(scopes))):raise ValueError('candidate_identity_mismatch')
            rows.append({k:copy.deepcopy(r[k]) for k in ('category','topic','text','importance_reason','lasting_effect','confidence')} |
                {'candidate_id':previous_id,'evidence':ev,'major_memory_ids':list(dict.fromkeys(majors)), 'scope':next(iter(scopes)),
                 'significance':'major','author_conflict':False,'assertion_type':'subjective_change'})
        except (ValueError,TypeError,KeyError) as ex:
            rejected.append({'index':i,'candidate_id':r.get('candidate_id') if isinstance(r,dict) else None,'reason':str(ex)[:160]})
    return rows,rejected


def apply_changes(profile,changes,episodes,job_id,strength,*,at=None):
    if not changes:return [],[]
    ts=now() if at is None else at;notes=profile.setdefault('role_development',[]);added=[];decisions=[]
    scope_used={};last_applied=max([r.get('applied_at',0) for r in notes if r.get('method')==METHOD],default=0)
    for r in notes:
        if r.get('method')==METHOD and r.get('status')=='active':scope_used[r['scope']]=scope_used.get(r['scope'],0)+r['weight']
    for c in changes:
        refs=c['evidence'];ids={e['memory_id'] for e in refs};old=next((r for r in notes if r['id']==c['candidate_id']),None)
        # Confirmations must cite the original major event and a fresh later event.
        if old and (not set(old['major_memory_ids'])<=ids or not ids-set(old['source_memory_ids'])):
            decisions.append({'topic':c['topic'],'status':'unchanged','reasons':['需要原重大经历及新的后续记忆']});continue
        exs=[episodes[m] for m in ids];event_ids={digest([e['scope'],e.get('event_id',m)]) for m,e in ((m,episodes[m]) for m in ids)}
        times=[e['occurred_at'] for e in exs];earliest=min(episodes[m]['occurred_at'] for m in c['major_memory_ids'])
        mental=[e for e in exs if (e.get('mental') or {}).get('evaluation_summary') or (e.get('mental') or {}).get('appraisal')]
        later=[e for e in exs if e['occurred_at']>=earliest+POLICY['maturity_seconds']]
        reasons=[]
        if len(event_ids)<POLICY['min_events'] or not later:reasons.append('等待至少24小时后的独立后续记忆')
        if not mental:reasons.append('缺少当时已记录的角色评价')
        if max(times)>ts+300:reasons.append('事件时间尚未到达')
        if strength<=0:reasons.append('学习强度为零')
        if ts-last_applied<POLICY['cooldown_seconds']:reasons.append('距上次人设变化不足24小时')
        if added:reasons.append('本批只允许一项人设变化')
        same=next((r for r in reversed(notes) if r.get('method')==METHOD and r.get('status')=='active' and r['scope']==c['scope'] and r['category']==c['category'] and r['topic']==c['topic']),None)
        weight=min(POLICY['max_item_weight'],(same or {}).get('weight',0)+POLICY['step_weight']*strength)
        if scope_used.get(c['scope'],0)-(same or {}).get('weight',0)+weight>POLICY['max_scope_weight']+1e-9:reasons.append('当前范围的人设补充已达到总权重预算')
        signature=digest([c['scope'],c['category'],c['topic'],sorted(event_ids)])
        if not old and any(r.get('evidence_signature')==signature and r.get('status')=='pending' for r in notes):
            decisions.append({'topic':c['topic'],'status':'unchanged','reasons':['候选已存在，等待新的后续证据']});continue
        if any(r.get('evidence_signature')==signature and r.get('status') in ('active','superseded','rejected') for r in notes):
            decisions.append({'topic':c['topic'],'status':'unchanged','reasons':['同一批经历已处理']});continue
        row={**copy.deepcopy(c),'id':old['id'] if old else 'role-memory:'+signature[:24], 'method':METHOD,
             'source_type':'experience_reflection','status':'pending' if reasons else 'active','weight':0 if reasons else weight,
             'evidence':[{'record_id':'experience:'+r['memory_id'],'quote':r['quote']} for r in refs],
             'source_memory_ids':sorted(ids),'job_id':job_id,'created_at':(old or {}).get('created_at',ts),
             'reviewed_at':ts,'reasons':reasons,'evidence_signature':signature,
             'epistemic_status':'memory_derived_subjective_change_not_identity_fact'}
        row.pop('candidate_id',None)
        if old:old.clear();old.update(row)
        else:
            if reasons and len(pending(profile))>=20:decisions.append({'topic':c['topic'],'status':'unchanged','reasons':['待确认候选已满，未改人设']});continue
            notes.append(row)
        if not reasons:
            if same:same.update(status='superseded',superseded_by=row['id'])
            row['applied_at']=ts;last_applied=ts;added.append(row['id'])
            scope_used[c['scope']]=scope_used.get(c['scope'],0)-(same or {}).get('weight',0)+weight
        decisions.append({'id':row['id'],'topic':c['topic'],'status':row['status'],'reasons':reasons})
    return added,decisions
