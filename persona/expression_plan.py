"""CBM-01: local, sufficient replies; an auditable policy, not a neural head.

The optional planner uses the existing assessment call. Speech acts are not
bubble quotas. Long-term pragmatic demonstrations, simulated affect, and actual
AI output are kept separate. No timer schedules a follow-up after yielding.
"""
from __future__ import annotations
import copy, hashlib, json, math, re
from .common import dumps

SCHEMA = 'interaction-plan/2.1'
BREAK = '[[QQ_MSG_BREAK]]'
STRATEGIES = ('MINIMAL_REPLY', 'RESPOND_AND_YIELD', 'CASUAL_BURST',
              'OPTIONAL_EXPANSION', 'CLARIFY_IF_NEEDED', 'REPAIR', 'NO_ACTION', 'WAIT')
FEATURES = ('local_relevance', 'sufficiency', 'redundancy_risk',
            'premature_progression_risk', 'conversation_burden',
            'spontaneous_motivation', 'persona_consistency')
ACTS = ('invitation', 'tentative_interest', 'complaint', 'question', 'closing',
        'correction', 'narrative', 'unknown')

ASSESS_INSTRUCTION = '''
[INTERACTION_PLAN_CBM01]
在同一次评估中附加 interaction_plan，不增加每气泡调用。只规划当前局部回应，足够即停；
不是 ACCEPT→补充→追问的固定脚本，不把兴趣/熟悉度/情绪直接当作必发几条。
可只说一个短回应。对明确邀请不重复确认意愿；对已经确定的安排不再次提问；
对抱怨不自动布置任务；结束交流可以回应后停止。明确知识/步骤问题须充分回答。
返回 interaction_plan:{"local_goal":"简短目标","strategy":"RESPOND_AND_YIELD",
"previous_act":"invitation/tentative_interest/complaint/question/closing/correction/narrative/unknown 之一",
"evidence_quote":"当前 input 逐字原文","established_facts":[{"fact":"已知事项","quote":"当前原文"}],
"follow_up_need":"确有未解决的必要信息才填，否则空字符串","follow_up_quote":"支持必要性的当前原文",
"allow_follow_up_question":false,"stop_after_reply":true,"sufficiency_target":"minimal/complete",
"split_reason":"仅在独立内容需要分别发送时说明，否则留空",
"forbidden_topic_progression":["不应擅自推进的事项"],
"evaluation":{"local_relevance":null,"sufficiency":null,"redundancy_risk":null,"premature_progression_risk":null,
"conversation_burden":null,"spontaneous_motivation":null,"persona_consistency":null}}。
策略可为 MINIMAL_REPLY/RESPOND_AND_YIELD/CASUAL_BURST/OPTIONAL_EXPANSION/CLARIFY_IF_NEEDED/REPAIR/NO_ACTION/WAIT。
evaluation 可填 0..1 未校准估计或 null，不能伪称量表测分。无依据不填事实、需求或置信度。
'''

REALIZE_INSTRUCTION = '''
[EXPRESSION_CBM01]
interaction_plan 是已冻结行动下的局部表达计划，不许重新决定行动。
已经足够便停止，不自动补全整个对话流程，不强加追问、安排、总结或建议。
一个话语行为可以一条或多条消息；一个气泡也可完成多个行为。max_bubbles 只是上限，没有目标条数。
优先返回 JSON {"message_parts":[{"step_id":"s1","text":"实际发送正文","act":"acknowledge","purpose":"当前片段的功能","depends_on":"current_input"}]}，允许只有一条。
act 可为 acknowledge/accept/empathize/answer/clarify/share/repair/close；交际动作不是气泡配额。
需要对方答复才能说的后续内容不要提前生成，depends_on=user_reply 的部分绝不能在本轮发送。
每条语义独立，不能按标点切碎。提问后停止，必须等对方真实新消息才另起计划。
无 JSON 能力时兼容纯文本；仅用 [[QQ_MSG_BREAK]] 显式区分真正的气泡边界。
各条总长度遵循 style.max_chars；完整回答所需信息优先，不为短句而漏掉必要步骤。
'''

CHECK_INSTRUCTION = '''
同时可返回 pragmatic_check:{"sufficient":true,"unnecessary_followup":false,
"premature_progression":false,"redundant_question":false,"drop_suffix_from":null,"quote":""}。
若候选末尾有多余追问/推进，可用 drop_suffix_from 给出删除起点字符位置，quote 必须与
candidate 从此处到末尾逐字一致，且剩余部分已足够履行冻结行动。不能为简短删掉必要信息。
这些是未校准的生成前检查，不是用户评价或心理测量。未提供时记录为未评估。
'''


