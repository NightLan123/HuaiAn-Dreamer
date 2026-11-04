"""Optional actual Chromium acceptance with synthetic data only; no screenshots uploaded."""
import os,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from persona.server import Runtime,Handler
from test_de_gate2 import ControlledProvider,TEXT

def main():
    with tempfile.TemporaryDirectory() as d:
        app=Runtime(d,ROOT);app.engine.provider_factory=ControlledProvider;app.engine.pmm_provider_factory=ControlledProvider
        sid=app.store.session();turns=[app.engine.turn(sid,TEXT)['turn_id'] for _ in range(2)];h=ThreadingHTTPServer(('127.0.0.1',0),Handler);h.app=app;app.http=h;app.port=h.server_port;threading.Thread(target=h.serve_forever,daemon=True).start()
        try:
            with sync_playwright() as w:
                opts={'executable_path':os.environ['CHROMIUM_PATH']} if os.environ.get('CHROMIUM_PATH') else {};b=w.chromium.launch(headless=True,**opts);page=b.new_page(viewport={'width':1280,'height':900});errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.goto('http://127.0.0.1:'+str(app.port));page.wait_for_function('uiReady===true');page.locator('nav [data-view="expressionPage"]').click();page.locator('[data-tab="language-actual"]').click()
                for tid in turns:
                    page.locator('#deTargetTurn').select_option(tid);page.locator('#deTargetField').select_option('burst_propensity');page.locator('#deTargetNote').fill('两个内容可独立表达');page.locator('#deTargetSave').click();page.wait_for_function('uiReady && document.querySelector("#notice").textContent.includes("已记录人工目标")')
                page.locator('[data-tab="language-evidence"]').click();page.locator('#deReviewNote').fill('两次独立回合');page.locator('#deReviewApply').click();page.wait_for_function('state.pragmatics.applied_tendencies.length===1');page.locator('[data-tab="language-plans"]').click();page.locator('[data-de-turn]').first.click();assert page.locator('#traceDialog').is_visible();assert '参与评分或表达控制' in page.locator('#traceBody').inner_text();page.keyboard.press('Escape');page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1');assert not errors,errors;b.close();print('PASS rendered D+E review, receipt dialog, mobile no horizontal overflow')
        finally:h.shutdown();h.server_close();app.close()
if __name__=='__main__':main()
