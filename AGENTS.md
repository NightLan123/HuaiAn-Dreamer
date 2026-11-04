# 槐安梦客 / HuaiAn Dreamer — Codex 项目约束

## 任务与指令优先级
- **当前开发目标：在现有2.8.1源码上实现2.8.2**。首先阅读 `docs/V282_SOL_ULTRA_SPEC.md` 的A–C部分，再按阶段阅读所需技术细节。
- 源码/真实测试与可观察行为是实施事实的依据。`docs/PMM_PERSONALITY_AFFECT_THEORY.md` 负责心理学算法约束；`docs/V281_SPEC.md`、`docs/V281_EMOTION_CONTRACT.md`、`docs/V281_LIMITS.md` 和旧版规范只用于理解既有实现、数据兼容和历史。出现冲突时以最新2.8.2规范的要求和用户当前明确纠偏为准，且不得假称已经完成尚未实现的功能。
- 不要从零重写简化版PMM，不要把项目改为只有Prompt/RAG的人设聊天机器人。除修复必要故障，不擅自改写人格与情绪核心数学公式。

## 架构必须保留的边界
- General LLM与PMM是不同的组件：General LLM负责用户消息语言理解与最终表达；PMM负责动态心理、记忆、人格、情绪、价值、关系、评价、协商与决策。
- General传给PMM必须同时包含**原始对话、结构化事件分析及上下文/证据引用**，不允许只给摘要。
- PMM-A负责事件/心理推理；PMM-B按同一完整人格状态生成和协商多个**综合情境立场**，不是固定角色或人格量表维度各自投票。保留分歧与逐轮可查的历史记录。
- 回复校验器不再根据`reply/clarify`标签是否完全相等直接吞掉正常回复；明确硬性约束与角色风格偏差需不同处理，发送状态必须可追踪、不可重复发。
- 动态人设JSON从**现有角色创建/编辑的人设资料**派生、版本同步；不另外建立能独立自我修改的人设真值来源。
- 入口Cognitive Router只按事件选择相关检索与LLM推理；高维人格/情绪可在本地完整计算，但不应全量反复塞进每个Prompt。
- PMM的内部A、B模型接口独立；本地Ollama或云端API均受支持；不能把General LLM算作PMM内部层。
- 保留原有2.8.1资料、人格包、情绪、关系、记忆、旧版兼容及旧数据库迁移。备用兼容仅故障恢复，不进行日常旧新版对照。

## 实施与测试
- 先核对当前工作树是2.8.1，以及数据库/测试数据有没有本地未提交变动。建立Git检查点或备份后，再逐阶段实施。
- 阶段0先核对调用链与复现 `invalid_evidence_span`、`clarify/reply`矛盾、异常Token输入（回复生成64,047输入Token）；阶段1优先修复无回复。其余严格按照 `docs/V282_SOL_ULTRA_SPEC.md`。
- 每阶段修改真实源码、运行对应测试，在 `docs/V282_PROGRESS.md` 追加状态、修改文件、实际测试命令与结果、未完成问题、下一步。不得将既往验收数当作本轮测试结果。
- 与用户真实人格、历史记录、API密钥、QQ消息有关的内容不得在日志或提交中泄露；使用脱敏/合成测试夹具。不得在云端环境声称验证本地Qwen、真实QQ或Windows原生测试。
- 不要在大量改动后才开始测试。先实现一条从消息接收、后端执行、记录、UI到测试的可观察路径，再扩展。
- 权重未经训练验证，不得自动更新长期人格；一次失败候选不能作为已发送事实写入长期记忆；失败或未送达不可被伪装成角色主动沉默。

## 入口与测试参考
- 首读：`README.md`、`RELEASE.json`、`docs/V281_ACCEPTANCE.md`、`docs/V281_LIMITS.md`、`docs/V282_SOL_ULTRA_SPEC.md`。
- 核心入口和模块：`run.py`、`persona/engine.py`、`persona/validation.py`、`persona/deliberation.py`、`persona/pmm_negotiator.py`、`persona/provider.py`、`persona/pmm_coordinator.py`、`web/app.js`。
- 现有2.8.1测试示例（视当前环境可用性执行，不能假称通过）：`python tests/run_v281_regression.py v281`、`python tests/run_ui_v281.py`、`python tests/browser_v281.py`。
