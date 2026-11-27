/* Owner-scoped physical model requests, loaded on demand, never homepage polling. */
(function (global) {
  'use strict';
  const esc = v => global.PsychViz.escape(v ?? ''), num = v => global.PsychViz.number(v);
  const count = v => num(v) === null ? '未知' : String(v);
  const label = v => global.DisplayText.state(v || '未提供');
  let context = '', state = {}, sequence = 0;
  function prepare(ctx) {
    const next = `${ctx.personaId}:${ctx.source}:${ctx.epoch}`;
    if (context !== next) { context = next; state = {}; sequence++; }
  }
  const button = (act, text, id = '') => `<button type="button" class="viz-button" data-token-action="${act}" data-token-id="${esc(id)}" ${state.loading ? 'disabled' : ''}>${text}</button>`;
  function callsBody() {
    const data = state.data;
    if (!data) return '<p>点击“读取调用记录”查看模型实际用量。此处不统计浏览器页面请求。</p>';
    const rows = data.calls || [], summary = data.summary || {};
    const groups = new Map();
    for (const r of rows) {
      const key = `${r.component_role || '未分类'} · ${r.task_name || r.phase_id || '阶段未标注'}`;
      const g = groups.get(key) || { calls: 0, tokens: 0, unknown: 0, ms: 0 };
      g.calls++; if (num(r.total_tokens) === null) g.unknown++; else g.tokens += r.total_tokens;
      g.ms += num(r.duration_ms) || 0; groups.set(key, g);
    }
    const cost = (summary.known_cost_subtotals || []).map(s => `${s.currency} ${s.cost_decimal}`).join(' / ') || '未知';
    return `<p>第 ${rows.length ? data.offset + 1 : 0}–${data.offset + rows.length} 条 / ${data.total} 条 · 本页已知费用 ${esc(cost)} · ${count(summary.unknown_cost_calls)} 次费用未知</p>
      <p class="viz-muted">费用按已配置价目折算，不是账单。下方汇总仅包含本页；各请求耗时之和不是整轮等待时间。推理 Token 已包含于输出时不重复相加。</p>
      <div class="wb-dual-track">${[...groups].map(([k, g]) => `<article><strong>${esc(k)}</strong><p>${g.calls} 次 · ${g.tokens} 已知 Token${g.unknown ? `，${g.unknown} 次用量未知` : ''} · 请求耗时合计 ${g.ms.toFixed(0)} ms</p></article>`).join('')}</div>
      <div style="overflow:auto"><table class="wb-token-table"><thead><tr><th>阶段 / 模型</th><th>输入 / 输出 / 总计</th><th>缓存 / 推理</th><th>耗时</th><th>结果与来源</th></tr></thead><tbody>${rows.map(r => `<tr><td>${esc(r.component_role)} · ${esc(r.task_name || r.phase_id)}<br>${esc(r.model)}</td><td>${count(r.prompt_tokens)} / ${count(r.completion_tokens)} / ${count(r.total_tokens)}</td><td>${count(r.cache_hit_tokens)} / ${count(r.reasoning_tokens)}</td><td>${count(r.duration_ms)} ms</td><td>${esc(label(r.status))} · ${r.usage_source === 'provider_actual' ? '供应商用量' : '用量未知'}${r.retry_reason ? '<br>修复：' + esc(r.retry_reason) : ''}<br>${r.turn_id ? button('run', '查看该轮', r.turn_id) : '后台任务 / 未关联对话'}<details><summary>调用依据</summary><pre>${esc(JSON.stringify(r, null, 2))}</pre></details></td></tr>`).join('')}</tbody></table></div>
      ${data.offset > 0 ? button('previous', '上一页') : ''} ${data.has_more ? button('next', '下一页') : ''} ${button('export', '导出本页记录')}`;
  }
  function cards(ctx) {
    prepare(ctx);
    return [{ id: 'developer_model_token_ledger', domain: 'decisions', title: '模型调用 · 用量与耗时', size: 'wide', body:
      `<div class="wb-toolbar"><label>起始日期<input id="tokenDateFrom" type="date" value="${esc(state.from)}"/></label><label>结束日期<input id="tokenDateTo" type="date" value="${esc(state.to)}"/></label><label>具体回合（可留空）<input id="tokenTurn" value="${esc(state.turn)}" placeholder="全部对话与后台任务"/></label>${button('load', '读取调用记录')}<a href="/legacy" target="_blank" rel="noopener">管理计价与完整历史 ↗</a></div>
       <div data-readonly-slot="model_token_ledger"><p role="status">${esc(state.error || (state.loading ? '正在读取…' : ''))}</p>${callsBody()}${state.run ? global.ReasoningView.renderRun(state.run) : ''}</div>` }];
  }
  async function handleClick(target, services) {
    const el = target.closest('[data-token-action]'); if (!el) return false;
    prepare(services.context);
    if (services.context.source !== 'live' || state.loading) return true;
    const act = el.dataset.tokenAction;
    if (act === 'export') {
      const blob = new Blob([JSON.stringify(state.data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = 'HuaiAn_Model_Calls_Page.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); return true;
    }
    if (act === 'load') {
      state.from = document.getElementById('tokenDateFrom')?.value || ''; state.to = document.getElementById('tokenDateTo')?.value || '';
      state.turn = document.getElementById('tokenTurn')?.value.trim() || ''; state.offset = 0;
    }
    if (act === 'next') state.offset = (state.data?.offset || 0) + 50;
    if (act === 'previous') state.offset = Math.max(0, (state.data?.offset || 0) - 50);
    const captured = context, request = ++sequence; state.loading = true; state.error = ''; services.render();
    try {
      const env = act === 'run' ? await services.adapter.fetchRunDetail(el.dataset.tokenId) : await services.adapter.fetchTokenPage({ offset: state.offset || 0, turn_id: state.turn, date_from: state.from, date_to: state.to });
      if (!services.isCurrent() || captured !== context || request !== sequence) return true;
      if (env.status !== 'success') throw new Error(env.error || '读取失败');
      if (act === 'run') state.run = env.data.run; else { state.data = env.data; state.run = null; }
    } catch (error) { if (services.isCurrent() && captured === context) state.error = String(error.message || error); }
    finally { if (captured === context && request === sequence) { state.loading = false; if (services.isCurrent()) services.render(); } }
    return true;
  }
  global.TokenView = { cards, handleClick };
})(window);
