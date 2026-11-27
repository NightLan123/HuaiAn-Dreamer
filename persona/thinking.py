"""Explicit, protocol-aware thinking controls. No speculative provider parameters.

The automatic default only changes the official DeepSeek endpoints to off.
Existing extra_body reasoning settings remain authoritative in auto/default mode.
Model capability rules are documented in docs/ARCHITECTURE.md (DeepSeek/Ollama checked 2026-10-28).
"""
from __future__ import annotations
import copy, re
from urllib.parse import urlsplit

MODES = ('auto', 'default', 'off', 'on', 'low', 'high')
ADAPTERS = ('auto', 'deepseek', 'openai', 'anthropic', 'gemini', 'ollama')
CONTROL_KEYS = {'thinking', 'reasoning', 'reasoning_effort', 'enable_thinking', 'think', 'thinking_budget'}


def has_controls(extra):
    return bool(CONTROL_KEYS.intersection(extra) or
                isinstance(extra.get('generationConfig'), dict) and 'thinkingConfig' in extra['generationConfig'] or
                isinstance(extra.get('output_config'), dict) and 'effort' in extra['output_config'])


def adapter_for(c):
    explicit = c.get('thinking_adapter', 'auto')
    if explicit != 'auto': return explicit
    host = urlsplit(c.get('base_url', '')).hostname
    proto = c.get('provider')
    if host == 'api.deepseek.com' and proto in ('chat_completions','responses','anthropic'): return 'deepseek'
    if host == 'api.openai.com' and proto in ('responses', 'chat_completions'): return 'openai'
    if host == 'api.anthropic.com' and proto == 'anthropic': return 'anthropic'
    if host == 'generativelanguage.googleapis.com' and proto == 'gemini': return 'gemini'
    if proto == 'ollama': return 'ollama'
    return 'unknown'


