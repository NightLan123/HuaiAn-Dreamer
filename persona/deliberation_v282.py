"""Same-subject, event-specific response proposals and explainable resolution.

This is the proposal boundary of the existing PMM, not a replacement personality
or affect model. Existing numerical results are read-only conditions. Local
heuristics and support softmax are engineering initial values, not calibrated
psychological probabilities or evidence of a permanent trait change.
"""
from __future__ import annotations
import copy, hashlib, json, math, re
from .provider import ProviderError
from .psychology import ACTIONS
from .registry import LONG_IDS
from .common import dumps

SCHEMA='pmm-deliberation/2.8.2'
VERSION='same-subject-proposals/1'
MAX_PERSPECTIVES=5
MAX_PROPOSALS=8
MAX_RETRIEVAL_QUERIES=4
TEMPERATURE=.25
_LOCKED_GATES={'hard_boundary','missing_evidence','knowledge_uncertain','image_unavailable','permission_withdrawn'}
_REQUIRED_PROPOSAL=('task_handling','content_goal','social_strategy','knowledge_policy')

class DeliberationFailure(ProviderError):
    def __init__(self,path,reason):
        self.code='INVALID_DELIBERATION'
        super().__init__('内部讨论输出不符合方案协议：'+path+' · '+reason,
            {'code':self.code,'schema_version':SCHEMA,'path':path,'reason':reason})

def _digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str).encode()).hexdigest()

def _finite(value,path,minimum=0.,maximum=1.):
    if type(value) not in (int,float) or not minimum<=value<=maximum or not math.isfinite(value):
        raise DeliberationFailure(path,'finite_number_required')
    return float(value)

def _text(value,path,limit=2000):
    if not isinstance(value,str) or not value.strip() or len(value)>limit:
        raise DeliberationFailure(path,'nonempty_bounded_text_required')
    return value.strip()

def _strings(value,path,limit=12):
    if not isinstance(value,list) or len(value)>limit or any(not isinstance(v,str) or len(v)>2000 for v in value):
        raise DeliberationFailure(path,'bounded_string_list_required')
    return copy.deepcopy(value)

def _number(value,default=0.):
    return float(value) if type(value) in (int,float) and math.isfinite(value) else default

def _affect(context):
    emotion=context.get('emotion') or context.get('activity') or {}
    state=emotion.get('emotion',emotion.get('short',emotion)) if isinstance(emotion,dict) else {}
    if isinstance(state,dict) and isinstance(state.get('state'),dict):state=state['state']
    mood=emotion.get('mood',{}) if isinstance(emotion,dict) else {}
    labels=(emotion.get('emotion_state') or {}).get('categorical_activations') or (context.get('emotion_dynamics') or {}).get('emotion_labels') or {}
    return {'current':{k:_number(state[k]) for k in ('valence','arousal','stress','engagement') if isinstance(state,dict) and k in state},
        'mood':{k:_number(mood[k]) for k in ('valence','arousal','stress','engagement') if isinstance(mood,dict) and k in mood},
        'categorical_activations':{k:v for k,v in labels.items() if type(v) in (int,float) and math.isfinite(v)}}

def _personality(profile):
    """Keep known posterior estimates and uncertainty, never matrices/evidence bodies."""
    from .known_personality import operative_personality
    return operative_personality(profile)

def _evidence(context,event,raw):
    raw_message=event.get('raw_message',{})
    current_ref=raw_message.get('message_id') or event.get('event_ref') or context.get('event_ref') or 'current_input'
    evidence={str(current_ref):{'kind':'current_input','scope':raw_message.get('scope',context.get('scope')),
        'digest':_digest(raw),'verifiability':'observed_input'}}
    for row in event.get('context_evidence',[]):
        if not isinstance(row,dict) or not row.get('id') or not isinstance(row.get('content'),str):continue
        if row.get('scope')!=raw_message.get('scope') or row.get('role') not in ('user','assistant'):continue
        evidence[row['id']]={'kind':'conversation_record','scope':row['scope'],'role':row['role'],
            'digest':_digest(row['content']),'verifiability':'observed_conversation_not_external_fact'}
    for memory in context.get('memories',[]):
        if not isinstance(memory,dict) or not isinstance(memory.get('id'),str):continue
        scope=raw_message.get('scope',context.get('scope'))
        if scope is not None and memory.get('scope') not in (scope,'self'):continue
        quote=memory.get('evidence');confidence=_number(memory.get('confidence'),0.)
        reliable=bool(isinstance(quote,str) and quote.strip() and memory.get('kind') not in ('hypothesis','self_observation') and confidence>=.6)
        evidence[memory['id']]={'kind':'memory','scope':memory.get('scope'),'digest':_digest(quote or ''),
            'verifiability':'cited_memory' if reliable else 'unverified_memory','confidence':confidence}
    return str(current_ref),evidence

