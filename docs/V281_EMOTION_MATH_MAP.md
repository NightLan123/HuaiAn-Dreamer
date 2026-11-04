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

