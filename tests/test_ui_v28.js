'use strict';
// Actual loopback HTTP + shipped app.js; structural DOM, not visual browser E2E.
const assert=require('node:assert/strict'),{server,client}=require('./test_ui_v251'),{harness}=require('./dom_harness_v222');
async function main(){const app=await server(),c=client(app.base);let ui,count=0;const ok=s=>console.log('PASS '+(++count)+' '+s);
 try{
  const html=await(await c.fetch('/')).text(),build=html.match(/name="app-build" content="([^\"]+)"/)[1];
  ui=harness(app.nodes,await(await c.fetch('/app.js')).text(),c.fetch,build);await ui.boot;
  assert(ui.run('uiReady'));assert.equal(ui.all.filter(n=>n.classList.contains('page')).length,11);ok('原十个页面及独立模型训练页启动');
  assert.equal(ui.ids.get('pmm281Form').closest('.page').id,'connections');assert.equal(ui.ids.get('pmm28Components').closest('.page').id,'diagnostics');ok('协同设置和组件记录位于现有入口');
  ui.run("showPage('connections','connections-panel-pmm')");ui.ids.get('pmmApplication281').value='full';ui.ids.get('bPolicy281').value='always';await ui.submit('pmm281Form');assert.equal(ui.run('state.config.pmm281.mode'),'full');assert.equal(ui.run('state.config.pmm281.b_policy'),'always');ok('协同模式独立保存且长期更新仍为候选');
  const out=await app.control('cbm');await ui.run('refreshPmm28()');const trace=ui.run('pmm28Traces[0]');assert(trace.components.neural.executed);assert.equal(trace.mode,'full');assert(!trace.components.neural.payload.formal_eligible);ok('实际回合执行神经计算且未校准预测不取得权限');
  assert(ui.ids.get('pmm28Components').innerHTML.includes('人格神经计算'));assert(ui.ids.get('pmm28Coverage').innerHTML.includes('<progress'));assert(ui.ids.get('pmm28Readiness').textContent.includes('未校准'));ok('组件路径、未知构念完整度与门禁可见');
  await ui.event(ui.ids.get('pmm28Ablate'));assert(ui.ids.get('pmm28AblationResult').innerHTML.includes('未重新调用 API'));assert(ui.ids.get('pmm28AblationResult').innerHTML.includes('relationship'));ok('六组件消融从真实回合运行并标注实验边界');
  await assert.rejects(ui.run("api('/api/pmm28/models',{op:'publish',subject_id:state.identity.id,expected_revision:0,version:'missing'})"),/模型版本不存在/);await assert.rejects(ui.run("api('/api/pmm28/longitudinal',{op:'commit',subject_id:state.identity.id,expected_revision:0,proposal_id:'missing'})"));ok('伪发布及无证据长期提交被后端拒绝');
  ui.run("showPage('connections','connections-panel-pmm')");ui.ids.get('pmmApplication281').value='compatibility';await ui.submit('pmm281Form');assert.equal(ui.run('state.config.pmm281.mode'),'compatibility');const history=await ui.run("api('/api/messages?session='+encodeURIComponent(state.sessions[0].id))");assert(history.length>0);ok('退回 Legacy 后已确认交互仍在');
  const outsider=await fetch(app.base+'/api/pmm28/traces');assert.equal(outsider.status,401);assert(!c.requests.some(r=>r.status>=500));ok('诊断需要本地授权会话且无服务端 500');
  console.log(`${count} v2.8 HTTP / structural DOM scenarios passed.`);
 }finally{if(ui)ui.run('stopAffectPolling()');await app.close();}
}
if(require.main===module)main().catch(e=>{console.error(e);process.exitCode=1});
module.exports={main};