def _task(context,raw):
    u=context.get('understanding') or {};sem=u.get('semantic') or {}
    need=u.get('knowledge_need','none')
    title_match=re.search(r'《([^》]{1,100})》',raw)
    title=title_match.group(1) if title_match else ('出师表' if '出师表' in raw else None)
    explicit_personal=bool(re.search(r'你(?:曾经|还)?(?:答应|承诺)|说好|我们(?:上次|以前|那次)|promis|last time',raw,re.I)) or (need=='personal' and bool(re.search(r'那天|那次|那回|当时|一起|昨天|前天|刚才|之前|上周|上个月|聊过|说过|跟你说|你说的|我说的|我们聊|咱们',raw)))
    explicit_personal=explicit_personal or bool(re.search(r'(?:我|你)(?:昨天|前天|上次|刚才|之前).{0,12}(?:跟你说|跟我说|告诉你|告诉我|答应|承诺)|我们(?:昨天|上周|刚才).{0,8}(?:说|聊|约)',raw))
    educational=bool(re.search(r'背诵|请背|解释|翻译|计算|总结|咋背|怎么背|recite|translate|explain',raw,re.I))
    knowledge_request=bool(title or need=='general' or educational)
    personal_request=explicit_personal or (need=='personal' and not knowledge_request)
    kind='personal_reference' if personal_request else 'current_fact' if need=='current' else 'knowledge_task' if knowledge_request else 'conversation'
    effective='personal' if explicit_personal and need!='current' else 'general' if kind=='knowledge_task' and need=='personal' else need
    correction=('explicit_shared_conversation_requires_evidence' if effective=='personal' and effective!=need else
        'educational_recall_is_not_shared_autobiography' if effective=='general' and effective!=need else None)
    goal=('完成关于《'+title+'》的知识任务') if title and kind=='knowledge_task' else str(u.get('intent') or '回应当前用户提出的内容')
    if goal in ('回应当前消息','回应当前用户提出的内容'):goal='回应当前原始消息所表达的请求：'+raw[:180]
    if title and kind=='knowledge_task' and re.search(r'背|recite',raw,re.I):goal='回答并按请求背诵《'+title+'》的可确认内容'
    implicit_opening=kind=='knowledge_task' and not re.search(r'请背|背诵全文|给我背|recite the|全文',raw,re.I) and bool(re.search(r'记得|会不会|咋背|还会|remember',raw,re.I))
    unclear_reference=personal_request or (sem.get('ambiguity',0)>=.8 and not knowledge_request and bool(re.search(r'那(?:个|件|篇|项|位)|这(?:个|件|篇|项|位)|怎么办|what do you mean|which',raw,re.I)))
    return {'kind':kind,'content_goal':goal[:500],'topic':title,'knowledge_need':need,
        'knowledge_confidence':_number(u.get('knowledge_confidence'),0.),'implicit_conversation_opening':implicit_opening,
        'corrected_knowledge_need':effective,'knowledge_need_effective':effective,'knowledge_need_correction_reason':correction,
        'has_knowledge_subtask':knowledge_request,'has_personal_reference':personal_request,
        'unclear_reference':unclear_reference,'raw_input_ref':None,
        'task_completion_rule':'实质处理用户原始任务；不能仅输出接受、拒绝或表达风格标签'}

def _proposal(identifier,goal,handling,strategy,knowledge,refs,action='reply',gaps=()):
    return {'id':identifier,'task_handling':handling,'content_goal':goal,'social_strategy':strategy,
        'knowledge_policy':knowledge,'expression_hints':[],'information_gaps':list(gaps),
        'evidence_refs':list(refs),'compat_action':action,'hard_constraint_status':'eligible',
        'expected_consequences':[],'requires_tools':[],'claims_tool_success':False}

