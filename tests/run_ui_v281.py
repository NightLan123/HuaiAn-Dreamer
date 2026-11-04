import concurrent.futures,json,os,re,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'reports/v281/stage4';OUT.mkdir(parents=True,exist_ok=True)
def run(code):
 start=time.monotonic();r=subprocess.run(['node',str(ROOT/'tests'/('test_ui_v'+code+'.js'))],cwd=ROOT,env={**os.environ,'TEST_PYTHON':sys.executable,'OPENBLAS_NUM_THREADS':'1'},stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=150);(OUT/('ui_'+code+'.log')).write_text(r.stdout);return code,{'exit_code':r.returncode,'checks':sum(x.startswith('PASS ') for x in r.stdout.splitlines()),'seconds':round(time.monotonic()-start,2)}
if __name__=='__main__':
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:summary=dict(pool.map(run,sys.argv[1:] or ['222','230','240','250','251','26','27','28']))
 p=OUT/'http_summary.json';combined=json.loads(p.read_text()) if p.exists() else {};combined.update(summary);p.write_text(json.dumps(combined,indent=2));print(json.dumps(summary));sys.exit(int(any(v['exit_code'] for v in summary.values())))
