"""Append-only motive transitions at the original state transaction boundary."""
import base64
import json
from .common import dumps, now
from .registry import digest

KIND = 'expressive_motive_transition'
FIELDS = ('status', 'delivery_outcome', 'defer_reason', 'proactive_defer_count',
          'completed_by_turn_id', 'source_event_ids')


def snapshot(motive):
    if not motive:
        return None
    return {**{k: motive.get(k) for k in FIELDS},
            'stage': (motive.get('intended_expression') or {}).get('stage'),
            'content_digest': digest([motive.get('content_anchor'),motive.get('research_reason')]),
            'reevaluation': {k: (motive.get('reevaluation') or {}).get(k)
                             for k in ('decision', 'reason', 'overlap')}}


def record_changes(store, before, after):
    """Caller owns the state transaction. Never commit, infer delivery or backfill."""
    if not isinstance(after, dict):
        return
    owner = (store.meta('identity') or {}).get('id')
    before_streams = (before or {}).get('streams', {})
    for key, stream in after.get('streams', {}).items():
        old = before_streams.get(key, {}).get('motives', {})
        identity = stream.get('identity') or {}
        for mid, motive in stream.get('motives', {}).items():
            previous = old.get(mid)
            left, right = snapshot(previous), snapshot(motive)
            if left == right:
                continue  # Time decay / page reads do not manufacture lifecycle events.
            transition_id = 'motive_transition:' + digest([owner, key, mid, left, right,
                                                           motive.get('state_revision')])
            row = {'schema': 'motive-transition/1', 'transition_id': transition_id,
                   'subject_id': owner, 'motive_id': mid,
                   'scope': identity.get('scope'), 'person_id': identity.get('person_id'),
                   'from_status': (previous or {}).get('status'), 'to_status': motive.get('status'),
                   'kind': 'observed' if not before else 'created' if previous is None else
                           'transition' if left['status'] != right['status'] else 'reevaluated',
                   'at': motive.get('updated_at'), 'recorded_at': now(),
                   'reason': motive.get('defer_reason') or (motive.get('reevaluation') or {}).get('reason'),
                   'turn_id': motive.get('completed_by_turn_id'),
                   'source_event_ids': motive.get('source_event_ids', []),
                   'delivery_outcome': motive.get('delivery_outcome'),
                   'origin': motive.get('origin','conversation'), 'research_only':bool(motive.get('research_only')),
                   'research_change': {'reason':motive.get('research_reason'),
                       'before':(previous or {}).get('content_anchor'), 'after':motive.get('content_anchor')}
                       if motive.get('origin')=='researcher' else None,
                   'before': left, 'after': right,
                   'values_before': {k: previous.get(k) for k in ('activation', 'urgency', 'persistence')} if previous else None,
                   'values_after': {k: motive.get(k) for k in ('activation', 'urgency', 'persistence')}}
            store.db.execute('INSERT OR IGNORE INTO events VALUES (?,?,?,?)',
                             (transition_id, KIND, dumps(row), row['recorded_at']))


def history(store, scope, person, motive_id, cursor=None, limit=50):
    if not all(isinstance(x, str) and x.strip() for x in (scope, person, motive_id)):
        raise ValueError('请选择具体会话、联系人和动机')
    limit = max(1, min(200, int(limit)))
    clauses = ["kind=?", "json_extract(payload,'$.subject_id')=?",
               "json_extract(payload,'$.scope')=?", "json_extract(payload,'$.person_id')=?",
               "json_extract(payload,'$.motive_id')=?"]
    args = [KIND, store.meta('identity')['id'], scope, person, motive_id]
    if cursor:
        try:
            stamp, ident = json.loads(base64.urlsafe_b64decode(cursor).decode())
            if type(stamp) not in (int, float) or not isinstance(ident, str): raise ValueError()
        except Exception as exc:
            raise ValueError('历史分页位置无效') from exc
        clauses.append('(created_at<? OR (created_at=? AND id<?))')
        args.extend([stamp, stamp, ident])
    rows = store.rows('SELECT id,payload,created_at FROM events WHERE ' + ' AND '.join(clauses)
                      + ' ORDER BY created_at DESC,id DESC LIMIT ?', (*args, limit + 1))
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = base64.urlsafe_b64encode(dumps([rows[-1]['created_at'], rows[-1]['id']]).encode()).decode() if more else None
    return {'schema': 'motive-history/1', 'subject_id': store.meta('identity')['id'],
            'scope': scope, 'person_id': person, 'motive_id': motive_id,
            'items': [json.loads(r['payload']) for r in rows], 'next_cursor': next_cursor,
            'has_more': more, 'coverage': 'recorded_transitions_only_no_historical_backfill'}
