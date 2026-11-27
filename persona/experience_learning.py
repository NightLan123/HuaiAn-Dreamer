"""Completed episodic memories -> bounded role development in the existing profile.

This is a scheduler/evidence adapter, not another PMM or a psychometric estimator.
It never trains on the agent's generated wording as personality ground truth.
"""
from __future__ import annotations
import copy
import threading
import time
from .common import now, dumps, uid
from .registry import LONG_IDS, BY_ID, digest, number, update_trait_evidence
from . import traits

KEY='pmm_experience_learning'
SCHEMA='experience-learning/1'
DEFAULT={'enabled':True,'new_memories':10,'max_attempts':3,'retry_seconds':300}
PROMPT='''[EXPERIENCE_PERSONALITY_LEARNING]
整理同一角色已经真实经历的事件，提出慢速角色倾向候选，不是心理量表测量，也不执行人格写入。
每条经历区分：external_event 是对方实际说过的话；outcome 是实际行动与送达记录、可能的后续反应；mental 是当时系统已记录的情绪与主观评价；person_views 是当时对特定人物的看法。
依据反复出现的事件、结果和个人反应，判断对角色自身的长期倾向有何支持与反例。不能把对方的性格直接赋给角色；不能因为角色自己说了某句话便证明其人格；一时情绪不是长期特质。未知结果保持未知。
只返回一个JSON对象 {"observations":[{"target_entity":"agent_self","feature_id":"registry中的ID","estimate":0.5,"confidence":0.5,"reason":"简短依据与反例","evidence":[{"memory_id":"给定ID","source":"external_event","quote":"事件中的逐字片段"}]}],"summary":"简短结论"}。
同一经历也可引用 source=delivered_action，以 outcome.actual_reply 中已确认公开的逐字片段为据，只说明角色当时怎样回应。说“我道过歉”只能证明说过这句话，不能据此认定曾经道歉。mental 和 person_views 只供解释，不能作为行为来源；未标明 delivery_basis 的回复不得引用。
estimate 为0..1的工程角色倾向候选；每项需要具体外部事件引用和角色受影响的理由。无充分依据返回空 observations，不要求凑数或强制变化。优先最多4项最有依据的变化；每项选有代表性的短原文引用和简短理由，不复制整段经历，整个输出控制在2000 tokens内。禁止返回情绪更新、神经权重、角色身份或无引用的结论。
'''

def settings(policy):
    return {**DEFAULT,**(policy.get('experience') or {})}

def validate_settings(value):
    if not isinstance(value,dict) or type(value.get('enabled')) is not bool:raise ValueError('经历学习开关无效')
    for k,lo,hi in (('new_memories',3,50),('max_attempts',1,3),('retry_seconds',60,86400)):
        if type(value.get(k)) is not int or not lo<=value[k]<=hi:raise ValueError('经历学习设置超出范围：'+k)

def validate_state(state):
    if state is None:return
    if not isinstance(state,dict) or state.get('schema')!=SCHEMA or not isinstance(state.get('consumed'),dict) or not isinstance(state.get('history'),list):raise ValueError('经历学习存档无效')
    number(state.get('started_at'),0,1e13)
    job=state.get('job')
    if job and (not isinstance(job,dict) or job.get('status') not in ('ready','running','failed','completed','partial','evidence_rejected','awaiting_review','rejected','rolled_back') or not isinstance(job.get('memory_ids'),list) or type(job.get('attempts')) is not int):raise ValueError('经历学习任务无效')
    batches=state.get('retry_batches',{})
    if not isinstance(batches,dict):raise ValueError('经历待重试队列无效')
    for group in batches.values():
        if (not isinstance(group,dict) or not isinstance(group.get('event_keys'),list)
            or not all(isinstance(k,str) and k for k in group['event_keys'])
            or type(group.get('attempts')) is not int or group['attempts']<0 or not isinstance(group.get('usage'),dict)):
            raise ValueError('经历待重试记录无效')
        number(group.get('retry_at',0),0,1e13)
    if job and job.get('rollback'):
        from .psychology import validate_profile
        rollback=job['rollback']
        if not isinstance(rollback,dict) or not isinstance(rollback.get('after_digest'),str) or len(rollback['after_digest'])!=64:raise ValueError('经历学习回滚记录无效')
        validate_profile(rollback.get('before'))

def delivery_basis(scope, reply, delivery, committed_parts=None):
    """Bind the cited wording to the actually committed message or ACK prefix."""
    if not isinstance(reply,str) or not reply.strip():
        return None
    if not delivery:
        return 'local_commit' if 'qq' not in scope.split(':') else None
    status=delivery.get('status')
    if status not in ('ACKNOWLEDGED','COMMITTED','DELIVERY_INTERRUPTED','DELIVERY_PARTIAL','PARTIAL_COMMITTED'):
        return None
    receipt=delivery.get('receipt') or {}
    sent=receipt.get('sent') or ([receipt] if receipt.get('message_id') is not None else [])
    if not sent or any(not isinstance(r,dict) or r.get('status')!='ok' or type(r.get('retcode')) is not int
                       or r['retcode']!=0 or r.get('message_id') in (None,'') or r.get('index',i)!=i for i,r in enumerate(sent)):
        return None
    payload=delivery.get('payload') or {}
    batch=payload.get('messages') or ([payload['message']] if payload.get('message') else [])
    if batch:
        committed_parts=[''.join(s.get('data',{}).get('text','') for s in parts if s.get('type')=='text')
                         for parts in batch[:len(sent)]]
    if not committed_parts or len(committed_parts)!=len(sent) or '\n'.join(committed_parts)!=reply:
        return None
    return 'qq_ack' if status in ('ACKNOWLEDGED','COMMITTED') else 'qq_ack_prefix'


