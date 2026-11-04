"""Structural DOM fixture and real empty runtime state; no browser rendering."""
import json,sys,tempfile
from html.parser import HTMLParser
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from persona.server import Runtime
class Parser(HTMLParser):
    def __init__(self):super().__init__();self.nodes=[];self.stack=[]
    def handle_starttag(self,t,a):
        i=len(self.nodes);self.nodes.append({'tag':t,'attrs':dict(a),'parent':self.stack[-1] if self.stack else None})
        if t not in ('input','img','meta','link','br','hr','source'):self.stack.append(i)
    def handle_endtag(self,t):
        for k in range(len(self.stack)-1,-1,-1):
            if self.nodes[self.stack[k]]['tag']==t:self.stack=self.stack[:k];break
if __name__=='__main__':
    p=Parser();p.feed((ROOT/'web/index.html').read_text())
    with tempfile.TemporaryDirectory() as d:
        app=Runtime(d,ROOT)
        try:print(json.dumps({'nodes':p.nodes,'state':app.state()},ensure_ascii=False))
        finally:app.close()
