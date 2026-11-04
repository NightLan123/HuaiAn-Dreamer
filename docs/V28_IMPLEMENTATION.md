# 槐安梦客 2.8：实现与适配记录

本版本的唯一开发依据为 [V28_SPEC.md](V28_SPEC.md)。以完整 2.7 为基底，执行第 0–VI 阶段；交付可运行的研究原型。没有读取其他对话补充或替换需求。

## 1. 实际运行路径

General LLM 负责输入理解和语言输出。PMM 内部通过 `PMMCoordinator` 串联原有范围内记忆、独立 API 心理推理、原情绪与关系计算、新人格反应网络及行动协调。新评分项进入原 `policy.choose()`，之后继续执行知识、身份、隐私与行动硬边界。发送、回执、部分发送和提交继续使用现有 Engine / ExecutionJournal / Outbox。

默认 `shadow + candidate_only`。Legacy 保留 2.7 正式决策；Shadow 在同一回合实际计算新网络、记录比较，不增加回复。Active 只有合格模型才贡献神经评分；否则明确记录降级。正常回合不自动训练，也不从生成回复制造长期人格真值。

## 2. 逐阶段改动

| 阶段 | 主要源码 | 实现与验收入口 |
|---|---|---|
| 0 | 完整 2.7 归档、351 个文件摘要 | 重新执行原 580 项 Python、107 项 HTTP/结构 DOM 基线；实际旧版运行、已训练双主体迁移；`reports/v28/stage0/` |
| I | `pmm_contracts.py`、`pmm_coordinator.py`、`engine.py`、`common.py` | 八类端口、统一来源及版本、同轮 API/数值双路径、独立 Shadow Trace；`test_v28_stage1.py` |
| II | `trait_dynamics.py`、`registry_pmm.py` | 公式 A/B、五块 68 项长期构念、未知掩码、低秩共享核心与个人 Adapter、NumPy/Torch 同构、手算与梯度检查；`test_v28_stage2.py` |
| III | `trait_estimator.py` | 公式 D/E、独立分时观测、G 禁用、协方差与病态检查、Joseph 更新、序数量表近似；`test_v28_stage3.py` |
| IV | `pmm_trainer.py`、`evidence.py`、`packages.py`、`storage.py` | 真实 SGD、主体及时间隔离、标签任务审核、不可变候选、冻结/发布/撤销/回滚、重启与续训；`test_v28_stage4.py` |
| V | `engine.py`、`api_pmm.py`、`policy.py`、`pmm_experiments.py`、`pmm_longitudinal.py`、现有前后端 | Active 贡献、共享 API 期限、各阶段失败回退、六项消融、长期 CAS 提交、量表绑定、诊断与训练界面；`test_v28_stage5.py`、`test_v28_longitudinal.py`、`test_v28_calibration.py`、`test_ui_v28.js` |
| VI | 回归与迁移脚本、示例、说明、导出器 | 跨主体/范围、并发、重启、来源撤回、回退、CLI 进程锁；`test_v28_stage6.py`、`upgrade_v28.py`、`run_v28_regression.py`、`scripts/demo_v28.py` |

阶段实际测试命令、日志、通过数量与发现的问题见 [V28_TEST_REPORT.md](V28_TEST_REPORT.md) 及各阶段 `REPORT.md`。同一场景被多轮复测时不累加成独立测试数量。

## 3. 对实际 2.7 契约的适配