def observed_reply(ex):
    out=ex['outcome']
    basis=out.get('delivery_basis')
    if 'delivery_basis' not in out and out.get('delivery')=='LOCAL_COMMITTED':
        basis=delivery_basis(ex['scope'],out.get('actual_reply'),None)
    if basis in ('local_commit','qq_ack','qq_ack_prefix'):
        return out.get('actual_reply') or ''
    return ''


def collect_experience(plan,profile,delivery):
    """Take recorded facts from the commit plan; do not reconstruct inner thought."""
    trace=plan['trace'];session=plan['session'];event=trace.get('event_packet') or {}
    layer=trace.get('trait_affect') or {};decoded=trace.get('decoded') or {}
    semantic=(trace.get('understanding') or {}).get('semantic') or {}
    kinds=[k for k in ('task','social','hostility','value_conflict','novelty') if semantic.get(k,0)>=.5]
    context_label='+'.join(kinds) or 'ordinary_conversation'
    relation=plan.get('relation') or {};dyad=relation.get('dyad') or {}
    person_views=[{'person_id':session['person'],'scope':session['scope'],
        'relationship':{k:copy.deepcopy(relation.get(k)) for k in ('trust','affection','familiarity') if k in relation},
        'beliefs':[{k:copy.deepcopy(r.get(k)) for k in ('kind','statement','uncertainty','knowledge_type','status')} for r in dyad.get('schemata',[]) if r.get('status')=='active'][-16:],
        'changes':copy.deepcopy(trace.get('relationship_update')),'epistemic_status':'recorded_subjective_view_not_external_fact'}]
    person_views.extend({'person_id':None,'person_label':r['person_label'],'scope':session['scope'],
        'relationship':{},'beliefs':[{'statement':r['view'],'uncertainty':1-r['confidence'],'evidence_quote':r['evidence_quote'],'knowledge_type':'inferred'}],
        'changes':{},'epistemic_status':'event_appraisal_not_resolved_identity'} for r in decoded.get('person_appraisals',[]))
    return {'schema':'experienced-event/1','persona_id':profile['id'],'turn_id':plan['turn_id'],
        'event_id':(event.get('raw_message') or {}).get('message_id') or plan['turn_id'],
        'scope':session['scope'],'person':session['person'],'session_id':session['id'],
        'occurred_at':plan['at'],'direct_interaction':session.get('direct_interaction',True),
        'external_event':{'record_id':plan['user_record']['id'],'text':plan['user_record']['text'],
                          'analysis':copy.deepcopy(event.get('events') or []),
                          'intent':(trace.get('understanding') or {}).get('intent'),
                          'major_event':(trace.get('understanding') or {}).get('major_event') is True,
                          'context_label':context_label,'source':'observed_input'},
        'mental':{'trait_version':profile['trait_profile']['version'],
                  'emotion_before':copy.deepcopy(layer.get('emotion_before')),
                  'emotion_after':copy.deepcopy(layer.get('emotion_state')),
                  'appraisal':copy.deepcopy(layer.get('appraisal')),
                  'evaluation_summary':decoded.get('language_condition'),
                  'uncertainties':copy.deepcopy(decoded.get('uncertainties') or []),
                  'decision':{k:copy.deepcopy(trace['decision'].get(k)) for k in ('action','gate','reason','condition_contributions')},
                  'expressive_drive':{k:copy.deepcopy((trace.get('expressive_drive') or {}).get(k)) for k in ('activation','urgency','persistence','expressive_intent','state_revision')}},
        'person_views':person_views,
        'outcome':{'action':trace['decision']['action'],'actual_reply':plan.get('reply',''),
                   'delivery':(delivery or {}).get('status') or ('LOCAL_COMMITTED' if plan.get('reply') else 'NO_ACTION'),
                   'delivery_basis':delivery_basis(session['scope'],plan.get('reply'),delivery),
                   'emotion_after_action':copy.deepcopy((plan.get('metadata') or {}).get('pmm_affect',{}).get('emotion')),
                   'external_followup':None,'external_result_known':False},
        'eligibility':'completed_direct_experience' if session.get('direct_interaction',True) else 'observation_requires_permission'}

def compact_episode(mid,ex,text_limit=700):
    mental=ex['mental'];outcome=ex['outcome'];emotion=mental.get('emotion_after') or {}
    app=mental.get('appraisal') or {}
    return {'memory_id':mid,'occurred_at':ex['occurred_at'],'scope':ex['scope'],'person':ex['person'],
        'external_event':{**{k:ex['external_event'].get(k) for k in ('context_label','intent','major_event')},'text':ex['external_event']['text'][:text_limit]},
        'mental':{'emotion':{k:emotion.get(k) for k in ('valence','arousal','stress','engagement')},
                  'appraisal':{k:app.get(k) for k in ('checks','estimates','appraisal_checks') if k in app},
                  'evaluation_summary':str(mental.get('evaluation_summary') or '')[:250]},
        'person_views':[{'person_id':p['person_id'],'person_label':p.get('person_label'),
            'relationship':{k:v for k,v in p['relationship'].items() if k in ('trust','affection','familiarity')},
            'beliefs':[{k:(v[:180] if isinstance(v,str) else v) for k,v in r.items()} for r in p.get('beliefs',[])[:4]]} for p in ex['person_views'][:6]],
        'outcome':{'action':outcome['action'],'delivery':outcome['delivery'],'actual_reply':observed_reply(ex)[:300],
                   'delivery_basis':outcome.get('delivery_basis') or ('local_commit' if observed_reply(ex) and outcome['delivery']=='LOCAL_COMMITTED' else None),
                   'external_followup':outcome.get('external_followup'),'external_result_known':outcome.get('external_result_known',False)}}

