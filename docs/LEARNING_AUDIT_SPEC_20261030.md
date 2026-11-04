# 槐安梦客 2.2.3-H2：人格、情绪、学习与整理功能核对

日期：2026-10-30。依据：本回合实际解压和检查 `HuaiAn_Dreamer_2.2.3_H2_Complete.zip` 的 `persona/`、`web/` 源码；截图由用户提供。没有读取用户本机正在运行的 SQLite 或私密聊天，因此不能确认本机具体任务是否已经成功、失败或参数变化数值。新增 H2 专项测试 7 项通过；并非本机 QQ/DeepSeek 实机验收。

## 1. 查核结果

| 用户疑问 | 现有 H2 代码 | 结论 |
|---|---|---|
| 人格证据整理有用吗 | `web/app.js:153` [在此文件中搜索 `synthesizePersona`] → `/api/persona/synthesize` (`persona/server.py`) → `persona/engine.py:synthesize()` → `persona/api_pmm.py:APIPMM.synthesize()` | 只做**报告**；提交 `pmm_synthesis` 和操作事件，不写 `pmm_profile`、`pmm_checkpoint` 或队列，因此不影响后续决策条件。报告主要用于 Web 展示与导出。 |
| “基于人格修订 33”是什么意思 | `web/app.js:renderSynthesis()` 读取报告的 `profile_revision` | 只是报告生成所依据的人格版本，不表示此报告修改了 33 个字段。`apply_distillation()` 在收到新原文时可以增加 revision，即便具体数值没有实质改变，故 revision 也不是有效学习量。 |
| 自动人格蒸馏实现了吗 | `persona/engine.py:_turn()`、`persona/consolidation.py:Consolidation.run()` | **部分已实现**：同步或后台反馈会尝试更新自身 `pmm_profile`、他人 `pmm_interlocutors`，但这不等于完整的跨历史再学习或可靠的人格形成。QQ 默认常走 deferred。 |
| 自动整理何时触发 | `persona/consolidation.py:due()` + `persona/qq.py` 的 poll | 有 pending 队列且达到批次量、空闲时间、字符预算或紧急标记之一才触发；运行依赖后台轮询；失败保存于 `consolidation_last`，不等于沉默。 |
| 手动蒸馏聊天 | 「学习资料」页面 → `/api/distill` → `persona/engine.py:import_records()` | **已有**，但要上传/粘贴记录并选定说话人；可写自身或指定交谈对象。用于自身时可训练 Learned Adapter，或存储 API 估计。 |
| 手动蒸馏当前已存的近期/全部聊天 | 无统一历史范围选择器与回溯任务 | **未实现**。已有 `/api/consolidation/run` 只清当前 `consolidation_queue` 的 pending/failed，不能自动扫描全库所有历史；`/api/memory/consolidate` 专供记忆要点整理，不是人格学习。 |
| 手动点击后台整理 | 「诊断记录」→「运行设置」→「回复速度与后台整理」→「现在整理一批 / 重试失败项」 | **已有但位置深**，只处理队列中的未完成工作；队列空返回 `processed:0`。 |
| 记忆要点蒸馏 | 「记忆」→「整理与来源」→「现在蒸馏一批 / 重试失败项」 | **已有**，`memory_lifecycle.py` 提取记忆要点，不自动更新自身 HEXACO/语言风格。 |
| 自己的情绪怎么变化 | `persona/affective_layers.py:advance_activity()` 及 `apply_event()` | 四维状态可在读取时依据现实经过时间推演、在交互事件中更新；固定未校准的时间尺度和混合公式，尚无真实人格条件化 24 类情绪、完整调节/主动内部评价。单纯读状态不会自动把时间推演结果写回数据库。 |
| 长期 BEQ/ERQ 会自动学习吗 | `affective_layers.py:empty_dispositions()` 和 `disposition_view()` | **暂无学习/晋升写入链路**；提供了独立数据表征和 UI 只读显示，但不能称为已训练。 |
| 对话风格自动蒸馏 | `psychology.py:style_stats()`、`engine.py:pmm_expression`、`persona/expression_plan.py` | 真正的目标风格主要来自导入记录/人类明确校正；AI 自己生成的语句被记录为观测和执行结果，不能被作为真实人类示范。完整多轮语用学习仍未实现。 |
| 对方人格是否自动判断 | `engine.py:apply_distillation(...,source='observed')`、`consolidation.py:run()` | **部分已有**，但未形成可审计、独立的实时人物模型更新流程；需展示未学习、证据不足、待整理、更新成功等状态。 |

## 2. 证据真正怎么流动

```
A. 证据整理（现有）：当前 pmm_profile.source_records 最后100条 → PMM生成 statements → 验证原文引用 → pmm_synthesis → 前端展示/备份
                                               [不进入后续回话条件]
B. 对话自动学习（现有）：收到消息 → 立即/延期的反馈 → apply_distillation(self/other) → pmm_profile/pmm_interlocutors → 下一轮 profile_condition
                                           \→ Learned 训练候选（仅在相应模式/开关满足时进行优化）
C. 手动导入（现有）：文件/粘贴 → parse_records → 蒸馏 → pmm_profile 或 other_model → 训练候选/参数（视模式）
D. 记忆要点（现有）：memory_pending → memory_lifecycle → gist/semantic memory → 供后续检索
```

特别警示：`psychology.py:apply_distillation()` 对 `source='generated'` 的旧 `traits` 观测仍允许低权重输入；当跨新记录 ID 累积到阈值时，可能触发每次最多 `.003` 的旧特质修订。虽然 `registry.py` 已对生成内容写入稳定 HEXACO 的路径有限制，这仍是一条需要消除的自举强化风险。`api_pmm.py:synthesize()` 的报告虽然提示“AI 自己生成仅是行为观察”，但没有将 generated 源彻底排除出长时人格结论。应修复为：仅用于表达监测与事实核查，不作为独立稳定人格证据。

