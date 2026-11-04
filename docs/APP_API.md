# 本机工作台 API · 2.7

工作台默认 `http://127.0.0.1:8765`。浏览器先打开 `/` 取得 HttpOnly 会话 Cookie，从 `GET /api/state` 取得 CSRF token。所有管理 POST 需要同源 Cookie 与 `X-CSRF-Token`；Host / Origin 校验保持启用。这是本机管理接口，不是无认证公网 API。

长任务返回 `{"job_id":"..."}`，轮询 `GET /api/jobs/{id}`，状态 `queued/running/done/error`。并行修改连接、权重、主体在活动任务/QQ 处理中会被拒绝。API 服务返回错误时不会自动换成测试夹具。

## 模型与训练

| 路径 | 输入 / 输出 |
| --- | --- |
| `GET /api/state` | 当前主体、profile/activity/expression/synthesis、脱敏 config、model 与 pending_samples |
| `POST /api/config` | 配置补丁；`pmm.mode=api/learned/legacy`；`pmm.api` 使用与顶层 General LLM 相同的连接字段 |
| `POST /api/test-model` / `/api/models` | General LLM 实际连接测试 / 列表 |
| `POST /api/pmm/test` / `/api/pmm/models` | 按当前模式测试 API-PMM 或数值 PMM / 列表 |
| `POST /api/pmm/api/copy-general` | 将已保存 General 连接在后端复制为 API-PMM 连接，不回显密钥 |
| `POST /api/pmm/start` | Learned/legacy 模式启动受管理的本机数值服务 |
| `POST /api/pmm/train` | `{"epochs":30}`，后台任务；Learned 更新 Adapter，API 模式拒绝梯度训练 |
| `GET /api/pmm/export` / `POST /api/pmm/import` | `pmm-weights/1` 主体绑定的完整数值检查点 |
| `GET /api/pmm/versions` | `{weights,cores,model}` 版本目录 |
| `POST /api/pmm/version/save` | 可选 `{label}`，保存本主体数值版本 |
| `POST /api/pmm/version/activate` | `{id}`，恢复数值版本，不恢复心理/记忆状态 |
| `GET /api/pmm/core/export` | 当前 `pmm-core/2`，无个体 Adapter 或回放样本 |
| `POST /api/pmm/core/import` | 完整 `pmm-core/2`，加入全局目录，不自动启用 |
| `POST /api/pmm/core/train` | `{epochs}` 后台任务，使用当前主体数据、空白 Adapter 训练核心，返回未启用版本 |
| `POST /api/pmm/core/activate` | `{id}`，切换核心及匹配 Adapter，原配对自动备份 |
| `GET /api/pmm/adapter/export` / `POST /api/pmm/adapter/import` | `personal-adapter/2`，必须匹配主体与核心摘要 |

配置关键结构示意（真实连接字段可通过设置界面填写，不要将示意密钥用作实际密钥）：

```json
{
  "provider":"responses",
  "base_url":"https://api.openai.com/v1",
  "model":"你的通用模型",
  "api_key":"你的General密钥",
  "pmm":{
    "mode":"api",
    "api":{
      "provider":"anthropic",
      "base_url":"https://api.anthropic.com/v1",
      "model":"你的心理模型",
      "api_key":"你的PMM密钥"
    }
  }
}
```

`api_key:null` / `extra_headers:null` 表示保留原值；换域名时先清除原服务凭据，再应用明确新值。`api_key:""` 清除密钥。回读只含 has_api_key 等标志。大模型列表只取当前一页；不支持列表的平台可手填模型。

## 人格与对话

| 路径 | 输入 / 输出 |
| --- | --- |
| `POST /api/session` | 新本机会话 |
| `POST /api/chat` | `{session_id,text}`，后台任务；QQ 会话在网页只读 |
| `POST /api/import/preview` | `{content,format?}`，说话人数量与预览 |
| `POST /api/distill` | `{content,speaker,target,person?,scope?}`，target 为 self 或 interlocutor，后台任务 |
| `POST /api/persona/synthesize` | 整理现有证据，后台任务，结果与不确定项存入 synthesis |
| `POST /api/feedback` | `{turn_id,rating,note?,state_target?,memory_feedback?,action_target?,corrected_reply?,perspective_target?}`；倾向为 v0/v1/v2 |
| `GET /api/persona/export?scope=continuity` | 完整延续包，包含私密记忆 |
| `GET /api/persona/export?scope=template` | 精简目标人格模板 |
| `POST /api/persona/import` | 完整包，新建独立主体并切换；重复 ID 明确拒绝 |
| `POST /api/persona/new` / `/api/persona/activate` | `{name,seed?}` / `{id}` |
| `POST /api/persona/apply` | 同主体完整延续包；自动备份并保留聊天历史 |
| `GET /api/persona/revisions` | 当前主体心理状态版本目录 |
| `POST /api/persona/checkpoint` / `/api/persona/rollback` | 可选 `{label}` / `{id}` |
| `GET /api/export` / `POST /api/restore` | 完整主体备份 / 恢复，包含会话和事件 |
| `GET /api/messages?session=...` / `/api/memories` / `/api/events` / `/api/relations` | 已存对话、记忆、事件、关系 |
| `POST /api/memory` / `/api/boundary` | 人工记忆修订与边界规则 |

