/* Trace projection of the existing ModelAdapter. No simulated execution. */
(function (global) {
  'use strict';
  const V = global.DevViz, { esc, arr, num, good, time, text, badge, detail, empty, fields, meter } = V;
  const names = { memory: '记忆检索', reasoner: 'API-PMM · 在线推理', affect: '情绪与心境', relationship: '关系评价', neural: 'Learned-PMM · 动力学', expressive_drive: '表达欲', decision: '决策与仲裁', negotiation: 'B · 方案协商', policy: '行动选择', expression: '表达规划', long_term: '长期更新提案', input: '输入事件', receipt: '提交回执', delivery: '实际表达' };
  let context = '', query = '', scope = '*', selected = '', cursor = '', latest, page;
  const key = t => String(t.turn_id ?? t.event_id ?? JSON.stringify([t.timestamp, t.scope]));
  const traces = env => good(env.decisions) ? arr(env.decisions.data?.traces) : [];
  function prepare(env, ctx, nav) {
    const next = `${ctx.personaId}:${ctx.source}:${ctx.scope}:${ctx.epoch}`;
    if (next !== context || page !== nav) { context = next; page = nav; query = ''; scope = '*'; selected = ''; cursor = ''; }
    latest = env;
    const list = traces(env).filter(t => (scope === '*' || t.scope === scope) && (!query || [t.turn_id, t.event_id, t.text].some(v => String(v || '').toLowerCase().includes(query.toLowerCase()))));
    if (!list.some(t => key(t) === selected)) { selected = list[0] ? key(list[0]) : ''; cursor = ''; }
    return { list, trace: list.find(t => key(t) === selected) };
  }
  function observed(n) {
    if (!n) return '未返回';
    if (n.status === 'failed') return '尝试失败';
    if (n.payload?.evaluation_use?.last_attempt === 'failed') return '补充评价失败';
    return n.executed === true ? '已参与' : n.executed === false ? '未参与' : '参与状态未知';
  }
  function evaluationLabel(use) {
    if (!use) return '';
    const label = global.DisplayText.state(use.source || 'unrecorded');
    return Number.isInteger(use.known_dimensions) ? label + ' · 有依据的维度 ' + use.known_dimensions + ' 项' : label;
  }
  function roleCoverage(t) {
    if (!t) return '';
    const stages = arr(t.role_retrieval), retrieval = stages[stages.length - 1], check = t.role_consistency || {}, a = t.components?.reasoner?.payload || {};
    const labels = { passed: '已核对本轮相关资料', required: '等待核对', not_required: '本轮未触发资料核对', not_run: '未执行', not_requested: '未记录检查需求', unavailable: '检查未完成', unresolved: '疑点尚未解决', repair_required: '发现冲突，需修复表达', reviewed_without_matching_facts: '已检查表达，未找到匹配资料' };
    return `<article class="wb-role-coverage"><h4>人设资料与表达一致性</h4>${fields([['本轮检索', retrieval ? retrieval.status === 'available' ? `返回 ${arr(retrieval.entry_ids).length} 条相关资料` : retrieval.status === 'not_needed' ? '无额外资料需求' : '未找到相关资料' : '旧记录未提供'], ['发送前核对', labels[check.status] || '旧记录未提供']])}${retrieval?.limited || check.limited ? '<p>本次检索达到资料预算，仅核对已返回的资料。</p>' : ''}${a.reappraisal_failure ? '<p>补充评价失败；已保留此前有效评价，其依据范围未自动扩大。</p>' : ''}${arr(a.optional_field_warnings).length ? '<p>部分可选评价未通过来源检查，已单独舍弃。</p>' : ''}<p class="wb-caption">检查覆盖与实际送达分别记录；发送成功不等于所有人设事实已经核实。</p>${detail('pmm-role', selected, '查看资料传递与核对范围 ↗')}</article>`;
  }
  function order(t) { return arr(t?.execution_order).filter(k => t.components?.[k]); }
  function node(t, id) { return id === 'long_term' ? t?.long_term : t?.components?.[id]; }
  function matchingTurn(env, t) { return t ? arr(env.experiences?.data?.visual_items).find(r => String(r.id) === String(t.turn_id)) : null; }
  function nodeCard(t, id) {
    const n = node(t, id), p = n?.payload || {}, label = names[id] || id;
    return `<button type="button" class="wb-flow-node ${n?.executed === true ? 'participated' : 'dormant'} ${cursor === id ? 'selected' : ''}" data-pmm-step="${esc(id)}"><span class="wb-eyebrow">${esc(observed(n))}</span><strong>${esc(label)}</strong><span>${esc(global.DisplayText.state(n?.status))}</span><small>${n?.elapsed_ms == null ? '耗时未提供' : `${esc(n.elapsed_ms)} ms`}</small>${id === 'reasoner' && p.evaluation_use ? `<span>${esc(evaluationLabel(p.evaluation_use))}</span>` : ''}${id === 'negotiation' && Number.isInteger(n?.attempts) ? `<span>本轮协商调用 ${esc(n.attempts)} 次</span>` : ''}${id === 'neural' ? `<span>校准：${esc(global.DisplayText.state(p.calibration))}</span><small>正式资格：${p.formal_eligible === true ? '有' : p.formal_eligible === false ? '无' : '未知'}</small>` : ''}</button>`;
  }
  function probabilities(t) {
    const reasoner = t?.components?.reasoner, use = reasoner?.payload?.evaluation_use;
    const a = reasoner?.status === 'ok' && reasoner.executed !== false ? reasoner.payload?.action_probabilities : null;
    const aLabel = use?.source === 'retained_previous_valid_evidence' ? 'A 上次有效结果' : 'A 在线行动倾向';
    const b = t?.components?.neural?.payload?.action_probabilities;
    const actions = [...new Set([...Object.keys(a || {}), ...Object.keys(b || {})])];
    return actions.length ? `<div class="wb-probabilities"><header><span>候选行动</span><span>${esc(aLabel)}</span><span>Learned-PMM</span></header>${actions.map(k => `<div><strong>${esc(k)}</strong><span>${meter(a?.[k])}</span><span>${meter(b?.[k])}</span></div>`).join('')}</div>` : empty('此回合未返回行动概率，不补画默认分布');
  }
  function dependencies(t) {
    const pairs = arr(t?.dependencies).filter(pair => Array.isArray(pair) && pair.length === 2 && t?.components?.[pair[0]] && t?.components?.[pair[1]]);
    if (!pairs.length) return empty('未提供可绘制的组件依赖，不生成推测连线');
    const keys = [...new Set(pairs.flat())], points = new Map(keys.map((k, i) => [k, { x: 115 + (i % 4) * 220, y: 80 + Math.floor(i / 4) * 160 }]));
    const height = Math.ceil(keys.length / 4) * 160;
    return `<svg class="wb-dependency-map" viewBox="0 0 900 ${height}" role="group" aria-label="后端明确返回的组件依赖，箭头不表示执行完成"><defs><marker id="wbDependencyArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10" fill="#a1b68c"/></marker></defs>${pairs.map(([a, b]) => { const p = points.get(a), q = points.get(b), dx = q.x - p.x, dy = q.y - p.y, length = Math.hypot(dx, dy) || 1; return `<path d="M${p.x} ${p.y}L${q.x - dx / length * 68} ${q.y - dy / length * 30}" fill="none" stroke="#b6c8a8" stroke-width="1.5" marker-end="url(#wbDependencyArrow)"><title>${esc(names[a] || a)} → ${esc(names[b] || b)}</title></path>`; }).join('')}${keys.map(k => { const p = points.get(k), n = t.components[k]; return `<g transform="translate(${p.x} ${p.y})" role="button" tabindex="0" data-pmm-step="${esc(k)}" class="wb-dependency-node ${n.executed === true ? 'participated' : 'dormant'} ${cursor === k ? 'selected' : ''}" aria-label="${esc(names[k] || k)}，${esc(observed(n))}"><rect x="-90" y="-28" width="180" height="56" rx="12"/><text text-anchor="middle" y="-3">${esc(names[k] || k)}</text><text text-anchor="middle" y="16" class="wb-dependency-caption">${esc(observed(n))}</text></g>`; }).join('')}</svg><p class="wb-caption">箭头表示已记录的处理依赖；位置不代表耗时或执行速度。</p>`;
  }
  function componentStatus(env) {
    const raw = env.decisions?.data?.observability || {}, api = raw.api_status?.connections?.A, learned = raw.learned_status, nodes = env.connections?.data?.nodes || {};
    return V.cards('developer_pmm_status', 'decisions', '组件配置、校准与正式发布门禁', `<div data-readonly-slot="pmm_status_visual"><div class="wb-dual-track"><section><h4>API-PMM · 连接观察</h4>${badge(nodes.api_pmm?.status)}${fields([['配置模型', api?.model], ['连接记录', api?.status], ['已配置', typeof api?.configured === 'boolean' ? api.configured : null]])}${detail('pmm-status', 'api', '完整状态与来源 ↗')}</section><section><h4>Learned-PMM · 数值模型</h4>${badge(nodes.learned_pmm?.status)}${fields([['校准', learned?.calibration], ['发布门禁', learned?.release_gate], ['正式提交资格', typeof learned?.long_term_commit_ready === 'boolean' ? learned.long_term_commit_ready : null], ['训练样本数', learned?.samples?.count]])}${detail('pmm-status', 'learned', '完整状态与来源 ↗')}</section></div><p class="wb-caption">以上为状态接口观测；下方所选回合的参与情况按实际组件记录独立显示。</p></div>`);
  }
  function options(list) { return list.length ? list.map(t => `<option value="${esc(key(t))}" ${key(t) === selected ? 'selected' : ''}>${esc(time(t.timestamp))} · ${esc(String(t.text || t.turn_id || '未命名回合').slice(0, 55))}</option>`).join('') : '<option value="">暂无匹配回合</option>'; }
  function cards(env, ctx, nav) {
    const { list, trace: t } = prepare(env, ctx, nav), d = t?.components?.decision?.payload || {}, r = matchingTurn(env, t), seq = order(t);
    const controls = `<div class="wb-toolbar"><label>查找回合<input type="search" id="pmmTraceSearch" value="${esc(query)}" placeholder="回合标识或事件原文"/></label><label>范围<select id="pmmTraceScope"><option value="*">全部已返回范围</option>${[...new Set(traces(env).map(x => x.scope).filter(Boolean))].map(s => `<option value="${esc(s)}" ${scope === s ? 'selected' : ''}>${esc(global.DisplayText.scope(s))}</option>`).join('')}</select></label><label class="wb-flex">选择记录<select id="pmmTraceSelect">${options(list)}</select></label></div>`;
    const general = env.connections?.data?.nodes?.general_llm;
    const graph = `<div class="wb-external"><span class="wb-eyebrow">PMM 外部 · General LLM</span><strong>语言理解 / 语言输出</strong>${badge(general?.status)}<small>连接状态不表示所选回合已执行；具体语言调用仅以该回合记录为准。</small></div><div class="wb-input">${detail('pmm-input', selected, '查看事件详情 ↗')}<p>${esc(t?.text || '尚无事件原文')}</p></div><div class="wb-dual-track"><section><h4>API-PMM</h4>${nodeCard(t, 'reasoner')}</section><section><h4>Learned-PMM</h4>${nodeCard(t, 'neural')}</section></div><p class="wb-caption">组件分栏不表示同时执行；执行顺序与依赖来自该回合的实际记录。</p><div class="wb-support-track">${['memory', 'affect', 'relationship', 'expressive_drive', ...(t?.components?.negotiation ? ['negotiation'] : [])].map(k => nodeCard(t, k)).join('')}</div><div class="wb-decision-row">${nodeCard(t, 'decision')}<article class="wb-arbitration"><h4>分歧与最终选择</h4>${fields([['分歧', typeof d.disagreement === 'boolean' ? (d.disagreement ? '存在' : '无') : null], ['A 在线首选', t?.components?.reasoner?.status === 'ok' && t.components.reasoner.executed !== false ? d.api_preference : null], ['Learned 首选', d.neural_preference], ['采纳动作', d.official_action], ['仲裁规则', d.arbitration || d.rule]])}</article></div><div class="wb-outcomes"><article><h4>事务提交</h4>${badge(t?.commit_receipt ? 'recorded' : 'unknown', t?.commit_receipt ? '有提交记录' : '未返回回执')}${fields([['类型', t?.commit_receipt?.kind], ['长期特质写入', t?.commit_receipt?.stable_trait_updates]])}${detail('pmm-receipt', selected, '查看提交内容 ↗')}</article><article><h4>实际表达</h4>${fields([['送达状态', r?.delivery], ['已确认数', r?.actual_confirmed], ['错误', r?.error]])}${detail('pmm-delivery', selected, r ? '查看同回合表达记录 ↗' : '暂无同回合表达记录')}</article>${nodeCard(t, 'long_term')}</div>`;
    const active = cursor ? node(t, cursor) : null;
    const replay = `<div class="wb-replay-controls"><button type="button" data-pmm-action="previous">上一步</button><button type="button" data-pmm-action="next">下一步</button><span>记录回放，不触发重新执行</span></div><div class="wb-replay-order">${seq.map((k, i) => `<button type="button" data-pmm-step="${esc(k)}" class="${cursor === k ? 'selected' : ''}">${i + 1} · ${esc(names[k] || k)}</button>`).join('') || empty('此回合未提供明确执行顺序；可点选上方组件查看')}</div><div class="wb-component-inspector"><h4>${esc(names[cursor] || cursor || '点选一个组件')}</h4>${active ? fields([['参与', observed(active)], ['状态', active.status], ['评价依据', evaluationLabel(active.payload?.evaluation_use) || null], ['执行模式', active.execution], ['耗时（ms）', active.elapsed_ms], ['作用目标', active.applied_to], ['发布门禁', active.payload?.release_gate]]) + detail('pmm-component', JSON.stringify([selected, cursor]), '证据与用量详情 ↗') : empty('未选择组件或该组件未返回记录')}</div>`;
    const durationNodes = Object.entries(t?.components || {}).filter(([, n]) => num(n?.elapsed_ms) !== null && num(n.elapsed_ms) >= 0), max = Math.max(1, ...durationNodes.map(([, n]) => num(n.elapsed_ms)));
    const durations = `<div class="wb-duration-chart">${durationNodes.map(([k, n]) => `<div><span>${esc(names[k] || k)}</span>${meter(n.elapsed_ms, max)}<small>ms</small></div>`).join('') || empty('此回合没有组件耗时')}</div><p class="wb-caption">各项独立耗时，不能从长度推断并发起止或将其总和当作总耗时。</p>`;
    const result = [V.cards(`developer_${nav}_flow`, 'decisions', nav === 'session_trace' ? '逐轮追踪 · 从输入到回执' : 'PMM · 组件参与与决策', `${controls}<div data-readonly-slot="pmm_visual_flow">${V.state(env.decisions)}${graph}${roleCoverage(t)}${V.source(env.decisions, 'decisions', 'traces')}</div>${nav === 'pmm_sys' ? '<div class="wb-operation"><button type="button" class="viz-button" id="btnTestPmmConn">主动探测 API-PMM</button><span id="connProbeFeedback" role="status"></span></div>' : ''}`), V.cards(`developer_${nav}_replay`, 'decisions', '组件记录回放', `<div data-readonly-slot="pmm_visual_replay">${replay}</div>`), V.cards(`developer_${nav}_comparison`, 'decisions', '行动分布与耗时', `<div data-readonly-slot="pmm_visual_comparison">${probabilities(t)}${durations}<p class="wb-caption">Learned 的输出与正式采纳资格分开；概率值不代表已经训练验证。</p></div>` )];
    result.push(global.ReasoningView.card(t?.turn_id || '', ctx));
    if (nav === 'behavior_event') return behaviorCards(env, ctx);
    result.push(V.cards(`developer_${nav}_dependencies`, 'decisions', '明确返回的组件依赖', `<div data-readonly-slot="pmm_dependencies">${dependencies(t)}</div>`));
    return nav === 'pmm_sys' ? [componentStatus(env), ...result] : result;
  }
  function behaviorCards(env) {
    const rows = good(env.experiences) ? arr(env.experiences.data?.visual_items).filter(r => !query || [r.id, r.text, r.strategy, r.delivery].some(v => String(v || '').toLowerCase().includes(query.toLowerCase()))) : [];
    return [V.cards('developer_behavior_visual', 'experiences', '行为与事件 · 规划不等于送达', `<div class="wb-toolbar"><label class="wb-flex">查找记录<input type="search" id="pmmTraceSearch" value="${esc(query)}" placeholder="原文、回合、策略或送达状态"/></label></div><div data-readonly-slot="behavior_visual"><p class="wb-caption">只展示当前接口返回的 ${rows.length} 条匹配记录。</p><ol class="wb-event-axis">${rows.map(r => `<li><time>${esc(time(r.at))}</time><article><h4>${esc(r.text || '原文未提供')}</h4><div class="wb-behavior-path"><div><span>评价条件</span><strong>${arr(r.usage).length} 项已返回</strong></div><div><span>行动选择</span><strong>${esc(global.DisplayText.label(r.strategy))}</strong></div><div><span>表达规划</span><strong>${r.raw?.planned_bubbles == null ? '未知' : `${esc(r.raw.planned_bubbles)} 条`}</strong></div><div><span>确认结果</span><strong>${esc(global.DisplayText.state(r.delivery))}</strong><small>${r.actual_confirmed == null ? '确认数未知' : `${esc(r.actual_confirmed)} 条`}</small></div></div>${detail('pmm-behavior', r.id, '条件评分、校验与回执详情 ↗')}</article></li>`).join('') || empty()}${V.state(env.experiences)}</ol>${V.source(env.experiences, 'experiences', 'evaluated_turns')}</div>`)];
  }
  function resolve(kind, id, env) {
    if (!kind.startsWith('pmm-')) return null;
    if (kind === 'pmm-status') {
      const obs = env.decisions?.data?.observability;
      const envelope = id === 'api' ? obs?.api_envelope : obs?.learned_envelope;
      return { title: id === 'api' ? 'API-PMM 状态' : 'Learned-PMM 状态', id, envelope, updated_at: null,
        description: '配置状态、发布门禁与某回合是否实际执行是不同记录；这里只展示原状态接口。', raw: V.redact(envelope?.data) };
    }
    let tid = id, component;
    if (kind === 'pmm-component') { try { [tid, component] = JSON.parse(id); } catch (_) { return null; } }
    const t = traces(env).find(t => key(t) === tid), base = { id: tid, envelope: env.decisions, field: 'traces', updated_at: t?.timestamp ?? null, description: '数据来自当前角色的真实记录。未执行、缺失、未校准和未送达分别保留，不用显示默认值补成成功。' };
    if (kind === 'pmm-behavior') { const r = arr(env.experiences?.data?.visual_items).find(x => String(x.id) === id); return r ? { ...base, title: '行为与送达审计', envelope: env.experiences, field: 'evaluated_turns', updated_at: r.at, fields: [{ label: '策略', value: r.strategy }, { label: '回执', value: r.delivery }, { label: '确认数', value: r.actual_confirmed }], evidence: r.usage, raw: V.redact(r.raw) } : null; }
    if (!t) return null;
    const n = component ? node(t, component) : null;
    const raw = kind === 'pmm-role' ? { role_retrieval: t.role_retrieval, role_consistency: t.role_consistency, persona_version_id: t.persona_version_id } : kind === 'pmm-input' ? t : kind === 'pmm-receipt' ? t.commit_receipt : kind === 'pmm-delivery' ? matchingTurn(env, t)?.raw : n;
    return { ...base, title: names[component] || ({ 'pmm-role': '人设资料传递与核对范围', 'pmm-input': '输入与依赖记录', 'pmm-receipt': '事务回执', 'pmm-delivery': '同回合表达记录' }[kind]),
      fields: [{ label: '回合', value: t.turn_id }, { label: '事件', value: t.event_id }, { label: '范围', value: t.scope }, { label: '参与', value: n ? observed(n) : undefined }, { label: 'Token / usage（仅原字段）', value: text(n?.payload?.usage ?? n?.usage ?? n?.payload?.tokens) }], evidence: n?.evidence_refs || n?.payload?.evidence || n?.payload?.evidence_quote, raw: V.redact(raw), derivation: component ? '展示原组件字段；不根据配置推断执行。' : '事务回执不等于外部消息送达；依赖取自 trace.dependencies。' };
  }
  function handleChange(el) { if (el.id === 'pmmTraceSearch') { query = el.value; return true; } if (el.id === 'pmmTraceScope') { scope = el.value; selected = ''; return true; } if (el.id === 'pmmTraceSelect') { selected = el.value; cursor = ''; global.PsychViz.close(); return true; } return false; }
  function handleClick(el) { const step = el.closest('[data-pmm-step]'); if (step) { cursor = step.dataset.pmmStep; return true; } const act = el.closest('[data-pmm-action]')?.dataset.pmmAction; if (!act) return false; const t = traces(latest).find(t => key(t) === selected), seq = order(t), i = seq.indexOf(cursor); if (seq.length) cursor = seq[Math.max(0, Math.min(seq.length - 1, i + (act === 'next' ? 1 : -1)))]; return true; }
  function syncControls(root) { const sel = root.querySelector('#pmmTraceSelect'); if (sel && latest) { const list = traces(latest).filter(t => (scope === '*' || t.scope === scope) && (!query || [t.turn_id, t.event_id, t.text].some(v => String(v || '').toLowerCase().includes(query.toLowerCase())))); const html = options(list); if (sel.innerHTML !== html) sel.innerHTML = html; sel.value = selected; } }
  global.PmmFlow = { cards, detail: resolve, handleChange, handleClick, syncControls };
})(window);
