(function(global){
  'use strict';
  const esc=v=>global.PsychViz.escape(v??'');
  function html(){return '<div id="notificationRecords"><button type="button" class="viz-button" data-notification-action="load">读取站内通知</button><p>仅显示更新后实际产生的任务、连接和待复核记录。</p></div>';}
  async function handleClick(target,services){
    const button=target.closest('[data-notification-action]');if(!button)return false;
    const root=document.getElementById('notificationRecords');if(!root||root.dataset.busy||services.context.source!=='live')return true;
    root.dataset.busy='true';button.disabled=true;
    try{
      if(button.dataset.notificationAction==='read'){
        if(!services.guard('/api/notifications/read'))return true;
        const result=await services.adapter.postJson('/api/notifications/read',{persona_id:services.context.personaId,ids:[button.dataset.notificationId]});
        if(result.status!=='success')throw new Error(result.error||'标记失败');
      }
      const offset=button.dataset.notificationOffset||'0',env=await services.adapter.fetchJson('/api/notifications?'+new URLSearchParams({offset,limit:50}));
      if(!services.isCurrent()||!root.isConnected)return true;
      if(env.status!=='success')throw new Error(env.error||'读取失败');
      root.innerHTML=`<p>${env.data.unread} 条未读</p>${env.data.items.map(r=>`<article><strong>${esc(r.title)}</strong><time>${esc(global.formatLocalDisplayTime(r.created_at))}</time>${r.read_at?' · 已读':`<button type="button" class="viz-button" data-notification-action="read" data-notification-id="${esc(r.id)}" data-notification-offset="${offset}">标为已读</button>`}<details><summary>来源标识</summary><code>${esc(r.source_id)}</code></details></article>`).join('')||'<p>暂无实际通知。</p>'}${Number(offset)>0?`<button type="button" data-notification-action="load" data-notification-offset="${Math.max(0,Number(offset)-50)}">上一页</button>`:''}${env.data.has_more?`<button type="button" data-notification-action="load" data-notification-offset="${Number(offset)+50}">下一页</button>`:''}<button type="button" data-notification-action="load">刷新</button>`;
    }catch(err){if(services.isCurrent()&&root.isConnected){let p=root.querySelector('[role=status]');if(!p){p=document.createElement('p');p.role='status';root.append(p);}p.textContent=String(err.message||err);}}
    finally{delete root.dataset.busy;button.disabled=false;}
    return true;
  }
  global.NotificationView={html,handleClick};
})(window);
