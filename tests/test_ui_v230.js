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
 const app=await server(),c=client(app.base);let checks=0;const ok=t=>console.log('PASS '+(++checks)+' '+t);let ui;
 try{
  const html=await(await c.fetch('/')).text(),build=html.match(/name="app-build" content="([^"]+)"/)[1],source=await(await c.fetch('/app.js')).text();ui=harness(app.nodes,source,c.fetch,build);await ui.boot;
  assert(ui.run('uiReady'));assert(!ui.ids.get('localStatus').textContent.includes('失败'));ok('分层版本真实 HTTP 启动，所有区域渲染成功');
  assert(ui.ids.get('psychologyPanel').innerHTML.includes('24＋1'));assert(!ui.ids.get('psychologyPanel').innerHTML.includes('affect.label'));assert(ui.ids.get('beqPanel').innerHTML.includes('积极情绪表达'));assert(ui.ids.get('erqPanel').innerHTML.includes('认知重评'));ok('人格页六域/25面向、19价值与 BEQ/ERQ；不再混入当前情绪');
  ui.run("showPage('affectPage')");assert.equal(ui.run('page'),'affectPage');assert(ui.ids.get('currentAffect').innerHTML.includes('主导感'));assert(ui.ids.get('emotionLabels').innerHTML.includes('未知'));assert(ui.ids.get('actualExpression').innerHTML.includes('尚无'));ok('独立情绪页保留未知主导感和标签，未执行计划不显示成已发送');
  const oldIdentity=ui.run('state.identity.id'),oldTraits=JSON.stringify(ui.run('state.profile.psychology.features'));
  ui.ids.get('affectBaseValence').value='-0.2';ui.ids.get('affectTau').value='3600';await ui.submit('affectParametersForm');assert.equal(ui.run('state.affect_state.transition_params.emotion_tau_seconds'),3600);assert.equal(JSON.stringify(ui.run('state.profile.psychology.features')),oldTraits);ok('时间模型表单实际保存参数且不改写人格');
  const current=await(await c.fetch('/api/affect')).json();assert.equal(current.persona_id,oldIdentity);assert.equal(current.affect_state.schema,'trait-affect/1');ok('实时情绪读取使用新协议并带当前主体 ID');
  ui.run("openTraitSeed('erq.expressive_suppression')");ui.ids.get('traitSeedValue').value='.85';await ui.submit('traitSeedForm');assert.equal(ui.run("state.profile.trait_profile.dispositions['erq.expressive_suppression'].estimate"),.85);assert(ui.ids.get('erqPanel').innerHTML.includes('主人设定'));assert.equal(ui.run('state.identity.id'),oldIdentity);ok('ERQ 表单保存 owner_seed；身份和现有历史保留');
  ui.run("showHabitEvidence('erq.expressive_suppression')");assert(ui.ids.get('traceBody').innerHTML.includes('主人设定'));assert(ui.ids.get('traceBody').innerHTML.includes('尚无独立原文证据'));ok('长期习惯来源入口区分主人设定、原文证据和正式量表');
  ui.run("openTraitSeed('beq.positive_expressivity')");ui.ids.get('traitSeedValue').value='';await ui.submit('traitSeedForm');assert.equal(ui.run("state.profile.trait_profile.dispositions['beq.positive_expressivity'].estimate"),null);ok('长期字段空值仍是未知，不转换成 0 或 0.5');
  ui.run("openTraitSeed('hexaco.e.anxiety')");ui.ids.get('traitSeedValue').value='.7';await ui.submit('traitSeedForm');assert.equal(ui.run("state.profile.psychology.features['hexaco.e.anxiety'].estimate"),.7);ok('HEXACO 手动先验可保存，显示主人设定并记录新人格版本');
  ui.run("openTraitSeed('panas.positive_affect')");ui.ids.get('traitSeedValue').value='.6';await ui.submit('traitSeedForm');assert.equal(ui.run("state.profile.trait_profile.dispositions['panas.positive_affect'].estimate"),.6);assert.equal(ui.run('state.affect_state.transition_params.baseline.valence'),-.2);ok('PANAS 总体倾向独立保存，不替代实时 VA 基线');
  const prior=JSON.stringify(ui.run('state.profile.psychology.features'));await ui.click('reviewTraitEvidence');assert.equal(JSON.stringify(ui.run('state.profile.psychology.features')),prior);assert(ui.ids.get('notice').textContent.includes('审查完成'));ok('证据不足的候选不能通过界面审查自动晋升');
  const pack=await(await c.fetch('/api/persona/export')).json();assert.equal(pack.format,'persona-package/2.3');assert.equal(pack.affect_state.schema,'trait-affect/1');assert(pack.learning.checkpoint);ok('新版连续包同时包含学习数据、分层状态与旧列权重');
  ui.run("openTraitSeed('erq.expressive_suppression')");ui.ids.get('personaSelect').value=ui.run('state.personas.items.find(i=>i.id!==state.identity.id).id');await ui.event(ui.ids.get('personaSelect'),'change');assert(!ui.ids.get('traitSeedDialog').open);assert.equal(ui.ids.get('affectBaseValence').value,'0');assert.equal(ui.run("state.profile.trait_profile.dispositions['erq.expressive_suppression'].estimate"),null);ok('切换主体关闭旧设定草稿、同步时间参数、不串情绪/习惯');
  ui.ids.get('personaSelect').value=oldIdentity;await ui.event(ui.ids.get('personaSelect'),'change');assert.equal(ui.ids.get('affectBaseValence').value,'-0.2');assert.equal(ui.run("state.profile.trait_profile.dispositions['erq.expressive_suppression'].estimate"),.85);ok('切回原主体恢复已有长期习惯、个体参数和旧历史');
  await app.control('restart');await ui.run('refresh()');assert.equal(ui.run("state.profile.trait_profile.dispositions['erq.expressive_suppression'].estimate"),.85);assert.equal(ui.run('state.affect_state.transition_params.emotion_tau_seconds'),3600);ok('后端实际重启后新增设定与分层状态持续可用');
  ui.run("state.profile.trait_profile.dispositions['erq.expressive_suppression'].source_type='<script>bad</script>';renderPsychology()");assert(!ui.ids.get('erqPanel').innerHTML.includes('<script>'));ok('新界面来源说明做 HTML 转义');
  console.log(`${checks} new trait/affect HTTP + structural UI scenarios passed. No visual browser or real provider acceptance claimed.`);
 }finally{if(ui)ui.run('stopAffectPolling()');await app.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1});
