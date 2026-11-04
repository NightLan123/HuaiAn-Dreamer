# 槐安梦客 2.4.0 — 讨论需求与遗留问题复核（2026-10-30）

**审计基线**：已取得完整 `HuaiAn_Dreamer_Source.md`（2.4.0）、`HuaiAn_Dreamer_v240_CBM_Report.md`，从前者抽取 174 个实际文件并检查关键调用路径。对照历史「UI 表达问题记录」「分析未回复原因」及近期有关 PMM/人格/情绪/蒸馏/关系/CBM 的讨论。**这是静态源码审计和已有本地测试记录的复核；并未读取用户电脑正在运行的数据库，不代表生产环境现场验收。**

## 实现状态判断口径

- **已实现（本地）**：对应运行路径存在，并有本地测试或实现报告；仍可能需要真实平台联调。
- **部分**：存在数据/入口/子流程，尚不能达到讨论要求。
- **未实现**：本次在 2.4.0 没找到对应完整运行路径。
- **待实机/科研验证**：可能有实现，但尚缺真实平台或独立心理学数据。

## 0. 2.4.0 已做，不能继续当作完全缺失

- CBM-01 多气泡实际发送、逐条回执、已发送前缀回流、中断/未知送达分类：已实现（本地）；`persona/expression_plan.py`、`execution.py`、`qq.py`、`engine.py`。
- 自然对话：MINIMAL_REPLY、RESPOND_AND_YIELD、CASUAL_BURST、可选补充、澄清、修复，减少无必要追问；已实现工程机制，神经语用学习/真实自然度尚缺；`expression_plan.py`、`pragmatics.py`。
- 表达倾向页面（人类示范、AI 实际表现、计划和回执），及有界指标进度条＋数值：已实现（本地），实际浏览器视觉未验。
- 人格/情绪分层基础、VA+D/压力/参与、12 情绪标签、BEQ/ERQ/PANAS 长期倾向数据结构、跨情境人格候选审查：已实现基础结构/部分机制，心理效度未校准；`affect.py`、`traits.py`。
- 手动**导入**聊天蒸馏、待办队列立即整理、记忆要点蒸馏、资料来源标签：已有不同入口，但**不是**统一历史回溯学习中心。
- P0 发送账本与有限结构重试有代码，旧 Phase 3/5 故障有本地修复测试；不等于所有新故障已消除。

## A. 故障与可靠性

| ID | 优先 | 状态 | 需求 / 2.4.0 发现 | 实际路径/建议 |
|---|---|---|---|---|
| ERR-NEW-01 | P0 | **未解决现场故障** | 真实日志中 `/boundary_appraisal` 应为列表却返回对象；一次修复后五条 quote 全部 `ungrounded_evidence`，`VALIDATION_FAILED` 且未产生行动。2.4.0 仍采取严格列表和逐字 quote 校验；现有单次 repair 不能保证可恢复。应区别契约输出/证据对齐/模型供应商行为，保留可信原文并有界重试，不能放宽到接受虚假证据。 | `persona/boundaries.py:api_appraisal`；`api_pmm.py:prepare`；`validation.py:validated_call` |
| ERR-OLD-02 | P0 | 本地修复，**待现场复测** | 历史 Phase 3“行动效用/视角字段无效”和 Phase 5“最终回复与行动不一致”已有校验/重试/回执工程机制，但须用原问题或真实模型新 trace 复测。 | `validation.py`、`engine.py`、`execution.py` |
| ERR-QQ-03 | P0 | 本地实现，待实机 | 需要实测 QQ 单条/多气泡、部分送达、OneBot 超时、发送状态 UNKNOWN、重启恢复与中途新消息打断；合成测试无法证明真机可靠。 | `qq.py`、`execution.py`、`test_cbm_v240.py` |
| PERF-04 | P2（暂缓） | 部分 | PMM Token、长时延、真实阶段 P50/P95 及不必要重复调用的优化未完成。用户当前指示暂不优先优化 Token，保留诊断与后续任务。 | `diagnostics.py`、`engine.py` |

## B. UI 表达问题记录（原截图）

