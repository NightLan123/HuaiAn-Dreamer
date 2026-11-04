"""D evidence and reviewed tendencies. No neural head or generated-output labels.

All thresholds/features below are explicit engineering choices, not validated
psychometric scales. Raw records stay in their original archive.
"""
from __future__ import annotations
import copy, hashlib, re
from collections import Counter
from .common import now, dumps
from .expression_plan import number

SCHEMA='language-evidence/2'
MIN_EVENTS=2

def signature(value):return hashlib.sha256(dumps(value).encode()).hexdigest()

def text_features(texts):
    content='\n'.join(texts)
    # Exact lexical surface features, not a claimed semantic/rhetorical diagnosis.
    words=re.findall(r'[A-Za-z]+|[\u4e00-\u9fff]',content.lower())
    phrases=re.findall(r'[\u4e00-\u9fff]{2,8}|[A-Za-z]{2,20}',content)
    lengths=[len(t) for t in re.split(r'[。！？!?\n]+',content) if t.strip()]
    return {'characters':len(content),'source_message_lengths':[len(t) for t in texts],
        'sentence_lengths':lengths,'lexical_units':dict(Counter(words).most_common(24)),
        'surface_phrases':dict(Counter(phrases).most_common(12)),
        'question_marks':len(re.findall(r'[?？]',content)),
        'exclamation_marks':len(re.findall(r'[!！]',content)),
        'ellipsis_marks':len(re.findall(r'…+|\.{3,}',content)),
        'quotation_marks':len(re.findall(r'[“”「」]',content)),
        'rhetorical_meaning':None,'measurement':'literal_surface_statistics_not_personality'}

def _filtered(rows,scope,act):
    rows=[r for r in rows if (scope is None or r.get('scope') in ('',scope)) and (act is None or r.get('prior_speech_act')==act)]
    # A declared event split across several source groups remains ONE support unit.
    return rows

def text_summary(p,scope=None,act=None):
    rows=_filtered(p.get('lexical_demonstrations',[]),scope,act)
    groups={}
    for row in rows:groups.setdefault(row.get('independent_event_id',row['id']),[]).append(row)
    words=Counter();phrases=Counter();lengths=[]
    for r in rows:
        f=r['text_features'];words.update(f['lexical_units']);phrases.update(f['surface_phrases']);lengths.extend(f['sentence_lengths'])
    return {'schema':SCHEMA,'effective_events':len(groups),'untimed_events':sum(all(x['at'] is None for x in rs) for rs in groups.values()),
        'mean_sentence_characters':sum(lengths)/len(lengths) if lengths else None,
        'lexical_units':dict(words.most_common(20)),'surface_phrases':dict(phrases.most_common(12)),
        'ellipsis_rate':sum(any(x['text_features']['ellipsis_marks']>0 for x in rs) for rs in groups.values())/len(groups) if groups else None,
        'question_rate':sum(any(x['question'] for x in rs) for rs in groups.values())/len(groups) if groups else None,
        'contexts':dict(Counter(rs[0]['prior_speech_act'] for rs in groups.values())),
        'timing_inferred_from_untimed':False,'semantic_rhetoric':None,
        'source_event_ids':[i for r in rows[-6:] for i in r['source_event_ids']][:24],
        'source_type':'human_text_statistics' if rows else 'unknown','calibrated':False}

def correction_targets(p,turn_id,text):
    if not text:return {}
    row=next((r for r in p.get('observed_ai',[]) if r['turn_id']==turn_id),None)
    if not row:return {}
    act=row.get('plan',{}).get('previous_act','unknown');question=bool(re.search(r'[?？]|吗[。！!]?$',text))
    values={'question_initiation_propensity':float(question)}
    if act not in ('question','unknown'):
        values['response_sufficiency_preference']=float(len(text)<=30 and not question)
    # No timestamp/segmentation inference from a corrected text.
    return values

def feedback_target(p,turn_id,field,value,note,labels):
    if field not in labels or number(value) is None:raise ValueError('请选择有效倾向及 0–1 数值')
    if not isinstance(note,str) or not note.strip() or len(note)>1000:raise ValueError('请填写独立人工评价依据（1–1000 字符）')
    observed=next((r for r in p.get('observed_ai',[]) if r['turn_id']==turn_id),None)
    if not observed or not observed.get('actual_bubbles'):raise ValueError('只能评价有实际成功发送内容的回合')
    out=copy.deepcopy(p);rows=out.setdefault('human_feedback',[])
    key=signature(['explicit_feedback',turn_id,field]);old=next((r for r in rows if r.get('id')==key),None)
    if old and old.get('targets')=={field:value} and old['note']==note:return out
    out['human_feedback']=[r for r in rows if r.get('id')!=key]+[{'id':key,'turn_id':turn_id,'at':now(),
        'rating':'targeted','note':note,'has_corrected_reply':False,
        'targets':{field:value},'source_type':'independent_owner_feedback'}]
    out['version']+=1
    return out

