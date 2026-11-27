'use strict';
// 2.8 UI state contains owner-only diagnostics, never General LLM prompt data.
let pmm28Status=null,pmm28Traces=[],pmm28Longitudinal=null;
const $=id=>document.getElementById(id);
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const actionNames={reply:'回答',unknown:'不知道',clarify:'澄清',disagree:'异议',decline:'拒绝',silence:'沉默'};
const titles={modelTraining:['候选、校准与发布','模型训练'],chat:['对话记录','对话'],profiles:['人物与证据','人物'],affectPage:['当前状态','情绪'],expressionPage:['示范与实际表现','语言习惯'],memory:['事件与来源','记忆'],distill:['来源与学习任务','蒸馏'],connections:['General LLM / PMM','模型设置'],qqPage:['连接与消息处理','QQ 设置'],diagnostics:['运行与执行记录','后台诊断记录'],research:['参数与数据管理','数据与版本']};
let state=null,sessionId='',page='chat',busy=false,events=[],memories=[],messages=[],feedbackTurn='',importParsed=false,versions={weights:[],cores:[]},personaRevisions=[];
const APP_VERSION='2.8.3-dev';
let csrfToken='',connectionPromise=null,uiReady=false,refreshSerial=0,panelFailures={},historyMore=false;
let activeOperationReceipt=null;
function requestError(message,path,status=0,code='NETWORK_ERROR',id='',method='GET'){
 const e=new Error(`${message} [${method} ${path} · ${status||'网络'} · ${code}${id?' · '+id:''}]`);
 Object.assign(e,{method,path,status,code,request_id:id});return e;
}
async function connectLocal(force=false){
 if(csrfToken&&!force)return;
 if(connectionPromise)return connectionPromise;
 connectionPromise=(async()=>{
  let r;try{r=await fetch('/api/bootstrap',{credentials:'same-origin',cache:'no-store'});}catch{throw requestError('无法连接本地程序，请检查启动窗口','/api/bootstrap');}
  let v;try{v=await r.json();}catch{throw requestError('本地初始化响应无法解析','/api/bootstrap',r.status,'INVALID_JSON');}
  if(!v||typeof v!=='object')throw requestError('本地初始化响应格式错误','/api/bootstrap',r.status,'INVALID_RESPONSE');
  if(!r.ok)throw requestError(v.error||'本地初始化失败','/api/bootstrap',r.status,v.code,v.request_id);
  const expected=document.querySelector('meta[name="app-build"]')?.content;
  if(v.version!==APP_VERSION||(expected&&/^[a-f0-9]{64}$/.test(expected)&&expected!==v.build_id)){
   csrfToken='';setDataReady(false);throw requestError('页面与后端版本不一致，请重新打开程序首页','/api/bootstrap',409,'FRONTEND_VERSION_MISMATCH');
  }
  if(typeof v.csrf!=='string'||!v.csrf)throw requestError('本地管理会话未建立','/api/bootstrap',r.status,'MISSING_SESSION');
  csrfToken=v.csrf;if(state)state.csrf=csrfToken;
 })();
 try{await connectionPromise;}finally{connectionPromise=null;}
}
async function api(path,body,retried=false){
 const requestOwner=state?.identity?.id;await connectLocal();
 const method=body===undefined?'GET':'POST';
 const options={credentials:'same-origin',cache:'no-store',headers:{'X-App-Client-Version':APP_VERSION}};
 if(body!==undefined)Object.assign(options,{method:'POST',headers:{...options.headers,'Content-Type':'application/json','X-CSRF-Token':csrfToken},body:JSON.stringify(body)});
 let r;try{r=await fetch(path,options);}catch{throw requestError('本地请求未完成，请检查程序是否仍在运行',path,0,'NETWORK_ERROR','',method);}
 let data;try{data=await r.json();}catch{throw requestError('服务响应无法解析',path,r.status,'INVALID_JSON',r.headers?.get('X-Request-ID'),method);}
 if(!data||typeof data!=='object')throw requestError('服务响应格式错误',path,r.status,'INVALID_RESPONSE',r.headers?.get('X-Request-ID'),method);
 if(!r.ok){
  if((r.status===401||data.code==='SESSION_EXPIRED')&&!retried){
   await connectLocal(true);
   if(body===undefined)return api(path,undefined,true);
   throw requestError('会话已重新连接。本次操作未自动重试，请再次保存',path,r.status,'SESSION_RECONNECTED',data.request_id,method);
  }
  const err=requestError(data.error||'请求失败',path,r.status,data.code||'REQUEST_FAILED',data.request_id,method);err.diagnostics=data.diagnostics;throw err;
 }
 if(body!==undefined)recordOperation(path,data,requestOwner);
 return data;
}
const loadingDisabled=new Map(),recoveryControls=new Set(['retryLocal','copyLocalError','exportSource','exportSourceIndex','exportSupport']);
function setDataReady(ready){uiReady=ready;document.querySelectorAll('button,input,select,textarea').forEach(el=>{if(recoveryControls.has(el.id)||el.dataset.view||el.dataset.goto||el.dataset.close)return;if(!ready){if(!loadingDisabled.has(el))loadingDisabled.set(el,el.disabled);el.disabled=true;}else if(loadingDisabled.has(el)){el.disabled=loadingDisabled.get(el);loadingDisabled.delete(el);}});}
function requireReady(){if(!uiReady||!state?.profile)throw new Error('本地数据尚未加载，请使用“重新连接”；当前没有执行编辑或保存。');}
function loadStatus(message,error=false){$('localStatus').textContent=message;$('localStatus').className=error?'error':'muted';}
function panelError(id,error){if($(id))$(id).innerHTML='<p class="error" role="status">'+esc(error.message||String(error))+'</p>';}
function renderSafely(id,fn){try{fn();return true;}catch(err){panelError(id,new Error('此区域渲染失败：'+err.message));return false;}}
function notice(message,error=false){$('notice').textContent=message;$('notice').className=error?'error':'';$('notice').hidden=!message;const dialog=document.querySelector('dialog[open]');if(dialog){let box=dialog.querySelector('.dialog-notice');if(!box){box=document.createElement('p');box.setAttribute('role','status');dialog.querySelector('.dialog-head').after(box);}box.className='dialog-notice'+(error?' error':'');box.textContent=message;box.hidden=!message;}}
function guard(fn){return async e=>{
 const form=e?.type==='submit'?e.target:null;let held=null;
 try{if(form){e.preventDefault();held=takeDraft(form.id);}const b=e?.target?.closest?.('button');if(!recoveryControls.has(b?.id)&&!b?.dataset?.view&&!b?.dataset?.goto&&!b?.dataset?.close)requireReady();await fn(e);updateDraftStatus();}
 catch(err){if(form&&held)formDrafts.set(draftKey(form.id),held);restoreDrafts();notice(err.message,true);showFailureReceipt(err);}
}}
function fmt(n){return typeof n==='number'?n.toFixed(3):'—';}
function date(t){return new Date(t*1000).toLocaleString('zh-CN',{hour12:false});}
function setBusy(on){busy=on;$('sendBtn').disabled=on;$('distillBtn').disabled=on||!importParsed;$('personaSelect').disabled=on;}
function meter(label,value,confidence=1,bipolar=false){
 const known=typeof value==='number'&&Number.isFinite(value)&&confidence!==0,min=bipolar?-1:0,max=1;
 const v=known?Math.max(min,Math.min(max,value)):0,width=known?(bipolar?Math.abs(v)*50:v*100):0,left=bipolar?(v<0?50-width:50):0;
 return `<div class="meter ${known?'':'unknown'} ${bipolar?'bipolar':''}"><div class="meter-label"><span>${esc(label)}</span><strong>${known?value.toFixed(3):'未知'}</strong></div><div class="track" role="meter" aria-label="${esc(label)}" aria-valuemin="${min}" aria-valuemax="1" ${known?`aria-valuenow="${value}"`:'aria-valuetext="未知，尚无证据"'}><div class="fill ${v<0?'negative':''}" style="left:${left}%;width:${width}%"></div>${bipolar?'<i class="zero-marker" aria-hidden="true"></i>':''}</div><div class="meter-range" aria-hidden="true"><span>${min}</span>${bipolar?'<span>0</span>':''}<span>${max}</span></div></div>`;
}
async function refresh(){
 const serial=++refreshSerial;setDataReady(false);loadStatus('正在读取本地人格与历史…');
 let next;
 try{
  next=await api('/api/state');
  if(!next||!next.profile?.id||!next.identity?.id||next.profile.id!==next.identity.id||!Array.isArray(next.sessions)||!next.config||!Array.isArray(next.personas?.items)||!next.state||!next.activity?.emotion||!next.model||!next.interlocutors||!Array.isArray(next.psychology_registry))throw requestError('本地数据响应缺少必要字段','/api/state',200,'INVALID_STATE');
 }catch(err){if(serial===refreshSerial){setDataReady(false);state=null;loadStatus(err.message,true);notice(err.message,true);}throw err;}
 if(serial!==refreshSerial)return;
 const changed=state?.identity?.id!==next.identity.id;state=next;csrfToken=next.csrf||csrfToken;setDataReady(true);
 if(changed){previewTrace281=null;selectedTrace281=null;workspace281=null;learningPolicyDirty=false;learningPreview=null;boundaryHistoryOffset=0;events=[];memories=[];versions={weights:[],cores:[]};personaRevisions=[];messages=[];sessionId='';resetRuntime282();activeOperationReceipt=null;$('operationReceipt').hidden=true;}
 if(!state.sessions.some(s=>s.id===sessionId))sessionId=state.sessions[0]?.id||'';
 let renderFailures=0;const draw=(id,fn)=>{if(!renderSafely(id,fn))renderFailures++;};
 draw('chatLog',renderShell);draw('psychologyPanel',renderProfiles);draw('affectStatus',renderAffect);draw('expressionStatus',renderExpression);draw('dynamicBoundaryList',renderBoundaryModel);draw('synthesisPanel',renderSynthesis);draw('cognitiveList',renderCognition);draw('learningOverview',renderLearning);if(typeof renderUI3==='function')draw('ui3IdentityHero',renderUI3);
 if(changed&&state.config){if(page==='affectPage')fillAffectParameters();if($('traitSeedDialog').open)$('traitSeedDialog').close();if(['connections','qqPage'].includes(page))draw('localStatus',()=>openSettings(false));if(['connections','qqPage','memory','diagnostics'].includes(page))draw('localStatus',fillOperations);}
 const jobs=[['events','/api/events'],['memories','/api/memories'],['versions','/api/pmm/versions'],['revisions','/api/persona/revisions']];
 if(sessionId)jobs.push(['messages','/api/messages?session='+encodeURIComponent(sessionId)]);
 panelFailures={events:new Error('操作记录正在读取…'),memories:new Error('记忆正在读取…'),messages:new Error('此会话历史正在读取…')};historyMore=false;renderChat();renderMemory();
 const results=await Promise.allSettled(jobs.map(async([key,path])=>{const value=await api(path);if(key==='versions'?(!Array.isArray(value.weights)||!Array.isArray(value.cores)):!Array.isArray(value))throw requestError('此区域的数据格式错误',path,200,'INVALID_RESPONSE');return value;}));
 if(serial!==refreshSerial)return;
 $('versionLoadError').textContent='';const failures={};results.forEach((r,i)=>{const key=jobs[i][0];if(r.status==='rejected'){failures[key]=r.reason;return;}if(key==='events')events=r.value;if(key==='memories')memories=r.value;if(key==='versions')versions=r.value;if(key==='revisions')personaRevisions=r.value;if(key==='messages')messages=r.value;});
 if(!sessionId)messages=[];panelFailures=failures;historyMore=!failures.messages&&messages.length===2000;
 draw('trainingPanel',renderResearch);draw('versionLoadError',renderVersions);draw('memoryList',renderMemory);draw('chatLog',renderChat);if(typeof renderUI3==='function')draw('ui3IdentityHero',renderUI3);
 const areas={events:'eventList',memories:'memoryList',versions:'versionLoadError',revisions:'versionLoadError',messages:'chatLog'};
 for(const [key,err] of Object.entries(failures))panelError(areas[key],err);if(failures.versions){$('activateWeights').disabled=true;$('activateCore').disabled=true;}if(failures.revisions)$('rollbackPersona').disabled=true;
 const component=Object.entries(state.component_errors||{});
 if(component.length)notice(component.map(([key,e])=>`${key}：${e.message} · ${e.request_id}`).join('；'),true);
 const failed=Object.keys(failures).length+component.length+renderFailures;
 loadStatus(`本地数据已连接 · ${state.profile.name} · ${state.sessions.length} 个会话${failed?' · '+failed+' 个区域加载失败，可重新连接重试':''}`,failed>0);
 if(page==='profiles')await loadPersonaViews282().catch(e=>{$('personaViewsStatus282').textContent=e.message;});
}
function renderShell(){const p=state.profile;$('personaSelect').innerHTML=state.personas.items.map(i=>`<option value="${esc(i.id)}" ${i.id===state.identity.id?'selected':''}>${esc(i.id===p.id?p.name:i.name)}</option>`).join('');$('subjectName').textContent=p.name;$('identitySummary').textContent=`${state.state.turn_count} 次互动 · 人格修订 ${p.revision}`;$('modelName').textContent=(state.config.model||'大模型待配置')+' · '+(state.config.pmm281.mode==='full'?'完整 PMM':'备用兼容模式');$('connectionDot').className=modelsConfigured()?'ready':'';$('connectionDot').querySelector('span').textContent=modelsConfigured()?'连接已填写 · 请测试':'需要配置模型连接';$('sessions').innerHTML=state.sessions.map(s=>`<button data-session="${esc(s.id)}" class="${s.id===sessionId?'selected':''}">${esc(s.title)}</button>`).join('')||'<p class="empty">还没有对话</p>';
const a=state.affect_state?.emotion||{};$('emotionMeters').innerHTML=affectMeter('效价',a.valence,true)+affectMeter('唤醒',a.arousal)+affectMeter('主导感',a.dominance);$('modelStats').innerHTML=`<p class="muted">${esc(state.model.status)} · ${esc(modeName(state.model.mode))}</p><div class="stat"><span>待训练样本</span><strong>${state.model.pending_samples||0}</strong></div><div class="stat"><span>训练样本</span><strong>${state.model.train_samples}</strong></div><div class="stat"><span>保留样本</span><strong>${state.model.heldout_samples}</strong></div><div class="stat"><span>参数更新</span><strong>${state.model.steps}</strong></div>`;const readonly=state.sessions.find(s=>s.id===sessionId)?.scope.startsWith('group:qq:')||state.sessions.find(s=>s.id===sessionId)?.scope.startsWith('private:qq:');$('message').disabled=!!readonly;$('composeHint').textContent=readonly?'QQ 会话在此查看；请到 QQ 继续交流，或新建本机对话。':'Enter 发送 · Shift + Enter 换行 · 每轮判断可查看并校正';}
function renderChat(){ $('loadEarlierMessages').hidden=!historyMore;if(panelFailures.messages){panelError('chatLog',panelFailures.messages);return;}if(!messages.length){$('chatLog').innerHTML=`<div class="welcome"><div class="mark">◒</div><span class="eyebrow">${esc(state.profile.name.toUpperCase())} / 本机对话</span><h2>开始本机对话</h2><p>${modelsConfigured()?'输入消息即可交流。也可在蒸馏页面导入历史聊天，先预览来源再建立学习任务。':'请先在模型设置中分别配置 General LLM 与 PMM，再测试连接。聊天记录保存在当前主体。'}</p><div><button data-open-settings class="primary">${modelsConfigured()?'检查模型连接':'配置模型连接'}</button><button data-goto="distill">导入聊天蒸馏 →</button></div><button data-new-session class="quiet">新建本机对话</button></div>`;return;}
$('chatLog').innerHTML=messages.map(m=>`<article class="message ${m.role} ${!m.content?'silent':''}"><div class="who">${m.role==='user'?'你':esc(state.profile.name)}</div><div class="bubble">${esc(m.content||'本轮选择沉默 · 没有发送消息')}</div>${m.role==='assistant'?`<div class="message-actions">${turnDuration(m.turn_id)}<button data-trace="${esc(m.turn_id)}">查看机制</button><button data-feedback="${esc(m.turn_id)}">校正表达</button></div>`:''}</article>`).join('');$('chatLog').scrollTop=$('chatLog').scrollHeight;}
const routeAliases={otherPage:['profiles','otherPage'],graphPage:['profiles','graphPage'],learningPage:['distill','learningPage'],mediaPage:['qqPage','qqPage-panel-incoming']};
function showPage(view,tab,focus=true){
 const alias=routeAliases[view];if(alias){view=alias[0];tab=tab||alias[1];}
 if(!titles[view]){notice('页面不存在，已返回对话。',true);view='chat';}
 page=view;stopAffectPolling();if(view==='affectPage')startAffectPolling();
 document.querySelectorAll('.page').forEach(el=>el.classList.toggle('active',el.id===view));
 document.querySelectorAll('nav [data-view]').forEach(el=>{const on=el.dataset.view===view;el.classList.toggle('active',on);el.setAttribute('aria-current',on?'page':'false');});
 $('pageKicker').textContent=titles[view][0];$('pageTitle').textContent=titles[view][1];
 if(tab&&$(tab)?.closest('.page')?.id===view)selectTab(tab);
 if(state?.config){
  if(['connections','qqPage'].includes(view))openSettings(false);
  if(['connections','qqPage','memory','diagnostics'].includes(view))fillOperations();
  if(view==='affectPage'){renderAffect();fillAffectParameters();}
  if(view==='expressionPage'){renderExpression();renderAffect();}
  if(view==='distill'){renderLearning();refreshLearningActivities().catch(e=>notice(e.message,true));}
  if(view==='profiles'){renderOtherLearning();renderLearning();loadBoundaryHistory(true).catch(e=>notice(e.message,true));}
  if(view==='qqPage')refreshSocial().catch(e=>notice(e.message,true));
  if(['connections','modelTraining','affectPage'].includes(view))refresh281().catch(e=>notice(e.message,true));
  if(view==='profiles')loadPersonaViews282().catch(e=>{$('personaViewsStatus282').textContent=e.message;});
  if(view==='modelTraining')refreshPmm28().catch(e=>notice(e.message,true));
  if(view==='diagnostics'){$('qqStatusBtn').onclick();refreshPmm28().catch(e=>notice(e.message,true));}
 }
 restoreDrafts();updateRoute();if(focus)$('pageTitle').focus();
}
async function newSession(){const r=await api('/api/session',{});sessionId=r.id;showPage('chat');await refresh();$('message').focus();}
async function runJob(result,kind){
 if(kind==='learning')return runLearningJob(result);
 const owner=state?.identity?.id;setBusy(true);$('progress').hidden=false;notice(kind==='distill'?'开始蒸馏。任务完成前请保持程序运行。':'');
 try{while(true){
  const j=await api('/api/jobs/'+result.job_id);updateJobOperationReceipt(j,owner);
  $('progress').textContent=(j.phase||'处理中')+' · 已用 '+Math.max(0,Math.floor(Date.now()/1000-(j.started_at||j.created_at)))+' 秒';
  if(kind==='distill')$('distillResult').innerHTML=`<article class="card"><div class="step">正在处理</div><p>${esc(j.phase)}</p></article>`;
  if(j.status==='error'){await refresh();updateJobOperationReceipt(j,owner);const error=new Error(j.error+'（详情见操作历史）');error.operationReceiptHandled=true;throw error;}
  if(j.status==='done'){
   await refresh();updateJobOperationReceipt(j,owner);
   if(kind==='distill'){
    const pending=j.result.learning_job&&j.result.learning_job.status!=='completed';
    $('distillResult').innerHTML=`<article class="card"><div class="step">${pending?'本批已结束，任务尚未全部完成':'蒸馏完成'}</div><h2>新增 ${j.result.report.added} 条来源</h2><p class="muted">接受 ${j.result.report.accepted} 项有引用的判断，拒绝 ${j.result.report.rejected} 项无效或无来源的判断。</p>${pending?`<p>已处理 ${j.result.learning_job.cursor} / ${j.result.learning_job.source_count}，请在学习任务中继续或检查状态。</p>`:''}<button data-goto="distill" data-target-tab="learningPage">查看实际写入与后续任务 →</button></article>`;
    notice(pending?'部分来源已处理，剩余任务可在学习中心继续。':'蒸馏完成，实际写入可在学习中心查看。');
   }else notice(j.result.warning||j.result.message||'');
   return j.result;
  }
  await new Promise(resolve=>setTimeout(resolve,900));
 }}catch(error){error.operationReceiptContext={owner,job_id:result.job_id};throw error;}
 finally{setBusy(false);$('progress').hidden=true;}
}
let pendingWebInput=null;
async function sendMessage(e){e.preventDefault();if(busy)return;const text=$('message').value.trim();if(!text)return;if(!modelsConfigured()){openSettings();return;}if(!sessionId)await newSession();setBusy(true);const key=state.identity.id+':'+sessionId;if(!pendingWebInput||pendingWebInput.key!==key||pendingWebInput.text!==text)pendingWebInput={key,text,id:globalThis.crypto?.randomUUID?.()||Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)};try{const j=await api('/api/chat',{session_id:sessionId,text,client_event_id:pendingWebInput.id});$('message').value='';messages.push({role:'user',content:text});renderChat();await runJob(j,'chat');pendingWebInput=null;}catch(err){$('message').value=text;await refresh();throw err;}finally{setBusy(false);}}
function renderProfiles(){const p=state.profile;$('characterSummary').textContent=`自称：${p.character?.self_reference||'我'} · 初始人格：${p.character?.initial_personality||'尚未设置'} · 基础设定：${p.seed||'尚未设置'}`;renderPsychology();$('selfProfileName').textContent=p.name;$('stylePanel').innerHTML=p.style.count?`<div class="stat"><span>原始表达样本</span><strong>${p.style.count}</strong></div><div class="stat"><span>句长中位数</span><strong>${p.style.median_chars} 字符</strong></div>${meter('极短表达（≤8 字符）比例',p.style.vector[1])}<div>${p.style.short_examples.map(x=>`<span class="tag">${esc(x)}</span>`).join('')}</div>`:'<p class="empty">导入聊天后，风格将从原始表达独立统计。</p>';
const selected=$('otherSelect').value;const choices={...Object.fromEntries((state.learning_center?.other_status||[]).map(x=>[x.key,{name:x.person+' · '+x.scope}])),...state.interlocutors};$('otherSelect').innerHTML=Object.entries(choices).filter(([k,v])=>!$('otherSearch').value||[k,v.name,state.interlocutors[k]?.scope].join(' ').toLowerCase().includes($('otherSearch').value.toLowerCase())).map(([k,v])=>`<option value="${esc(k)}">${esc(v.name)} · ${k.slice(0,6)}</option>`).join('')||'<option value="">尚无对象模型</option>';if(choices[selected]&&[...$('otherSelect').options||[]].some(x=>x.value===selected))$('otherSelect').value=selected;renderOther();$('evidencePanel').innerHTML='<p class="fine">各心理维度的原文依据位于“自身人格”中的来源按钮；旧来源记录保存在主体档案和备份中。</p>'; }
function renderOther(){const p=state.interlocutors[$('otherSelect').value];$('otherPanel').innerHTML=p?`<h3>${esc(p.name)}</h3>${constructHTML(p)}${dyadHTML(state.dyads?.[p.id])}<h3>可修正的偏好与信念</h3>${p.beliefs.slice(-8).map(b=>`<div class="evidence"><p>${esc(b.text)}</p>${b.evidence.map(e=>`<blockquote>${esc(e.quote)}</blockquote>`).join('')}</div>`).join('')||'<p class="empty">暂无足够证据</p>'}<p class="fine">修订 ${p.revision} · ${p.source_records.length} 条来源记录</p>`:'<p class="empty">开始对话，或将历史记录蒸馏到“交谈对象模型”。它与当前 AI 人格分开保存。</p>';}
function renderMemory(){if(panelFailures.memories){panelError('memoryList',panelFailures.memories);return;}const q=$('memorySearch').value.toLowerCase();$('memoryList').innerHTML=memories.filter(m=>m.content.toLowerCase().includes(q)).map(m=>`<article class="memory-item ${m.status==='active'?'':'inactive'}"><div class="row spread"><div><span class="tag">${esc(m.kind)}</span><span class="tag">${esc(m.scope)}</span><span class="tag">${esc(m.status)}</span></div><span class="record-id">${date(m.created_at)}</span></div><p class="memory-content">${esc(m.content)}</p>${memoryStrengthHTML(m)}<div class="row"><button data-memory-edit="${esc(m.id)}">修订</button><button data-memory-toggle="${esc(m.id)}">${m.status==='active'?'停用':'恢复'}</button><button data-memory-sources="${esc(m.id)}">查看原文来源</button>${m.scope!=='self'?`<button data-memory-erase="${esc(m.scope)}">删除来源会话及学习影响…</button>`:''}</div>${m.evidence?`<details><summary>来源与解释</summary><p class="fine">${esc(m.evidence)}</p><p class="fine">${esc(m.interpretation||'')}</p></details>`:''}</article>`).join('')||'<p class="empty">暂无匹配的记忆。</p>';}
function renderResearch(){const m=state.model,metrics=m.metrics||{};$('trainingPanel').innerHTML=`<p class="muted">${esc(m.architecture)}</p><p class="fine">${esc(m.note||'')}</p><p>待训练样本：${m.pending_samples||0}</p><div class="row"><span class="tag">${m.train_samples} 训练样本</span><span class="tag">${m.heldout_samples} 保留样本</span><span class="tag">${m.steps} 次参数更新</span></div><table><thead><tr><th>数据</th><th>重建 MSE</th><th>状态 MSE</th><th>风格 MSE</th><th>行动准确率</th><th>视角 CE</th><th>投影 MSE</th><th>语用 MSE</th></tr></thead><tbody>${[['train','训练集'],['heldout','保留集']].map(([k,label])=>`<tr><td>${label} (${metrics[k]?.n||0})</td><td>${fmt(metrics[k]?.reconstruction_mse)}</td><td>${fmt(metrics[k]?.state_mse)}</td><td>${fmt(metrics[k]?.style_mse)}</td><td>${meter('行动准确率',metrics[k]?.action_accuracy)}</td><td>${fmt(metrics[k]?.perspective_cross_entropy)}</td><td>${fmt(metrics[k]?.projection_mse)}</td><td>${fmt(metrics[k]?.linguistic_mse)}</td></tr>`).join('')}</tbody></table>`;renderEvents();}
function showTrace(id){const t=events.find(e=>e.kind==='turn'&&e.payload.turn_id===id)?.payload;if(!t){notice('这轮超出最近记录范围。完整备份中保留了全部事件。');return;}$('traceTitle').textContent='本轮机制 · '+actionNames[t.decision.action];$('traceBody').innerHTML=`${timingHTML(t)}${traitTraceHTML(t.trait_affect)}${interactionHTML(t.interaction_plan)}<p class="tag">${esc(modeName(t.pmm_mode||'legacy'))} · General ${esc(t.model||'')} · PMM ${esc(t.pmm_model||'')}</p><div class="trace-stage"><h3>1. 先理解消息</h3><p>${esc(t.understanding?.intent||'旧版本记录')}</p></div><div class="trace-stage"><h3>2. 记忆与人格条件</h3><p>检索 ${t.retrieved.length} 条记忆 · 知识门控：${esc(t.decision.gate||'旧版')}</p>${t.retrieved.map(m=>`<details><summary>${esc(m.content.slice(0,70))}</summary>${meter('检索相关度',m.score)}<p>${esc(m.content)}</p><div class="row"><button data-relevant="${esc(m.id)}" data-turn="${esc(id)}">与此轮相关</button><button data-irrelevant="${esc(m.id)}" data-turn="${esc(id)}">不相关</button></div></details>`).join('')}</div>${deliberationHTML(t.deliberation)}<div class="trace-stage"><h3>3. ${t.deliberation?.multi_view?"同一主体的动态倾向":"PMM 单路径综合决策"}</h3>${(t.decision.perspectives||[]).map(v=>`<div class="evidence">${meter('倾向权重',v.weight)}<strong>${esc(v.label)}</strong><p>${esc(v.summary)}</p></div>`).join('')}</div><div class="trace-stage"><h3>4. 程序决定行动</h3><p>${esc(actionNames[t.decision.action])}：${esc(t.decision.reason||'')}</p></div><div class="trace-stage"><h3>5–6. 最终回复回流更新</h3><p>自身资料修订 ${t.self_revision??'—'} · 对象模型修订 ${t.interlocutor_revision??'—'} · 风格预算${t.style?.max_chars||'自然长度'}${t.style_over_budget?'（生成仍超预算，已记录）':''}</p><p>${esc(t.warning||'反馈与经历已保存；生成内容不自动作为外部事实。')}</p></div><details><summary>完整结构化日志</summary><pre>${esc(JSON.stringify(t,null,2))}</pre></details>`;$('traceDialog').showModal();}
function protocolHint(){const hints={ollama:'使用 Ollama 原生 API。先在本机运行并加载模型。',chat_completions:'适用于 OpenAI 兼容服务。模型不支持 JSON 时可关闭原生模式，仍会校验结构化输出。',responses:'Responses 原生协议。程序传入完整上下文，store=false；推理模型通常不发送温度。',anthropic:'Claude 原生 Messages；通过指令要求 JSON 并验证结果，可修复一次。JSON 开关不发送不兼容的 response_format。',gemini:'Gemini 原生 generateContent；API Key 使用请求头传递。',azure_chat:'填写你自己的资源地址和部署名。/openai/v1 无需 api-version；旧部署接口使用版本字段。'};$('protocolHint').textContent=hints[$('provider').value]||'';}
function modeName(mode){return {full:'完整 PMM',api:'API-PMM',learned:'Learned-PMM',legacy:'兼容载入的数值参数'}[mode]||mode;}
function modelsConfigured(){const c=state?.config;if(!c?.model)return false;if(c.pmm281.mode==='full')return !!c.pmm.api.model&&(c.pmm281.b_share_a||!!c.pmm281.b_api.model);return c.pmm.mode!=='api'||!!c.pmm.api.model;}
const paFields={provider:'Provider',base_url:'BaseUrl',model:'ModelInput',auth_mode:'AuthMode',max_output_tokens:'MaxOutputTokens',token_field:'TokenField',temperature:'Temperature',timeout:'Timeout',anthropic_version:'AnthropicVersion',api_version:'ApiVersion'};
function fillPmm(){const c=state.config,m=c.pmm,a=m.api,d=c.deliberation;const co=c.pmm28||{mode:'shadow',long_term_mode:'candidate_only',reasoner_timeout:15};$('pmm28LongMode').value=co.long_term_mode;$('deliberationEnabled').checked=d.enabled;$('deliberationMode').value=d.mode;$('maxPerspectives').value=d.max_perspectives;$('deliberationRounds').value=d.max_rounds;$('unresolvedConflict').checked=d.return_unresolved_conflict;$('pmmMode').value=m.mode==='legacy'?'':m.mode;$('pmmBackend').value=m.backend;$('pmmUrl').value=m.base_url;$('pmmKey').value='';$('pmmKey').placeholder=m.has_api_key?'已保存独立 PMM 密钥；留空保留':'填写 PMM 服务密钥';$('clearPmmKey').checked=false;$('pmmModel').value=m.model;$('pmmTimeout').value=m.timeout;$('onlineLearning').checked=c.online_learning;$('retrievalRounds').value=c.max_retrieval_rounds;$('pmmCheckpoint').textContent='保留的数值权重 SHA256 · '+state.model.checkpoint_sha256;
$('paThinkingMode').value=a.thinking_mode||'auto';$('paThinkingAdapter').value=a.thinking_adapter||'auto';$('paProviderPreset').innerHTML=state.presets.map(p=>`<option value="${esc(p.id)}">${esc(p.label)}</option>`).join('');$('paProviderPreset').value=state.presets.find(p=>p.provider===a.provider&&p.base_url===a.base_url)?.id||'custom';for(const [k,id] of Object.entries(paFields))$('pa'+id).value=a[k];for(const [k,id] of Object.entries({json_mode:'JsonMode',json_repair:'JsonRepair',send_temperature:'SendTemp'}))$('pa'+id).checked=a[k];$('paApiKey').value='';$('paApiKey').placeholder=a.has_api_key?'已保存 API-PMM 密钥；留空保留':'填写 API-PMM 密钥';$('paClearLlmKey').checked=false;$('paExtraHeaders').value='';$('paExtraHeaders').placeholder=a.has_extra_headers?'已保存：'+a.extra_header_names.join(', '):'附加请求头 JSON';$('paExtraBody').value=JSON.stringify(a.extra_body||{},null,2);$('paProtocolHint').textContent='API-PMM 使用与 General LLM 相同的六类协议适配器，配置独立。';pmmFields();fill281();}
function pmmFields(){const mode=$('pmmMode').value,isApi=mode==='api',local=$('pmmBackend').value==='local';const cooperative=state?.config?.pmm28?.mode!=='legacy';$('pmmApiPanel').hidden=!isApi&&!cooperative;$('pmmNumericPanel').hidden=isApi;for(const el of $('pmmApiPanel').querySelectorAll('input,select,textarea,button'))el.disabled=!isApi&&!cooperative;for(const el of $('pmmNumericPanel').querySelectorAll('input,select,textarea,button'))el.disabled=isApi;$('pmmHttpFields').hidden=local;$('pmmModel').readOnly=local||mode==='learned';if(local||mode==='learned')$('pmmModel').value=mode==='learned'?'learned-pmm-v21':'pmm-mlp-v3';$('onlineLearning').disabled=isApi;$('trainPmm').disabled=isApi;$('pmmModeHint').textContent=isApi?'独立 API 负责心理评价、人格与语言蒸馏、状态和记忆更新。无需训练即可使用；样本可带入 Learned-PMM。':mode==='learned'?'实际训练编码、状态转移、视角与表达特征。日常学习只更新个体 Adapter；核心 θ 单独发布版本。':'保留 v0.3 / v0.4 数值模型及其数据。可切换到 API-PMM 或迁移到 Learned-PMM。';}
function openSettings(navigate=true){const c=state.config;$('llmThinkingMode').value=c.thinking_mode||'auto';$('llmThinkingAdapter').value=c.thinking_adapter||'auto';$('generalDiagnostics').hidden=true;$('pmmDiagnostics').hidden=true;$('providerPreset').innerHTML=state.presets.map(p=>`<option value="${esc(p.id)}">${esc(p.label)}</option>`).join('');$('providerPreset').value=state.presets.find(p=>p.provider===c.provider&&p.base_url===c.base_url)?.id||'custom';$('provider').value=c.provider;$('baseUrl').value=c.base_url;$('apiKey').value='';$('apiKey').placeholder=c.has_api_key?'已保存密钥；留空保留':'填写大模型 API Key';$('clearLlmKey').checked=false;$('modelInput').value=c.model;$('jsonMode').checked=c.json_mode;$('jsonRepair').checked=c.json_repair;$('sendTemp').checked=c.send_temperature;$('timeout').value=c.timeout;$('temperature').value=c.temperature;$('authMode').value=c.auth_mode;$('maxOutputTokens').value=c.max_output_tokens;$('tokenField').value=c.token_field;$('anthropicVersion').value=c.anthropic_version;$('apiVersion').value=c.api_version;$('extraHeaders').value='';$('extraHeaders').placeholder=c.has_extra_headers?'已保存：'+c.extra_header_names.join(', ')+'；留空保留':'例如 {"anthropic-beta":"..."}';$('extraBody').value=JSON.stringify(c.extra_body||{},null,2);fillPmm();protocolHint();const q=c.qq;$('qqSelfId').value=q.self_id||'';$('qqEnabled').checked=q.enabled;$('qqUrl').value=q.api_url;$('qqToken').value='';$('qqHmac').value='';$('qqUsers').value=q.allowed_users.join(', ');$('qqGroups').value=q.allowed_groups.join(', ');$('qqMention').checked=q.group_mention_only;$('connectionResult').textContent='大模型 · 尚未执行本次连接测试';$('pmmResult').textContent=state.pmm_start_error||'PMM · 尚未执行本次连接测试';if(navigate)showPage('connections');}
function parseSettingsJSON(id,empty){const raw=$(id).value.trim();if(!raw)return empty;let v;try{v=JSON.parse(raw)}catch{throw new Error('附加请求头或参数不是合法 JSON。')}if(!v||Array.isArray(v)||typeof v!=='object')throw new Error('附加参数应为 JSON 对象。');return v;}
async function saveSettings(){const c={provider:$('provider').value,base_url:$('baseUrl').value.trim(),api_key:$('apiKey').value||($('clearLlmKey').checked?'':null),model:$('modelInput').value.trim(),json_mode:$('jsonMode').checked,json_repair:$('jsonRepair').checked,send_temperature:$('sendTemp').checked,timeout:Number($('timeout').value),temperature:Number($('temperature').value),auth_mode:$('authMode').value,max_output_tokens:Number($('maxOutputTokens').value),token_field:$('tokenField').value,anthropic_version:$('anthropicVersion').value.trim(),api_version:$('apiVersion').value.trim(),extra_headers:parseSettingsJSON('extraHeaders',null),extra_body:parseSettingsJSON('extraBody',{}),thinking_mode:$('llmThinkingMode').value,thinking_adapter:$('llmThinkingAdapter').value};await api('/api/config',c);await refresh();$('apiKey').value='';$('extraHeaders').value='';$('clearLlmKey').checked=false;$('connectionResult').textContent='大模型配置已保存，待测试。';}
async function savePmm(){const mode=$('pmmMode').value,m={mode};if(!['api','learned'].includes(mode))throw new Error('当前载入兼容参数。请明确选择 API-PMM 或 Learned-PMM；尚未修改原配置和权重。');if(mode==='api'||state.config.pmm28?.mode!=='legacy'){const a={};for(const [k,id] of Object.entries(paFields))a[k]=['max_output_tokens','timeout','temperature'].includes(k)?Number($('pa'+id).value):$('pa'+id).value.trim();Object.assign(a,{api_key:$('paApiKey').value||($('paClearLlmKey').checked?'':null),json_mode:$('paJsonMode').checked,json_repair:$('paJsonRepair').checked,send_temperature:$('paSendTemp').checked,extra_headers:parseSettingsJSON('paExtraHeaders',null),extra_body:parseSettingsJSON('paExtraBody',{}),thinking_mode:$('paThinkingMode').value,thinking_adapter:$('paThinkingAdapter').value});m.api=a;}if(mode!=='api'){Object.assign(m,{backend:$('pmmBackend').value,base_url:$('pmmUrl').value.trim(),api_key:$('pmmKey').value||($('clearPmmKey').checked?'':null),model:$('pmmModel').value.trim(),timeout:Number($('pmmTimeout').value)});m.managed=state.config.pmm.managed&&m.backend==='http'&&m.base_url===state.config.pmm.base_url;}await api('/api/config',{deliberation:{enabled:$('deliberationEnabled').checked,mode:$('deliberationMode').value,max_perspectives:Number($('maxPerspectives').value),max_rounds:Number($('deliberationRounds').value),return_unresolved_conflict:$('unresolvedConflict').checked},pmm:m,online_learning:$('onlineLearning').checked,max_retrieval_rounds:Number($('retrievalRounds').value)});await refresh();fillPmm();$('pmmResult').textContent='PMM 配置已保存，主体状态与经历已保留。';}
async function testConnection(button,resultId,prepare,route){$(button).disabled=true;$(resultId).className='connection-result';try{await prepare();$(resultId).textContent='正在执行实际接口请求…';const r=await api(route,{});$(resultId).textContent=r.message+'\n'+(r.protocol||r.backend)+' · '+r.model+' · 耗时 '+seconds(r.duration_ms);showDiagnostics(resultId,r.calls||r);return r;}catch(e){showDiagnostics(resultId,e.diagnostics||{error:e.message});$(resultId).textContent=e.message;$(resultId).className='connection-result error';throw e;}finally{$(button).disabled=false;}}
async function download(path,name){const r=await fetch(path);if(!r.ok)throw new Error('导出失败');const url=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),3000);}
$('chatForm').addEventListener('submit',guard(sendMessage));$('message').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('chatForm').requestSubmit();}});
$('newSession').onclick=guard(newSession);$('settingsBtn').onclick=openSettings;$('settingsTop').onclick=openSettings;$('newPersona').onclick=()=>$('personaDialog').showModal();$('personaSelect').onchange=guard(async()=>{await api('/api/persona/activate',{id:$('personaSelect').value});sessionId='';await refresh();notice('已切换主体，当前显示它自己的经历与关系。');});
$('personaForm').onsubmit=guard(async e=>{e.preventDefault();await api($('cloneTemplate').checked?'/api/persona/clone':'/api/persona/new',$('cloneTemplate').checked?{name:$('newName').value}:{name:$('newName').value,seed:$('newSeed').value,character:{self_reference:$('newSelfReference').value,initial_personality:$('newInitialPersonality').value}});$('personaDialog').close();sessionId='';await refresh();showPage('distill');});
$('settingsForm').onsubmit=guard(async e=>{e.preventDefault();await saveSettings();});
$('testModel').onclick=guard(()=>testConnection('testModel','connectionResult',saveSettings,'/api/test-model'));
$('modelsBtn').onclick=guard(async()=>{await saveSettings();$('connectionResult').textContent='正在读取模型列表…';const r=await api('/api/models',{});$('modelOptions').innerHTML=r.models.map(m=>`<option value="${esc(m)}"></option>`).join('');if(!$('modelInput').value&&r.models.length)$('modelInput').value=r.models[0];$('connectionResult').textContent=`读取到 ${r.models.length} 个模型。选择并保存；列表不可用时也可手动填写。`;});
$('provider').onchange=()=>{$('providerPreset').value='custom';protocolHint();};
$('providerPreset').onchange=()=>{const p=state.presets.find(p=>p.id===$('providerPreset').value);if(!p)return;$('llmThinkingMode').value=p.thinking_mode||'auto';$('llmThinkingAdapter').value=p.thinking_adapter||'auto';$('provider').value=p.provider;if(p.base_url)$('baseUrl').value=p.base_url;$('apiKey').value='';$('clearLlmKey').checked=true;$('extraHeaders').value='{}';$('modelInput').value='';$('modelOptions').innerHTML='';$('authMode').value=p.auth_mode||'auto';$('tokenField').value=p.token_field||'max_tokens';$('sendTemp').checked=p.send_temperature??true;$('jsonMode').checked=true;$('extraBody').value=JSON.stringify(p.extra_body||{},null,2);$('presetHint').textContent=p.hint||'请填入此服务的密钥和实际模型名。切换预设会清除旧服务凭据。';protocolHint();};
$('pmmForm').onsubmit=guard(async e=>{e.preventDefault();await savePmm();});$('pmmBackend').onchange=pmmFields;$('pmmMode').onchange=pmmFields;
$('testPmm').onclick=guard(()=>testConnection('testPmm','pmmResult',savePmm,'/api/pmm/test'));
$('pmmModelsBtn').onclick=guard(async()=>{await savePmm();const r=await api('/api/pmm/models',{});$('pmmModels').innerHTML=r.models.map(m=>`<option value="${esc(m)}"></option>`).join('');$('pmmResult').textContent='可用 PMM：'+r.models.join('、');});
$('startPmm').onclick=guard(async()=>{await testConnection('startPmm','pmmResult',savePmm,'/api/pmm/start');await refresh();fillPmm();});
$('exportWeights').onclick=guard(()=>download('/api/pmm/export','pmm_weights.json'));$('importWeights').onclick=()=>$('weightsFile').click();
$('weightsFile').onchange=guard(async()=>{const f=$('weightsFile').files[0];if(!f)return;if(f.size>25_000_000)throw new Error('权重文件超过 25 MB');await api('/api/pmm/import',JSON.parse(await f.text()));await refresh();fillPmm();$('pmmResult').textContent='已载入当前主体的 PMM 权重，替换前检查点已保留。';$('weightsFile').value='';});
$('trainPmm').onclick=guard(async()=>{await savePmm();$('trainPmm').disabled=true;try{$('pmmResult').textContent='正在训练 PMM…';const job=await api('/api/pmm/train',{epochs:Number($('pmmEpochs').value)});await runJob(job,'pmm_train');fillPmm();$('pmmResult').textContent='PMM 训练完成，指标已更新到实验记录。';}finally{pmmFields();}});
$('chatFile').onchange=guard(async()=>{const f=$('chatFile').files[0];if(!f)return;if(f.size>2_000_000)throw new Error('单批文件最多 2 MB');$('sourceText').value=await f.text();importParsed=false;$('distillBtn').disabled=true;});$('sourceText').oninput=()=>{importParsed=false;$('distillBtn').disabled=true;};
$('previewImport').onclick=guard(async()=>{const r=await api('/api/import/preview',{content:$('sourceText').value});$('speakerSelect').innerHTML=Object.entries(r.speakers).map(([speaker,n])=>`<option value="${esc(speaker)}">${esc(speaker)} · ${n} 条</option>`).join('');$('importPreview').innerHTML=`<b>${r.count} 条消息 · ${Object.keys(r.speakers).length} 位说话人</b>${r.preview.map(x=>`<p><strong>${esc(x.speaker)}：</strong>${esc(x.text.slice(0,220))}</p>`).join('')}`;importParsed=true;$('distillBtn').disabled=busy;});
$('distillTarget').onchange=()=>{const other=$('distillTarget').value==='interlocutor';$('otherFields').hidden=!other;$('distillBtn').textContent=other?'蒸馏交谈对象模型':'蒸馏人格与语言';};$('distillBtn').onclick=guard(async()=>{if(!(state.config.pmm.mode==='api'?state.config.pmm.api.model:state.config.model)){openSettings();return;}setBusy(true);try{const r=await api('/api/distill',{content:$('sourceText').value,speaker:$('speakerSelect').value,target:$('distillTarget').value,person:$('personId').value,scope:$('personScope').value});await runJob(r,'distill');}finally{setBusy(false);}});
$('otherSelect').onchange=()=>{renderOther();renderOtherLearning();};$('memorySearch').oninput=renderMemory;$('latestTrace').onclick=()=>{const e=events.find(e=>e.kind==='turn');if(e)showTrace(e.payload.turn_id);else notice('开始对话后，这里会显示完整闭环记录。');};
$('exportPack').onclick=guard(()=>download('/api/persona/export?scope='+$('packageScope').value,'persona_'+$('packageScope').value+'.json'));$('backupBtn').onclick=guard(()=>download('/api/export','persona_snapshot.json'));$('importPack').onclick=()=>$('packFile').click();$('restoreBtn').onclick=()=>$('backupFile').click();
$('packFile').onchange=guard(async()=>{const f=$('packFile').files[0];if(!f)return;if(f.size>25_000_000)throw new Error('人格包超过 25 MB');await api('/api/persona/import',JSON.parse(await f.text()));sessionId='';await refresh();notice('人格包已载入，模型连接保持当前设置。');$('packFile').value='';});
$('backupFile').onchange=guard(async()=>{const f=$('backupFile').files[0];if(!f)return;if(f.size>25_000_000)throw new Error('备份超过 25 MB');await api('/api/restore',JSON.parse(await f.text()));await refresh();notice('主体已恢复；原有数据已自动备份。');$('backupFile').value='';});
$('reloadBtn').onclick=guard(async()=>{await api('/api/reload',{});notice('正在重启程序并重新加载代码…');for(let i=0;i<30;i++){await new Promise(r=>setTimeout(r,1000));try{await fetch('/');await refresh();notice('代码已重新加载，继续使用同一主体。');return;}catch{}}throw new Error('程序尚未就绪，请查看终端后刷新。');});
$('feedbackForm').onsubmit=guard(async e=>{e.preventDefault();await api('/api/feedback',{turn_id:feedbackTurn,rating:'unhelpful',note:$('feedbackNote').value,action_target:$('feedbackAction').value||null,corrected_reply:$('correctedReply').value||null,perspective_target:$('feedbackPerspective').value||null});$('feedbackDialog').close();await refresh();notice('校正已保存到学习数据，风格示范已更新；部分样本保留用于验证。');});
$('qqForm').onsubmit=guard(async e=>{e.preventDefault();const list=id=>$(id).value.split(/[,，\s]+/).filter(Boolean);await api('/api/config',{qq:{self_id:$('qqSelfId').value.trim(),enabled:$('qqEnabled').checked,api_url:$('qqUrl').value.trim(),api_token:$('qqToken').value||null,hmac_secret:$('qqHmac').value||null,allowed_users:list('qqUsers'),allowed_groups:list('qqGroups'),group_mention_only:$('qqMention').checked}});await refresh();$('qqResult').textContent='QQ 设置已保存。';});$('qqTest').onclick=guard(async()=>{const r=await api('/api/qq/test',{});$('qqResult').textContent=`已登录 ${r.nickname} (${r.user_id})`;});$('qqSetup').onclick=guard(async()=>{const r=await api('/api/qq/setup',{});$('qqResult').textContent=r.event_url+' · 仅填写到你自己的 OneBot HTTP 事件上报设置。';});
document.addEventListener('click',guard(async e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.view)showPage(b.dataset.view);if(b.dataset.goto)showPage(b.dataset.goto,b.dataset.targetTab);if(b.dataset.close)$(b.dataset.close).close();if(b.hasAttribute('data-open-settings'))openSettings();if(b.hasAttribute('data-new-session'))await newSession();if(b.dataset.session){sessionId=b.dataset.session;showPage('chat');await refresh();}if(b.dataset.trace)showTrace(b.dataset.trace);if(b.dataset.feedback){feedbackTurn=b.dataset.feedback;$('feedbackAction').value='';$('feedbackPerspective').innerHTML='<option value="">不标记倾向</option>'+((events.find(x=>x.kind==='turn'&&x.payload.turn_id===feedbackTurn)?.payload.projections)||[]).map(v=>`<option value="${esc(v.id)}">${esc(v.label)}</option>`).join('');$('correctedReply').value='';$('feedbackNote').value='';$('feedbackDialog').showModal();}if(b.dataset.memoryEdit){const m=memories.find(x=>x.id===b.dataset.memoryEdit);const content=prompt('修订记忆内容（原始版本会保留在事件记录中）',m.content);if(content?.trim()){await api('/api/memory',{id:m.id,op:'UPDATE',content});await refresh();}}if(b.dataset.memoryToggle){const m=memories.find(x=>x.id===b.dataset.memoryToggle);await api('/api/memory',{id:m.id,op:m.status==='active'?'DELETE':'KEEP'});await refresh();}if(b.dataset.relevant||b.dataset.irrelevant){await api('/api/feedback',{turn_id:b.dataset.turn,rating:'helpful',memory_feedback:[{id:b.dataset.relevant||b.dataset.irrelevant,relevant:!!b.dataset.relevant}]});notice('检索相关性反馈已用于调整检索权重。');}}));

function renderSynthesis(){const r=state.synthesis;$('synthesisPanel').innerHTML=r?`<p class="callout">仅分析 · 未应用到人格或权重 · 不参与后续决策</p><p class="fine">保存位置：pmm_synthesis · 基于来源修订 ${r.profile_revision} · ${date(r.updated_at)}${r.profile_revision!==state.profile.revision?' · 之后的新增证据尚未整理':''}</p>${r.statements.map(s=>`<div class="evidence"><span class="tag">${esc(s.domain)}</span><p>${esc(s.text)}</p>${s.evidence.map(e=>`<blockquote>${esc(e.quote)}</blockquote><span class="record-id">${esc(e.record_id)}</span>`).join('')}</div>`).join('')}<p class="fine">尚不确定：${r.uncertainties.map(esc).join('；')||'未列出'}</p>`:'<p class="empty">已有来源记录后，可以整理跨情境的表达与判断规律。</p>';
const e=state.expression;$('expressionPanel').innerHTML=e?`<p class="fine">已观察 ${e.count} 条 AI 实际回复 · ${Object.entries(e.action_counts).map(([k,v])=>esc(actionNames[k]||k)+' '+v).join(' / ')}</p>`:'';}
function fillVersions(id,rows){const old=$(id).value;$(id).innerHTML=rows.map(r=>`<option value="${esc(r.id)}">${esc(r.label)} · ${date(r.created_at)}</option>`).join('')||'<option value="">尚无保存版本</option>';if(rows.some(r=>r.id===old))$(id).value=old;}
function renderVersions(){fillVersions('weightVersion',versions.weights);fillVersions('coreVersion',versions.cores);fillVersions('personaRevision',personaRevisions);const m=state.model,learned=m.mode==='learned';$('parameterSummary').innerHTML=learned?`<p class="record-id">核心 θ · ${esc(m.core_sha256)}<br>个体 Adapter · ${esc(m.adapter_id)} · 修订 ${m.adapter_revision}</p><p>核心训练 ${m.core_steps} 步 · 个体训练 ${m.adapter_steps} 步</p>`:`<p class="muted">${esc(modeName(m.mode))} · ${m.mode==='api'?'保留的数值参数可导出；切换 Learned-PMM 后启用核心与 Adapter 管理。':'迁移到 Learned-PMM 后可使用核心与 Adapter 管理。'}</p>`;for(const id of ['saveCore','exportCore','exportAdapter','importAdapter','activateCore','trainCore'])$(id).disabled=!learned;$('activateWeights').disabled=!versions.weights.length;$('rollbackPersona').disabled=!personaRevisions.length;}
async function selectedVersion(id,route){const value=$(id).value;if(!value)throw new Error('请先保存或载入一个版本。');const r=await api(route,{id:value});await refresh();notice(r.message||'选中版本已恢复，主体身份与聊天记录保持连续。');}
function bindImport(button,input,route,message){$(button).onclick=()=>$(input).click();$(input).onchange=guard(async()=>{const f=$(input).files[0];if(!f)return;try{if(f.size>25_000_000)throw new Error('文件超过 25 MB');const r=await api(route,JSON.parse(await f.text()));await refresh();notice(r.message||message);}finally{$(input).value='';}});}
$('copyGeneral').onclick=guard(async()=>{await api('/api/pmm/api/copy-general',{});await refresh();fillPmm();$('pmmResult').textContent='已复制保存的 General LLM 连接；API-PMM 仍可独立修改。';});
$('paProvider').onchange=()=>{$('paProviderPreset').value='custom';};
$('paProviderPreset').onchange=()=>{const p=state.presets.find(p=>p.id===$('paProviderPreset').value);if(!p)return;$('paThinkingMode').value=p.thinking_mode||'auto';$('paThinkingAdapter').value=p.thinking_adapter||'auto';$('paProvider').value=p.provider;if(p.base_url)$('paBaseUrl').value=p.base_url;$('paApiKey').value='';$('paClearLlmKey').checked=true;$('paExtraHeaders').value='{}';$('paModelInput').value='';$('paModelOptions').innerHTML='';$('paAuthMode').value=p.auth_mode||'auto';$('paTokenField').value=p.token_field||'max_tokens';$('paSendTemp').checked=p.send_temperature??true;$('paJsonMode').checked=true;$('paExtraBody').value=JSON.stringify(p.extra_body||{},null,2);$('paPresetHint').textContent=p.hint||'填写独立 API-PMM 的密钥与模型名。';};
$('paModelsBtn').onclick=guard(async()=>{await savePmm();const r=await api('/api/pmm/models',{});$('paModelOptions').innerHTML=r.models.map(m=>`<option value="${esc(m)}"></option>`).join('');if(!$('paModelInput').value&&r.models.length)$('paModelInput').value=r.models[0];$('pmmResult').textContent=`API-PMM 读取到 ${r.models.length} 个模型；选择后保存。`;});
$('synthesizePersona').onclick=guard(async()=>{const r=await api('/api/persona/synthesize',{});await runJob(r,'synthesize');showPage('profiles');notice('证据报告已保存；未修改人格或模型权重，也未加入下一轮决策条件。');});
$('saveWeightsVersion').onclick=guard(async()=>{await api('/api/pmm/version/save',{label:'手动参数检查点'});await refresh();notice('已保存当前参数版本。');});
$('activateWeights').onclick=guard(()=>selectedVersion('weightVersion','/api/pmm/version/activate'));
$('exportAdapter').onclick=guard(()=>download('/api/pmm/adapter/export','persona_adapter.json'));
$('exportCore').onclick=guard(()=>download('/api/pmm/core/export','pmm_core.json'));
$('saveCore').onclick=guard(async()=>{await api('/api/pmm/core/import',await api('/api/pmm/core/export'));await refresh();notice('当前核心已登记到共享目录，其他人格也可以选择。');});
$('activateCore').onclick=guard(()=>selectedVersion('coreVersion','/api/pmm/core/activate'));
$('trainCore').onclick=guard(async()=>{const r=await api('/api/pmm/core/train',{epochs:Number($('coreEpochs').value)});await runJob(r,'core_train');});
$('savePersonaRevision').onclick=guard(async()=>{await api('/api/persona/checkpoint',{label:'手动人格检查点'});await refresh();notice('当前人格、心理状态、记忆与关系已保存为检查点。');});
$('rollbackPersona').onclick=guard(()=>selectedVersion('personaRevision','/api/persona/rollback'));
bindImport('importAdapter','adapterFile','/api/pmm/adapter/import','已载入匹配当前主体与核心的 Adapter。');
bindImport('importCore','coreFile','/api/pmm/core/import','核心已加入目录；选中并启用后才应用。');
bindImport('applyPack','applyPackFile','/api/persona/apply','同主体人格包已应用。');
document.querySelectorAll('dialog').forEach(d=>d.addEventListener('close',()=>d.querySelector('.dialog-notice')?.remove()));

function constructHTML(profile){const psychology=profile.psychology;if(!psychology)return '<p class="empty">尚无长期人格记录</p>';const registry=(state.psychology_registry||[]).filter(f=>f.feature_temporality==='long'),groups=[...new Set(registry.map(f=>f.group))];return groups.map(group=>{const fs=registry.filter(f=>f.group===group);return `<details class="trait-section"><summary>${esc(group==='价值'?'Schwartz · 19 项价值优先级':group==='语言身份'?'程序行为与语用习惯':group)} · ${fs.filter(f=>psychology.features[f.id]?.estimate!=null).length}/${fs.length} 项有估计</summary><div class="trait-grid">${fs.map(spec=>traitRow(profile,spec)).join('')}</div></details>`}).join('');}

function renderPsychology(){const p=state.profile,features=p.psychology?.features||{},reg=state.psychology_registry||[],version=p.trait_profile?.version??0;const known=reg.filter(f=>f.feature_temporality==='long'&&features[f.id]?.estimate!=null).length;$('registrySummary').textContent=`长期人格版本 ${version} · HEXACO 25 面向与 Schwartz 19 价值分别保存 · 长期/行为字段有来源 ${known} 项。当天情绪不在此处；聊天推断不等于正式量表分数。`;
 const domains=[['h','诚实—谦逊'],['e','情绪性倾向'],['x','外向性'],['a','宜人性'],['c','尽责性'],['o','开放性']];
 const domainCards=domains.map(([key,label])=>{const fields=reg.filter(f=>f.id.startsWith('hexaco.'+key+'.')),values=fields.map(f=>features[f.id]?.estimate).filter(v=>v!=null),mean=values.length?values.reduce((a,b)=>a+b,0)/values.length:null;return `<article class="domain-card"><h4>${label}</h4>${mean===null?'<p class="unknown-label">尚无可汇总的面向估计</p>':traitMeter('已知面向均值',mean)}<p class="fine">${values.length}/4 面向有估计；非完整量表测分</p><details data-disclosure="hexaco-${key}"><summary>查看四个面向与来源</summary>${fields.map(f=>traitRow(p,f)).join('')}</details></article>`;}).join('');
 $('psychologyPanel').innerHTML='<h3>HEXACO · 六域与 24＋1 面向</h3><p class="fine">情绪性是长期倾向，不是今天的恐惧或悲伤。展开面向可查看估计、来源和不确定性。</p><div class="domain-grid">'+domainCards+'</div><details data-disclosure="hexaco-additional"><summary>附加面向</summary>'+reg.filter(f=>f.id.startsWith('hexaco.interstitial.')).map(f=>traitRow(p,f)).join('')+'</details><details data-disclosure="values"><summary>Schwartz · 19 项价值优先级</summary><div class="trait-grid">'+reg.filter(f=>f.group==='价值').map(f=>traitRow(p,f)).join('')+'</div></details><details data-disclosure="interpersonal"><summary>稳定人际倾向</summary><div class="trait-grid">'+reg.filter(f=>f.group==='人际倾向').map(f=>traitRow(p,f)).join('')+'</div></details>';
 $('languageIdentity').innerHTML='<details data-disclosure="language-identity"><summary>已有语言身份估计与依据</summary><div class="trait-grid">'+reg.filter(f=>f.group==='语言身份').map(f=>traitRow(p,f)).join('')+'</div></details>';
 const dispositions=p.trait_profile?.dispositions||{};for(const [prefix,id] of [['beq.','beqPanel'],['erq.','erqPanel'],['panas.','panasPanel']])$(id).innerHTML=(state.disposition_registry?.fields||[]).filter(f=>f.id.startsWith(prefix)).map(f=>{const v=dispositions[f.id]||{};return `<article class="habit-card"><h4>${esc(f.name_zh)}</h4>${v.estimate==null?'<p class="unknown-label">未知 · 尚无足够证据</p>':traitMeter('特征估计值',v.estimate)+traitMeter('工程不确定性',v.uncertainty,'uncertainty')}<p class="fine">${esc(sourceName(v.source_type))} · ${v.updated_at?date(v.updated_at):'更新时间未记录'}</p><p class="record-id">来源类型 ID：${esc(v.source_type||'unknown')} · ${esc(f.id)}</p><button data-habit-edit="${esc(f.id)}">编辑设定</button><button data-habit-evidence="${esc(f.id)}">来源依据</button></article>`}).join('');
 renderTraitReview(state.trait_review);renderFormationStatus();
}
function dyadHTML(d){if(!d)return '';return `<div class="callout"><h3>这段关系 · ${esc(d.context_id)}</h3><p>互动 ${d.interactions} 次</p><div class="metric-grid">${meter('信任',d.trust)}${meter('亲近',d.affiliation)}${meter('熟悉度',d.familiarity)}${Object.entries(d.preferences||{}).map(([k,v])=>meter(({humor_tolerance:'幽默接受度',action_preference:'行动倾向',empathy_need:'共情需要',directness:'直接程度',boundary_sensitivity:'边界敏感度',information_density:'信息密度'})[k]||k,typeof v==='number'?v:v?.estimate)).join('')}</div><details><summary>关系偏好、共享语境与轨迹</summary><pre>${esc(JSON.stringify({preferences:d.preferences,shared_jokes:d.shared_jokes,preferred_addressing:d.preferred_addressing,belief_provenance:d.belief_provenance,trajectory:d.trajectory.slice(-20)},null,2))}</pre></details>${relationshipSchemaHTML(d)}</div>`;}
function deliberationHTML(d){if(!d)return '';return `<div class="callout"><strong>内部协商 · ${esc(d.mode)} · ${d.multi_view?'已运行多视角':'单路径'}</strong><p>规则 ${esc(d.rule_version)} · ${esc(d.reason)}</p><div class="row">${Object.entries(d.scores||{}).map(([k,v])=>`${meter(k,v)}`).join('')}</div>${(d.rounds||[]).map(r=>`<details><summary>第 ${r.index} 轮 · PMM 复核</summary>${r.candidates.map(v=>`${meter(v.label+' · 权重',v.weight)}<p>${esc(v.source_features.join('、')||'当前主体综合状态')}</p><p class="record-id">${esc(v.evidence_ids.join('、'))}</p>`).join('')}<p>${esc(r.pmm_review.summary)}</p><pre>${esc(JSON.stringify(r.pmm_review,null,2))}</pre></details>`).join('')}<p class="fine">${d.unresolved_conflict?'保留未解决分歧。':''}内部候选与推演不会写成真实经历。</p></div>`;}

function seconds(ms){return typeof ms==='number'?(ms/1000).toFixed(2)+' 秒':'未记录';}
function turnDuration(id){const t=events.find(e=>e.kind==='turn'&&e.payload.turn_id===id)?.payload;return t?.timing?`<span class="duration">${seconds(t.timing.total_ms)}</span>`:'';}
function timingHTML(t){if(!t.timing)return '';const x=t.timing;return `<div class="callout"><strong>本轮处理 ${seconds(x.total_ms)}</strong><p>General LLM ${seconds(x.general_api_ms)} · API-PMM ${seconds(x.pmm_api_ms)}</p><details><summary>分阶段耗时与实际请求参数</summary>${x.stages.map(s=>`<p>${esc(s.phase)} · ${seconds(s.duration_ms)}</p>`).join('')}<pre>${esc(JSON.stringify({general:t.api_calls,pmm:t.pmm_api_calls},null,2))}</pre></details></div>`;}
function showDiagnostics(resultId,detail){const prefix=resultId==='pmmResult'?'pmm':'general';$(prefix+'Diagnostics').hidden=false;$(prefix+'DiagnosticBody').textContent=JSON.stringify(detail,null,2);}
function eventLabel(kind){return {turn_taking:'回复时机',group_attention:'群聊注意',memory_consolidated:'记忆要点蒸馏',scope_erased:'来源会话删除',memory_queue_full:'记忆队列已满',consolidation:'后台整理',social_decision:'主动社交决策',social_sent:'主动消息',social_failed:'主动社交失败',social_feedback:'主动联系反馈',media_sent:'图片 / 表情发送',media_feedback:'用图反馈',turn:'对话闭环',turn_failed:'对话失败',distillation:'聊天蒸馏',feedback:'人工校正',config_updated:'连接更新',connection_test:'连接测试',character_updated:'角色设定',boundary_edited:'边界修订',persona_created:'人格创建',memory_manual:'记忆修订',restore:'恢复备份'}[kind]||kind;}
function eventError(e){return e.kind.includes('failed')||e.kind.includes('error')||e.payload?.ok===false||e.payload?.status==='failed';}
function groupEvents(rows){const groups=[];for(const e of rows){const merge=['config_updated','connection_test'].includes(e.kind)&&!eventError(e);const key=merge?'connections':e.id;let g=merge?groups.find(x=>x.key===key):null;if(!g){g={key,rows:[]};groups.push(g);}g.rows.push(e);}return groups;}
function renderEvents(){if(panelFailures.events){panelError('eventList',panelFailures.events);return;}const filter=$('eventFilter').value;const selected=events.filter(e=>filter==='all'||(filter==='connection'&&['config_updated','connection_test'].includes(e.kind))||(filter==='errors'&&eventError(e))||e.kind===filter);$('eventList').innerHTML=groupEvents(selected).map(g=>{const e=g.rows[0];return `<details class="event-row ${eventError(e)?'event-error':''}"><summary><span>${esc(g.key==='connections'?'连接设置与测试':eventLabel(e.kind))}${g.rows.length>1?' · '+g.rows.length+' 次':''}</span><time>${date(e.created_at)}</time>${e.payload.timing?`<span>${seconds(e.payload.timing.total_ms)}</span>`:''}</summary>${g.rows.map(row=>`<div class="event-detail"><p class="fine">${esc(eventLabel(row.kind))} · ${date(row.created_at)}</p>${row.payload.error?`<p>${esc(row.payload.error)}</p>`:''}${row.kind==='turn'?`<button data-trace="${esc(row.payload.turn_id)}">查看本轮机制</button>`:''}<button data-event-record="${esc(row.id)}">完整记录</button></div>`).join('')}</details>`}).join('')||'<p class="empty">没有匹配记录</p>';}
$('eventFilter').onchange=renderEvents;
$('moreEvents').onclick=guard(async()=>{const rows=await api('/api/events?offset='+events.length);const ids=new Set(events.map(e=>e.id));events.push(...rows.filter(e=>!ids.has(e.id)));renderEvents();notice(rows.length?'已加载更早记录。':'已到最早记录。');});
$('exportEvents').onclick=guard(()=>download('/api/events/export','persona_operation_history.json'));
let characterRevision=0;
$('editCharacter').onclick=guard(()=>{const p=state.profile;characterRevision=p.revision;$('characterName').value=p.name;$('characterSelfReference').value=p.character?.self_reference||'我';$('characterInitialPersonality').value=p.character?.initial_personality||'';$('characterSeed').value=p.seed;$('characterDialog').showModal();});
$('characterForm').onsubmit=guard(async e=>{e.preventDefault();await api('/api/persona/settings',{expected_revision:characterRevision,name:$('characterName').value,self_reference:$('characterSelfReference').value,initial_personality:$('characterInitialPersonality').value,seed:$('characterSeed').value});$('characterDialog').close();await refresh();notice('角色设定已保存，下轮对话生效；修改前版本可在数据与版本中恢复。');});
$('qqStatusBtn').onclick=guard(async()=>{const q=await api('/api/qq/status');const labels={accepted:'OneBot 已接受，送达未确认',pending:'等待处理',processing:'处理中',sent:'已发送',silent:'主动沉默',failed:'处理失败',validation_failed:'输出校验失败',delivery_failed:'QQ 明确发送失败',delivery_unknown:'发送结果未知',sent_postprocess_pending:'已发送 · 本地提交待恢复',permission_withdrawn:'对方已撤回联系许可',skipped:'已跳过',not_sent:'未发送',interrupted:'上次被中断',awaiting_input:'保留原文，等待补充或重试',held:'超出单轮容量，已保留'};$('qqStatusPanel').innerHTML=`<p>自动回复${q.enabled?'已启用':'未启用'} · General ${q.general_configured?'已填写':'待配置'} · PMM ${q.pmm_configured?'已填写':'待配置'}</p><p>最近事件：${q.last_receipt?date(q.last_receipt.at)+' · '+esc(q.last_receipt.reason):'尚未收到已验证事件，请检查 OneBot 上报地址与令牌'}</p>${q.recent.map(r=>`<details class="event-row"><summary>${esc(labels[r.status]||r.status)} · ${date(r.created_at)} · ${esc(r.result.phase||'')}${r.result.timing?' · '+seconds(r.result.timing.qq_total_ms??r.result.timing.total_ms):''}</summary>${['failed','validation_failed','delivery_failed','not_sent'].includes(r.status)?`<button data-retry-failure="${esc(r.id)}">重试未发送的消息</button>`:''}${r.status==='awaiting_input'?`<button data-retry-appraisal="${esc(r.id)}">重试认知判断</button>`:''}<pre>${esc(JSON.stringify(r.result,null,2))}</pre></details>`).join('')}`;});

const splitList=id=>$(id).value.split(/[,，\s]+/).filter(Boolean);

function fillConnectionPresets(){const kind=$('connectionKind').value,old=$('connectionPreset').value;const rows=(state.connection_presets||[]).filter(r=>r.kind===kind);$('connectionPreset').innerHTML='<option value="">选择预设</option>'+rows.map(r=>`<option value="${esc(r.id)}">${esc(r.name)}</option>`).join('');if(rows.some(r=>r.id===old))$('connectionPreset').value=old;const b=state.connection_bindings?.[kind];$('connectionBinding').textContent=b?'最近应用：'+b.name+'（本人格独立副本）':'当前使用独立连接，尚未应用命名预设';}
function fillOperations(){fillCognitiveOperations();$('appraisalTimeout').value=state.config.cognition?.assessment_timeout||30;document.querySelectorAll('[data-baseline-only]').forEach(el=>{el.disabled=state.config.cognition?.mode!=='baseline';});const c=state.config,p=c.performance,m=c.media,s=c.social;$('operationsTitle').textContent=state.profile.name+' · 运行设置';fillConnectionPresets();$('performanceMode').value=p.mode;$('performanceQQOnly').checked=p.qq_only;for(const [id,key] of Object.entries({replyChars:'reply_chars',batchTurns:'batch_turns',idleSeconds:'idle_seconds',workChars:'work_chars'}))$(id).value=p[key];$('consolidationStatus').textContent=JSON.stringify(state.consolidation,null,2);$('mediaReceive').checked=m.receive;$('visionModel').value=m.vision_model;$('mediaHosts').value=m.download_hosts.join(', ');$('socialEnabled').checked=s.enabled;$('socialPrivate').checked=s.private_enabled;$('socialGroup').checked=s.group_enabled;$('socialRecipients').value=s.recipients.filter(v=>v.startsWith('private:')).map(v=>v.split(':').pop()).join(', ');$('socialGroupRecipients').value=s.recipients.filter(v=>v.startsWith('group:')).map(v=>v.split(':').pop()).join(', ');$('socialPreviewScope').innerHTML='<option value="">选择已保存的联系对象</option>'+s.recipients.map(v=>`<option value="${esc(v)}">${v.startsWith('private:')?'私聊':'群聊'} ${esc(v.split(':').pop())}</option>`).join('');renderSocialReadiness();for(const [id,key] of Object.entries({socialIdle:'idle_minutes',socialCooldown:'cooldown_minutes',socialBudget:'daily_budget',socialUnanswered:'unanswered_limit',quietStart:'quiet_start',quietEnd:'quiet_end',socialTimezone:'timezone'}))$(id).value=s[key];}

async function refreshSocial(){const s=await api('/api/social');$('socialResult').textContent=JSON.stringify({running:s.running,attempts:s.attempts},null,2);$('socialContacts').innerHTML=Object.entries(s.contacts).map(([scope,c])=>`<p class="fine">${esc(scope)} · 未回复 ${c.unanswered||0} 次 · ${c.blocked?'对方已要求停止':'正常'} ${c.blocked?`<button data-social-unblock="${esc(scope)}">由我解除暂停</button>`:''}</p>`).join('');}
$('openOperations').onclick=()=>{showPage('diagnostics');selectTab('diagnostics-panel-runtime');};
$('connectionKind').onchange=fillConnectionPresets;
$('connectionPreset').onchange=()=>{const p=state.connection_presets.find(p=>p.id===$('connectionPreset').value);if(p)$('connectionName').value=p.name;};
async function presetAction(op,newItem=false){const id=newItem?undefined:$('connectionPreset').value;if(!newItem&&!id)throw new Error('请先选择连接预设');const r=await api('/api/connection-presets',{op,id,kind:$('connectionKind').value,name:$('connectionName').value});$('presetResult').textContent=op==='test'?JSON.stringify(r,null,2):'操作已保存。'+(op==='apply'?'已应用到当前人格；其他人格和原预设不受影响。':'');await refresh();fillConnectionPresets();if(op==='apply'){openSettings();fillOperations();}}
for(const [id,op] of Object.entries({presetSave:'save',presetCopy:'copy',presetRename:'rename',presetApply:'apply',presetTest:'test',presetDelete:'delete'}))$(id).onclick=guard(()=>presetAction(op));$('presetNew').onclick=guard(()=>presetAction('save',true));
$('performanceForm').onsubmit=guard(async e=>{e.preventDefault();await api('/api/config',{performance:{mode:$('performanceMode').value,qq_only:$('performanceQQOnly').checked,reply_chars:Number($('replyChars').value),batch_turns:Number($('batchTurns').value),idle_seconds:Number($('idleSeconds').value),work_chars:Number($('workChars').value)}});await refresh();fillOperations();notice('当前人格的回复流程已保存。');});
$('refreshConsolidation').onclick=guard(async()=>{await refresh();$('consolidationStatus').textContent=JSON.stringify(state.consolidation,null,2);});
$('consolidateNow').onclick=guard(async()=>{const r=await runJob(await api('/api/consolidation/run',{retry:true}),'consolidation');$('consolidationStatus').textContent=JSON.stringify(r,null,2);});
$('mediaConfigForm').onsubmit=guard(async()=>{await api('/api/config',{media:{receive:$('mediaReceive').checked,vision_model:$('visionModel').value.trim(),download_hosts:splitList('mediaHosts')}});await refresh();notice('QQ 图片收件设置已保存；处理结果请查看后台诊断记录。');});



$('socialForm').onsubmit=guard(async e=>{e.preventDefault();const missing=renderSocialReadiness();if($('socialEnabled').checked&&missing.length)throw new Error('启用主动联系还需：'+missing.join('；')+'。也可以取消启用，先保存草稿。');await api('/api/config',{social:{enabled:$('socialEnabled').checked,private_enabled:$('socialPrivate').checked,group_enabled:$('socialGroup').checked,recipients:socialRecipients(),idle_minutes:Number($('socialIdle').value),cooldown_minutes:Number($('socialCooldown').value),daily_budget:Number($('socialBudget').value),unanswered_limit:Number($('socialUnanswered').value),quiet_start:$('quietStart').value,quiet_end:$('quietEnd').value,timezone:$('socialTimezone').value}});await refresh();fillOperations();await refreshSocial();notice('当前人格的主动社交设置已保存。');});
$('socialRefresh').onclick=guard(refreshSocial);
$('socialPreview').onclick=guard(async()=>{if(!$('socialPreviewScope').value)throw new Error('请先保存主动联系对象，再从列表选择。');const r=await runJob(await api('/api/social/preview',{scope:$('socialPreviewScope').value.trim()}),'social_preview');$('socialResult').textContent=JSON.stringify(r,null,2);});
document.addEventListener('click',guard(async e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.socialUnblock){await api('/api/social/unblock',{scope:b.dataset.socialUnblock});await refreshSocial();}}));


function memoryStrengthHTML(m){const s=m.memory_strength;return `<div class="metric-grid">${meter('记忆可信度',m.confidence)}${meter('重要性',m.importance)}${s?meter('存储强度',s.storage_strength)+meter('当前检索强度',s.retrieval_strength):''}</div>${s?`<p class="fine">${s.source_type==='observed_group'?'旁观资料 · 非共同经历':'有来源的记忆'} · 采用 ${s.accesses} 次。强度为实验参数；原文不随衰减删除。</p>`:''}`;}
function fillCognitiveOperations(){const c=state.config,t=c.turn_taking,g=c.group_attention,m=c.memory;if(!t||!g||!m)return;$('turnTakingEnabled').checked=t.enabled;$('turnDebounce').value=t.debounce_seconds;$('turnMaxWait').value=t.max_wait_seconds;$('groupAttentionEnabled').checked=g.enabled;$('groupAllowReply').checked=g.allow_unmentioned_reply;$('groupPerMinute').value=g.per_minute;$('groupContextChars').value=g.context_chars;$('memoryGistEnabled').checked=m.enabled;$('memoryLifecycleStatus').textContent=JSON.stringify(state.memory_lifecycle,null,2);$('groupKnowledge').innerHTML=(state.group_attention?.people||[]).map(p=>`<p class="fine">${esc(p.scope)} · ${esc(p.person)} · ${esc(p.relationship)} · 直接互动 ${p.direct_interactions} 次</p>`).join('')||'<p class="fine">还没有群聊旁观记录。</p>';}
$('turnTakingForm').onsubmit=guard(async e=>{e.preventDefault();await api('/api/config',{turn_taking:{enabled:$('turnTakingEnabled').checked,debounce_seconds:Number($('turnDebounce').value),max_wait_seconds:Number($('turnMaxWait').value)}});await refresh();fillCognitiveOperations();notice('回复时机已保存。');});
$('groupAttentionForm').onsubmit=guard(async e=>{e.preventDefault();await api('/api/config',{group_attention:{enabled:$('groupAttentionEnabled').checked,allow_unmentioned_reply:$('groupAllowReply').checked,per_minute:Number($('groupPerMinute').value),context_chars:Number($('groupContextChars').value)}});await refresh();fillCognitiveOperations();notice('群聊注意已保存。');});
$('memoryLifecycleForm').onsubmit=guard(async e=>{e.preventDefault();await api('/api/config',{memory:{enabled:$('memoryGistEnabled').checked}});await refresh();fillCognitiveOperations();});
$('memoryConsolidateNow').onclick=guard(async()=>{await runJob(await api('/api/memory/consolidate',{retry:true}),'memory_gist');fillCognitiveOperations();});
document.addEventListener('click',guard(async e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.memorySources){const r=await api('/api/memory/sources?id='+encodeURIComponent(b.dataset.memorySources));$('traceTitle').textContent='记忆的原文来源';$('traceBody').innerHTML='<pre>'+esc(JSON.stringify(r,null,2))+'</pre>';$('traceDialog').showModal();}if(b.dataset.memoryErase){const scope=b.dataset.memoryErase,p=await api('/api/memory/erase-preview?scope='+encodeURIComponent(scope));const confirmation=prompt(p.impact+'\n\n'+p.limits+'\n\n将删除 '+p.messages+' 条消息、'+p.memories+' 条记忆。不可撤销。输入 '+p.confirmation+' 确认：');if(confirmation!==p.confirmation)return;await api('/api/memory/erase',{scope,confirmation});await refresh();notice('来源会话已删除，当前人格学习状态已重置。');}}));

const cognitiveLabels={turn_complete:'话语完成度',addressed:'明确指向',personal_relevance:'人格相关性',relationship_salience:'关系显著性',novelty:'新信息',emotional_salience:'情绪显著性',uncertainty:'不确定性',conflict:'内部冲突',consequence:'后果重要性',event_boundary:'新事件边界'};
const cognitiveActions={WAIT:'等待补充',REPLY:'进入回复',CLARIFY:'先澄清',NO_ACTION:'不发言',VALIDATION_FAILED:'判断失败（不是沉默）',PERMISSION_WITHDRAWN:'已撤回联系许可'};
function selectTab(id,focus=false){
 const panel=$(id);if(!panel)return;const pageNode=panel.closest('.page');if(!pageNode)return;
 pageNode.querySelectorAll('[role="tabpanel"]').forEach(el=>{el.hidden=el.id!==id;});
 pageNode.querySelectorAll('[role="tab"]').forEach(el=>{const active=el.dataset.tab===id;el.setAttribute('aria-selected',String(active));el.tabIndex=active?0:-1;if(active&&focus)el.focus();});
 updateRoute();
}
function renderCognition(){const c=state.cognition;if(!c){$('cognitionStatus').textContent='认知记录读取失败';panelError('cognitiveList',state.component_errors?.cognition||new Error('认知数据暂不可用'));return;}const recent=c.recent||[];$('cognitionStatus').textContent=`${c.mechanism} · 数值头更新 ${c.numeric_steps} 次 · 留出标注 ${c.metrics?.heldout?.labels||0} 项 · 尚未完成长期心理效度验证`;$('runtimeSummary').innerHTML=`<div><span>程序版本</span><strong>${esc(state.version)}</strong></div><div><span>认知路径</span><strong>${c.mode==='adaptive'?'事前估计（实验）':'旧版规则基线'}</strong></div><div><span>后台记忆</span><strong>${state.memory_lifecycle?.pending||0} 待整理 / ${state.memory_lifecycle?.failed||0} 失败</strong></div>`;$('cognitiveList').innerHTML=recent.map(r=>`<article class="decision-row"><div class="row spread"><strong>${esc(cognitiveActions[r.decision?.action]||'未完成')}</strong><time>${date(r.created_at)}</time><button data-cognitive-audit="${esc(r.id)}">查看依据与执行</button></div><p>${esc(r.decision?.reason||'')}</p><p class="fine">${esc(r.scope)} · ${esc(r.mechanism)} · ${r.before_generation?'生成前记录':'记录时间未知'}${r.decision?.await_input?' · 原文仍在等待队列':''}</p></article>`).join('')||'<p class="empty">尚无 QQ 事前决策。接入并收到消息后，这里会展示等待、注意选择与行动的依据。</p>';$('cognitiveRecord').innerHTML=recent.filter(r=>r.status==='estimated').map(r=>`<option value="${esc(r.id)}">${date(r.created_at)} · ${esc(r.scope)} · ${esc(cognitiveActions[r.decision.action])}</option>`).join('');if(!$('cognitiveField').innerHTML)$('cognitiveField').innerHTML=Object.entries(cognitiveLabels).map(([k,v])=>`<option value="${k}">${v}</option>`).join('');}
function showAudit(r){$('traceTitle').textContent='事前认知与执行证据';const decisions=events.filter(e=>e.kind==='turn'&&e.payload.decision?.cognitive_id===r.id);$('traceBody').innerHTML=`<p class="callout">${esc(r.mechanism)} · ${date(r.created_at)} · 人格修订 ${r.profile_revision} · 输入版本 ${r.input_version}</p><h3>1. 原始输入依据</h3>${(r.evidence||[]).map(e=>`<blockquote>${esc(e.quote)}</blockquote><p class="record-id">${esc(e.record_id)} · ${e.fields.map(f=>esc(cognitiveLabels[f])).join('、')}</p>`).join('')||'<p>没有通过来源验证的估计。</p>'}<h3>2. 生成前估计</h3><table><tbody>${Object.entries(r.estimates||{}).map(([k,v])=>`<tr><th>${esc(cognitiveLabels[k]||k)}</th><td>${meter(cognitiveLabels[k]||cognitiveActions[k]||k,v,1,v<0)}</td></tr>`).join('')}</tbody></table><h3>3. 行动比较与限制</h3><p>${esc(cognitiveActions[r.decision?.action])} · ${esc(r.decision?.reason||'')}</p><table><tbody>${Object.entries(r.decision?.scores||{}).map(([k,v])=>`<tr><th>${esc(cognitiveActions[k])}</th><td>${meter(cognitiveLabels[k]||cognitiveActions[k]||k,v,1,v<0)}</td></tr>`).join('')}</tbody></table><p class="fine">${esc(r.decision?.resource_reason||'')} · 策略 ${esc(r.decision?.policy_version||'未完成')}，效用参数未经效度验证。</p><h3>4. 后续执行</h3>${decisions.map(e=>`<button data-trace="${esc(e.payload.turn_id)}">查看实际回复与状态更新</button>`).join('')||'<p>当前载入记录中没有已提交的回复；可能仍在等待、未发言、失效或处理失败。可结合 QQ 状态和完整操作日志检查。</p>'}<details><summary>完整事前记录</summary><pre>${esc(JSON.stringify(r,null,2))}</pre></details>`;$('traceDialog').showModal();}
$('exportSupport').onclick=guard(()=>download('/api/support','HuaiAn_Dreamer_Diagnostics.json'));
$('exportSource').onclick=guard(()=>download('/api/source','HuaiAn_Dreamer_Source.md'));
$('exportSourceIndex').onclick=guard(()=>download('/api/source-index','HuaiAn_Dreamer_Code_Index.md'));
$('cognitionForm').onsubmit=guard(async e=>{e.preventDefault();await api('/api/config',{cognition:{assessment_timeout:Number($('appraisalTimeout').value)}});await refresh();fillOperations();notice('认知路径已保存，下一轮生效。');});
$('cognitiveFeedbackForm').onsubmit=guard(async e=>{e.preventDefault();if(!$('cognitiveRecord').value)throw new Error('请先选择一条成功的事前决策');const r=await api('/api/cognition/feedback',{id:$('cognitiveRecord').value,targets:{[$('cognitiveField').value]:Number($('cognitiveTarget').value)}});await refresh();notice(r.numeric_updated?(r.heldout?'已保存为留出标注，本条不参与梯度更新。':'已保存标注并更新数值认知头。'):'已保存 API-PMM 校准示例；没有修改远端模型权重。');});
document.addEventListener('click',guard(async e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.tab)selectTab(b.dataset.tab);if(b.dataset.cognitiveAudit){const r=state.cognition.recent.find(r=>r.id===b.dataset.cognitiveAudit);if(r)showAudit(r);}if(b.dataset.retryAppraisal){await api('/api/qq/retry-appraisal',{id:b.dataset.retryAppraisal});await refresh();await $('qqStatusBtn').onclick();notice('已重新排队；仅重试从未发送的认知判断。');}if(b.dataset.eventRecord){const row=events.find(r=>r.id===b.dataset.eventRecord);$('traceTitle').textContent=eventLabel(row.kind);$('traceBody').innerHTML='<pre>'+esc(JSON.stringify(row.payload,null,2))+'</pre>';$('traceDialog').showModal();}if(b.dataset.feature){const p=state.profile.id===b.dataset.profile?state.profile:Object.values(state.interlocutors).find(p=>p.id===b.dataset.profile);const f=p.psychology.features[b.dataset.feature];$('traceTitle').textContent=state.psychology_registry.find(x=>x.id===b.dataset.feature)?.name_zh||b.dataset.feature;$('traceBody').innerHTML=`<p class="fine">${esc(f.source_type)} · ${esc(f.method_version)} · ${esc(f.scope)}</p>`+p.psychology.observations.filter(o=>o.feature_id===b.dataset.feature).slice(-12).map(o=>`${meter('候选估计',o.estimate)}<p>${esc(o.source)}</p>${o.evidence.map(e=>`<blockquote>${esc(e.quote)}</blockquote><p class="record-id">${esc(e.record_id)}</p>`).join('')}`).join('');$('traceBody').innerHTML+='<details><summary>原始字段记录（未改写）</summary><pre>'+esc(JSON.stringify(f,null,2))+'</pre></details>';$('traceDialog').showModal();}}));
document.addEventListener('keydown',e=>{const b=e.target.closest('[role="tab"]');if(!b||!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const tabs=[...b.closest('[role="tablist"]').querySelectorAll('[role="tab"]')];let index=tabs.indexOf(b);index=e.key==='Home'?0:e.key==='End'?tabs.length-1:(index+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;selectTab(tabs[index].dataset.tab,true);});

const boundaryActionNames={answer:'正常回应',direct_refusal:'直接拒绝',polite_refusal:'委婉拒绝',defer:'暂不讨论',limited_disclosure:'部分披露',explain_boundary:'解释边界',ask_intent:'询问来意',redirect:'转移话题',humor:'幽默化解',correct_claim:'修正先前说法',no_action:'不发言'};
const boundaryStatusNames={confirmed:'已确认',provisional:'证据候选 · 弱参与',revoked:'已撤销'};
let executionData={runs:[],outbox:[]};
let calibrationSelection=null;
$('brmCalibrationForm').onsubmit=guard(async ev=>{ev.preventDefault();if(!calibrationSelection)throw new Error('请先选择实际边界判断');const r=await api('/api/boundaries/calibrate',{...calibrationSelection,activation:Number($('brmTarget').value),action:$('brmAction').value||null});$('brmCalibrationDialog').close();await refresh();notice(r.numeric_updated?'已更新边界头；仍需留出验证。':r.heldout?'已保存留出样本，本条不参与训练。':'已保存 API 校准示例。');});
function renderBoundaryModel(){
 const unavailable=!!state.component_errors?.boundaries||!state?.boundary_model;
 for(const id of ['newDynamicBoundary','boundaryEvidence','boundaryMetrics'])$(id).disabled=unavailable;
 if(state.component_errors?.boundaries){panelError('dynamicBoundaryList',state.component_errors.boundaries);return;}
 const b=state?.boundary_model;if(!b)return;const filter=$('boundaryFilter').value||'active',q=$('boundarySearch').value.trim().toLowerCase();
 $('boundaryModelSummary').textContent=`${b.boundaries.filter(v=>!v.archived&&v.status==='confirmed').length} 项确认边界 · ${b.boundaries.filter(v=>!v.archived&&v.status==='provisional').length} 项证据候选 · 数值头更新 ${b.numeric_head.steps} 次`;
 const rows=b.boundaries.filter(v=>(filter==='all'||filter==='archived'&&v.archived||filter==='revoked'&&!v.archived&&v.status==='revoked'||filter==='active'&&!v.archived&&v.status!=='revoked')&&(!q||[v.topic,v.recipient,v.scope].join(' ').toLowerCase().includes(q)));
 const groups=new Map();for(const v of rows){const k=JSON.stringify([v.domain,v.topic.trim(),v.scope,v.recipient]);if(!groups.has(k))groups.set(k,[]);groups.get(k).push(v);}
 $('dynamicBoundaryList').innerHTML=Array.from(groups.values()).map(g=>`<article class="boundary-state"><h3>${esc(g[0].topic)}</h3>${g.length>1?`<p class="fine">同主题、同对象、同范围的 ${g.length} 条记录；按来源保留，未擅自合并。</p>`:''}${g.map(v=>`<div class="boundary-version"><div class="row spread"><strong>${v.archived?'已删除（归档）':esc(boundaryStatusNames[v.status])}</strong><span>版本 ${v.version}</span></div><p class="fine">${v.origin==='owner_seed'?'主人设定':'外部证据推断'} · ${esc(v.scope)} · ${esc(v.recipient)}</p>${meter('长期敏感度',v.stable_sensitivity)}${meter('不确定性',v.uncertainty)}<p class="fine">支持 ${v.evidence_ids.length} / 反例 ${v.counterevidence_ids.length}</p><div class="row"><button data-brm-history="${esc(v.boundary_id)}">依据与版本</button>${v.archived?`<button data-brm-restore="${esc(v.boundary_id)}">恢复到已撤销</button>`:`<button data-brm-edit="${esc(v.boundary_id)}">${v.status==='provisional'?'检查并确认':'纠正'}</button>${v.status==='revoked'?`<button data-brm-archive="${esc(v.boundary_id)}">归档（保留历史引用）</button>`:`<button data-brm-revoke="${esc(v.boundary_id)}">撤销</button>`}`}</div></div>`).join('')}</article>`).join('')||'<p class="empty">当前筛选下没有边界记录。</p>';
 renderBoundaryHistory(b.recent.slice(-5).reverse());renderCalibrationResults();
}

function editDynamicBoundary(b){$('dynamicBoundaryId').value=b?.boundary_id||'';$('dynamicBoundaryTopic').value=b?.topic||'';$('dynamicBoundaryDomain').value=b?.domain||'disclosure';$('dynamicBoundaryStrength').value=b?.stable_sensitivity??.65;$('dynamicBoundaryScope').value=b?.scope||'*';$('dynamicBoundaryPerson').value=b?.recipient||'*';$('dynamicBoundaryDialog').showModal();}
function showBoundaryEvidence(id){const b=state.boundary_model;$('traceTitle').textContent='边界证据与修订';const rows=b.evidence.filter(r=>!id||r.boundary_id===id);$('traceBody').innerHTML='<p class="fine">外部反馈、主人修正与模型推断分别保留。AI 自己的回复不计为独立心理证据。</p>'+rows.map(r=>`<article><p>${r.polarity==='counter'?'反例':'支持'} · ${esc(r.source)} · ${esc(r.date)} · ${esc(r.person)}</p><blockquote>${esc(r.quote)}</blockquote><p>${esc(r.interpretation)}</p><p class="fine">其他解释：${r.alternative_explanations.map(esc).join('；')}</p></article>`).join('')+'<h3>修订记录</h3><pre>'+esc(JSON.stringify(b.history.filter(r=>!id||r.boundary_id===id),null,2))+'</pre>';$('traceDialog').showModal();}
const executionStatusNames={HOLD_HARD_CONSTRAINT:'硬约束待核实 · 未发送',CHECKER_UNAVAILABLE:'检查器不可用 · 待处理',CANDIDATE_REPAIR_REQUIRED:'候选需修复 · 未发送',INTERRUPTED_AFTER_ACK:'已发部分 · 因新事件停止',DELIVERY_INTERRUPTED:'已确认部分 · 剩余已停止',PARTIAL_COMMITTED:'已保存确认部分',DELIVERY_PARTIAL:'已发部分 · 后续接口失败',COMPLETED:'已完成',VALIDATION_FAILED:'输出校验失败',DELIVERY_FAILED:'QQ 明确发送失败',DELIVERY_UNKNOWN:'发送结果未知',POSTPROCESS_FAILED:'已发送 · 本地提交待恢复',FAILED:'处理失败',RUNNING:'处理中',CANCELLED:'已取消',PERMISSION_WITHDRAWN:'对方已撤回联系许可'};
function renderExecution(data){executionData=data;const m=data.metrics||{};$('executionMetrics').textContent=`成功回执样本 ${m.acknowledged_samples||0} · P50 ${m.p50_first_ack_ms==null?'暂无':seconds(m.p50_first_ack_ms)} · P95 ${m.p95_first_ack_ms==null?'暂无':seconds(m.p95_first_ack_ms)}。计时终点为 OneBot 回执，用户客户端收信时间尚无测量。`;
$('executionList').innerHTML=(data.runs||[]).map(r=>`<article class="decision-row"><div class="row spread"><strong>${esc(executionStatusNames[r.status]||r.status)}</strong><time>${date(r.started_at)}</time><button data-execution="${esc(r.turn_id)}">查看阶段与字段诊断</button></div><p>行动 ${esc(r.action_state||r.selected_action||'尚未决定')} · 候选 ${esc(r.candidate_status)} · 发送 ${esc(r.delivery_status)} · 学习 ${esc(r.learning_status||r.memory_commit_status)}</p><p class="record-id">Trace ${esc(r.trace_id)}</p>${r.candidate_inspection?`<p>候选检查：${esc(({SEND:"本地通过",SEND_WITH_NOTE:"通过，偏差已记录",HOLD_HARD_CONSTRAINT:"硬约束待核实",CHECKER_UNAVAILABLE:"检查器不可用",REPAIR_CANDIDATE:"修复已证实问题"})[r.candidate_inspection.disposition]||r.candidate_inspection.disposition)} · ${r.candidate_inspection.checker_status==="completed"?"已运行异常复核":r.candidate_inspection.checker_status==="unavailable"?"异常复核失败":"本地检查"}</p>`:""}<p class="fine">${r.cognitive_summary?.persisted?"已保留本轮认知中间记录，可核对失败前的组件状态。":""}</p></article>`).join('')||'<p class="empty">尚无执行记录。连接模型并发起对话后显示。</p>';}
async function loadExecution(){renderExecution(await api('/api/execution'));}
$('newDynamicBoundary').onclick=()=>editDynamicBoundary();
$('dynamicBoundaryForm').onsubmit=guard(async e=>{e.preventDefault();await api('/api/boundaries/edit',{op:'save',boundary_id:$('dynamicBoundaryId').value||undefined,topic:$('dynamicBoundaryTopic').value,domain:$('dynamicBoundaryDomain').value,stable_sensitivity:Number($('dynamicBoundaryStrength').value),scope:$('dynamicBoundaryScope').value,recipient:$('dynamicBoundaryPerson').value});$('dynamicBoundaryDialog').close();await refresh();notice('边界倾向已保存。');});
$('boundaryEvidence').onclick=()=>showBoundaryEvidence();
$('boundaryMetrics').onclick=()=>{$('traceTitle').textContent='边界校准与消融';$('traceBody').innerHTML='<p>当前指标仅基于独立事件的人工作答标注。无留出样本时显示 null；不把夹具测试当作心理效度。</p><pre>'+esc(JSON.stringify(state.boundary_model.metrics,null,2))+'</pre>';$('traceDialog').showModal();};
$('executionRefresh').onclick=guard(loadExecution);$('executionExport').onclick=guard(()=>download('/api/execution/export','HuaiAn_Execution_Trace.jsonl'));
$('executionRecover').onclick=guard(async()=>{const r=await api('/api/execution/recover',{});await refresh();await loadExecution();notice(`本地恢复完成 ${r.recovered?.length||0} 项；没有重新发送消息。`);});
$('receiptForm').onsubmit=guard(async e=>{e.preventDefault();await api('/api/execution/reconcile',{outbox_id:$('receiptOutbox').value,message_id:$('receiptMessage').value});await loadExecution();notice('真实回执已验证，已尝试恢复本地提交。');});
document.addEventListener('click',guard(async e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.brmEdit)editDynamicBoundary(state.boundary_model.boundaries.find(v=>v.boundary_id===b.dataset.brmEdit));if(b.dataset.brmRevoke){await api('/api/boundaries/edit',{op:'revoke',boundary_id:b.dataset.brmRevoke});await refresh();}if(b.dataset.brmHistory)showBoundaryEvidence(b.dataset.brmHistory);if(b.dataset.brmCalibrate){calibrationSelection={turn_id:b.dataset.brmCalibrate,boundary_id:b.dataset.brmId};$('brmTarget').value=.5;$('brmAction').innerHTML='<option value="">只校准激活程度</option>'+Object.entries(boundaryActionNames).map(([k,v])=>`<option value="${k}">${v}</option>`).join('');$('brmCalibrationDialog').showModal();}if(b.dataset.tab==='diagnostics-panel-execution')await loadExecution();if(b.dataset.execution){const r=executionData.runs.find(r=>r.turn_id===b.dataset.execution);$('traceTitle').textContent='执行与发送诊断';$('traceBody').innerHTML='<pre>'+esc(JSON.stringify(r,null,2))+'</pre>';$('traceDialog').showModal();}if(b.dataset.retryFailure){await api('/api/qq/retry-failed',{id:b.dataset.retryFailure});await refresh();notice('已重新排队确定未发送的原始事件。');}}));

$('loadEarlierMessages').onclick=guard(async()=>{const sid=sessionId,identity=state.identity.id,serial=refreshSerial;const button=$('loadEarlierMessages');button.disabled=true;try{const older=await api('/api/messages?session='+encodeURIComponent(sid)+'&offset='+messages.length);if(!Array.isArray(older))throw requestError('历史响应格式错误','/api/messages',200,'INVALID_RESPONSE');if(sid!==sessionId||identity!==state?.identity.id||serial!==refreshSerial)return;const known=new Set(messages.map(m=>m.id));messages=[...older.filter(m=>!known.has(m.id)),...messages];historyMore=older.length===2000;renderChat();$('chatLog').scrollTop=0;}finally{button.disabled=false;}});
$('retryLocal').onclick=async()=>{try{csrfToken='';await refresh();if(uiReady)notice('本地工作台已重新连接。');}catch(err){notice(err.message,true);}};
$('copyLocalError').onclick=async()=>{const text='页面 '+APP_VERSION+'\n'+$('localStatus').textContent+'\n'+$('notice').textContent+(state?'\n数据目录：'+state.data_status?.root+'\n主体：'+state.identity.id:'');try{await navigator.clipboard.writeText(text);notice('已复制诊断信息。');}catch{notice(text,true);}};
document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b||uiReady||recoveryControls.has(b.id)||b.dataset.view||b.dataset.close)return;e.preventDefault();e.stopImmediatePropagation();notice('本地数据尚未加载，请先重新连接。没有执行此次操作。',true);},true);
setDataReady(false);

function socialRecipients(){
 const rows=[];
 for(const [id,kind] of [['socialRecipients','private'],['socialGroupRecipients','group']])for(const value of splitList(id)){
  if(!/^[0-9]+$/.test(value))throw new Error((kind==='private'?'私聊 QQ 号':'群号')+'只填写数字，多个号码用逗号分隔。');
  const scope=kind+':qq:'+value;if(rows.includes(scope))throw new Error('主动联系号码重复，请删除重复项。');rows.push(scope);
 }
 return rows;
}
function renderSocialReadiness(){
 const q=state.config.qq,missing=[];
 if(!q.enabled)missing.push('启用并保存 QQ 连接');
 if(!q.self_id)missing.push('填写并保存机器人自己的 QQ 号');
 try{
  const recipients=socialRecipients();if(!recipients.length)missing.push('填写联系对象');
  for(const scope of recipients){const privateChat=scope.startsWith('private:'),field=privateChat?'allowed_users':'allowed_groups';
   if(!q[field].map(String).includes(scope.split(':').pop()))missing.push('将'+(privateChat?'私聊号码 ':'群号 ')+scope.split(':').pop()+' 加入 QQ 允许名单');
   if(!$(privateChat?'socialPrivate':'socialGroup').checked)missing.push('开启所填对象的'+(privateChat?'私聊':'群聊')+'主动联系开关');
  }
 }catch(err){missing.push(err.message);}
 const distinct=[...new Set(missing)];$('socialReadiness').textContent=distinct.length?'启用前还需：'+distinct.join('；')+'。可先关闭自动联系并保存草稿。':'配置条件已齐全。实际联系仍受交流记录、免打扰、预算和人格判断约束。';
 return distinct;
}
for(const id of ['socialRecipients','socialGroupRecipients','socialPrivate','socialGroup','socialEnabled'])$(id).oninput=()=>{if(uiReady)renderSocialReadiness();};

$('cloneTemplate').onchange=()=>{for(const id of ['newSeed','newSelfReference','newInitialPersonality'])$(id).disabled=$('cloneTemplate').checked;};
function sourceName(s){return {owner_seed:'主人设定（非测分）',questionnaire:'有题本及计分记录',promoted_evidence:'跨情境证据推断',model_inference:'模型候选估计',legacy_engineering:'旧版工程值',uncalibrated_engineering:'未校准工程估计',uncalibrated:'未校准先验',unknown:'未知',inferred:'历史工程推断（尚未按现行标准复核）'}[s]||s||'未知';}
function traitMeter(label,value,kind='estimate'){
 return `<div class="metric-${kind}" title="${kind==='uncertainty'?'越大表示估计越不确定；未经心理统计校准，不是置信概率':'特征估计值，范围 0–1，不是心理准确率'}">${meter(label,value)}</div>`;
}
function traitRow(profile,spec){
 const f=profile.psychology?.features?.[spec.id];if(!f)return '';
 const known=f.estimate!=null;
 return `<div class="construct-row ${known?'':'trait-unknown'}"><h4>${esc(spec.name_zh)}</h4>${known?traitMeter('特征估计值',f.estimate)+traitMeter('工程不确定性',f.posterior_uncertainty,'uncertainty'):'<p class="unknown-label">未知 · 尚无足够证据</p>'}<p class="fine">${esc(sourceName(f.source_type))} · ${f.updated_at?date(f.updated_at):'更新时间未记录'}</p><p class="record-id">来源类型 ID：${esc(f.source_type||'unknown')} · 字段：${esc(spec.id)}</p><button data-feature="${esc(spec.id)}" data-profile="${esc(profile.id)}">原始来源与依据</button></div>`;
}
function affectMeter(label,value,bipolar=false){return meter(label,value,1,bipolar);}
function renderAffect(){const a=state?.affect_state;if(!a){$('affectStatus').textContent='情绪状态尚不可用';return;}const e=a.emotion,m=a.mood,labels=state.emotion_catalog?.labels||{joy:'喜悦',sadness:'悲伤',anger:'愤怒',fear:'恐惧',disgust:'厌恶',surprise:'惊讶',interest:'兴趣',shame:'羞耻',guilt:'内疚',gratitude:'感激',pride:'自豪',frustration:'挫败'};
 $('affectStatus').textContent=`${state.profile.name} · 长期人格版本 ${state.profile.trait_profile?.version??0} · 即时情绪版本 ${e.state_revision} · ${sourceName(e.source_type)}。模型产生的值是模拟估计。`;
 $('currentAffect').innerHTML=affectMeter('效价 VA · V',e.valence,true)+affectMeter('唤醒 VA · A',e.arousal)+affectMeter('主导感 D',e.dominance);
 $('affectAuxiliary').innerHTML=affectMeter('压力',e.stress)+affectMeter('参与',e.engagement);
 const top=Object.entries(e.categorical_activations).filter(([,v])=>typeof v==='number'&&v>0).sort((a,b)=>b[1]-a[1]).slice(0,3);$('emotionTop').innerHTML=top.length?top.map(([k,v])=>meter(labels[k]||k,v)).join(''):'<p class="empty">暂无已激活类别；未知不等于没有情绪。</p>';
 $('moodPanel').innerHTML=affectMeter('心境效价',m.valence,true)+affectMeter('心境唤醒',m.arousal)+affectMeter('心境主导感',m.dominance)+meter('心境不确定性',m.uncertainty)+`<p class="fine">${esc(sourceName(m.source_type))}</p>`;
 $('affectProvenance').innerHTML=meter('当前状态估计置信度',e.confidence)+`<p class="fine">事件：${esc(e.event_id||'尚无')} · ${e.last_updated?date(e.last_updated):'来源时间未知'}</p>`;
 $('emotionLabels').innerHTML=Object.entries(labels).map(([k,label])=>{const d=state.emotion_details?.find(v=>v.id===k);return `<details class="habit-card"><summary>${esc(label)} · ${e.categorical_activations[k]===null?'未知':fmt(e.categorical_activations[k])}${d?.stale?' · 来源较旧':''}</summary>${meter(label,e.categorical_activations[k])}${meter('估计置信度',d?.confidence)}<p class="fine">${esc(d?.source||'未知')} · ${d?.last_triggered_at?date(d.last_triggered_at):'触发时间未知'} · 恢复时间参数 ${d?.time_constant??'—'} 秒（未校准）</p>${d?.quote?`<blockquote>${esc(d.quote)}</blockquote>`:''}<p class="record-id">${esc(d?.source_event_id||'尚无来源事件')}</p></details>`;}).join('');
 const last=a.expressions[a.expressions.length-1];$('actualExpression').innerHTML=last?`<p>${esc(actionNames[last.dialogue_action]||last.dialogue_action)} · ${esc({none:'自然表达',expressive_suppression:'表达抑制',cognitive_reappraisal:'认知重评'}[last.expression_strategy]||last.expression_strategy)}</p>${meter('计划表达强度',last.intensity)}<div class="row"><span class="tag">实际发送 ${last.actual_message_count} 条</span><span class="tag">${esc(last.delivery)}</span></div><p class="fine">人格版本 ${last.linked_trait_version} · 情绪版本 ${last.linked_emotion_revision} · ${date(last.at)}</p>`:'<p class="empty">尚无已执行表达；生成计划不算已发送。</p>';
 $('affectTrajectory').innerHTML=a.trajectory.length?'<table><thead><tr><th>事件时间</th><th>效价</th><th>唤醒</th><th>愤怒</th><th>心境</th><th>人格版本</th></tr></thead><tbody>'+a.trajectory.slice(-20).reverse().map(r=>`<tr><td>${date(r.at)}</td><td>${meter('效价',r.emotion.valence,1,true)}</td><td>${meter('唤醒',r.emotion.arousal,1,false)}</td><td>${meter('愤怒',r.emotion.categorical_activations.anger,1,false)}</td><td>${meter('心境效价',r.mood.valence,1,true)}</td><td>${r.trait_version}</td></tr>`).join('')+'</tbody></table>':'<p class="empty">开始对话后保存真实事件的状态轨迹。</p>';
}
function fillAffectParameters(){const p=state.affect_state?.transition_params;if(!p)return;for(const [k,id] of Object.entries({valence:'Valence',arousal:'Arousal',dominance:'Dominance',stress:'Stress',engagement:'Engagement'}))$('affectBase'+id).value=p.baseline[k]??'';$('affectTau').value=p.emotion_tau_seconds;$('moodTau').value=p.mood_tau_seconds;$('affectReactivity').value=p.reactivity;}
let traitEditVersion=null,traitEditIdentity=null;
function showHabitEvidence(key){const t=state.profile.trait_profile,f=t.dispositions[key];if(!f)return;const rows=t.disposition_observations.filter(o=>o.feature_id===key);$('traceTitle').textContent=state.disposition_registry.fields.find(x=>x.id===key)?.name_zh||key;$('traceBody').innerHTML=`<p>${esc(sourceName(f.source_type))} · 人格版本 ${t.version}</p><p>${esc(f.note||'尚无人工说明')}</p>${f.measurement?'<h3>量表记录</h3><pre>'+esc(JSON.stringify(f.measurement,null,2))+'</pre>':''}<h3>长期候选的原文依据</h3>`+(rows.map(o=>`<article><p>${esc(sourceName(o.source))} · ${esc(o.timeframe)}</p>${meter('候选估计',o.estimate)}${o.evidence.map(e=>`<blockquote>${esc(e.quote)}</blockquote><p class="record-id">${esc(e.record_id)}</p>`).join('')}</article>`).join('')||'<p>尚无独立原文证据；主人设定不等于完成量表。</p>');$('traceDialog').showModal();}
function openTraitSeed(key){const reg=state.psychology_registry.filter(f=>f.feature_temporality==='long'),habits=state.disposition_registry?.fields||[];$('traitSeedField').innerHTML=[...reg,...habits].map(f=>`<option value="${esc(f.id)}">${esc(f.name_zh)} · ${esc(f.id)}</option>`).join('');if(key)$('traitSeedField').value=key;traitEditVersion=state.profile.trait_profile.version;traitEditIdentity=state.identity.id;fillTraitSeedValue();$('traitSeedDialog').showModal();}
function fillTraitSeedValue(){const k=$('traitSeedField').value;const f=state.profile.trait_profile.dispositions[k]||state.profile.psychology.features[k];$('traitSeedValue').value=f?.estimate??'';$('traitSeedNote').value=f?.note||'';}
function renderTraitReview(r){const rows=r?.candidates||[];$('traitReviewPanel').innerHTML=rows.length?'<p class="fine">候选证据需来自独立事件、至少两个情境且跨越一天；来源不明或显著反例会阻止晋升。</p><div class="table-scroll"><table><thead><tr><th>候选</th><th>事件 / 情境</th><th>审查结果</th></tr></thead><tbody>'+rows.map(v=>`<tr><td>${esc(state.psychology_registry.find(f=>f.id===v.feature_id)?.name_zh||state.disposition_registry.fields.find(f=>f.id===v.feature_id)?.name_zh||v.feature_id)}</td><td>${v.independent_events} / ${v.contexts}</td><td>${v.eligible?'满足当前工程门槛':v.reasons.map(esc).join('；')}</td></tr>`).join('')+'</tbody></table></div>':'<p class="fine">尚无待审查的长期候选。旧版已保存的人格值继续可用；后续情绪事件不直接修改它们。</p>';}
function traitTraceHTML(t){if(!t)return '';return `<section class="trace-stage"><h3>人格 → 评价 → 情绪 → 调节 → 表达</h3><p>长期人格版本 ${t.trait_version} · 即时情绪版本 ${t.emotion_revision}</p><p class="fine">${esc(t.provider_contract)} · 评价 ${esc(t.appraisal_id)}</p><p>本轮调节：${esc(t.regulation_action?.strategy)} · ${t.expression_state?'已提交实际行动':'尚未提交'}</p>${meter('表达强度',t.expression_plan?.intensity)}${t.person_relational_appraisal?`<h4>本轮读取的关系解释条件</h4><p>关系版本 ${t.person_relational_appraisal.relation_version} · ${esc(t.person_relational_appraisal.scope)}</p><div class="metric-grid">${meter('威胁评价',t.person_relational_appraisal.estimates.threat)}${meter('澄清需要',t.person_relational_appraisal.estimates.clarification_need)}${meter('支持取向',t.person_relational_appraisal.estimates.support_orientation)}</div><p class="fine">${esc(t.person_relational_appraisal.interpretation)}</p>`:''}</section>`;}
$('editTraitSeed').onclick=guard(()=>openTraitSeed());
$('traitSeedField').onchange=fillTraitSeedValue;
$('traitSeedForm').onsubmit=guard(async()=>{if(traitEditIdentity!==state.identity.id)throw new Error('主体已切换，请重新打开长期设定');const k=$('traitSeedField').value;await api('/api/traits/disposition',{persona_id:traitEditIdentity,feature_id:k,expected_version:traitEditVersion,estimate:$('traitSeedValue').value===''?null:Number($('traitSeedValue').value),source_type:'owner_seed',timeframe:k.startsWith('panas.')?'generally':'habitual',note:$('traitSeedNote').value});$('traitSeedDialog').close();await refresh();notice('长期设定已保存；记忆和训练参数继续保留。');});
$('reviewTraitEvidence').onclick=guard(async()=>{const r=await api('/api/traits/review',{persona_id:state.identity.id,apply:state.config.pmm281.mode!=='full'});await refresh();notice(state.config.pmm281.mode==='full'?'审查完成：未写入稳定人格。已标定提案可在模型训练页核验。':`审查完成：${r.promoted} 项晋升。未满足门槛的候选继续保留。`);});
$('affectParametersForm').onsubmit=guard(async()=>{const baseline={};for(const [k,id] of Object.entries({valence:'Valence',arousal:'Arousal',dominance:'Dominance',stress:'Stress',engagement:'Engagement'})){const v=$('affectBase'+id).value;baseline[k]=v===''?null:Number(v);}await api('/api/affect/parameters',{persona_id:state.identity.id,baseline,emotion_tau_seconds:Number($('affectTau').value),mood_tau_seconds:Number($('moodTau').value),reactivity:Number($('affectReactivity').value)});await refresh();fillAffectParameters();notice('已保存本主体的工程参数，长期人格未改变。');});
document.addEventListener('click',guard(e=>{const b=e.target.closest('button');if(b?.dataset?.habitEdit)openTraitSeed(b.dataset.habitEdit);if(b?.dataset?.habitEvidence)showHabitEvidence(b.dataset.habitEvidence);}));


let affectPollTimer=null;
function stopAffectPolling(){if(affectPollTimer!=null)clearTimeout(affectPollTimer);affectPollTimer=null;}
function startAffectPolling(){stopAffectPolling();affectPollTimer=setTimeout(async()=>{try{if(page!=='affectPage'||!uiReady)return;const identity=state.identity.id,r=await api('/api/affect');if(state?.identity.id===identity&&r.persona_id===identity){state.affect_state=r.affect_state;state.emotion_details=r.emotion_details;renderAffect();}}catch(e){if(page==='affectPage')$('affectStatus').textContent='实时状态刷新失败：'+e.message;}finally{if(page==='affectPage')startAffectPolling();}},5000);affectPollTimer?.unref?.();}


const expressionActs={invitation:'邀请',tentative_interest:'尚在考虑',complaint:'倾诉与抱怨',question:'提问',closing:'结束交流',correction:'纠正',narrative:'叙事',unknown:'语境未知'};
const expressionStrategies={MINIMAL_REPLY:'最小充分回应',RESPOND_AND_YIELD:'回应后让轮',CASUAL_BURST:'自然连续气泡',OPTIONAL_EXPANSION:'有依据的补充',CLARIFY_IF_NEEDED:'必要时澄清',REPAIR:'修正误解',NO_ACTION:'不发言',WAIT:'等待真实输入'};
const expressionFields={local_relevance:'局部相关性',sufficiency:'回应充分性',redundancy_risk:'重复风险',premature_progression_risk:'过早推进风险',conversation_burden:'额外回答负担',spontaneous_motivation:'自发补充动机',persona_consistency:'人格一致性'};
function interactionHTML(p){if(!p?.schema)return '';return `<section class="trace-stage"><h3>本轮表达安排</h3><p>${esc(expressionStrategies[p.candidate_strategy]||p.candidate_strategy)} · ${esc(p.local_goal)}</p><p>追问：${p.allow_follow_up_question?'仅限 '+esc(p.follow_up_need||'真实信息缺口'):'本轮无需追问'}。${p.sufficiency_target==='complete'?'先保证必要信息完整。':'当前回应足够即可结束。'}</p><p>${esc(p.stop_reason||'完成后让轮')}</p><p>分条依据：${esc(p.layout_decision?.reason||p.split_reason||'未记录')}</p><p class="fine">最多 ${p.message_plan?.max_bubbles||1} 条，目标条数不预设；${esc(p.basis?.model_type)} · 未校准</p><div class="metric-grid">${Object.entries(expressionFields).map(([k,label])=>meter(label,p.evaluation?.[k])).join('')}</div></section>`;}
function renderExpression(){const data=state?.pragmatics;if(!data){$('expressionStatus').textContent='表达倾向尚不可用';return;}const p=data.profile;
 $('expressionStatus').textContent=`${state.profile.name} · 语用版本 ${p.version} · ${p.effective_episodes} 个独立示范事件 · ${p.contexts} 个情境 / ${p.days} 天。描述统计尚未校准，未训练独立语用神经头。`;
 $('pragmaticProfile').innerHTML=Object.entries(data.labels).map(([k,label])=>{const f=p.fields[k]||{};return `<article class="habit-card">${meter(label,f.estimate)}<p class="fine">${f.estimate==null?'尚无可用证据':(f.source_type==='human_episode_annotation'?'人工标注 · ':'人类示范统计 · ')+f.effective_episodes+' 个独立事件'} · 支持 ${f.support||0} / 反例 ${f.counterevidence||0}</p>${f.sampling_interval?`<p class="fine">95% 抽样区间 ${f.sampling_interval.map(fmt).join('–')}；不是心理置信度</p>`:''}</article>`}).join('');
 $('pragmaticContexts').innerHTML=Object.entries(p.burst_context_distribution||{}).map(([k,v])=>`<article>${meter((expressionActs[k]||k)+' · 多气泡比例',v.estimate)}<p class="fine">${v.effective_episodes} 个示范事件</p></article>`).join('')||'<p class="empty">还没有带时间戳、说话人和上下文的连发示范。</p>';
 const selected=$('pragmaticEpisode').value;$('pragmaticEpisode').innerHTML=(data.demonstration_choices||[]).map(r=>`<option value="${esc(r.id)}">${r.at?date(r.at):'无可靠时间'} · ${esc(r.scope||'导入情境')} · ${esc(expressionActs[r.prior_speech_act]||r.prior_speech_act)}</option>`).join('')||'<option value="">尚无已授权人类示范</option>';if(data.demonstration_choices?.some(r=>r.id===selected))$('pragmaticEpisode').value=selected;
 $('pragmaticField').innerHTML=Object.entries(data.labels).map(([k,v])=>`<option value="${esc(k)}">${esc(v)}</option>`).join('');$('savePragmaticAnnotation').disabled=!data.demonstration_choices?.length;renderPragmaticOriginal();
 $('pragmaticSources').textContent=`${p.untimed_records} 条无时间戳资料用于语言内容统计，不用于节奏学习。四条连续气泡按一个事件计数；当前情绪不会改写这些长期统计。`;
 $('expressionObservation').innerHTML=`<p>AI 实际表达 ${data.observed_ai_episodes} 轮 · 独立人工反馈 ${data.human_feedback_count} 条</p><p class="fine">实际气泡分布：${Object.entries(data.observed_bubble_distribution||{}).map(([k,v])=>esc(k)+' 条 × '+v+' 轮').join('；')||'尚无'}</p><p class="fine">AI 自己的输出只用于检查行为，不会作为自己的正确示范继续训练。${esc(data.evaluation_note)}</p>`;
 $('expressionPlans').innerHTML=(data.recent||[]).map((r,i)=>`<article class="decision-row"><div class="row spread"><strong>${esc(expressionStrategies[r.plan.candidate_strategy]||'旧版表达')}</strong><time>${date(r.at)}</time></div><p>${esc(r.plan.local_goal||'已确认的发送记录')}</p><p>实际 ${r.actual_bubbles} 条 · ${esc(executionStatusNames[r.status]||r.status)} · ${r.plan.allow_follow_up_question?'仅在需要时追问':'回应后停止'}</p><p class="fine">${esc(r.plan.stop_reason||'')} ${r.actual_bubbles===1?'一条已足够，无需凑满上限。':''}</p><button data-expression-index="${i}">查看依据与回执</button></article>`).join('')||'<p class="empty">开始对话后，这里显示为什么只说一条、为什么补充，以及实际发送了几条。</p>';
}
document.addEventListener('click',guard(async e=>{const b=e.target.closest('[data-expression-index]');if(!b)return;const r=state.pragmatics.recent[Number(b.dataset.expressionIndex)];if(!r)return;$('traceTitle').textContent='表达计划与实际发送';$('traceBody').innerHTML=interactionHTML(r.plan)+`<h3>实际发送</h3><p>${r.actual_bubbles} 条 · ${esc(r.status)}</p><p class="record-id">回执 ID：${r.message_ids.map(esc).join('、')||'本地对话，无 QQ 回执'}</p><details><summary>完整来源与计划</summary><pre>${esc(JSON.stringify(r,null,2))}</pre></details>`;$('traceDialog').showModal();}));

function renderPragmaticOriginal(){const r=state?.pragmatics?.demonstration_choices?.find(r=>r.id===$('pragmaticEpisode').value);$('pragmaticOriginal').textContent=r?(state.profile.source_records||[]).filter(v=>r.source_event_ids.includes(v.id)).map(v=>(v.context?'上文：'+v.context+'\n':'')+v.speaker+'：'+v.text).join('\n'):'导入有人物与来源的人工对话后可标注；时序标注还需可靠时间。';$('pragmaticValuePreview').innerHTML=meter('标注值',Number($('pragmaticValue').value));}
$('pragmaticEpisode').onchange=renderPragmaticOriginal;
$('pragmaticValue').oninput=()=>{$('pragmaticValuePreview').innerHTML=meter('标注值',Number($('pragmaticValue').value));};
$('pragmaticAnnotationForm').onsubmit=guard(async()=>{await api('/api/pragmatics/annotate',{persona_id:state.identity.id,episode_id:$('pragmaticEpisode').value,field:$('pragmaticField').value,value:Number($('pragmaticValue').value),note:$('pragmaticNote').value});await refresh();notice('人类示范标注已保存；长期人格、当前情绪和旧训练参数保持独立。');});

// 2.5 learning, calibrated-output receipts and scoped relationship review.
const learningNames={self:'自身人格',other:'交谈对象',relationship:'双边关系',language:'语言与语用',memory:'记忆',social_graph:'人际网络'};
const learningStates={ready:'待运行',running:'处理中',awaiting_review:'等待审阅',completed:'已应用',analysis_complete:'分析完成 · 未应用',paused:'已暂停',cancelled:'已取消',failed:'失败 · 进度已保留',rolled_back:'已回滚',budget_paused:'预算已到 · 可继续'};
let learningPreview=null,learningPolicyDirty=false,learningActivitiesOffset=0,boundaryHistoryOffset=0,boundaryHistoryTotal=0,graphResult=null;
function selectedValues(id){const el=$(id);return Array.from(el.selectedOptions||el.options||[]).filter(o=>o.selected!==false).map(o=>o.value).filter(Boolean);}
function setMultiOptions(id,items){const selected=new Set(selectedValues(id));$(id).innerHTML=items.map(v=>`<option value="${esc(v)}" ${selected.has(v)?'selected':''}>${esc(v)}</option>`).join('');}
function learningBody(){const range=$('learningRange').value,n=Number($('learningAmount').value);return {persona_id:state.identity.id,target:$('learningTarget').value,person:$('learningPerson').value.trim(),scopes:selectedValues('learningScopes'),source:'history',intent:$('learningIntent').value,include_observations:$('learningIncludeObservations').checked,train_weights:$('learningTrainWeights').checked,reanalyse:$('learningReanalyse').checked,...(range==='recent'?{limit:n}:range==='days'?{days:n}:range==='session'?{session_id:$('learningSession').value}:{})};}
function renderLearning(){
 const center=state?.learning_center;if(!center){$('learningOverview').innerHTML='<p>学习中心暂不可用，请查看本地诊断。</p>';return;}
 const p=center.policy;$('learningOverview').innerHTML=`<div class="learning-summary"><div><span>自动处理</span><strong>${p.paused?'已暂停':'按领域策略运行'}</strong></div><div><span>待后台整理</span><strong>${state.consolidation?.pending||0} 项</strong></div><div><span>已追踪任务</span><strong>${center.total_jobs}</strong></div><div><span>已应用的来源×目标</span><strong>${center.processed_sources}</strong></div></div><p class="fine">当前主体 ${esc(state.profile.name)} · 策略版本 ${p.version} · 人物与关系整理沿用“累计 ${state.config.performance?.batch_turns||5} 条 / 空闲 ${state.config.performance?.idle_seconds||60} 秒”的触发设置；自身经历成长按下方新增记忆数量单独触发。</p>${center.last_failure?`<p class="error">最近失败：${esc(center.last_failure.error||center.last_failure.status)} <button data-learning-detail="${esc(center.last_failure.id)}">查看任务</button></p>`:''}`;
 const legacy=center.legacy_generated_audit;if(legacy?.old_observations)$('learningOverview').innerHTML+=`<p class="callout">旧来源复核：发现 ${legacy.old_observations} 项旧观测引用生成回复。${esc(legacy.action)} 可用下方历史原文重新分析；未自动清空已训练权重。</p>`;
 if(!learningPolicyDirty){
  $('learningPolicyFields').innerHTML=Object.entries(p.domains).map(([d,r])=>`<fieldset class="learning-domain"><legend>${esc(learningNames[d])}</legend><label><input id="lp-enabled-${d}" type="checkbox" ${r.enabled?'checked':''}> 允许长期学习</label><label for="lp-mode-${d}">模式</label><select id="lp-mode-${d}">${[['manual','仅手动'],['candidate_only','自动收集候选，等待审阅'],['automatic','在证据门槛内自动更新']].map(([v,l])=>`<option value="${v}" ${r.mode===v?'selected':''}>${l}</option>`).join('')}</select><label for="lp-strength-${d}">更新强度 <output id="lp-value-${d}">${Math.round(r.strength*100)}%</output></label><input id="lp-strength-${d}" data-learning-strength="${d}" type="range" min="0" max="100" step="1" value="${Math.round(r.strength*100)}"><details><summary>范围与旁观授权</summary><label for="lp-scopes-${d}">允许范围（每行一个；留空沿用直接交互范围）</label><textarea id="lp-scopes-${d}" rows="2">${esc(r.scopes.join('\n'))}</textarea><label for="lp-people-${d}">允许人物（每行一个）</label><textarea id="lp-people-${d}" rows="2">${esc(r.people.join('\n'))}</textarea><label><input id="lp-group-${d}" type="checkbox" ${r.allow_group_observation?'checked':''}> 允许旁观学习（上方必须指定群与人物）</label></details></fieldset>`).join('');
  $('learningPaused').checked=p.paused;for(const [id,key] of [['learningBatchRecords','batch_records'],['learningBatchChars','batch_chars'],['learningMaxCalls','max_calls'],['learningMaxTokens','max_tokens']])$(id).value=p.budget[key];
  $('experienceLearningEnabled').checked=p.experience?.enabled ?? true;
  $('experienceLearningCount').value=p.experience?.new_memories ?? 10;
 }
 const experience=center.experience_learning;
 $('experienceLearningStatus').textContent=experience ? `待整理 ${experience.pending_memories} 条 / 每 ${experience.next_at} 条触发 · 已处理 ${experience.processed_events} 个事件 · 待确认人设变化 ${(experience.role_change_candidates||[]).length} 项 · 已生效补充 ${(experience.role_supplements||[]).length} 项（仅重大经历及后续证据触发）` : '经历学习状态尚未返回。';
 setMultiOptions('learningScopes',center.available_scopes||[]);setMultiOptions('graphScopes',center.available_scopes||[]);
 const selected=$('learningSession').value;$('learningSession').innerHTML='<option value="">选择会话</option>'+state.sessions.map(s=>`<option value="${esc(s.id)}" ${s.id===selected?'selected':''}>${esc(s.title)} · ${esc(s.person)} · ${esc(s.scope)}</option>`).join('');
 renderLearningJobs(center.jobs||[]);renderLearningPaging(center);renderCalibrationResults();renderOtherLearning();
}
function renderLearningJobs(jobs){
 $('learningJobs').innerHTML=jobs.map(j=>`<article class="learning-job"><div class="row spread"><strong>${esc(learningNames[j.target])} · ${esc(learningStates[j.status]||j.status)}</strong><time>${date(j.created_at)}</time></div><p>${esc(j.source==='import'?'导入资料':j.origin==='automatic'?'自动旁观整理':'已存历史')} · ${esc(j.person||'当前主体')} · ${j.source_count} 条来源</p><div class="job-progress"><progress max="${Math.max(1,j.source_count)}" value="${j.cursor}"></progress><span>${j.cursor} / ${j.source_count}</span></div><p class="fine">调用 ${j.usage.calls} 次 · Token ${j.usage.tokens}（${j.usage.token_accounting?'包含供应商用量或保守估计':'已返回用量'}） · 费用 ${typeof j.usage.cost==='number'?j.usage.cost:'未知'} · ${esc(j.id)}</p>${j.error?`<p class="error">${esc(j.error)}</p>`:''}<div class="row"><button data-learning-detail="${esc(j.id)}">来源、候选与写入差异</button>${['ready'].includes(j.status)?`<button data-learning-run="${esc(j.id)}">运行</button>`:''}${['paused','budget_paused','failed'].includes(j.status)?`<button data-learning-action="resume" data-learning-id="${esc(j.id)}">继续 / 重试一批预算</button>`:''}${j.status==='running'?`<button data-learning-action="pause" data-learning-id="${esc(j.id)}">暂停</button>`:''}${j.status==='awaiting_review'?`<button data-learning-action="approve" data-learning-id="${esc(j.id)}">审阅并应用</button><button data-learning-action="reject" data-learning-id="${esc(j.id)}">拒绝候选</button>`:''}${['ready','running','paused','budget_paused','failed'].includes(j.status)?`<button data-learning-action="cancel" data-learning-id="${esc(j.id)}">取消后续处理</button>`:''}${j.can_rollback?`<button data-learning-action="rollback" data-learning-id="${esc(j.id)}">回滚本任务写入</button>`:''}</div></article>`).join('')||'<p class="empty">还没有历史学习任务。可到“手动学习”选择已有记录并预览。</p>';
}
function changeHTML(changes){return changes?.length?`<table><thead><tr><th>字段</th><th>之前</th><th>之后</th></tr></thead><tbody>${changes.map(c=>`<tr><th>${esc(c.field)}</th><td>${typeof c.before==='number'&&c.before>=0&&c.before<=1?meter('之前',c.before):esc(c.before===null?'未知':JSON.stringify(c.before))}</td><td>${typeof c.after==='number'&&c.after>=0&&c.after<=1?meter('之后',c.after):esc(c.after===null?'未知':JSON.stringify(c.after))}</td></tr>`).join('')}</tbody></table>`:'<p class="fine">没有实际字段变化。</p>';}
async function showLearningDetail(id){const j=await api('/api/learning/job?id='+encodeURIComponent(id));$('traceTitle').textContent='学习任务 · '+(learningStates[j.status]||j.status);$('traceBody').innerHTML=`<p class="callout">${esc(learningNames[j.target])} · ${j.cursor}/${j.source_count} 条 · ${esc(j.id)}</p>${(j.audit||[]).map(a=>`<article><h3>实际写入：${esc(a.destination)}</h3><p>${a.weights_updated?'已更新数值权重':'未更新数值权重'} · ${esc(a.next_use||'仅应用此目标的有来源结果')}</p>${changeHTML(a.changed_fields)}${a.promotion?`<p>晋升 ${a.promotion.promoted} 项；未晋升原因：</p>${(a.promotion.candidates||[]).filter(c=>!c.eligible).map(c=>`<p class="fine">${esc(c.feature_id)}：${c.reasons.map(esc).join('；')}</p>`).join('')}`:''}</article>`).join('')||'<p>尚无已应用写入。候选、分析和失败结果保留如下。</p>'}<h3>候选结果</h3>${j.proposals.map(p=>`<details><summary>${esc(p.status)} · ${esc(p.id)}</summary><pre>${esc(JSON.stringify(p.report,null,2))}</pre></details>`).join('')}<h3>实际来源原文</h3>${j.evidence.map(r=>`<details><summary>${esc(r.person)} · ${esc(r.scope)} · ${esc(r.id)}</summary><blockquote>${esc(r.text)}</blockquote><p class="fine">${esc(r.source)} · ${esc(r.timestamp||'时间未知')}</p></details>`).join('')}`;$('traceDialog').showModal();}
async function refreshLearningActivities(reset=true){if(reset)learningActivitiesOffset=0;const rows=await api('/api/learning/activities?offset='+learningActivitiesOffset);const html=rows.map(r=>`<details class="activity-item"><summary>${date(r.created_at)} · ${esc(r.kind)} · ${esc(r.payload.person||r.payload.target||'')}</summary><p>${r.payload.weights_updated?'已更新权重':'未报告权重更新'} · ${esc(r.payload.status||r.payload.error||'')}</p>${changeHTML(r.payload.self_changes)}${changeHTML(r.payload.other_changes)}<pre>${esc(JSON.stringify(r.payload,null,2))}</pre></details>`).join('')||'<p class="fine">此范围暂无更多记录。</p>';if(reset)$('learningActivities').innerHTML=html;else $('learningActivities').insertAdjacentHTML('beforeend',html);learningActivitiesOffset+=rows.length;$('learningMoreActivities').disabled=rows.length<20;}
function renderOtherLearning(){const key=$('otherSelect').value,summary=(state.learning_center?.other_status||[]).find(r=>r.key===key);$('otherLearningStatus').innerHTML=summary?`<h3>这个对象的学习状态</h3><p>${esc(summary.status)}</p><div class="learning-summary"><div><span>已保存原文</span><strong>${summary.observed}</strong></div><div><span>待处理 / 失败</span><strong>${summary.pending} / ${summary.failed}</strong></div><div><span>候选证据</span><strong>${summary.candidates}</strong></div><div><span>已知稳定字段</span><strong>${summary.known_traits}</strong></div></div><p class="fine">${esc(summary.scope)} · ${esc(summary.person)} · ${summary.last_processed?date(summary.last_processed):'尚无已处理记录'}</p><p>${(summary.reasons||[]).map(esc).join('；')}</p>`:'<h3>尚无对象学习记录</h3><p>创建空档案不表示已经分析出人格。真实原文、后台队列和证据门槛会分别显示。</p>';}
function calibrationHTML(r){const fields=typeof r.prediction_before==='object'&&r.prediction_before!==null?Object.keys(r.targets||{}):['activation'];return `<details class="calibration-receipt"><summary>${r.heldout?'留出验证':r.numeric_updated?'数值头已更新':'API 校准示例已保存'} · ${esc(r.event_id||r.id)}</summary><p><strong>保存位置：</strong>${esc(r.destination)}</p><p>${esc(r.usage_note)}</p><p>${r.used_on_next_turn?'符合所列范围时可用于下一次估计':'不用于下一轮训练或提示'} · 人格字段${r.profile_updated?'已变更':'未变更'}</p>${fields.map(k=>`<div class="two-col">${meter('校准前 '+(cognitiveLabels[k]||k),typeof r.prediction_before==='object'?r.prediction_before?.[k]:r.prediction_before)}${meter('校准后 '+(cognitiveLabels[k]||k),typeof r.prediction_after==='object'?r.prediction_after?.[k]:r.prediction_after)}</div>`).join('')}<p class="fine">训练步骤 ${r.steps_before??'—'} → ${r.steps_after??'—'}。API 示例没有调用模型重算，校准后估计显示未知。</p></details>`;}
function renderCalibrationResults(){const br=(state.boundary_model?.calibration||[]).filter(r=>r.receipt).slice(-12).reverse();$('boundaryCalibrationResults').innerHTML=br.map(r=>calibrationHTML(r.receipt)).join('')||'<p class="fine">保存人工标注后，这里显示用途及前后结果。</p>';$('cognitiveCalibrationResults').innerHTML=(state.cognition?.calibration_results||[]).slice().reverse().map(calibrationHTML).join('')||'<p class="fine">尚无新版校准回执。旧标注保留在原数据中。</p>';}
function renderBoundaryHistory(records){const b=state.boundary_model;$('boundaryActivations').innerHTML=records.map(r=>`<details class="boundary-turn"><summary>${date(r.at)} · ${r.rows.length} 项判断 · ${esc(r.turn_id.slice(0,12))}</summary>${r.rows.map(v=>`<article><h4>${esc(b.boundaries.find(x=>x.boundary_id===v.boundary_id)?.topic||v.boundary_id)}</h4><p class="fine">${esc(v.person)} / ${esc(v.scope)} · ${esc(v.mechanism)}${v.status==='unavailable'?' · 估计不可用':''}</p>${meter('本次激活',v.activation)}${v.cue?.quote?`<blockquote>${esc(v.cue.quote)}</blockquote>`:''}${v.activation!==null?`<button data-brm-calibrate="${esc(r.turn_id)}" data-brm-id="${esc(v.boundary_id)}">校准本次判断</button>`:'<p>本次失败估计不作为训练样本。</p>'}</article>`).join('')}</details>`).join('')||'<p class="empty">尚无匹配的情境判断。</p>';}
async function loadBoundaryHistory(reset=false){if(reset)boundaryHistoryOffset=0;const r=await api('/api/boundaries/history?offset='+boundaryHistoryOffset+'&q='+encodeURIComponent($('boundaryHistorySearch').value));boundaryHistoryTotal=r.total;renderBoundaryHistory(r.items);$('boundaryHistoryCount').textContent=`${r.total?boundaryHistoryOffset+1:0}–${Math.min(r.total,boundaryHistoryOffset+r.items.length)} / ${r.total} 回合`;$('boundaryHistoryPrevious').disabled=boundaryHistoryOffset===0;$('boundaryHistoryNext').disabled=boundaryHistoryOffset+10>=r.total;}
function renderGraph(r){graphResult=r;const people=r.people.slice(0,60),W=800,H=Math.max(260,Math.ceil(people.length/5)*110),positions=new Map(people.map((p,i)=>[p.person_id,{x:85+(i%5)*155,y:60+Math.floor(i/5)*110}]));const edges=r.relation_claims.filter(c=>c.status!=='retracted'&&positions.has(c.subject_person_id)&&positions.has(c.object_person_id));$('graphSummary').innerHTML=`<h3>${r.people.length} 人 · ${r.contexts.length} 个情境 · ${r.relation_claims.length} 条陈述</h3><p class="fine">实线表示人工确认，虚线表示未核验/有争议；连线有方向，单方陈述不推断互认。图中最多显示60人，全部来源保留在下方。</p>`;
 $('graphCanvas').innerHTML=people.length?`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="所选范围内的人际关系陈述"><defs><marker id="graphArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"/></marker></defs>${edges.map(c=>{const a=positions.get(c.subject_person_id),b=positions.get(c.object_person_id);return `<line x1="${a.x}" y1="${a.y+15}" x2="${b.x}" y2="${b.y-15}" class="graph-edge ${c.status==='confirmed'?'confirmed':''}" marker-end="url(#graphArrow)"><title>${esc(c.relation_type+' · '+c.status+' · '+c.scope_id)}</title></line>`;}).join('')}${people.map(p=>{const a=positions.get(p.person_id);return `<g><circle cx="${a.x}" cy="${a.y}" r="17"/><text x="${a.x}" y="${a.y+40}" text-anchor="middle">${esc(p.alias.slice(0,19))}</text><title>${esc(p.person_id)}</title></g>`;}).join('')}</svg>`:'<p class="empty">所选范围暂无已授权图谱记录。可在学习与蒸馏中启用人际网络领域并预览原文。</p>';
 $('graphIntersections').innerHTML=r.intersections.map(x=>`<p>${esc(x.person_id)} 出现在 ${x.contexts.map(esc).join('、')}。${esc(x.meaning)}</p>`).join('');
 const names={self_report:'本人单方陈述',third_party_report:'第三方转述',observed:'实际观察',inferred:'模型推测',confirmed:'已核验'};
 $('graphClaims').innerHTML=r.relation_claims.map(c=>`<details class="graph-claim"><summary>${esc(c.subject_person_id)} → ${esc(c.object_person_id)} · ${esc(c.relation_type)} · ${esc({unverified:'待核验',confirmed:'人工确认',disputed:'有争议',retracted:'已撤回'}[c.status])}</summary><p>${esc(names[c.knowledge_type])} · ${esc(c.scope_id)} · 版本 ${c.version}</p>${meter('陈述置信度（未校准）',c.confidence)}${meter('不确定性',c.uncertainty)}${c.evidence.map(e=>`<blockquote>${esc(e.quote)}</blockquote><p class="record-id">说话者 ${esc(e.speaker)} · ${esc(e.record_id)}</p>`).join('')}<label>核验或撤回说明 <input data-graph-reason="${esc(c.id)}" maxlength="1000"></label><div class="row">${[['confirm','人工确认'],['dispute','标记争议'],['retract','撤回']].map(([op,l])=>`<button data-graph-op="${op}" data-graph-id="${esc(c.id)}">${l}</button>`).join('')}</div></details>`).join('')||'<p class="fine">同群出现不会自动生成朋友关系。</p>';
}
async function queryGraph(){const scopes=selectedValues('graphScopes');if(!scopes.length)throw new Error('请选择至少一个可查询范围');renderGraph(await api('/api/social-graph?'+scopes.map(s=>'scope='+encodeURIComponent(s)).join('&')+'&person='+encodeURIComponent($('graphPerson').value.trim())));}
function bindLearningUI(){
 $('learningPolicyForm').oninput=e=>{learningPolicyDirty=true;const d=e.target.dataset?.learningStrength;if(d)$('lp-value-'+d).textContent=e.target.value+'%';};
 $('learningPolicyForm').onsubmit=guard(async()=>{
  const p=JSON.parse(JSON.stringify(state.learning_center.policy));
  for(const d of Object.keys(p.domains)) p.domains[d]={enabled:$('lp-enabled-'+d).checked,mode:$('lp-mode-'+d).value,strength:Number($('lp-strength-'+d).value)/100,scopes:$('lp-scopes-'+d).value.split('\n').map(s=>s.trim()).filter(Boolean),people:$('lp-people-'+d).value.split('\n').map(s=>s.trim()).filter(Boolean),allow_group_observation:$('lp-group-'+d).checked};
  p.paused=$('learningPaused').checked;
  p.experience={...(p.experience || {max_attempts:3,retry_seconds:300}),enabled:$('experienceLearningEnabled').checked,new_memories:Number($('experienceLearningCount').value)};
  for(const [id,k] of [['learningBatchRecords','batch_records'],['learningBatchChars','batch_chars'],['learningMaxCalls','max_calls'],['learningMaxTokens','max_tokens']])p.budget[k]=Number($(id).value);
  await api('/api/learning/policy',{persona_id:state.identity.id,expected_version:state.learning_center.policy.version,policy:p});
  learningPolicyDirty=false;learningPreview=null;$('learningCreate').disabled=true;await refresh();notice('学习策略已保存；已有历史不会被自动重新扫描。');
 });
 $('learningPreset').onchange=()=>{const preset=$('learningPreset').value;if(preset==='custom')return;const strength={observe:50,cautious:20,standard:50,broad:80}[preset];for(const d of Object.keys(learningNames)){$('lp-mode-'+d).value=preset==='observe'?'candidate_only':'automatic';$('lp-strength-'+d).value=strength;$('lp-value-'+d).textContent=strength+'%';}learningPolicyDirty=true;};
 $('learningPreviewForm').onchange=()=>{learningPreview=null;$('learningCreate').disabled=true;};
 $('learningPreviewForm').onsubmit=guard(async()=>{const body=learningBody();if($('learningRange').value==='session'&&!body.session_id)throw new Error('请选择会话');const p=await api('/api/learning/preview',body);learningPreview={body,preview:p};$('learningPreviewResult').innerHTML=`<div class="callout">${p.source_count} 条可用原文 · ${p.duplicate_count} 条已处理 · ${p.excluded_count} 条被策略排除<br>预计 ${p.estimated_calls} 次调用 / ${p.estimated_tokens} Token，实际费用未知。</div><p class="fine">${esc(p.self_source_rule||p.estimate_note)}</p>${p.excluded.map(r=>`<p class="fine">${esc(r.id)}：${r.reasons.map(esc).join('；')}</p>`).join('')}<div class="source-preview">${p.samples.map(r=>`<details><summary>${esc(r.person)} · ${esc(r.scope)} · ${esc(r.id)}</summary><blockquote>${esc(r.text)}</blockquote></details>`).join('')}</div>`;$('learningCreate').disabled=!p.source_count;});
 $('learningCreate').onclick=guard(async()=>{if(!learningPreview)throw new Error('请先预览当前范围');const {body,preview}=learningPreview;const j=await api('/api/learning/create',{...body,authorized:true,source_digest:preview.source_digest,policy_version:preview.policy_version});learningPreview=null;$('learningCreate').disabled=true;await runJob(await api('/api/learning/run',{persona_id:state.identity.id,id:j.id}),'learning');await refreshLearningActivities();});
 $('learningRefresh').onclick=guard(async()=>{await refresh();await refreshLearningActivities();});$('learningMoreActivities').onclick=guard(()=>refreshLearningActivities(false));
 $('boundaryFilter').onchange=renderBoundaryModel;$('boundarySearch').oninput=renderBoundaryModel;$('boundaryHistoryForm').onsubmit=guard(()=>loadBoundaryHistory(true));$('boundaryHistoryPrevious').onclick=guard(()=>{boundaryHistoryOffset=Math.max(0,boundaryHistoryOffset-10);return loadBoundaryHistory();});$('boundaryHistoryNext').onclick=guard(()=>{boundaryHistoryOffset+=10;return loadBoundaryHistory();});
 $('graphQueryForm').onsubmit=guard(queryGraph);
 document.addEventListener('click',guard(async e=>{const b=e.target.closest('button');if(!b)return;const d=b.dataset;
  if(d.learningDetail)return showLearningDetail(d.learningDetail);
  if(d.learningRun)return runJob(await api('/api/learning/run',{persona_id:state.identity.id,id:d.learningRun}),'learning');
  if(d.learningAction){if(d.learningAction==='approve'&&!window.confirm('将审阅此任务所有候选，并仅应用通过证据门槛的结果。确认继续？'))return;const r=await api('/api/learning/control',{persona_id:state.identity.id,id:d.learningId,action:d.learningAction,extend_budget:d.learningAction==='resume'});if(d.learningAction==='resume')await runJob(await api('/api/learning/run',{persona_id:state.identity.id,id:r.id}),'learning');else await refresh();return;}
  if(d.brmArchive||d.brmRestore){await api('/api/boundaries/edit',{boundary_id:d.brmArchive||d.brmRestore,op:d.brmArchive?'archive':'restore'});await refresh();return;}
  if(d.graphOp){const input=Array.from(document.querySelectorAll('[data-graph-reason]')).find(x=>x.dataset.graphReason===d.graphId);await api('/api/social-graph/edit',{persona_id:state.identity.id,id:d.graphId,op:d.graphOp,reason:input?.value||'',expected_version:graphResult.version});await queryGraph();}
 }));
}
bindLearningUI();

let learningJobsOffset=0,learningMonitor=null;
function learningPreviewHTML(p){return `<p class="callout">${p.source_count} 条可用原文 · ${p.duplicate_count} 条已处理 · ${p.excluded_count} 条被策略排除</p><p>预计 ${p.estimated_calls} 次调用 / ${p.estimated_tokens} Token；费用未知。</p><p class="fine">${esc(p.self_source_rule||p.estimate_note)}</p>${p.samples.map(r=>`<details><summary>${esc(r.person)} · ${esc(r.scope)} · ${esc(r.id)}</summary><blockquote>${esc(r.text)}</blockquote></details>`).join('')}`;}
async function runLearningJob(result){
 if(learningMonitor===result.job_id)return;learningMonitor=result.job_id;const identity=state.identity.id;
 try{while(state?.identity.id===identity){const j=await api('/api/jobs/'+result.job_id);if(state?.identity.id!==identity)return;updateJobOperationReceipt(j,identity);$('learningProgress').textContent=j.phase||'后台处理中，对话仍可使用';
  if(j.status==='error'){await refresh();updateJobOperationReceipt(j,identity);const error=new Error(j.error);error.operationReceiptHandled=true;throw error;}
  if(j.status==='done'){await refresh();await refreshLearningActivities();$('learningProgress').textContent='此批已结束，可查看状态、来源与实际写入差异。';updateJobOperationReceipt(j,identity);return j.result;}
  const center=await api('/api/learning?offset='+learningJobsOffset);if(state?.identity.id!==identity)return;state.learning_center=center;renderLearningJobs(center.jobs);renderLearningPaging(center);await new Promise(resolve=>setTimeout(resolve,900));
 }}catch(error){error.operationReceiptContext={owner:identity,job_id:result.job_id};throw error;}finally{if(learningMonitor===result.job_id)learningMonitor=null;}
}
function renderLearningPaging(c=state.learning_center){if(!c)return;$('learningJobPage').textContent=`共 ${c.total_jobs} 个任务 · 第 ${Math.floor((c.offset||0)/50)+1} 页`;$('learningJobsPrevious').disabled=!(c.offset>0);$('learningJobsNext').disabled=(c.offset||0)+c.jobs.length>=c.total_jobs;}
async function loadLearningJobs(delta=0){learningJobsOffset=Math.max(0,learningJobsOffset+delta);const c=await api('/api/learning?offset='+learningJobsOffset);state.learning_center=c;renderLearningJobs(c.jobs);renderLearningPaging(c);}
$('learningJobsPrevious').onclick=guard(()=>loadLearningJobs(-50));$('learningJobsNext').onclick=guard(()=>loadLearningJobs(50));
$('synthesisCandidates').onclick=guard(async()=>{
 const r=state.synthesis;if(!r?.source_record_ids?.length)throw new Error('这份报告尚无可引用的真人原文；请先导入示范或保存人工校正。');
 showPage('distill','distill-manual');$('learningTarget').value='self';$('learningRange').value='all';$('learningIntent').value='review';$('learningReanalyse').checked=true;
 const ids=new Set(r.source_record_ids),scopes=new Set(state.profile.source_records.filter(x=>ids.has(x.id)).map(x=>x.scope||'self:imported'));
 for(const o of $('learningScopes').options)o.selected=scopes.has(o.value);
 const body={...learningBody(),source_report_id:r.id};const preview=await api('/api/learning/preview',body);learningPreview={body,preview};$('learningPreviewResult').innerHTML=learningPreviewHTML(preview);$('learningCreate').disabled=!preview.source_count;
 notice('已选择报告对应的原文并生成预览；创建后会重新提取候选，报告文字本身不会写成人格。');
});

// UI state only: memory-resident drafts, no browser persistence of keys or messages.
const formDrafts=new Map(),disclosureState=new Map();
function draftKey(id){return (state?.identity?.id||'loading')+'::'+id;}
function takeDraft(id){const key=draftKey(id),draft=formDrafts.get(key);formDrafts.delete(key);return draft;}
function captureDraft(e){
 const form=e.target?.closest?.('form');if(!form?.id||form.id==='chatForm'||!state)return;
 const fields={};form.querySelectorAll('input,select,textarea').forEach(el=>{
  if(!el.id||(el.type||el.attrs?.type)==='file')return;
  fields[el.id]={value:el.value,checked:el.checked,selected:el.multiple?[...el.selectedOptions].map(v=>v.value):null};
 });formDrafts.set(draftKey(form.id),fields);updateDraftStatus();
}
function updateDraftStatus(){
 const count=[...formDrafts.keys()].filter(k=>k.startsWith((state?.identity?.id||'loading')+'::')).length;
 $('draftStatus').hidden=!count;$('draftStatus').textContent=count?`${count} 个表单尚未提交。切页与后台刷新会保留本页草稿；关闭或刷新浏览器前请保存。`:'';
}
function restoreDrafts(){
 const prefix=(state?.identity?.id||'loading')+'::';
 for(const [key,fields] of formDrafts){if(!key.startsWith(prefix))continue;for(const [id,v] of Object.entries(fields)){
  const el=document.getElementById(id);if(!el)continue;
  if(v.selected&&el.options){for(const option of el.options)option.selected=v.selected.includes(option.value);}else el.value=v.value;
  if(typeof v.checked==='boolean')el.checked=v.checked;
 }}updateDraftStatus();
 for(const el of document.querySelectorAll('[data-disclosure]')){const v=disclosureState.get(draftKey(el.dataset.disclosure));if(v!==undefined)el.open=v;}
}
document.addEventListener('input',captureDraft);
document.addEventListener('change',captureDraft);
document.addEventListener('toggle',e=>{if(e.target?.dataset?.disclosure)disclosureState.set(draftKey(e.target.dataset.disclosure),e.target.open);},true);
globalThis.addEventListener?.('beforeunload',e=>{if(formDrafts.size){e.preventDefault();e.returnValue='';}});
let lastDialogOpener=null;
document.addEventListener('click',e=>{if(!document.querySelector('dialog[open]'))lastDialogOpener=e.target?.closest?.('button')||lastDialogOpener;},true);
document.querySelectorAll('dialog').forEach(d=>d.addEventListener('close',()=>{lastDialogOpener?.focus?.();}));

function updateRoute(){
 if(!globalThis.history?.replaceState)return;
 const active=[...$(page).querySelectorAll('[role="tab"]')].find(b=>b.getAttribute('aria-selected')==='true');
 const hash='#view='+encodeURIComponent(page)+(active?'&tab='+encodeURIComponent(active.dataset.tab):'');
 globalThis.history.replaceState(null,'',hash);
}
function restoreRoute(){
 const hash=globalThis.location?.hash;if(!hash)return;
 const parts=new URLSearchParams(hash.replace(/^#/,'')),view=parts.get('view');
 if(view)showPage(view,parts.get('tab'),false);
}
globalThis.addEventListener?.('hashchange',restoreRoute);
function operationTarget(path){
 if(path==='/api/cognition/feedback')return ['diagnostics','diagnostics-panel-cognition','认知校准结果'];
 if(path.startsWith('/api/execution'))return ['diagnostics','diagnostics-panel-execution','执行与发送回执'];
 if(path==='/api/traits/disposition')return ['profiles','profiles-self','长期倾向设定'];
 if(path==='/api/persona/settings')return ['profiles','profiles-settings','人物设定'];
 if(path==='/api/persona/checkpoint')return ['research','research-checkpoints','人格检查点'];
 if(path==='/api/pragmatics/review')return ['distill','distill-results','语言审核写入'];
 if(path==='/api/pragmatics/target')return ['expressionPage','language-evidence','人工反馈候选'];
 if(path==='/api/pragmatics/annotate')return ['expressionPage','language-evidence','示范标注结果'];
 if(path==='/api/learning/policy')return ['distill','distill-policy','学习策略'];
 if(path==='/api/distill')return ['distill','learningPage','导入学习任务'];
 if(path.includes('/boundar'))return ['profiles','profiles-boundaries','人际边界与校准'];
 if(path.includes('/traits')||path.includes('/persona/synthesize'))return ['profiles','profiles-evidence','人格证据与修订'];
 if(path.includes('/learning')||path.includes('/import')||path.includes('/consolidation'))return ['distill','learningPage','学习任务'];
 if(path.includes('/pragmatics')||path.includes('/feedback'))return ['expressionPage','language-actual','语言表现与反馈'];
 if(path.includes('/affect'))return ['affectPage','affect-parameters','情绪状态参数'];
 if(path.includes('/memory'))return ['memory','memory-panel-list','记忆与来源'];
 if(path.includes('/social-graph'))return ['profiles','graphPage','人际网络'];
 if(path.includes('/pmm/')||path==='/api/restore')return ['research','research-parameters','数据与版本'];
 if(path.includes('/config')||path.includes('/connection'))return ['diagnostics','diagnostics-panel-history','配置操作记录'];
 return ['diagnostics','diagnostics-panel-history','操作记录'];
}
function recordOperation(path,result,owner=state?.identity?.id){
 if(owner!==state?.identity?.id)return;
 if(path==='/api/learning/preview'||path==='/api/import/preview'||path==='/api/chat')return;
 const [view,tab,label]=operationTarget(path),job=result.learning_job||result.job||(result.target&&result.id?result:{}),status=result.status||job.status;
 const domainStatus=status?(learningStates[status]||executionStatusNames[status]||status):null;
 const jobStatus={queued:'已排队，尚未完成',running:'处理中',done:domainStatus?'本批已结束 · '+domainStatus:'已完成',error:'处理失败'}[result.async_job_status];
 const actual=jobStatus|| (domainStatus|| (result.job_id?'已排队，尚未完成':result.ok===false?'未完成':'请求已完成'));
 activeOperationReceipt={owner,path,job_id:result.job_id||null};
 const id=result.job_id||job.id||result.id||result.boundary_id;
 const text=`${state?.profile?.name||'当前主体'} · ${label} · ${actual}${id?' · 记录 ID：'+id:''}${typeof result.promoted==='number'?' · 实际晋升 '+result.promoted+' 项':''}`;
 $('operationReceipt').innerHTML=`<div><strong>${esc(text)}</strong><p class="fine">${esc(result.message||result.warning||'实际字段变化、证据与写入状态请查看对应记录。')}</p></div><div class="row">${job.id?`<button type="button" data-learning-detail="${esc(job.id)}">此任务的原文与变化 →</button>`:''}<button type="button" data-goto="${view}" data-target-tab="${tab}">查看结果 →</button></div>`;$('operationReceipt').hidden=false;
}
function updateJobOperationReceipt(job,owner){
 const receipt=activeOperationReceipt;if(!receipt||owner!==state?.identity?.id||receipt.owner!==owner||receipt.job_id!==job.id)return false;
 recordOperation(receipt.path,{...(job.result||{}),job_id:job.id,async_job_status:job.status,...(job.status==='error'?{message:job.error}: {})},owner);return true;
}
function showFailureReceipt(error){
 if(error.operationReceiptHandled)return;
 const context=error.operationReceiptContext;if(context&&(context.owner!==state?.identity?.id||activeOperationReceipt?.owner!==context.owner||activeOperationReceipt?.job_id!==context.job_id))return;
 activeOperationReceipt=null;
 $('operationReceipt').innerHTML=`<div><strong>操作未完成</strong><p>${esc(error.message||error)}${error.request_id?' · 请求 ID：'+esc(error.request_id):''}</p></div><button type="button" data-goto="diagnostics" data-target-tab="diagnostics-panel-history">查看错误记录 →</button>`;$('operationReceipt').hidden=false;
}

function renderAffectRecords(){
 const a=state?.affect_state;if(!a)return;
 const records=(rows,label)=>rows.slice(-20).reverse().map(r=>`<details><summary>${r.at?date(r.at):'历史记录 · 时间未知'} · ${esc(r.strategy||r.event_id||label)}</summary><p class="record-id">${esc(r.id||r.appraisal_id||r.feature_id||'未记录标识')}</p>${r.quote?'<blockquote>'+esc(r.quote)+'</blockquote>':''}<pre>${esc(JSON.stringify(r,null,2))}</pre></details>`).join('')||`<p class="empty">尚无${label}记录。收到事件并完成处理后可在这里核对。</p>`;
 $('affectAppraisals').innerHTML=records(a.appraisals||[],'事件评价');$('affectRegulations').innerHTML=records(a.regulation_actions||[],'情绪调节');
}
$('otherSearch').oninput=()=>{renderProfiles();renderOtherLearning();};
$('exportLegacyMedia').onclick=guard(()=>download('/api/export/legacy-media','legacy_media_archive.zip'));
// Rendering may refresh options and fields. Restore only this identity's drafts.
const baseRenderVersions=renderVersions;
renderVersions=function(){baseRenderVersions();$('personaRevisionSummary').innerHTML=personaRevisions.slice(0,8).map(r=>`<p class="fine">${esc(r.label||r.reason||'已保存的人格状态')} · ${r.created_at?date(r.created_at):'时间未记录'} · ${esc(r.id)}</p>`).join('')||'<p class="empty">尚无已保存人格检查点。可在数据与版本中保存当前状态。</p>';};
const baseRenderProfiles=renderProfiles,baseRenderExpression=renderExpression,baseRenderLearning=renderLearning,baseOpenSettings=openSettings,baseFillOperations=fillOperations,baseFillAffectParameters=fillAffectParameters,baseRenderAffect=renderAffect;
renderProfiles=function(){baseRenderProfiles();restoreDrafts();};
renderExpression=function(){baseRenderExpression();deVisiblePage=null;renderDE();restoreDrafts();renderDECandidate();};
renderLearning=function(){baseRenderLearning();$('recentAppliedLearning').innerHTML=(state?.learning_center?.jobs||[]).filter(j=>['completed','rolled_back'].includes(j.status)).slice(0,6).map(j=>`<p>${esc(learningNames[j.target])} · ${esc(learningStates[j.status])} <button data-learning-detail="${esc(j.id)}">核对实际写入 · ${esc(j.id.slice(0,8))}</button></p>`).join('')||'<p class="fine">最近任务中暂无完成或回滚记录。完成状态也不保证发生字段变化，需核对任务差异。</p>';restoreDrafts();};
openSettings=function(navigate=true){baseOpenSettings(navigate);restoreDrafts();};
fillOperations=function(){baseFillOperations();restoreDrafts();};
fillAffectParameters=function(){baseFillAffectParameters();restoreDrafts();};
renderAffect=function(){baseRenderAffect();renderAffectRecords();restoreDrafts();};

const deLabels={long_term_language:'长期语言习惯',emotion:'即时情绪',mood:'慢变心境',stable_trait:'稳定人格',situation:'当前情境',observed_ai:'AI 实际发送'};
const deUse={scored:'参与评分或表达控制',read:'已读取',recorded_only:'仅记录，未参与'};
const deTone={steady:'平稳',restrained:'克制',warm:'温暖',no_action:'不发言'};
const deReasons={insufficient_independent_events:'至少需要两个独立事件',conflicting_evidence_requires_more_review:'证据分歧较大，需要复核',already_applied:'这版证据已经应用',owner_rejected_current_evidence:'本版证据已由人工驳回',scope_not_authorized:'该会话范围未授权',person_not_authorized:'该对象未授权',domain_disabled:'语言学习已关闭',strength_zero:'语言学习强度为零',no_explicit_target_or_corrected_example:'仅评价好坏，缺少明确目标或校正示范'};
function deReason(xs){return (xs||[]).map(x=>deReasons[x]||x).join('；');}
const deAxes={valence:'愉悦度',arousal:'唤醒度',dominance:'掌控感',stress:'压力',engagement:'投入度'};
function deEmpty(s){return `<p class="empty">${esc(s)}</p>`;}
function deOptions(id,rows,empty){const el=$(id),old=el.value;el.innerHTML=rows.map(([v,l])=>`<option value="${esc(v)}">${esc(l)}</option>`).join('')||`<option value="">${esc(empty)}</option>`;if(rows.some(x=>x[0]===old))el.value=old;}
function deProof(r){return `${esc(r.scope||'导入资料')} · ${esc(expressionActs[r.prior_speech_act]||r.prior_speech_act)} · ${r.effective_events} 个独立事件`;}
function renderDE(){const data=state?.pragmatics;if(!data)return;const s=data.profile,t=s.text_style||{},rows=data.learning_candidates||[];
 $('deTextStats').innerHTML=`<p>可用文本：<strong>${t.effective_events||0}</strong> 个独立事件，其中 ${t.untimed_events||0} 个没有可靠时间；平均句长 ${t.mean_sentence_characters==null?'未知':t.mean_sentence_characters.toFixed(1)+' 字'}。</p><p class="fine">常见原文片段：${Object.keys(t.surface_phrases||{}).slice(0,8).map(esc).join('、')||'暂无资料'}。标点只描述表面形式，不自动解释修辞意图。</p>`;
 $('deCandidates').innerHTML=rows.slice(0,30).map(r=>`<div class="decision-row">${meter(data.labels[r.field]||r.field,r.estimate)}<p>${deProof(r)} · ${esc(r.status==='applied'?'已应用':r.eligible?'待人工审核':'未采纳')}</p><p class="fine">${esc(deReason(r.reasons)||'达到工程门槛，可核对来源后应用。')}</p></div>`).join('')||deEmpty('还没有候选。可在本页标注人类示范，或到“实际发送与反馈”评价具体回合。');
 deOptions('deCandidate',rows.map(r=>[r.id,(data.labels[r.field]||r.field)+' · '+(r.scope||'导入资料')+' · '+(expressionActs[r.prior_speech_act]||r.prior_speech_act)]),'尚无候选');renderDECandidate();
 const turns=(data.recent||[]).filter(r=>r.actual_bubbles>0);deOptions('deTargetTurn',turns.map(r=>[r.turn_id,date(r.at)+' · '+(expressionActs[r.plan?.previous_act]||'对话')+' · 实际 '+r.actual_bubbles+' 条']),'尚无成功发送的回合');
 deOptions('deTargetField',Object.entries(data.labels||{}),'尚无字段');$('deTargetSave').disabled=!turns.length;$('deTargetValuePreview').innerHTML=meter('建议倾向',Number($('deTargetValue').value));
 const hist=(data.review_history||[]).slice(-12).reverse();$('deReviewHistory').innerHTML=hist.map(h=>`<div class="decision-row"><strong>语言档案 v${h.version_before} → v${h.version_after}</strong> · ${esc(({apply:'应用',reject:'驳回',revoke:'撤销'})[h.action])}<p>${(h.changed_fields||[]).map(x=>esc(data.labels[x.field]||x.field)+'：'+fmt(x.before)+' → '+fmt(x.after)).join('；')}</p><p>${esc(h.note)}</p></div>`).join('')||deEmpty('尚无人工审核结果。');
 $('deUnusedFeedback').textContent=(data.unusable_feedback||[]).length?`有 ${data.unusable_feedback.length} 条最近的好坏评价缺少明确目标，未用于学习。`:'没有等待补充目标的评价。';
 renderDETurns(state.de_turns);
}
function renderDECandidate(){const c=state?.pragmatics?.learning_candidates?.find(r=>r.id===$('deCandidate').value);$('deReviewApply').disabled=!c?.eligible;$('deReviewReject').disabled=!c;$('deReviewRevoke').disabled=c?.status!=='applied';$('deCandidateEvidence').textContent=c?(c.evidence||[]).map(e=>`${e.source_type==='independent_owner_annotation'?'人类示范标注':'独立人工反馈'} · ${e.person||'人物未记'} · ${e.authorization_scope} · ${e.source_event_ids.join('、')}\n${e.note} → ${fmt(e.value)}`).join('\n\n'):'请选择有人类证据的候选。';}
function renderDETurns(result){const list=result?.rows||[];const joint=list.filter(r=>r.joint&&r.affect_committed);
 $('expressionPlans').innerHTML=list.map(r=>`<article class="decision-row"><div class="row spread"><strong>${esc(expressionStrategies[r.strategy]||'历史表达')}</strong><time>${date(r.at)}</time></div><p>${esc(r.joint?.event?.quote||'旧记录未保存联合条件')}</p><p>计划 ${r.planned_bubbles??'未知'} 条 · 实际 ${r.actual_confirmed} 条${r.delivery==='DELIVERY_UNKNOWN'?'已确认，另有回执未知':''} · ${esc(executionStatusNames[r.delivery]||r.delivery||'未记录')}</p><button type="button" data-de-turn="${esc(r.turn_id)}">查看依据与回执</button></article>`).join('')||deEmpty('开始对话后，可核对同一回合的输入、计划与确认发送。');
 $('deTurnPage').textContent=result?.total?`${result.offset+1}–${result.offset+list.length} / ${result.total} 轮`:'0 轮';$('dePrevious').disabled=!result?.offset;$('deNext').disabled=!result||result.offset+list.length>=result.total;
 const latest=(state.de_turns?.rows||[]).find(r=>r.joint&&r.affect_committed);$('deAffectEvent').innerHTML=latest?`<p>${esc(latest.joint.event.quote)} · 情绪 v${latest.joint.emotion_revision}</p>${deChangeHTML(latest.joint.event_change)}<button type="button" data-de-turn="${esc(latest.turn_id)}">核对同轮表达与发送</button>`:deEmpty('尚无已提交事件。仅读取时钟不会产生新事件。');
}
function deChangeHTML(change){if(!change)return '';return `<p class="fine">现实经过 ${change.clock?.elapsed_seconds==null?'未知':change.clock.elapsed_seconds.toFixed(1)+' 秒'}；轮次只标记事件顺序。前值是事件发生时、按现实时间演化后的状态。</p><div class="de-changes">${Object.entries(change.emotion||{}).map(([k,x])=>`<div>${meter(deAxes[k]||k,x.after,1,k==='valence')}<small>事件前 ${fmt(x.before)} → 后 ${fmt(x.after)} · 差值 ${fmt(x.delta)}</small></div>`).join('')}</div>`;}
function deDetail(r){const j=r.joint;const data=state.pragmatics;return (j?`<p><strong>${esc(j.event.quote)}</strong></p><p class="record-id">输入事件 ${esc(j.event.original_ids.join('、'))} · 回合 ${esc(r.turn_id)}</p><p>语言 v${j.language_version??'未知'} · 情绪 v${j.emotion_revision??'未知'} · 人格 v${j.trait_version??'未知'}</p><p>策略：${esc(expressionStrategies[j.strategy_before]||j.strategy_before)} → <strong>${esc(expressionStrategies[j.strategy_after]||j.strategy_after)}</strong> · 外显语气：${esc(deTone[j.tone]||j.tone)}</p><p>分条依据：${j.grounded_split_purpose?'有独立内容与当前输入依据':'未用情绪或习惯强制分条'}；追问仍需满足本轮交际条件。</p>${meter('计划外显强度',j.expression_intensity)}<h3>条件实际如何参与</h3>${j.usage.map(u=>`<p><strong>${esc(deLabels[u.condition]||u.condition)}</strong> · ${esc(deUse[u.status]||u.status)}</p>`).join('')}<p class="fine">“已读取”只表示条件传入。可核对本地评分项，无法据此归因云模型的每个词。</p><h3>${r.affect_committed?'已提交的情绪变化':'候选情绪变化（未提交）'}</h3>${deChangeHTML(j.event_change)}`:deEmpty('这是旧版回合，未记录联合条件；保留当时能核对的事实。'))+`<h3>实际发送与人工反馈</h3>${(r.actual_parts||[]).map(v=>'<blockquote>'+esc(v)+'</blockquote>').join('')}<p>计划 ${r.planned_bubbles??'未知'} · 确认 ${r.actual_confirmed} · ${esc(executionStatusNames[r.delivery]||r.delivery||'未知')}</p><p class="record-id">回执：${r.receipt_ids.length?r.receipt_ids.map(esc).join('、'):r.delivery==='LOCAL_COMMITTED'?'本地对话提交':'无已确认 QQ 消息 ID'}</p>${r.feedback.map(f=>`<p>${esc(f.note||'未填写说明')} ${Object.entries(f.targets||{}).map(([k,v])=>esc(data.labels[k]||k)+' '+fmt(v)).join('；')}</p>`).join('')||'<p>尚无独立人工评价。</p>'}<details><summary>数值贡献、原始事件与回执明细</summary><pre>${esc(JSON.stringify(r,null,2))}</pre></details>`;}
let deVisiblePage=null;
async function deMove(offset){const identity=state.identity.id,result=await api('/api/de/turns?offset='+Math.max(0,offset));if(state.identity.id!==identity||result.persona_id!==identity)return;deVisiblePage=result;renderDETurns(result);}
$('dePrevious').onclick=guard(()=>deMove((deVisiblePage||state.de_turns).offset-12));$('deNext').onclick=guard(()=>deMove((deVisiblePage||state.de_turns).offset+12));
document.addEventListener('click',guard(e=>{const btn=e.target.closest?.('[data-de-turn]');if(!btn)return;const r=[...(deVisiblePage?.rows||[]),...(state.de_turns?.rows||[])].find(x=>x.turn_id===btn.dataset.deTurn);if(r){$('traceTitle').textContent='本轮语言、情绪与实际发送';$('traceBody').innerHTML=deDetail(r);$('traceDialog').showModal();}}));
$('deCandidate').onchange=renderDECandidate;$('deTargetValue').oninput=()=>{$('deTargetValuePreview').innerHTML=meter('建议倾向',Number($('deTargetValue').value));};
$('deFeedbackForm').onsubmit=guard(async()=>{const res=await api('/api/pragmatics/target',{persona_id:state.identity.id,turn_id:$('deTargetTurn').value,field:$('deTargetField').value,value:Number($('deTargetValue').value),note:$('deTargetNote').value});await refresh();notice('已记录人工目标，可在“已有学习证据”核对候选。语言档案 v'+res.version);});
$('deReviewForm').onsubmit=guard(async e=>{const action=e.submitter?.dataset?.deReview||'apply',p=state.pragmatics,c=p.learning_candidates.find(x=>x.id===$('deCandidate').value);if(!c)throw Error('请选择要审核的候选');const result=await api('/api/pragmatics/review',{persona_id:state.identity.id,candidate_id:c.id,evidence_digest:c.evidence_digest,expected_version:p.profile.version,action,note:$('deReviewNote').value});if(!result.ok)throw Error('未应用：'+deReason(result.reasons));await refresh();notice('审核已记录，语言档案 v'+result.version+'。到“蒸馏 → 结果与证据”可核对字段前后值。');});

// 2.7: existing profiles/other pages, same PMM state and provenance index.
let formationTurnCache=[],peopleV27Result=null,evidenceV27Offset=0,evidenceV27Total=0;
function v27FeatureName(k){return state.psychology_registry.find(f=>f.id===k)?.name_zh||state.disposition_registry.fields.find(f=>f.id===k)?.name_zh||k;}
function preserveOptions(id,items){const el=$(id),old=el.value;el.innerHTML=items.map(([v,l])=>`<option value="${esc(v)}">${esc(l)}</option>`).join('');if(items.some(([v])=>v===old))el.value=old;}
function renderFormationStatus(){
 if(!$('formationHistory'))return;
 preserveOptions('formationSession',state.sessions.map(s=>[s.id,`${s.person} · ${s.scope} · ${s.title||'对话'}`]));
 const scopes=[...new Set(state.sessions.map(s=>s.scope))];for(const id of ['peopleScope','evidenceScope'])preserveOptions(id,scopes.map(s=>[s,s]));
 preserveOptions('formationFeature',[...state.psychology_registry.filter(f=>f.feature_temporality==='long'),...state.disposition_registry.fields].map(f=>[f.id,f.name_zh]));
 const history=state.profile.trait_profile.promotion_history.slice(-20).reverse();
 $('formationHistory').innerHTML=history.map(h=>`<article class="evidence"><h4>${esc(v27FeatureName(h.feature_id))} · 版本 ${h.trait_version}</h4><div class="metric-grid">${meter('更新前',h.before?.estimate)}${meter('更新后',h.after?.estimate)}</div><p class="fine">${esc(h.method)} · ${h.independent_events??'—'} 个独立事件 · ${h.contexts??'—'} 个情境</p>${(h.source_evidence||[]).map(e=>`<blockquote>${esc(e.quote)}</blockquote><p class="record-id">${esc(e.record_id)}</p>`).join('')}</article>`).join('')||'<p class="empty">尚无长期修订。</p>';
 const ev=state.profile.psychology.evidence_records.filter(r=>r.subject_entity==='agent_self').slice(-30).reverse();
 $('formationEvidence').innerHTML=ev.map(r=>`<article class="evidence"><p>${esc(r.scope)} · 经历 ${esc(r.experience_turn_id)}</p><blockquote>${esc(r.text)}</blockquote><p>${r.withdrawn?'已撤回：'+esc(r.withdrawal_reason):'外部评价；估计仍受独立证据门槛约束'}</p>${r.withdrawn?'':`<button type="button" data-formation-withdraw="${esc(r.id)}">撤回此依据</button>`}</article>`).join('')||'<p class="empty">尚无针对 AI 实际经历的外部评价。</p>';
}
function relationshipSchemaHTML(d){const rows=d.schemata||[];return `<h4>关系图式 · 版本 ${d.schema_revision||0}</h4><p class="fine">角色、规范与期待均附来源；未知不推断为友谊。</p>`+(rows.map(r=>`<article class="evidence"><p>${esc({role:'角色',norm:'交往规范',expectation:'互动期待'}[r.kind])} · ${r.knowledge_type==='reported'?'原话陈述':'模型推断'} · ${esc({active:'当前有效',disputed:'有争议',retracted:'已撤回'}[r.status])}</p><p>${esc(r.statement)}</p>${meter('不确定性（未校准）',r.uncertainty)}${r.evidence.slice(-3).map(e=>`<blockquote>${esc(e.quote)}</blockquote><p class="record-id">${esc(e.event_id)}</p>`).join('')}<button type="button" data-rel-revise="${esc(r.id)}" data-rel-person="${esc(d.other_id)}" data-rel-scope="${esc(d.context_id)}" data-rel-version="${d.schema_revision}" data-rel-op="${r.status==='active'?'dispute':'restore'}">${r.status==='active'?'标记争议':'恢复候选'}</button> <button type="button" data-rel-revise="${esc(r.id)}" data-rel-person="${esc(d.other_id)}" data-rel-scope="${esc(d.context_id)}" data-rel-version="${d.schema_revision}" data-rel-op="retract">撤回图式</button></article>`).join('')||'<p class="empty">尚无有依据的关系图式。</p>')+`<details><summary>关系修订历史（最近20项）</summary><pre>${esc(JSON.stringify((d.schema_history||[]).slice(-20),null,2))}</pre></details>`;}
async function loadPeopleV27(){const scope=$('peopleScope').value;if(!scope)throw new Error('请选择会话范围');const r=await api('/api/people?scope='+encodeURIComponent(scope));peopleV27Result=r;
 $('peopleV27').innerHTML=`<p class="fine">${esc(r.identity_rule)}</p>`+r.people.map(p=>`<article class="evidence"><h4>${esc(p.alias)} · ${p.entity_type==='interlocutor'?'交谈对象':'提及的第三方'}</h4><p class="record-id">${esc(p.person_id)} · ${esc(p.scope)}</p>${meter('身份不确定性',p.uncertainty)}<p>${esc(p.identity_status)} · ${p.source_count} 条本范围来源</p>${p.relationship?relationshipSchemaHTML(p.relationship):'<p class="fine">尚无与 AI 的特定关系证据。</p>'}<details><summary>人物原始证据（最近50条）</summary>${p.sources.map(e=>`<blockquote>${esc(e.text)}</blockquote><p class="record-id">${esc(e.record_id)} · ${esc(e.source_type)}</p>`).join('')}</details></article>`).join('');
 const sources=r.people.flatMap(p=>p.sources).filter(s=>s.source_type!=='generated');preserveOptions('identitySource',sources.map(s=>[s.source_key,`${s.person}：${s.text.slice(0,80)}`]));
}
async function loadEvidenceV27(){const scope=$('evidenceScope').value;if(!scope)throw new Error('请选择会话范围');const r=await api('/api/evidence?scope='+encodeURIComponent(scope)+'&offset='+evidenceV27Offset+'&limit=10');evidenceV27Total=r.total;
 $('unifiedEvidenceTrace').innerHTML=`<p>共 ${r.total} 项修订 · 当前 ${r.offset+1}–${Math.min(r.offset+r.revisions.length,r.total)}</p>`+r.revisions.map(v=>`<details class="evidence"><summary>${esc(v.domain)} · ${date(v.at)} · ${v.changed?'有状态变化':'仅登记来源'}</summary>${v.source_keys.map(k=>`<blockquote>${esc(r.sources[k].text)}</blockquote><p class="record-id">${esc(r.sources[k].record_id)} · ${esc(r.sources[k].event_id)}</p>`).join('')}<p>${v.mixed_scope_details_redacted?'跨范围任务的其他详情已隐藏。':''}</p><pre>${esc(JSON.stringify({before:v.before,after:v.after,links:v.links,path:v.path,rolled_back:v.rolled_back},null,2))}</pre></details>`).join('');
 $('previousEvidenceTrace').disabled=evidenceV27Offset===0;$('nextEvidenceTrace').disabled=evidenceV27Offset+10>=r.total;
}
$('loadPeople').onclick=guard(loadPeopleV27);
$('identityEvidenceForm').onsubmit=guard(async()=>{if(!peopleV27Result||peopleV27Result.scope!==$('peopleScope').value)throw new Error('请先读取当前范围人物');await api('/api/people/edit',{persona_id:state.identity.id,expected_version:peopleV27Result.version,scope:$('peopleScope').value,person:$('identityPerson').value.trim(),alias:$('identityAlias').value.trim(),source_key:$('identitySource').value,quote:$('identityQuote').value,op:$('identityOp').value});await loadPeopleV27();notice('本范围身份依据已保存。');});
$('loadFormationTurns').onclick=guard(async()=>{const s=state.sessions.find(s=>s.id===$('formationSession').value);if(!s)throw new Error('请选择经历所在会话');const rows=await api('/api/formation/interactions?scope='+encodeURIComponent(s.scope)+'&person='+encodeURIComponent(s.person));formationTurnCache=rows;preserveOptions('formationTurn',rows.map(r=>[r.turn_id,`${date(r.timestamp)} · ${r.actual_reply.slice(0,100)}`]));$('formationOriginalInput').textContent='当时用户输入：'+(rows.find(r=>r.turn_id===$('formationTurn').value)?.original_input||rows[0]?.original_input||'无可用回合');});
$('formationTurn').onchange=()=>{$('formationOriginalInput').textContent='当时用户输入：'+(formationTurnCache.find(r=>r.turn_id===$('formationTurn').value)?.original_input||'');};
$('formationSession').onchange=()=>{formationTurnCache=[];$('formationOriginalInput').textContent='';$('formationTurn').innerHTML='<option value="">请重新读取这个会话的经历</option>';};
for(const id of ['formationValue','formationConfidence'])$(id).oninput=()=>$(id+'Out').textContent=Number($(id).value).toFixed(2);
$('formationForm').onsubmit=guard(async()=>{const feature=$('formationFeature').value,field=state.disposition_registry.fields.find(f=>f.id===feature);const r=await api('/api/formation/annotate',{persona_id:state.identity.id,expected_version:state.profile.trait_profile.version,experience_turn_id:$('formationTurn').value,feature_id:feature,estimate:Number($('formationValue').value),confidence:Number($('formationConfidence').value),timeframe:field?.required_timeframe||'sustained',context_label:$('formationContext').value,context_quote:$('formationContextQuote').value,note:$('formationNote').value});await refresh();$('formationResult').textContent=`新增候选 ${r.accepted} 项；晋升 ${r.promoted} 项。详细门槛与变化见上方审查表及下方修订记录。`;});
$('loadEvidenceTrace').onclick=guard(async()=>{evidenceV27Offset=0;await loadEvidenceV27();});$('previousEvidenceTrace').onclick=guard(async()=>{evidenceV27Offset=Math.max(0,evidenceV27Offset-10);await loadEvidenceV27();});$('nextEvidenceTrace').onclick=guard(async()=>{if(evidenceV27Offset+10<evidenceV27Total)evidenceV27Offset+=10;await loadEvidenceV27();});
document.addEventListener('click',guard(async e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.formationWithdraw){const reason=prompt('请填写撤回依据。依赖此依据晋升的字段会转为未知，历史会保留。');if(!reason)return;await api('/api/formation/withdraw',{persona_id:state.identity.id,expected_version:state.profile.trait_profile.version,record_id:b.dataset.formationWithdraw,reason});await refresh();}if(b.dataset.relRevise){const reason=prompt('请填写关系图式修订理由');if(!reason)return;await api('/api/relationships/revise',{persona_id:state.identity.id,person:b.dataset.relPerson,scope:b.dataset.relScope,expected_version:Number(b.dataset.relVersion),id:b.dataset.relRevise,op:b.dataset.relOp,reason});await refresh();if(peopleV27Result)await loadPeopleV27();}}));


$('compareFormationDecision').onclick=guard(async()=>{const r=await api('/api/research/decision-compare',{persona_id:state.identity.id,turn_id:$('formationTurn').value,feature_id:$('formationFeature').value});
 const labels={without_personality:'移除人格',without_relationship:'移除关系',without_regulation:'移除长期情绪倾向',low:'所选字段 0.2',high:'所选字段 0.8'};
 $('decisionComparison').innerHTML=`<h4>同一事件的固定条件对照</h4><p>${esc(r.interpretation)}</p><p class="record-id">输入 ${esc(r.input_digest)} · 模型 ${esc(r.model_digest)}</p><p>基线行动：${esc(actionNames[r.rows.baseline.decision.action])} · 重现当时行动：${r.reproduces_actual_base_action?'是':'否，请检查记录'}</p>`+r.comparisons.map(v=>`<article class="evidence"><h4>${esc(labels[v.condition])}</h4><p>${esc(v.finding)} · 行动：${esc(actionNames[r.rows[v.condition].decision.action])}</p>${meter('最大行动评分差异',v.max_absolute_score_change)}${meter('表达强度差异',v.expression_change,1,true)}<p>调节策略：${esc(r.rows[v.condition].regulation)} · 关系评价${v.appraisal_changed?'有变化':'未变'}</p><details><summary>各行动贡献与固定条件</summary><pre>${esc(JSON.stringify({contributions:r.rows[v.condition].contributions,fixed:r.fixed,gate:r.rows[v.condition].decision.gate},null,2))}</pre></details></article>`).join('');
});



async function refreshPmm28(){
 const owner=state?.identity?.id;if(!owner)return;
 const [status,traces,longitudinal]=await Promise.all([api('/api/pmm28/status'),api('/api/pmm28/traces'),api('/api/pmm28/longitudinal')]);
 if(owner!==state?.identity?.id)return;
 pmm28Status=status;pmm28Traces=traces.traces;pmm28Longitudinal=longitudinal;
 $('pmm28Readiness').textContent=`${state.config.pmm281.mode==='full'?'完整 PMM':'备用兼容模式'} · ${status.calibration==='uncalibrated'?'网络未校准，未加入神经概率评分':'行为留出检验通过'} · 长期更新：${status.config.long_term_mode}。门禁：${status.release_gate}`;
 const selected=$('pmm28Turn').value;$('pmm28Turn').innerHTML=pmm28Traces.map(t=>`<option value="${esc(t.turn_id)}">${date(t.timestamp||0)} · ${esc(t.scope)} · ${esc(t.official_decision?.action||'未记录')}</option>`).join('')||'<option value="">暂无新版回合</option>';
 if(pmm28Traces.some(t=>t.turn_id===selected))$('pmm28Turn').value=selected;
 const old=$('pmm28ModelVersion').value;$('pmm28ModelVersion').innerHTML=status.models.versions.map(v=>`<option value="${esc(v.sha256)}">${esc(v.sha256.slice(0,12))} · ${v.steps} 步 · ${v.revoked?'已撤销':v.sha256===status.models.published?'已发布':v.frozen?'已冻结':'候选'}${v.engineering_only?' · 工程数据':''}</option>`).join('')||'<option value="">暂无候选权重</option>';
 if(status.models.versions.some(v=>v.sha256===old))$('pmm28ModelVersion').value=old;
 $('pmm28DataStatus').textContent=`已登记 ${status.samples.count} 条标签 · 数据版本 ${status.samples.revision}。训练不覆盖已发布权重。`;
 $('pmm28ScaleProtocol').innerHTML=Object.entries(longitudinal.protocols||{}).map(([k,v])=>`<option value="${esc(k)}">${esc(k.slice(0,12))} · ${v.model.construct_ids.length} 个面向 · ${v.model.validated?'待实时核验':'未通过发布标定'}</option>`).join('')||'<option value="">尚无测量标定</option>';
 const proposals=Object.values(longitudinal.proposals||{});$('pmm28LongStatus').textContent=`${Object.keys(longitudinal.protocols||{}).length} 个测量标定 · ${Object.keys(longitudinal.transitions||{}).length} 个纵向模型 · ${proposals.length} 个候选。参数未验证时 G 禁用。`;
 $('pmm28Proposal').innerHTML=proposals.map(p=>`<option value="${esc(p.payload.proposal_id)}">${esc(p.payload.proposal_id.slice(0,12))} · ${p.committed?'已提交':p.engineering_only?'工程候选，不可提交':p.status}</option>`).join('')||'<option value="">暂无长期候选</option>';
 $('pmm28Sample').innerHTML=(status.samples.recent||[]).map(r=>`<option value="${esc(r.key)}">${esc(r.key.slice(0,10))} · ${esc(r.subject_id)} · ${esc(r.task)}${r.withdrawn?' · 已撤回':''}</option>`).join('')||'<option value="">暂无审核标签</option>';
 renderPmm28Turn();renderPmm28Validation();renderPmm28Sources();
}
function renderPmm28Turn(){
 const t=pmm28Traces.find(t=>t.turn_id===$('pmm28Turn').value)||pmm28Traces[0];
 if(!t){$('pmm28Components').innerHTML='<p class="empty">完成一轮完整 PMM 对话后，可查看组件凭证。</p>';$('pmm28Coverage').innerHTML='';return;}
 const components=t.components||{},blocks=components.neural?.payload?.blocks||{},names={H:'HEXACO 面向',V:'Schwartz 价值',I:'人际倾向',L:'长期语言身份',D:'长期情绪与调节倾向'};
 $('pmm28Coverage').innerHTML=Object.entries(blocks).map(([k,v])=>{const count=v.mask.reduce((a,b)=>a+b,0);return `<div class="pmm28-coverage"><div class="row spread"><span>${esc(names[k]||k)} · 有依据的输入</span><strong>${count} / ${v.mask.length}</strong></div><progress value="${count}" max="${v.mask.length}" aria-label="${esc(names[k])}已知项数"></progress></div>`;}).join('');
 const labels={memory:'记忆与证据',reasoner:'内部 API 推理',affect:'情绪动力学',relationship:'关系认知',neural:'人格神经计算',decision:'决策协调'};
 $('pmm28Components').innerHTML=`<div class="pmm28-table-wrap"><table><thead><tr><th>组件</th><th>执行状态</th><th>实际路径</th></tr></thead><tbody>${Object.entries(components).map(([k,v])=>`<tr><td>${esc(labels[k]||k)}</td><td>${v.executed?'已执行':'未执行'} · ${esc(v.status)}</td><td>${esc(v.provenance?.execution||v.payload?.arbitration||Object.values(v.model_versions||{}).join(' / '))}</td></tr>`).join('')}</tbody></table></div><p>正式行动：${esc(actionNames[t.official_decision?.action]||t.official_decision?.action||'未记录')} · ${components.decision?.payload?.formal_contribution?'新版条件已计入政策评分':'新版网络未增加正式评分'}</p><p class="fine">仲裁：${esc(components.decision?.payload?.arbitration||t.fallback||t.status)} · 数值变化不等于心理学效度。</p>`;
}
function renderPmm28Validation(){
 const v=pmm28Status?.models?.versions.find(v=>v.sha256===$('pmm28ModelVersion').value),r=v?.report;
 $('pmm28Validation').innerHTML=r?`<p>${r.engineering_only?'工程训练通路验证，不能发布':'独立标签验证'} · ${r.subject_held_out?'按主体与时间隔离':'个人 Adapter：同主体未来窗口'} · ${r.epochs} 步</p><table><thead><tr><th>分组</th><th>训练前损失</th><th>训练后损失</th><th>独立主体</th></tr></thead><tbody>${['train','validation','test'].map(k=>`<tr><td>${esc(k)}</td><td>${fmt(r.before[k].loss)}</td><td>${fmt(r.after[k].loss)}</td><td>${r.after[k].subjects}</td></tr>`).join('')}</tbody></table>`:'<p class="fine">尚无候选训练报告。</p>';
}
async function pmm28ReadFile(id){const file=$(id).files?.[0];if(!file)throw new Error('请先选择对应 JSON 文件。');if(file.size>10*1024*1024)throw new Error('单个标注文件请控制在 10 MB 内。');return JSON.parse(await file.text());}
$('pmm28Refresh').onclick=guard(refreshPmm28);$('pmm28Turn').onchange=renderPmm28Turn;$('pmm28ModelVersion').onchange=renderPmm28Validation;
$('pmm28ExportTrace').onclick=guard(async()=>{const t=pmm28Traces.find(t=>t.turn_id===$('pmm28Turn').value)||pmm28Traces[0];if(!t)throw new Error('暂无完整回合 Trace。');const url=URL.createObjectURL(new Blob([JSON.stringify(t,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='PMM28_Trace_'+t.turn_id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
$('pmm28Ablate').onclick=guard(async()=>{const turn=$('pmm28Turn').value||pmm28Traces[0]?.turn_id;if(!turn)throw new Error('请选择已提交回合。');const r=await api('/api/pmm28/ablation',{subject_id:state.identity.id,turn_id:turn});$('pmm28AblationResult').innerHTML=`<p class="callout">固定当前权重和输入，读取原回合条件。未重新调用 API，未写回人格；这不是现实心理因果实验。</p><table><thead><tr><th>移除组件</th><th>行动概率最大变化</th><th>结果</th></tr></thead><tbody>${r.cases.map(c=>`<tr><td>${esc(c.component)}</td><td>${c.max_abs_delta==null?'—':c.max_abs_delta.toFixed(6)}</td><td>${c.component==='neural'?'停用神经贡献':c.no_observable_difference?'未观察到差异':'预测出现数值差异'}</td></tr>`).join('')}</tbody></table>`;});
$('pmm28ImportSamples').onclick=guard(async()=>{if(!pmm28Status)await refreshPmm28();const data=await pmm28ReadFile('pmm28DatasetFile');const rows=Array.isArray(data)?data:data.samples;if(!Array.isArray(rows))throw new Error('需要 samples 标签列表。');const r=await api('/api/pmm28/samples',{subject_id:state.identity.id,expected_revision:pmm28Status.samples.revision,samples:rows.map(x=>({...x,owner_id:state.identity.id}))});await refreshPmm28();$('pmm28DataStatus').textContent=`新增 ${r.report.added||0} 条独立标签 · 重复 ${r.report.duplicate_keys?.length||0} 条 · 版本 ${r.revision}`;});
$('pmm28TrainForm').onsubmit=guard(async e=>{e.preventDefault();if(!pmm28Status)await refreshPmm28();const plan=await pmm28ReadFile('pmm28PlanFile');const job=await api('/api/pmm28/models',{op:'train',subject_id:state.identity.id,expected_revision:pmm28Status.models.revision,job_id:globalThis.crypto?.randomUUID?.()||'train-'+Date.now(),split_plan:plan.split_plan||plan,target:$('pmm28TrainTarget').value,epochs:Number($('pmm28Epochs').value),version:$('pmm28ModelVersion').value||null});const r=await runJob(job,'pmm28_train');await refreshPmm28();$('pmm28ModelResult').textContent='候选训练完成：'+r.candidate+'；已发布权重未被覆盖。';});
for(const [id,op] of [['pmm28Freeze','freeze'],['pmm28Publish','publish'],['pmm28Revoke','revoke'],['pmm28Rollback','rollback']])$(id).onclick=guard(async()=>{if(!pmm28Status)await refreshPmm28();const version=$('pmm28ModelVersion').value;if(!version)throw new Error('请选择模型版本。');await api('/api/pmm28/models',{op,subject_id:state.identity.id,expected_revision:pmm28Status.models.revision,version});await refreshPmm28();$('pmm28ModelResult').textContent='版本操作已记录：'+op;});
$('pmm28LongRun').onclick=guard(async()=>{if(!pmm28Longitudinal)await refreshPmm28();const body=await pmm28ReadFile('pmm28LongFile');if(!['calibrate_scale','train_transition','estimate'].includes(body.op))throw new Error('此入口只接收测量标定、纵向训练或候选估计。');const r=await api('/api/pmm28/longitudinal',{...body,subject_id:state.identity.id,expected_revision:pmm28Longitudinal.revision});await refreshPmm28();$('pmm28LongResult').textContent=r.proposal?'已生成候选，尚未写入正式人格。':r.model?.validated?'模型已通过独立数据工程门禁。':'工程计算完成；缺少合格真实数据时不会启用正式更新。';});
$('pmm28CommitProposal').onclick=guard(async()=>{if(!pmm28Longitudinal)await refreshPmm28();const proposal_id=$('pmm28Proposal').value;if(!proposal_id)throw new Error('请选择候选提案。');const r=await api('/api/pmm28/longitudinal',{op:'commit',subject_id:state.identity.id,expected_revision:pmm28Longitudinal.revision,proposal_id});await refresh();await refreshPmm28();$('pmm28LongResult').textContent=r.duplicate?'此提案已经提交，本次未重复学习。':'已提交到现有人格先验，下一轮读取新版本。';});

function renderPmm28Sources(){const p=pmm28Longitudinal?.proposals?.[$('pmm28Proposal').value];const refs=[...new Set((p?.source_rows||[]).flatMap(r=>r.evidence_refs))];$('pmm28LongSource').innerHTML=refs.map(k=>`<option value="${esc(k)}">${esc(k)}</option>`).join('')||'<option value="">暂无可选来源</option>';}
$('pmm28Proposal').onchange=renderPmm28Sources;
$('pmm28WithdrawSample').onclick=guard(async()=>{const key=$('pmm28Sample').value,reason=$('pmm28WithdrawReason').value.trim();if(!key||!reason)throw new Error('请选择标签并填写撤回理由。');await api('/api/pmm28/samples',{op:'withdraw',subject_id:state.identity.id,expected_revision:pmm28Status.samples.revision,key,reason});await refreshPmm28();$('pmm28DataStatus').textContent='事件标签已撤回，后续训练和发布将重新核验来源。';});
$('pmm28LongWithdraw').onclick=guard(async()=>{const source_key=$('pmm28LongSource').value,reason=$('pmm28LongWithdrawReason').value.trim();if(!source_key||!reason)throw new Error('请选择来源并填写撤回理由。');await api('/api/pmm28/longitudinal',{op:'withdraw_evidence',subject_id:state.identity.id,expected_revision:pmm28Longitudinal.revision,source_key,reason});await refresh();await refreshPmm28();$('pmm28LongResult').textContent='来源已撤回；相关人格估计已停用，历史与权重保留以供审计。';});

$('pmm28BindScale').onclick=guard(async()=>{if(!pmm28Status)await refreshPmm28();const protocol_id=$('pmm28ScaleProtocol').value;if(!protocol_id)throw new Error('请先完成独立测量标定。');const r=await api('/api/pmm28/models',{op:'bind_scale',subject_id:state.identity.id,expected_revision:pmm28Status.models.revision,version:$('pmm28ModelVersion').value||null,protocol_id});await refreshPmm28();$('pmm28ModelVersion').value=r.candidate;$('pmm28ModelResult').textContent='尺度已绑定至新候选，仍需独立状态/行为训练与发布验证。';});

// 2.8.1: actual A/B endpoints and isolated full-turn execution.
let workspace281=null,selectedTrace281=null,previewTrace281=null;
const connMap281={Protocol:'provider',Url:'base_url',Model:'model',Thinking:'thinking_mode',Adapter:'thinking_adapter',Tokens:'max_output_tokens',Timeout:'timeout',Auth:'auth_mode',TokenField:'token_field'};
function mode281(){const full=$('pmmApplication281').value==='full';$('fullPMM281').hidden=!full;$('pmmRun281').hidden=!full;document.querySelectorAll('[data-compat]').forEach(el=>el.hidden=full);$('BService281').hidden=$('BShare281').checked;$('BProtocol281').disabled=$('BShare281').checked;$('BAuth281').disabled=$('BShare281').checked;}
function fill281(){if(!state?.config)return;const c=state.config,v=c.pmm281;$('pmmApplication281').value=v.mode;$('BShare281').checked=v.b_share_a;$('bPolicy281').value=v.b_policy;$('bRounds281').value=c.deliberation.max_rounds;
 for(const r of ['A','B']){const a=r==='A'?c.pmm.api:v.b_api;for(const [id,k]of Object.entries(connMap281))$(r+id+'281').value=a[k];$(r+'Type281').value=a.provider==='ollama'?'local':'cloud';$(r+'JSON281').checked=a.json_mode;$(r+'Key281').value='';$(r+'Key281').placeholder=a.has_api_key?'密钥已保存；留空保留':'本地通常留空；云服务填写密钥';$(r+'Clear281').checked=false;$(r+'Extra281').value=JSON.stringify(a.extra_body||{},null,2);$(r+'Headers281').value='';}
 mode281();}
function connectionPatch281(r){const o={};for(const [id,k]of Object.entries(connMap281))o[k]=['Tokens','Timeout'].includes(id)?Number($(r+id+'281').value):$(r+id+'281').value.trim();o.api_key=$(r+'Clear281').checked?'':$(r+'Key281').value||null;o.json_mode=$(r+'JSON281').checked;o.extra_body=JSON.parse($(r+'Extra281').value||'{}');o.extra_headers=$(r+'Headers281').value.trim()?JSON.parse($(r+'Headers281').value):null;return o;}
async function save281(){const patch={pmm281:{mode:$('pmmApplication281').value,b_policy:$('bPolicy281').value,b_share_a:$('BShare281').checked,b_api:connectionPatch281('B')},pmm:{api:connectionPatch281('A')},deliberation:{max_rounds:Number($('bRounds281').value)}};const form=$('pmm281Form');form.inert=true;$('pmmSave281').textContent='正在保存…';try{state.config=await api('/api/config',patch);takeDraft('pmm281Form');fill281();$('pmmSave281').textContent='已保存：'+(state.config.pmm281.mode==='full'?'完整 PMM':'备用兼容模式');}finally{form.inert=false;}}
$('pmmApplication281').onchange=mode281;$('BShare281').onchange=mode281;
for(const r of ['A','B']){$(r+'Type281').onchange=()=>{const local=$(r+'Type281').value==='local';$(r+'Protocol281').value=local?'ollama':'chat_completions';if(local)$(r+'Url281').value='http://127.0.0.1:11434';};$(r+'Protocol281').onchange=()=>{$(r+'Type281').value=$(r+'Protocol281').value==='ollama'?'local':'cloud';};}
$('pmm281Form').onsubmit=guard(async e=>{e.preventDefault();await save281();await refresh281();});
$('longMode281').onsubmit=guard(async e=>{e.preventDefault();await api('/api/config',{pmm28:{long_term_mode:$('pmm28LongMode').value}});await refresh();notice('长期人格更新策略已保存。');});
for(const btn of document.querySelectorAll('[data-probe]'))btn.onclick=guard(async()=>{const [role,operation]=btn.dataset.probe.split(':');await save281();$(role+'Result281').textContent='正在实际请求模型…';const r=await api('/api/pmm281/connection',{role,operation});await refresh281();if(r.ok&&operation==='models')$(role+'Models281').innerHTML=(r.output.models||[]).map(m=>`<option value="${esc(m)}"></option>`).join('');$(role+'Result281').textContent=r.ok?`${operation==='models'?'已读取 '+r.output.models.length+' 个模型':operation==='invoke'?'任务调用通过':'连接测试通过'} · ${r.model} · ${r.elapsed_ms} ms`:r.failure_reason+' · '+r.error.type;});
const connStatus281={unconfigured:'未配置',saved_not_tested:'已保存 · 尚未测试',tested:'最近测试通过',failed:'最近测试失败',last_call_succeeded:'最近回合执行成功',last_call_failed:'最近回合执行失败'};
async function refresh281(){const owner=state?.identity?.id;if(!owner)return;const s=await api('/api/pmm281/status');if(owner!==state?.identity?.id)return;workspace281=s;
 for(const r of ['A','B']){const c=s.connections[r],last=c.latest;$(r+'Result281').textContent=`${connStatus281[c.status]}${c.model?' · '+c.model:''}${last?' · '+Number(last.elapsed_ms||0).toFixed(1)+' ms · '+date(last.at):''}`;}
 const selected=$('pmmTurn281').value;$('pmmTurn281').innerHTML=s.traces.map(t=>`<option value="${esc(t.turn_id)}">${date(t.timestamp)} · ${esc(actionNames[t.official_decision?.action]||'未完成')}</option>`).join('')||'<option value="">尚无正式回合</option>';if(s.traces.some(t=>t.turn_id===selected))$('pmmTurn281').value=selected;
 selectedTrace281=s.traces.find(t=>t.turn_id===$('pmmTurn281').value)||null;renderRun281(previewTrace281||selectedTrace281);renderEmotion281();renderAffectTraining281();
 if(page==='connections')await refreshRuntime282();
}
$('refresh281').onclick=guard(refresh281);$('pmmTurn281').onchange=()=>{previewTrace281=null;selectedTrace281=workspace281.traces.find(t=>t.turn_id===$('pmmTurn281').value);renderRun281(selectedTrace281);renderEmotion281();};
const nodeNames281={reasoner:'事件理解 A',affect:'新情绪动力学',neural:'人格神经计算',memory:'记忆与证据',relationship:'关系认知',negotiation:'内部协商 B',decision:'统一决策',expression:'外部语言表达'};
const appliedNames281={A:'事件理解',B:'内部协商',neural:'人格网络',labels:'情绪标签',expression:'表达',policy:'行动选择',decision:'决策评分',appraisal:'心理评价',candidate_diagnostics:'候选计算',candidate_reply:'最终回复'};
function renderRun281(t){$('pmmRunSummary281').textContent=t?`${previewTrace281?'隔离测试':'正式回合'} · ${date(t.timestamp)} · ${t.elapsed_ms} ms（协调器） · ${t.formal_state_writes?'已提交情绪快照':'未提交正式状态'}${previewTrace281?'，写入仅发生在副本':''}`:'完成一次对话，或运行下方整轮测试。';
 const co=t?.components||{};const order=['reasoner','affect','neural','memory','relationship','negotiation','decision','expression'];
 $('workflow281').innerHTML=order.map(k=>{const n=co[k],expr=false;const status=n?n.executed?(n.status==='failed'?'运行失败':'本轮执行'):'本轮跳过':expr?'本轮执行':'尚无执行记录';const calibrated=k==='neural'&&n? n.payload?.formal_eligible?'已发布并通过核验':'未校准':k==='affect'&&n?n.payload?.dynamics_v2?.calibration_status:null;return `<article class="workflow-node281 ${n?.status==='failed'?'failed':''}"><span class="eyebrow">${esc(status)}</span><h3>${nodeNames281[k]}</h3><p>${n?esc((n.applied_to||[]).map(x=>appliedNames281[x]||x).join('、')||(n.reason==='on_demand_no_conflict_or_risk'?'按需策略：没有触发冲突或风险':(n.failure_reason||n.payload?.error?.failure_reason||'未采用'))):expr?'最终语言输出':'等待实际调用'}</p>${n?`<small>${Number(n.elapsed_ms||0).toFixed(1)} ms${calibrated?' · '+esc(statusLabel281(calibrated)):''}</small>`:''}</article>`;}).join('');
 if(!t){$('componentDetail281').innerHTML='';return;}
 const rows=Object.entries(co).map(([k,n])=>{const p=n.payload||{},ids=n.evidence_refs||[],model=n.connection?.model||Object.values(n.model_versions||{}).join(' / ');let input=k==='neural'?`快慢情绪条件 ${p.inputs?.affect_context?.length||0} 项 · 人格 ${Object.values(p.blocks||{}).reduce((s,b)=>s+(b.mask||[]).filter(Boolean).length,0)} 项已知`:k==='affect'?`真实时间 ${p.dynamics_v2?.delta_seconds?.toFixed(3)||0} 秒 · 版本 ${p.dynamics_v2?.state_revision||0}`:k==='memory'?`可用记录 ${p.records?.length||0} 条`:k==='negotiation'?`候选视角 ${n.input_summary?.perspectives||0} · ${n.input_summary?.neural_received?'已读取人格网络':'未读取人格网络'}`:k==='reasoner'?`评价 ${Object.values(p.appraisal_packet?.checks||{}).filter(x=>x!==null).length} 项`:k==='relationship'?'当前对象与作用范围':'候选行动与仲裁';return `<tr><td>${esc(nodeNames281[k]||k)}</td><td>${esc(input)}</td><td>${esc(model||'本机计算')}<br><small>${esc(ids.join(', ')||'无额外证据 ID')}</small></td></tr>`;}).join('');
 $('componentDetail281').innerHTML=`<p>本轮行动：<strong>${esc(actionNames[t.official_decision?.action]||'未记录')}</strong> · ${co.decision?.payload?.formal_contribution?'人格网络已计入正式决策评分':'人格网络完成候选计算，未加入未校准概率评分'}</p><details><summary>输入摘要、模型与实际依赖</summary><div class="pmm28-table-wrap"><table><thead><tr><th>组件</th><th>输入摘要</th><th>计算引擎 / 证据</th></tr></thead><tbody>${rows}</tbody></table></div><p class="fine">${(t.dependencies||[]).map(([a,b])=>esc(nodeNames281[a]||a)+' → '+esc(nodeNames281[b]||b)).join('；')}</p></details>`;
}
$('preview281').onclick=guard(async()=>{const text=$('pmmTestEvent281').value;await save281();$('previewStatus281').textContent='正在调用 A、情绪与人格组件，并按策略调用 B…';const job=await api('/api/pmm281/preview',{subject_id:state.identity.id,text});const result=await runJob(job,'pmm281_preview');previewTrace281=result.trace.pmm28;renderRun281(previewTrace281);renderEmotion281();$('previewReply281').textContent=result.reply;$('previewStatus281').textContent=`整轮测试已完成 · 正式状态写入 ${result.production_state_writes} · 外部消息发送 ${result.external_messages_sent}`;});
$('export281').onclick=guard(async()=>{const t=previewTrace281||selectedTrace281;if(!t)throw new Error('请先执行一次 PMM 或选择正式回合。');const url=URL.createObjectURL(new Blob([JSON.stringify(t,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='PMM_281_trace.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
function statusLabel281(s){return {unvalidated:'工程参数 · 未标定',uncalibrated:'未校准',calibrated_partial:'部分标签已校准',validated_partial:'分项验证',advanced:'时间已推进',zero_interval:'零时间间隔',rollback_no_time_reversal:'时钟回拨 · 时间未倒退',long_offline_exact:'长间隔离线恢复'}[s]||s;}
function meter281(label,value,signed=false){if(!Number.isFinite(value))return `<p>${esc(label)} · 未知</p>`;return `<div class="metric281"><div><span>${esc(label)}</span><strong>${value.toFixed(4)}</strong></div><progress aria-label="${esc(label)}" value="${signed?(value+1)/2:value}" max="1"></progress></div>`;}
function curve281(history){if(!history.length)return '<p class="fine">尚无已提交状态记录。</p>';const xs=history.map(h=>Date.parse(h.at)),min=Math.min(...xs),max=Math.max(...xs),x=i=>36+560*(max>min?(xs[i]-min)/(max-min):.5),y=v=>18+(1-v)*60;const line=key=>history.map((h,i)=>`${x(i)},${y(h[key].valence)}`).join(' ');return `<figure class="curve281"><svg viewBox="0 0 640 172" role="img" aria-label="已保存的情绪和心境效价时间曲线"><path d="M36 78H596" stroke="#cfd9d1" stroke-dasharray="4 4"/><polyline points="${line('affect_observed')}" fill="none" stroke="#286852" stroke-width="2.5"/><polyline points="${line('mood_observed')}" fill="none" stroke="#ba7844" stroke-width="2.5"/>${history.map((h,i)=>`<circle cx="${x(i)}" cy="${y(h.affect_observed.valence)}" r="3" fill="#286852"/>`).join('')}<text x="36" y="164" font-size="11" fill="#526259">${esc(date(min/1000))}</text><text x="596" y="164" text-anchor="end" font-size="11" fill="#526259">${esc(date(max/1000))}</text></svg><figcaption>快情绪效价（绿） / 慢心境效价（棕） · ${history.length} 条真实保存的计算记录</figcaption></figure>`;}
function renderEmotion281(){const stream=workspace281?.affect.streams.find(s=>s.session_id===sessionId)||workspace281?.affect.streams.slice().sort((a,b)=>b.last_at-a.last_at)[0];const history=stream?.history||[],em=(previewTrace281||selectedTrace281)?.components?.affect?.payload?.dynamics_v2||history.at(-1);
 let html='<article class="card"><h3>情绪动力学与慢心境</h3>';if(!em)html+='<p>尚无新情绪回合。首次运行后显示真实状态、冲击来源与模型版本。</p>';
 else{const names={valence:'效价',arousal:'唤醒',dominance:'主导感',stress:'压力',engagement:'投入'};html+=`<p class="fine">${em.delta_seconds.toFixed(3)} 秒 · 第 ${em.turn_index} 轮 · 状态修订 ${em.state_revision} · ${esc(statusLabel281(em.clock_status))}</p><div class="two-col"><section><h4>快情绪</h4>${Object.entries(em.affect_observed).map(([k,v])=>meter281(names[k]||k,v,k==='valence')).join('')}</section><section><h4>慢心境</h4>${Object.entries(em.mood_observed).map(([k,v])=>meter281(names[k]||k,v,k==='valence')).join('')}<p>调节策略：${esc({none:'未调节',suppression:'表达抑制',reappraisal:'认知重评'}[em.regulation.strategy]||em.regulation.strategy)}</p><p class="fine">标签状态：${esc(statusLabel281(em.label_status))} · ${Object.values(em.emotion_labels).filter(x=>x!==null).length} / 24 已校准</p></section></div>${previewTrace281?'<p class="fine">当前为隔离测试快照；下方曲线来自正式回合。</p>':''}${curve281(history)}<details><summary>参数与变化来源</summary><p>模型 ${esc(em.affect_model_version.slice(0,16))} · ${esc(statusLabel281(em.calibration_status))}</p><div class="pmm28-table-wrap"><table><thead><tr><th>轴</th><th>自然推进</th><th>事件冲击</th><th>重评冲击差</th></tr></thead><tbody>${Object.keys(em.affect_observed).map((k,i)=>`<tr><td>${esc(names[k])}</td><td>${(em.pre_jump_fast[i]-em.before_fast[i]).toFixed(6)}</td><td>${em.jump[i].toFixed(6)}</td><td>${em.reappraisal_jump_difference[i].toFixed(6)}</td></tr>`).join('')}</tbody></table></div><p class="fine">变化量在无界潜变量空间；自然推进包含回归与已保存随机扰动。工程初始参数与已发布版本分别标记。</p><pre>${esc(JSON.stringify({parameters:em.parameters,propagation:em.propagation,regulation:em.regulation},null,2))}</pre></details>`;}
 html+='</article>';$('emotionDynamics281').innerHTML=html;$('affectDynamicsPage281').innerHTML=state?.config?.pmm281.mode==='full'?html:'';
}
function renderAffectTraining281(){const a=workspace281?.emotion_training;if(!a)return;const ver=$('affectVersion281').value,ds=$('affectDatasetChoice281').value;$('affectTrainSummary').textContent=`${a.datasets.length} 个数据集 · ${a.versions.length} 个版本 · ${a.active?'已发布 '+a.active.slice(0,12):'当前使用未标定工程初始参数'} · NumPy 前向 / PyTorch 梯度训练`;$('affectDatasetChoice281').innerHTML=a.datasets.map(d=>`<option value="${esc(d.id)}">${d.id.slice(0,12)} · ${d.rows} 条 · ${d.withdrawn?'已撤回':d.engineering_only?'工程数据':'独立测量'}</option>`).join('')||'<option value="">请先导入监督数据</option>';if(a.datasets.some(d=>d.id===ds))$('affectDatasetChoice281').value=ds;$('affectVersion281').innerHTML=a.versions.map(v=>`<option value="${esc(v.version)}">${v.version.slice(0,12)} · ${v.steps} 步 · ${v.revoked?'已撤销':v.published?'已发布':v.frozen?'已冻结':v.calibration.status}</option>`).join('');if(a.versions.some(v=>v.version===ver))$('affectVersion281').value=ver;renderEmotionReport281();}
function renderEmotionReport281(){const v=workspace281?.emotion_training.versions.find(v=>v.version===$('affectVersion281').value);$('affectTrainingReport281').innerHTML=v?`<p>${v.steps?'候选已训练':'未训练'} · 校准：${esc(v.calibration.status)}</p>${v.report?`<details><summary>训练、留出与校准记录</summary><pre>${esc(JSON.stringify(v.report,null,2))}</pre></details>`:''}`:'';}
$('affectVersion281').onchange=renderEmotionReport281;
async function affectAction281(extra){if(!workspace281)await refresh281();const a=workspace281.emotion_training;let out=await api('/api/pmm281/emotion/models',{subject_id:state.identity.id,expected_revision:a.revision,version:$('affectVersion281').value,...extra});if(out.job_id)out=await runJob(out,'affect_train');await refresh281();if(out.created&&out.versions?.some(v=>v.version===out.created)){$('affectVersion281').value=out.created;renderEmotionReport281();}$('affectTrainResult281').textContent='操作已完成 · 修订 '+out.revision;return out;}
$('affectImport281').onsubmit=guard(async e=>{e.preventDefault();const dataset=await pmm28ReadFile('affectDataset281');await affectAction281({op:'import',dataset});});
$('affectTrain281').onsubmit=guard(async e=>{e.preventDefault();await affectAction281({op:'train',dataset_id:$('affectDatasetChoice281').value,component:$('affectTarget281').value,epochs:Number($('affectEpochs281').value),lr:Number($('affectLR281').value)});});
for(const b of document.querySelectorAll('[data-affect-op]'))b.onclick=guard(async()=>{await affectAction281({op:b.dataset.affectOp,dataset_id:$('affectDatasetChoice281').value});});
refresh().then(async()=>{if(!state)return;restoreRoute();if(state.pmm_start_error)notice(state.pmm_start_error,true);const pending=state.active_jobs?.[0];if(pending)await runJob({job_id:pending.id},pending.kind);}).catch(e=>notice(e.message,true));

// BEGIN UI282: pure formatters also exercised by the structural UI tests.
let runtime282={owner:null,runs:[],calls:[],selected:null,detail:null,filteredRuns:[],filteredCalls:[],dateQuery:'',nextOffset:null,hasMore:false,total:null},personaViews282={owner:null,current_id:null,versions:[],selected:null},runtimeRequestSerial282=0;
let tokenPrices282={owner:null,price_revision:null,entries:[]};
const roleNames282={General:'General · 理解与表达','PMM-A':'A · 事件评价','PMM-B':'B · 综合立场协商'};
const phaseNames282={prospective_appraisal:'事前认知评估',cognitive_json_repair:'认知 JSON 格式修复',understanding:'理解原始消息',event_appraisal:'A 事件评价',psychological_preparation:'A 心理准备',internal_discussion:'B 内部讨论',internal_review:'B 方案复核',reply_generation:'生成回复',candidate_inspection:'异常复核',candidate_repair:'局部修复',feedback:'已确认回合反馈',background_consolidation:'后台证据整理'};
const dispositions282={SEND:'通过',SEND_WITH_NOTE:'通过，偏差已记录',REPAIR_CANDIDATE:'修复已证实问题',HOLD_HARD_CONSTRAINT:'硬约束待核实，未发送',CHECKER_UNAVAILABLE:'检查器不可用，待处理'};
function known282(v){return typeof v==='number'&&Number.isFinite(v)&&v>=0;}
function n282(v){return known282(v)?v.toLocaleString('zh-CN'):'未知';}
function status282(v){return executionStatusNames[v]||({requesting:'请求中',completed:'已完成',failed:'失败',disabled:'未调用',ok:'已执行'}[v])||v||'未记录';}
function stamp282(v){if(v==null)return '时间未记录';const t=typeof v==='number'?v:Date.parse(v)/1000;return Number.isFinite(t)?date(t):'时间未记录';}
function list282(v){return Array.isArray(v)?v.filter(x=>x!=null).map(String):v==null?[]:[String(v)];}
function refs282(v){const values=Array.isArray(v)?v:v==null?[]:[v];return values.length?values.map(x=>`<span class="tag record-id">${esc(typeof x==='object'?[x.id||x.ref,x.kind,x.scope].filter(Boolean).join(' · '):x)}</span>`).join(' '):'<span class="fine">未记录引用</span>';}
function aggregate282(calls){
 const fields=['prompt_tokens','completion_tokens','total_tokens','cache_hit_tokens','cache_miss_tokens','reasoning_tokens'];
 const out={calls:calls.length,retries:calls.filter(c=>Number(c.request_attempt||0)>0).length,unknown_counts:{},known_subtotals:{}};
 for(const f of fields){const known=calls.filter(c=>known282(c[f]));out.unknown_counts[f]=calls.length-known.length;out.known_subtotals[f]=known.reduce((a,c)=>a+c[f],0);out[f]=calls.length&&known.length===calls.length?out.known_subtotals[f]:null;}
 out.duration_ms=calls.length&&calls.every(c=>known282(c.duration_ms))?calls.reduce((a,c)=>a+c.duration_ms,0):null;
 out.cost_by_currency={};out.unpriced_calls=0;for(const c of calls){if(known282(c.cost)&&c.currency){out.cost_by_currency[c.currency]=(out.cost_by_currency[c.currency]||0)+c.cost;}else out.unpriced_calls++;}
 return out;
}
function costText282(summary,calls=[]){const s=summary?.cost_by_currency?summary:aggregate282(calls),parts=Object.entries(s.cost_by_currency).map(([currency,amount])=>esc(currency)+' '+amount.toLocaleString('zh-CN',{maximumSignificantDigits:8}));return parts.length?parts.join(' / ')+(s.unpriced_calls?' · '+s.unpriced_calls+' 次未知':''):'未配置费用或用量不足';}
function tokenCards282(summary,calls=[]){
 const s=summary||aggregate282(calls),retry=Number.isFinite(s.retries)?s.retries:calls.filter(c=>Number(c.request_attempt||0)>0).length;
 const labels=[['total_tokens','实际总 Token'],['prompt_tokens','输入 Token'],['completion_tokens','输出 Token'],['cache_hit_tokens','输入中的缓存命中']];
 return `<div class="token-cards282">${labels.map(([k,label])=>`<div><span>${label}</span><strong>${n282(s[k])}</strong>${s.unknown_counts?.[k]?`<small>${n282(s.unknown_counts[k])} 次调用缺少该项；已知小计 ${n282(s.known_subtotals?.[k])}</small>`:''}</div>`).join('')}<div><span>实际请求 / 重试</span><strong>${n282(s.calls)} / ${n282(retry)}</strong><small>缓存与 reasoning 不重复加总</small></div><div><span>按当前价目折算</span><strong>${costText282(s,calls)}</strong><small>币种分别计算；未知用量保持未知</small></div></div>`;
}
function callsForTurn282(id,calls=runtime282.calls){return calls.filter(c=>c.turn_id===id||(Array.isArray(c.turn_ids)&&c.turn_ids.includes(id)));}
function resetRuntime282(){
 runtimeRequestSerial282++;runtime282={owner:null,runs:[],calls:[],selected:null,detail:null,filteredRuns:[],filteredCalls:[],dateQuery:'',nextOffset:null,hasMore:false,total:null};personaViews282={owner:null,current_id:null,versions:[],selected:null};
 $('runtimeRuns282').innerHTML='';$('runtimeOverview282').innerHTML='';$('runtimeTrend282').innerHTML='';$('runtimeDetail282').innerHTML='<p class="empty">选择当前角色的回合查看。</p>';
 $('runtimePageStatus282').textContent='';$('runtimeMore282').hidden=true;$('runtimeStatus282').textContent='打开 PMM 设置后读取当前角色的真实回合记录。';
 $('personaVersionsList282').innerHTML='';$('personaVersionDetail282').innerHTML='';$('personaViewsStatus282').textContent='打开人物设定后读取当前角色的版本记录。';
 $('personaVersionsDelete282').disabled=true;
 tokenPrices282={owner:null,price_revision:null,entries:[]};$('tokenPriceRows282').innerHTML='';$('tokenPricesStatus282').textContent='读取价目后可编辑；留空的用量或单价保持未知。';
}
function dateQuery282(){const values=[];if($('runtimeFrom282').value)values.push('date_from='+encodeURIComponent($('runtimeFrom282').value));if($('runtimeTo282').value)values.push('date_to='+encodeURIComponent($('runtimeTo282').value));return values.join('&');}
async function refreshRuntime282(append=false){
 const owner=state?.identity?.id;if(!owner)return;const serial=++runtimeRequestSerial282,query=dateQuery282(),offset=append?runtime282.nextOffset:0;
 if(append&&(query!==runtime282.dateQuery||offset==null))return refreshRuntime282(false);
 $('runtimeStatus282').textContent='正在读取当前角色的回合与请求账本…';
 try{
  const [history,ledger]=await Promise.all([api('/api/pmm282/history?limit=200&offset='+offset+(query?'&'+query:'')),api('/api/token-ledger')]);
  if(owner!==state?.identity?.id||serial!==runtimeRequestSerial282)return;
  if(!Array.isArray(history.runs)||!Array.isArray(ledger.calls))throw new Error('运行历史或账本响应格式无效');
  const prior=append&&runtime282.owner===owner?runtime282.runs:[],byId=new Map([...prior,...history.runs].map(r=>[r.turn_id,r]));
  runtime282.owner=owner;runtime282.runs=[...byId.values()];runtime282.calls=ledger.calls;
  runtime282.dateQuery=query;runtime282.nextOffset=history.next_offset??null;runtime282.hasMore=history.has_more===true;runtime282.total=history.total??null;
  $('runtimeMore282').hidden=!runtime282.hasMore;$('runtimePageStatus282').textContent=`当前日期范围已载入 ${runtime282.runs.length} / ${known282(runtime282.total)?runtime282.total:'总量未记录'} 个回合。`;
  $('runtimeModels282').innerHTML=[...new Set(ledger.calls.map(c=>c.model).filter(Boolean))].map(m=>`<option value="${esc(m)}"></option>`).join('');
  applyRuntimeFilters282();
  if(runtime282.selected&&runtime282.filteredRuns.some(r=>r.turn_id===runtime282.selected))await openRuntimeTurn282(runtime282.selected);
 }catch(error){if(owner!==state?.identity?.id||serial!==runtimeRequestSerial282)return;$('runtimeStatus282').textContent='运行历史读取失败：'+error.message;$('runtimeDetail282').innerHTML='<p class="error">'+esc(error.message)+'</p>';}
}
function runtimeFilterValues282(){return {range:['20','100','all'].includes($('runtimeRange282').value)?$('runtimeRange282').value:'20',query:$('runtimeQuery282').value.trim().toLowerCase(),role:$('runtimeRole282').value,model:$('runtimeModel282').value.trim().toLowerCase(),phase:$('runtimePhase282').value.trim().toLowerCase(),from:$('runtimeFrom282').value,to:$('runtimeTo282').value};}
function applyRuntimeFilters282(){
 const f=runtimeFilterValues282(),start=f.from?Date.parse(f.from+'T00:00:00')/1000:-Infinity,end=f.to?Date.parse(f.to+'T23:59:59.999')/1000:Infinity;
 let calls=runtime282.calls.filter(c=>(!f.role||c.component_role===f.role)&&(!f.model||String(c.model||'').toLowerCase().includes(f.model))&&(!f.phase||[c.task_name,c.phase_id,phaseNames282[c.task_name]].join(' ').toLowerCase().includes(f.phase)));
 let runs=runtime282.runs.filter(r=>{const at=typeof r.started_at==='number'?r.started_at:Date.parse(r.started_at)/1000;return at>=start&&at<=end&&(!f.query||[r.turn_id,r.event_summary].join(' ').toLowerCase().includes(f.query))&&(!(f.role||f.model||f.phase)||callsForTurn282(r.turn_id,calls).length);}).sort((a,b)=>Number(b.started_at)-Number(a.started_at));
 if(f.range!=='all')runs=runs.slice(0,Number(f.range));const ids=new Set(runs.map(r=>r.turn_id));
 calls=calls.filter(c=>ids.has(c.turn_id)||(Array.isArray(c.turn_ids)&&c.turn_ids.some(id=>ids.has(id))));
 runtime282.filteredRuns=runs;runtime282.filteredCalls=calls;
 $('runtimeStatus282').textContent=`当前角色 · ${runs.length} 个回合 · ${calls.length} 次物理请求${f.role||f.model||f.phase?'（按调用筛选）':''}。共享后台请求只计一次。`;
 $('runtimeOverview282').innerHTML=tokenCards282(aggregate282(calls),calls);
 $('runtimeTrend282').innerHTML=trendHTML282(runs,calls);
 $('runtimeRuns282').innerHTML=runs.map(r=>{const s=aggregate282(callsForTurn282(r.turn_id,calls)),selected=r.turn_id===runtime282.selected;return `<button type="button" class="runtime-turn282 ${selected?'selected':''}" data-runtime-turn282="${esc(r.turn_id)}" aria-pressed="${selected}"><span>${esc(status282(r.status))} · ${esc(r.cognitive_route?.level||r.cognitive_route?.route_level||'路由未记录')}</span><strong>${esc(r.event_summary||r.turn_id)}</strong><small>${stamp282(r.started_at)} · Token ${n282(s.total_tokens)}</small></button>`;}).join('')||'<p class="empty">当前筛选下没有已保存回合。</p>';
 if(runtime282.selected&&!runs.some(r=>r.turn_id===runtime282.selected)){runtime282.selected=null;runtime282.detail=null;$('runtimeDetail282').innerHTML='<p class="empty">当前筛选未包含原回合，请重新选择。</p>';}
}
function trendHTML282(runs,calls){
 if(!runs.length)return '<p class="fine">有回合记录后显示历史趋势。</p>';
 const rows=runs.slice().reverse().map(r=>({r,s:aggregate282(callsForTurn282(r.turn_id,calls))})),known=rows.filter(v=>known282(v.s.total_tokens)),peak=known.length?Math.max(...known.map(v=>v.s.total_tokens)):null;
 const latencies=runs.map(r=>r.timing?.total_ms??(known282(r.ended_at)&&known282(r.started_at)?(r.ended_at-r.started_at)*1000:null)).filter(known282).sort((a,b)=>a-b);
 const median=latencies.length?(latencies[Math.floor((latencies.length-1)/2)]+latencies[Math.ceil((latencies.length-1)/2)])/2:null,mean=latencies.length?latencies.reduce((a,b)=>a+b,0)/latencies.length:null;
 const completed=runs.filter(r=>['COMPLETED','COMMITTED','INTERRUPTED_AFTER_ACK'].includes(r.status)).length,failed=runs.filter(r=>['FAILED','VALIDATION_FAILED','HOLD_HARD_CONSTRAINT','CHECKER_UNAVAILABLE','CANDIDATE_REPAIR_REQUIRED','DELIVERY_UNKNOWN','DELIVERY_FAILED','POSTPROCESS_FAILED'].includes(r.status)).length;
 const width=640,step=600/rows.length;const bars=rows.map((v,i)=>{const x=24+i*step;if(!known282(v.s.total_tokens))return `<text x="${x+step/2}" y="135" font-size="12" text-anchor="middle">?</text>`;const h=peak?100*v.s.total_tokens/peak:0;return `<rect x="${x}" y="${130-h}" width="${Math.max(1,step-2)}" height="${Math.max(1,h)}" class="trend-bar282"><title>${esc(v.r.turn_id)} · 实际 Token ${n282(v.s.total_tokens)}</title></rect>`;}).join('');
 return `<figure class="trend282"><svg viewBox="0 0 ${width} 156" role="img" aria-label="按回合的实际Token趋势，问号表示未知用量"><line x1="24" y1="131" x2="624" y2="131" stroke="currentColor" opacity=".3"/>${bars}<text x="24" y="152" font-size="11">较早</text><text x="624" y="152" font-size="11" text-anchor="end">较近</text></svg><figcaption>实际 Token 峰值 ${n282(peak)} · ${rows.length-known.length} 轮用量未完整记录</figcaption></figure><p class="fine">已测回合耗时：平均 ${known282(mean)?(mean/1000).toFixed(2)+' 秒':'未知'} / 中位 ${known282(median)?(median/1000).toFixed(2)+' 秒':'未知'}；失败 ${failed} / 已结束 ${completed+failed}${completed+failed?'（'+(100*failed/(completed+failed)).toFixed(1)+'%）':''}。节省率：尚无同场景实测基线。</p>`;
}
async function openRuntimeTurn282(id){
 const owner=state?.identity?.id;if(owner!==runtime282.owner)return;runtime282.selected=id;$('runtimeDetail282').innerHTML='<p>正在读取此回合的已保存记录…</p>';applyRuntimeFilters282();
 const data=await api('/api/pmm282/history?turn_id='+encodeURIComponent(id));
 if(owner!==state?.identity?.id||runtime282.selected!==id)return;
 if(!data.run)throw new Error('此回合不存在或不属于当前角色');runtime282.detail=data;
 $('runtimeDetail282').innerHTML=runtimeDetailHTML282(data);
}
function stageNode282(title,status,content){return `<details class="route-node282"><summary><strong>${esc(title)}</strong><span>${esc(status)}</span></summary>${content}</details>`;}
function componentNode282(key,component,calls){
 const names={affect:'本地情绪与慢心境',neural:'本地人格前向',reasoner:'A 事件评价',negotiation:'B 内部讨论'};const local=['affect','neural'].includes(key);
 if(!component)return stageNode282(names[key],'未记录','<p class="fine">此回合未保存该组件执行信息。</p>');
 const state=component.executed?status282(component.status):'未调用',cost=local&&component.executed?'本地运算 · 0 API Token':calls.length?`实际请求 ${calls.length} 次 · Token ${n282(aggregate282(calls).total_tokens)}`:'未记录额外API请求';
 return stageNode282(names[key],state,`<p>${cost}</p><p>${esc(component.reason||component.execution||component.input_summary?.reason||'未记录触发说明')}</p><p class="fine">耗时 ${known282(component.elapsed_ms)?component.elapsed_ms.toFixed(1)+' ms':'未知'}；配置位置：模型设置 → 心理模型 PMM。</p>`);
}
function retrievalEvidenceHTML282(r){return refs282(r.retrieved_refs)+(r.retrieved_evidence?.length?'<details><summary>查看本轮实际检索证据</summary>'+r.retrieved_evidence.map(m=>`<article><p class="record-id">${esc(m.id)} · ${esc(m.kind)} · ${esc(m.scope)}</p><blockquote>${esc(m.evidence||m.content||'无正文')}</blockquote></article>`).join('')+'</details>':'');}
function deliberationHTML282(d){
 if(!d||!Array.isArray(d.perspectives)||!Array.isArray(d.proposals))return '<p class="empty">此回合未保存新版综合方案讨论。旧版回合保留原始记录。</p>';
 const perspectives=Array.isArray(d.perspectives)?d.perspectives:[],proposals=Array.isArray(d.proposals)?d.proposals:[],support=d.support||{};
 return `<p>${esc(({local:'本地综合方案',local_only:'本地综合方案',local_plus_B:'本地方案与B深化',B_failed_local:'B未完成，采用本地方案',local_fallback:'B未完成，采用本地方案'})[d.discussion_mode]||d.discussion_mode||'未记录讨论模式')} · ${d.unresolved_disagreement?'保留未解决分歧':'未记录实质分歧'}</p><p class="fine">B 实际状态：${esc(({completed:'已完成',failed:'调用失败',not_called:'本轮未调用'})[d.b_status]||d.b_status||'未记录')}${d.b_error_type?' · '+esc(d.b_error_type):''}</p><p>${esc(d.selection_reason||'未记录选择理由')}</p><div class="perspectives282">${perspectives.map(p=>`<article><h4>${esc(p.hypothesis||p.label||p.id)}</h4><p>${esc(p.goal||'未记录本立场目标')}</p><p class="fine">支持方案：${list282(p.proposal_ids).map(esc).join('、')||'未记录'} · 激活权重 ${known282(p.weight)?p.weight.toFixed(3):'未知'}</p>${refs282(p.evidence_refs)}${p.expected_consequences?`<p>预期后果：${list282(p.expected_consequences).map(esc).join('；')}</p>`:''}${p.limitations?`<p class="fine">不确定处：${list282(p.limitations).map(esc).join('；')}</p>`:''}</article>`).join('')}</div><h4>具体应对方案</h4><p class="fine">相对支持度未经心理概率校准；硬约束先于方案比较。</p>${proposals.map(p=>{const value=typeof support[p.id]==='number'?support[p.id]:support.values?.[p.id],selected=p.id===d.selected_proposal_id;return `<article class="proposal282 ${selected?'selected':''}"><div class="row spread"><strong>${selected?'已选 · ':''}${esc(p.content_goal||p.id)}</strong><span>${known282(value)?(value*100).toFixed(1)+'%':'支持度未记录'}</span></div>${known282(value)?`<progress aria-label="${esc(p.id)} 相对支持度" max="1" value="${Math.min(1,value)}"></progress>`:''}<p>${esc(p.task_handling||'任务处理未记录')}</p><p>关系策略：${esc(p.social_strategy||'未记录')}</p><p>知识与记忆：${esc(p.knowledge_policy||'未记录')}</p><p class="fine">表达：${list282(p.expression_hints).map(esc).join('；')||'未指定'} · 硬约束：${esc(p.hard_constraint_status||'未记录')}</p>${list282(p.information_gaps).length?`<p>必要信息缺口：${list282(p.information_gaps).map(esc).join('；')}</p>`:''}</article>`;}).join('')}${Array.isArray(d.rounds)&&d.rounds.length?'<details><summary>逐轮内部讨论（'+d.rounds.length+' 轮）</summary>'+d.rounds.map((round,index)=>'<article><h5>第 '+(index+1)+' 轮</h5><pre>'+esc(JSON.stringify(round,null,2))+'</pre></article>').join('')+'</details>':''}<details><summary>证据、原始效用与立场贡献</summary><pre>${esc(JSON.stringify({shared_state_ref:d.shared_state_ref,evidence_registry:d.evidence_registry,factor_registry:d.factor_registry,utility_matrix:d.utility_matrix,contributions:d.contributions,support_method:d.support_method||d.support?.method},null,2))}</pre></details>`;
}
function callHTML282(c){
 const parts=Array.isArray(c.prompt_sections)?c.prompt_sections:[],max=Math.max(1,...parts.map(s=>known282(s.estimate_tokens)?s.estimate_tokens:0));
 return `<details class="call282"><summary><span>${esc(roleNames282[c.component_role]||c.component_role||'角色未记录')} · ${esc(phaseNames282[c.task_name]||c.task_name||c.phase_id||'阶段未记录')}</span><strong>${n282(c.total_tokens)} Token</strong></summary><p>${esc(c.model||'模型未记录')} · ${esc(c.protocol||c.provider||'协议未记录')} · ${esc(status282(c.status))}</p><p>输入 ${n282(c.prompt_tokens)} / 输出 ${n282(c.completion_tokens)} / 缓存命中 ${n282(c.cache_hit_tokens)} / reasoning ${n282(c.reasoning_tokens)}</p><p class="fine">耗时 ${known282(c.duration_ms)?c.duration_ms.toFixed(1)+' ms':'未知'} · 尝试 ${known282(c.request_attempt)?c.request_attempt+1:'未知'} · ${esc(c.retry_reason||'无重试原因')} · ${esc(c.trigger_reason||'调用原因未记录')}</p><p class="fine">按当前价目折算：${known282(c.cost)&&c.currency?esc(c.currency)+' '+c.cost.toLocaleString('zh-CN',{maximumSignificantDigits:8}):'未知'} · ${esc(c.cost_reason||c.reason||'')}${c.price_revision!=null?' · 价目修订 '+esc(c.price_revision):''}</p><p class="record-id">调用 ${esc(c.call_id)}${c.parent_call_id?' · 父调用 '+esc(c.parent_call_id):''}</p><h5>Prompt 组成（估算）</h5>${parts.map(s=>`<div class="section-bar282"><div><span>${esc(sectionName282(s.section_id))}</span><strong>${n282(s.estimate_tokens)}</strong></div>${known282(s.estimate_tokens)?`<progress max="${max}" value="${s.estimate_tokens}" aria-label="${esc(s.section_id)} 估算Token"></progress>`:''}<small>${esc(s.section_id)} · ${n282(s.chars)} 字符 / ${n282(s.bytes)} 字节 · ${esc(s.tokenizer_id||'估算器未记录')}</small></div>`).join('')||'<p class="fine">该调用没有组成估算记录。</p>'}<p class="fine">估算输入小计 ${n282(c.estimated_prompt_tokens)}；供应商实际输入 ${n282(c.prompt_tokens)}；实际减估算 ${typeof c.actual_minus_section_estimate==='number'?esc(c.actual_minus_section_estimate):'未知'}。估算与实际口径不同，差值不能全部解释为协议开销。</p>${c.budget_exceeded||c.soft_warning?'<p class="warning">超过本阶段预算目标；没有据此静默截断原文。</p>':''}</details>`;
}
function sectionName282(id){const key=String(id||'').split('.').pop();return ({instructions:'任务指令',self:'当前有效人设',profile:'必要角色资料',persona_view_revision:'同源人设版本',decision:'本轮决策',response_policy:'具体应对方案',style:'表达风格',interaction_plan:'当前交流计划',emotion:'当前情绪',relation:'当前关系',memories:'相关记忆',history:'必要历史',event_packet:'原文、事件分析与引用',base:'综合立场与方案',user:'原始消息与上下文',persona:'人设',checker:'检查契约'})[key]||id;}
function runtimeDetailHTML282(data){
 const r=data.run,calls=Array.isArray(data.calls)?data.calls:[],co=r.components||r.cognitive_snapshot?.pmm28?.components||{},route=r.cognitive_route||{},d=r.deliberation;
 const roleCalls=role=>calls.filter(c=>c.component_role===role),inspection=r.candidate_inspection||{},raw=r.raw_input??r.input??r.event_packet?.raw_message?.text;
 const nodes=[stageNode282('原文与事件分析',raw!=null?'已接收':'原文未记录',`${raw!=null?'<blockquote>'+esc(raw)+'</blockquote>':''}<p>${esc(r.event_summary||'未记录摘要')}</p><details><summary>结构化分析与来源</summary><pre>${esc(JSON.stringify(r.event_analysis||r.event_packet?.event_analysis||r.context_refs||{},null,2))}</pre></details>`),stageNode282('认知路由',route.level||route.route_level||'未记录',`<p>${list282(route.trigger_reasons||route.reason_codes).map(esc).join('；')||'触发原因未记录'}</p><pre>${esc(JSON.stringify(route,null,2))}</pre>`),stageNode282('相关记忆检索',Array.isArray(r.retrieved_refs)?r.retrieved_refs.length+' 条来源':'未记录',retrievalEvidenceHTML282(r)),componentNode282('affect',co.affect,[]),componentNode282('neural',co.neural,[]),componentNode282('reasoner',co.reasoner,roleCalls('PMM-A')),componentNode282('negotiation',co.negotiation,roleCalls('PMM-B')),stageNode282('候选生成与校验',dispositions282[inspection.disposition]||r.candidate_status||'未记录',`<p>是否已生成：${esc(r.candidate_status||'未记录')} · 处置：${esc(dispositions282[inspection.disposition]||inspection.disposition||'未记录')}</p><p>${esc(inspection.trigger_reason||'无额外异常复核原因')}</p><pre>${esc(JSON.stringify(inspection,null,2))}</pre>`),stageNode282('发送与已确认表达',status282(r.delivery_status),`<p>记忆提交：${esc(r.memory_commit_status||'未记录')}</p>${r.confirmed_reply?'<blockquote>'+esc(r.confirmed_reply)+'</blockquote>':'<p class="fine">此回合没有可展示的已确认表达；候选不等于已送达。</p>'}${r.delivery_status==='DELIVERY_UNKNOWN'?'<p class="warning">回执未知，不能盲目重发；到后台诊断的执行记录核对实际回执。</p>':''}`)];
 if(r.prospective_appraisal){
  const a=r.prospective_appraisal,recovery=a.format_recovery||{},failed=a.status==='failed';
  const label=failed?'未通过 · 保留待处理':recovery.local_normalization?'本地格式整理后通过':recovery.attempted?'一次格式修复后通过':'已通过';
  const reason={INVALID_JSON:'返回正文无法解析为 JSON',INVALID_APPRAISAL:'字段或原文证据未通过验证',ASSESSMENT_TIMEOUT:'已超过本次认知评估预算'}[a.failure_code]||a.failure_code;
  nodes.splice(1,0,stageNode282('事前认知评估',label,`<p>${esc(reason||a.decision?.reason||'认知评估已记录')}</p><p>${recovery.attempted?'已尝试一次小上下文 JSON 格式修复':'未进行格式修复'} · ${known282(a.duration_ms)?esc(a.duration_ms)+' ms':'耗时未记录'}</p><p class="fine">评估通过后仍须遵循行动决策，不自动授权回复。修复后字段或原文引用不符时继续保留待处理。</p><pre>${esc(JSON.stringify({decision:a.decision?.action,attempts:recovery.attempts||[],context_compilation:a.context_compilation,persona_view_revision:a.persona_view_revision},null,2))}</pre>`));
 }
 if(inspection.role_consistency){
  const c=inspection.role_consistency,labels={passed:'已核对本轮相关资料',not_required:'本轮未触发资料核对',required:'等待核对',unavailable:'检查未完成',unresolved:'疑点未解决',repair_required:'需要修复表达',reviewed_without_matching_facts:'已检查表达，未找到匹配资料'};
  nodes.splice(2,0,stageNode282('人设一致性覆盖',labels[c.status]||'未记录',`<p>核对 ${esc((c.entry_ids||[]).length)} 条已返回资料。送达状态不代表人设核对结果。</p>${c.limited?'<p>检索达到本轮资料预算，仅覆盖已返回部分。</p>':''}`));
 }
 if(r.prompt_compilation?.persona_selection){
  const s=r.prompt_compilation.persona_selection;
  nodes.splice(2,0,stageNode282('人设资料选取',`${s.included_count??'未知'} 条入选`, `<p>当前版本：${esc(s.source_version_id||r.persona_version_id||'未记录')}</p><p>涉及类别：${list282(s.included_categories).map(k=>esc(personaCategoryNames282[k]||k)).join('、')||'无'}</p><p>未选入 ${esc(s.omitted_count??'未知')} 条。未选入不代表删除；完整资料保留在人设版本中。</p><details><summary>选取依据</summary><pre>${esc(JSON.stringify(s,null,2))}</pre></details>`));
 }
 const ed=r.expressive_drive||co.expressive_drive?.payload;
 if(ed){
  const intent=ed.expressive_intent||ed.dominant_intent||'未记录',st=ed.status||ed.motive_status||'未记录';
  nodes.splice(Math.min(nodes.length,4),0,stageNode282('表达欲动态中介',`${intent} · ${st}`,`<p>Activation ${known282(ed.activation)?ed.activation.toFixed(3):'未知'} · Urgency ${known282(ed.urgency)?ed.urgency.toFixed(3):'未知'} · Persistence ${known282(ed.persistence)?ed.persistence.toFixed(3):'未知'}</p><p>当前未竟动机：${esc(ed.active_motive?.topic_or_goal||'无')}（未完成度 ${known282(ed.unfinished_degree)?ed.unfinished_degree.toFixed(3):'0'}）</p><details><summary>表达欲结构化诊断</summary><pre>${esc(JSON.stringify(ed,null,2))}</pre></details>`));
 }
 return `<div class="row spread"><h3>${esc(status282(r.status))}</h3><time>${stamp282(r.started_at)}</time></div><p class="record-id">${esc(r.turn_id)} · ${esc(r.trace_id||'Trace 未记录')}</p><p>本轮人设版本：${esc(r.persona_version_id||r.persona_view_version||r.persona_view_id||r.prospective_appraisal?.persona_view_revision||'未记录')}</p>${tokenCards282(data.summary||r.token_summary||aggregate282(calls),calls)}<h4>实际执行路径</h4><div class="route282">${nodes.join('')}</div><h4>同一主体的综合立场与方案</h4>${deliberationHTML282(d)}<h4>阶段用量</h4>${stageTokensHTML282(calls,co)}<h4>逐次模型请求与输入组成</h4>${calls.map(callHTML282).join('')||'<p class="fine">此回合未记录实际API用量，不能按0显示。</p>'}`;
}
function stageTokensHTML282(calls,components){
 const groups=new Map();for(const c of calls){const key=c.task_name||c.phase_id||'未记录阶段';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(c);}
 const rows=[...groups].map(([name,values])=>({name,summary:aggregate282(values)})),max=Math.max(1,...rows.map(v=>v.summary.total_tokens||0));
 return rows.map(({name,summary})=>`<div class="section-bar282"><div><span>${esc(phaseNames282[name]||name)}</span><strong>${n282(summary.total_tokens)} Token · ${summary.calls} 次请求</strong></div>${known282(summary.total_tokens)?`<progress aria-label="${esc(name)} 实际Token" max="${max}" value="${summary.total_tokens}"></progress>`:'<p class="fine">供应商用量不完整</p>'}</div>`).join('')+['affect','neural'].map(k=>`<p class="fine">${k==='affect'?'本地情绪与慢心境':'本地人格前向'}：${components[k]?.executed?'已执行 · 0 API Token':components[k]?'未执行，'+esc(components[k].reason||'原因未记录'):'执行状态未记录'}</p>`).join('');
}
function exportRows282(calls){const fields=['call_id','turn_id','trace_id','phase_id','component_role','task_name','trigger_reason','model','protocol','request_attempt','retry_reason','parent_call_id','started_at','ended_at','duration_ms','prompt_tokens','completion_tokens','total_tokens','cache_hit_tokens','cache_miss_tokens','reasoning_tokens','usage_source','status','response_disposition','cost','cost_decimal','currency','cost_status','cost_reason','price_revision'];return calls.map(c=>Object.fromEntries(fields.map(k=>[k,c[k]??null])));}
function exportRuns282(runs){return runs.map(r=>({turn_id:r.turn_id,started_at:r.started_at,status:r.status,delivery_status:r.delivery_status,candidate_status:r.candidate_status,route_level:r.cognitive_route?.level||r.cognitive_route?.route_level||null,discussion_mode:r.deliberation?.discussion_mode||null,selected_proposal_id:r.deliberation?.selected_proposal_id||null,support:Object.fromEntries(Object.entries(r.deliberation?.support||{}).filter(([,v])=>known282(v)))}));}
function csv282(rows){const fields=Object.keys(rows[0]||{call_id:null});const cell=v=>{const text=v==null?'':String(v);return '"'+(/^[=+\-@\t\r]/.test(text)?"'":'')+text.replace(/"/g,'""')+'"';};return '\ufeff'+fields.map(cell).join(',')+'\r\n'+rows.map(r=>fields.map(k=>cell(r[k])).join(',')).join('\r\n');}
function download282(filename,data,type){const url=URL.createObjectURL(new Blob([data],{type})),a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
const priceFields282=[['input','普通输入'],['output','输出'],['cache_read','缓存读取'],['cache_write','缓存写入']];
function renderTokenPrices282(){
 const text=(index,key,label,value)=>`<input data-price-row282="${index}" data-price-key282="${key}" aria-label="第 ${index+1} 条 ${label}" value="${esc(value??'')}" ${['provider','model','currency'].includes(key)?'type="text"':'type="number" min="0" step="any"'}>`;
 $('tokenPriceRows282').innerHTML=tokenPrices282.entries.map((row,index)=>`<fieldset class="price-row282"><legend>价目 ${index+1}</legend><div class="price-grid282"><label>协议标识${text(index,'provider','协议标识',row.provider)}</label><label>准确模型名${text(index,'model','准确模型名',row.model)}</label><label>币种${text(index,'currency','币种',row.currency)}</label>${priceFields282.map(([key,label])=>`<label>${label} / 百万 Token${text(index,key,label,row[key])}</label>`).join('')}<label>失败请求计费<select data-price-row282="${index}" data-price-key282="failed_request_billing" aria-label="第 ${index+1} 条失败请求计费">${[['unknown','未知'],['bill_usage','按返回用量计算'],['not_billed','服务商明确不计费']].map(([key,label])=>`<option value="${key}" ${row.failed_request_billing===key?'selected':''}>${label}</option>`).join('')}</select></label></div><button type="button" data-price-delete282="${index}">移除此价目</button></fieldset>`).join('')||'<p class="fine">尚未配置价目；请求费用显示未知。</p>';
 $('tokenPricesStatus282').textContent=tokenPrices282.owner?`当前角色价目修订 ${tokenPrices282.price_revision}。修改后点击保存。`:'请先读取价目。';
 $('tokenPricesSave282').disabled=tokenPrices282.owner!==state?.identity?.id;
}
function readTokenPriceRows282(){
 const rows=tokenPrices282.entries.map(row=>({...row}));for(const input of document.querySelectorAll('[data-price-row282]')){const key=input.dataset.priceKey282,value=input.value.trim();rows[Number(input.dataset.priceRow282)][key]=priceFields282.some(([field])=>field===key)?value||null:value||null;}return rows;
}
async function loadTokenPrices282(){
 const owner=state?.identity?.id;if(!owner)return;const data=await api('/api/token-prices');if(owner!==state?.identity?.id)return;
 if(!Array.isArray(data.entries))throw new Error('价目响应格式无效');tokenPrices282={owner,price_revision:data.price_revision,entries:data.entries};renderTokenPrices282();
}
async function saveTokenPrices282(){
 const owner=state?.identity?.id;if(owner!==tokenPrices282.owner)throw new Error('请先读取当前角色价目。');
 const data=await api('/api/token-prices',{subject_id:owner,expected_revision:tokenPrices282.price_revision,entries:readTokenPriceRows282()});if(owner!==state?.identity?.id)return;
 tokenPrices282={owner,price_revision:data.price_revision,entries:data.entries};renderTokenPrices282();await refreshRuntime282();$('tokenPricesStatus282').textContent='价目已保存，历史用量按当前价目重新折算；原始用量不变。';
}
async function loadPersonaViews282(){
 const owner=state?.identity?.id;if(!owner)return;$('personaViewsStatus282').textContent='正在读取当前角色人设版本…';const result=await api('/api/persona/views');
 if(owner!==state?.identity?.id)return;if(!Array.isArray(result.versions))throw new Error('人设版本响应格式错误');
 personaViews282={owner,current_id:result.current_id,versions:result.versions,selected:personaViews282.owner===owner?personaViews282.selected:null};renderPersonaViews282();
 if(personaViews282.selected&&personaViews282.versions.some(v=>v.id===personaViews282.selected))await openPersonaView282(personaViews282.selected);
}
function renderPersonaViews282(){
 $('personaViewsStatus282').textContent=`当前使用 ${personaViews282.current_id||'未编译'} · 共 ${personaViews282.versions.length} 个保留版本。查看历史不会改变当前版本。`;
 $('personaVersionsList282').innerHTML=personaViews282.versions.map(v=>{const current=v.is_current||v.id===personaViews282.current_id;return `<article class="persona-version282"><div class="row spread"><label><input type="checkbox" data-persona-view-select282="${esc(v.id)}" ${current?'disabled':''}> 版本 ${esc(v.version??v.id)} ${current?'<span class="tag">当前有效 · 生成与校验使用</span>':''}</label><button type="button" data-persona-view282="${esc(v.id)}">查看 JSON</button>${!current&&v.can_delete!==false?`<button type="button" data-persona-view-delete282="${esc(v.id)}">删除历史</button>`:''}</div><p class="fine">原角色修订 ${esc(v.source_profile_revision??'未知')} · ${stamp282(v.compiled_at)}</p><p class="record-id">${esc(v.source_digest||'摘要未记录')}</p></article>`;}).join('')||'<p class="empty">尚无已编译人设版本。</p>';
 $('personaVersionsDelete282').disabled=!personaViews282.versions.some(v=>!v.is_current&&v.id!==personaViews282.current_id&&v.can_delete!==false);
}
const personaCategoryNames282={identity_background:'身份与背景',personality_values:'性格与价值观',experiences:'经历',key_events:'关键事件',relationships:'关系',expression:'表达习惯',boundaries:'边界与禁忌',unclassified:'待归类'};
function personaCatalogHTML282(catalog,category='all'){
 const entries=Array.isArray(catalog?.entries)?catalog.entries:[],groups=catalog?.categories||{};
 const categoriesOf=row=>Object.keys(groups).filter(key=>Array.isArray(groups[key])&&groups[key].includes(row.id));
 const rows=category==='all'?entries:entries.filter(row=>categoriesOf(row).includes(category));
 const sourceNames={owner_setting:'作者设定',owner_reviewed:'已审核习惯',confirmed_personality_reference:'已确认人格资料'};
 const methodNames={explicit_heading_and_lexical_hints:'原文标题与文字线索',local_lexical_hints:'文字线索',source_field:'原资料字段',unclassified:'尚无法归类',existing_typed_source:'原有已确认资料'};
 return `<p class="fine">共 ${entries.length} 条来源资料。正文按条目保存，多个分类引用同一条目。按原文标题和文字线索整理，无法确定的内容保留为待归类；作者设定中的经历不代表双方真实发生过的会话。</p><label>按类别查看 <select id="personaCategory282"><option value="all" ${category==='all'?'selected':''}>全部条目</option>${Object.keys(personaCategoryNames282).map(key=>`<option value="${key}" ${category===key?'selected':''}>${personaCategoryNames282[key]}（${(groups[key]||[]).length}）</option>`).join('')}</select></label><div>${rows.map(row=>{const method=row.classification?.method||row.classification_method||row.method;return `<article class="persona-entry282"><p>${categoriesOf(row).map(key=>`<span class="tag">${esc(personaCategoryNames282[key]||key)}</span>`).join(' ')}</p><blockquote>${esc(row.text||(row.representation==='reference'?'引用已确认的人格或习惯资料，原始数值保留在来源记录中。':''))}</blockquote><p class="fine">来源：${esc(sourceNames[row.source_type]||row.source_type||'未记录')} · 分类依据：${esc(methodNames[method]||method||'见原始记录')} · 适用范围：${esc(row.scope&&row.scope!=='*'?row.scope:'角色通用资料')}</p><details><summary>原文位置与条目记录</summary><pre>${esc(JSON.stringify(row,null,2))}</pre></details></article>`;}).join('')||'<p class="fine">此类别没有资料。</p>'}</div>`;
}
function renderPersonaCategory282(catalog,category='all'){
 $('personaCatalog282').innerHTML=personaCatalogHTML282(catalog,category);
 $('personaCategory282').onchange=event=>renderPersonaCategory282(catalog,event.target.value);
}
async function openPersonaView282(id){
 const owner=state?.identity?.id;personaViews282.selected=id;const result=await api('/api/persona/views?version_id='+encodeURIComponent(id));
 if(owner!==state?.identity?.id||personaViews282.selected!==id)return;
 const current=result.is_current||result.view?.id===personaViews282.current_id;
 const view=result.view,source=view.source_payload?{version_id:view.version_id,source_revision:view.source_revision,source_digest:view.source_digest,source:view.source_payload}:view;
 const projection=v=>Object.fromEntries(Object.entries(v||{}).filter(([key])=>key!=='role_catalog'));
 const derived=view.source_payload?`<details><summary>查看生成与校验各自使用的内容</summary><p class="fine">两者由上面同一份角色资料生成；每次调用仅选用对应视图。</p><pre>${esc(JSON.stringify({generator_view:projection(view.generator_view),checker_view:projection(view.checker_view)},null,2))}</pre></details>`:'';
 const raw=`<pre class="persona-json282">${esc(JSON.stringify(source,null,2))}</pre>`;
 $('personaVersionDetail282').innerHTML=`<h4>${current?'当前有效人设':'历史人设 · 仅查看'}</h4><p class="fine">${current?'生成器和校验器读取此最新版本。':'当前使用版本不变，生成器和校验器不会读取此历史快照。'}</p>${view.role_catalog?'<div id="personaCatalog282"></div><details><summary>原始填写资料与版本来源</summary>'+raw+'</details>':raw}${derived}`;
 if(view.role_catalog)renderPersonaCategory282(view.role_catalog);
}
async function deletePersonaViews282(ids){
 const owner=state?.identity?.id;if(owner!==personaViews282.owner)throw new Error('角色已切换，请重新读取版本记录。');
 if(!ids.length)throw new Error('请先勾选要删除的历史记录。');
 if(ids.some(id=>id===personaViews282.current_id||personaViews282.versions.find(v=>v.id===id)?.is_current))throw new Error('当前有效人设不能作为历史记录删除。');
 if(ids.some(id=>!personaViews282.versions.some(v=>v.id===id&&v.can_delete!==false)))throw new Error('所选历史已变化，请刷新版本记录。');
 await api('/api/persona/views/delete',{version_ids:ids,subject_id:owner});if(owner!==state?.identity?.id)return;
 if(ids.includes(personaViews282.selected)){personaViews282.selected=null;$('personaVersionDetail282').innerHTML='<p class="fine">所查看的历史记录已删除，当前有效人设没有变化。</p>';}
 await loadPersonaViews282();notice('已删除所选人设历史记录；当前人设保持不变。');
}
// END UI282 pure formatters and API actions.
$('runtimeRefresh282').onclick=guard(()=>refreshRuntime282(false));
$('tokenPricesLoad282').onclick=guard(loadTokenPrices282);
$('tokenPricesAdd282').onclick=guard(()=>{if(tokenPrices282.owner!==state?.identity?.id)throw new Error('请先读取当前角色价目。');tokenPrices282.entries=readTokenPriceRows282();tokenPrices282.entries.push({provider:'',model:'',currency:'',input:null,output:null,cache_read:null,cache_write:null,failed_request_billing:'unknown'});renderTokenPrices282();});
$('tokenPricesForm282').onsubmit=guard(async e=>{e.preventDefault();await saveTokenPrices282();});
document.addEventListener('click',guard(e=>{const b=e.target.closest('button');if(!b||b.dataset.priceDelete282===undefined)return;tokenPrices282.entries=readTokenPriceRows282();tokenPrices282.entries.splice(Number(b.dataset.priceDelete282),1);renderTokenPrices282();}));
$('runtimeMore282').onclick=guard(async()=>{$('runtimeRange282').value='all';await refreshRuntime282(true);});
$('runtimeFilters282').onsubmit=guard(async e=>{e.preventDefault();if(dateQuery282()!==runtime282.dateQuery)await refreshRuntime282(false);else applyRuntimeFilters282();});
$('runtimeExportJSON282').onclick=guard(()=>download282('HuaiAn_Token_History.json',JSON.stringify({schema:'runtime-export/2.8.2',runs:exportRuns282(runtime282.filteredRuns),calls:exportRows282(runtime282.filteredCalls),summary:aggregate282(runtime282.filteredCalls)},null,2),'application/json'));
$('runtimeExportCSV282').onclick=guard(()=>download282('HuaiAn_Token_Calls.csv',csv282(exportRows282(runtime282.filteredCalls)),'text/csv;charset=utf-8'));
$('personaViewsRefresh282').onclick=guard(loadPersonaViews282);
$('personaVersionsDelete282').onclick=guard(()=>deletePersonaViews282([...document.querySelectorAll('[data-persona-view-select282]')].filter(n=>n.checked&&!n.disabled).map(n=>n.dataset.personaViewSelect282)));
document.addEventListener('click',guard(async e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.runtimeTurn282)await openRuntimeTurn282(b.dataset.runtimeTurn282);if(b.dataset.personaView282)await openPersonaView282(b.dataset.personaView282);if(b.dataset.personaViewDelete282)await deletePersonaViews282([b.dataset.personaViewDelete282]);if(b.dataset.tab==='profiles-settings')await loadPersonaViews282();}));


// ============================================================================
// HuaiAn Dreamer UI 3.0 Controller: Character Space & Cultivation Studio
// Dual-Port (User Character Space ⇄ Developer Research Workbench) + Dual-Theme
// ============================================================================
function ui3ById(id) {
  try { return document.getElementById(id); } catch (_) { return null; }
}
let ui3CurrentPage = 'ui3PageHome';
let ui3SelectedConstructId = 'hexaco.x.social_boldness';
let ui3SelectedGraphNodeId = null;
let ui3MemoryViewMode = 'graph';
let ui3StudioPreviewData = null;

const ui3IntentLabels = {
  LISTEN: ['倾听等待 (LISTEN)', '对方话轮尚未结束或无需打断，优先安静倾听', 'sage'],
  BACKCHANNEL: ['轻声附和 (BACKCHANNEL)', '简短自然回应，把继续讲述的空间留给对方', 'indigo'],
  TAKE_TURN: ['主动接话 (TAKE_TURN)', '表达欲与回应义务充分激活，准备完整回应', 'accent'],
  DEFER: ['暂存待机 (DEFER)', '已有明确想说的念头，但因时机或克制暂缓表达', 'amber'],
  CLOSE: ['自然收束 (CLOSE)', '当前交流已充分或对方准备结束，自然收尾不强行追问', 'sage'],
  INITIATE: ['主动发起 (INITIATE)', '基于具体未竟表达动机，在合适窗口准备主动关怀或续接话题', 'plum'],
};

const ui3SourceLabels = {
  owner_seed: ['主人初始设定', 'accent'],
  owner_rule: ['主人规则设定', 'accent'],
  promoted: ['经审核证据晋升', 'sage'],
  reviewed_owner_evidence: ['经审核证据', 'sage'],
  model_estimate: ['模型经验估计', 'indigo'],
  uncalibrated_engineering: ['未校准工程估计', 'amber'],
  uncalibrated_engineering_initial: ['工程初始先验', 'amber'],
  prior: ['工程先验', 'amber'],
  unknown: ['未知（尚无证据）', ''],
};

function ui3SourceBadge(sourceType, isNull = false) {
  if (isNull || !sourceType || sourceType === 'unknown') {
    return '<span class="ui3-badge">未知 · 尚无测量证据</span>';
  }
  const [label, cls] = ui3SourceLabels[sourceType] || [String(sourceType), 'indigo'];
  return `<span class="ui3-badge ${cls}">${esc(label)}</span>`;
}

function switchUI3Port(port) {
  if (typeof document !== 'undefined' && document.body && document.body.classList) {
    document.body.classList.toggle('ui-port-user', port !== 'developer');
    document.body.classList.toggle('ui-port-developer', port === 'developer');
  }
  if (port !== 'developer' && state) {
    renderUI3();
  }
}

function toggleUI3Theme() {
  if (typeof document === 'undefined' || !document.body) return;
  const cur = document.body.getAttribute('data-ui3-theme') || 'light';
  const next = cur === 'dark' ? 'light' : 'dark';
  document.body.setAttribute('data-ui3-theme', next);
  if ($('ui3ThemeToggle')) {
    $('ui3ThemeToggle').textContent = next === 'dark' ? '☀ 晨雾浅色' : '☾ 槐安夜境';
  }
}

function showUI3Page(pageId, subtabId) {
  ui3CurrentPage = pageId;
  document.querySelectorAll('.ui3-section').forEach(sec => {
    sec.classList.toggle('active', sec.id === pageId);
  });
  document.querySelectorAll('[data-ui3-page]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.ui3Page === pageId);
  });
  if (subtabId) {
    const targetPanel = $(subtabId);
    if (targetPanel && targetPanel.parentElement) {
      targetPanel.parentElement.querySelectorAll('.ui3-subpanel').forEach(p => {
        p.classList.toggle('active', p.id === subtabId);
      });
    }
    document.querySelectorAll('[data-ui3-inner-tab],[data-ui3-timeline-tab],[data-ui3-mem-tab],[data-ui3-set-tab]').forEach(b => {
      const val = b.dataset.ui3InnerTab || b.dataset.ui3TimelineTab || b.dataset.ui3MemTab || b.dataset.ui3SetTab;
      if (val && $(val)?.parentElement === targetPanel?.parentElement) {
        b.classList.toggle('active', val === subtabId);
      }
    });
  }
  if (state) renderUI3();
}

function renderUI3AffectCircumplexSVG(fast, slow, movement, compact = false) {
  const size = compact ? 240 : 320;
  const pad = 28;
  const plotW = size - pad * 2;
  const cx = pad + plotW / 2;
  const cy = pad + plotW * 0.75; // arousal=0.25 resting center

  const mapX = v => pad + ((Math.max(-1, Math.min(1, Number(v))) + 1) / 2) * plotW;
  const mapY = a => pad + (1 - Math.max(0, Math.min(1, Number(a)))) * plotW;

  const hasFast = fast && fast.known && typeof fast.valence === 'number' && typeof fast.arousal === 'number';
  const hasSlow = slow && slow.known && typeof slow.valence === 'number' && typeof slow.arousal === 'number';

  const fx = hasFast ? mapX(fast.valence) : cx;
  const fy = hasFast ? mapY(fast.arousal) : cy;
  const sx = hasSlow ? mapX(slow.valence) : cx;
  const sy = hasSlow ? mapY(slow.arousal) : cy;

  const dx = movement && typeof movement.dx_valence === 'number' ? movement.dx_valence : 0;
  const dy = movement && typeof movement.dy_arousal === 'number' ? movement.dy_arousal : 0;
  const prevX = hasFast ? mapX(fast.valence - dx) : fx;
  const prevY = hasFast ? mapY(fast.arousal - dy) : fy;

  return `<svg viewBox="0 0 ${size} ${size}" role="img" aria-label="二维愉悦度与唤醒度情绪空间">
    <rect x="${pad}" y="${pad}" width="${plotW}" height="${plotW}" rx="12" fill="rgba(128,120,105,0.05)" stroke="rgba(128,120,105,0.22)" />
    <line x1="${cx}" y1="${pad}" x2="${cx}" y2="${pad + plotW}" stroke="rgba(128,120,105,0.25)" stroke-dasharray="4 4" />
    <line x1="${pad}" y1="${pad + plotW / 2}" x2="${pad + plotW}" y2="${pad + plotW / 2}" stroke="rgba(128,120,105,0.25)" stroke-dasharray="4 4" />
    <text x="${pad + 8}" y="${pad + 16}" font-size="10" fill="currentColor" opacity="0.55">高唤醒 · 紧张/警觉</text>
    <text x="${pad + plotW - 8}" y="${pad + 16}" font-size="10" text-anchor="end" fill="currentColor" opacity="0.55">高唤醒 · 欣快/投入</text>
    <text x="${pad + 8}" y="${pad + plotW - 8}" font-size="10" fill="currentColor" opacity="0.55">低唤醒 · 疲惫/低落</text>
    <text x="${pad + plotW - 8}" y="${pad + plotW - 8}" font-size="10" text-anchor="end" fill="currentColor" opacity="0.55">低唤醒 · 平静/舒缓</text>
    ${hasSlow ? `<circle cx="${sx.toFixed(1)}" cy="${sy.toFixed(1)}" r="15" fill="rgba(63,88,140,0.16)" stroke="#3f588c" stroke-width="2" stroke-dasharray="3 2" />
    <text x="${sx.toFixed(1)}" y="${(sy + 26).toFixed(1)}" font-size="10" text-anchor="middle" fill="#3f588c">慢心境</text>` : ''}
    ${hasFast && (Math.abs(dx) > 0.005 || Math.abs(dy) > 0.005) ? `<line x1="${prevX.toFixed(1)}" y1="${prevY.toFixed(1)}" x2="${fx.toFixed(1)}" y2="${fy.toFixed(1)}" stroke="#b45638" stroke-width="2" />` : ''}
    ${hasFast ? `<circle cx="${fx.toFixed(1)}" cy="${fy.toFixed(1)}" r="8" fill="#b45638" stroke="#fff" stroke-width="2" />
    <text x="${fx.toFixed(1)}" y="${(fy - 12).toFixed(1)}" font-size="10" font-weight="600" text-anchor="middle" fill="#b45638">快情绪</text>` : `<text x="${cx}" y="${pad + plotW / 2}" font-size="12" text-anchor="middle" fill="currentColor" opacity="0.6">尚未积累事件情绪坐标（未知）</text>`}
  </svg>`;
}

function renderUI3HexacoRadarSVG(domains) {
  const size = 270, cx = 135, cy = 135, rMax = 92;
  const pts = [];
  const axes = domains.map((d, i) => {
    const angle = (-Math.PI / 2) + (i * 2 * Math.PI / domains.length);
    const xEnd = cx + rMax * Math.cos(angle);
    const yEnd = cy + rMax * Math.sin(angle);
    const xLbl = cx + (rMax + 24) * Math.cos(angle);
    const yLbl = cy + (rMax + 24) * Math.sin(angle);
    const val = typeof d.estimate === 'number' ? Math.max(0, Math.min(1, d.estimate)) : null;
    if (val !== null) {
      pts.push(`${(cx + rMax * val * Math.cos(angle)).toFixed(1)},${(cy + rMax * val * Math.sin(angle)).toFixed(1)}`);
    }
    return { d, angle, xEnd, yEnd, xLbl, yLbl, val };
  });
  return `<svg viewBox="0 0 ${size} ${size}" role="img" aria-label="HEXACO 六领域结构概览">
    ${[0.25, 0.5, 0.75, 1.0].map(level => `<circle cx="${cx}" cy="${cy}" r="${(rMax * level).toFixed(1)}" fill="none" stroke="rgba(128,120,105,0.18)" stroke-dasharray="${level === 0.5 ? '3 3' : 'none'}" />`).join('')}
    ${axes.map(a => `<line x1="${cx}" y1="${cy}" x2="${a.xEnd.toFixed(1)}" y2="${a.yEnd.toFixed(1)}" stroke="rgba(128,120,105,0.22)" />
      <text x="${a.xLbl.toFixed(1)}" y="${(a.yLbl + 4).toFixed(1)}" font-size="11" font-weight="600" text-anchor="middle" fill="currentColor">${esc(a.d.code)}·${esc(a.d.name_zh.split('—')[0])}</text>`).join('')}
    ${pts.length === domains.length ? `<polygon points="${pts.join(' ')}" fill="rgba(46,111,94,0.20)" stroke="#2e6f5e" stroke-width="2" />` : ''}
    ${axes.map(a => a.val !== null ? `<circle cx="${(cx + rMax * a.val * Math.cos(a.angle)).toFixed(1)}" cy="${(cy + rMax * a.val * Math.sin(a.angle)).toFixed(1)}" r="4.5" fill="#2e6f5e" stroke="#fff" stroke-width="1.5" />` : `<circle cx="${(cx + rMax * 0.5 * Math.cos(a.angle)).toFixed(1)}" cy="${(cy + rMax * 0.5 * Math.sin(a.angle)).toFixed(1)}" r="3.5" fill="none" stroke="rgba(128,120,105,0.5)" stroke-dasharray="2 2" />`).join('')}
  </svg>`;
}

function renderUI3SchwartzCircleSVG(values) {
  const size = 280, cx = 140, cy = 140, rMax = 92, rInner = 22;
  const n = values.length || 19;
  const quadColors = {
    openness_to_change: '#b45638',
    self_enhancement: '#b87b28',
    conservation: '#3f588c',
    self_transcendence: '#2e6f5e',
  };
  const wedges = values.map((v, i) => {
    const a0 = (-Math.PI / 2) + (i * 2 * Math.PI / n);
    const a1 = (-Math.PI / 2) + ((i + 0.86) * 2 * Math.PI / n);
    const amid = (a0 + a1) / 2;
    const known = typeof v.estimate === 'number';
    const r = known ? rInner + (rMax - rInner) * Math.max(0.08, Math.min(1, v.estimate)) : rInner + (rMax - rInner) * 0.35;
    const x1 = cx + r * Math.cos(a0), y1 = cy + r * Math.sin(a0);
    const x2 = cx + r * Math.cos(a1), y2 = cy + r * Math.sin(a1);
    const xi1 = cx + rInner * Math.cos(a0), yi1 = cy + rInner * Math.sin(a0);
    const xi2 = cx + rInner * Math.cos(a1), yi2 = cy + rInner * Math.sin(a1);
    const lx = cx + (rMax + 20) * Math.cos(amid), ly = cy + (rMax + 20) * Math.sin(amid);
    const col = quadColors[v.quadrant] || '#3f588c';
    const dPath = `M ${xi1.toFixed(1)} ${yi1.toFixed(1)} L ${x1.toFixed(1)} ${y1.toFixed(1)} A ${r.toFixed(1)} ${r.toFixed(1)} 0 0 1 ${x2.toFixed(1)} ${y2.toFixed(1)} L ${xi2.toFixed(1)} ${yi2.toFixed(1)} Z`;
    return `<g>
      <path d="${dPath}" fill="${known ? col : 'none'}" fill-opacity="${known ? '0.68' : '0'}" stroke="${col}" stroke-width="1.2" ${known ? '' : 'stroke-dasharray="2 2" opacity="0.45"'} />
      <text x="${lx.toFixed(1)}" y="${(ly + 3).toFixed(1)}" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.82">${esc(v.label.slice(0, 4))}</text>
    </g>`;
  }).join('');
  return `<svg viewBox="0 0 ${size} ${size}" role="img" aria-label="Schwartz 19项价值环">
    <circle cx="${cx}" cy="${cy}" r="${rMax}" fill="none" stroke="rgba(128,120,105,0.18)" />
    <circle cx="${cx}" cy="${cy}" r="${rInner}" fill="none" stroke="rgba(128,120,105,0.25)" />
    ${wedges}
  </svg>`;
}

function renderUI3Home() {
  if (!state || !state.profile) return;
  const p = state.profile;
  const ov = state.ui3_overview || {};
  const ed = state.expressive_drive || {};
  const streams = ov.expressive_drive_detail?.streams || ed.streams || [];
  const topStream = streams[0] || {
    activation: 0.45,
    urgency: 0.35,
    persistence: 0.48,
    expressive_intent: 'LISTEN',
    baseline: { activation: 0.45, urgency: 0.35, persistence: 0.48 },
  };
  const unfinished = ov.expressive_drive_detail?.unfinished_motives || [];
  const qqCfg = state.config?.qq || {};
  const modelsOk = modelsConfigured();

  if ($('ui3PersonaSelect')) {
    $('ui3PersonaSelect').innerHTML = (state.personas?.items || []).map(item =>
      `<option value="${esc(item.id)}" ${item.id === state.identity.id ? 'selected' : ''}>${esc(item.id === p.id ? p.name : item.name)}</option>`
    ).join('');
  }
  if ($('ui3ConnBadge')) {
    $('ui3ConnBadge').className = 'ui3-badge ' + (modelsOk ? 'ok' : 'warn');
    $('ui3ConnBadge').textContent = modelsOk ? `已连接 · ${state.config.model || '本地模型'}` : '待配置模型连接';
  }

  // A. Identity Hero
  const firstChar = (p.name || '槐').trim().slice(0, 1);
  const seedPreview = (p.character?.initial_personality || p.seed || '尚未填写初始角色背景设定，可在连接与设置中补充，或通过成长工作室从聊天记录蒸馏。').slice(0, 140);
  $('ui3IdentityHero').innerHTML = `
    <div class="ui3-avatar-wrap" aria-hidden="true">
      <span>${esc(firstChar)}</span>
      <i class="ui3-avatar-status-dot" title="本地服务在线"></i>
    </div>
    <div>
      <span class="ui3-kicker">ACTIVE PERSONA · 当前角色空间</span>
      <h1 style="margin:2px 0 6px;font-size:24px">${esc(p.name)} <small style="font-size:13px;font-weight:500;color:var(--ui3-text-muted)">自称「${esc(p.character?.self_reference || '我')}」</small></h1>
      <p class="ui3-sub" style="margin:0">${esc(seedPreview)}${seedPreview.length >= 140 ? '…' : ''}</p>
      <div class="ui3-hero-meta">
        <span class="ui3-badge indigo">人格修订 v${esc(p.revision)} · 长期特征 v${esc(p.trait_profile?.version ?? 0)}</span>
        <span class="ui3-badge ${qqCfg.enabled ? 'ok' : ''}">QQ 渠道：${qqCfg.enabled ? ('已启用 · 机器人 ' + esc(qqCfg.self_id || '未填号码')) : '未开启自动回复'}</span>
        <span class="ui3-badge ${modelsOk ? 'ok' : 'warn'}">对话模型：${esc(state.config?.model || '待配置')} · PMM：${esc(modeName(state.model?.mode))}</span>
        <span class="ui3-badge">累计互动 ${esc(state.state?.turn_count ?? 0)} 轮 · 记忆 ${esc(state.memory_count ?? 0)} 条</span>
      </div>
    </div>
    <div style="display:flex;flex-direction:column;gap:8px;align-items:flex-end">
      <button type="button" class="ui3-pill-btn primary" id="ui3HeroEditCharBtn">编辑角色设定</button>
      <button type="button" class="ui3-pill-btn" data-ui3-jump="ui3PageStudio">进入成长工作室 →</button>
    </div>
  `;
  const heroEditBtn = ui3ById('ui3HeroEditCharBtn');
  if (heroEditBtn) heroEditBtn.onclick = () => $('editCharacter')?.click();

  // F. Pending Actions (only shown if real items exist)
  const pendingItems = ov.pending_actions || [];
  if (pendingItems.length > 0) {
    $('ui3PendingActionsWrap').hidden = false;
    $('ui3PendingActionsList').innerHTML = pendingItems.map(item => `
      <div class="ui3-card-compact">
        <span class="ui3-badge ${item.severity === 'warning' ? 'warn' : 'indigo'}">${esc(item.kind.toUpperCase())}</span>
        <h3 style="font-size:15px;margin:8px 0 4px">${esc(item.title)}</h3>
        <p class="ui3-sub" style="font-size:12px">${esc(item.detail)}</p>
        <button type="button" class="ui3-pill-btn" style="margin-top:10px" data-ui3-jump="${esc(item.target_view)}">前往处理 →</button>
      </div>
    `).join('');
  } else {
    $('ui3PendingActionsWrap').hidden = true;
    $('ui3PendingActionsList').innerHTML = '';
  }

  // B1. Emotion Centerpiece
  const aff2d = ov.affect_2d || {};
  const fast = aff2d.fast_emotion || {};
  const slow = aff2d.slow_mood || {};
  const mov = aff2d.movement || {};
  const fastDesc = fast.known
    ? `当前快情绪效价 ${fast.valence.toFixed(2)}（${fast.valence > 0.15 ? '偏愉悦温暖' : fast.valence < -0.15 ? '偏低落紧绷' : '平和中性'}），唤醒度 ${fast.arousal.toFixed(2)}，主导感 ${(fast.dominance ?? 0.5).toFixed(2)}。`
    : '当前尚无触发快情绪的近期事件，处于平静未激活基线。';
  const slowDesc = slow.known
    ? `慢心境基调效价 ${slow.valence.toFixed(2)}，唤醒度 ${slow.arousal.toFixed(2)}。`
    : '慢心境保持中性工程先验。';

  $('ui3HomeEmotionCenter').innerHTML = `
    <div style="display:grid;grid-template-columns:minmax(180px,230px) minmax(0,1fr);gap:16px;align-items:center">
      <div class="ui3-viz-box">${renderUI3AffectCircumplexSVG(fast, slow, mov, true)}</div>
      <div>
        <div style="margin-bottom:10px">
          <span class="ui3-badge accent">快情绪 · 即时反应</span>
          <span class="ui3-badge indigo" style="margin-left:6px">慢心境 · 长期基调</span>
        </div>
        <p style="font-size:14px;line-height:1.65;margin:0 0 8px"><strong>${esc(fastDesc)}</strong></p>
        <p class="ui3-sub" style="margin:0 0 10px">${esc(slowDesc)} 最近状态变化：${esc(mov.latest_summary || '无')}</p>
        <div class="ui3-trait-row">
          <div class="ui3-trait-top"><span>压力负荷 (Stress)</span><strong>${typeof fast.stress === 'number' ? fast.stress.toFixed(3) : '未知'}</strong></div>
          <div class="ui3-bar-track"><div class="ui3-bar-fill warm" style="width:${typeof fast.stress === 'number' ? (fast.stress * 100).toFixed(1) : 0}%"></div></div>
        </div>
        <div class="ui3-trait-row" style="margin-bottom:0">
          <div class="ui3-trait-top"><span>互动投入度 (Engagement)</span><strong>${typeof fast.engagement === 'number' ? fast.engagement.toFixed(3) : '未知'}</strong></div>
          <div class="ui3-bar-track"><div class="ui3-bar-fill" style="width:${typeof fast.engagement === 'number' ? (fast.engagement * 100).toFixed(1) : 0}%"></div></div>
        </div>
      </div>
    </div>
  `;

  // B2. Expressive Drive Centerpiece
  const [intentTitle, intentDesc, intentCls] = ui3IntentLabels[topStream.expressive_intent] || [topStream.expressive_intent || 'LISTEN', '', 'sage'];
  const actVal = Number(topStream.activation ?? 0.45);
  const urgVal = Number(topStream.urgency ?? 0.35);
  const persVal = Number(topStream.persistence ?? 0.48);
  $('ui3HomeDriveCenter').innerHTML = `
    <div style="margin-bottom:12px;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">
      <span class="ui3-badge ${intentCls}" style="font-size:12px;padding:5px 12px">当前话轮意图：${esc(intentTitle)}</span>
      <span class="ui3-badge">未完成表达动机：${unfinished.length} 项</span>
    </div>
    <p class="ui3-sub" style="margin:0 0 14px">${esc(intentDesc)}</p>
    <div class="ui3-trait-row">
      <div class="ui3-trait-top"><span>想表达程度 (Activation · 内部表达能量)</span><strong>${actVal.toFixed(3)}</strong></div>
      <div class="ui3-bar-track"><div class="ui3-bar-fill warm" style="width:${(actVal * 100).toFixed(1)}%"></div></div>
    </div>
    <div class="ui3-trait-row">
      <div class="ui3-trait-top"><span>立即接话倾向 (Urgency · 话轮紧迫感)</span><strong>${urgVal.toFixed(3)}</strong></div>
      <div class="ui3-bar-track"><div class="ui3-bar-fill plum" style="width:${(urgVal * 100).toFixed(1)}%"></div></div>
    </div>
    <div class="ui3-trait-row">
      <div class="ui3-trait-top"><span>话题挂念持续度 (Persistence · 跨时间保持)</span><strong>${persVal.toFixed(3)}</strong></div>
      <div class="ui3-bar-track"><div class="ui3-bar-fill" style="width:${(persVal * 100).toFixed(1)}%"></div></div>
    </div>
    <details style="margin-top:10px;font-size:12px;color:var(--ui3-text-sec)">
      <summary style="cursor:pointer;font-weight:600">展开查看人格表达基线 b(θ) 与流修订号</summary>
      <p style="margin:6px 0 0">人格表达基线：Activation=${fmt(topStream.baseline?.activation)} · Urgency=${fmt(topStream.baseline?.urgency)} · Persistence=${fmt(topStream.baseline?.persistence)} · 状态修订 v${esc(topStream.state_revision ?? 0)}</p>
    </details>
  `;

  // D. Unfinished Expressive Motives
  $('ui3HomeUnfinishedList').innerHTML = unfinished.length ? unfinished.slice(0, 4).map(m => {
    const ie = m.intended_expression || {};
    const topic = m.content_anchor?.topic || '未命名表达议题';
    const goal = ie.intended_goal || m.content_anchor?.summary || '';
    const unsentSteps = ie.unsent_plan_steps || [];
    return `<div class="ui3-card-compact" style="margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:6px">
        <span class="ui3-badge plum">内部未完成表达动机 · 尚未发送</span>
        <span class="ui3-badge">${esc(m.status)} · 激活度 ${Number(m.activation || 0).toFixed(2)}</span>
      </div>
      <h4 style="margin:4px 0;font-size:14px">主题：${esc(topic)}</h4>
      <p class="ui3-sub" style="font-size:12.5px;margin:4px 0"><strong>主体想表达的目标：</strong>${esc(goal)}</p>
      ${unsentSteps.length ? `<p class="ui3-sub" style="font-size:12px;margin:4px 0"><strong>待续接步骤 (${unsentSteps.length})：</strong>${esc(unsentSteps.map(s => s.intended_point || s.purpose).join(' / '))}</p>` : ''}
      <p class="ui3-sub" style="font-size:11.5px;color:var(--ui3-text-muted)">关联对象：${esc(m.person_id || m.scope)} · 暂缓原因：${esc(m.defer_reason || '等待合适话轮窗口')} · 更新于 ${date(m.updated_at)}</p>
    </div>`;
  }).join('') : '<p class="ui3-sub">当前没有搁置或待续接的未完成表达动机；角色表达状态已充分结算。</p>';

  // C. Recent Experiences
  const recentMems = (memories || []).slice(0, 3);
  const recentEvs = (events || []).filter(e => ['turn', 'social_sent', 'trait_evidence_promoted', 'expression_partial'].includes(e.kind)).slice(0, 3);
  const combinedExp = [
    ...recentMems.map(m => ({
      at: m.updated_at || m.created_at || 0,
      badge: `记忆形成 · ${m.kind}`,
      title: (m.content || '').replace(/\n/g, ' ').slice(0, 72),
      sub: `范围：${m.scope || '通用'} · 重要度 ${Number(m.importance || 0.5).toFixed(2)}`,
      jumpPage: 'ui3PageMemory',
    })),
    ...recentEvs.map(e => ({
      at: e.created_at || 0,
      badge: `事件记录 · ${eventLabel(e.kind)}`,
      title: e.payload?.reply ? `回复：${String(e.payload.reply).slice(0, 64)}` : `完成 ${eventLabel(e.kind)} 状态更新`,
      sub: date(e.created_at || 0),
      jumpPage: 'ui3PageTimeline',
    })),
  ].sort((a, b) => b.at - a.at).slice(0, 5);

  $('ui3HomeRecentList').innerHTML = combinedExp.length ? `<div class="ui3-timeline-list">${combinedExp.map(item => `
    <div class="ui3-timeline-item">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:4px">
        <span class="ui3-badge sage">${esc(item.badge)}</span>
        <button type="button" class="ui3-pill-btn" style="padding:2px 9px;font-size:11px" data-ui3-jump="${esc(item.jumpPage)}">查看详情 →</button>
      </div>
      <p style="margin:4px 0;font-size:13px;font-weight:550">${esc(item.title)}</p>
      <span style="font-size:11.5px;color:var(--ui3-text-muted)">${esc(item.sub)}</span>
    </div>
  `).join('')}</div>` : '<p class="ui3-sub">尚无历史互动或记忆记录。可从“成长工作室”导入聊天记录蒸馏，或在“时光与对话”中开启测试会话。</p>';
}

function renderUI3InnerWorld() {
  if (!state || !state.profile) return;
  const ov = state.ui3_overview || {};
  const hexDomains = ov.hexaco_domains || [];
  const schwartz = ov.schwartz_values || [];
  const interp2d = ov.interpersonal_2d || {};
  const tSnap = state.trait_snapshot || {};

  // 2.1 Layer 1: HEXACO 6 Domains
  $('ui3HexacoRadarBox').innerHTML = `
    <div style="display:grid;grid-template-columns:minmax(200px,260px) minmax(0,1fr);gap:16px;align-items:center">
      <div class="ui3-viz-box">${renderUI3HexacoRadarSVG(hexDomains)}</div>
      <div>
        ${hexDomains.map(d => `
          <div class="ui3-trait-row">
            <div class="ui3-trait-top">
              <span><strong>${esc(d.code)} · ${esc(d.name_zh)}</strong> <small style="color:var(--ui3-text-muted)">(${d.known_facet_count}/${d.total_facet_count} 已知分面)</small></span>
              <strong>${typeof d.estimate === 'number' ? d.estimate.toFixed(3) : '未知'}</strong>
            </div>
            <div class="ui3-bar-track"><div class="ui3-bar-fill" style="width:${typeof d.estimate === 'number' ? (d.estimate * 100).toFixed(1) : 0}%"></div></div>
          </div>
        `).join('')}
      </div>
    </div>
  `;

  // 2.1 Layer 2A: Schwartz Value Circle & Attachment 2D Space
  const att = interp2d.attachment_space || {};
  const ic = interp2d.interpersonal_circumplex || {};
  const attX = typeof att.seeking_closeness === 'number' ? 24 + att.seeking_closeness * 152 : 100;
  const attY = typeof att.anxiety === 'number' ? 24 + (1 - att.anxiety) * 152 : 100;
  $('ui3ValuesAndAttachmentBox').innerHTML = `
    <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;align-items:start">
      <div class="ui3-viz-box">
        <strong style="font-size:12px;margin-bottom:6px">Schwartz 19 项价值环</strong>
        ${renderUI3SchwartzCircleSVG(schwartz)}
      </div>
      <div class="ui3-viz-box">
        <strong style="font-size:12px;margin-bottom:6px">依恋与人际二维空间</strong>
        <svg viewBox="0 0 200 200" role="img" aria-label="依恋焦虑与亲近需求二维空间">
          <rect x="24" y="24" width="152" height="152" rx="10" fill="rgba(128,120,105,0.05)" stroke="rgba(128,120,105,0.22)" />
          <line x1="100" y1="24" x2="100" y2="176" stroke="rgba(128,120,105,0.24)" stroke-dasharray="3 3" />
          <line x1="24" y1="100" x2="176" y2="100" stroke="rgba(128,120,105,0.24)" stroke-dasharray="3 3" />
          <text x="100" y="17" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.65">高关系焦虑 (hexaco.e.anxiety)</text>
          <text x="100" y="191" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.65">低焦虑 · 安全稳定</text>
          <text x="28" y="96" font-size="8.5" fill="currentColor" opacity="0.6">独立疏离</text>
          <text x="172" y="96" font-size="8.5" text-anchor="end" fill="currentColor" opacity="0.6">高联结依恋</text>
          ${att.known ? `<circle cx="${attX.toFixed(1)}" cy="${attY.toFixed(1)}" r="7" fill="#78477a" stroke="#fff" stroke-width="2" />` : `<text x="100" y="104" font-size="10" text-anchor="middle" fill="currentColor" opacity="0.55">依恋坐标未知 (待设定或蒸馏)</text>`}
        </svg>
        <p class="ui3-sub" style="font-size:11.5px;margin-top:8px">
          焦虑倾向 (<code>hexaco.e.anxiety</code>)：<strong>${typeof att.anxiety === 'number' ? att.anxiety.toFixed(3) : '未知'}</strong> ·
          依恋支持 (<code>dependence/sentimentality</code>)：<strong>${typeof att.seeking_closeness === 'number' ? att.seeking_closeness.toFixed(3) : '未知'}</strong><br>
          人际能动 (<code>social.agency</code>)：<strong>${typeof ic.agency === 'number' ? ic.agency.toFixed(3) : '未知'}</strong> ·
          人际亲和 (<code>social.communion</code>)：<strong>${typeof ic.communion === 'number' ? ic.communion.toFixed(3) : '未知'}</strong>
        </p>
      </div>
    </div>
  `;

  // 2.1 Layer 2B: Full Construct Spectrum List
  const groupFilter = $('ui3ConstructGroupFilter')?.value || 'all';
  const allConstructs = [];
  const regMap = Object.fromEntries((state.psychology_registry || []).map(f => [f.id, f]));
  const dispMap = Object.fromEntries((Array.isArray(state.disposition_registry) ? state.disposition_registry : (state.disposition_registry?.fields || state.disposition_registry?.items || [])).map(d => [d.id, d]));

  const pushGroup = (groupKey, groupTitle, mapObj) => {
    if (groupFilter !== 'all' && groupFilter !== groupKey) return;
    for (const [cid, info] of Object.entries(mapObj || {})) {
      const meta = regMap[cid] || dispMap[cid] || { name_zh: cid, id: cid };
      allConstructs.push({
        id: cid,
        name_zh: meta.name_zh || cid,
        groupKey,
        groupTitle,
        estimate: info?.estimate ?? null,
        uncertainty: info?.uncertainty ?? 1.0,
        source_type: info?.source_type || 'unknown',
      });
    }
  };
  pushGroup('HEXACO', 'HEXACO 25 面向', tSnap.hexaco_facets);
  pushGroup('VALUES', 'Schwartz 19 价值', tSnap.value_priorities);
  pushGroup('AFFECTIVE', '情绪调节与基底习惯', tSnap.affective_disposition);
  pushGroup('INTERPERSONAL', '人际倾向', tSnap.interpersonal_dispositions);
  pushGroup('STYLE', '语言与互动风格', tSnap.behavioral_dispositions);

  $('ui3ConstructsSpectrumList').innerHTML = `<div class="ui3-grid-3">${allConstructs.map(c => {
    const known = typeof c.estimate === 'number';
    const isSel = c.id === ui3SelectedConstructId;
    return `<div class="ui3-trait-row" style="cursor:pointer;border-color:${isSel ? 'var(--ui3-accent)' : 'var(--ui3-border)'}" data-ui3-select-construct="${esc(c.id)}">
      <div class="ui3-trait-top">
        <span><strong>${esc(c.name_zh)}</strong> <small style="color:var(--ui3-text-muted)">${esc(c.id)}</small></span>
        <strong>${known ? c.estimate.toFixed(3) : '未知'}</strong>
      </div>
      <div class="ui3-bar-track" style="margin-bottom:6px">
        <div class="ui3-bar-fill ${c.groupKey === 'AFFECTIVE' ? 'plum' : c.groupKey === 'VALUES' ? 'warm' : ''}" style="width:${known ? (c.estimate * 100).toFixed(1) : 0}%"></div>
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;gap:6px">
        ${ui3SourceBadge(c.source_type, !known)}
        <span style="font-size:11px;color:var(--ui3-text-muted)">不确定性 ${(Number(c.uncertainty ?? 1)).toFixed(2)}</span>
      </div>
    </div>`;
  }).join('')}</div>`;

  // 2.1 Layer 3: Selected Construct Provenance & Evidence
  const selC = allConstructs.find(x => x.id === ui3SelectedConstructId) || allConstructs[0];
  if (selC) {
    const manualSeed = (tSnap.manual_seed || {})[selC.id];
    const dispEntry = (state.profile.trait_profile?.dispositions || {})[selC.id] || {};
    const obsList = ((state.profile.trait_profile?.disposition_observations || {})[selC.id] || []).slice(-5);
    const promos = (state.profile.trait_profile?.promotion_history || []).filter(h => h.feature_id === selC.id || (h.changes && h.changes[selC.id]));
    const lastPromo = promos[promos.length - 1] || null;
    $('ui3ConstructProvenanceDetail').innerHTML = `
      <div class="ui3-card-compact">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:10px">
          <div>
            <span class="ui3-kicker">${esc(selC.groupTitle)}</span>
            <h3 style="margin:2px 0">${esc(selC.name_zh)} (<code>${esc(selC.id)}</code>)</h3>
          </div>
          <button type="button" class="ui3-pill-btn" data-ui3-edit-seed="${esc(selC.id)}">修改主人设定值</button>
        </div>
        <div class="ui3-grid-2" style="gap:10px;margin-bottom:10px">
          <div class="ui3-trait-row" style="margin:0"><span class="ui3-sub">1. 用户设定初始值 (owner_seed)</span><br><strong>${manualSeed?.value != null ? Number(manualSeed.value).toFixed(3) : (selC.source_type === 'owner_seed' && selC.estimate != null ? selC.estimate.toFixed(3) : '未单独设定')}</strong></div>
          <div class="ui3-trait-row" style="margin:0"><span class="ui3-sub">2. 系统当前估计值</span><br><strong>${selC.estimate != null ? selC.estimate.toFixed(3) : '未知 (null)'}</strong> ${ui3SourceBadge(selC.source_type, selC.estimate == null)}</div>
          <div class="ui3-trait-row" style="margin:0"><span class="ui3-sub">3. 当前情境表现</span><br><strong>${selC.estimate != null ? '已参与当前情境解码与表达欲基线 b(θ) 计算' : '因数值未知，通过掩码屏蔽，不强行插补 0.5'}</strong></div>
          <div class="ui3-trait-row" style="margin:0"><span class="ui3-sub">5. 最近一次经审核更新</span><br><strong>${lastPromo ? `${date(lastPromo.at || lastPromo.promoted_at || 0)} · 版本 v${esc(lastPromo.version ?? '')}` : '暂无晋升记录'}</strong></div>
        </div>
        <div class="ui3-trait-row">
          <div class="ui3-trait-top"><span>4. 支持与反对的历史证据 (${obsList.length} 条近期观测)</span></div>
          ${obsList.length ? obsList.map(o => `<p class="ui3-sub" style="font-size:12px;margin:4px 0">· 观测值 ${Number(o.value ?? o.estimate ?? 0.5).toFixed(2)} · 来源事件 <code>${esc(o.event_id || o.source_id || '已记录')}</code> ${o.quote ? `「${esc(String(o.quote).slice(0, 60))}」` : ''}</p>`).join('') : '<p class="ui3-sub" style="font-size:12px;margin:2px 0">暂无记录（尚未积累针对该构念的独立正反历史证据）</p>'}
        </div>
        <div class="ui3-trait-row" style="margin-bottom:0">
          <div class="ui3-trait-top"><span>6. 在实际认知或决策中的影响</span></div>
          <p class="ui3-sub" style="font-size:12px;margin:2px 0">${selC.estimate != null ? '作为长期人格条件输入 PMM 状态解码器、情绪反应调节头与 Expressive Drive 基线矩阵 W_θ。' : '暂无记录（当前構念为未知状态，未对决策施加偏移）。'}</p>
        </div>
      </div>
    `;
  }

  // 2.1 Layer 4: Longitudinal Personality Revisions
  const promoHist = (state.profile.trait_profile?.promotion_history || []).slice().reverse();
  const revFiles = (personaRevisions || []).slice(0, 8);
  $('ui3TraitLongitudinalHistory').innerHTML = `
    <div style="max-height:380px;overflow:auto">
      ${promoHist.length ? promoHist.map(h => `
        <div class="ui3-trait-row">
          <div class="ui3-trait-top">
            <span class="ui3-badge sage">经审核晋升 · 版本 v${esc(h.version ?? '')}</span>
            <small>${h.at ? date(h.at) : ''}</small>
          </div>
          <p class="ui3-sub" style="font-size:12px;margin:4px 0">构念 <code>${esc(h.feature_id || '多项构念')}</code>：${fmt(h.before)} → <strong>${fmt(h.after)}</strong>（证据数：${esc(h.evidence_count ?? (h.records || []).length)}）</p>
        </div>
      `).join('') : '<p class="ui3-sub">尚无经审核晋升的长期人格参数变更记录。</p>'}
      <h4 style="font-size:13px;margin:14px 0 8px">已保存的人格恢复点 (${revFiles.length})</h4>
      ${revFiles.length ? revFiles.map(r => `
        <div class="ui3-trait-row" style="display:flex;justify-content:space-between;align-items:center;gap:8px">
          <div>
            <strong style="font-size:13px">${esc(r.label || r.id)}</strong>
            <div style="font-size:11px;color:var(--ui3-text-muted)">修订 v${esc(r.revision ?? '')} · ${r.created_at ? date(r.created_at) : ''}</div>
          </div>
          <button type="button" class="ui3-pill-btn" data-ui3-rollback-rev="${esc(r.id)}">回滚到此版本</button>
        </div>
      `).join('') : '<p class="ui3-sub">尚无手动保存的恢复点。</p>'}
    </div>
  `;

  // 2.2 Dynamic Emotion Space
  const aff2d = ov.affect_2d || {};
  const fast = aff2d.fast_emotion || {};
  const slow = aff2d.slow_mood || {};
  const mov = aff2d.movement || {};
  $('ui3Emotion2DSpaceBox').innerHTML = `
    <div style="display:grid;grid-template-columns:minmax(220px,290px) minmax(0,1fr);gap:16px;align-items:center">
      <div class="ui3-viz-box">${renderUI3AffectCircumplexSVG(fast, slow, mov, false)}</div>
      <div>
        <div class="ui3-trait-row">
          <span class="ui3-badge accent">快情绪 (Fast Emotion)</span>
          <p class="ui3-sub" style="font-size:12.5px;margin:6px 0 0">
            愉悦度 Valence：<strong>${typeof fast.valence === 'number' ? fast.valence.toFixed(3) : '未知'}</strong> [-1..1]<br>
            唤醒度 Arousal：<strong>${typeof fast.arousal === 'number' ? fast.arousal.toFixed(3) : '未知'}</strong> [0..1]<br>
            主导感 Dominance：<strong>${typeof fast.dominance === 'number' ? fast.dominance.toFixed(3) : '未知'}</strong> [0..1]<br>
            压力 Stress：<strong>${typeof fast.stress === 'number' ? fast.stress.toFixed(3) : '未知'}</strong> · 投入度 Engagement：<strong>${typeof fast.engagement === 'number' ? fast.engagement.toFixed(3) : '未知'}</strong>
          </p>
        </div>
        <div class="ui3-trait-row">
          <span class="ui3-badge indigo">慢心境 (Slow Mood)</span>
          <p class="ui3-sub" style="font-size:12.5px;margin:6px 0 0">
            心境效价：<strong>${typeof slow.valence === 'number' ? slow.valence.toFixed(3) : '未知'}</strong> ·
            心境唤醒：<strong>${typeof slow.arousal === 'number' ? slow.arousal.toFixed(3) : '未知'}</strong> ·
            心境主导：<strong>${typeof slow.dominance === 'number' ? slow.dominance.toFixed(3) : '未知'}</strong>
          </p>
        </div>
        <div class="ui3-card-compact" style="font-size:11.5px;color:var(--ui3-text-sec)">
          <strong>正式展示投影规则：</strong>横轴 X = (Valence + 1) / 2 ∈ [0, 1]（中心点 0.0），纵轴 Y = 1 - Arousal ∈ [0, 1]（静息中心 0.25）。仅表示内部模拟状态，不等同于已证实的主观体验。
        </div>
      </div>
    </div>
  `;

  // 2.2 B: 24 Emotion Categories
  const details24 = state.emotion_details || [];
  $('ui3Emotion24Grid').innerHTML = `<div class="ui3-grid-3" style="max-height:360px;overflow:auto">${details24.map(item => {
    const val = item.value;
    const known = typeof val === 'number' && Number.isFinite(val);
    return `<div class="ui3-trait-row" style="margin:0">
      <div class="ui3-trait-top">
        <span><strong>${esc(item.name_zh || item.id)}</strong></span>
        <strong>${known ? val.toFixed(3) : '未知'}</strong>
      </div>
      <div class="ui3-bar-track"><div class="ui3-bar-fill ${known && val > 0.55 ? 'warm' : ''}" style="width:${known ? (val * 100).toFixed(1) : 0}%"></div></div>
      <small style="font-size:10.5px;color:var(--ui3-text-muted)">${esc(item.status_label || (known ? '已激活' : '未校准/未知'))}</small>
    </div>`;
  }).join('')}</div>`;

  // 2.2 C & D: Emotion Trajectory & Raw Researcher Drawer
  const horizon = $('ui3EmotionHorizonFilter')?.value || 'all';
  const nowSec = Date.now() / 1000;
  const horizonCut = horizon === '6h' ? nowSec - 21600 : horizon === '24h' ? nowSec - 86400 : horizon === '7d' ? nowSec - 604800 : 0;
  const traj = (aff2d.trajectory || []).filter(pt => !horizonCut || Number(pt.at || 0) >= horizonCut);
  const causeLabels = {
    inbound_event_reaction: ['真实事件触发', 'accent'],
    time_propagation: ['现实时间传播', 'sage'],
    regulation: ['情绪调节', 'indigo'],
    internal_expression_feedback: ['表达行为反馈', 'plum'],
    external_partner_response: ['外部回应评价', 'amber'],
  };
  $('ui3EmotionTrajectoryBox').innerHTML = `
    ${traj.length ? `<div class="ui3-timeline-list" style="max-height:320px;overflow:auto;margin-bottom:14px">${traj.slice().reverse().map(pt => {
      const [cLbl, cCls] = causeLabels[pt.cause_category] || [pt.cause_category || '状态更新', 'indigo'];
      return `<div class="ui3-timeline-item">
        <div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap">
          <span class="ui3-badge ${cCls}">${esc(cLbl)}</span>
          <small style="color:var(--ui3-text-muted)">${pt.at ? date(pt.at) : ''}</small>
        </div>
        <p style="margin:6px 0 2px;font-size:13px"><strong>${esc(pt.summary)}</strong></p>
        <p class="ui3-sub" style="font-size:12px;margin:0">快情绪效价=${fmt(pt.valence)} · 唤醒=${fmt(pt.arousal)} · 主导=${fmt(pt.dominance)} | 慢心境效价=${fmt(pt.mood_valence)} · 事件 <code>${esc(pt.event_id || '—')}</code></p>
      </div>`;
    }).join('')}</div>` : '<p class="ui3-sub">当前时间范围内尚无情绪轨迹变化点。</p>'}
    <details style="border:1px solid var(--ui3-border);border-radius:10px;padding:10px 14px;background:var(--ui3-surface-solid)">
      <summary style="cursor:pointer;font-weight:600;font-size:13px">展开研究者原始情绪状态与动力学参数 (affect_state)</summary>
      <pre style="font-size:11.5px;max-height:280px;overflow:auto;margin-top:8px">${esc(JSON.stringify(state.affect_state, null, 2))}</pre>
    </details>
  `;

  // 2.3 Expressive Drive Sub-tab
  const edDetail = ov.expressive_drive_detail || {};
  const edStreams = edDetail.streams || [];
  const primaryStream = edStreams[0] || { activation: 0.45, urgency: 0.35, persistence: 0.48, expressive_intent: 'LISTEN', baseline: {} };
  const [dIntentLbl, dIntentDesc, dIntentCls] = ui3IntentLabels[primaryStream.expressive_intent] || [primaryStream.expressive_intent || 'LISTEN', '', 'sage'];

  $('ui3DriveChannelsBox').innerHTML = `
    <div style="margin-bottom:12px">
      <span class="ui3-badge ${dIntentCls}" style="font-size:12.5px;padding:5px 12px">${esc(dIntentLbl)}</span>
      <p class="ui3-sub" style="margin-top:6px">${esc(dIntentDesc)}</p>
    </div>
    <div class="ui3-trait-row">
      <div class="ui3-trait-top"><span>Activation（当前想表达的程度）</span><strong>${fmt(primaryStream.activation)} <small style="color:var(--ui3-text-muted)">(基线 ${fmt(primaryStream.baseline?.activation)})</small></strong></div>
      <div class="ui3-bar-track"><div class="ui3-bar-fill warm" style="width:${(Number(primaryStream.activation || 0) * 100).toFixed(1)}%"></div></div>
    </div>
    <div class="ui3-trait-row">
      <div class="ui3-trait-top"><span>Urgency（是否倾向立即抢话轮/接话）</span><strong>${fmt(primaryStream.urgency)} <small style="color:var(--ui3-text-muted)">(基线 ${fmt(primaryStream.baseline?.urgency)})</small></strong></div>
      <div class="ui3-bar-track"><div class="ui3-bar-fill plum" style="width:${(Number(primaryStream.urgency || 0) * 100).toFixed(1)}%"></div></div>
    </div>
    <div class="ui3-trait-row" style="margin-bottom:0">
      <div class="ui3-trait-top"><span>Persistence（未完成话题在真实时间下的留存韧性）</span><strong>${fmt(primaryStream.persistence)} <small style="color:var(--ui3-text-muted)">(基线 ${fmt(primaryStream.baseline?.persistence)})</small></strong></div>
      <div class="ui3-bar-track"><div class="ui3-bar-fill" style="width:${(Number(primaryStream.persistence || 0) * 100).toFixed(1)}%"></div></div>
    </div>
  `;

  // 2.3 History Curve SVG
  const edHist = edDetail.recent_history || [];
  if (edHist.length >= 1) {
    const w = 440, h = 170, pad = 24;
    const ptsFor = key => edHist.map((item, idx) => {
      const x = pad + (edHist.length === 1 ? (w - pad * 2) / 2 : (idx / (edHist.length - 1)) * (w - pad * 2));
      const y = pad + (1 - Math.max(0, Math.min(1, Number(item[key] || 0)))) * (h - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    $('ui3DriveCurveBox').innerHTML = `
      <div class="ui3-viz-box">
        <svg viewBox="0 0 ${w} ${h}" role="img" aria-label="表达欲三通道变化曲线">
          <line x1="${pad}" y1="${pad}" x2="${w - pad}" y2="${pad}" stroke="rgba(128,120,105,0.18)" />
          <line x1="${pad}" y1="${h / 2}" x2="${w - pad}" y2="${h / 2}" stroke="rgba(128,120,105,0.18)" stroke-dasharray="3 3" />
          <line x1="${pad}" y1="${h - pad}" x2="${w - pad}" y2="${h - pad}" stroke="rgba(128,120,105,0.18)" />
          <polyline fill="none" stroke="#b45638" stroke-width="2.2" points="${ptsFor('activation')}" />
          <polyline fill="none" stroke="#78477a" stroke-width="2" stroke-dasharray="4 2" points="${ptsFor('urgency')}" />
          <polyline fill="none" stroke="#2e6f5e" stroke-width="2" points="${ptsFor('persistence')}" />
        </svg>
        <div style="display:flex;gap:12px;font-size:11.5px;margin-top:6px">
          <span style="color:#b45638">● Activation</span>
          <span style="color:#78477a">● Urgency</span>
          <span style="color:#2e6f5e">● Persistence</span>
          <span style="color:var(--ui3-text-muted)">共 ${edHist.length} 次事件记录</span>
        </div>
      </div>
    `;
  } else {
    $('ui3DriveCurveBox').innerHTML = '<p class="ui3-sub">尚无表达欲历史事件曲线数据。</p>';
  }

  // 2.3 Motives Detail List
  const allMotives = edDetail.all_motives || [];
  $('ui3DriveMotivesDetailList').innerHTML = allMotives.length ? `<div class="ui3-grid-2">${allMotives.map(m => {
    const ie = m.intended_expression || {};
    const ext = ie.external_stimulus || {};
    const steps = ie.unsent_plan_steps || [];
    const statusCls = m.status === 'satisfied' ? 'ok' : m.status === 'abandoned' ? '' : 'plum';
    return `<div class="ui3-card-compact">
      <div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:6px">
        <span class="ui3-badge ${statusCls}">状态：${esc(m.status)} · 结果：${esc(m.delivery_outcome || 'pending')}</span>
        <span class="ui3-badge"><code>${esc(m.motive_id)}</code></span>
      </div>
      <h4 style="margin:4px 0;font-size:14.5px">话题：${esc(m.content_anchor?.topic || '未命名')}</h4>
      <p class="ui3-sub" style="font-size:12.5px;margin:4px 0"><strong>主体内部表达目标 (intended_goal)：</strong>${esc(ie.intended_goal || m.content_anchor?.summary || '—')}</p>
      <p class="ui3-sub" style="font-size:12px;margin:4px 0"><strong>具体想说的要点/追问：</strong>${esc(ie.candidate_point_or_question || '—')}</p>
      <p class="ui3-sub" style="font-size:12px;margin:4px 0"><strong>外部触发证据 (source_event_ids: ${esc((m.source_event_ids || []).join(', '))})：</strong>「${esc(ext.evidence_quote || m.content_anchor?.quote || '—')}」</p>
      ${steps.length ? `<div class="ui3-trait-row" style="margin:6px 0"><strong style="font-size:12px">待续接/待用户回复步骤 (${steps.length})：</strong>${steps.map(s => `<div style="font-size:11.5px;margin-top:3px">· [${esc(s.step_id)}] (${esc(s.depends_on)} / ${esc(s.status)}): ${esc(s.intended_point || s.purpose)}</div>`).join('')}</div>` : ''}
      <div style="font-size:11.5px;color:var(--ui3-text-muted);margin-top:6px">
        对象：${esc(m.person_id || m.scope)} · Activation=${fmt(m.activation)} · Urgency=${fmt(m.urgency)} · Persistence=${fmt(m.persistence)} · 暂缓原因：${esc(m.defer_reason || '无')}
      </div>
    </div>`;
  }).join('')}</div>` : '<p class="ui3-sub">尚无已记录的表达动机。</p>';
}

function renderUI3Timeline() {
  if (!state) return;
  const sessions = state.sessions || [];
  if ($('ui3TimelineSessionSelect')) {
    $('ui3TimelineSessionSelect').innerHTML = sessions.map(s =>
      `<option value="${esc(s.id)}" ${s.id === sessionId ? 'selected' : ''}>${esc(s.title || s.id)} (${esc(s.scope)})</option>`
    ).join('') || '<option value="">尚无会话</option>';
  }
  const curSession = sessions.find(s => s.id === sessionId) || sessions[0];
  const isQQ = curSession && (curSession.scope.startsWith('private:qq:') || curSession.scope.startsWith('group:qq:'));
  if ($('ui3SandboxSendBtn')) $('ui3SandboxSendBtn').disabled = Boolean(isQQ || busy);
  if ($('ui3SandboxInput')) $('ui3SandboxInput').disabled = Boolean(isQQ || busy);
  if ($('ui3SandboxHint')) {
    $('ui3SandboxHint').textContent = isQQ
      ? '当前所选为 QQ 历史会话（只读档案）。如需使用本机调试沙盒，请点击上方“＋ 新建本机测试会话”。'
      : '当前为本机会话 (private:web:owner)，可发送测试消息验证 PMM 与表达欲运行链。';
  }

  const kw = ($('ui3TimelineSearchInput')?.value || '').trim().toLowerCase();
  const dateFilter = ($('ui3TimelineDateInput')?.value || '').trim();
  const matchFilter = (text, ts) => {
    if (kw && !String(text || '').toLowerCase().includes(kw)) return false;
    if (dateFilter && ts) {
      const dStr = new Date(ts * 1000).toISOString().slice(0, 10);
      if (dStr !== dateFilter) return false;
    }
    return true;
  };

  const filteredMsgs = (messages || []).filter(m => matchFilter(m.content, m.created_at));
  $('ui3TimelineMessagesBox').innerHTML = filteredMsgs.length ? `<div class="ui3-timeline-list">${filteredMsgs.map(m => {
    const isUser = m.role === 'user';
    const isSilent = !m.content;
    return `<div class="ui3-timeline-item">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap">
        <div>
          <span class="ui3-badge ${isUser ? 'indigo' : isSilent ? 'amber' : 'ok'}">${isUser ? '对方来信' : isSilent ? '角色内部倾听/暂缓 · 未发消息' : esc(state.profile?.name || '角色回复') + ' · 已确认记录'}</span>
          ${m.turn_id ? `<small style="color:var(--ui3-text-muted);margin-left:6px">回合 <code>${esc(m.turn_id.slice(0, 12))}</code></small>` : ''}
        </div>
        <div style="display:flex;align-items:center;gap:6px">
          <small style="color:var(--ui3-text-muted)">${m.created_at ? date(m.created_at) : ''}</small>
          ${!isUser && m.turn_id ? `<button type="button" class="ui3-pill-btn" style="padding:2px 8px;font-size:11px" data-trace="${esc(m.turn_id)}">查看心理机制</button><button type="button" class="ui3-pill-btn" style="padding:2px 8px;font-size:11px" data-feedback="${esc(m.turn_id)}">校正表达</button>` : ''}
        </div>
      </div>
      <div style="font-size:14px;line-height:1.65;white-space:pre-wrap">${esc(m.content || '（本轮选择倾听或暂缓表达，未向外部发送消息）')}</div>
    </div>`;
  }).join('')}</div>` : '<p class="ui3-sub">当前会话或筛选条件下没有匹配的消息记录。</p>';

  // 7.2 Event Timeline
  const evRows = (events || []).filter(e => matchFilter(JSON.stringify(e.payload || {}), e.created_at));
  $('ui3TimelineEventsBox').innerHTML = evRows.length ? `<div class="ui3-timeline-list">${evRows.slice(0, 40).map(e => `
    <div class="ui3-timeline-item">
      <div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap">
        <span class="ui3-badge sage">${esc(eventLabel(e.kind))} (<code>${esc(e.kind)}</code>)</span>
        <small style="color:var(--ui3-text-muted)">${e.created_at ? date(e.created_at) : ''}</small>
      </div>
      <p class="ui3-sub" style="font-size:12.5px;margin:6px 0">${esc(e.payload?.reply || e.payload?.reason || e.payload?.scope || '已完成事件记录')}</p>
      <details style="font-size:11.5px;color:var(--ui3-text-sec)">
        <summary style="cursor:pointer">查看原始证据与事件载荷</summary>
        <pre style="max-height:200px;overflow:auto;margin-top:6px">${esc(JSON.stringify(e.payload, null, 2))}</pre>
      </details>
    </div>
  `).join('')}</div>` : '<p class="ui3-sub">暂无匹配的事件时间线记录。</p>';

  // 7.3 Historical Review
  const memRows = (memories || []).filter(m => matchFilter(m.content, m.created_at));
  $('ui3TimelineReviewBox').innerHTML = memRows.length ? `<div class="ui3-grid-2">${memRows.map(m => `
    <div class="ui3-card-compact">
      <div style="display:flex;justify-content:space-between;gap:8px;margin-bottom:6px">
        <span class="ui3-badge indigo">${esc(m.kind)} · 重要度 ${Number(m.importance || 0.5).toFixed(2)}</span>
        <small style="color:var(--ui3-text-muted)">${m.created_at ? date(m.created_at) : ''}</small>
      </div>
      <p style="font-size:13.5px;line-height:1.6;margin:6px 0;white-space:pre-wrap">${esc(m.content)}</p>
      ${m.evidence ? `<blockquote style="margin:6px 0;padding:6px 10px;border-left:3px solid var(--ui3-accent);font-size:12px;color:var(--ui3-text-sec)">原始证据：${esc(m.evidence)}</blockquote>` : ''}
    </div>
  `).join('')}</div>` : '<p class="ui3-sub">尚无可确认的历史共同经历记录（系统不会生成未经证实的虚假共同回忆）。</p>';
}

function renderUI3MemoryAndRelations() {
  if (!state) return;
  const ov = state.ui3_overview || {};
  const graph = ov.memory_relation_graph || { nodes: [], edges: [] };
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];

  // 8.2 Nomi-style Interactive SVG Graph
  if (ui3MemoryViewMode === 'graph' && nodes.length > 0) {
    const w = 560, h = 380, cx = w / 2, cy = h / 2;
    const posMap = {};
    const selfNode = nodes.find(n => n.kind === 'self') || nodes[0];
    posMap[selfNode.id] = { x: cx, y: cy };
    const others = nodes.filter(n => n.id !== selfNode.id);
    others.forEach((n, idx) => {
      const ring = n.kind === 'person' ? 95 : n.kind === 'motive' ? 135 : 155;
      const angle = (-Math.PI / 2) + (idx * 2 * Math.PI / Math.max(1, others.length));
      posMap[n.id] = {
        x: cx + ring * Math.cos(angle),
        y: cy + ring * Math.sin(angle),
      };
    });
    const kindColor = {
      self: '#b45638',
      person: '#3f588c',
      episode: '#2e6f5e',
      gist: '#588157',
      semantic: '#b87b28',
      motive: '#78477a',
    };
    $('ui3MemoryGraphWrap').innerHTML = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="记忆与关系关联网络图">
      ${edges.map(e => {
        const p1 = posMap[e.source], p2 = posMap[e.target];
        if (!p1 || !p2) return '';
        return `<line x1="${p1.x.toFixed(1)}" y1="${p1.y.toFixed(1)}" x2="${p2.x.toFixed(1)}" y2="${p2.y.toFixed(1)}" stroke="rgba(128,120,105,0.32)" stroke-width="${Math.max(1, (e.strength || 0.4) * 2.5).toFixed(1)}" />`;
      }).join('')}
      ${nodes.map(n => {
        const pt = posMap[n.id] || { x: cx, y: cy };
        const r = n.kind === 'self' ? 22 : n.kind === 'person' ? 16 : 12;
        const col = kindColor[n.kind] || '#2e6f5e';
        const isSel = n.id === ui3SelectedGraphNodeId;
        return `<g class="ui3-graph-node" data-ui3-graph-node="${esc(n.id)}">
          <circle cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" r="${r}" fill="${col}" stroke="${isSel ? '#1f1d1a' : '#fff'}" stroke-width="${isSel ? 3 : 1.8}" />
          <text x="${pt.x.toFixed(1)}" y="${(pt.y + r + 13).toFixed(1)}" font-size="10.5" font-weight="600" text-anchor="middle" fill="currentColor">${esc(n.label)}</text>
        </g>`;
      }).join('')}
    </svg>`;
  } else {
    $('ui3MemoryGraphWrap').innerHTML = `<div style="max-height:340px;overflow:auto;padding:8px">${nodes.map(n => `
      <div class="ui3-trait-row" style="cursor:pointer" data-ui3-graph-node="${esc(n.id)}">
        <span class="ui3-badge">${esc(n.kind)}</span> <strong>${esc(n.label)}</strong>
        <p class="ui3-sub" style="font-size:12px;margin:4px 0 0">${esc(n.content || n.intended_goal || n.subtitle || '')}</p>
      </div>
    `).join('')}</div>`;
  }

  const selNode = nodes.find(n => n.id === ui3SelectedGraphNodeId) || nodes[0];
  $('ui3MemoryNodeDetail').innerHTML = selNode ? `
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
      <span class="ui3-badge indigo">选中节点 · ${esc(selNode.kind)}</span>
      <small style="color:var(--ui3-text-muted)"><code>${esc(selNode.id)}</code></small>
    </div>
    <h4 style="margin:6px 0 4px">${esc(selNode.label)}</h4>
    <p class="ui3-sub" style="font-size:12.5px;margin:0">${esc(selNode.content || selNode.intended_goal || selNode.subtitle || `关联范围：${selNode.scope || '全局'}`)}</p>
  ` : '<p class="ui3-sub">点击上方网络图中的任意节点可查看关联证据详情。</p>';

  // 8.1 Memory Archive List
  const mSearch = ($('ui3MemorySearchInput')?.value || '').trim().toLowerCase();
  const mKind = $('ui3MemoryKindFilter')?.value || 'all';
  const filteredMems = (memories || []).filter(m => {
    if (mKind !== 'all' && m.kind !== mKind) return false;
    if (mSearch && !String(m.content || '').toLowerCase().includes(mSearch) && !String(m.evidence || '').toLowerCase().includes(mSearch)) return false;
    return true;
  });
  $('ui3MemoryArchiveList').innerHTML = filteredMems.length ? filteredMems.map(m => `
    <div class="ui3-trait-row">
      <div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:4px">
        <div>
          <span class="ui3-badge ${m.kind === 'hypothesis' ? 'amber' : 'sage'}">${esc(m.kind === 'episode' ? '事实经历' : m.kind === 'gist' ? '要点归纳' : m.kind === 'hypothesis' ? '待核实推测' : m.kind)}</span>
          <span class="ui3-badge">${esc(m.status || 'active')} · 重要度 ${Number(m.importance || 0.5).toFixed(2)}</span>
        </div>
        <small style="color:var(--ui3-text-muted)">${m.updated_at ? date(m.updated_at) : ''}</small>
      </div>
      <p style="font-size:13px;line-height:1.6;margin:6px 0;white-space:pre-wrap">${esc(m.content)}</p>
      ${m.evidence ? `<p class="ui3-sub" style="font-size:11.5px;margin:4px 0">来源证据：「${esc(String(m.evidence).slice(0, 120))}」</p>` : ''}
      <div style="display:flex;gap:6px;margin-top:8px;flex-wrap:wrap">
        <button type="button" class="ui3-pill-btn" style="padding:3px 10px;font-size:11px" data-ui3-mem-op="verify" data-ui3-mem-id="${esc(m.id)}">核实确认</button>
        <button type="button" class="ui3-pill-btn" style="padding:3px 10px;font-size:11px" data-ui3-mem-op="correct" data-ui3-mem-id="${esc(m.id)}" data-ui3-mem-text="${esc(m.content)}">修改校正</button>
        <button type="button" class="ui3-pill-btn" style="padding:3px 10px;font-size:11px" data-ui3-mem-op="delete" data-ui3-mem-id="${esc(m.id)}">删除</button>
      </div>
    </div>
  `).join('') : '<p class="ui3-sub">没有匹配的记忆条目。</p>';

  // 8.3 People & Dyads
  const dyads = Object.entries(state.dyads || {});
  const inters = state.interlocutors || {};
  $('ui3PeopleAndDyadsList').innerHTML = dyads.length ? dyads.map(([dkey, d]) => {
    const pid = d.person_id || d.target_id || dkey.split('|').pop();
    const sc = d.context_id || dkey.split('|')[0];
    const prof = inters[`${sc}|${pid}`] || inters[pid] || {};
    return `<div class="ui3-card-compact" style="margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:6px">
        <strong>${esc(prof.name || pid)} <small style="color:var(--ui3-text-muted)">(${esc(sc)})</small></strong>
        <span class="ui3-badge indigo">互动 ${esc(d.interactions ?? 0)} 次</span>
      </div>
      <div class="ui3-grid-3" style="gap:8px;margin:8px 0">
        <div class="ui3-trait-row" style="margin:0"><span class="ui3-sub">信任度 (Trust)</span><br><strong>${fmt(d.trust)}</strong></div>
        <div class="ui3-trait-row" style="margin:0"><span class="ui3-sub">熟悉度 (Familiarity)</span><br><strong>${fmt(d.familiarity)}</strong></div>
        <div class="ui3-trait-row" style="margin:0"><span class="ui3-sub">亲和度 (Affection)</span><br><strong>${fmt(d.affection ?? d.affiliation)}</strong></div>
      </div>
      <p class="ui3-sub" style="font-size:11.5px;margin:0">关系来源：${esc(d.source_type === 'manual' ? '主人手动设定' : '根据真实互动经历更新')} · 冲突记录 ${(d.conflict_history || []).length} 次</p>
    </div>`;
  }).join('') : '<p class="ui3-sub">尚无已记录的交谈对象与人际关系档案。</p>';

  // 8.3 Boundaries
  const hardBounds = state.profile?.boundaries || [];
  const dynBounds = state.boundary_model?.boundaries || [];
  $('ui3BoundariesPanel').innerHTML = `
    <h4 style="font-size:13px;margin:0 0 8px">主人设定的硬边界规则 (${hardBounds.length})</h4>
    ${hardBounds.map(b => `
      <div class="ui3-trait-row">
        <div class="ui3-trait-top">
          <span><span class="ui3-badge accent">主人设定 (${esc(b.action)})</span> <strong>${esc(b.label)}</strong></span>
          <span>${b.enabled ? '已启用' : '已停用'}</span>
        </div>
        <small style="color:var(--ui3-text-muted)">触发词：${esc((b.keywords || []).join('、') || '语义复核')}</small>
      </div>
    `).join('') || '<p class="ui3-sub">尚无硬边界规则。</p>'}
    <h4 style="font-size:13px;margin:14px 0 8px">情境动态边界倾向 (${dynBounds.length})</h4>
    ${dynBounds.map(b => `
      <div class="ui3-trait-row">
        <div class="ui3-trait-top">
          <span><span class="ui3-badge indigo">${esc(b.domain)}</span> <strong>${esc(b.topic)}</strong></span>
          <strong>敏感度 ${fmt(b.long_term_weight)}</strong>
        </div>
        <small style="color:var(--ui3-text-muted)">适用范围：${esc(b.scope)} · 对象：${esc(b.person)}</small>
      </div>
    `).join('') || '<p class="ui3-sub">尚无动态边界倾向。</p>'}
  `;
}

function renderUI3Studio() {
  if (!state) return;
  const learn = state.learning_center || {};
  const pol = learn.policy?.domains || {};
  const domainNames = {
    memory: ['记忆与经历 (Memory)', '提炼带原文引用的具体事件与归纳记忆'],
    self: ['稳定人格倾向与价值 (Self Traits & Values)', '提炼 HEXACO 分面、价值优先级与自我经验候选'],
    language: ['语言表达习惯 (Pragmatics & Style)', '统计分句、句长、标点与回应充足度习惯'],
    other: ['交谈对象画像 (Interlocutor Model)', '更新对其他人物的认识，不写入 AI 自身人格'],
    relationship: ['人际关系维度 (Relationships)', '更新熟悉度、信任度与亲和度证据'],
  };

  if ($('ui3StudioDomainsBox')) {
    $('ui3StudioDomainsBox').innerHTML = Object.entries(domainNames).map(([k, [title, desc]]) => {
      const dPol = pol[k] || { enabled: true, mode: k === 'memory' ? 'automatic' : 'candidate_only' };
      return `<div class="ui3-trait-row">
        <div class="ui3-trait-top">
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
            <input type="checkbox" data-ui3-pol-enable="${esc(k)}" ${dPol.enabled !== false ? 'checked' : ''}>
            <strong>${esc(title)}</strong>
          </label>
          <select data-ui3-pol-mode="${esc(k)}" class="ui3-pill-btn" style="padding:2px 8px;font-size:11.5px">
            <option value="candidate_only" ${dPol.mode === 'candidate_only' ? 'selected' : ''}>仅生成待审核候选 (candidate_only)</option>
            <option value="automatic" ${dPol.mode === 'automatic' ? 'selected' : ''}>有证据时自动应用 (automatic)</option>
          </select>
        </div>
        <p class="ui3-sub" style="font-size:12px;margin:2px 0 0">${esc(desc)}</p>
      </div>`;
    }).join('');
  }

  // Step 4: Jobs & Progress
  const activeJobs = state.active_jobs || [];
  $('ui3StudioLiveProgressBox').innerHTML = activeJobs.length ? activeJobs.map(j => `
    <div class="ui3-trait-row">
      <span class="ui3-badge amber">运行中 · ${esc(j.kind)}</span>
      <strong style="display:block;margin:6px 0">${esc(j.phase || '正在处理…')}</strong>
    </div>
  `).join('') : '<p class="ui3-sub">当前没有正在后台运行的蒸馏任务。点击上方按钮即可启动。</p>';

  const jobsList = learn.jobs || [];
  $('ui3StudioJobsList').innerHTML = jobsList.length ? jobsList.map(j => `
    <div class="ui3-trait-row">
      <div class="ui3-trait-top">
        <span><span class="ui3-badge">${esc(j.status)}</span> <strong>${esc(j.target === 'other' ? '认识他人' : '角色学习')}</strong></span>
        <small>${j.updated_at ? date(j.updated_at) : ''}</small>
      </div>
      <p class="ui3-sub" style="font-size:12px;margin:4px 0">进度：${esc(j.cursor ?? 0)} / ${esc(j.source_count ?? 0)} 条来源 · 范围 ${esc((j.scopes || []).join(', '))}</p>
      <div style="display:flex;gap:6px;margin-top:6px">
        ${j.status !== 'completed' ? `<button type="button" class="ui3-pill-btn" style="padding:2px 8px;font-size:11px" data-ui3-run-ljob="${esc(j.id)}">继续执行批次</button>` : ''}
      </div>
    </div>
  `).join('') : '<p class="ui3-sub">尚无历史学习批次记录。</p>';

  // Step 5: Candidates Review
  const tRev = state.trait_review || {};
  const tCands = tRev.candidates || [];
  $('ui3StudioTraitCandidatesBox').innerHTML = tCands.length ? tCands.map(c => `
    <div class="ui3-trait-row">
      <div class="ui3-trait-top">
        <strong>${esc(c.feature_id)}</strong>
        <span class="ui3-badge ${c.eligible ? 'ok' : 'amber'}">${c.eligible ? '满足晋升条件' : '待更多证据'}</span>
      </div>
      <p class="ui3-sub" style="font-size:12px;margin:4px 0">当前值 ${fmt(c.current)} → 候选估计 <strong>${fmt(c.proposed)}</strong> · 独立事件证据 ${esc(c.evidence_count ?? 0)} 条</p>
    </div>
  `).join('') : '<p class="ui3-sub">当前没有待审阅的长期人格倾向候选。</p>';

  const pCands = state.pragmatics?.learning_candidates || [];
  $('ui3StudioPragmaticCandidatesBox').innerHTML = pCands.length ? pCands.map(c => `
    <div class="ui3-trait-row">
      <div class="ui3-trait-top">
        <strong>${esc(c.label || c.field)}</strong>
        <span class="ui3-badge indigo">估计值 ${fmt(c.estimate)} (${esc(c.effective_events)} 次示范)</span>
      </div>
      <div style="display:flex;gap:6px;margin-top:6px">
        <button type="button" class="ui3-pill-btn primary" style="padding:2px 9px;font-size:11px" data-ui3-prag-review="${esc(c.id)}" data-ui3-prag-digest="${esc(c.evidence_digest)}" data-ui3-prag-act="apply">接受并应用</button>
        <button type="button" class="ui3-pill-btn" style="padding:2px 9px;font-size:11px" data-ui3-prag-review="${esc(c.id)}" data-ui3-prag-digest="${esc(c.evidence_digest)}" data-ui3-prag-act="reject">拒绝</button>
      </div>
    </div>
  `).join('') : '<p class="ui3-sub">当前没有待审阅的语言表达习惯候选。</p>';

  // Step 6: Four-State Outcome Report
  $('ui3StudioOutcomeReportBox').innerHTML = `
    <div class="ui3-grid-4" style="margin-bottom:16px">
      <div class="ui3-card-compact">
        <span class="ui3-badge sage">状态 1 · 蒸馏与提炼任务</span>
        <strong style="display:block;font-size:20px;margin:8px 0">${esc(learn.processed_sources ?? 0)} 条来源已处理</strong>
        <span class="ui3-sub" style="font-size:12px">累计任务 ${esc(learn.total_jobs ?? 0)} 个（蒸馏完成不代表已直接修改人格参数）</span>
      </div>
      <div class="ui3-card-compact">
        <span class="ui3-badge indigo">状态 2 · 记忆与经历入库</span>
        <strong style="display:block;font-size:20px;margin:8px 0">${esc(state.memory_count ?? 0)} 条有效记忆</strong>
        <span class="ui3-sub" style="font-size:12px">已入库记忆可立即用于对话检索与关联图展示</span>
      </div>
      <div class="ui3-card-compact">
        <span class="ui3-badge accent">状态 3 · 长期人格参数更新</span>
        <strong style="display:block;font-size:20px;margin:8px 0">长期特征版本 v${esc(state.profile?.trait_profile?.version ?? 0)}</strong>
        <span class="ui3-sub" style="font-size:12px">已晋升历史 ${(state.profile?.trait_profile?.promotion_history || []).length} 次 · 待审候选 ${tCands.length} 项</span>
      </div>
      <div class="ui3-card-compact">
        <span class="ui3-badge plum">状态 4 · 神经网络权重训练</span>
        <strong style="display:block;font-size:20px;margin:8px 0">已训练 ${esc(state.model?.steps ?? 0)} 步</strong>
        <span class="ui3-sub" style="font-size:12px">待训样本 ${esc(state.model?.pending_samples ?? 0)} 条 · 训练样本 ${esc(state.model?.train_samples ?? 0)} 条</span>
        <button type="button" class="ui3-pill-btn" style="margin-top:8px" id="ui3TriggerPmmTrainBtn">执行 PMM 权重训练</button>
      </div>
    </div>
  `;
  const trainBtn = ui3ById('ui3TriggerPmmTrainBtn');
  if (trainBtn) trainBtn.onclick = () => $('trainPmm')?.click();
}

function renderUI3Settings() {
  if (!state || !state.config) return;
  const p = state.profile;
  const c = state.config;
  const q = c.qq || {};
  const s = c.social || {};

  // 9.1 Persona Management
  $('ui3SettingsPersonaBox').innerHTML = `
    <div class="ui3-grid-2">
      <div class="ui3-card">
        <div class="ui3-card-head">
          <div>
            <span class="ui3-kicker">CHARACTER ROSTER · 角色列表与切换</span>
            <h2>创建、切换、克隆或导入角色</h2>
            <p class="ui3-sub">每个角色拥有完全独立的数据库、记忆、人际关系、情绪流与表达欲状态。</p>
          </div>
          <div style="display:flex;gap:8px">
            <button type="button" class="ui3-pill-btn primary" id="ui3SetNewPersonaBtn">＋ 创建新角色</button>
            <button type="button" class="ui3-pill-btn" id="ui3SetImportPackBtn">导入人格包</button>
          </div>
        </div>
        <div>
          ${(state.personas?.items || []).map(item => {
            const active = item.id === state.identity.id;
            return `<div class="ui3-trait-row" style="display:flex;justify-content:space-between;align-items:center;gap:10px">
              <div>
                <strong>${esc(active ? p.name : item.name)}</strong>
                ${active ? '<span class="ui3-badge ok" style="margin-left:6px">当前使用中</span>' : ''}
                <div style="font-size:11.5px;color:var(--ui3-text-muted)">ID: <code>${esc(item.id)}</code></div>
              </div>
              ${active ? `<button type="button" class="ui3-pill-btn" id="ui3SetEditCurrentCharBtn">编辑基础设定</button>` : `<button type="button" class="ui3-pill-btn primary" data-ui3-switch-persona="${esc(item.id)}">切换到此角色</button>`}
            </div>`;
          }).join('')}
        </div>
      </div>

      <div class="ui3-card">
        <div class="ui3-card-head">
          <div>
            <span class="ui3-kicker">INITIAL SEED VS LEARNED STATE · 设定与习得分离</span>
            <h2>当前角色基础设定与人格包导出</h2>
            <p class="ui3-sub">修改基础文字设定或回复风格不会覆盖模型通过经历习得的长期人格权重。</p>
          </div>
        </div>
        <div class="ui3-trait-row">
          <span class="ui3-sub">角色名称与自称：</span><strong>${esc(p.name)}（自称：${esc(p.character?.self_reference || '我')}）</strong>
        </div>
        <div class="ui3-trait-row">
          <span class="ui3-sub">用户设定的初始性格描述：</span>
          <p style="font-size:13px;margin:4px 0 0;white-space:pre-wrap">${esc(p.character?.initial_personality || '未填写')}</p>
        </div>
        <div class="ui3-trait-row">
          <span class="ui3-sub">基础背景资料 (Seed)：</span>
          <p style="font-size:13px;margin:4px 0 0;white-space:pre-wrap">${esc((p.seed || '未填写').slice(0, 300))}</p>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
          <button type="button" class="ui3-pill-btn primary" id="ui3SetOpenCharDialogBtn">修改角色基础设定</button>
          <button type="button" class="ui3-pill-btn" id="ui3SetExportContinuityBtn">导出完整延续人格包 (.json)</button>
          <button type="button" class="ui3-pill-btn" id="ui3SetSaveCheckpointBtn">保存当前恢复点</button>
        </div>
      </div>
    </div>
  `;

  // 9.2 Model Configuration Center (General LLM strictly distinct from PMM!)
  $('ui3SettingsModelsBox').innerHTML = `
    <div class="ui3-grid-3">
      <div class="ui3-card">
        <span class="ui3-badge ok">独立通用语言层 · General LLM</span>
        <h3 style="margin:10px 0 6px">1. 对话生成与理解模型</h3>
        <p class="ui3-sub">负责自然语言理解与最终回复生成。General LLM 独立于 PMM，不作为 PMM 的内部心理层。</p>
        <div class="ui3-trait-row" style="margin-top:12px">
          <span class="ui3-sub">当前模型：</span><strong>${esc(c.model || '未配置')}</strong><br>
          <span class="ui3-sub">协议类型：</span><code>${esc(c.protocol)}</code> · <span class="ui3-sub">服务地址：</span><code>${esc(c.base_url)}</code>
        </div>
        <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
          <button type="button" class="ui3-pill-btn primary" id="ui3TestGeneralModelBtn">测试对话模型连接</button>
          <button type="button" class="ui3-pill-btn" data-ui3-open-dev="connections">展开高级参数配置 →</button>
        </div>
      </div>

      <div class="ui3-card">
        <span class="ui3-badge indigo">人工心理核心 · PMM / PMM-A</span>
        <h3 style="margin:10px 0 6px">2. 内部心理理解与推理模型</h3>
        <p class="ui3-sub">负责事件情绪评价、表达欲计算、记忆检索排序与内在行动效用评估。</p>
        <div class="ui3-trait-row" style="margin-top:12px">
          <span class="ui3-sub">运行模式：</span><strong>${esc(modeName(state.model?.mode))} (${esc(c.pmm281?.mode === 'full' ? '完整 2.8.3 运行链' : '兼容模式')})</strong><br>
          <span class="ui3-sub">PMM-A 模型：</span><strong>${esc(c.pmm?.api?.model || state.model?.architecture || '本地数值模型')}</strong>
        </div>
        <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
          <button type="button" class="ui3-pill-btn primary" id="ui3TestPmmModelBtn">测试 PMM 连接</button>
          <button type="button" class="ui3-pill-btn" id="ui3CopyGeneralToPmmBtn">复用 General 连接配置</button>
        </div>
      </div>

      <div class="ui3-card">
        <span class="ui3-badge plum">深度协商 · PMM-B &amp; 成本概览</span>
        <h3 style="margin:10px 0 6px">3. 内部方案协商与 Token 账本</h3>
        <p class="ui3-sub">在存在目标冲突或边界风险时按需激活多视角方案协商 (PMM-B)。</p>
        <div class="ui3-trait-row" style="margin-top:12px">
          <span class="ui3-sub">PMM-B 触发策略：</span><strong>${esc(c.pmm281?.b_policy || 'auto')}</strong> ·
          <span class="ui3-sub">连接方式：</span><strong>${c.pmm281?.b?.share_a ? '共享 PMM-A 连接' : '独立配置'}</strong>
        </div>
        <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
          <button type="button" class="ui3-pill-btn" data-ui3-open-dev="connections">管理 Token 价目与账本 →</button>
        </div>
      </div>
    </div>
  `;

  // 9.3 QQ & Proactive Contact
  $('ui3SettingsQQBox').innerHTML = `
    <div class="ui3-grid-2">
      <div class="ui3-card">
        <div class="ui3-card-head">
          <div>
            <span class="ui3-kicker">QQ / ONEBOT BRIDGE · 外部交流渠道</span>
            <h2>QQ 连接状态与白名单授权</h2>
            <p class="ui3-sub">用户主要在 QQ 中与角色交流；仅允许白名单内的私聊号码与群号触发回复。</p>
          </div>
          <span class="ui3-badge ${q.enabled ? 'ok' : 'warn'}">${q.enabled ? 'QQ 自动回复已启用' : 'QQ 自动回复未启用'}</span>
        </div>
        <div class="ui3-trait-row">
          <span class="ui3-sub">机器人自身 QQ 号：</span><strong>${esc(q.self_id || '未填写')}</strong><br>
          <span class="ui3-sub">OneBot API 地址：</span><code>${esc(q.api_url || 'http://127.0.0.1:3000')}</code><br>
          <span class="ui3-sub">允许私聊 QQ 号 (${(q.allowed_users || []).length})：</span><code>${esc((q.allowed_users || []).join(', ') || '无')}</code><br>
          <span class="ui3-sub">允许群号 (${(q.allowed_groups || []).length})：</span><code>${esc((q.allowed_groups || []).join(', ') || '无')}</code>
        </div>
        <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
          <button type="button" class="ui3-pill-btn primary" id="ui3TestQQBtn">测试 OneBot 连接</button>
          <button type="button" class="ui3-pill-btn" data-ui3-open-dev="qqPage">编辑 QQ 号码与白名单 →</button>
        </div>
      </div>

      <div class="ui3-card">
        <div class="ui3-card-head">
          <div>
            <span class="ui3-kicker">PROACTIVE CONTACT · 表达欲驱动的主动联系</span>
            <h2>主动联系权限、免打扰与冷却限制</h2>
            <p class="ui3-sub">主动联系绝不是强制发言开关：必须同时满足授权白名单、非免打扰时段，且角色存在具体未完成表达动机 (has_concrete_motive)。</p>
          </div>
          <span class="ui3-badge ${s.enabled ? 'ok' : ''}">${s.enabled ? '主动联系已开启' : '主动联系默认关闭'}</span>
        </div>
        <div class="ui3-trait-row">
          <span class="ui3-sub">授权主动联系对象：</span><code>${esc((s.recipients || []).join(', ') || '未授权任何对象')}</code><br>
          <span class="ui3-sub">免打扰时段：</span><strong>${esc(s.quiet_start)} – ${esc(s.quiet_end)} (${esc(s.timezone)})</strong><br>
          <span class="ui3-sub">静默等待 / 冷却间隔：</span><strong>${esc(s.idle_minutes)} 分钟 / ${esc(s.cooldown_minutes)} 分钟</strong> · 每日预算 ${esc(s.daily_budget)} 条
        </div>
        <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap">
          <button type="button" class="ui3-pill-btn" data-ui3-open-dev="qqPage">修改主动联系设置 →</button>
        </div>
      </div>
    </div>
  `;

  // 9.4 Data Management & Developer Research Workbench Entry
  $('ui3SettingsDataBox').innerHTML = `
    <div class="ui3-grid-2">
      <div class="ui3-card">
        <span class="ui3-kicker">DATA &amp; PRIVACY · 数据目录与备份恢复</span>
        <h2 style="margin:4px 0 8px">本地数据存储与安全导出</h2>
        <p class="ui3-sub">所有聊天档案、记忆、人格参数与权重均保存在本地目录；支持完整快照备份与按范围清理个人数据。</p>
        <div class="ui3-trait-row" style="margin-top:12px">
          <span class="ui3-sub">当前角色数据目录：</span><code>${esc(state.data_dir)}</code><br>
          <span class="ui3-sub">全局数据根目录：</span><code>${esc(state.data_status?.root || '')}</code>
        </div>
        <div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap">
          <button type="button" class="ui3-pill-btn primary" id="ui3ExportSnapshotBtn">导出完整系统快照 (.json)</button>
          <button type="button" class="ui3-pill-btn" id="ui3RestoreSnapshotBtn">从快照文件恢复</button>
          <button type="button" class="ui3-pill-btn" id="ui3ExportSupportBtn">导出脱敏诊断报告</button>
        </div>
      </div>

      <div class="ui3-card" style="border-color:var(--ui3-accent)">
        <span class="ui3-kicker">RESEARCH WORKBENCH · 高级研究与开发者工作台</span>
        <h2 style="margin:4px 0 8px">进入完整研发与调试视图</h2>
        <p class="ui3-sub">面向研究者与开发者，完整保留 PMM-A/PMM-B 协商详情、Learned-PMM 权重训练、情绪动力学标定、Expressive Drive 矩阵贡献、CognitiveRouter、Token 账本、Outbox 事务恢复及全部 11 个原始研发子页面。</p>
        <div style="display:flex;gap:8px;margin-top:16px;flex-wrap:wrap">
          <button type="button" class="ui3-pill-btn primary" id="ui3EnterDevWorkbenchBtn">🛠 切换到高级研究工作台</button>
          <button type="button" class="ui3-pill-btn" data-ui3-open-dev="diagnostics">直接打开执行与诊断记录 →</button>
          <button type="button" class="ui3-pill-btn" data-ui3-open-dev="modelTraining">直接打开模型训练与校准 →</button>
        </div>
      </div>
    </div>
  `;
}

function renderUI3() {
  if (!state || !state.profile) return;
  try {
    renderUI3Home();
    renderUI3InnerWorld();
    renderUI3Timeline();
    renderUI3MemoryAndRelations();
    renderUI3Studio();
    renderUI3Settings();
  } catch (err) {
    console.error('UI3 render error:', err);
  }
}

// Wire UI 3.0 interactive delegation
if (typeof document !== 'undefined') {
  document.addEventListener('click', guard(async e => {
    const btn = e.target?.closest?.('button, a, [data-ui3-select-construct], [data-ui3-graph-node]');
    if (!btn) return;

    if (btn.id === 'ui3PortSwitchBtn' || btn.id === 'ui3EnterDevWorkbenchBtn') {
      switchUI3Port('developer');
      return;
    }
    if (btn.id === 'ui3ReturnToUserBtn') {
      switchUI3Port('user');
      return;
    }
    if (btn.id === 'ui3ThemeToggle' || btn.id === 'ui3DevThemeBtn') {
      toggleUI3Theme();
      return;
    }
    if (btn.dataset?.ui3OpenDev) {
      switchUI3Port('developer');
      showPage(btn.dataset.ui3OpenDev);
      return;
    }
    if (btn.dataset?.ui3Page) {
      showUI3Page(btn.dataset.ui3Page);
      return;
    }
    if (btn.dataset?.ui3Jump) {
      showUI3Page(btn.dataset.ui3Jump, btn.dataset.ui3Subtab);
      return;
    }
    if (btn.dataset?.ui3InnerTab) {
      showUI3Page('ui3PageInner', btn.dataset.ui3InnerTab);
      return;
    }
    if (btn.dataset?.ui3TimelineTab) {
      showUI3Page('ui3PageTimeline', btn.dataset.ui3TimelineTab);
      return;
    }
    if (btn.dataset?.ui3MemTab) {
      showUI3Page('ui3PageMemory', btn.dataset.ui3MemTab);
      return;
    }
    if (btn.dataset?.ui3SetTab) {
      showUI3Page('ui3PageSettings', btn.dataset.ui3SetTab);
      return;
    }
    if (btn.dataset?.ui3Step || btn.dataset?.ui3StepGoto) {
      const stepNum = btn.dataset.ui3Step || btn.dataset.ui3StepGoto;
      document.querySelectorAll('#ui3StudioStepper .ui3-step-btn').forEach(b => b.classList.toggle('active', b.dataset.ui3Step === String(stepNum)));
      showUI3Page('ui3PageStudio', 'ui3StudioStep' + stepNum);
      return;
    }
    if (btn.dataset?.ui3ChooseTarget) {
      const t = btn.dataset.ui3ChooseTarget;
      if ($('ui3StudioTargetMode')) $('ui3StudioTargetMode').value = t === 'other' ? 'other' : 'self';
      document.querySelectorAll('#ui3StudioStepper .ui3-step-btn').forEach(b => b.classList.toggle('active', b.dataset.ui3Step === '2'));
      showUI3Page('ui3PageStudio', 'ui3StudioStep2');
      return;
    }
    if (btn.dataset?.ui3SelectConstruct) {
      ui3SelectedConstructId = btn.dataset.ui3SelectConstruct;
      renderUI3InnerWorld();
      return;
    }
    if (btn.dataset?.ui3EditSeed) {
      openTraitSeed(btn.dataset.ui3EditSeed);
      return;
    }
    if (btn.id === 'ui3OpenTraitSeedBtn') {
      openTraitSeed(ui3SelectedConstructId || 'hexaco.x.social_boldness');
      return;
    }
    if (btn.id === 'ui3NewPersonaBtn' || btn.id === 'ui3SetNewPersonaBtn') {
      $('newPersona')?.click();
      return;
    }
    if (btn.id === 'ui3ClonePersonaBtn') {
      $('cloneTemplate').checked = true;
      $('personaDialog').showModal();
      return;
    }
    if (btn.id === 'ui3SetImportPackBtn') {
      $('importPack')?.click();
      return;
    }
    if (btn.id === 'ui3SetEditCurrentCharBtn' || btn.id === 'ui3SetOpenCharDialogBtn') {
      $('editCharacter')?.click();
      return;
    }
    if (btn.id === 'ui3SetExportContinuityBtn') {
      download('/api/persona/export?scope=continuity');
      return;
    }
    if (btn.id === 'ui3SaveCheckpointBtn' || btn.id === 'ui3SetSaveCheckpointBtn') {
      await api('/api/persona/checkpoint', { label: 'UI 3.0 手动恢复点' });
      await refresh();
      notice('已保存当前角色恢复点。');
      return;
    }
    if (btn.dataset?.ui3RollbackRev) {
      await api('/api/persona/rollback', { id: btn.dataset.ui3RollbackRev });
      await refresh();
      notice('已回滚到所选角色版本。');
      return;
    }
    if (btn.dataset?.ui3SwitchPersona) {
      await api('/api/persona/activate', { id: btn.dataset.ui3SwitchPersona });
      await refresh();
      notice('已切换当前角色。');
      return;
    }
    if (btn.id === 'ui3HomeAdvanceIdleBtn' || btn.id === 'ui3InnerAdvanceIdleBtn') {
      const curScope = state.sessions?.[0]?.scope || 'private:web:owner';
      await api('/api/pmm283/expressive-drive/advance', { scope: curScope, commit: true });
      await refresh();
      notice('已按真实挂钟时间推进表达欲静默演化。');
      return;
    }
    if (btn.id === 'ui3GraphViewBtn') {
      ui3MemoryViewMode = 'graph';
      $('ui3GraphViewBtn').classList.add('primary');
      $('ui3ListViewBtn').classList.remove('primary');
      renderUI3MemoryAndRelations();
      return;
    }
    if (btn.id === 'ui3ListViewBtn') {
      ui3MemoryViewMode = 'list';
      $('ui3ListViewBtn').classList.add('primary');
      $('ui3GraphViewBtn').classList.remove('primary');
      renderUI3MemoryAndRelations();
      return;
    }
    if (btn.dataset?.ui3GraphNode) {
      ui3SelectedGraphNodeId = btn.dataset.ui3GraphNode;
      renderUI3MemoryAndRelations();
      return;
    }
    if (btn.dataset?.ui3MemOp) {
      const op = btn.dataset.ui3MemOp, id = btn.dataset.ui3MemId;
      if (op === 'correct') {
        const nextText = prompt('修改记忆内容：', btn.dataset.ui3MemText || '');
        if (!nextText) return;
        await api('/api/memory', { id, op: 'correct', content: nextText });
      } else {
        await api('/api/memory', { id, op });
      }
      await refresh();
      notice('记忆状态已更新。');
      return;
    }
    if (btn.id === 'ui3RunMemoryGistBtn') {
      const out = await api('/api/memory/consolidate', {});
      if (out.job_id) await runJob(out, 'memory_gist');
      await refresh();
      return;
    }
    if (btn.id === 'ui3AddDynamicBoundaryBtn') {
      editDynamicBoundary();
      return;
    }
    if (btn.id === 'ui3NewLocalSessionBtn') {
      const r = await api('/api/session', {});
      sessionId = r.id;
      await refresh();
      notice('已创建新的本机测试会话。');
      return;
    }
    if (btn.id === 'ui3TimelineClearFilterBtn') {
      if ($('ui3TimelineSearchInput')) $('ui3TimelineSearchInput').value = '';
      if ($('ui3TimelineDateInput')) $('ui3TimelineDateInput').value = '';
      renderUI3Timeline();
      return;
    }
    if (btn.id === 'ui3SandboxSendBtn') {
      const txt = ($('ui3SandboxInput')?.value || '').trim();
      if (!txt) throw new Error('请输入测试消息内容');
      $('ui3SandboxInput').value = '';
      const out = await api('/api/chat', { session_id: sessionId, text: txt, client_event_id: 'ui3_' + Date.now() });
      if (out.job_id) await runJob(out, 'chat');
      await refresh();
      return;
    }
    if (btn.id === 'ui3StudioPreviewBtn') {
      const raw = ($('ui3StudioRawText')?.value || '').trim();
      if (!raw) throw new Error('请先粘贴聊天记录或选择本地文件');
      const fmtVal = $('ui3StudioFormatSelect')?.value || 'auto';
      const prev = await api('/api/import/preview', { content: raw, format: fmtVal });
      ui3StudioPreviewData = prev;
      const spkEntries = Object.entries(prev.speakers || {});
      if ($('ui3StudioSpeakerSelect')) {
        $('ui3StudioSpeakerSelect').innerHTML = spkEntries.map(([spk, cnt]) =>
          `<option value="${esc(spk)}">${esc(spk)}（${cnt} 条消息）</option>`
        ).join('') || '<option value="">未识别到说话人</option>';
      }
      if ($('ui3StudioPreviewSummary')) {
        $('ui3StudioPreviewSummary').innerHTML = `<div class="ui3-trait-row"><span class="ui3-badge ok">格式检查通过 · 共 ${esc(prev.count)} 条记录</span><p class="ui3-sub" style="font-size:12px;margin-top:6px">识别到 ${spkEntries.length} 位说话人。预览首条：「${esc(prev.preview?.[0]?.text || '')}」</p></div>`;
      }
      notice(`已识别 ${prev.count} 条聊天记录，请选择目标说话人。`);
      return;
    }
    if (btn.id === 'ui3SaveLearningPolicyBtn') {
      const domains = {};
      document.querySelectorAll('[data-ui3-pol-enable]').forEach(chk => {
        const k = chk.dataset.ui3PolEnable;
        const modeEl = document.querySelector(`[data-ui3-pol-mode="${k}"]`);
        domains[k] = { enabled: chk.checked, mode: modeEl ? modeEl.value : 'candidate_only' };
      });
      await api('/api/learning/policy', { persona_id: state.identity.id, domains });
      await refresh();
      notice('学习与审核策略已保存。');
      return;
    }
    if (btn.id === 'ui3StartDistillBtn') {
      const content = ($('ui3StudioRawText')?.value || '').trim();
      const speaker = $('ui3StudioSpeakerSelect')?.value || '';
      if (!content || !speaker) throw new Error('请先在“步骤 2：选择数据”中输入记录并选择说话人');
      const res = await api('/api/distill', {
        content,
        format: $('ui3StudioFormatSelect')?.value || 'auto',
        speaker,
        target: $('ui3StudioTargetMode')?.value || 'self',
        person: $('ui3StudioPersonInput')?.value || 'web:owner',
        scope: $('ui3StudioScopeInput')?.value || 'private:web:owner',
      });
      await runJob(res, 'distill');
      await refresh();
      return;
    }
    if (btn.id === 'ui3CreateLearningJobBtn') {
      const created = await api('/api/learning/create', {
        persona_id: state.identity.id,
        target: $('ui3StudioTargetMode')?.value || 'self',
        scopes: [$('ui3StudioScopeInput')?.value || 'private:web:owner'],
        range: 'all',
        intent: 'review',
      });
      if (created.job?.id) {
        const started = await api('/api/learning/run', { persona_id: state.identity.id, id: created.job.id });
        if (started.job_id) await runJob(started, 'learning');
      }
      await refresh();
      return;
    }
    if (btn.dataset?.ui3RunLjob) {
      const started = await api('/api/learning/run', { persona_id: state.identity.id, id: btn.dataset.ui3RunLjob });
      if (started.job_id) await runJob(started, 'learning');
      await refresh();
      return;
    }
    if (btn.id === 'ui3RunConsolidationBtn') {
      const out = await api('/api/consolidation/run', { retry: true });
      if (out.job_id) await runJob(out, 'consolidation');
      await refresh();
      return;
    }
    if (btn.id === 'ui3ApplyTraitReviewBtn') {
      await api('/api/traits/review', { persona_id: state.identity.id, apply: true });
      await refresh();
      notice('已审阅并应用合格的长期人格倾向候选。');
      return;
    }
    if (btn.dataset?.ui3PragReview) {
      await api('/api/pragmatics/review', {
        persona_id: state.identity.id,
        candidate_id: btn.dataset.ui3PragReview,
        evidence_digest: btn.dataset.ui3PragDigest,
        expected_version: state.pragmatics?.profile?.version ?? 0,
        action: btn.dataset.ui3PragAct || 'apply',
        note: 'UI 3.0 成长工作室人工审阅',
      });
      await refresh();
      notice('已更新语言表达习惯候选审阅状态。');
      return;
    }
    if (btn.id === 'ui3TestGeneralModelBtn') {
      await testConnection('general');
      return;
    }
    if (btn.id === 'ui3TestPmmModelBtn') {
      await testConnection('pmm');
      return;
    }
    if (btn.id === 'ui3CopyGeneralToPmmBtn') {
      await api('/api/pmm/api/copy-general', {});
      await refresh();
      notice('已将对话生成模型的连接配置复制到 PMM。');
      return;
    }
    if (btn.id === 'ui3TestQQBtn') {
      const r = await api('/api/qq/test', {});
      notice(`QQ 连接正常：${r.nickname || ''} (${r.user_id || ''})`);
      return;
    }
    if (btn.id === 'ui3ExportSnapshotBtn') {
      download('/api/export');
      return;
    }
    if (btn.id === 'ui3RestoreSnapshotBtn') {
      $('backupFile')?.click();
      return;
    }
    if (btn.id === 'ui3ExportSupportBtn') {
      download('/api/support');
      return;
    }
  }));

  if ($('ui3PersonaSelect')) {
    $('ui3PersonaSelect').onchange = guard(async e => {
      if (e.target.value && e.target.value !== state?.identity?.id) {
        await api('/api/persona/activate', { id: e.target.value });
        await refresh();
      }
    });
  }
  if ($('ui3ConstructGroupFilter')) $('ui3ConstructGroupFilter').onchange = () => renderUI3InnerWorld();
  if ($('ui3EmotionHorizonFilter')) $('ui3EmotionHorizonFilter').onchange = () => renderUI3InnerWorld();
  if ($('ui3TimelineSessionSelect')) {
    $('ui3TimelineSessionSelect').onchange = guard(async e => {
      sessionId = e.target.value;
      messages = await api('/api/messages?session=' + encodeURIComponent(sessionId));
      renderChat();
      renderUI3Timeline();
    });
  }
  if ($('ui3TimelineSearchInput')) $('ui3TimelineSearchInput').oninput = () => renderUI3Timeline();
  if ($('ui3TimelineDateInput')) $('ui3TimelineDateInput').onchange = () => renderUI3Timeline();
  if ($('ui3MemorySearchInput')) $('ui3MemorySearchInput').oninput = () => renderUI3MemoryAndRelations();
  if ($('ui3MemoryKindFilter')) $('ui3MemoryKindFilter').onchange = () => renderUI3MemoryAndRelations();
  if ($('ui3StudioFileInput')) {
    $('ui3StudioFileInput').onchange = async e => {
      const f = e.target.files?.[0];
      if (!f) return;
      const txt = await f.text();
      if ($('ui3StudioRawText')) $('ui3StudioRawText').value = txt;
      notice(`已读取文件 ${f.name}（${txt.length} 字符），请点击“检查格式并识别说话人”。`);
    };
  }
}
