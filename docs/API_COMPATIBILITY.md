# General LLM / API-PMM 接入与兼容范围

协议依据核对日期：2026-10-23。v2.1.1 双连接本机协议测试：2026-10-25。实现位于 `persona/provider.py`，预设位于 `persona/presets.py`。两套连接使用同一适配器，分别从顶层配置与 `pmm.api` 读取各自的协议、地址、模型、密钥和兼容选项。这里只描述已经实现的**非流式文本对话**路径。服务端可用模型、地区、额度与特殊参数仍以你的账号和该服务文档为准；协议测试不等于逐家真实密钥联调。

## 原生协议映射

| 界面协议 | 请求 | 系统提示与对话 | 输出提取 | JSON 方式 |
| --- | --- | --- | --- | --- |
| Chat Completions | POST `/chat/completions` | `messages` | `choices[0].message.content`，支持字符串 / text 块 | `response_format.type=json_object` 可关闭 |
| Responses | POST `/responses` | `instructions` + `input` | `output[].message.content[].output_text` | `text.format.type=json_object` 可关闭 |
| Anthropic Messages | POST `/messages` | 顶层 `system` + user/assistant `messages` | `content[].text`，忽略 thinking 块 | JSON 指令、解析校验、可选一次修复；不发送 OpenAI 字段 |
| Gemini | POST `/models/{model}:generateContent` | `systemInstruction` + `contents[].parts`，assistant 转 model | `candidates[0].content.parts[].text`，忽略 thought 块 | `generationConfig.responseMimeType=application/json` 可关闭 |
| Ollama | POST `/api/chat` | `messages` | `message.content` | `format=json` 可关闭 |
| Azure Chat | v1 `/openai/v1/chat/completions` 或旧 `/openai/deployments/{deployment}/chat/completions?api-version=...` | Chat 格式，model 填部署名 | Chat 格式 | Chat 格式 |

Responses 固定 `store=false`；上下文由本程序维护，不靠服务方会话 ID 保持人格。所有生成请求关闭流式返回，避免把尚未通过行动检查的半条消息发出。推理字段不作为用户可见回答保存。

默认 Token 上限 4096，可改为 256–131072 范围内且服务接受的值。Chat 可选择 `max_tokens`、`max_completion_tokens` 或不发送；Responses / Claude / Gemini / Ollama 分别映射为原生字段。推理模型的预算可能同时覆盖推理与输出，过小会导致无正文或截断。程序检测截断、工具调用、显式拒绝或安全拦截后报错，不保存半轮。

## 服务预设

| 服务 | 预设地址 | 协议 / 备注 |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | Responses 或 Chat；推理模型默认不发温度 |
| Claude | `https://api.anthropic.com/v1` | Messages；可调 anthropic-version，默认兼容版 2023-06-01 |
| Gemini | `https://generativelanguage.googleapis.com/v1beta` | Gemini Developer API；密钥使用头，不放 URL |
| DeepSeek | `https://api.deepseek.com/chat/completions` | Chat 完整端点 |
| 千问 / 百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 北京按量地址；可改为自己业务空间 / 地域地址；预设 `enable_thinking=false`，模型不接受时在附加参数删除 |
| Kimi | `https://api.moonshot.cn/v1` | Chat；也可手动改 Responses 或 Messages 及其对应地址 |
| GLM | `https://open.bigmodel.cn/api/paas/v4` | Chat |
| OpenRouter | `https://openrouter.ai/api/v1` | Chat；模型 ID 可含组织前缀 |
| 硅基流动 | `https://api.siliconflow.cn/v1` | Chat |
| 火山方舟 / 豆包 | `https://ark.cn-beijing.volces.com/api/v3` | Chat；使用实际模型 / 推理接入点 ID |
| Groq | `https://api.groq.com/openai/v1` | Chat |
| Mistral | `https://api.mistral.ai/v1` | Chat |
| Azure OpenAI | `https://YOUR-RESOURCE.openai.azure.com/openai/v1` | 必须替换资源域名，模型填部署名 |
| Ollama | `http://127.0.0.1:11434` | 原生 Ollama |
| LM Studio | `http://127.0.0.1:1234/v1` | 本地 Chat 兼容服务 |
| 自定义 | 自填 | 选择真实协议，可连接 vLLM、其他兼容网关等 |

平台常有按量、Coding Plan、不同地区等不同地址与密钥；不要把一个服务的预设当成所有计费渠道共用地址。模型列表是便利功能，不支持列表的服务仍可手动填写。当前列表只读取返回的一页，更多模型可手填。

## Thinking 补丁

v2.1.1 增加独立 thinking_mode / thinking_adapter、阶段耗时、失败诊断和模型 ID 修复。具体模式优先级、模型限制与最新官方依据见 [THINKING.md](THINKING.md)。原始远程错误正文仍不回显，安全参数和白名单错误字段会显示。

