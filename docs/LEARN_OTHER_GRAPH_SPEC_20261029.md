# 槐安梦客 — LEARN-01 / OTHER-01 / GRAPH-01 研发整改方案

**审计基线**：`HuaiAn_Dreamer_2.2.3_H2_Complete.zip`，版本 `2.2.3-h2`。日期：2026-10-29。本文是**代码检查及下一轮开发规范**，未修改运行中的程序。

## 0. 原始需求

- 为人格和对象学习提供**范围、模式、强度**三个彼此独立的维度；同时支持手动、自动蒸馏。自动学习不等于默认信任所有群聊发言。可以仅收集证据候选。
- AI 必须在交流中形成**有证据、允许未知、可修订**的对交谈对象的认识；应展示观测→候选→晋升的状态，不应把一次发言等同稳定人格。群聊旁观与双方实际交往分别建模。
- 新增**社会关系知识图谱**：区分“AI↔某人”双边关系、“A↔B”第三方关系、个体参加的多个群体及其交集；每条边需要来源、证据、权限、置信度、时间、情境与核验状态。

## 1. 2.2.3-H2 源码确认的现状

| 目标 | 文件与现状 | 判断 |
|---|---|---|
| 手动蒸馏 | `persona/server.py` `/api/distill`；`persona/engine.py` `import_records(target=self/interlocutor)`；`web/index.html` 学习资料页面 | 已实现，未提供细粒度学习政策 |
| 自动蒸馏 | `persona/engine.py` `FEEDBACK`、`apply_distillation`; QQ 路径 `deferred = deferred or ':qq:' in session['scope']`; `persona/consolidation.py` 批处理 | 部分实现。处理了有完整回复/提交的轮次；后台失败、证据不足时没有可见的候选更新 |
| 学习强度 | `persona/common.py` `online_learning: True`；`persona/web/app.js` 的 onlineLearning 开关；`persona/psychology.py` 人格更新裁剪 0.003、观测置信度封顶 | 无统一强度政策。在线学习开关主要涉及 Learned-PMM 数值训练，**不是**全系统自动观察/人格蒸馏总开关 |
| Other Model | `pmm_interlocutors`、`other_key(scope,person)`、`apply_distillation(other, ...)`，UI `renderOther()` | 有对象模型；QQ 延迟后台整理，未证实真实实例有充分观察。空对象不能算已产生人格判断 |
| 旁观群聊 | `group_attention.py` `observed_only`、`memory_lifecycle.enqueue()` | 仅部分进入记忆整合；尚无完整旁观证据→他人候选人格的链路 |
| 双边关系 | `relationships.py` `pmm_dyads`，支持信任/熟悉度/偏好/共同梗/冲突历史 | 仅 AI 与目标人物之间，按情境隔离 |
| 多人关系图 | 未发现通用 person→person 边、群体节点、跨群身份关联和关系网络查询协议 | 缺失 |

### 必须先修的可观察问题

1. 为每个人物显示：消息已观察条数、符合可用证据条数、后台待处理/失败、候选人格数量、已晋升维度数量、最近处理时间与拒绝原因。尤其 `consolidation.status()` 及 `pmm_interlocutors` 对接。
2. 仅仅创建一个 `empty_profile()` 绝不应显示为“已经分析出人格”。
3. 群聊未 @AI 的旁观数据应按许可/参与者配置决定是否参与画像学习。不能默认扫描和推断所有旁观者的敏感人格。

## 2. LEARN-01 统一学习政策

### 2.1 三条正交控制轴

- `mode`: `manual`（仅明确手动蒸馏）/ `candidate_only`（自动收集证据，只审核晋升）/ `automatic`（自动在证据门槛内更新）
- `scope`: `self`, `other`, `social_graph`, `episodic_memory`, `pragmatic_style` 单独授权；进一步按 QQ 私聊、群聊、对象、来源类别和允许时间窗限制。
- `strength`: **长期状态更新强度**，仅在可信证据通过门控后调节可接受的更新幅度或不确定性变化。与模型调用频率、Token 预算、证据收集覆盖率分离。0 不执行长期写入；100 也不能越过证据标准、隐私和身份隔离。

建议提供四种友好预设：观察但不晋升 / 谨慎学习 / 标准学习 / 广泛学习；高级模式才开放实际学习系数与门槛。数值为**工程先验**，未经实验不可声称心理学准确。

### 2.2 计算契约

`LearningPolicy` 决定该事件是否可被处理及可学习领域；`EvidenceGate` 验证来源、时序、目标主体、独立性和反例；`UpdateController` 按受约束的学习系数更新长期参数。**不能仅按“对话条数”提升人格。**

API-PMM：接受有证据的 LLM 候选 + 本地统计/贝叶斯证据聚合；Learned-PMM：监督样本进入队列，训练策略与状态学习分离，明确是否更新 adapter。两者共享政策及完整审计日志。

### 2.3 交互

- 人格学习页面只展示一张学习策略卡：模式、范围、强度、当前生效对象、自动处理状态。
- 手动蒸馏可对选定的历史片段、对象和时间窗执行，先预览来源、重复证据与预计写入类型。
- 自动蒸馏可停止/恢复/查看队列，查看“候选未晋升”的理由；支持后续人工纠正、撤销和按来源删除派生结果。
- 改变学习政策只影响未来任务；对历史数据重新学习必须明确确认和可审计执行。

## 3. OTHER-01 持续性他人认知

### 3.1 独立的两步认知

每条允许处理的发言进行轻量理解：对方当前表达意图/情绪线索/自述事实/偏好证据（需要则可稍后深入）。自动后台只在证据独立性足够时形成稳定特质候选；跨时间、跨情境校准后才更新稳定他人模型。不得将自己的情绪或自动生成的回复写成对方的真实人格。

