"""Atomic, event-idempotent emotion drafts in the existing subject database."""
from __future__ import annotations
import copy
import numpy as np
from .registry import digest
from .affect import empty as legacy_empty,AXES,LABELS
from .affect_dynamics_v2 import seconds,iso,inverse,link,propagate,coupled_moments,MOOD_AXES
from .affect_response import initial_model,validate_model,parameters,response
from .affect_regulation import choose,expression
from .pmm_contracts import construct_blocks

KEY='pmm281_affect';MODELS='pmm281_affect_models';SCHEMA='affect-state/2.8.1'

def migrate(store):
    owner=store.meta('identity')['id']
    with store.lock,store.db:
        existing=store.meta(KEY)
        if existing is not None:validate(existing,owner);return existing
        old=store.meta('pmm_affect') or legacy_empty(owner)
        model=initial_model(owner,old['transition_params'])
        value={'schema':SCHEMA,'subject_id':owner,'revision':0,'streams':{},'legacy_snapshot':copy.deepcopy(old),
            'migration':{'old_sha256':digest(old),'old_parameters_preserved':True,'initial_model':model['sha256']}}
        store.setmeta(KEY,value)
        if store.meta(MODELS) is None:store.setmeta(MODELS,{'subject_id':owner,'revision':0,'seed':model['sha256'],'active':None,'versions':{model['sha256']:model},'reports':{},'datasets':{},'audit':[]})
        store.event('affect_v2_migration',value['migration']);return value

def stream_key(subject,event):
    for k in ('scope','person','id','text'):
        if not isinstance(event.get(k),str) or not event[k]:raise ValueError('情绪事件缺少主体、范围或原文')
    return digest([subject,event['scope'],event['person'],event.get('session_id',event['scope'])])

def validate(data,owner):
    if data is None:return
    if not isinstance(data,dict) or data.get('schema')!=SCHEMA or data.get('subject_id')!=owner or type(data.get('revision')) is not int or data['revision']<0:raise ValueError('情绪状态主体/版本无效')
    if not isinstance(data.get('streams'),dict):raise ValueError('情绪快照分区无效')
    for key,row in data['streams'].items():
        if key!=stream_key(owner,{'id':'validate','text':'validate',**row['identity']}):raise ValueError('情绪快照范围无效')
        seconds(row['last_at'])
        for field,size in [('fast',5),('mood',3)]:
            a=np.asarray(row[field],float)
            if a.shape!=(size,) or not np.isfinite(a).all():raise ValueError('情绪潜变量无效')
        rng=np.random.default_rng();rng.bit_generator.state=row['rng_state']
        if type(row['revision']) is not int or row['revision']<0 or type(row['turn_index']) is not int or row['turn_index']<0:raise ValueError('情绪轮次/修订号错误')
        if not isinstance(row.get('events'),dict):raise ValueError('情绪幂等记录错误')
        for event_id,record in row['events'].items():
            if record['result']['event_id']!=event_id or record['result']['subject_id']!=owner:raise ValueError('情绪事件归属错误')
            for name,n in [('fast_state_latent',5),('slow_mood_latent',3)]:
                a=np.asarray(record['result'][name],float)
                if a.shape!=(n,) or not np.isfinite(a).all():raise ValueError('历史情绪潜变量错误')

def validate_metadata(meta):
    owner=meta.get('identity',{}).get('id');validate(meta.get(KEY),owner)
    cat=meta.get(MODELS)
    if cat is None:return
    if cat.get('subject_id')!=owner or type(cat.get('revision')) is not int:raise ValueError('情绪模型目录主体错误')
    for key,model in cat['versions'].items():
        validate_model(model,owner)
        if key!=model['sha256']:raise ValueError('情绪模型索引错误')
    for key in ('seed','active'):
        if cat.get(key) and cat[key] not in cat['versions']:raise ValueError('情绪模型引用不存在')
    if cat.get('active'):
        from .affect_training import release_gate
        if not release_gate(cat,cat['active'])[0]:raise ValueError('已发布情绪模型缺少有效校准')

def model_for(store):
    cat=store.meta(MODELS)
    if not cat:migrate(store);cat=store.meta(MODELS)
    key=cat.get('active') or cat['seed'];model=cat['versions'][key]
    validate_model(model,store.meta('identity')['id'])
    if cat.get('active'):
        from .affect_training import release_gate
        if not release_gate(cat,key)[0]:raise ValueError('情绪发布资格失效，请撤销或切换版本')
        from .affect_learning import bind_sources
        bind_sources(store,cat['datasets'][cat['reports'][key]['dataset_sha256']])
    return model

