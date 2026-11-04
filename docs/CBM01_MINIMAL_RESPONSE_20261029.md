# 槐安梦客 · CBM-01 修订：自然交流、局部响应与表达规划

基线：2.2.3-H2 源码；修订既有 `interaction-plan/2` 设计。此文为开发规范，**尚未写入运行程序**。

## 0. 必须纠正的设计偏差

旧方案把每次对话组织成 `ACCEPT → ELABORATE → ASK → YIELD` 等完整步骤，容易诱发：不必要的追问、自动补充、话题过度推进、既已明确的意愿重复确认、为凑多气泡而拆分。**交际动作和消息气泡非一一映射。**

新目标：生成**对当前语境足够、对双方自然、又符合稳定人格**的下一步表达。一次行为可以只有 `ACKNOWLEDGE` 或 `ACCEPT`，完全无须额外问题。`YIELD_FLOOR` 是停止发送并留给对方，不是必须问一个问题。对话可以留白、停住或自然结束。

心理学/会话分析参考：König (2019), *Sequential patterns in SMS and WhatsApp dialogues*, DOI:10.1177/1750481319868853；Clark & Brennan (1991), *Grounding in Communication*；对话关联、邻接对与协作努力，不直接等于已训练心理预测器。

## 1. 明确的纠错例子（必须作为评测集）

1. 上文：`最近有点想玩胡闹厨房` → `胡闹厨房可以啊` / `胡闹厨房可以啊` + `你想玩？`；禁止没有上下文就问“你想玩几关/什么时候开/你玩什么模式”。
2. 上文：`要不要一起玩胡闹厨房？` → `可以啊` 或 `行啊`；对方已经表达邀请，不能重复问“你想玩？”；如确有时间安排需求才问“现在吗？”。
3. 上文：`我打算今晚八点开胡闹厨房，你来吗` → `可以啊，八点是吧`；避免跳转“几关”。
4. 上文：`我打工累死了` → `唉，真的累`/`那你先歇歇`；不可机械追问详细安排或自动提供方案。
5. 上文：`这游戏怎么联机？` → 以有效步骤为主，信息完整；不能因为偏好短句而省掉关键步骤。
6. 上文：`我先去忙了` → `行，去吧`/`好`/允许无回复；不可强行新增问题延续话题。

上述均为候选，最终取决于人格、关系、上下文和已授权行为。

## 2. 交互状态：先判断现在交流处于哪里

在 `InteractionState` 中新增/完善以下**情境字段**（状态值可以未知，不能伪造）：

- `prior_speech_act`：对方刚才做了什么，邀请、建议、抱怨、叙事、提问、感叹或结束。
- `pending_response_obligation`：是否存在明确待回答的问题或请求；要求高时确保完整回答。
- `already_established`：已经共同确认的事项，如“对方想玩”“已经约定时间”。
- `proposed_next_move`：此刻下一步最自然的回应功能。
- `unresolved_need`：真正需要进一步询问的事项；空时**不得为了互动率强行提问**。
- `partner_floor_status`：对方是否正在连发、等待自己接话或结束。
- `topic_sensitivity` 与 `social_distance`：说话分寸和关系，不作为机械常数。
- `context_version`、`source_event_ids`、`uncertainty`：便于检验和复核。

**切忌**由 `interest=true` 自动生成问题，或由 `social=true` 自动生成三条消息。

## 3. 调整 PMM 的目标函数与动作空间

候选策略包括：
- `MINIMAL_REPLY`：一个简短完成当前应答的表达；正常优选项之一。
- `RESPOND_AND_YIELD`：简单回应后停止，交还话语权；提问可有可无。
- `CASUAL_BURST`：一次交流中连续发送几个自然、独立且必要的短消息，允许一条。
- `OPTIONAL_EXPANSION`：存在真实自发补充动机才稍后补充，不为了活跃而硬加内容。
- `CLARIFY_IF_NEEDED`：有关键歧义或决策确有必要时才追问。
- `REPAIR`：出现实际误解或错误时修正。
- `NO_ACTION / WAIT`：合法的无输出/等待。

旧 `ASK_AND_YIELD` 退为可选的 `CLARIFY_IF_NEEDED`；不再设定“问完才算让轮”。

每次计划决策必须评估以下**不等同于构念量表的计算特征**：
- `local_relevance`：是否回应眼前消息。
- `sufficiency`：当前回复是否已足以完成合理交际目的。
- `redundancy_risk`：是否重复已知内容或已表达的意愿。
- `premature_progression_risk`：是否提前进入对方尚未要求的任务阶段。
- `conversation_burden`：是否给对方施加无意义的回答义务。
- `spontaneous_motivation`：是否真的存在分享、询问、调侃或修正的倾向。
- `persona_consistency`：稳定人格/长期表达习惯是否得到尊重；当前情绪只作调节。

上述指标在 API-PMM 中是**待验证的结构化推断或基线特征**，不得声称心理学已给出其数值系数。先用候选对照/有限排序，不增加每气泡 PMM 调用。

## 4. 协议升级到 `interaction-plan/2.1`

示例：