## 3. 需要增补的统一功能（按优先级）

### P0：区分显示和真正应用
- 将原按钮改名为「生成证据整理报告」，并在报告标题旁明确写「未更新人格 / 未更新模型权重 / 不参与后续决策」。
- 如果设计为「审阅并应用」，须单独执行证据晋升、前后差异计算、可拒绝和回滚，不能静默应用整个自由文本报告。
- 新增独立「学习活动」页：逐任务显示来源范围、事件数、来源独立性、当前阶段、耗时、Token 与费用、是否更新了 Self/Other/Language、哪些参数发生了实际变化、失败原因和追踪 ID。

### P0：稳定人格与生成语言隔离
- `source='generated'` 绝不作为独立真值证据直接提升 Self Trait；模型自己的回复只用于 `expression_observation`、行为连续性检验及有限的交互反思。
- “revision/修订次数”与“实际字段更新数”分开，报告真实 `changed_fields`、`unchanged_fields`、`reasons`；同类重复输出不叠加独立证据。
- 对旧版积累的生成来源证据提供审核/重算，不直接清空历史或权重。

### P1：新增历史回溯手动学习与自动调度
- 统一任务 `LearningJob`：`source={live,inbox,conversation,scope,all_history,import}`, `target={self,other,relationship,language,memory}`, `mode={manual,automatic,review}`, `range={since,until,unprocessed,all}`。
- 从已有消息、事件与记忆的**真实原文**建立可追溯输入；已压缩的 gist 只能当检索线索，不能取代没有原文支持的评分证据。
- 只允许授权范围扫描；每条消息有稳定 source ID 和每目标学习游标，实现幂等、去重、分批、继续运行和中止。
- 运行前展示预估工作量与 Token 预算；“全部重新学习”支持多批次而不是单个超长 LLM 请求。
- 自动调度周期/触发门槛、学习范围和强度可独立控制；人工设置 0% 应不推进长期学习，但不影响普通理解/必要隐私行为。
- 自动及手动调用同一底层学习管线，仅触发方式不同。保留原有 API-PMM 与 Learned-PMM 的差别。

### P1：即时情绪与长期人格严格分层
- 明确 EmotionState/MoodState/Disposition/TraitProfile 独立的持久记录与时标。现阶段的 VA/四键时间演化只是未校准基线。
- 内部没有新事件时，可由时间演化触发心境投影；真正主动的认知事件应通过独立事件协议记录，不能凭随机值更新稳定人格。
- 当前情绪变化与人格字段修订必须分别显示，避免「情绪变化」被用户误解为人格被训练。

### P1：语言蒸馏闭环
- 将授权的真人聊天、AI 已发送话语、用户明确校正、聊天接收分段信息分别存储，不混合为训练标签。
- 显示语用习惯的来源/版本、实际用在什么回复、与本次表达计划的差异，避免仅统计长度/问号或连发比例。

## 4. UI 目标

一级导航：`自身人格`、`交谈对象`、`人际网络`、`学习与蒸馏`、`记忆`（保留已有模型连接和诊断页面）。

「学习与蒸馏」内显示：
- 概览：自动学习开关、最后成功/失败任务、下一次触发条件、待处理事件数、上次已影响的模块、Token 成本。
- 新建手动任务：目标（自身/某对象/语言风格/关系/记忆）、时间范围（最近 N 轮/最近 N 天/选定会话/全部授权历史）、学习模式（仅分析/候选审核/证据晋升）、预算上限、执行。
- 学习历史：每次任务实际输入量、报告与**真正写入**的字段差异，任务状态、错误信息、版本回退。
- 来源证据：原文/来源类别/可靠性/是否独立/与当前估计的关系。

## 5. 必测用例

1. 只点「生成证据整理报告」：`pmm_profile` / `pmm_checkpoint` 不变化，UI明确标记只是报告。
2. 人格字段全无有效独立证据：能生成不确定报告，但 Self 特质不被写为伪确定数值。
3. 一次真实外部证据 + 30 次 AI 自己相似回复：不会形成 30 份独立人格证据或明显人格漂移。
4. 手动选择最近 20 条真实对话学习：如有有效新证据则可审阅/晋升，并显示 `before -> after`；重复运行不重复算。
5. 手动选择全部历史：分批去重、跨群/私聊边界、用户授权、预算、可恢复。
6. 自动整理同一来源：只算一次；`pending=0` 应显示「无待处理任务」，不是「人格蒸馏完成」。
7. 同一条用户消息引发情绪变化，不应直接修改 HEXACO、BEQ/ERQ。
8. 自身与对方不同的证据来源；双方模型和关系数据不串写。
9. 修改人格后下一次 PMM 决策读取新 profile revision；报告不参与则不得假称生效。
10. 原 93 字段顺序、既有聊天、人格包、模型权重兼容迁移；有备份及回滚。

## 6. 验收状态限定

此文是源码核对和下一轮开发规范，**没有修改 H2 运行源码**，也不能证明截图中用户本机那次 `2026-10-30 01:34` 的整理在其 SQLite 的实际落盘状态。若需验证本机的真实变更，导出脱敏 `pmm_profile` 各版本的特质数值、`pmm_synthesis` 元数据、`consolidation_last` / `consolidation_queue` 摘要及相关 `persona_synthesized`、`consolidation`、`distillation` 日志，禁止上传密钥或未授权私密聊天原文。
