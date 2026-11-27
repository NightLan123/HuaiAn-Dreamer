"""Local notifications derived from actual events; no model or external messages."""
from .common import now

TITLES = {'task_completed': '任务已完成', 'task_failed': '任务处理失败',
          'learning_job_failed': '学习任务失败', 'social_failed': '主动联系未完成',
          'social_sent': '主动联系已送达', 'memory_reflection_failed': '记忆候选整理失败'}


def on_event(store, identifier, kind, payload, at):
    title = TITLES.get(kind)
    if kind in ('connection_test', 'pmm281_connection_test') and payload.get('ok') is False:
        title = '心理推理模型连接检查失败' if kind == 'pmm281_connection_test' else '连接检查失败'
    if not title: return
    store.db.execute('INSERT OR IGNORE INTO notifications VALUES (?,?,?,?,?,?)',
                     (identifier, kind, title, identifier, at, None))


def on_learning_change(store, before, after):
    from .registry import digest
    previous = {j['id']: j for j in (before or {}).get('jobs', [])}
    for job in (after or {}).get('jobs', []):
        old = previous.get(job['id'])
        status = job.get('status')
        if old is not None and old.get('status') == status: continue
        title = {'awaiting_review':'学习候选等待复核', 'completed':'学习任务已完成',
                 'analysis_complete':'资料分析已完成', 'budget_paused':'学习任务因预算暂停'}.get(status)
        if not title: continue
        identifier = 'learning_notification:'+digest([job['id'], status, job.get('updated_at')])
        store.db.execute('INSERT OR IGNORE INTO notifications VALUES (?,?,?,?,?,?)',
                         (identifier, 'learning_status', title, job['id'], now(), None))


def page(store, offset=0, limit=50):
    limit=max(1,min(200,int(limit)));offset=max(0,int(offset))
    rows=store.rows('SELECT * FROM notifications ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?', (limit+1, offset))
    return {'items':rows[:limit], 'offset':offset, 'limit':limit, 'has_more':len(rows)>limit,
            'unread':store.rows('SELECT COUNT(*) AS n FROM notifications WHERE read_at IS NULL')[0]['n']}


def on_experience_change(store, before, after):
    from .registry import digest
    old=(before or {}).get('job') or {};job=(after or {}).get('job') or {}
    status=job.get('status')
    if not job.get('id') or (old.get('id'),old.get('status'),old.get('attempts'))==(job['id'],status,job.get('attempts')):return
    title={'awaiting_review':'经历学习候选等待复核','completed':'经历学习已完成','failed':'经历学习未完成'}.get(status)
    if not title:return
    identifier='experience_notification:'+digest([job['id'],status,job.get('attempts'),job.get('completed_at')])
    store.db.execute('INSERT OR IGNORE INTO notifications VALUES (?,?,?,?,?,?)',
        (identifier,'experience_status',title,job['id'],now(),None))


def mark_read(store, identifiers):
    if not isinstance(identifiers,list) or len(identifiers)>200 or any(not isinstance(i,str) for i in identifiers): raise ValueError('通知标识无效')
    with store.lock,store.db:
        for identifier in identifiers:
            store.db.execute('UPDATE notifications SET read_at=COALESCE(read_at,?) WHERE id=?', (now(), identifier))
    return {'ok':True}
