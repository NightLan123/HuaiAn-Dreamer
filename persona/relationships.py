"""Context-specific dyads, source-backed preferences and observable trajectories."""
import copy, hashlib, math
from .common import now,clamp
from .registry import digest

PREFERENCES=('humor_tolerance','action_preference','empathy_need','directness','boundary_sensitivity','information_density')
def key(person,scope):return hashlib.sha256((scope+'|'+person).encode()).hexdigest()[:32]
def empty(person,scope):
    return {'schema_version':'2.1.0','other_id':person,'context_id':scope,'trust':None,'familiarity':0.,'affiliation':None,
        'interactions':0,'preferences':{k:None for k in PREFERENCES},'conflict_history':[],'shared_jokes':[],
        'preferred_addressing':None,'belief_provenance':[],'trajectory':[],'updated_at':None}
def policy_relation(d):
    d=ensure(d)
    d['schema_history']=[]
    d['schemata']=[{k:copy.deepcopy(v) for k,v in r.items() if k!='history'} for r in d['schemata'] if r['status']=='active'][-20:]
    for field in ('trajectory','belief_provenance','conflict_history','shared_jokes'):d[field]=d[field][-20:]
    return {'trust':d['trust'] if d['trust'] is not None else .5,'familiarity':d['familiarity'],
        'affection':d['affiliation'] if d['affiliation'] is not None else .5,'interactions':d['interactions'],'dyad':copy.deepcopy(d),
        'baseline_note':'缺少信任/亲近证据时，程序用 .5 作为行动计算基线；记录值仍为 null。'}
def _update_legacy(d,feedback,text,turn_id,action,reply_style,count_interaction=True,strength=1.):
    out=copy.deepcopy(d);accepted=[];rejected=0
    rows=feedback.get('relationship_updates',[])
    if not isinstance(rows,list):rows=[]
    for row in rows[:20] if strength>0 else []:
        if not isinstance(row,dict):rejected+=1;continue
        q=row.get('quote');field=row.get('field')
        if any(ev.get('turn_id')==turn_id and ev.get('field')==field and ev.get('quote')==q for ev in out['belief_provenance']):continue
        if not isinstance(q,str) or not q.strip() or q not in text:rejected+=1;continue
        try:
            if field in (*PREFERENCES,'trust','affiliation','familiarity'):
                value=row.get('estimate')
                if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:raise ValueError()
                target=out['preferences'] if field in PREFERENCES else out;old=target[field]
                target[field]=value if old is None else old+clamp(value-old,-.03*strength,.03*strength)
            elif field=='shared_jokes':
                if not any(v['quote']==q for v in out[field]):out[field].append({'quote':q,'turn_id':turn_id})
            elif field=='preferred_addressing':out[field]=q[:100]
            elif field=='conflict_history':out[field].append({'quote':q,'turn_id':turn_id})
            else:raise ValueError()
            evidence={'field':field,'quote':q,'turn_id':turn_id,'timestamp':now(),'source':'user_statement'}
            out['belief_provenance'].append(evidence);accepted.append(evidence)
        except (ValueError,TypeError):rejected+=1
    already_counted=any(r.get('turn_id')==turn_id for r in out['trajectory'])
    count_interaction=count_interaction and not already_counted
    out['interactions']+=int(count_interaction);out['updated_at']=now()
    out.setdefault('familiarity_provenance','legacy_count_prior' if out['familiarity'] else 'unknown_or_owner_evidence')
    if any(e['field']=='familiarity' for e in accepted):out['familiarity_provenance']='grounded_statement'
    out['exposure_count']=out['interactions']
    if count_interaction:out['trajectory'].append({'turn_id':turn_id,'timestamp':now(),'action':action,'reply_style':reply_style,
        'interlocutor_emotion':feedback.get('interlocutor_emotion') if isinstance(feedback.get('interlocutor_emotion'),dict) and feedback['interlocutor_emotion'].get('quote') and feedback['interlocutor_emotion']['quote'] in text else None,
        'trust':out['trust'],'affiliation':out['affiliation'],'accepted_updates':len(accepted)})
    return out,{'accepted':len(accepted),'rejected':rejected}
