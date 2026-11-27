"""D+E expression contract. Conditions have separate versions and write owners.

This small inspectable policy ranks only permissible expressions for a frozen
communicative action. It is not an independently trained neural policy.
"""
from __future__ import annotations
import copy
from .common import clamp
from .expression_plan import number

SCHEMA='de-expression/1'
AXES=('valence','arousal','dominance','stress','engagement')

def conditions(language,affect,traits,event,act,*,use_d=True,use_e=True,expressive_drive=None):
    """use_d/use_e support controlled offline ablations; live callers use both."""
    e=affect['emotion'];m=affect['mood'];s=language or {};d=s.get('text_style',{})
    out={'schema':SCHEMA,'source_event':{'id':event['id'],'original_ids':list(event.get('source_event_ids') or [event['id']]),
        'scope':event['scope'],'person':event['person'],'quote':event['text'][:300]},'situation':{'prior_speech_act':act},
        'stable_trait':{'version':traits['trait_version'],'digest':traits['trait_digest'],'known_dispositions':{
            k:{'estimate':v['estimate'],'source_type':v['source_type']} for k,v in traits['affective_disposition'].items() if v['estimate'] is not None}},
        'long_term_language':None if not use_d else {'version':s.get('version',0),'context':act,'counts':s.get('effective_episodes',0),
            'statistics':{k:{'estimate':v.get('estimate'),'events':v.get('effective_episodes',0),'source_type':v.get('source_type')} for k,v in s.get('policy_statistics',{}).items() if v.get('estimate') is not None},
            'reviewed':copy.deepcopy(s.get('reviewed_tendencies',[])), 'text_features':{k:d.get(k) for k in ('effective_events','untimed_events','mean_sentence_characters','ellipsis_rate','question_rate','surface_phrases')},
            'source_event_ids':s.get('source_event_ids',[]),'text_source_event_ids':d.get('source_event_ids',[]),'neural_head':'not_trained'},
        'emotion':None if not use_e else {'revision':e['state_revision'],'as_of':e['last_updated'],'event_id':e['event_id'],'source_type':e['source_type'],**{k:e[k] for k in AXES},
            'categorical_activations':{k:v for k,v in e['categorical_activations'].items() if v is not None}},
        'mood':None if not use_e else {'as_of':m['updated_at'],'baseline_ref':m['baseline_ref'],'source_type':m['source_type'],**{k:m.get(k) for k in ('valence','arousal','dominance')}},
        'calibrated':False}
    out['stable_trait']['operative_personality']=copy.deepcopy(traits.get('operative_personality') or {})
    if use_e and isinstance(expressive_drive,dict):
        out['expressive_drive']={k:copy.deepcopy(expressive_drive[k]) for k in ('activation','urgency','persistence','expressive_intent','state_revision','active_motive_id','status') if k in expressive_drive}
    return out

def values(language):
    if not language:return {}
    out={k:{'estimate':r['estimate'],'events':r['events'],'source':'human_episode_statistics'} for k,r in language['statistics'].items() if r['events']>=2}
    for r in language['reviewed']:
        if r['effective_events']>=2:out[r['field']]={'estimate':r['estimate'],'events':r['effective_events'],'source':'reviewed_owner_evidence','candidate_id':r['id'],'learning_strength':r.get('learning_strength',1.),'source_event_ids':r.get('source_event_ids',[])}
    return out

