/* Session presentation and in-memory drafts. Backend writes stay in the controller. */
(function (global) {
  'use strict';
  const esc = v => global.PsychViz.escape(v ?? '');
  const time = v => v ? global.formatLocalDisplayTime(v) : '时间未提供';
  const threads = new Map();
  let latest = null;
  const key = ctx => JSON.stringify([ctx.personaId, ctx.source, ctx.sessionId || '']);
  function thread(ctx) {
    const k = key(ctx);
    if (!threads.has(k)) threads.set(k, { draft: '', active: false, status: 'idle', job_id: null, error: null, messageEnvelope: null, messageError: null, scroll: null });
    return threads.get(k);
  }
  const statusText = t => ({ idle: '可以开始一段对话', creating: '正在准备新会话…', submitting: '正在提交消息…', queued: '消息已排队，等待处理…', running: '正在处理这条消息…', done: '处理完成，回复以实际消息记录为准。', failed: '此次处理失败，草稿已保留。', error: '此次处理失败，草稿已保留。', timeout: '暂未取得最终结果。可继续查看进度，无需重复发送。', observation_paused: '后台处理结果尚未确认，可继续查看进度。', pending: '暂未取得最终结果，可继续查看进度。' }[t.status] || '正在等待处理结果…');
  function options(env, ctx) {
    const rows = (env.characterProfile?.data?.sessions || []).filter(s => s.scope === 'private:web:owner');
    if (ctx.sessionId && !rows.some(s => s.id === ctx.sessionId)) rows.unshift({ id: ctx.sessionId });
    return rows.length ? rows.map((s, i) => `<option value="${esc(s.id)}" ${s.id === ctx.sessionId ? 'selected' : ''}>${esc(s.title || s.name || (s.created_at ? time(s.created_at) : `对话 ${i + 1}`))}</option>`).join('') : '<option value="">尚无会话，发送时创建</option>';
  }
  function messageHtml(env, ctx, messages) {
    const t = thread(ctx), name = env.characterProfile?.data?.name || '角色';
    if (ctx.source !== 'live') return '<div class="parlor-empty">演示模式不发送真实消息。切换到 LIVE 后可继续会话。</div>';
    const notice = t.messageError ? `<p class="life-warning">本次历史读取失败${messages.length ? '，保留已读取的记录' : ''}：${esc(t.messageError)}</p>` : '';
    return notice + (messages.length ? messages.map((m, i) => `<article class="parlor-message ${m.role === 'user' ? 'from-user' : m.role === 'assistant' ? 'from-character' : 'from-system'}"><header><strong>${esc(m.role === 'user' ? '你' : m.role === 'assistant' ? name : m.role || '未提供角色')}</strong><time>${esc(time(m.created_at))}</time></header><div class="parlor-bubble">${esc(m.content)}</div><button type="button" class="parlor-message-detail" data-psych-detail="parlor-message" data-detail-id="${esc(m.id ?? JSON.stringify([m.created_at, m.role, i]))}">记录详情</button></article>`).join('') : `<div class="parlor-empty"><span>在这里，慢慢说。</span><p>${ctx.sessionId ? '当前尚无已读取的消息。' : '写下第一句话，开始与角色的对话。'}</p></div>`);
  }
  function cards(env, mode, ctx, messages) {
    latest = { env, ctx: { ...ctx }, messages };
    const t = thread(ctx), profile = env.characterProfile?.data || {}, emotion = env.emotion?.data || {}, fast = emotion.fast_emotion;
    const known = ['success', 'empty'].includes(env.emotion?.status) && fast?.known === true && global.PsychViz.number(fast.valence) !== null && global.PsychViz.number(fast.arousal) !== null;
    const mood = known ? `愉悦度 ${Number(fast.valence).toFixed(2)} · 唤醒度 ${Number(fast.arousal).toFixed(2)}` : '当前心境尚待观察';
    return [{ id: `${mode}_parlor_room`, domain: 'profile', title: '会客室', size: 'wide', body: `<div class="parlor-room"><aside class="parlor-presence"><img src="/public/assets/decorations/card_parlor_window.png" alt="夏日窗边的会客室" class="parlor-window"/><div data-readonly-slot="parlor_presence"><span class="parlor-name-mark" aria-hidden="true">${esc((profile.name || '客').slice(0, 1))}</span><h3>${esc(profile.name || '未命名角色')}</h3><p class="parlor-mood">${esc(mood)}</p><details><summary>关于角色</summary><p class="parlor-profile">${esc(profile.summary || '尚未填写角色介绍。')}</p></details></div><p class="parlor-media-note">当前支持文字对话。图片、语音与视频尚未开放。</p></aside><section class="parlor-conversation"><header class="parlor-session-tools"><label>会话<select id="selectParlorSession">${options(env, ctx)}</select></label><span id="parlorSessionBadge">${ctx.sessionId ? '独立会话' : '待创建'}</span><button type="button" class="viz-button" id="btnNewParlorSession">新对话</button><button type="button" class="viz-button" id="btnRefreshParlorMessages">刷新历史</button></header><div id="parlorChatHistoryBox" data-readonly-slot="parlor_messages" class="parlor-history" role="log" aria-label="当前会话消息" aria-live="off">${messageHtml(env, ctx, messages)}</div><div class="parlor-composer"><label class="parlor-compose-label" for="inputParlorMessage">说些什么</label><textarea id="inputParlorMessage" rows="3" placeholder="写给${esc(profile.name || '角色')}…" ${t.active ? 'disabled' : ''}>${esc(t.draft)}</textarea><div class="parlor-compose-actions"><button type="button" id="btnFillParlorDemoText" class="parlor-quiet-button">填入示例问候</button><span>Ctrl / ⌘ + Enter 发送</span><button type="button" class="parlor-send" id="btnSendParlorChat" ${t.active || (t.job_id && ['pending', 'timeout', 'observation_paused'].includes(t.status)) ? 'disabled' : ''}>${t.active ? '处理中…' : '发送'}</button></div><div class="parlor-status-row"><p id="parlorSendStatus" role="status" aria-live="polite">${esc(statusText(t))}</p><button type="button" class="life-link" data-psych-detail="parlor-job" data-detail-id="current">处理详情</button><button type="button" class="viz-button" id="btnResumeParlorJob" ${!t.job_id || t.active || !['timeout', 'pending', 'observation_paused'].includes(t.status) ? 'hidden' : ''}>继续查看进度</button></div></div></section></div>` }];
  }
  function syncControls(root) {
    if (!latest) return; const { env, ctx } = latest, t = thread(ctx);
    const select = root.querySelector('#selectParlorSession'); if (select) { const html = options(env, ctx); if (select.innerHTML !== html) select.innerHTML = html; select.value = ctx.sessionId || ''; select.disabled = !!t.creating; }
    const input = root.querySelector('#inputParlorMessage'); if (input) { if (input.value !== t.draft) input.value = t.draft; input.disabled = t.active; }
    const send = root.querySelector('#btnSendParlorChat'); if (send) { send.disabled = t.active || !!(t.job_id && ['pending', 'timeout', 'observation_paused'].includes(t.status)); send.textContent = t.active ? '处理中…' : '发送'; }
    const resume = root.querySelector('#btnResumeParlorJob'); if (resume) resume.hidden = !t.job_id || t.active || !['pending', 'timeout', 'observation_paused'].includes(t.status);
    const feedback = root.querySelector('#parlorSendStatus'); if (feedback) feedback.textContent = t.notice || statusText(t);
    const create = root.querySelector('#btnNewParlorSession'); if (create) create.disabled = !!t.creating;
    const badge = root.querySelector('#parlorSessionBadge'); if (badge) badge.textContent = ctx.sessionId ? '独立会话' : '待创建';
  }
  function detail(kind, id) {
    if (!latest || !kind.startsWith('parlor-')) return null;
    const { ctx, messages } = latest, t = thread(ctx);
    if (kind === 'parlor-job') return { id: t.job_id || '', title: '会话处理详情', envelope: t.jobEnvelope || t.submitEnvelope, updated_at: t.job?.updated_at || t.job?.created_at || null, description: '任务完成与消息送达分别记录。等待超时只表示界面未取得最终结果，不表示角色选择沉默。', fields: [{ label: '会话', value: ctx.sessionId }, { label: '状态', value: statusText(t) }, { label: '错误', value: t.error }, { label: '耗时（毫秒）', value: t.elapsed_ms }], raw: { job: t.job, job_id: t.job_id, status: t.status } };
    const m = messages.find((m, i) => String(m.id ?? JSON.stringify([m.created_at, m.role, i])) === id);
    return m ? { id: m.id || id, title: '消息记录', envelope: t.messageEnvelope, updated_at: m.created_at, fields: [{ label: '角色', value: m.role }, { label: '会话', value: m.session_id }, { label: '关联回合', value: m.turn_id }, { label: '原文', value: m.content }], raw: m.raw || m } : null;
  }
  function handleChange(el) { if (el.id !== 'inputParlorMessage' || !latest) return false; thread(latest.ctx).draft = el.value; return true; }
  function observeMessages(ctx, result) { const t = thread(ctx); t.messageError = result.ok ? null : result.error; t.messageEnvelope = result.envelope; }
  global.ParlorView = { cards, thread, detail, syncControls, handleChange, observeMessages, statusText, messageHtml };
})(window);
