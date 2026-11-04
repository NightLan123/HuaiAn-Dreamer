# 历版要求逐项核对：2.2.3

`实现`=有运行代码且本地测试覆盖；`部分`=只有要求中的一部分；`待实现`=当前没有完整路径；`待实机`=未接真实用户环境；`待研究`=需要独立数据或实验，不能用程序测试代替。未带目录的 Python 模块均位于 persona/；其他路径相对程序根目录。历史对话未完整取得，范围见 VERSION_AUDIT_20261028.md。

| ID / 来源 | 要求 | 当前结果 | 实际代码 | 验证或缺口 |
|---|---|---|---|---|
| R01 v1/v2 | General 与 PMM 独立配置和请求 | 实现 | provider.py、api_pmm.py、server.py | test_v2 / test_providers_v04；同物理模型也保留角色区分 |
| R02 v0.4/v2 | 小模型也可通过独立接口运行 | 实现 | pmm_interface.py、pmm_service.py | test_pmm_interface；本地 HTTP 运行真实数值计算 |
| R03 v2 | 六种主流原生协议 | 实现，待实机 | provider.py | Ollama、Chat、Responses、Messages、Gemini、Azure；本地协议服务测试；非所有型号逐家验证 |
| R04 v2 | 未连接或失败时不静默用 mock | 实现 | engine.py、provider.py、pmm_interface.py | test_runtime / test_v2 / test_v211；夹具仅在测试注入 |
| R05 v1/v2 | 状态更新与权重训练分离 | 实现 | engine.py、registry.py、registry_pmm.py | API 状态持续更新；Learned 才执行参数优化；capabilities 独立标记 |
| R06 v2 | API / Learned 统一外部 Backend 全合约 | 部分 | engine.py、api_pmm.py、pmm_interface.py | Engine 编排兼容；没有完整同名 observe→commit 类接口 |
| R07 v2 | 模块明确规则/API/权重/mock/未实现 | 本次补全清单 | capabilities.py、Runtime.state | test_v223.TemplateCloneAudit；权重加载与 trained_steps 分开 |
| R08 v2.1 | HEXACO 24+1 固定 ID | 实现 | registry.py、construct_registry.json | test_v21；UI 聚合不替代底层字段 |
| R09 v2.1 | 精细化 19 价值 | 实现，待研究 | registry.py、deliberation.py | 注册表/范围/冲突轴覆盖；权重与冲突解释未校准 |
| R10 v2.1 | 共 93 字段、未知 null、missing mask | 实现 | registry.py、registry_pmm.py | test_v21；25+19+3+12+12+5+2+15=93；不补造 0.5 |
| R11 v2.1 | registry hash / 顺序 / schema / encoder 锁定 | 实现 | registry.py、packages.py、registry_pmm.py | 包及权重不兼容拒绝，迁移保留旧前缀 |
| R12 v1/v2.1 | 不把聊天推断当正式量表 | 实现标签，待研究 | registry.py、web/app.js | source_type / evidence / uncertainty；没有真人量表效度证明 |
| R13 v2.1 | 实时 VAD、基线和衰减，与稳定人格分层 | 部分 | registry.py、psychology.py、engine.py | VAD 三字段可保存/训练；活动环主要仍是 valence/arousal/stress/engagement，完整 dominance 生命周期未统一 |
| R14 v2.1 | 12 情绪、12 评价、5 调节策略可提取/消费 | 部分 | registry.py、api_pmm.py、registry_pmm.py | 编解码与证据更新有路径；没有完整逐策略执行器或经独立数据验证的全域估计 |
| R15 v2.1 | person×context 的关系和对象模型 | 实现 | relationships.py、engine.py、packages.py | test_v21 / test_v212_cognition；不同群/私聊隔离 |
| R16 v1 | Self、Other、观察与共同经历分离 | 实现核心，待研究 | engine.py、group_attention.py、memory_lifecycle.py | 旁观不增加熟悉度；推断准确性仍依赖模型 |
| R17 v2.1 | 协商 off 仍有完整单路径心理决策 | 实现 | deliberation.py、engine.py | test_v21；关闭不是转为裸 LLM |
| R18 v2.1 | auto 按冲突/不确定性触发 | 实现，待研究 | deliberation.py、cognition.py | 触发记录可查；系数为工程选择 |
| R19 v2.1 | always 不固定三个虚构角色 | 实现 | deliberation.py:views | 已知字段投影；允许只有一个有效视角 |
| R20 v1/v2.1 | 推演回 PMM 复核/补检索，限次数 | 实现，本次修轮数 | engine.py、api_pmm.py | test_v223.RetrievalAudit；重复 query 早停，初次检索预算与协商预算分开 |
| R21 v1/v2.1 | 内部讨论不伪装为真实经历 | 实现 | engine.py、validation.py、execution.py | discussion 留在 Trace；发送后才提交自我行为 |
| R22 v1 | 回答/不知道/拒绝/澄清/沉默分开 | 实现 | policy.py、deliberation.py、validation.py | test_runtime / test_v21 / test_v221；内部枚举另有 disagree |
| R23 v1/v2 | 私密与知识约束不能被投票覆盖 | 实现核心，本次修泄漏 | context_profile、engine.py、policy.py | 跨范围双模型请求断言；输出语义判断仍可能有误 |
| R24 v2 | 原始授权上下文+目标回复蒸馏 | 部分，本次修来源 | psychology.py:parse_records/distill | 保留时间/范围/引用；当前自动上下文主要是同线程前一条，不是完整多轮关系训练集 |
| R25 v2 | Style Encoder / 案例 / Pragmatic Policy | 部分 | psychology.py、registry_pmm.py | 统计向量、案例、15 字段及数值头；非完整语用模型/多候选排序 |
| R26 v2 | 相同来源不重复当独立证据 | 本次修复导入 | psychology.py:parse_records/distill | 明确会话+来源 ID 跨批次稳定；无来源 ID 的旧 TXT 只能按原批次识别 |
| R27 v2 | 真实人类示范与生成自证分开 | 实现核心，本次修范围 | engine.py:feedback、psychology.py | 校正保留来源；AI 自己复述不当新的边界证据 |
| R28 v2 | 同一身份跨模式、连接变更保持连续 | 实现 | packages.py、server.py、subjects.py | test_v2 / test_v21 / test_v212；模型协议改变不清空人格 |
| R29 v2 | 热切换不串会话/任务 | 实现，本次修 UI | server.py:context/switch、web/app.js | 请求捕获 Engine、QQ 路由独立；连接页切换立即刷新 |
| R30 v2 | 延续包、模板、完整备份明确范围 | 实现，本次收紧模板 | packages.py、subjects.py | test_v2 / test_v223；参数可携学习影响，不能称完全匿名 |
| R31 v2 | 克隆新身份，关系与私密不默认继承 | 本次实现 | Runtime.clone_persona、personaForm | 新 ID/新权重/新连接；不改原人格；UI 与 backend 测试 |
| R32 v2 | 检查点、同身份回滚、坏包不部分应用 | 实现 | versions.py、subjects.py、packages.py | test_v2 / test_v221；回滚不重发外部已发消息 |
| R33 v2 | Core 与个体 Adapter 独立 | 实现原型 | learned_pmm.py、registry_pmm.py、versions.py | 真实 NumPy 梯度、冻结核心、独立哈希；无群体预训练 |
| R34 v2.1 | 93 字段缺失标签不参与损失 | 实现 | registry_pmm.py | test_v21；未训练字段预测保持 null |
| R35 v2 | 真实数据划分、独立外部评估 | 部分，待研究 | learned_pmm.py、registry_pmm.py、cognition.py | 有软件层留出；未完成按人物/关系/时间外部划分与心理真值验证 |
| R36 v2 | 训练取消、评估达标后发布 | 待实现完整流程 | versions.py、server.py | 手动训练/保存/切换有路径；不能撤销正在运行的训练或自动性能把关 |
| R37 v2 | LoRA/QLoRA、远程 GPU 编排 | 待实现 | 当前无相应训练器 | 当前 Adapter 是小型 NumPy 网络参数，不是语言模型 LoRA |
| R38 v2 | 固定 Prompt/RAG/API/Learned 公平消融 | 待研究 | docs/PMM_AUDIT_V220.md | 没有真实独立数据结果，不用合成夹具替代 |
| ARCH-01 | 可编辑角色名、自称、种子和初始人格 | 实现 | subjects.py:edit_character | test_v211；不重置状态、关系或历史 |
| ARCH-03 | 每人格 General/PMM/QQ 和预设 | 实现，本次修切换表单 | connections.py、server.py、web/app.js | test_v212；预设应用不默默启用 QQ |
| PERF-01 | 降低实际整轮延迟 | 部分，待实机 | engine.py、consolidation.py、thinking.py | 有减少同步链路和 Thinking 控制；没有真实 P50/P95 增益数据 |
| PERF-02 | 即时状态+持久后台整理 | 实现 | consolidation.py、engine.py | 批次失败保留已发送事实、代次复核；test_v212 / test_v221 |
| TURN-01 | WAIT/REPLY/NO_ACTION、过时生成取消 | 实现核心 | turn_taking.py、qq.py、cognition.py | 片段/版本/发送前复核；Web 不是逐字输入预测 |
| CBM-01 | 增量表达、修复、让轮、话题管理 | 部分 | psychology.py、turn_taking.py | 详细缺口见 VERSION_AUDIT；不能用按标点切分冒充 |
| MULTI-01 M1 | 普通/引用图真实下载与视觉请求 | 实现，待实机 | media.py、provider.py、qq.py | 六协议内联图片、IMAGE_UNAVAILABLE；SnowLuma 现场未测 |
| MULTI-01 M2 | 授权图片/GIF/原生表情发送与回执 | 实现，待实机 | media.py、qq.py、execution.py | 结构消息、素材范围与回执；真实 QQ 未测 |
| MULTI-01 M3 | 人格用图偏好与反馈 | 部分 | media.py:Assets、engine.py | 可选素材、偏好/反馈有路径；语境化审美学习效果未验证 |
| VIDEO-01 | 视频+ASR+时序理解 | 待实现 | media.py 现有仅图片路径 | 不将 GIF 抽帧称为视频理解 |
| SOC-01 | 机会→人格决策→发送→真实反馈 | 部分，本次修配置/再生成 | social.py、execution.py | 有 NO_ACTION 和未回复约束；完整主动 BRM 及自主分享机制不足 |
| GROUP-01 | 群多线程语义解缠 | 部分 | group_attention.py、turn_taking.py | 显式引用/说话人分组不等同语义分线 |
| GROUP-02 | 旁观、陌生人、直接关系分离 | 实现核心 | group_attention.py、relationships.py | test_v212_cognition / test_v220；错解内容仍可发生 |
| MEM-01 | 事件分段、主旨/结论/情绪/来源 | 实现原型 | memory_lifecycle.py、cognition.py | 分段/批次/去重/重新解释测试；摘要真实性需人工核对 |
| MEM-02 | 衰减、提取强化、再巩固、原文不覆盖 | 实现原型，待研究 | memory_lifecycle.py、engine.py、memory_ops.py | 强度是未校准工程参数；原始记录与解释层分开 |
| TRAIT-01 | 跨事件/情境/反例晋升长期特质 | 部分 | registry.py、boundaries.py | 边界有独立证据晋升；全部长期构念尚未统一完成 |
| BOUND-02/BRM-01 | 边界原则、即时激活、表达策略分层 | 实现原型，待研究 | boundaries.py、engine.py、api_pmm.py | API/数值两机制、11 类策略；未建立心理效度 |
| BRM-01 | 手工种子/真实蒸馏/外部权限分离 | 实现 | boundaries.py、execution.py | 支持候选确认/撤销/反例；test_v221 |
| BRM-01 | 主动消息的完整数值边界反馈闭环 | 部分 | social.py、boundaries.py | 本轮仅补硬约束和撤回复核，不能称完整完成 |
| TRUTH-01 | 已说过≠事实、未知≠不愿披露 | 实现核心，实验未启用 | boundaries.py:ClaimMemory、policy.py | 独立 Claim Memory；策略性不实陈述实验未实现 |
| ERROR-01/BUG-01 | 字段级错误及有限结构修复 | 实现 | validation.py、api_pmm.py | test_v221；原始坏 body 缺失，只有同类故障回放 |
| ERROR-01/BUG-02 | 行动冻结、发送前候选校验 | 实现，本次补主动再生成 | validation.py、engine.py、social.py | 最多一次候选再生，不把失败当正常沉默 |
| ERROR-01/BUG-03 | Outbox、回执、未知不重发 | 实现核心，待实机 | execution.py、qq.py、engine.py | 故障注入/恢复/幂等；非跨系统 exactly-once 承诺 |
| OBS-01 | 请求/决策/发送/学习分别诊断 | 实现，本次细分完成错误 | diagnostics.py、execution.py、server.py | 脱敏、字段路径、用量/耗时；真实客户端收信时间未知 |
| UX-01 | 平级导航与减少嵌套 | 实现结构，待视觉验收 | web/index.html、style.css、app.js | 9 个平级页面；结构 DOM 检查无嵌套 form/dialog/details |
| UX-02 | 活动合并、重要故障可见 | 实现 | web/app.js:groupEvents/renderEvents | test_ui_v211 / test_ui_v220；原日志保留 |
| OPS-01 | Windows 双击、错误不闪退 | 实现脚本，待 Windows 实机 | Start_HuaiAn.cmd、launcher.py | 真 CRLF、UTF-8、目录引号；Linux 中文空格路径监督启动通过 |
| OPS-01 | 跨对话可读完整代码 | 实现 | scripts/export_sources.py、review/ | 文件 SHA256 / 索引；其他对话需有文件访问能力 |
| P0-UI-BOOT/H1 | 初始化不依赖未创建 DOM | 本次合并 H1 | web/index.html、test_html_script_order.py | 旧版顺序测试失败；新版通过及 21 场景联调 |
| P0-LOCAL-SESSION | bootstrap、端口 Cookie、重连 | 实现 | server.py:Handler、web/app.js:api | GET 可重连；POST 不重放；test_v222 |
| P0-DATA-CONTINUITY | 找回旧目录、坏库停止、不建空替身 | 实现，待生产库 | data_guard.py、storage.py | 旧数据痕迹/坏身份/孤立历史/坏权重测试 |
| P0-UPGRADE | 先备份、SQLite 一致性快照和前后哈希 | 实现，待生产库 | data_guard.py | 实际旧运行时生成的双人格数据升级；二次启动幂等 |
| P0-HISTORY | 全会话列表和超过 2000 条分页 | 实现 | storage.py、web/app.js | 44 会话/2010 条消息联调 |
| DELETE | 删除原话与派生学习及自动副本 | 本次补升级副本 | erasure.py | 默认/非默认人格副本互不删除；预览说明更广影响 |
| THINKING | General/PMM 分别控制且不泄露思考正文 | 实现，本次修多协议 | thinking.py、provider.py、diagnostics.py | test_v211 / test_v223；自定义网关需明确适配或 default |
| FUTURE | Activation Steering | 待实现 | 无隐藏状态干预器 | 与 API 条件提示区分，不能提前宣称 |

结论以“结果”列为准。实现状态不随说明文件中的愿景自动升级；缺口继续进入 NEXT_STEPS.md 与问题台账。
