/* Phase 3.0 · Read-only psychological weather, using the existing DataEnvelopes. */
(function (global) {
  'use strict';
  let contextKey = '';
  let state = { fast: true, slow: true, filter: 'active' };
  const esc = value => global.PsychViz.escape(value);
  const num = value => global.PsychViz.number(value);
  const fmt = value => num(value) === null ? '待观察' : num(value).toFixed(2);
  const safeArray = value => Array.isArray(value) ? value : [];
  const time = value => value ? global.formatLocalDisplayTime(value) : '未提供';
  const own = (object, key) => Object.prototype.hasOwnProperty.call(object || {}, key);
  const source = (envelope, field) => global.PsychViz.provenance(envelope, 'emotion', field);
  const detailButton = (kind, id, label, className = 'ev-text-button') => `<button type="button" class="${className}" data-psych-detail="${esc(kind)}" data-detail-id="${esc(id)}">${label}</button>`;

  function reset() { contextKey = ''; state = { fast: true, slow: true, filter: 'active' }; }
  function syncContext(envelopes) {
    const key = `${envelopes.characterProfile?.data?.id || ''}:${envelopes.mode || envelopes.emotion?.source || ''}`;
    if (key !== contextKey) { reset(); contextKey = key; }
  }
  function canRead(envelope) { return !!envelope && !['error', 'unavailable', 'loading'].includes(envelope.status); }
  function point(data, kind) {
    const fast = kind === 'fast';
    const raw = data[fast ? 'fast_emotion' : 'slow_mood'];
    const v = num(raw ? raw.valence : data[fast ? 'valence' : 'mood_valence']);
    const a = num(raw ? raw.arousal : data[fast ? 'arousal' : 'mood_arousal']);
    const known = (raw ? raw.known : data[fast ? 'known' : 'mood_known']) === true;
    return { kind, raw: raw || {}, v, a, known: known && v !== null && a !== null && v >= -1 && v <= 1 && a >= 0 && a <= 1 };
  }
  function categories(data) {
    return safeArray(data.categorical_list).map(item => {
      const value = num(item.activation);
      return { ...item, activation: item.known === false || value === null || value < 0 || value > 1 ? null : value };
    });
  }
  function fallback(envelope, message) {
    if (envelope?.status === 'error') return `<div class="ev-notice ev-error" role="status"><strong>暂时无法读取心理状态</strong><p>${esc(envelope.error || '本次读取失败，请稍后刷新。')}</p></div>`;
    if (envelope?.status === 'loading') return '<div class="ev-notice" role="status">正在读取心理观测…</div>';
    return `<div class="ev-notice" role="status"><strong>${esc(message)}</strong><p>取得观测后将在这里呈现。缺失值不会被画成中性状态。</p></div>`;
  }

  function affectPlane(data, envelope) {
    const fast = point(data, 'fast'), slow = point(data, 'slow');
    const readable = canRead(envelope);
    const visible = [fast, slow].filter(p => readable && p.known && state[p.kind]);
    const x = v => 60 + (v + 1) * 230;
    const y = a => 300 - a * 250;
    const palette = global.deriveAffectColorPalette(fast.v, fast.a, readable && fast.known);
    const ticks = [0, 0.25, 0.5, 0.75, 1].map(a => `<line x1="60" x2="520" y1="${y(a)}" y2="${y(a)}" class="ev-grid-line"/><text x="44" y="${y(a) + 4}" text-anchor="end" class="ev-tick">${a.toFixed(2)}</text>`).join('');
    const verticals = [-1, -0.5, 0, 0.5, 1].map(v => `<line x1="${x(v)}" x2="${x(v)}" y1="50" y2="300" class="ev-grid-line"/><text x="${x(v)}" y="320" text-anchor="middle" class="ev-tick">${v > 0 ? '+' : ''}${v.toFixed(1)}</text>`).join('');
    const marks = visible.map(p => {
      const px = x(p.v), py = y(p.a);
      const color = global.deriveAffectColorPalette(p.v, p.a, true).primary;
      const shape = p.kind === 'fast'
        ? `<circle cx="${px}" cy="${py}" r="22" fill="${color}" opacity=".16"/><circle cx="${px}" cy="${py}" r="8" fill="${color}" stroke="#fffdf4" stroke-width="3"/>`
        : `<path d="M${px} ${py - 12}L${px + 12} ${py}L${px} ${py + 12}L${px - 12} ${py}Z" fill="none" stroke="#5e7455" stroke-width="2.5"/>`;
      return `<g role="button" tabindex="0" class="ev-plot-point" data-psych-detail="affect" data-detail-id="${p.kind}" aria-label="${p.kind === 'fast' ? '快情绪' : '慢心境'}，愉悦度 ${fmt(p.v)}，唤醒度 ${fmt(p.a)}，查看来源"><title>${p.kind === 'fast' ? '快情绪' : '慢心境'} · V ${fmt(p.v)} / A ${fmt(p.a)}</title>${shape}</g>`;
    }).join('');
    return `<div class="ev-plane-layout">
      <div class="ev-plane-wrap">
        <div class="ev-plot-heading"><span class="ev-kicker">情绪空间</span>${detailButton('affect', 'legend', '如何阅读这张图 ↗')}</div>
        <svg class="ev-affect-plane" viewBox="0 0 580 350" role="group" aria-label="愉悦度与唤醒度二维空间，实心圆为快情绪，菱形为慢心境">
          <defs><linearGradient id="ev-plane-wash" x1="0" x2="1"><stop offset="0" stop-color="#dce5e8"/><stop offset="1" stop-color="#e8ebd3"/></linearGradient></defs>
          <rect x="60" y="50" width="460" height="250" rx="22" fill="url(#ev-plane-wash)" opacity=".55"/>
          ${ticks}${verticals}<line x1="290" x2="290" y1="50" y2="300" class="ev-axis-line"/>
          <text x="62" y="30" class="ev-axis-label">唤醒度 A · 激活程度 ↑</text>
          <text x="90" y="76" class="ev-quadrant-label">负向 · 高唤醒</text><text x="402" y="76" class="ev-quadrant-label">正向 · 高唤醒</text>
          <text x="90" y="282" class="ev-quadrant-label">负向 · 低唤醒</text><text x="402" y="282" class="ev-quadrant-label">正向 · 低唤醒</text>
          <text x="290" y="344" text-anchor="middle" class="ev-axis-label">← 负向　　愉悦度 V　　正向 →</text>
          ${marks}
          ${readable && !fast.known && !slow.known ? '<g class="ev-dormant-note"><rect x="173" y="141" width="234" height="68" rx="20"/><text x="290" y="170" text-anchor="middle">尚未产生情绪观测</text><text x="290" y="192" text-anchor="middle" class="ev-tick">坐标等待观测，不绘制默认点</text></g>' : ''}
        </svg>
        <div class="ev-point-legend"><span><i class="ev-fast-symbol" style="background:${palette.primary}"></i>快情绪 · 此刻的状态</span><span><i class="ev-slow-symbol"></i>慢心境 · 较慢变化的基线</span></div>
        ${!readable ? fallback(envelope, '当前数据不可用') : !state.fast && !state.slow ? '<p class="ev-caption">两层已隐藏，可使用上方开关重新显示。</p>' : ''}
      </div>
      <aside class="ev-side-summary">
        <p class="ev-kicker">此刻与基线</p>
        <div class="ev-sample-summary">${sampleSummary(fast, readable)}${sampleSummary(slow, readable)}</div>
        <div class="ev-dimension-links">${detailButton('affect', 'valence', '愉悦度的含义')}${detailButton('affect', 'arousal', '唤醒度的含义')}</div>
        <div class="ev-auxiliary">${[['dominance', '掌控感'], ['stress', '压力'], ['engagement', '投入度']].map(([key, label]) => auxiliary(data, key, label, readable)).join('')}</div>
        <p class="ev-caption">辅助指标独立呈现；不作为情绪平面的坐标轴。</p>
      </aside>
    </div>${source(envelope, 'fast_emotion')}${source(envelope, 'slow_mood')}`;
  }
  function sampleSummary(p, readable) {
    return detailButton('affect', p.kind, `<span>${p.kind === 'fast' ? '● 快情绪' : '◇ 慢心境'}</span><strong>${readable && p.known ? `V ${fmt(p.v)} <small> / </small> A ${fmt(p.a)}` : '尚未产生观测'}</strong>`, 'ev-sample-card');
  }
  function auxiliary(data, key, label, readable) {
    const raw = data.fast_emotion || data;
    const value = raw.known === false ? null : num(raw[key]);
    const known = readable && value !== null && value >= 0 && value <= 1;
    return `<div class="ev-aux-row">${detailButton('affect', key, `<span>${label}</span><strong>${known ? fmt(value) : '待观察'}</strong>`, 'ev-aux-label')}<div class="ev-meter ${known ? '' : 'ev-meter-unknown'}">${known ? `<i style="width:${value * 100}%"></i>` : ''}</div></div>`;
  }
  function emotionBubbles(data, envelope) {
    if (!canRead(envelope)) return fallback(envelope, '情绪目录暂不可用') + source(envelope, 'categorical_list');
    const all = categories(data), active = all.filter(c => c.activation > 0), zeros = all.filter(c => c.activation === 0), unknown = all.filter(c => c.activation === null);
    const selected = (state.filter === 'active' ? active : state.filter === 'zero' ? zeros : state.filter === 'unknown' ? unknown : all).slice().sort((a, b) => (b.activation ?? -1) - (a.activation ?? -1));
    const palette = global.deriveAffectColorPalette(data.valence, data.arousal, point(data, 'fast').known);
    const count = `<div class="ev-catalog-summary"><span><b>${active.length}</b> 已激活</span><span><b>${zeros.length}</b> 未激活</span><span><b>${unknown.length}</b> 待观察</span><small>本次目录 ${all.length} 项</small></div>`;
    const bubbles = selected.map(c => {
      const known = c.activation !== null && c.activation >= 0 && c.activation <= 1;
      const size = known ? 36 + 64 * Math.sqrt(c.activation) : 44;
      return `<button type="button" class="ev-emotion-item ${!known ? 'ev-bubble-unknown' : c.activation === 0 ? 'ev-bubble-zero' : ''}" data-psych-detail="emotion" data-detail-id="${esc(c.id)}" aria-label="${esc(c.name || c.id)}，${known ? `激活强度 ${fmt(c.activation)}` : '待观察'}，查看详情"><span class="ev-bubble-field"><span class="ev-bubble" style="--ev-bubble-size:${size}px;--ev-bubble-color:${palette.primary}">${known ? fmt(c.activation) : '—'}</span></span><span class="ev-emotion-name">${esc(c.name || c.id)}</span></button>`;
    }).join('');
    return `${count}${selected.length ? `<div class="ev-bubble-grid">${bubbles}</div>` : `<div class="ev-empty-garden"><span aria-hidden="true">◌</span><strong>${all.length === 0 ? '尚无情绪目录数据' : state.filter === 'active' ? '本次没有已激活的情绪项' : '当前筛选中没有条目'}</strong><p>${all.length ? '零值与缺失值分别保留，可在筛选器中查看。' : '待后端提供情绪目录后再显示花谱。'}</p></div>`}
      <p class="ev-caption">实心气泡表示激活，空心表示真实零值，虚线表示待观察。大小随强度增加，精确值见气泡及详情。</p>${source(envelope, 'categorical_list')}`;
  }
  function cognitionEnvelope(envelopes) {
    const char = envelopes.characterProfile;
    return char?.data?.cognition_envelope || { source: char?.source || 'unavailable', status: char?.data?.cognition ? 'success' : 'unavailable', data: char?.data?.cognition || {}, endpoint: '/api/cognition', updated_at: null, fetched_at: char?.fetched_at || null, field_sources: {} };
  }
  function cognitionCard(envelopes) {
    const envelope = cognitionEnvelope(envelopes), data = envelope.data || envelopes.characterProfile?.data?.cognition || {};
    if (!canRead(envelope)) return fallback(envelope, '认知状态暂不可用') + global.PsychViz.provenance(envelope, 'cognition', 'recent');
    const recent = safeArray(data.recent), latest = recent[0], decision = latest?.decision || {};
    const labels = { REPLY: '准备回应', WAIT: '等待后续输入', NO_ACTION: '暂不行动', VALIDATION_FAILED: '本次评估失败', PERMISSION_WITHDRAWN: '权限已撤回' };
    const modes = { adaptive: '自适应模式', baseline: '基线模式' };
    const latestLabel = latest ? labels[decision.action] || decision.action || (latest.status === 'estimated' ? '最近一次评估' : latest.status === 'failed' ? '本次评估失败' : '已有评估记录') : '尚无评估记录';
    return `<div class="ev-cognition-summary"><span class="ev-cognition-icon" aria-hidden="true">◎</span><div><p class="ev-kicker">${esc(modes[data.mode] || data.mode || '模式尚未提供')}</p><h4>${esc(latestLabel)}</h4><p>${latest ? `最近记录：${esc(time(latest.created_at))}` : '发生认知评估后，这里显示其真实决策与记录。'}</p></div></div>
      ${latest ? `<div class="ev-cognition-note"><p class="ev-kicker">记录中的决策依据</p><p>${esc(decision.reason || '该记录未提供决策说明。')}</p></div>` : '<div class="ev-cognition-note"><p>当前没有可供解释的决策。此处不会推断角色正在关注什么。</p></div>'}
      <div class="ev-cognition-facts"><span>已返回评估 <b>${recent.length}</b></span><span>数值训练步数 <b>${num(data.numeric_steps) === null ? '未提供' : esc(data.numeric_steps)}</b></span></div>
      ${detailButton('cognition', latest?.id || 'overview', '检视认知记录与来源 ↗', 'ev-detail-action')}
      <div class="ev-calibration-note">${data.calibrated === false ? '认知模型尚未完成实证校准。' : data.calibrated === true ? '认知模型已记录校准结果。' : '校准状态尚未提供'}<p>具体依据与限制可在详情中查看。</p></div>
      ${global.PsychViz.provenance(envelope, 'cognition', 'recent')}`;
  }
  function cards(envelopes, mode = 'user') {
    syncContext(envelopes);
    const envelope = envelopes.emotion, data = envelope?.data || {};
    return [
      { id: `${mode}_psych_c1`, domain: 'emotion', title: '心理天气 · 此刻与心境', size: 'wide', body: `<div class="psych-viz ev-view"><div class="ev-toolbar"><p>从两种时间尺度，观察心理状态的相对位置。</p><div class="ev-toggles"><label><input type="checkbox" data-ev-toggle="fast" ${state.fast ? 'checked' : ''}/> ● 快情绪</label><label><input type="checkbox" data-ev-toggle="slow" ${state.slow ? 'checked' : ''}/> ◇ 慢心境</label></div></div><div data-readonly-slot="psych_main">${affectPlane(data, envelope)}</div></div>` },
      { id: `${mode}_psych_c2`, domain: 'emotion', title: '情绪花谱', body: `<div class="psych-viz ev-view"><div class="ev-toolbar"><span class="ev-kicker">每一项真实情绪，各有强度</span><label class="ev-filter-label">显示 <select data-ev-filter aria-label="筛选情绪类型">${[['active', '已激活'], ['all', '全部情绪'], ['zero', '未激活'], ['unknown', '待观察']].map(([value, label]) => `<option value="${value}" ${state.filter === value ? 'selected' : ''}>${label}</option>`).join('')}</select></label></div><div data-readonly-slot="psych_cats24">${emotionBubbles(data, envelope)}</div></div>` },
      { id: `${mode}_psych_c3`, domain: 'cognition', title: '认知焦点', body: `<div class="psych-viz ev-view"><div data-readonly-slot="psych_cognition">${cognitionCard(envelopes)}</div></div>` }
    ];
  }
  function detail(kind, id, envelopes) {
    const envelope = envelopes.emotion, data = envelope?.data || {};
    if (kind === 'emotion') {
      const item = categories(data).find(c => String(c.id) === String(id));
      if (!item) return null;
      return { title: item.name || item.id, id: item.id, description: '真实情绪目录中的单项激活强度；零值表示未激活，缺值表示待观察。', envelope, field: 'categorical_list', updated_at: item.updated_at ?? null, fields: [{ label: '激活强度', value: fmt(item.activation) }, { label: '来源类型', value: item.source_type || '未提供' }, { label: '业务时间', value: time(item.updated_at) }], evidence: item.evidence_refs || item.evidence || null, history: null, raw: item.raw || item };
    }
    if (kind === 'cognition') {
      const cogEnv = cognitionEnvelope(envelopes), cog = cogEnv.data || envelopes.characterProfile?.data?.cognition || {};
      const record = safeArray(cog.recent).find(r => String(r.id) === String(id));
      return { title: record ? '认知评估记录' : '认知状态', id: record?.id || 'cognition', envelope: cogEnv, field: 'recent', updated_at: record?.created_at ?? null, description: '记录来自认知接口；未将缺失的注意原因或影响链补写为心理事实。', fields: [{ label: '运行模式', value: cog.mode || '未提供' }, { label: '机制', value: cog.mechanism || '未提供' }, { label: '评估状态', value: record?.status || '尚无评估记录' }, { label: '动作', value: record?.decision?.action || '未提供' }, { label: '记录时间', value: time(record?.created_at) }, { label: '校准状态', value: cog.calibrated === false ? 'uncalibrated' : cog.calibrated === true ? '接口返回 calibrated=true' : '未提供' }], evidence: record?.evidence || null, history: safeArray(cog.recent).map(r => ({ id: r.id, at: r.created_at, status: r.status, action: r.decision?.action })), raw: record || cog };
    }
    if (kind !== 'affect') return null;
    if (id === 'legend') return { title: '如何阅读心理天气', id: 'affect-plane-legend', envelope, field: 'color_palette', description: '圆点代表快情绪，菱形代表慢心境。两点展示不同时间尺度上的状态，不表示因果或变化轨迹。', fields: [{ label: '横轴', value: 'Valence 愉悦度，−1 至 +1' }, { label: '纵轴', value: 'Arousal 唤醒度，0 至 1' }, { label: '坐标派生', value: 'x = 60 + (V + 1) × 230；y = 300 − A × 250（SVG 坐标）' }, { label: '颜色派生', value: '复用首页 deriveAffectColorPalette(V, A, known)，不改变公式。' }, { label: '缺失处理', value: 'known=false 或缺少合法 V/A 时不绘制点。' }], raw: { coordinate_ranges: { valence: [-1, 1], arousal: [0, 1] }, palette: data.palette }, evidence: null, history: null };
    const names = { valence: '愉悦度', arousal: '唤醒度', dominance: '掌控感', stress: '压力', engagement: '投入度' };
    if (own(names, id)) {
      const raw = data.fast_emotion || data;
      return { title: names[id], id, envelope, field: 'fast_emotion', updated_at: raw.last_updated ?? null, description: `${names[id]}是独立心理状态维度。${id === 'valence' ? '范围 −1 至 +1。' : '范围 0 至 1。'}数值仅来自现有后端计算。`, fields: [{ label: '当前值', value: raw.known === false ? '待观察' : fmt(raw[id]) }, { label: '来源类型', value: raw.source_type || '未提供' }, { label: '业务时间', value: time(raw.last_updated) }], evidence: raw.evidence_refs || null, history: null, raw };
    }
    if (id !== 'fast' && id !== 'slow') return null;
    const p = point(data, id);
    return { title: id === 'fast' ? '快情绪 · 此刻' : '慢心境 · 基线', id: id === 'fast' ? 'fast_emotion' : 'slow_mood', envelope, field: id === 'fast' ? 'fast_emotion' : 'slow_mood', updated_at: p.raw.last_updated || p.raw.updated_at || null, description: id === 'fast' ? '当前快情绪观测，不代表长期人格。' : '较慢变化的心境观测，与快情绪分别展示。', fields: [{ label: '观测状态', value: p.known ? '已有观测' : '尚未产生合法坐标观测' }, { label: '愉悦度 V', value: p.known ? fmt(p.v) : '待观察' }, { label: '唤醒度 A', value: p.known ? fmt(p.a) : '待观察' }, { label: '来源类型', value: p.raw.source_type || '未提供' }, { label: '业务时间', value: time(p.raw.last_updated || p.raw.updated_at) }], evidence: p.raw.evidence_refs || null, history: null, raw: p.raw };
  }
  function handleChange(target) {
    if (target.matches('[data-ev-toggle]') && own(state, target.dataset.evToggle)) { state[target.dataset.evToggle] = target.checked; return true; }
    if (target.matches('[data-ev-filter]') && ['active', 'all', 'zero', 'unknown'].includes(target.value)) { state.filter = target.value; return true; }
    return false;
  }
  global.EmotionView = { cards, detail, handleChange, handleClick: () => false, reset };
})(typeof window !== 'undefined' ? window : globalThis);
