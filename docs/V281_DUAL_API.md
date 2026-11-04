# 2.8.1：双内部模型设置与实测记录

| 角色 | 用途 | 配置与执行 |
|---|---|---|
| General LLM | 输入语言解析、最终语言表达 | 原「语言模型」连接；不属于 PMM 内部。 |
| A | 识别事实锚点、评价、行动初始候选与不确定性 | `pmm.api`；`EventReasoner.prepare`，提示 `PMM_A_EVENT_V281`。 |
| B | 在情绪、人格、记忆、关系与候选计算后复核 | `pmm281.b_api`；`Negotiator.assess`，提示 `PMM_B_DELIBERATION_V281`。按需或每轮，可设最大轮数。 |

本地 Ollama、Chat Completions 兼容服务、Responses、Anthropic Messages、Gemini generateContent 和 Azure Chat 均复用已有 Provider。A/B 各自保存协议、模型、地址、密钥及运行参数；共用 A 时，B 只引用服务地址、协议、模型及鉴权，继续使用自己的任务、Thinking、Token、JSON、超时和日志。在本地 Qwen 卡片里，先填写运行 Ollama 的地址，读取模型列表再选机器上实际存在的名称。代理协议和 Thinking 如需调整，在高级设置中选择。未验证的供应商组合不标成在线。

应用公开配置仅返回密钥是否存在。密钥保存在各主体本地配置文件，沿用既有文件权限，并非操作系统密钥链。更换服务主机不会把旧主机密钥带到新主机。请勿对外共享包含本地配置和个人数据的整目录备份。

| 接口 | 后端行为 |
|---|---|
| `GET /api/pmm281/status` | 读取当前连接、最近测试/回合、历史和模型目录；不抽样或推进情绪。 |
| `POST /api/pmm281/connection` | `role=A/B`；`operation=models/connect/invoke`：分别取模型列表、测试 JSON 通信、按该角色实际调用一次。 |
| `POST /api/pmm281/preview` | 输入 `subject_id` 和 `text`，可指定已有会话；返回 `job_id`，由既有任务接口读取结果。复制 SQLite 快照，在临时库运行正常 Engine；不启动 QQ，不写正式心理状态。 |
| `POST /api/pmm281/emotion/models` | 参数包含 `subject_id`、`expected_revision`、`op`。导入、训练、校准、冻结、发布、撤回及回退；训练/校准由后台任务执行。 |

## 实际传输结果

以下为两套不同本地 HTTP 服务收到的真实请求。端口是测试临时端口，不能复制为用户的真实配置。服务返回可控的协议样例，不是商业云模型或 Qwen 权重。

| 角色 | 操作 | 协议与模型 | 耗时（ms） | 结果 |
|---|---|---|---:|---|
| A | 读取模型 | ollama / A-http | 10.663 | 通过 |
| A | JSON 连通性 | ollama / A-http | 2.911 | 通过 |
| A | 角色任务 | ollama / A-http | 21.336 | 通过 |
| B | 读取模型 | chat_completions / B-http | 2.786 | 通过 |
| B | JSON 连通性 | chat_completions / B-http | 2.902 | 通过 |
| B | 角色任务 | chat_completions / B-http | 17.690 | 通过 |
| B | 角色任务（共用 A） | ollama / A-http | 16.783 | 通过 |
| B | 角色任务 | chat_completions / B-http | 22.046 | 预期故障：HTTP 503，模型服务暂时不可用 |

另有真实 socket 超时、重试及消息去重断言。原始请求路径、模型名、Token 预算与任务标识见 `reports/v281/stage4/dual_http_receipts.json`；未保存凭据或完整对话。复现 `python tests/capture_v281_transport.py`。真实账户接入请用程序自身的两张卡分别测试。
