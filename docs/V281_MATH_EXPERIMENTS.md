# 槐安梦客 2.8.1：公式、代码和固定条件实验

保留原人格公式 P-A—P-E；本次在正式 P-A 输入增加 5 个快情绪轴、3 个慢心境轴及 8 个有效掩码。P-B 的行动候选仍经过独立模型与证据门槛。旧权重缺少新投影时保持原预测。

| 公式 | 最终源码位置 | 实际计算 |
|---|---|---|
| E-A | `persona/affect_response.py` → `parameters`，第 68–72 行 | 带缺失掩码的 H/D → 8 个基线、每秒恢复率、扩散尺度；κ/σ 通过 softplus。 |
| E-B | `persona/affect_dynamics_v2.py` → `ou_moments`，第 47–53 行 | 潜变量 OU 精确区间均值与方差，expm1 和 κ→0 极限；展示时做 Link。 |
| E-C | `persona/affect_dynamics_v2.py` → `propagate`，第 94–116 行 | 真实秒数与轮次分别记录；轮次独立项默认 0，非零需显式验证。 |
| E-D | `persona/affect_response.py` → `response`，第 87–92 行 | q、H/V/D、关系、慢心境和冲击前情绪 → 一次潜变量加法冲击。无评价只推进时间。 |
| E-E | `persona/affect_dynamics_v2.py` → `coupled_moments`，第 69–92 行 | 三个快慢耦合二维 OU 块的均值与协方差，另两个快轴独立；冲击只在区间末施加。 |
| E-F | `persona/affect_response.py` → `label_readout`，第 78–85 行 | 24 个独立 sigmoid 读取当前 h、评价与情绪；未校准的标签对外为 null。 |
| E-G | `persona/affect_regulation.py` → `choose`，第 10–28 行 | softmax 策略抽样；重评核验事实不变，抑制仅进入 expression 控制外显强度。 |

慢心境不会直接接收事件跳变，快慢状态收敛尺度不同。参数和策略都是待估计对象。E-F 在本轮人格网络输出 h 后重读标签头；不会因此再次推进 OU 或施加冲击。

| 支持环节 | 最终实现 |
|---|---|
| `seconds` | `persona/affect_dynamics_v2.py`，第 15–23 行 |
| `link` | `persona/affect_dynamics_v2.py`，第 27–30 行 |
| `inverse` | `persona/affect_dynamics_v2.py`，第 32–45 行 |
| `initial_model` | `persona/affect_response.py`，第 23–38 行 |
| `appraisal_packet` | `persona/affect_response.py`，第 60–66 行 |
| `jump_inputs` | `persona/affect_response.py`，第 74–76 行 |
| `expression` | `persona/affect_regulation.py`，第 30–37 行 |
| `migrate` | `persona/affect_runtime.py`，第 14–25 行 |
| `draft` | `persona/affect_runtime.py`，第 90–126 行 |
| `commit` | `persona/affect_runtime.py`，第 128–132 行 |
| `current_view` | `persona/affect_runtime.py`，第 134–142 行 |
| `archive_view` | `persona/affect_runtime.py`，第 166–174 行 |
| `validate_dataset` | `persona/affect_training.py`，第 16–46 行 |
| `torch_prediction` | `persona/affect_training.py`，第 81–113 行 |
| `train` | `persona/affect_training.py`，第 115–147 行 |
| `calibrate` | `persona/affect_training.py`，第 183–202 行 |
| `release_gate` | `persona/affect_training.py`，第 149–181 行 |
| `publish` | `persona/affect_training.py`，第 204–209 行 |
| `run_full` | `persona/pmm_coordinator.py`，第 145–197 行 |
| `runtime_inputs` | `persona/trait_dynamics.py`，第 215–231 行 |
| `connection` | `persona/pmm_connections.py`，第 8–14 行 |
| `probe` | `persona/pmm_connections.py`，第 30–64 行 |
| `preview` | `persona/pmm_workspace.py`，第 35–58 行 |

## 七个受控回合

每个条件从同一个隔离的 SQLite 快照开始，使用同一数值权重、同一事件、相同初始 RNG（281）。两个人格条件只改变已知 HEXACO 输入（0.2 / 0.8）。B 采用固定的测试服务，按收到的情绪和心境生成效用；General 使用确定性响应。由正式 Engine 执行计算、行动选择和事务。

| 人格条件 | 秒数 | 干预 | 快效价 | 慢效价 | 回复评分 | 表达强度 | 最终行动 |
|---|---:|---|---:|---:|---:|---:|---|
| persona_low | 60 | 无额外干预 | 0.5102 | 0.1971 | 0.7592 | 0.3502 | reply |
| persona_low | 86400 | 无额外干预 | -0.1712 | 0.1233 | 0.6156 | 0.2418 | reply |
| persona_high | 60 | 无额外干预 | 0.5102 | 0.1971 | 0.7592 | 0.3502 | reply |
| persona_high | 86400 | 无额外干预 | -0.1712 | 0.1233 | 0.6156 | 0.2418 | reply |
| persona_low | 60 | fast_intervention | -0.6780 | 0.1967 | 0.5216 | 0.3502 | reply |
| persona_low | 60 | suppression | 0.5102 | 0.1971 | 0.7592 | 0.1226 | reply |
| persona_low | 60 | none | 0.5102 | 0.1971 | 0.7592 | 0.3502 | reply |

相同 60 秒与事件下，两个人格条件的神经状态向量确有差异（L2 = 0.133514）。初始化的人格→情绪参数系数为零，所以两个条件的快慢效价相同；没有把工程初值写成发现的人格规律。仅改变初始快情绪，候选回复评分从 0.7592 变为 0.5216；在这七个条件下，最终行动均为回复。抑制与不调节的快情绪相同，表达强度不同。

原始向量、评分与完整组件记录位于 `reports/v281/stage4/final/controlled_experiment.json` 和 `component_trace.json`。复现：`python scripts/evaluate_affect_v281.py`。以上是路径和数学作用的工程证据，不是已证实人类心理因果效应。
