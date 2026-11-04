# 槐安梦客 / Persona Dialogue：TRAIT–EMOTION 分层纠偏与人格量表扩展

版本：2026-10-29，作为 `CORE-01 + EMOTION-01` 的纠偏补充规范。**本文是待开发设计，不声称已修改运行程序。** 依据当前可取得的 2.2.3 完整源码导出与研究文献。

## 0. 核心纠偏

1. **人格（trait）**是相对稳定的性格、动机、价值及习惯性行为倾向；**情绪（state）**是时间与事件条件化的当前反应；**心境（mood）**是较持久但仍属状态的情感背景；**表达（expression）**是当前行为结果；**情绪调节倾向（habit）**与**当次调节行为（operation）**必须分开。
2. 现有 `construct_registry.json` 的 93 字段 = HEXACO 24+1 + Schwartz 19 + VAD 3 + emotion 12 + appraisal 12 + regulation 5 + interpersonal 2 + linguistic 15。**不是 93 项稳定人格特质。** 其中 32 个 `affect.*` 包含情绪状态、事件评价和调节操作，不得被持久人格学习器以同一方式更新。
3. `persona/psychology.py` 的旧 `traits` 五项和 `values` 十项是历史兼容层；正式人格以 HEXACO-PI-R 为主、Schwartz 19 价值独立存在；不可将旧 Big Five 简单换算 HEXACO。
4. `persona/registry.py:update_state()` 的 `k.startswith('affect.')` 分支和 `state_view()` 对全部 `affect.*` 的统一时间过期，须拆成不同类别的更新与有效期规则。
5. `persona/engine.py:activity()` 当前四维效价/唤醒/压力/参与和固定中性基线，以及 `mood = .96*mood+.04*emotion`，只能算工程基线。替换为基于真实时间的心境模型，禁止把长期平滑后的 mood 回写人格。
6. `persona/registry_pmm.py` 的 93 字段打包保持向后兼容，但新推理路径必须使用类型化分组/独立掩码、时间戳和不同训练损失，不能把即时情绪、稳定特质混为等价标签。

## 1. 五个分离的存储实体

- **TraitProfile（长期）**：`persona_id, trait_schema_version, hexaco_facets[25], value_priorities[19], interpersonal_dispositions, response_sensitivity(optional), expression_dispositions, regulation_habits, motivation(optional), evidence/provenance, uncertainty, manual_seed, updated_at, version`。仅由用户明确编辑或 TRAIT-01 的跨情境证据晋升更新。
- **AffectiveDisposition（长期个体差异，属于 TraitProfile 的扩展）**：可根据足够样本描述正/负情感倾向、情绪反应性、调节及表达习惯；**不保存今日的 joy、anger 数值**。
- **MoodState（中期动态）**：`baseline_ref, valence, arousal, optional_dominance, updated_at, uncertainty, transition_params_version`；随现实时间、持续事件和调节变化，不作为人格测量分数。
- **EmotionState（短期动态）**：`valence, arousal, dominance|null, categorical_activations, stress, engagement, event_id, appraisal_id, onset_at, last_updated, confidence, state_revision`；具体情绪支持多标签、未知和不同持续时间。
- **ExpressionState（当次行为）**：`dialogue_action, expression_strategy, disclosure_decision, intensity, timing, sentence_segmentation, social_context, linked_emotion_revision, linked_trait_version`；记录实际发送后的行为，不回写瞬时情绪当稳定特质。

**同一角色的心理人格、当前情绪、对他人的推测和双方真实关系必须有独立的对象/作用域 ID。** 内部模拟的情绪值不等于真实主观体验或正式量表结果。

## 2. 经文献支持的人格核心与增补量表

### A. 必备核心

**HEXACO-PI-R**：六域（Honesty–Humility、Emotionality、Extraversion、Agreeableness、Conscientiousness、Openness），每域四个面向，另有 Altruism interstitial facet，共 **24+1 个面向**。六域是对这些面向的上层汇总，不能把 24+1 与六域当成互不相关的 31 个独立量表维度。官方存在 60/100/200-item 版本。重要：HEXACO 的 **Emotionality 是稳定倾向，不是今日恐惧、焦虑、悲伤的量化值**。

