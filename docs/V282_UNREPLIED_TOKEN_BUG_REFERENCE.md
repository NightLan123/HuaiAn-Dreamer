# 槐安梦客 2.8.1：未回复故障、Token 异常及逐阶段可视化——紧急修复规格

日期：2026-11-04。依据：用户提供的单轮故障 JSON（turn_id=`ab580f19d0794917a975823a8d82f391`，trace_id=`69368c2dee2d493dbb045ae4b3aa42e8`）、最新 2.8.1 `HuaiAn_Dreamer_Source.md`，以及此前“分析未回复原因”的已经确认的错误类型。**以真实源码为准实施；这份文件是故障与优化开发任务，不是已修改的源码。**

## A. 本轮已证实的事实（不允许误报成超时）

- `selected_action=clarify`；候选检测为 `reply`；第 4 阶段 `candidate-action-check/1` 的 `/spans/0` 出现 `invalid_evidence_span`；尝试 0 和 1 均失败，最后 `VALIDATION_FAILED`；`delivery_may_have_occurred=false`。候选在发送前被拦截，不能归因于网络未返回。
- `spans[0]` 的 `actual_type=object` 并不意味着类型错误；`validation.py:candidate_check` 第101–102行要求对象内含 Python 字符偏移 `start,end` 且 `candidate[start:end] == quote`。失败可能由偏移越界、引用不匹配、整数缺失等造成；由于日志不含原始 candidate 与 span，无法唯一确定哪一种。另有行动不一致，须单独处理。
- 五次实际模型调用如下（缓存属于输入Token的子集，不可与输入再次相加）：

| 责任模块/阶段 | 输入 | 输出 | 命中缓存 | 未命中缓存 |
|---|---:|---:|---:|---:|
| General：第1阶段理解 | 15010 | 208 | 384 | 14626 |
| PMM API：第2阶段心理准备 | 28186 | 1305 | 768 | 27418 |
| General：第4阶段生成 | **64047** | **17** | 17536 | 46511 |
| General：第4阶段首次校验 | 13146 | 135 | 256 | 12890 |
| General：第4阶段二次校验 | 13435 | 126 | 13056 | 379 |
| 合计 | **133824** | **1791** | **32000** | **101824** |

总调用 Token 135615；生成请求输入64047，但输出仅17 token、候选24字符。**主矛盾是输入上下文膨胀，不是模型输出过多**。`max_tokens=4096` 是输出预算，不约束输入 Token。

## B. 代码级原因：已确认结构性膨胀点，精确贡献待计量

1. `persona/engine.py` 633–646：生成请求把 `REALIZE + dumps(conditions)` 作为系统提示，再追加 `*history` 与当前输入；`conditions` 同时放入 `self=profile_condition`、`trait_prior`、`interlocutor=profile_condition(other)`、`emotion`、`decision_conditions`、`boundary_model`、`memories=memory_context(memories)`、`pmm_decoded`、`decision`、`style`、`expression_plan`、`interaction_plan`、`de_conditions` 等。存在语义重复和嵌套冗余，某些字段包含同一人格、情绪、决策信息。
2. `persona/engine.py:98–99` `memory_context` 使用 `{**m,...}` 扩展整个检索对象，连同动态评分、记忆强度、来源详情和额外 `epistemic` 一起进入提示词；即便内容被局部截断，也没有单次请求总预算。生成与候选校验还重复发送这些对象。
3. `persona/engine.py:380` 理解阶段也携带历史、人格快照、身份、关系、边界、状态；`persona/api_pmm.py:64–92` / `persona/pmm_event_reasoner.py` 的事件解释又传入完整人格和记忆。相同资料跨阶段重复计费。
4. `persona/engine.py:653–663` 候选校验把 `evidence_context=memory_context(memories)` 与边界、知识、决策等再次发送；`persona/validation.py:56–79` 校验失败时又发送原请求加错误及上一模型输出，引起额外调用。不能因缓存命中就认为没有Token成本。
5. `persona/provider.py` 已能从响应记录 `usage`，`persona/diagnostics.py:response_meta` 支持 Ollama、DeepSeek兼容API、Anthropic、Gemini等，但目前没有**预发送的字段级 Prompt 预算与账本**；无法从已有日志精确计算每个 `conditions` 字段的Token贡献。**禁止把上述结构诊断伪装成准确字段百分比。**

## C. P0：先修“明明已生成但不能回复”

### C1. 校验故障分型

在 `persona/validation.py` 将 `invalid_evidence_span` 细分为 `missing_offsets` / `non_integer_offsets` / `out_of_bounds` / `quote_not_substring` / `offset_quote_mismatch` / `ambiguous_duplicate_quote`，逐项输出只含字段和摘要的安全诊断。

对模型返回的quote若**确实存在于candidate中且唯一匹配**，本地重新定位字符偏移，不需再调用LLM；若找不到、重复或存在严重内容问题，不得伪造片段。把这种可证明等价的校正规范化记录为 `span_offset_normalized`。加中文标点、emoji、Unicode组合字符、换行、多气泡与重复引文单测（采用Python字符索引契约）。

