"""Run inherited tests separately from new v2.8 tests; record actual results."""
import argparse,json,platform,sys,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]

def flatten(suite):
    for case in suite:
        if isinstance(case,unittest.TestSuite):yield from flatten(case)
        else:yield case

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'reports/v28/stage6');args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    cases=list(flatten(unittest.defaultTestLoader.discover(str(ROOT/'tests'))));groups={'inherited':[],'v28':[]}
    for case in cases:groups['v28' if case.__class__.__module__.startswith('test_v28') else 'inherited'].append(case)
    summary={'python':platform.python_version(),'platform':platform.platform(),'fixture_transport':True,'live_Qwen_QQ_Windows':False,'groups':{}}
    import numpy
    summary['numpy']=numpy.__version__
    try:
        import torch
        summary['torch']=torch.__version__
    except ImportError:summary['torch']='missing'
    success=True
    for name,selected in groups.items():
        start=time.monotonic()
        with (args.output/(name+'_python.log')).open('w',encoding='utf8') as log:
            result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.TestSuite(selected))
        summary['groups'][name]={'tests':result.testsRun,'seconds':round(time.monotonic()-start,3),'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'passed':result.wasSuccessful()}
        success=success and result.wasSuccessful();print(json.dumps({name:summary['groups'][name]}),flush=True)
    summary['total']=sum(r['tests'] for r in summary['groups'].values());summary['passed']=success
    (args.output/'python_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    raise SystemExit(0 if success else 1)

if __name__=='__main__':main()
