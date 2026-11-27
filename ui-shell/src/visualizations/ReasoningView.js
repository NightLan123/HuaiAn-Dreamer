/* Recorded internal B stances are distinct from Learned-PMM predictions. */
(function (global) {
  'use strict';
  const esc = v => global.PsychViz.escape(v ?? ''), arr = v => Array.isArray(v) ? v : [];
  const val = v => global.PsychViz.number(v) === null ? '未记录' : Number(v).toFixed(3);
  const raw = (title, x) => `<details><summary>${title}</summary><pre>${esc(JSON.stringify(x ?? null, null, 2))}</pre></details>`;
  let context = '', loaded = new Map(), errors = new Map(), busy = new Set();
  function prepare(ctx) {
    const next = `${ctx.personaId}:${ctx.source}:${ctx.epoch}`;
    if (next !== context) { context = next; loaded.clear(); errors.clear(); busy.clear(); }
  }
  function round(r, index) {
    const plans = arr(r.proposals), perspectives = arr(r.perspectives);
    return `<details ${index === 0 ? 'open' : ''}><summary>讨论记录 ${index + 1} · ${r.b_called === false ? 'B 未调用' : r.b_status === 'failed' ? 'B 失败，采用本地方案' : r.b_status === 'completed' ? 'B 已返回' : '调用状态未记录'}</summary>
      ${perspectives.map(p => `<article><h4>${esc(p.hypothesis)}</h4><p>目标：${esc(p.goal)} · 权重 ${val(p.weight)}</p><p>局限：${esc(arr(p.limitations).join('；') || '未记录')}</p>${raw('关系、价值及其他关注依据', arr(p.salient_factors).map(f => ({ ...f, source: r.factor_registry?.[f.ref] })))}${raw('引用依据', arr(p.evidence_refs).map(ref => ({ ref, source: r.evidence_registry?.[ref] })))}</article>`).join('')}
      <div style="overflow:auto"><table><thead><tr><th>候选方案</th>${perspectives.map((p, i) => `<th>立场 ${i + 1}</th>`).join('')}<th>相对支持</th><th>选择</th></tr></thead><tbody>${plans.map(p => `<tr><td>${esc(p.content_goal || p.goal || p.intended_goal || p.id)}</td>${perspectives.map(v => `<td>${val(r.utility_matrix?.[v.id]?.[p.id])}</td>`).join('')}<td>${val(r.support?.[p.id])}</td><td>${r.selected_proposal_id === p.id ? '选中' : '未选中'}</td></tr>`).join('')}</tbody></table></div>
      <p>${esc(r.selection_reason || '选择原因未记录')}</p>${raw('约束、贡献与冻结状态', { blocked: r.blocked_proposals, contributions: r.contributions, state: r.shared_state_ref, support_method: r.support_method })}</details>`;
  }
  function renderRun(run) {
    const discussion = run.deliberation, drive = run.expressive_drive || {}, contributions = drive.channel_contributions || {};
    const names = { personality_b_theta: '人格基线', fast_emotion: '快情绪', slow_mood: '慢心境', cognitive_appraisal: '事件评价', relationship: '关系', dialogue_context: '对话环境', residual_motive: '未完成动机' };
    const timing = { ...(run.timing || {}), local_retrieval: run.local_retrieval, discussion_stops: run.discussion_stops, discussion_requests: run.discussion_requests };
    return `<section class="wb-recorded-reasoning"><h3>本轮心理条件与内部 B 讨论</h3><p>${esc(run.event_summary)}</p><p>候选：${esc(run.candidate_status || '未记录')} · 送达：${esc(run.delivery_status || '未记录')}</p>
      ${raw('实际时间记录（不将请求耗时相加当作等待时间）', timing)}
      <h4>表达欲的计算贡献</h4><p>下列三列分别作用于激活度、紧迫度、持续度的计算输入，不是百分比或经过验证的心理因果。</p>
      ${Object.keys(contributions).length ? `<table><thead><tr><th>条件</th><th>激活</th><th>紧迫</th><th>持续</th></tr></thead><tbody>${Object.entries(contributions).map(([k, v]) => `<tr><th>${esc(names[k] || k)}</th>${[0, 1, 2].map(i => `<td>${val(v?.[i])}</td>`).join('')}</tr>`).join('')}</tbody></table>` : '<p>此回合未保存分项贡献，不按当前参数补算历史。</p>'}
      ${raw('来源及行为影响', { inputs: drive.inputs_summary, timing: drive.turn_taking_influence, actions: drive.policy_score_terms, expression: run.expression_conditions, decision: run.actual_decision })}
      <h4>同一角色的不同情境立场</h4><p>这里是内部 B 的提案讨论，不是 Learned-PMM 的数值网络；相对支持不是人格概率。</p>
      ${discussion ? (arr(discussion.rounds).length ? discussion.rounds.map(round).join('') + raw('最终选择', {selected_proposal_id:discussion.selected_proposal_id, blocked:discussion.blocked_proposals, contributions:discussion.contributions}) : round(discussion, 0)) : '<p>该回合没有保留内部讨论，可能未调用 B；不生成替代观点。</p>'}</section>`;
  }
  function card(turnId, ctx) {
    prepare(ctx);
    return { id: 'developer_recorded_reasoning', domain: 'decisions', title: '内部讨论与心理条件 · 回合依据', size: 'wide', body:
      `<button type="button" class="viz-button" data-reasoning-load="${esc(turnId)}" ${!turnId || busy.has(turnId) || ctx.source !== 'live' ? 'disabled' : ''}>读取所选回合的完整依据</button><div data-readonly-slot="recorded_reasoning"><p role="status">${esc(errors.get(turnId) || (busy.has(turnId) ? '正在读取…' : ''))}</p>${loaded.has(turnId) ? renderRun(loaded.get(turnId)) : '<p>按需读取实际记录，不触发模型重新思考。</p>'}</div>` };
  }
  async function handleClick(target, services) {
    const el = target.closest('[data-reasoning-load]'); if (!el) return false;
    prepare(services.context); const id = el.dataset.reasoningLoad, captured = context;
    if (!id || busy.has(id) || services.context.source !== 'live') return true;
    busy.add(id); errors.delete(id); services.render();
    try {
      const env = await services.adapter.fetchRunDetail(id);
      if (!services.isCurrent() || captured !== context) return true;
      if (env.status !== 'success') throw new Error(env.error || '读取失败'); loaded.set(id, env.data.run);
    } catch (error) { if (services.isCurrent() && captured === context) errors.set(id, String(error.message || error)); }
    finally { if (captured === context) { busy.delete(id); if (services.isCurrent()) services.render(); } }
    return true;
  }
  global.ReasoningView = { card, handleClick, renderRun };
})(window);