class RejectedObservations(ValueError):
    def __init__(self,report):
        self.report=report
        super().__init__('本批人格观察均未通过证据检查')


def validate_observation(row,episodes):
    if not isinstance(row,dict) or row.get('target_entity')!='agent_self' or row.get('feature_id') not in (*LONG_IDS,*traits.DISPOSITIONS):
        raise ValueError('候选须指向角色自身的长期构念')
    number(row.get('estimate'))
    if number(row.get('confidence'))<=0:raise ValueError('缺少有效置信度')
    if not isinstance(row.get('reason'),str) or not row['reason'].strip() or len(row['reason'])>1200:
        raise ValueError('缺少有界的变化依据')
    evidence=row.get('evidence')
    if not isinstance(evidence,list) or not 1<=len(evidence)<=50:raise ValueError('缺少事件引用')
    refs=[]
    for item in evidence:
        if not isinstance(item,dict) or not isinstance(item.get('memory_id'),str) or item['memory_id'] not in episodes:
            raise ValueError('引用未指向本批记忆')
        mid=item['memory_id'];ex=episodes[mid];source=item.get('source','external_event');quote=item.get('quote')
        if source=='external_event':original=ex['external_event']['text']
        elif source=='delivered_action':original=observed_reply(ex)
        else:raise ValueError('该来源不能作为行为证据')
        if not isinstance(quote,str) or not quote.strip() or len(quote)>2000 or quote not in original:
            raise ValueError('引文未匹配指定事件原文或已送达回复')
        ref={'memory_id':mid,'source':source,'quote':quote}
        if ref not in refs:refs.append(ref)
    return {'target_entity':'agent_self','feature_id':row['feature_id'],'estimate':row['estimate'],
            'confidence':min(.5,row['confidence']),'reason':row['reason'],'evidence':refs}


def validate_report(value,episodes,*,role_episodes=None,profile=None):
    if not isinstance(value,dict) or not isinstance(value.get('observations'),list) or len(value['observations'])>16:raise ValueError('经历学习需要带 observations 的单个对象')
    rows=[];rejections=[];seen=set()
    for index,row in enumerate(value['observations']):
        try:
            observation=validate_observation(row,episodes)
            if observation['feature_id'] in seen:raise ValueError('同一构念重复候选')
        except ValueError as error:
            refs=row.get('evidence') if isinstance(row,dict) else None
            ids=[r.get('memory_id') if isinstance(r,dict) else None for r in refs] if isinstance(refs,list) else []
            identified=bool(ids) and all(isinstance(mid,str) and mid in episodes for mid in ids)
            rejections.append({'index':index,'feature_id':row.get('feature_id') if isinstance(row,dict) and row.get('feature_id') in (*LONG_IDS,*traits.DISPOSITIONS) else None,
                'memory_ids':list(dict.fromkeys(ids)) if identified else [],'reason':str(error),'unattributed':not identified})
            continue
        seen.add(observation['feature_id']);rows.append(observation)
    from .memory_role_changes import parse_changes
    role_changes,rejected=parse_changes(value.get('role_changes'),role_episodes or episodes,profile)
    report={'observations':rows,'summary':str(value.get('summary') or '')[:1000],
        'role_changes':role_changes,'role_rejections':rejected,'observation_rejections':rejections}
    if rejections and not rows and not role_changes and not rejected:raise RejectedObservations(report)
    return report

