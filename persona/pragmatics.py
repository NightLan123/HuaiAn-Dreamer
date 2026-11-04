"""Provenance-separated pragmatic demonstrations and observed delivery metrics.

These are descriptive episode statistics, not questionnaire scores, neural
training, or calibrated personality predictions. A four-bubble burst is ONE
episode. The legacy PMM checkpoint and all long-term traits are untouched.
"""
from __future__ import annotations
import copy, datetime, hashlib, math, re
from collections import Counter
from .common import dumps, now
from .expression_plan import speech_act, number
from . import language_learning as ll

SCHEMA = 'pragmatic-style/1'
LABELS = {'response_sufficiency_preference':'短回应后停止（示范代理指标）',
          'question_initiation_propensity':'发起问题的比例',
          'topic_progression_tendency':'主动推进话题',
          'ellipsis_and_understatement':'语用省略与低强度表达',
          'yield_after_acknowledgement':'简短认同后让轮',
          'burst_propensity':'多气泡使用比例'}


def empty():
    return {'schema':SCHEMA, 'version':0, 'demonstrations':[], 'untimed_record_ids':[],
            'observed_ai':[], 'human_feedback':[], 'annotations':[], 'calibrated':False,
            'mechanism':'episode_statistics_uncalibrated', 'neural_head':'not_trained',
            'evidence_schema':'language-evidence/2', 'lexical_demonstrations':[],
            'applied_tendencies':[], 'review_history':[]}


def timestamp(value):
    try:
        n = float(value)
    except (ValueError, TypeError):
        try:
            parsed=datetime.datetime.fromisoformat(str(value).replace('Z','+00:00'))
            if parsed.tzinfo is None:return None  # Unknown timezone is not a reliable sending time.
            n=parsed.timestamp()
        except (ValueError, OverflowError): return None
    return n if math.isfinite(n) and 0 < n < 253402300799 else None


