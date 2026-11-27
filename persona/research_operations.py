"""Explicit research operations; never interpreted as external dialogue evidence."""
import copy
import json
from .common import now, uid
from .registry import digest
from . import expression_drive as ed


def record_event_samples(store, before, after):
    """Index newly committed event observations in the same original transaction."""
    if not before or not isinstance(after, dict): return  # Never backfill imported history.
    from .common import dumps
    from .affect_dynamics_v2 import seconds
    for key,row in after.get('streams',{}).items():
        previous=before.get('streams',{}).get(key,{})
        if previous.get('revision')==row.get('revision'):continue
        for eid,event in row.get('events',{}).items():
            if eid in previous.get('events',{}):continue
            result=event.get('result') or {};observed=result.get('affect_observed')
            if not observed or not result.get('at'):continue
            identity=row['identity'];at=seconds(result['at'])
            identifier='affect_event_sample:'+digest([after['subject_id'],key,eid])
            payload={'id':identifier,'subject_id':after['subject_id'],'stream_key':key,**identity,'at':at,
                'source_kind':'event_observation','source_event_id':eid,'affect_observed':observed,
                'mood_observed':result.get('mood_observed'),'state_revision':result.get('state_revision'),
                'model_version':result.get('affect_model_version'),'trait_version':result.get('trait_version_read'),
                'calibration_status':result.get('calibration_status'),'trait_written':False}
            store.db.execute('INSERT OR IGNORE INTO affect_samples VALUES (?,?,?,?,?,?,?)',
                (identifier,key,identity['scope'],identity['person'],at,'event_observation',dumps(payload)))


def edit_motive(engine, body):
    st = engine.store
    with engine.lock, st.lock, st.db:
        scope, person = body.get('scope'), body.get('person')
        sessions = st.rows('SELECT * FROM sessions WHERE scope=? AND person=? ORDER BY created_at DESC LIMIT 1', (scope, person))
        if not sessions: raise ValueError('请选择当前角色已有的会话与联系人')
        base = st.meta('pmm283_research_drive') or ed.empty_state(engine.profile()['id'])
        if body.get('revision') != base['revision']: raise ValueError('表达状态已变化，请重新读取后操作')
        reason = body.get('reason')
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 500: raise ValueError('请填写本次研究操作原因')
        action = body.get('action'); mid = body.get('motive_id'); at = now()
        if action not in ('create', 'revise', 'abandon'): raise ValueError('研究操作无效')
        if action != 'abandon':
            for field in ('topic', 'intended_goal', 'candidate_point_or_question'):
                if not isinstance(body.get(field), str) or not 1 <= len(body[field].strip()) <= 500: raise ValueError('请完整填写话题、目标和待表达内容')
        draft = copy.deepcopy(base); key = ed.stream_key(engine.profile()['id'], scope, person)
        if action == 'create':
            event = {'id': 'research:'+uid(), 'text': body['candidate_point_or_question'], 'scope': scope, 'person': person,
                     'subject_id': engine.profile()['id'], 'session_id': sessions[0]['id'], 'independent_motive': True}
            draft, result = ed.evaluate_event(base, engine.profile(), event, at, understanding={'topic': body['topic']},
                affect_view=engine.activity(scope, person, sessions[0]['id']), environment={'scope': scope, 'addressed': False},
                appraisal_summary='研究者人工输入，非外部事件')
            mid = result['active_motive_id']
            motive = draft['streams'][key]['motives'][mid]
            motive.update(origin='researcher', research_only=True, learning_eligible=False, automatic_contact_allowed=False)
            motive['source_evidence'] = [{'kind': 'researcher', 'ref': event['id'], 'quote': body['candidate_point_or_question']}]
        else:
            motive = (draft['streams'].get(key) or {}).get('motives', {}).get(mid)
            if not motive or motive.get('origin') != 'researcher': raise ValueError('此入口只能修改人工研究动机')
            if motive['status'] in ('satisfied', 'abandoned'): raise ValueError('已结束的动机保留原记录，请另建动机')
            if body.get('motive_revision') != motive['state_revision']: raise ValueError('动机版本已变化')
            motive.update(updated_at=at, state_revision=motive['state_revision']+1)
            draft['revision'] += 1; draft['streams'][key]['state_revision'] += 1
        if action == 'abandon':
            motive.update(status='abandoned', delivery_outcome='abandoned', defer_reason='researcher_abandoned')
            motive['intended_expression']['stage'] = 'abandoned'
        else:
            motive['content_anchor'].update(topic=body['topic'], summary=body['intended_goal'])
            for target in (motive['content_anchor'], motive['intended_expression']):
                target.update(intended_goal=body['intended_goal'], candidate_point_or_question=body['candidate_point_or_question'],
                              formation_basis=reason, epistemic_status='researcher_input_not_external_fact')
        motive['research_reason'] = reason
        ed.validate(draft, engine.profile()['id']); st.setmeta('pmm283_research_drive', draft)
        st.event('research_motive_edited', {'scope': scope, 'person': person, 'action': action, 'motive_id': mid,
            'reason': reason, 'origin': 'researcher', 'revision': draft['revision'], 'learning_eligible': False})
        return {'ok': True, 'revision': draft['revision'], 'motive': copy.deepcopy(motive), 'sent': False}


