"""Allowlisted transport diagnostics: no keys, prompts, replies, or reasoning text."""
from __future__ import annotations
import math, re

ENUMS = {'enabled', 'disabled', 'adaptive', 'none', 'low', 'medium', 'high', 'max', 'minimal', 'xhigh', 'json_object', 'text', 'json_schema', 'application/json', 'LOW', 'HIGH'}
OPTION_KEYS = {'max_tokens', 'max_completion_tokens', 'max_output_tokens', 'temperature', 'top_p', 'stream', 'store', 'thinking', 'reasoning', 'reasoning_effort', 'enable_thinking', 'think', 'response_format', 'format', 'text', 'generationConfig', 'options', 'output_config', 'type', 'effort', 'budget_tokens', 'thinkingConfig', 'thinkingBudget', 'thinkingLevel', 'maxOutputTokens', 'responseMimeType', 'num_predict', 'includeThoughts'}
ERROR_CODES = {'invalid_request_error', 'invalid_request', 'invalid_argument', 'unsupported_parameter', 'unsupported_value', 'invalid_value', 'model_not_found', 'authentication_error', 'permission_error', 'rate_limit_error', 'rate_limit_exceeded', 'insufficient_quota', 'context_length_exceeded', 'server_error', 'overloaded_error', 'not_found_error', 'bad_request'}
KNOWN_PARAMS = OPTION_KEYS | {'model', 'messages', 'stream_options', 'tool_choice', 'tools', 'input', 'contents', 'system', 'authorization', 'api_key'}


def safe_options(value):
    if isinstance(value, dict):
        return {k: safe_options(v) for k, v in value.items() if k in OPTION_KEYS}
    if value is None or type(value) is bool: return value
    if isinstance(value, (int, float)) and math.isfinite(value): return value
    return value if isinstance(value, str) and value in ENUMS else '[omitted]'


def remote_error(body, status):
    error = body.get('error', {}) if isinstance(body, dict) else {}
    if not isinstance(error, dict): error = {}
    result = {'http_status': status}
    for k in ('type', 'code', 'status'):
        value = str(error.get(k, '')).lower()
        if value in ERROR_CODES: result[k] = value
    param = error.get('param')
    if isinstance(param, str) and all(p in KNOWN_PARAMS for p in param.split('.')): result['param'] = param
    # Some APIs put the rejected parameter only in a free-form message. Classify
    # only fixed field names and fixed causes; never persist the remote message.
    message = str(error.get('message', '')).lower()
    result['mentioned_parameters'] = sorted(k for k in KNOWN_PARAMS if re.search(r'(?<![a-z_])' + re.escape(k.lower()) + r'(?![a-z_])', message))
    for label, fragments in {
        'unsupported_parameter': ('not supported', 'unsupported', 'unknown parameter', 'unrecognized'),
        'invalid_value': ('invalid value', 'must be', 'must use', 'out of range'),
        'context_length': ('context length', 'context_length'),
    }.items():
        if any(f in message for f in fragments): result['cause'] = label; break
    return result


def numeric_usage(value):
    if not isinstance(value, dict): return {}
    result = {}
    for k, v in value.items():
        if not re.fullmatch(r'[A-Za-z_]{1,70}', str(k)): continue
        if not any(word in k.lower() for word in ('token', 'cache', 'duration', 'count')): continue
        if isinstance(v, dict): result[k] = numeric_usage(v)
        elif type(v) in (int, float) and math.isfinite(v) and v >= 0: result[k] = v
    return result


def response_meta(r, proto):
    out = {'usage': numeric_usage(r.get('usage', r.get('usageMetadata', {})))}
    reason = None; reasoning_chars = 0
    if proto in ('chat_completions', 'azure_chat'):
        choice = (r.get('choices') or [{}])[0]; reason = choice.get('finish_reason')
        reasoning_chars = len(choice.get('message', {}).get('reasoning_content') or '')
    elif proto == 'ollama':
        reason = r.get('done_reason'); reasoning_chars = len(r.get('message', {}).get('thinking') or '')
        out['usage'].update(numeric_usage({k: r[k] for k in ('prompt_eval_count', 'eval_count', 'total_duration') if k in r}))
    elif proto == 'anthropic':
        reason = r.get('stop_reason'); reasoning_chars = sum(len(b.get('thinking') or '') for b in r.get('content', []) if b.get('type') == 'thinking')
    elif proto == 'gemini':
        candidate = (r.get('candidates') or [{}])[0]; reason = candidate.get('finishReason')
        reasoning_chars = sum(len(b.get('text') or '') for b in candidate.get('content', {}).get('parts', []) if b.get('thought'))
    else:
        reason = r.get('status')
        detail=r.get('incomplete_details') or {}
        if detail.get('reason') in ('max_output_tokens','content_filter'):out['incomplete_reason']=detail['reason']
        reasoning_chars=sum(len(b.get('text') or '') for item in r.get('output',[]) if item.get('type')=='reasoning' for b in item.get('summary',[]))
    if reason in ('stop', 'length', 'content_filter', 'tool_calls', 'function_call', 'max_tokens', 'end_turn', 'tool_use', 'refusal', 'pause_turn', 'STOP', 'MAX_TOKENS', 'SAFETY', 'RECITATION', 'BLOCKLIST', 'PROHIBITED_CONTENT', 'SPII', 'completed', 'incomplete', 'failed', 'cancelled'):
        out['finish_reason'] = reason
    out['reasoning_chars'] = reasoning_chars
    return out