## 鉴权与兼容参数

鉴权可选自动、Bearer、x-api-key、api-key、x-goog-api-key、无鉴权。API Key 只保存在 Python 后端配置中，UI 回读、日志、人格包与备份不含密钥值。附加请求头允许服务指定的版本 / 项目信息，回读只显示头名称。换服务域名时不会自动把旧凭据送到新域名；切换预设会清空旧凭据。

附加 JSON 参数用于真实服务支持的选项，例如：

```json
{"reasoning_effort":"low"}
```

或：

```json
{"thinking":{"type":"disabled"}}
```

两者只是不同服务的语法示例，不是可同时通用的参数。Gemini 使用 `generationConfig`，Ollama 使用 `options`。附加对象与已生成的顶层对象合并一层；不能覆盖主体消息、模型、stream 或 store。鉴权不放在附加 body 内。

仅 JSON 文本解析失败时可向**同一模型**修复一次，失败不伪造控制结果。语义字段仍由 Engine 校验；“合法 JSON”不等于心理判断正确。连接测试验证 `{"ok":true}`，完整场景测试仍需要你的真实输入。HTTP 401/403、404、429、超时、参数不兼容会显示可操作的简短错误；不回显可能含秘密的服务原始错误正文。

## 当前边界

- 不保证每家所有模型都支持 JSON、温度或同样的扩展参数；这些开关可以分别调整。
- 不实现 AWS Bedrock SigV4 / Converse、Google Vertex 服务账号自动换取 OAuth、特殊私有签名协议。可经已实现协议的网关接入，或新增适配器；手动 Bearer 令牌不会自动刷新。
- 不实现语音、图像、工具执行、流式展示或第三方 Agent 服务端点；它们不是此次人格文本闭环接口。
- API-PMM 可以连接上述普通 LLM API，由其执行心理任务；Learned-PMM 的远程数值后端使用独立 PMM HTTP/1，普通聊天 API 不能直接冒充该数值服务。

## 官方协议依据

- [OpenAI 结构化输出](https://developers.openai.com/api/docs/guides/structured-outputs)
- [OpenAI Responses 创建接口](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [Claude Messages](https://platform.claude.com/docs/en/api/messages/create)
- [Gemini generateContent](https://ai.google.dev/api/generate-content)
- [Ollama Chat](https://docs.ollama.com/api/chat)
- [Azure OpenAI 端点与部署名](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/switching-endpoints)
- [DeepSeek 首次调用](https://api-docs.deepseek.com/)
- [百炼 Base URL](https://help.aliyun.com/zh/model-studio/base-url)
- [Kimi API 协议兼容表](https://platform.moonshot.cn/docs/api)
- [智谱 OpenAI 兼容](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction)
- [OpenRouter API](https://openrouter.ai/docs/api-reference/overview)
- [硅基流动快速开始](https://docs.siliconflow.cn/docs/userguide/quickstart)
- [火山方舟快速开始](https://docs.volcengine.com/docs/ark/quick-start?lang=zh)
- [Groq OpenAI 兼容](https://console.groq.com/docs/openai)
- [Mistral Chat API](https://docs.mistral.ai/api)

## v2.1.2 图像内容

图像在 Python 侧验证并编码，六个传输适配器分别生成 Chat/Azure image_url、Responses input_image、Claude base64 image source、Gemini inlineData、Ollama images 数组。纯文本结构保持原行为。图像 URL 不直接交给模型抓取，而由受限下载器取得字节；本机 HTTP 测试验证实际请求体含图像字节、诊断中不含原始图像。

同一协议的某个模型不一定支持视觉。General 模型不支持时，可在运行设置覆盖视觉模型名称，沿用同一接口与密钥；不支持的响应显示读取失败。DeepSeek Flash 的图像接口依据其官方 vision 文档适配，非所有 DeepSeek 历史型号均可看图。

官方协议来源（核对日期 2026-10-26）：

- https://api-docs.deepseek.com/guides/vision/
- https://developers.openai.com/api/docs/guides/images-vision
- https://platform.claude.com/docs/en/build-with-claude/vision
- https://ai.google.dev/api/generate-content
- https://docs.ollama.com/capabilities/vision
- https://github.com/botuniverse/onebot-11/blob/master/message/segment.md
- https://github.com/botuniverse/onebot-11/blob/master/api/public.md

主动聊天机制参考大肥鱼项目的低频机会检测、冷却和未回复控制；只借鉴可核实的工程设计，没有引入该项目代码或声称与其行为相同：
https://github.com/whyever77/dafeiyu-astrbot/blob/main/README.md
https://github.com/whyever77/dafeiyu-astrbot/blob/main/CHANGELOG.md
