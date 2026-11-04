# 2.8 数学、理论约束与代码映射

本文对应最终交付的 2.8 源码。行号是单个源文件中的起始行；源码汇编中的位置另见 `review/HuaiAn_Dreamer_Code_Index.md`。公式完整定义保存在唯一规格 [V28_SPEC.md](V28_SPEC.md)。

## 理论定位

| 规格书中的理论 | 本实现采用的结构约束 | 不能据此推论 |
|---|---|---|
| CAPS | 情境 q 与人格构念的乘性交互影响当前 h | 任意神经连接已被证明为心理因果 |
| Whole Trait Theory | 稳定构念、当前反应及独立状态测量分开 | 单轮生成回复就是稳定人格真值 |
| TESSERA | 独立重复经历、分时反应及前后测可形成长期候选 | 每条消息必须固定改变人格数值 |
| LST-R / 自回归扩展 | 稳定潜变量、时变状态、过程/测量误差和时间结构分别表示 | 当前模型已通过测量等值或长期外部验证 |

这是依规格书实施的可检验工程假设；本轮没有把理论名称用作参数大小的实证依据。

## 维度与尺度

`d_h=16, d_q=11, d_r=8, d_m=6, d_affect=8, rank=4`。各块 `d_b` 为原构念数量：25/19/2/15/7。A 由 Rank4 加对角项组成；W/C/U 按块低秩；个人 Adapter 为独立所属主体的 Rank4 递归项。Lambda_H 取可训练对角形式，状态头不与行动头混用。

H 六领域继续由 25 面向分层汇总，不新增六个独立维度。V 的相对优先级仅减去已知项均值；未知项仍 null/mask0。学习的缺失嵌入不是观测估值。长期 D 使用独立注册结构，不能用即时情绪替代。

B 的 eta 以显式过程协方差报告，不逐轮采样一个随机“人格变化”。未标定模型的数值只是 engineering_latent；初始过程协方差也是工程占位。通过独立尺度拟合后才允许已标定面向的真实状态训练。行动验证和量表标定是不同门禁。

## 公式与实现

| 项目 | 代码位置 | 实现要点 |
|---|---|---|
| 长期构念和未知掩码 | `persona/pmm_contracts.py:90` · `construct_blocks` | H25/V19/I2/L15/D7；读取原注册表，不补造观测值 |
| A：构念编码 | `persona/trait_dynamics.py:112` · `pack_blocks` | 按面向身份编码，价值仅对已知项中心化 |
| A/B：共用代数 | `persona/trait_dynamics.py:129` · `algebra` | A低秩+对角；W/C/U按块低秩；个人Adapter；状态和行动分头 |
| B：测量尺度 | `persona/trait_dynamics.py:89` · `bind_measurement_scale` | 只绑定独立有效协议及已标定面向mask |
| B：NumPy前向 | `persona/trait_dynamics.py:170` · `TraitDynamics.forward` | 输出预测、构念路径、掩码与误差语义，绝不生成观测 |
| A/B：可训练同构 | `persona/trait_dynamics.py:185` · `torch_model` | 同一参数名和算式，float64自动微分 |
| C：结构软约束 | `persona/pmm_trainer.py:101` · `structural_loss` | 分块ridge与相邻价值环平滑；强度可为0 |
| C：监督损失 | `persona/pmm_trainer.py:118` · `masked_loss` | 除以有效mask×weight之和 |
| C：梯度训练 | `persona/pmm_trainer.py:149` · `fit` | 真实SGD；验证集选lambda/温度，测试集不选参数 |
| D：分时状态 | `persona/trait_estimator.py:109` · `adjusted_state_summary` | 独立观测减独立情境预期，含测量/情境与事件间误差 |
| D：均值及协方差预测 | `persona/trait_estimator.py:44` · `predict` | G未验证即零；明确Q及相关误差交叉项 |
| D：G拟合 | `persona/pmm_trainer.py:237` · `fit_transition` | 独立前后测，对角ridge，留出对比持久基线 |
| D：服务端观测派生 | `persona/pmm_longitudinal.py:37` · `transition_rows` | 从原始分时状态重算zeta，不信任上传神经预测偏移 |
| E：高斯更新 | `persona/trait_estimator.py:64` · `linear_gaussian` | Cholesky检查、solve与Joseph式；缺失观察不更新 |
| E：序数近似 | `persona/trait_estimator.py:83` · `ordinal_logit` | ordinal-logit似然+Gauss–Hermite/ADF |
| 尺度与情境标定 | `persona/trait_estimator.py:189` · `fit_measurement_scale` | 独立主体/时间切分，分开测量残差和情境残差 |
| D/E：候选 | `persona/trait_estimator.py:147` · `LongTermEstimator.estimate` | 有前提才计算；保持candidate_only，缺证据not_ready |
| 正式提交 | `persona/pmm_longitudinal.py:82` · `action` | 活跃证据重算、重复事件阻断、CAS与原事务 |
| 原人格写回 | `persona/traits.py:12` · `apply_pmm28_proposal` | 尺度逆变换、范围检查、完整前后状态/证据 |
| 同轮接入 | `persona/pmm_coordinator.py:145` · `PMMCoordinator.run` | 统一turn/event/scope；独立API与实际网络 |
| 决策门禁 | `persona/pmm_coordinator.py:105` · `CoordinatedDecision.decide` | 未校准零贡献；分歧记录及澄清，不平均模型 |
| 正式政策 | `persona/policy.py:17` · `choose` | 在原边界之前增加条件，继续执行硬约束 |

## 复算例与近似边界

D 的手算输入 `mu=.4, P=.1, zeta=.2, Omega=.04, G=.5, Q=.01` 输出 `mu_prior=.5, P_prior=.12`；无验证时关闭 G，不使用此人工系数获得发布资格。

E 的手算输入 `mu=.4, P=.2, y=.8, H=1, R=.1` 输出 `K=2/3, mu_post=2/3, P_post=1/15`。实现使用稳定求解而不是显式逆矩阵。对非正定创新矩阵或条件数超过 1e12 明确拒绝，不用任意 jitter 隐藏无效输入；PSD 的微小舍入误差单独处理。

纵向情境调整先由独立标定的 context 模型得到参考值，再计算 observed−context；绝不以当前神经预测减去现有人格来生成监督。Omega 包含测量误差、情境误差及事件间异质性。F=I、b=0 是初始限制；G 为独立前后测拟合的对角 ridge，未通过验证恒禁用。其他构念的长期变化仍须独立协议。

序数后验通过64点Gauss–Hermite计算倾斜矩，再用高斯ADF传播；近似类型和积分点数明确写入结果。测试比对数值、梯度、缺失、病态、精度变化、重复事件及作用范围。它们证明实现层面的可复算性，不证明心理学解释。

具体演示输出见 `examples/v28_demo/`，验收见 [V28_TEST_REPORT.md](V28_TEST_REPORT.md)，当前研究边界见 [V28_LIMITS.md](V28_LIMITS.md)。
