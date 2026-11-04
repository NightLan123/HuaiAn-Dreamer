"""Disposable UI test server with synthetic models; no personal data or QQ sends."""
import json,sys
from pathlib import Path
from http.server import ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from persona.server import Handler
from test_v281_connections import Connections
x=Connections();x.setUp();app=x.r
app.preview=True;app.host='0.0.0.0';app.port=4173
sid=app.store.session();app.engine.turn(sid,'这是一个用于界面验收的合成事件。')
server=ThreadingHTTPServer(('0.0.0.0',4173),Handler);server.app=app;app.http=server
print(json.dumps({'url':'http://terminal.local:4173','synthetic':True,'A':x.a.url,'B':x.b.url}),flush=True)
try:server.serve_forever()
finally:server.server_close();x.tearDown()
