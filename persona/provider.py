"""Text-model protocol adapters. Keys stay on the Python side, never in URLs/logs."""
from __future__ import annotations
import copy, json, urllib.request, urllib.error, urllib.parse, ipaddress, re, time

PROTOCOLS = ('ollama', 'chat_completions', 'responses', 'anthropic', 'gemini', 'azure_chat')
AUTH_MODES = ('auto', 'bearer', 'x-api-key', 'api-key', 'x-goog-api-key', 'none')
from .thinking import apply_thinking
from .diagnostics import safe_options, remote_error, response_meta

class ProviderError(Exception):
    def __init__(self, message, details=None):
        super().__init__(message); self.details=details or {}



def validate_url(url, allow_query=False):
    p = urllib.parse.urlsplit(str(url))
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or (p.query and not allow_query) or p.fragment:
        raise ValueError('地址需为不含密码、查询参数的 HTTP(S) URL')
    if any(c in str(url) for c in ('\r','\n','\t',' ')): raise ValueError('地址包含无效字符')
    if p.scheme == 'http':
        local = p.hostname == 'localhost'
        try: local = local or ipaddress.ip_address(p.hostname).is_loopback
        except ValueError: pass
        if not local: raise ValueError('非本机地址请使用 HTTPS')
    return str(url).rstrip('/')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError('接口发生重定向，请填写最终接口地址')


