# 2.6 当前 D/E 路径与写入边界

早期整体架构保存在 ARCHITECTURE.md（明确标注 v2.1）；当前分层见 TRAIT_EMOTION_IMPLEMENTATION_20261029.md，表达/发送见 CBM_IMPLEMENTATION_20261030.md。2.6 沿用这些边界并加入如下模块。

| 数据或阶段 | 负责人 | 可写内容 |
|---|---|---|
| 授权人类来源 | psychology.py / learning.py | 原始记录及原有学习任务；AI 来源不能改名冒充人类 |
| 语言证据视图 | pragmatics.py | 有时间与无时间两类派生特征，保留来源和独立事件 ID |
| 独立人工目标 | language_learning.py | 候选、门槛、应用与不可变审核证据；不把观察到的 AI 输出自动当目标 |
| 稳定人格 | traits.py / registry.py | 沿用既有独立长期证据晋升；本轮不由情绪回写 |
| 短期情绪与心境 | affect.py | 按真实时间与有证据的事件评价演化；Emotion/Mood 分开，事件重放不重复提交 |
| 行动与表达 | engine.py / expression_plan.py / joint_expression.py | 冻结行动、权限及边界后，分别读取 D/E/trait/context；既有策略的可审计候选评分 |
| 生成与验证 | api_pmm.py / engine.py / validation.py | 为模型提供版本化条件；语义分段与最终检查继续生效 |
| 已发事实 | execution.py / engine.py / qq.py | 依据实际回执提交消息、状态与学习；未知回执不重发，部分确认只提交成功前缀 |
| 所有者追踪 | joint_expression.timeline / server.py / web | 分页连接输入、版本、状态、策略、实际消息、回执与人工反馈；公开诊断仍脱敏 |

`pragmatic-style/1` 外层保持兼容，附加 `language-evidence/2`。`de-expression/1` 单独传递语言版本、情绪 revision/time、心境 time 和 trait digest；它们没有合并为一个人格分数。AI 行为只进入 observed_ai，人工独立评价才进入目标候选。

两种“更新”分开：导入/来源变更可重建描述统计；人工标注/修订生成候选后必须经门槛和审核才能改变目标倾向。统计与已审核目标均按话语行为供策略读取，旧未审核值不会混入。源证据改动后旧目标应用失效，审核历史仍保存原始证据副本。

本机输入可带持久 client_event_id，已提交重试回到原回合；完全相同的人工修订有独立反馈回执，避免重复训练。部分 QQ 回执核验沿用原 Outbox，不以模型生成的条数代替发送事实。

局部评分可以解释哪个条件进入了哪项增减；`read` 只能表示字段交给了决策/模型，不能证明对某个输出词语的因果影响。新增语用头保持 not_trained，时间常数、基线、权重与候选门槛保持未校准标记。
