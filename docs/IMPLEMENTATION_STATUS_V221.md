# 2.2.1 实施状态与源码定位

日期：2026-10-27（Asia/Shanghai）。依据 `ERROR_BRM_REQUIREMENTS_2026-10-27.md`。`已实现 / 本地验证` 与 `已实机验证 / 心理效度成立` 不等价。本目录没有建立 Git 提交；定位依据完整源码索引中的文件路径、源码行区间和 SHA256，不虚构 commit。

| 需求 | 实际实现与关键符号 | 本地验证 | 剩余事项 |
|---|---|---|---|
| ERROR-A1 旧故障证据 | `FAILURE_EVIDENCE_REDACTED.json`；`scripts/replay_error01.py` | 25 字符候选不符、Phase 3 缺效用的同类故障回放 | 原始坏 HTTP body 缺失，原故障根因不能精确归因 |
| ERROR-A2 分层 Trace | `execution.py: public_trace/safe_call/metrics`；`engine.py: turn/_turn`；`cognition.py`；`provider.py` | 请求标识、阶段耗时、字段路径、默认脱敏、JSONL 和 HTTP 路由 | 无真实 QQ 首次回执 P50/P95；客户端收信时刻未知 |
| ERROR-A3 结构合约 | `validation.py: assessment/preparation/validated_call`；`api_pmm.py: prepare` | 单/多路径、缺失/null/NaN/布尔、错枚举、重复 ID、最多一次修复 | 各真实服务输出分布下的修复率与成本 |
| ERROR-A4 冻结与候选 | `validation.py: candidate_check`；`engine.py: _turn`；`social.py: evaluate` | ID/revision/action 匹配、逐字证据位置、一次重生、零幽灵记忆 | 真实语义检查器的误判率 |
| ERROR-A4 发送一致性 | `execution.py: prepare/dispatch/acknowledge`；`qq.py: process/retry_failed` | 实际发出后超时、async、无 ID、回执后提交崩溃、重启、旧备份去重；主动路径同测 | 实机回执、网络故障及目标字段兼容性 |
| ERROR-A4 后台学习 | `engine.py: commit_plan/commit_social/recover_delivered`；`consolidation.py` | 已发送仍已发送，失败只重试学习；提交恢复幂等 | 真实大规模队列、断电与硬盘故障 |
| ERROR-A4 状态分离 | `turn_taking.py`；`qq.py`；`execution.py` | WAIT 不强制回复，校验失败不伪装沉默，REFUSE 与故障分离 | 实际对话适切性 |
| BRM-B1/B2 模型/来源 | `boundaries.py: Boundaries.context/estimate/policy/edit` | 软种子/候选/外部硬约束分开；Other/Self/Relationship 隔离 | 多样真实对象与跨情境数据 |
| BRM-B3 API 实现 | `boundaries.py: api_appraisal`；`api_pmm.py: prepare` | 真实调用路径接入和完整 schema；既有请求合并边界评估 | 测试服务提供响应，尚未真实云端验收 |
| BRM-B3 数值实现 | `boundaries.py: BoundaryHead/features/calibrate/evaluation` | 16×12 独立权重、masked BCE、梯度、事件留出集、消融；防激活输出自我泄漏 | 冷启动工程先验；真实标注 0，未校准；行为精度/心理效度未知 |
| BRM-B4 形成/反例 | `boundaries.py: absorb/import_candidates`；`consolidation.py` | 授权 Self 导入、实际对方反馈、独立事件去重、反例、候选/撤销/版本、主人种子不被覆盖 | 跨人/跨日期/话题的统计标准仍为保守工程规则，未标定 |
| BRM-B5 历史陈述 | `boundaries.py: ClaimMemory` | 已说过与事实分开，纠正引用需存在，按情境隔离，不从生成文本强化边界 | 没有启用策略性欺瞒实验；陈述提取受模型质量影响 |
| BRM-B6 动态协商 | `deliberation.py`；`engine.py` | 保留同一人格动态候选及 off/auto/always；边界在既有调用链内 | 额外候选检查带来的真实延迟与收益需测量 |
| BRM-B7 UI | `web/index.html/app.js/style.css`；`server.py` | 同级入口、可编辑状态、证据/反例/变化史、实际校准、执行状态、DOM 与 HTTP 路由 | 无浏览器视觉验收，仍需不同分辨率下的人工体验 |
| BRM-B7 主动联系 | `social.py: evaluate` | 边界上下文、Claim Memory、撤回许可、候选检查、可靠发送 | 尚未接入与入站回复相同的独立数值激活/慢学习闭环 |
| 迁移/回滚 | `packages.py`；`subjects.py`；`server.py`；`execution.py: merge_snapshot/erase` | 新旧包、非法导入拒绝、权重/证据延续、导入发送计划隔离、恢复不盲发 | 原生 Windows 与真实长期数据库需备份后验收 |

## 数值边界机制的可核查范围

`BoundaryHead` 是独立线性 sigmoid 头，不冒充已训练的大型心理模型。激活头与 11 个行为效用头分离；动作仍必须经过允许集合和硬性门控。在线校准按 turn ID 的 SHA256 固定分出约 20% 留出事件，同一事件不能重复训练；其余数值标签执行 16 步 SGD。API 模式标注仅作为同情境的可追溯示例，不声称训练了 API 服务商的参数。

`BOUNDARY_FIXTURE_V221.json` 给出 12 个关系×情绪×种子条件和“只提到、未请求”的控制项。语义线索是测试输入，不能据此计算真实语言识别精度。当前真实人工标注数量为 0；固定关键词、API-PMM、Learned-PMM 的触发精度、误拒绝、适切性、心理一致性及端到端延迟对比均未完成。

## 发送与权限的边界

数据库与 QQ 不存在一个共同事务。本实现选择在结果不明时停止重发，可能需要人工核对而牺牲自动可用性；不是端到端 exactly-once 保证。`get_msg` 只有同时验证 bot、目标、完整消息与 ID 才能解除未知。OneBot 11 标准查询回执不保证包含目标字段，缺失时继续保留未知，不能自动把它当成功或失败。

恢复或擦除不能撤回已发到 QQ 的消息。擦除会删除本地私密内容，但保留不含原文的去重墓碑与撤回许可，以防旧备份重新触发联系。恢复旧备份可能保守保留已撤回权限；重新授权必须来自实际收件人的新入站消息。
