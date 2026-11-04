"""Conservative, auditable PMM expression-plan baseline (not a trained policy).

Message segmentation is a *semantic* instruction to the language model.  A break
marker is deliberately distinct from punctuation and newlines. If the model
cannot provide valid complete segments, one message is sent instead.
"""
from __future__ import annotations
import datetime
import re

BREAK = '[[QQ_MSG_BREAK]]'


def _timestamp(s):
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        return float(s)
    except ValueError:
        try:
            return datetime.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
        except (ValueError, OverflowError):
            return None


def learned_chunking(profile, scope):
    """Count *human-authored* consecutive message bursts with genuine timing data."""
    rows = [r for r in profile.get('source_records', [])
            if r.get('source') == 'imported' and
            (r.get('scope') in ('', scope)) and _timestamp(r.get('timestamp')) is not None]
    rows.sort(key=lambda r: _timestamp(r['timestamp']))
    adjacent = 0
    bursts = 0
    evidence = []
    last = None
    for r in rows[-300:]:
        if last is not None:
            dt = _timestamp(r['timestamp']) - _timestamp(last['timestamp'])
            if 0 <= dt <= 15 and r['speaker'] == last['speaker'] and r.get('conversation_id') == last.get('conversation_id'):
                bursts += 1
                evidence.append(r['id'])
            if 0 <= dt <= 90 and r.get('conversation_id') == last.get('conversation_id'):
                adjacent += 1
        last = r
    return {'observations': adjacent, 'consecutive_fragments': bursts,
            'ratio': bursts / adjacent if adjacent else None,
            'evidence_ids': evidence[-12:]}


def decide_expression(profile, scope, decision, understanding, style, relationship, current_emotion):
    """A personality/relationship/state-conditioned candidate, with explicit provenance.

    Defaults to one bubble when contextual evidence for fragmented expression is
    absent. This is an engineering heuristic until a learned pragmatic policy is
    trained and calibrated, not a claim about psychological validity.
    """
    result = {'schema': 'expression-plan/1', 'delivery': 'single', 'max_messages': 1,
              'basis': 'conservative_baseline', 'policy_type': 'heuristic_uncalibrated',
              'allow_interruption': True}
    if ':qq:' not in scope or decision.get('action') != 'reply':
        return result
    sem = understanding.get('semantic', {})
    if sem.get('task', 0) > .55 or sem.get('complexity', 0) > .58 or sem.get('urgency', 0) > .55:
        return result
    chunking = learned_chunking(profile, scope)
    character = profile.get('character') or {}
    setting = ' '.join((str(profile.get('seed', '')), str(character.get('initial_personality', ''))))
    explicitly_fragmented = bool(re.search(r'分(?:开|条|段)(?:发|说|消息)|多条(?:消息|气泡)|碎碎念', setting))
    evidenced = chunking['observations'] >= 8 and chunking['consecutive_fragments'] >= 3 and chunking['ratio'] >= .20
    casual = sem.get('social', 0) >= .55 and sem.get('task', 0) < .3
    social_signal = relationship.get('familiarity', 0) >= .14 or relationship.get('affection', .5) >= .65
    engaged = current_emotion.get('engagement', .5) >= .55
    if (explicitly_fragmented and casual) or (evidenced and casual and social_signal and engaged):
        result.update(delivery='multi', max_messages=4 if evidenced and chunking['ratio'] >= .43 else 3,
                      basis='owner_personality_seed' if explicitly_fragmented else 'imported_turn_timing',
                      evidence_ids=chunking['evidence_ids'], chunking=chunking)
    return result


def prompt_instruction(plan):
    if plan['delivery'] != 'multi':
        return '本轮为一条完整 QQ 消息。不要输出特殊分隔标记。'
    return (f'本轮允许自然的多气泡表达，最多 {plan["max_messages"]} 条，也允许只发一条。'
            '根据互动意图在不同消息之间安排语义边界，必要时先简短认同再补充。'
            f'如果确实需要多条，只用 {BREAK} 分隔，禁止编号、伪造发信人或按逗号机械拆句。'
            '各条必须可独立理解；不要为凑条数而重复或发送半句。')


def parse_message_parts(response, plan):
    if not isinstance(response, str) or not response.strip():
        raise ValueError('回复正文为空')
    if plan['delivery'] != 'multi':
        return [response.replace(BREAK, ' ').strip()]
    parts = [p.strip() for p in response.split(BREAK)]
    if len(parts) == 1 or not 1 <= len(parts) <= plan['max_messages'] or any(not p or len(p) > 2000 for p in parts):
        return [response.replace(BREAK, ' ').strip()]
    if any(re.match(r'^\s*(?:[①②③④]|(?:第[一二三四]条)|\d+[.、])', part) for part in parts):
        return [response.replace(BREAK, ' ').strip()]
    return parts
