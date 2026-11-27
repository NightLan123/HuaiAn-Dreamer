/* Phase 3: shared, read-only psychology presentation and accessible details. */
(function (global) {
  'use strict';
  const escape = raw => global.escapeHtml(raw);
  function number(raw) {
    if (raw === null || raw === undefined || raw === '' || typeof raw === 'boolean') return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }
  const value = raw => number(raw) === null ? '待观察' : number(raw).toFixed(2);
  const time = raw => raw ? global.formatLocalDisplayTime(raw) : '尚无业务时间';
  function source(envelope, field) {
    if (!envelope || ['error', 'unavailable', 'loading'].includes(envelope.status)) return envelope?.status?.toUpperCase() || 'UNAVAILABLE';
    if (envelope.source === 'mock') return 'MOCK';
    const s = envelope.field_sources?.[field];
    if (s === 'unavailable' || envelope.source === 'unavailable') return 'UNAVAILABLE';
    if (String(s).startsWith('derived')) return 'DERIVED';
    return envelope.source === 'live' ? 'LIVE' : 'UNAVAILABLE';
  }
  function provenance(envelope, domain, field) {
    const badge = source(envelope, field);
    return `<div class="viz-provenance"><button type="button" data-psych-detail="provenance" data-detail-domain="${escape(domain)}" data-detail-id="${escape(field)}"><span class="viz-source viz-source-${badge.toLowerCase()}">${escape(badge)}</span><span>${badge === 'MOCK' ? '演示数据 · 非真实心理状态' : '查看来源与时间'}</span><span aria-hidden="true">↗</span></button><span>${envelope?.updated_at ? '更新于 ' + escape(time(envelope.updated_at)) : '尚无业务更新时间'}</span></div>`;
  }
  function legend(items) {
    return `<ul class="viz-legend" aria-label="图例">${items.map(it => `<li><span aria-hidden="true">${escape(it.symbol || '○')}</span>${escape(it.label)}</li>`).join('')}</ul>`;
  }
  function state(envelope) {
    if (envelope?.status === 'loading') return '<div class="viz-state" role="status">正在读取当前角色的观测…</div>';
    if (!envelope || ['error', 'unavailable'].includes(envelope.status)) return `<div class="viz-state" role="status"><strong>暂时无法读取</strong><p>${escape(envelope?.error || '当前数据源不可用；没有使用演示数据填补。')}</p></div>`;
    return '';
  }
  let root, previousFocus, selected, resolveDetail, currentContext, contentFingerprint;
  function focusable() {
    return [...root.querySelectorAll('button, summary, a[href], [tabindex="0"]')].filter(el => !el.disabled && el.getClientRects().length);
  }
  function ensureDrawer() {
    if (root) return;
    root = document.createElement('div');
    root.id = 'psychDetailsBackdrop';
    root.className = 'viz-drawer-backdrop';
    root.hidden = true;
    root.innerHTML = `<aside class="viz-drawer" role="dialog" aria-modal="true" aria-labelledby="psychDetailsTitle"><header><div><span class="viz-eyebrow">心理观察 · 数据详情</span><h2 id="psychDetailsTitle"></h2></div><button type="button" class="viz-icon-button" data-viz-close aria-label="关闭详情">×</button></header><div class="viz-drawer-scroll" id="psychDetailsBody"></div><footer><button type="button" class="viz-button" data-viz-copy>复制标识</button><span class="viz-copy-status" role="status"></span><button type="button" class="viz-button" data-viz-close>返回观察</button></footer></aside>`;
    document.body.appendChild(root);
    root.addEventListener('click', async e => {
      if (e.target === root || e.target.closest('[data-viz-close]')) close();
      if (e.target.closest('[data-viz-copy]')) {
        try {
          await navigator.clipboard.writeText(selected?.id || selected?.field || '');
          root.querySelector('.viz-copy-status').textContent = '已复制标识';
        } catch (_) { root.querySelector('.viz-copy-status').textContent = '剪贴板不可用，可在技术字段中选取标识'; }
      }
    });
    root.addEventListener('keydown', e => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
      if (e.key === 'Tab') {
        const items = focusable(), first = items[0], last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
      }
    });
  }
  function close() {
    if (!root || root.hidden) return;
    root.hidden = true;
    selected = null;
    document.body.classList.remove('viz-drawer-open');
    if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
    else {
      const replacement = previousFocus?.dataset?.psychDetail && [...document.querySelectorAll('[data-psych-detail]')].find(el => el.dataset.psychDetail === previousFocus.dataset.psychDetail && el.dataset.detailId === previousFocus.dataset.detailId);
      replacement?.focus({ preventScroll: true });
    }
  }
  function show(detail, trigger, resolver, context) {
    if (!detail) return;
    ensureDrawer();
    previousFocus = trigger || document.activeElement;
    resolveDetail = resolver;
    currentContext = context;
    selected = detail;
    contentFingerprint = '';
    root.hidden = false;
    document.body.classList.add('viz-drawer-open');
    render(detail);
    root.querySelector('[data-viz-close]').focus();
  }
  function readableRecords(records, empty) {
    if (records === undefined || records === null || (Array.isArray(records) && !records.length)) return `<p class="viz-muted">${escape(empty)}</p>`;
    const list = Array.isArray(records) ? records : [records];
    return `<ol class="viz-records">${list.map(item => `<li>${typeof item === 'object' && item !== null ? `<p>${escape(item.quote || item.text || item.summary || item.reason || '来源记录')}</p><details><summary>原始记录</summary><pre>${escape(JSON.stringify(item, null, 2))}</pre></details>` : escape(item)}</li>`).join('')}</ol>`;
  }
  function render(detail) {
    const fingerprint = JSON.stringify(detail);
    if (fingerprint === contentFingerprint) return;
    contentFingerprint = fingerprint;
    selected = detail;
    const body = root.querySelector('#psychDetailsBody');
    const scroll = body.scrollTop;
    const opened = [...body.querySelectorAll('details[open]')].map(el => el.dataset.section);
    const focusSection = document.activeElement?.closest('details')?.dataset.section;
    const env = detail.envelope || {};
    root.querySelector('#psychDetailsTitle').textContent = detail.title || '数据详情';
    body.innerHTML = `<p class="viz-description">${escape(detail.description || '只展示当前角色已返回的数据；未知与未提供的信息保持缺失。')}</p><dl class="viz-detail-fields">${(detail.fields || []).map(it => `<div><dt>${escape(it.label)}</dt><dd>${escape(it.value ?? '未提供')}</dd></div>`).join('')}</dl><section><h3>来源与时间</h3><dl class="viz-detail-fields"><div><dt>数据来源</dt><dd>${escape(source(env, detail.field))}</dd></div><div><dt>业务更新时间</dt><dd>${escape(time(Object.prototype.hasOwnProperty.call(detail, 'updated_at') ? detail.updated_at : env.updated_at))}</dd></div><div><dt>本次采集时间</dt><dd>${escape(env.fetched_at ? time(env.fetched_at) : '未采集')}</dd></div></dl><p class="viz-muted">采集时间表示界面读取时刻，不代表心理状态发生变化。</p></section><details data-section="evidence"><summary>证据与引用</summary>${readableRecords(detail.evidence, '此字段未提供可关联的证据记录。')}</details><details data-section="history"><summary>已有变更记录</summary>${readableRecords(detail.history, '尚无该字段的变更记录；未生成推测历史。')}</details><details data-section="technical"><summary>技术字段与派生规则</summary><pre>${escape(JSON.stringify({ id: detail.id, endpoint: env.endpoint, field: detail.field, field_source: env.field_sources?.[detail.field], status: env.status, derivation: detail.derivation || env.derivations?.[detail.field] || null, raw: detail.raw ?? null }, null, 2))}</pre></details>`;
    if (detail.actions?.length) {
      const actions = document.createElement('div');
      actions.className = 'viz-detail-actions';
      actions.innerHTML = detail.actions.map(action => `<button type="button" class="viz-button" data-viz-action="${escape(action.action)}" data-action-id="${escape(action.id)}">${escape(action.label)}</button>`).join('');
      body.prepend(actions);
    }
    for (const name of opened) body.querySelector(`details[data-section="${name}"]`)?.setAttribute('open', '');
    body.scrollTop = scroll;
    if (focusSection) body.querySelector(`details[data-section="${focusSection}"] summary`)?.focus({ preventScroll: true });
  }
  function refresh(envelopes, context) {
    if (!selected || !root || root.hidden) return;
    if (context !== currentContext) { close(); return; }
    const detail = resolveDetail?.(envelopes);
    if (detail) render(detail); else close();
  }
  global.PsychViz = { escape, number, value, provenance, legend, state, source, show, close, refresh };
})(window);
