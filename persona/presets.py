"""Protocol presets, not a promise that every model supports every option.
Models are deliberately not hardcoded: use account-specific model lists/names.
"""
PRESETS=[
    {'id':'ollama','label':'Ollama · 本机','provider':'ollama','base_url':'http://127.0.0.1:11434','auth_mode':'none'},
    {'id':'openai','label':'OpenAI · Responses','provider':'responses','base_url':'https://api.openai.com/v1','send_temperature':False},
    {'id':'openai_chat','label':'OpenAI · Chat Completions','provider':'chat_completions','base_url':'https://api.openai.com/v1','send_temperature':False,'token_field':'max_completion_tokens'},
    {'id':'claude','label':'Anthropic Claude · 原生 Messages','provider':'anthropic','base_url':'https://api.anthropic.com/v1','send_temperature':False},
    {'id':'gemini','label':'Google Gemini · 原生 generateContent','provider':'gemini','base_url':'https://generativelanguage.googleapis.com/v1beta','send_temperature':False},
    {'id':'deepseek','label':'DeepSeek','provider':'chat_completions','base_url':'https://api.deepseek.com/chat/completions','send_temperature':False,'thinking_mode':'off','thinking_adapter':'deepseek','hint':'当前官方模型名可填写 deepseek-flash；默认关闭思考，两个模型可分别调整。'},
    {'id':'qwen','label':'通义千问 · 百炼（北京）','provider':'chat_completions','base_url':'https://dashscope.aliyuncs.com/compatible-mode/v1','extra_body':{'enable_thinking':False}},
    {'id':'moonshot','label':'Kimi · Moonshot','provider':'chat_completions','base_url':'https://api.moonshot.cn/v1','send_temperature':False},
    {'id':'glm','label':'智谱 GLM','provider':'chat_completions','base_url':'https://open.bigmodel.cn/api/paas/v4','send_temperature':False},
    {'id':'openrouter','label':'OpenRouter','provider':'chat_completions','base_url':'https://openrouter.ai/api/v1'},
    {'id':'siliconflow','label':'硅基流动','provider':'chat_completions','base_url':'https://api.siliconflow.cn/v1'},
    {'id':'ark','label':'火山方舟 / 豆包','provider':'chat_completions','base_url':'https://ark.cn-beijing.volces.com/api/v3','send_temperature':False},
    {'id':'groq','label':'Groq','provider':'chat_completions','base_url':'https://api.groq.com/openai/v1'},
    {'id':'mistral','label':'Mistral','provider':'chat_completions','base_url':'https://api.mistral.ai/v1'},
    {'id':'azure','label':'Azure OpenAI · v1（填写资源域名与部署名）','provider':'azure_chat','base_url':'https://YOUR-RESOURCE.openai.azure.com/openai/v1','send_temperature':False,'token_field':'max_completion_tokens'},
    {'id':'lmstudio','label':'LM Studio / 本地兼容服务','provider':'chat_completions','base_url':'http://127.0.0.1:1234/v1','auth_mode':'none'},
    {'id':'custom','label':'自定义兼容服务','provider':'chat_completions','base_url':'','hint':'填写所用服务的 API 基地址或完整生成地址。'}
]
