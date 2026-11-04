# 记忆补丁的研究依据与实现边界

这组文献用于约束设计，并不表示本程序已经复现人脑或获得人格真实性的实证验证。实现中的时间阈值、强度和预算均为待校准参数。

| 依据 | 对本程序的设计启发 | 不作的推断 |
| --- | --- | --- |
| Reyna、Corbin、Weldon、Brainerd（2016），Fuzzy-Trace Theory | 区分字面记录与意义要点；保存两者并保留来源。 | gist 不自动等于正确；摘要可能误解或造成错误推断。 |
| McClelland、McNaughton、O’Reilly（1995），互补学习系统 | 快速保存当前事件，较慢地批量整合；前台经历与后台长期整理分工。 | 两个软件模块不等于海马/新皮层，也不能据此称为生物学模型。 |
| Bjork 与 Bjork（1992），New Theory of Disuse | 区分存储强度和当前可检索性；遗忘优先表现为不易想起，而非立即删掉原始记录。 | 本版指数函数不是该理论的完整实现；没有从文献推导出默认 30 天或增量 0.03。 |
| Zacks 等（2007），事件分段理论 | 用明确结束、重大事件、时间间隔和工作预算作为整理触发线索。 | 当前规则与 PMM 判断不等于经过验证的人类事件边界检测。 |

## 原始论文与作者来源

- Reyna et al. (2016). *How Fuzzy-Trace Theory Predicts True and False Memories for Words, Sentences, and Narratives*. https://pmc.ncbi.nlm.nih.gov/articles/PMC4815269/ ，DOI: 10.1016/j.jarmac.2015.12.003。
- McClelland et al. (1995). *Why There Are Complementary Learning Systems in the Hippocampus and Neocortex*. 作者稿：https://web.stanford.edu/~jlmcc/papers/McCMcNaughtonOReilly95.pdf ；摘要：https://pubmed.ncbi.nlm.nih.gov/7624455/ 。
- Bjork & Bjork (1992). *A New Theory of Disuse and an Old Theory of Stimulus Fluctuation*. 作者实验室：https://bjorklab.psych.ucla.edu/wp-content/uploads/sites/13/2016/07/RBjork_EBjork_1992.pdf ；概念说明：https://bjorklab.psych.ucla.edu/research/ 。
- Zacks et al. (2007). *Event Perception: A Mind–Brain Perspective*. 摘要：https://pubmed.ncbi.nlm.nih.gov/17338600/ ；作者论文：https://pmc.ncbi.nlm.nih.gov/articles/PMC2852534/ 。

核对日期：2026-10-26。PMC 的 Zacks 全文页在本次读取时出现校验页，文献信息和理论摘要使用 PubMed 记录核对；没有假装读取受阻全文。

## 建议实验

以原始对话为基准，分别测量摘要事实忠实度、来源归属错误、旧事实检索率、错误共同经历、重复/过早回复与真实延迟。对照组应关闭相应机制，并固定模型、提示、温度和输入顺序。记忆曲线需用重复测量数据校准；当前自动测试只覆盖程序合约、隔离、可恢复性和错误路径。
