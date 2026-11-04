# 槐安梦客 / EMOTION-01 — 实时情绪扩展修订（适用于 2.2.3）

> 本文件是《CORE-01 + EMOTION-01 实施方案》的优先修订补充。原方案中“仅保留现有 12 类而不扩容”的倾向被本文件取代。这里的 24 类是第一轮工程候选目录，不是心理学公认的唯一分类体系，不等于情绪真实体验的测量结果。

## 0. 真实源码核对与根本缺口

- `web/app.js` 的 `renderChat()` 中，`$('emotionMeters').innerHTML` 仅渲染 `valence / arousal / stress / engagement` 四条进度条。
- `persona/psychology.py` 定义的 `STATE_KEYS=('valence','arousal','stress','engagement')` 仍是旧的活动状态路径。
- `persona/construct_registry.json` 已定义 VAD 三项、12 类情绪、12 项 appraisal、5 项 emotion regulation；`registry.py` 打包为 93 个固定字段。因此“注册表有 12 类”不能认定“实时维护了 12 类”。
- `persona/cognition.py:features()` 等路径也直接读取四维 `activity['emotion']`；这涉及后端消费者，不能只加 24 条 UI 进度条。

## 1. 理论区分，避免混维度

1. **Core affect（低维连续）**：Valence [-1,1]、Arousal [0,1]，Dominance [0,1] 可选、未知用 null。参考 Russell（1980）、Bradley & Lang（1994）。
2. **Emotion categories（具体情绪激活）**：多标签、可同时存在、每项独立强度、置信度、来源与时间动力学；不强制和为一；不能由 VA 四象限直接等式映射。参考 Cowen & Keltner（2017）；该研究识别出 27 种有区别的自报体验，但不是项目必须照抄的固定枚举。
3. **Appraisal（事件评价）**：保持既有 12 字段作为事件级条件估计，不假装它们是十二个实时“情绪”；参考 Scherer 的成分过程模型。
4. **Regulation（调节）**：保持现有 5 大策略；它们可以改变注意、解释、内在动力学或对外表达，不能简单等效为“情绪值降低”；参考 Gross（2015）。
5. **Contextual auxiliaries（辅助状态）**：stress、engagement 是负荷及参与状态，不是与 valence/arousal 同级的基础情感维度。
6. **Mood vs episode**：慢变心境/情绪基线与快变的事件性情绪分别保存。显示的是“模型化的当前情绪倾向”，不宣称 AI 主观体验已经被测量。

## 2. 第一阶段具体情绪目录：旧 12 + 新候选 12

### A. 现有 12 个 ID 保持不变

| 中文 | 英文 | 现有注册表 ID |
|---|---|---|
| 喜悦 | joy | `affect.label.joy` |
| 悲伤 | sadness | `affect.label.sadness` |
| 愤怒 | anger | `affect.label.anger` |
| 恐惧 | fear | `affect.label.fear` |
| 厌恶 | disgust | `affect.label.disgust` |
| 惊讶 | surprise | `affect.label.surprise` |
| 兴趣 | interest | `affect.label.interest` |
| 羞耻 | shame | `affect.label.shame` |
| 内疚 | guilt | `affect.label.guilt` |
| 感激 | gratitude | `affect.label.gratitude` |
| 自豪 | pride | `affect.label.pride` |
| 挫败 | frustration | `affect.label.frustration` |

### B. 增加 12 项可测候选（名称、粒度及归属须在标注预实验中核查）

| 中文 | 英文 ID | 区分要点 |
|---|---|---|
| 焦虑 | anxiety | 面向未来的不确定威胁，不与即刻恐惧合并 |
| 宽慰 | relief | 威胁/负担解除后的变化，与一般喜悦区分 |
| 平静 | calmness | 低唤醒不等于平静；需要低威胁/安全评价 |
| 逗乐、好笑 | amusement | 幽默相关的正向体验，与一般喜悦区分 |
| 失望 | disappointment | 期待结果落空；不等于悲伤或挫败 |
| 无聊 | boredom | 低刺激、低意义或持续参与不足，可不同于低唤醒 |
| 孤独感 | loneliness | 社会连接需求未满足的情感状态；可能更慢变 |
| 喜爱、亲近感 | affection | 对特定对象的亲近倾向，必须严格区分关系事实 |
| 尴尬 | awkwardness | 社交不协调体验，不直接等同羞耻 |
| 敬畏 | awe | 规模感/认知调适；与惊讶区分 |
| 羡慕 | envy | 社会比较中的所欲差距；不直接等同嫉妒（jealousy） |
| 怀旧 | nostalgia | 由真实自传式记忆线索激活；不得凭空编造经历 |

