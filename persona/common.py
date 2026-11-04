from __future__ import annotations
import json, os, tempfile, math, time, uuid
from pathlib import Path

VERSION = '2.8.1'
SCHEMA = 1

def uid(): return uuid.uuid4().hex

def now(): return time.time()

def clamp(x, low=0.0, high=1.0):
    x = float(x)
    if not math.isfinite(x): raise ValueError('数值必须为有限数字')
    return max(low, min(high, x))

def dumps(x): return json.dumps(x, ensure_ascii=False, allow_nan=False)

def atomic_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(dumps(value)); f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
        try: path.chmod(0o600)
        except OSError: pass
    finally:
        if os.path.exists(name): os.unlink(name)

DEFAULT_CONFIG = {
    'provider': 'ollama', 'base_url': 'http://127.0.0.1:11434', 'api_key': '',
    'model': '', 'controller_model': '', 'json_mode': True, 'timeout': 120,
    'temperature': 0.65, 'send_temperature': True,
    'auth_mode': 'auto', 'max_output_tokens': 4096, 'token_field': 'max_tokens',
    'anthropic_version': '2023-06-01', 'api_version': '2024-10-21',
    'extra_headers': {}, 'extra_body': {}, 'json_repair': True,
    'thinking_mode': 'auto', 'thinking_adapter': 'auto',
    'pmm': {'mode': 'api', 'api': {}, 'backend': 'local', 'base_url': 'http://127.0.0.1:8766', 'api_key': '',
            'model': 'pmm-mlp-v3', 'timeout': 120, 'managed': False},
    'pmm28': {'mode':'shadow','long_term_mode':'candidate_only','reasoner_timeout':15},
    'pmm281': {'mode':'full','b_policy':'auto','b_share_a':True,'b_api':{}},
    'persona_name': '未央',
    'persona_seed': '你叫未央。表达自然、克制，有好奇心和自己的判断。重视诚实与相互尊重；可以不同意，也可以承认不知道。初始没有虚构的人生经历。通过真实对话积累认识与关系。',
    'retrieval_k': 8, 'online_learning': True, 'max_retrieval_rounds': 1,
    'cognition': {'mode':'adaptive','assessment_timeout':30},
    'turn_taking': {'enabled':True,'debounce_seconds':1.5,'max_wait_seconds':12,'decision_timeout_seconds':3},
    'group_attention': {'enabled':False,'allow_unmentioned_reply':False,'per_minute':8,'sample_every':5,'context_chars':6000,'watched_terms':[]},
    'memory': {'enabled':True,'half_life_days':30},
    'social': {'enabled':False,'private_enabled':True,'group_enabled':False,'recipients':[],'idle_minutes':120,'cooldown_minutes':240,'daily_budget':3,'unanswered_limit':1,'quiet_start':'23:00','quiet_end':'08:00','timezone':'Asia/Shanghai'},
    'media': {'receive':True,'send':False,'vision_model':'','download_hosts':['multimedia.nt.qq.com','gchat.qpic.cn','c2cpicdw.qpic.cn','*.qpic.cn']},
    'performance': {'mode':'balanced','qq_only':True,'batch_turns':6,'idle_seconds':90,'work_chars':24000,'reply_chars':180},
    'deliberation': {'enabled':True,'mode':'auto','max_perspectives':4,'max_rounds':2,'log_level':'summary','return_unresolved_conflict':True},
    'qq': {'enabled': False, 'api_url': 'http://127.0.0.1:3000', 'api_token': '',
           'inbound_token': '', 'hmac_secret': '', 'allowed_users': [], 'allowed_groups': [],
           'group_mention_only': True, 'self_id': ''}
}

PROVIDER_FIELDS=('provider','base_url','api_key','model','json_mode','timeout','temperature','send_temperature','auth_mode','max_output_tokens','token_field','anthropic_version','api_version','extra_headers','extra_body','json_repair','thinking_mode','thinking_adapter')
import copy as _copy
DEFAULT_CONFIG['pmm']['api']={k:_copy.deepcopy(DEFAULT_CONFIG[k]) for k in PROVIDER_FIELDS}
DEFAULT_CONFIG['pmm']['api'].update(temperature=.25,send_temperature=False)
DEFAULT_CONFIG['pmm281']['b_api']=_copy.deepcopy(DEFAULT_CONFIG['pmm']['api'])
DEFAULT_CONFIG['pmm281']['b_api']['max_output_tokens']=2048

