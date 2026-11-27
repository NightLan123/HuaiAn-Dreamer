/* Stage 4: page-specific projections around the existing guarded forms. */
(function (global) {
  'use strict';
  const V = global.DevViz, { esc, arr, num, good, time, text, badge, detail, empty, fields, meter } = V;
  const pages = ['role_info', 'persona_set', 'archives', 'model_cfg', 'pmm_sys', 'qq_conn', 'run_state', 'data_import', 'distill_task', 'learn_record', 'version_mgmt', 'behavior_event', 'session_trace', 'logs_monitor', 'api_tools', 'settings'];
  const titles = { role_info: ['角色资料 · 当前主体', '角色目录 · 独立档案'], persona_set: ['正式人格设定 · 核对后提交', '长期倾向 · 当前观测'], archives: ['来源目录与证据', '边界档案'], model_cfg: ['General LLM · 外部语言模型'], qq_conn: ['QQ / OneBot · 连接与路由'], run_state: ['运行状态 · 七个节点', '后台活动任务'], data_import: ['资料导入 · 预览与授权'], distill_task: ['学习任务 · 队列与处理'], learn_record: ['学习记录 · 活动时间线', '候选复核与对象观察'], version_mgmt: ['人格版本 · 检查点与恢复'], logs_monitor: ['请求日志 · 当前浏览器'], api_tools: ['接口工具 · 手动操作区'], settings: ['刷新与显示偏好', '布局与模式'] };
  let context = '', page = '', state = {}, latest, ctx = {}, density = 'comfortable';
  try { density = localStorage.getItem('huaian.ui.panel-density') === 'compact' ? 'compact' : 'comfortable'; } catch (_) {}
  const data = (env, domain) => good(env[domain]) ? env[domain].data || {} : {};
  const recordId = (r, i) => String(r?.id ?? r?.feature_id ?? JSON.stringify([r?.created_at, r?.kind, i]));
  function prepare(nav, env, contextData) {
    const next = `${contextData.personaId}:${contextData.source}:${contextData.scope}:${contextData.epoch}`;
    if (next !== context || page !== nav) { context = next; page = nav; state = { query: '', group: '*', status: '*', limit: 18, feature: '', estimate: '', revA: '', revB: '', logStatus: '*', logCode: '*', logBin: '*' }; }
    latest = env; ctx = contextData;
  }
  function replaceSlot(card, slot, html) {
    const div = document.createElement('div'); div.innerHTML = card.body;
    const target = div.querySelector(`[data-readonly-slot="${slot}"]`);
    if (target) { target.innerHTML = html; target.removeAttribute('style'); target.classList.add('wb-slot'); }
    card.body = div.innerHTML;
  }
  function removeSlot(card, slot) { const d = document.createElement('div'); d.innerHTML = card.body; d.querySelector(`[data-readonly-slot="${slot}"]`)?.remove(); card.body = d.innerHTML; }
  const toolbar = (placeholder, extras = '') => `<div class="wb-toolbar"><label class="wb-flex">检索<input type="search" id="workbenchSearch" value="${esc(state.query)}" placeholder="${esc(placeholder)}"/></label>${extras}</div>`;
  const includes = (...values) => !state.query || values.some(v => String(v ?? '').toLowerCase().includes(state.query.toLowerCase()));
  const more = (count) => count > state.limit ? '<button type="button" class="viz-button" data-wb-action="more">继续展开</button>' : '';
  const provenance = (domain, field) => V.source(latest[domain], domain, field);
  function role(env, cards) {
    const p = data(env, 'characterProfile'), catalog = arr(p.personas_catalog);
    replaceSlot(cards[0], 'role_header', `${V.state(env.characterProfile)}<div class="wb-role-hero"><span class="wb-monogram">${esc((p.name || '？').slice(0, 1))}</span><div><span class="wb-eyebrow">当前激活主体</span><h3>${esc(p.name || '身份未提供')}</h3><p>${esc(p.summary || '尚未提供介绍')}</p></div>${detail('wb-profile', 'current', '档案来源 ↗')}</div>${fields([['资料修订号', p.revision], ['特质版本', p.trait_version], ['业务更新时间', time(env.characterProfile?.updated_at)]])}`);
    replaceSlot(cards[1], 'role_catalog_list', `<div class="wb-role-grid">${catalog.map(r => `<article class="${r.id === p.id ? 'active' : ''}"><span class="wb-monogram">${esc((r.name || '？').slice(0, 1))}</span><h4>${esc(r.name || '未命名主体')}</h4>${r.id === p.id ? badge('healthy', '当前激活') : `<button type="button" class="viz-button" data-switch-persona="${esc(r.id)}">切换角色</button>`}${detail('wb-role', r.id, '标识与资料 ↗')}</article>`).join('') || empty()}</div>`);
    return cards;
  }
  function constructPreview(env) {
    const rows = arr(data(env, 'personality').editable_constructs), f = rows.find(r => r.id === state.feature) || rows[0];
    const n = num(state.estimate);
    return f ? `<div class="wb-compare"><div><span>当前 · ${esc(f.name_zh || f.id)}</span>${meter(f.estimate)}</div><span aria-hidden="true">→</span><div><span>拟设定值</span>${meter(n)}</div></div><p class="wb-caption">${n === null ? '尚未输入目标值。' : '这里只是本地预览，尚未写入。'}版本 ${esc(data(env, 'personality').version ?? '未知')}；提交仍需原来的版本核对和确认。</p>` : empty('没有可编辑的注册构念');
  }
  function personality(env, cards) {
    const p = data(env, 'personality'), rows = arr(p.editable_constructs), filtered = rows.filter(f => (state.group === '*' || f.group === state.group) && includes(f.id, f.name_zh, f.group));
    const groups = [...new Set(rows.map(f => f.group).filter(Boolean))];
    const primary = V.cards('developer_construct_explorer', 'personality', '构念目录 · 按组检索并选取', `${toolbar('构念名称或标识', `<label>分组<select id="workbenchGroup"><option value="*">全部分组</option>${groups.map(g => `<option value="${esc(g)}" ${state.group === g ? 'selected' : ''}>${esc(g)}</option>`).join('')}</select></label>`)}<div data-readonly-slot="wb_constructs">${V.state(env.personality)}<div class="wb-construct-grid">${filtered.slice(0, state.limit).map(f => `<button type="button" data-wb-feature="${esc(f.id)}" class="${f.id === state.feature ? 'selected' : ''}"><small>${esc(f.group)}</small><strong>${esc(f.name_zh || f.id)}</strong><span>${meter(f.estimate)}</span><small>${esc(global.DisplayText.label(f.source_type || '来源未提供'))}</small></button>`).join('') || empty('没有匹配构念')}</div>${more(filtered.length)}</div><div data-readonly-slot="wb_construct_preview">${constructPreview(env)}</div>`);
    const d = document.createElement('div'); d.innerHTML = cards[0].body;
    const input = d.querySelector('#inputDispositionVal'); if (input) { input.setAttribute('value', state.estimate); input.setAttribute('placeholder', '输入目标值'); }
    const save = d.querySelector('#btnSaveDisposition'); if (save) save.textContent = '核对并提交';
    cards[0].body = d.innerHTML;
    replaceSlot(cards[1], 'dispositions_table', `<div class="wb-dispositions">${arr(p.dispositions).map(f => `<div>${detail('wb-construct', f.id, f.label || f.id)}<span>${meter(f.estimate)}</span><small>${esc(global.DisplayText.label(f.source_type))}</small></div>`).join('') || empty()}</div>`);
    return [primary, ...cards];
  }
  function archives(env, cards) {
    const p = data(env, 'characterProfile'), sources = arr(p.source_records), filtered = sources.filter(r => (state.group === '*' || r.source === state.group) && includes(r.text, r.id, r.speaker, r.source));
    cards[0].body = toolbar('原文、来源或说话人', `<label>来源<select id="workbenchGroup"><option value="*">全部来源</option>${[...new Set(sources.map(r => r.source).filter(Boolean))].map(g => `<option value="${esc(g)}" ${state.group === g ? 'selected' : ''}>${esc(g)}</option>`).join('')}</select></label>`) + cards[0].body;
    replaceSlot(cards[0], 'archives_sources', `${V.state(env.characterProfile)}<div class="wb-source-grid">${filtered.slice(0, state.limit).map((r, i) => `<article><span class="wb-eyebrow">${esc(r.source || '来源未提供')} · ${esc(r.speaker || r.person || '说话人未提供')}</span><blockquote>${esc(r.text || '未提供原文')}</blockquote><footer><time>${esc(time(r.timestamp || r.created_at))}</time>${detail('wb-source', recordId(r, sources.indexOf(r)), '原文与引用链 ↗')}</footer></article>`).join('') || empty()}</div>${more(filtered.length)}${provenance('characterProfile', 'source_records')}`);
    replaceSlot(cards[1], 'archives_boundaries', `<div class="wb-boundaries">${arr(p.boundary_model?.boundaries).map((b, i) => `<article><span class="wb-boundary-mark">◇</span><h4>${esc(b.topic || b.id || '未命名边界')}</h4>${badge(b.status)}<p>来源：${esc(b.origin || '未提供')}</p>${detail('wb-boundary', recordId(b, i), '边界与依据 ↗')}</article>`).join('') || empty('当前未返回边界记录，不代表没有边界')}</div><p class="wb-caption">只呈现现有边界；本页未接入额外写入操作。</p>`);
    return cards;
  }
  function connectionCard(env, key, heading) {
    const n = data(env, 'connections').nodes?.[key];
    const settings = { general_llm: 'model_cfg', api_pmm: 'pmm_sys', qq_channel: 'qq_conn' }[key];
    return `<article class="wb-service"><span class="wb-eyebrow">${esc(heading || '连接状态')}</span><h4>${esc(n?.name || '服务')}</h4>${badge(n?.status)}<p>${esc(global.DisplayText.state(n?.status))}</p>${settings ? `<button type="button" class="viz-button" data-dev-nav="${settings}">设置连接</button>` : ''}${detail('wb-connection', key, '查看连接详情 ↗')}</article>`;
  }
  function connections(nav, env, cards) {
    const conn = data(env, 'connections'), p = data(env, 'characterProfile');
    if (nav === 'model_cfg') replaceSlot(cards[0], 'model_cfg_status', `<div class="wb-model-separation">${connectionCard(env, 'general_llm', '外部语言层')}<span class="wb-architecture-arrow">⇄</span><div class="wb-internal-label"><strong>内部 PMM</strong><p>心理推理与动力学在 PMM 页面独立观察</p><button type="button" class="viz-button" data-dev-nav="pmm_sys">查看 PMM</button></div></div>`);
    if (nav === 'qq_conn') { const q = p.config?.qq || {}; replaceSlot(cards[0], 'qq_conn_status', `<div class="wb-channel-map"><article><span class="wb-eyebrow">外部通道</span><h4>OneBot</h4><p>${esc(q.api_url || '接口地址未提供')}</p>${detail('wb-qq-config', 'route', '路由与白名单详情 ↗')}</article><span class="wb-architecture-arrow">⇄</span>${connectionCard(env, 'qq_channel', '接口状态')}<span class="wb-architecture-arrow">⇄</span><article><h4>角色消息处理</h4><p>回调地址由下方现有操作取得；连接图仅表示配置路径，不表示当前有消息送达。</p></article></div>`); }
    if (nav === 'run_state') {
      replaceSlot(cards[0], 'runstate_matrix', `${V.state(env.connections)}<div class="wb-state-legend">${['healthy', 'reachable', 'running', 'configured', 'unknown', 'unavailable'].map(s => badge(s)).join('')}</div><div class="wb-service-grid">${Object.keys(conn.nodes || {}).map(k => connectionCard(env, k)).join('') || empty()}</div>${provenance('connections', 'nodes')}`);
      replaceSlot(cards[1], 'runstate_jobs', `<p class="wb-caption">${esc(ctx.polling?.summary || '刷新状态未提供')}</p><div class="wb-active-jobs">${arr(conn.active_jobs).map((j, i) => `<article>${badge(j.status)}<strong>${esc(j.kind || '后台任务')}</strong>${detail('wb-active-job', recordId(j, i), '状态与时间 ↗')}</article>`).join('') || empty('未返回活动任务')}</div><p class="wb-caption">后台任务的检查时点和自主整理设置见下方“后台任务与自主候选”。</p><h4 class="wb-section-heading">最近实际请求错误</h4><div class="wb-active-jobs">${arr(ctx.callLog).filter(r => !r.ok && !r.injected).slice(0, 6).map(r => `<article><time>${esc(time(r.at))}</time><span>${esc(global.DisplayText.endpoint(r.endpoint))}</span>${detail('wb-http', logKey(r, arr(ctx.callLog).indexOf(r)), '错误详情 ↗')}</article>`).join('') || empty('当前浏览器未记录实际请求错误')}</div>`);
    }
    return cards;
  }
  function importWizard(cards) {
    const preview = ctx.learningPreview?.preview;
    cards[0].body = `<div data-readonly-slot="wb_import_steps"><ol class="wb-import-steps"><li class="current"><b>1</b><strong>准备原文</strong><span>选择目标与范围</span></li><li class="${preview ? 'recorded' : ''}"><b>2</b><strong>后端预览</strong><span>${preview ? '已取得预览记录' : '等待读取预览'}</span></li><li><b>3</b><strong>明确授权</strong><span>核对内容后自行勾选</span></li><li><b>4</b><strong>创建与回执</strong><span>实际结果显示在操作区</span></li></ol><p class="wb-caption">只输入文字不会创建任务。富文档二进制导入尚未开放。</p></div>` + cards[0].body;
    return cards;
  }
  function taskLane(status) { return ['done', 'completed', 'analysis_complete'].includes(status) ? 'done' : ['failed', 'error', 'cancelled', 'canceled'].includes(status) ? 'failed' : ['paused', 'awaiting_review'].includes(status) ? 'paused' : ['running', 'processing'].includes(status) ? 'running' : 'queued'; }
  function taskBoard(env, cards) {
    const l = data(env, 'learning'), jobs = arr(l.raw_jobs).filter(j => includes(j.title, j.id, j.target, j.scope));
    cards[0].body = toolbar('任务名称、标识或目标') + cards[0].body;
    replaceSlot(cards[0], 'distill_jobs', `${V.state(env.learning)}<div class="wb-kanban">${[['queued', '队列 / 其他待处理'], ['running', '进行中'], ['paused', '暂停 / 待复核'], ['done', '已结束'], ['failed', '失败 / 取消']].map(([lane, title]) => { const rows = jobs.filter(j => taskLane(j.status) === lane); return `<section><header><h4>${title}</h4><span>${rows.length}</span></header>${rows.map(j => { const count = num(j.source_count), cursor = num(j.cursor), progress = num(j.progress) ?? (count > 0 && cursor !== null ? cursor / count * 100 : null); return `<article>${badge(j.status)}<h5>${esc(j.title || j.summary || j.target || '学习任务')}</h5><p>${esc(j.phase || '阶段未提供')}</p><div>${meter(progress, 100)}</div><small>${j.progress == null && progress !== null ? '按已处理游标 / 原文数计算' : '后端进度；未知不填零'}</small>${detail('wb-job', j.id, '来源与任务详情 ↗')}<footer>${!['done', 'failed'].includes(lane) ? `<button type="button" data-job-control="${j.status === 'paused' ? 'resume' : 'pause'}" data-job-id="${esc(j.id)}">${j.status === 'paused' ? '恢复' : '暂停'}</button><button type="button" data-job-control="cancel" data-job-id="${esc(j.id)}">取消</button>` : ''}${j.can_rollback === true ? `<button type="button" data-job-control="rollback" data-job-id="${esc(j.id)}">回滚</button>` : ''}</footer></article>`; }).join('') || '<p class="wb-caption">暂无任务</p>'}</section>`; }).join('')}</div>`);
    return cards;
  }
  function learning(env, cards) {
    const l = data(env, 'learning'), acts = good(l.activities_envelope) ? arr(l.activities_envelope.data) : [], candidates = good(l.candidates_envelope) ? arr(l.candidates_envelope.data) : [];
    const shown = acts.filter(a => (state.status === '*' || a.kind === state.status) && includes(a.kind, a.id, a.payload?.scope, a.payload?.summary));
    cards[0].body = toolbar('类型、范围或记录标识', `<label>事件类型<select id="workbenchStatus"><option value="*">全部类型</option>${[...new Set(acts.map(a => a.kind))].map(s => `<option value="${esc(s)}" ${state.status === s ? 'selected' : ''}>${esc(s)}</option>`).join('')}</select></label>`) + cards[0].body;
    replaceSlot(cards[0], 'learn_record_activities', `${V.state(l.activities_envelope)}<ol class="wb-event-axis">${shown.slice(0, state.limit).map(a => `<li><time>${esc(time(a.created_at))}</time><article><h4>${esc(a.payload?.summary || a.kind || '学习活动')}</h4>${fields([['范围', a.payload?.scope], ['修订前', a.payload?.profile_revision_before], ['修订后', a.payload?.profile_revision_after]])}${detail('wb-activity', a.id, '证据来源与处理详情 ↗')}</article></li>`).join('') || empty()}</ol>${more(shown.length)}`);
    replaceSlot(cards[1], 'learn_record_candidates', `${V.state(l.candidates_envelope)}<div class="wb-candidate-grid">${candidates.map((c, i) => `<article>${badge(c.eligible === true ? 'recorded' : 'unknown', c.eligible === true ? '符合复核条件' : '尚待证据')}<h4>${esc(c.feature_id || '候选')}</h4><ul>${arr(c.reasons).map(r => `<li>${esc(r)}</li>`).join('')}</ul>${detail('wb-candidate', recordId(c, i), '复核条件与精确证据量 ↗')}</article>`).join('') || empty('暂无已返回候选')}</div><h4 class="wb-section-heading">交谈对象的观察状态</h4><div class="wb-object-states">${arr(l.other_status).map((o, i) => `<article><strong>${esc(o.person || '人物未提供')}</strong><p>${esc(o.status || '状态未提供')}</p><small>${esc(o.scope || '范围未提供')}</small>${detail('wb-other', recordId(o, i), '对象观察依据 ↗')}</article>`).join('') || empty()}</div><p class="wb-caption">此处只读复核依据；候选不自动写入正式人格。</p>`);
    cards[1].body += `<div class="wb-operation"><button type="button" class="viz-button" id="btnPreviewTraitReview">重新读取复核结果</button><button type="button" class="viz-button" id="btnPrepareTraitApply">核对晋升操作</button></div><div id="traitReviewConfirmBox" hidden></div><p id="traitReviewFeedback" role="status"></p>`;
    return cards;
  }
  function revisions(env, cards) {
    const rows = arr(data(env, 'personality').revisions);
    if (!rows.some(r => r.id === state.revA)) state.revA = rows[1]?.id || rows[0]?.id || '';
    if (!rows.some(r => r.id === state.revB)) state.revB = rows[0]?.id || '';
    const a = rows.find(r => r.id === state.revA), b = rows.find(r => r.id === state.revB);
    const opts = selected => rows.map(r => `<option value="${esc(r.id)}" ${r.id === selected ? 'selected' : ''}>${esc(r.label || r.id)} · ${esc(time(r.created_at))}</option>`).join('');
    const compare = `<div class="wb-toolbar"><label>比较起点<select id="workbenchRevisionA">${opts(state.revA)}</select></label><span>→</span><label>比较终点<select id="workbenchRevisionB">${opts(state.revB)}</select></label></div><div data-readonly-slot="wb_revision_compare"><div class="wb-revision-compare">${[a, b].map(r => `<article><h4>${esc(r?.label || '未选择版本')}</h4>${fields([['创建时间', time(r?.created_at)], ['内容指纹', r?.sha256], ['版本标识', r?.id]])}</article>`).join('')}</div><p class="wb-caption">${a && b ? a.sha256 && b.sha256 ? (a.sha256 === b.sha256 ? '两个已返回内容指纹相同。' : '内容指纹不同；目录接口未返回快照正文，不能据此推断哪些心理字段改变。') : '目录未提供可比较的内容指纹。' : '等待版本记录。'}人格构念的实际前后变更可在成长页查看。</p></div>`;
    cards[0].body = compare + cards[0].body;
    replaceSlot(cards[0], 'revisions_list', `<ol class="wb-version-axis">${rows.map(r => `<li><span class="wb-version-dot"></span><article><time>${esc(time(r.created_at))}</time><h4>${esc(r.label || '未命名版本')}</h4><div>${detail('wb-revision', r.id, '目录字段与版本来源 ↗')}<button type="button" class="viz-button" data-rollback-rev="${esc(r.id)}">恢复至此检查点</button></div></article></li>`).join('') || empty('尚无检查点')}</ol>`);
    return cards;
  }
  function logKey(r, i) { return String(r.ui_id ?? JSON.stringify([r.at, r.method, r.endpoint, i])); }
  function logs(env, cards) {
    const all = arr(ctx.callLog), actual = all.filter(r => !r.injected && num(r.elapsed_ms) !== null && num(r.elapsed_ms) >= 0);
    const bins = [[0, 250, '<250 ms'], [250, 1000, '250–999 ms'], [1000, 5000, '1–5 s'], [5000, Infinity, '≥5 s']];
    const counts = bins.map(([min, max]) => actual.filter(r => r.elapsed_ms >= min && r.elapsed_ms < max).length), maxCount = Math.max(1, ...counts);
    const shown = all.filter(r => (state.logStatus === '*' || (state.logStatus === 'ok' ? r.ok : state.logStatus === 'injected' ? r.injected : !r.ok)) && (state.logCode === '*' || String(r.status) === state.logCode) && (state.logBin === '*' || (!r.injected && num(r.elapsed_ms) !== null && r.elapsed_ms >= bins[Number(state.logBin)][0] && r.elapsed_ms < bins[Number(state.logBin)][1])) && includes(r.endpoint, global.DisplayText.endpoint(r.endpoint), r.method, r.error));
    cards[0].body = `${toolbar('请求名称或错误', `<label>结果<select id="workbenchLogStatus"><option value="*">全部</option><option value="ok" ${state.logStatus === 'ok' ? 'selected' : ''}>成功</option><option value="error" ${state.logStatus === 'error' ? 'selected' : ''}>错误</option><option value="injected" ${state.logStatus === 'injected' ? 'selected' : ''}>注入记录</option></select></label><label>状态码<select id="workbenchLogCode"><option value="*">全部</option>${[...new Set(all.map(r => String(r.status)))].map(c => `<option value="${esc(c)}" ${state.logCode === c ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select></label>`)}<div data-readonly-slot="wb_logs_visual"><div class="wb-latency-histogram">${bins.map((b, i) => `<button type="button" data-wb-bin="${i}" aria-pressed="${state.logBin === String(i)}"><strong>${counts[i]}</strong><i style="height:${8 + counts[i] / maxCount * 92}px"></i><span>${b[2]}</span></button>`).join('')}<button type="button" data-wb-bin="*" class="wb-hist-reset">全部耗时</button></div><p class="wb-caption">当前浏览器最多保留 ${all.length} 条请求记录；图中仅统计 ${actual.length} 条实际请求耗时，排除本地注入。未接入后端全量日志流。</p><div class="wb-request-ledger">${shown.slice(0, state.limit).map(r => `<article>${badge(r.injected ? 'unknown' : r.ok ? 'healthy' : 'failed', r.injected ? '本地注入' : String(r.status))}<div><strong>${esc(global.DisplayText.endpoint(r.endpoint))}</strong><small>${esc(time(r.at))} · ${r.elapsed_ms == null ? '耗时未知' : `${esc(r.elapsed_ms)} ms`}</small></div>${detail('wb-http', logKey(r, all.indexOf(r)), '请求详情 ↗')}</article>`).join('') || empty('没有匹配请求')}</div>${more(shown.length)}</div>`;
    return cards;
  }
  function toolsPage(cards) {
    const faults = Object.entries(ctx.faultOverrides || {});
    cards[0].body = `<div data-readonly-slot="wb_tools_state"><div class="wb-tools-state"><article><span class="wb-eyebrow">当前数据源</span><strong>${esc(ctx.source?.toUpperCase() || '未知')}</strong></article><article><span class="wb-eyebrow">本地注入覆盖</span><strong>${faults.length} 项</strong><p>${faults.map(([ep, type]) => `${esc(ep)} · ${esc(type)}`).join('<br>') || '没有活动覆盖'}</p></article><article><span class="wb-eyebrow">执行方式</span><strong>仅手动触发</strong><p>进入页面不会主动探测、注入或调用模型。</p></article></div></div>` + cards[0].body;
    return cards;
  }
  function settings(cards) {
    cards[0].body = `<div class="wb-settings-preview"><div class="wb-density-example"><i></i><i></i><i></i></div><div><h4>子页面信息密度</h4><p>仅改变专题页面的间距，不改变首页或角色数据。</p><label><select id="workbenchDensity"><option value="comfortable" ${density === 'comfortable' ? 'selected' : ''}>舒展</option><option value="compact" ${density === 'compact' ? 'selected' : ''}>紧凑</option></select></label><p id="workbenchPreferenceNotice" role="status"></p></div></div>` + cards[0].body;
    return cards;
  }
  function enhance(nav, base, env, contextData) {
    if (!pages.includes(nav)) return base;
    prepare(nav, env, contextData);
    if (['pmm_sys', 'session_trace', 'behavior_event'].includes(nav)) return [...(nav === 'pmm_sys' ? global.ModelSettings.cards(env, 'developer', nav) : []), ...global.PmmFlow.cards(env, contextData, nav)];
    let cards = base.map((c, i) => ({ ...c, title: titles[nav]?.[i] || c.title }));
    if (nav === 'role_info') cards = role(env, cards);
    if (nav === 'persona_set') cards = personality(env, cards);
    if (nav === 'archives') cards = archives(env, cards);
    if (['model_cfg', 'qq_conn', 'run_state'].includes(nav)) cards = connections(nav, env, cards);
    if (nav === 'data_import') cards = importWizard(cards);
    if (nav === 'distill_task') cards = taskBoard(env, cards);
    if (nav === 'learn_record') cards = learning(env, cards);
    if (nav === 'version_mgmt') cards = revisions(env, cards);
    if (nav === 'logs_monitor') cards = logs(env, cards);
    if (nav === 'api_tools') cards = toolsPage(cards);
    if (nav === 'settings') cards = settings(cards);
    return cards.map(c => ({ ...c, body: `<div class="wb-page-body">${c.body}</div>` }));
  }
  function resolve(kind, id, env) {
    if (!kind.startsWith('wb-')) return null;
    const p = data(env, 'characterProfile'), l = data(env, 'learning'), personality = data(env, 'personality');
    let raw, domain = 'characterProfile', field = kind.slice(3), evidence, history, updated;
    if (kind === 'wb-profile') raw = { id: p.id, name: p.name, character: p.character, seed: p.seed, revision: p.revision, trait_version: p.trait_version };
    if (kind === 'wb-role') raw = arr(p.personas_catalog).find(r => String(r.id) === id);
    if (kind === 'wb-source') { raw = arr(p.source_records).find((r, i) => recordId(r, i) === id); history = arr(p.evidence_trace?.items).filter(e => arr(e.source_ids).includes(raw?.id) || arr(e.evidence_ids).includes(raw?.id)); evidence = raw ? [raw] : []; updated = raw?.timestamp || raw?.created_at; }
    if (kind === 'wb-boundary') { raw = arr(p.boundary_model?.boundaries).find((r, i) => recordId(r, i) === id); evidence = raw?.evidence || raw?.source_ids; }
    if (kind === 'wb-construct') { domain = 'personality'; raw = arr(personality.editable_constructs).find(r => r.id === id); evidence = raw?.evidence; history = raw?.history; }
    if (kind === 'wb-connection') {
      domain = 'connections'; const conn = data(env, 'connections'), n = conn.nodes?.[id];
      const probe = conn.probe_results?.[{ general_llm: 'general', api_pmm: 'pmm', qq_channel: 'qq' }[id]];
      raw = n ? { ...n, latest_probe: probe || null, ...(id === 'qq_channel' ? { channel_status: conn.qq_observation } : {}) } : null;
      updated = null;
    }
    if (kind === 'wb-qq-config') raw = { api_url: p.config?.qq?.api_url, self_id: p.config?.qq?.self_id, group_mention_only: p.config?.qq?.group_mention_only, allowed_users: p.config?.qq?.allowed_users, allowed_groups: p.config?.qq?.allowed_groups };
    if (kind === 'wb-active-job') { domain = 'connections'; raw = arr(data(env, 'connections').active_jobs).find((r, i) => recordId(r, i) === id); }
    if (kind === 'wb-job') { domain = 'learning'; raw = arr(l.raw_jobs).find(r => String(r.id) === id); evidence = raw?.source_ids; }
    if (kind === 'wb-activity') { domain = 'learning'; raw = arr(l.activities).find(r => String(r.id) === id); evidence = raw?.payload?.source_ids; }
    if (kind === 'wb-candidate') { domain = 'learning'; raw = arr(l.candidates).find((r, i) => recordId(r, i) === id); evidence = raw?.reasons; }
    if (kind === 'wb-other') { domain = 'learning'; raw = arr(l.other_status).find((r, i) => recordId(r, i) === id); }
    if (kind === 'wb-revision') { domain = 'personality'; raw = arr(personality.revisions).find(r => String(r.id) === id); }
    if (kind === 'wb-http') { raw = arr(ctx.callLog).find((r, i) => logKey(r, i) === id); return raw ? { title: '浏览器请求详情', id, envelope: { source: raw.injected ? 'mock' : 'live', status: 'success', endpoint: 'browser://PMMAdapter.callLog', fetched_at: raw.at }, updated_at: null, fields: [{ label: '请求', value: `${raw.method} ${raw.endpoint}` }, { label: '记录性质', value: raw.injected ? '本地注入，无对应真实请求耗时' : '浏览器发起的实际 HTTP 请求' }, { label: 'HTTP 状态', value: raw.status }, { label: '观测耗时 ms', value: raw.elapsed_ms }, { label: 'UTC', value: raw.at }, { label: '错误', value: raw.error || raw.code }], raw: V.redact(raw), description: '只反映当前浏览器的请求记录；不代表后端全量日志。' } : null; }
    if (!raw) return null;
    return { id, title: { 'wb-profile': '当前主体档案', 'wb-role': '角色目录记录', 'wb-source': '来源与引用链', 'wb-boundary': '边界记录', 'wb-construct': '构念与来源', 'wb-connection': '连接观察', 'wb-qq-config': '通道路由配置', 'wb-active-job': '后台任务', 'wb-job': '学习任务', 'wb-activity': '学习活动', 'wb-candidate': '候选复核依据', 'wb-other': '对象观察', 'wb-revision': '版本目录记录' }[kind] || '数据详情', envelope: env[domain], field, updated_at: updated || raw.updated_at || raw.created_at || null,
      fields: Object.entries(raw).filter(([k, v]) => v == null || ['string', 'number', 'boolean'].includes(typeof v)).slice(0, 14).map(([label, value]) => ({ label, value: V.redact({ [label]: value })[label] })), evidence: V.redact(evidence), history: V.redact(history), raw: V.redact(raw) };
  }
  function handleChange(el) {
    const map = { workbenchSearch: 'query', workbenchGroup: 'group', workbenchStatus: 'status', workbenchRevisionA: 'revA', workbenchRevisionB: 'revB', workbenchLogStatus: 'logStatus', workbenchLogCode: 'logCode' };
    if (map[el.id]) { state[map[el.id]] = el.value; state.limit = 18; return true; }
    if (el.id === 'selectDispositionField') { state.feature = el.value; return true; }
    if (el.id === 'inputDispositionVal') { state.estimate = el.value; return true; }
    if (el.id === 'workbenchDensity') { density = el.value === 'compact' ? 'compact' : 'comfortable'; try { localStorage.setItem('huaian.ui.panel-density', density); } catch (_) {} return true; }
    return false;
  }
  function handleClick(el) {
    const feature = el.closest('[data-wb-feature]');
    if (feature) { state.feature = feature.dataset.wbFeature; const select = document.getElementById('selectDispositionField'); if (select) { select.value = state.feature; select.focus({ preventScroll: true }); } return true; }
    const bin = el.closest('[data-wb-bin]'); if (bin) { state.logBin = bin.dataset.wbBin; return true; }
    if (el.closest('[data-wb-action="more"]')) { state.limit += 18; return true; }
    return false;
  }
  function syncControls(root) {
    root.dataset.panelDensity = density;
    if (!root.classList.contains('dev-viz-page') && !root.querySelector('#workbenchDensity')) return;
    global.PmmFlow.syncControls(root);
    if (page === 'persona_set') {
      const select = root.querySelector('#selectDispositionField');
      if (select) {
        if (!state.feature) state.feature = select.value;
        else select.value = state.feature;
        const rows = arr(data(latest, 'personality').editable_constructs);
        for (const opt of select.options) { const f = rows.find(r => r.id === opt.value); if (f) { opt.dataset.curEst = f.estimate == null ? 'null' : String(f.estimate); opt.dataset.curSrc = f.source_type || 'unknown'; opt.dataset.nameZh = f.name_zh || f.id; } }
      }
    }
    if (page === 'settings') { const label = root.querySelector('#workbenchPreferenceNotice'); if (label) label.textContent = `当前为${density === 'compact' ? '紧凑' : '舒展'}间距，仅作用于子页面。`; }
    if (page === 'version_mgmt') {
      const rows = arr(data(latest, 'personality').revisions);
      for (const [id, value] of [['workbenchRevisionA', state.revA], ['workbenchRevisionB', state.revB]]) {
        const el = root.querySelector(`#${id}`); if (!el) continue;
        const html = rows.map(r => `<option value="${esc(r.id)}">${esc(r.label || r.id)} · ${esc(time(r.created_at))}</option>`).join('');
        if (el.innerHTML !== html) el.innerHTML = html;
        el.value = value;
      }
    }
    if (page === 'logs_monitor') {
      const select = root.querySelector('#workbenchLogCode');
      if (select) { const codes = [...new Set(arr(ctx.callLog).map(r => String(r.status)))]; if (state.logCode !== '*' && !codes.includes(state.logCode)) codes.push(state.logCode); const html = '<option value="*">全部</option>' + codes.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join(''); if (select.innerHTML !== html) select.innerHTML = html; select.value = state.logCode; }
    }
  }
  global.DeveloperViews = { pages, enhance, detail: resolve, handleChange, handleClick, syncControls };
})(window);
