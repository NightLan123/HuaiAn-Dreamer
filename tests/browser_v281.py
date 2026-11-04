"""Real Chromium, application HTTP server and two independent loopback model APIs."""
import json,sys,tempfile,threading,time
from pathlib import Path
from http.server import ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from persona.server import Handler
from test_v281_connections import Connections
from test_v281_affect import dataset
from playwright.sync_api import sync_playwright,expect
OUT=ROOT/'reports/v281/stage3';OUT.mkdir(parents=True,exist_ok=True)
x=Connections();x.setUp();app=x.r;http=ThreadingHTTPServer(('127.0.0.1',0),Handler);http.app=app;app.port=http.server_port;app.http=http
thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start();checks=[];errors=[];finished=False
def check(name,value):
    checks.append({'name':name,'passed':bool(value)})
    if not value:raise AssertionError(name)
try:
    sid=app.store.session();app.engine.turn(sid,'一个用于界面验收的合成事件。')
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1440,'height':1050},device_scale_factor=1)
        page.on('pageerror',lambda e:errors.append(str(e)));page.on('dialog',lambda d:d.dismiss())
        page.goto('http://127.0.0.1:'+str(http.server_port));expect(page.locator('#localStatus')).to_contain_text('本地数据已连接')
        page.click('nav [data-view="connections"]');page.click('#connections-tab-pmm');expect(page.locator('#pmmRunSummary281')).to_contain_text('正式回合')
        check('only one application mode',page.locator('#pmmApplication281').is_visible());check('default full',page.input_value('#pmmApplication281')=='full');check('compat hidden',not page.locator('#pmmForm').is_visible())
        check('two actual connections',page.input_value('#AModel281')=='A-http' and page.input_value('#BModel281')=='B-http')
        page.click('[data-probe="A:invoke"]');expect(page.locator('#AResult281')).to_contain_text('任务调用通过')
        page.click('[data-probe="B:invoke"]');expect(page.locator('#BResult281')).to_contain_text('任务调用通过')
        check('independent task tests',True)
        page.locator('#pmmApplication281').scroll_into_view_if_needed();page.screenshot(path=str(OUT/'pmm_settings_desktop.png'))
        before=app.store.meta('pmm281_affect');page.fill('#pmmTestEvent281','我想认真讨论一下今天的计划。');page.click('#preview281')
        expect(page.locator('#previewStatus281')).to_contain_text('整轮测试已完成',timeout=60000)
        check('preview no formal state changes',before==app.store.meta('pmm281_affect'));check('eight workflow components',page.locator('#workflow281 .workflow-node281').count()==8)
        check('actual previews reach B',page.locator('#workflow281').inner_text().count('本轮执行')>=7)
        page.locator('#workflow281').scroll_into_view_if_needed();page.screenshot(path=str(OUT/'pmm_runtime_desktop.png'))
        page.locator('#emotionDynamics281').scroll_into_view_if_needed();page.screenshot(path=str(OUT/'emotion_desktop.png'))
        page.select_option('#pmmApplication281','compatibility');check('compat visible after selection',page.locator('#pmmForm').is_visible());
        with page.expect_response(lambda r:r.url.endswith('/api/config') and r.request.method=='POST'):page.click('#pmm281Form button[type="submit"]')
        expect(page.locator('#pmmSave281')).to_contain_text('已保存：备用兼容模式');check('compat persisted',app.config.get()['pmm281']['mode']=='compatibility')
        page.select_option('#pmmApplication281','full');page.click('#pmm281Form button[type="submit"]');expect(page.locator('#pmmSave281')).to_contain_text('已保存：完整 PMM');expect(page.locator('#pmmForm')).to_be_hidden();check('switch retains both connections',app.config.get()['pmm281']['b_api']['model']=='B-http')
        page.click('nav [data-view="modelTraining"]');expect(page.locator('#affectTrainSummary')).to_contain_text('个数据集')
        check('separate training page',page.locator('#affectTrain281').is_visible() and page.locator('#pmm28TrainForm').is_visible())
        data=dataset(app.engine.profile()['id'],count=12);page.set_input_files('#affectDataset281',{'name':'synthetic_supervision.json','mimeType':'application/json','buffer':json.dumps(data).encode()})
        page.click('#affectImport281 button');expect(page.locator('#affectTrainSummary')).to_contain_text('1 个数据集')
        page.fill('#affectEpochs281','2');page.click('#affectTrain281 button');expect(page.locator('#affectVersion281 option').filter(has_text='2 步')).to_have_count(1,timeout=60000)
        check('real gradient job from UI',True);page.screenshot(path=str(OUT/'training_desktop.png'))
        page.set_viewport_size({'width':390,'height':844});page.click('nav [data-view="connections"]');page.click('#connections-tab-pmm')
        check('mobile no horizontal overflow',page.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1'))
        page.locator('#pmmApplication281').scroll_into_view_if_needed();page.screenshot(path=str(OUT/'pmm_mobile.png'))
        check('no browser JS errors',not errors)
        browser.close();finished=True
finally:
    result={'checks':checks,'passed':finished and bool(checks) and all(c['passed'] for c in checks) and not errors,'javascript_errors':errors,'browser':'system Chromium 155','transport':'real HTTP to loopback model fixtures; not cloud/Qwen validation'}
    (OUT/'browser_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));http.shutdown();http.server_close();thread.join();x.tearDown()
print(json.dumps(result,ensure_ascii=False))
