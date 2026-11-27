"""Independent A/B transport configuration, task probes and verifiable receipts."""
from __future__ import annotations
import copy,time
from .common import now,PROVIDER_FIELDS
from .registry import digest
SERVICE_FIELDS=('provider','base_url','api_key','model','auth_mode','anthropic_version','api_version','extra_headers')
PROBE_CONTRACT={'A':'current-input-appraisal/1','B':'pmm-deliberation/2.8.2'}

def connection(config,role):
    if role not in ('A','B'):raise ValueError('模型角色须为 A 或 B')
    if role=='A':return copy.deepcopy(config['pmm']['api'])
    result=copy.deepcopy(config['pmm281']['b_api'])
    if config['pmm281']['b_share_a']:
        result.update({k:copy.deepcopy(config['pmm']['api'][k]) for k in SERVICE_FIELDS})
    return result

def receipt(config,role):
    c=connection(config,role)
    from urllib.parse import urlsplit
    return {'role':role,'provider':c['provider'],'model':c['model'],'service':urlsplit(c['base_url']).netloc,
        'configuration_sha256':digest(c),'shared_service':role=='B' and config['pmm281']['b_share_a']}

def failure(error):
    detail=getattr(error,'details',{}) or {};wire=(detail.get('call') or {}).get('response') or detail
    status=wire.get('http_status');code=wire.get('code') or wire.get('type') or detail.get('code') or type(error).__name__
    labels={400:'请求参数不兼容',401:'密钥或认证方式错误',403:'模型服务拒绝访问',404:'地址或模型不存在',429:'限流或额度不足',500:'模型服务内部错误',502:'上游服务不可用',503:'模型服务暂时不可用'}
    reason=labels.get(status) or {'TRANSPORT_UNAVAILABLE':'连接失败或请求超时','TimeoutError':'超过本任务超时预算','VALIDATION_FAILED':'模型输出不符合任务契约','INVALID_JSON':'响应不是有效 JSON'}.get(code,'任务输出或协议无效')
    from .support import exception_frames
    if status==429 or code in ('rate_limit_exceeded','rate_limit_error','insufficient_quota','SERVICE_QUOTA'):
        category,reason='service_limit','限流或额度不足'
    elif code in ('VALIDATION_FAILED','INVALID_DELIBERATION','INVALID_JSON'):
        reasons=[r.get('reason','') for r in detail.get('issues',[]) if isinstance(r,dict)]+[detail.get('reason','')]
        category='json_format' if code=='INVALID_JSON' or detail.get('validator')=='json_parser' else 'contract'
        if any(r in ('ungrounded_quote','unknown_current_input_ref','incompatible_appraisal_sources','missing_appraisal_source','missing_fact_source','current_event_required','current_evidence_required','unknown_reference') for r in reasons):
            category='evidence'
    else:
        category='service' if status or code in ('TRANSPORT_UNAVAILABLE','TimeoutError','OUTPUT_LIMIT','EMPTY_RESPONSE','INCOMPLETE_RESPONSE') else 'component'
    out={'error':exception_frames(error),'failure_code':str(code)[:80],'failure_category':category,'http_status':status,'failure_reason':reason}
    if detail.get('repair_skipped'):out['repair_skipped']=detail['repair_skipped']
    # Structured contract location only; never copy rejected private output.
    for key in ('path','reason'):
        if isinstance(detail.get(key),str):out['contract_'+key]=detail[key][:200]
    if isinstance(detail.get('issues'),list):
        out['contract_issues']=[{k:r[k] for k in ('path','reason','code') if k in r} for r in detail['issues'][:16] if isinstance(r,dict)]
    return out

def probe(engine,role,operation='invoke'):

    cfg=engine.config.get();c=connection(cfg,role);start=time.monotonic();result=receipt(cfg,role)
    result.update(operation=operation,at=now(),ok=False)
    try:
        def probe_client(config):
            client=engine.pmm_provider_factory(config)
            client.trace_context={'component_role':'PMM-'+role,'task_name':'connection_'+operation,'trigger_reason':'explicit_connection_test'}
            return client
        if operation in ('models','connect'):client=probe_client(c)
        if operation=='models':output={'models':client.models()}
        elif operation=='connect':output=client.test()
        elif operation=='invoke':
            result['task_contract']=PROBE_CONTRACT[role]
            from .psychology import empty_profile
            from .common import uid
            profile=empty_profile('connection-probe','连接示例');text='请确认这次连接测试已收到。'
            activity={'emotion':{},'mood':{}}
            if role=='A':
                from .pmm_event_reasoner import EventReasoner
                a=EventReasoner(cfg,probe_client)
                from .api_pmm import BudgetedProvider
                a.provider=BudgetedProvider(a.provider,c['timeout'])
                decoded,_=a.prepare(text,{'semantic':{}},profile,activity,{},[],validation_records=[])
                output={'appraisal_count':sum(x is not None for x in decoded['appraisal_checks'].values()),'candidate_actions':list(decoded['action_probabilities']),'task':'event_understanding'}
            else:
                from .pmm_negotiator import Negotiator
                from .deliberation_v282 import build
                context={'input':text,'turn_id':uid(),'scope':'probe','understanding':{'semantic':{}},
                         'emotion':activity,'relationship':{},'memories':[]}
                base=build(context,profile)
                discussion,trace=Negotiator(cfg,probe_client).discuss(base,[])
                output={'task':'internal_negotiation','contract':base['schema'],
                        'evaluated_views':[v['id'] for v in discussion['perspectives']],'trace':trace}
        else:raise ValueError('测试操作无效')
        result.update(ok=True,output=output)
    except Exception as ex:
        result.update(failure(ex))
    result['elapsed_ms']=round((time.monotonic()-start)*1000,3)
    with engine.store.lock,engine.store.db:engine.store.event('pmm281_connection_test',result)
    return result
