"""Versioned long-term priors. Evidence collection is not trait promotion."""
from __future__ import annotations
import copy, datetime, json, math
from pathlib import Path
from .common import now, uid
from .registry import LONG_IDS, BY_ID, REGISTRY, number, digest

SCHEMA='trait-profile/1'
DISPOSITION_REGISTRY=json.loads(Path(__file__).with_name('trait_disposition_registry.json').read_text('utf8'))
DISPOSITIONS={f['id']:f for f in DISPOSITION_REGISTRY['fields']}

def apply_pmm28_proposal(profile,proposal,protocol,source_rows):
    """Coordinator-only adapter; preserve canonical evidence and revision history.

    The coordinator verifies calibration, permissions, CAS and event reuse before
    calling. This pure adapter also checks identities, scale and numeric ranges.
    """
    import numpy as np
    p=ensure_traits(profile);payload=proposal['payload'];ids=payload['construct_ids']
    if proposal['subject_id']!=p['id'] or proposal['prior_revision']!=p['revision'] or protocol['construct_ids']!=ids or payload['scale_id']!=protocol['scale_id']:
        raise ValueError('Proposal identity/revision/scale mismatch')
    if not protocol.get('validated') or proposal.get('engineering_only') or not source_rows:raise ValueError('Unvalidated personality proposal')
    slope=np.asarray(protocol['slope']);intercept=np.asarray(protocol['intercept']);mu=np.asarray(payload['posterior']['mu']);P=np.asarray(payload['posterior']['P'])
    if slope.shape!=mu.shape or np.any(np.abs(slope)<1e-6):raise ValueError('Invalid canonical scale conversion')
    values=(mu-intercept)/slope
    if not np.isfinite(values).all() or np.any(values<0) or np.any(values>1):raise ValueError('Posterior outside canonical scale; manual review required')
    at=now();t=p['trait_profile'];t['version']+=1;t['updated_at']=at
    records=[]
    for r in source_rows:
        records.append({'id':r['record_id'],'speaker':r['person'],'text':r['text'],'scope':r['scope'],'event_id':r['event_id'],'timestamp':r['occurred_at'],'source':r['source_type']})
    known={r['id']:r for r in p['psychology']['evidence_records']+p['source_records']}
    for r in records:
        if r['id'] in known and known[r['id']]['text']!=r['text']:raise ValueError('Canonical evidence ID conflict')
        if r['id'] not in known:p['psychology']['evidence_records'].append(r);known[r['id']]=r
    ev=[{'record_id':r['id'],'quote':r['text']} for r in records];record_ids=sorted({r['id'] for r in records})
    for i,k in enumerate(ids):
        if not k.startswith('hexaco.') or k not in LONG_IDS:raise ValueError('Wrong construct estimator')
        f=p['psychology']['features'][k];before=copy.deepcopy(f);uncertainty=min(1.,float(np.sqrt(max(0,P[i,i]))/abs(slope[i])))
        f.update(estimate=float(values[i]),posterior_uncertainty=uncertainty,evidence_ids=record_ids,evidence_count=len(record_ids),
                 source_type='longitudinal_estimate',updated_at=at,method_version='pmm-D-E/2.8',conflict=False,
                 uncertainty_semantics='posterior canonical standard deviation, display saturated at 1',proposal_id=payload['proposal_id'])
        p['psychology']['observations'].append({'id':uid(),'feature_id':k,'estimate':float(values[i]),'confidence':1-uncertainty,'evidence':ev,
            'source':'independent_longitudinal_measurements','timestamp':at,'method_version':'pmm-D-E/2.8','status':'validated_estimate'})
        t['promotion_history'].append({'id':uid(),'feature_id':k,'before':before,'after':copy.deepcopy(f),'at':at,'trait_version':t['version'],
            'method':'pmm-D-E/2.8','proposal_id':payload['proposal_id'],'source_evidence':ev})
    p['revision']+=1;p['updated_at']=at;return p