### C2. 分开检查行动不一致

`expected=clarify/detected=reply` 不能用修span来忽略。追加上游 `decision.gate`、必要信息缺口、候选文本摘要（默认本地受控存储、导出脱敏）、验证器引用和不一致原因；查明是决策上游过度强制clarify、回复生成未遵守，还是校验器误判。

先做无需LLM的格式/证据检查；只有内容语义或行动确有争议时再请求语义检查。需要再生成时用**简短冻结行动、明确待澄清的信息、当前输入及候选**重新生成，不能复制整份64k上下文。不得静默改为reply、不得绕过硬边界、不得因验证失败伪装成`NO_ACTION`。

### C3. 失败恢复与投递一致性

既有QQ执行日志 / outbox / ACK逻辑完整保留。候选已生成但未投递：在UI显示“生成成功、校验未通过、发送未尝试”，提供有上下文约束的重试入口；自动重试要有有限次数和Token预算。确定已ACK的消息不得再次发送；输出失败时不学习生成但未发送的内容。将 `VALIDATION_FAILED` / `DELIVERY_FAILED` / `DELIVERY_UNKNOWN` / `NO_ACTION` / `WAIT` 分离。

## D. P0：建立**精确Token账本**（先计量，后优化）

新增：`persona/token_ledger.py` 或类似独立模块，复用现有 Provider 和 ExecutionJournal，记录每次请求（不记录原文及密钥）：

```
turn_id, trace_id, call_id, parent_call_id, attempt, retry_reason,
phase_id, phase_name, component_role [General|PMM-A|PMM-B|PMM-other],
model, protocol, endpoint_type, status, duration_ms,
prompt_tokens, completion_tokens, total_tokens,
cache_hit_tokens, cache_miss_tokens, reasoning_tokens,
usage_source [provider_actual|local_estimate|unavailable],
prompt_sections [{section_id, chars, estimated_tokens, digest}],
input_budget, over_budget, outcome [accepted|repaired|rejected|skipped],
model_version, prompt_schema_version
```

1. **请求发送前**：在组装器中为每个消息块分配确定的section ID，包括 `system_core`、`persona`、`values`、`emotion`、`relationship`、`memory`、`history`、`decision`、`style`、`other`；按供应商对应tokenizer估算，标记为 `estimated`，至少保存字符数与字节数；不声称字符数等于Token数。不同供应商特殊Token与JSON开销归入 `protocol_overhead`/unattributed。
2. **响应返回后**：按真实服务Usage统一字段（Chat Completions `prompt_tokens` / `completion_tokens`; Ollama `prompt_eval_count` / `eval_count`; Anthropic input/output tokens，Gemini `promptTokenCount` 等），保留原始usage供复查，但只对真正的输入/输出求和，不能重复累加嵌套缓存字段或reasoning子项。模型无Usage时展示“缺失/估算”，不得当作0。
3. 同一阶段的重试与修复都必须计入该阶段；独立模型A/B调用分开；本地NumPy/PyTorch执行记录耗时/执行次数，其LLM API Token计0（如调用LLM则应归属其远程调用）。
4. 将每一轮所有阶段连成唯一trace，失败、重启、回退仍能查询；界面实时显示本次输入预计Token（请求前）、已返回的真实Token（请求后），并明确区分两者。
5. 缓存命中/未命中、推理Token、成本（用户输入模型/价格后估算）分别统计。缓存命中是输入的子集，**不得加总到输入Token上**。价格不明确时不展示假定金额。
6. 个人资料和消息正文不进入Token日志。分项统计使用section名、估计Token、摘要哈希；敏感日志本地保存并可清理、导出脱敏版。不能记录完整API Key、隐私记忆、原始个人聊天以供可视化。

## E. P1：分阶段减重，不牺牲PMM核心功能

新增 Prompt Compiler / ContextBuilder，按任务构造不同的**最小必要证据包**，不要通过无差别裁掉人格、记忆或长期状态来“优化”。

| 阶段 | 应当发送 | 不应重复发送 |
|---|---|---|
| General理解 | 当前文本、关键对话、必要身份/边界与情境 | 全量心理档案、无关记忆细节 |
| PMM-A事件评价 | 结构化情境、必要人格/关系状态、筛选后的证据片段 | 旧长说明、整份检索对象、重复快照 |
| PMM-B认知协商 | A的事实/评价摘要、神经与情绪结果、冲突点和相关证据ID | 再读整份原始数据和冗余人格说明 |
| 生成回复 | 已冻结行动、短人格表达条件、当前情绪/风格、必要事实与短历史 | `pmm_decoded` 整包、完整`profile_condition`重复项、完整评分对象 |
| 候选校验 | 候选、冻结行动、相关边界、实际需核对的事实/引文 | 与该候选无关的全部记忆、长人格设定 |
| 后台反馈 | 经确认送达的输入/输出、相关记录引用 | 全量construct registry每轮重复 |

