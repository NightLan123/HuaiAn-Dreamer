"""Disposable persisted-data server for the JS startup/HTTP integration tests.

Test controls are stdin-only; they are never installed in the application API.
"""
import json,secrets,sys,tempfile,threading
from pathlib import Path
from http.server import ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from persona.server import Runtime,Handler
from test_v222 import populate
from ui_fixture_v220 import Parser

def emit(value):print('TEST_CONTROL '+json.dumps(value,ensure_ascii=False),flush=True)

with tempfile.TemporaryDirectory() as directory:
    first,second,_,_=populate(directory)
    app=Runtime(directory,ROOT)
    faults={};posts=[]
    class TestHandler(Handler):
        def do_GET(self):
            mode=faults.get(self.path.split('?')[0])
            if mode=='500':return self.send({'error':'合成的局部接口故障','code':'SYNTHETIC_FAILURE'},500)
            if mode=='null':return self.send(b'null')
            if mode=='json':return self.send(b'{invalid')
            return super().do_GET()
        def do_POST(self):
            posts.append(self.path);return super().do_POST()
    server=ThreadingHTTPServer(('127.0.0.1',0),TestHandler)
    def bind(runtime):
        server.app=runtime;runtime.http=server;runtime.port=server.server_port
        original=runtime.engine.boundaries.status
        def boundary_status():
            if faults.get('boundaries'):raise RuntimeError('Synthetic boundary failure')
            return original()
        runtime.engine.boundaries.status=boundary_status
    bind(app)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    parser=Parser();parser.feed((ROOT/'web/index.html').read_text('utf-8'))
    emit({'base':'http://127.0.0.1:'+str(server.server_port),'nodes':parser.nodes,'first':first,'second':second})
    try:
        for line in sys.stdin:
            command=json.loads(line);op=command['op']
            if op=='faults':faults.clear();faults.update(command.get('value',{}));emit({'ok':True})
            elif op=='rotate':app.token=secrets.token_urlsafe(32);emit({'ok':True})
            elif op=='stats':emit({'posts':list(posts),'name':app.engine.profile()['name'],'id':app.engine.profile()['id']})
            elif op=='large_history':
                for i in range(41):app.store.session(title='合成旧会话 '+str(i))
                sid=app.store.session(title='合成长历史')
                with app.store.lock,app.store.db:app.store.db.executemany('INSERT INTO messages VALUES (?,?,?,?,?,?)',[(f'long-{i:05}',sid,'user',f'合成分页消息 {i}',1,'pagination') for i in range(2010)])
                emit({'session':sid})
            elif op=='cbm':
                from test_cbm_v240 import BurstProvider
                from persona.psychology import parse_records
                from test_v281_runtime import Provider281
                class FullBurst(Provider281,BurstProvider):pass
                app.engine.provider_factory=FullBurst;app.engine.pmm_provider_factory=FullBurst
                records=parse_records(json.dumps([{'id':str(i),'speaker':'other' if i==0 else 'target','text':'最近有点想出去' if i==0 else '可以啊','timestamp':1700000000+i,'scope':'private:web:owner','conversation_id':'ui-demo'} for i in range(5)]))
                app.engine.import_records(records[1:])
                out=app.engine.turn(app.store.session(),'最近有点想出去')
                emit({'turn_id':out['turn_id'],'parts':out['reply_parts']})
            elif op=='restart':
                app.close();app=Runtime(directory,ROOT);bind(app);emit({'ok':True})
            elif op=='stop':emit({'ok':True});break
            else:raise ValueError('Unknown test control')
    finally:server.shutdown();server.server_close();app.close()
