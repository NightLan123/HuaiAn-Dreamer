"""Task-specific prompt views. Full source state stays in the existing stores.

Budgets are observable soft targets, never an instruction to silently cut facts.
"""
from __future__ import annotations
import copy,hashlib,json,math,re

SCHEMA='prompt-compiler/2.8.2'
def encoded(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'),sort_keys=True)
def digest(value):return hashlib.sha256(encoded(value).encode('utf8')).hexdigest()

def memory_evidence(memories,knowledge=None):
    required=set((knowledge or {}).get('supporting_ids',[]));out=[];seen=set()
    for row in memories:
        if row.get('relevance',1)<.04 and row.get('id') not in required:continue
        # Scope and source remain part of the key: two speakers' words are not
        # interchangeable even when their text happens to match.
        key=digest([row.get('scope'),row.get('person'),row.get('source_turn'),row.get('content'),row.get('evidence')])
        if key in seen:continue
        seen.add(key)
        out.append({k:copy.deepcopy(row[k]) for k in ('id','scope','person','kind','content','evidence','confidence','source_turn') if k in row})
    return out

def profile_view(profile,query='',purpose='appraisal',policy=None):
    if isinstance(profile.get('role_catalog'),dict):
        return runtime_persona(profile,policy,query=query,purpose=purpose)
    out={k:copy.deepcopy(profile.get(k)) for k in ('id','name','seed','revision','character')}
    style=profile.get('style') or {}
    out['style']={k:copy.deepcopy(style[k]) for k in ('count','p90_chars','vector') if k in style}
    out['boundaries']=[copy.deepcopy(b) for b in profile.get('boundaries',[]) if b.get('enabled')]
    return out

def emotion_view(activity):
    return {k:copy.deepcopy(activity[k]) for k in ('emotion','mood','emotion_state','mood_state') if k in activity}

def relationship_view(relation):
    return {k:copy.deepcopy(relation[k]) for k in ('trust','affection','affiliation','familiarity','interactions','version','humor_tolerance','preferred_addressing','conflict_history') if k in relation}

def boundary_requirements(conditions):
    selected=conditions.get('decision',{}).get('boundary') or {}
    states=[{k:copy.deepcopy(row[k]) for k in ('boundary_id','topic','domain','target','scope','recipient','authority_level','status') if k in row}
        for row in (conditions.get('boundary_model') or {}).get('states',[]) if row.get('boundary_id')==selected.get('active')]
    result={'boundary_policy':copy.deepcopy(selected),'selected_boundaries':states}
    if selected.get('action')=='correct_claim':
        result['claim_memory']=[{k:copy.deepcopy(row[k]) for k in ('id','scope','turn_id','record_id','statement','intent','truth_status','source','external_fact','corrects') if k in row}
            for row in conditions.get('claim_memory',[])]
    return result

def selected_personality(state,policy):
    known=state.get('stable_personality') or {};text=encoded(policy or {}).lower()
    # Selection only; these ranks do not alter the numerical PMM or its weights.
    cues={'sociability':('关系','接续','social'),'patience':('耐心','解释','压力'),
        'humor':('幽默','humor'),'honesty':('知识','核验','证据'),'emotionality':('情绪','安慰')}
    def rank(item):
        key,row=item
        relevant=any(term in text for label,terms in cues.items() if label in key for term in terms)
        return (not relevant,row.get('posterior_uncertainty',1),-abs(row.get('estimate',.5)-.5),key)
    rows=sorted(known.items(),key=rank)[:12]
    return {'source_ref':state.get('state_ref'),'selection':'task_cues_then_known_confidence',
        'items':dict(copy.deepcopy(rows)),'known_count':len(known),'included_count':len(rows)}

def runtime_persona(view,policy=None,*,query='',purpose='generator'):
    """Select current source entries; the complete catalog stays in history.

    Legacy projections remain readable, while catalog-backed projections never
    smuggle the old free-form source through seed/initial_personality again.
    """
    catalog=view.get('role_catalog')
    if isinstance(catalog,dict):
        from .persona_catalog import select_catalog
        scoped_policy={**(policy or {}),'scope':view.get('view_scope') or (policy or {}).get('scope','')}
        selected=select_catalog(catalog,query=query,purpose=purpose,policy=scoped_policy)
        from .role_context import bound_selection
        selected=bound_selection(view,selected)
        result={k:copy.deepcopy(view[k]) for k in ('schema','id','name','profile_id','version_id','profile_revision',
            'source_profile_revision','source_digest','compiler_version','learned_revision','view_scope','projection',
            'style','boundaries','reviewed_tendencies','stable_personality') if k in view}
        result['character']={'self_reference':copy.deepcopy(view.get('character',{}).get('self_reference','我'))}
        # Existing typed policy fields are authoritative and already included.
        # Do not repeat their text as source entries in the same prompt.
        typed_paths=('boundaries','stable_personality','reviewed_tendencies')
        def paths(row):
            values=[row.get('source_path')]
            for origin in row.get('origins',row.get('sources',[])):
                if isinstance(origin,dict):values.append(origin.get('source_path',origin.get('path')))
            return [str(value).lstrip('$').strip('/.').replace('/','.') for value in values if value]
        def already_typed(path):
            return path in ('name','character.self_reference') or any(
                path==key or path.startswith(key+'.') or path.startswith(key+'[') for key in typed_paths)
        selected_rows=[row for row in selected.get('entries',[])
            if not paths(row) or not all(already_typed(path) for path in paths(row))]
        # Entry ID + source version resolves detailed spans in the local catalog.
        # The model needs the source's nature, scope, time and exact text, not a
        # repeat of every original span or classification diagnostic per entry.
        entry_fields=('id','text','source_type','scope','time','time_reference','categories','weight','confidence','development_id','epistemic_status')
        selected_ids={row['id'] for row in selected_rows}
        entries=[]
        for row in selected_rows:
            entry={key:copy.deepcopy(row[key]) for key in entry_fields if key in row}
            # Keep a selected situation/response pair understandable without
            # copying its full original source paths into every model prompt.
            pattern_fields=sorted({path.rsplit('.',1)[-1] for path in paths(row)
                if path.startswith('owner_material.patterns.')})
            if pattern_fields:entry['pattern_fields']=pattern_fields
            for key in ('related_entry_ids','context_ids'):
                refs=[identifier for identifier in row.get(key,[]) if identifier in selected_ids]
                if refs:entry[key]=refs
            entries.append(entry)
        result['role_entries']=entries
        if view.get('role_context'):result['role_context']=copy.deepcopy(view['role_context'])
        selection=selected.get('selection') or {}
        reasons=selection.get('reasons') or {}
        result['role_selection']={
            'purpose':purpose,'source_version_id':view.get('version_id'),
            'included_count':len(entries),'omitted_count':len(selection.get('omitted_ids',[])),
            'represented_in_fields_count':len(selected.get('entries',[]))-len(entries),
            'included_categories':copy.deepcopy(selection.get('included_categories',[])),
            'reasons':{k:copy.deepcopy(v) for k,v in reasons.items() if k in selected_ids} if isinstance(reasons,dict) else [],
            'source_policy':'current_version_entries_only; owner_settings_are_not_observed_events'}
    else:
        result=copy.deepcopy(view)
    if 'stable_personality' in result:
        result['stable_personality']=selected_personality({'stable_personality':result['stable_personality']},policy)['items']
    return result

def prospective(context):
    """Pre-generation attention uses source views, not full psychological state."""
    result=copy.deepcopy(context)
    if 'self' in result:
        view=result['self']
        query='\n'.join(str(row.get('text','')) for row in result.get('records',[]) if isinstance(row,dict))
        if isinstance(view.get('role_catalog'),dict):
            result['self']=runtime_persona(view,query=query,purpose='prospective')
            result['self'].pop('stable_personality',None)
        else:
            result['self']={k:copy.deepcopy(view[k]) for k in ('id','name','seed','character','beliefs','patterns','boundaries','reviewed_tendencies','version_id','profile_revision','source_digest') if k in view}
        result['self']['selected_personality']=selected_personality({'stable_personality':view.get('stable_personality',{})},
            {'content_goal':'判断事件与当前主体人格、情绪和关系的相关性'})
    if 'activity' in result:
        result['activity']=emotion_view(result['activity'])
        # Keep different values and legacy-only channels; omit exact mirrors.
        for legacy,current in (('emotion','emotion_state'),('mood','mood_state')):
            rich=result['activity'].get(current)
            if isinstance(rich,dict) and isinstance(result['activity'].get(legacy),dict):
                unique={k:v for k,v in result['activity'][legacy].items() if k not in rich or rich[k]!=v}
                if unique:result['activity'][legacy]=unique
                else:result['activity'].pop(legacy)
    if 'relationship' in result:
        relation=result['relationship'];result['relationship']=relationship_view(relation)
        if isinstance(relation.get('dyad'),dict):
            # policy_relation's .5 defaults are numerical action baselines,
            # not observed trust/affiliation. Keep the source nulls explicit.
            source=relation['dyad'];view=result['relationship']
            view.update(trust=source.get('trust'),affection=source.get('affiliation'))
            view['unknown_fields']=[key for key in ('trust','affection') if view[key] is None]
            view['action_baseline']={key:relation[key] for key in view['unknown_fields'] if key in relation}
            if 'baseline_note' in relation:view['baseline_note']=relation['baseline_note']
            view['source_identity']={key:copy.deepcopy(source[key]) for key in ('other_id','context_id') if key in source}
            view['preferences']={key:copy.deepcopy(value) for key,value in source.get('preferences',{}).items() if value is not None}
            for key in ('familiarity_provenance','preferred_addressing','conflict_history','shared_jokes','uncertainties','schema_revision'):
                if key in source:view[key]=copy.deepcopy(source[key])
            view['source_evidence']=copy.deepcopy(source.get('belief_provenance',[]))
            view['schemata']=[{key:copy.deepcopy(value) for key,value in row.items() if key!='history'}
                for row in source.get('schemata',[]) if row.get('status')=='active']
    result['human_calibration']=[{k:copy.deepcopy(row[k]) for k in ('id','targets','evidence','source') if k in row}
        for row in result.get('human_calibration',[])]
    return result

def feedback(context):
    """Lossless registry rows and only the feedback task's current conditions."""
    out=copy.deepcopy(context)
    fields=('id','name_zh','minimum','maximum','construct_kind','feature_temporality')
    registry=out.get('construct_registry',[])
    if isinstance(registry,list):
        out['construct_registry']={'columns':list(fields),'rows':[[row.get(key) for key in fields] for row in registry],
            'unknown_policy':'omit_unobserved; no_default_midpoint'}
    dispositions=out.get('disposition_registry') or {};fields=('id','name_zh','kind','required_timeframe','minimum','maximum')
    if isinstance(dispositions,dict):
        out['disposition_registry']={'schema':dispositions.get('schema'),'columns':list(fields),
            'rows':[[row.get(key) for key in fields] for row in dispositions.get('fields',[])],
            'temporality':'long','encoder_extension':False,'unknown_policy':'omit_unobserved'}
    def turn(row):
        row=copy.deepcopy(row)
        row['decision']={key:copy.deepcopy(row.get('decision',{}).get(key)) for key in ('action','gate','knowledge','boundary')}
        if 'previous_emotion' in row:row['previous_emotion']=emotion_view(row['previous_emotion'])
        row['memories']=memory_evidence(row.get('memories',[]))
        return row
    if isinstance(out.get('turns'),list):out['turns']=[turn(row) for row in out['turns']]
    else:out=turn(out)
    return out

def appraisal(context):
    packet=context.get('event_packet') or context.get('understanding',{}).get('event_packet')
    return {'input':context['input'],'event_packet':copy.deepcopy(packet),
        'understanding':{k:copy.deepcopy(context.get('understanding',{}).get(k)) for k in ('intent','semantic','knowledge_need','knowledge_confidence','keywords','boundary_cues','relational_appraisal')},
        'self':profile_view(context.get('self',{}),query=context['input'],purpose='appraisal',policy=context.get('understanding')),'activity':emotion_view(context.get('activity',{})),
        'relationship':relationship_view(context.get('relationship',{})),
        'memories':memory_evidence(context.get('memories',[])),
        'role_index':copy.deepcopy(context.get('role_index')),
        'appraisal_registry':copy.deepcopy(context.get('appraisal_registry',[])),
        'boundary_context':copy.deepcopy(context.get('boundary_context',{}))}

def generator(conditions,persona,policy,history,*,query=''):
    decision=conditions['decision'];style=conditions.get('style',{})
    query=query or conditions.get('input') or conditions.get('current_input') or ''
    view=runtime_persona(persona.get('generator_view',{}),policy,query=query,purpose='generator')
    stable=view.pop('stable_personality',{})
    compact={
        'self':copy.deepcopy(view),
        'persona_view_revision':persona.get('version_id',persona.get('id')),
        'decision':{k:copy.deepcopy(decision[k]) for k in ('action','gate','reason','knowledge','boundary','decision_id','decision_revision','selected_proposal_id','expressive_drive') if k in decision},
        'response_policy':copy.deepcopy(policy),
        'emotion':emotion_view(conditions.get('emotion',{})),
        'relationship':relationship_view(conditions.get('relationship',{})),
        'memories':memory_evidence(conditions.get('memories',[]),decision.get('knowledge')),
        'visual_observation':copy.deepcopy(conditions.get('visual_observation')),
        'style':{k:copy.deepcopy(style[k]) for k in ('max_chars','decoded_vector','instruction','api_language_condition') if k in style},
        'interaction_plan':{k:copy.deepcopy(conditions.get('interaction_plan',{}).get(k)) for k in
            ('plan_id','candidate_strategy','local_goal','previous_act','sufficiency_target','allow_follow_up_question','max_bubbles','message_plan','stop_after_reply','expressive_drive') if k in conditions.get('interaction_plan',{})},
        'expression_plan':{k:copy.deepcopy(conditions.get('expression_plan',{}).get(k)) for k in ('intensity','regulation_v2','delivery_tone','expressive_drive') if k in conditions.get('expression_plan',{})},
        'identity_context':copy.deepcopy(conditions.get('identity_context',{})),
        'group_context':copy.deepcopy(conditions.get('group_context',[])),
        'social_knowledge_rule':conditions.get('social_knowledge_rule')}
    # Keep one complete copy per distinct drive, within this request only.
    drive_locations = {}
    for section in ('decision', 'interaction_plan', 'expression_plan'):
        plan = compact[section]
        if isinstance(plan.get('expressive_drive'), dict):
            signature = encoded(plan['expressive_drive'])
            if signature in drive_locations:
                del plan['expressive_drive']
                plan['expressive_drive_ref'] = drive_locations[signature]
            else:
                drive_locations[signature] = section + '.expressive_drive'
    compact['boundary_requirements']=boundary_requirements(conditions)
    compact['selected_personality']=selected_personality(conditions.get('shared_subject_state') or {'stable_personality':stable},policy)
    # Examples are language evidence, not facts about the present speaker.
    examples=[];seen=set()
    for row in style.get('examples',[]):
        key=digest([row.get('record_id'),row.get('input'),row.get('output')])
        if key not in seen:
            seen.add(key);examples.append({k:row.get(k) for k in ('record_id','input','output','function')})
    if examples:compact['language_examples']={'source_type':'style_only_not_current_facts','items':examples}
    # Nearby history retains its sequence and speaker. It is never deduplicated
    # across different people or conflated with retrieved private memories.
    kept=copy.deepcopy(history[-6:])
    names={'self':'persona_view','decision':'plan','response_policy':'selected_policy','emotion':'emotion_current',
        'relationship':'relationship','memories':'memory_evidence','identity_context':'identity_context'}
    sections=[]
    for key,value in compact.items():
        raw=encoded(value);sections.append({'section_id':names.get(key,key),'source_ref_digest':digest(value),
            'chars':len(raw),'bytes':len(raw.encode('utf8')),'estimate_tokens':math.ceil(len(raw.encode('utf8'))/4),
            'tokenizer_id':'utf8-bytes-div4-heuristic/1','included_reason':'current_task_required'})
    sections.append({'section_id':'history','source_ref_digest':digest(kept),'chars':len(encoded(kept)),
        'estimate_tokens':math.ceil(len(encoded(kept).encode('utf8'))/4),'tokenizer_id':'utf8-bytes-div4-heuristic/1','included_reason':'nearby_conversation'})
    receipt={'schema':SCHEMA,'phase':'generation','persona_version_id':persona.get('version_id',persona.get('id')),
        'original_condition_bytes':len(encoded(conditions).encode('utf8')),'compiled_condition_bytes':len(encoded(compact).encode('utf8')),
        'sections':sections,'budget_target':5000,'estimate_only':True,'source_state_deleted':False,
        'removed_full_objects':['pmm_decoded','trait_prior','decision_conditions','de_conditions','coordinated_pmm','interlocutor']}
    if view.get('role_selection'):
        receipt['persona_selection']=copy.deepcopy(view['role_selection'])
    receipt['soft_warning']=sum(r['estimate_tokens'] for r in sections)>receipt['budget_target']
    return compact,kept,receipt