参考 Funder 的 Realistic Accuracy Model：相关线索→可用线索→被注意到→合理利用。**聊天推断不是正式 HEXACO 测验**。只对足够证据领域给出候选，其他保持 `unknown`。

### 3.2 身份、情境与关系分开

`PersonIdentity`：QQ 用户 ID 或明确可靠的稳定标识；`PersonContextObservation`：某群/私聊环境中的观察；`OtherHypothesis`：跨许可情境或仅局部情境的候选认识；`SelfPersonRelationship`：AI 与此人的真实互动历史。相同 QQ 可在多个群出现，但记录来源和访问权限不自动全部打通。

- 旁观用户发言：可以知道“TA 说过什么”，不因此增加 AI 与其的熟悉度。
- 直接私聊/真实回复：可增加直接交互事件，但信任亲密度不能单靠次数自发增加为确定值。
- AI 无法准确判断的人格维度应保持未知，并报告证据不足。

### 3.3 必须排查的现存工作流

检查 `persona/engine.py` 的 QQ deferred 分支、`consolidation.py` 的真实队列完成状态、FEEDBACK 返回的 `interlocutor` 内容及 `psychology.py` 的 `apply_distillation()` 判定和修订，并用真实 QQ 测试确认结果。群聊旁观消息没有完整走通同一条对象认知链，应单独接入轻量任务，而不触发每条消息一次高成本 PMM API。

## 4. GRAPH-01 社会关系图谱

### 4.1 数据结构

逻辑上独立的社会关系知识库，但复用已有统一 `EventLedger`、身份索引、证据协议和访问权限。

- `people`: person_id, identity_source, alias, confidence, created_at。
- `contexts`: context_id, type(private/group/community), scope, metadata。
- `memberships`: person_id, context_id, since, until, evidence_id, status。
- `relation_claims`: subject_person_id, object_person_id, relation_type, directed, knowledge_type(observed/self_report/third_party_report/inferred/confirmed), scope_id, valid_time, recorded_time, evidence_ids, confidence, uncertainty, status。
- `graph_events`: 关系的版本化修订、冲突与撤回。

`A 和 B 在同一群` 仅形成 `co_member` 或共同出现的上下文关联，**不能自动推断是朋友**；`A 说 B 是自己朋友` 只能记录“来自 A 的关系陈述”，还不能证明 B 也承认。`A 和 AI 熟悉` 与 `AI 观察 A 很久` 是不同关系。

### 4.2 群体交叉

支持多个上下文/群体重叠：A、B 在游戏群；B、C 在校友群；A、C 没有可验证关系。共同成员 B 形成图结构上的桥，但不能由此推断 A 与 C 相识。关系按人和情境带证据更新，避免跨群传播不必要的私人信息。

### 4.3 实施技术

首版 SQLite 三类关系表 + 证据表 + 索引即可，支持范围查询、邻居查询与成员交集。人数和查询复杂度增长以后再评估 NetworkX、图数据库和社区发现算法。算法预测的社区只标记为 `inferred`，不可替代实际群成员关系或获得过确认的社交圈。

### 4.4 记忆用途

记忆提取在合法上下文内可查人物/情境/关系，但不得让 AI 依据未经证实的第三方关系像老熟人一样和对方说话；允许 `unknown` 和冲突证据。重要群聊和私人关系只在相关人授权、允许访问的范围使用。

## 5. 推荐开发顺序及验收

1. **现有链路审计与可视诊断（P0）**：重现私聊交谈后对象无明显人格判断，区别 `后台待处理 / 失败 / 无充分证据 / UI 未刷新`，交付实际调用追踪；保证核心回复不中断。
2. **LEARN-01（P1）**：统一学习政策，自动/手动双入口，分领域/对象的范围和强度，完整来源审计与回滚。
3. **OTHER-01（P1）**：实时观察候选 + 延迟证据晋升，补全群聊旁观的合法学习路径，分离 self/other 与情绪/人格。
4. **GRAPH-01（P1）**：单独社会关系逻辑存储、跨群成员交集、关系证据版本化、图查询与简洁可视图。

**至少测试**：关闭长期学习但正常聊天；手动导入不串 self/other；同一人跨不同群有相同基础身份但不同上下文证据；旁观大量消息关系熟悉度不自动上升；第三方自述关系不直接晋升确认；相同来源重复导入去重；有反例时更新不确定性；100% 强度仍不能突破授权或伪造人格量表；多人格包升级旧版数据不丢失；Graph 查询只读取允许范围；观察/处理/训练/发送分别显示真实状态；资源预算使高流量群聊不阻塞正常回复。

**重要**：此方案未经真实 QQ 联合验收；不应把软件内部推断当作实际心理测量。新功能必须兼容 `2.2.3-h2` 的数据目录、93 字段注册表、人格包与训练检查点。迁移前 SQLite 一致性备份，增量 Schema 版本迁移与旧版回归测试。

## 6. 文献

- Funder, D. C. (1995). On the accuracy of personality judgment: a realistic approach. *Psychological Review*, 102(4), 652–670. https://doi.org/10.1037/0033-295X.102.4.652
- Funder, D. C. (2012). Accurate Personality Judgment. *Current Directions in Psychological Science*, 21(3). https://doi.org/10.1177/0963721412445309
- Dunbar, R. I. M. (2014). The Social Brain: Psychological Underpinnings and Implications for the Structure of Organizations. *Current Directions in Psychological Science*, 23(2). https://doi.org/10.1177/0963721413517118
- Sutcliffe, A., et al. (2012). Relationships and the social brain: integrating psychological and evolutionary perspectives. *British Journal of Psychology*. https://doi.org/10.1111/j.2044-8295.2011.02061.x