def rebuild(current, records):
    out = copy.deepcopy(current or empty()); known = {}; untimed = []
    for r in records:
        if r.get('source') not in ('imported','human') or r.get('language_authorized') is False: continue
        if r['id'] in known:
            if known[r['id']].get('text')!=r.get('text'):raise ValueError('语言证据同一 ID 对应不同原文')
            continue
        known[r['id']] = r
    # Explicit predecessor links define adjacency. Sorting alone never supplies it.
    ordered = sorted(known.values(), key=lambda r:(r.get('scope',''), r.get('conversation_id','') or r.get('batch_id',''), r.get('thread_id',''), timestamp(r.get('timestamp')) or 0, r['id']))
    groups=[];by_id={}
    for r in ordered:
        at=timestamp(r.get('timestamp'))
        if at is None:untimed.append(r['id'])
        key=(r.get('scope',''),r.get('conversation_id','') or r.get('batch_id',''),r.get('thread_id',''),r['speaker'])
        by_id[r['id']]={'record':r,'at':at,'key':key}
    # Walk source chains even when untimed ID sorting differs from source order.
    consumed=set()
    def predecessor(r):return r.get('previous_record_id') or (r.get('context_record_id') if not r.get('context') else None)
    successors={}
    for r in ordered:
        previous=predecessor(r)
        if previous:successors.setdefault(previous,[]).append(r)
    def linked(a,b):
        x,y=by_id[a['id']],by_id[b['id']]
        if x['key']!=y['key']:return False
        if bool(x['at'] is None)!=bool(y['at'] is None):return False
        if a.get('event_id') and b.get('event_id') and a['event_id']!=b['event_id']:return False
        return x['at'] is None or 0<=y['at']-x['at']<=15
    starts=[r for r in ordered if predecessor(r) not in by_id or not linked(by_id[predecessor(r)]['record'],r)]
    for first in starts+ordered:
        if first['id'] in consumed:continue
        rows=[first];consumed.add(first['id'])
        while True:
            options=[r for r in successors.get(rows[-1]['id'],[]) if r['id'] not in consumed and linked(rows[-1],r)]
            if len(options)!=1:break  # Ambiguous source graph is not a burst.
            rows.append(options[0]);consumed.add(options[0]['id'])
        groups.append(rows)
    episodes=[];lexical=[]
    for rows in groups:
        first=rows[0];texts=[r['text'] for r in rows];content='\n'.join(texts);ids=[r['id'] for r in rows]
        at=timestamp(first.get('timestamp'));act=speech_act(first.get('context','')) if first.get('context') else 'unknown'
        ended=not re.search(r'[?？]|吗[。！!]?$',content);short=len(content)<=30 and ended
        declared={r.get('event_id') for r in rows if r.get('event_id')}
        event_key=['declared',first.get('scope',''),first.get('conversation_id') or ('' if first.get('scope') else first.get('batch_id','')),first.get('thread_id',''),first['speaker'],next(iter(declared))] if len(declared)==1 else ['source_chain',*by_id[first['id']]['key'],ids]
        row={'id':hashlib.sha256(dumps(ids).encode()).hexdigest()[:32],
            'independent_event_id':hashlib.sha256(dumps(event_key).encode()).hexdigest()[:32],
            'source_type':'authorized_human_demonstration','content_source':first['source'],
            'scope':first.get('scope',''),'authorization_scope':first.get('authorization_scope',first.get('scope','') or 'self:imported'),
            'person':first.get('person',first['speaker']),'speaker':first['speaker'],
            'conversation_id':first.get('conversation_id','') or first.get('batch_id',''),'thread_id':first.get('thread_id',''),
            'at':at,'source_event_ids':ids,'original_event_ids':sorted(declared),'content_sha256':hashlib.sha256(content.encode()).hexdigest(),
            'deduplication_basis':'scoped_original_event_or_explicit_source_chain',
            'incoming_record_id':first.get('context_record_id'),'prior_speech_act':act,
            'question':not ended,'short_response':short,'ack_yield':short if act in ('invitation','tentative_interest') else None,
            'independent_episodes':1,'timing_status':'known_source_times' if at is not None else 'unknown_no_reliable_timestamp',
            'text_features':ll.text_features(texts)}
        lexical.append(row)
        if at is not None:
            episodes.append({**row,'bubble_count':len(rows),'bubble_lengths':[len(t) for t in texts],
                'gaps_seconds':[timestamp(rows[i]['timestamp'])-timestamp(rows[i-1]['timestamp']) for i in range(1,len(rows))],
                'grouping_rule':'source_adjacency_and_15s_uncalibrated'})
    episodes.sort(key=lambda r:(r['at'],r['id']));lexical.sort(key=lambda r:(r['at'] or 0,r['id']));untimed.sort()
    if out['demonstrations']!=episodes or out['untimed_record_ids']!=untimed or out.get('lexical_demonstrations')!=lexical:
        ids={r['id'] for r in lexical}
        archived=[r for r in out.get('annotations',[]) if r['episode_id'] not in ids]
        if archived:out.setdefault('archived_annotations',[]).extend([{**r,'archive_reason':'episode_resegmented'} for r in archived])
        out['annotations']=[r for r in out.get('annotations',[]) if r['episode_id'] in ids]
        out.update(demonstrations=episodes,lexical_demonstrations=lexical,untimed_record_ids=untimed,version=out['version']+1,updated_at=now(),evidence_schema='language-evidence/2')
    out.setdefault('applied_tendencies',[]);out.setdefault('review_history',[])
    return out


def ratio(rows, field):
    unique={r.get('independent_event_id',r.get('id',str(i))):r for i,r in enumerate(rows)}
    values = [r[field] for r in unique.values() if r.get(field) is not None]
    if not values: return {'estimate':None,'effective_episodes':0,'support':0,'counterevidence':0,'confidence':None,'source_type':'unknown'}
    yes = sum(bool(v) for v in values); n = len(values); p = yes/n
    # Wilson 95% sampling interval; does not measure construct validity.
    z = 1.96; center = (p+z*z/(2*n))/(1+z*z/n); spread = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
    return {'estimate':p,'effective_episodes':n,'support':yes,'counterevidence':n-yes,'confidence':None,
            'sampling_interval':[max(0,center-spread),min(1,center+spread)], 'source_type':'human_episode_statistics'}