def apply_thinking(payload, c):
    """Return the actual body and its resolved control; reject conflicts before HTTP."""
    out = copy.deepcopy(payload)
    requested = c.get('thinking_mode', 'auto'); adapter = adapter_for(c)
    if requested not in MODES or c.get('thinking_adapter', 'auto') not in ADAPTERS:
        raise ValueError('Thinking 模式或适配器无效')
    custom = has_controls(c.get('extra_body', {}))
    mode = requested
    if mode == 'auto': mode = 'off' if adapter == 'deepseek' and not custom else 'default'
    info = {'requested': requested, 'effective': mode, 'adapter': adapter,
            'source': 'extra_body' if mode == 'default' and custom else 'provider_default' if mode == 'default' else 'control',
            'parameters': {}, 'adjustments': []}
    if mode == 'default': return out, info
    if custom:
        raise ValueError('Thinking 开关与附加参数重复：请删除 extra_body 中的推理字段，或选择“服务默认 / 附加参数”')
    proto = c['provider']; model = c.get('model', '').lower()
    if mode=='on' and adapter!='ollama':raise ValueError('“开启（布尔）”适用于 Ollama；此服务请选择低 / 高或服务默认')
    params = {}
    if adapter == 'deepseek':
        if proto not in ('chat_completions','responses','anthropic'): raise ValueError('DeepSeek 思考适配器支持 Chat Completions、Responses 和 Messages')
        if 'max_completion_tokens' in out: raise ValueError('DeepSeek 使用 max_tokens；请更改 Token 字段')
        if out.get('stream_options') is not None: raise ValueError('非流式请求不能携带 stream_options，请删除该附加参数')
        if proto=='responses':params={'reasoning':{'effort':'none' if mode=='off' else mode}}
        else:
            params = {'thinking': {'type': 'disabled' if mode == 'off' else 'enabled'}}
            if mode != 'off':
                if proto=='anthropic':params['output_config']={'effort':mode}
                else:params['reasoning_effort'] = mode
    elif adapter == 'openai':
        if proto not in ('responses', 'chat_completions', 'azure_chat'): raise ValueError('OpenAI 推理适配器需要 Responses 或 Chat Completions')
        # Deployment names cannot be inferred. Explicit adapter opts into protocol mapping;
        # known model restrictions still apply and remote errors are never silently retried.
        if mode == 'off' and (re.match(r'^(o[134](?:-|$)|gpt-5(?:-(?:mini|nano))?(?:-20\d\d-\d\d-\d\d)?$)', model) or model.startswith(('gpt-6-astra', 'gpt-6.1-sol'))):
            raise ValueError('此模型不支持关闭推理；请选择低 / 高或服务默认')
        if model.startswith(('gpt-4', 'gpt-3')): raise ValueError('此模型不使用 reasoning_effort；请选择服务默认')
        effort = 'none' if mode == 'off' else mode
        params = {'reasoning': {'effort': effort}} if proto == 'responses' else {'reasoning_effort': effort}
        if proto != 'responses' and 'max_tokens' in out:
            out['max_completion_tokens'] = out.pop('max_tokens'); info['adjustments'].append('max_tokens → max_completion_tokens')
    elif adapter == 'anthropic':
        if proto != 'anthropic': raise ValueError('Claude 思考适配器需要原生 Messages 协议')
        manual = bool(re.match(r'^claude-(?:opus|sonnet|haiku)-4-5(?:-|$)', model) or re.match(r'^claude-(?:opus|sonnet)-4(?:-20|$)', model) or model.startswith('claude-3-7-sonnet'))
        adaptive = model.startswith(('claude-opus-4-6', 'claude-opus-4-7', 'claude-opus-4-8', 'claude-sonnet-4-6', 'claude-opus-5', 'claude-sonnet-5', 'claude-haiku-5-5', 'claude-fable-', 'claude-mythos-'))
        if not manual and not adaptive: raise ValueError('未确认此 Claude 型号的思考能力；请选择服务默认，或按官方文档填写附加参数')
        if mode == 'off':
            if model.startswith(('claude-opus-5-5', 'claude-sonnet-5-5', 'claude-fable-', 'claude-mythos-')):
                raise ValueError('此 Claude 型号不能完全关闭思考；请选择低或服务默认')
            params = {'thinking': {'type': 'disabled'}}
            if model.startswith(('claude-opus-5', 'claude-haiku-5-5')): params['output_config'] = {'effort': 'low'}
        elif adaptive: params = {'thinking': {'type': 'adaptive'}, 'output_config': {'effort': mode}}
        else:
            budget = 1024 if mode == 'low' else 8192
            if out['max_tokens'] <= budget: raise ValueError(f'Claude {mode} 思考预算为 {budget}，输出 Token 上限必须大于该预算')
            params = {'thinking': {'type': 'enabled', 'budget_tokens': budget}}
    elif adapter == 'gemini':
        if proto != 'gemini': raise ValueError('Gemini 思考适配器需要原生 generateContent 协议')
        if model.startswith('gemini-2.5-'):
            if 'pro' in model and mode == 'off': raise ValueError('Gemini 2.5 Pro 不支持关闭思考；请选择低 / 高')
            params = {'generationConfig': {'thinkingConfig': {'thinkingBudget': {'off': 0, 'low': 1024, 'high': 8192}[mode]}}}
        elif re.match(r'^gemini-3(?:\.|-)', model):
            if mode == 'off': raise ValueError('Gemini 3 的低思考不等于关闭；请选择低 / 高或服务默认')
            params = {'generationConfig': {'thinkingConfig': {'thinkingLevel': mode.upper()}}}
        else: raise ValueError('未确认此 Gemini 型号的思考能力；请选择服务默认或使用官方附加参数')
    elif adapter == 'ollama':
        if proto != 'ollama': raise ValueError('Ollama 思考适配器需要原生 Ollama 协议')
        value = False if mode == 'off' else True if mode=='on' else mode
        values = c.get('_thinking_values', [])
        if not any(type(v) is type(value) and v == value for v in values):
            raise ValueError('Ollama 此模型未声明支持所选思考档位；请选择服务默认或模型实际支持的档位')
        params = {'think': value}
    else:
        raise ValueError('无法确认此服务的 Thinking 协议。请明确选择适配器，或选服务默认并填写该服务的附加参数')
    if mode != 'off' and adapter in ('deepseek', 'openai', 'anthropic'):
        for key in ('temperature', 'top_p', 'logprobs', 'top_logprobs'):
            if key in out: out.pop(key); info['adjustments'].append('省略 ' + key)
    for key, value in params.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict): out[key].update(value)
        else: out[key] = value
    info['parameters'] = copy.deepcopy(params)
    return out, info