def speech_act(text):
    """Explicit, uncalibrated fallback; semantic PMM evidence takes priority."""
    if re.search(r'我先去忙|先走了|不聊了|回头聊|再见|\b(?:bye|gotta go)\b', text, re.I): return 'closing'
    if re.search(r'怎么|如何|为什么|什么原因|\b(?:how|why|what is)\b', text, re.I): return 'question'
    if re.search(r'要不要一起|一起来|你来吗|一起.+[吗？?]|\b(?:join me|want to join)\b', text, re.I): return 'invitation'
    if re.search(r'有点想|最近想|想试试|\b(?:thinking of|might try)\b', text, re.I): return 'tentative_interest'
    if re.search(r'累死|好累|烦死|难受|委屈|\b(?:exhausted|so tired)\b', text, re.I): return 'complaint'
    if re.search(r'不是这个意思|说错了|更正|\b(?:correction|I meant)\b', text, re.I): return 'correction'
    if re.search(r'[?？]|吗[。！!]?$', text): return 'question'
    return 'unknown'


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1 else None


def interaction_state(text, understanding, context, relationship):
    act = speech_act(text)
    return {'prior_speech_act': act, 'pending_response_obligation': 'answer' if act == 'question' else 'acknowledge' if act == 'invitation' else 'none',
            'already_established': [], 'proposed_next_move': None, 'unresolved_need': '',
            'partner_floor_status': 'closing' if act == 'closing' else 'waiting_for_response',
            'topic_sensitivity': None, 'social_distance': number(1 - relationship.get('familiarity', 0)),
            'context_version': context.get('version'), 'source_event_ids': list(context.get('sources', [])),
            'uncertainty': None, 'source_type': 'engineering_fallback_uncalibrated'}