class AffectSampling:
    """Persist actual scheduled model evolution using its existing RNG exactly once."""
    KEY = 'affect_sampling_settings'

    def __init__(self, engine):
        self.e = engine
        self.last_poll = 0

    def status(self):
        from . import affect_runtime as ar
        state = self.e.store.meta(ar.KEY) or {}
        return {'settings': self.e.store.meta(self.KEY) or {'enabled': False, 'interval_seconds': 300, 'streams': [], 'revision': 0},
                'streams': [{'key': k, **v['identity']} for k, v in state.get('streams', {}).items()],
                'source_kind': 'model_time_evolution', 'model_calls': 0}

    def configure(self, body):
        st = self.e.store
        with self.e.lock, st.lock, st.db:
            current = self.status(); old = current['settings']; cfg = body.get('settings') or {}
            if body.get('revision') != old['revision']: raise ValueError('采样设置已变化，请重新读取')
            known = {r['key'] for r in current['streams']}
            if type(cfg.get('enabled')) is not bool or type(cfg.get('interval_seconds')) is not int or not 60 <= cfg['interval_seconds'] <= 3600: raise ValueError('采样开关或间隔无效')
            streams = cfg.get('streams')
            if not isinstance(streams, list) or any(not isinstance(s, str) or s not in known for s in streams) or len(streams) > 20: raise ValueError('请选择已有情绪会话')
            if cfg['enabled'] and not streams: raise ValueError('开启采样需要选择会话')
            st.setmeta(self.KEY, {**cfg, 'streams': list(dict.fromkeys(streams)), 'revision': old['revision']+1})
            st.event('affect_sampling_settings', {'enabled': cfg['enabled'], 'interval_seconds': cfg['interval_seconds']})
        return self.status()

    def poll(self):
        if now()-self.last_poll < 10: return
        self.last_poll = now(); cfg = (self.e.store.meta(self.KEY) or {})
        if not cfg.get('enabled') or not self.e.lock.acquire(blocking=False): return
        try:
            from . import affect_runtime as ar
            from .affect_dynamics_v2 import propagate, link, MOOD_AXES
            from .affect_response import parameters
            from .pmm_contracts import construct_blocks
            import numpy as np
            st = self.e.store
            with st.lock, st.db:
                base = st.meta(ar.KEY)
                if not base: return
                draft = copy.deepcopy(base); profile = self.e.profile(); model = ar.model_for(st)
                params = parameters(model, construct_blocks(profile)); count = 0
                for key in cfg['streams']:
                    row = draft['streams'].get(key)
                    if not row: continue
                    previous = st.rows("SELECT MAX(at) AS at FROM affect_samples WHERE stream_key=? AND source_kind='model_time_evolution'", (key,))[0]['at']
                    at = now()
                    if previous and at-previous < cfg['interval_seconds']: continue
                    dt = at-row['last_at']
                    if dt <= 0: continue
                    rng = np.random.default_rng(); rng.bit_generator.state = copy.deepcopy(row['rng_state'])
                    before = digest(row['rng_state'])
                    fast, mood, propagation = propagate(row['fast'], row['mood'], params, dt, rng, delta_turns=0)
                    row.update(fast=fast.tolist(), mood=mood.tolist(), last_at=at, revision=row['revision']+1,
                               rng_state=copy.deepcopy(rng.bit_generator.state), model_version=model['sha256'])
                    identity = row['identity']; sample_id = 'affect_sample:'+digest([profile['id'], key, row['revision'], at])
                    payload = {'id':sample_id, 'subject_id':profile['id'], 'stream_key':key, **identity, 'at':at,
                        'source_kind':'model_time_evolution', 'affect_observed':link(fast), 'mood_observed':link(mood, MOOD_AXES),
                        'state_revision':row['revision'], 'interval_seconds':cfg['interval_seconds'], 'elapsed_seconds':dt,
                        'model_version':model['sha256'], 'trait_version':profile['trait_profile']['version'],
                        'rng_before_ref':before, 'rng_after_ref':digest(row['rng_state']), 'trait_written':False,
                        'calibration_status':model['calibration']['status'], 'gap':bool(previous and at-previous>cfg['interval_seconds']*1.5)}
                    from .common import dumps
                    st.db.execute('INSERT INTO affect_samples VALUES (?,?,?,?,?,?,?)', (sample_id, key, identity['scope'], identity['person'], at, 'model_time_evolution', dumps(payload)))
                    count += 1
                if count:
                    draft['revision'] += count; ar.validate(draft, profile['id']); st.setmeta(ar.KEY, draft)
        finally: self.e.lock.release()


def samples(store, stream_key, start=None, end=None, limit=200, offset=0):
    if not isinstance(stream_key, str) or not stream_key: raise ValueError('请选择具体情绪会话')
    limit=max(1,min(1000,int(limit)));offset=max(0,int(offset));clauses=['stream_key=?'];args=[stream_key]
    if start is not None: clauses.append('at>=?');args.append(float(start))
    if end is not None: clauses.append('at<?');args.append(float(end))
    rows=store.rows('SELECT payload FROM affect_samples WHERE '+' AND '.join(clauses)+' ORDER BY at DESC,id DESC LIMIT ? OFFSET ?',(*args,limit+1,offset))
    return {'items':[json.loads(r['payload']) for r in rows[:limit]], 'has_more':len(rows)>limit, 'offset':offset, 'limit':limit,
            'historical_backfill':False, 'interpolation':False, 'model_calls':0}