def _evidence(p):
    episodes={r['id']:r for r in p.get('lexical_demonstrations',p.get('demonstrations',[]))}
    rows=[]
    for a in p.get('annotations',[]):
        e=episodes.get(a['episode_id'])
        if not e:continue
        if a['field']=='burst_propensity' and e.get('at') is None:continue
        rows.append({'event_id':e.get('independent_event_id',e['id']),'field':a['field'],'value':a['value'],
            'scope':e['scope'],'authorization_scope':e.get('authorization_scope',e['scope'] or 'self:imported'),
            'person':e.get('person',e.get('speaker','')),'act':e['prior_speech_act'],'source_event_ids':e['source_event_ids'],
            'source_type':'independent_owner_annotation','evidence_at':a['at'],'note':a['note']})
    observed={r['turn_id']:r for r in p.get('observed_ai',[])}
    for f in p.get('human_feedback',[]):
        actual=observed.get(f['turn_id'])
        if not actual or not actual.get('actual_bubbles'):continue
        plan=actual.get('plan',{});scope=plan.get('scope') or ''
        for field,value in f.get('targets',{}).items():
            rows.append({'event_id':'feedback:'+f['turn_id'],'field':field,'value':value,'scope':scope,
                'authorization_scope':scope or 'self:imported','person':plan.get('person_id',''),
                'act':plan.get('previous_act','unknown'),'source_event_ids':[f['turn_id']],
                'source_type':'independent_owner_feedback','evidence_at':f['at'],'note':f['note']})
    return rows

def candidates(p):
    # Latest explicit evaluation of an event/field replaces the old label. An
    # edited/retried evaluation is never an additional independent sample.
    unique={}
    for r in sorted(_evidence(p),key=lambda r:r['evidence_at']):unique[(r['event_id'],r['field'])]=r
    groups={}
    for r in unique.values():groups.setdefault((r['scope'],r['act'],r['field']),[]).append(r)
    out=[]
    for (scope,act,field),rows in sorted(groups.items()):
        rows=sorted(rows,key=lambda r:r['event_id']);values=[r['value'] for r in rows];estimate=sum(values)/len(values)
        reasons=[]
        if len(rows)<MIN_EVENTS:reasons.append('insufficient_independent_events')
        if max(values)-min(values)>.6:reasons.append('conflicting_evidence_requires_more_review')
        cid=signature([scope,act,field]);revision=signature(rows)
        old=next((r for r in p.get('applied_tendencies',[]) if r['id']==cid),None)
        if old and old['evidence_digest']==revision:reasons.append('already_applied')
        recent=next((r for r in reversed(p.get('review_history',[])) if r['candidate_id']==cid and r.get('evidence_digest')==revision),None)
        if recent and recent['action']=='reject':reasons.append('owner_rejected_current_evidence')
        out.append({'id':cid,'field':field,'scope':scope,'prior_speech_act':act,'estimate':estimate,
            'effective_events':len(rows),'evidence_digest':revision,'evidence':rows,'eligible':not reasons,
            'reasons':reasons,'status':'applied' if 'already_applied' in reasons else 'ready_for_review' if not reasons else 'not_adopted',
            'threshold':{'minimum_independent_events':MIN_EVENTS,'max_value_spread':.6,'calibrated':False},
            'source_type':'independent_human_evaluation','neural_head':'not_trained'})
    return out

def unusable_feedback(p):
    return [{'turn_id':r['turn_id'],'reason':'no_explicit_target_or_corrected_example','note':r.get('note','')}
        for r in p.get('human_feedback',[]) if not r.get('targets')][-20:]

def applied(p,scope=None,act=None):
    active={r['id']:r for r in candidates(p)}
    out=[]
    for r in p.get('applied_tendencies',[]):
        if scope is not None and r['scope'] not in ('',scope):continue
        if act is not None and r['prior_speech_act']!=act:continue
        # New/removed/resegmented evidence invalidates a stale application until
        # re-reviewed; keeping its history does not silently keep it active.
        c=active.get(r['id'])
        if c and c['evidence_digest']==r['evidence_digest'] and not (set(c['reasons'])-{'already_applied'}):out.append(copy.deepcopy(r))
    return out

