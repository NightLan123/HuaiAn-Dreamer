# PMM v2.1：完整心理构念注册表与内部协商开关——强制开发补丁

> 类型：架构补丁／实现契约；它不等于现有软件已实现，也不意味着已完成心理测量或训练。优先级高于此前 v2.0 中的简化性格字段。

## 0. 核查结论

- 以前 v1/v2 文档提出过同一人格的动态多视角投影和协商，但没有正式定义 `off/auto/always` 控制、独立 Trace、开关测试。不能仅凭设计文档或 UI 中的“倾向评估”认定最新版程序已实现。未获得最新源码时，实际状态标记为 `UNVERIFIED`。
- 以前 v2 文档仅泛称 HEXACO / values 与情绪，缺少完整版心理学字段与映射。**训练前必须锁定完整字段协议，并提供后向兼容迁移。**

## 1. 内部多视角协商：作为独立功能开关

配置建议：

```yaml
deliberation:
  enabled: true
  mode: auto                  # off | auto | always
  max_perspectives: 4        # 上限，不等于每轮固定4个
  max_rounds: 2
  log_level: summary
  return_unresolved_conflict: true
```

| 模式 | 行为 | 必须保留 |
|---|---|---|
| off | 事件理解→PMM 单路径综合决策→语言条件解码→LLM 生成→实际回写 | 人格/情绪/记忆/知识边界/安全检查全部保留；不运行多视角讨论调用 |
| auto | 由真实价值冲突、情绪-关系冲突、行动不确定性及复杂度触发多视角，否则直接决策 | 每次记录触发分数、规则版本与是否启动 |
| always | 每次需要动作时运行候选视角推演；如果只有一个有意义的视角，允许无需额外对抗 | 不人为制造冲突；最多轮数可控 |

### 1.1 真正的双向过程

1. General LLM 首先解析输入，产生 SemanticEvent，区分说话者与被提及对象。
2. PMM 检索持久证据，读取人格 facet、价值冲突圈、即时情绪、关系和认识状态。
3. PMM 根据当前问题投影 `k` 个候选心理视角，每个视角保留同一 AI 的身份约束，包含 `source_features/evidence_ids/intensity/weight/uncertainty`；k 按情境选取，不能复制固定三个角色 prompt。
4. General LLM 为各视角推演可选行动及理由；不允许为角色编造未经证实经历。
5. 结果与证据质疑回 PMM；它可以再检索、拒绝错误推论、修订活跃视角、保留合理分歧。
6. PMM 决定 `ANSWER/ABSTAIN/CLARIFY/REFUSE/SILENCE`，进行硬性知识/隐私边界检查，再解码语言条件给通用大模型。
7. 对外实际执行的动作和之后发生的真实反馈才允许进入长期状态更新。

### 1.2 独立验收

- `off` 下不得出现多视角调用，完整心理记忆和决策仍正常；`always` 下可查看独立视角和双向日志；`auto` 的触发与否可追踪。
- 交换两个人格包，视角来源、权重及行动变化必须可解释；不能每轮复用同三个字符串。
- 切换开关后 Persona ID、记忆历史与情绪状态不得重置。
- 讨论内容仅记录在 Active Memory，不把内部猜测当作外部经历。
- 私人知识边界与系统约束不可通过角色投票取消。

## 2. 完整心理构念：训练前锁定完整结构

**主基线采用 HEXACO-PI-R 6 域／24 Facets + 1 跨领域量表；Schwartz 精细化 19 价值。BFI-2 的 15 facets 仅作为备选或对照视图，不与 HEXACO 简单相加。**

### 2.1 HEXACO：24+1（以下 ID 固定）

