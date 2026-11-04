"""Same supplied candidates, no model calls: mechanism comparison, not quality study."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_cbm_v240 import plan
from persona import expression_plan as xp
from h2_expression_reference import parse_message_parts as h2parse
cases=[('tentative','最近有点想玩胡闹厨房',['可以啊。','你想玩几关？']),('invite','要不要一起玩胡闹厨房？',['行啊。','你想玩？']),('time','我打算今晚八点开胡闹厨房，你来吗',['好，八点见。','你想玩几关？']),('complaint','我打工累死了',['先歇歇。','你明天几点上班？']),('question','这游戏怎么联机？',['打开联机菜单。','一方建房，另一方输入房间码。']),('closing','我先去忙了',['好。','什么时候回来？'])]
rows=[]
for key,text,parts in cases:
    legacy=h2parse(xp.BREAK.join(parts),{'delivery':'multi','max_messages':4})
    p=plan(text);parsed,_=xp.parse_message_parts(json.dumps({'message_parts':[{'step_id':str(i),'text':v} for i,v in enumerate(parts)]}),p);new,check=xp.trim_excess(parsed,p)
    assert len(new)==1
    if key=='question':assert all(s in new[0] for s in parts)
    else:assert new==parts[:1]
    rows.append({'case':key,'input':text,'same_supplied_candidate':parts,'h2_output':legacy,'cbm_output':new,'new_strategy':p['candidate_strategy'],'sufficiency_target':p['sufficiency_target'],'check':check})
print(json.dumps({'kind':'deterministic same-candidate policy comparison','model_calls_each':0,'cases':6,'passed':6,'real_model_or_human_blind_evaluation':False,'limits':'仅验证裁剪、信息保留与停止规则；不能推断真实模型的自然度或质量提升比例。','results':rows},ensure_ascii=False,indent=2))
