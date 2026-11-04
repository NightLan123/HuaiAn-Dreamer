"""Rendered Chromium + actual HTTP/runtime, fake model providers, disposable data."""
import json,sys,tempfile,threading,time,os
from pathlib import Path
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from persona.server import Runtime,Handler
from persona.common import now
from test_v212 import PatchProvider

checks=[]
def check(condition,label):
    assert condition,label
    checks.append(label);print('PASS',label,flush=True)
with tempfile.TemporaryDirectory(prefix='槐安 UI ') as d:
    app=Runtime(d,ROOT);app.configure({'model':'fixture','cognition':{'mode':'baseline'},'pmm':{'mode':'api','api':{'model':'fixture'}}})
    app.engine.provider_factory=PatchProvider;app.engine.pmm_provider_factory=PatchProvider
    sources=[{'id':'demo'+str(i),'speaker':'示范者','text':'听你说完，我再慢慢想。'+str(i),'context':'熟人交谈','source':'imported','timestamp':now()-172800+i*50000,'batch_id':'day'+str(i)} for i in range(4)]
    app.engine.import_records(sources)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.app=app;app.http=server;app.port=server.server_port
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();errors=[];requests=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=os.environ.get('CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1)
            page.on('pageerror',lambda e:errors.append(str(e)));page.on('response',lambda r:requests.append((r.status,r.url)) if r.status>=400 else None);page.on('dialog',lambda dialog:dialog.accept())
            page.goto('http://127.0.0.1:'+str(app.port));page.wait_for_function('uiReady===true');check(page.locator('#localStatus').inner_text().find('失败')<0,'实际网页启动成功')
            page.locator('nav [data-view="affectPage"]').click();check(page.locator('#emotionLabels details').count()==24,'24 类情绪真实 DOM');check('未知' in page.locator('#emotionLabels').inner_text(),'新类别保留未知');check(page.locator('#currentAffect [role=meter]').count()==3,'核心情感与辅助状态分开');check(page.locator('#affectAuxiliary [role=meter]').count()==2,'辅助压力参与可见')
            page.locator('nav [data-view="otherPage"]').click();check(page.locator('#otherPage').is_visible(),'交谈对象为独立主页面')
            page.locator('nav [data-view="learningPage"]').click();page.locator('#learningTarget').select_option('self');page.locator('#learningScopes').select_option('self:imported');page.locator('#learningRange').select_option('all');page.locator('#learningIntent').select_option('review');page.locator('#learningReanalyse').check()
            page.locator('#learningPreviewForm button').click();page.wait_for_function('learningPreview!==null');check('4 条可用原文' in page.locator('#learningPreviewResult').inner_text(),'历史学习预览展示真实原文数量')
            page.locator('#learningCreate').click();page.wait_for_function("state.learning_center.jobs.some(j=>j.status==='awaiting_review')");check(page.locator('#learningJobs [data-learning-action=approve]').count()==1,'候选任务等待审阅')
            j=page.evaluate("state.learning_center.jobs.find(j=>j.status==='awaiting_review').id");page.locator(f'[data-learning-detail="{j}"]').click();check(page.locator('#traceDialog').is_visible(),'任务详情可打开');check('demo0' in page.locator('#traceBody').inner_text(),'任务显示来源 ID');page.locator('#traceDialog').evaluate('(e)=>e.close()')
            page.locator(f'[data-learning-action=approve][data-learning-id="{j}"]').click();
            page.wait_for_function('(id)=>state.learning_center.jobs.find(j=>j.id===id)?.status===\'completed\'',arg=j);check(True,'审阅应用接口落盘')
            page.locator(f'[data-learning-action=rollback][data-learning-id="{j}"]').click();page.wait_for_function('(id)=>state.learning_center.jobs.find(j=>j.id===id)?.status===\'rolled_back\'',arg=j);check(True,'任务回滚通过界面执行')
            page.locator('#lp-strength-other').fill('0');page.locator('#lp-strength-other').dispatch_event('input');check('0%' in page.locator('#lp-value-other').inner_text(),'强度滑条显示数值');page.locator('#learningPolicyForm button[type=submit]').click();page.wait_for_function('state.learning_center.policy.domains.other.strength===0');check(app.engine.learning.status()['policy']['domains']['other']['strength']==0,'学习策略真实保存')
            page.locator('nav [data-view="profiles"]').click();page.locator('#newDynamicBoundary').click();page.locator('#dynamicBoundaryTopic').fill('私人日记需要先了解询问来意');page.locator('#dynamicBoundaryForm button[type=submit]').click();page.wait_for_function("state.boundary_model.boundaries.some(b=>b.topic.includes('私人日记'))");b=page.evaluate("state.boundary_model.boundaries.find(b=>b.topic.includes('私人日记')).boundary_id");check(True,'边界新建入口工作')
            page.locator(f'[data-brm-revoke="{b}"]').click();page.wait_for_function('(id)=>state.boundary_model.boundaries.find(b=>b.boundary_id===id).status===\'revoked\'',arg=b);page.locator('#boundaryFilter').select_option('revoked');page.locator(f'[data-brm-archive="{b}"]').click();page.wait_for_function('(id)=>state.boundary_model.boundaries.find(b=>b.boundary_id===id).archived===true',arg=b);page.locator('#boundaryFilter').select_option('archived');check(page.locator(f'[data-brm-restore="{b}"]').count()==1,'撤销边界可归档与恢复');page.locator(f'[data-brm-restore="{b}"]').click()
            page.locator('#synthesizePersona').click();page.wait_for_function('state.synthesis?.source_record_ids?.length===4');check('仅分析' in page.locator('#synthesisPanel').inner_text(),'整理报告明确未写入人格');page.locator('#synthesisCandidates').click();page.wait_for_function('learningPreview?.body?.source_report_id!=null');check(page.locator('#learningPage').is_visible(),'报告链接到对应原文候选预览')
            with app.engine.lock,app.store.lock,app.store.db:
                for scope,person in [('group:1','qq:1'),('group:1','qq:2'),('group:2','qq:1')]:app.store.session(person,scope);app.engine.social_graph.observe_membership(scope,person,[{'id':scope+person}])
                app.engine.social_graph.apply_claims([{'record_id':'graph1','subject':'qq:1','object':'qq:2','quote':'我和他是朋友','relation_type':'friend','knowledge_type':'self_report','confidence':.7}],[{'id':'graph1','text':'我和他是朋友','person':'qq:1','scope':'group:1'}],'fixture')
            page.evaluate('refresh()');page.locator('nav [data-view="graphPage"]').click();page.locator('#graphScopes').select_option(['group:1','group:2']);page.locator('#graphQueryForm button').click();page.wait_for_function('graphResult?.relation_claims?.length===1');check(page.locator('#graphCanvas svg').count()==1,'人际网络 SVG 由真实图谱数据生成')
            out=ROOT.parent/'v250_browser_artifacts';out.mkdir(exist_ok=True);page.screenshot(path=str(out/'graph-desktop.png'),full_page=True)
            page.locator('nav [data-view="learningPage"]').click();page.screenshot(path=str(out/'learning-desktop.png'),full_page=True)
            page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(out/'learning-mobile.png'),full_page=True);check(page.evaluate('document.documentElement.scrollWidth<=window.innerWidth+2'),'390px 页面无横向溢出')
            check(not errors,'无浏览器运行时错误');check(not requests,'无 HTTP 错误响应');browser.close()
            print(json.dumps({'version':'2.5.0','rendered_chromium':True,'checks':len(checks),'items':checks,'model':'deterministic_fixture','real_provider':False,'live_qq':False},ensure_ascii=False,indent=2))
    finally:server.shutdown();server.server_close();app.close()
