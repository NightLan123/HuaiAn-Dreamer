"""Deterministic protocol fixtures: never presented as real model output."""
import json
from persona.pmm import SEMANTIC_KEYS
from persona.psychology import ACTIONS

TEXT='我喜欢安静，也重视自主。'

def response(messages,structured=False):
    system=messages[0]['content'];ctx=next((json.loads(m['content']) for m in reversed(messages) if isinstance(m.get('content'),str) and m['content'].lstrip().startswith('{')),None) if structured and '[' in system[:2] else None
    if any(marker in system for marker in ('[COGNITIVE_APPRAISAL_V220]','[COGNITIVE_CUES_V220]')):
        r=ctx['records'][0]
        return {'estimates':{'turn_complete':.99,'addressed':.99,'personal_relevance':.8,'relationship_salience':.5,'novelty':.5,'emotional_salience':.3,'uncertainty':.05,'conflict':.05,'consequence':.05,'event_boundary':.2},'evidence':[{'record_id':r['id'],'quote':r['text'],'fields':['turn_complete','addressed']}],'summary':'确定性协议夹具，非真实心理验证'}
    if '[ACTION_CHECK_V221]' in system:
        return {'decision_id':ctx['decision_id'],'decision_revision':ctx['decision_revision'],'expected_action':ctx['expected_action'],'detected_action':ctx['expected_action'],'compliant':True,'failure_code':'NONE','spans':[]}
    if 'connection test' in str(messages):return {'ok':True}
    if '[API_PMM_PREPARE_V2]' in system:
        return {'boundary_appraisal':[{'boundary_id':b['boundary_id'],'activation':0.,'uncertainty':1.,'quote':'','utilities':{a:(.9 if a=='answer' else .1) for a in __import__('persona.boundaries',fromlist=['SOCIAL_ACTIONS']).SOCIAL_ACTIONS}} for b in ctx.get('boundary_context',{}).get('states',[])],'appraisal':{'valence':.2,'arousal':.3,'stress':.1,'engagement':.7},'evidence_quote':ctx['input'],
            'memory_focus':[{'id':m['id'],'quote':m['evidence'],'weight':.8} for m in ctx['memories']],
            'tendencies':[{'id':'v0','weight':.3,'value_offsets':{'self_direction':.15},'summary':'自主倾向'}, {'id':'v1','weight':.4,'value_offsets':{},'summary':'中间状态'}, {'id':'v2','weight':.3,'value_offsets':{'benevolence':.15},'summary':'关系倾向'}],
            'action_prior':{a:.5 if a=='reply' else .1 for a in ACTIONS},'language_condition':'依原始表达样本，简短而直接。','retrieval_queries':[]}
    if '[API_PMM_SYNTHESIS_V2]' in system:
        r=ctx['source_records'][0]
        return {'statements':[{'domain':'language','text':'这是测试夹具的有证据归纳。','evidence':[{'record_id':r['id'],'quote':r['text']}]}],'uncertainties':['证据仍不足以推断长期稳定性']}
    if '[UNDERSTAND_V3]' in system:
        text=ctx['current_input'];sem={k:0. for k in SEMANTIC_KEYS};sem.update(social=.6,agency=.5,certainty=.6,goal_congruence=.6,needs_answer=.6)
        need='personal' if '记得' in text else 'current' if '今天股价' in text else 'none'
        if '再见' in text:sem['disengagement']=1
        return {'intent':'回应当前消息','semantic':sem,'knowledge_need':need,'knowledge_confidence':.8,'keywords':['安静'] if '安静' in text else [],'value_tension':['self_direction','benevolence'],'boundary_matches':[],'boundary_cues':[],'boundary_feedback':{'about_ai':False,'quote':''},'contact_withdrawal':{'stop':False,'quote':''}}
    if any(marker in system for marker in ('[ASSESS_V3]','[ASSESS_V21]','[DECIDE_V21]')):
        action='silence' if '再见' in ctx['input'] else 'reply'
        return {'views':[{'id':f'v{i}','summary':'测试倾向摘要','utilities':{a:.95 if a==action else .05 for a in ACTIONS}} for i in range(len(ctx.get('projections',[0,1,2])))],'supported_memory_evidence':[{'id':m['id'],'quote':m['evidence']} for m in ctx['memories'] if '安静' in m['content']],'retrieval_queries':[]}
    if '[PMM_REVIEW_V21]' in system:
        return {'weights':[{'id':v['id'],'weight':v['weight']} for v in ctx['projections']],'reject_ids':[],'retrieval_queries':[],'unresolved_conflict':False,'summary':'测试夹具：已核对来源'}
    if '[FEEDBACK_V3]' in system:
        u=ctx['user_record'];a=ctx['self_record'];ev=lambda r:[{'record_id':r['id'],'quote':r['text']}]
        return {'action_compliant':True,'self_appraisal':{'valence':.25,'arousal':.35,'stress':.1,'engagement':.7},
            'self_observations':{'observations':[{'domain':'traits','key':'open_mindedness','value':.6,'confidence':.5,'evidence':ev(a)}]},
            'interlocutor':{'observations':[{'domain':'traits','key':'extraversion','value':.2,'confidence':.5,'evidence':ev(u)}], 'beliefs':[{'text':'对方表示喜欢安静','evidence':ev(u)}]},
            'interlocutor_emotion':{'valence':.2,'arousal':.3,'stress':.1,'engagement':.5,'quote':u['text']},
            'memory_ops':[{'op':'ADD','kind':'preference','content':'对方表示喜欢安静。','evidence_quote':u['text'],'confidence':.7,'importance':.7}],
            'relation_delta':{'trust':.01,'affection':.005}}
    if '[DISTILL_V3]' in system:
        records=ctx['target_records'];ev=[{'record_id':r['id'],'quote':r['text']} for r in records[:8]]
        return {'construct_updates':[{'feature_id':'hexaco.x.sociability','estimate':.25,'confidence':.7,'evidence':ev},{'feature_id':'value.self_direction_thought','estimate':.8,'confidence':.7,'evidence':ev}], 'observations':[{'domain':'traits','key':'extraversion','value':.25,'confidence':.7,'evidence':ev},{'domain':'values','key':'self_direction','value':.8,'confidence':.6,'evidence':ev}],
            'beliefs':[],'patterns':[{'situation':'熟人开场','response':'先让对方说','evidence':ev}],
            'boundaries':[{'label':'不讨论银行卡密码','keywords':['银行卡密码'],'action':'decline','evidence':ev}],
            'examples':[{'record_id':r['id'],'action':'reply','function':'回应'} for r in records]}
    if '[REALIZE_V3]' in system:
        condition=json.loads(system.split('\n条件：',1)[1]);action=condition['decision']['action']
        return {'unknown':'不知道。','decline':'不说这个。','clarify':'说哪件事？','disagree':'我不认同。'}.get(action,'说。')
    return '协议测试'

class FixtureProvider:
    calls=[];fail_stage=None
    def __init__(self,config):self.config=config
    def complete(self,messages,structured=False,controller=False):
        from persona.provider import ProviderError
        self.calls.append(messages)
        if self.fail_stage and self.fail_stage in messages[0]['content']:raise ProviderError('fixture failure')
        return response(messages,structured)
