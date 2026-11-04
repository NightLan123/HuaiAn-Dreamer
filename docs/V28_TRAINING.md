# 2.8 训练、测量与发布操作

## 1. 安装与入口

正常对话和 NumPy 前向不依赖 PyTorch。新网络训练才需要 `requirements-learning.txt`。在程序目录安装到启动器使用的同一个环境：

```bat
.venv\Scripts\python.exe -m pip install -r requirements-learning.txt
```

Linux/macOS 对应 `.venv/bin/python -m pip install -r requirements-learning.txt`。本次实际测试用 Python 3.12.14、NumPy 2.3.5、torch 2.15.0+cpu。其他安装组合须另行检查。

打开「后台诊断记录 → 2.8 协同 PMM」。先登记已审核标签，再上传主体/时间切分方案，选择共享核心或个人 Adapter，训练新的候选。训练完成后会显示版本和指标，已发布权重不会被覆盖。仅行动标签可以在工程潜在尺度上训练；真实状态标签需要先绑定独立测量协议。

## 2. 标签数据契约

上传对象可以是 `{"samples":[...]}`。每行需要：

| 字段 | 约束 |
|---|---|
| `schema` | `pmm-supervision/2.8` |
| `owner_id` | 当前 AI 主体 ID，表示谁持有此数据与模型 |
| `subject_id` | 实际受测/作出选择的主体 ID；与持有者分开 |
| `scope`、`event_id`、`timestamp` | 授权范围、独立事件、原始 Unix 秒；同一来源不可伪造新事件重复贡献 |
| `protocol_id`、`reviewer`、`reviewed` | 可解释的测量/评价协议及审核记录；`reviewed=true` |
| `source_kind` | `independent_questionnaire`、`independent_observer`、`human_choice`、`verified_outcome`；测试使用 `controlled_fixture` |
| `engineering_fixture` | 必须显式布尔值；合成资料必须为 `true`，不可取消此标记获取发布资格 |
| `permissions` | `parameter_training=true`，范围包含当前 `scope`；核心要求 `shared_core=true`，个人训练要求 `personal_adapter=true` |
| `task`、`labels` | `action_choice`：六类行动之一；`state_reaction`：25 项状态数组，缺失用 `null`，另需 `scale_id` |
| `weight` | 0.001–100 的有限正数；它是监督权重，不是人格变化量 |
| `inputs` | 当前反应的完整构念块、q/r/m/affect/h_prev；不得包含该目标标签或事后答案 |
| `evidence_refs`、`quotes` | 对应现有统一来源索引的键和逐字引文；必须仍有效 |

首轮导入可附 `record` 和 `quote`，由服务器在原来源索引登记：`record` 含 `id,event_id,text,speaker,scope,source,timestamp,measurement_subject_id`，且主体、时间和范围必须与标签一致。导入后服务器生成规范的事件键与来源键；不可凭空填一个看似有效的 evidence ID。

`record.source` 沿用原始资料类型 `human / observed / imported`；`source_kind` 说明测量方法。合成测试记录即使通过 imported 载入，仍必须标 `engineering_fixture=true`，原文应明确注明合成资料。

五个块固定为 H25、V19、I2、L15、D7，每块都有 `ids,values,mask,uncertainty,sources`。未知值为 `null`、mask 为 0，不确定性保持未知。其余输入维度：q11、r8、m6、affect8、h_prev16。当前 q 是有来源的内部 API 评价与行动先验编码，不是通用文本嵌入。完整机器样例见 `examples/v28_demo/training_dataset.json`，其原主体 ID 和来源只属于临时演示库，不能原样导入你的真实主体。

静态人格问卷、当前状态测量、行动选择/后果、长期前后测是不同任务。静态人格/长期标签不能送进 `action_choice`，旧规则晋升、生成回复、模型自评、未经核验的 API 推断不能当长期真值。

## 3. 切分、真实训练与恢复

切分文件结构：

```json
{
  "train": {"subjects": ["P01", "P02"], "start": 1700000000, "end": 1701000000},
  "validation": {"subjects": ["P03", "P04"], "start": 1702000000, "end": 1703000000},
  "test": {"subjects": ["P05", "P06"], "start": 1704000000, "end": 1705000000}
}
```

这些是格式例子，不是可用研究数据。核心的主体集合和时间窗口必须互不重叠，每条记录恰好落入一个分区。个人 Adapter 的三个窗口使用同一个所属主体，允许主体内未来验证，但不能声称跨主体验证；正式发布还要求经过发布验证的父核心。

使用 float64、完整批次 SGD、梯度范数裁剪 5、无 momentum。保存 JSON 参数、训练步数、父版本、数据摘要及报告；2+2 步恢复与连续 4 步在测试中比较参数一致性。正则强度与行动温度只由 validation 选择；test 在选定后评估，不参与拟合或调参。

