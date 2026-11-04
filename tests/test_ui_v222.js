'use strict';
// Executes the shipped app.js startup over a real loopback HTTP server and cookie jar.
// No injected state object and no external model calls. This is not visual browser E2E.
const assert=require('node:assert/strict'),cp=require('node:child_process'),readline=require('node:readline'),path=require('node:path');
const {harness}=require('./dom_harness_v222');
async function server(){
 const child=cp.spawn(process.env.TEST_PYTHON||'python3',[path.join(__dirname,'ui_server_v222.py')],{env:{...process.env,OPENBLAS_NUM_THREADS:'1'},stdio:['pipe','pipe','pipe']});
 let queued=[],pending=[],errors='';child.stderr.on('data',v=>errors+=v);
 readline.createInterface({input:child.stdout}).on('line',line=>{if(line.startsWith('TEST_CONTROL ')){const v=JSON.parse(line.slice(13));pending.length?pending.shift()(v):queued.push(v)}});
 const next=()=>new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Test server timeout '+errors)),15000);const done=v=>{clearTimeout(timer);resolve(v)};queued.length?done(queued.shift()):pending.push(done)});
 const exited=new Promise(resolve=>child.once('exit',resolve));
 const info=await next();
 return {...info,async control(op,value){child.stdin.write(JSON.stringify({op,value})+'\n');return next()},async close(){if(child.exitCode===null){await this.control('stop');child.stdin.end();}await exited;}};
}
function client(base,jar=new Map()){
 const requests=[];
 const fetcher=async(url,opts={})=>{const res=await fetch(base+url,{...opts,headers:{...(opts.headers||{}),Cookie:[...jar].map(([k,v])=>k+'='+v).join('; ')}});for(const cookie of res.headers.getSetCookie()){const first=cookie.split(';')[0],i=first.indexOf('=');jar.set(first.slice(0,i),first.slice(i+1));}requests.push({method:opts.method||'GET',path:url,status:res.status});const bytes=await res.arrayBuffer();return new Response(bytes,{status:res.status,statusText:res.statusText,headers:res.headers})};
 return {fetch:fetcher,requests,jar};
}
async function main(){
 const app=await server();let other;const c=client(app.base);let checks=0;
 const ok=name=>console.log('PASS '+(++checks)+' '+name);
 try{
  const html=await(await c.fetch('/')).text(),build=html.match(/name="app-build" content="([^"]+)"/)[1],source=await(await c.fetch('/app.js')).text();
  let release,requested;const hold=new Promise(r=>release=r),arrived=new Promise(r=>requested=r);
  const ui=harness(app.nodes,source,async(...args)=>{if(args[0]==='/api/state'&&!release.done){requested();await hold;}return c.fetch(...args)},build);
  await arrived;assert(ui.ids.get('editCharacter').disabled);await ui.click('editCharacter');assert(!ui.ids.get('characterDialog').open);assert.equal(ui.run('state'),null);release.done=true;release();await ui.boot;
  assert.equal(ui.run('uiReady'),true);assert.equal(ui.ids.get('selfProfileName').textContent,'原来的槐安');assert(ui.ids.get('psychologyPanel').innerHTML.includes('HEXACO'));assert(ui.ids.get('chatLog').innerHTML.includes('合成历史原文'));
  assert.equal(ui.run('state.identity.id'),app.first);assert.equal(ui.run('state.sessions.length'),2);ok('真实首次启动先禁用编辑，再呈现同一主体、维度和 QQ 历史');
  await ui.click('editCharacter');ui.ids.get('characterName').value='修复后仍是原主体';await ui.submit('characterForm');assert.equal((await app.control('stats')).name,'修复后仍是原主体');assert.equal(ui.run('state.identity.id'),app.first);ok('角色表单通过实际 POST 保存，保留主体 ID');
  await ui.click('newDynamicBoundary');ui.ids.get('dynamicBoundaryTopic').value='合成边界修改';await ui.submit('dynamicBoundaryForm');assert(ui.ids.get('dynamicBoundaryList').innerHTML.includes('合成边界修改'));ok('边界表单独立保存，无模型连接依赖');
  await app.control('faults',{'/api/events':'500'});await ui.run('refresh()');assert(ui.ids.get('eventList').innerHTML.includes('SYNTHETIC_FAILURE'));assert.equal(ui.ids.get('selfProfileName').textContent,'修复后仍是原主体');assert(ui.ids.get('chatLog').innerHTML.includes('合成历史原文'));ok('操作日志 500 不阻断人格、维度和聊天历史');
  await app.control('faults',{boundaries:true});await ui.run('refresh()');assert(ui.ids.get('dynamicBoundaryList').innerHTML.includes('此模块读取失败'));assert(ui.ids.get('newDynamicBoundary').disabled);assert(ui.ids.get('psychologyPanel').innerHTML.includes('HEXACO'));ok('可选边界模块故障显示诊断，其余人格页面仍可用');
  await app.control('faults',{'/api/state':'500'});await assert.rejects(ui.run('refresh()'));assert(!ui.run('uiReady'));await ui.click('editCharacter');assert(ui.ids.get('localStatus').textContent.includes('GET /api/state'));assert(ui.ids.get('localStatus').textContent.includes('500'));ok('核心状态失败无空值崩溃，显示方法、路径、状态和错误编号');
  await app.control('faults',{});await ui.click('retryLocal');assert(ui.run('uiReady'));assert(!ui.ids.get('newDynamicBoundary').disabled);ok('不刷新网页即可重新建立管理会话并恢复本地数据');
  for(const fault of ['null','json']){await app.control('faults',{'/api/state':fault});await assert.rejects(ui.run('refresh()'));assert(!ui.run('uiReady'));assert(ui.ids.get('notice').textContent.includes(fault==='null'?'INVALID_RESPONSE':'INVALID_JSON'));}
  await app.control('faults',{'/api/memories':'null'});await ui.run('refresh()');ui.run('renderMemory()');assert(ui.run('uiReady'));assert(ui.ids.get('memoryList').innerHTML.includes('INVALID_RESPONSE'));ok('空值与坏 JSON 显示具体错误，搜索也不把失败伪装为零条记录');
  await app.control('faults',{});await ui.run('refresh()');await ui.click('editCharacter');ui.ids.get('characterName').value='会话恢复后保存';await app.control('rotate');const before=(await app.control('stats')).posts.length;
  await ui.submit('characterForm');const first=(await app.control('stats'));assert.equal(first.posts.length,before+1);assert.equal(first.name,'修复后仍是原主体');assert(ui.ids.get('notice').textContent.includes('SESSION_RECONNECTED'));await ui.submit('characterForm');assert.equal((await app.control('stats')).name,'会话恢复后保存');ok('会话过期后不重放写请求，用户再次保存才修改');
  await app.control('restart');await ui.run('refresh()');assert.equal(ui.run('state.identity.id'),app.first);assert.equal(ui.run('state.profile.name'),'会话恢复后保存');assert(ui.ids.get('chatLog').innerHTML.includes('合成历史原文'));assert(ui.ids.get('dynamicBoundaryList').innerHTML.includes('合成边界修改'));ok('实际后端重启后 GET 自动重连，身份、历史、角色与边界连续');
  const bad=harness(app.nodes,source,c.fetch,'f'.repeat(64));await bad.boot;assert(!bad.run('uiReady'));assert(bad.ids.get('localStatus').textContent.includes('FRONTEND_VERSION_MISMATCH'));ok('前后端构建不一致时停止编辑并提示重新打开首页');
  await app.control('faults',{'/api/bootstrap':'null'});const noSession=harness(app.nodes,source,c.fetch,build);await noSession.boot;assert(!noSession.run('uiReady'));assert(noSession.ids.get('localStatus').textContent.includes('INVALID_RESPONSE'));await app.control('faults',{});ok('初始化接口返回空值仍保留可读故障和重试入口');
  other=await server();const c2=client(other.base,c.jar);await c2.fetch('/');assert.equal((await c.fetch('/api/state')).status,200);assert.equal((await c2.fetch('/api/state')).status,200);assert.equal([...c.jar.keys()].filter(k=>k.startsWith('persona_session_')).length,2);ok('两个端口共享 Cookie 容器时互不覆盖管理会话');
  const long=await app.control('large_history');await ui.run('refresh()');await ui.event(ui.make({tag:'button',attrs:{'data-session':long.session},parent:null}));assert.equal((ui.ids.get('sessions').innerHTML.match(/data-session=/g)||[]).length,44);assert.equal(ui.run('messages.length'),2000);assert(!ui.ids.get('loadEarlierMessages').hidden);await ui.click('loadEarlierMessages');assert.equal(ui.run('messages.length'),2010);assert(ui.ids.get('chatLog').innerHTML.includes('合成分页消息 0'));assert(ui.ids.get('loadEarlierMessages').hidden);ok('超过 40 个会话仍可访问，超过 2000 条消息可加载到最早原记录');
  ui.run("showPage('qqPage')");ui.ids.get('socialEnabled').checked=false;ui.ids.get('socialRecipients').value='123';ui.ids.get('socialGroupRecipients').value='';await ui.submit('socialForm');assert.equal(ui.run('state.config.social.recipients[0]'),'private:qq:123');assert(ui.ids.get('socialReadiness').textContent.includes('启用'));ok('未连接 QQ 时可用普通号码保存停用的主动联系草稿');
  ui.ids.get('socialEnabled').checked=true;const postsBefore=(await app.control('stats')).posts.length;await ui.submit('socialForm');assert.equal((await app.control('stats')).posts.length,postsBefore);assert(ui.ids.get('notice').textContent.includes('启用主动联系还需'));ok('启用条件缺失时表单指出具体项，保留输入且不提交无效配置');
  ui.ids.get('qqEnabled').checked=true;ui.ids.get('qqSelfId').value='999';ui.ids.get('qqUsers').value='123';ui.ids.get('qqGroups').value='456';await ui.submit('qqForm');ui.ids.get('socialEnabled').checked=true;ui.ids.get('socialPrivate').checked=true;ui.ids.get('socialGroup').checked=true;ui.ids.get('socialRecipients').value='123';ui.ids.get('socialGroupRecipients').value='456';await ui.submit('socialForm');assert.equal(JSON.stringify(ui.run('state.config.social.recipients')),JSON.stringify(['private:qq:123','group:qq:456']));assert(ui.run('state.config.social.enabled'));assert(ui.ids.get('socialPreviewScope').innerHTML.includes('group:qq:456'));ok('私聊和群聊分别填写普通号码，经实际 HTTP 保存为正确范围');
  ui.ids.get('socialGroupRecipients').value='777';await ui.submit('socialForm');assert(ui.ids.get('notice').textContent.includes('777'));assert.equal(JSON.stringify(ui.run('state.config.qq.allowed_groups')),JSON.stringify(['456']));ok('主动联系表单不会自动扩大 QQ 允许名单');
  await ui.click('newPersona');ui.ids.get('cloneTemplate').checked=true;await ui.event(ui.ids.get('cloneTemplate'),'change');ui.ids.get('newName').value='模板副本';await ui.submit('personaForm');assert.notEqual(ui.run('state.identity.id'),app.first);assert.equal(ui.run('state.profile.name'),'模板副本');assert.equal(ui.run('state.sessions.length'),0);assert(!ui.run('state.config.qq.enabled'));assert(!ui.run('state.config.has_api_key'));ui.ids.get('personaSelect').value=app.first;await ui.event(ui.ids.get('personaSelect'),'change');assert.equal(ui.run('state.identity.id'),app.first);ok('模板克隆表单创建独立身份和空历史，可切回完整原人格');
  const clone=ui.run('state.personas.items.at(-1).id');ui.run("showPage('connections')");assert.equal(ui.ids.get('modelInput').value,'offline-fixture');ui.ids.get('personaSelect').value=clone;await ui.event(ui.ids.get('personaSelect'),'change');assert.equal(ui.ids.get('modelInput').value,'');assert.equal(ui.ids.get('qqUsers').value,'');assert(!ui.ids.get('socialEnabled').checked);ok('停留连接页切换人格时立即换成该人格的表单，防止沿用上一人的连接草稿');
  ui.ids.get('personaSelect').value=app.first;await ui.event(ui.ids.get('personaSelect'),'change');ui.ids.get('modelInput').value='offline-fixture-saved';await ui.submit('settingsForm');assert.equal(ui.run('state.config.model'),'offline-fixture-saved');assert(ui.run('state.config.has_api_key'));ok('模型表单附加请求头留空可正常保存，保留原密钥而不发起模型请求');
  console.log(`${checks} startup / HTTP / structural DOM scenarios passed. Visual browser layout, native Windows and real QQ remain untested.`);
 }finally{if(other)await other.close();await app.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1});
