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
  const html=await(await c.fetch('/')).text(),build=html.match(/name="app-build" content="([^\"]+)"/)[1],source=await(await c.fetch('/app.js')).text();ui=harness(app.nodes,source,c.fetch,build);await ui.boot;ui.run('globalThis.window=globalThis;confirm=()=>true');
  assert(ui.run('uiReady'));assert.equal(ui.run('state.version'),'2.8.1');ok('2.5 页面与后端版本一致');
  for(const [p,main] of [['profiles','profiles'],['otherPage','profiles'],['learningPage','distill'],['graphPage','profiles']]){ui.run(`showPage('${p}')`);assert(ui.ids.get(main).classList.contains('active'));if(p!==main)assert(!ui.ids.get(p).hidden);}ok('旧入口迁移到人物和蒸馏子页，数据功能保持可用');
  assert.equal(ui.run('Object.keys(state.emotion_catalog.labels).length'),24);assert.equal((ui.ids.get('emotionLabels').innerHTML.match(/<summary>/g)||[]).length,24);assert(ui.ids.get('emotionTop').innerHTML.includes('未知'));ok('24 类情绪及未知态可见');
  assert.equal((ui.ids.get('currentAffect').innerHTML.match(/role="meter"/g)||[]).length,3);assert.equal((ui.ids.get('affectAuxiliary').innerHTML.match(/role="meter"/g)||[]).length,2);ok('VA/D 与压力参与分区');
  assert(ui.ids.get('learningPolicyFields').innerHTML.includes('lp-strength-social_graph'));assert.equal((ui.ids.get('learningPolicyFields').innerHTML.match(/type="range"/g)||[]).length,6);ok('六个领域各自有模式、权限和强度滑条');
  await app.control('cbm');await ui.run('refresh()');ui.run("showPage('learningPage')");
  ui.ids.get('learningTarget').value='self';ui.ids.get('learningScopes').selectedOptions=[{value:'private:web:owner',selected:true}];ui.ids.get('learningRange').value='all';ui.ids.get('learningIntent').value='review';ui.ids.get('learningReanalyse').checked=true;
  await ui.submit('learningPreviewForm');assert(ui.run('learningPreview.preview.source_count>0'));assert(ui.ids.get('learningPreviewResult').innerHTML.includes('条可用原文'));ok('历史预览表单从真实 HTTP 查询已存原文');
  const before=ui.run('JSON.stringify(state.profile)'),checkpoint=ui.run('state.model.checkpoint_sha256');await ui.click('learningCreate');assert.equal(ui.run('state.learning_center.jobs[0].status'),'awaiting_review');assert.equal(ui.run('JSON.stringify(state.profile)'),before);assert.equal(ui.run('state.model.checkpoint_sha256'),checkpoint);assert(!ui.ids.get('sendBtn').disabled);ok('任务保存候选，未审批不改人格或权重，聊天按钮可用');
  const id=ui.run('state.learning_center.jobs[0].id');assert(ui.ids.get('operationReceipt').innerHTML.includes('data-learning-detail="'+id+'"'));await ui.event(ui.make({tag:'button',attrs:{'data-learning-detail':id},parent:null}));assert(ui.ids.get('traceDialog').open);assert(ui.ids.get('traceBody').innerHTML.includes('原文'));ok('任务详情显示候选与原文');ui.ids.get('traceDialog').close();
  await ui.event(ui.make({tag:'button',attrs:{'data-learning-action':'approve','data-learning-id':id},parent:null}));assert.equal(ui.run(`state.learning_center.jobs.find(j=>j.id==='${id}').status`),'completed');assert(ui.ids.get('learningJobs').innerHTML.includes('回滚本任务写入'));ok('审阅按钮提交并展示可回滚状态');
  await ui.event(ui.make({tag:'button',attrs:{'data-learning-action':'rollback','data-learning-id':id},parent:null}));assert.equal(ui.run(`state.learning_center.jobs.find(j=>j.id==='${id}').status`),'rolled_back');assert.equal(ui.run('JSON.stringify(state.profile)'),before);ok('界面回滚保留原始资料并恢复任务前人格');
  await ui.run("api('/api/learning/policy',{persona_id:state.identity.id,expected_version:state.learning_center.policy.version,policy:{...state.learning_center.policy,domains:{...state.learning_center.policy.domains,other:{...state.learning_center.policy.domains.other,strength:0}}}})");await ui.run('refresh()');assert(ui.ids.get('learningPolicyFields').innerHTML.includes('lp-value-other">0%'));ok('保存后的独立 0% 强度反映在界面');
  await ui.run("api('/api/boundaries/edit',{topic:'界面归档测试',domain:'disclosure'})");await ui.run('refresh()');const bid=ui.run("state.boundary_model.boundaries.find(b=>b.topic==='界面归档测试').boundary_id");
  await ui.event(ui.make({tag:'button',attrs:{'data-brm-revoke':bid},parent:null}));await ui.event(ui.make({tag:'button',attrs:{'data-brm-archive':bid},parent:null}));ui.ids.get('boundaryFilter').value='archived';ui.run('renderBoundaryModel()');assert(ui.ids.get('dynamicBoundaryList').innerHTML.includes('恢复'));await ui.event(ui.make({tag:'button',attrs:{'data-brm-restore':bid},parent:null}));assert.equal(ui.run(`state.boundary_model.boundaries.find(b=>b.boundary_id==='${bid}').archived`),false);ok('边界撤销、归档、恢复完整连接后端');
  await ui.run('loadBoundaryHistory(true)');assert(ui.ids.get('boundaryHistoryCount').textContent.includes('回合'));ok('历史分页从持续事件记录读取');
  const s=await ui.run("(async()=>runJob(await api('/api/persona/synthesize',{}),'synthesize'))()");assert(s.source_record_ids.length);assert(ui.ids.get('synthesisPanel').innerHTML.includes('未应用'));ok('整理报告列出来源并标明未应用');
  ui.ids.get('learningScopes').options=[{value:'private:web:owner',selected:false}];ui.ids.get('learningScopes').selectedOptions=ui.ids.get('learningScopes').options;await ui.click('synthesisCandidates');assert(ui.run('learningPreview.body.source_report_id===state.synthesis.id'));assert(ui.ids.get('learningPreviewResult').innerHTML.includes('条可用原文'));ok('整理报告按钮建立对应原文预览，不直接学习报告文字');
  ui.ids.get('graphScopes').selectedOptions=[{value:'group:fixture',selected:true}];await ui.submit('graphQueryForm');assert.equal(ui.run('graphResult.relation_claims.length'),0);assert(ui.ids.get('graphCanvas').innerHTML.includes('暂无'));ok('没有图谱证据时保持空态，不编造好友关系');
  const pack=await(await c.fetch('/api/persona/export')).json();assert(pack.learning_center&&pack.learning_policy);assert(pack.learning_center.jobs.some(j=>j.id===id));ok('连续人格包包含持久学习任务及策略');
  await app.control('restart');await ui.run('refresh()');assert.equal(ui.run(`state.learning_center.jobs.find(j=>j.id==='${id}').status`),'rolled_back');ok('实际后端重启后任务状态可继续查看');
  console.log(`${checks} v2.5 HTTP and structural DOM scenarios passed; rendered browser unavailable.`);
 }finally{if(ui)ui.run('stopAffectPolling()');await app.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1});
