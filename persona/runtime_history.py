"""Owner-only history views assembled from actual journal and committed events."""
from __future__ import annotations
import copy,json,datetime
from zoneinfo import ZoneInfo
from .token_ledger import aggregate
from .token_prices import TokenPrices,price_records,summarize

def calls_view(engine,turn_id=None):
    return price_records(engine.journal.token_calls(turn_id),TokenPrices(engine.store).get())

def summary_view(calls):return {**aggregate(calls),**summarize(calls)}

def calls_page(engine,limit=50,offset=0,turn_id=None,date_from=None,date_to=None,filters=None):
    def stamp(value,end=False):
        if not value:return None
        day=datetime.date.fromisoformat(value)+datetime.timedelta(days=int(end))
        return datetime.datetime.combine(day,datetime.time(),ZoneInfo('Asia/Shanghai')).timestamp()
    limit=max(1,min(200,int(limit)));offset=max(0,int(offset))
    if date_from and date_to and date_from>date_to:raise ValueError('开始日期不能晚于结束日期')
    if turn_id:
        run=engine.journal.get(turn_id)
        if not run or run.get('persona_id')!=engine.profile()['id']:raise ValueError('当前角色没有这个回合')
    rows,total=engine.journal.token_page(limit,offset,turn_id,stamp(date_from),stamp(date_to,True),filters)
    rows=price_records(rows,TokenPrices(engine.store).get())
    return {'schema':'token-ledger/2.8.2','subject_id':engine.profile()['id'],'calls':rows,
            'summary':summary_view(rows),'summary_scope':'current_page','total':total,
            'offset':offset,'limit':limit,'has_more':offset+len(rows)<total}

def run_view(engine,run,private=False):
    snapshot=run.get('cognitive_snapshot') or {};packet=run.get('event_packet') or {}
    raw=packet.get('raw_message',{}).get('text','')
    if not raw:raw='\n'.join(row.get('text','') for row in run.get('prospective_input',[]) if isinstance(row,dict))
    pmm=snapshot.get('pmm28') or {};discussion=run.get('deliberation')
    component_rows=pmm.get('components') or {}
    components={key:{k:copy.deepcopy(node.get(k)) for k in ('executed','status','elapsed_ms','reason','execution','input_summary','output_summary') if k in node}
        for key,node in component_rows.items() if isinstance(node,dict)}
    calls=calls_view(engine,run['turn_id'])
    saved=engine.store.rows("SELECT payload FROM events WHERE kind IN ('turn','expression_partial') AND json_extract(payload,'$.turn_id')=? ORDER BY created_at DESC LIMIT 1",(run['turn_id'],))
    trace=json.loads(saved[0]['payload']) if saved else {}
    from .pmm_coordinator import evaluation_history
    retrieved=trace.get('retrieved') or snapshot.get('retrieved_evidence') or []
    if not retrieved and discussion:
        retrieved=[{**m,'evidence':m.get('quote'),'source':'retained_discussion_evidence'} for m in discussion.get('memory_evidence',[])]
    confirmed=trace.get('reply','') if run.get('memory_commit_status') in ('COMMITTED','PREFIX_COMMITTED') else ''
    drive=trace.get('expressive_drive') or run.get('expressive_drive') or (component_rows.get('expressive_drive') or {}).get('payload')
    result={k:copy.deepcopy(run.get(k)) for k in ('turn_id','trace_id','persona_id','session_id','started_at','ended_at','status',
        'candidate_status','delivery_status','memory_commit_status','candidate_inspection','cognitive_route','persona_version_id','prompt_compilation','stages','timing','prospective_appraisal','local_retrieval','discussion_stops','discussion_requests')}
    result.update(event_summary=raw[:180] if raw else '旧回合未保存事件包',components=components,
        deliberation=copy.deepcopy(discussion),expressive_drive=copy.deepcopy(drive),**evaluation_history(run,trace.get('pmm28')),
        actual_decision=copy.deepcopy(trace.get('decision')),expression_conditions=copy.deepcopy(trace.get('de_conditions') or trace.get('interaction_plan')),
        token_summary=summary_view(calls),confirmed_reply=confirmed,
        retrieved_refs=[{'id':m.get('id'),'kind':m.get('kind'),'scope':m.get('scope')} for m in retrieved],
        retry_status='must_reconcile_receipt' if run.get('delivery_status')=='DELIVERY_UNKNOWN' else
            'already_committed' if confirmed else 'unsent_review_allowed')
    if private:
        result.update(raw_input=raw,input=raw,event_packet=copy.deepcopy(packet),
            candidate_preview=(run.get('candidate_archive') or [{}])[-1].get('text'),
            retrieved_evidence=[{k:m.get(k) for k in ('id','content','evidence','scope','kind')} for m in retrieved])
    return result

def history(engine,turn_id=None,limit=100,offset=0,date_from=None,date_to=None):
    if turn_id:
        run=engine.journal.get(turn_id)
        if not run or run.get('persona_id')!=engine.profile()['id']:raise ValueError('当前角色没有这个回合记录')
        calls=calls_view(engine,turn_id)
        return {'run':run_view(engine,run,True),'calls':calls,'summary':summary_view(calls)}
    def stamp(value,end=False):
        if not value:return None
        date=datetime.date.fromisoformat(value)
        if end:date+=datetime.timedelta(days=1)
        return datetime.datetime.combine(date,datetime.time(),ZoneInfo('Asia/Shanghai')).timestamp()
    limit=max(1,min(200,int(limit)));offset=max(0,int(offset))
    rows,total=engine.journal.history_page(limit,offset,stamp(date_from),stamp(date_to,True))
    rows=[r for r in rows if r.get('persona_id')==engine.profile()['id']]
    calls=calls_view(engine)
    return {'runs':[run_view(engine,r) for r in rows],'token_summary':summary_view(calls),
        'total':total,'offset':offset,'has_more':offset+len(rows)<total,
        'next_offset':offset+len(rows) if offset+len(rows)<total else None}