| ID | 优先 | 状态 | 2.4.0 现状 / 未完成要求 | 路径 |
|---|---|---|---|---|
| UI-001 | P1 | **部分** | 边界校准提交后有保存/数值头更新或 API 样本保留，界面只有 toast；缺少“写入何处、训练/留出、旧→新对比、是否用于下一轮、对应事件 ID”的完整校准结果面板。认知校准也存在同类去向不透明。 | `web/app.js:brmCalibrationForm`、`boundaries.py:calibrate` |
| UI-002 | P1 | **未实现** | 已撤销的人际边界仍列在动态边界卡片中，没有删除/归档/隐藏入口；`edit` 只实现 save/confirm/correct/revoke。需要软删除和保留引用完整性的明确确认策略，不能连历史证据一起静默抹除。 | `web/app.js:renderBoundaryModel`、`boundaries.py:edit` |
| UI-003 | P2 | **部分** | 同一边界反复修订仍并列展示版本号和来源，不足以一眼识别重复/撤销/合并关系；需要分组、筛选和版本变更可视化。 | `web/app.js:renderBoundaryModel` |
| UI-004 | P1 | **未实现** | “最近情境判断”渲染 `b.recent.slice(-5).reverse()`，未按回合折叠、没有搜索/分页/历史浏览。后端保留最多 100 条，UI 状态接口只返回末 20 条，故仅改前端还不够。 | `web/app.js:renderBoundaryModel`、`boundaries.py:status` |
| UI-005 | P1 | **未实现** | “自身人格”和“交谈对象”仍共同位于 `profiles` 页面两列，不是明确的两个一级界面。独立 Social Graph 和统一学习中心同样未创建。 | `web/index.html` 导航和 `profiles` |
| UI-006 | P1 | **未实现** | 对“有证据的人格整理”没有应用去向的清楚说明：按钮保存 `pmm_synthesis` 报告，不直接修改 HEXACO/权重；必须在 UI 标明“仅分析/未应用”，展示各个后续模块的实际使用与否。 | `engine.py:synthesize`、`web/app.js:renderSynthesis` |
| UI-007 | P1 | **部分** | 有 HEXACO/语言/情绪/表达量化视图；自动学习任务的来源、目标（Self/Other/关系）、真正变更前后、拒绝原因、是否更新训练权重仍没有统一可追溯界面。 | `web/index.html`、`web/app.js` |

## C. 人格、情绪、学习蒸馏

| ID | 优先 | 状态 | 仍缺的功能 | 当前证据 |
|---|---|---|---|---|
| LEARN-01 | P1 | 未实现 | 手动/自动/仅候选审核的**统一策略**，按自身、他人、关系、语言学习单独设置学习范围与强度；当前 `online_learning` 只是模型数值训练相关开关。 | `common.py`、`server.py`、`consolidation.py` |
| LEARN-02 | P1 | 未实现 | 对**已经保存的最近 N 条、最近 X 天、选定会话、全部已授权历史**重新蒸馏，无需重新上传文件，且需去重/原文来源/干运行预览。 | 当前仅 `/api/distill` 输入上传记录；`/api/consolidation/run` 只处理待办队列 |
| LEARN-03 | P1 | 部分 | 自动整理的触发已有（5–10 条/空闲 60–120 秒/预算），但没有完整任务中心和持续透明的按目标更新审计、人工审核、失败报告/重试视图。 | `consolidation.py`、`web/app.js` |
| TRAIT-01 | P1 | 部分 | 已有慢速候选晋升按钮和独立证据、跨情境跨度门槛，但并未自动形成完整长期人格学习策略；当前更多是人工执行 `review_traits(apply=True)`，参数阈值为未校准工程规则。 | `traits.py:review`、`engine.py:review_traits` |
| TRAIT-02 | P1 | 部分 | BEQ/ERQ/PANAS 支持长期倾向设定/候选与显式条件，但自动蒸馏、独立信效度验证、真正 Learned-PMM 习惯头未实现。 | `traits.py`、`capabilities.py` |
| EMOTION-01 | P1 | 部分 | 已有连续现实时间、事件转移、心境和人格条件化；具体情绪仍只有 12 类，讨论的扩展到 24 类未实现，维度/效度未校准。 | `affect.py:LABELS` / `TAU` |
| COGNITION-01 | P2 | 未实现 | 主动回忆、无消息时自主生成有来源的认知事件、内部动机议程和人格条件化主动学习尚无完整运行链；只有时间状态外推与被动/定时社会任务。 | `affect.py`、`consolidation.py`、`social.py` |
| CBM-LEARN-01 | P1 | 部分 | 2.4 已有语用计划、示范统计、人工注释、表达回执，但 Learned-PMM 独立语用神经头、跨关系长期反馈学习及真实自然度验证缺。 | `pragmatics.py`、`docs/CBM_IMPLEMENTATION_20261030.md` |
| SYNTHESIS-01 | P1 | 未实现 | “人格整理报告 → 是否形成候选 → 是否晋升 → 写到何处 → 下一轮如何使用”的强关联结果链；`pmm_synthesis` 并非新的长期人格参数。 | `engine.py:synthesize` |