class ConfigError(ValueError):
    """Validation failure with field paths, never credential values."""
    def __init__(self, message, fields=()):
        super().__init__(message)
        self.failed_fields=list(fields)

def config_shape(value, partial=False):
    if not isinstance(value,dict):raise ConfigError('连接配置必须是 JSON 对象', ['/'])
    for key,default in DEFAULT_CONFIG.items():
        if key not in value:continue
        item=value[key];path='/'+key
        if isinstance(default,dict):
            if partial and key=='extra_headers' and item is None:continue # null retains saved headers in a partial UI update.
            if not isinstance(item,dict):raise ConfigError('配置分区必须是对象：'+key,[path])
            if key=='pmm' and 'api' in item and not isinstance(item['api'],dict):raise ConfigError('API-PMM 连接必须是对象',['/pmm/api'])
            if key=='pmm281' and 'b_api' in item and not isinstance(item['b_api'],dict):raise ConfigError('模型 B 连接必须是对象',['/pmm281/b_api'])
    return value

class Config:
    def __init__(self, directory):
        import threading, copy
        self.path = Path(directory) / 'config.json'; self.lock = threading.RLock()
        if not self.path.exists():
            cfg = copy.deepcopy(DEFAULT_CONFIG); cfg['qq']['inbound_token'] = uid() + uid()
            atomic_json(self.path, cfg)
        self.get()

    def get(self):
        with self.lock:
            import copy
            raw = config_shape(json.loads(self.path.read_text('utf-8')))
            v = copy.deepcopy(DEFAULT_CONFIG)
            v.update({k:x for k,x in raw.items() if k not in ('qq','pmm','deliberation','performance','media','social','turn_taking','group_attention','memory','cognition','pmm28','pmm281')})
            v['deliberation'].update(raw.get('deliberation',{}))
            for section in ('turn_taking','group_attention','memory','cognition','pmm28','pmm281'):v[section].update(raw.get(section,{}))
            v['performance'].update(raw.get('performance',{}))
            v['media'].update(raw.get('media',{}))
            v['social'].update(raw.get('social',{}))
            v['qq'].update(raw.get('qq',{}))
            v['pmm'].update({k:x for k,x in raw.get('pmm',{}).items() if k!='api'})
            v['pmm']['api'].update(raw.get('pmm',{}).get('api',{}))
            v['pmm281']={**DEFAULT_CONFIG['pmm281'],**raw.get('pmm281',{})}
            v['pmm281']['b_api']={**_copy.deepcopy(DEFAULT_CONFIG['pmm281']['b_api']),**raw.get('pmm281',{}).get('b_api',{})}
            v['pmm28']['mode']='active' if v['pmm281']['mode']=='full' else 'legacy'
            if 'mode' not in raw.get('pmm',{}):v['pmm']['mode']='legacy'
            self.validate(v)
            return v

    def public(self):
        c = self.get(); c['has_api_key'] = bool(c.pop('api_key', ''))
        a=c['pmm']['api'];a['has_api_key']=bool(a.pop('api_key',''));a['has_extra_headers']=bool(a.get('extra_headers'));a['extra_header_names']=list(a.pop('extra_headers',{}))
        b=c['pmm281']['b_api'];b['has_api_key']=bool(b.pop('api_key',''));b['has_extra_headers']=bool(b.get('extra_headers'));b['extra_header_names']=list(b.pop('extra_headers',{}))
        c['pmm']['has_api_key']=bool(c['pmm'].pop('api_key',''))
        c['has_extra_headers']=bool(c['extra_headers']);c['extra_header_names']=list(c['extra_headers']);c.pop('extra_headers')
        for k in ['api_token', 'inbound_token', 'hmac_secret']:
            c['qq']['has_' + k] = bool(c['qq'].pop(k, ''))
        return c

    @staticmethod
    def validate(c, validate_pmm_api=True):
        try:return Config._validate(c,validate_pmm_api)
        except (TypeError,KeyError,AttributeError,OverflowError):
            raise ConfigError('配置字段类型错误或缺少必填项，请核对数字、开关和连接分区',['/']) from None

    @staticmethod
    def _validate(c, validate_pmm_api=True):
        config_shape(c)
        if c.get('pmm281',DEFAULT_CONFIG['pmm281']).get('mode') not in ('full','compatibility') or c.get('pmm281',DEFAULT_CONFIG['pmm281']).get('b_policy') not in ('auto','always'):raise ValueError('PMM 应用方式或协商策略无效')
        if type(c.get('pmm281',DEFAULT_CONFIG['pmm281']).get('b_share_a')) is not bool:raise ValueError('共用 A 连接开关必须为布尔值')
        v28=c.get('pmm28',DEFAULT_CONFIG['pmm28'])
        if v28.get('mode') not in ('legacy','shadow','active') or v28.get('long_term_mode') not in ('disabled','candidate_only','validated_commit'):raise ValueError('PMM 2.8 模式无效')
        t=v28.get('reasoner_timeout')
        if type(t) not in (int,float) or not math.isfinite(t) or not 1<=t<=60:raise ValueError('PMM 2.8 内部推理预算须为 1–60 秒')
        from .provider import validate_url, PROTOCOLS, AUTH_MODES
        import re
        from .thinking import MODES, ADAPTERS
        if c.get('thinking_mode','auto') not in MODES or c.get('thinking_adapter','auto') not in ADAPTERS:raise ValueError('Thinking 模式或适配器无效')
        if c.get('provider') not in PROTOCOLS: raise ValueError('未知模型协议')
        validate_url(c['base_url'])
        validate_url(c['qq']['api_url'])
        if c.get('auth_mode') not in AUTH_MODES:raise ValueError('未知鉴权方式')
        if c.get('token_field') not in ('max_tokens','max_completion_tokens','omit'):raise ValueError('Token 字段无效')
        if type(c['max_output_tokens']) is not int or not 256<=c['max_output_tokens']<=131072:raise ValueError('输出 Token 上限应为 256–131072')
        for name in ('anthropic_version','api_version'):
            if not isinstance(c[name],str) or not re.fullmatch(r'[a-zA-Z0-9._-]{1,80}',c[name]):raise ValueError('API 版本无效')
        h=c.get('extra_headers');b=c.get('extra_body')
        if not isinstance(h,dict) or not isinstance(b,dict) or len(dumps(b))>16000:raise ValueError('附加参数与请求头必须是 JSON 对象')
        for name,value in h.items():
            if not re.fullmatch(r'[A-Za-z0-9-]{1,80}',name) or name.lower() in ('host','content-length','content-type','authorization','x-api-key','api-key','x-goog-api-key','connection','transfer-encoding','cookie'):raise ValueError('请求头名称无效；认证请使用鉴权方式和 API Key')
            if not isinstance(value,str) or not value.isascii() or any(ch in value for ch in ('\r','\n')) or len(value)>2000:raise ValueError('请求头值必须是无换行的 ASCII 文本')
        if any(k in b for k in ('model','messages','input','contents','system','systemInstruction','instructions','stream','store')):raise ValueError('附加参数不能覆盖核心消息字段')
        def reject_secrets(obj):
            if isinstance(obj,dict):
                for k,v in obj.items():
                    if k.lower() in ('api_key','apikey','authorization','access_token','token','secret'):raise ValueError('请将凭据放入 API Key，不放入附加参数')
                    reject_secrets(v)
            elif isinstance(obj,list):
                for v in obj:reject_secrets(v)
        reject_secrets(b)
        for section,fields in [('turn_taking',('enabled',)),('group_attention',('enabled','allow_unmentioned_reply')),('memory',('enabled',))]:
            if any(type(c[section].get(f)) is not bool for f in fields):raise ValueError('轮次、群聊或记忆开关无效')
        for section,field,lo,hi in [('turn_taking','debounce_seconds',.5,6),('turn_taking','max_wait_seconds',6,15),('turn_taking','decision_timeout_seconds',.5,5),('group_attention','per_minute',1,30),('group_attention','sample_every',1,50),('group_attention','context_chars',1000,12000),('memory','half_life_days',1,365)]:
            value=c[section].get(field)
            if type(value) not in (int,float) or not math.isfinite(value) or not lo<=value<=hi:raise ValueError('轮次、群聊或记忆参数超出范围')
            if section=='group_attention' and type(value) is not int:raise ValueError('群聊预算必须为整数')
        if c['cognition'].get('mode') not in ('adaptive','baseline'):raise ValueError('认知模式必须为 adaptive 或 baseline')
        timeout=c['cognition'].get('assessment_timeout')
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 3<=timeout<=120:raise ValueError('认知评估超时应为 3–120 秒')
        terms=c['group_attention'].get('watched_terms')
        if not isinstance(terms,list) or len(terms)>30 or not all(isinstance(w,str) and 1<=len(w)<=40 for w in terms):raise ValueError('群聊关注词无效')
        if c['group_attention']['allow_unmentioned_reply'] and not c['group_attention']['enabled']:raise ValueError('未@参与需要先启用群聊注意')
        from .social import validate_social
        validate_social(c)
        media=c['media']
        if type(media.get('receive')) is not bool or type(media.get('send')) is not bool or not isinstance(media.get('vision_model'),str) or len(media['vision_model'])>150:raise ValueError('图片配置无效')
        if not isinstance(media.get('download_hosts'),list) or len(media['download_hosts'])>30 or not all(isinstance(h,str) and re.fullmatch(r'(?:\*\.)?[a-z0-9][a-z0-9.-]{0,252}',h) for h in media['download_hosts']):raise ValueError('图片允许域名格式无效')
        perf=c['performance']
        if perf.get('mode') not in ('balanced','full') or type(perf.get('qq_only')) is not bool:raise ValueError('回复流程配置无效')
        for field,lo,hi in [('batch_turns',5,10),('idle_seconds',60,120),('work_chars',4000,100000),('reply_chars',40,500)]:
            if type(perf.get(field)) is not int or not lo<=perf[field]<=hi:raise ValueError('后台批量阈值或回复预算超出范围')
        d=c['deliberation']
        if not isinstance(d,dict) or d.get('mode') not in ('off','auto','always') or any(type(d.get(k)) is not bool for k in ('enabled','return_unresolved_conflict')):raise ValueError('内部协商配置无效')
        if type(d.get('max_perspectives')) is not int or not 1<=d['max_perspectives']<=4 or type(d.get('max_rounds')) is not int or not 1<=d['max_rounds']<=4 or d.get('log_level')!='summary':raise ValueError('内部协商上限应为 1–4，日志仅为摘要')
        m=c['pmm']
        if m.get('mode') not in ('api','learned','legacy'):raise ValueError('PMM 模式应为 api / learned / legacy')
        if validate_pmm_api:
            import copy
            test=copy.deepcopy(c);test.update(m['api']);Config.validate(test,False)
            test=copy.deepcopy(c);test.update(c['pmm281']['b_api']);Config.validate(test,False)
        validate_url(m['base_url'])
        if not isinstance(m['managed'],bool):raise ValueError('PMM 管理开关无效')
        if m['backend'] not in ('local','http'):raise ValueError('PMM 后端应为 local 或 http')
        if m['backend']=='local' and m['model'] not in ('pmm-mlp-v3','learned-pmm-v2','learned-pmm-v21'):raise ValueError('内置 PMM 模型标识无效')
        if not isinstance(m['model'],str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,100}',m['model']):raise ValueError('PMM 模型标识无效')
        if type(m['timeout']) not in (int,float) or not math.isfinite(m['timeout']) or not 10<=m['timeout']<=300:raise ValueError('PMM 超时应为 10–300 秒的数值')
        if not isinstance(m['api_key'],str) or any(ch in m['api_key'] for ch in ('\r','\n')):raise ValueError('PMM 密钥格式无效')
        if not isinstance(c['model'], str) or len(c['model']) > 150: raise ValueError('模型名称无效')
        if type(c['retrieval_k']) is not int or not 1 <= c['retrieval_k'] <= 20: raise ValueError('检索数应为 1–20 的整数')
        if type(c['timeout']) not in (int,float) or not math.isfinite(c['timeout']) or not 10 <= c['timeout'] <= 300: raise ValueError('超时应为 10–300 秒的数值')
        if type(c['max_retrieval_rounds']) is not int or not 0 <= c['max_retrieval_rounds'] <= 2: raise ValueError('重新检索轮数应为 0–2 的整数')
        if type(c['temperature']) not in (int,float) or not math.isfinite(c['temperature']) or not 0 <= c['temperature'] <= 2: raise ValueError('温度应为 0–2 的数值')
        for field in ('json_mode','send_temperature','online_learning','json_repair'):
            if not isinstance(c[field],bool): raise ValueError('开关字段必须为布尔值')
        for field in ('enabled','group_mention_only'):
            if not isinstance(c['qq'][field],bool): raise ValueError('QQ 开关字段必须为布尔值')
        for value in (c['api_key'], c['model'], c['controller_model'], *[c['qq'][k] for k in ('api_token','inbound_token','hmac_secret')]):
            if not isinstance(value,str) or any(ch in value for ch in ('\r','\n')):raise ValueError('密钥和模型名称不能包含换行符')
        if not isinstance(c['qq'].get('self_id',''),str) or (c['qq'].get('self_id') and not c['qq']['self_id'].isdigit()):raise ValueError('机器人 QQ 号必须是数字')
        for key in ('allowed_users', 'allowed_groups'):
            if not isinstance(c['qq'][key], list) or not all(str(x).isdigit() for x in c['qq'][key]):
                raise ValueError('QQ 白名单必须是号码列表')
        if c['qq']['enabled'] and not (c['qq']['allowed_users'] or c['qq']['allowed_groups']):
            raise ValueError('启用 QQ 前请至少填一个允许联系的 QQ 号或群号')
        if c['qq']['enabled'] and not (c['qq']['inbound_token'] or c['qq']['hmac_secret']):
            raise ValueError('启用 QQ 前请配置事件验证令牌')
        for key, limit in [('persona_name', 40), ('persona_seed', 8000)]:
            if not isinstance(c[key], str) or not c[key].strip() or len(c[key]) > limit:
                raise ValueError('人格名称或初始描述无效')

    def update(self, patch, commit=True):
        import urllib.parse
        config_shape(patch,partial=True)
        with self.lock:
            c=self.get()
            def origin(url):
                p=urllib.parse.urlsplit(url);return (p.scheme,p.hostname,p.port or (443 if p.scheme=='https' else 80))
            # A retained credential must never silently follow a change to another host.
            if 'base_url' in patch and origin(patch['base_url'])!=origin(c['base_url']):
                c['api_key']='';c['extra_headers']={}
            qp=patch.get('qq',{})
            if 'api_url' in qp and origin(qp['api_url'])!=origin(c['qq']['api_url']):c['qq']['api_token']=''
            pm=patch.get('pmm',{})
            ap=pm.get('api',{})
            if 'base_url' in ap and origin(ap['base_url'])!=origin(c['pmm']['api']['base_url']):
                c['pmm']['api']['api_key']='';c['pmm']['api']['extra_headers']={}
            bp=patch.get('pmm281',{}).get('b_api',{})
            if 'base_url' in bp and origin(bp['base_url'])!=origin(c['pmm281']['b_api']['base_url']):
                c['pmm281']['b_api']['api_key']='';c['pmm281']['b_api']['extra_headers']={}
            if 'base_url' in pm and origin(pm['base_url'])!=origin(c['pmm']['base_url']):c['pmm']['api_key']=''
            for k,v in patch.items():
                if k in ('qq','pmm','deliberation','performance','media','social','turn_taking','group_attention','memory','cognition','pmm28','pmm281'):
                    if not isinstance(v,dict):raise ValueError('连接配置应为对象')
                    for q,value in v.items():
                        if (k=='pmm' and q=='api') or (k=='pmm281' and q=='b_api'):
                            if not isinstance(value,dict):raise ValueError('API-PMM 连接应为对象')
                            for f,x in value.items():
                                if f in PROVIDER_FIELDS and not (x is None and f in ('api_key','extra_headers')):c[k][q][f]=x
                            continue
                        if q in DEFAULT_CONFIG[k]:
                            if (q.endswith('token') or q in ('hmac_secret','api_key')) and value is None:continue
                            c[k][q]=value
                elif k in DEFAULT_CONFIG:
                    if k in ('api_key','extra_headers') and v is None:continue
                    c[k]=v
            if 'recipients' in patch.get('social',{}):
                from .social import normalize_recipients
                c['social']['recipients']=normalize_recipients(c['social']['recipients'],c['social'])
            if 'allowed_users' in qp or 'allowed_groups' in qp:
                for field in ('allowed_users','allowed_groups'):
                    if not isinstance(c['qq'][field],list):raise ConfigError('QQ 白名单必须是号码列表',['/qq/'+field])
                c['social']['recipients']=[scope for scope in c['social']['recipients'] if scope.rsplit(':',1)[-1] in list(map(str,c['qq']['allowed_users' if scope.startswith('private:') else 'allowed_groups']))]
                if not c['social']['recipients']:c['social']['enabled']=False
            self.validate(c)
            if not commit:return c
            atomic_json(self.path,c)
            return self.public()