所有新增项采用单独 `emotion_catalog_v2` ID 空间或独立扩展表。**不要未经版本化迁移直接向既有 93 字段数组追加 12 列**：这会更改 `registry_hash`、`feature_order` 和 `registry_pmm`/`cognition` 的固定向量长度，破坏旧权重与人格包读取。V2 先保留 93 字段原貌，以 12 旧类别 ID 为桥接，额外维度放在可扩展、带 schema_version 的实时情绪状态对象；Learned-PMM 后续为新增维度建立显式映射与训练版本。

## 3. 新实时状态数据协议

`AffectiveState` 应至少包含：
- `persona_id, state_version, updated_at, last_event_id, dynamics_model_version, calibrated`。
- `core_affect: {valence, arousal, dominance}`，各项允许 `null` 并保存估计/置信度。 valence 的旧范围保持 [-1,1]。
- `context_state: {stress, engagement}`（沿用旧数据兼容，但不作为核心情感维度）。
- `mood: {baseline, current, uncertainty}`，慢变；与即时情绪 episode 分离。
- `emotion_activations: {emotion_id: {intensity, confidence, last_triggered_at, source_event_ids, time_constant, unknown}}`，覆盖当前 12 + 扩展 12，多标签，不强制总和为 1。
- `active_episodes: [{episode_id, appraisal_id, trigger_event_ids, actor_id, subject_id, scope, started_at, intensity, resolved_at}]`，支持多情绪和混合情绪。
- `expression_state` 应与内部情绪状态分离：实际表达受到人格和调节策略约束，不能从消息语气反推唯一真实内部状态。

严格区分 **0 = 有足够依据的低激活**、**null/unknown = 未知**、**stale = 缺少近期依据**。旧四项状态升级只迁移同名字段，不凭 VA 算出过去不存在的 24 项“历史情绪”。

## 4. 动力学与事件评价（实施算法而非固定关键词）

1. 时间演化（事件间）： `z_i(t+Δt)^- = b_i + exp(-k_i Δt)(z_i(t)-b_i) + ξ_i`；`b_i,k_i` 允许人格条件化及训练校准，未经校准标记先验。不同情绪可有不同时间尺度，不应复用一个统一 30 天或 2 小时参数。
2. 事件评价（事件时）：复用 General LLM 的事件理解结果，计算 `a_t=f_appraisal(event, self, relation, goals, memory)`；必须基于真实来源证据，不直接复制他人表达的情绪为自己的状态。
3. 情绪激活（事件后）：`z(t^+)=project(z(t^-)+g_θ(a_t,self,context,prior_emotions))`；多标签允许混合、延续与重叠； `g` 的参数与交叉作用需要训练或实验校准。第一阶段 API-PMM 使用结构化评价 + 可审计参数模型，Learned-PMM 后续进行训练。
4. 调节：`regulation` 作用于事件选择、注意、重新评价与外在表达等不同阶段，不是统一乘一个小于 1 的系数。表达抑制不能直接清除内在激活。
5. 状态更新具备 event_id 幂等、时间顺序、版本/CAS 与重启连续性。相同消息被 QQ 重发或后台批次重复读取，不得二次增加情绪。
6. 不要求每秒额外调用一次外部 LLM。无消息时可在下一次使用时按 elapsed time 重算；若自主认知循环产生真实内部状态事件，再进入同一协议。

## 5. UI：实际替换“四条情绪柱”

