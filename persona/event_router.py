"""Traceable raw event packets and conservative, locally computed call plans."""
from __future__ import annotations
import copy,hashlib,json,re

PACKET='event-packet/2.8.2';ROUTE='cognitive-route/2.8.2'
_RELATION=re.compile(r'你(?:还)?(?:记得|答应|承诺)|我们(?:上次|之前|以前)|说好|承诺|欠我|失望|背叛|remember|promis|last time|you said',re.I)
_RISK=re.compile(r'密码|验证码|授权|转账|支付|自杀|伤害|威胁|password|permission|transfer|suicid',re.I)
_GREETING=re.compile(r'^(?:早(?:上好|啊|安)?|晚安|你好|嗨|在吗|hello|hi|hey|good morning)[！!。,.，?？\s🙂]*$',re.I)

def preflight(text,media=None):
    """Only an unambiguous greeting gets a small initial context, never by length."""
    return 'L1' if _GREETING.fullmatch(text.strip()) and not media else 'L2'

def packet(text,understanding,run,session,history=(),media=None):
    raw_ref=(run.get('input_event_ids') or [run['turn_id']])[0]
    analysis={k:copy.deepcopy(understanding.get(k)) for k in ('intent','semantic','knowledge_need','knowledge_confidence','keywords','value_tension','major_event')}
    events=[]
    for row in understanding.get('events',[]) if isinstance(understanding.get('events'),list) else []:
        if not isinstance(row,dict):continue
        quote=row.get('quote');valid=isinstance(quote,str) and bool(quote.strip()) and quote in text
        events.append({'kind':str(row.get('kind','reported'))[:80],'summary':str(row.get('summary',''))[:500],
            'evidence_ref':raw_ref,'quote':quote if valid else None,'evidence_status':'verified_input' if valid else 'unverified'})
    if not events:events=[{'kind':'current_message','summary':str(understanding.get('intent',''))[:500],
        'evidence_ref':raw_ref,'quote':text,'evidence_status':'verified_input'}]
    return {'schema':PACKET,'turn_id':run['turn_id'],'trace_id':run['trace_id'],
        'raw_message':{'message_id':raw_ref,'source_event_ids':list(run.get('input_event_ids',[])),
            'text':text,'speaker_id':session['person'],'scope':session['scope'],'timestamp':run['started_at'],
            'media_refs':['visual:'+hashlib.sha256(json.dumps(media,ensure_ascii=False,sort_keys=True).encode()).hexdigest()] if isinstance(media,dict) else []},
        'event_analysis':analysis,'events':events,
        'context_evidence':[{'id':r['id'],'role':r.get('role'),'content':r.get('content',''),
            'scope':session['scope'],'source_type':'confirmed_conversation_record_not_external_fact'} for r in history if r.get('id')],
        'context_refs':{'history_message_ids':[r['id'] for r in history if r.get('id')],
            'relationship_object_id':session['person'],'session_id':session['id']},
        'uncertainty':{'ambiguity':understanding.get('semantic',{}).get('ambiguity',0),
            'knowledge_confidence':understanding.get('knowledge_confidence'),'status':'model_report_not_calibrated'}}

def route(event,hard_constraints=(),force_b=False):
    raw=event['raw_message'];text=raw['text'];a=event['event_analysis'];sem=a.get('semantic') or {};reasons=[]
    risk=bool(_RISK.search(text)) or any(b.get('enabled') and b.get('hard') and any(isinstance(k,str) and k.strip() and k.lower() in text.lower() for k in b.get('keywords',[])) for b in hard_constraints)
    relationship=bool(_RELATION.search(text)) or a.get('knowledge_need')=='personal'
    complex_event=bool(a.get('major_event')) or max((sem.get(k,0) for k in ('hostility','urgency','value_conflict','complexity','ambiguity')),default=0)>=.6
    if risk:reasons.append('permission_or_boundary_risk')
    if relationship:reasons.append('history_or_relationship_reference')
    if complex_event:reasons.append('complex_or_uncertain_event')
    if risk or complex_event:level='L3'
    elif relationship or a.get('knowledge_need') not in ('none',None) or sem.get('task',0)>=.4 or raw['media_refs']:level='L2';reasons.append('task_or_evidence_needed')
    elif _GREETING.fullmatch(text.strip()):level='L1';reasons.append('unambiguous_ordinary_greeting')
    else:level='L2';reasons.append('conservative_non_greeting')
    return {'schema':ROUTE,'turn_id':event['turn_id'],'level':level,'trigger_reasons':reasons,
        'retrieval':{'enabled':level!='L1','reason':'current_event_relevance' if level!='L1' else 'no_retrieval_need'},
        'call_A':level!='L1','deepen_B':level=='L3' or force_b,'force_B':bool(force_b),
        'local_personality':True,'local_affect':True,'upgrades':[],
        'budgets':{'understanding':4000,'A':8000 if level!='L1' else 0,'B':5000 if level=='L3' or force_b else 0,'generation':5000},
        'budget_semantics':'soft_targets_not_truncation'}

def upgrade(plan,reason):
    if plan['level']!='L3':plan['upgrades'].append({'from':plan['level'],'to':'L3','reason':reason})
    plan.update(level='L3',call_A=True,deepen_B=True)
    plan['retrieval']['enabled']=True
    plan['budgets'].update(A=8000,B=5000)
    if reason not in plan['trigger_reasons']:plan['trigger_reasons'].append(reason)
    return plan