在 UI 选择一个候选版本再训练，就是从该版本续训。核心训练冻结/清零个人 Adapter；Adapter 训练冻结共享核心。每次仍写新版本，旧参数保留。

关闭正在使用同一数据目录的程序后，也可独立调用：

```text
python scripts/train_pmm28.py --data-dir "原数据目录" --subject-id "现有主体ID" --split-plan split_plan.json --target core --epochs 20 --output candidate-export
```

CLI 读取已有审核数据，获取原运行进程锁，调用相同 Coordinator，把候选及审计写入现有目录并导出 JSON；不会自动发布。续训增加 `--parent-version SHA256`。程序正在运行时，使用 UI 的后台训练入口即可。

## 4. 发布规则

候选需要先冻结，再点击「验证并发布」。后端重新核查 Checkpoint/报告/数据摘要、独立来源、父版本、主体/时间切分、参数与指标可复算性。当前工程门槛要求 validation/test 分别至少 24 条行动标签、至少两类行动；共享核心分别至少两个主体；准确率超过多数类基线且不低于 0.5，五箱 ECE 不大于 0.2，损失不劣于父模型。它们是明确的工程门槛，并非心理学效度标准，也不足以替代预注册研究或置信区间分析。

合成数据一律不能发布。附件中的单一行动合成训练即使达到 100% 夹具准确率，也没有超过多数类基线，仍被拒绝。只训练状态头的模型也不能跳过行为发布验证去直接控制对话。

撤销会停用对应版本；回退只允许曾经发布且目前仍通过来源/校准检查的版本。来源撤回会阻止后续训练、发布及依赖它的长期提交。已有权重保存为不可变审计材料，不承诺机器遗忘；需要重新训练新的有效版本。

## 5. 测量尺度与长期变化

纵向请求 JSON 经「长期人格候选与测量标定 → 审核并计算」提交：

1. `calibrate_scale`：输入具原文引用的独立配对 `canonical / latent / context / state` 数据、HEXACO 构念 ID 和主体/时间切分。服务端拟合尺度斜率、截距、测量残差、情境预期及情境误差。
2. 若要训练真实神经状态头，选择这一协议并点击「核验并绑定至候选网络」。后端重新计算协议；仅已标定面向可作为状态标签。绑定本身不训练或发布网络。
3. `train_transition`：提供独立前后测和两者之间分时状态观测，跨度至少 24 小时。服务器由观测和独立情境模型重新计算 zeta，忽略任意上传的神经偏移建议；用隔离窗口拟合对角 ridge G，并比较持久不变基线。无有效验证则 G 禁用。
4. `estimate`：给定当前主体与范围的原始基线测量、分时状态及独立后测，输出公式 D/E 的候选均值、协方差、来源与版本。它不改变正式人格。
5. `commit`：仅 `active + validated_commit`，且尺度与 G 均可从仍有效的真实资料重新验证时允许。还检查独立事件未消费、来源角色不重叠、人格版本及完整摘要未变化。任何不满足均保留原状态并返回原因。

完整请求形状与受控运算实例见 `examples/v28_demo/longitudinal_audit.json`。其中所有测量是合成资料，G 标为未验证，后验只作候选；不能据此声称完成真实长期人格学习。非 HEXACO 构念仍参与每轮反应，其长期变化须各自建立合格的测量/转移接口，不能套用 HEXACO 参数。

序数观测使用 ordinal-logit 似然、Gauss–Hermite 积分和 ADF 矩近似；线性高斯观测使用 Joseph 形式。误差很大、矩阵病态、尺度不一致或来源不足会明确拒绝，不进行任意截断来强行提交。

## 6. 接口一览

以下接口全部沿用本地会话鉴权与 CSRF；请求中的 `subject_id` 必须匹配当前主体，修改带 `expected_revision`。

| 路由 | 功能 |
|---|---|
| GET `/api/pmm28/status` | 模式、构念契约、样本摘要、模型与门禁 |
| GET `/api/pmm28/traces` | 最近已提交回合，可按 scope 筛选 |
| POST `/api/pmm28/samples` | 登记已审核标签、撤回事件标签 |
| POST `/api/pmm28/models` | train / bind_scale / freeze / publish / revoke / rollback |
| GET/POST `/api/pmm28/longitudinal` | 读取目录、标定、训练 G、候选、提交、撤回来源 |
| POST `/api/pmm28/ablation` | 原回合、原 Checkpoint 的固定输入六项消融 |

Trace 与资料导出包含研究输入和来源，应按原授权范围使用。诊断界面由本地所有者查看，不会自动把全部后台资料送入 General LLM。