**Schwartz refined values**：19 项个人价值优先级，属于相对稳定的价值系统，**与人格特质在界面和学习目标上分开**。不可把爱玩剧情游戏等兴趣直接当作价值量表分数。

### B. 本轮应优先补足的“长期情绪表达与调节”构念

| 文献量表 | 构念 | 应用 | 注释 |
|---|---|---|---|
| Berkeley Expressivity Questionnaire / BEQ（Gross & John, 1995/1997） | Positive Expressivity、Negative Expressivity、Impulse Strength（3） | 人格对情绪**如何表现出来**的习惯性倾向；影响措辞强度、情绪外露和分段行为 | BEQ 测量表达性个体差异，并非当前情绪分数；不能以“话多=开心”直接估计 |
| Emotion Regulation Questionnaire / ERQ（Gross & John, 2003） | Cognitive Reappraisal、Expressive Suppression（2） | 长期更倾向使用哪种调节策略 | Gross 的五类过程是**当次操作类型**，不是 ERQ 五项人格量表 |
| PANAS（Watson, Clark & Tellegen, 1988） | Positive Affect、Negative Affect（2） | **仅在“总体上/通常”时间框架**下，作为情感倾向的候选测量；“此时此刻”表述测量状态 | PANAS 的 PA/NA 与 VA 不相同；不可据此自动替代实时 VA，更不能把同一数值同时存两层 |

前期先建 **BEQ 3 + ERQ 2** 的长期扩展表征，并在可用证据充分时引入 PANAS 的 PA/NA；值可以为 `null`。不要拿 AI 自生成的一句话计算这些量表的正式得分。手动编辑需标注 `owner_seed`，实际完成量表才可标注 `questionnaire` 并注明工具、题本版本、计分方法、时间框架与作答者。

### C. 可选的互补人格/社会动机量表，第二阶段按研究需要启用

- **BIS/BAS（Carver & White, 1994）**：BIS 惩罚/威胁敏感性 + BAS Reward Responsiveness / Drive / Fun Seeking，四个分量表。适合社交趋近、回避、主动联络与奖惩预期；与 HEXACO 特征存在相关但非同一构念。可选模型，不必在第一轮强行加入。
- **IRI（Davis, 1983）**：Perspective Taking、Empathic Concern、Personal Distress、Fantasy 四个分量表。适合研究共情与社会视角差异，**自我不适不等于对别人关怀**。属于补充的人际倾向，不把每次安慰行为直接认定为量表高分。
- **BFI-2、BFAS**：可以保留为交叉效度/对照量表，**不与 HEXACO 拼接成多个独立“人格域”**，以免严重重复计量。
- **DERS**：主要衡量情绪调节困难，不等同一般人格特质，也不宜默认作为 AI 人格的临床属性；只在明确实验需要时使用。

**无心理测量依据的“风格”15 字段**保留为行为/语用习惯，并在 UI 单独标注为程序行为表征，不得直接称为心理学量表分数。

## 3. 明确的计算顺序：人格先验 → 事件评价 → 当前情绪 → 行动与表达

对任意输入事件 `X_t`：

1. **Load Trait Prior**：读取当前人物的 `TraitProfile@version`、价值、长期表达/调节习惯，锁定本轮快照；读取真实关系、授权和知识约束。
2. **Interpret Event**：General LLM 或其他语义组件提取事件事实、话题、参与者、可能情境；**事实提取与人格预测独立**。
3. **Appraisal**：`A_t = f(X_t, Traits, Values, Goals, Relationship, Memory)`。同一事件面对不同人物可能产生不同评价，评价是临时状态，不能写入 trait。
4. **Affect Dynamics**：用真实时间 `Δt` 先推进 mood/emotion，再结合 `A_t` 更新 VA/D、具体情绪和压力；情绪的更新只写入 `EmotionState` 和 `MoodState`。
5. **Regulation Decision**：根据 ERQ/其他长期习惯、即时情绪、关系、目标和安全边界选择当次调节，明确区分改变内部评价 vs 抑制外部表达。
6. **Action Decision**：`action = π(TraitSnapshot, MoodState, EmotionState, Appraisal, Relationship, Goal, Context)`，必要时进行动态多视角协商；人格不能被情绪覆盖，情绪也不能被忽略。
7. **Expression Planning**：先决定表达意图、强度、语用行为、是否多条 QQ 消息，再由 General LLM 生成语言；表达风格由 BEQ/ERQ/Language Identity 等倾向 + 当前情绪共同条件化。
8. **Commit & Slow Learning**：快状态根据真实事件和实际行动回执提交；长期人格只能由独立的证据晋升任务慢速更新，记录反例、来源、上下文与版本。