def build(context,profile,decision=None):
    """Create the local minimum proposal record from one complete subject state.

    Context accepts the existing Engine assessment fields. The complete profile,
    neural result and affect are used only in the local immutable state digest;
    the retained state is a compact read-only view for downstream reasoning.
    """
    if not isinstance(context,dict) or not isinstance(profile,dict) or not isinstance(profile.get('id'),str):
        raise DeliberationFailure('/context','subject_profile_required')
    u=context.get('understanding') or {};event=context.get('event_packet') or u.get('event_packet') or {}
    raw=event.get('raw_message',{}).get('text',context.get('input',''))
    if not isinstance(raw,str) or not raw.strip():raise DeliberationFailure('/input','raw_input_required')
    turn_id=event.get('turn_id') or context.get('turn_id') or 'pending'
    drive=context.get('expressive_drive') if isinstance(context.get('expressive_drive'),dict) else {}
    state_ref='state:'+_digest({'profile':profile,'emotion':context.get('emotion'),'relationship':context.get('relationship'),
        'neural':context.get('pmm_neural'),'decision_conditions':context.get('decision_conditions')})
    current_ref,evidence=_evidence(context,event,raw);task=_task(context,raw);task['raw_input_ref']=current_ref
    relation=context.get('relationship') or {};affect=_affect(context);traits=_personality(profile)
    familiarity=max(0.,min(1.,_number(relation.get('familiarity'))))
    stress=max(0.,min(1.,_number(affect['current'].get('stress'))))
    sociability=_number((traits.get('hexaco.x.sociability') or {}).get('estimate'),.5)
    stable_source=state_ref+'/stable';relation_ref=state_ref+'/relationship';affect_ref=state_ref+'/affect';drive_ref=state_ref+'/expressive_drive'
    factor_registry={state_ref:'complete_subject_state',stable_source:'stable_personality_and_author_settings',
        relation_ref:'current_relationship',affect_ref:'current_affect',state_ref+'/neural':'existing_numerical_PMM_output',
        drive_ref:'expressive_drive_and_unfinished_motives'}
    neural=context.get('pmm_neural') or {}
    if not isinstance(neural,dict):neural={}
    neural_summary={key:copy.deepcopy(neural.get(key)) for key in ('formal_eligible','calibration','release_gate','prediction_is_observation','q_provenance') if key in neural}
    neural_summary['state_ref']=state_ref+'/neural'
    neural_summary['latent_digest']=_digest(neural.get('latent'))
    neural_summary['use_policy']='formal_condition' if neural.get('formal_eligible') is True else 'uncalibrated_hypothesis_not_formal_evidence'
    if neural.get('formal_eligible') is True:
        neural_summary['action_tendencies']=copy.deepcopy(neural.get('action_probabilities') or {})
        from .pmm_contracts import BLOCK_IDS
        ids=(neural.get('scale') or {}).get('construct_ids',[]);values=neural.get('state_prediction') or [];mask=neural.get('calibrated_state_mask') or []
        neural_summary['known_state_predictions']={key:values[i] for i,key in enumerate(BLOCK_IDS['H'])
            if key in ids and i<len(mask) and mask[i] and i<len(values) and type(values[i]) in (int,float) and math.isfinite(values[i])}
    drive_summary={k:copy.deepcopy(drive[k]) for k in ('activation','urgency','persistence','expressive_intent','active_motive_id','status','pending_motives_count') if k in drive} if drive else {}
    subject={'profile_id':profile['id'],'profile_revision':profile.get('revision'),'name':profile.get('name'),
        'character':copy.deepcopy(profile.get('character') or {}),'stable_personality':traits,'affect':affect,
        'relationship':{k:copy.deepcopy(relation[k]) for k in ('familiarity','trust','affection','interactions','affiliation','conflict_history') if k in relation},
        'author_settings':{'seed_excerpt':str(profile.get('seed') or ''),'seed_ref':state_ref+'/author_settings','is_excerpt':False},
        'boundaries':[{k:copy.deepcopy(row[k]) for k in ('id','label','keywords','action','hard','enabled','forbidden_quotes') if k in row}
            for row in profile.get('boundaries',[]) if row.get('enabled')],
        'neural_summary':neural_summary,'neural_ref':state_ref+'/neural','state_ref':state_ref,
        'expressive_drive':drive_summary,'expressive_drive_ref':drive_ref,
        'source_policy':'one_complete_subject; temporary_stances_are_not_personalities_or_facts'}
    if (context.get('persona_view') or {}).get('role_catalog'):
        from .prompt_compiler import runtime_persona
        selected=runtime_persona(context['persona_view'],task,query=raw,purpose='discussion')
        subject['character']={'self_reference':(selected.get('character') or {}).get('self_reference','我')}
        subject['author_settings']={'source_ref':selected.get('source_digest'),'version_id':selected.get('version_id')}
        subject['role_entries']=copy.deepcopy(selected.get('role_entries',[]))
        subject['role_selection']=copy.deepcopy(selected.get('role_selection',{}))
    valid_memory=[key for key,row in evidence.items() if row['kind']=='memory' and row['verifiability']=='cited_memory']
    valid_memory += [key for key,row in evidence.items() if row['kind']=='conversation_record'][-3:]
    knowledge='只使用可确认知识；不把基础模型知识当作私人共同经历，也不声称查询过未调用的工具。'
    strategy='按当前关系自然回应；关系未知时不擅称熟人。'
    if familiarity>=.5:strategy='接续已存在的熟悉关系自然回应，保留本轮任务；不虚构额外共同经历。'
    elif relation.get('interactions',0)==0:strategy='回应当前问题，保持尚未建立熟悉关系的称呼和事实边界。'
    if stress>=.6:strategy+='当前压力较高时减少额外社交推进，仍完成必要内容。'
    ed_intent=drive.get('expressive_intent')
    if ed_intent=='BACKCHANNEL':strategy+='当前表达欲指向简短附和（BACKCHANNEL），回应要点后自然让轮。'
    elif ed_intent=='DEFER':strategy+='当前表达欲倾向暂缓展开（DEFER），仅作必要回应并保留未完成动机。'
    elif ed_intent=='CLOSE':strategy+='当前表达目标已满足或趋于收束（CLOSE），自然结束本轮表达。'
    proposals=[];perspectives=[];matrix={};requirements=[]
    if task['kind']=='knowledge_task':
        handling='识别并直接处理“'+task['content_goal']+'”；需要正文时给出可确认正文，不只回答会或不会。'
        proposals.append(_proposal('proposal_content',task['content_goal'],handling,strategy,knowledge,[current_ref]))
    elif task['kind']=='personal_reference' and not valid_memory:
        requirement={'description':'缺少能确定所指经历或承诺的可信来源','required':True,'evidence_refs':[current_ref],'reason':'unverified_personal_reference'}
        requirements.append(requirement)
        proposals.append(_proposal('proposal_identify_reference',task['content_goal'],
            '说明尚不能确定原消息所指的经历或承诺，请对方给出事件线索；不编造自己曾答应的内容。',
            strategy,'未确认的私人往事保持未知；新问题不是旧承诺已经发生的证据。',[current_ref],'clarify',[requirement]))
    elif task['kind']=='current_fact' and not ((decision or {}).get('knowledge') or {}).get('verified_external'):
        proposals.append(_proposal('proposal_verify_current',task['content_goal'],
            '明确当前信息尚未核验，指出完成原始任务需要的最新来源；有真实工具可用才提出核验，不编造实时结论。',
            strategy,'实时事实必须来自可核验的新来源；没有真实查询回执不能声称已查询。',[current_ref],'unknown'))
    elif task['unclear_reference'] and not valid_memory:
        requirement={'description':'原消息所指对象或事件未能确定','required':True,'evidence_refs':[current_ref],'reason':'necessary_reference_missing'}
        requirements.append(requirement)
        proposals.append(_proposal('proposal_identify_reference',task['content_goal'],'就原消息缺少的具体对象或事件询问一个必要问题；不以内部意见分歧代替信息缺口。',strategy,knowledge,[current_ref],'clarify',[requirement]))
    else:
        refs=[current_ref]+valid_memory[:3]
        handling=('依据提供的已引用记忆回应所指经历，区分记忆内容与用户当前的推测。' if task['kind']=='personal_reference' else '回应原始消息的实际内容和交流目的；不强行追加问题或发展无关话题。')
        proposals.append(_proposal('proposal_content',task['content_goal'],handling,strategy,knowledge,refs))
    if ed_intent in ('BACKCHANNEL','DEFER','CLOSE','TAKE_TURN') and proposals:
        proposals[0]['expression_hints'].append('expressive_intent:'+ed_intent)
    if drive.get('resumed_motive') and proposals:
        proposals[0]['expression_hints'].append('resumed_motive:'+str(drive['resumed_motive'].get('motive_id','')))
    base_id=proposals[0]['id']
    salient_base=[{'type':'subject','ref':state_ref},{'type':'relationship','ref':relation_ref},{'type':'affect','ref':affect_ref}]
    if drive:salient_base.append({'type':'expressive_drive','ref':drive_ref})
    perspectives.append({'id':'perspective_event','hypothesis':'按原始消息的直接任务含义理解本轮事件。',
        'confidence':None,'weight':1.,'shared_identity':profile['id'],'shared_state_ref':state_ref,
        'salient_factors':salient_base,
        'evidence_refs':[current_ref]+valid_memory[:3],'goal':task['content_goal'],'proposal_ids':[base_id],
        'expected_consequences':['推进或明确原消息所述任务，保持事实来源。'],'limitations':['来自本地初始假设；是否经B深化见回合调用状态。']})
    matrix['perspective_event']={base_id:.8}
    if task['implicit_conversation_opening']:
        alternative=_proposal('proposal_opening',task['content_goal'],
            '先回答是否掌握该知识，并给出与任务有关的可确认开头或要点；在语境确有需要时让对方选择继续范围，不能只追问而不回应任务。',
            strategy+'将此问句也作为一次话题开启理解。',knowledge,[current_ref])
        proposals.append(alternative)
        # These are explicit contextual engineering values; no extra personality,
        # affect or relationship bonus is added later to count them a second time.
        drive_mod=0.10*(_number(drive.get('activation'),.45)-.45) if drive else 0.
        opening_weight=max(.15,min(.75,.25+.35*familiarity+.15*(sociability-.5)-.1*stress+drive_mod))
        perspectives[0]['weight']=1-opening_weight
        salient_open=[{'type':'subject','ref':state_ref},{'type':'stable_personality','ref':stable_source},{'type':'relationship','ref':relation_ref},{'type':'affect','ref':affect_ref}]
        if drive:salient_open.append({'type':'expressive_drive','ref':drive_ref})
        perspectives.append({'id':'perspective_opening','hypothesis':'用户也可能借知识回忆开启本轮交流，尚未明确要求全文。',
            'confidence':None,'weight':opening_weight,'shared_identity':profile['id'],'shared_state_ref':state_ref,
            'salient_factors':salient_open,
            'evidence_refs':[current_ref],'goal':task['content_goal'],'proposal_ids':['proposal_opening'],
            'expected_consequences':['兼顾实际知识回应和本轮关系语境。'],'limitations':['话题开启只是解释假设，不是用户明确承认的意图。']})
        matrix={'perspective_event':{base_id:.9,'proposal_opening':.65},
            'perspective_opening':{base_id:.6,'proposal_opening':.9}}
    local={'schema':SCHEMA,'version':VERSION,'turn_id':str(turn_id),'trace_id':event.get('trace_id',context.get('trace_id')),
        'persona_id':profile['id'],'shared_state_ref':state_ref,'shared_state':subject,'event_ref':current_ref,
        'event_packet_version':event.get('schema'),'evidence_registry':evidence,'factor_registry':factor_registry,
        'event_packet':copy.deepcopy(event) if event.get('raw_message') else {'schema':'event-packet/2.8.2','turn_id':str(turn_id),
            'raw_message':{'message_id':current_ref,'text':raw,'scope':context.get('scope')},
            'event_analysis':{k:copy.deepcopy(v) for k,v in u.items() if k not in ('event_packet','decision_conditions')},
            'context_refs':copy.deepcopy(context.get('context_refs') or {})},
        'memory_evidence':[{'id':m['id'],'scope':m.get('scope'),'confidence':m.get('confidence'),'kind':m.get('kind'),
            'quote':str(m.get('evidence') or '')[:2000],'is_excerpt':len(str(m.get('evidence') or ''))>2000,
            'source_ref':m['id'],'verifiability':evidence[m['id']]['verifiability']} for m in context.get('memories',[]) if isinstance(m,dict) and m.get('id') in evidence],
        'reasoner_evaluation':{k:copy.deepcopy(context.get('decoded',{}).get(k)) for k in
            ('facts','appraisal_checks','appraisal_evidence','reappraisal_checks','uncertainties','language_condition','evaluation_status') if k in context.get('decoded',{})},
        'task':task,'information_requirements':requirements,'perspectives':perspectives,'proposals':proposals,'utility_matrix':matrix,
        'retrieval_queries':[],
        'actual_tool_receipts':copy.deepcopy(context.get('actual_tool_receipts') or []),
        'disengagement_observed':_number((u.get('semantic') or {}).get('disengagement'))>=.7,
        'local_basis':{'method':'context_conditioned_engineering_initial_values','calibrated':False,
            'personality_affect_relationship_already_in_utilities':bool(task['implicit_conversation_opening']),'additional_bias_terms':{},
            'condition_refs':[state_ref,relation_ref,affect_ref,stable_source]+([drive_ref] if drive else [])},
        'discussion_mode':'local_only','b_status':'not_called','b_trigger_reason':'no_deep_discussion_requested',
        'unresolved_disagreement':len(perspectives)>1,'working_memory_only':True,'learning_evidence':False}
    return resolve(local,decision=decision)