def request_json(url, payload=None, token='', timeout=120, headers=None, max_bytes=4_000_000):
    validate_url(url, allow_query=True)
    h = {'Content-Type':'application/json','Accept':'application/json'}
    if token: h['Authorization'] = 'Bearer ' + token
    h.update(headers or {})
    body = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
    req = urllib.request.Request(url, data=body, headers=h)
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=timeout) as res:
            data = res.read(max_bytes+1)
            if len(data)>max_bytes: raise ProviderError('模型响应超过大小限制')
            result=json.loads(data,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite')))
            if not isinstance(result,dict): raise ProviderError('接口响应应为 JSON 对象')
            if result.get('error'): raise ProviderError('模型服务返回错误；请检查模型、额度和请求参数',remote_error(result,200))
            return result
    except urllib.error.HTTPError as e:
        hints={401:'认证失败，请检查 API Key 或令牌',403:'接口拒绝访问',404:'地址或模型不存在',
               429:'请求过于频繁或额度不足',400:'请求不兼容；请检查 JSON、温度、Token 字段和附加参数',
               413:'请求过大',422:'服务不支持当前参数',500:'服务内部错误',502:'服务暂时不可用',503:'服务繁忙'}
        try: detail=remote_error(json.loads(e.read(65536)),e.code)
        except (ValueError,OSError): detail={'http_status':e.code}
        fields=detail.get('param') or ', '.join(detail.get('mentioned_parameters',[]))
        hint=('；服务端指向参数：'+fields) if fields else ''
        raise ProviderError(f'HTTP {e.code}：'+hints.get(e.code,'模型服务未能完成请求')+hint,detail) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ProviderError('无法连接模型服务或请求超时，请检查地址、网络及模型是否启动',{'code':'TRANSPORT_UNAVAILABLE'}) from None
    except (json.JSONDecodeError, UnicodeError, ValueError): raise ProviderError('接口未返回合法 JSON') from None


def parse_object(text):
    text=str(text).strip()
    if text.startswith('```'): text=text.split('\n',1)[-1].rsplit('```',1)[0].strip()
    try: obj=json.loads(text, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (json.JSONDecodeError,ValueError): raise ProviderError('模型没有返回合法 JSON 对象；可开启 JSON 修复或更换模型') from None
    if not isinstance(obj,dict): raise ProviderError('模型返回格式应为 JSON 对象')
    return obj


def text_blocks(value):
    if isinstance(value,str): return value
    if isinstance(value,list):
        return ''.join(b.get('text','') for b in value if isinstance(b,dict) and b.get('type') in ('text','output_text') and isinstance(b.get('text'),str))
    return ''


def endpoint(base, leaf, root='v1'):
    """Accept origin, versioned API base, or this protocol's full endpoint."""
    base=validate_url(base);was_endpoint=False
    for suffix in ('/chat/completions','/responses','/messages','/api/chat','/api/tags','/models'):
        if base.endswith(suffix):
            base=base[:-len(suffix)];was_endpoint=True
            if suffix.startswith('/api/'): base+='/api'
            break
    if not was_endpoint and not urllib.parse.urlsplit(base).path and root: base+='/'+root
    if leaf.startswith('api/') and base.endswith('/api'): leaf=leaf[4:]
    return base+'/'+leaf


def merge_extra(payload, extra, protected):
    if any(k in protected for k in extra): raise ValueError('附加参数不能覆盖 model/messages/input/contents/system/stream 等核心字段')
    for k,v in extra.items():
        if isinstance(v,dict) and isinstance(payload.get(k),dict): payload[k].update(copy.deepcopy(v))
        else: payload[k]=copy.deepcopy(v)
    return payload

def media_messages(messages, protocol):
    """Convert our text/image content blocks to each native wire format."""
    out=copy.deepcopy(messages)
    for message in out:
        content=message.get('content')
        if not isinstance(content,list):continue
        if message['role']!='user':raise ValueError('图片块只能放在用户输入中')
        parts=[];images=[];texts=[]
        for block in content:
            if block.get('type')=='text':
                text=str(block.get('text',''));texts.append(text)
                parts.append({'type':'input_text' if protocol=='responses' else 'text','text':text})
            elif block.get('type')=='image_url':
                url=block.get('image_url',{}).get('url','')
                match=re.fullmatch(r'data:(image/(?:jpeg|png|webp|gif));base64,([A-Za-z0-9+/=]+)',url)
                if not match or len(url)>12_000_000:raise ValueError('视觉请求仅接受已验证的内联图片')
                mime,data=match.groups();images.append(data)
                if protocol=='responses':parts.append({'type':'input_image','image_url':url})
                elif protocol=='anthropic':parts.append({'type':'image','source':{'type':'base64','media_type':mime,'data':data}})
                elif protocol=='gemini':parts.append({'inlineData':{'mimeType':mime,'data':data}})
                else:parts.append(block)
            else:raise ValueError('未知视觉内容块')
        if protocol=='ollama':message.update(content='\n'.join(texts),images=images)
        elif protocol=='gemini':message['content']=[{'text':p['text']} if 'text' in p else p for p in parts]
        else:message['content']=parts
    return out


class Provider:
    def __init__(self,config): self.config=copy.deepcopy(config);self.calls=[];self.stage='';self.thinking_capabilities=None
    def headers(self):
        c=self.config;mode=c.get('auth_mode','auto');p=c['provider']
        if mode=='auto':mode={'anthropic':'x-api-key','gemini':'x-goog-api-key','azure_chat':'api-key'}.get(p,'bearer')
        h=dict(c.get('extra_headers',{}));key=c.get('api_key','')
        if key and mode!='none':h['Authorization' if mode=='bearer' else mode]=('Bearer ' if mode=='bearer' else '')+key
        if p=='anthropic':h['anthropic-version']=c.get('anthropic_version','2023-06-01')
        return h
    def _url(self,kind='generate'):
        c=self.config;p=c['provider'];base=validate_url(c['base_url'])
        if urllib.parse.urlsplit(base).hostname=='api.deepseek.com':
            if kind=='models':return 'https://api.deepseek.com/models'
            if p=='anthropic' and urllib.parse.urlsplit(base).path in ('','/anthropic'):
                return 'https://api.deepseek.com/anthropic/v1/messages'
            if p in ('chat_completions','responses') and not urllib.parse.urlsplit(base).path:
                return endpoint(base,'responses' if p=='responses' else 'chat/completions','')
        if p=='azure_chat':
            if kind=='models': raise ProviderError('Azure 使用部署名，请在模型名称中手动填写；本接口不列出部署')
            if '/openai/v1' in base:return endpoint(base,'chat/completions')
            if '/deployments/' in base:url=endpoint(base,'chat/completions')
            else:url=base+'/openai/deployments/'+urllib.parse.quote(c['model'],safe='')+'/chat/completions'
            return url+'?'+urllib.parse.urlencode({'api-version':c.get('api_version','2024-10-21')})
        if p=='gemini':
            if ':generateContent' in base:
                # Full URL is a convenience; the selected model remains authoritative.
                base=base.split('/models/',1)[0]
            if kind=='models':return endpoint(base,'models','v1beta')
            name=c['model'].removeprefix('models/')
            return endpoint(base,'models/'+urllib.parse.quote(name,safe='')+':generateContent','v1beta')
        leaf={'ollama':'api/tags' if kind=='models' else 'api/chat','chat_completions':'chat/completions','responses':'responses','anthropic':'messages'}[p]
        if kind=='models' and p!='ollama':leaf='models'
        return endpoint(base,leaf,'' if p=='ollama' else 'v1')
    def _request(self,messages,structured):
        started=time.monotonic()
        call={'protocol':self.config['provider'],'model':self.config.get('model',''),'structured':structured,
              'stage':self.stage or 'model_request','status':'preparing','started_at':time.time(),'call_id':__import__('uuid').uuid4().hex,**getattr(self,'trace_context',{})}
        self.calls.append(call)
        try:
            result=self._execute(messages,structured,call)
            call.update(status='ok',output_chars=len(result));return result
        except (ProviderError,ValueError) as ex:
            call['status']='error'
            if isinstance(ex,ProviderError):call['response']=ex.details
            detail={'call':copy.deepcopy(call)}
            detail['call']['duration_ms']=round((time.monotonic()-started)*1000)
            raise ProviderError(str(ex),detail) from None
        finally:call['duration_ms']=round((time.monotonic()-started)*1000);call['ended_at']=time.time()

    def _execute(self,messages,structured,call):
        c=self.config;proto=c['provider'];model=c.get('model','').strip()
        if not model:raise ProviderError('尚未选择大模型。请打开“双模型与连接”完成设置。')
        messages=media_messages(messages,proto)
        if structured:
            instruction='Return one valid JSON object only. No Markdown, explanation, or reasoning text.'
            system_message=next((m for m in messages if m['role']=='system'),None)
            if system_message is None:messages.insert(0,{'role':'system','content':instruction})
            else:system_message['content']+='\n'+instruction
        system='\n\n'.join(m['content'] for m in messages if m['role'] in ('system','developer'))
        conversation=[m for m in messages if m['role'] in ('user','assistant')]
        limit=c.get('max_output_tokens',4096);temp=.2 if structured else c.get('temperature',.65)
        sendtemp=c.get('send_temperature',True);jsonmode=structured and c.get('json_mode',True)
        if proto=='ollama':
            payload={'model':model,'messages':messages,'stream':False,'options':{'num_predict':limit}}
            if sendtemp:payload['options']['temperature']=temp
            if jsonmode:payload['format']='json'
        elif proto in ('chat_completions','azure_chat'):
            payload={'model':model,'messages':messages,'stream':False}
            field=c.get('token_field','max_tokens')
            if field!='omit':payload[field]=limit
            if sendtemp:payload['temperature']=temp
            if jsonmode:payload['response_format']={'type':'json_object'}
        elif proto=='responses':
            payload={'model':model,'instructions':system,'input':conversation,'stream':False,'store':False,'max_output_tokens':limit}
            if sendtemp:payload['temperature']=temp
            if jsonmode:payload['text']={'format':{'type':'json_object'}}
        elif proto=='anthropic':
            payload={'model':model,'system':system,'messages':conversation,'max_tokens':limit,'stream':False}
            if sendtemp:payload['temperature']=min(1.,temp)
            # Prompt JSON works with older Messages models too; no invented response_format.
        else:
            payload={'systemInstruction':{'parts':[{'text':system}]},'contents':[{'role':'model' if m['role']=='assistant' else 'user','parts':m['content'] if isinstance(m['content'],list) else [{'text':m['content']}]} for m in conversation],
                     'generationConfig':{'maxOutputTokens':limit}}
            if sendtemp:payload['generationConfig']['temperature']=temp
            if jsonmode:payload['generationConfig']['responseMimeType']='application/json'
        payload=merge_extra(payload,c.get('extra_body',{}),{'model','messages','input','contents','system','systemInstruction','instructions','stream','store'})
        if proto=='ollama' and c.get('thinking_mode') in ('off','on','low','high'):
            show_url=endpoint(c['base_url'],'api/show','')
            if self.thinking_capabilities is None:
                meta=request_json(show_url,{'model':model},timeout=c.get('timeout',120),headers=self.headers())
                self.thinking_capabilities=meta.get('thinking',{}).get('values') if isinstance(meta.get('thinking'),dict) else None
            controls=self.thinking_capabilities
            if not isinstance(controls,list):raise ProviderError('Ollama 未返回此模型的思考能力；请使用服务默认或官方附加参数')
            c={**c,'_thinking_values':controls}
        payload,thinking=apply_thinking(payload,c)
        call.update(thinking=thinking,request_options=safe_options(payload),endpoint=urllib.parse.urlsplit(self._url()).path,status='requesting')
        r=request_json(self._url(),payload,timeout=c.get('timeout',120),headers=self.headers())
        call['http_status']=200
        try:call.update(response_meta(r,proto))
        except (TypeError,AttributeError,IndexError):raise ProviderError('模型响应结构与所选接口协议不符') from None
        def fail(code,message):
            raise ProviderError(message,{'code':code,**{k:call[k] for k in ('finish_reason','incomplete_reason','reasoning_chars','usage') if k in call}})
        def truncated():
            fail('OUTPUT_LIMIT','模型达到输出 Token 上限，正文未完整生成；请在本次调用对应的模型设置中提高输出上限，或降低 Thinking。实际参数与用量见操作历史')
        try:
            if proto=='ollama':
                if r.get('done_reason')=='length':truncated()
                if r.get('done') is False:fail('INCOMPLETE_RESPONSE','Ollama 返回未完成响应；请检查接口是否支持非流式调用')
                if r.get('message',{}).get('tool_calls'):fail('UNSUPPORTED_TOOL_CALL','模型要求调用工具，但此对话接口未提供工具执行器；请关闭附加参数中的工具选项')
                result=r.get('message',{}).get('content','')
            elif proto in ('chat_completions','azure_chat'):
                choice=r.get('choices',[{}])[0];message=choice.get('message',{})
                if choice.get('finish_reason')=='length':truncated()
                if choice.get('finish_reason')=='content_filter':fail('CONTENT_FILTER','模型服务拦截了本次内容；提高 Token 上限不能解决该问题，请检查输入及服务规则')
                if choice.get('finish_reason') in ('tool_calls','function_call') or message.get('tool_calls') or message.get('function_call'):fail('UNSUPPORTED_TOOL_CALL','模型要求调用工具，但此对话接口未提供工具执行器；请关闭附加参数中的工具选项')
                if message.get('refusal'):fail('MODEL_REFUSAL','模型服务拒绝了本次请求，没有返回可用正文')
                result=text_blocks(message.get('content'))
            elif proto=='responses':
                if r.get('status')=='incomplete' and call.get('incomplete_reason')=='max_output_tokens':truncated()
                if r.get('status')=='incomplete' and call.get('incomplete_reason')=='content_filter':fail('CONTENT_FILTER','模型服务拦截了本次内容，请检查输入及服务规则')
                if r.get('status') in ('incomplete','failed','cancelled'):fail('INCOMPLETE_RESPONSE','Responses 返回未完成状态，详情见本次调用记录')
                output=r.get('output',[])
                if any(item.get('type')=='function_call' for item in output):fail('UNSUPPORTED_TOOL_CALL','模型要求调用函数，但此对话接口未提供函数执行器')
                if any(b.get('type')=='refusal' for item in output for b in item.get('content',[])):fail('MODEL_REFUSAL','模型服务拒绝了本次请求，没有返回可用正文')
                result=''.join(text_blocks(item.get('content')) for item in output if item.get('type')=='message')
            elif proto=='anthropic':
                if r.get('stop_reason')=='max_tokens':truncated()
                if r.get('stop_reason')=='refusal':fail('MODEL_REFUSAL','模型服务拒绝了本次请求，没有返回可用正文')
                if r.get('stop_reason')=='tool_use' or any(b.get('type')=='tool_use' for b in r.get('content',[])):fail('UNSUPPORTED_TOOL_CALL','模型要求调用工具，但此对话接口未提供工具执行器')
                if r.get('stop_reason')=='pause_turn':fail('INCOMPLETE_RESPONSE','模型暂停了本轮，未得到完整正文；本接口不自动续发工具轮次')
                result=text_blocks(r.get('content'))
            else:
                if r.get('promptFeedback',{}).get('blockReason'):fail('CONTENT_FILTER','模型服务拦截了本次输入，请检查输入及服务规则')
                candidate=r.get('candidates',[{}])[0]
                if candidate.get('finishReason')=='MAX_TOKENS':truncated()
                if candidate.get('finishReason') in ('SAFETY','RECITATION','BLOCKLIST','PROHIBITED_CONTENT','SPII'):fail('CONTENT_FILTER','模型服务拦截了本次内容，请检查输入及服务规则')
                if candidate.get('finishReason') not in (None,'STOP'):fail('INCOMPLETE_RESPONSE','Gemini 输出未正常完成，详情见本次调用记录')
                if any('functionCall' in b for b in candidate.get('content',{}).get('parts',[])):fail('UNSUPPORTED_TOOL_CALL','模型要求调用函数，但此对话接口未提供函数执行器')
                result=''.join(b.get('text','') for b in candidate.get('content',{}).get('parts',[]) if not b.get('thought') and isinstance(b.get('text'),str))
        except (IndexError,TypeError,AttributeError,KeyError):raise ProviderError('模型响应结构与所选接口协议不符') from None
        if not isinstance(result,str) or not result.strip():
            fail('REASONING_ONLY' if call.get('reasoning_chars') else 'EMPTY_RESPONSE','模型只返回了 reasoning/thinking，缺少最终正文；请关闭或降低思考、提高输出上限' if call.get('reasoning_chars') else '模型返回了空文本；请检查模型、输出上限及协议')
        return result.strip()
    def complete(self,messages,structured=False,controller=False):
        # controller is accepted for v0.2 callers only, never selects a hidden third model.
        result=self._request(messages,structured)
        if not structured:return result
        try:return parse_object(result)
        except ProviderError as ex:
            if self.calls:self.calls[-1]['format_status']='invalid_json'
            if not self.config.get('json_repair',False):raise ProviderError(str(ex),{'code':'INVALID_JSON','calls':copy.deepcopy(self.calls)}) from None
        # One explicit repair request to the same model; no model substitution or state write.
        retry=[*messages,{'role':'assistant','content':result[:24000]},
               {'role':'user','content':'Your previous output was not a valid JSON object. Return the requested complete JSON object only, using double quotes and finite numbers.'}]
        try:return parse_object(self._request(retry,True))
        except ProviderError as ex:
            if not ex.details:ex.details={'calls':copy.deepcopy(self.calls)}
            raise
    def models(self):
        r=request_json(self._url('models'),timeout=20,headers=self.headers());p=self.config['provider']
        if p=='gemini':return [x['name'].removeprefix('models/') for x in r.get('models',[]) if 'generateContent' in x.get('supportedGenerationMethods',[])]
        return [str(x.get('id') or x.get('name')) for x in r.get('models',r.get('data',[])) if x.get('name') or x.get('id')]
    def test(self):
        r=self.complete([{'role':'system','content':'Return a JSON object with exactly {"ok":true}.'},{'role':'user','content':'connection test'}],structured=True)
        if r.get('ok') is not True:raise ProviderError('连接建立，但模型未通过 JSON 输出测试',{'calls':copy.deepcopy(self.calls)})
        return {'ok':True,'message':'大模型连接与 JSON 输出正常','protocol':self.config['provider'],'model':self.config['model'],'calls':self.calls,'duration_ms':sum(x.get('duration_ms',0) for x in self.calls)}