def validate(dyads):
    if not isinstance(dyads,dict):raise ValueError('情境关系档案无效')
    for identifier,d in dyads.items():
        if not isinstance(d,dict) or not isinstance(d.get('other_id'),str) or not isinstance(d.get('context_id'),str) or identifier!=key(d['other_id'],d['context_id']) or d.get('schema_version')!='2.1.0':raise ValueError('关系对象或情境不匹配')
        if not isinstance(d.get('preferences'),dict) or set(d['preferences'])!=set(PREFERENCES):raise ValueError('关系偏好字段缺失')
        for value in [d.get('trust'),d.get('affiliation'),d.get('familiarity'),*d['preferences'].values()]:
            if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1):raise ValueError('关系数值无效')
        for field in ('conflict_history','shared_jokes','belief_provenance','trajectory'):
            if not isinstance(d.get(field),list):raise ValueError('关系历史字段无效')
        if type(d.get('interactions')) is not int or d['interactions']<0:raise ValueError('关系互动计数无效')
        for ev in d['belief_provenance']:
            if not isinstance(ev,dict) or not isinstance(ev.get('quote'),str) or not ev['quote'].strip() or not isinstance(ev.get('turn_id'),str):raise ValueError('关系证据格式无效')
        validate_schema(d)
    return dyads

SCHEMA_KINDS=('role','norm','expectation')
def ensure(d):
    out=copy.deepcopy(d)
    out.setdefault('schema_revision',0);out.setdefault('schemata',[]);out.setdefault('schema_history',[]);out.setdefault('uncertainties',{})
    out.setdefault('entities',{'self':'agent_self','other':d['other_id'],'scope':d['context_id'],'kind':'specific_dyad'})
    return out

def validate_schema(d):
    if 'schema_revision' not in d:return
    if type(d['schema_revision']) is not int or d['schema_revision']<0 or not isinstance(d.get('schemata'),list) or not isinstance(d.get('schema_history'),list):raise ValueError('关系图式版本或历史无效')
    if d.get('entities')!={'self':'agent_self','other':d['other_id'],'scope':d['context_id'],'kind':'specific_dyad'}:raise ValueError('关系图式主体身份不匹配')
    if not isinstance(d.get('uncertainties'),dict):raise ValueError('关系不确定性结构无效')
    for value in d['uncertainties'].values():
        v=value.get('estimate') if isinstance(value,dict) else None
        if type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1:raise ValueError('关系不确定性无效')
    seen=set()
    for r in d['schemata']:
        if not isinstance(r,dict) or r.get('id') in seen or r.get('kind') not in SCHEMA_KINDS or r.get('status') not in ('active','disputed','retracted') or r.get('knowledge_type') not in ('reported','inferred'):raise ValueError('关系图式类别或状态无效')
        seen.add(r['id'])
        if not isinstance(r.get('statement'),str) or not r['statement'].strip() or not isinstance(r.get('evidence'),list) or not r['evidence']:raise ValueError('关系图式缺少原文')
        if type(r.get('uncertainty')) not in (int,float) or not math.isfinite(r['uncertainty']) or not 0<=r['uncertainty']<=1:raise ValueError('关系不确定性无效')
        for e in r['evidence']:
            if e.get('scope')!=d['context_id'] or e.get('person')!=d['other_id'] or not isinstance(e.get('quote'),str) or not e['quote']:raise ValueError('关系图式证据越界')

def update(d,feedback,text,turn_id,action,reply_style,count_interaction=True,strength=1.):
    before=ensure(d);rows=feedback.get('relationship_updates',[])
    rows=rows if isinstance(rows,list) else []
    simple=[r for r in rows if not isinstance(r,dict) or r.get('field') not in SCHEMA_KINDS]
    out,report=_update_legacy(before,{**feedback,'relationship_updates':simple},text,turn_id,action,reply_style,count_interaction,strength)
    changes=[]
    for field in (*PREFERENCES,'trust','affiliation','familiarity','shared_jokes','preferred_addressing','conflict_history'):
        a=before['preferences'][field] if field in PREFERENCES else before[field];b=out['preferences'][field] if field in PREFERENCES else out[field]
        if a!=b:
            evidence=[e for e in out['belief_provenance'][len(before['belief_provenance']):] if e['field']==field]
            out['uncertainties'][field]={'estimate':.5,'semantics':'未校准工程不确定性','knowledge_type':'inferred','event_ids':sorted({e['turn_id'] for e in out['belief_provenance'] if e['field']==field})}
            changes.append({'field':field,'before':copy.deepcopy(a),'after':copy.deepcopy(b),'evidence':copy.deepcopy(evidence)})
    for row in [r for r in rows if isinstance(r,dict) and r.get('field') in SCHEMA_KINDS][:20] if strength>0 else []:
        try:
            kind=row['field'];q=row.get('quote');statement=row.get('statement');kt=row.get('knowledge_type');confidence=row.get('confidence',.4)
            if not isinstance(q,str) or not q.strip() or q not in text or not isinstance(statement,str) or not statement.strip() or len(statement)>1000:raise ValueError()
            if kt not in ('reported','inferred') or type(confidence) not in (int,float) or not math.isfinite(confidence) or not 0<=confidence<=1:raise ValueError()
            # 'reported' describes a recorded statement, never verified truth.
            if kt=='reported' and statement not in q:raise ValueError()
            identifier='schema:'+digest([kind,statement])[:24];old=next((r for r in out['schemata'] if r['id']==identifier),None)
            if old and any(e['event_id']==turn_id for e in old['evidence']):continue
            if old and old['status']=='retracted':continue
            ev={'record_id':row.get('record_id',turn_id+':u'),'event_id':turn_id,'scope':d['context_id'],'person':d['other_id'],'quote':q,'source':'recorded_statement','at':now()}
            previous=copy.deepcopy(old)
            if old:
                old['evidence'].append(ev);old['version']+=1
                old['uncertainty']=max(.25,1-min(.75,confidence)*strength)
            else:
                old={'id':identifier,'kind':kind,'statement':statement,'knowledge_type':kt,'uncertainty':max(.25,1-min(.75,confidence)*strength),'status':'active','version':1,'evidence':[ev],'history':[]};out['schemata'].append(old)
            old['history'].append({'version':old['version'],'before':{k:v for k,v in previous.items() if k!='history'} if previous else None,'event_id':turn_id,'at':now()})
            changes.append({'field':kind,'schema_id':identifier,'before':{k:v for k,v in previous.items() if k!='history'} if previous else None,'after':{k:copy.deepcopy(v) for k,v in old.items() if k!='history'},'evidence':[ev]});report['accepted']+=1
        except (ValueError,TypeError,KeyError):report['rejected']+=1
    if changes:
        out['schema_revision']+=1
        out['schema_history'].append({'version':out['schema_revision'],'event_id':turn_id,'changes':changes,'at':now()})
    validate_schema(out);report['schema_revision']=out['schema_revision']
    return out,report