def initial_stream(base,event,model,at):
    owner=base['subject_id'];old=base['legacy_snapshot'];last=next((r for r in reversed(old['appraisals']) if r.get('scope')),None)
    match=(last and last['scope']==event['scope'] and last.get('person_id')==event['person']) or (not last and event['scope']=='private:web:owner' and event['person']=='web:owner')
    values=old['emotion'] if match else {};mvalues=old['mood'] if match else {}
    fast,fmask,fprecision=inverse(values);mood,mmask,mprecision=inverse(mvalues,MOOD_AXES)
    mu=model['parameters']['mu_b']
    fast=[v if m else mu[i] for i,(v,m) in enumerate(zip(fast,fmask))];mood=[v if m else mu[i+5] for i,(v,m) in enumerate(zip(mood,mmask))]
    seed=int(stream_key(owner,event)[:16],16);rng=np.random.default_rng(seed)
    return {'identity':{'scope':event['scope'],'person':event['person'],'session_id':event.get('session_id',event['scope'])},'fast':fast,'mood':mood,
        'fast_mask':fmask,'mood_mask':mmask,'last_at':seconds(old['emotion']['last_updated']) if match and old['emotion'].get('last_updated') else at,
        'turn_index':0,'revision':0,'model_version':model['sha256'],'rng_state':rng.bit_generator.state,'events':{},
        'link_precision':{'fast':fprecision,'mood':mprecision},'legacy_seed_used':bool(match)}

def draft(base,model,profile,event,at,packet,relation,goal=None,strategy=None):
    """Pure, replayable proposal. No database mutation, even for first event."""
    owner=profile['id'];validate(base,owner);validate_model(model,owner)
    at=seconds(at);key=stream_key(owner,event);out=copy.deepcopy(base)
    row=out['streams'].setdefault(key,initial_stream(base,event,model,at));fingerprint=digest([event['text'],packet['event_facts']])
    if event['id'] in row['events']:
        previous=row['events'][event['id']]
        if previous['content_sha256']!=fingerprint:raise ValueError('同一事件 ID 的原文发生变化')
        result=copy.deepcopy(previous['result']);result.update(updated=False,replayed=True)
        return out,result
    before_rng=copy.deepcopy(row['rng_state']);rng=np.random.default_rng();rng.bit_generator.state=before_rng
    effective=max(at,row['last_at']);dt=effective-row['last_at'];blocks=construct_blocks(profile);params=parameters(model,blocks)
    fast,mood,propagation=propagate(row['fast'],row['mood'],params,dt,rng,1)
    effective_packet,regulation=choose(model,fast,packet,blocks,goal or {},rng,strategy)
    # Reappraisal changes the input to exactly one jump; original candidate is
    # computed only for the auditable counterfactual and is never accumulated.
    after,jump=response(model,effective_packet,blocks,relation,mood,fast)
    _,original=response(model,packet,blocks,relation,mood,fast)
    observed=link(after);mood_observed=link(mood,MOOD_AXES);plan=expression(observed,regulation,blocks)
    result={'schema':SCHEMA,'subject_id':owner,'event_id':event['id'],'scope':event['scope'],'person_id':event['person'],
        'session_id':event.get('session_id',event['scope']),'at':iso(effective),'received_at':iso(at),'affect_model_version':model['sha256'],
        'calibration_status':model['calibration']['status'],'fast_state_latent':after.tolist(),'slow_mood_latent':mood.tolist(),
        'affect_observed':observed,'mood_observed':mood_observed,'emotion_labels':jump['emotion_labels'],'label_activations':jump['label_activations'],
        'label_status':jump['label_status'],'appraisal_evidence_ids':packet['evidence_ids'],'appraisal':effective_packet,
        'regulation':regulation,'expression_plan':plan,'delta_seconds':dt,'delta_turns':1,'turn_index':row['turn_index']+1,
        'rng_state_ref':digest(before_rng),'rng_before':before_rng,'rng_after':copy.deepcopy(rng.bit_generator.state),
        'state_revision':row['revision']+1,'catalog_revision':base['revision']+1,'updated':True,'replayed':False,
        'parameters':params,'propagation':propagation,'jump':jump['jump'],'original_appraisal_jump':original['jump'],
        'reappraisal_jump_difference':(np.array(jump['jump'])-np.array(original['jump'])).tolist(),
        'jump_applied':jump['jump_applied'],'before_fast':row['fast'],'before_mood':row['mood'],'pre_jump_fast':fast.tolist(),
        'clock_status':'rollback_no_time_reversal' if at<row['last_at'] else 'long_offline_exact' if dt>2592000 else 'zero_interval' if not dt else 'advanced',
        'model_switch':{'from':row['model_version'],'to':model['sha256'],'state_preserved':True} if row['model_version']!=model['sha256'] else None,
        'trait_version_read':profile['trait_profile']['version'],'trait_written':False,'state_kind':'computed_simulated_state',
        'input_digest':digest([blocks,packet,relation,goal,strategy]),'link_precision':row['link_precision']}
    row.update(fast=after.tolist(),mood=mood.tolist(),last_at=effective,turn_index=result['turn_index'],revision=result['state_revision'],
        model_version=model['sha256'],rng_state=result['rng_after']);row['events'][event['id']]={'content_sha256':fingerprint,'result':copy.deepcopy(result)}
    out['revision']+=1;validate(out,owner);return out,result