def apply_report(profile,report,episodes,job_id,strength,apply,*,role_episodes=None,review_at=None):
    """Use canonical evidence and the existing cross-context slow promotion rule."""
    p=copy.deepcopy(profile);records=[];rows=[];dispositions=[]
    stored={r['id']:r for r in p['psychology']['evidence_records']}
    existing_observations=p['psychology']['observations']+p['trait_profile']['disposition_observations']
    old_ids={o['id'] for o in existing_observations}
    seen_events={(o['feature_id'],stored[e['record_id']]['experience_event_key'])
                 for o in existing_observations for e in o['evidence']
                 if stored.get(e['record_id'],{}).get('experience_event_key')}
    source_episodes={**(role_episodes or {}),**episodes}
    by_source={}
    for mid,ex in source_episodes.items():
        rid='experience:'+mid;label=ex['external_event']['context_label']
        record={'id':rid,'speaker':ex['person'],'person':ex['person'],'text':ex['external_event']['text'],
            'source':'observed','scope':ex['scope'],'timestamp':ex['occurred_at'],'event_id':ex['event_id'],
            'subject_entity':'agent_self','evidence_kind':'experienced_event','memory_id':mid,
            'experience_turn_id':ex['turn_id'],'experience_timestamp':ex['occurred_at'],
            'experience_event_key':digest([profile['id'],ex['scope'],ex['event_id']]),
            'experience_context_key':digest([ex['scope'],label]),'experience_context_label':label}
        records.append(record);by_source[mid,'external_event']=record
        reply=observed_reply(ex)
        if reply:
            action={**record,'id':'experience-action:'+mid,'speaker':profile['id'],'role':'assistant',
                    'text':reply,'evidence_channel':'delivered_action','external_record_id':rid,
                    'delivery_basis':ex['outcome'].get('delivery_basis') or 'local_commit'}
            by_source[mid,'delivered_action']=action
    for row in report['observations']:
        refs=[]
        for e in row['evidence']:
            source=e.get('source','external_event')
            record=by_source.get((e['memory_id'],source))
            if not record or not e['quote'] or e['quote'] not in record['text']:
                raise ValueError('观察来源已变化，保留记忆等待重新整理')
            if (row['feature_id'],record['experience_event_key']) in seen_events:continue
            if source=='delivered_action' and record not in records:records.append(record)
            refs.append({'record_id':record['id'],'quote':e['quote']})
        if not refs:continue
        item={**row,'evidence':refs}
        if row['feature_id'] in traits.DISPOSITIONS:
            item['timeframe']=traits.DISPOSITIONS[row['feature_id']]['required_timeframe'];dispositions.append(item)
        else:rows.append(item)
    p['psychology'],stats=update_trait_evidence(p['psychology'],rows,records,'observed')
    # Disposition observation references need the same canonical evidence rows.
    ids={r['id'] for r in p['psychology']['evidence_records']}
    required={e['record_id'] for r in dispositions for e in r['evidence']}
    required.update(r['external_record_id'] for r in records if r.get('evidence_channel')=='delivered_action')
    required.update('experience:'+e['memory_id'] for r in report.get('role_changes',[]) for e in r['evidence'])
    p['psychology']['evidence_records'].extend(r for r in records if r['id'] in required and r['id'] not in ids)
    p,ds=traits.observe_dispositions(p,dispositions,records,'observed')
    reasons={r['feature_id']:r['reason'] for r in report['observations']}
    accepted_observations=[]
    by_id={r['id']:r for r in records}
    for o in p['psychology']['observations']+p['trait_profile']['disposition_observations']:
        if o['id'] not in old_ids and o.get('feature_id') in reasons:
            o.update(experience_job_id=job_id,development_reason=reasons[o['feature_id']],measurement_claim=False)
            sources=[]
            for evidence in o['evidence']:
                record=by_id[evidence['record_id']]
                ref={'memory_id':record['memory_id'],'source':record.get('evidence_channel','external_event')}
                if ref not in sources:sources.append(ref)
            accepted_observations.append({'feature_id':o['feature_id'],'sources':sources})
    p,result=traits.review(p,apply and bool(stats['accepted']+ds['accepted']),strength=strength,experience_only=True,review_at=review_at)
    from .memory_role_changes import apply_changes
    fresh_role_changes=[r for r in report.get('role_changes',[]) if any(e['memory_id'] in episodes for e in r['evidence'])]
    additions,role_decisions=apply_changes(p,fresh_role_changes,source_episodes,job_id,strength,at=review_at) if apply else ([],[])
    role_decisions.extend({'topic':r['topic'],'status':'unchanged','reasons':['本批没有新的支持记忆']} for r in report.get('role_changes',[]) if r not in fresh_role_changes)
    if apply:
        for rejected in report.get('role_rejections',[]):
            if rejected.get('reason') not in ('unresolved_counterevidence','author_conflict_or_unknown'):continue
            for row in p.get('role_development',[]):
                if row['id']==rejected.get('candidate_id') and row['status']=='pending':row.update(status='rejected',reasons=[rejected['reason']],reviewed_at=now())
    result.update(role_supplements_added=len(additions),role_supplement_ids=additions,
        role_decisions=role_decisions,role_rejections=report.get('role_rejections',[]),
        role_update_policy='major_memory_only; independent_of_trait_numbers; delayed_and_bounded')
    if (stats['accepted']+ds['accepted'] or p.get('role_development')!=profile.get('role_development')) and not result['promoted']:p['revision']+=1;p['updated_at']=now()
    result.update(accepted=stats['accepted']+ds['accepted'],accepted_observations=accepted_observations,
                  summary=report['summary'],job_id=job_id)
    for h in p['trait_profile']['promotion_history']:
        if h.get('method')=='experienced-role-development/1' and not h.get('job_id'):h['job_id']=job_id
    return p,result


def event_key(ex):
    return digest([ex['scope'],ex['event_id']])


def queue_retry(state,job,keys,opts):
    batches=state.setdefault('retry_batches',{})
    group_id=job.get('retry_of') or job['id']
    held=[k for k in batches.get(group_id,{}).get('event_keys',[]) if k not in job['event_keys'] and k not in state['consumed']]
    keys=list(dict.fromkeys([*keys,*held]))
    if not keys:
        batches.pop(group_id,None)
        return
    job['retry_at']=now()+opts['retry_seconds']*max(1,job['attempts'])
    batches[group_id]={'event_keys':list(keys),'attempts':job['attempts'],'retry_at':job['retry_at'],
                       'usage':copy.deepcopy(job['usage'])}


def next_batch(state,available,opts):
    groups=dict(state.get('retry_batches',{}))
    last=state.get('job') or {}
    # Previously saved failures predate the per-batch retry queue.
    if last.get('status')=='failed' and (last.get('retry_of') or last['id']) not in groups:
        groups[last.get('retry_of') or last['id']]=last
    ids={event_key(ex):mid for mid,ex in available.items()}
    reserved=set()
    for group_id,group in groups.items():
        reserved.update(group['event_keys'])
        keys=[k for k in group['event_keys'] if k in ids]
        if keys and group['attempts']<opts['max_attempts'] and now()>=group.get('retry_at',0):
            return group_id,group,{ids[key]:available[ids[key]] for key in keys}
    fresh=[mid for key,mid in ids.items() if key not in reserved]
    count=opts['new_memories']
    return None,{},({mid:available[mid] for mid in fresh[:count]} if len(fresh)>=count else {})

