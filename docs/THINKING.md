# API Thinking 控制

既有适配规则核对于 2026-10-25；本轮于 2026-10-28 复核 DeepSeek / Ollama 官方文档。General 配置的 `thinking_mode` / `thinking_adapter` 与 `pmm.api` 内同名字段各自独立。此功能控制模型服务的推理参数，不替代 PMM 内部协商。

## 模式与优先级

| 模式 | 行为 |
| --- | --- |
| auto（缺省） | 官方 DeepSeek Chat / Responses / Messages 且没有手工思考参数时关闭；其余沿用服务和附加参数 |
| default | 不注入思考控制，附加参数按原样使用；服务默认不等于关闭 |
| on（仅 Ollama） | 模型能力列表包含布尔 true 才发送 `think:true`，不把分级思考伪装成布尔模式 |
| off / low / high | 显式映射；不能与 `extra_body` 中思考控制混用，冲突会在 HTTP 前报错 |

自动适配仅识别官方域名和原生 Ollama，不依据一个包含“deepseek”的模型名称去猜代理协议。自定义网关或 Azure 部署可明确选适配器；没有确认的服务使用 default，并按其官方文档填写 extra_body。

## 映射及适用范围

| 适配器 | off | low / high |
| --- | --- | --- |
| DeepSeek Chat | `thinking.type=disabled` | `thinking.type=enabled` + `reasoning_effort=low/high` |
| DeepSeek Responses | `reasoning.effort=none` | `reasoning.effort=low/high` |
| DeepSeek Messages | `thinking.type=disabled` | `thinking.type=enabled` + `output_config.effort=low/high`；不使用 Claude budget_tokens |
| OpenAI Responses | `reasoning.effort=none`，仅支持该值的型号 | `reasoning.effort=low/high` |
| OpenAI / Azure Chat | `reasoning_effort=none`，仅支持该值的型号 | `reasoning_effort=low/high`，输出字段改为 `max_completion_tokens` |
| Claude Messages（已识别型号） | `thinking.type=disabled`，不支持关闭的型号拒绝 | 4.6 及已识别后续型号使用 adaptive + output_config.effort；4.5 和受支持旧型号使用 1024 / 8192 thinking budget |
| Gemini 2.5 generateContent | Flash 使用 thinkingBudget=0；Pro 拒绝关闭 | thinkingBudget=1024 / 8192，这是本程序的预算预设 |
| Gemini 3 generateContent | 不将低思考伪称为关闭；off 拒绝 | thinkingLevel=LOW / HIGH |
| Ollama | `/api/show` 的 thinking.values 必须包含 false | `/api/show` 必须声明对应 low / high，布尔 true 不等同于分级思考 |

Claude 旧式预算必须小于总 max_tokens；选择 high 时原默认 4096 不足，会要求调高总上限。Claude Opus 5.5、Sonnet 5.5、Fable / Mythos 等不能完全关闭的已知型号拒绝 off。OpenAI GPT-5（初代）、o 系列、GPT-6 Astra、GPT-6.1 Sol 的已知 none 限制在本地提示。尚未识别的型号和网关仍以服务实际支持为准，代码不宣称所有型号都能使用全部档位。

显式开启 DeepSeek / OpenAI / Claude 思考时，省略 temperature / top_p / logprobs / top_logprobs，实际调整列入诊断。手动 default 模式由用户控制，不悄悄移除参数。DeepSeek 不接受 OpenAI 的 `max_completion_tokens`，非流式请求不应带 stream_options；受控模式会提前提示。

其他兼容服务继续使用原有 `extra_body`；例如千问的 `enable_thinking` 并不转换成 OpenAI reasoning_effort。此补丁没有给每一家供应商猜测一套统一开关。

## 诊断与耗时

成功和失败请求均记录调用阶段、持续毫秒数、结构化请求与否、实际生效的安全参数、响应终止原因、可用 usage，以及 reasoning 字符数。思考正文不混入回复或诊断；不持久化请求头、密钥或原始远程错误正文。

HTTP 错误只提取白名单错误类型、字段名与固定错误类别；无法安全识别的错误仍显示状态码和通用提示。用户对话仍按原有机制保存在主体历史中，诊断过滤不代表删除聊天。

六个阶段由单调时钟计时；General 与 PMM API 时间是各自实际请求时间累加。整轮数值截至生成、反馈、学习与入库阶段，QQ 另记录发送耗时和总处理耗时。该接口是非流式文本，未声称测得首 token 延迟或服务内部纯思考时间。

## 官方依据

- [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)
- [DeepSeek Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)
- [DeepSeek 模型能力列表](https://api-docs.deepseek.com/api/list-models/)
- [OpenAI Reasoning models](https://developers.openai.com/api/docs/guides/reasoning)
- [OpenAI Responses 参数](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [Claude Thinking](https://platform.claude.com/docs/en/build-with-claude/thinking)
- [Claude Extended thinking](https://platform.claude.com/docs/en/build-with-claude/extended-thinking)
- [Claude 各模型限制](https://platform.claude.com/docs/en/build-with-claude/thinking-troubleshooting)
- [Gemini generateContent Thinking](https://ai.google.dev/gemini-api/docs/generate-content/thinking)
- [Ollama Thinking 与能力发现](https://docs.ollama.com/capabilities/thinking)


## 2.2.3 完成错误分类

`OUTPUT_LIMIT` 是输出预算截断；`CONTENT_FILTER` 是服务拦截；`UNSUPPORTED_TOOL_CALL` 是当前没有执行器的工具请求；`MODEL_REFUSAL`、`INCOMPLETE_RESPONSE`、`REASONING_ONLY`、`EMPTY_RESPONSE` 分开记录。不接受半截正文作为已完成回复，也不增加隐藏自动重试。

实际设置应查看失败调用自己的 protocol/model/stage/request_options/finish_reason/usage；PMM 和 General 各有设置，改错一侧不会解决另一侧的预算问题。原截图只有通用错误，不能反推其具体原因。

官方 DeepSeek 根地址对应 `/chat/completions`、`/responses`；Messages 兼容基础地址为 `/anthropic`，Messages 路径为 `/anthropic/v1/messages`。代理仍按用户填写的最终路径及明确适配器处理，不依据模型名字猜供应商。新增协议已做本地请求/响应测试，未用真实密钥验证。

补充依据：
- https://api-docs.deepseek.com/guides/responses_api/
- https://api-docs.deepseek.com/guides/anthropic_api/
- https://api-docs.deepseek.com/guides/thinking_mode/
- https://docs.ollama.com/capabilities/thinking
