"""Standalone authenticated, stateless CPU PMM worker."""
from __future__ import annotations
import json, secrets, threading
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from .common import dumps
from .pmm_interface import execute_request, CONTRACT, MODEL_ID, LEARNED_ID, REGISTRY_ID, MAX_BYTES, OPERATIONS

class PMMHandler(BaseHTTPRequestHandler):
    server_version='PMM';sys_version=''
    def log_message(self,*args):pass
    def setup(self):super().setup();self.connection.settimeout(30)
    def send(self,data,status=200):
        raw=dumps(data).encode();self.send_response(status)
        for k,v in {'Content-Type':'application/json; charset=utf-8','Content-Length':str(len(raw)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}.items():self.send_header(k,v)
        self.end_headers()
        try:self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError):pass
    def auth(self):
        return secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+self.server.api_key)
    def do_GET(self):
        if not self.auth():return self.send({'error':'PMM 认证失败'},401)
        if self.path=='/health':return self.send({'ok':True,'contract':CONTRACT,'models':[MODEL_ID,LEARNED_ID,REGISTRY_ID],'operations':OPERATIONS,'stateless':True})
        if self.path=='/v1/models':return self.send({'data':[{'id':MODEL_ID,'contract':CONTRACT,'checkpoint_format':'pmm/3'},{'id':LEARNED_ID,'contract':CONTRACT,'checkpoint_format':'learned-pmm/2'},{'id':REGISTRY_ID,'contract':CONTRACT,'checkpoint_format':'learned-pmm/2.1'}]})
        self.send({'error':'接口不存在'},404)
    def do_POST(self):
        if not self.auth():return self.send({'error':'PMM 认证失败'},401)
        if self.path!='/v1/pmm/execute':return self.send({'error':'接口不存在'},404)
        if not self.server.slots.acquire(blocking=False):return self.send({'error':'PMM 服务繁忙'},429)
        try:
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=MAX_BYTES:return self.send({'error':'PMM 请求体过大或为空'},413)
            raw=self.rfile.read(n)
            if len(raw)!=n:raise ValueError('请求未完整接收')
            body=json.loads(raw,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('不允许非有限数字')))
            self.send(execute_request(body))
        except (ValueError,KeyError,TypeError,OverflowError):self.send({'error':'PMM 合约、模型或参数校验失败'},400)
        except Exception:self.send({'error':'PMM 执行失败'},500)
        finally:self.server.slots.release()


def make_server(host,port,api_key):
    if not isinstance(api_key,str) or len(api_key)<16:raise ValueError('PMM API Key 至少 16 个字符')
    server=ThreadingHTTPServer((host,port),PMMHandler);server.api_key=api_key;server.slots=threading.BoundedSemaphore(2)
    return server
