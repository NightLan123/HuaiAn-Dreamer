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
 const app=await server(),c=client(app.base);let ui,checks=0;const ok=t=>console.log('PASS '+(++checks)+' '+t);
 try{
  const html=await(await c.fetch('/')).text(),build=html.match(/name="app-build" content="([^\"]+)"/)[1],source=await(await c.fetch('/app.js')).text();ui=harness(app.nodes,source,c.fetch,build);await ui.boot;
  assert(ui.run('uiReady'));assert.equal(ui.run('state.version'),'2.8.1');assert(!ui.ids.get('localStatus').textContent.includes('失败'));ok('2.6 实际 HTTP 启动，全部初始区域渲染成功');
  const nav=ui.all.filter(n=>n.dataset.view&&n.closest('nav'));assert.deepEqual(nav.map(n=>n.dataset.view),['chat','profiles','affectPage','expressionPage','memory','distill','connections','modelTraining','qqPage','diagnostics','research']);assert.equal(ui.all.filter(n=>n.classList.contains('page')).length,11);ok('十一个一级入口及对应页面容器');
  for(const n of nav){await ui.event(n);assert.equal(ui.run('page'),n.dataset.view);assert.equal(ui.all.filter(n=>n.classList.contains('page')&&n.classList.contains('active')).length,1);}
  for(const tab of ui.all.filter(n=>n.attrs.role==='tab')){const p=tab.closest('.page');ui.run(`showPage('${p.id}')`);await ui.event(tab);assert(!ui.ids.get(tab.dataset.tab).hidden);assert.equal(tab.attrs['aria-selected'],'true');assert.equal(p.querySelectorAll('[role="tabpanel"]').filter(n=>!n.hidden).length,1);}
  ok('每个主页面与全部子视图实际点击，无空 DOM 初始化或切页异常');
  for(const [old,view,tab] of [['otherPage','profiles','otherPage'],['graphPage','profiles','graphPage'],['learningPage','distill','learningPage'],['mediaPage','qqPage','qqPage-panel-incoming']]){ui.run(`showPage('${old}')`);assert.equal(ui.run('page'),view);assert(!ui.ids.get(tab).hidden);}ok('旧入口分别迁移到人物、蒸馏与 QQ 收件机制');
  for(const [id,page] of [['stylePanel','expressionPage'],['pragmaticProfile','expressionPage'],['actualExpression','expressionPage'],['expressionPanel','expressionPage'],['learningPolicyForm','distill'],['sourceText','distill'],['graphQueryForm','profiles'],['mediaConfigForm','qqPage']])assert.equal(ui.ids.get(id).closest('.page').id,page);
  for(const id of ['mediaPage','assetForm','mediaSend','mediaPreferenceForm','mediaFeedbackForm'])assert(!ui.ids.has(id));assert(!/refreshMedia|operationMedia|allowed_assets|data-asset-delete/.test(source));ok('语言与蒸馏使用原数据控件，图库控件及调用全部移除');
  const tabs=ui.ids.get('profiles').querySelectorAll('[role="tab"]');ui.run("showPage('profiles')");await ui.event(tabs[0],'keydown',{key:'End'});assert.equal(ui.document.activeElement,tabs.at(-1));assert(!ui.ids.get('graphPage').hidden);await ui.event(tabs.at(-1),'keydown',{key:'Home'});assert.equal(ui.document.activeElement,tabs[0]);ok('ARIA tabs 的 Home/End 键切换与焦点正常');
  ui.run("showPage('connections')");ui.ids.get('modelInput').value='未提交的模型草稿';await ui.event(ui.ids.get('modelInput'),'input');ui.run("showPage('memory');showPage('connections')");assert.equal(ui.ids.get('modelInput').value,'未提交的模型草稿');await ui.run('refresh()');assert.equal(ui.ids.get('modelInput').value,'未提交的模型草稿');assert(!ui.ids.get('draftStatus').hidden);ok('连接草稿在切页与实际后台刷新后保留，并有未提交提示');
  const first=ui.run('state.identity.id');ui.ids.get('personaSelect').value=app.second;await ui.event(ui.ids.get('personaSelect'),'change');assert.notEqual(ui.ids.get('modelInput').value,'未提交的模型草稿');ui.ids.get('personaSelect').value=first;await ui.event(ui.ids.get('personaSelect'),'change');assert.equal(ui.ids.get('modelInput').value,'未提交的模型草稿');ok('草稿按主体隔离，切回原主体可恢复');
  const form=ui.ids.get('modelInput').closest('form');await ui.submit(form.id);assert.equal(ui.run('state.config.model'),'未提交的模型草稿');assert.equal(ui.run(`formDrafts.has(draftKey('${form.id}'))`),false);assert(!ui.ids.get('operationReceipt').hidden);assert(ui.ids.get('operationReceipt').innerHTML.includes('查看结果'));ok('保存真实配置后清除草稿，并显示结果位置');
  ui.run("showPage('distill','distill-import')");ui.ids.get('sourceText').value='资料甲：尚未提交\n资料乙：测试';await ui.event(ui.ids.get('sourceText'),'input');ui.run("showPage('affectPage');showPage('distill','distill-import')");assert.equal(ui.ids.get('sourceText').value,'资料甲：尚未提交\n资料乙：测试');ok('导入原文切页后仍保留，不意外提交学习');
  ui.run("showPage('profiles','profiles-self')");const before=ui.run('JSON.stringify(state.profile)');assert(ui.ids.get('psychologyPanel').innerHTML.includes('0/4 面向有估计'));assert(!ui.ids.get('psychologyPanel').innerHTML.includes('aria-valuenow="0"'));assert.equal(ui.run('JSON.stringify(state.profile)'),before);ok('未知人格不伪装成零分，部分面向汇总明确标识完整度');
  await ui.run("api('/api/traits/disposition',{persona_id:state.identity.id,feature_id:'hexaco.h.sincerity',expected_version:state.profile.trait_profile.version,estimate:.72,source_type:'owner_seed',timeframe:'habitual',note:'UI fixture'})");await ui.run('refresh()');
  const traits=ui.ids.get('psychologyPanel').innerHTML;assert(traits.includes('metric-estimate'));assert(traits.includes('metric-uncertainty'));assert(traits.includes('0.720'));assert(traits.includes('1/4 面向有估计'));assert(traits.includes('owner_seed'));assert(traits.includes('更新时间')||traits.includes('2026'));
  assert.equal(ui.run("sourceName('inferred')"),'历史工程推断（尚未按现行标准复核）');ok('已知值、不确定性与来源分开显示，未复核历史来源不改写');
  const feature=ui.make({tag:'button',attrs:{'data-feature':'hexaco.h.sincerity','data-profile':ui.run('state.profile.id')},parent:null});await ui.event(feature);assert(ui.ids.get('traceBody').innerHTML.includes('原始字段记录'));assert(ui.ids.get('traceBody').innerHTML.includes('owner_seed'));ui.ids.get('traceDialog').close();assert.equal(ui.document.activeElement,feature);ok('来源详情保留原始记录，关闭后焦点返回原按钮');
  ui.run("showPage('qqPage','qqPage-panel-incoming')");ui.ids.get('mediaReceive').checked=false;ui.ids.get('visionModel').value='vision-fixture';await ui.submit('mediaConfigForm');assert.equal(ui.run('state.config.media.receive'),false);assert.equal(ui.run('state.config.media.vision_model'),'vision-fixture');ok('QQ 收图设置在新入口真实保存，独立于已移除图库');
  const old=ui.run('JSON.stringify(state.config)');for(const url of ['/api/media','/api/media/preferences','/api/media/image/old']){await assert.rejects(ui.run(`api('${url}')`),/FEATURE_REMOVED/);await assert.rejects(ui.run(`api('${url}',{op:'delete',id:'old'})`),/FEATURE_REMOVED/);}await ui.run('refresh()');assert.equal(ui.run('JSON.stringify(state.config)'),old);ok('六种旧图库 GET/POST 请求明确返回 410，配置不变');
  const archive=await c.fetch('/api/export/legacy-media');assert.equal(archive.status,200);assert.equal(archive.headers.get('content-type'),'application/zip');assert((await archive.arrayBuffer()).byteLength>100);ok('历史图片原文件可从数据与版本独立导出');
  assert(ui.ids.get('affectAppraisals').innerHTML.includes('事件评价'));assert(ui.ids.get('affectRegulations').innerHTML.includes('情绪调节'));assert.equal(ui.ids.get('actualExpression').closest('.page').id,'expressionPage');ok('情绪事件与调节保留原始记录，表达主视图集中到语言习惯');
  assert(!c.requests.some(r=>/\/api\/media/.test(r.path)&&r.status<400));assert(!c.requests.some(r=>r.status>=500));ok('遍历所有入口没有图库成功请求或服务端 500');
  console.log(`${checks} v2.6 HTTP and structural DOM scenarios passed; rendered browser separately reported.`);
 }finally{if(ui)ui.run('stopAffectPolling()');await app.close();}
}
module.exports={server,client};
if(require.main===module)main().catch(e=>{console.error(e);process.exitCode=1});

