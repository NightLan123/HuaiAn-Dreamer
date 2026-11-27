/* Stage 2: read-only drive observations. Only the controller can advance state. */
(function (global) {
  'use strict';
  const esc = v => global.PsychViz.escape(v ?? '');
  const arr = v => Array.isArray(v) ? v : [];
  const num = v => global.PsychViz.number(v);
  const time = v => v ? global.formatLocalDisplayTime(v) : '未提供时间';
  const metrics = [['activation', '激活度', '此刻表达动机被激活的程度', 'A'], ['urgency', '紧迫度', '表达需要被及时处理的程度', 'U'], ['persistence', '持续度', '表达动机继续保留的程度', 'P']];
  const statuses = { active: '活跃', pending: '待处理', resolved: '已结束', satisfied: '已完成', deferred: '已暂缓', partially_satisfied: '部分完成', abandoned: '已放弃', delivered_full: '完整送达', delivered_partial: '部分送达', proactive_deferred: '主动表达暂缓', deferred_wait: '等待表达', obstructed_expression: '表达受阻' };
  let key = '', ctx = {}, selected = '', filter = 'all', limit = 8, lastGood = null, latest = null;
  const evaluations = new Map(), lifecycle = new Map();
  const readable = env => env && ['success', 'empty'].includes(env.status);
  const button = (kind, id, label, cls = 'dv-link') => `<button type="button" class="${cls}" data-psych-detail="${esc(kind)}" data-detail-id="${esc(id)}">${label}</button>`;
  function prepare(envelopes, context) {
    if (context) ctx = context;
    const next = `${ctx.personaId}:${ctx.source}:${ctx.scope}:${ctx.epoch}`;
    if (next !== key) { key = next; selected = ''; filter = 'all'; limit = 8; lastGood = null; evaluations.clear(); lifecycle.clear(); }
    const incoming = envelopes.expressionDrive;
    if (readable(incoming)) lastGood = incoming;
    const env = readable(incoming) ? incoming : lastGood || incoming;
    const streams = arr(env?.data?.visual_streams);
    if (!streams.some(s => s.stream_key === selected)) selected = (streams.find(s => s.scope === ctx.scope) || streams[0])?.stream_key || '';
    const stream = streams.find(s => s.stream_key === selected);
    latest = { env: env ? { ...env, updated_at: global.formatBusinessTimestamp(stream?.updated_at) } : env, incoming, streams, stream, stale: !!lastGood && !readable(incoming) };
    return latest;
  }
  function recordEvaluation(evaluation, target, envelope) {
    if (target.context !== key) return;
    const record = { ...evaluation, ui_received_at: new Date().toISOString(), response_envelope: envelope };
    evaluations.set(target.streamKey, record);
    evaluations.set(JSON.stringify([target.scope, target.person]), record);
  }
  function getAdvanceTarget(envelopes, context) {
    const m = prepare(envelopes, context);
    if (!readable(m.incoming) || m.incoming.source !== 'live') return null;
    if (m.stream && (!m.stream.scope || !m.stream.person_id)) return null;
    return { context: key, streamKey: selected, scope: m.stream?.scope || ctx.scope,
      person: m.stream?.person_id || 'web:owner', session_id: m.stream?.session_id || null };
  }
  function gate(stream) {
    const ev = evaluations.get(stream?.stream_key || '') || evaluations.get(JSON.stringify([stream?.scope, stream?.person_id]));
    return ev ? { ev, historical: !stream || ev.state_revision !== stream.state_revision } : null;
  }
  function ring(s, metric) {
    const [field, label, hint, letter] = metric, n = num(s?.[field]);
    const valid = n !== null && n >= 0 && n <= 1;
    return button('drive-metric', field, `<svg viewBox="0 0 160 160" aria-hidden="true"><circle class="dv-ring-track" cx="80" cy="80" r="62"/>${valid ? `<circle class="dv-ring-fill dv-${field}" cx="80" cy="80" r="62" pathLength="100" stroke-dasharray="${n * 100} 100" transform="rotate(-90 80 80)"/>` : '<circle class="dv-ring-unknown" cx="80" cy="80" r="62"/>'}<text x="80" y="76" text-anchor="middle" class="dv-ring-value">${valid ? (n * 100).toFixed(1) + '%' : '待观察'}</text><text x="80" y="99" text-anchor="middle" class="dv-ring-letter">${letter}</text></svg><strong>${label}</strong><span>${hint}</span>`, 'dv-ring');
  }
  function streamOptions(streams) {
    return streams.length ? streams.map(s => `<option value="${esc(s.stream_key)}" ${s.stream_key === selected ? 'selected' : ''}>${esc(global.DisplayText.person(s.person_id))} · ${esc(global.DisplayText.scope(s.scope))}</option>`).join('') : '<option value="">暂无表达流</option>';
  }
  function motives(m) { return arr(m.stream?.motives); }
  const recordKey = h => JSON.stringify([h.event_id, h.at, h.state_revision, h.scope, h.person_id]);
  function history(m) { return arr(m.env?.data?.recent_history).filter(h => m.stream && h.scope === m.stream.scope && h.person_id === m.stream.person_id); }
  function affectCard(envelopes, mode) {
    const env = envelopes.emotion, points = readable(env) ? arr(env.data?.events_points) : [];
    return { id: `${mode}_drive_affect_history`, domain: 'emotion_trend', title: '情绪观测 · 离散历史', size: 'wide', body: `<div data-readonly-slot="drive_affect_history">${global.PsychViz.state(env)}<p class="viz-muted">角色层面的既有情绪事件。缺少范围引用的观测不与当前表达流建立因果关联。</p><div class="dv-events">${points.map(p => { const v = num(p.v), a = num(p.a), valid = v !== null && a !== null && v >= -1 && v <= 1 && a >= 0 && a <= 1; return `<article class="dv-event">${button('drive-affect', recordKey(p), esc(time(p.at)))}<svg viewBox="0 0 180 100" role="img" aria-label="${valid ? `愉悦度 ${v}，唤醒度 ${a}` : '观测缺失'}"><rect x="10" y="10" width="160" height="70" rx="8" fill="#e8eddf"/><path d="M90 10V80M10 80H170" stroke="#bac6ac" fill="none"/>${valid ? `<circle cx="${10 + (v + 1) * 80}" cy="${80 - a * 70}" r="5" fill="#6c8d60"/>` : '<text x="90" y="48" text-anchor="middle" fill="#7e8a71" font-size="12">待观察</text>'}<text x="10" y="96" fill="#7e8a71" font-size="9">低愉悦 ← V → 高愉悦 · A ↑</text></svg><small>${esc(global.DisplayText.scope(p.scope))} · ${esc(p.t)}</small></article>`; }).join('') || '<p class="dv-empty">暂无已返回的情绪事件。</p>'}</div>${global.PsychViz.provenance(env, 'emotion', 'events_points')}</div>` };
  }
  function contributionCard(s, mode) {
    const saved = s?.recorded_contributions || {}, terms = saved.channel_contributions || {};
    const names = { personality_b_theta: '人格基线', fast_emotion: '快情绪', slow_mood: '慢心境', cognitive_appraisal: '事件评价', relationship: '关系', dialogue_context: '对话环境', residual_motive: '未完成动机' };
    return { id: `${mode}_drive_contributions`, domain: 'expression_drive', title: '表达欲 · 条件如何参与计算', size: 'wide', body: `<div data-readonly-slot="drive_contributions"><p>所选会话最近一次已保存的事件贡献；三列是进入计算的数值，不是百分比，也不代表已验证的心理因果。</p>${Object.keys(terms).length ? `<table class="wb-token-table"><thead><tr><th>条件来源</th><th>激活</th><th>紧迫</th><th>持续</th></tr></thead><tbody>${Object.entries(terms).map(([k,v]) => `<tr><th>${esc(names[k] || k)}</th>${[0,1,2].map(i => `<td>${num(v?.[i]) === null ? '未记录' : Number(v[i]).toFixed(3)}</td>`).join('')}</tr>`).join('')}</tbody></table><details><summary>查看该次计算的来源与影响</summary><pre>${esc(JSON.stringify(saved, null, 2))}</pre></details>` : '<p>此会话尚无保存的贡献快照；不会按当前参数补算旧记录。</p>'}</div>` };
  }
  function cards(envelopes, mode, context) {
    const m = prepare(envelopes, context), s = m.stream, g = gate(s);
    const notice = m.stale ? '<p class="dv-notice" role="status">本次读取失败，以下保留上次读取结果。推进暂不可用。</p>' : global.PsychViz.state(m.incoming);
    const all = motives(m), visible = all.filter(x => filter === 'all' || (filter === 'unfinished' ? ['pending', 'deferred', 'partially_satisfied'].includes(x.status) : !!x.delivery_outcome));
    const tendency = arr(s?.observed_tendencies);
    const events = history(m);
    return [
      contributionCard(s, mode),
      { id: `${mode}_drive_observation`, domain: 'expression_drive', title: '表达欲 · 此刻想说的话', size: 'wide', body: `<div class="dv-toolbar"><label>观察会话流 <select id="selectDriveStream">${streamOptions(m.streams)}</select></label><span>各指标独立呈现，不合成为单一分数</span></div><div data-readonly-slot="drive_observation">${notice}<div class="dv-observation"><div class="dv-rings">${metrics.map(mt => ring(s, mt)).join('')}</div><aside class="dv-intent"><span class="viz-eyebrow">当前表达意图</span><h4>${esc(global.DisplayText.label(s?.expressive_intent || '尚未形成观测'))}</h4><p>${esc(global.DisplayText.person(s?.person_id))} · ${esc(global.DisplayText.scope(s?.scope || ctx.scope))}</p><p>状态更新：${esc(time(s?.updated_at))}</p>${button('drive-stream', selected, '查看会话与状态来源 ↗')}<div class="dv-gate"><strong>${g ? (g.historical ? '最近一次推进记录' : '本版本推进结果') : '尚无主动表达门控观测'}</strong><p>${g ? (g.ev.proactive_eligible === true ? '允许发起表达；送达需另看回执。' : g.ev.proactive_eligible === false ? '本次暂不发起表达。' : '门控结果未提供。') : '现有状态接口未返回资格判断，可推进一次查看后端结果。'}</p>${g ? button('drive-gate', selected, '查看判断依据 ↗') : ''}</div></aside></div>${global.PsychViz.provenance(m.env, 'expressionDrive', 'visual_streams')}</div><div class="dv-advance"><div><strong>推进现有表达状态</strong><p>按所选会话更新状态并取得门控结果，此操作本身不发送消息。</p></div><button type="button" class="viz-button" id="btnTriggerDriveAdvance">推进一次</button></div><p id="driveAdvanceFeedback" role="status" aria-live="polite"></p>` },
      { id: `${mode}_drive_motives`, domain: 'expression_drive', title: '动机如何走向表达', size: 'wide', body: `<div class="dv-toolbar"><label>显示 <select id="selectDriveMotives"><option value="all" ${filter === 'all' ? 'selected' : ''}>所有已返回动机</option><option value="unfinished" ${filter === 'unfinished' ? 'selected' : ''}>未结束</option><option value="receipt" ${filter === 'receipt' ? 'selected' : ''}>有处理回执</option></select></label><span>动机 → 表达目标 → 发起条件 → 处理结果</span></div><div data-readonly-slot="drive_motives_visual"><div class="dv-motive-list">${visible.slice(0, limit).map(x => `<article class="dv-motive"><div><span class="dv-step">01 · 内部动机</span>${button('drive-motive', x.motive_id, esc(x.content_anchor?.topic || x.topic || '未命名动机'))}<small>${esc(statuses[x.status] || global.DisplayText.state(x.status || '状态未提供'))}</small></div><div><span class="dv-step">02 · 表达目标</span><p>${esc(x.intended_expression?.intended_goal || x.intended_goal || '未提供')}</p><small>${esc(global.DisplayText.person(s?.person_id))}</small></div><div><span class="dv-step">03 · 发起条件</span><p>${g?.ev.active_motive?.motive_id === x.motive_id ? (g.ev.proactive_eligible === true ? (g.historical ? '历史判断可发起' : '本次判断可发起') : g.ev.proactive_eligible === false ? (g.historical ? '历史判断暂缓' : '本次判断暂缓') : '结果未提供') : '尚无关联门控结果'}</p><small>${g?.ev.active_motive?.motive_id === x.motive_id ? esc(global.DisplayText.state(g.ev.ineligible_reason || '详见推进记录')) : '不由指标推算资格'}</small></div><div><span class="dv-step">04 · 处理结果</span><p>${esc(statuses[x.delivery_outcome] || global.DisplayText.state(x.delivery_outcome || '尚无送达回执'))}</p><small>${esc(x.defer_reason ? global.DisplayText.state(x.defer_reason) : '')}</small></div></article>`).join('') || '<p class="dv-empty">当前筛选下没有已返回的动机。</p>'}</div><p class="viz-muted">已显示 ${Math.min(limit, visible.length)} / ${visible.length} 条；详细动机补充数据：${esc(global.DisplayText.state(m.env?.data?.detail_status || 'unavailable'))}。</p>${visible.length > limit ? '<button type="button" class="viz-button" data-drive-more>继续展开动机</button>' : ''}</div><details class="dv-planned"><summary>人工研究动机</summary><p>可在开发工具中创建、修订和放弃独立的研究动机；不会自动联系或参与真实人格成长。</p><button type="button" class="viz-button" data-dev-nav="api_tools">打开研究工作区</button></details>` },
      { id: `${mode}_drive_events`, domain: 'expression_drive', title: '表达状态 · 事件记录', size: 'wide', body: `<div data-readonly-slot="drive_events_visual"><p class="viz-muted">仅展示所选会话实际返回的离散事件；点之间不插值，不代表连续采样。</p><div class="dv-events">${events.map((h, i) => `<article class="dv-event">${button('drive-event', recordKey(h), esc(time(h.at)))}<div class="dv-event-bars">${metrics.map(([field, label, , letter]) => { const n = num(h[field]); const valid = n !== null && n >= 0 && n <= 1; return `<div><span>${letter}</span><span class="dv-event-track">${valid ? `<i class="dv-${field}" style="width:${n * 100}%"></i>` : ''}</span><span>${valid ? n.toFixed(2) : '未知'}</span><span class="dv-sr">${label}</span></div>`; }).join('')}</div><small>${esc(global.DisplayText.state(h.expressive_intent || '意图未提供'))}</small></article>`).join('') || '<p class="dv-empty">暂无此会话的事件记录。</p>'}</div><p class="viz-muted">后台时间采样需主动开启；已保存采样可在开发工具的研究工作区查看和导出。</p></div>` },
      { id: `${mode}_drive_tendencies`, domain: 'expression_drive', title: '表达倾向 · 已知与待观察', size: 'wide', body: `<div data-readonly-slot="drive_tendencies"><div class="dv-tendencies">${tendency.length ? tendency.map((t, i) => button('drive-tendency', String(i), `<strong>${esc(t.label || t.name || t.id || '倾向')}</strong><span>${esc(t.value ?? t.score ?? '未提供')}</span>`, 'dv-tendency')).join('') : '<div class="dv-empty"><strong>待观察</strong><p>当前接口未返回独立的表达倾向观测，暂不展示百分比。</p></div>'}</div>${global.PsychViz.provenance(m.env, 'expressionDrive', 'observed_tendencies')}</div>` }
    ];
  }
  function detail(kind, id, envelopes) {
    if (!kind.startsWith('drive-')) return null;
    if (kind === 'drive-affect') {
      const env = envelopes.emotion;
      const p = readable(env) && arr(env.data?.events_points).find(x => recordKey(x) === id);
      return p ? { title: '离散情绪观测', id: p.event_id || id, envelope: env, field: 'events_points', updated_at: p.at ?? null,
        fields: [{ label: '愉悦度', value: p.v }, { label: '唤醒度', value: p.a }, { label: '范围', value: p.scope }], evidence: p.event_id ? [p.event_id] : [], raw: p.raw || p,
        description: '真实情绪轨迹点。未用连续曲线插值，未将时间接近的表达事件当作原因。' } : null;
    }
    const m = prepare(envelopes), s = m.stream;
    const common = { id, envelope: m.env, field: 'visual_streams', updated_at: s?.updated_at ?? null,
      description: m.stale ? 'STALE：本次读取失败，展示上次读取的记录。' : '来自所选会话的后端观测。表达资格与实际送达分别记录。' };
    if (kind === 'drive-metric') { const mt = metrics.find(x => x[0] === id); return mt ? { ...common, title: mt[1], fields: [{ label: '含义', value: mt[2] }, { label: '原始值', value: s?.[id] }, { label: '会话流', value: selected }], raw: s, history: history(m) } : null; }
    if (kind === 'drive-stream') return { ...common, title: '表达会话', fields: [{ label: '对象', value: s?.person_id }, { label: '范围', value: s?.scope }, { label: '版本', value: s?.state_revision }], raw: s };
    if (kind === 'drive-motive') { const x = motives(m).find(v => String(v.motive_id) === String(id)); return x ? { ...common, title: x.content_anchor?.topic || x.topic || '表达动机', fields: [{ label: '目标', value: x.intended_expression?.intended_goal || x.intended_goal }, { label: '待说的话', value: x.intended_expression?.candidate_point_or_question || x.candidate_point_or_question }, { label: '状态', value: statuses[x.status] || x.status }, { label: '送达结果', value: statuses[x.delivery_outcome] || x.delivery_outcome }, { label: '暂缓原因', value: x.defer_reason }], updated_at: x.updated_at ?? null, raw: x, evidence: x.source_evidence || x.source_event_ids, history: lifecycle.get(x.motive_id)?.items || history(m).filter(h => h.motive_id === x.motive_id || arr(h.motive_ids).includes(x.motive_id)), description: lifecycle.get(x.motive_id)?.error || '仅展示实际记录的变化；升级前缺失的历史不会补造。', actions: [{ action: 'drive-history-refresh', id: x.motive_id, label: '读取生命周期' }, ...(lifecycle.get(x.motive_id)?.next_cursor ? [{ action: 'drive-history-more', id: x.motive_id, label: '更早记录' }] : [])] } : null; }
    if (kind === 'drive-gate') { const g = gate(s); return g ? { ...common, title: '实际推进结果', envelope: g.ev.response_envelope, field: 'proactive_eligible', updated_at: g.ev.at ?? g.ev.updated_at ?? null, fields: [{ label: '记录性质', value: g.historical ? '历史版本结果' : '当前版本结果' }, { label: '允许发起', value: g.ev.proactive_eligible === true ? '是' : g.ev.proactive_eligible === false ? '否' : '未提供' }, { label: '原因', value: g.ev.ineligible_reason }, { label: '实际送达', value: '推进操作不负责发送消息' }], raw: g.ev } : null; }
    if (kind === 'drive-event') { const x = history(m).find(h => recordKey(h) === id); return x ? { ...common, id: x.event_id || id, title: '离散表达事件', updated_at: x.at ?? null, raw: x, fields: metrics.map(([f, label]) => ({ label, value: x[f] })), evidence: x.event_id ? [x.event_id] : [] } : null; }
    if (kind === 'drive-tendency') return { ...common, title: '后端表达倾向', field: 'observed_tendencies', raw: arr(s?.observed_tendencies)[Number(id)] };
    return null;
  }
  async function loadHistory(id, more, adapter, isCurrent) {
    const m = latest, captured = key, previous = more ? lifecycle.get(id) : null;
    if (!m?.stream || m.env?.source !== 'live') return;
    const response = await adapter.fetchMotiveHistory({ scope: m.stream.scope, person: m.stream.person_id,
      motive_id: id, cursor: previous?.next_cursor });
    if (captured !== key || !isCurrent()) return;
    if (response.status !== 'success') { lifecycle.set(id, { ...previous, error: '生命周期读取失败，请重试。' }); return; }
    const data = response.data;
    lifecycle.set(id, { ...data, items: [...(previous?.items || []), ...(data.items || []).map(r => ({ ...r,
      text: `${time(r.at)} · ${statuses[r.from_status] || '首次记录'} → ${statuses[r.to_status] || '未知状态'}${r.reason ? ' · ' + global.DisplayText.state(r.reason) : ''}` }))] });
  }
  function handleChange(el) {
    if (el.id === 'selectDriveStream') { selected = el.value; limit = 8; global.PsychViz.close(); return true; }
    if (el.id === 'selectDriveMotives') { filter = el.value; limit = 8; return true; }
    return false;
  }
  function handleClick(el) { if (!el.closest('[data-drive-more]')) return false; limit += 8; return true; }
  function syncControls(root) {
    const select = root.querySelector('#selectDriveStream');
    if (select && latest) { const html = streamOptions(latest.streams); if (select.innerHTML !== html) select.innerHTML = html; select.value = selected; }
  }
  global.DriveView = { loadHistory, cards: (envelopes, mode, context) => [...cards(envelopes, mode, context), affectCard(envelopes, mode)], detail, handleChange, handleClick, syncControls, getAdvanceTarget, recordEvaluation };
})(window);
