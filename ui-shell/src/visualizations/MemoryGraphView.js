/* Stage 2: display layout only; every node and edge comes from the backend graph. */
(function (global) {
  'use strict';
  const esc = v => global.PsychViz.escape(v ?? '');
  const arr = v => Array.isArray(v) ? v : [];
  const readable = env => env && ['success', 'empty'].includes(env.status);
  const types = { all: '全部', episode: '经历', fact: '事实', preference: '偏好', boundary: '边界', person: '人物', motive: '动机', self: '角色' };
  const time = v => v ? global.formatLocalDisplayTime(v) : '未提供';
  let key = '', ctx = {}, state, lastGood = null, lastGraph = null, latest, mount = null, controller = null;
  let transform = { x: 0, y: 0, k: 1 }, drag = null, suppressUntil = 0, fingerprint = '', positions = new Map();
  function reset() {
    unmount(); state = { scope: ctx.scope, kind: 'all', query: '', nodeType: 'all', selection: '', memory: '', limit: 12, graphLimit: 120 };
    lastGood = null; lastGraph = null; transform = { x: 0, y: 0, k: 1 }; positions = new Map(); fingerprint = '';
  }
  const edgeKey = (e, i) => JSON.stringify([e.source, e.target, e.kind, i]);
  function prepare(envelopes, context) {
    if (context) ctx = context;
    const next = `${ctx.personaId}:${ctx.source}:${ctx.scope}:${ctx.epoch}`;
    if (key !== next) { key = next; reset(); }
    const incoming = envelopes.memories;
    if (readable(incoming)) lastGood = incoming;
    const env = readable(incoming) ? incoming : lastGood || incoming;
    const incomingGraph = incoming?.data?.relation_graph_envelope;
    if (readable(incomingGraph)) lastGraph = incomingGraph;
    const graphEnv = readable(incomingGraph) ? incomingGraph : lastGraph || incomingGraph;
    const graph = readable(graphEnv) ? graphEnv.data : { nodes: [], edges: [] };
    const nodes = arr(graph.nodes).filter(n => n.id != null);
    const edges = arr(graph.edges).map((e, i) => ({ ...e, ui_key: edgeKey(e, i) }));
    const items = arr(env?.data?.items);
    latest = { env, incoming, graphEnv, nodes, edges, items, stale: !!lastGood && !readable(incoming), graphStale: !!lastGraph && !readable(incomingGraph) };
    return latest;
  }
  function inScope(item) { return state.scope === '*' || item.scope === state.scope; }
  function matches(item) { return !state.query || [item.content, item.label, item.id, item.person, item.person_id].some(v => String(v ?? '').toLowerCase().includes(state.query.toLowerCase())); }
  function filtered(m) { return m.items.filter(x => inScope(x) && (state.kind === 'all' || x.kind === state.kind) && matches(x)); }
  function graphData(m) {
    const allowed = m.nodes.filter(n => n.kind === 'self' || inScope(n));
    const direct = new Set(allowed.filter(n => (state.nodeType === 'all' || n.kind === state.nodeType) && (state.kind === 'all' || n.kind === state.kind) && matches(n)).map(n => n.id));
    // Context neighbours must already exist in the returned graph and scope.
    const wanted = new Set(direct);
    if (state.selection) wanted.add(state.selection);
    for (const e of m.edges) if (direct.has(e.source) || direct.has(e.target)) { wanted.add(e.source); wanted.add(e.target); }
    const all = allowed.filter(n => wanted.has(n.id));
    const priority = all.slice().sort((a, b) => Number(b.id === state.selection) - Number(a.id === state.selection) || Number(direct.has(b.id)) - Number(direct.has(a.id)));
    const nodes = priority.slice(0, state.graphLimit), ids = new Set(nodes.map(n => n.id));
    return { nodes, edges: m.edges.filter(e => ids.has(e.source) && ids.has(e.target)), direct, total: all.length };
  }
  function scopeOptions(m) {
    const scopes = [...new Set([ctx.scope, ...m.items.map(x => x.scope), ...m.nodes.map(x => x.scope)].filter(Boolean))];
    return `<option value="*" ${state.scope === '*' ? 'selected' : ''}>全部范围（当前角色）</option>` + scopes.map(s => `<option value="${esc(s)}" ${s === state.scope ? 'selected' : ''}>${esc(s)}</option>`).join('');
  }
  function detailButton(kind, id, label, cls = 'mg-record-button') { return `<button type="button" class="${cls}" data-psych-detail="${kind}" data-detail-id="${esc(id)}">${label}</button>`; }
  function cards(envelopes, mode, context) {
    const m = prepare(envelopes, context), list = filtered(m), g = graphData(m);
    const notice = (m.stale ? '<div class="mg-notice" role="status">STALE · 读取失败，保留上次记忆快照。</div>' : global.PsychViz.state(m.incoming)) + (m.graphStale ? '<div class="mg-notice" role="status">图谱 STALE · 图谱读取失败，保留上次关联快照；来源时间属于该快照。</div>' : '');
    return [{ id: `${mode}_memory_atlas`, domain: 'memories', title: '记忆图谱 · 线索与关联', size: 'wide', body: `<div class="mg-toolbar"><label>观察范围 <select id="selectMemoryScope">${scopeOptions(m)}</select></label><label class="mg-search">搜索记忆 <input type="search" id="inputSubpageMemSearch" value="${esc(state.query)}" placeholder="内容、标识或人物" autocomplete="off"/></label></div><div class="mg-filters" aria-label="记忆类型">${['all', 'episode', 'fact', 'preference', 'boundary'].map(t => `<button type="button" data-mem-filter="${t}" aria-pressed="${t === state.kind}">${types[t]}</button>`).join('')}</div><div data-readonly-slot="memory_notice">${notice}</div><div class="mg-workspace"><section class="mg-library" aria-label="记忆列表"><div data-readonly-slot="memory_count" class="mg-library-heading"><strong>记忆索引</strong><span>${list.length} 条匹配 / ${m.items.length} 条返回</span></div><div id="memoriesFilteredListBox" data-readonly-slot="memories_list" class="mg-list">${list.slice(0, state.limit).map(item => `<article class="mg-record ${String(item.id) === state.memory ? 'is-selected' : ''}" data-memory-record="${esc(item.id)}"><div class="mg-record-meta"><span>${esc(types[item.kind] || item.kind)}</span><span>${esc(item.status || '状态未提供')}</span></div>${detailButton('memory-record', item.id, esc(item.content || '内容未提供'))}<p>${esc(time(item.updated_at || item.created_at))}</p><small>${esc(item.scope || '范围未提供')}</small></article>`).join('') || '<p class="mg-empty">当前范围及筛选下没有记忆。</p>'}${list.length > state.limit ? '<button type="button" class="viz-button" data-mg-action="more">继续加载记忆</button>' : ''}</div><div data-readonly-slot="memory_provenance">${global.PsychViz.provenance(m.env, 'memories', 'memories')}</div></section><section class="mg-map" aria-label="真实关联图"><div class="mg-map-toolbar"><label>节点 <select id="selectMemoryNodeType">${['all', 'person', 'motive', 'episode', 'fact', 'preference', 'boundary'].map(t => `<option value="${t}" ${state.nodeType === t ? 'selected' : ''}>${types[t]}</option>`).join('')}</select></label><div class="mg-map-buttons"><button type="button" data-mg-action="zoom-in" aria-label="放大图谱">＋</button><button type="button" data-mg-action="zoom-out" aria-label="缩小图谱">−</button><button type="button" data-mg-action="fit">适应视图</button><button type="button" data-mg-action="reset">重置</button></div></div><div class="mg-canvas"><svg id="memoryGraphCanvas" viewBox="0 0 900 560" role="group" tabindex="0" aria-label="记忆关联图。拖动空白处平移，滚轮缩放，方向键移动，回车查看节点。"><g data-mg-world></g></svg><div class="mg-map-caption" data-readonly-slot="memory_graph_status">${!readable(m.graphEnv) ? global.PsychViz.state(m.graphEnv) : !g.nodes.length ? '<p>当前范围下没有可显示的节点。</p>' : ''}<span>${g.nodes.length} / ${g.total} 个筛选节点 · ${g.edges.length} 条关联</span>${g.total > state.graphLimit ? '<button type="button" data-mg-action="graph-more">继续加载节点</button>' : ''}</div></div><div class="mg-legend"><span>● 角色</span><span>◇ 人物</span><span>▢ 记忆</span><span>△ 动机</span><span>— 后端关联</span></div><div data-readonly-slot="memory_selection" class="mg-selection">${selectionSummary(m)}<p>位置与距离仅用于排版，不表示心理相似度或因果强度。图谱为接口返回的有限子集，未进入图谱的记忆仍可从左侧阅读。语义相似度检索尚未开放。</p>${global.PsychViz.provenance(m.graphEnv, 'memoryGraph', 'nodes')}</div></section></div>` }];
  }
  function selectionSummary(m) {
    const node = m.nodes.find(n => n.id === state.selection), item = m.items.find(x => String(x.id) === state.memory);
    return node ? `<strong>已选：${esc(node.label || node.id)}</strong><span> · ${m.edges.filter(e => e.source === node.id || e.target === node.id).length} 条返回关联</span>` : item ? '<strong>此记忆未包含在当前图谱子集中，可查看完整记忆详情。</strong>' : '<strong>选择节点或记忆，查看其内容、来源与关联。</strong>';
  }
  function selectDetail(kind, id) {
    if (!latest || !kind.startsWith('memory-')) return;
    if (kind === 'memory-record') { state.memory = String(id); state.selection = latest.nodes.find(n => String(n.memory_id) === String(id))?.id || ''; }
    if (kind === 'memory-node') { state.selection = id; const n = latest.nodes.find(n => n.id === id); state.memory = n?.memory_id == null ? '' : String(n.memory_id); }
    if (state.memory) {
      const item = latest.items.find(x => String(x.id) === state.memory);
      if (item && (!matches(item) || (state.kind !== 'all' && state.kind !== item.kind))) { state.query = ''; state.kind = 'all'; }
    }
    const index = filtered(latest).findIndex(x => String(x.id) === state.memory);
    if (index >= state.limit) state.limit = index + 1;
  }
  function detail(kind, id, envelopes) {
    if (!kind.startsWith('memory-')) return null;
    const m = prepare(envelopes), common = { id, envelope: m.env, field: 'memories', updated_at: null,
      description: m.stale || m.graphStale ? 'STALE：记忆或关联图读取失败，以下包含上次读取的快照。' : '完整记忆读取自当前角色的记忆库；关联图仅呈现后端已返回的投影。' };
    if (kind === 'memory-edge') {
      const e = m.edges.find(x => x.ui_key === id); return e ? { ...common, title: '后端关联', envelope: m.graphEnv, field: 'edges', fields: [{ label: '起点', value: e.source }, { label: '终点', value: e.target }, { label: '关系', value: e.label || e.kind }, { label: '强度（原值）', value: e.strength }], raw: e, derivation: '展示接口现有边；不新增相似度或因果关系。ui_key 仅用于界面定位，非业务标识。' } : null;
    }
    const node = kind === 'memory-node' ? m.nodes.find(n => n.id === id) : m.nodes.find(n => String(n.memory_id) === String(id));
    const item = m.items.find(x => String(x.id) === String(kind === 'memory-node' ? node?.memory_id : id));
    if (!node && !item) return null;
    const raw = item || node, neighbors = node ? m.edges.filter(e => e.source === node.id || e.target === node.id) : [];
    const experience=item?.raw?.experience;
    const experienceFields=experience ? [
      {label:'事件原文',value:experience.external_event?.text},
      {label:'当时的评价',value:experience.mental?.evaluation_summary || '尚无明确评价记录'},
      {label:'当时的情绪',value:Object.entries(experience.mental?.emotion_after || {}).filter(([k,v])=>['valence','arousal','stress','engagement'].includes(k) && typeof v==='number').map(([k,v])=>`${({valence:'愉悦',arousal:'唤醒',stress:'压力',engagement:'投入'})[k]} ${v.toFixed(3)}`).join(' · ') || '尚无情绪记录'},
      {label:'已执行的回应',value:experience.outcome?.actual_reply || '本轮未发言'},
      {label:'后续外界反馈',value:experience.outcome?.external_followup?.text || '尚未观察到'},
      {label:'当时对人物的看法',value:(experience.person_views || []).map(p=>`${p.person_label || p.person_id || '身份未确认'}：${(p.beliefs || []).map(b=>b.statement).join('；') || '暂无明确看法记录'}`).join('\n')}
    ] : [];
    return { ...common, title: item ? '记忆内容与来源' : types[node.kind] || '图谱节点', envelope: item ? m.env : m.graphEnv, field: item ? 'memories' : 'nodes', updated_at: raw.updated_at || raw.created_at || null,
      fields: [...experienceFields, { label: '内容', value: item?.content || node?.content || node?.label }, { label: '类别', value: types[raw.kind] || raw.kind }, { label: '范围', value: raw.scope }, { label: '人物', value: raw.person || raw.person_id }, { label: '状态', value: raw.status }, { label: '重要性（原值）', value: raw.importance }, { label: '置信度（原值）', value: raw.confidence }, { label: '形成时间', value: time(raw.created_at) }, { label: '图谱关联', value: neighbors.length ? neighbors.map(e => `${e.label || e.kind}: ${e.source === node.id ? e.target : e.source}`).join('\n') : '未返回关联' }],
        evidence: item?.evidence, raw: { record: item?.raw || item, node, edges: neighbors, source_turn: item?.source_turn },
      actions: node ? [{ action: 'memory-locate', id: node.id, label: '在图中定位' }] : [], derivation: '节点坐标为界面排版。未用内容相似度生成边，未将投影边当作独立证据。' };
  }
  function applyTransform() { mount?.querySelector('[data-mg-world]')?.setAttribute('transform', `translate(${transform.x} ${transform.y}) scale(${transform.k})`); }
  function position(n, i) {
    if (!positions.has(n.id)) { const radius = n.kind === 'self' ? 0 : 95 + 28 * Math.sqrt(i + 1), a = i * 2.399963; positions.set(n.id, { x: 450 + Math.cos(a) * radius, y: 280 + Math.sin(a) * radius }); }
    return positions.get(n.id);
  }
  function fit(nodes) {
    if (!nodes.length) { transform = { x: 0, y: 0, k: 1 }; applyTransform(); return; }
    const p = nodes.map((n, i) => position(n, i)), xs = p.map(v => v.x), ys = p.map(v => v.y);
    const left = Math.min(...xs) - 75, right = Math.max(...xs) + 75, top = Math.min(...ys) - 45, bottom = Math.max(...ys) + 55;
    const k = Math.min(2, 900 / (right - left), 560 / (bottom - top));
    transform = { k, x: 450 - ((left + right) / 2) * k, y: 280 - ((top + bottom) / 2) * k }; applyTransform();
  }
  function zoom(factor, x = 450, y = 280) { const k = Math.max(.2, Math.min(4, transform.k * factor)), r = k / transform.k; transform = { k, x: x - (x - transform.x) * r, y: y - (y - transform.y) * r }; applyTransform(); }
  function localPoint(e) { const p = new DOMPoint(e.clientX, e.clientY); return p.matrixTransform(mount.getScreenCTM().inverse()); }
  function afterRender(root) {
    const svg = root.querySelector('#memoryGraphCanvas');
    if (!svg || !latest) return;
    if (svg !== mount) {
      unmount(); mount = svg; controller = new AbortController(); const signal = controller.signal;
      mount.addEventListener('pointerdown', e => { if (e.button !== 0 || e.target.closest('[data-psych-detail]')) return; const p = localPoint(e); drag = { id: e.pointerId, x: p.x, y: p.y, tx: transform.x, ty: transform.y, moved: false }; mount.setPointerCapture(e.pointerId); }, { signal });
      mount.addEventListener('pointermove', e => { if (!drag || drag.id !== e.pointerId) return; const p = localPoint(e), dx = p.x - drag.x, dy = p.y - drag.y; drag.moved ||= Math.abs(dx) + Math.abs(dy) > 5; transform.x = drag.tx + dx; transform.y = drag.ty + dy; applyTransform(); }, { signal });
      const finish = () => { if (drag?.moved) suppressUntil = Date.now() + 250; drag = null; };
      mount.addEventListener('pointerup', finish, { signal }); mount.addEventListener('pointercancel', finish, { signal }); mount.addEventListener('lostpointercapture', finish, { signal });
      mount.addEventListener('wheel', e => { e.preventDefault(); const p = localPoint(e); zoom(e.deltaY < 0 ? 1.12 : 1 / 1.12, p.x, p.y); }, { signal, passive: false });
      mount.addEventListener('keydown', e => { if (e.target !== mount) return; if (e.key === '+' || e.key === '=') zoom(1.2); else if (e.key === '-') zoom(1 / 1.2); else if (e.key === 'Home') fit(graphData(latest).nodes); else if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) { transform.x += e.key === 'ArrowLeft' ? 30 : e.key === 'ArrowRight' ? -30 : 0; transform.y += e.key === 'ArrowUp' ? 30 : e.key === 'ArrowDown' ? -30 : 0; applyTransform(); } else return; e.preventDefault(); }, { signal });
      fingerprint = '';
    }
    const g = graphData(latest), fp = JSON.stringify([g.nodes, g.edges, state.selection, state.query, state.kind, state.nodeType]);
    if (fp !== fingerprint && !drag) {
      const focused = document.activeElement?.dataset?.detailId;
      const world = mount.querySelector('[data-mg-world]');
      g.nodes.forEach(position);
      world.innerHTML = g.edges.map(e => { const a = positions.get(e.source), b = positions.get(e.target); return `<g role="button" tabindex="0" class="mg-edge" data-psych-detail="memory-edge" data-detail-id="${esc(e.ui_key)}" aria-label="${esc(e.label || e.kind)}，查看关联"><title>${esc(e.label || e.kind)}</title><line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" class="mg-edge-hit"/><line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" class="mg-edge-line"/></g>`; }).join('') + g.nodes.map(n => { const p = positions.get(n.id), shape = n.kind === 'self' ? '<circle r="23"/>' : n.kind === 'person' ? '<path d="M0 -19L19 0L0 19L-19 0Z"/>' : n.kind === 'motive' ? '<path d="M0 -20L20 16L-20 16Z"/>' : '<rect x="-16" y="-16" width="32" height="32" rx="8"/>'; return `<g transform="translate(${p.x} ${p.y})" role="button" tabindex="0" class="mg-node mg-node-${['self', 'person', 'motive'].includes(n.kind) ? n.kind : 'memory'} ${n.id === state.selection ? 'is-selected' : ''} ${g.direct.has(n.id) ? '' : 'is-context'}" data-psych-detail="memory-node" data-detail-id="${esc(n.id)}" aria-label="${esc(types[n.kind] || n.kind)}：${esc(n.label || n.id)}，查看详情"><title>${esc(n.label || n.id)}</title>${shape}<text y="38" text-anchor="middle">${esc(String(n.label || n.id).slice(0, 16))}</text></g>`; }).join('');
      fingerprint = fp;
      if (focused) [...world.querySelectorAll('[data-detail-id]')].find(el => el.dataset.detailId === focused)?.focus({ preventScroll: true });
    }
    applyTransform(); syncControls(root);
  }
  function unmount() { controller?.abort(); controller = null; mount = null; drag = null; }
  function locate(id) {
    if (!latest?.nodes.some(n => n.id === id)) return;
    state.selection = id; state.nodeType = 'all'; state.kind = 'all'; state.query = ''; state.limit = Math.max(state.limit, latest.items.findIndex(x => String(x.id) === String(latest.nodes.find(n => n.id === id)?.memory_id)) + 1);
    const node = latest.nodes.find(n => n.id === id);
    state.memory = node?.memory_id == null ? '' : String(node.memory_id);
    const p = position(node, latest.nodes.indexOf(node));
    transform.x = 450 - p.x * transform.k; transform.y = 280 - p.y * transform.k; applyTransform();
    global.PsychViz.close();
  }
  function handleClick(el) {
    const locateButton = el.closest('[data-viz-action="memory-locate"]'); if (locateButton) { locate(locateButton.dataset.actionId); return true; }
    const filter = el.closest('[data-mem-filter]'); if (filter) { state.kind = filter.dataset.memFilter; state.limit = 12; return true; }
    const action = el.closest('[data-mg-action]')?.dataset.mgAction; if (!action) return false;
    if (action === 'more') state.limit += 12;
    if (action === 'graph-more') state.graphLimit += 120;
    if (action === 'zoom-in') zoom(1.25);
    if (action === 'zoom-out') zoom(.8);
    if (action === 'fit') fit(graphData(latest).nodes);
    if (action === 'reset') { transform = { x: 0, y: 0, k: 1 }; positions.clear(); fingerprint = ''; applyTransform(); }
    return true;
  }
  function handleChange(el) {
    if (el.id === 'inputSubpageMemSearch') { state.query = el.value; state.limit = 12; return true; }
    if (el.id === 'selectMemoryScope') { state.scope = el.value; state.selection = ''; state.memory = ''; state.limit = 12; global.PsychViz.close(); transform = { x: 0, y: 0, k: 1 }; return true; }
    if (el.id === 'selectMemoryNodeType') { state.nodeType = el.value; return true; }
    return false;
  }
  function syncControls(root) {
    root.querySelectorAll('[data-mem-filter]').forEach(el => el.setAttribute('aria-pressed', el.dataset.memFilter === state.kind ? 'true' : 'false'));
    const scope = root.querySelector('#selectMemoryScope'); if (scope && latest) { const html = scopeOptions(latest); if (scope.innerHTML !== html) scope.innerHTML = html; scope.value = state.scope; }
    const search = root.querySelector('#inputSubpageMemSearch'); if (search && search.value !== state.query) search.value = state.query;
    const type = root.querySelector('#selectMemoryNodeType'); if (type) type.value = state.nodeType;
  }
  global.MemoryGraphView = { cards, detail, selectDetail, handleChange, handleClick, afterRender, unmount, isDragging: () => Date.now() < suppressUntil };
})(window);
