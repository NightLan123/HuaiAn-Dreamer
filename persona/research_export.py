"""User-selected metadata export. No credentials, prompts or full chat content."""
import base64
import csv
import datetime
import io
import json
import subprocess
import zipfile
from zoneinfo import ZoneInfo
from .common import now, dumps, VERSION


def export(engine, root, body):
    fields = body.get('fields'); scope = body.get('scope')
    if not isinstance(fields, list) or not fields or set(fields)-{'affect', 'motives', 'calls', 'runs'}:
        raise ValueError('请选择需要导出的记录类别')
    st = engine.store
    sessions = st.rows('SELECT id FROM sessions WHERE scope=?', (scope,))
    if not sessions: raise ValueError('请选择当前角色已有会话范围')
    def stamp(value, end=False):
        day = datetime.date.fromisoformat(value)+datetime.timedelta(days=int(end))
        return datetime.datetime.combine(day, datetime.time(), ZoneInfo('Asia/Shanghai')).timestamp()
    begin, end = stamp(body.get('date_from')), stamp(body.get('date_to'), True)
    if end <= begin or end-begin > 366*86400: raise ValueError('导出日期范围应为一天至一年')
    chosen = {}; session_ids = {r['id'] for r in sessions}; limit = 10000
    def bounded(rows):
        if len(rows)>limit: raise ValueError('记录超过一万条，请缩小日期范围')
        return rows
    if 'affect' in fields:
        rows = bounded(st.rows('SELECT payload FROM affect_samples WHERE scope=? AND at>=? AND at<? ORDER BY at,id LIMIT ?', (scope, begin, end, limit+1)))
        chosen['affect'] = [json.loads(r['payload']) for r in rows]
    if 'motives' in fields:
        rows = bounded(st.rows("SELECT payload FROM events WHERE kind='expressive_motive_transition' AND json_extract(payload,'$.scope')=? AND created_at>=? AND created_at<? ORDER BY created_at,id LIMIT ?", (scope, begin, end, limit+1)))
        allowed = ('transition_id','subject_id','motive_id','scope','person_id','from_status','to_status','kind','at','recorded_at','turn_id','source_event_ids','delivery_outcome','values_before','values_after','origin','research_only')
        chosen['motives'] = [{k:v for k,v in json.loads(r['payload']).items() if k in allowed} for r in rows]
    if 'calls' in fields:
        # Filter in SQL before paging; no unrelated conversation body is fetched.
        journal = engine.journal
        with journal.lock:
            rows = journal.db.execute("""SELECT tc.payload FROM token_calls tc WHERE
                (json_extract(tc.payload,'$.scope')=? OR json_extract(tc.payload,'$.session_id') IN (SELECT value FROM json_each(?))
                 OR EXISTS (SELECT 1 FROM runs r WHERE json_extract(r.payload,'$.scope')=? AND
                    (r.id=tc.turn_id OR r.id IN (SELECT value FROM json_each(tc.payload,'$.turn_ids')))))
                AND json_extract(tc.payload,'$.started_at')>=? AND json_extract(tc.payload,'$.started_at')<?
                ORDER BY json_extract(tc.payload,'$.started_at'),tc.id LIMIT ?""", (scope,dumps(sorted(session_ids)),scope,begin,end,limit+1)).fetchall()
        allowed = ('call_id','turn_id','turn_ids','session_id','scope','persona_id','component_role','task_name','phase_id','model','protocol','provider','started_at','ended_at','duration_ms','status','prompt_tokens','completion_tokens','total_tokens','cache_hit_tokens','cache_miss_tokens','reasoning_tokens','usage_source','provider_usage_fields','persona_view_revision','request_attempt','retry_reason')
        allowed += ('parent_call_id','trigger_reason','response_disposition','request_options')
        chosen['calls'] = [{k:v for k,v in json.loads(r['payload']).items() if k in allowed} for r in bounded(rows)]
    if 'runs' in fields:
        with engine.journal.lock:
            rows=engine.journal.db.execute("""SELECT payload FROM runs WHERE json_extract(payload,'$.scope')=?
                AND json_extract(payload,'$.started_at')>=? AND json_extract(payload,'$.started_at')<?
                ORDER BY json_extract(payload,'$.started_at'),id LIMIT ?""",(scope,begin,end,limit+1)).fetchall()
        allowed=('turn_id','trace_id','persona_id','session_id','scope','started_at','ended_at','status','candidate_status','delivery_status','memory_commit_status','persona_version_id','timing','cognitive_route')
        allowed += ('reasoner_evaluation','negotiation_result')
        from .pmm_coordinator import evaluation_history
        chosen['runs']=[]
        for row in bounded(rows):
            run=json.loads(row['payload'])
            chosen['runs'].append({**{k:v for k,v in run.items() if k in allowed},**evaluation_history(run)})
    try:
        source = subprocess.check_output(['git','rev-parse','HEAD'], cwd=root, text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
        dirty = bool(subprocess.check_output(['git','diff','--name-only'], cwd=root, text=True, stderr=subprocess.DEVNULL, timeout=3).strip())
    except (OSError, subprocess.SubprocessError):source=None;dirty=None
    cfg=engine.config.get();profile=engine.profile()
    from .pmm_connections import connection
    manifest={'schema':'huaian-research-export/1','created_at':now(),'application_version':VERSION,
        'source_commit':source,'source_has_uncommitted_changes':dirty,'subject_id':profile['id'],
        'scope':scope,'date_from':body['date_from'],'date_to':body['date_to'],'timezone':'Asia/Shanghai',
        'profile_revision_at_export':profile['revision'],'model_at_export':{'general':cfg['model'],'pmm_a':connection(cfg,'A')['model'],'pmm_b':connection(cfg,'B')['model']},
        'counts':{k:len(v) for k,v in chosen.items()},'unknown_values_preserved':True,
        'includes_full_chat':False,'includes_credentials':False,
        'call_scope_policy':'Exact scope/session or linked run; shared background calls are counted once in this export and must be deduplicated by call_id across exports. Unattributed historical calls are excluded.',
        'historical_versions':'Use each row version where available; export-time configuration is not historical evidence.'}
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', dumps(manifest))
        for name,rows in chosen.items():
            archive.writestr(name+'.jsonl','\n'.join(dumps(r) for r in rows))
            columns=sorted({k for r in rows for k in r}); text=io.StringIO(newline='')
            writer=csv.DictWriter(text,fieldnames=columns);writer.writeheader()
            for row in rows:
                values={k:dumps(v) if isinstance(v,(list,dict)) else '' if v is None else v for k,v in row.items()}
                # Spreadsheet programs should not interpret string identifiers as formulas.
                values={k:"'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v for k,v in values.items()}
                writer.writerow(values)
            archive.writestr(name+'.csv', '\ufeff'+text.getvalue())
    return {'filename':'HuaiAn_Research_Records.zip','content_base64':base64.b64encode(out.getvalue()).decode(), 'manifest':manifest}
