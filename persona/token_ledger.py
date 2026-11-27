"""Request-level accounting. Raw prompts and credentials never enter this ledger.

Section counts are explicitly byte heuristics, not vendor token measurements.
Vendor totals remain authoritative; unknown usage remains None.
"""
from __future__ import annotations
import contextvars, hashlib, json, math, re

SCHEMA='token-ledger/2.8.2'
_context=contextvars.ContextVar('huaian_token_ledger',default=None)
_FIELDS=set('current_input input history recent_history trait_prior relationship_schema identity_context boundaries boundary_states visual_observation self emotion relationship interlocutor decision_conditions group_context boundary_model claim_memory social_knowledge_rule decision style memories pmm_decoded expression_plan interaction_plan de_conditions coordinated_pmm understanding activity pragmatic_style appraisal_registry boundary_context projections last_round interaction_state social_graph pmm_neural emotion_dynamics candidate actual_tool_receipts boundary_policy hard_constraints knowledge decision_id decision_revision expected_action persona trigger_reason persona_view_revision response_policy language_examples event_packet base'.split())
_FIELDS.update('shared_state reasoner_evaluation raw_message event_analysis context_evidence context_refs events schema version turn_id trace_id persona_id shared_state_ref event_ref event_packet_version memory_evidence evidence_registry factor_registry task information_requirements perspectives proposals utility_matrix retrieval_queries profile_id profile_revision name character stable_personality affect author_settings neural_summary neural_ref state_ref source_policy records required_fields invalid_output source_context format_error recent_memory attribution elapsed_seconds human_calibration group_observations'.split())

_FIELDS.update({'role_entries','role_selection','catalog_ref'})
_FIELDS.update({'role_conditions','registry','episodes','external_event','mental','outcome','person_views'})

def begin(journal,run):return _context.set((journal,{k:run.get(k) for k in ('turn_id','trace_id','persona_id','session_id','scope')}))
def end(token):_context.reset(token)

def bind_factory(factory,journal,persona_id,role):
    def create(config):
        client=factory(config)
        client.ledger_sink=journal;client.ledger_identity=persona_id;client.ledger_role=role
        return client
    return create

def number(value):
    return value if type(value) is int and value>=0 else None

def normalized_usage(protocol,usage):
    u=usage if isinstance(usage,dict) else {}
    def get(key):return number(u.get(key))
    def nested(key,leaf):return number((u.get(key) or {}).get(leaf)) if isinstance(u.get(key),dict) else None
    p=c=hit=miss=reason=total=None
    if protocol=='ollama':p=get('prompt_eval_count');c=get('eval_count')
    elif protocol=='anthropic':
        # Anthropic excludes cache reads/writes from input_tokens.
        base=get('input_tokens');read=get('cache_read_input_tokens');write=get('cache_creation_input_tokens')
        p=base+sum(x or 0 for x in (read,write)) if base is not None else None
        c=get('output_tokens');hit=read
    elif protocol=='gemini':
        prompt=get('promptTokenCount');tools=get('toolUsePromptTokenCount');thought=get('thoughtsTokenCount')
        p=prompt+(tools or 0) if prompt is not None else None
        answer=get('candidatesTokenCount');c=answer+(thought or 0) if answer is not None else None
        reason=thought;hit=get('cachedContentTokenCount');total=get('totalTokenCount')
    else:
        p=get('prompt_tokens') if get('prompt_tokens') is not None else get('input_tokens')
        c=get('completion_tokens') if get('completion_tokens') is not None else get('output_tokens')
        total=get('total_tokens')
        hit=get('prompt_cache_hit_tokens')
        if hit is None:hit=nested('prompt_tokens_details','cached_tokens')
        if hit is None:hit=nested('input_tokens_details','cached_tokens')
        miss=get('prompt_cache_miss_tokens')
        reason=nested('completion_tokens_details','reasoning_tokens')
        if reason is None:reason=nested('output_tokens_details','reasoning_tokens')
    computed=p+c if p is not None and c is not None else None
    if total is None:total=computed
    if miss is None and p is not None and hit is not None and hit<=p:miss=p-hit
    source_keys=('prompt_tokens','completion_tokens','total_tokens','input_tokens','output_tokens','prompt_cache_hit_tokens',
        'prompt_cache_miss_tokens','prompt_tokens_details','completion_tokens_details','input_tokens_details','output_tokens_details',
        'prompt_eval_count','eval_count','cache_creation_input_tokens','cache_read_input_tokens','promptTokenCount',
        'toolUsePromptTokenCount','candidatesTokenCount','thoughtsTokenCount','totalTokenCount','cachedContentTokenCount')
    from .diagnostics import numeric_usage
    source_fields=numeric_usage({k:u[k] for k in source_keys if k in u})
    return {'prompt_tokens':p,'completion_tokens':c,'total_tokens':total,'provider_usage_fields':source_fields,
        'cache_hit_tokens':hit,'cache_miss_tokens':miss,'reasoning_tokens':reason,
        'usage_source':'provider_actual' if any(v is not None for v in (p,c,total)) else 'unavailable',
        'usage_total_discrepancy':total-computed if total is not None and computed is not None else None,
        'usage_contract':protocol+'/2026-11-04'}