def decide_expression(text, understanding, decision, context, relation, trait_ref, affect_ref, pragmatic, proposal=None):
    state = interaction_state(text, understanding, context, relation)
    proposal = proposal if isinstance(proposal, dict) else {}
    quote = proposal.get('evidence_quote')
    grounded = isinstance(quote, str) and bool(quote.strip()) and quote in text
    warnings = []
    if proposal and not grounded: warnings.append('ungrounded_proposal_ignored')
    p = proposal if grounded else {}
    if p.get('previous_act') in ACTS: state['prior_speech_act'] = p['previous_act']
    act = state['prior_speech_act']
    state['pending_response_obligation'] = 'answer' if act == 'question' else 'acknowledge' if act == 'invitation' else 'none'
    facts = p.get('established_facts', [])
    state['already_established'] = [v for v in facts[:12] if isinstance(v, dict) and isinstance(v.get('fact'), str) and isinstance(v.get('quote'), str) and v['quote'].strip() and v['quote'] in text] if isinstance(facts, list) else []
    need, need_quote = p.get('follow_up_need', ''), p.get('follow_up_quote', '')
    if isinstance(need, str) and isinstance(need_quote, str) and need_quote.strip() and need_quote in text:
        state['unresolved_need'] = need[:400]
    sem = understanding.get('semantic', {})
    phatic=bool(re.fullmatch(r'\s*(?:在吗|在不在|忙吗|还在吗|are you there)[?？。！!\s]*',text,re.I))
    complete = act == 'question' and not phatic or understanding.get('knowledge_need') in ('general', 'current') or sem.get('task', 0) > .55
    complete = complete or p.get('sufficiency_target') == 'complete'
    strategy = 'RESPOND_AND_YIELD'
    if complete: strategy = 'MINIMAL_REPLY'  # minimal *sufficient*, not necessarily short
    if act == 'correction': strategy = 'REPAIR'
    if p.get('strategy', p.get('candidate_strategy')) in STRATEGIES:
        strategy = p.get('strategy', p.get('candidate_strategy'))
    if decision['action'] == 'silence': strategy = 'NO_ACTION'
    elif strategy in ('WAIT', 'NO_ACTION'): strategy = 'RESPOND_AND_YIELD'
    if decision['action'] == 'clarify':
        strategy = 'CLARIFY_IF_NEEDED'
        state['unresolved_need'] = state['unresolved_need'] or decision.get('reason', '冻结行动要求澄清')
    elif strategy == 'CLARIFY_IF_NEEDED' and not state['unresolved_need']:
        strategy = 'RESPOND_AND_YIELD'; warnings.append('clarification_without_need_rejected')
    allow = decision['action'] == 'clarify' or bool(state['unresolved_need'])
    # Tentative interest may permit a light confirmation, never a new task schedule.
    if act == 'tentative_interest' and decision['action'] == 'reply': allow = True
    if act == 'closing' and decision['action'] != 'clarify': allow = False
    max_bubbles = 1 if complete or decision['action'] != 'reply' else 4
    learned_burst=(pragmatic or {}).get('fields',{}).get('burst_propensity',{})
    split_reason=str(p.get('split_reason') or '按完整语义单元选择边界；允许一条，不按标点切碎或凑数')[:400]
    # Only directly comparable human episodes can narrow the delivery envelope.
    # This threshold is an explicit engineering rule, never a learned coefficient.
    if learned_burst.get('effective_episodes',0)>=8 and learned_burst.get('estimate')==0:
        max_bubbles=1;split_reason='当前情境至少八个独立人类示范均为单条，暂优先合并表达（未校准规则）'
    goal = str(p.get('local_goal') or {'invitation':'回应邀请后让轮', 'tentative_interest':'回应当前兴趣，不擅自安排', 'complaint':'回应感受，不自动布置任务', 'closing':'自然结束交流', 'question':'充分回答当前问题'}.get(act, '完成当前回应，足够即停'))[:400]
    state.update(proposed_next_move=strategy, source_type='API_PMM_STRUCTURED' if grounded else 'engineering_fallback_uncalibrated')
    evaluation = p.get('evaluation') if isinstance(p.get('evaluation'), dict) else {}
    plan = {'schema': SCHEMA, 'plan_id': decision['decision_id'] + ':expression', 'decision_id': decision['decision_id'],
            'turn_id': context.get('execution_turn_id'), 'scope': context.get('scope'), 'context_version': context.get('version'),
            'selected_action': decision['action'].upper(), 'previous_act': act, 'response_obligation': state['pending_response_obligation'],
            'established_facts': state['already_established'], 'local_goal': goal, 'sufficiency_target': 'complete' if complete else 'minimal',
            'candidate_strategy': strategy, 'allow_follow_up_question': allow,
            'follow_up_need': state['unresolved_need'] or ('only_if_natural_confirmation' if act == 'tentative_interest' else ''),
            'forbidden_topic_progression': ['无依据安排下一阶段', '重复确认已明确的意愿', '为互动率强行追问'],
            'message_plan': {'delivery': 'single' if max_bubbles == 1 else 'single_or_burst', 'max_bubbles': max_bubbles, 'target_bubbles': None},
            'split_reason':split_reason,
            'yield_after_current_reply': True, 'continuation': 'new_input_only', 'interaction_state': state,
            'evaluation': {k: number(evaluation.get(k)) for k in FEATURES},
            'candidate_comparison': [{'strategy': strategy, 'reason': goal}, {'strategy':'CLARIFY_IF_NEEDED', 'eligible': bool(state['unresolved_need']), 'reason':'只有真实信息缺口才增加回答义务'}],
            'trait_ref': trait_ref, 'affect_ref': affect_ref, 'pragmatic_condition': copy.deepcopy(pragmatic),
            'basis': {'source_event_ids': state['source_event_ids'], 'model_type': state['source_type'], 'calibrated': False, 'warnings': warnings},
            'stop_reason': '本轮完成当前应答即让轮；后续补充必须由真实新输入重新规划',
            'timing': {'mode':'bounded_transport_gap', 'gap_seconds':0.12, 'max_gap_seconds':0.35, 'automatic_followup':False}}
    return plan