def invalidate_pmm28_evidence(profile,record_ids,reason):
    """Withdraw a derived estimate without deleting observed history or weights."""
    p=ensure_traits(profile);changes=[];at=now()
    for k in LONG_IDS:
        f=p['psychology']['features'][k]
        if f.get('source_type')!='longitudinal_estimate' or not set(f['evidence_ids'])&set(record_ids):continue
        before=copy.deepcopy(f)
        f.update(estimate=None,posterior_uncertainty=None,evidence_ids=[],evidence_count=0,source_type='unknown',updated_at=at,conflict=True,method_version='pmm28-source-withdrawal/1')
        changes.append({'id':uid(),'feature_id':k,'before':before,'after':copy.deepcopy(f),'at':at,'method':'pmm28-source-withdrawal/1','reason':str(reason)[:1000]})
    if changes:
        p['revision']+=1;p['updated_at']=at;p['trait_profile']['version']+=1
        for row in changes:row['trait_version']=p['trait_profile']['version']
        p['trait_profile']['promotion_history'].extend(changes)
    return p,changes
PROMOTION_POLICY={'version':'cross-context-evidence/2','independent_events':3,'contexts':2,'span_seconds':86400,'min_confidence':.4,'max_spread':.4,'max_step':.03}

def ensure_traits(profile,scope='agent_self'):
    p=copy.deepcopy(profile)
    if 'trait_profile' not in p:
        p['trait_profile']={'schema':SCHEMA,'persona_id':p['id'],'scope':scope,'version':0,
            'updated_at':p.get('updated_at'),'dispositions':{k:{'estimate':None,'uncertainty':None,
            'source_type':'unknown','evidence':[],'updated_at':None,'measurement':None} for k in DISPOSITIONS},
            'disposition_observations':[],'promotion_history':[],
            'legacy_fields':{'traits':'archived_big_five_view','values':'archived_ten_value_view'},
            'migration':'preserve_existing_canonical_values_and_masks/1','promotion_policy':copy.deepcopy(PROMOTION_POLICY)}
    if any(f.get('scope')=='model_of_other' for f in p['psychology']['features'].values()):p['trait_profile']['scope']='model_of_other'
    return p

def validate(profile):
    t=profile.get('trait_profile')
    if t is None:return
    if not isinstance(t,dict) or t.get('schema')!=SCHEMA or t.get('persona_id')!=profile['id']:raise ValueError('长期人格主体或版本不匹配')
    if t.get('scope') not in ('agent_self','model_of_other'):raise ValueError('长期人格作用域无效')
    if type(t.get('version')) is not int or t['version']<0:raise ValueError('长期人格版本无效')
    if set(t.get('dispositions',{}))!=set(DISPOSITIONS):raise ValueError('长期表达/调节字段缺失')
    for k,f in t['dispositions'].items():
        if not isinstance(f,dict) or not isinstance(f.get('evidence'),list):raise ValueError('长期习惯证据无效')
        if f.get('estimate') is not None:
            number(f['estimate']);number(f.get('uncertainty'))
            if f.get('source_type') not in ('owner_seed','questionnaire','promoted_evidence','legacy_engineering'):raise ValueError('长期习惯必须注明来源')
            if f['source_type']=='questionnaire':validate_measurement(k,f.get('measurement'))
        elif f.get('uncertainty') is not None:raise ValueError('未知习惯不得伪造置信度')
    if not isinstance(t.get('disposition_observations'),list) or not isinstance(t.get('promotion_history'),list):raise ValueError('长期人格证据日志无效')
    # Re-validate imported evidence rather than trusting an arbitrary package.
    records={r['id']:r for r in profile['source_records']+profile['psychology'].get('evidence_records',[])}
    for r in records.values():
        if r.get('subject_entity')=='agent_self':
            if r.get('source') not in ('human','observed','imported') or r.get('evidence_kind') not in ('external_feedback','owner_evaluation') or not all(isinstance(r.get(k),str) and r[k] for k in ('scope','experience_turn_id','experience_event_key')) or event_time({'timestamp':r.get('experience_timestamp')}) is None:raise ValueError('自身经历的外部评价来源无效')
            if 'experience_context' in r:
                c=r['experience_context']
                if not isinstance(c,dict) or not all(isinstance(c.get(k),str) and c[k] for k in ('label','quote','source')) or r.get('experience_context_key')!=digest([r['scope'],c['label']]):raise ValueError('自身经历的情境来源无效')
    for o in t['disposition_observations']:
        if not isinstance(o,dict) or o.get('feature_id') not in DISPOSITIONS:raise ValueError('长期习惯观察字段无效')
        number(o.get('estimate'));number(o.get('confidence'))
        if not o.get('evidence') or not isinstance(o['evidence'],list):raise ValueError('长期习惯观察缺少证据')
        for e in o['evidence']:
            if not isinstance(e,dict) or e.get('record_id') not in records or not isinstance(e.get('quote'),str) or not e['quote'] or e['quote'] not in records[e['record_id']]['text']:raise ValueError('长期习惯观察证据不匹配')