全量 JSON 包 / 备份 / 数值导入的请求上限 25 MB；其他请求 3 MB。真实长时数据库可停止程序后整体备份。

`pmm-core/2` 和 Adapter 的版本恢复不等同于完整主体状态回退。恢复心理检查点会保留之后产生的聊天记录，但不会自动将这些记录重新学习一遍。完整会话回退使用主体备份。

QQ 接口、事件白名单与 Token/HMAC 说明见 README；数值 PMM 独立服务接口见 `PMM_HTTP_API.md`。

## v2.2.1 执行、边界与陈述

下列管理接口沿用同源 Cookie、CSRF 与空闲检查，不暴露给 QQ 对话对象。

| 路径 | 合约 |
|---|---|
| `GET /api/execution` | 最近 60 个执行记录、最近 100 个 Outbox 状态和指标；默认脱敏 |
| `GET /api/execution/export` | 最近最多 2000 个执行记录，NDJSON；最后一行为 `summary` 指标，不含原始提示、消息或媒体 |
| `POST /api/execution/recover` | `{}`；仅恢复本机有有效回执而本地未提交的计划，不重发 QQ |
| `POST /api/execution/reconcile` | `{outbox_id,message_id}`；只读调用当前 OneBot `get_msg`，验证 bot、目标、完整消息和 ID；证据不足保留未知 |
| `POST /api/qq/retry-failed` | `{id}` 为 inbox ID；仅明确未发送的失败，且窗口未过时，才重新排队 |
| `GET /api/boundaries` | 软边界、候选、证据/反例、历史、最近实际评估、校准状态及外部硬约束 |
| `POST /api/boundaries/edit` | `op=save/confirm/correct/revoke`；已有项带 `boundary_id`；新项提供 `topic`，可设 `domain,stable_sensitivity,scope,recipient,disclosure_preference,relationship_condition,emotion_condition` |
| `POST /api/boundaries/calibrate` | `{turn_id,boundary_id,activation,action?}`；只接受最近实际评估，activation 为有限 0–1；同事件不重复标注，留出集不训练 |
| `GET /api/claims?scope=...` | 该情境最近 20 条 AI 历史陈述，默认 `private:web:owner`；陈述不等于事实 |

边界 domain 为 `disclosure/distance/load/emotion/values/autonomy`；动作见响应 `actions`。关系条件为 `{"distance_sensitivity":0.5}`，情绪条件为 `{"stress_sensitivity":0.5}`。新种子默认全局 `scope="*",recipient="*"`，通过 UI 可限制对象/情境。

执行中的 `candidate_status`、`delivery_status`、`memory_commit_status`、`learning_status` 分别表示候选、发送、写入及学习；不能用 HTTP 200 代替四种状态。`REFUSE` 对应内部 `decline`，`NO_ACTION` 对应有意不发言，`VALIDATION_FAILED` 则是故障。

`p50_first_ack_ms/p95_first_ack_ms` 只统计已确认的入站回复，包含聚合等待和推理的墙钟时间；主动机会耗时独立置于 `proactive`。阶段使用单调时钟。`user_receipt_time` 为 null，未测量客户端收信时刻；没有回执样本时指标为 null。