**重要**：“先人格后情绪”是模型数据依赖与运算结构，并不意味着先生成一遍人格化文字，再用第二遍 Prompt 给它加喜怒哀乐。情绪评价本身已经受人格约束，最终行动仍联合读取两者。

### 情绪时间模型（工程假设）

`E_t^- = μ_trait + exp(-K_trait × Δt) · (E_{t-1} - μ_trait) + noise_t`

`A_t = Appraise(event, trait_prior, goals, values, relationships, memory)`

`E_t^+ = Project(E_t^- + Impact(A_t, context, reactivity) - RegulationEffect_t)`

`Mood_t = TimeBasedMoodTransition(Mood_{t-1}, E_t^+, environmental_context)`

其中 `μ_trait、K_trait、reactivity` 是经过明确标记的个体差异参数，不是某个 HEXACO 面向的直接同义词，也不是单条消息带来的 trait 改变。若没有独立数据，先用未校准先验及敏感性区间，显示 `uncalibrated`，不要称为人类心理学定律。禁止使用固定 `.96/.04` 事件次数平滑伪装真实时间动力学。

## 4. 源码改造任务

1. `persona/construct_registry.json`：保留原 93 IDs、顺序、权重映射；新增 `feature_temporality` / `construct_kind` 类型清单和独立扩展 `trait_disposition_registry`；**不要强行将扩展字段加到旧 93 encoder 输出列**。
2. `persona/registry.py`：拆分 `update_trait_evidence`、`update_affect_state`、`update_event_appraisal`、`record_regulation_action`；取消 `k.startswith('affect.')` 一刀切的覆盖、过期/证据门控。
3. `persona/psychology.py`：把历史 `STATE_KEYS` 四维通道标记为兼容视图，停止把它作为全部情绪的实际数据模型；旧 `traits/values` 仅允许明确的兼容/历史标记。
4. `persona/engine.py`：用独立 `TraitSnapshot`, `MoodState`, `EmotionState`, `ExpressionPlan` 替代单一 `activity` 大字典；去掉固定中性基线与事件次数 `.96/.04` 的正式状态转移路径。所有自我人格/他人印象更新限作用域。
5. `persona/registry_pmm.py`：按特质/价值/社会偏好与当前状态拆分遮罩，训练损失分离；旧权重兼容只读映射；必要时新路径初始化新权重并显式标明未经训练，不重建人格。
6. `persona/api_pmm.py`：将人格先验读取、事件评价、情绪转移、行动候选与表达生成分为明确契约；禁止一条模型 JSON 的“当前情绪”直接写入 HEXACO 或 BEQ/ERQ。
7. `persona/subjects.py`、`storage.py`、`data_guard.py`：执行自动无损迁移与双版本兼容；保留旧主体、历史、证据、QQ/API 配置、训练权重。遇旧 mood 无时间戳/无法校准，标记未知或工程旧值，不擅自转换成正式新分数。
8. `web/app.js`、`web/index.html`：人格页显示六个 HEXACO 域、25 面向及 Schwartz 价值，新增独立“习惯性情绪表达 BEQ/调节 ERQ”（来源和未知状态）；情绪页显示当前 VA/D、具体情绪激活、短期轨迹和中期 mood。不得将两者混在同一进度条或将当天情绪展示到人格面向。单独展示情绪“内部估计”与“实际外部表达”。
9. 保留历史领域 `affect.appraisal.*` 和 `affect.regulation.*` 的数据来源，但其**语义和时间规则**迁移到事件评价与操作日志，禁止相同字段原地混用不同含义；必须进行前后版本可读性检查。

## 5. 验收与科学验证