def revise(d,body):
    out=ensure(d)
    if body.get('expected_version')!=out['schema_revision']:raise ValueError('关系图式已变化，请刷新')
    r=next((r for r in out['schemata'] if r['id']==body.get('id')),None);op=body.get('op');reason=str(body.get('reason','')).strip()
    if not r or op not in ('dispute','retract','restore') or not reason:raise ValueError('请指定图式与修订理由')
    before=copy.deepcopy(r);r['status']={'dispute':'disputed','retract':'retracted','restore':'active'}[op];r['version']+=1
    r['owner_review']={'reason':reason[:1000],'at':now(),'source':'owner_annotation'}
    if op=='dispute':r['uncertainty']=max(.75,r['uncertainty'])
    r['history'].append({'version':r['version'],'before':{k:v for k,v in before.items() if k!='history'},'at':now(),'op':op})
    out['schema_revision']+=1;out['schema_history'].append({'version':out['schema_revision'],'schema_id':r['id'],'before':before,'after':copy.deepcopy(r),'reason':reason,'at':now()})
    validate_schema(out);return out

def cognition(traits,understanding,relation,enabled=True):
    """Transparent, bounded relational appraisal; empirical coefficients pending."""
    sem=understanding['semantic'];d=ensure(relation['dyad']);fields=traits['hexaco_facets']|traits['interpersonal_dispositions']|traits['value_priorities']
    read=[]
    def prior(k):
        f=fields.get(k,{});v=f.get('estimate');unc=f.get('posterior_uncertainty')
        if v is None or not enabled:return 0.
        read.append({'feature_id':k,'estimate':v,'uncertainty':unc,'source_type':f.get('source_type')})
        return (v-.5)*2*(1-(unc if unc is not None else 1))
    patience=prior('hexaco.a.patience');prudence=prior('hexaco.c.prudence');communion=prior('social.communion');anxiety=prior('hexaco.e.anxiety')
    uncertainty=d.get('uncertainties',{}).get('trust',{}).get('estimate',.5)
    trust=(d['trust']-.5)*2*(1-uncertainty) if d['trust'] is not None else 0.
    hostility=sem.get('hostility',0);ambiguity=sem.get('ambiguity',0);social=sem.get('social',0)
    threat=clamp(hostility+.12*anxiety*ambiguity-.12*patience*hostility-.1*trust*social)
    clarification=clamp(ambiguity+.15*prudence*ambiguity-.06*trust*social)
    support=clamp(social*.5+.15*communion*social+.1*trust*social)
    return {'schema':'relational-appraisal/1','trait_version':traits['trait_version'],'trait_digest':traits['trait_digest'],'relation_version':d['schema_revision'],
        'scope':d['context_id'],'person':d['other_id'],'self_entity':'agent_self','source_features':read,
        'relationship_sources':[r['id'] for r in d['schemata'] if r['status']=='active'],
        'estimates':{'threat':threat,'clarification_need':clarification,'support_orientation':support},
        'baseline':{'threat':hostility,'clarification_need':ambiguity,'support_orientation':social*.5},
        'interpretation':'可复现工程假设；不更改输入事实、人物身份或长期人格，不代表心理学效度'}
