(function (global) {
  'use strict';
  const esc = v => global.PsychViz.escape(v ?? ''), time = v => v ? global.formatLocalDisplayTime(v) : '未记录';
  let key = '', state = {};
  function prepare(ctx) { const k = `${ctx.personaId}:${ctx.source}:${ctx.epoch}`; if (key !== k) { key = k; state = {}; } }
  const button = (action, title) => `<button type="button" class="viz-button" data-research-action="${action}">${title}</button>`;
  function card(ctx) {
    prepare(ctx);
    const data = state.data, sampling = data?.sampling, settings = sampling?.settings, motives = data?.motives || [];
    return { id:'developer_research_operations', domain:'connections', title:'研究记录与受控操作', size:'wide', body:`
      ${button('load','读取研究工作区')}<div data-readonly-slot="research_message"><p role="status">${esc(state.message || '')}</p></div>
      ${data ? `<details><summary>人工研究动机</summary><p>使用独立研究状态，不影响真实对话、主动联系或人格成长。所有修改保存原因与版本。</p>
      <label>会话<select id="researchSession">${data.sessions.map(s=>`<option value="${esc(s.id)}">${esc(global.DisplayText.scope(s.scope))} · ${esc(global.DisplayText.person(s.person))}</option>`).join('')}</select></label>
      <label>现有研究动机<select id="researchMotive"><option value="">新建动机</option>${motives.map(m=>`<option value="${esc(m.motive_id)}">${esc(m.content_anchor.topic)} · ${esc(global.DisplayText.state(m.status))}</option>`).join('')}</select></label>
      <label>话题<input id="researchTopic" maxlength="500"/></label><label>表达目标<input id="researchGoal" maxlength="500"/></label>
      <label>待表达内容<textarea id="researchPoint" maxlength="500"></textarea></label><label>操作原因<input id="researchReason" maxlength="500"/></label>
       ${button('create','创建研究动机')} ${button('revise','保存修订')} ${button('abandon','放弃所选动机')}
       ${button('history','查看所选动机历史')}<div data-readonly-slot="research_history">${historyBody()}</div></details>
      <details><summary>时间采样与已记录观测</summary><p>开启后按原模型推进时间并保存随机状态；不调用语言模型，不修改长期人格。关闭时不补造遗漏的采样点。</p>
      <label><input id="samplingEnabled" type="checkbox" ${settings.enabled?'checked':''}/>开启时间采样</label>
      <label>采样间隔（秒）<input id="samplingInterval" type="number" min="60" max="3600" value="${settings.interval_seconds}"/></label>
      ${sampling.streams.map(s=>`<label><input type="checkbox" data-sample-stream="${esc(s.key)}" ${settings.streams.includes(s.key)?'checked':''}/>${esc(global.DisplayText.scope(s.scope))} · ${esc(global.DisplayText.person(s.person))}</label>`).join('')||'<p>尚无可采样的情绪会话。</p>'}
      ${button('sampling-save','保存采样设置')}<label>读取会话<select id="sampleStream">${sampling.streams.map(s=>`<option value="${esc(s.key)}">${esc(global.DisplayText.scope(s.scope))} · ${esc(global.DisplayText.person(s.person))}</option>`).join('')}</select></label>
      ${button('samples','读取最近观测')}<div data-readonly-slot="research_samples">${sampleBody()}</div></details>
      <details><summary>表达欲链路的离线干预</summary><p>固定历史回合的输入、角色和模型结果，只检查表达欲参与的本地计算路径；不重发消息或调用模型。</p><label>回合标识<input id="researchTurn"/></label>${button('compare','读取固定条件并比较')}<div data-readonly-slot="research_comparison">${state.comparison?`<pre>${esc(JSON.stringify(state.comparison,null,2))}</pre>`:'尚未执行比较。'}</div></details>
      <details><summary>导出研究记录</summary><p>导出所选范围内的版本、状态、贡献指标和模型用量；不含完整私人聊天、提示词或密钥。</p>
      <label>会话范围<select id="researchExportScope">${[...new Set(data.sessions.map(s=>s.scope))].map(s=>`<option value="${esc(s)}">${esc(global.DisplayText.scope(s))}</option>`).join('')}</select></label>
      <label>起始日期<input type="date" id="researchFrom"/></label><label>结束日期<input type="date" id="researchTo"/></label>
      ${[['affect','情绪采样'],['motives','动机变化'],['calls','模型用量'],['runs','回合状态']].map(([v,n])=>`<label><input type="checkbox" data-export-field="${v}" checked/>${n}</label>`).join('')}
      ${button('export','生成并下载记录包')}</details>`:'<p>按需读取当前角色的记录与设置。</p>'}` };
  }
  function sampleBody() {
    const rows = state.samples?.items || [];
    if (!state.samples) return '<p>尚未读取观测。</p>';
    if (!rows.length) return '<p>此会话没有已保存的采样点。</p>';
    const sorted = [...rows].reverse(), start = sorted[0].at, span = Math.max(1, sorted[sorted.length-1].at-start);
    const plot = sorted.map(r=>{
      const v=global.PsychViz.number(r.affect_observed?.valence), a=global.PsychViz.number(r.affect_observed?.arousal);
      return `${v===null?'':`<circle cx="${20+560*(r.at-start)/span}" cy="${100-70*v}" r="3" fill="#6c8d60"><title>${esc(time(r.at))} · 愉悦度 ${v}</title></circle>`}${a===null?'':`<circle cx="${20+560*(r.at-start)/span}" cy="${170-140*a}" r="3" fill="#bf895b"><title>${esc(time(r.at))} · 唤醒度 ${a}</title></circle>`}`;
    }).join('');
    return `<p>${rows.length} 个实际采样点${state.samples.has_more?'；更多记录可按日期导出':''}。绿色为愉悦度，橙色为唤醒度；不连接或填补空档。</p><svg viewBox="0 0 600 190" role="img" aria-label="实际采样点"><path d="M20 20V170H580M20 100H580" fill="none" stroke="#bbc7ad"/>${plot}</svg><p>${esc(time(sorted[0].at))} — ${esc(time(sorted[sorted.length-1].at))}</p><details><summary>采样来源与版本</summary><pre>${esc(JSON.stringify(rows,null,2))}</pre></details>`;
  }
  function handleChange(target) {
    if (target.id!=='researchMotive') return false;
    const m=state.data?.motives.find(v=>v.motive_id===target.value);
    const history=document.querySelector('[data-readonly-slot="research_history"]');state.history=null;if(history)history.innerHTML=historyBody();
    if (!m) {
      for (const id of ['researchTopic','researchGoal','researchPoint','researchReason']) document.getElementById(id).value='';
      return true;
    }
    const session=state.data.sessions.find(s=>s.scope===m.target.scope&&s.person===m.target.person_id);
    if (session) document.getElementById('researchSession').value=session.id;
    document.getElementById('researchTopic').value=m.content_anchor.topic;
    document.getElementById('researchGoal').value=m.intended_expression.intended_goal;
    document.getElementById('researchPoint').value=m.intended_expression.candidate_point_or_question;
    document.getElementById('researchReason').value=m.research_reason||'';
    return true;
  }
  function historyBody() {
    if(!state.history)return '<p>选择动机后可查看实际保存的修订。</p>';
    return `${state.history.items.map(r=>`<article><strong>${esc(time(r.recorded_at))} · ${esc(global.DisplayText.state(r.to_status))}</strong><p>${esc(r.research_change?.reason||r.reason||'首次记录')}</p><details><summary>修订前后内容</summary><pre>${esc(JSON.stringify(r.research_change||{before:r.before,after:r.after},null,2))}</pre></details></article>`).join('')||'<p>尚无保存的变更。</p>'}${state.history.has_more?button('history-more','读取更早记录'):''}`;
  }
  async function handleClick(target, services) {
    const el=target.closest('[data-research-action]'); if (!el) return false;
    prepare(services.context); if (state.busy||services.context.source!=='live') return true;
    const action=el.dataset.researchAction, captured=key;
    let endpoint='/api/research/workspace', body;
    if (['create','revise','abandon'].includes(action)) {
      const session=state.data.sessions.find(s=>s.id===document.getElementById('researchSession').value);
      if (!session) return true;
      const motive=state.data.motives.find(m=>m.motive_id===document.getElementById('researchMotive').value);
      endpoint='/api/pmm283/motives/research';body={persona_id:services.context.personaId,action,revision:state.data.revision,
        scope:session.scope,person:session.person,motive_id:motive?.motive_id,motive_revision:motive?.state_revision,
        topic:document.getElementById('researchTopic').value,intended_goal:document.getElementById('researchGoal').value,
        candidate_point_or_question:document.getElementById('researchPoint').value,reason:document.getElementById('researchReason').value};
    } else if (action==='sampling-save') {
      endpoint='/api/affect/sampling/settings';body={persona_id:services.context.personaId,revision:state.data.sampling.settings.revision,
        settings:{enabled:document.getElementById('samplingEnabled').checked,interval_seconds:Number(document.getElementById('samplingInterval').value),
          streams:[...document.querySelectorAll('[data-sample-stream]:checked')].map(n=>n.dataset.sampleStream)}};
     } else if (action==='history'||action==='history-more') {
       const m=state.data.motives.find(m=>m.motive_id===document.getElementById('researchMotive').value);if(!m)return true;
       const q={scope:m.target.scope,person:m.target.person_id,motive_id:m.motive_id,limit:50};
       if(action==='history-more'&&state.history?.next_cursor)q.cursor=state.history.next_cursor;
       endpoint='/api/pmm283/motives/history?'+new URLSearchParams(q);
     } else if (action==='samples') endpoint='/api/affect/samples?'+new URLSearchParams({stream_key:document.getElementById('sampleStream').value,limit:200});
    else if (action==='compare') {endpoint='/api/research/expressive-drive-compare';body={persona_id:services.context.personaId,turn_id:document.getElementById('researchTurn').value.trim()};}
    else if (action==='export') {
      endpoint='/api/research/export';body={persona_id:services.context.personaId,scope:document.getElementById('researchExportScope').value,
        date_from:document.getElementById('researchFrom').value,date_to:document.getElementById('researchTo').value,
        fields:[...document.querySelectorAll('[data-export-field]:checked')].map(n=>n.dataset.exportField)};
    }
    if (body&&!services.guard(endpoint)) return true;
    state.busy=true;state.message='正在处理…';services.render();let remount=false;
    try {
      const env=body?await services.adapter.postJson(endpoint,body):await services.adapter.fetchJson(endpoint);
      if (key!==captured||!services.isCurrent()) return true;
      if (env.status!=='success') throw new Error(env.error||'处理失败');
      if (action==='load') {state.data=env.data;remount=true;}
      else if (action==='samples') state.samples=env.data;
      else if (action==='compare') state.comparison=env.data;
       else if (action==='history'||action==='history-more') {
         if(document.getElementById('researchMotive')?.value!==env.data.motive_id)return true;
         state.history={...env.data,items:action==='history-more'?[...(state.history?.items||[]),...env.data.items]:env.data.items};
       }
      else if (action==='export') {
        const bytes=Uint8Array.from(atob(env.data.content_base64),c=>c.charCodeAt(0));
        const url=URL.createObjectURL(new Blob([bytes],{type:'application/zip'})),a=document.createElement('a');a.href=url;a.download=env.data.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      } else {
        const fresh=await services.adapter.fetchJson('/api/research/workspace');
        if (key!==captured||!services.isCurrent()) return true;
        if (fresh.status==='success') {state.data=fresh.data;remount=true;} else throw new Error('操作已保存，但刷新失败，请重新读取');
      }
      state.message='已完成所选操作。';
    } catch(err) {if(key===captured&&services.isCurrent())state.message=String(err.message||err);}
    finally {if(key===captured){state.busy=false;if(services.isCurrent())remount?services.remount():services.render();}}
    return true;
  }
  global.ResearchView={card,handleClick,handleChange};
})(window);
