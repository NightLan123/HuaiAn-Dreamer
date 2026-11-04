"""Local connection presets. Applying a preset copies it, never creates a live alias."""
from __future__ import annotations
import copy, json, threading
from pathlib import Path
from .common import Config, PROVIDER_FIELDS, atomic_json, uid, now
from .provider import Provider, request_json, ProviderError

KINDS = ('general', 'pmm', 'qq')

def extract(config, kind):
    if kind not in KINDS: raise ValueError('预设类型应为 general / pmm / qq')
    return {k:copy.deepcopy(config[k]) for k in PROVIDER_FIELDS} if kind=='general' else copy.deepcopy(config[kind])

def patch(kind, value):
    return copy.deepcopy(value) if kind=='general' else {kind:copy.deepcopy(value)}

def redact(value):
    if isinstance(value, dict):
        return {k:('[已保存]' if k in ('api_key','api_token','inbound_token','hmac_secret','extra_headers') and v else '' if k in ('api_key','api_token','inbound_token','hmac_secret') else {} if k=='extra_headers' else redact(v)) for k,v in value.items()}
    return copy.deepcopy(value)

class Presets:
    def __init__(self, root):
        self.path=Path(root)/'connection_presets.json';self.lock=threading.RLock()
        if not self.path.exists():atomic_json(self.path, {'format':'connection-presets/1','items':[]})
    def read(self):return json.loads(self.path.read_text('utf8'))
    def list(self):return [{**v,'value':redact(v['value'])} for v in self.read()['items']]
    def get(self, identifier):
        row=next((v for v in self.read()['items'] if v['id']==identifier), None)
        if row is None:raise ValueError('连接预设不存在')
        return row
    def mutate(self, body, config):
        with self.lock:
            data=self.read();op=body.get('op','save');identifier=body.get('id')
            old=self.get(identifier) if identifier else None
            if op=='delete':
                if old is None:raise ValueError('请选择要删除的预设')
                data['items']=[v for v in data['items'] if v['id']!=identifier]
            else:
                name=body.get('name',old['name'] if old else '')
                if not isinstance(name,str) or not 1<=len(name.strip())<=60:raise ValueError('预设名称应为 1–60 个字符')
                if op not in ('save','copy','rename'):raise ValueError('预设操作无效')
                if op in ('copy','rename') and old is None:raise ValueError('请先选择预设')
                kind=old['kind'] if old else body.get('kind')
                value=copy.deepcopy(old['value']) if op in ('copy','rename') else extract(config,kind)
                row={'id':uid() if not old or op=='copy' else identifier,'kind':kind,'name':name.strip(),'value':value,'updated_at':now()}
                data['items']=[v for v in data['items'] if v['id']!=row['id']]+[row]
            atomic_json(self.path,data)
            return self.list()
    def test(self, identifier, base):
        row=self.get(identifier);kind=row['kind'];value=row['value']
        if kind=='general':return Provider(value).test()
        if kind=='pmm':
            if value['mode']=='api':return Provider(value['api']).test()
            from .pmm_interface import create_pmm
            c=copy.deepcopy(base);c['pmm']=copy.deepcopy(value)
            return create_pmm(c,None,'').test()
        r=request_json(value['api_url'].rstrip('/')+'/get_login_info',{},value['api_token'],20)
        if r.get('retcode')!=0:raise ProviderError('QQ 预设登录检查失败')
        d=r.get('data') or {}
        if value.get('self_id') and str(d.get('user_id'))!=value['self_id']:raise ProviderError('QQ 登录账号与预设绑定账号不同')
        return {'ok':True,'user_id':d.get('user_id'),'nickname':d.get('nickname')}

def check_routes(configs):
    enabled=[(i,c['qq']) for i,c in configs.items() if c['qq']['enabled']]
    for n,(left,a) in enumerate(enabled):
        for right,b in enabled[n+1:]:
            if not a.get('self_id') or not b.get('self_id'):
                raise ValueError('多个人格启用 QQ 时，每个人格都必须填写机器人 QQ 号')
            if a['self_id']!=b['self_id']:continue
            for field in ('allowed_users','allowed_groups'):
                if set(map(str,a[field])) & set(map(str,b[field])):
                    raise ValueError('同一 QQ 账号的联系人或群已绑定另一个人格，请调整白名单后再启用')
