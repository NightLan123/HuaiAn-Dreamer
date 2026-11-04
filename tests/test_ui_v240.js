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
 const app=await server(),c=client(app.base);let checks=0,ui;const ok=t=>console.log('PASS '+(++checks)+' '+t);
 try{
  const html=await(await c.fetch('/')).text(),build=html.match(/name="app-build" content="([^"]+)"/)[1],source=await(await c.fetch('/app.js')).text();ui=harness(app.nodes,source,c.fetch,build);await ui.boot;
  assert(ui.run('uiReady'));assert(!ui.ids.get('localStatus').textContent.includes('失败'));ok('2.4.0 真实 HTTP 启动与新表达页渲染');
  ui.run("showPage('expressionPage')");assert.equal(ui.run('page'),'expressionPage');assert(ui.ids.get('pragmaticProfile').innerHTML.includes('role="meter"'));assert(ui.ids.get('pragmaticProfile').innerHTML.includes('未知'));ok('独立表达倾向页保留未知，未伪造训练结果');
  for(const id of ['psychologyPanel','beqPanel','erqPanel','panasPanel'])assert(ui.ids.get(id).innerHTML.includes('未知')||ui.ids.get(id).innerHTML.includes('尚无'),id);for(const id of ['currentAffect','moodPanel','emotionLabels'])assert(ui.ids.get(id).innerHTML.includes('role="meter"'),id);ok('未知人格字段不绘制误导分数，情绪仍使用数值条');
  const unknown=ui.run("meter('未知测试',null)");assert(!unknown.includes('aria-valuenow'));assert(unknown.includes('未知'));assert(unknown.includes('width:0%'));ok('未知值不伪装成零或中点');
  const zero=ui.run("meter('零',0)");assert(zero.includes('aria-valuenow="0"'));assert(zero.includes('0.000'));ok('真实零值与未知明确区分');
  const negative=ui.run("meter('效价',-.6,1,true)");assert(negative.includes('aria-valuemin="-1"'));assert(negative.includes('zero-marker'));assert(negative.includes('left:20%'));assert(negative.includes('width:30%'));ok('双极效价从零点显示负向范围');
  const malicious=ui.run("meter('<img src=x onerror=bad>',.7)");assert(!malicious.includes('<img'));assert(malicious.includes('&lt;img'));ok('数值标签及可访问名称转义');
  const flow=await app.control('cbm');await ui.run('refresh()');assert.equal(flow.parts.length,3);assert(ui.ids.get('expressionPlans').innerHTML.includes('实际 3 条'));assert(ui.ids.get('expressionStatus').textContent.includes('1 个独立示范事件'));ok('真实引擎夹具产生三气泡，四条人类示范只计一个事件');
  assert(ui.ids.get('pragmaticOriginal').textContent.includes('target'));assert(!ui.ids.get('savePragmaticAnnotation').disabled);ok('标注界面可追溯导入的人类原话');
  const prior=JSON.stringify(ui.run('state.profile.trait_profile'));ui.ids.get('pragmaticField').value='topic_progression_tendency';ui.ids.get('pragmaticValue').value='.7';ui.ids.get('pragmaticNote').value='独立示范中的人工判断';await ui.submit('pragmaticAnnotationForm');assert.equal(ui.run("state.pragmatics.profile.fields.topic_progression_tendency.estimate"),.7);assert.equal(JSON.stringify(ui.run('state.profile.trait_profile')),prior);ok('人工语用标注通过真实接口保存，不改长期人格');
  ui.ids.get('pragmaticField').value='topic_progression_tendency';ui.ids.get('pragmaticValue').value='.6';await ui.submit('pragmaticAnnotationForm');assert.equal(ui.run("state.pragmatics.profile.fields.topic_progression_tendency.effective_episodes"),1);ok('同一事件修订不增加独立样本量');
  const button=ui.make({tag:'button',attrs:{'data-expression-index':'0'},parent:null});await ui.event(button);assert(ui.ids.get('traceBody').innerHTML.includes('分条依据'));assert(ui.ids.get('traceBody').innerHTML.includes('追问'));ok('后台详情显示分条、追问、停止依据与实际结果');
  await app.control('restart');await ui.run('refresh()');assert.equal(ui.run("state.pragmatics.profile.fields.topic_progression_tendency.estimate"),.6);ok('重启保留表达倾向和人工修订');
  const pack=await(await c.fetch('/api/persona/export')).json();assert(pack.pragmatics);assert.equal(pack.pragmatics.annotations.length,1);ok('连续人格包含新语用证据，旧权重接口仍在');
  console.log(`${checks} CBM HTTP / structural DOM checks passed; no visual-browser claim.`);
 }finally{if(ui)ui.run('stopAffectPolling()');await app.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1});
