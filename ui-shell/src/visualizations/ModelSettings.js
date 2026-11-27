/* The existing configuration endpoint, presented as short editable connection cards. */
(function (global) {
  'use strict';
  const esc = v => global.PsychViz.escape(v ?? '');
  const protocols = { ollama: '本地 Ollama', chat_completions: 'OpenAI 兼容接口', responses: 'OpenAI Responses', anthropic: 'Anthropic', gemini: 'Gemini', azure_chat: 'Azure OpenAI' };
  const headings = { general: '对话模型', A: 'PMM-A · 理解与评价', B: 'PMM-B · 内部讨论', qq: 'QQ 连接' };
  const descriptions = { general: '理解用户的语言，并组织最终回复。', A: '根据事件与当前人格进行心理评价。', B: '围绕当前情境形成不同立场并进行内部讨论。它与 Learned-PMM 数值模型是不同部分。' };
  const choices = (values, selected) => Object.entries(values).map(([value, title]) => `<option value="${esc(value)}" ${String(selected) === value ? 'selected' : ''}>${esc(title)}</option>`).join('');
  const input = (key, title, value, type = 'text', hint = '') => `<label>${esc(title)}<input data-connection-field="${key}" type="${type}" value="${esc(value)}" ${hint ? `placeholder="${esc(hint)}"` : ''} ${type === 'password' ? 'autocomplete="new-password"' : ''}/></label>`;
  const select = (key, title, values, selected) => `<label>${esc(title)}<select data-connection-field="${key}">${choices(values, selected)}</select></label>`;
  const checkbox = (key, title, checked) => `<label class="connection-check"><input type="checkbox" data-connection-field="${key}" ${checked ? 'checked' : ''}/> ${esc(title)}</label>`;
  function config(env, role) { const c = env.characterProfile?.data?.config || {}; return role === 'general' ? c : role === 'A' ? c.pmm?.api || {} : c.pmm281?.b_api || {}; }
  function status(env, role) {
    if (role === 'general') return env.connections?.data?.nodes?.general_llm?.status;
    return env.decisions?.data?.observability?.api_status?.connections?.[role]?.status;
  }
  function connection(env, role, mode) {
    const c = config(env, role), all = env.characterProfile?.data?.config || {}, shared = role === 'B' && all.pmm281?.b_share_a === true;
    return { id: `${mode}_connection_${role}`, domain: 'connections', title: headings[role], size: 'wide', body: `<form class="connection-form" data-connection-role="${role}" autocomplete="off">
      <header><p>${descriptions[role]}</p><span data-readonly-slot="connection_status_${role}" class="connection-status">${esc(global.DisplayText.state(status(env, role)))}</span></header>
      ${role === 'B' ? checkbox('b_share_a', '与 PMM-A 共用地址、模型和密钥', shared) : ''}
      <p class="connection-shared-note" ${shared ? '' : 'hidden'}>当前使用 PMM-A 的连接，无需重复填写。取消勾选后可独立设置。</p>
      <div class="connection-service-fields" ${shared ? 'hidden' : ''}><div class="connection-grid">
        ${select('provider', '连接方式', protocols, c.provider || 'ollama')}
        ${input('model', '模型名称', c.model || '', 'text', '填写服务商提供的模型名称')}
        ${input('base_url', '服务地址', c.base_url || '', 'url', '填写你的模型服务地址')}
        ${input('api_key', '密钥', '', 'password', c.has_api_key ? '已保存；留空保留' : '云服务填写密钥，本地通常留空')}
      </div><p class="connection-caption">地址更换到其他服务商时，请重新填写密钥。</p></div>
      <details class="connection-advanced"><summary>高级设置</summary><div class="connection-grid">
        ${input('timeout', '等待上限（秒）', c.timeout ?? 120, 'number')}
        ${input('max_output_tokens', '单次输出上限（Token）', c.max_output_tokens ?? 4096, 'number')}
        ${select('thinking_mode', '模型思考', { auto: '自动', default: '模型默认', on: '开启', off: '关闭', low: '低强度', high: '高强度' }, c.thinking_mode || 'auto')}
        ${select('auth_mode', '鉴权方式', { auto: '自动', bearer: 'Bearer', 'x-api-key': 'Anthropic 密钥', 'api-key': 'Azure 密钥', 'x-goog-api-key': 'Google 密钥', none: '无需鉴权' }, c.auth_mode || 'auto')}
      </div>${checkbox('clear_key', '清除已保存的密钥', false)}<p class="connection-caption">其他既有参数保持原值。特殊协议设置可在<a href="/legacy" target="_blank" rel="noopener">完整设置</a>中调整。</p></details>
      <footer><button type="submit" class="viz-button connection-primary">保存配置</button><button type="button" class="viz-button" data-connection-probe="${role}">保存并检查连接</button>${['A','B'].includes(role) ? `<button type="button" class="viz-button" data-connection-probe="${role}" data-operation="invoke">保存并试用${role === 'A' ? '事件评价' : '方案协商'}</button>` : ''}<span class="connection-feedback" role="status" aria-live="polite"></span></footer>
    </form>` };
  }
  function qq(env, mode) {
    const c = env.characterProfile?.data?.config?.qq || {};
    return { id: `${mode}_connection_qq`, domain: 'connections', title: 'QQ 连接与接收范围', size: 'wide', body: `<form class="connection-form" data-connection-role="qq" autocomplete="off"><header><p>填写机器人连接信息，并选择允许接收的联系人与群聊。</p><span data-readonly-slot="connection_status_qq" class="connection-status">${esc(global.DisplayText.state(env.connections?.data?.nodes?.qq_channel?.status))}</span></header>${checkbox('enabled', '启用 QQ 连接', c.enabled)}<div class="connection-grid">${input('api_url', '机器人服务地址', c.api_url || '', 'url')}${input('self_id', '机器人 QQ 号', c.self_id || '')}${input('api_token', '访问令牌', '', 'password', c.has_api_token ? '已保存；留空保留' : '按机器人服务配置填写')}${input('allowed_users', '允许私聊的 QQ 号', (c.allowed_users || []).join('，'), 'text', '多个号码用逗号分隔')}${input('allowed_groups', '允许接收的群号', (c.allowed_groups || []).join('，'), 'text', '多个号码用逗号分隔')}</div>${checkbox('group_mention_only', '群聊仅在被提及时回应', c.group_mention_only !== false)}<details class="connection-advanced"><summary>事件认证与密钥管理</summary><div class="connection-grid">${input('inbound_token', '事件访问令牌', '', 'password', c.has_inbound_token ? '已保存；留空保留' : '选填')}${input('hmac_secret', '事件签名密钥', '', 'password', c.has_hmac_secret ? '已保存；留空保留' : '选填')}</div>${checkbox('clear_key', '清除机器人访问令牌', false)}</details><footer><button type="submit" class="viz-button connection-primary">保存配置</button><button type="button" class="viz-button" data-connection-probe="qq">保存并检查连接</button><button type="button" class="viz-button" id="btnFetchQqWebhookUrl">获取事件回调地址</button><span class="connection-feedback" id="connProbeFeedback" role="status" aria-live="polite"></span></footer></form>` };
  }
  function cards(env, mode, page) {
    if (page === 'qq_conn') return [qq(env, mode)];
    return (page === 'pmm_sys' ? ['A', 'B'] : ['general', 'A', 'B']).map(role => connection(env, role, mode));
  }
  function change(el) {
    const form = el.closest('.connection-form'); if (!form) return false;
    const shared = form.querySelector('[data-connection-field="b_share_a"]')?.checked || false;
    const fields = form.querySelector('.connection-service-fields'), note = form.querySelector('.connection-shared-note');
    if (fields) fields.hidden = shared;
    if (note) note.hidden = !shared;
    form.querySelector('.connection-feedback').textContent = '有未保存的修改';
    return true;
  }
  function patch(form) {
    const role = form.dataset.connectionRole, value = key => form.querySelector(`[data-connection-field="${key}"]`)?.value.trim() || '', checked = key => !!form.querySelector(`[data-connection-field="${key}"]`)?.checked;
    if (role === 'qq') return { qq: { enabled: checked('enabled'), api_url: value('api_url'), self_id: value('self_id'), api_token: checked('clear_key') ? '' : value('api_token') || null, inbound_token: value('inbound_token') || null, hmac_secret: value('hmac_secret') || null, allowed_users: value('allowed_users').split(/[,，\s]+/).filter(Boolean), allowed_groups: value('allowed_groups').split(/[,，\s]+/).filter(Boolean), group_mention_only: checked('group_mention_only') } };
    const shared = role === 'B' && checked('b_share_a');
    const p = {};
    // A shared B connection retains its independent settings for a later switch.
    for (const key of ['provider', 'base_url', 'model', 'auth_mode']) if (!shared) p[key] = value(key);
    if (!shared && (!p.base_url || !p.model)) throw new Error('请填写服务地址和模型名称。');
    if (!shared) p.api_key = checked('clear_key') ? '' : value('api_key') || null;
    for (const key of ['timeout', 'max_output_tokens']) { const n = Number(value(key)); if (!Number.isFinite(n) || (key === 'timeout' ? n < 10 || n > 300 : !Number.isInteger(n) || n < 256 || n > 131072)) throw new Error('等待上限为 10–300 秒；输出上限为 256–131072 个 Token。'); p[key] = n; }
    p.thinking_mode = value('thinking_mode');
    return role === 'general' ? p : role === 'A' ? { pmm: { api: p } } : { pmm281: { b_share_a: shared, b_api: p } };
  }
  async function save(form, probe, services) {
    if (form.dataset.saving === 'true') return;
    const role = form.dataset.connectionRole, feedback = form.querySelector('.connection-feedback');
    if (!services.guard(feedback)) return;
    let body;
    try { body = patch(form); } catch (e) { feedback.textContent = e.message; return; }
    const epoch = services.context();
    const current = () => epoch === services.context();
    form.dataset.saving = 'true'; form.inert = true; feedback.textContent = '正在保存…';
    try {
      const res = await services.post('/api/config', body);
      if (!current()) return;
      if (res.status !== 'success') { feedback.textContent = '保存失败：' + (res.error || '请稍后重试'); return; }
      const saved = role === 'general' ? res.data : role === 'A' ? res.data?.pmm?.api : role === 'B' ? res.data?.pmm281?.b_api : res.data?.qq;
      form.querySelectorAll('input[type="password"]').forEach(el => { el.value = ''; el.placeholder = saved?.['has_' + el.dataset.connectionField] ? '已保存；留空保留' : '尚未保存密钥'; });
      const clear = form.querySelector('[data-connection-field="clear_key"]'); if (clear) clear.checked = false;
      services.invalidate(role);
      feedback.textContent = '配置已保存';
      if (probe) {
        const invoke = probe === 'invoke';
        feedback.textContent = invoke ? '正在用示例事件执行实际任务…' : '配置已保存，正在检查连接…';
        const ep = role === 'general' ? '/api/test-model' : role === 'qq' ? '/api/qq/test' : '/api/pmm281/connection';
        const result = await services.post(ep, ['A', 'B'].includes(role) ? { role, operation: invoke ? 'invoke' : 'connect' } : {}, role === 'qq' ? 30000 : (Number(body.timeout || body.pmm?.api?.timeout || body.pmm281?.b_api?.timeout || 120) + 5) * 1000);
        if (!current()) return;
        const ok = result.status === 'success' && result.data?.ok !== false;
        services.probed(role, ok);
        feedback.textContent = ok ? (invoke ? '示例任务已通过实际输出校验。' : '服务连接检查通过。') : '检查未通过。' + (result.data?.failure_reason || result.error || '请检查地址、模型和密钥。');
      }
      if (current()) await services.refresh();
    } catch (_) { if (current()) feedback.textContent = '操作未完成，请查看连接状态后重试。'; }
    finally { form.inert = false; delete form.dataset.saving; }
  }
  global.ModelSettings = { cards, change, save };
})(window);