def commit(store,expected_revision,draft_state):
    with store.lock,store.db:
        current=store.meta(KEY)
        if current['revision']!=expected_revision:raise ValueError('情绪状态版本冲突，请重读已提交事件')
        validate(draft_state,store.meta('identity')['id']);store.setmeta(KEY,draft_state)

def current_view(store,profile,event,at):
    """Read the selected stream, never advance time or sample on a read."""
    base=store.meta(KEY);model=model_for(store);key=stream_key(profile['id'],event)
    row=base['streams'].get(key) or initial_stream(base,event,model,seconds(at))
    view=legacy_empty(profile['id'],row['last_at']);view['transition_params']=copy.deepcopy(base['legacy_snapshot']['transition_params'])
    view['emotion'].update(link(row['fast']));view['emotion']['state_revision']=row['revision'];view['mood'].update(link(row['mood'],MOOD_AXES))
    if row['events']:
        result=next(reversed(row['events'].values()))['result'];view['emotion']['categorical_activations']=copy.deepcopy(result['emotion_labels'])
    return view

def legacy_view(base,result,profile):
    """Compatibility DTO only; never invokes the old affect dynamics."""
    out=copy.deepcopy(base);e=out['emotion'];m=out['mood'];ts=seconds(result['at']);aid=digest([result['subject_id'],result['scope'],result['event_id']])[:32]
    e.update(result['affect_observed']);e.update(categorical_activations=copy.deepcopy(result['emotion_labels']),event_id=result['event_id'],appraisal_id=aid,
        onset_at=ts,last_updated=ts,state_revision=result['state_revision'],confidence=1. if result['calibration_status']=='validated' else .2,source_type='affect_v2_computed')
    m.update(result['mood_observed']);m.update(updated_at=ts,source_type='affect_v2_computed',uncertainty=.8)
    checks={k:v for k,v in result['appraisal']['checks'].items() if v is not None}
    app={'id':aid,'event_key':aid,'event_id':result['event_id'],'persona_id':profile['id'],'scope':result['scope'],'person_id':result['person_id'],'at':ts,
         'checks':checks,'evidence_quote':result['appraisal']['quote'],'method':'latent_affect_v2','clock':{'elapsed_seconds':result['delta_seconds'],'event_sequence':result['turn_index']},
         'emotion_before':link(result['before_fast']),'mood_before':link(result['before_mood'],MOOD_AXES),'emotion_model_version':result['affect_model_version']}
    reg={'id':aid+':reg','persona_id':profile['id'],'event_id':result['event_id'],'appraisal_id':aid,'at':ts,'applied':True,
         'strategy':{'none':'none','reappraisal':'cognitive_reappraisal','suppression':'expressive_suppression'}[result['regulation']['strategy']],
         'internal_effect':float(min(1.,np.linalg.norm(result['reappraisal_jump_difference']))),'expression_multiplier':result['expression_plan']['expression_multiplier']}
    out['appraisals'].append(app);out['regulation_actions'].append(reg)
    out['trajectory'].append({'persona_id':profile['id'],'at':ts,'event_id':result['event_id'],'event_key':aid,'scope':result['scope'],'emotion':copy.deepcopy(e),'mood':copy.deepcopy(m)})
    from .traits import snapshot
    trace={'trait_snapshot':snapshot(profile),'appraisal':app,'regulation_action':reg,'emotion_before':app['emotion_before'],'mood_before':app['mood_before'],
        'emotion_state':copy.deepcopy(e),'mood_state':copy.deepcopy(m),'transition_params':out['transition_params'],'replayed':result['replayed'],
        'trait_version':profile['trait_profile']['version'],'emotion_revision':e['state_revision'],'appraisal_id':aid,'provider_contract':'affect-state/2.8.1','dynamics_v2':result}
    return out,trace