def summary(current, scope=None, act=None):
    p = current or empty(); rows = p['demonstrations']
    if scope is not None: rows = [r for r in rows if r['scope'] in ('',scope)]
    if act is not None: rows = [r for r in rows if r['prior_speech_act'] == act]
    counts=Counter(r.get('independent_event_id',r['id']) for r in rows)
    # Disconnected pieces declaring one event have unknown rhythm as a whole.
    rows = [{**r,'burst':r['bubble_count']>1} for r in rows if counts[r.get('independent_event_id',r['id'])]==1]
    fields = {k:ratio([], '') for k in LABELS}
    fields.update(response_sufficiency_preference=ratio([r for r in rows if r['prior_speech_act'] not in ('question','unknown')],'short_response'),
                  question_initiation_propensity=ratio(rows,'question'), yield_after_acknowledgement=ratio(rows,'ack_yield'), burst_propensity=ratio(rows,'burst'))
    policy_statistics=copy.deepcopy(fields)
    ids={r['id'] for r in rows}
    for field in LABELS:
        labels=[r for r in p.get('annotations',[]) if r['episode_id'] in ids and r['field']==field]
        if labels:fields[field]={'estimate':sum(r['value'] for r in labels)/len(labels),'effective_episodes':len(labels),'support':sum(r['value']>=.5 for r in labels),
            'counterevidence':sum(r['value']<.5 for r in labels),'confidence':None,'source_type':'human_episode_annotation'}
    return {'schema':SCHEMA,'version':p['version'],'fields':fields,'policy_statistics':policy_statistics,'effective_episodes':len(rows),
            'contexts':len({(r['scope'],r['conversation_id']) for r in rows}),
            'days':len({datetime.datetime.fromtimestamp(r['at'],datetime.timezone.utc).date().isoformat() for r in rows}),
            'bubble_distribution':dict(Counter(str(r['bubble_count']) for r in rows)),
            'burst_context_distribution':{a:ratio([r for r in rows if r['prior_speech_act']==a],'burst') for a in sorted({r['prior_speech_act'] for r in rows})},
            'untimed_records':sum(len(r['source_event_ids']) for r in p.get('lexical_demonstrations',[]) if r['at'] is None and (scope is None or r['scope'] in ('',scope)) and (act is None or r['prior_speech_act']==act)) if 'lexical_demonstrations' in p else len(p['untimed_record_ids']) if scope is None else 0, 'calibrated':False,'neural_head':'not_trained',
            'source_event_ids':[v for r in rows[-6:] for v in r['source_event_ids']][:24],
            'text_style':ll.text_summary(p,scope,act),'reviewed_tendencies':ll.applied(p,scope,act),
            'note':'按独立事件描述示范习惯；抽样区间不表示心理效度。无时间戳记录仅用于字词、句式、长度及语境，不推断发送间隔。'}


def for_planner(p,scope,act):
    # Unreviewed annotations remain visible as descriptive evidence in the UI,
    # never as applied policy preferences in either model's input.
    s=summary(p,scope,act);s['fields']=copy.deepcopy(s['policy_statistics'])
    for v in s['reviewed_tendencies']:
        s['fields'][v['field']]={'estimate':v['estimate'],'effective_episodes':v['effective_events'],'source_type':'reviewed_owner_evidence','confidence':None}
    return s


def observe(current, turn_id, plan, parts, receipts, status,receipt_states=None):
    out = copy.deepcopy(current or empty())
    row = {'turn_id':turn_id,'at':now(),'source_type':'actual_ai_behavior_not_training_truth',
           'plan':copy.deepcopy(plan), 'status':status, 'actual_bubbles':len(parts),
           'message_ids':[r['message_id'] for r in receipts], 'bubble_lengths':[len(p) for p in parts],
           'question':any(re.search(r'[?？]',p) for p in parts), 'receipt_states':copy.deepcopy(receipt_states or [])}
    # Upsert, including later receipt reconciliation. It is still ONE episode.
    out['observed_ai'] = [r for r in out['observed_ai'] if r['turn_id'] != turn_id] + [row]
    return out


def feedback(current, turn_id, rating, note, corrected_reply=None):
    out = copy.deepcopy(current or empty())
    checksum=hashlib.sha256(dumps([turn_id,rating,str(note)[:2000],corrected_reply]).encode()).hexdigest()
    if any(r.get('feedback_id')==checksum for r in out['human_feedback']):return out
    out['version']+=1
    out['human_feedback'].append({'feedback_id':checksum,'turn_id':turn_id,'at':now(),'rating':rating,'note':str(note)[:2000],
                                  'has_corrected_reply':bool(corrected_reply),'source_type':'independent_owner_feedback',
                                  'targets':ll.correction_targets(out,turn_id,corrected_reply),
                                  'correction_sha256':hashlib.sha256(corrected_reply.encode()).hexdigest() if corrected_reply else None})
    return out