def sections(messages):
    result=[]
    def add(identifier,value):
        raw=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,separators=(',',':'))
        encoded=raw.encode('utf8')
        result.append({'section_id':identifier,'source_ref_digest':hashlib.sha256(encoded).hexdigest(),
            'chars':len(raw),'bytes':len(encoded),'estimate_tokens':math.ceil(len(encoded)/4),
            'tokenizer_id':'utf8-bytes-div4-heuristic/1','usage_source':'local_estimate',
            'included_reason':'existing_request_field'})
    def split(prefix,key,value):
        label=key if key in _FIELDS else 'field_'+hashlib.sha256(str(key).encode()).hexdigest()[:12]
        identifier=prefix+'.'+label
        if key in ('base','shared_state','event_packet') and isinstance(value,dict) and value:
            for child,part in value.items():split(identifier,child,part)
        else:add(identifier,value)
    for i,message in enumerate(messages):
        raw=message.get('content','');prefix=f'm{i}.{message.get("role","unknown")}'
        if isinstance(raw,str):
            head,sep,body=raw.partition('\n条件：')
            try:value=json.loads(body if sep else raw)
            except (ValueError,TypeError):value=None
            if isinstance(value,dict):
                if sep:add(prefix+'.instructions',head)
                for key,part in value.items():
                    # Untrusted JSON key text is hashed rather than copied into logs.
                    split(prefix,key,part)
            else:add(prefix,raw)
        else:
            # Media tokenization is model-specific, and base64 is not text tokens.
            add(prefix+'.media_descriptor',{'blocks':len(raw) if isinstance(raw,list) else 0})
            result[-1].update(estimate_tokens=None,tokenizer_id='media_unavailable',usage_source='unavailable')
    return result

def task(messages):
    system=str(messages[0].get('content','')) if messages else ''
    all_text='\n'.join(str(m.get('content',''))[:300] for m in messages)
    if 'CANDIDATE_REPAIR' in all_text:return 'General','candidate_repair'
    for marker,role,name in (('CANDIDATE_INSPECTION','General','candidate_inspection'),('ACTION_CHECK','General','candidate_inspection'),
        ('PMM_A_EVENT','PMM-A','event_appraisal'),('PMM_B_DELIBERATION','PMM-B','internal_discussion'),
        ('API_PMM_PREPARE','PMM-A','psychological_preparation'),('PMM_REVIEW','PMM-B','internal_review'),
        ('UNDERSTAND','General','understanding'),('REALIZE','General','reply_generation'),('FEEDBACK','PMM','feedback'),
        ('CONSOLIDATE','PMM-A','background_consolidation'),('EXPERIENCE_PERSONALITY_LEARNING','PMM-A','experience_learning'),('DISTILL','PMM-A','evidence_distillation'),
        ('SYNTHESIZE','PMM-A','persona_synthesis'),('COGNITIVE','General','incoming_cognitive_appraisal'),
        ('SOCIAL_DECISION','PMM-A','proactive_decision')):
        if marker in system:return role,name
    return 'unassigned','model_request'

def start_record(call,messages):
    role,name=task(messages);s=sections(messages);context=_context.get()
    name=call.get('task_name') or name
    estimate=sum(v['estimate_tokens'] or 0 for v in s)
    target={'understanding':4000,'event_appraisal':8000,'internal_discussion':5000,
            'reply_generation':5000,'candidate_inspection':1500,'candidate_repair':3000,'prospective_appraisal':4000,'cognitive_json_repair':2500}.get(name)
    return {'schema':SCHEMA,**(context[1] if context else {}),
        **{k:call.get(k) for k in ('call_id','turn_id','trace_id','turn_ids','trace_ids','persona_id','session_id','scope','parent_call_id','model','protocol','started_at') if call.get(k) is not None},
        'phase_id':call.get('stage') or name,'component_role':call.get('component_role') or role,'task_name':call.get('task_name') or name,
        'task_source':'trace_context' if call.get('task_name') else 'prompt_marker_inference',
        'provider':call.get('protocol'),'trigger_reason':call.get('trigger_reason') or name,
        'route_level':call.get('route_level'),'prompt_version':SCHEMA,'persona_view_revision':call.get('persona_view_revision'),
        'request_attempt':call.get('attempt',call.get('retry_count',0)),'retry_reason':call.get('retry_reason'),
        'prompt_sections':s,'estimated_prompt_tokens':estimate,'estimate_complete':all(v['estimate_tokens'] is not None for v in s),
        'budget_target':target,'soft_warning':estimate>target if target else False,'hard_provider_limit':None,
        'status':'requesting','response_disposition':'not_applicable',**normalized_usage(call.get('protocol'),{})}

def save(record,journal=None):
    context=_context.get()
    target=context[0] if context else journal
    if target:target.save_token_call(record)

def finish_record(record,call,journal=None):
    record.update(normalized_usage(call.get('protocol'),call.get('usage')))
    if 'request_options' in call:record['request_options']=call['request_options']
    record.update(status='completed' if call.get('status')=='ok' else 'failed',
        ended_at=call.get('ended_at'),duration_ms=call.get('duration_ms'))
    p=record['prompt_tokens'];estimate=record['estimated_prompt_tokens']
    record['actual_minus_section_estimate']=p-estimate if p is not None else None
    record['budget_exceeded']=p>record['budget_target'] if p is not None and record['budget_target'] is not None else None
    save(record,journal)

def aggregate(records):
    fields=('prompt_tokens','completion_tokens','total_tokens','cache_hit_tokens','cache_miss_tokens','reasoning_tokens')
    return {'calls':len(records),'actual_usage_calls':sum(r.get('usage_source')=='provider_actual' for r in records),
        **{field:sum(r[field] for r in records) if records and all(r.get(field) is not None for r in records) else None for field in fields},
        'known_subtotals':{field:sum(r.get(field) or 0 for r in records) for field in fields},
        'unknown_counts':{field:sum(r.get(field) is None for r in records) for field in fields},
        'cost':None,'cost_status':'prices_not_configured'}
