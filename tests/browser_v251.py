"""Rendered UI acceptance on disposable data. No real models/accounts or production DB.

Install the optional Playwright test dependency and its Chromium browser first.
Run: PYTHONPATH=.:tests python tests/browser_v251.py
Optional: CHROMIUM_PATH selects an already installed browser executable.
Screenshots contain synthetic fixtures only; a successful launch is required.
"""
import json,os,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from persona.server import Runtime,Handler
from persona.common import now
from test_v212 import PatchProvider

def main():
    checks=[];errors=[];failed=[]
    def check(condition,label):
        assert condition,label
        checks.append(label);print('PASS',label,flush=True)
    with tempfile.TemporaryDirectory(prefix='huai-an-ui-') as d:
        app=Runtime(d,ROOT);app.configure({'model':'fixture','cognition':{'mode':'baseline'},'pmm':{'mode':'api','api':{'model':'fixture'}}})
        app.engine.provider_factory=PatchProvider;app.engine.pmm_provider_factory=PatchProvider
        records=[{'id':'demo'+str(i),'speaker':'示范者','text':'听你说完，我再慢慢想。'+str(i),'context':'熟人交谈','source':'imported','timestamp':now()-172800+i*50000,'batch_id':'day'+str(i)} for i in range(4)]
        app.engine.import_records(records)
        app.engine.edit_disposition({'persona_id':app.engine.profile()['id'],'feature_id':'hexaco.h.sincerity','estimate':.72,'source_type':'owner_seed','timeframe':'habitual','expected_version':app.engine.profile()['trait_profile']['version'],'note':'合成视觉验收'})
        app.engine.boundaries.edit({'topic':'谈私事前说明询问来意','domain':'disclosure'})
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.app=app;app.http=server;app.port=server.server_port;threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with sync_playwright() as pw:
                opts={'headless':True}
                if os.environ.get('CHROMIUM_PATH'):opts['executable_path']=os.environ['CHROMIUM_PATH']
                browser=pw.chromium.launch(**opts);context=browser.new_context(viewport={'width':1440,'height':1000},device_scale_factor=1);page=context.new_page()
                page.on('pageerror',lambda e:errors.append(str(e)));page.on('response',lambda r:failed.append((r.status,r.url)) if r.status>=400 else None);page.on('dialog',lambda dialog:dialog.accept())
                page.goto('http://127.0.0.1:'+str(app.port));page.wait_for_function('uiReady===true');check('失败' not in page.locator('#localStatus').inner_text(),'启动无组件渲染失败')
                out=ROOT.parent/'v251_browser_artifacts';out.mkdir(exist_ok=True)
                names=['对话','人物','情绪','语言习惯','记忆','蒸馏','模型设置','QQ 设置','后台诊断记录','数据与版本']
                check(page.locator('nav [data-view]').all_text_contents()==names,'十个指定一级入口')
                for view in page.locator('nav [data-view]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.view)'):
                    page.locator(f'nav [data-view="{view}"]').click();check(page.locator('#'+view).is_visible(),'主页面 '+view)
                    page.screenshot(path=str(out/(view+'-desktop.png')),full_page=True)
                    tabs=page.locator(f'#{view} [role=tab]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.tab)')
                    for tab in tabs:
                        page.locator(f'[data-tab="{tab}"]').click();check(page.locator('#'+tab).is_visible(),'子视图 '+tab)
                        check(page.locator(f'#{view} [role=tabpanel]:visible').count()==1,'仅显示一个子视图 '+tab)
                        page.screenshot(path=str(out/(tab+'-desktop.png')),full_page=True)
                page.locator('nav [data-view=profiles]').click();page.locator('[data-tab=profiles-self]').click();page.locator('[data-disclosure=hexaco-h]').evaluate('(n)=>n.open=true')
                colors=page.evaluate("({estimate:getComputedStyle(document.querySelector('.metric-estimate .fill')).backgroundColor,uncertainty:getComputedStyle(document.querySelector('.metric-uncertainty .fill')).backgroundColor})")
                check(colors['estimate']!=colors['uncertainty'],'主估计与工程不确定性颜色不同')
                page.locator('[data-tab=profiles-self]').focus();page.keyboard.press('End');check(page.locator('#graphPage').is_visible(),'键盘 End 切换最后子页');page.keyboard.press('Home');check(page.locator('#profiles-settings').is_visible(),'键盘 Home 返回首子页')
                page.locator('nav [data-view=connections]').click();page.locator('[data-tab=connections-panel-general]').click();page.locator('#modelInput').fill('未保存的测试模型');page.locator('nav [data-view=memory]').click();page.locator('nav [data-view=connections]').click();check(page.locator('#modelInput').input_value()=='未保存的测试模型','切页保留表单草稿')
                page.evaluate('refresh()');page.wait_for_function('uiReady');check(page.locator('#modelInput').input_value()=='未保存的测试模型','后台刷新保留表单草稿')
                page.evaluate("showPage('profiles','profiles-boundaries')");bid=page.evaluate("state.boundary_model.boundaries[0].boundary_id")
                page.locator(f'[data-brm-revoke="{bid}"]').click();page.wait_for_function('(id)=>state.boundary_model.boundaries.find(b=>b.boundary_id===id).status===\'revoked\'',arg=bid)
                page.locator('#boundaryFilter').select_option('revoked');page.locator(f'[data-brm-archive="{bid}"]').click();page.wait_for_function('(id)=>state.boundary_model.boundaries.find(b=>b.boundary_id===id).archived===true',arg=bid)
                page.locator('#boundaryFilter').select_option('archived');page.locator(f'[data-brm-restore="{bid}"]').click();check(True,'边界归档恢复可点击')
                page.evaluate("showPage('distill','distill-manual')");page.locator('#learningScopes').select_option('self:imported');page.locator('#learningRange').select_option('all');page.locator('#learningReanalyse').check();page.locator('#learningPreviewForm button').click();page.wait_for_function('learningPreview!==null');check('4 条可用原文' in page.locator('#learningPreviewResult').inner_text(),'同一学习任务来源预览')
                page.locator('#learningCreate').click();page.wait_for_function("state.learning_center.jobs.some(j=>j.status==='awaiting_review')");page.evaluate("showPage('distill','learningPage')")
                j=page.evaluate("state.learning_center.jobs.find(j=>j.status==='awaiting_review').id");page.locator(f'[data-learning-detail="{j}"]').click();check(page.locator('#traceDialog').is_visible(),'任务详情');page.locator('#traceDialog [data-close]').click()
                page.locator(f'[data-learning-action=approve][data-learning-id="{j}"]').click();page.wait_for_function('(id)=>state.learning_center.jobs.find(j=>j.id===id)?.status===\'completed\'',arg=j)
                page.locator(f'[data-learning-action=rollback][data-learning-id="{j}"]').click();page.wait_for_function('(id)=>state.learning_center.jobs.find(j=>j.id===id)?.status===\'rolled_back\'',arg=j);check(True,'学习审批与回滚')
                page.set_viewport_size({'width':390,'height':844})
                for view in page.locator('nav [data-view]').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.view)'):
                    page.locator(f'nav [data-view="{view}"]').click();check(page.evaluate('document.documentElement.scrollWidth<=innerWidth+2'),'390px 无整页横向溢出 '+view);page.screenshot(path=str(out/(view+'-mobile.png')),full_page=True)
                check(not errors,'无 JS 运行时错误');check(not failed,'无非预期 HTTP 错误');browser.close()
                result={'version':'2.5.1','rendered_browser':True,'checks':len(checks),'items':checks,'synthetic_data':True,'real_provider':False,'real_qq':False}
                (out/'browser-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False,indent=2))
        finally:server.shutdown();server.server_close();app.close()
if __name__=='__main__':main()