def refine(plan,c,expression,decision,proposal=None,text=None):
    """Apply auditable terms after model appraisal/boundary selection, before realization."""
    out=copy.deepcopy(plan);d=c['long_term_language'];e=c['emotion'];m=c['mood'];trait=c['stable_trait'];s=c['source_event'];ed=c.get('expressive_drive')
    act=out['previous_act'];action=decision['action'];initial=out['candidate_strategy'];p=proposal or {}
    grounded=bool(isinstance(p.get('evidence_quote'),str) and p['evidence_quote'].strip() and p['evidence_quote'] in (text or s['quote']))
    split_basis=grounded and isinstance(p.get('split_reason'),str) and bool(p['split_reason'].strip())
    room=action=='reply' and decision.get('gate','weighted_policy')=='weighted_policy' and out['sufficiency_target']!='complete' and act not in ('closing','correction') and initial not in ('CLARIFY_IF_NEEDED','NO_ACTION','WAIT','REPAIR')
    allowed_burst=room and split_basis and out['message_plan']['max_bubbles']>1
    candidates={'RESPOND_AND_YIELD':.55,'MINIMAL_REPLY':.43}
    if allowed_burst:candidates.update(CASUAL_BURST=.39,OPTIONAL_EXPANSION=.34)
    if initial in candidates:candidates[initial]+=.10 if grounded else .015
    if not room:candidates={initial:1.}
    terms={k:[] for k in candidates};evidence=values(d);uses=[]
    def add(k,group,field,delta):
        if k in terms and abs(delta)>1e-10:terms[k].append({'channel':group,'field':field,'delta':round(delta,6)})
    if room:
        # Role tendency affects how much to develop a permissible response,
        # not whether to fabricate a question, split a bubble or ignore a task.
        personality=trait.get('operative_personality') or {}
        def tendency(key):
            r=personality.get(key) or {};v=r.get('estimate');unc=r.get('posterior_uncertainty')
            return (v-.5)*2*(1-unc) if type(v) in (int,float) and type(unc) in (int,float) else 0.
        sociability=tendency('hexaco.x.sociability');communion=tendency('social.communion')
        add('RESPOND_AND_YIELD','P','sociability',.12*sociability)
        add('MINIMAL_REPLY','P','sociability',-.12*sociability)
        add('RESPOND_AND_YIELD','P','communion',.08*communion)
        for k,v in evidence.items():
            # Both proxies derive from the same short demonstration. Use the more
            # specific acknowledgement measure once; a short burst may also yield.
            if k=='response_sufficiency_preference' and v['source']=='human_episode_statistics' and evidence.get('yield_after_acknowledgement',{}).get('source')=='human_episode_statistics':continue
            n=v['events'];delta=(v['estimate']-.5)*2*n/(n+2)*v.get('learning_strength',1.)
            if k=='burst_propensity' and allowed_burst:add('CASUAL_BURST','D',k,.75*delta);add('RESPOND_AND_YIELD','D',k,-.14*delta)
            elif k in ('response_sufficiency_preference','yield_after_acknowledgement') and act in ('invitation','tentative_interest','complaint','narrative'):
                add('RESPOND_AND_YIELD','D',k,.34*delta);add('CASUAL_BURST','D',k,.34*delta);add('OPTIONAL_EXPANSION','D',k,-.15*delta)
            elif k=='topic_progression_tendency' and split_basis:add('OPTIONAL_EXPANSION','D',k,.56*delta)
            elif k=='ellipsis_and_understatement':add('MINIMAL_REPLY','D',k,.35*delta)
            elif k=='question_initiation_propency' and out['allow_follow_up_question'] and out.get('follow_up_need'):
                add('OPTIONAL_EXPANSION','D',k,.12*delta)
            elif k=='question_initiation_propensity' and out['allow_follow_up_question'] and out.get('follow_up_need'):
                add('OPTIONAL_EXPANSION','D',k,.12*delta)
        # Short-term state can favour yielding in an actual demanding exchange;
        # it never creates a split purpose or an ungrounded clarification.
        if act=='complaint' and e and e['stress'] is not None:
            add('RESPOND_AND_YIELD','E','stress_in_complaint',max(0,e['stress']-.25)*.15)
        if isinstance(ed,dict):
            ed_intent=ed.get('expressive_intent')
            ed_act=float(ed.get('activation',.45));ed_urg=float(ed.get('urgency',.40))
            if ed_intent in ('BACKCHANNEL','DEFER','LISTEN','CLOSE'):
                add('MINIMAL_REPLY','ED','expressive_intent:'+ed_intent,max(.04,.16*(1.-ed_urg)))
            elif ed_intent=='TAKE_TURN' and ed_act>=.65 and allowed_burst:
                add('OPTIONAL_EXPANSION','ED','high_expressive_drive_take_turn',.14*(ed_act-.5))
            elif ed_intent in ('TAKE_TURN','INITIATE','CONTINUE'):
                add('RESPOND_AND_YIELD','ED','expressive_activation',.14*(ed_act-.5))
                add('MINIMAL_REPLY','ED','expressive_activation',-.14*(ed_act-.5))
    scores=[{'strategy':k,'base':v,'terms':terms[k],'score':round(v+sum(t['delta'] for t in terms[k]),6)} for k,v in candidates.items()]
    selected=max(scores,key=lambda r:r['score'])['strategy']
    if not any(terms.values()):selected=initial  # No new evidence: preserve the existing planner.
    if selected=='CASUAL_BURST' and not (allowed_burst or not room):selected='RESPOND_AND_YIELD'
    if action=='silence':selected='NO_ACTION'
    out['candidate_strategy']=selected;out['interaction_state']['proposed_next_move']=selected
    if selected=='CASUAL_BURST' and allowed_burst:out['split_reason']=p['split_reason'][:400]
    traits=trait['known_dispositions'];v=e.get('valence') if e else None;a=e.get('arousal') if e else None
    mood=m.get('valence') if m else None;reg=expression.get('expression_strategy','none') if e else 'none'
    # Expression quality/intensity, not a bubble quota. Unknown values have no term.
    tone_terms={}
    if action!='silence':
        if v is not None:tone_terms['event_valence']=round(.72*v,6)
        if mood is not None:tone_terms['mood_valence']=round(.18*mood,6)
        if a is not None and v is not None:tone_terms['arousal_modulation']=round(.10*(a-.25)*v,6)
    tone_score=sum(tone_terms.values());tone='restrained' if reg=='expressive_suppression' or tone_score<-.15 else 'warm' if tone_score>.15 else 'steady'
    if action=='silence':tone='no_action'
    expr_intensity=expression.get('intensity') if e is not None and action!='silence' else None
    def usage(name,status,basis):uses.append({'condition':name,'status':status,'basis':basis})
    d_read=[{'strategy':r['strategy'],'field':t['field'],'delta':t['delta']} for r in scores for t in r['terms'] if t['channel']=='D']
    e_read=[{'strategy':r['strategy'],'field':t['field'],'delta':t['delta']} for r in scores for t in r['terms'] if t['channel']=='E']
    ed_read=[{'strategy':r['strategy'],'field':t['field'],'delta':t['delta']} for r in scores for t in r['terms'] if t['channel']=='ED']
    usage('long_term_language','scored' if d_read else 'read' if d else 'recorded_only',d_read or ('没有适用的独立示范或已审核倾向，或冻结行动不允许调整策略' if d else '消融：此通道未提供'))
    used_e=e is not None and action!='silence' and (v is not None or a is not None or bool(e_read))
    usage('emotion','scored' if used_e else 'read' if e else 'recorded_only',{'strategy_terms':e_read,'tone_terms':{k:x for k,x in tone_terms.items() if k!='mood_valence'},'expression_intensity':expr_intensity} if used_e else '未修改候选或外显强度')
    usage('mood','scored' if tone_terms.get('mood_valence') else 'read' if m else 'recorded_only',{'tone_delta':tone_terms.get('mood_valence')} if m else '消融：未提供心境')
    if ed is not None:
        usage('expressive_drive','scored' if ed_read else 'read',{'strategy_terms':ed_read,'intent':ed.get('expressive_intent'),'activation':ed.get('activation'),'urgency':ed.get('urgency'),'persistence':ed.get('persistence')})
    p_read=[{'strategy':r['strategy'],'field':t['field'],'delta':t['delta']} for r in scores for t in r['terms'] if t['channel']=='P']
    usage('stable_trait','scored' if p_read else 'read',p_read or '本轮没有适用的已提供人格条件项，或行动约束不允许策略调整')
    usage('situation','scored' if room else 'read',{'speech_act':act,'grounded_split_purpose':bool(split_basis),'frozen_action':action,'gate':decision.get('gate')})
    usage('observed_ai','recorded_only','只记录实际行为；未将生成内容作为本轮策略学习目标')
    out['person_id']=s['person'];out['joint_decision']={'schema':SCHEMA,'event':copy.deepcopy(s),'language_version':d['version'] if d else None,
        'trait_version':trait['version'],'trait_digest':trait['digest'],'emotion_revision':e['revision'] if e else None,'emotion_as_of':e['as_of'] if e else None,
        'mood_as_of':m['as_of'] if m else None,'expressive_drive_revision':ed.get('state_revision') if ed else None,
        'expressive_drive_intent':ed.get('expressive_intent') if ed else None,
        'usage':uses,'scores':scores,'strategy_before':initial,'strategy_after':selected,
        'language_evidence':evidence,'source_event_ids':d['source_event_ids'] if d else [],
        'tone':tone,'tone_terms':tone_terms,'expression_intensity':expr_intensity,'grounded_split_purpose':bool(split_basis),
        'frozen_action':action,'boundary_gate':decision.get('gate'),'calibrated':False,'neural_head':'not_trained',
        'output_causality':'Local score terms are auditable; provider reading does not prove an effect on any individual word.'}
    return out