def review(p,body,gate):
    if type(body.get('expected_version')) is not int or body['expected_version']!=p['version']:raise ValueError('语言档案已变化，请刷新后重新审核')
    cid=body.get('candidate_id');action=body.get('action')
    c=next((r for r in candidates(p) if r['id']==cid),None)
    if c is None or action not in ('apply','reject','revoke'):raise ValueError('候选或审核操作无效')
    if body.get('evidence_digest')!=c['evidence_digest']:raise ValueError('候选证据已变化，请重新审核')
    if not isinstance(body.get('note'),str) or not body['note'].strip() or len(body['note'])>1000:raise ValueError('请填写审核理由（1–1000 字符）')
    reasons=[];strength=1.
    if action=='apply':
        reasons.extend(c['reasons'])
        for r in c['evidence']:
            g=gate(r['authorization_scope'],r['person'])
            if not g['allowed']:reasons.extend(g['reasons'])
            strength=min(strength,g.get('strength',1.))
    if reasons:return copy.deepcopy(p),{'ok':False,'reasons':sorted(set(reasons)),'changed_fields':[],'version':p['version']}
    out=copy.deepcopy(p);old=next((r for r in out.get('applied_tendencies',[]) if r['id']==cid),None)
    out['applied_tendencies']=[r for r in out.get('applied_tendencies',[]) if r['id']!=cid]
    if action=='apply':out['applied_tendencies'].append({**{k:copy.deepcopy(c[k]) for k in ('id','field','scope','prior_speech_act','estimate','effective_events','evidence_digest','source_type')},'learning_strength':strength,'source_event_ids':sorted({i for e in c['evidence'] for i in e['source_event_ids']})})
    out['version']+=1;changed=[{'field':c['field'],'scope':c['scope'],'prior_speech_act':c['prior_speech_act'],
        'before':old['estimate'] if old else None,'after':c['estimate'] if action=='apply' else None}]
    entry={'candidate_id':cid,'evidence_digest':c['evidence_digest'],'action':action,'at':now(),
        'note':body['note'],'evidence':copy.deepcopy(c['evidence']),'learning_strength':strength,'version_before':p['version'],'version_after':out['version'],'changed_fields':changed}
    out.setdefault('review_history',[]).append(entry)
    return out,{'ok':True,'version':out['version'],'changed_fields':changed,'review':entry,'reasons':[]}

def validate(p,labels):
    for key in ('lexical_demonstrations','applied_tendencies','review_history'):
        if key in p and (not isinstance(p[key],list) or len(p[key])>100000):raise ValueError('语言学习扩展格式无效')
    for r in p.get('lexical_demonstrations',[]):
        if not isinstance(r,dict) or not isinstance(r.get('id'),str) or not isinstance(r.get('source_event_ids'),list) or not r['source_event_ids'] or r.get('source_type')!='authorized_human_demonstration' or not isinstance(r.get('text_features'),dict):raise ValueError('语言文本证据缺少原始来源')
        if r.get('at') is None and any(k in r for k in ('gaps_seconds','bubble_count')):raise ValueError('无时间资料不能包含时序学习结果')
    for r in p.get('human_feedback',[]):
        if not isinstance(r.get('targets',{}),dict) or any(k not in labels or number(v) is None for k,v in r.get('targets',{}).items()):raise ValueError('人工语言目标无效')
    cs={r['id']:r for r in candidates(p)}
    for h in p.get('review_history',[]):
        if not isinstance(h,dict) or h.get('action') not in ('apply','reject','revoke') or not isinstance(h.get('candidate_id'),str) or not isinstance(h.get('evidence_digest'),str) or not isinstance(h.get('changed_fields'),list):raise ValueError('语言审核历史无效')
    for r in p.get('applied_tendencies',[]):
        if not isinstance(r,dict) or r.get('field') not in labels or number(r.get('estimate')) is None or number(r.get('learning_strength',1.)) is None or not isinstance(r.get('evidence_digest'),str):raise ValueError('已审核语言倾向格式无效')
        # Historic applications may be stale, but may never fabricate a matching
        # current evidence revision's field or estimate during backup import.
        if not any(h['action']=='apply' and h['candidate_id']==r.get('id') and h['evidence_digest']==r['evidence_digest'] for h in p.get('review_history',[])):raise ValueError('语言倾向缺少对应的人工审核记录')
        c=cs.get(r.get('id'))
        if c and c['evidence_digest']==r['evidence_digest'] and (c['effective_events']<MIN_EVENTS or 'conflicting_evidence_requires_more_review' in c['reasons'] or any(r.get(k)!=c[k] for k in ('field','scope','prior_speech_act','estimate','effective_events'))):raise ValueError('已应用倾向与原始人工证据不一致')