### 强制工程回归

- 同一个人格，连续发生 10 次愤怒相关事件：短期愤怒可上升，但其 HEXACO Emotionality、长期 BEQ/ERQ 等不能因此被自动改写。
- 同样的情绪事件，在两个不同的 `TraitProfile` 下，评价、调节策略和外部表达可以不同；记录真实执行的状态和动作，不能事后生成说明。
- 相同人格在激动/平静情境下保持相同稳定特质和价值优先级，但输出强度可变。
- 若调节为“表达抑制”，应主要影响表达层，不能自动把内部负性情绪删除。
- 无新事件但经历 10 秒 vs 5 小时：短期状态按照真实时间演化，长期人格不变；重启不重置。
- `MoodState` 不得回写 HEXACO；`EmotionState` 不得当成长时量表分数；群友的状态不得污染 AI 自身。
- 旧 2.2.1/2.2.2/2.2.3 主体、HEXACO 已有值/未知 mask、聊天历史、权重和配置升级后字节或结构校验通过。
- 老模型若无新表征输入，必须明确报 `unsupported_feature` 或使用旧协议的降级模式，不能悄悄当作已训练新版人格。
- 仅有网页的进度条更新，不算通过；必要时同一 `turn_id` 保存 trait_version、emotion_revision、appraisal_id、regulation_action、expression_plan、provider_usage。

### 科学验证

- 使用有授权的人类量表或稳定人格标注时，必须注明具体问卷版本、时间框架、自评/他评来源、规范评分和信度。AI 输出的 0–1 值只能标“模型推断的候选估计”，不能叫 HEXACO-PI-R / ERQ / PANAS 正式测量分数。
- 设计 2×2 控制：两个人格 × 两种事件诱发的实时情绪；测量 trait 漂移率、state 反应合理性、表达区分度、校准与 QQ 延迟。
- 消融：只有人格、只有情绪、混合未分层、显式分层四组等预算比较；验证是否解决单次情绪污染人格或人格完全压制情绪问题。
- 长期人格晋升依赖独立事件、跨时间/情境、反例、来源可靠性和慢速版本化更新；不能根据聊天次数自动晋升。

## 6. 推荐文献及用途

1. Lee & Ashton; HEXACO-PI-R versions and facets: https://hexaco.org/references ; Ashton & Lee (2020) https://doi.org/10.1007/978-3-319-24612-3_900
2. Schwartz et al. (2012), 19 refined values: https://doi.org/10.1037/a0029393
3. Fleeson (2001), state distributions vs traits: https://pubmed.ncbi.nlm.nih.gov/11414368/
4. Gross & John (1997), Berkeley Expressivity Questionnaire facets: https://pubmed.ncbi.nlm.nih.gov/9107009/ ; https://doi.org/10.1016/0191-8869(95)00055-B
5. Gross & John (2003), ERQ two habitual strategies: https://pubmed.ncbi.nlm.nih.gov/12916575/
6. Watson, Clark & Tellegen (1988), PANAS state vs trait framing: https://pubmed.ncbi.nlm.nih.gov/3397865/
7. Carver & White (1994), BIS/BAS: https://doi.org/10.1037/0022-3514.67.2.319
8. Davis (1983), IRI: https://doi.org/10.1037/0022-3514.44.1.113
9. Kuppens, Oravecz & Tuerlinckx (2010), DynAffect: https://pubmed.ncbi.nlm.nih.gov/20853980/

## 7. 实施顺序

先审计旧状态与制作迁移前快照 → **建立类型和作用域分层（无行为变化）** → 分离 trait 与 state 写入 → 增加 BEQ/ERQ 习惯性人格扩展 → 接入时间连续的 VA / 情绪、mood 和调节执行 → 修改 PMM 行动顺序和训练损失 → UI 重组 → 旧主体迁移、浏览器、QQ 联合与心理学对照测试。

**最终完成判据**：情绪可随事件/时间变化而不改变人格；同一当前情绪在不同人格下能产生不同评价和表达；相同人格面对不同情绪时保留稳定心理倾向；人格变化只经独立证据晋升。所有新增量表都标注证据和测量方式，禁止靠新字段数量宣称心理机制成熟。