| 上层域 | 四个细分面向 |
|---|---|
| 诚实—谦逊（H） | 真诚 (`hexaco.h.sincerity`)、公平 (`hexaco.h.fairness`)、不贪婪 (`hexaco.h.greed_avoidance`)、谦逊 (`hexaco.h.modesty`) |
| 情绪性（E） | 畏惧倾向 (`hexaco.e.fearfulness`)、焦虑倾向 (`hexaco.e.anxiety`)、情感支持需要 (`hexaco.e.dependence`)、情感依恋 (`hexaco.e.sentimentality`) |
| 外向性（X） | 社会自尊 (`hexaco.x.social_self_esteem`)、社交自信 (`hexaco.x.social_boldness`)、合群性 (`hexaco.x.sociability`)、活力 (`hexaco.x.liveliness`) |
| 宜人性（A） | 宽恕 (`hexaco.a.forgivingness`)、温和 (`hexaco.a.gentleness`)、灵活妥协 (`hexaco.a.flexibility`)、耐心 (`hexaco.a.patience`) |
| 尽责性（C） | 条理性 (`hexaco.c.organization`)、勤奋 (`hexaco.c.diligence`)、完美主义 (`hexaco.c.perfectionism`)、审慎 (`hexaco.c.prudence`) |
| 经验开放性（O） | 审美欣赏 (`hexaco.o.aesthetic_appreciation`)、求知欲 (`hexaco.o.inquisitiveness`)、创造性 (`hexaco.o.creativity`)、非传统性 (`hexaco.o.unconventionality`) |

额外跨领域：利他性 / 对抗性（`hexaco.interstitial.altruism`）。6 个上层域是 UI 聚合视图，训练与状态保存必须容纳全部 24+1 facets；上层汇总不得取代下层证据。

### 2.2 Schwartz：19 价值（以下 ID 固定）

| 高阶价值组 | 细分价值 |
|---|---|
| 开放变革 | 自主思想 (`value.self_direction_thought`)、自主行动 (`value.self_direction_action`)、刺激与新奇 (`value.stimulation`)、享乐 (`value.hedonism`) |
| 自我提升 | 成就 (`value.achievement`)、支配权力 (`value.power_dominance`)、资源权力 (`value.power_resources`)、维护社会形象 (`value.face`) |
| 保守维护 | 个人安全 (`value.security_personal`)、社会安全 (`value.security_societal`)、传统 (`value.tradition`)、遵守规则 (`value.conformity_rules`)、人际顺从 (`value.conformity_interpersonal`)、谦卑 (`value.humility`) |
| 自我超越 | 善意—可靠 (`value.benevolence_dependability`)、善意—关怀 (`value.benevolence_caring`)、普世—包容 (`value.universalism_tolerance`)、普世—关切 (`value.universalism_concern`)、普世—自然 (`value.universalism_nature`) |

价值构念保持理论上相邻兼容、对立冲突的结构；不可把它们当作 19 条互不相关的规则，也不可将主观价值权重凌驾于系统安全、隐私和知识边界之上。

### 2.3 情绪、评价、调节（与人格严格分层）

- **瞬时维度**：VAD（Valence／Arousal／Dominance）3 个连续变量，并提供基线、更新时间与衰减参数。
- **可观察情绪标签**：喜悦、悲伤、愤怒、恐惧、厌恶、惊讶、兴趣、羞耻、内疚、感激、自豪、挫败；是可扩展候选标签，不是声称这是唯一的“官方十二情绪量表”。
- **事件认知评价**：基于 Scherer 组件过程模型，分 Relevance（3 checks）、Implications（4）、Coping（3）、Normative（2），共 12 个示意连续检查变量；这些检查的数量与拆法是本项目操作化，不宣称标准化量表只有十二项。
- **情绪调节策略**：Gross 过程模型的情境选择、情境改变、注意分配、认知改变、反应调节。这些是策略节点，不是五个人格类型。
- **时间尺度**：短期情绪变化快、人格/价值长期变化慢；实际事件的影响与内部讨论的假设严格分开。

### 2.4 人际关系、语言身份与认知

