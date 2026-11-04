"""Independent A/B transport configuration, task probes and verifiable receipts."""
from __future__ import annotations
import copy,time
from .common import now,PROVIDER_FIELDS
from .registry import digest
SERVICE_FIELDS=('provider','base_url','api_key','model','auth_mode','anthropic_version','api_version','extra_headers')

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
    status=wire.get('http_status');code=wire.get('code') or detail.get('code') or type(error).__name__
    labels={400:'请求参数不兼容',401:'密钥或认证方式错误',403:'模型服务拒绝访问',404:'地址或模型不存在',429:'限流或额度不足',500:'模型服务内部错误',502:'上游服务不可用',503:'模型服务暂时不可用'}
    reason=labels.get(status) or {'TRANSPORT_UNAVAILABLE':'连接失败或请求超时','TimeoutError':'超过本任务超时预算','VALIDATION_FAILED':'模型输出不符合任务契约','INVALID_JSON':'响应不是有效 JSON'}.get(code,'任务输出或协议无效')
    from .support import exception_frames
    return {'error':exception_frames(error),'failure_code':str(code)[:80],'http_status':status,'failure_reason':reason}

def probe(engine,role,operation='invoke'):

    cfg=engine.config.get();c=connection(cfg,role);start=time.monotonic();result=receipt(cfg,role)
    result.update(operation=operation,at=now(),ok=False)
    try:
        client=engine.pmm_provider_factory(c)
        if operation=='models':output={'models':client.models()}
        elif operation=='connect':output=client.test()
        elif operation=='invoke':
            from . import deliberation as dl
            from .psychology import profile_condition
            from .affect_runtime import current_view
            from .affect import compatibility
            profile=engine.profile();text='请确认这次连接测试已收到。'
            activity=compatibility(current_view(engine.store,profile,{'id':'probe','text':text,'person':'web:owner','scope':'private:web:owner'},now()))
            if role=='A':
                from .pmm_event_reasoner import EventReasoner
                a=EventReasoner(cfg,engine.pmm_provider_factory)
                from .api_pmm import BudgetedProvider
                a.provider=BudgetedProvider(a.provider,c['timeout'])
                decoded,_=a.prepare(text,{'semantic':{}},profile,activity,{},[],validation_records=[])
                output={'appraisal_count':sum(x is not None for x in decoded['appraisal_checks'].values()),'candidate_actions':list(decoded['action_probabilities']),'task':'event_understanding'}
            else:
                from .pmm_negotiator import Negotiator
                view=dl.views(profile,{'semantic':{}},{'action_probabilities':{}},{'activated':False},1)
                context={'input':text,'self':profile_condition(profile),'understanding':{'semantic':{}},'emotion':activity,'relationship':{},'memories':[],'projections':view,'last_round':True,'pmm_neural':None,'test_context':True}
                a,_,trace=Negotiator(cfg,engine.pmm_provider_factory).assess(context,view,[])
                output={'task':'internal_negotiation','evaluated_views':[v['id'] for v in a['views']],'trace':trace}
        else:raise ValueError('测试操作无效')
        result.update(ok=True,output=output)
    except Exception as ex:
        result.update(failure(ex))
    result['elapsed_ms']=round((time.monotonic()-start)*1000,3)
    with engine.store.lock,engine.store.db:engine.store.event('pmm281_connection_test',result)
    return result
