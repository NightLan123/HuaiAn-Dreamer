/* Runtime observations and opt-in reflection settings. No polling starts a model. */
(function (global) {
  'use strict';
  const esc = v => global.PsychViz.escape(v ?? '');
  const time = v => v ? global.formatLocalDisplayTime(v) : '尚无记录';
  const labels = { resume_wait: '等待与停顿恢复', delivery_recovery: '送达记录整理', consolidation: '对话整理', learning: '已授权学习', memory: '记忆维护', social: '已授权主动联系', memory_reflection: '自主候选整理', affect_sampling: '情绪时间采样' };
  const skipReasons={learning_paused:'学习已暂停',disabled_budget_or_interval:'尚未到间隔或已到请求上限',no_new_eligible_source_or_idle_session:'尚无符合条件的新来源或空闲会话',required_context_exceeds_budget:'必要资料超过预算，本次未调用模型',source_set_already_processed:'这些来源已经整理过',api_pmm_a_required:'需要配置在线心理推理模型'};
  let key = '', state = {};
  function prepare(ctx) { const k = `${ctx.personaId}:${ctx.source}:${ctx.epoch}`; if (k !== key) { key = k; state = {}; } }
  function card(ctx) {
    prepare(ctx);
    const data = state.data, reflection = data?.reflection, cfg = reflection?.settings || {};
    return { id: 'developer_scheduler', domain: 'connections', title: '后台任务与自主候选', size: 'wide', body: `
      <button type="button" class="viz-button" data-scheduler-action="load" ${state.busy || ctx.source !== 'live' ? 'disabled' : ''}>读取后台状态</button>
      <div data-readonly-slot="scheduler_status"><p role="status">${esc(state.message || '')}</p>${data ? `<p>调度：${data.running ? '正在运行' : '未运行'}。每秒检查本地任务条件，模型请求仍由各任务的开关和预算决定。</p>
      <div class="wb-active-jobs">${(data.tasks || []).map(t => `<article><strong>${esc(labels[t.task_id] || '后台任务')}</strong><span>${t.status === 'failed' ? '最近检查失败' : t.status === 'busy' ? '正在处理对话，本次未检查' : '已检查触发条件'}</span><time>${esc(time(t.last_run))}</time>${t.status === 'failed' ? `<small>${esc(t.last_result)}</small>` : ''}</article>`).join('') || '<p>尚无本进程的调度记录。</p>'}</div>
      <p>自主整理：${reflection?.running ? '正在处理' : cfg.enabled ? '等待符合条件的记忆' : '未开启'}；本日已发起 ${reflection?.requests_today || 0} 次。最近结果：${esc(global.DisplayText.state(reflection?.last_result?.status || '尚无记录'))}。</p>
      ${reflection?.last_check?.reason?`<p>最近条件检查：${esc(skipReasons[reflection.last_check.reason]||'未满足整理条件')}。</p>`:reflection?.last_check?.status==='failed'?'<p>最近整理未完成，可查看调用记录与任务详情。</p>':''}` : '<p>读取当前角色的真实后台状态，不触发任务执行。</p>'}</div>
      ${reflection ? `<fieldset class="wb-reflection-settings"><legend>从记忆形成想说的话</legend>
      <p>整理所选会话的有效记忆，以及作者设定中明确的兴趣和目标；设定不会被当成已发生的事件。没有合适话题可以不产生候选，开启不等于允许主动联系。</p>
      <label><input id="reflectionEnabled" type="checkbox" ${cfg.enabled ? 'checked' : ''}/>启用内部候选整理</label>
      <div>${[...new Set((reflection.scopes || []).map(s => s.scope))].map(s => `<label><input type="checkbox" data-reflection-scope="${esc(s)}" ${(cfg.scopes || []).includes(s) ? 'checked' : ''}/>${esc(global.DisplayText.scope(s))}</label>`).join('') || '<p>当前角色尚无会话。</p>'}</div>
      <label>两次机会至少间隔（分钟）<input id="reflectionInterval" type="number" min="30" max="10080" value="${cfg.interval_minutes}"/></label>
      <label>每日最多请求<input id="reflectionDaily" type="number" min="1" max="6" value="${cfg.daily_requests}"/></label>
      <label>输入预算（本地估计）<input id="reflectionInput" type="number" min="500" max="3000" value="${cfg.input_budget}"/></label>
      <label>输出上限<input id="reflectionOutput" type="number" min="100" max="600" value="${cfg.output_tokens}"/></label>
      <p>此版本需配置在线心理推理模型。输入过长时跳过，输出和请求次数均受上限约束。</p>
      <button type="button" class="viz-button" data-scheduler-action="save" ${state.busy || ctx.source !== 'live' ? 'disabled' : ''}>保存自主整理设置</button></fieldset>` : ''}` };
  }
  async function handleClick(target, services) {
    const button = target.closest('[data-scheduler-action]'); if (!button) return false;
    prepare(services.context); if (services.context.source !== 'live' || state.busy) return true;
    const captured = key, action = button.dataset.schedulerAction;
    let body;
    if (action === 'save') {
      if (!state.data?.reflection || !services.guard('/api/memory-reflection/settings')) return true;
      body = { persona_id: services.context.personaId, revision: state.data.reflection.revision, settings: {
        enabled: document.getElementById('reflectionEnabled').checked,
        scopes: [...document.querySelectorAll('[data-reflection-scope]:checked')].map(el => el.dataset.reflectionScope),
        interval_minutes: Number(document.getElementById('reflectionInterval').value),
        daily_requests: Number(document.getElementById('reflectionDaily').value),
        input_budget: Number(document.getElementById('reflectionInput').value), output_tokens: Number(document.getElementById('reflectionOutput').value) } };
    }
    state.busy = true; state.message = '正在处理…'; services.render();
    try {
      const env = body ? await services.adapter.postJson('/api/memory-reflection/settings', body) : await services.adapter.fetchJson('/api/scheduler');
      if (captured !== key || !services.isCurrent()) return true;
      if (env.status !== 'success') throw new Error(env.error || '处理失败');
      if (body) { state.data.reflection = env.data; state.message = '设置已保存；主动联系权限保持独立。'; }
      else { state.data = env.data; state.message = '已读取当前后台状态。'; }
    } catch (err) { if (captured === key && services.isCurrent()) state.message = String(err.message || err); }
    finally { if (captured === key) { state.busy = false; if (services.isCurrent()) services.remount(); } }
    return true;
  }
  global.SchedulerView = { card, handleClick };
})(window);