1. 原数据使用 `value.*` 表示 19 项价值，不能改成不存在的 `schwartz.*`。五块按注册表的实际顺序读取；原 93 字段、370 维 Legacy 输入均保留。7 项 BEQ/ERQ/PANAS 仍从现有独立长期倾向结构读取。
2. 原运行接口 `decode_conditions()` 是 `_turn()` 内的闭包。本轮在闭包之后接入 Coordinator。API 基线已完成且有当前事件引文的结果作为同轮缓存使用，Trace 明示额外请求数；数值基线则另外请求独立 PMM 接口。
3. 部分历史 API 模式仍保存 184 维权重。内部 API 失败时经 `RegistryPMM` 桥接新输入，禁止直接把 370 维送入 184 维网络；降级输出不使用随机影响权重驱动决定。
4. 原输入幂等契约是 `turn_context.sources`，Journal 才将其记为 `input_event_ids`。继续沿用原契约，不引入另一个重复事件索引。
5. 新版本状态存放在原主体 SQLite 的 `pmm28_models`、`pmm28_samples`、`pmm28_estimator` 元数据；它们保存新参数和审计，稳定人格仍写原 `pmm_profile`，情绪仍写原 `pmm_affect`，关系与记忆使用原结构。
6. 原 continuity 包保持 `persona-package/2.3`，仅增加可选 `pmm28` 区块。导入时检查主体、构念顺序、数值、摘要及数据引用。旧包没有此区块仍可导入。
7. `legacy` 与 `shadow` 保留旧晋升行为；`active` 阻止旧工程晋升规则自动写入稳定人格，但继续收集候选。主人明确编辑设定仍是原有独立操作，并被标为 `owner_seed`。
8. 真实状态训练需要独立尺度。新增 `bind_scale` 将可重新核验的测量协议绑定到候选网络，使用逐面向标定掩码。只标定一个 HEXACO 面向时，其余 24 项不能接收真实状态标签。绑定、训练、发布分开。
9. CLI 训练与 UI 训练调用同一 Coordinator。CLI 获取原数据目录进程锁；程序运行时应使用后台训练入口，避免另一个 Runtime 抢先执行恢复逻辑。

## 4. 模型与证据纪律

核心训练禁用个人 Adapter 并按主体与时间双隔离。个人 Adapter 只读取本主体许可数据、冻结核心，使用主体内未来窗口验证，并要求父核心已有独立发布验证。测试集不参与正则或温度选择。

公式 C 使用状态平方损失与行动交叉熵的有效掩码加权平均。结构项含分块 ridge 和相邻价值环形参数平滑的软假设，强度在含零的验证候选中选择；没有把相邻价值的行为效应强制设成相等。该假设仍需要实证检验。

发布重新计算行为指标、核查父版本及原文是否仍有效。冻结并不授予发布资格。样本撤回后，默认训练只选择未撤回行；显式请求撤回标签会拒绝。依赖无效来源的已发布模型在下一轮门禁检查中失去正式使用资格，原权重留作审计。这不是机器遗忘算法。

长期路径分别进行尺度/情境标定、独立前后测的 G 训练、分时状态汇总与后验候选。正式提交还检查 active、validated_commit、真实有效资料、独立后测、状态时间跨度、已验证 G、人格版本 CAS 和已消费事件。一个事务写入原人格、完整前后状态和来源历史。下一轮直接从这些原人格字段读取新值。

## 5. 界面与演示

保留十个主页面。在「模型设置 → PMM」选择运行模式和长期更新权限，General 与 PMM 独立接口继续使用原配置与 Thinking 适配。在「后台诊断记录 → 2.8 协同 PMM」查看组件、已知构念数量条与数值、正式评分采用、Trace 导出、六项消融、标签审核、训练、测量绑定及版本操作。

`python scripts/demo_v28.py` 实际运行八类工程场景，输出到 `examples/v28_demo/`。所有 API 传输、输入、测量与标签均明确标为合成夹具；数值前向、梯度训练、SQLite、证据审核和回退代码实际执行。附带候选不能发布为正式模型。

## 6. 当前边界

公式、数据管线和事务的可复算性已经有工程检查。真实 Qwen、QQ、Windows、用户生产资料和长期心理学效度没有被这些测试替代。完整边界和未完成的外部验收列于 [V28_LIMITS.md](V28_LIMITS.md)。
