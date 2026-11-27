/* Shared presentation only. No requests, writes or model inference. */
(function (global) {
  'use strict';
  const esc = v => global.PsychViz.escape(v ?? '');
  const arr = v => Array.isArray(v) ? v : [];
  const num = v => global.PsychViz.number(v);
  const good = e => e && ['success', 'empty', 'degraded'].includes(e.status);
  const time = v => v ? global.formatLocalDisplayTime(v) : '时间未提供';
  const text = v => v == null ? '未提供' : typeof v === 'object' ? '查看详情' : global.DisplayText.label(v);
  function redact(v) {
    if (Array.isArray(v)) return v.map(redact);
    if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, value]) => [k, /^(api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|secret|cookie)$/i.test(k) ? '[已隐藏]' : redact(value)]));
    return v;
  }
  const badge = (status, label) => `<span class="wb-badge wb-${/^[a-z_]+$/.test(status || '') ? status : 'unknown'}">${esc(label || ({ healthy: '已验证', reachable: '可达', running: '运行中', configured: '已配置', unavailable: '不可用', unknown: '未知', completed: '已完成', paused: '已暂停', failed: '失败', empty: '暂无记录' }[status] || global.DisplayText.state(status)))}</span>`;
  const detail = (kind, id, label, extra = '') => `<button type="button" class="wb-link" data-psych-detail="${esc(kind)}" data-detail-id="${esc(id)}" ${extra}>${esc(label)}</button>`;
  const empty = (label = '暂无已返回记录') => `<div class="wb-empty">${esc(label)}</div>`;
  const source = (env, domain, field) => global.PsychViz.provenance(env, domain, field);
  const fields = pairs => `<dl class="wb-fields">${pairs.map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${esc(/状态|校准|门禁|连接记录|执行模式|采纳动作|仲裁规则|作用目标/.test(label) ? global.DisplayText.state(value) : text(value))}</dd></div>`).join('')}</dl>`;
  const meter = (value, max = 1) => { const n = num(value), valid = n !== null && n >= 0 && max > 0 && n <= max; return `<span class="wb-meter ${valid ? '' : 'unknown'}">${valid ? `<i style="width:${n / max * 100}%"></i>` : ''}</span><span class="wb-meter-value">${valid ? esc(n.toFixed(max === 1 ? 3 : 0)) : '未知'}</span>`; };
  const cards = (id, domain, title, body, wide = true) => ({ id, domain, title, size: wide ? 'wide' : 'standard', body });
  const state = env => good(env) && env.status === 'degraded' ? '<p class="wb-notice">部分接口不可用；各节点保留自己的来源状态。</p>' : global.PsychViz.state(env);
  global.DevViz = { esc, arr, num, good, time, text, redact, badge, detail, empty, source, fields, meter, cards, state };
})(window);