def validate_measurement(k,m):
    if not isinstance(m,dict) or m.get('instrument')!=DISPOSITIONS[k]['instrument']:raise ValueError('量表名称与字段不匹配')
    for field in ('version','scoring_method','timeframe','respondent','respondent_type'):
        if not isinstance(m.get(field),str) or not m[field].strip() or len(m[field])>1000:raise ValueError('量表记录缺少题本版本、计分方法、时间框架或作答者')
    if m['timeframe']!=DISPOSITIONS[k]['required_timeframe']:raise ValueError('量表时间框架必须是长期习惯；当下情绪不得写入人格')
    if m['respondent_type'] not in ('self_report','informant_report'):raise ValueError('量表须说明自评/他评；AI 模拟回答不是正式测量')
    if m.get('authorized') is not True:raise ValueError('请注明量表资料已获授权')
    if not isinstance(m.get('normalization'),str) or not m['normalization'].strip():raise ValueError('请说明原始量表到 0–1 表征的转换方法')

def snapshot(profile):
    p=ensure_traits(profile);t=p['trait_profile']
    fields={k:copy.deepcopy(p['psychology']['features'][k]) for k in LONG_IDS}
    return {'schema':SCHEMA,'persona_id':p['id'],'scope':t['scope'],'trait_version':t['version'],
            'trait_digest':digest({'features':fields,'dispositions':t['dispositions'],'character':p.get('character',{}),'seed':p.get('seed','')}),
            'hexaco_facets':{k:v for k,v in fields.items() if k.startswith('hexaco.')},
            'value_priorities':{k:v for k,v in fields.items() if k.startswith('value.')},
            'interpersonal_dispositions':{k:v for k,v in fields.items() if k.startswith('social.')},
            'behavioral_dispositions':{k:v for k,v in fields.items() if k.startswith('style.')},
            'manual_seed':{'seed':p.get('seed',''),'character':copy.deepcopy(p.get('character',{}))},
            'affective_disposition':{k:{n:copy.deepcopy(v.get(n)) for n in ('estimate','uncertainty','source_type','updated_at')} for k,v in t['dispositions'].items()},
            'interpretation':'工程表征；owner_seed 为主人设定，推断候选不等于正式量表分数'}