def event_change(trace):
    def change(before,after,keys):
        return {k:{'before':before.get(k),'after':after.get(k),'delta':round(after[k]-before[k],6) if before.get(k) is not None and after.get(k) is not None else None} for k in keys}
    app=trace['appraisal'];return {'appraisal_id':app['id'],'event_id':app['event_id'],'clock':app.get('clock'),
        'emotion':change(trace['emotion_before'],trace['emotion_state'],AXES),'mood':change(trace.get('mood_before',{}),trace['mood_state'],('valence','arousal','dominance')),
        'regulation':trace['regulation_action']['strategy'],'trait_sources':app.get('evidence_provenance',{}).get('trait_inputs',{})}

def timeline(engine,offset=0,limit=12):
    """Join owner-only facts by turn, never infer delivery from generated text."""
    p=engine.store.meta('pmm_pragmatics') or {};feedback={}
    for f in p.get('human_feedback',[]):feedback.setdefault(f['turn_id'],[]).append({k:f.get(k) for k in ('rating','targets','note','at')})
    ids={r['turn_id'] for r in p.get('observed_ai',[])};rows=[]
    for r in p.get('observed_ai',[]):rows.append((r['at'],r['turn_id'],r,True))
    with engine.journal.lock:
        pending=engine.journal.db.execute("SELECT id,json_extract(payload,'$.started_at') AS at FROM runs WHERE json_type(payload,'$.interaction_plan')='object' AND coalesce(json_extract(payload,'$.memory_commit_status'),'')!='COMMITTED'").fetchall()
    for r in pending:
        if r['id'] not in ids:rows.append((r['at'],r['id'],None,False))
    rows.sort(reverse=True,key=lambda x:(x[0],x[1]));selected=[];offset=max(0,int(offset));limit=max(1,min(30,int(limit)))
    page=rows[offset:offset+limit];actual_parts={}
    if page:
        for msg in engine.store.rows("SELECT turn_id,content FROM messages WHERE role='assistant' AND content!='' AND turn_id IN ("+','.join('?'*len(page))+") ORDER BY created_at,id",[r[1] for r in page]):actual_parts.setdefault(msg['turn_id'],[]).append(msg['content'])
    for at,tid,r,committed in page:
        if not committed:r=engine.journal.get(tid)
        plan=r.get('plan' if committed else 'interaction_plan') or {};j=plan.get('joint_decision');actual=r.get('actual_bubbles') if committed else 0
        delivery=r.get('status');receipt_ids=r.get('message_ids',[]) if committed else [];steps=r.get('receipt_states',[]) if committed else []
        if not committed:
            facts=engine.journal.delivery(tid)
            if facts:
                delivery=facts['status'];receipt=facts['receipt'];receipt_ids=receipt.get('message_ids') or ([receipt['message_id']] if receipt.get('message_id') is not None else []);actual=len(receipt_ids);steps=receipt.get('steps',[])
        selected.append({'turn_id':tid,'at':at,'scope':plan.get('scope'),'strategy':plan.get('candidate_strategy'),'message_cap':plan.get('message_plan',{}).get('max_bubbles'),
            'planned_bubbles':plan.get('realization',{}).get('generated_bubbles'),'actual_confirmed':actual,'receipt_ids':receipt_ids,'receipt_states':steps,
            'actual_parts':actual_parts.get(tid,[])[:actual],'delivery':delivery,'affect_committed':committed,'joint':j,'feedback':feedback.get(tid,[]),'historical_without_joint_trace':j is None})
    return {'persona_id':engine.store.meta('identity')['id'],'offset':offset,'limit':limit,'total':len(rows),'rows':selected}
