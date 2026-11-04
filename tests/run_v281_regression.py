"""Run historical contracts in their original mode fixture; verify new defaults separately.
Only the test process restores the superseded Shadow/Active configuration semantics.
No production switch, model, provider, decisions, or data are mocked by this runner.
"""
import argparse,json,os,sys,time,unittest,platform
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from run_v28_regression import flatten
from persona.common import Config

def historical_mode_fixture():
    original=Config.get
    def read(self):
        c=original(self);raw=json.loads(self.path.read_text('utf8'))
        c['pmm281']['mode']='compatibility';c['pmm28']['mode']=raw.get('pmm28',{}).get('mode','shadow');return c
    Config.get=read

def run(group,out):
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'));cases=list(flatten(suite))
    def name(c):
        m=c.__class__.__module__;return 'v281' if m.startswith('test_v281') else 'v28' if m.startswith('test_v28') else 'inherited'
    selected=[c for c in cases if name(c)==group]
    if group!='v281':historical_mode_fixture()
    start=time.monotonic();out.mkdir(parents=True,exist_ok=True)
    with (out/(group+'_python.log')).open('w',encoding='utf8') as f:r=unittest.TextTestRunner(stream=f,verbosity=2).run(unittest.TestSuite(selected))
    result={'group':group,'mode_context':'normal_281_defaults_and_explicit_compatibility' if group=='v281' else 'original_2_8_mode_fixture_on_2_8_1_source','tests':r.testsRun,'seconds':round(time.monotonic()-start,3),'python':platform.python_version(),'failures':[str(c) for c,_ in r.failures],'errors':[str(c) for c,_ in r.errors],'skips':len(r.skipped),'passed':r.wasSuccessful()}
    (out/(group+'_summary.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False));return r.wasSuccessful()
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('group',choices=['inherited','v28','v281']);ap.add_argument('--out',type=Path,default=ROOT/'reports/v281/stage4');a=ap.parse_args();sys.exit(0 if run(a.group,a.out) else 1)