def edit_disposition(profile,body):
    p=ensure_traits(profile);t=p['trait_profile'];k=body.get('feature_id')
    if k in LONG_IDS:return edit_canonical(p,body)
    if k not in DISPOSITIONS:raise ValueError('请选择 BEQ、ERQ 或 PANAS 的已注册长期字段')
    if body.get('expected_version')!=t['version']:raise ValueError('人格版本已变化，请刷新后保存')
    value=body.get('estimate');source=body.get('source_type','owner_seed');measurement=None
    if value is not None:
        number(value)
        if source not in ('owner_seed','questionnaire'):raise ValueError('手动写入须为主人设定或有记录的量表')
        if source=='questionnaire':validate_measurement(k,body.get('measurement'));measurement=copy.deepcopy(body['measurement'])
        if k.startswith('panas.') and body.get('timeframe')!='generally':raise ValueError('PANAS 仅接受“总体上/通常”的长期时间框架')
    else:source='unknown'
    old=copy.deepcopy(t['dispositions'][k]);at=now()
    t['dispositions'][k]={'estimate':value,'uncertainty':None if value is None else 0. if source=='owner_seed' else .25,
        'source_type':source,'evidence':[],'updated_at':at,'measurement':measurement,
        'note':str(body.get('note',''))[:1000],'uncertainty_semantics':'设定确定性，不代表心理测量精度' if source=='owner_seed' else '未校准的工程不确定性'}
    t['version']+=1;t['updated_at']=at
    t['promotion_history'].append({'id':uid(),'at':at,'method':'explicit_owner_edit/1','feature_id':k,'before':old,'after':copy.deepcopy(t['dispositions'][k]),'trait_version':t['version']})
    p['revision']+=1;p['updated_at']=at
    return p

def edit_canonical(profile,body):
    p=copy.deepcopy(profile);t=p['trait_profile'];k=body['feature_id']
    if body.get('expected_version')!=t['version']:raise ValueError('人格版本已变化，请刷新后保存')
    if body.get('source_type','owner_seed')!='owner_seed':raise ValueError('此入口仅记录主人设定，不是正式问卷计分')
    value=body.get('estimate');old=p['psychology']['features'][k];before=copy.deepcopy(old);at=now()
    if value is None:
        old.update(estimate=None,posterior_uncertainty=None,evidence_ids=[],evidence_count=0,source_type='unknown',updated_at=at,method_version='explicit-owner-clear/1',conflict=False)
    else:
        number(value,BY_ID[k]['minimum']);rid=uid()
        text=f"主人设置 {BY_ID[k]['name_zh']} = {value}。"+str(body.get('note',''))[:1000]
        record={'id':rid,'speaker':'owner','text':text,'context':'','source':'human','event_id':rid,'timestamp':at,'scope':'owner:settings'}
        p['psychology']['evidence_records'].append(record)
        p['psychology']['observations'].append({'id':uid(),'feature_id':k,'estimate':value,'confidence':1.,'evidence':[{'record_id':rid,'quote':text}],
            'source':'owner_seed','timestamp':at,'method_version':'explicit-owner-edit/1','status':'owner_seed'})
        old.update(estimate=value,posterior_uncertainty=0.,evidence_ids=[rid],evidence_count=1,source_type='owner_seed',updated_at=at,method_version='explicit-owner-edit/1',conflict=False)
    t['version']+=1;t['updated_at']=at;p['revision']+=1;p['updated_at']=at
    t['promotion_history'].append({'id':uid(),'feature_id':k,'at':at,'before':before,'after':copy.deepcopy(old),'method':'explicit-owner-edit/1','trait_version':t['version']})
    return p

def observe_dispositions(profile,rows,records,source):
    p=ensure_traits(profile);stats={'accepted':0,'rejected':0};byid={r['id']:r for r in records}
    if not isinstance(rows,list):raise ValueError('长期习惯候选应为列表')
    for row in rows[:100]:
        try:
            k=row['feature_id'];spec=DISPOSITIONS[k]
            if source not in ('imported','observed','human') or row.get('timeframe')!=spec['required_timeframe']:raise ValueError('缺少长期时间框架或来源')
            value=number(row['estimate']);confidence=min(.75,number(row.get('confidence',.4)))
            ev=[copy.deepcopy(e) for e in row.get('evidence',[]) if isinstance(e,dict) and e.get('record_id') in byid and isinstance(e.get('quote'),str) and e['quote'].strip() and e['quote'] in byid[e['record_id']]['text']]
            if not ev:raise ValueError('缺少证据')
            obs=p['trait_profile']['disposition_observations']
            if any(o['feature_id']==k and o['evidence']==ev for o in obs):continue
            obs.append({'id':uid(),'feature_id':k,'estimate':value,'confidence':confidence,'evidence':ev,'source':source,'timestamp':now(),'timeframe':row['timeframe'],'status':'candidate'})
            stats['accepted']+=1
        except (KeyError,ValueError,TypeError):stats['rejected']+=1
    return p,stats

