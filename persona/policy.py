"""Executable gates and weighted same-person perspectives. LLM supplies appraisal,
not the final action or vote weights. Coefficients are explicit engineering choices.
"""
from __future__ import annotations
import copy, math, re
from .psychology import ACTIONS, VALUES
from .common import clamp


def project(profile,understanding,state,relation,decoded=None):
    """Compatibility entry point delegates to typed canonical priors."""
    from .deliberation import views
    from .registry import ensure_profile
    return views(ensure_profile(profile),understanding,decoded or {'influence':0.}, {'activated':False},1)


def choose(understanding,profile,views,assessments,decoded,memories,text):
    u=understanding;sem=u['semantic'];hard=[];soft=[]
    matches={x.get('id') for x in u.get('boundary_matches',[]) if isinstance(x,dict) and x.get('quote') and x['quote'] in text}
    for b in profile.get('boundaries',[]):
        if not b.get('enabled'):continue
        lexical=any(str(k).strip() and str(k).lower() in text.lower() for k in b.get('keywords',[]))
        if lexical or b['id'] in matches:(hard if b.get('hard') else soft).append(b)
    score={a:0. for a in ACTIONS};summary=[]
    byid={r.get('id'):r for r in assessments if isinstance(r,dict)}
    for v in views:
        r=byid.get(v['id'],{});utility=r.get('utilities',{})
        for a in ACTIONS:score[a]+=v['weight']*clamp(utility.get(a,0))
        summary.append({'id':v['id'],'label':v['label'],'weight':v['weight'],'summary':str(r.get('summary',''))[:400]})
    contributions={}
    negotiated=u.get('proposal_action_assessment') or {}
    if negotiated.get('source')=='validated_B_proposals':
        replacement={a:float(v) for a,v in negotiated.get('utilities',{}).items() if a in ACTIONS and type(v) in (int,float) and math.isfinite(v) and 0<=v<=1}
        # B replaces the A assessment for actions it actually evaluated. It does
        # not erase the separate local psychological terms or add duplicate votes.
        contributions['negotiated_assessment']={a:replacement[a]-score[a] for a in replacement}
        score.update(replacement)
    for a in ACTIONS:score[a]+=.25*decoded['influence']*decoded['action_probabilities'].get(a,0)
    condition=u.get('decision_conditions',{})
    if condition.get('schema')=='pmm-person-relational-conditions/1':
        for group in ('personality','relationship','regulation','emotion'):
            terms=condition.get('terms',{}).get(group,{})
            contributions[group]={a:clamp(terms.get(a,0),-.2,.2) for a in ACTIONS}
            for a,value in contributions[group].items():score[a]+=value
    for b in soft:score[b['action']]+=.4
    cooperative=u.get('pmm28_decision',{})
    if cooperative.get('schema')=='coordinated-policy/2.8' and cooperative.get('formal_contribution') is True:
        terms=cooperative.get('score_terms',{})
        contributions['pmm28']={a:clamp(terms.get(a,0),-.2,.2) for a in ACTIONS}
        for a,value in contributions['pmm28'].items():score[a]+=value
    ed_policy=u.get('expressive_drive_policy',{})
    if isinstance(ed_policy,dict) and ed_policy.get('schema')=='expressive-drive/2.8.3' and isinstance(ed_policy.get('policy_score_terms'),dict):
        terms=ed_policy['policy_score_terms']
        contributions['expressive_drive']={a:clamp(terms.get(a,0),-.2,.2) for a in ACTIONS}
        for a,value in contributions['expressive_drive'].items():score[a]+=value
    need=u.get('knowledge_need','none')
    # Episodic claims require a cited source and nontrivial lexical/relevance support.
    evidence={e.get('id'):str(e.get('quote','')) for e in u.get('supported_memory_evidence',[]) if isinstance(e,dict)}
    supporting=[m for m in memories if m['id'] in evidence and evidence[m['id']].strip() and evidence[m['id']] in m.get('evidence','') and m.get('relevance',0)>=.12 and m['confidence']>=.6 and m['kind'] not in ('hypothesis','self_observation')]
    evidence_ok=bool(supporting) and need!='current'
    if hard:
        b=next((x for x in hard if x['action']=='decline'),hard[0])
        action=b['action'];reason='启用的硬边界：'+b['label'];gate='hard_boundary'
    elif need in ('current','personal') and not evidence_ok:
        action='clarify' if sem.get('ambiguity',0)>.65 else 'unknown';reason='需要可核验的记忆或当前信息，现有证据不足';gate='missing_evidence'
    elif need=='general' and u.get('knowledge_confidence',0)<.45:
        action='unknown';reason='基础模型报告不确定';gate='knowledge_uncertain'
    elif sem.get('ambiguity',0)>.8:
        action='clarify';reason='输入缺少作答所需信息';gate='ambiguity'
    else:
        # Silence requires evidence of disengagement and is never inferred just from a quiet personality.
        if sem.get('disengagement',0)<.7:score['silence']=-1
        if need=='none':score['unknown']=-1
        action=max(score,key=score.get);reason='同一人格三个倾向的加权效用';gate='weighted_policy'
    out={'action':action,'reason':reason,'gate':gate,'scores':score,'perspectives':summary,'condition_contributions':contributions,
         'knowledge':{'need':need,'grounded_memory':evidence_ok,'supporting_ids':[m['id'] for m in supporting],
                      'base_model_confidence':u.get('knowledge_confidence',0),'verified_external':False}}
    if isinstance(ed_policy,dict) and ed_policy.get('schema')=='expressive-drive/2.8.3':
        out['expressive_drive']={k:copy.deepcopy(ed_policy.get(k)) for k in ('activation','urgency','persistence','expressive_intent','active_motive_id','status') if k in ed_policy}
    return out


def style_condition(profile,text,understanding,decoded):
    style=profile['style'];samples=profile['examples'];words=set(re.findall(r'[a-z]+|[\u3400-\u9fff]',text.lower()))
    def match(e):
        k=set(re.findall(r'[a-z]+|[\u3400-\u9fff]',e['input'].lower()));return len(words&k)/max(1,len(words|k))
    selected=sorted(samples,key=match,reverse=True)[:5]
    natural=understanding['semantic'].get('complexity',0)<.6 and understanding['semantic'].get('task',0)<.7
    limit=None
    if style['count']>=3 and natural:
        measured=style['p90_chars']*1.8+4
        predicted=clamp(decoded['style'][0]*256+4,measured*.75,measured*1.25)
        limit=int(max(4,min(500,(1-decoded['influence'])*measured+decoded['influence']*predicted)))
    return {'measured':style,'decoded_vector':dict(zip(('length','short','question','exclamation','emoji','linebreak','ellipsis','punctuation'),decoded['style'])),
            'learned_influence':decoded['influence'],'max_chars':limit,'examples':selected,
            'canonical_style':{k:v for k,v in __import__('persona.registry',fromlist=['compact']).compact(profile['psychology'])['known'].items() if k.startswith('style.')},
            'api_language_condition':decoded.get('language_condition',''),'learned_linguistic_features':decoded.get('linguistic',{}),
            'instruction':'模仿目标的语用、句长和节奏。极短回答可以完整，不自动补充解释或服务式结尾。例句只示范风格，不照搬其中事实。'}
