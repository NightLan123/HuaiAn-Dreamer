"""Dependency-free bootstrap. Double-click entry points keep failures visible."""
from __future__ import annotations
import argparse, datetime, importlib.util, os, subprocess, sys, traceback
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def log_directory(root=ROOT):
    candidates=[root/'logs',Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'HuaiAnDreamer'/'logs']
    for path in candidates:
        try:path.mkdir(parents=True,exist_ok=True);return path
        except OSError:continue
    raise OSError('Cannot create a startup log directory')

class StartupLog:
    def __init__(self,path):
        self.path=Path(path)
        if self.path.exists() and self.path.stat().st_size>2_000_000:
            previous=self.path.with_suffix('.previous.log');previous.unlink(missing_ok=True);self.path.replace(previous)
        self.file=self.path.open('a',encoding='utf-8')
    def write(self,text):
        self.file.write(text);self.file.flush()
        try:sys.stdout.write(text);sys.stdout.flush()
        except UnicodeEncodeError:sys.stdout.buffer.write(text.encode(sys.stdout.encoding or 'utf-8',errors='replace'));sys.stdout.flush()
    def close(self):self.file.close()

def run_logged(args,log,env=None,cwd=ROOT):
    """Do not use shell=True: spaces and Chinese directories remain literal paths."""
    process=subprocess.Popen(list(map(str,args)),cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',bufsize=1)
    try:
        for line in process.stdout:log.write(line)
        return process.wait()
    except KeyboardInterrupt:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=8)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        return 130
    finally:
        process.stdout.close()

def python_path(root=ROOT):return root/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')

def bootstrap(args,root=ROOT):
    log_name='pmm-startup.log' if getattr(args,'pmm',False) else 'startup.log'
    log=StartupLog(log_directory(root)/log_name)
    try:
        log.write('\n=== HuaiAn Dreamer / '+datetime.datetime.now().astimezone().isoformat()+' ===\n')
        log.write('工作目录：'+str(root)+'\n启动日志：'+str(log.path)+'\n')
        if sys.version_info<(3,10):log.write('需要 Python 3.10 或更新版本。\n');return 2
        env=os.environ.copy();env.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8',PYTHONUNBUFFERED='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
        python=python_path(root)
        if not python.exists():
            log.write('首次启动：正在准备独立 Python 环境。\n')
            code=run_logged([sys.executable,'-m','venv',root/'.venv'],log,env,root)
            if code:return code
        version=run_logged([python,'-c','import sys; sys.exit(0 if sys.version_info >= (3,10) else 2)'],log,env,root)
        if version:
            log.write('已有 .venv 无法使用。请关闭程序，将程序目录的 .venv 改名后重新启动；人格数据不在此目录。\n');return version
        check=run_logged([python,'-c','import numpy, PIL, tzdata'],log,env,root)
        if check:
            log.write('正在安装或修复运行依赖；这一步需要网络。\n')
            code=run_logged([python,'-m','pip','install','-r',root/'requirements.txt'],log,env,root)
            if code:return code
            code=run_logged([python,'-c','import numpy, PIL, tzdata'],log,env,root)
            if code:return code
        if args.check:
            log.write('环境检查通过。\n');return 0
        pmm=getattr(args,'pmm',False)
        log.write('正在启动独立 PMM HTTP 服务。\n' if pmm else '正在启动槐安梦客，浏览器会自动打开。保留此窗口可查看运行状态。\n')
        command=[python,'-u',root/('run_pmm_service.py' if pmm else 'run.py'),*args.arguments]
        return run_logged(command,log,env,root)
    except Exception:
        log.write(traceback.format_exc());return 1
    finally:
        log.write('启动器已退出。若有错误，请查看以上内容和 startup.log。\n');log.close()

def main():
    parser=argparse.ArgumentParser(description='槐安梦客启动与环境检查')
    parser.add_argument('--check',action='store_true');parser.add_argument('--pmm',action='store_true');parser.add_argument('arguments',nargs=argparse.REMAINDER)
    args,unknown=parser.parse_known_args();args.arguments=unknown+args.arguments
    if args.arguments and args.arguments[0]=='--':args.arguments=args.arguments[1:]
    return bootstrap(args)

if __name__=='__main__':raise SystemExit(main())