def parse_message_parts(response, plan):
    if not isinstance(response, str) or not response.strip(): raise ValueError('回复正文为空')
    plan.pop('realization_steps',None)
    text = response.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.I).strip()
    protocol = 'plain_text'
    if text.startswith(('{', '[')) and BREAK not in text:
        try: value = json.loads(text)
        except ValueError:
            if 'message_parts' in text or 'step_id' in text: raise ValueError('结构化表达不能解析，不发送协议碎片') from None
            value = None
        if value is not None:
            rows = value.get('message_parts') if isinstance(value, dict) else value
            if not isinstance(rows, list) or not 1 <= len(rows) <= 4: raise ValueError('表达需要 1–4 个消息片段')
            if any(not isinstance(r, dict) or not isinstance(r.get('text'), str) or not r['text'].strip() or not isinstance(r.get('step_id'), str) or not r['step_id'] for r in rows): raise ValueError('表达片段缺少 step_id 或正文')
            if len({r['step_id'] for r in rows}) != len(rows): raise ValueError('表达片段 step_id 重复')
            eligible=[]
            for r in rows:
                dependency=r.get('depends_on','current_input')
                if dependency=='user_reply':break
                if dependency!='current_input' and dependency not in {v['step_id'] for v in eligible}:raise ValueError('消息片段依赖未完成的步骤')
                eligible.append(r)
            if not eligible:raise ValueError('当前没有可发送的表达步骤；不能代替尚未收到的回答')
            parts = [r['text'].strip() for r in eligible]; protocol = 'structured_parts'
            plan['realization_steps']=[{'step_id':r['step_id'],'act':r.get('act') if r.get('act') in ('acknowledge','accept','empathize','answer','clarify','share','repair','close') else 'unspecified',
                'purpose':str(r.get('purpose',''))[:300],'depends_on':r.get('depends_on','current_input')} for r in eligible]
        else: parts = [text]
    else:
        parts = [s.strip() for s in text.split(BREAK)]; protocol = 'h2_marker_compat' if len(parts) > 1 else 'plain_text'
        if any(not s for s in parts) or len(parts) > 4: raise ValueError('旧版分段标记包含空消息或超过四条')
    if sum(map(len, parts)) > 20000: raise ValueError('回复过长，本轮未发送')
    if len(parts) > plan['message_plan']['max_bubbles']:
        parts = ['\n'.join(parts)]  # coherent tasks keep complete information
    plan['layout_decision']={'bubbles':len(parts),'reason':'信息完整性或当前情境的示范偏好要求单条' if plan['message_plan']['max_bubbles']==1 else plan['split_reason'],
                             'quota':False,'protocol':protocol}
    return parts, protocol


def trim_excess(parts, plan):
    """Conservative, inspectable suffix edits; action validator runs afterwards."""
    original = list(parts); clean = []
    for part in parts:
        if part not in clean: clean.append(part)
    if plan['sufficiency_target'] == 'minimal' and plan['selected_action'] == 'REPLY':
        output = []
        for part in clean:
            clauses = re.split(r'(?<=[。！？!?\n])', part)
            kept = []
            for clause in clauses:
                question = bool(re.search(r'[?？]|(?:吗|么|呢)\s*$', clause.strip()))
                progression = bool(re.search(r'几关|什么模式|什么时候开|安排(?:一下|时间)|计划(?:一下|行程)|定个(?:时间|计划)', clause))
                redundant = plan['previous_act'] == 'invitation' and bool(re.search(r'你(?:也)?想(?:玩|去)|你要不要', clause))
                if (question and not plan['allow_follow_up_question']) or progression and plan['previous_act'] in ('tentative_interest','invitation','complaint','closing') or redundant:
                    if kept or output: break
                    # Never turn an entire answer into silence; request bounded repair.
                    return original, {'status':'needs_repair','reason':'只有多余追问，缺少足够的当前回应'}
                kept.append(clause)
            if ''.join(kept).strip(): output.append(''.join(kept).strip())
            if len(kept) < len(clauses): break
            if output and re.search(r'[?？]\s*$',output[-1]):break  # yield after a real question
        clean = output or clean
    return clean, {'status':'trimmed' if clean != original else 'unchanged', 'removed_chars':sum(map(len, original))-sum(map(len, clean)), 'source_type':'engineering_check_uncalibrated'}


def pragmatic_check(value, candidate):
    if value is None: return {'status':'not_evaluated', 'source_type':'unknown'}
    if not isinstance(value, dict): raise ValueError('pragmatic_check 必须是对象')
    for key in ('sufficient','unnecessary_followup','premature_progression','redundant_question'):
        if type(value.get(key)) is not bool: raise ValueError('语用校验缺少布尔字段 '+key)
    index = value.get('drop_suffix_from')
    if index is not None and (type(index) is not int or not 0 < index < len(candidate) or value.get('quote') != candidate[index:] or not value['sufficient']): raise ValueError('语用裁剪必须引用完整尾部，且剩余回答充分')
    return {**value, 'status':'evaluated', 'source_type':'model_inference_uncalibrated'}


def diagnostic(plan, parts, receipts=None):
    """Local owner UI, not the redacted support export."""
    return {'plan':copy.deepcopy(plan), 'actual_bubbles':len(parts), 'steps':[{'step_id':f's{i+1}', 'text':v, 'status':'SENT_ACK' if receipts else 'LOCAL_COMMITTED', 'message_id':receipts[i].get('message_id') if receipts and i < len(receipts) else None} for i,v in enumerate(parts)]}
