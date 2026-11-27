/* Exact scoped social claims. Co-presence does not create a relationship. */
(function (global) {
  'use strict';
  const esc = v => global.PsychViz.escape(v ?? '');
  const arr = v => Array.isArray(v) ? v : [];
  const good = e => e && ['success', 'empty'].includes(e.status);
  const name = p => global.DisplayText.person(p?.alias || p?.display_name || p?.label || p?.person_id || p?.id || '名称未提供');
  const label = s => ({ unverified: '未核验陈述', disputed: '存在争议', confirmed: '已确认', verified: '已核验', retracted: '已撤回', self_report: '本人陈述', third_party_report: '第三方转述', support: '支持', counter: '反例' }[s] || s || '未提供');
  const edgeKey = (e, i) => String(e.id ?? JSON.stringify([e.source, e.target, e.relation_type || e.kind, i]));
  let context = '', state, latest, cached = null, positions = new Map(), rendered = '';
  const viewport = new global.GraphViewport();
  function prepare(env, ctx) {
    if (ctx) { const key = `${ctx.personaId}:${ctx.source}:${ctx.scope}:${ctx.epoch}`; if (key !== context) { context = key; cached = null; state = { query: '', status: '*', selected: '', limit: 100 }; positions.clear(); viewport.detach(); viewport.reset(); rendered = ''; } }
    const incoming = env.socialGraph; if (good(incoming)) cached = incoming;
    const e = good(incoming) ? incoming : cached || incoming, data = e?.data || {};
    latest = { env: e, incoming, stale: !!cached && !good(incoming), data,
      nodes: arr(data.topology?.nodes).filter(n => n.id != null), edges: arr(data.topology?.edges).map((r, i) => ({ ...r, ui_key: edgeKey(r, i) })),
      people: arr(data.people).filter(p => p.scope === data.scope) };
    return latest;
  }
  function graph(m) {
    const edges = m.edges.filter(e => state.status === '*' || e.status === state.status);
    const matches = new Set(m.nodes.filter(n => !state.query || name(m.people.find(p => p.person_id === n.id) || n).toLowerCase().includes(state.query.toLowerCase()) || String(n.id).includes(state.query)).map(n => n.id));
    const selected = new Set(matches);
    for (const e of edges) if (matches.has(e.source) || matches.has(e.target)) { selected.add(e.source); selected.add(e.target); }
    const all = m.nodes.filter(n => selected.has(n.id)), nodes = all.slice(0, state.limit), ids = new Set(nodes.map(n => n.id));
    return { nodes, total: all.length, edges: edges.filter(e => ids.has(e.source) && ids.has(e.target)) };
  }
  function cards(env, mode, ctx) {
    const m = prepare(env, ctx), g = graph(m), self = m.nodes.find(n => n.entity_type === 'agent_self');
    const contacts = m.nodes.filter(n => n.entity_type !== 'agent_self'), options = arr(m.data.scope_options);
    const optionsHtml = options.map(o => `<option value="${esc(o.value)}" ${ctx.scope === o.value ? 'selected' : ''}>${esc(o.label)}</option>`).join('');
    return [{ id: `${mode}_relation_network`, domain: 'social', title: '与谁相识 · 怎样相处', size: 'wide', body: `
      <div class="relation-overview"><span class="relation-self-avatar">${esc(name(self).slice(0, 1))}</span><div><h4>${esc(self ? name(self) : '当前角色')}的关系记录</h4><p>选择一段私聊或群聊，查看这一范围内的互动。点击人物或连线，可以了解记录的依据。</p></div></div>
      <div class="life-toolbar"><label>联系人与会话<select id="inputSocialScope">${optionsHtml || `<option value="${esc(ctx.scope)}">${esc(global.DisplayText.scope(ctx.scope))}</option>`}</select></label><label class="life-search">寻找人物<input type="search" id="relationSearch" value="${esc(state.query)}" placeholder="输入昵称或 QQ 号"/></label><label>关系状态<select id="relationStatus"><option value="*">全部状态</option>${[...new Set(m.edges.map(e => e.status).filter(Boolean))].map(v => `<option value="${esc(v)}" ${v === state.status ? 'selected' : ''}>${esc(global.DisplayText.label(v))}</option>`).join('')}</select></label></div>
      <div class="relation-scope-picker" data-readonly-slot="relation_scope_choices">${options.map(o => `<button type="button" data-relationship-scope="${esc(o.value)}" class="${ctx.scope === o.value ? 'active' : ''}">${esc(o.label)}</button>`).join('')}</div>
      <div data-readonly-slot="relation_notice">${m.stale ? '<p class="life-warning">暂时未能刷新，显示上次读取的关系。</p>' : global.PsychViz.state(m.incoming)}
        ${!contacts.length ? '<div class="relation-empty-guide"><strong>这段会话还没有人物记录</strong><p>QQ 私聊与网页聊天分别记录。若想查看与 QQ 联系人的关系，请选择上方对应的 QQ 私聊；尚未出现的联系人需要先在已有会话中产生记录。</p></div>' : '<p class="viz-muted">金色连线表示角色与对象的已有互动；绿色箭头表示记录中的人物关系陈述。有过交谈不等于已成为朋友。</p>'}
      </div>
      <div class="relation-workspace ${contacts.length ? '' : 'is-empty'}"><section>
        <div class="relation-tools"><button type="button" data-relation-action="in" aria-label="放大关系图">＋</button><button type="button" data-relation-action="out" aria-label="缩小关系图">−</button><button type="button" data-relation-action="fit">适应视图</button><button type="button" data-relation-action="reset">重置</button></div>
        <svg id="relationGraphCanvas" viewBox="0 0 900 540" tabindex="0" role="group" aria-label="角色与人物的关系网络"><defs><marker id="relationArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10" fill="#83966f"/></marker></defs><g data-graph-world></g></svg>
        <div data-readonly-slot="relation_counts" class="relation-legend"><span>${contacts.length} 位人物 · ${g.edges.length} 条关联</span><span>虚线：待核实或有争议</span>${g.total > state.limit ? '<button type="button" class="viz-button" data-relation-action="more">继续加载人物</button>' : ''}${!g.nodes.length && contacts.length ? '<p class="life-empty">没有符合筛选的人物，试试其他昵称或清空筛选。</p>' : ''}</div>
      </section><aside class="relation-people" data-readonly-slot="relation_people">
        ${m.people.filter(p => !state.query || name(p).toLowerCase().includes(state.query.toLowerCase())).map(p => `<article class="${p.person_id === state.selected ? 'is-selected' : ''}"><span class="life-eyebrow">${p.direct_interaction === true ? '已有交谈' : '记录中提及的人物'}</span><button type="button" class="life-link" data-psych-detail="relation-person" data-detail-id="${esc(p.person_id)}">${esc(name(p))}</button><p>${p.relationship ? `与${esc(self ? name(self) : '角色')}的互动关系` : '尚未形成关系判断'}</p>${relationshipBars(p.relationship)}<small>${p.relationship?.interactions == null ? '互动次数尚未记录' : `已记录 ${esc(p.relationship.interactions)} 次互动`}</small></article>`).join('') || (contacts.length ? '<p class="life-empty">尚无符合筛选的人物详情；可点选图中人物。</p>' : '')}
      </aside></div><div data-readonly-slot="relation_source">${global.PsychViz.provenance(m.env, 'socialGraph', 'topology')}<p class="viz-muted">位置与距离仅用于排版，不表示亲疏。关系判断随真实互动与证据记录变化。</p></div>` }];
  }
  function relationshipBars(r) {
    return ['trust', 'familiarity', 'affiliation'].map((f, i) => { const n = global.PsychViz.number(r?.[f]), valid = n !== null && n >= 0 && n <= 1; return `<div class="relation-meter"><span>${['信任', '熟悉', '亲近'][i]}</span><i>${valid ? `<b style="width:${n * 100}%"></b>` : ''}</i><span>${valid ? n.toFixed(2) : '待观察'}</span></div>`; }).join('');
  }
  function position(n, i) { if (!positions.has(n.id)) { const a = i * 2.39996, radius = 90 + Math.sqrt(i) * 60; positions.set(n.id, n.entity_type === 'agent_self' ? { x: 450, y: 270 } : { x: 450 + Math.cos(a) * radius, y: 270 + Math.sin(a) * radius }); } return positions.get(n.id); }
  function afterRender(root) {
    const svg = root.querySelector('#relationGraphCanvas'); if (!svg || !latest) return;
    const contacts = latest.nodes.filter(n => n.entity_type !== 'agent_self');
    root.querySelector('.relation-workspace')?.classList.toggle('is-empty', !contacts.length);
    const scopeSelect = root.querySelector('#inputSocialScope');
    if (scopeSelect) {
      const options = arr(latest.data.scope_options).map(o => `<option value="${esc(o.value)}">${esc(o.label)}</option>`).join('');
      if (options && scopeSelect.innerHTML !== options) scopeSelect.innerHTML = options;
      scopeSelect.value = latest.data.scope;
    }
    const select = root.querySelector('#relationStatus');
    if (select) {
      const statuses = [...new Set(latest.edges.map(e => e.status).filter(Boolean))];
      const html = '<option value="*">全部状态</option>' + statuses.map(s => `<option value="${esc(s)}">${esc(global.DisplayText.label(s))}</option>`).join('');
      if (select.innerHTML !== html) select.innerHTML = html;
      if (!statuses.includes(state.status)) state.status = '*';
      select.value = state.status;
    }
    if (viewport.svg !== svg) rendered = '';
    viewport.attach(svg);
    const g = graph(latest), fp = JSON.stringify([g, state.selected, latest.people]);
    if (fp === rendered) return;
    const firstDraw = !rendered;
    const focused = document.activeElement?.dataset?.detailId;
    g.nodes.forEach(position);
    const paths = g.edges.map((e, i) => {
      const a = positions.get(e.source), b = positions.get(e.target);
      const dx = b.x - a.x, dy = b.y - a.y, length = Math.hypot(dx, dy) || 1;
      const x = b.x - dx / length * 24, y = b.y - dy / length * 24, bend = 20 + (i % 3) * 12;
      const cx = (a.x + x) / 2 - dy / length * bend, cy = (a.y + y) / 2 + dx / length * bend;
      const dyad = ['dyad', 'interaction'].includes(e.kind), title = global.DisplayText.label(e.label || e.relation_type);
      return `<g class="relation-edge ${dyad ? 'dyad' : ''} ${e.status === 'retracted' ? 'retracted' : ['unverified', 'disputed'].includes(e.status) || e.polarity === 'counter' ? 'uncertain' : ''}" tabindex="0" role="button" data-psych-detail="relation-edge" data-detail-id="${esc(e.ui_key)}" aria-label="${esc(title)}，查看依据"><title>${esc(title)}</title><path class="relation-edge-hit" d="M${a.x} ${a.y}Q${cx} ${cy} ${x} ${y}"/><path class="relation-edge-line" ${dyad ? '' : 'marker-end="url(#relationArrow)"'} d="M${a.x} ${a.y}Q${cx} ${cy} ${x} ${y}"/><text class="relation-edge-label" x="${cx}" y="${cy}" text-anchor="middle">${esc(title)}</text></g>`;
    }).join('');
    svg.querySelector('[data-graph-world]').innerHTML = paths + g.nodes.map(n => {
      const p = position(n), person = latest.people.find(x => x.person_id === n.id), title = name(person || n);
      return `<g class="relation-node ${n.entity_type === 'agent_self' ? 'agent' : ''} ${state.selected === n.id ? 'is-selected' : ''}" transform="translate(${p.x} ${p.y})" tabindex="0" role="button" data-psych-detail="relation-person" data-detail-id="${esc(n.id)}" aria-label="${esc(title)}，查看人物"><circle r="22"/><text text-anchor="middle" y="5">${esc(title.slice(0, 1))}</text><text class="relation-node-label" text-anchor="middle" y="42">${esc(title.slice(0, 22))}</text></g>`;
    }).join('');
    rendered = fp;
    if (firstDraw && g.nodes.length > 1) viewport.fit(g.nodes.map(position));
    else viewport.apply();
    if (focused) [...svg.querySelectorAll('[data-detail-id]')].find(el => el.dataset.detailId === focused)?.focus({ preventScroll: true });
  }
  function detail(kind, id, env) {
    if (!kind.startsWith('relation-')) return null;
    const m = prepare(env), base = { id, envelope: m.env, field: 'topology', updated_at: null, description: m.stale ? 'STALE：来自上次同范围快照。' : '严格使用当前范围的身份依据与关系陈述；不从昵称相同或共同出现推断相识。' };
    if (kind === 'relation-edge') {
      const e = m.edges.find(x => x.ui_key === id); if (!e) return null;
      if (['dyad', 'interaction'].includes(e.kind)) {
        const r = e.relationship, person = m.people.find(p => p.person_id === e.target), self = m.nodes.find(n => n.id === e.source);
        return { ...base, title: `${name(self)}与${name(person)}`, updated_at: r?.updated_at,
          description: r ? '这是角色在这段会话中积累的关系判断，不代表对方对角色的评价。' : '已记录直接交谈，尚未形成信任或亲近判断。',
          fields: [{ label: '会话', value: global.DisplayText.scope(m.data.scope) }, { label: '信任', value: r?.trust }, { label: '熟悉', value: r?.familiarity }, { label: '亲近', value: r?.affiliation }, { label: '互动次数', value: r?.interactions }],
          evidence: r?.belief_provenance || [], history: r?.trajectory || [], raw: e.raw };
      }
      return { ...base, title: '关系陈述与证据', updated_at: e.recorded_time || e.updated_at || null, fields: [{ label: '陈述主体', value: name(m.nodes.find(n => n.id === e.source)) }, { label: '陈述对象', value: name(m.nodes.find(n => n.id === e.target)) }, { label: '关系类型', value: global.DisplayText.label(e.relation_type || e.label) }, { label: '核验状态', value: label(e.status) }, { label: '知识来源', value: label(e.knowledge_type) }, { label: '置信度', value: e.confidence }, { label: '会话', value: global.DisplayText.scope(e.scope_id || m.data.scope) }], evidence: e.evidence, raw: e.raw || e };
    }
    const p = m.people.find(x => x.person_id === id), node = m.nodes.find(n => n.id === id); if (!p && !node) return null;
    if (node?.entity_type === 'agent_self') return { ...base, title: name(node), description: '当前角色。金色连线表示与联系人的已有互动；绿色箭头表示记录中的人物关系陈述。', raw: node.raw };
    return { ...base, title: name(p || node), fields: [{ label: '人物标识', value: id }, { label: '范围', value: m.data.scope }, { label: '身份状态', value: p?.identity_status }, { label: '身份不确定度', value: p?.uncertainty }, { label: '有关联陈述', value: m.edges.filter(e => e.source === id || e.target === id).length }], evidence: [...arr(p?.identity_evidence), ...arr(p?.relationship?.belief_provenance)], history: p?.relationship?.trajectory || m.edges.filter(e => e.source === id || e.target === id), raw: { person: p, node, memberships: arr(m.data.topology?.memberships).filter(x => x.person_id === id) } };
  }
  function handleChange(el) { if (el.id === 'relationSearch') { state.query = el.value; return true; } if (el.id === 'relationStatus') { state.status = el.value; return true; } return false; }
  function handleClick(el) { const a = el.closest('[data-relation-action]')?.dataset.relationAction; if (!a) return false; if (a === 'in') viewport.zoom(1.2); if (a === 'out') viewport.zoom(1 / 1.2); if (a === 'fit') viewport.fit(graph(latest).nodes.map(position)); if (a === 'reset') viewport.reset(); if (a === 'more') state.limit += 100; return true; }
  global.RelationView = { cards, detail, afterRender, handleClick, handleChange, select: id => { if (state) state.selected = id; }, unmount: () => viewport.detach(), suppressClick: () => Date.now() < viewport.suppressUntil };
})(window);