- 人际环状模型：Agency 和 Communion 作为个体倾向视图；真实关系状态必须按 `person_id × context_id` 独立建档，含信任、熟悉度、关系历史、共享梗和证据。
- 语言身份：词语和标点只是表层；应包含简洁/断句/正式/直接/幽默/反讽/熟人调侃/共情显露/主动参与/表情/俚语/反问/话题延展等风格特征，配完整上下文—真实回复样本，供蒸馏与语用预测。
- 知识边界：自有经历、用户提供的个人信息、一般知识、推断和未知必须分别标记；缺证据允许弃答；自我人格与对他人的模型分开。

### 2.5 不允许伪造数值

每个构念保存：`feature_id, estimate|null, posterior_uncertainty|null, evidence_ids, evidence_count, scope, source_type, updated_at, method_version`。
没有足够材料时 `estimate=null`，不能填 0、0.5 或随机中性值。展示“尚无可靠依据”；通过真人量表得到的分数与从聊天推断的值标明不同测量方式，**不得将聊天推断冒充正式心理测量分数**。

## 3. 防止以后训练的人格失效：版本与迁移

### 3.1 现在建立 Canonical Construct Registry

- `PMM_psychological_construct_registry_v2.1.json` 是机器可读字段目录；所有字段从现在起具有稳定不可复用的 ID。
- `Persona Package` 永远保存可移植状态 + 原始授权事件证据 + 采样时间 + 版本信息。
- Learned-PMM 训练读取固定顺序的特征向量及 missing mask；同时记录 `registry_hash, encoder_version, state_schema_version, feature_order`。
- latent vectors、embedding 索引与 LoRA 另外记录兼容的骨干模型/编码器版本，无法直接复用时重建，不得静默重新解释维度顺序。
- 模块未来扩展特征时只能新增字段或引入明确的 schema major version；旧数据保持有效且新字段为 unknown，旧权重若需要新输入必须经过显式特征映射或重训练。
- 正式训练前要求 state schema migration、data replay、checksum、rollback 全部通过；不允许因迁移删除旧人格包或历史。

### 3.2 训练兼容性的现实边界

完整字段提前确定能显著降低返工，但不能保证将来所有神经网络结构都无需迁移。尤其是固定大小的隐状态向量、编码器词表或 LoRA 基础模型改变时，权重仍可能不兼容。开发时必须同时保护结构化层、证据层和可重建编码路径。

## 4. 开发交付顺序与验收要求

| 顺序 | 实际交付 | 不通过条件 |
|---|---|---|
| A | 审计最新版代码里的多视角代码、调用日志、开关、实体状态字段，明确真实/规则/Mock | 仅根据 README 宣称已实现 |
| B | 实现 off/auto/always 运行控制，日志反查各视角来源及权重 | 只是隐藏 UI，后端仍跑相同代码 |
| C | 在训练开始前实现 24+1、19、情绪评价、关系和语言状态的注册表、数据模型、完整读写/导出/导入 | UI 只有六个总分；底层也只保存六个数 |
| D | 加旧包兼容迁移、unknown mask、证据追溯、维度顺序版本锁、数据回滚 | 迁移丢旧人格或无法解释旧训练数据 |
| E | API-PMM 对各状态领域能够提取证据、推断更新、解码并被多视角过程消费 | 底层虽然有字段却永远没被调用 |
| F | Learned-PMM 使用 registry/mask 训练；分 persona 验证迁移和输出稳定性 | 新旧向量混用或只调用预训练 LLM 冒称训练 |

### 每次工作对话回报必须增加

汇报：`deliberation.enabled/mode` 的真实运行行为与测试日志、psychology schema_version、完整字段覆盖率、旧 Persona 迁移测试、模型实际调用与 trained/untrained 标记。不得用“已加入人格维度”笼统代替逐域实现状态。

## 5. 参考来源（定义核对）

- HEXACO-PI-R 官方 facets：https://www.hexaco.org/scaledescriptions
- HEXACO 24+1 官方说明：https://hexaco.org/history
- Schwartz 2012 refined 19 values：https://doi.org/10.1037/a0029393
- BFI-2 5 domains / 15 facets：https://pubmed.ncbi.nlm.nih.gov/27055049/
- Scherer 组件过程模型：https://pubmed.ncbi.nlm.nih.gov/18540750/