OneBot 11 依据：[HTTP 返回约定](https://github.com/botuniverse/onebot-11/blob/master/communication/http.md)、[发送与 get_msg](https://github.com/botuniverse/onebot-11/blob/master/api/public.md)。`async` 仅表示接受，标准 `get_msg` 不保证有目标字段；此时本实现不解除未知状态。

## v2.1 新增合约

GET `/api/psychology/registry` 返回原始 registry、固定 contract 和93条带范围/分组字段。GET `/api/state` 增加 `psychology_registry`、`dyads`；profile/对象模型的 `psychology` 为完整状态。模型信息含 `field_coverage`、`registry_contract`、`trained_features`（数值模式）与 `deliberation`。

POST `/api/config` 支持：

```json
{"deliberation":{"enabled":true,"mode":"auto","max_perspectives":4,"max_rounds":2,"log_level":"summary","return_unresolved_conflict":true}}
```

`enabled=false`与`mode=off`都会停用多视角调用，不停用PMM。配置改变经过同一空闲锁与验证，不重置主体。`mode`仅接受off/auto/always；两个上限为1–4。

每轮trace新增独立deliberation块：触发分数/版本/原因、activated/multi_view、每轮候选与评估、PMM复核、未解决分歧。`/api/feedback` 的 perspective_target 必须是该轮真实候选ID；来源字段被编码为动态门控监督，不冒充已测人格真值。

延续包格式更新为 `persona-package/2.1`，增加psychology_contract与dyads，仍读取2.0。新增learned模型`learned-pmm-v21`，检查点`learned-pmm/2.1`。单个370维待训练样本也必须携带registry_contract；旧184维队列仅经显式补零迁移。


## v2.1.1 补丁接口

- POST `/api/persona/settings`：`name`, `self_reference`, `initial_personality`, `seed`, 可选 `expected_revision`。只编辑当前主体；忙碌时拒绝，修订冲突拒绝。返回 profile 与修改前 checkpoint_id；不重置记忆或权重。
- 配置顶层以及 `pmm.api` 均增加 `thinking_mode`（auto/default/off/low/high）和 `thinking_adapter`（auto/deepseek/openai/anthropic/gemini/ollama）；复制 General 连接会一起复制。
- GET `/api/events?offset=0&limit=120`：最近事件，limit 最大 120；全部原事件仍保存。
- GET `/api/events/export`：导出全部事件 JSON。
- GET `/api/qq/status`：连接是否填写、最近已验证事件、最近 30 条收发状态与计时，不返回原始入站 payload 或认证凭据。
- 对话 trace 增加 `timing`；Provider call 增加生效 thinking、安全 request_options、失败信息和 duration_ms。HTTP 错误响应增加 `diagnostics`。
- 新事件：`character_updated`、`connection_test`、`turn_failed`。失败轮只记录诊断，不提交人格/记忆/训练状态。

## v2.1.2 补丁接口

所有管理接口继续要求本机会话 Cookie；写接口另要求 CSRF。后台任务返回 job_id，通过既有任务接口轮询。

| 方法 / 路径 | 行为 |
| --- | --- |
| GET/POST `/api/connection-presets` | 列出预设 / op=save,copy,rename,delete,apply,test；kind=general,pmm,qq |
| POST `/api/consolidation/run` | 整理一批长期反馈；retry=true 重试失败项 |
| GET/POST `/api/media` | 授权素材列表 / 添加或删除 |
| GET `/api/media/image/{asset_id}` | 认证后的本地素材预览 |
| POST `/api/media/preferences` | 设置用图偏好或记录真实发送反馈 |
| GET `/api/social` | 联系状态、授权与实际尝试记录 |
| POST `/api/social/preview` | 给定 scope，只预览、不发送 |
| POST `/api/social/unblock` | 管理者解除该 scope 的停止请求状态 |
| POST `/onebot/events/{persona_id}` | 可选定向事件入口，按此人格的签名/令牌、机器人号和范围校验 |
| POST `/api/memory/consolidate` | 整理一批记忆主旨；retry=true 重试 |
| GET `/api/memory/sources?id=...` | 返回该记忆的逐字引用和可用原文 |
| GET `/api/memory/erase-preview?scope=...` | 返回删除条数、影响与确认文本，不写入 |
| POST `/api/memory/erase` | scope + 完整 confirmation；删除本地范围并广泛重置当前人格学习影响 |

`/api/config` 新增 performance、media、social、turn_taking、group_attention、memory 节；`qq.self_id` 是绑定的机器人账号。`/api/state` 新增预设、应用记录、反馈队列、记忆队列、群聊知识状态；`/api/memories` 新增 memory_strength。原 `DELETE` 记忆操作仍是可恢复停用；LLM 无权调用会话彻底删除。数据格式与数值边界以 common.py 的验证为准。


## 2.2.0 追加接口

所有管理接口沿用本机登录 Cookie，写接口需要 CSRF。

- `GET /api/cognition`：机制、数值头更新步数/标签误差和最近事前决策，不返回训练输入向量。
- `POST /api/cognition/feedback`：`{"id":"决策ID","targets":{"turn_complete":0.8}}`；人工校准。
- `POST /api/qq/retry-appraisal`：`{"id":"收件ID"}`；仅允许 awaiting_input，不重发已发送/不确定发送。
- `GET /api/support`：只含允许字段的环境、配置选项、队列计数和异常定位。
- `GET /api/source` / `GET /api/source-index`：下载当前安装的完整源码和对应索引。
- `POST /api/config` 支持 `cognition:{mode:"adaptive"|"baseline",assessment_timeout:30}`。

完整人格包的可选 `cognitive_state` 保存认知头和人工标注；`memory_state` 增加 `open_events`，pending/traces 支持 event_id、appraisal、links/context。旧包缺少这些字段时使用空初始状态。


## 2.2.3 新增

- `POST /api/persona/clone`：`{"name":"新身份名称"}`；显式复制当前可用模板，创建新 ID，重置权重、连接和关系，返回新状态。不能用于同身份恢复。
- `GET /api/state`：`capabilities` 包含模块机制、state_updates_enabled、parameter_training_available、automatic_adapter_updates_enabled 与未完成项。未训练/未校准不因模型模式名变为已验证。
- `POST /api/config`：社交 recipient 支持旧的明确范围格式；纯数字只在私聊/群聊通道无歧义时转换。停用草稿可先保存；启用失败返回具体 failed_fields。


## 2.3.0 人格、情绪与表达

以下 POST 同样要求现有同源认证、CSRF，并且后台/QQ 空闲。每次请求携带当前 `persona_id`，防止切换主体后误用旧表单。

| 路径 | 合约 |
|---|---|
| `GET /api/state` | 额外返回 `trait_snapshot`、`disposition_registry`、`affect_state`、`trait_review`；旧 activity 只是派生兼容视图 |
| `GET /api/affect` | `{persona_id, affect_state}`，按当前现实时间返回视图，不因轮询增加情绪版本 |
| `POST /api/traits/disposition` | `{persona_id, feature_id, expected_version, estimate:0..1或null, source_type:"owner_seed", timeframe:"habitual", note}`；可编辑原长期字段与新 BEQ/ERQ；PANAS 需 generally |
| `POST /api/traits/review` | `{persona_id, apply:false}` 只审查；`apply:true` 晋升符合门槛的候选。返回 candidates/reasons/promoted/trait_version；旧记录保留 |
| `POST /api/affect/parameters` | `{persona_id, baseline:{valence,arousal,dominance,stress,engagement}, emotion_tau_seconds, mood_tau_seconds, reactivity}`；只改本主体工程动力学参数，不改人格 |

长期字段更新必须携带当前 TraitProfile.version。未知用 null；owner_seed 的不确定性是设定确定性，不是人类量表测量误差。问卷写入仅支持新习惯字段，`source_type:"questionnaire"` 同时要求 `measurement` 中包含 instrument、version、scoring_method、normalization、timeframe、respondent、respondent_type（self_report/informant_report）及 authorized=true；不能把模型自答标成正式问卷。

`trait-affect/1` 包含独立 emotion、mood、appraisals、regulation_actions、expressions、trajectory、transition_params 与 migration。emotion 的 VA/D、压力、参与和 12 标签可未知，事件/评价 ID、时间和 state_revision 单独记录。ExpressionPlan 是计划，ExpressionState 是实际提交，二者不可互换。只有真实成功 Outbox 回执才标 qq_acknowledged；单纯 QQ scope 不足以证明发送。

API-PMM 继续使用独立连接，旧 PREPARE 字段兼容。新增可选返回示例：

```json
{
  "layered_affect": {
    "schema": "trait-affect/1",
    "subject": "agent_self",
    "evidence_quote": "逐字引自当前输入",
    "appraisal_checks": {"affect.appraisal.goal_conduciveness": 0.4},
    "emotion_proposal": {"valence": -0.2, "arousal": 0.4, "dominance": null, "categorical_activations": {"anger": 0.2}, "confidence": 0.4},
    "regulation_proposal": "cognitive_reappraisal"
  }
}
```

这只是当前事件提案，不是直接覆盖状态；运行时结合固定本轮 TraitSnapshot、时间衰减、反应性与调节后计算实际状态。未知标签可省略或 null。禁止加入 HEXACO/BEQ/ERQ/价值写入字段，禁止 subject=model_of_other 写入 AI 自身。校验失败记录 `/layered_affect`，最多一次协议修复，仍失败则本轮不提交。省略新字段时报告 `legacy_prepare_v2_degraded` 和具体 unsupported_features，不声称已支持全部新输入。

新数值监督附加 `training_context={schema:"typed-supervision/1",target_entity:"event_state"|"trait_promotion"|"imported_history",event_id,scope,at}`。原始样本不强行补时间。保持原 370 维/93 列与合约，event_state 的长期标签被屏蔽，各类型 loss 独立归一化。BEQ/ERQ/PANAS 尚无神经 encoder 列与训练头，模型状态明确给出新习惯训练步数为 0。

连续包导出为 `persona-package/2.3`，同时读入 /2.0 和 /2.1；完整主体快照与模板仍有各自用途，详见 `MIGRATION_NOTES.md`。


## 2.4.0 表达规划与语用标注

`GET /api/state` 新增 `pragmatics`：独立人类示范概况、条件化统计、AI 行为观测、人工反馈、近期计划与可标注事件。仅本地已认证管理会话可读。

`POST /api/pragmatics/annotate` 接受 `persona_id`、`episode_id`、`field`、`value`（0..1）和 `note`（1..1000 字符）。要求当前主体、空闲状态、CSRF 校验和真实人类示范 ID。同一事件/字段修订不增加独立样本数。

连续包 `/2.3` 新增可选 `pragmatics`。新聊天 Trace 包含 `interaction_plan/2.1`；QQ 回执包含逐步 SENT_ACK/CANCELLED/UNKNOWN 状态。公开支持诊断只包含去内容的表达摘要，原文仍留在本地授权查看界面。

## 2.6 D/E 证据与结果

沿用本机同源 Cookie/CSRF；人工写入须空闲且 persona_id 与当前主体一致。目标值为有限 0–1，note 必填，最长 1000 字。

| 路径 | 输入及语义 |
|---|---|
| GET /api/de/turns?offset=0&limit=12 | 当前主体的原始输入 ID、D/E 版本、局部评分用途、计划/实际气泡、已确认内容、回执与独立反馈；limit 最大 30 |
| POST /api/pragmatics/annotate | persona_id, episode_id, field, value, note；对有来源人类示范标注，只生成候选 |
| POST /api/pragmatics/target | persona_id, turn_id, field, value, note；仅允许有成功发送事实的回合，作为独立外部评价 |
| POST /api/pragmatics/review | persona_id, candidate_id, expected_version, evidence_digest, action=apply/reject/revoke, note；检查门槛及当前权限，返回 changed_fields/reasons/version |
| GET /api/state | 增加 de_turns 与扩展的 pragmatics；各模块读取失败单独显示诊断 |
| POST /api/chat | 原 session_id/text 外可带 client_event_id（1–128 字符）；相同 ID 已提交则返回原回合，不重发/重复学习；相同 ID 改内容拒绝 |

审核目标与原描述统计独立。版本或证据摘要过期会拒绝审核；未达门槛时返回 ok=false、reasons 与空 changed_fields。原始反馈/输入仅在所有者管理页面可见，公共脱敏执行导出不包含联合原文。API-PMM 的条件中新增 de_conditions（de-expression/1），各字段保留独立版本与来源，现有模型供应商协议不变。


## 2.7 证据、人物与固定条件对照

沿用本机所有者会话、CSRF与主体隔离。新增POST均需当前`persona_id`；版本字段分别对应人格trait version、social_graph version或关系schema_revision，过时请求拒绝，不自动覆盖。

| 路径 | 输入与用途 |
|---|---|
| `GET /api/evidence` | 可选`scope,person,event_id,offset,limit`，统一来源、应用回执及修订；范围过滤会删去混合修订中的越界详情 |
| `GET /api/people?scope=...&person=...` | scope必填且不能为星号；person可选，返回范围身份、关系与原文依据 |
| `GET /api/formation/interactions?scope=...&person=...` | 查询实际已发送的经历，供独立行为评价选取 |
| `POST /api/people/edit` | `persona_id,expected_version,scope,person,alias,source_key,quote,op`；op为annotate/dispute，quote须逐字来自同范围真人记录 |
| `POST /api/relationships/revise` | `persona_id,expected_version,scope,person,id,op,reason`；op为dispute/retract/restore，保留历史 |
| `POST /api/formation/annotate` | `persona_id,expected_version,experience_turn_id,feature_id,estimate,confidence,note,timeframe`；可选context_label/context_quote，后者必须引用该经历原输入；具体时间框架按注册字段检查 |
| `POST /api/formation/withdraw` | `persona_id,expected_version,record_id,reason`；来源与历史保留，停用依赖先验并移除相关待训练标签 |
| `POST /api/research/decision-compare` | `persona_id,turn_id`，可选`feature_id,low,high`；只读执行同一policy/affect局部对照，默认耐心0.2/0.8；旧回合无冻结输入时明确拒绝 |

原始来源和完整对照是所有者后台内容，不是给任意QQ对象的查询接口。API输出不宣称现实身份认证、心理学置信区间或真实LLM反事实效果。