def archive_view(existing,current):
    """Merge owner-visible history only at the write boundary. Prompt reads stay scoped."""
    out=copy.deepcopy(current)
    if not existing:return out
    for name,identity in [('appraisals','id'),('regulation_actions','id'),('expressions','turn_id'),('trajectory','event_key')]:
        prior=copy.deepcopy(existing.get(name,[]));seen={r.get(identity) for r in prior if r.get(identity)}
        out[name]=prior+[copy.deepcopy(r) for r in current.get(name,[]) if not r.get(identity) or r[identity] not in seen]
    out['migration']=copy.deepcopy(existing.get('migration'));out['transition_params']=copy.deepcopy(existing['transition_params'])
    return out


def apply_expression_feedback(base, model, profile, event, at, feedback, relation=None, *, standalone=False):
    """Apply post-expression internal appraisal feedback to fast emotion and slow mood.

    Explicitly separates:
    1) Pre-expression inbound event reaction ('inbound_event_reaction' / 'external_partner_response'),
    2) Post-expression internal appraisal ('internal_expression_feedback': delivered_full,
       delivered_partial, voluntary_restraint_or_listening, obstructed_or_suppressed_expression),
    3) Subsequent external partner response on later turns.

    Idempotent per feedback_id and never re-applies the inbound event jump.
    """
    owner = profile['id']
    validate(base, owner)
    validate_model(model, owner)
    out = copy.deepcopy(base)
    at = seconds(at)
    base_event = {
        'id': str(event.get('id') or 'internal_expr'),
        'text': str(event.get('text') or 'internal_expression_appraisal'),
        'scope': str(event.get('scope') or 'private:web:owner'),
        'person': str(event.get('person') or 'web:owner'),
        'session_id': str(event.get('session_id') or event.get('scope') or 'private:web:owner'),
    }
    key = stream_key(owner, base_event)
    row = out['streams'].setdefault(key, initial_stream(base, base_event, model, at))
    if not isinstance(feedback, dict) or not feedback.get('applied') or not feedback.get('checks_delta'):
        return out, {
            'applied': False,
            'updated': False,
            'replayed': False,
            'event_origin': 'internal_expression_feedback',
            'reason': (feedback or {}).get('rationale', 'no_feedback_delta'),
        }

    kind = str(feedback.get('internal_event_kind') or feedback.get('outcome') or 'expression_outcome')
    fb_id = str(feedback.get('feedback_id') or f"expr_fb:{base_event['id']}:{kind}")
    deltas = {k: float(v) for k, v in (feedback.get('checks_delta') or {}).items() if v is not None}
    fingerprint = digest([fb_id, kind, deltas, base_event['scope'], base_event['person']])
    applied_map = row.setdefault('expression_feedback_events', {})
    if fb_id in applied_map:
        prev = applied_map[fb_id]
        if prev.get('content_sha256') != fingerprint:
            raise ValueError('同一表达反馈事件 ID 的评价内容发生变化')
        cached = copy.deepcopy(prev['result'])
        cached.update(updated=False, replayed=True)
        return out, cached

    blocks = construct_blocks(profile)
    params = parameters(model, blocks)
    before_fast = [float(x) for x in row['fast']]
    before_mood = [float(x) for x in row['mood']]
    effective = max(at, row['last_at'])
    dt = effective - row['last_at']
    before_rng = copy.deepcopy(row['rng_state'])
    rng = np.random.default_rng()
    rng.bit_generator.state = before_rng

    if standalone and dt > 0:
        fast_prop, mood_prop, propagation = propagate(before_fast, before_mood, params, dt, rng, 0)
    else:
        fast_prop = np.asarray(before_fast, dtype=float)
        mood_prop = np.asarray(before_mood, dtype=float)
        propagation = None

    from .registry import APPRAISAL_IDS
    # Map signed checks_delta in [-0.5, 0.5] into [0, 1] check inputs around 0.5 so
    # affect_response.masked(v) = 2*v - 1 = 2*delta drives model['parameters']['jump_W'].
    internal_checks = {}
    for k in APPRAISAL_IDS:
        if k in deltas and abs(deltas[k]) > 1e-9:
            internal_checks[k] = float(max(0.0, min(1.0, 0.5 + deltas[k])))
        else:
            internal_checks[k] = None

    fb_packet = {
        'checks': internal_checks,
        'mask': {k: internal_checks[k] is not None for k in APPRAISAL_IDS},
        'event_facts': {
            'event_id': fb_id,
            'parent_event_id': base_event['id'],
            'text': base_event['text'][:300],
            'scope': base_event['scope'],
            'person': base_event['person'],
            'internal_event_kind': kind,
        },
        'evidence_ids': [base_event['id']],
        'quote': base_event['text'][:180],
        'kind': 'internal_expression_appraisal_not_external_fact',
        'reappraisal_candidate': None,
    }
    after_fast, jump = response(model, fb_packet, blocks, relation or {}, mood_prop, fast_prop)
    delta_fast = after_fast - fast_prop

    # Couple the post-expression fast emotion shift into slow mood via coupled_moments
    after_mood = np.asarray(mood_prop, dtype=float).copy()
    reflect_horizon = 90.0
    for i in range(3):
        mean_with, _ = coupled_moments(
            float(after_fast[i]), float(mood_prop[i]),
            params['mu'][i], params['mu'][i + 5],
            params['kappa'][i], params['kappa'][i + 5],
            0.0, 0.0, params['coupling'][i], reflect_horizon
        )
        mean_base, _ = coupled_moments(
            float(fast_prop[i]), float(mood_prop[i]),
            params['mu'][i], params['mu'][i + 5],
            params['kappa'][i], params['kappa'][i + 5],
            0.0, 0.0, params['coupling'][i], reflect_horizon
        )
        after_mood[i] = float(mood_prop[i]) + float(mean_with[1] - mean_base[1])

    observed_fast = link(after_fast)
    observed_mood = link(after_mood, MOOD_AXES)

    in_turn_event = (not standalone) and (base_event['id'] in row['events'])
    if in_turn_event:
        state_rev = row['revision']
        cat_rev = out['revision']
    else:
        state_rev = row['revision'] + 1
        cat_rev = out['revision'] + 1

    fb_result = {
        'schema': SCHEMA,
        'subject_id': owner,
        'event_id': fb_id,
        'parent_event_id': base_event['id'],
        'event_origin': 'internal_expression_feedback',
        'internal_event_kind': kind,
        'outcome': feedback.get('outcome'),
        'rationale': feedback.get('rationale'),
        'delivered_externally': bool(feedback.get('delivered_externally', False)),
        'scope': base_event['scope'],
        'person_id': base_event['person'],
        'session_id': base_event['session_id'],
        'at': iso(effective),
        'received_at': iso(at),
        'affect_model_version': model['sha256'],
        'calibration_status': model['calibration']['status'],
        'checks_delta': copy.deepcopy(deltas),
        'internal_appraisal_checks': {k: v for k, v in internal_checks.items() if v is not None},
        'before_fast': before_fast,
        'before_mood': before_mood,
        'fast_state_latent': after_fast.tolist(),
        'slow_mood_latent': after_mood.tolist(),
        'jump': jump['jump'],
        'mood_coupling_delta': (after_mood - mood_prop).tolist(),
        'affect_observed': observed_fast,
        'mood_observed': observed_mood,
        'emotion_labels': jump['emotion_labels'],
        'label_activations': jump['label_activations'],
        'label_status': jump['label_status'],
        'state_revision': state_rev,
        'catalog_revision': cat_rev,
        'delta_seconds': dt,
        'delta_turns': 0,
        'turn_index': row['turn_index'],
        'updated': True,
        'replayed': False,
        'applied': True,
    }

    row.update(
        fast=after_fast.tolist(),
        mood=after_mood.tolist(),
        last_at=effective,
        revision=state_rev,
        rng_state=copy.deepcopy(rng.bit_generator.state),
    )
    applied_map[fb_id] = {'content_sha256': fingerprint, 'result': copy.deepcopy(fb_result)}

    if in_turn_event:
        ev_res = row['events'][base_event['id']]['result']
        ev_res.setdefault('event_origin', 'inbound_event_reaction' if row['turn_index'] <= 1 else 'external_partner_response')
        ev_res.setdefault('pre_expression_fast_state_latent', copy.deepcopy(before_fast))
        ev_res.setdefault('pre_expression_slow_mood_latent', copy.deepcopy(before_mood))
        ev_res.setdefault('pre_expression_affect_observed', copy.deepcopy(ev_res['affect_observed']))
        ev_res.setdefault('pre_expression_mood_observed', copy.deepcopy(ev_res['mood_observed']))
        ev_res['fast_state_latent'] = after_fast.tolist()
        ev_res['slow_mood_latent'] = after_mood.tolist()
        ev_res['post_expression_affect_observed'] = observed_fast
        ev_res['post_expression_mood_observed'] = observed_mood
        ev_res['expression_feedback'] = copy.deepcopy(fb_result)
        ev_res['expressive_drive_feedback'] = copy.deepcopy(fb_result)
    else:
        row['events'][fb_id] = {'content_sha256': fingerprint, 'result': copy.deepcopy(fb_result)}
        out['revision'] = cat_rev

    validate(out, owner)
    return out, fb_result
