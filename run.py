#!/usr/bin/env python3
"""Launcher supervises code reloads; a reload never creates a new subject."""
import argparse, os, sys, subprocess, time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
# Public source release: isolate both role storage and the saved-location pointer.
# An explicit --data-dir still supports deliberate migration by the owner.
os.environ.setdefault('HUAIAN_DATA_HOME', str(ROOT / '.local-home'))

def main():
    if sys.version_info < (3,10):
        print('需要 Python 3.10 或更新版本。');return 1
    parser=argparse.ArgumentParser(description='槐安梦客 / HuaiAn Dreamer')
    parser.add_argument('--data-dir',default=os.environ.get('PERSONA_DATA_DIR') or str(ROOT/'data'))
    parser.add_argument('--new-data',action='store_true',help='明确创建独立数据目录；不会迁移或覆盖已有主体')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--preview',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    from persona.data_guard import resolve_data_directory,DataGuardError
    # Only permit automatic initialization in this release's own empty data folder.
    # Explicit external paths retain the original migration checks.
    local_data = ROOT / 'data'
    fresh_local = (Path(args.data_dir).expanduser().resolve() == local_data.resolve()
                   and (not local_data.exists() or local_data.is_dir() and not any(local_data.iterdir())))
    try:directory=resolve_data_directory(args.data_dir,ROOT,allow_new=args.new_data or fresh_local)
    except (DataGuardError,ValueError,OSError) as exc:print('数据保护检查未通过：',str(exc));return 2
    if args.worker or args.preview:
        try:from persona.server import serve
        except ModuleNotFoundError:
            print('请先运行启动脚本，或执行：python -m pip install -r requirements.txt');return 1
        from persona.lock import InstanceLock
        try:
            with InstanceLock(directory):
                return serve(directory,ROOT,args.port,args.preview,not args.no_browser and not args.preview,remember_directory=True)
        except (RuntimeError,OSError) as exc:
            print('启动失败：',str(exc));return 1
    env=os.environ.copy();env['OPENBLAS_NUM_THREADS']='1';env['OMP_NUM_THREADS']='1'
    child_args=[sys.executable,str(ROOT/'run.py'),'--worker','--data-dir',str(directory),'--port',str(args.port)]
    if args.no_browser:child_args+=['--no-browser']
    if args.new_data:child_args+=['--new-data']
    try:
        while True:
            child=subprocess.Popen(child_args,env=env)
            code=child.wait()
            if code!=75:return code
            print('Applying code update; continuing the same subject...',flush=True)
            if '--no-browser' not in child_args:child_args.append('--no-browser')
            time.sleep(.2)
    except KeyboardInterrupt:
        if child.poll() is None:child.terminate();child.wait()
        return 0
if __name__=='__main__':sys.exit(main())