日常人格/对话界面：
- 第一行「当前情绪倾向」：展示当前最显著的 1–3 种具体情绪，可展示混合情绪，并注明估计时间/置信度。无证据时显示未知，不应虚构“平静”。
- 第二行 Core Affect：Valence、Arousal、可选 Dominance；辅助状态 Stress、Engagement 放在独立“参与与负荷”区域。
- 点击「查看完整情绪」出现 24 项实时类别状态，按社会、自我评价、积极体验、消极体验等 **仅用于展示** 的组别分区；能查看相应时间曲线、触发事件、恢复程度及来源。
- 「研究与诊断」才显示完整 appraisal、regulation、情绪耦合与时间参数、先验/已校准标志。不能把 24 个滑杆当作算法。
- 任何显示值都从持久化 `AffectiveState` 读取，不能用前端默认值或从 VA 临时补造 24 类。

## 6. 代码落点及升级策略

- `persona/psychology.py`：停止将 `STATE_KEYS` 的四项视作完整实时情绪表示；保留兼容适配。
- `persona/cognition.py`：把旧四值特征读入改为版本化 `AffectiveState` 编码与缺失掩码；已训练数值头不得静默改输入维度，应显式版本迁移或保留兼容投影。
- `persona/registry.py` 和 `construct_registry.json`：原有 93 IDs 与 hash 暂时保持，新的实时目录独立版本管理。
- `persona/engine.py` / `consolidation.py`：所有实时情绪写入走同一状态入口；长期人格证据仍独立进入后台。
- `web/app.js` / 对应 HTML/CSS：新增实时类别状态展示，移除仅四维情绪面板的“全量情绪”假象。
- 保留人格 ID、会话、情绪历史、PMM 包、训练参数、QQ/API 连接；在迁移脚本中使用只读兼容扫描、幂等升级、迁移前后统计和旧包回归。

## 7. 验收测试

- 静态：24 类目录定义完整，旧 12 稳定 ID 不变，既有 93 字段/哈希不被误改。
- 实时：同一事件可同时激活焦虑与兴趣；焦虑与恐惧分离；威胁解除可出现宽慰；负效价并不直接决定愤怒。
- 个体：相同事件不同人格的先验、关系与基线会影响结果，来源和参数可审计。
- 独立：群友说“我很悲伤”不能自动让 AI 的悲伤=1；AI 自发语言不能反复作为独立情绪外部证据。
- 时间：无事件时多种情绪以不同时间尺度改变；短期 episode 与慢变心境分离；重启恢复与输入事件去重正确。
- 显示：界面不再只有四项；能查看 24 类当前激活/未知状态、时间和触发来源；真实前后端值一致。
- 性能：普通消息不额外触发 24 次 API 调用，记录耗时和调用次数。
- 迁移：从 2.2.3 真实格式旧档升级，历史数据、人格与原有权重不丢失；新字段未知而非虚假零值。
- 研究：比较 VA-only、旧 12 类、扩展 24 类的情绪标签合理性与行为预测，使用独立标注数据、置信度校准和人格/关系消融，不预设“类别越多越好”。

## 8. 参考文献

- Russell, J. A. (1980). A circumplex model of affect. https://doi.org/10.1037/h0077714
- Bradley, M. M., & Lang, P. J. (1994). Measuring emotion: The self-assessment manikin and the semantic differential. https://pubmed.ncbi.nlm.nih.gov/7962581/
- Scherer, K. R. (2005). What are emotions? And how can they be measured? https://doi.org/10.1177/0539018405058216
- Kuppens, P., Oravecz, Z., & Tuerlinckx, F. (2010). Feelings change: Accounting for individual differences in the temporal dynamics of affect. https://doi.org/10.1037/a0020962
- Gross, J. J. (2015). Emotion regulation: Current status and future prospects. https://doi.org/10.1080/1047840X.2014.940781
- Cowen, A. S., & Keltner, D. (2017). Self-report captures 27 distinct categories of emotion bridged by continuous gradients. https://doi.org/10.1073/pnas.1702247114
- Barrett, L. F. (2004). Feelings or words? Understanding the content in self-report ratings of experienced emotion. https://doi.org/10.1037/0022-3514.87.2.266