def _refs(value,path,known):
    result=_strings(value,path,32)
    if any(v not in known for v in result):raise DeliberationFailure(path,'unknown_reference')
    if len(set(result))!=len(result):raise DeliberationFailure(path,'duplicate_reference')
    return result

def validate(value,base):
    """Validate model output without accepting its claimed identity or evidence."""
    if not isinstance(value,dict):raise DeliberationFailure('/','object_required')
    headers=('schema','turn_id','persona_id','shared_state_ref','event_ref')
    for field in headers:
        if field in value and value[field]!=base[field]:raise DeliberationFailure('/'+field,'frozen_subject_or_event_mismatch')
    # Shared state and reference registries are not writable by B.
    for field in ('shared_state','evidence_registry','factor_registry','actual_tool_receipts','information_requirements','task','event_packet','memory_evidence','reasoner_evaluation'):
        if field in value and value[field]!=base.get(field):raise DeliberationFailure('/'+field,'local_authority_is_read_only')
    for field in headers:
        if field not in value:raise DeliberationFailure('/'+field,'missing_required_header')
    ps=value.get('perspectives');plans=value.get('proposals');utilities=value.get('utility_matrix')
    if not isinstance(ps,list) or not 1<=len(ps)<=MAX_PERSPECTIVES:raise DeliberationFailure('/perspectives','one_to_five_stances_required')
    if not isinstance(plans,list) or not 1<=len(plans)<=MAX_PROPOSALS:raise DeliberationFailure('/proposals','one_to_eight_concrete_proposals_required')
    evidence=base['evidence_registry'];factors=base['factor_registry'];out=copy.deepcopy(base);rows=[];seen=set()
    for i,row in enumerate(plans):
        path='/proposals/'+str(i)
        if not isinstance(row,dict):raise DeliberationFailure(path,'object_required')
        identifier=_text(row.get('id'),path+'/id',100)
        if identifier in seen:raise DeliberationFailure(path+'/id','duplicate_id')
        seen.add(identifier)
        plan={'id':identifier,**{key:_text(row.get(key),path+'/'+key) for key in _REQUIRED_PROPOSAL}}
        # Labels alone do not satisfy the task/content contract.
        if plan['task_handling'].lower() in ACTIONS or plan['content_goal'].lower() in ACTIONS:
            raise DeliberationFailure(path,'action_label_is_not_a_content_plan')
        topic=base.get('task',{}).get('topic')
        if base.get('task',{}).get('kind')=='knowledge_task' and topic and topic not in plan['task_handling']+plan['content_goal']:
            raise DeliberationFailure(path,'known_task_topic_omitted_from_content_plan')
        plan['evidence_refs']=_refs(row.get('evidence_refs',[]),path+'/evidence_refs',evidence)
        if base['event_ref'] not in plan['evidence_refs']:raise DeliberationFailure(path+'/evidence_refs','current_event_required')
        plan['expression_hints']=_strings(row.get('expression_hints',[]),path+'/expression_hints')
        plan['expected_consequences']=_strings(row.get('expected_consequences',[]),path+'/expected_consequences')
        plan['requires_tools']=_strings(row.get('requires_tools',[]),path+'/requires_tools')
        action=row.get('compat_action')
        if action not in ACTIONS:raise DeliberationFailure(path+'/compat_action','compatibility_action_required')
        plan['compat_action']=action
        status=row.get('hard_constraint_status')
        if status not in ('eligible','blocked','needs_verification'):raise DeliberationFailure(path+'/hard_constraint_status','constraint_status_required')
        plan['hard_constraint_status']=status
        if type(row.get('claims_tool_success',False)) is not bool:raise DeliberationFailure(path+'/claims_tool_success','boolean_required')
        plan['claims_tool_success']=row.get('claims_tool_success',False)
        gaps=row.get('information_gaps',[])
        if not isinstance(gaps,list) or len(gaps)>8:raise DeliberationFailure(path+'/information_gaps','bounded_gap_list_required')
        plan['information_gaps']=[]
        for j,gap in enumerate(gaps):
            if isinstance(gap,str):gap={'description':gap,'required':False}
            if not isinstance(gap,dict) or type(gap.get('required',False)) is not bool:raise DeliberationFailure(path+'/information_gaps/'+str(j),'gap_object_required')
            description=_text(gap.get('description'),path+'/information_gaps/'+str(j)+'/description',500)
            refs=_refs(gap.get('evidence_refs',[base['event_ref']]),path+'/information_gaps/'+str(j)+'/evidence_refs',evidence)
            plan['information_gaps'].append({'description':description,'required':gap.get('required',False),
                'evidence_refs':refs,'reason':str(gap.get('reason','model_hypothesis'))[:100]})
        rows.append(plan)
    proposal_ids={row['id'] for row in rows};stance_rows=[];seen=set()
    for i,row in enumerate(ps):
        path='/perspectives/'+str(i)
        if not isinstance(row,dict):raise DeliberationFailure(path,'object_required')
        identifier=_text(row.get('id'),path+'/id',100)
        if identifier in seen:raise DeliberationFailure(path+'/id','duplicate_id')
        seen.add(identifier)
        if row.get('shared_identity',base['persona_id'])!=base['persona_id'] or row.get('shared_state_ref',base['shared_state_ref'])!=base['shared_state_ref']:
            raise DeliberationFailure(path,'split_subject_state_not_allowed')
        if any(k in row for k in ('profile','personality','traits','identity','stable_personality')):raise DeliberationFailure(path,'stance_cannot_own_a_separate_personality')
        stance={k:_text(row.get(k),path+'/'+k) for k in ('hypothesis','goal')}
        stance.update(id=identifier,weight=_finite(row.get('weight'),path+'/weight'),
            confidence=None if row.get('confidence') is None else _finite(row.get('confidence'),path+'/confidence'),
            shared_identity=base['persona_id'],shared_state_ref=base['shared_state_ref'])
        stance['proposal_ids']=_refs(row.get('proposal_ids'),path+'/proposal_ids',proposal_ids)
        if not stance['proposal_ids']:raise DeliberationFailure(path+'/proposal_ids','must_consider_concrete_proposal')
        stance['evidence_refs']=_refs(row.get('evidence_refs'),path+'/evidence_refs',evidence)
        if not stance['evidence_refs']:raise DeliberationFailure(path+'/evidence_refs','current_evidence_required')
        salient=row.get('salient_factors',[])
        if not isinstance(salient,list) or len(salient)>20:raise DeliberationFailure(path+'/salient_factors','bounded_factors_required')
        stance['salient_factors']=[]
        for factor in salient:
            if not isinstance(factor,dict) or not isinstance(factor.get('ref'),str) or factor['ref'] not in factors:
                raise DeliberationFailure(path+'/salient_factors','unknown_shared_state_factor')
            stance['salient_factors'].append({'type':str(factor.get('type','context'))[:80],'ref':factor['ref']})
        for key in ('expected_consequences','limitations'):stance[key]=_strings(row.get(key,[]),path+'/'+key)
        stance_rows.append(stance)
    mass=sum(v['weight'] for v in stance_rows)
    if not mass:raise DeliberationFailure('/perspectives/weight','nonzero_activation_mass_required')
    for stance in stance_rows:stance['weight']/=mass
    if not isinstance(utilities,dict) or set(utilities)!=seen:raise DeliberationFailure('/utility_matrix','exact_stance_ids_required')
    matrix={}
    for key,row in utilities.items():
        if not isinstance(row,dict) or set(row)!=proposal_ids:raise DeliberationFailure('/utility_matrix/'+key,'exact_proposal_ids_required_not_six_actions')
        matrix[key]={pid:_finite(score,'/utility_matrix/'+key+'/'+pid) for pid,score in row.items()}
    if type(value.get('unresolved_disagreement',False)) is not bool:raise DeliberationFailure('/unresolved_disagreement','boolean_required')
    # B may ask the existing scoped retriever for more evidence, but cannot
    # supply records, destinations, SQL or a new scope through this contract.
    # The Engine owns execution and its configured bounded round count.
    queries=value.get('retrieval_queries',[])
    if not isinstance(queries,list) or len(queries)>MAX_RETRIEVAL_QUERIES:
        raise DeliberationFailure('/retrieval_queries','bounded_query_list_required')
    queries=[_text(query,'/retrieval_queries/'+str(i),200) for i,query in enumerate(queries)]
    if len(set(queries))!=len(queries):raise DeliberationFailure('/retrieval_queries','duplicate_query')
    out.update(perspectives=stance_rows,proposals=rows,utility_matrix=matrix,
        retrieval_queries=queries,
        unresolved_disagreement=value.get('unresolved_disagreement',False),discussion_mode='local_plus_B',b_status='completed',
        model_summary=str(value.get('summary',''))[:1000])
    return out

