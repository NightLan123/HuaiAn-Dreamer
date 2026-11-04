"""Shareable diagnostics: allowlisted operational metadata, no conversation bodies."""
import json, platform, sys, traceback
from .common import VERSION, now

def exception_frames(ex):
    return {'type':type(ex).__name__,'frames':[{'module':frame.filename.replace('\\','/').rsplit('/',1)[-1],'line':frame.lineno,'function':frame.name} for frame in traceback.extract_tb(ex.__traceback__)]}

def report(app):
    c=app.config.get();inbox=app.store.rows('SELECT status,COUNT(*) AS count FROM inbox GROUP BY status')
    failures=[]
    for r in app.store.recent_events(120):
        p=r['payload']
        if 'fail' in r['kind'] or 'error' in r['kind'] or p.get('ok') is False or p.get('status')=='failed':
            failures.append({'kind':r['kind'],'at':r['created_at'],'exception_type':p.get('exception_type'),'frames':p.get('frames',[])})
    return {'format':'huaian-support/1','version':VERSION,'created_at':now(),'python':sys.version.split()[0],'system':platform.system(),'machine':platform.machine(),
            'general':{k:c[k] for k in ('provider','model','thinking_mode','thinking_adapter','timeout','max_output_tokens')},
            'pmm':{'mode':c['pmm']['mode'],'backend':c['pmm']['backend'],**{k:c['pmm']['api'][k] for k in ('provider','model','thinking_mode','thinking_adapter','timeout','max_output_tokens')}},
            'pmm28':{'mode':c['pmm28']['mode'],'long_term_mode':c['pmm28']['long_term_mode'],'published_version':(app.store.meta('pmm28_models') or {}).get('published'),'catalog_revision':(app.store.meta('pmm28_models') or {}).get('revision',0)},
            'cognition':c['cognition'],'inbox_statuses':inbox,'memory_queue':{k:v for k,v in app.engine.memory_lifecycle.status().items() if k in ('running','pending','failed','curve','calibrated')},
            'failures':failures,'contents':'版本、运行环境、模型选项、队列数量与异常定位；不含密钥、地址、原文、完整配置或原始日志。'}
