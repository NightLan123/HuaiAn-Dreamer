"""User-configured per-million token arithmetic; never an invoice or price feed.

No default model prices, currency or cache discount is invented. Calculations use
actual ledger usage, and keep unknown billing/counts visibly unpriced.
"""
from __future__ import annotations

import copy
from decimal import Decimal, InvalidOperation
import math
import re

SCHEMA = 'token-prices/2.8.2'
KEY = 'pmm_token_prices'
UNIT = 'per_million_tokens'
_RATE_KEYS = ('input', 'output', 'cache_read', 'cache_write')
_POLICIES = ('unknown', 'bill_usage', 'not_billed')


def _rate(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError('Token单价必须是非负有限数值或留空')
    if isinstance(value, str) and not re.fullmatch(r'[+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', value.strip()):
        raise ValueError('Token单价格式无效')
    try:
        result = Decimal(str(value).strip())
        compatible = float(result)
    except (InvalidOperation, ValueError, OverflowError) as ex:
        raise ValueError('Token单价格式无效') from ex
    if not result.is_finite() or result < 0 or not math.isfinite(compatible):
        raise ValueError('Token单价必须是非负有限数值')
    if result and compatible == 0:
        raise ValueError('Token单价小于支持的数值范围')
    return result


def _entry(row):
    if not isinstance(row, dict):
        raise ValueError('每条Token价目应为对象')
    out = {}
    for key in ('provider', 'model'):
        value = row.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 240:
            raise ValueError('Token价目必须指定准确的供应商和模型')
        out[key] = value.strip()
    currency = row.get('currency')
    if currency is not None:
        if not isinstance(currency, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,15}', currency):
            raise ValueError('费用币种应为明确的币种或计价单位代码')
        currency = currency.upper()
    out['currency'] = currency
    for key in _RATE_KEYS:
        value = _rate(row.get(key))
        # Preserve text-entered decimal precision; JSON number input stays a
        # number for normal form controls. Both forms are explicitly validated.
        out[key] = str(value) if value is not None and isinstance(row.get(key), str) else float(value) if value is not None else None
    policy = row.get('failed_request_billing', 'unknown')
    if policy not in _POLICIES:
        raise ValueError('失败请求计费策略无效')
    out['failed_request_billing'] = policy
    return out


def validate(config, profile_id=None):
    if config is None:
        return None
    if not isinstance(config, dict) or config.get('schema') != SCHEMA or config.get('unit') != UNIT:
        raise ValueError('Token价格配置格式无效')
    if type(config.get('price_revision')) is not int or config['price_revision'] < 0:
        raise ValueError('Token价格配置修订号无效')
    if not isinstance(config.get('profile_id'), str) or not config['profile_id'] or profile_id is not None and config['profile_id'] != profile_id:
        raise ValueError('Token价格配置所属主体不一致')
    rows = config.get('entries')
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError('Token价格条目无效或过多')
    seen = set()
    for row in rows:
        normalized = _entry(row)
        key = normalized['provider'], normalized['model']
        if key in seen or normalized != row:
            raise ValueError('Token价格条目重复或未规范化')
        seen.add(key)
    return config


class TokenPrices:
    def __init__(self, store):
        self.store = store

    def get(self):
        owner = self.store.meta('identity')['id']
        config = self.store.meta(KEY)
        if config is None:
            return {'schema': SCHEMA, 'profile_id': owner, 'price_revision': 0, 'unit': UNIT, 'entries': []}
        validate(config, owner)
        return copy.deepcopy(config)

    def set(self, body):
        if not isinstance(body, dict):
            raise ValueError('Token价格配置必须是对象')
        with self.store.lock, self.store.db:
            old = self.get()
            expected = body.get('expected_revision', body.get('price_revision', old['price_revision']))
            if type(expected) is not int or expected != old['price_revision']:
                raise ValueError('Token价格配置已变化，请刷新后保存')
            if body.get('profile_id', old['profile_id']) != old['profile_id']:
                raise ValueError('当前主体已变化，请重新读取价格配置')
            rows = body.get('entries', body.get('rates'))
            if not isinstance(rows, list):
                raise ValueError('Token价格配置缺少entries列表')
            entries = [_entry(row) for row in rows]
            config = {**old, 'entries': entries}
            validate(config, old['profile_id'])
            if entries == old['entries']:
                return old
            config['price_revision'] += 1
            self.store.setmeta(KEY, config)
            self.store.event('token_prices_updated', {'price_revision': config['price_revision'],
                'configured_models': len(entries)})
            return copy.deepcopy(config)


def _count(value):
    return value if type(value) is int and value >= 0 else None


def cost(record, prices):
    """Price one physical request using a disclosed user configuration revision.

    Returned money is a configured estimate based on actual counts, not a claim
    that the supplier has charged it. Reasoning is already in output_tokens.
    """
    revision = prices.get('price_revision') if isinstance(prices, dict) else None
    result = {'cost': None, 'cost_decimal': None, 'currency': None, 'price_revision': revision,
        'cost_status': 'unavailable', 'reason': None, 'breakdown': [],
        'pricing_basis': 'user_configured_rates_not_verified_invoice'}
    def unknown(reason):
        return {**result, 'reason': reason}
    if not isinstance(record, dict):
        return unknown('invalid_record')
    try:
        validate(prices)
    except ValueError:
        return unknown('invalid_price_config')
    if not prices or not prices.get('entries'):
        return unknown('prices_not_configured')
    if record.get('persona_id') is not None and record['persona_id'] != prices['profile_id']:
        return unknown('price_scope_mismatch')
    provider = record.get('provider') or record.get('protocol')
    row = next((item for item in prices['entries'] if item['provider'] == provider and item['model'] == record.get('model')), None)
    if row is None:
        return unknown('model_price_not_configured')
    result['currency'] = row['currency']
    if not row['currency']:
        return unknown('currency_not_configured')
    status = record.get('status')
    if status in ('failed', 'error', 'cancelled'):
        policy = row['failed_request_billing']
        if policy == 'unknown':
            return unknown('failed_request_billing_unknown')
        if policy == 'not_billed':
            return {**result, 'cost': 0.0, 'cost_decimal': '0', 'cost_status': 'not_billed',
                'reason': 'user_configured_failed_requests_not_billed'}
    elif status not in ('completed', 'ok'):
        return unknown('request_not_completed')
    if record.get('usage_source') not in ('provider_actual', 'provider_actual_historical_fixture'):
        return unknown('actual_usage_unavailable')
    for field in ('prompt_tokens', 'completion_tokens', 'total_tokens', 'cache_hit_tokens', 'cache_miss_tokens', 'reasoning_tokens'):
        if record.get(field) is not None and _count(record[field]) is None:
            return unknown('invalid_usage_count')
    prompt, output = _count(record.get('prompt_tokens')), _count(record.get('completion_tokens'))
    if prompt is None or output is None:
        return unknown('input_or_output_usage_unavailable')
    total = _count(record.get('total_tokens'))
    if total is not None and total != prompt + output:
        return unknown('usage_total_mismatch')
    reasoning = _count(record.get('reasoning_tokens'))
    if reasoning is not None and reasoning > output:
        return unknown('reasoning_exceeds_output')
    rates = {key: _rate(row.get(key)) for key in _RATE_KEYS}
    hit = _count(record.get('cache_hit_tokens'))
    miss = _count(record.get('cache_miss_tokens'))
    raw = record.get('provider_usage_fields') or {}
    if not isinstance(raw, dict):
        return unknown('invalid_usage_fields')
    for field in ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'):
        if raw.get(field) is not None and _count(raw[field]) is None:
            return unknown('invalid_usage_count')
    write = 0
    if (record.get('protocol') or provider) == 'anthropic':
        raw_base = _count(raw.get('input_tokens'))
        raw_read = _count(raw.get('cache_read_input_tokens'))
        write = _count(raw.get('cache_creation_input_tokens'))
        if hit is not None and raw_read is not None and hit != raw_read:
            return unknown('cache_usage_mismatch')
        if hit is None:
            hit = raw_read
        # normalized_usage derives prompt_tokens from these Anthropic fields.
        # Its computed total is not independent evidence that an omitted cache
        # field was zero: inferring it back would hide incomplete usage.
        if raw_base is None:
            return unknown('base_input_usage_unavailable')
        if write is None:
            return unknown('cache_write_usage_unavailable')
        if raw_read is None:
            return unknown('cache_read_usage_unavailable')
        if raw_base is not None and hit is not None and raw_base + hit + write != prompt:
            return unknown('cache_usage_mismatch')
    elif hit is None and miss is not None:
        hit = prompt - miss
    if prompt == 0 and hit is None:
        hit = 0
    if write < 0 or hit is not None and (hit < 0 or hit + write > prompt):
        return unknown('cache_usage_exceeds_input')
    if miss is not None and hit is not None and miss != prompt - hit:
        return unknown('cache_usage_mismatch')
    components = [('output', output, rates['output'])]
    if hit is None:
        # A uniform configured price makes the split mathematically irrelevant;
        # this does not invent a zero cache hit count.
        if rates['cache_read'] is None or rates['input'] is None or rates['cache_read'] != rates['input']:
            return unknown('cache_read_usage_unavailable')
        if write and (rates['cache_write'] is None or rates['cache_write'] != rates['input']):
            return unknown('cache_write_usage_unavailable')
        components.append(('input_unsplit', prompt, rates['input']))
    else:
        components.extend([('input', prompt - hit - write, rates['input']),
            ('cache_read', hit, rates['cache_read']), ('cache_write', write, rates['cache_write'])])
    amount = Decimal(0)
    for name, tokens, rate in components:
        if tokens == 0:
            continue
        if rate is None:
            return unknown(name + '_price_not_configured')
        part = Decimal(tokens) * rate / Decimal(1000000)
        amount += part
        result['breakdown'].append({'kind': name, 'tokens': tokens, 'price_per_million': str(rate), 'cost_decimal': str(part)})
    try:
        numeric = float(amount)
    except (OverflowError, ValueError):
        return unknown('amount_not_representable')
    if not math.isfinite(numeric) or amount and numeric == 0:
        return unknown('amount_not_representable')
    return {**result, 'cost': numeric, 'cost_decimal': str(amount), 'cost_status': 'calculated', 'reason': None}


def price_records(records, config):
    rows=[]
    for record in records:
        priced=cost(record,config)
        rows.append({**copy.deepcopy(record),**priced,'cost_reason':priced.get('reason')})
    return rows


def summarize(records):
    """Summarize already-priced rows without converting or mixing currencies.

    A known subtotal remains useful when some requests cannot be priced, but it
    is deliberately not returned as the total. Historical calculations all
    disclose their applied configuration revision; changing prices recalculates
    a view and does not rewrite the underlying usage ledger.
    """
    rows = list(records)
    groups = {}
    unknown_reasons = {}
    revisions = set()
    for row in rows:
        revision = row.get('price_revision')
        if type(revision) is int:
            revisions.add(revision)
        amount = None
        if row.get('cost_status') in ('calculated', 'not_billed') and row.get('currency'):
            try:
                amount = _rate(row.get('cost_decimal'))
            except ValueError:
                pass
        if amount is None:
            reason = row.get('reason') or 'cost_unavailable'
            unknown_reasons[reason] = unknown_reasons.get(reason, 0) + 1
            continue
        currency = row['currency']
        group = groups.setdefault(currency, {'currency': currency, 'cost_decimal': Decimal(0),
            'calls': 0, 'price_revisions': set()})
        group['cost_decimal'] += amount
        group['calls'] += 1
        if type(revision) is int:
            group['price_revisions'].add(revision)
    subtotals = []
    for currency in sorted(groups):
        group = groups[currency]
        amount = group['cost_decimal']
        numeric = float(amount)
        # _rate already checked individual amounts; a very large collection
        # could still overflow a float. Decimal subtotals remain inspectable.
        subtotals.append({**group, 'cost_decimal': str(amount),
            'cost': numeric if math.isfinite(numeric) else None,
            'price_revisions': sorted(group['price_revisions'])})
    unknown = sum(unknown_reasons.values())
    total = subtotals[0] if len(subtotals) == 1 and not unknown else None
    return {'cost': total['cost'] if total else None,
        'cost_decimal': total['cost_decimal'] if total else None,
        'currency': total['currency'] if total else None,
        'cost_status': ('no_calls' if not rows else 'partial' if unknown and subtotals else
            'unavailable' if unknown else 'mixed_currencies' if len(subtotals) > 1 else
            'calculated' if total and total['cost'] is not None else 'unavailable'),
        'known_cost_subtotals': subtotals, 'unknown_cost_calls': unknown,
        'unknown_cost_reasons': unknown_reasons, 'price_revisions': sorted(revisions),
        'pricing_basis': 'user_configured_rates_not_verified_invoice'}