class ExperienceLearning:
    def __init__(self,learning):
        self.learning=learning;self.e=learning.e;self.st=learning.st;self.thread=None
        self.research_event_time=None
        with self.st.lock,self.st.db:
            state=self.state();validate_state(state)
            if (state.get('job') or {}).get('status')=='running':
                job=state['job'];job.update(status='failed',error='上次整理被中断，待重新整理',retry_at=now())
                queue_retry(state,job,job['event_keys'],DEFAULT)
            self.st.setmeta(KEY,state)

    def state(self):
        return copy.deepcopy(self.st.meta(KEY) or {'schema':SCHEMA,'started_at':now(),'consumed':{},'history':[],'job':{}})

    def cited_episode(self,ex):
        out=ex['outcome'];reply=out.get('actual_reply')
        if not isinstance(reply,str) or not reply.strip():return ex
        rows=self.st.rows("SELECT content FROM messages WHERE session_id=? AND turn_id=? AND role='assistant' ORDER BY created_at,id",
                          (ex['session_id'],ex['turn_id']))
        parts=[r['content'] for r in rows]
        basis=None
        if parts and '\n'.join(parts)==reply:
            if 'qq' in ex['scope'].split(':'):
                delivery=self.e.journal.delivery(ex['turn_id'])
                if delivery:basis=delivery_basis(ex['scope'],reply,delivery,parts)
            elif out.get('delivery')=='LOCAL_COMMITTED':
                basis='local_commit'
        ex=copy.deepcopy(ex)
        ex['outcome']['delivery_basis']=basis
        return ex

    def capture(self,mid,plan,delivery):
        traces=self.st.meta('memory_traces') or {};ex=collect_experience(plan,self.e.profile(),delivery)
        if self.research_event_time is not None:
            ex.update(recorded_at=plan['at'],occurred_at=number(self.research_event_time,0,1e13),simulated_clock=True)
        # The next external utterance is an observed followup, not proof that
        # the previous action caused it or succeeded.
        previous=[v['experience'] for k,v in traces.items() if k!=mid and isinstance(v,dict) and isinstance(v.get('experience'),dict) and v['experience'].get('session_id')==ex['session_id']]
        if previous:
            last=max(previous,key=lambda r:r['occurred_at'])
            if last['outcome'].get('external_followup') is None:
                last['outcome']['external_followup']={'event_id':ex['event_id'],'text':ex['external_event']['text'][:700],'meaning':'subsequent_statement_not_causal_proof'}
                last['outcome']['external_result_known']=False
        traces[mid]['experience']=ex;self.st.setmeta('memory_traces',traces)
        return {'memory_id':mid,'schema':ex['schema'],'event_id':ex['event_id']}

    def episodes(self,*,pending=False):
        from .learning import permission
        state=self.state();traces=self.st.meta('memory_traces') or {};out={};seen=set();persona_id=self.e.profile()['id']
        for row in self.st.rows("SELECT id,source_turn,scope,person FROM memories WHERE kind='episode' AND status='active' ORDER BY created_at,id"):
            mid=row['id'];ex=(traces.get(mid) or {}).get('experience')
            if not isinstance(ex,dict) or ex.get('schema')!='experienced-event/1' or ex.get('persona_id')!=persona_id:continue
            if ex.get('scope')!=row['scope'] or ex.get('person')!=row['person'] or ex.get('turn_id')!=row['source_turn']:continue
            key=digest([ex['scope'],ex['event_id']])
            if key in seen or pending and key in state['consumed']:continue
            gate=permission(self.e,'self',ex['scope'],ex['person'],observed_only=not ex.get('direct_interaction',True))
            if not gate['allowed']:continue
            seen.add(key);out[mid]=ex
        return out

    def status(self):
        from .learning import policy
        state=self.state();job=state.get('job') or {};opts=settings(policy(self.e));pending=self.episodes(pending=True)
        pending_keys={event_key(ex) for ex in pending.values()}
        public={k:copy.deepcopy(v) for k,v in job.items() if k not in ('report','rollback','captured','captured_role_sources','request')}
        public['can_rollback']=job.get('status') in ('partial','completed') and bool(job.get('rollback'))
        if job.get('status')=='awaiting_review':
            public['observation_rejections']=copy.deepcopy(job.get('report',{}).get('observation_rejections',[]))
            public['proposed_count']=len(job.get('report',{}).get('observations',[]))
        from .role_development import active
        supplements=[{k:copy.deepcopy(r[k]) for k in ('id','text','feature_id','category','topic','weight','confidence','created_at','importance_reason','lasting_effect') if k in r}
            for r in active(self.e.profile())][-12:]
        from .memory_role_changes import pending as role_pending,POLICY
        return {'settings':opts,'pending_memories':len(pending),'next_at':opts['new_memories'],
            'role_supplements':supplements,
            'role_change_policy':POLICY,'role_change_candidates':[{k:copy.deepcopy(r[k]) for k in ('id','category','topic','text','reasons','created_at') if k in r} for r in role_pending(self.e.profile())],
            'processed_events':len(state['consumed']),'job':public,'history':state['history'][-20:],
            'deferred_events':sum(k in pending_keys for group in state.get('retry_batches',{}).values() for k in group['event_keys']),
            'exhausted_batches':sum(group['attempts']>=opts['max_attempts'] and bool(pending_keys.intersection(group['event_keys']))
                                    for group in state.get('retry_batches',{}).values()),
            'running':bool(self.thread and self.thread.is_alive()),'legacy_policy':'only_new_structured_memories; original_history_preserved'}

    def poll(self):
        from .learning import policy
        p=policy(self.e);opts=settings(p);state=self.state();job=state.get('job') or {}
        if not opts['enabled'] or p['paused'] or p['domains']['self']['mode']=='manual' or self.learning.lock.locked() or self.thread and self.thread.is_alive():return False
        if job.get('status')=='awaiting_review':return False
        if not next_batch(state,self.episodes(pending=True),opts)[2]:return False
        def worker():
            try:self.run()
            except Exception:pass # run persists error, attempts and unconsumed sources.
        self.thread=threading.Thread(target=worker,daemon=True,name='experience-learning');self.thread.start();return True

    def run(self):
        from .learning import policy,permission
        if not self.learning.lock.acquire(blocking=False):raise ValueError('已有学习任务正在运行')
        identifier=None;started=time.monotonic()
        try:
            with self.e.lock,self.st.lock,self.st.db:
                p=policy(self.e);opts=settings(p);state=self.state();job=state.get('job') or {}
                if not opts['enabled'] or p['paused']:raise ValueError('经历学习已暂停')
                available=self.episodes(pending=True)
                if job.get('status')=='awaiting_review':raise ValueError('当前经历候选等待审阅')
                if job.get('status')=='failed':
                    # Preserve a legacy failure even if a different batch is selected.
                    state.setdefault('retry_batches',{}).setdefault(job.get('retry_of') or job['id'],
                        {k:copy.deepcopy(job[k]) for k in ('event_keys','attempts','retry_at','usage') if k in job})
                retry_of,previous,selected=next_batch(state,available,opts)
                if not selected:return {'status':'waiting','pending':len(available)}
                episodes={mid:self.cited_episode(ex) for mid,ex in selected.items()}
                job={'id':uid(),'retry_of':retry_of,'created_at':now(),'attempts':previous.get('attempts',0),
                     'memory_ids':list(episodes),'event_keys':[event_key(e) for e in episodes.values()],
                     'usage':copy.deepcopy(previous.get('usage',{'calls':0,'tokens':0,'budget_tokens':0}))}
                if self.research_event_time is not None:
                    job.update(review_at=number(self.research_event_time,0,1e13),simulated_clock=True)
                profile=self.e.profile();identifier=job['id'];captured=self.e.config.get()
                from .memory_role_changes import source_digest,pending as role_pending
                role_sources=dict(episodes);pending_rows=[];all_allowed=self.episodes()
                # Only a bounded set of pending candidates and their original
                # evidence return to the next batch, never the whole memory DB.
                for row in role_pending(profile):
                    mids=row.get('source_memory_ids',[])
                    if len(pending_rows)>=2:break
                    if any(m not in all_allowed for m in mids) or len(set(role_sources)|set(mids))>len(episodes)+8:continue
                    for mid in mids:role_sources.setdefault(mid,all_allowed[mid])
                    pending_rows.append(row)
                job.update(status='running',attempts=job['attempts']+1,trait_version=profile['trait_profile']['version'],policy_version=p['version'],
                    role_source_digest=source_digest(profile),error=None)
                state['job']=job;self.st.setmeta(KEY,state)
            from .api_pmm import APIPMM
            # Retry belongs to this durable job, not a hidden second request in
            # Provider.complete. Keep the user's connection configuration intact.
            captured=copy.deepcopy(captured)
            captured.update(json_repair=False,max_output_tokens=min(captured.get('max_output_tokens',4096),2000))
            captured['pmm']['api'].update(json_repair=False,max_output_tokens=min(captured['pmm']['api'].get('max_output_tokens',4096),2000))
            client=APIPMM(captured,self.e.pmm_provider_factory).provider if captured['pmm281']['mode']=='full' or captured['pmm']['mode']=='api' else self.e.provider_factory(captured)
            client.stage='经历人格学习';client.trace_context={'task_name':'experience_learning','component_role':'PMM-A','turn_ids':[e['turn_id'] for e in episodes.values()],'parent_call_id':identifier}
            from .known_personality import operative_personality
            # One bounded batch, no full profile, raw history, matrices or prompts.
            limit=max(80,min(700,p['budget']['batch_chars']//max(1,len(episodes))-650))
            compact={mid:compact_episode(mid,ex,limit) for mid,ex in episodes.items()}
            role_compact={mid:compact_episode(mid,ex,min(limit,350)) for mid,ex in role_sources.items()}
            registry=[{'id':k,'name':BY_ID[k]['name_zh']} for k in LONG_IDS]+[{'id':k,'name':v.get('name_zh',k)} for k,v in traits.DISPOSITIONS.items()]
            conditions=operative_personality(profile)
            request={'role_conditions':{'columns':['feature_id','estimate','uncertainty','source_type'],
                'rows':[[k,r['estimate'],r['posterior_uncertainty'],r['source_type']] for k,r in conditions.items()],
                'interpretation':'role_conditions_not_psychometric_measurements'},
                'registry':registry,'episodes':list(compact.values())}
            from .memory_role_changes import INSTRUCTION
            role_enabled=bool(pending_rows or any(ex['external_event'].get('major_event') is True for ex in episodes.values()))
            prompt=PROMPT
            if role_enabled:
                from .role_context import retrieve
                from .prompt_compiler import runtime_persona
                contexts=[]
                for scope in sorted({ex['scope'] for ex in role_sources.values()}):
                    view=self.e.persona_views.scoped_views(profile,scope)['generator_view']
                    query=' '.join(ex['external_event']['text'][:200] for ex in role_sources.values() if ex['scope']==scope)[:2000]
                    view['role_context']=retrieve(view,query)
                    selected=runtime_persona(view,query=query,purpose='role_change_review')
                    contexts.append({'scope':scope,'name':selected.get('name'),'role_entries':selected.get('role_entries',[]),'role_context':selected.get('role_context')})
                request.update(current_role=contexts,pending_role_changes=[{k:copy.deepcopy(r[k]) for k in ('id','category','topic','text','scope','source_memory_ids','major_memory_ids','reasons')} for r in pending_rows],
                    role_prior_episodes=[e for m,e in role_compact.items() if m not in compact])
                prompt+=INSTRUCTION
            request_chars=len(dumps(request));estimated=(len(prompt)+request_chars)*2+2000
            if estimated+job['usage'].get('budget_tokens',0)>p['budget']['max_tokens'] or job['usage']['calls']>=p['budget']['max_calls']:raise ValueError('本批超过经历学习资源预算，未发送请求')
            with self.st.lock,self.st.db:
                state=self.state();state['job']['usage']['calls']+=1;self.st.setmeta(KEY,state)
            try:
                value=client.complete([{'role':'system','content':prompt},{'role':'user','content':dumps(request)}],structured=True)
            finally:
                calls=getattr(client,'calls',[])
                totals=[(c.get('token_ledger') or {}).get('total_tokens') for c in calls]
                with self.st.lock,self.st.db:
                    state=self.state()
                    if state['job'].get('id')==identifier:
                        usage=state['job']['usage'];usage['tokens']+=sum(v for v in totals if type(v) is int)
                        usage['unknown_usage_calls']=usage.get('unknown_usage_calls',0)+(sum(v is None for v in totals) if totals else 1)
                        usage['budget_tokens']=usage.get('budget_tokens',0)+(sum(totals) if totals and all(type(v) is int for v in totals) else estimated)
                        usage.setdefault('call_ids',[]).extend(c['call_id'] for c in calls if c.get('call_id'))
                        self.st.setmeta(KEY,state)
            try:report=validate_report(value,compact,role_episodes={**role_compact,**compact},profile=profile)
            except RejectedObservations as error:report=error.report
            with self.e.lock,self.st.lock,self.st.db:
                state=self.state();job=state['job'];current_policy=policy(self.e);current=self.e.profile()
                if job['id']!=identifier or job['status']!='running':raise ValueError('经历任务状态已变化，未写入人格')
                if digest(current_policy)!=digest(p) or current['trait_profile']['version']!=profile['trait_profile']['version'] or source_digest(current)!=job['role_source_digest']:raise ValueError('学习策略或人设版本已变化，保留经历等待重算')
                allowed=self.episodes(pending=True)
                if not self.sources_current(episodes,allowed):raise ValueError('经历来源或权限已变化，未写入人格')
                allowed_roles=self.episodes()
                if any(mid not in allowed_roles or allowed_roles[mid]['external_event']!=ex['external_event'] for mid,ex in role_sources.items()):raise ValueError('人设变化的历史记忆已删除或权限变化')
                gates=[permission(self.e,'self',ex['scope'],ex['person'],observed_only=not ex.get('direct_interaction',True)) for ex in role_sources.values()]
                if not all(g['allowed'] for g in gates):raise ValueError('经历学习权限已变化')
                strength=min(g['strength'] for g in gates);automatic=all(g['mode']=='automatic' for g in gates)
                job.update(request_characters=request_chars,elapsed_ms=round((time.monotonic()-started)*1000,3),report=report)
                # Keep candidate-only distinct: no profile writes until approval.
                if not automatic:
                    job.update(status='awaiting_review',captured=episodes,captured_role_sources=role_sources);self.st.setmeta(KEY,state);return self.status()
                self._commit(state,job,current,report,episodes,strength,role_sources)
            return self.status()
        except Exception as ex:
            if identifier:
                with self.st.lock,self.st.db:
                    state=self.state();job=state.get('job') or {}
                    if job.get('id')==identifier and job.get('status')=='running':
                        job.update(status='failed',error_type=type(ex).__name__,error=str(ex)[:500] if isinstance(ex,ValueError) else '模型请求或输出失败，请查看调用记录',retry_at=now()+settings(policy(self.e))['retry_seconds']*max(1,job['attempts']))
                        queue_retry(state,job,job['event_keys'],settings(policy(self.e)))
                        self.st.setmeta(KEY,state)
            raise
        finally:self.learning.lock.release()

    def sources_current(self,episodes,allowed):
        for mid,captured in episodes.items():
            if mid not in allowed or event_key(allowed[mid])!=event_key(captured) or allowed[mid]['external_event']!=captured['external_event']:
                return False
            current=self.cited_episode(allowed[mid])
            captured_outcome=captured['outcome']
            # Reports saved by the older learner could only cite the external event.
            # Match the stored action text too, without promoting it to new evidence.
            if 'delivery_basis' not in captured_outcome:
                if captured_outcome.get('actual_reply')!=current['outcome'].get('actual_reply'):
                    return False
            elif observed_reply(current)!=observed_reply(captured):
                return False
        return True

    def _commit(self,state,job,current,report,episodes,strength,role_sources=None):
        from .learning import policy
        current=copy.deepcopy(current)
        active_ids={r['id'] for r in self.st.rows("SELECT id FROM memories WHERE kind='episode' AND status='active'")}
        for record in current['psychology'].get('evidence_records',[]):
            if record.get('evidence_kind')=='experienced_event' and record.get('memory_id') not in active_ids:record['withdrawn']=True
        if report['observations'] or report.get('role_changes') or report.get('role_rejections'):
            updated,result=apply_report(current,report,episodes,job['id'],strength,True,role_episodes=role_sources,review_at=job.get('review_at'))
            from .psychology import validate_profile
            validate_profile(updated)
            if updated!=current:
                job['rollback']={'before':current,'after_digest':digest(updated)}
                self.st.setmeta('pmm_profile',updated)
        else:
            result={'accepted':0,'promoted':0,'role_supplements_added':0,'candidates':[],
                    'trait_version':current['trait_profile']['version'],'summary':report['summary'],'job_id':job['id']}
        rejected=report.get('observation_rejections',[])
        unresolved={mid for r in rejected for mid in r['memory_ids']}
        if rejected and (any(r['unattributed'] for r in rejected) or not report['observations'] and not report.get('role_changes')):
            unresolved=set(episodes)
        for mid,ex in episodes.items():
            if mid not in unresolved:state['consumed'][event_key(ex)]=job['id']
        queue_retry(state,job,[event_key(episodes[mid]) for mid in sorted(unresolved)],settings(policy(self.e)))
        status='completed'
        if rejected:status='partial' if report['observations'] or report.get('role_changes') else 'evidence_rejected'
        result.update(observation_rejections=rejected,deferred_memory_ids=sorted(unresolved),
                      processed_event_count=len(episodes)-len(unresolved))
        job.update(status=status,completed_at=now(),result=result)
        summary={k:copy.deepcopy(job[k]) for k in ('id','retry_of','status','created_at','completed_at','review_at','simulated_clock','memory_ids','result','request_characters','elapsed_ms') if k in job}
        state['history'].append(summary);self.st.setmeta(KEY,state)
        self.st.event('experience_learning',summary)

    def control(self,action):
        from .learning import permission
        with self.e.lock,self.st.lock,self.st.db:
            if self.learning.lock.locked():raise ValueError('学习正在运行，请等待当前批次完成')
            state=self.state();job=state.get('job') or {}
            group_id=job.get('retry_of') or job.get('id')
            batches=state.setdefault('retry_batches',{})
            if action=='retry' and job.get('status') in ('partial','evidence_rejected','failed'):
                job.update(attempts=0,retry_at=0)
                if group_id in batches:batches[group_id].update(attempts=0,retry_at=0)
            elif action=='retry_deferred' and batches:
                from .learning import policy
                limit=settings(policy(self.e))['max_attempts']
                for group in batches.values():
                    if group['attempts']>=limit:group.update(attempts=0,retry_at=0)
            elif action=='cancel' and job.get('status') in ('partial','evidence_rejected','failed','awaiting_review'):
                batches.pop(group_id,None)
                for key in job.get('event_keys',[]):state['consumed'][key]=job['id']
                state['history'].append({'id':job['id'],'status':'rejected','at':now(),'reason':'owner_cancelled_batch'});state['job']={}
            elif action=='approve' and job.get('status')=='awaiting_review':
                if self.e.profile()['trait_profile']['version']!=job['trait_version']:raise ValueError('人格版本已变化，请取消后重新整理')
                from .memory_role_changes import source_digest
                if job.get('role_source_digest') and source_digest(self.e.profile())!=job['role_source_digest']:raise ValueError('人设资料已变化，请取消后重新整理')
                available=self.episodes(pending=True);episodes=job['captured']
                if not self.sources_current(episodes,available):raise ValueError('经历来源或权限已变化')
                from .learning import policy
                if policy(self.e)['version']!=job['policy_version']:raise ValueError('学习策略已变化，请取消后重新整理')
                roles=job.get('captured_role_sources') or episodes;allowed=self.episodes()
                if any(m not in allowed or allowed[m]['external_event']!=e['external_event'] for m,e in roles.items()):raise ValueError('人设来源已删除或权限变化')
                strength=min(permission(self.e,'self',e['scope'],e['person'])['strength'] for e in roles.values())
                self._commit(state,job,self.e.profile(),job['report'],episodes,strength,roles)
            elif action=='rollback' and job.get('status') in ('completed','partial') and job.get('rollback'):
                if digest(self.e.profile())!=job['rollback']['after_digest']:raise ValueError('人格已有后续变动，不能覆盖回滚')
                if job['rollback']['before']['id']!=self.e.profile()['id']:raise ValueError('回滚记录不属于当前角色')
                self.st.setmeta('pmm_profile',job['rollback']['before']);job['status']='rolled_back'
                batches.pop(group_id,None)
                for key in job['event_keys']:state['consumed'][key]=job['id']
                # Consumed IDs remain, preventing the same memories immediately
                # recreating an owner-rejected change on the next background tick.
                self.st.event('experience_learning',{'id':job['id'],'status':'rolled_back','at':now()})
            else:raise ValueError('当前状态不支持该操作')
            self.st.setmeta(KEY,state)
        return self.status()
