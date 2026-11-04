"""Export allowlisted records of actual requests against two loopback fixtures."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_v281_connections import Connections
from persona.pmm_connections import probe
from persona.pmm_workspace import preview

def main():
 x=Connections();x.setUp()
 try:
  receipts=[]
  for role in ('A','B'):
   for op in ('models','connect','invoke'):
    r=probe(x.r.engine,role,op);assert r['ok'],(role,op);receipts.append({k:r[k] for k in ('role','operation','service','provider','model','elapsed_ms','ok')})
  owner=x.r.engine.profile()['id'];before=x.r.store.meta('pmm281_affect')['revision'];v=preview(x.r.engine,{'subject_id':owner,'text':'这是合成的协议验收事件。'});assert x.r.store.meta('pmm281_affect')['revision']==before
  co=v['trace']['pmm28']['components'];assert co['reasoner']['connection']['model']=='A-http' and co['negotiation']['connection']['model']=='B-http'
  x.r.configure({'pmm281':{'b_share_a':True}});r=probe(x.r.engine,'B','invoke');assert r['ok'];receipts.append({k:r[k] for k in ('role','operation','service','provider','model','elapsed_ms','ok','shared_service')})
  x.r.configure({'pmm281':{'b_share_a':False}});x.b.fail=True;r=probe(x.r.engine,'B','invoke');assert not r['ok'];receipts.append({k:r.get(k) for k in ('role','operation','service','provider','model','elapsed_ms','ok','http_status','failure_reason')})
  wire=[]
  for name,endpoint in [('Ollama',x.a),('OpenAI-compatible',x.b)]:
   for req in endpoint.requests:
    b=req.get('body',{});messages=b.get('messages') or [];system=messages[0]['content'] if messages else ''
    marker=next((v for v in ('PMM_A_EVENT_V281','PMM_B_DELIBERATION_V281','UNDERSTAND_V3','REALIZE_V3','ACTION_CHECK_V221','FEEDBACK_V3') if '['+v+']' in system),'generic_probe_or_listing')
    wire.append({'endpoint':name,'path':req['path'],'model':b.get('model'),'task':marker,'max_tokens':b.get('max_tokens') or b.get('options',{}).get('num_predict')})
  print(json.dumps({'live_http':True,'upstream':'two_synthetic_loopback_services','real_cloud_or_Qwen':False,'receipts':receipts,'wire':wire,'preview_production_writes':v['production_state_writes'],'external_messages':v['external_messages_sent']},ensure_ascii=False,indent=2))
 finally:x.tearDown()
if __name__=='__main__':main()