def _guard(base,decision):
    action=(decision or {}).get('action')
    gate=(decision or {}).get('gate')
    # Action scores already contain A, personality, relationship and drive.
    # Content proposals refine that decision; they must not replace it with the
    # sole default proposal. B's content alternatives remain available inside it.
    if gate=='weighted_policy' and action in ACTIONS and action!='silence':return action,'weighted_policy'
    if gate in _LOCKED_GATES and action in ACTIONS:return action,gate
    if action=='silence' and base.get('disengagement_observed'):return action,'confirmed_disengagement'
    if gate=='ambiguity' and any(r.get('required') for r in base.get('information_requirements',[])) and action=='clarify':return action,gate
    # The executable resolver may apply a final boundary/cognitive policy after
    # initial proposal scoring. Its preserved action and the content plan must
    # agree. The retired close-margin gate is explicitly not such authority.
    if gate and gate not in ('weighted_policy','ambiguity','proposal_policy','unresolved_conflict') and action in ACTIONS:
        return action,gate
    return None,None

def resolve(base,model_result=None,decision=None):
    """Resolve concrete proposals, with hard gates preceding relative support.

    Use ``resolve(base)`` for a local/skipped-B path, and
    ``resolve(base, model_result=raw_B)`` after a real B call. An invalid B result
    raises DeliberationFailure so the caller can preserve the error and explicitly
    choose local fallback. No provider call, permanent write or emotion update
    happens here.
    """
    out=validate(model_result,base) if model_result is not None else copy.deepcopy(base)
    # A concrete newly discovered gap can be considered when the independent
    # input analysis also reported ambiguity. A model's uncertainty or tied
    # utilities alone cannot create a mandatory question.
    ambiguity=((out.get('event_packet') or {}).get('event_analysis') or {}).get('semantic',{}).get('ambiguity',0)
    if out.get('b_status')=='completed' and _number(ambiguity)>=.65:
        requirements=out.setdefault('information_requirements',[])
        known={row.get('description') for row in requirements}
        for proposal in out['proposals']:
            for gap in proposal.get('information_gaps',[]):
                if gap.get('required') and out['event_ref'] in gap.get('evidence_refs',[]) and gap['description'] not in known:
                    requirements.append({**copy.deepcopy(gap),'reason':'B_gap_corroborated_by_independent_input_ambiguity',
                        'corroboration_ref':out['event_ref'],'ambiguity_report':ambiguity})
                    known.add(gap['description'])
    action,gate=_guard(out,decision);out['policy_gate']={'gate':gate,'compat_action':action,'source':'existing_policy'} if action else None
    proposals=out['proposals'];perspectives=out['perspectives'];matrix=out['utility_matrix'];duplicates={};blocked=[];eligible=[]
    for proposal in proposals:
        reasons=[]
        if proposal.get('hard_constraint_status')!='eligible':reasons.append('constraint_'+str(proposal.get('hard_constraint_status')))
        if action and proposal['compat_action']!=action:reasons.append('authoritative_policy_gate:'+gate)
        if proposal['compat_action']=='silence' and not out.get('disengagement_observed') and action!='silence':reasons.append('no_observed_disengagement')
        if proposal.get('claims_tool_success') and not out.get('actual_tool_receipts'):reasons.append('no_actual_tool_receipt')
        if proposal.get('requires_tools') and not out.get('actual_tool_receipts'):reasons.append('required_tool_not_executed')
        # Model uncertainty alone cannot turn a close score into mandatory asking.
        if proposal['compat_action']=='clarify' and action!='clarify' and not any(g.get('required') for g in out.get('information_requirements',[])):
            reasons.append('no_locally_supported_necessary_information_gap')
        private_refs=[r for r in proposal['evidence_refs'] if out['evidence_registry'][r]['kind']=='memory']
        if any(out['evidence_registry'][r]['verifiability']!='cited_memory' for r in private_refs):reasons.append('unverified_memory_source')
        signature=_digest({k:re.sub(r'\s+','',proposal[k]).casefold() for k in _REQUIRED_PROPOSAL})
        if signature in duplicates:
            reasons.append('equivalent_proposal:'+duplicates[signature]);proposal['equivalent_to']=duplicates[signature]
        elif not reasons:duplicates[signature]=proposal['id']
        proposal['eligibility']={'eligible':not reasons,'reasons':reasons}
        if reasons:blocked.append({'id':proposal['id'],'reasons':reasons})
        else:eligible.append(proposal['id'])
    if not eligible:
        required=action or 'unknown';guard=_proposal('proposal_policy_guard',out['task']['content_goal'],
            {'decline':'明确拒绝原请求中不允许的部分，并说明仍可处理的任务范围。',
             'unknown':'说明当前缺少可核验信息，保留原任务并指出完成所需来源；不虚构知识、经历或工具结果。',
             'clarify':'只询问完成原任务所缺少的必要信息，不把内部意见分歧当作追问理由。',
             'silence':'遵循已确认的停止交流或权限约束，不生成待发送内容。'}.get(required,'在已确认的约束内处理原任务。'),
            '保留当前主体身份、关系与情绪条件，不通过投票越过明确约束。','只使用已确认来源；不虚构授权和已执行操作。',
            [out['event_ref']],required,out.get('information_requirements',[]) if required=='clarify' else [])
        guard['eligibility']={'eligible':True,'reasons':[]};guard['constraint_origin']=gate or 'no_feasible_proposal'
        # The guard is a deterministic policy result, not a fabricated model vote.
        proposals.append(guard);eligible=[guard['id']]
        for stance in perspectives:matrix[stance['id']][guard['id']]=1.
        out['policy_guard_added']=True
    mass=sum(v['weight'] for v in perspectives)
    if not mass:raise DeliberationFailure('/perspectives','nonzero_activation_mass_required')
    for stance in perspectives:stance['weight']/=mass
    scores={pid:sum(stance['weight']*matrix[stance['id']][pid] for stance in perspectives) for pid in eligible}
    maximum=max(scores.values());weights={pid:math.exp((score-maximum)/TEMPERATURE) for pid,score in scores.items()};den=sum(weights.values())
    support={pid:weights[pid]/den for pid in eligible};selected=max(eligible,key=lambda pid:(scores[pid],-eligible.index(pid)))
    byid={p['id']:p for p in proposals};winner=copy.deepcopy(byid[selected])
    favourites={max(eligible,key=lambda pid:(matrix[v['id']][pid],-eligible.index(pid))) for v in perspectives}
    out.update(support=support,scores=scores,selected_proposal_id=selected,selected_proposal=winner,
        contributions={pid:[{'perspective_id':v['id'],'weight':v['weight'],'utility':matrix[v['id']][pid],
            'weighted_utility':v['weight']*matrix[v['id']][pid],'shared_state_ref':out['shared_state_ref']} for v in perspectives] for pid in eligible},
        blocked_proposals=blocked,eligible_proposal_ids=eligible,
        unresolved_disagreement=bool(out.get('unresolved_disagreement')) or len(favourites)>1,
        selection_reason=('原有明确政策门先筛选合法方案；' if action else '')+'在可执行的具体任务方案中选择加权条件效用最高项；分歧保留，不因分差小自动澄清。',
        support_method={'name':'weighted_utility_stable_softmax','temperature':TEMPERATURE,'calibrated':False,
            'meaning':'relative_support_not_psychological_probability','additional_bias_terms':{},
            'double_counting_policy':'personality_affect_relationship_are_context_of_utilities_not_added_again'},
        working_memory_only=True,learning_evidence=False)
    return out

