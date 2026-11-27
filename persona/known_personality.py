"""Read confirmed source estimates, never infer traits from a candidate reply."""
import copy,math,hashlib,json
from .registry import LONG_IDS

def known_personality(profile):
    out={}
    for key,row in (profile.get('psychology',{}).get('features') or {}).items():
        if key not in LONG_IDS or not isinstance(row,dict) or row.get('known') is False or row.get('stale'):continue
        if row.get('source_type') not in ('owner_seed','promoted_evidence','questionnaire','longitudinal_estimate'):continue
        if row.get('scope','agent_self')!='agent_self' or not row.get('evidence_ids'):continue
        if row.get('status') in ('unknown','candidate','uncalibrated'):continue
        value=row.get('estimate');uncertainty=row.get('posterior_uncertainty')
        if type(value) not in (int,float) or not math.isfinite(value):continue
        if type(uncertainty) not in (int,float) or not math.isfinite(uncertainty) or not 0<=uncertainty<=1:continue
        out[key]={k:copy.deepcopy(row[k]) for k in ('estimate','posterior_uncertainty','status','source_type','method_version') if k in row}
        out[key].update(source_evidence_digest=hashlib.sha256(json.dumps(row['evidence_ids'],sort_keys=True).encode()).hexdigest(),evidence_count=len(row['evidence_ids']))
    for key,row in (profile.get('trait_profile',{}).get('dispositions') or {}).items():
        if not isinstance(row,dict) or row.get('source_type') not in ('owner_seed','questionnaire','promoted_evidence'):continue
        if row.get('source_type')=='promoted_evidence' and not row.get('evidence'):continue
        value=row.get('estimate');uncertainty=row.get('uncertainty')
        if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:continue
        if type(uncertainty) not in (int,float) or not math.isfinite(uncertainty) or not 0<=uncertainty<=1:continue
        out[key]={'estimate':value,'posterior_uncertainty':uncertainty,'source_type':row['source_type'],
            'evidence_digest':hashlib.sha256(json.dumps({'evidence':row.get('evidence',[]),'measurement':row.get('measurement')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()}
    return out


def operative_personality(profile):
    """Role conditions, not a claim that inferred traits are measurements.

    Keep the strict reader above for measurement/estimator gates. Existing
    evidenced role estimates may condition behaviour with their uncertainty;
    generated replies, withdrawn evidence and other people's traits cannot.
    """
    out=known_personality(profile)
    records={r['id']:r for r in profile.get('source_records',[])+profile.get('psychology',{}).get('evidence_records',[]) if isinstance(r,dict) and r.get('id')}
    def eligible(record,source_type):
        if not record or record.get('withdrawn') or record.get('source') not in ('human','imported','observed','owner','owner_seed'):
            return False
        if record.get('role')=='assistant' and source_type=='experience_derived':
            from .traits import confirmed_behavior
            return confirmed_behavior(record,records)
        return record.get('role') not in ('assistant','system','tool')
    for key,row in (profile.get('psychology',{}).get('features') or {}).items():
        if key in out or key not in LONG_IDS or not isinstance(row,dict):continue
        if row.get('source_type') not in ('inferred','experience_derived') or row.get('scope','agent_self')!='agent_self':continue
        if row.get('stale') or row.get('conflict') or row.get('known') is False or row.get('status') in ('unknown','rejected','withdrawn'):continue
        v=row.get('estimate');unc=row.get('posterior_uncertainty');ids=row.get('evidence_ids') or []
        if type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1:continue
        if type(unc) not in (int,float) or not math.isfinite(unc) or not 0<=unc<=1:continue
        if not ids or not all(eligible(records.get(i),row['source_type']) for i in ids):continue
        out[key]={'estimate':v,'posterior_uncertainty':max(.25,unc),'source_type':row['source_type'],
                  'status':'role_estimate','formal_measurement':False,'evidence_count':len(ids),
                  'source_evidence_digest':hashlib.sha256(json.dumps(ids,sort_keys=True).encode()).hexdigest()}
    for key,row in (profile.get('trait_profile',{}).get('dispositions') or {}).items():
        if key in out or row.get('source_type')!='experience_derived':continue
        ids=[e.get('record_id') for e in row.get('evidence',[])];v=row.get('estimate');unc=row.get('uncertainty')
        if not ids or any(i not in records or records[i].get('withdrawn') or records[i].get('evidence_kind')!='experienced_event' for i in ids):continue
        from .traits import confirmed_behavior
        if any(records[i].get('evidence_channel')=='delivered_action' and not confirmed_behavior(records[i],records) for i in ids):continue
        if type(v) in (int,float) and type(unc) in (int,float) and math.isfinite(v) and math.isfinite(unc) and 0<=v<=1 and 0<=unc<=1:
            out[key]={'estimate':v,'posterior_uncertainty':max(.25,unc),'source_type':'experience_derived','status':'role_estimate','formal_measurement':False,'evidence_count':len(ids)}
    return out