```json
{
  "schema": "interaction-plan/2.1",
  "selected_action": "REPLY",
  "previous_act": "express_tentative_interest",
  "response_obligation": "none",
  "established_facts": ["partner mentioned potential interest; no agreement yet"],
  "local_goal": "friendly_acknowledgement",
  "sufficiency_target": "minimal",
  "candidate_strategy": "RESPOND_AND_YIELD",
  "allow_follow_up_question": true,
  "follow_up_need": "only_if_natural_confirmation",
  "forbidden_topic_progression": ["plan_game_rounds", "schedule_session"],
  "message_plan": {"delivery": "single_or_burst", "max_bubbles": 4, "target_bubbles": null},
  "yield_after_current_reply": true,
  "basis": {"source_event_ids": [], "model_type": "API_PMM_STRUCTURED", "calibrated": false}
}
```

`max_bubbles` 为硬资源上限，`target_bubbles:null` 表示不预设必发条数。更简短的合法计划可以只有 `local_goal`、`strategy`、`stop_after_reply`。**不能将此示例字段直接解释为已学得的心理变量。**

## 5. 改造 General LLM 输出层

- 明确要求**不补全对话流程**：内容已经足够时就结束；不要自动追问、归纳、建议、安排未来步骤。
- 不应每次生成完整三步脚本，不应为了达到上游 Step 数强行生成额外内容。
- 优先按原始上下文辨认对方已表达/未表达的意愿；已经直接邀请不能再问“你想玩吗”。
- `message_parts` 可以 1 至上限条；每条可以是短感叹、短补充、问题，前提是语境自然。
- 文本生成完成后执行简短的校验：回答了必要问题？加入了多余问题？是否提前安排并不存在的任务？是否重复上文？若不必要，允许**删除尾句而不是重生成所有内容**（必须校验删除后仍符合 PMM 原选定行动）。
- `STEPWISE` 与 `CASUAL_BURST` 区分：后者可在同一决策中发完；前者先发一部分再等真实新事件，后续不是倒计时强行继续发，长期未响应时不强迫补发。

## 6. 可学习的自然口语策略

在现有 `PragmaticStyleProfile` 中增加条件化特征：
- `response_sufficiency_preference`：普通闲聊倾向在什么程度结束当前轮。
- `question_initiation_propensity`：在何种关系/情境有明确需要时会主动提问。
- `topic_progression_tendency`：通常是回应当前内容还是主动推进到新步骤。
- `ellipsis_and_understatement`：语用省略与低强度表达的习惯，和语法不完整区分。
- `yield_after_acknowledgement`：简短认同后让轮的倾向。
- `burst_context_distribution`：什么语境下真正使用多气泡；和“发几条”统计分离。

学习材料只使用授权的多轮原始对话与时间戳，并区分人类示范、AI 自己实际发送、独立他人反馈；自生成回复不可自我循环当成真值。长期人格、当前情绪、对方角色、对方真实关系**分开入模**。训练时同一句在不同 `prior_speech_act` 下应可产生不同策略。

## 7. 代码修改点（基于 2.2.3-H2）

- `persona/expression_plan.py`：删除“分段即表达策略”的单一目标。`decide_expression` 从是否 multi 改为使用 `InteractionState` 选择局部话语行为与默认终止条件；保留 H2 为显式对照基线。
- `persona/engine.py`：在 PMM 选择 `REPLY` 时输出 `local_goal`、`sufficiency`、`question_necessity` 等计划；`REALIZE` 增加避免过度推进/虚假提问的约束。无需每气泡多次推理。
- `persona/turn_taking.py`：跟踪当前说话权，支持自然停止、不追问、收到新消息重新规划。
- `persona/psychology.py`：将多轮语言蒸馏从短句/连发比例扩展为上下文条件化话语行为分布。
- `persona/qq.py`、`persona/execution.py`：已发送前缀逐条提交，计划余量可停止；停止不是发送错误，必须与 `DELIVERY_PARTIAL` 技术失败区分。
- `web/app.js`：诊断时解释“为何停止/为何提问/为什么只发一条”，普通 UI 不加一堆控制项。

**特别安全约束**：不应把自然化视为降低对明确问题的答复质量；任务、健康、法律、危险、高风险或需要完整步骤的问答应优先确保充分性；当话题需要准确说明时不能靠故意含糊模拟口语。

## 8. 测试与研究验收

固定测试集覆盖：已邀请/尚在考虑/表达抱怨/事实询问/结束交流/陌生人与熟人/相同稳定人格不同当前情绪/被打断/无新消息。

观测指标：
- `unnecessary_followup_rate` 不必要追问率；
- `premature_commitment_rate` 过早推进安排率；
- `response_sufficiency` 当前应答充分性；
- `conversational_burden` 无意义回答义务；
- `redundant_question_rate` 重复提问率；
- `naturalness` 人工盲评自然度；
- `persona_consistency` 人格条件化一致性；
- `realized_bubbles_per_turn` 实际气泡分布；
- `delivery_consistency` 真实回执与对话历史一致。

要求与 H2 启发式在同一数据、同模型/调用预算下比较，报告样本与失败例；不以更多气泡、更少字或更活跃作为单一性能目标。

## 9. 交付要求

先实现最小局部响应计划和有效终止，再扩展多气泡。提供实际源码差异、清晰调用 Trace、旧 2.2.3-H2 数据兼容、单轮对照样例与回归测试；不能仅替换固定示例句，不能只写 Prompt 且宣称完整 PMM 策略学习完成。实际改造应先保证此前 2.2.3-H2 多气泡确认/部分发送事件的一致性。