def status(current):
    p = current or empty()
    return {'profile':summary(p), 'labels':LABELS,'recent':list(reversed(p['observed_ai'][-30:])),
            'demonstration_choices':[{k:r.get(k) for k in ('id','at','scope','prior_speech_act','source_event_ids','timing_status')} for r in p.get('lexical_demonstrations',p['demonstrations'])[-100:]],
            'learning_candidates':ll.candidates(p),'review_history':p.get('review_history',[])[-30:],
            'applied_tendencies':ll.applied(p,None,None),
            'unusable_feedback':ll.unusable_feedback(p),
            'observed_ai_episodes':len(p['observed_ai']), 'observed_bubble_distribution':dict(Counter(str(r['actual_bubbles']) for r in p['observed_ai'])),
            'human_feedback_count':len(p['human_feedback']), 'human_feedback':p['human_feedback'][-20:],
            'evaluation':{k:None for k in ('unnecessary_followup_rate','premature_commitment_rate','response_sufficiency','conversational_burden','redundant_question_rate','naturalness','persona_consistency')},
            'evaluation_note':'自动检查只用于发送前约束；这些质量指标尚无独立人工评测。'}


def annotate(current,episode_id,field,value,note):
    out=copy.deepcopy(current or empty());episode=next((r for r in out.get('lexical_demonstrations',out['demonstrations']) if r['id']==episode_id),None)
    if episode is None or field not in LABELS or number(value) is None:raise ValueError('只能标注有来源的人类示范事件，数值须为 0–1')
    if field=='burst_propensity' and episode.get('at') is None:raise ValueError('无可靠时间戳的资料不能标注多气泡时序倾向')
    if not isinstance(note,str) or not note.strip() or len(note)>1000:raise ValueError('请记录标注依据（1–1000 字符）')
    if any(a['episode_id']==episode_id and a['field']==field and a['value']==value and a['note']==note for a in out.get('annotations',[])):return out
    row={'episode_id':episode_id,'field':field,'value':value,'note':note,'at':now(),'source_event_ids':episode['source_event_ids'],'source_type':'independent_owner_annotation'}
    out['annotations']=[r for r in out.get('annotations',[]) if (r['episode_id'],r['field'])!=(episode_id,field)]+[row]
    out['version']+=1
    return out


def validate(p):
    if p is None: return
    if not isinstance(p,dict) or p.get('schema') != SCHEMA or type(p.get('version')) is not int or p['version'] < 0: raise ValueError('语用倾向版本无效')
    for key in ('demonstrations','untimed_record_ids','observed_ai','human_feedback'):
        if not isinstance(p.get(key),list) or len(p[key])>100000: raise ValueError('语用倾向记录无效')
    for row in p['demonstrations']:
        if not isinstance(row,dict) or row.get('source_type')!='authorized_human_demonstration' or not isinstance(row.get('source_event_ids'),list) or not row['source_event_ids'] or not isinstance(row.get('scope'),str) or timestamp(row.get('at')) is None: raise ValueError('语用示范缺少来源或时间')
        if type(row.get('bubble_count')) is not int or row['bubble_count']<1: raise ValueError('语用示范气泡计数无效')
    for row in p['observed_ai']:
        if not isinstance(row,dict) or not isinstance(row.get('turn_id'),str) or type(row.get('actual_bubbles')) is not int or not 0<=row['actual_bubbles']<=4 or not isinstance(row.get('plan'),dict): raise ValueError('实际表达记录无效')
    for row in p['human_feedback']:
        if not isinstance(row,dict) or not isinstance(row.get('turn_id'),str) or row.get('rating') not in ('helpful','unhelpful','targeted'): raise ValueError('独立语用反馈无效')
    annotations=p.get('annotations',[])
    if not isinstance(annotations,list) or len(annotations)>100000:raise ValueError('语用人工标注无效')
    ids={r['id'] for r in p.get('lexical_demonstrations',p['demonstrations'])};seen=set()
    for row in annotations:
        if not isinstance(row,dict) or row.get('episode_id') not in ids or row.get('field') not in LABELS or number(row.get('value')) is None or not isinstance(row.get('note'),str):raise ValueError('语用人工标注缺少有效原始事件')
        key=(row['episode_id'],row['field'])
        if key in seen:raise ValueError('同一语用事件重复标注')
        seen.add(key)

    ll.validate(p,LABELS)