## D. 他人认知、关系形成与社交网络

| ID | 优先 | 状态 | 遗留内容 | 对应位置 |
|---|---|---|---|---|
| OTHER-01 | P1 | 部分 | 收消息可更新按 `scope+person` 的他人模型；群聊旁观没有完整、可审计的“观察→他人心理候选”学习链；跨群身份共识、对象人格精度与不确定性仍需完善。 | `engine.py`、`consolidation.py`、`group_attention.py` |
| REL-01 | P1 | 部分 | 现有 trust/affiliation/familiarity/preferences/trajectory 属基础双边模型，未实现主流文献支持的关系图式、关系规范、相互依赖、双方不对称认识、修复过程及人格↔关系完整耦合。 | `relationships.py` |
| REL-BUG-01 | P1 | 待整改 | 现有 `familiarity=1-exp(-interactions/60)` 仍以互动数自动提升熟悉度，不能代表真实关系质量；`relation_delta` 对临时关系的修改与正式 dyad `relationship_updates` 路径仍需要一致性审计。 | `relationships.py:update`、`engine.py` |
| GRAPH-01 | P1 | 未实现 | 多人关系 Social Graph（A-B/C、社交圈/跨群交集、第三方关系、来源证据、隐私作用域、网络 UI）没有结构化图存储和实际学习链。 | 暂无 `social_graph` 运行模块 |
| BRM-01 | P1 | 部分 | 被动人际边界有 API/数值估计、证据和人工校准；主动联系仍没有完整的数值 BoundaryHead → 行为决策 → 真实反馈学习闭环。 | `boundaries.py`、`social.py`、`capabilities.py` |
| GROUP-01 | P2 | 部分 | 有引用线程、选读预算和不同来源隔离；没有**无显式引用**时语义多话题解缠；群体关注调度还保留工程 `sample_every` 规则。 | `group_attention.py`、`turn_taking.py` |

## E. 多模态、Agent、训练与研究验证

| ID | 优先 | 状态 | 遗留内容 |
|---|---|---|---|
| MULTI-01 | P1 | 待实机 | 图片/引用图/GIF/授权发图路径已存在，但此前“图片没读出来”案例缺真实 QQ/SnowLuma 联合验收。 |
| VIDEO-01 | P2 | 未实现 | QQ 视频下载、时序抽帧、音频 ASR、时间线语义理解与预算/错误链。 |
| AGENT-01 | P2 | 未实现 | PMM 与浏览器、新闻、桌面/外部执行 Agent 的通用观察/行动协议及权限、主动学习机制；架构可容纳，不等于工具已经接入。 |
| TRAIN-01 | P2 | 部分 | Learned-PMM 已有小型梯度训练 Core/Adapter，缺独立指标门槛发布、训练取消/可恢复完整流程、群体预训练和跨人/关系/时间外部验证。 |
| TRAIN-02 | 研究 | 未实现 | LoRA/QLoRA、隐藏状态 Activation Steering、跨模型迁移验证；不得把 API Prompt 条件化误称为内部激活控制。 |
| RESEARCH-01 | 研究 | 待验证 | 心理量表效度、持续人格稳定性与可塑性、情绪时间参数、他人推断准确度、关系预测、语言自然度、等预算 Prompt/RAG/API/Learned 消融。 |
| OPS-E2E | P0 | 待实机 | 原生 Windows 双击与 UI 渲染、用户生产数据库连续迁移、云端模型、SnowLuma/QQ、真实延迟与错误复现。现有 476 Python + 51 HTTP/DOM 本地用例不能替代它们。 |

## 开发次序建议

1. **P0**：复现并诊断 `boundary_appraisal` 列表/证据错配导致的实际无回复；做真实 QQ/云模型/Windows 最小闭环。
2. **P1（UI 小修）**：校准结果去向、撤销边界删除、情境判断折叠/历史/筛选、人格整理“未应用”明确说明。
3. **P1（学习与人际）**：LEARN-01 统一入口和学习强度、历史回溯蒸馏、学习差异日志；分离 Self/Other UI；再实现 OTHER/REL/GRAPH 多主体证据与关系机制。
4. **P1（模型）**：补长期人格与情绪的可验证学习，完整类别情绪、成熟的关系/语用反馈闭环。
5. **P2 / 研究**：群语义分线、视频/Agent、训练发布与 Activation Steering、科学效度与性能优化。

**限制**：这次并没有运行真实模型或真实 QQ，也没有对用户本机 2.4.0 生产库作核验；除源码足以证明缺失的项目外，真实效果均列“待验证”。