def model_payload(base):
    """One versioned state summary and evidence refs, without the full profile."""
    return {key:copy.deepcopy(base[key]) for key in ('schema','version','turn_id','persona_id','shared_state_ref','shared_state',
        'event_ref','event_packet','memory_evidence','reasoner_evaluation','evidence_registry','factor_registry','task','information_requirements','perspectives','proposals','utility_matrix','retrieval_queries')}

def discussion_payload(base, previous=None):
    """Self-contained request: frozen conditions, current evidence, last valid plans.

    Providers are stateless. An ID never replaces evidence absent from this
    request. Only repeated verbatim spans are interned; source metadata stays.
    """
    payload=model_payload(base); original_bytes=len(dumps(payload).encode('utf-8'))
    mode='initial';delta=None
    if previous and all(previous.get(k)==base.get(k) for k in ('turn_id','persona_id','shared_state_ref','event_ref')):
        known=set(base['evidence_registry']);old=previous.get('evidence_registry') or {}
        delta={'new_or_changed':[k for k,v in base['evidence_registry'].items() if old.get(k)!=v],
               'removed':[k for k in old if k not in known]}
        # Reuse validated proposals as seeds, never their prior support as a fact.
        plans=[copy.deepcopy(p) for p in previous.get('proposals',[]) if set(p.get('evidence_refs',[]))<=known]
        ids={p['id'] for p in plans}
        views=[copy.deepcopy(p) for p in previous.get('perspectives',[])
               if set(p.get('evidence_refs',[]))<=known and set(p.get('proposal_ids',[]))<=ids]
        matrix=previous.get('utility_matrix') or {}
        if plans and views and all(all(pid in matrix.get(v['id'],{}) for pid in ids) for v in views):
            proposal_fields=('id',)+tuple(_REQUIRED_PROPOSAL)+('compat_action','hard_constraint_status','evidence_refs','expression_hints','information_gaps','expected_consequences','requires_tools')
            view_fields=('id','shared_state_ref','hypothesis','goal','weight','evidence_refs','proposal_ids','salient_factors','limitations')
            payload.update(proposals=[{k:v for k,v in p.items() if k in proposal_fields} for p in plans],
                perspectives=[{k:v for k,v in p.items() if k in view_fields} for p in views],
                utility_matrix={v['id']:{pid:matrix[v['id']][pid] for pid in ids} for v in views})
            mode='review_new_evidence_with_previous_plans'
        payload['evidence_delta']=delta
    # Intern exact repeats within this request, retaining all scope/role/source tags.
    fields=('event_packet','memory_evidence','reasoner_evaluation');counts={}
    def count(value):
        if isinstance(value,str) and len(value)>=80:counts[value]=counts.get(value,0)+1
        elif isinstance(value,dict):
            for v in value.values():count(v)
        elif isinstance(value,list):
            for v in value:count(v)
    for field in fields:count(payload[field])
    repeated={value:'text_'+str(i+1) for i,(value,n) in enumerate(counts.items()) if n>1}
    compact=copy.deepcopy(payload)
    def intern(value):
        if isinstance(value,str) and value in repeated:return {'verbatim_text_ref':repeated[value]}
        if isinstance(value,dict):return {k:intern(v) for k,v in value.items()}
        if isinstance(value,list):return [intern(v) for v in value]
        return value
    if repeated:
        for field in fields:compact[field]=intern(compact[field])
        compact['verbatim_texts']={ref:value for value,ref in repeated.items()}
        if len(dumps(compact).encode('utf-8'))<len(dumps(payload).encode('utf-8')):payload=compact
    return payload,{'mode':mode,'evidence_delta':delta,'baseline_bytes':original_bytes,
        'request_bytes':len(dumps(payload).encode('utf-8')),'interned_texts':len(payload.get('verbatim_texts',{})),
        'frozen_conditions_included':True,'measurement':'utf8_bytes_not_provider_tokens'}

def supporting_memory_evidence(bundle):
    """Compatibility evidence bridge; existing policy still verifies relevance.

    A cited quote is a source reference, not a claim that its content is an
    objectively true shared experience. Unknown/unselected memory is excluded.
    """
    used=set((bundle.get('selected_proposal') or {}).get('evidence_refs') or [])
    return [{'id':row['id'],'quote':row['quote']} for row in bundle.get('memory_evidence',[])
        if row.get('id') in used and row.get('verifiability')=='cited_memory' and row.get('quote')]

def supporting_conversation_evidence(bundle):
    used=set((bundle.get('selected_proposal') or {}).get('evidence_refs') or [])
    registry=bundle.get('evidence_registry') or {}
    return [copy.deepcopy(row) for row in (bundle.get('event_packet') or {}).get('context_evidence',[])
        if row.get('id') in used and registry.get(row['id'],{}).get('kind')=='conversation_record']
