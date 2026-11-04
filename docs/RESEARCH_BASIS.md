# 研究依据与工程假设

本版从最新讨论中落实“长期人格、短期倾向、即时情绪、长期情感、记忆、关系、自我与对象模型分离”的要求。下面的理论提供组织维度，**没有提供本程序所用的更新系数、网络权重或人格测量效度**。

| 依据 | 在本程序中的使用 | 不能据此声称的事 |
| --- | --- | --- |
| HEXACO-PI-R | 主字段采用24面向+利他性，完整来源与不确定性 | 本程序没有施测 HEXACO，也不输出量表标准分；没有复制问卷题目 |
| Schwartz精细化价值理论 | 采用19种价值动机；近似圆环距离用于冲突提示 | 动态候选、效用权重和触发阈值为工程设计 |
| VAD与情绪连续维度 | canonical采用效价/唤醒/主导感；旧版效价/唤醒/压力/参与另行保留 | VAD不等于Russell二维环状模型；标签集合和评价检查拆分为工程操作化 |
| Mischel & Shoda 的认知—情感人格系统（CAPS） | 保留“情境—反应”规律和反例；同一人格可以随情境作不同反应 | 没有实现经验证的完整 CAPS 动力系统，不能把生成一致性等同于人格真实性 |

| Scherer认知评价 / Gross调节过程 | 12项评价检查与5类调节节点，分别记录证据 | 十二检查的拆分为本项目操作化；策略节点不是人格类型 |

旧版Big Five五因素和十价值作为兼容视图保留，不换算或拼接为HEXACO。短时情绪和较慢心境采用不同时间尺度；情境人格偏移受到边界限制，不改写稳定人格证据。关系中的熟悉度、信任和情感倾向单独保存。当前更新率、两小时/四十八小时回落常数、关系单次变化上限以及人格偏移公式全部是可检验、可替换的工程假设。

AI 自身生成的回复只能提供“它本轮实际说了什么”的行为证据。它不是对方事实的证据，也不应成为自己风格学习的无限自我复制来源。因此：

- canonical稳定HEXACO/价值不由自身生成回复创建真值；旧版兼容观察保持原有低权重处理。生成内容不升为全局信念或经历事实。
- 原始目标聊天和人工改写才定义目标风格；生成回复回流用于编码、情绪反馈和风格偏差观察。
- 对象模型只接收该对象在该情境中的原话证据，并标为待修正假设。
- 逐字引用校验可以排除伪造引文，但不等于验证“引文真的蕴含模型判断”。推断仍须人工校准。

## 原始资料

1. Berkeley Personality Lab. **Big Five Inventory (BFI-2)**. 研究团队说明：https://www.ocf.berkeley.edu/~johnlab/bfi
2. Schwartz, S. H. (2012). **An Overview of the Schwartz Theory of Basic Values**. *Online Readings in Psychology and Culture*, 2(1). https://doi.org/10.9707/2307-0919.1116 。原文页：https://scholarworks.gvsu.edu/orpc/vol2/iss1/11/
3. Schwartz 对其理论的作者说明：https://i2insights.org/2022/05/10/schwartz-theory-of-basic-values/
4. Russell, J. A. (1980). **A Circumplex Model of Affect**. *Journal of Personality and Social Psychology*, 39(6), 1161–1178. https://doi.org/10.1037/h0077714 。原论文副本：https://pdodds.w3.uvm.edu/research/papers/others/1980/russell1980a.pdf
5. Mischel, W., & Shoda, Y. (1995). **A Cognitive-Affective System Theory of Personality: Reconceptualizing Situations, Dispositions, Dynamics, and Invariance in Personality Structure**. *Psychological Review*, 102(2), 246–268. https://doi.org/10.1037/0033-295X.102.2.246

接口参考：

- Ollama Chat：https://docs.ollama.com/api/chat
- Chat Completions：https://developers.openai.com/api/reference/resources/chat
- OneBot 11 HTTP 上报：https://github.com/botuniverse/onebot-11/blob/master/communication/http-post.md
- OneBot 11 公共 API：https://github.com/botuniverse/onebot-11/blob/master/api/public.md

本次核对日期：2026-10-23。没有以网页搜索代替用户已经确认的研究目标；这些资料用于解释维度和接口选择。


## 参数分离与学习边界

v2.1 延续核心 θ 与个体残差 Adapter Δ，使日常适配与共享参数版本管理分开。低秩潜变量适配、状态转移矩阵和任务头为本项目的具体设计，未声称是 LoRA 原论文的复现，也未对基础 LLM 进行权重注入。可比较的参数高效学习原始资料：Hu et al., *LoRA: Low-Rank Adaptation of Large Language Models* (2021), https://arxiv.org/abs/2106.09685 。这里参考参数分离思路，不能以该论文的结果证明本 PMM 的有效性。

最近样本回放用于让增量梯度同时读取一部分既有样本；不保证解决遗忘。持续学习与经验回放的相关原始资料：Rolnick et al., *Experience Replay for Continual Learning* (NeurIPS 2019), https://arxiv.org/abs/1811.11682 。本项目只实现有界回放和分组保留集，没有复现其完整强化学习方法。

v2.1不把内部候选和价值偏移自动当作真实标签；人类选定的候选可训练动态门控，实际事件的模型反馈仍是弱标签。四类语用特征来自显式中英文词频表，属于可检查的工程代理。它们需要独立的人类标注与构念效度检验，不能直接叫作稳定心理真值。

研究目标检索与实现更新日期：2026-10-25；心理学基础文献仍沿用前版已核对的原始资料。

## v2.1新增定义来源

- HEXACO官方面向与24+1说明：https://www.hexaco.org/scaledescriptions 、https://hexaco.org/history
- Schwartz et al. (2012), Refining the theory of basic individual values：https://doi.org/10.1037/a0029393 。19价值结构亦见作者/机构记录：https://publications.hse.ru/en/articles/67055241
- Scherer组件过程模型：沿用研究原契约的文献标识 https://pubmed.ncbi.nlm.nih.gov/18540750/ 。本次网页仅返回站点页脚，未据此声称重新全文核验。
- Gross (2015), Emotion Regulation: Current Status and Future Prospects：https://doi.org/10.1080/1047840X.2014.940781 。期刊原页：https://www.tandfonline.com/doi/abs/10.1080/1047840x.2014.940781

2026-10-25更新：字段表来自用户已确认的研究开发契约，额外核对官方/原始论文来源。引用理论只说明组织依据，不提供本程序的心理效度保证。
