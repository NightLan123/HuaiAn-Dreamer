/* Stage 3: existing evaluated turns and recorded personality changes, read-only. */
(function (global) {
  'use strict';
  const esc = v => global.PsychViz.escape(v ?? '');
  const arr = v => Array.isArray(v) ? v : [];
  const num = v => global.PsychViz.number(v);
  const time = v => v ? global.formatLocalDisplayTime(v) : '时间未提供';
  const good = e => e && ['success', 'empty'].includes(e.status);
  const button = (kind, id, label) => `<button type="button" class="life-link" data-psych-detail="${kind}" data-detail-id="${esc(id)}">${label}</button>`;
  const labels = { reply: '回应', clarify: '澄清', wait: '等待', silence: '保留表达', refuse: '拒绝', LOCAL_COMMITTED: '本地已提交', delivered_full: '完整送达', delivered_partial: '部分送达' };
  const display = x => labels[x] || x || '未提供';
  let context = '', state, latest;
  function prepare(env, ctx) {
    if (ctx) {
      const key = `${ctx.personaId}:${ctx.source}:${ctx.scope}:${ctx.epoch}`;
      if (context !== key) { context = key; state = { scope: ctx.scope, session: '*', type: '*', date: '', query: '', feature: '*', change: '*', limit: 12, growthLimit: 12 }; }
    }
    latest = env;
    return env;
  }
  const exp = env => good(env.experiences) ? arr(env.experiences.data?.visual_items) : [];
  const promotions = env => good(env.personality) ? arr(env.personality.data?.promotion_history) : [];
  const promotionKey = p => String(p.id ?? JSON.stringify([p.feature_id, p.at, p.trait_version, p.method]));
  const candidateKey = p => String(p.id ?? p.feature_id);
  function linked(env, row) {
    const keys = [row.id, row.event_id].filter(v => v != null).map(String);
    const affect = good(env.emotion) ? arr(env.emotion.data?.events_points).filter(p => p.event_id != null && keys.includes(String(p.event_id))) : [];
    const drive = good(env.expressionDrive) ? arr(env.expressionDrive.data?.recent_history).filter(p => p.event_id != null && keys.includes(String(p.event_id))) : [];
    return { affect, drive };
  }
  function option(values, chosen, all) { return `<option value="*">${all}</option>` + [...new Set(values.filter(v => v != null && v !== ''))].map(v => `<option value="${esc(v)}" ${String(v) === chosen ? 'selected' : ''}>${esc(v)}</option>`).join(''); }
  function experienceCards(env, mode, ctx) {
    prepare(env, ctx);
    const rows = exp(env), shown = rows.filter(r => (state.scope === '*' || r.scope === state.scope) && (state.session === '*' || r.session_id === state.session) && (state.type === '*' || r.event_type === state.type) && (!state.date || (r.at && time(r.at).slice(0, 10) === state.date)) && (!state.query || String(r.text || '').toLowerCase().includes(state.query.toLowerCase()))).sort((a, b) => (Date.parse(b.at) || 0) - (Date.parse(a.at) || 0));
    return [{ id: `${mode}_experience_journey`, domain: 'experiences', title: '经历 · 一次互动如何被理解', size: 'wide', body: `<div class="life-toolbar"><label>范围<select id="lifeExperienceScope">${option([state.scope, ...rows.map(r => r.scope)], state.scope, '全部已返回范围')}</select></label><label>会话<select id="lifeExperienceSession">${option(rows.map(r => r.session_id), state.session, '全部已返回会话')}</select></label><label>事件类型<select id="lifeExperienceType">${option(rows.map(r => r.event_type), state.type, '全部类型')}</select></label><label>日期<input type="date" id="lifeExperienceDate" value="${esc(state.date)}"/></label><label class="life-search">搜索<input type="search" id="lifeExperienceSearch" value="${esc(state.query)}" placeholder="发生了什么…"/></label><button type="button" class="viz-button" data-life-action="clear-experience">清除筛选</button></div><div data-readonly-slot="experience_timeline">${global.PsychViz.state(env.experiences)}<div class="life-overview"><strong>${shown.length}</strong><span>条匹配经历 · 当前返回 ${rows.length} 条${env.experiences?.data?.total_count != null ? ` / 库中 ${esc(env.experiences.data.total_count)} 条` : ''}</span></div><p class="viz-muted">顺序表示事件的处理过程。相邻记录不代表因果；没有会话或类型标识的记录保留缺失。</p><ol class="life-timeline">${shown.slice(0, state.limit).map(r => {
      const links = linked(env, r);
      return `<li><time>${esc(time(r.at))}</time><article class="life-event"><span class="life-eyebrow">${esc(r.event_type || '事件类型未提供')} · ${esc(r.person || '对象未提供')}</span><h4>${esc(r.text || '事件原文未提供')}</h4><div class="life-process"><div><span>01 · 理解与评价</span>${button('life-appraisal', r.id, r.appraisal ? '查看认知评价 ↗' : r.usage.length ? '查看已记录的评价依据 ↗' : '评价内容未提供')}</div><div><span>02 · 决策与表达</span><strong>${esc(display(r.strategy))}</strong>${button('life-experience', r.id, '查看策略与轨迹 ↗')}</div><div><span>03 · 回复与回执</span><strong>${esc(r.delivery ? display(r.delivery) : '送达结果未提供')}</strong><small>${r.actual_confirmed == null ? '确认数量未知' : `已确认 ${esc(r.actual_confirmed)} 条`}</small></div></div><details data-life-expand="${esc(r.id)}"><summary>展开真实回复与关联观测</summary><div class="life-replies">${r.actual_parts.length ? r.actual_parts.map(p => `<p>${esc(p)}</p>`).join('') : r.reply ? `<p>${esc(r.reply)}</p>` : '<p class="viz-muted">此记录未提供回复文本。</p>'}</div><p>${links.affect.length || links.drive.length ? button('life-linked', r.id, `查看 ${links.affect.length} 条情绪观测与 ${links.drive.length} 条表达事件 ↗`) : '暂无关联证据'}</p>${r.error ? `<p class="life-error">${esc(typeof r.error === 'string' ? r.error : JSON.stringify(r.error))}</p>` : ''}</details></article></li>`;
    }).join('') || '<li class="life-empty">当前筛选下没有已记录经历。</li>'}</ol>${shown.length > state.limit ? '<button type="button" class="viz-button" data-life-action="more-experience">继续展开经历</button>' : ''}${global.PsychViz.provenance(env.experiences, 'experiences', 'evaluated_turns')}<aside class="life-planned"><strong>人生章节 · 待后续开放</strong><p>目前可以浏览逐轮经历，尚无跨月自传章节。</p></aside></div>` }];
  }
  function changeType(p) { return p.after?.source_type === 'experience_derived' ? 'experience' : p.after?.source_type === 'promoted_evidence' ? 'promoted' : /owner|seed|questionnaire/.test(`${p.method} ${p.after?.source_type}`) ? 'setting' : 'other'; }
  function featureName(env, id) { const f = arr(env.personality?.data?.editable_constructs).find(x => x.id === id); return f?.name_zh || f?.label || id; }
  function comparison(p, env) {
    const f = arr(env.personality?.data?.editable_constructs).find(x => x.id === p.feature_id), min = num(f?.minimum) ?? 0, max = num(f?.maximum) ?? 1;
    const points = [['before', '变更前', '○'], ['after', '变更后', '●']].map(([field, label, symbol]) => {
      const n = num(p[field]?.estimate), valid = n !== null && max > min && n >= min && n <= max;
      return `<div class="life-estimate"><span>${symbol} ${label}</span><div class="life-estimate-track">${valid ? `<i class="${field}" style="left:${(n - min) / (max - min) * 100}%"></i>` : ''}</div><strong>${n === null ? '待观察' : esc(n.toFixed(3))}</strong></div>`;
    }).join('');
    return `<div class="life-comparison">${points}<small>范围 ${min}—${max}；数值变化不代表好坏评价。</small></div>`;
  }
  function growthCards(env, mode, ctx) {
    prepare(env, ctx);
    const all = promotions(env), shown = all.filter(p => (state.feature === '*' || p.feature_id === state.feature) && (state.change === '*' || changeType(p) === state.change)).slice().reverse();
    const learning = good(env.learning) ? env.learning.data : {}, candidateEnv = learning.candidates_envelope, activityEnv = learning.activities_envelope;
    const candidates = good(candidateEnv) ? arr(candidateEnv.data) : [], acts = good(activityEnv) ? arr(activityEnv.data) : [];
    const version = good(env.personality) ? env.personality.data.version : null;
    const cog = env.characterProfile?.data?.cognition_envelope;
    return [
      learningCard(env, mode),
      { id: `${mode}_growth_changes`, domain: 'personality', title: '成长 · 已记录的变化', size: 'wide', body: `<div class="life-toolbar"><label>构念<select id="lifeGrowthFeature">${option(all.map(p => p.feature_id), state.feature, '全部构念')}</select></label><label>变化来源<select id="lifeGrowthChange"><option value="*">全部来源</option><option value="promoted" ${state.change === 'promoted' ? 'selected' : ''}>证据晋升</option><option value="experience" ${state.change === 'experience' ? 'selected' : ''}>经历成长</option><option value="setting" ${state.change === 'setting' ? 'selected' : ''}>明确设定</option><option value="other" ${state.change === 'other' ? 'selected' : ''}>其他记录</option></select></label></div><div data-readonly-slot="growth_changes_visual">${global.PsychViz.state(env.personality)}<div class="life-growth-overview"><div><span>当前人格版本</span><strong>${version == null ? '未提供' : esc(version)}</strong></div><div><span>已记录变更</span><strong>${good(env.personality) ? all.length : '未知'}</strong></div><div><span>候选待复核</span><strong>${good(candidateEnv) ? candidates.length : '未知'}</strong></div><div><span>认知校准状态</span><strong>${good(cog) && typeof cog.data?.calibrated === 'boolean' ? (cog.data.calibrated ? '已标记校准' : '尚未校准') : '未提供'}</strong></div></div><p class="viz-muted">明确设定与证据晋升分开记录；存在版本变化不等于模型已训练或校准。</p><ol class="life-timeline">${shown.slice(0, state.growthLimit).map(p => `<li><time>${esc(time(p.at))}</time><article class="life-event"><span class="life-eyebrow">${changeType(p) === 'experience' ? '经历成长' : changeType(p) === 'promoted' ? '证据晋升' : changeType(p) === 'setting' ? '明确设定' : '已有变更'} · ${p.trait_version == null ? '版本未提供' : `版本 ${esc(p.trait_version)}`}</span><h4>${esc(featureName(env, p.feature_id))}</h4>${comparison(p, env)}${button('life-growth', promotionKey(p), '查看变更依据与原记录 ↗')}</article></li>`).join('') || '<li class="life-empty">当前没有符合筛选的变更记录。</li>'}</ol>${shown.length > state.growthLimit ? '<button type="button" class="viz-button" data-life-action="more-growth">继续展开变化</button>' : ''}${global.PsychViz.provenance(env.personality, 'personality', 'promotion_history')}</div>` },
      { id: `${mode}_growth_candidates`, domain: 'learning', title: '尚在形成 · 候选证据', body: `<div data-readonly-slot="growth_candidates_visual">${global.PsychViz.state(candidateEnv)}<div class="life-candidates">${candidates.map(c => `<article><span class="life-eyebrow">候选，未当作正式人格</span><h4>${esc(featureName(env, c.feature_id))}</h4><p>${c.eligible === true ? '后端标记符合复核条件，是否晋升以变更记录为准。' : c.eligible === false ? '现有证据仍有待补足。' : '复核资格未提供。'}</p><ul>${arr(c.reasons).map(r => `<li>${esc(r)}</li>`).join('')}</ul>${button('life-candidate', candidateKey(c), '查看证据量与复核条件 ↗')}</article>`).join('') || '<p class="life-empty">暂无已返回候选。</p>'}</div></div>` },
      { id: `${mode}_growth_learning`, domain: 'learning', title: '学习活动 · 留下的记录', body: `<div data-readonly-slot="growth_learning_visual">${global.PsychViz.state(activityEnv)}<ol class="life-activity-list">${acts.map(a => `<li><time>${esc(time(a.created_at))}</time>${button('life-activity', a.id, esc(a.payload?.summary || a.payload?.target || a.kind || '学习活动'))}</li>`).join('') || '<li class="life-empty">暂无已返回的学习活动。</li>'}</ol><aside class="life-planned"><strong>长期发展曲线 · 待后续开放</strong><p>目前仅展示实际存储的变更与活动，不补画连续成长趋势。</p></aside></div>` }
    ];
  }
  function detail(kind, id, env) {
    if (!kind.startsWith('life-')) return null;
    const base = { id, updated_at: null };
    if (['life-experience', 'life-appraisal', 'life-linked'].includes(kind)) {
      const r = exp(env).find(x => String(x.id) === id); if (!r) return null;
      const related = linked(env, r);
      return { ...base, title: kind === 'life-appraisal' ? '认知评价与依据' : kind === 'life-linked' ? '同一事件的关联观测' : '经历详情', envelope: env.experiences, field: 'evaluated_turns', updated_at: r.at,
        description: '关联只按真实事件标识匹配；处理顺序不构成额外的因果解释。', fields: [{ label: '原文', value: r.text }, { label: '会话', value: r.session_id }, { label: '范围', value: r.scope }, { label: '策略', value: display(r.strategy) }, { label: '回执', value: display(r.delivery) }, { label: '确认数', value: r.actual_confirmed }], raw: kind === 'life-linked' ? related : r.raw,
        evidence: kind === 'life-linked' ? [...related.affect.map(p => ({ ...p, endpoint: env.emotion?.endpoint })), ...related.drive.map(p => ({ ...p, endpoint: env.expressionDrive?.endpoint }))] : r.appraisal || r.usage };
    }
    if (kind === 'life-growth') {
      const p = promotions(env).find(x => promotionKey(x) === id); if (!p) return null;
      const evidence = p.source_evidence || p.after?.evidence || p.after?.evidence_ids || [];
      const sourceIds = new Set(arr(evidence).map(x => typeof x === 'string' ? x : x.record_id).filter(Boolean));
      const acts = arr(env.learning?.data?.activities).filter(a => arr(a.payload?.source_ids).some(k => sourceIds.has(k)) || (p.job_id && a.payload?.job_id === p.job_id));
      return { ...base, title: featureName(env, p.feature_id), envelope: env.personality, field: 'promotion_history', updated_at: p.at, fields: [{ label: '构念', value: p.feature_id }, { label: '方法', value: p.method }, { label: '版本', value: p.trait_version }, { label: '变更前', value: p.before?.estimate }, { label: '变更后', value: p.after?.estimate }, { label: '精确关联活动', value: acts.length ? `${acts.length} 条` : '暂无关联证据' }], evidence, history: acts, raw: p };
    }
    if (kind === 'life-candidate') { const e = env.learning?.data?.candidates_envelope, c = arr(e?.data).find(x => candidateKey(x) === id); return c ? { ...base, title: '候选复核依据', envelope: e, field: 'candidates', fields: [{ label: '构念', value: featureName(env, c.feature_id) }, { label: '独立事件', value: c.independent_events }, { label: '情境数', value: c.contexts }, { label: '证据跨度（秒）', value: c.span_seconds }, { label: '审查状态', value: c.review_status ?? (c.eligible === true ? '符合复核条件' : '尚未满足条件') }], evidence: c.reasons, raw: c } : null; }
    if (kind === 'life-activity') { const e = env.learning?.data?.activities_envelope, a = arr(e?.data).find(x => String(x.id) === id); return a ? { ...base, title: '学习活动详情', envelope: e, field: 'activities', updated_at: a.created_at, fields: [{ label: '类型', value: a.kind }, { label: '状态', value: a.payload?.status }], raw: a, evidence: a.payload?.source_ids } : null; }
    return null;
  }
  function learningCard(env, mode) {
    const data = good(env.learning) ? env.learning.data : {}, p = data.policy || {}, x = data.experience_learning;
    if (!x) return { id: `${mode}_experience_learning`, domain: 'learning', title: '从经历中成长', body: '<p>经历学习状态尚未返回。</p>' };
    const cfg = p.experience || x.settings, self = p.domains?.self || {}, job = x.job || {};
    const status = { running: '正在整理经历', failed: '整理失败，经历仍然保留', completed: '本批整理完成', partial: '部分观察已采纳，余项待整理', evidence_rejected: '观察缺少可核实的依据', awaiting_review: '候选等待审阅', rolled_back: '已撤销本批变化' }[job.status] || '等待新的经历';
    const controls = [];
    if (['failed','partial','evidence_rejected'].includes(job.status)) controls.push(['retry', '重试未处理经历'], ['cancel', '跳过本批剩余经历']);
    if (job.status === 'awaiting_review') controls.push(['approve', '审阅后采纳'], ['cancel', '跳过本批']);
    if (job.can_rollback) controls.push(['rollback', job.status === 'partial' ? '撤销本批变化并跳过余项' : '撤销本批变化']);
    if (x.exhausted_batches && job.status !== 'awaiting_review' && !x.running) controls.push(['retry_deferred','重新开放已暂停的批次']);
    const accepted = arr(job.result?.accepted_observations);
    const adopted = accepted.length ? '<details><summary>查看已采纳观察（' + accepted.length + '）</summary><ul>' + accepted.map(r => '<li>' + esc(featureName(env,r.feature_id)) + ' · ' + esc([...new Set(arr(r.sources).map(s => s.memory_id))].length) + ' 个事件 · ' + esc([...new Set(arr(r.sources).map(s => s.source === 'delivered_action' ? '已确认的回应' : '事件原文'))].join('、')) + '</li>').join('') + '</ul></details>' : '';
    const rejected = arr(job.result?.observation_rejections || job.observation_rejections);
    const receipt = rejected.length ? '<details><summary>查看退回的观察及原因（' + rejected.length + '）</summary><ul>' + rejected.map(r => '<li>' + esc(r.feature_id ? featureName(env,r.feature_id) : '构念未确认') + ' · ' + esc(r.reason) + ' · ' + (r.unattributed ? '无法定位到本批经历' : esc(arr(r.memory_ids).length) + ' 条关联经历') + '</li>').join('') + '</ul></details>' : '';
    return { id: `${mode}_experience_learning`, domain: 'learning', title: '从经历中成长', size: 'wide', body: `<form id="experienceLearningForm" class="life-toolbar"><label><input type="checkbox" name="enabled" ${cfg.enabled && self.enabled ? 'checked' : ''}> 启用经历学习</label><label>每新增几条经历整理一次<input type="number" name="new_memories" min="3" max="50" step="1" value="${esc(cfg.new_memories)}" required></label><label>变化方式<select name="mode">${[['automatic','符合证据条件后自动更新'],['candidate_only','先形成候选，由我审阅'],['manual','暂停自动整理']].map(([v,l])=>`<option value="${v}" ${self.mode===v?'selected':''}>${l}</option>`).join('')}</select></label><label>更新强度（%）<input type="number" name="strength" min="0" max="100" value="${Math.round((self.strength ?? .5)*100)}" required></label><button type="submit" class="viz-button">保存设置</button></form><p id="experienceLearningFeedback" role="status" aria-live="polite"></p><div data-readonly-slot="experience_learning_status"><div class="life-growth-overview"><div><span>待整理的新经历</span><strong>${esc(x.pending_memories)} / ${esc(x.next_at)}</strong></div><div><span>已处理事件</span><strong>${esc(x.processed_events)}</strong></div><div><span>当前进度</span><strong>${esc(status)}</strong></div></div>${adopted}${receipt}${job.status === 'awaiting_review' ? `<p>待审阅的有效人格观察 ${esc(job.proposed_count ?? 0)} 项。</p>` : ''}${x.deferred_events ? `<p>待重试 ${esc(x.deferred_events)} 条经历，${esc(x.exhausted_batches)} 批已达到自动重试上限。</p>` : ''}${p.paused ? '<p>学习总开关已暂停；请在学习策略中恢复。</p>' : ''}<p>积累事件、实际结果、当时情绪和对人物的看法，再缓慢调整角色倾向。证据不足时保持不变；不会将一次情绪变化当成人格变化。</p><p class="viz-muted">至少 3 个独立事件、跨情境且跨度达到 24 小时才可能更新。默认强度下，已有倾向每批最多变化 0.015。未锁定的角色倾向可以成长，原始人设保留。</p>${job.result ? `<p>本批新增 ${esc(job.result.accepted)} 项候选，改变 ${esc(job.result.promoted)} 项倾向，形成 ${esc(job.result.role_supplements_added ?? 0)} 条经历补充。</p><details><summary>查看未改变的原因</summary><ul>${arr(job.result.candidates).filter(r=>r.reasons?.length).map(r=>`<li>${esc(featureName(env,r.feature_id))}：${esc(r.reasons.join('；'))}</li>`).join('')}</ul></details>` : ''}<p class="viz-muted">人设内容另走重大经历筛选：需要重大记忆及至少24小时后的独立后续支持，每24小时最多生效一项。默认新增参考权重1%，单项上限5%；这不是人格量表分数。候选权重为零，未确认前不会用于回复。</p><details><summary>待确认的人设变化（${arr(x.role_change_candidates).length}）</summary><ul>${arr(x.role_change_candidates).map(n=>`<li>${esc(n.topic)}：${esc(n.text)}<small> ${esc(arr(n.reasons).join('；'))}</small></li>`).join('') || '<li>暂无候选，普通对话不会自动改写人设。</li>'}</ul></details><details><summary>当前经历形成的人设补充</summary><ul>${arr(x.role_supplements).map(n=>`<li>${esc(({experiences:"经历影响",relationships:"关系看法",preferences:"偏好",values:"价值取向",behavior:"行为习惯"})[n.category] || "经历补充")}：${esc(n.text)} <small>补充参考权重 ${esc(Math.round(n.weight*100))}% · ${esc(time(n.created_at))}</small></li>`).join('') || '<li>尚无符合条件的补充；原有角色设定保持。</li>'}</ul></details>${arr(job.result?.role_rejections).length ? '<p>部分人设候选缺少重大经历依据、存在反例或与设定冲突，已阻止应用；具体原因保留在整理记录中。</p>' : ''}${job.error ? `<p role="alert">${esc(job.error)}</p>` : ''}<div class="life-toolbar">${controls.map(([a,l])=>`<button type="button" class="viz-button" data-experience-control="${a}">${l}</button>`).join('')}</div><details><summary>最近整理记录</summary><ol>${arr(x.history).slice().reverse().map(r=>`<li>${esc(time(r.completed_at || r.at))} · ${r.result ? `处理 ${esc(r.result.processed_event_count ?? arr(r.memory_ids).length)} / ${esc(arr(r.memory_ids).length)} 条经历，改变 ${esc(r.result.promoted)} 项倾向` : esc(r.status === 'rejected' ? '已跳过' : r.status)}</li>`).join('') || '<li>暂无整理记录。</li>'}</ol></details></div>` };
  }
  function handleChange(el) {
    const map = { lifeExperienceScope: 'scope', lifeExperienceSession: 'session', lifeExperienceType: 'type', lifeExperienceDate: 'date', lifeExperienceSearch: 'query', lifeGrowthFeature: 'feature', lifeGrowthChange: 'change' };
    if (!map[el.id]) return false;
    state[map[el.id]] = el.value; state.limit = 12; state.growthLimit = 12; return true;
  }
  function handleClick(el) {
    const a = el.closest('[data-life-action]')?.dataset.lifeAction; if (!a) return false;
    if (a === 'more-experience') state.limit += 12;
    if (a === 'more-growth') state.growthLimit += 12;
    if (a === 'clear-experience') Object.assign(state, { scope: '*', session: '*', type: '*', date: '', query: '' });
    return true;
  }
  function syncControls(root) {
    if (!state || !latest) return;
    const rows = exp(latest);
    [['lifeExperienceScope', rows.map(r => r.scope), state.scope, '全部已返回范围'], ['lifeExperienceSession', rows.map(r => r.session_id), state.session, '全部已返回会话'], ['lifeExperienceType', rows.map(r => r.event_type), state.type, '全部类型'], ['lifeGrowthFeature', promotions(latest).map(p => p.feature_id), state.feature, '全部构念']].forEach(([id, vals, value, label]) => { const el = root.querySelector(`#${id}`); if (el) { const html = option([...vals, value === '*' ? null : value], value, label); if (el.innerHTML !== html) el.innerHTML = html; el.value = value; } });
    [['lifeExperienceDate', state.date], ['lifeExperienceSearch', state.query], ['lifeGrowthChange', state.change]].forEach(([id, value]) => { const el = root.querySelector(`#${id}`); if (el && el.value !== value) el.value = value; });
  }
  global.LifeViews = { experienceCards, growthCards, learningCard, detail, handleChange, handleClick, syncControls };
})(window);