def event_time(record):
    v=record.get('timestamp',record.get('created_at'))
    if type(v) in (int,float) and math.isfinite(v) and v>0:return float(v)
    if isinstance(v,str):
        try:
            n=float(v)
            if math.isfinite(n) and n>0:return n
        except ValueError:pass
        try:
            dt=datetime.datetime.fromisoformat(v.replace('Z','+00:00'))
            if dt.tzinfo:return dt.timestamp()
        except ValueError:pass
    return None

def review(profile,apply=False,strength=1.):
    """Separate slow job. Three events is necessary, never sufficient by count alone."""
    number(strength);p=ensure_traits(profile);t=p['trait_profile'];rows=[];changes=[]
    records={r['id']:r for r in p['source_records']+p['psychology'].get('evidence_records',[])}
    observations=p['psychology']['observations']+t['disposition_observations']
    for k in (*LONG_IDS,*DISPOSITIONS):
        obs=[o for o in observations if o['feature_id']==k and o.get('source') in ('imported','observed','human') and o.get('confidence',0)>=PROMOTION_POLICY['min_confidence'] and o.get('status') not in ('rejected','withdrawn')]
        if not obs:continue
        from .evidence import identity
        def prior_events(h):
            after=h.get('after',{});ids=after.get('evidence_ids',[]) or [e['record_id'] for e in after.get('evidence',[])]
            return set(h.get('event_ids',[])) or {records[i].get('experience_event_key') or identity(records[i]) for i in ids if i in records}
        consumed=set().union(*(prior_events(h) for h in t['promotion_history'] if h.get('feature_id')==k and h.get('evidence_signature')))
        events=set();contexts=set();times=[];used=[];evidence=[];event_votes={}
        for o in obs:
            valid=False
            for ev in o['evidence']:
                r=records.get(ev['record_id'],{});timestamp=event_time({'timestamp':r.get('experience_timestamp')}) if r.get('subject_entity')=='agent_self' else event_time(r);timestamp=timestamp if timestamp and timestamp<=now()+300 else None;context=r.get('experience_context_key') or r.get('scope') or r.get('context_id') or r.get('conversation_id')
                event=r.get('event_id') or r.get('source_event_id') or r.get('batch_id')
                # batch_id deliberately prevents multiple quotes from one imported
                # transcript or one generated turn counting as independent events.
                if r.get('source')=='generated' or r.get('withdrawn') or not timestamp or not context or not event:continue
                from .evidence import identity
                event_key=r.get('experience_event_key') or identity(r)
                if event_key in consumed:continue
                events.add(event_key);contexts.add(context);times.append(timestamp);evidence.append(ev);valid=True
                event_votes.setdefault(event_key,[]).append(o)
            if valid:used.append(o)
        spread=max([o['estimate'] for o in used],default=0)-min([o['estimate'] for o in used],default=0)
        span=max(times)-min(times) if times else 0
        old=t['dispositions'][k] if k in DISPOSITIONS else p['psychology']['features'][k]
        reasons=[]
        if strength==0:reasons.append('学习强度为0，不晋升长期字段')
        if len(events)<3:reasons.append('少于 3 个有来源的独立事件')
        if len(contexts)<2:reasons.append('缺少跨情境证据')
        if span<86400:reasons.append('证据跨度不足 24 小时或时间不明')
        if spread>.4:reasons.append('存在显著反例，需要人工核对')
        if old.get('source_type') in ('owner_seed','questionnaire'):reasons.append('明确设定/量表记录不能被聊天候选覆盖')
        signature=digest({'feature_id':k,'independent_events':sorted(events)})
        def historic_events(h):
            after=h.get('after',{});ids=after.get('evidence_ids',[]) or [e['record_id'] for e in after.get('evidence',[])]
            return set(h.get('event_ids',[])) or {identity(records[i]) for i in ids if i in records}
        if any(h.get('evidence_signature')==signature or h.get('feature_id')==k and events and events<=historic_events(h) for h in t['promotion_history']):reasons.append('同一批证据已经审查，不重复晋升')
        row={'feature_id':k,'eligible':not reasons,'reasons':reasons,'independent_events':len(events),'previously_consumed_events':len(consumed),'contexts':len(contexts),'span_seconds':span,'counterevidence_spread':spread,'method':PROMOTION_POLICY['version']}
        rows.append(row)
        if not apply or reasons:continue
        # Correlated quotes/hypotheses cannot increase the event's weight.
        votes=[]
        for os in event_votes.values():
            unique={(o['estimate'],o['confidence']) for o in os}
            votes.append(sum(v*w for v,w in unique)/sum(w for _,w in unique))
        mean=sum(votes)/len(votes)
        before=copy.deepcopy(old);previous=old['estimate']
        value=mean if previous is None else previous+max(-.03*strength,min(.03*strength,mean-previous))
        ids=sorted({e['record_id'] for e in evidence});uncertainty=max(.25,1-strength*len(events)/(len(events)+3))
        if k in DISPOSITIONS:old.update(estimate=value,uncertainty=uncertainty,source_type='promoted_evidence',evidence=evidence,updated_at=now())
        else:old.update(estimate=value,posterior_uncertainty=uncertainty,evidence_ids=ids,evidence_count=len(ids),source_type='promoted_evidence',updated_at=now(),method_version=PROMOTION_POLICY['version'],conflict=False)
        changes.append({'id':uid(),'at':now(),'feature_id':k,'before':before,'after':copy.deepcopy(old),'evidence_signature':signature,'event_ids':sorted(events),'source_evidence':copy.deepcopy(evidence),'method':PROMOTION_POLICY['version'],'counterevidence_spread':spread,'independent_events':len(events),'contexts':len(contexts),'span_seconds':span})
    if changes:
        t['promotion_policy']=copy.deepcopy(PROMOTION_POLICY)
        t['version']+=1;t['updated_at']=now();p['revision']+=1;p['updated_at']=now()
        for change in changes:change['trait_version']=t['version']
        t['promotion_history'].extend(changes)
    return p,{'policy':PROMOTION_POLICY,'candidates':rows,'promoted':len(changes),'trait_version':t['version']}

def filter_template(profile,ids):
    """Drop scoped long-term evidence from a portable template, not live identity."""
    t=profile['trait_profile']
    t['disposition_observations']=[o for o in t['disposition_observations'] if all(e['record_id'] in ids for e in o['evidence'])]
    for k,f in t['dispositions'].items():
        if any(e['record_id'] not in ids for e in f['evidence']):t['dispositions'][k]={'estimate':None,'uncertainty':None,'source_type':'unknown','evidence':[],'updated_at':None,'measurement':None}
    t['promotion_history']=[]


def promotion_records(profile,change):
    """One supervised sample per independent event, not per repeated quote."""
    from .evidence import identity
    records={r['id']:r for r in profile['source_records']+profile['psychology']['evidence_records']}
    ids=[e['record_id'] for e in change.get('source_evidence',[])] or change['after'].get('evidence_ids',[])
    seen=set();out=[]
    for rid in ids:
        if rid not in records:continue
        r=records[rid];key=r.get('experience_event_key') or identity(r)
        if key in seen or r.get('withdrawn'):continue
        seen.add(key);out.append(r)
    return out
