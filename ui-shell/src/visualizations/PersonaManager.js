/* Role lifecycle uses the original package and subject APIs. */
(function (global) {
  'use strict';
  const esc = global.escapeHtml;
  let busy = false;
  const field = (label, html) => `<label style="display:grid;gap:6px;margin:10px 0;">${label}${html}</label>`;
  function render(env) {
    const p = env.characterProfile?.data || {}, catalog = p.personas_catalog || [], trash = p.personas_trash || [];
    return `<div data-persona-manager="${esc(p.id || '')}" style="display:grid;gap:16px;">
      <p>每位角色拥有独立的设定、记忆和经历。当前角色：<strong>${esc(p.name || '尚未读取')}</strong></p>
      <div style="display:grid;gap:8px;">${catalog.map(r => `<div class="wb-toolbar" style="justify-content:space-between;">
        <strong>${esc(r.name)}</strong><span>${r.id === p.id ? '当前角色' : `<button type="button" class="viz-button" data-switch-persona="${esc(r.id)}">切换</button>`}
        <button type="button" class="viz-button" data-persona-archive="${esc(r.id)}" ${r.id === p.id ? 'disabled title="先切换到另一位角色后再删除"' : ''}>删除</button></span></div>`).join('') || '<p>角色目录尚未读取，请刷新页面后重试。</p>'}</div>
      <p class="wb-caption">删除会移入回收站，保留资料并停止此角色的后台处理。当前角色请先切换后再删除。</p>
      <details open><summary>新建角色</summary>
        ${field('角色名称', '<input id="managerPersonaName" maxlength="60" placeholder="填写角色名称"/>')}
        ${field('背景与设定', '<textarea id="managerPersonaSeed" maxlength="8000" rows="3" placeholder="可以先写简介，创建后继续补充"></textarea>')}
        <button type="button" class="layout-bar-btn save" data-persona-create>创建并切换</button>
      </details>
      <details open><summary>导入与导出</summary>
        <p class="wb-caption">导入已有的槐安人格包会新增并切换角色，不覆盖同名角色。同一身份已存在时会提示；回收站中的角色请直接恢复。</p>
        ${field('选择人格包（JSON，最大 25 MB）', '<input type="file" id="managerPersonaFile" accept=".json,application/json"/>')}
        ${field('导出当前角色', `<select id="managerPersonaScope"><option value="continuity">连续人格包：设定、学习参数、记忆与关系</option><option value="template">角色模板：筛选后的设定与示范</option></select>`)}
        <p class="wb-caption">连续人格包包含可能私密的记忆和人物资料，不含模型密钥或完整聊天记录；模板也不是完全空白的角色。导出只针对上方当前角色。</p>
        <button type="button" class="viz-button" data-persona-export>导出当前角色</button>
      </details>
      <details><summary>回收站（${trash.length}）</summary>
        ${trash.map(r => `<div class="wb-toolbar" style="justify-content:space-between;"><span>${esc(r.name)}</span><button type="button" class="viz-button" data-persona-restore="${esc(r.id)}">恢复角色</button></div>`).join('') || '<p>回收站为空。</p>'}
      </details>
      <div id="personaManagerFeedback" role="status" aria-live="polite"></div>
    </div>`;
  }
  function feedback(message, failed = false) {
    const el = document.getElementById('personaManagerFeedback');
    if (el) { el.textContent = message; el.style.color = failed ? '#B83B2A' : '#3E5626'; }
  }
  async function operate(services, endpoint, body, message) {
    if (busy || !services.guard()) return;
    const ctx = services.context();
    busy = true; services.setBusy(true); feedback('正在处理，请稍候…');
    try {
      const result = await services.adapter.postJson(endpoint, body, 60000);
      if (result.status !== 'success') throw new Error(result.error || '操作未完成');
      const refreshed = await services.changed(ctx);
      feedback(refreshed ? message : `${message}；列表暂未刷新成功，请刷新页面后确认，不要重复提交。`);
    } catch (err) {
      feedback(`${err.message}。若提示超时或连接中断，请先刷新角色目录确认结果，避免重复提交。`, true);
    } finally { busy = false; services.setBusy(false); }
  }
  async function click(target, services) {
    const button = target.closest('[data-persona-create],[data-persona-export],[data-persona-archive],[data-persona-restore]');
    if (!button) return false;
    if (busy || button.disabled) return true;
    const p = services.profile(), ctx = services.context();
    if (!p?.id || document.querySelector('[data-persona-manager]')?.dataset.personaManager !== p.id) { feedback('角色目录已变化，请重新打开管理窗口。', true); return true; }
    if (button.hasAttribute('data-persona-create')) {
      const name = document.getElementById('managerPersonaName').value.trim();
      const seed = document.getElementById('managerPersonaSeed').value;
      if (!name) { feedback('请填写角色名称。', true); return true; }
      await operate(services, '/api/persona/new', { name, seed }, `已创建并切换到「${name}」。`);
    } else if (button.hasAttribute('data-persona-export')) {
      if (!services.guard()) return true;
      const scope = document.getElementById('managerPersonaScope').value;
      busy = true; services.setBusy(true); feedback('正在准备导出…');
      try {
        const result = await services.adapter.fetchJson(`/api/persona/export?scope=${encodeURIComponent(scope)}&persona_id=${encodeURIComponent(p.id)}`, 60000);
        if (result.status !== 'success') throw new Error(result.error || '导出失败');
        if (!services.isCurrent(ctx) || result.data?.profile?.id !== p.id) throw new Error('当前角色已变化，未下载可能属于其他角色的文件');
        const url = URL.createObjectURL(new Blob([JSON.stringify(result.data, null, 2)], { type: 'application/json;charset=utf-8' }));
        const a = document.createElement('a'); a.href = url;
        a.download = `${(p.name || '角色').replace(/[<>:"/\\|?*\x00-\x1f]/g, '_')}_${scope}.json`;
        document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
        feedback('已生成下载文件。');
      } catch (err) { feedback(err.message, true); }
      finally { busy = false; services.setBusy(false); }
    } else {
      const restore = button.hasAttribute('data-persona-restore');
      const id = restore ? button.dataset.personaRestore : button.dataset.personaArchive;
      const row = (restore ? p.personas_trash : p.personas_catalog)?.find(r => r.id === id);
      if (!row) { feedback('角色目录已变化，请重新打开。', true); return true; }
      if (!restore && !global.confirm(`将「${row.name}」移入回收站？\n会停止此角色的后台处理，聊天、记忆和参数保留，可以恢复。`)) return true;
      await operate(services, restore ? '/api/persona/restore' : '/api/persona/delete',
        { id, confirm_name: row.name, expected_active: p.id }, restore ? `已恢复「${row.name}」，可以切换使用。` : `「${row.name}」已移入回收站。`);
    }
    return true;
  }
  async function change(input, services) {
    if (input.id !== 'managerPersonaFile') return false;
    const file = input.files?.[0], ctx = services.context(); input.value = '';
    if (!file || busy) return true;
    try {
      if (file.size > 25000000) throw new Error('文件超过 25 MB');
      const pack = JSON.parse((await file.text()).replace(/^\uFEFF/, ''));
      if (!services.isCurrent(ctx)) throw new Error('当前角色已变化，请重新选择文件');
      if (!pack || typeof pack !== 'object' || !String(pack.format || '').startsWith('persona-package/')) throw new Error('请选择槐安人格包；完整备份不能从此处导入');
      if (!pack.profile?.id || !pack.profile?.name) throw new Error('人格包缺少角色身份或名称');
      const p = services.profile();
      if ([...(p.personas_catalog || []), ...(p.personas_trash || [])].some(r => r.id === pack.profile.id)) throw new Error('此角色已经存在，请切换使用或从回收站恢复；不会覆盖现有角色');
      if (!global.confirm(`导入「${pack.profile.name}」并切换到此角色？`)) return true;
      await operate(services, '/api/persona/import', pack, `已导入并切换到「${pack.profile.name}」。`);
    } catch (err) { feedback(err instanceof SyntaxError ? '文件不是有效的 JSON 人格包。' : err.message, true); }
    return true;
  }
  global.PersonaManager = { render, click, change };
})(window);