保留来源ID与原文证据映射，必要时按ID二次检索，不要把删除来源检查等同于优化。对于长任务允许动态扩充；每次扩充须记录原因与分项增量。建议**把普通短消息的64k级输入作为需要解释的警示**，通过真实回放对比优化前后Token，而不是强行写死所有请求不超过某个数字。可提供阶段预算（例如：短消息生成目标4k–8k输入、复杂任务可调）作为产品默认候选值，需测量验证后定稿。超过预算先去重、分级摘取、保留硬约束和关键信息；无损缩减失败时明确报预算不足，不擅自丢弃关键规则或静默换模型。

## F. P1：可视化Token仪表盘，直接嵌入现有“PMM运行记录”

**固定概要区**：本轮总Token（输入+输出）、输入、输出、缓存命中/未命中、实际调用次数、校验重试次数、耗时、状态，以及估算费用（有用户配置单价时才展示）。

**核心图**：六阶段横向堆叠条（每阶段按 General / PMM-A / PMM-B /其他 分段，可切换输入/输出/缓存）；每阶段右侧标注调用次数与总Token。无远端调用的阶段标记 `0 (无LLM调用)`，未执行的阶段标记 `— (未执行)`，不可混淆。

**组件拓扑**：General、PMM-A、PMM-B、神经人格、情绪、记忆、关系与候选校验；每个结点显示最近执行状态、耗时、调用次数、Token（本地NumPy注明 `本地计算，无LLM Token`）。

**展开一阶段**：按实际调用表列出模型、请求序号、尝试次数、输入、输出、命中/未命中缓存、原因、耗时与结果；点击可看输入构成条形图（人格、记忆、历史、决策、风格等估算贡献及残余开销），不显示敏感原文。

**设置**：输入预算目标、异常预警阈值、Token历史清理策略、是否展示估算费用；高级设置默认折叠。所有状态名附一个短功能说明，禁止防御性空话。

**趋势**：最近20轮／100轮／24小时按阶段Token和失效率，突出异常、重试增加和峰值；可导出脱敏JSON/CSV供科研分析。

## G. 关键验收条件（需要真代码、真请求）

1. **故障回放**：使用该turn的脱敏等价fixture重现 `(clarify,reply,invalid span)`；首次本地偏移修正不发送LLM；真正行动冲突不得凭span修正误放行；重复失败可显示具体失败和处理入口，不发生假沉默。
2. **Token对账**：该turn回放账本能准确聚合为输入133824、输出1791、总135615、缓存命中32000、缓存未命中101824；重试调用计入第4阶段。不能混合阶段耗时和Token。
3. **字段级定位**：测试环境中构造10条长记忆、长人格设定、重复表达条件，真实记录分项估计并能定位最大字段；请求前后Token来源标记清楚。
4. **优化对照**：同一固定输入/模型/种子（可用的情况下）比较原与新Prompt，列出每阶段实际输入Token、最终行动一致性、事实与边界遵循、证据引用准确率、回复质量；不能只报告省Token百分比。
5. **A/B双接口**：云端和Ollama各自Usage正常；独立A/B可分账、共用模型仍按任务归属分账；所有异常和重试可追溯。
6. **零误计**：纯NumPy/本地PyTorch计算不显示为云Token；API无Usage显示缺失；没有输出或未调用的阶段状态明确；缓存子字段不重复求和。
7. **发送事务**：异常场景验证不重复QQ发送、不将未送达文本写成已发生经历，不对长期人格产生误提交。
8. **完整回归**：重跑2.8.1既有709项Python和116项HTTP/DOM及浏览器检查；真实模型和QQ环境另行报告，不用mock冒充实机。

## H. 开发顺序与交付

- **阶段0：** 备份目前2.8.1，抓取脱敏失败回放，固定测试。
- **阶段1 P0：** 校验分型、局部证据定位和行动冲突修复；保留冻结决策、硬边界、投递事务。
- **阶段2 P0：** 全部Provider适配器统一Usage，建立请求前分项账本与回合汇总，并使失败时仍可看到Token。
- **阶段3 P1：** Prompt Compiler：从生成阶段先去重，再治理PMM-A/B和校验；对照实际Tokenizer数据，保留必需语义和证据。
- **阶段4 P1：** PMM页面加入Token仪表盘、阶段图、调用明细、输入构成、趋势和预警。
- **阶段5：** 全回归、真实Qwen/API、故障注入与QQ投递验收，报告从64k级输入下降的实际程度（没有数据不预填节省率）。

交付：更新后的完整源码、测试结果、故障根因链（代码位置与复现样本）、真实Token账单示例、可用的可视化页面截图、与旧版兼容升级/回滚记录。**修复报错和Token优化不得擅自废除复杂人格、情绪、记忆和决策机制。**
