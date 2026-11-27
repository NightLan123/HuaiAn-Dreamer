/* Actual saved samples; explicit reads only, no interpolation or model execution. */
(function(global){
  'use strict';
  const esc=v=>global.PsychViz.escape(v??''), num=v=>global.PsychViz.number(v);
  let key='',panels={};
  function prepare(ctx,id){const next=`${ctx.personaId}:${ctx.source}:${ctx.epoch}`;if(next!==key){key=next;panels={};}return panels[id]||(panels[id]={range:'24h',items:[],streams:[],sequence:0});}
  function graph(s){
    if(!s.loaded)return '<p>读取此时间段已保存的采样记录；不会触发心理计算。</p>';
    if(!s.items.length)return '<p>所选会话和时段没有已记录的采样点。时间采样可在开发端研究工作区开启。</p>';
    const span=Math.max(1,s.to-s.from),points=s.items.map(r=>{
      const x=24+332*(r.at-s.from)/span,v=num(r.affect_observed?.valence),a=num(r.affect_observed?.arousal);
      const title=esc(`${global.formatLocalDisplayTime(r.at)} · ${r.source_kind==='event_observation'?'事件计算':'时间演化'}`);
      return `${v===null?'':`<circle cx="${x}" cy="${66-v*48}" r="2.5" fill="#6e8953"><title>${title} · 愉悦度 ${v}</title></circle>`}${a===null?'':`<circle cx="${x}" cy="${114-a*96}" r="2.5" fill="#df9b52"><title>${title} · 唤醒度 ${a}</title></circle>`}`;
    }).join('');
    return `<svg viewBox="0 0 380 132" role="img" aria-label="所选时间内实际保存的情绪点"><path d="M24 18V114H356M24 66H356" fill="none" stroke="#c8cebd"/>${points}</svg><small>绿：愉悦度 −1～1；橙：唤醒度 0～1。共 ${s.items.length} 点，空档不填补。${s.more?'下方可读更早记录。':''}</small><details><summary>采样时间与来源</summary><p>${esc(global.formatLocalDisplayTime(s.from))} — ${esc(global.formatLocalDisplayTime(s.to))}</p><p>事件计算 ${s.items.filter(r=>r.source_kind==='event_observation').length} 点；时间演化 ${s.items.filter(r=>r.source_kind==='model_time_evolution').length} 点。均为模型记录。</p></details>`;
  }
  function html(ctx,id='psych',range){
    const s=prepare(ctx,id);
    if(range&&range!==s.range){s.range=range;s.loaded=false;s.items=[];s.more=false;s.sequence++;s.busy=false;}
    const button=(a,t)=>`<button type="button" class="viz-button" data-sample-action="${a}" data-sample-panel="${id}" ${s.busy||ctx.source!=='live'?'disabled':''}>${t}</button>`;
    return `<div data-readonly-slot="samples_${id}"><div data-sample-view="${id}">${id==='psych'?button('24h','24 小时')+button('7d','7 天'):''}
      ${s.streams.length?`<label>会话<select data-sample-select="${id}">${s.streams.map(r=>`<option value="${esc(r.key)}" ${r.key===s.stream?'selected':''}>${esc(global.DisplayText.scope(r.scope))} · ${esc(global.DisplayText.person(r.person))}${r.session_id?' · '+esc(r.session_id.slice(0,6)):''}</option>`).join('')}</select></label>`:''}
      ${button('load',s.busy?'正在读取…':'读取采样')}<p role="status">${esc(s.error||'')}</p>${graph(s)}${s.more?button('more','读取更早采样'):''}</div></div>`;
  }
  function card(ctx){return {id:'psych_saved_samples',domain:'emotion',title:'情绪随时间变化 · 已保存采样',size:'wide',body:html(ctx)};}
  function handleChange(target){const id=target.dataset.sampleSelect;if(!id||!panels[id])return false;const s=panels[id];s.stream=target.value;s.loaded=false;s.items=[];s.more=false;s.sequence++;s.busy=false;return true;}
  async function read(services,id,range,more=false){
    const s=prepare(services.context,id);if(services.context.source!=='live'||s.busy)return;
    if(range)s.range=range;
    const captured=key,seq=++s.sequence,current=()=>key===captured&&s.sequence===seq&&services.isCurrent();
    if(!more){s.from=Date.now()/1000-(s.range==='7d'?7:1)*86400;s.to=Date.now()/1000;s.items=[];s.more=false;s.loaded=false;}
    s.busy=true;s.error='';services.render();
    try{
      if(!s.streams.length){const env=await services.adapter.fetchJson('/api/affect/sampling');if(!current())return;if(env.status!=='success')throw new Error(env.error||'读取会话失败');s.streams=env.data.streams||[];}
      if(!s.streams.some(r=>r.key===s.stream))s.stream=(s.streams.find(r=>r.scope===services.context.scope)||s.streams[0])?.key;
      if(!s.stream){s.loaded=true;return;}
      const env=await services.adapter.fetchJson('/api/affect/samples?'+new URLSearchParams({stream_key:s.stream,from:s.from,to:s.to,offset:more?s.items.length:0,limit:1000}));
      if(!current())return;if(env.status!=='success')throw new Error(env.error||'读取采样失败');
      const all=more?[...s.items,...env.data.items]:env.data.items;s.items=[...new Map(all.map(r=>[r.id,r])).values()];s.more=env.data.has_more;s.loaded=true;
    }catch(err){if(current())s.error=String(err.message||err);}
    finally{if(key===captured&&s.sequence===seq){s.busy=false;if(services.isCurrent())services.render();}}
  }
  async function handleClick(target,services){const el=target.closest('[data-sample-action]');if(!el)return false;const action=el.dataset.sampleAction;await read(services,el.dataset.samplePanel,['24h','7d'].includes(action)?action:null,action==='more');return true;}
  global.SampleView={html,card,read,handleClick,handleChange};
})(window);
