"""Run independently: python run_pmm_service.py --port 8766 --token-file /path/to/key"""
import argparse, os, secrets
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description='Persona Dialogue 第二模型：独立 PMM HTTP 服务')
    parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--token-file',type=Path,default=Path.home()/'.persona_dialogue'/'pmm_service.key')
    parser.add_argument('--parent-stdin',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args();key=os.environ.get('PERSONA_PMM_API_KEY','')
    if not key:
        if args.token_file.exists():key=args.token_file.read_text('utf8').strip()
        else:
            args.token_file.parent.mkdir(parents=True,exist_ok=True)
            fd=os.open(args.token_file,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            key=secrets.token_urlsafe(32)
            with os.fdopen(fd,'w',encoding='utf8') as f:f.write(key)
        print('PMM API Key 文件（在连接设置中填入其内容）：',args.token_file,flush=True)
    os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
    from persona.pmm_service import make_server
    server=make_server(args.host,args.port,key)
    print(f'PMM HTTP/1 | http://{args.host}:{server.server_port} | learned-pmm-v21 / learned-pmm-v2 / pmm-mlp-v3',flush=True)
    print('服务不保存人格状态；检查点随请求计算后交回主程序。',flush=True)
    if args.parent_stdin:
        import sys,threading
        def watch_parent():
            sys.stdin.buffer.read();server.shutdown()
        threading.Thread(target=watch_parent,daemon=True).start()
    try:server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
