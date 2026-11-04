"""Real supervisor smoke in a Unicode/spaces directory (Linux, no model requests)."""
from pathlib import Path
import json,os,shutil,signal,socket,subprocess,sys,tempfile,time,urllib.request
ROOT=Path(__file__).resolve().parents[1]
VERSION=json.loads((ROOT/'RELEASE.json').read_text())['version']
with tempfile.TemporaryDirectory(prefix='槐安 启动验收 ') as d:
    env=os.environ.copy();env['HUAIAN_DATA_HOME']=str(Path(d)/'测试用户');Path(env['HUAIAN_DATA_HOME']).mkdir()
    work=Path(d)/'程序 文件';shutil.copytree(ROOT,work,ignore=shutil.ignore_patterns('__pycache__','.venv','exports','logs'))
    subprocess.run([sys.executable,'-m','venv','--system-site-packages',str(work/'.venv')],check=True,capture_output=True)
    check=subprocess.run([sys.executable,str(work/'launcher.py'),'--check'],cwd=work,env=env,capture_output=True,text=True,timeout=30)
    assert check.returncode==0,check.stdout+check.stderr
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    data=Path(d)/'人格 数据';out=(Path(d)/'supervisor-output.txt').open('w')
    child=subprocess.Popen([sys.executable,str(work/'launcher.py'),'--','--no-browser','--port',str(port),'--data-dir',str(data)],cwd=work,env=env,stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
    try:
        base='http://127.0.0.1:'+str(port);page=None
        for _ in range(100):
            if child.poll() is not None:raise AssertionError('Launcher exited early')
            try:
                with urllib.request.urlopen(base,timeout=.5) as r:page=r.read().decode();cookie=r.headers['Set-Cookie'].split(';')[0]
                break
            except OSError:time.sleep(.1)
        assert page and '槐安梦客' in page
        with urllib.request.urlopen(urllib.request.Request(base+'/api/state',headers={'Cookie':cookie})) as r:state=json.load(r)
        assert state['version']==VERSION and state['config']['cognition']['mode']=='adaptive'
        with urllib.request.urlopen(urllib.request.Request(base+'/api/support',headers={'Cookie':cookie})) as r:diagnostic=json.load(r)
        assert diagnostic['version']==VERSION
        assert Path(json.loads((Path(env['HUAIAN_DATA_HOME'])/'.huai_an_dreamer/data-location.json').read_text())['path'])==data
        log=(work/'logs/startup.log').read_text();assert '环境检查通过' in log and '正在启动槐安梦客' in log
        print(json.dumps({'platform':sys.platform,'unicode_and_spaces_directory':True,'environment_check':True,'real_supervised_http_start':True,'page_brand':True,'version':state['version'],'diagnostic_endpoint':True,'startup_log':True,'real_model_calls':0,'windows_native_execution':False},ensure_ascii=False))
    finally:
        os.killpg(child.pid,signal.SIGTERM);child.wait(timeout=10);out.close()
