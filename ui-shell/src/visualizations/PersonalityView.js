/* Phase 3.0 Stage 1 — read-only personality visualization over the existing envelope. */
(function (global) {
  'use strict';
  const state = { persona: null, group: 'all', filter: 'all', sort: 'estimate', query: '', limit: 8 };
  const esc = value => global.PsychViz.escape(value);
  const num = value => global.PsychViz.number(value);
  const fmt = value => global.PsychViz.value(value);
  const clamp = value => Math.max(0, Math.min(1, value));
  const coord = (radius, angle, cx = 210, cy = 163) => [cx + Math.cos(angle) * radius, cy + Math.sin(angle) * radius];
  const xy = point => point.map(v => v.toFixed(2)).join(',');
  const list = value => Array.isArray(value) ? value : [];
  const sourceLabels = { owner_seed: '角色设定', promoted: '证据晋升', questionnaire: '量表记录', unknown: '来源待确认' };
  const groupLabels = { HEXACO: '人格特质', SCHWARTZ: '价值取向', INTERPERSONAL: '人际倾向', PID5: '适应性倾向', PID_5: '适应性倾向', PANAS: '情感倾向', ERQ: '情绪调节', ATTACHMENT: '依恋倾向' };
  function reset(persona) {
    Object.assign(state, { persona: persona ?? null, group: 'all', filter: 'all', sort: 'estimate', query: '', limit: 8 });
  }
  function sync(envelopes) {
    const persona = `${envelopes.characterProfile?.data?.id || ''}:${envelopes.mode || envelopes.personality?.source || ''}`;
    if (state.persona !== persona) reset(persona);
  }
  function catalog(data) {
    const entries = list(data.editable_constructs);
    // The registry defines membership and denominators. Snapshot buckets are only a fallback for older explicit demos.
    return entries.length ? entries : list(data.blocks68).flatMap(b => list(b.items).map(i => ({ ...i, name_zh: i.label || i.id, group: b.name, minimum: 0, maximum: 1 })));
  }
  function evidence(item) { return list(item.evidence).length ? item.evidence : (item.evidence_refs ?? item.evidence ?? []); }
  function evidenceCount(item) {
    if (num(item.evidence_count) !== null) return Number(item.evidence_count);
    const refs = evidence(item);
    return Array.isArray(refs) ? refs.length : (refs && typeof refs === 'object' ? Object.keys(refs).length : 0);
  }
  function groupName(group) { return groupLabels[String(group).toUpperCase()] || group || '其他构念'; }
  function groupList(items) {
    const groups = new Map();
    items.forEach(item => {
      const key = item.group || 'CONSTRUCT';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(item);
    });
    return Array.from(groups, ([id, entries]) => ({ id, entries, known: entries.filter(i => num(i.estimate) !== null) }));
  }
  function source(envelope, field) {
    return global.PsychViz?.provenance ? global.PsychViz.provenance(envelope, 'personality', field) : '';
  }
  function action(kind, id, text, cls = '') {
    return `<button type="button" class="pv-detail-link ${cls}" data-psych-detail="${esc(kind)}" data-detail-id="${esc(id)}">${text}</button>`;
  }
  function unavailable(envelope) {
    if (!envelope) return global.PsychViz.state(envelope);
    if (envelope?.status === 'error' || envelope?.status === 'unavailable' || envelope?.status === 'loading') {
      const label = envelope.status === 'loading' ? '正在读取人格档案' : '人格数据暂不可用';
      return `<div class="pv-empty" role="status"><span class="pv-empty-icon">◇</span><strong>${label}</strong><p>${esc(envelope.error || '等待真实数据返回后再描绘人格轮廓。')}</p></div>`;
    }
    return '';
  }
  function radar(data) {
    const domains = list(data.hexaco);
    if (!domains.length) return '<div class="pv-empty"><span class="pv-empty-icon">◇</span><strong>人格轮廓待形成</strong><p>当前数据未提供可绘制的维度目录。</p></div>';
    const radius = 111, count = domains.length;
    const angle = i => -Math.PI / 2 + i * Math.PI * 2 / count;
    const known = domains.filter(d => num(d.val) !== null);
    const points = domains.map((d, i) => num(d.val) === null ? null : coord(clamp(Number(d.val)) * radius, angle(i)));
    let drawing = [0.25, 0.5, 0.75, 1].map(r => `<polygon class="pv-radar-grid" points="${domains.map((d, i) => xy(coord(radius * r, angle(i)))).join(' ')}"/>`).join('');
    drawing += domains.map((d, i) => {
      const p = coord(radius, angle(i)), t = coord(radius + 32, angle(i));
      const chosen = state.group === `domain:${d.code}`;
      return `<line class="pv-radar-axis ${num(d.val) === null ? 'is-unknown' : ''}" x1="210" y1="163" x2="${p[0]}" y2="${p[1]}"/>
        <g role="button" tabindex="0" aria-label="查看${esc(d.name)}构念" data-pv-axis="${esc(d.code)}" class="pv-radar-label ${chosen ? 'is-selected' : ''}"><rect x="${t[0] - 48}" y="${t[1] - 15}" width="96" height="43" rx="12"/><text x="${t[0]}" y="${t[1]}" text-anchor="middle">${esc(d.name)}</text><text class="pv-axis-value" x="${t[0]}" y="${t[1] + 17}" text-anchor="middle">${num(d.val) === null ? '待观察' : fmt(d.val)}</text></g>`;
    }).join('');
    if (known.length === domains.length) drawing += `<polygon class="pv-radar-fill" points="${points.map(xy).join(' ')}"/>`;
    // Connect only adjacent observed axes; a gap never becomes a zero-valued polygon vertex.
    points.forEach((p, i) => {
      const next = points[(i + 1) % points.length];
      if (p && next) drawing += `<line class="pv-radar-edge" x1="${p[0]}" y1="${p[1]}" x2="${next[0]}" y2="${next[1]}"/>`;
      if (p) drawing += `<circle data-pv-known-axis="${esc(domains[i].code)}" class="pv-radar-point" cx="${p[0]}" cy="${p[1]}" r="5"/>`;
    });
    if (!known.length) drawing += '<text class="pv-chart-empty-title" x="210" y="159" text-anchor="middle">轮廓待形成</text><text class="pv-chart-empty-note" x="210" y="181" text-anchor="middle">有观测后，才描绘形状</text>';
    return `<div class="pv-radar-wrap"><svg class="pv-radar" viewBox="0 0 420 342" role="group" aria-label="HEXACO 人格轮廓：${known.length} 个维度已有估计；点击轴名查看构念">${drawing}</svg>
      <div class="pv-chart-legend"><span><i class="pv-key is-known"></i>已有估计</span><span><i class="pv-key"></i>待观察轴保留缺口</span></div>
      <p class="pv-note">点击轴名，查看这一维度如何形成。维度数值沿用后端对已知子维度的汇总。</p></div>`;
  }
  function overview(data, envelope) {
    const items = catalog(data), known = items.filter(i => num(i.estimate) !== null), groups = groupList(items);
    const ratio = items.length ? known.length / items.length : 0;
    return `<div class="pv-overview"><div class="pv-overview-heading"><div><div class="pv-eyebrow">构念全景</div><h4>正在认识的自己</h4><p>已建档 <strong>${known.length}</strong> / ${items.length} 项 · 人格版本 ${esc(data.version ?? '待确认')}</p></div>
        <svg class="pv-coverage" viewBox="0 0 80 80" aria-label="目录建档 ${known.length}/${items.length}"><circle cx="40" cy="40" r="32" class="pv-coverage-track"/><circle cx="40" cy="40" r="32" class="pv-coverage-value" stroke-dasharray="${ratio * 201.06} 201.06"/><text x="40" y="45" text-anchor="middle">${Math.round(ratio * 100)}%</text></svg></div>
        <div class="pv-groups">${groups.map(g => {
          const top = g.known.slice().sort((a,b) => Number(b.estimate) - Number(a.estimate))[0];
          return `<button type="button" class="pv-group ${state.group === g.id ? 'is-selected' : ''}" data-pv-group="${esc(g.id)}" aria-pressed="${state.group === g.id}"><span class="pv-group-head"><strong>${esc(groupName(g.id))}</strong><small>${g.known.length} / ${g.entries.length}</small><span aria-hidden="true">↗</span></span><span class="pv-coverage-bar"><i style="width:${g.known.length / g.entries.length * 100}%"></i></span><span class="pv-group-note">${top ? `已知较高项 · ${esc(top.name_zh || top.id)} ${fmt(top.estimate)}` : '尚未形成估计，等待设定或证据'}</span></button>`;
        }).join('') || '<p class="pv-note">当前未返回构念目录。</p>'}</div>
        <div class="pv-provenance">${source(envelope, 'constructs_68')}</div></div>`;
  }
  function valuesChart(data, envelope) {
    const values = list(data.schwartz_values), known = values.filter(v => num(v.estimate) !== null);
    const colors = { openness_to_change: '#789368', self_enhancement: '#ac9464', conservation: '#8599a1', self_transcendence: '#a18491' };
    const labels = { openness_to_change: '开放与变化', self_enhancement: '自我提升', conservation: '保守与稳定', self_transcendence: '自我超越' };
    let drawing = [36, 67, 98].map(r => `<circle class="pv-value-grid" cx="185" cy="154" r="${r}"/>`).join('');
    drawing += values.map((v, i) => {
      const angle = ((num(v.angle_deg) ?? (i * 360 / Math.max(1, values.length))) - 90) * Math.PI / 180;
      const base = coord(37, angle, 185, 154), end = coord(37 + 61 * clamp(num(v.estimate) ?? 0), angle, 185, 154);
      const outer = coord(98, angle, 185, 154), label = coord(122, angle, 185, 154);
      const isKnown = num(v.estimate) !== null;
      return `<g class="pv-value-mark" role="button" tabindex="0" data-psych-detail="value" data-detail-id="${esc(v.id)}" aria-label="${esc(v.label)}：${isKnown ? fmt(v.estimate) : '待观察'}"><line class="pv-value-ray" x1="${base[0]}" y1="${base[1]}" x2="${outer[0]}" y2="${outer[1]}"/>
      ${isKnown ? `<line data-pv-value="${esc(v.id)}" class="pv-value-bar" style="stroke:${colors[v.quadrant] || '#789368'}" x1="${base[0]}" y1="${base[1]}" x2="${end[0]}" y2="${end[1]}"/><circle cx="${end[0]}" cy="${end[1]}" r="3.5" fill="${colors[v.quadrant] || '#789368'}"/>` : `<circle class="pv-value-unknown" cx="${outer[0]}" cy="${outer[1]}" r="3"/>`}
      <text x="${label[0]}" y="${label[1] + 3}" text-anchor="${label[0] < 165 ? 'end' : label[0] > 205 ? 'start' : 'middle'}">${esc(v.label)}</text></g>`;
    }).join('');
    drawing += `<text class="pv-chart-empty-note" x="185" y="152" text-anchor="middle">已知价值</text><text class="pv-value-count" x="185" y="172" text-anchor="middle">${known.length} / ${values.length}</text>`;
    return `<div class="pv-values"><p class="pv-lead">不同方向，呈现当前已记录的价值优先级。</p><svg viewBox="0 0 370 307" role="group" aria-label="Schwartz 价值方向，${known.length}项已知">${drawing}</svg><div class="pv-chart-legend">${Object.entries(labels).map(([key,label]) => `<span><i class="pv-key" style="background:${colors[key]};border-color:${colors[key]}"></i>${label}</span>`).join('')}</div><p class="pv-note">实心端点为已知值，空心端点为待观察；径向长度表示估计值，不代表证据强弱。点击查看来源。</p>${source(envelope, 'schwartz_values')}</div>`;
  }
  function interpersonal(data, envelope) {
    const ip = data.interpersonal_2d?.interpersonal_circumplex || {};
    const a = num(ip.agency), c = num(ip.communion), known = ip.known === true && a !== null && c !== null;
    const x = 58 + clamp(c ?? 0) * 254, y = 246 - clamp(a ?? 0) * 200;
    return `<div class="pv-interpersonal"><p class="pv-lead">在人际互动中，观察主体性与联结倾向。</p><svg viewBox="0 0 370 307" role="group" aria-label="人际坐标，${known ? `亲和性 ${fmt(c)}，主体性 ${fmt(a)}` : '待形成，未绘制坐标点'}">
      <rect x="58" y="46" width="254" height="200" rx="18" class="pv-plane-bg"/>
      <line class="pv-plane-midline" x1="185" y1="46" x2="185" y2="246"/><line class="pv-plane-midline" x1="58" y1="146" x2="312" y2="146"/>
      <text class="pv-plane-label" x="185" y="24" text-anchor="middle">主体性 Agency ↑</text><text class="pv-plane-label" x="185" y="286" text-anchor="middle">亲和性 Communion →</text>
      <text class="pv-plane-tick" x="42" y="51">1</text><text class="pv-plane-tick" x="42" y="250">0</text><text class="pv-plane-tick" x="58" y="265">0</text><text class="pv-plane-tick" x="307" y="265">1</text>
      ${known ? `<g role="button" tabindex="0" class="pv-ip-point" data-psych-detail="interpersonal" data-detail-id="interpersonal_circumplex" aria-label="查看人际坐标来源"><circle class="pv-ip-halo" cx="${x}" cy="${y}" r="20"/><circle data-pv-interpersonal-point="true" class="pv-radar-point" cx="${x}" cy="${y}" r="7"/></g>` : '<text class="pv-chart-empty-title" x="185" y="141" text-anchor="middle">人际坐标待形成</text><text class="pv-chart-empty-note" x="185" y="164" text-anchor="middle">两个维度都有估计后再定位</text>'}
      </svg><div class="pv-ip-numbers">${action('construct', 'social.agency', `<span>主体性</span><strong>${fmt(a)}</strong>`)}${action('construct', 'social.communion', `<span>亲和性</span><strong>${fmt(c)}</strong>`)}</div><p class="pv-note">坐标是模型构念的线性投影，不预测具体行为。</p>${source(envelope, 'interpersonal_2d')}</div>`;
  }
  function selectedItems(data) {
    let items = catalog(data).slice();
    if (state.group.startsWith('domain:')) {
      const domain = list(data.hexaco).find(d => String(d.code) === state.group.slice(7));
      const ids = new Set(list(domain?.facets).map(f => typeof f === 'string' ? f : f.id));
      items = items.filter(i => ids.has(i.id));
    } else if (state.group !== 'all') items = items.filter(i => (i.group || 'CONSTRUCT') === state.group);
    if (state.filter !== 'all') items = items.filter(i => (num(i.estimate) !== null) === (state.filter === 'known'));
    const query = state.query.trim().toLocaleLowerCase();
    if (query) items = items.filter(i => `${i.name_zh || ''} ${i.id || ''}`.toLocaleLowerCase().includes(query));
    const timestamp = i => typeof i.updated_at === 'number' ? i.updated_at * (i.updated_at < 1e11 ? 1000 : 1) : Date.parse(i.updated_at || '') || 0;
    items.sort((a,b) => {
      if (state.sort === 'evidence') return evidenceCount(b) - evidenceCount(a);
      if (state.sort === 'time') return timestamp(b) - timestamp(a);
      return (num(b.estimate) ?? -Infinity) - (num(a.estimate) ?? -Infinity) || String(a.id).localeCompare(String(b.id));
    });
    return items;
  }
  function matrix(data, envelope) {
    const items = selectedItems(data);
    const selectedName = state.group.startsWith('domain:') ? list(data.hexaco).find(d => String(d.code) === state.group.slice(7))?.name : groupName(state.group);
    return `<div class="pv-matrix-caption"><span>${state.group === 'all' ? '全部构念' : esc(selectedName || '所选维度')} · ${items.length} 项符合条件</span>${state.group !== 'all' ? '<button type="button" class="pv-text-button" data-pv-group="all">显示所有分组</button>' : ''}</div>
      <div class="pv-matrix">${items.slice(0, state.limit).map(item => {
        const value = num(item.estimate), min = num(item.minimum), max = num(item.maximum);
        const fraction = value !== null && min !== null && max !== null && max > min ? clamp((value - min) / (max - min)) : null;
        return `<button type="button" class="pv-construct ${value === null ? 'is-unknown' : ''}" data-psych-detail="construct" data-detail-id="${esc(item.id)}"><span class="pv-construct-name"><strong>${esc(item.name_zh || item.id)}</strong><small>${esc(groupName(item.group))} · ${esc(sourceLabels[item.source_type] || item.source_type || '来源待确认')}</small></span><span class="pv-construct-meter" aria-hidden="true">${fraction !== null ? `<i style="width:${fraction * 100}%"></i>` : ''}</span><span class="pv-construct-value">${fmt(value)}</span><span class="pv-construct-evidence">${evidenceCount(item) ? `${evidenceCount(item)} 条证据` : '查看依据'} ↗</span></button>`;
      }).join('') || '<div class="pv-empty pv-empty-small"><strong>没有符合条件的构念</strong><p>可调整分组、已知状态或搜索词。</p></div>'}</div>
      <div class="pv-matrix-footer"><span>每项只展示当前估计，依据与真实历史在详情中查看。</span>${items.length > state.limit ? `<button type="button" class="pv-text-button" data-pv-more="true">再显示 ${Math.min(8, items.length - state.limit)} 项 ↓</button>` : ''}</div>${source(envelope, 'constructs_68')}`;
  }
  function controls() {
    return `<div class="pv-controls"><label>查找构念<input type="search" data-pv-search="true" value="${esc(state.query)}" placeholder="名称或标识" autocomplete="off"/></label><label>记录状态<select data-pv-filter="true"><option value="all" ${state.filter === 'all' ? 'selected' : ''}>全部</option><option value="known" ${state.filter === 'known' ? 'selected' : ''}>已有估计</option><option value="unknown" ${state.filter === 'unknown' ? 'selected' : ''}>待观察</option></select></label><label>排列方式<select data-pv-sort="true"><option value="estimate" ${state.sort === 'estimate' ? 'selected' : ''}>估计值</option><option value="time" ${state.sort === 'time' ? 'selected' : ''}>最近更新</option><option value="evidence" ${state.sort === 'evidence' ? 'selected' : ''}>证据数量</option></select></label></div>`;
  }
  function cards(envelopes, mode = 'user') {
    sync(envelopes);
    const env = envelopes.personality, data = env?.data || {}, fault = unavailable(env);
    return [
      { id: `${mode}_panalysis_c1`, domain: 'personality', title: '人格轮廓 · 逐渐清晰的自己', size: 'wide', body: `<div class="psych-viz pv-view" data-readonly-slot="panalysis_blocks68">${fault || `<div class="pv-profile">${radar(data)}${overview(data, env)}</div>`}</div>` },
      { id: `${mode}_panalysis_c2`, domain: 'personality', title: '价值方向 · 什么更重要', body: `<div class="psych-viz pv-view" data-readonly-slot="panalysis_schwartz">${fault || valuesChart(data, env)}</div>` },
      { id: `${mode}_panalysis_ip`, domain: 'personality', title: '人际坐标 · 自主与联结', body: `<div class="psych-viz pv-view" data-readonly-slot="panalysis_interpersonal">${fault || interpersonal(data, env)}</div>` },
      { id: `${mode}_panalysis_matrix`, domain: 'personality', title: '形成的依据 · 从构念深入', size: 'wide', body: `<div class="psych-viz pv-view">${controls()}<div data-readonly-slot="panalysis_matrix">${fault || matrix(data, env)}</div></div>` }
    ];
  }
  function handleClick(target) {
    const group = target.closest?.('[data-pv-group]');
    const axis = target.closest?.('[data-pv-axis]');
    const more = target.closest?.('[data-pv-more]');
    if (group || axis) { state.group = group ? group.dataset.pvGroup : `domain:${axis.dataset.pvAxis}`; state.limit = 8; return true; }
    if (more) { state.limit += 8; return true; }
    return false;
  }
  function handleChange(target) {
    if (target.matches?.('[data-pv-search]')) state.query = target.value;
    else if (target.matches?.('[data-pv-filter]')) state.filter = target.value;
    else if (target.matches?.('[data-pv-sort]')) state.sort = target.value;
    else return false;
    state.limit = 8;
    return true;
  }
  function detail(kind, id, envelopes) {
    const envelope = envelopes.personality, data = envelope?.data || {};
    if (kind === 'interpersonal') {
      const raw = data.interpersonal_2d?.interpersonal_circumplex || {};
      return { title: '人际坐标', id, envelope, field: 'interpersonal_2d', description: '横轴为亲和性，纵轴为主体性；仅在两个真实估计均存在且 known=true 时绘制坐标。', fields: [{label:'主体性',value:fmt(raw.agency)}, {label:'亲和性',value:fmt(raw.communion)}, {label:'主体性来源',value:raw.agency_source || '未提供'}, {label:'亲和性来源',value:raw.communion_source || '未提供'}], evidence:raw.construct_refs || [], history:[], raw };
    }
    if (kind !== 'construct' && kind !== 'value') return null;
    const current = catalog(data).find(i => i.id === id);
    const valueItem = list(data.schwartz_values).find(i => i.id === id);
    const raw = current ? { ...valueItem, ...current } : valueItem;
    if (!raw) return {title:'当前角色尚无该构念记录', id, envelope, field:'constructs_68', fields:[], evidence:[], history:[], raw:null};
    // Only exact feature references link a promotion to this construct; revisions are not invented value history.
    const history = Array.isArray(raw.history) ? raw.history : list(data.promotion_history).filter(h => h.feature_id === id || h.construct_id === id || h.id === id);
    return { title:raw.name_zh || raw.label || id, id, envelope, field:id, updated_at:raw.updated_at, description:'当前值来自角色档案。缺失的不确定度、证据及历史保持未提供；构念不能直接等同于具体行为。', fields:[{label:'当前估计',value:fmt(raw.estimate)}, {label:'不确定度',value:num(raw.uncertainty) === null ? '未提供' : fmt(raw.uncertainty)}, {label:'来源类型',value:sourceLabels[raw.source_type] || raw.source_type || '未提供'}, {label:'证据数量',value:evidenceCount(raw)}, {label:'记录更新',value:raw.updated_at ? global.formatLocalDisplayTime(raw.updated_at) : '未提供'}, {label:'人格版本',value:data.version ?? '未提供'}, {label:'分组',value:groupName(raw.group || valueItem?.quadrant)}, {label:'尺度',value:raw.minimum !== undefined && raw.maximum !== undefined ? `${raw.minimum} 至 ${raw.maximum}` : '0 至 1'}, {label:'源字段',value:raw.field_path || '未提供'}], evidence:evidence(raw), history, raw };
  }
  global.PersonalityView = { cards, detail, handleClick, handleChange, reset, getState: () => ({ ...state }) };
})(window);
