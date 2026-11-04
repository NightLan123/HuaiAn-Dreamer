# 槐安梦客 PMM：人格与情绪计算的理论依据、数学公式及程序实现规范

**版本：** Research/Implementation Reference v1.0  
**整理日期：** 2026-11-03  
**用途：** 可独立上传至其他开发对话的、无需引用历史聊天即可理解的研究与算法规范。  
**依据：** 已核对的心理学原始研究；《槐安梦客》2.8源码（包括 `persona/trait_dynamics.py`、`persona/trait_estimator.py`、`persona/affect.py`、`persona/pmm_coordinator.py` 等）。  
**范围：** 人格动态（Personality Dynamics）、短期情绪与心境（Affect/Mood Dynamics）、两者的耦合、训练与验证。不等于整套PMM项目规格书。  
**重要提醒：** 本文公式分为已有理论支持的模型类别、为槐安梦客提出的可检验实现、纯工程约束三种；绝不能声称这些组合公式已经由某一篇心理学文献直接证明。

---

## 0. 使用本文件前必须理解的四点

1. **PMM独立于General LLM。** General LLM面向用户接收、生成最终语言；PMM是内部心理计算与决策增强系统，包含内部Qwen/API心理推理、Learned神经计算、长期心理构念、情绪、关系、记忆、决策、证据与学习组件。General LLM不是PMM内部子层。
2. **数学公式与神经网络并不冲突。** 数学式规定变量关系和计算约束；NumPy/PyTorch实现它，反向传播学习未知参数；内部Qwen可以为复杂经历提供结构化情境评价，但其输出不能自动成为人格变化的真值。
3. **必须区分三种变化：** (A)当前心理状态改变；(B)情境条件反应/认知策略参数改变；(C)跨情境、长时间稳定人格改变。A不自动意味着B，B不自动意味着C。特质估计更新也不等于“人格生成机制已经改变”。
4. **每轮推断 ≠ 每轮训练 ≠ 每轮修改长期人格。** 已发布并校准的心理计算可以每轮参与；训练只使用合格样本；长期人格仅在纵向数据和独立测量支持且通过门禁后才提交。未经验证的模型只允许Shadow或候选结果。

## 1. 已有心理构念与2.8实现边界

### 1.1 保留的长期结构

| 参数块 | 字段数量 | 心理学概念 | 计算约束 |
|---|---:|---|---|
| `H`，HEXACO | 25 | 六领域的24面向＋跨领域利他主义 | 六领域为上层聚合，不是额外6个互不相关的可训练特质；保留原ID/层级 |
| `V`，Schwartz精细价值 | 19 | 相对动机价值优先级 | 具有环形邻接/对立关系；中心化仅用作衍生特征，原始字段不得覆盖 |
| `I`，人际稳定倾向 | 2 | Agency、Communion等 | 不等于特定对象关系信任分数 |
| `L`，长期语言身份 | 15 | 表达/语用习惯 | 不能与HEXACO特质共享未经标定的量表尺度 |
| `D`，长期情绪倾向 | 7 | BEQ 3＋ERQ 2＋PANAS 2 | BEQ是表达倾向，ERQ是调节策略使用倾向，PANAS是正负情感倾向；不能视为相同的“情绪强度” |

**合计：68个长期字段**。它们由不同构念组成，**不是68个性质相同、可一起任意加减的“人格分数”**。关系状态、记忆、心境、瞬时情绪、事件评价必须另行存储。

### 1.2 2.8源码中的已实现与未实现

- `persona/trait_dynamics.py`：新版理论约束神经计算有五块输入，实际计算主隐状态 **16维**（`DH=16`），情境输入11维（`DQ=11`），关系8维（`DR=8`），心境6维（`DM=6`），情绪8维（`DA=8`），低秩为4；这与2.7 Legacy的**370维输入/64维潜在表示/Rank-8 Adapter**是不同网络，不要混淆。
- `persona/trait_estimator.py`：已有HEXACO长期状态空间估计与候选提交接口；当前纵向映射能力不应被表述为已经覆盖全部68个长期字段。
- `persona/affect.py`：旧情绪实现保留5个连续轴（`valence, arousal, dominance, stress, engagement`）与24个情绪标签；`emotion_tau_seconds=7200`、`mood_tau_seconds=172800` 等为**未标定工程参数**；当前有指数时间演化及重评/抑制实现，但还不是个体化随机情绪动力学模型。
- `persona/pmm_coordinator.py`：新版内部API与Learned可同轮调用，但“调用成功”与“已校准、实际决定行为”必须在测试中分别报告。
- 本文是研究设计参考文件；不能根据本文件声称现有2.8已经实现以下所有新增公式。

---

# 第一部分：人格计算的学术依据与公式

## 2. 理论—计算关系映射

| 理论 | 原始研究支持的关系 | 对本项目的可实现约束 | 不支持的过度推论 |
|---|---|---|---|
| **CAPS**，Mischel & Shoda (1995) [P1] | 个体对情境有特征性的“若…则…”反应规律；认知/情感/预期/目标等单元相互作用 | 人格×情境的条件反应函数，内部机制可学习 | 并未指定GRU、GNN或任何具体层数 |
| **Whole Trait Theory**，Fleeson & Jayawickreme (2015) [P2] | 特质描述侧是人格状态分布，解释侧是生成分布的认知机制 | 区分长期特质状态分布与条件生成参数 | 单次行为不等于稳定特质变化 |
| **TESSERA**，Wrzus & Roberts (2017) [P3] | 情境—预期—状态/状态表达—反应及联想/反思可促进人格发展 | 经历作为序列形成纵向学习证据 | 不存在论文直接给出的通用“经历使人格+0.02” |
| **LST-R**，Steyer et al. (2015) [P4]、Bader et al. (2025) [P5] | 分离潜在状态、稳定特质、情境变异、测量误差；自回归扩展可检验短期偏离对长期改变的关系 | 观测模型、纵向特质估计与不确定性 | 卡尔曼公式本身不是心理人格变化定律 |
| **PersDyn**，Sosnowska et al. (2019) [P6] | 特质状态的基线、变异性和吸引强度 | 允许人格状态具有动态回归、个体差异 | 不保证每种特质使用完全相同的恢复常数 |
| **Schwartz**，Schwartz et al. (2012) [P7] | 19类价值形成环形动机连续体 | 价值块单独编码并施加结构先验 | 不存在论文认证的固定价值转换矩阵 |
| **机制证据边界**，Jackson & Wright (2024) [P8] | 人格变化机制证据仍混合且不完全一致 | 容许“长期不变”作为合理结果 | 不能称统一人格转移算法已获科学证实 |

## 3. 变量与时间尺度

以下定义在同一主体 `i`、交互时间 `t` 和较慢的纵向阶段 `k` 上：

- `θ_i,k^(b)`：第`b`个长期心理构念块，b ∈ {H,V,I,L,D}；可能含缺失掩码及后验协方差。
- `q_i,t`：事件/目标/责任归因/威胁等**由证据支持的结构化情境评价**，可由内部Qwen提出，但要记录置信度、来源与未知项。
- `r_i,t`：当前对象或关系特有的信任、经历和边界，不并入全局长期特质。
- `m_i,t`：慢变心境；`e_i,t`：短时情绪；`h_i,t`：认知机制潜在状态。
- `s_i,t`：当轮可定义的人格状态潜变量；`y_i,t`：独立的行为、量表或人工测量观测。
- `ψ_i`：情境条件反应网络参数。`G`：潜在状态偏离对下一阶段特质的纵向映射；两者不是同一参数。
- `Δt`：现实秒数；`Δn`：交互事件数；对于长期人格测量不能把两者互相替代。

**符号维度原则：** 与HEXACO相容的当轮状态可为25维，但并不表示存在“19维Schwartz瞬时人格状态”或每个字段都有同量表状态指标；后者如需建模须有自己的观测方程。

## 4. P-A：人格与情境相互作用，产生当轮潜在心理状态

**候选公式：**

```math
h_t = \tanh\left(Ah_{t-1}+Bq_t+Rr_t+Mm_t+Ea_t + b
+\sum_{g\in\{H,V,I,L,D\}}\left[W_g z_t^{(g)}+C_g\left(z_t^{(g)}\odot U_gq_t\right)\right]\right).
```

这里 `z_t^(g)=Encode_g(θ^(g),mask_g,uncertainty_g)`，`a_t`是当前情绪提取/状态特征（不与动作 `action` 混用）。矩阵形状须一致；现有2.8使用低秩矩阵以减少参数。

**原理：** 人格不是仅在最后一步加一个风格提示，而是在评估、预期、行动倾向形成时影响内部计算；同样事件因长期特质与价值结构不同可获得不同反应。根据CAPS、Whole Trait Theory建立此设计，但具体`tanh`、低秩分解以及权重矩阵属于本项目的待检验神经实现，不是原文公式。

**必须输出：** `h_t`、各构念块的参与痕迹、缺失数据/不确定性、版本号；是否参与最终决策需要独立消融证明，不能仅凭调用日志认定。

## 5. P-B：特质、当轮人格状态、实际观测分离

对具有有效状态测量的特质块（先以HEXACO为例）：

```math
s_t = \Lambda\theta_k^{(H)}+Hh_t+u_t, \quad
 y_t = Ls_t+\varepsilon_t.
```

- `Λθ`：长期特质所对应的状态基线；`Hh`：情境/认知机制造成的偏移；`u`：其他状态变异。
- `y`是可观测指标；`ε`代表测量误差。未知的真实状态不能用模型自己的预测充当独立标签。
- 同一个维度的状态观测需要可比的量表语义。若数据来自不同语言、个体或时点，需要检验测量等值。

这部分受Whole Trait Theory和LST-R约束，但矩阵映射仍须通过纵向测量估计。

## 6. P-C：条件反应机制如何训练（不等同于长期人格更新）

定义合格监督数据`D_verified`，只包含有时间、来源、可核验标签和主体作用域的样本：

```math
\mathcal L_{\mathrm{mechanism}} =
\lambda_s\,\mathcal L_{\mathrm{state}}^{\mathrm{masked}}
+\lambda_a\,\mathcal L_{\mathrm{action}}^{\mathrm{masked}}
+\lambda_c\,\mathcal L_{\mathrm{calibration}}
+\lambda_r\,\mathcal R(\psi).
```

```math
\psi \leftarrow \psi-\eta\,\nabla_\psi\mathcal L_{\mathrm{mechanism}}.
```

参数`ψ`可由NumPy显式反传或PyTorch自动微分训练。损失项系数`λ`、学习率`η`是训练超参数，要在开发集选择，不是心理学常数。若某项无合格标签，该项不进入损失。

**关键约束：** 训练机制后可以改变对相似情境的预测，但绝不能因此自动声称HEXACO稳定特质发生变化；不得用LLM自己生成的回复或2.7固定步长晋升值作为独立的纵向人格真值。

## 7. P-D：经历驱动的长期特质变化候选

首先必须有独立测得的潜在人格状态`ŝ_t`，并计算相对于稳定基线的情境偏离：

```math
\zeta_t=\hat s_t-\Lambda\theta_k^{(H)}.
```

注意：用于**训练预测机制**的误差是`\delta_t=ŝ_t-ŝ_t^(pred)`；用于**纵向状态—特质研究**的`ζ_t`是相对于稳定基线的状态偏离，两者绝不能混淆。`ζ_t`受情境影响，不能把它直接当成“人格已经改变”。

分时段整理有效偏离：

```math
\bar\zeta_k=\frac{\sum_{t\in k}w_t\zeta_t}{\sum_{t\in k}w_t},\qquad
\Omega_k =\operatorname{Var}(\bar\zeta_k\mid D_k).
```

权重`w_t`来自**预先定义的独立性/抽样/测量模型**，不能用LLM随手给出的“可靠度0.9”代替。

随后建立线性高斯候选纵向模型：

```math
\theta^-_{k+1}=F\theta_k+G\bar\zeta_k+b,
```

```math
P^-_{k+1}=FP_kF^\top+G\Omega_kG^\top+Q_k.
```

第二个协方差式假设先前特质误差、状态偏离估计误差、过程噪声相互独立；不满足时必须处理交叉协方差，不能直接使用这个简化式。

**理论与限制：** TESSERA为重复经历可能参与发展提供机制假设；LST-R的自回归扩展提供统计研究范式；具体`F,G,b,Q`是本研究的**待估计参数**，不是文献发布的人格变化常数。无可靠纵向数据时允许`G=0`，且不得因一次聊天自动跨构念修改人格。

**学习G：** 利用多个主体、跨多个时间点、前后均有人格测量的纵向数据拟合；初期可使用分块/对角/稀疏层级结构，再与跨块结构比较预测效度。数据不够时不开放高维自由矩阵。价值、BEQ/ERQ、语言习惯都要先各自建立测量模型，再讨论纵向G块。

## 8. P-E：长期人格后验校准、候选审核

有独立后续测量`y_{k+1}`及观测矩阵`H_o`时：

```math
S=H_oP^-H_o^\top+R, \qquad K=P^-H_o^\top S^{-1},
```

```math
\mu^+=\mu^-+K(y_{k+1}-H_o\mu^-),
```

```math
P^+=(I-KH_o)P^-(I-KH_o)^\top+KRK^\top.
```

这是**线性高斯状态估计（卡尔曼式校准）**；其统计性质有一般状态空间模型依据，**不是LST-R论文原封不动的人格更新公式**。若实际测量为序数、缺失严重或非线性，应使用适当的序数潜变量测量模型或其他近似方法，不得直接把1—5分量表假定为已校准连续正态真值。

**更新结果：** `θ_candidate`, `covariance`, `evidence_ids`, `model_version`, `measurement_protocol`, `uncertainty`, `review_status`。

**提交门禁：** 必须同时符合有效测量、训练与验证门禁、事件去重、主体隔离、人格版本CAS、可回滚与Legacy兼容。更新后还必须独立验证行为生成机制在新情境是否表现出相应持久变化；否则只能说“特质估计变了”。

## 9. 人格计算的完整运算频率

| 操作 | 发生频率 | 是否改变永久人格 |
|---|---|---|
| P-A前向神经心理推理 | 已校准Active模式中每轮；Shadow时仅旁路对照 | 否 |
| P-B状态预测及必要的观测校正 | 每轮可预测；有合格观测才校正 | 否 |
| P-C网络梯度学习 | 仅候选数据审核通过且训练被调度时 | 不直接改变人格字段 |
| P-D纵向变化预测 | 有足够纵向样本且满足时间/测量条件时 | 仅形成候选 |
| P-E测量校准与审核提交 | 有独立后续测量并通过门禁时 | 可能，且可为零变化 |

---

# 第二部分：情绪与心境的学术依据及公式

## 10. 需要在PMM中区分的情感结构

- **瞬时情绪 `e_t`：** 由当前事件评价触发、相对快速变化的内部计算状态。
- **心境 `m_t`：** 相对缓慢、可能受一系列事件影响的基线偏离状态。
- **情感核心 `x_t`：** 如效价（valence）、唤醒（arousal），可用连续坐标表示；`dominance`、`stress`、`engagement`是2.8兼容的额外指标，需要分别定义，不能称为Russell理论必然包含的五个基本轴。
- **类别激活 `p_t^(emotion)`：** 24个现有标签的模型输出；允许共同激活，不等于Cowen & Keltner（2017）发现的27类完整分类。
- **长期倾向 `D`：** ERQ策略习惯、BEQ表达倾向、PANAS长期正负情感倾向，不能在单次事件中随意加减。
- **外在表达 `o_t`：** 最终话语、语气与其他输出，不等于内部情感状态；应独立建模。

## 11. 情绪理论—计算映射

| 文献 | 可支持的计算结构 | 重要限制 |
|---|---|---|
| **Russell (1980)** [E1] | 核心情感的效价—唤醒等连续空间 | 不等于所有情绪只需要两个数字 |
| **DynAffect**，Kuppens et al. (2010) [E2] | 情感基线、变异性、吸引强度存在个体差异 | 不能直接把“HEXACO高焦虑”换算成固定恢复分钟数 |
| **Oravecz et al. (2011)** [E3] | 分层潜在随机微分方程与个体差异 | OU是统计动力学假设，不是“真实感受”的证明 |
| **Scherer (2009)** [E4] | 事件评价的动态组织与情绪反应生成 | 不支持单个“敌意”标记自动决定全部情绪 |
| **Cowen & Keltner (2017)** [E5] | 细粒度情绪类别与连续梯度共存 | 该研究是人类情绪报告，不能宣称当前24类已被其验证 |
| **Gross (2002, 2015)** [E6][E7] | 认知重评与表达抑制发生在不同阶段，作用位置不同 | 抑制表达不应默认将内部愤怒同时乘0.6 |
| **Gross & John (2003)** [E8] | ERQ的重评/抑制倾向 | ERQ分数不是实时调节效果 |
| **Gross & John (1995)** [E9] | BEQ的正负表达和冲动强度 | BEQ测量表达倾向，不等同于核心情感 |
| **Watson et al. (1988)** [E10] | PANAS正向、负向情感 | PANAS并非Russell效价/唤醒的直接换算表 |

## 12. E-A：长期人格条件化的情感动力学参数

定义每个主体的核心情感基线、回归速率与随机扰动规模：

```math
\mu_i = g_\mu(\theta_i^{(H)},\theta_i^{(D)}),
```

```math
\kappa_i=\mathrm{softplus}(g_\kappa(\theta_i^{(H)},\theta_i^{(D)}))+\epsilon_\kappa,
\qquad \sigma_i=\mathrm{softplus}(g_\sigma(\theta_i^{(H)},\theta_i^{(D)})).
```

- `μ`情绪/心境典型基线；`κ`回归速度（单位：1/秒）；`σ`扩散强度（单位：情感状态/√秒）。
- `g`可使用低维层级线性模型或神经网络，从有纵向密集观测的数据中训练。**DynAffect支持这三类动态参数，具体人格→参数函数属于本项目假设**。
- `κ`和`σ`不能凭少量聊天同时准确估计；若数据不足应使用具有来源的共享先验并将参数标记为未校准，不允许自动正式发布。
- 现有2.8的`emotion_tau_seconds`等仅是Legacy工程常数；若旧参数形式为`exp(-Δt/τ)`，则可在纯确定性同类OU近似下写`κ=1/τ`，**不是理论推导出的真实人格速率**。

## 13. E-B：现实时间下的连续随机情绪动力学（OU）

一维或相互独立各轴上的原型：

```math
dx_t=-\kappa_i(x_t-\mu_i)\,dt+\sigma_i\,dW_t.
```

对于两次实际事件相隔`Δt`秒，参数在区间内固定时的**精确离散式**：

```math
x_{t+\Delta t}=\mu_i+e^{-\kappa_i\Delta t}(x_t-\mu_i)+\varepsilon_{\Delta t},
```

```math
\varepsilon_{\Delta t}\sim\mathcal N\left(0,\frac{\sigma_i^2}{2\kappa_i}(1-e^{-2\kappa_i\Delta t})\right).
```

**数学要点：** 这里的`κ`是每秒回归率；`σ`是扩散系数，不能把`σ²`误写成固定的一次性方差。当`κ→0`时，要采用连续极限`Var≈σ²Δt`处理避免数值不稳定。多变量耦合OU可以用矩阵指数及积分协方差实现，但第一版推荐先使用经过验证的独立轴或稀疏协方差，避免无依据地拟合全部交叉项。

**边界处理：** 情感量表如果约束在[-1,1]或[0,1]，优先在无界潜在空间执行OU，再用`tanh/sigmoid`映射观测/展示，不直接截断高斯采样后声称仍是严格OU分布。

**“自发波动”含义：** 仅指内部仿真状态在无新外部事件时可随机波动，不表示AI具有人的主观体验，也不允许自动捏造外部经历。

## 14. E-C：现实时间＋交互轮次的不同贡献

先设**有实证支持的基础模型**为E-B：真实时间连续演化，交互事件通过下文E-D产生冲击。

如果实验支持在控制真实时间及事件内容后，轮次本身仍有独立效应，才在候选模型中加入：

```math
x_{n+1}^- = \mu_i+
\exp[-\kappa_i^{(t)}\Delta t-\kappa_i^{(n)}\Delta n]
(x_n^+-\mu_i)+\varepsilon_{n+1}.
```

这里的轮次系数`κ^(n)`不是已证实的心理学常数，**必须与`κ^(n)=0`基线进行消融比较**；若会话轮次本来就代表新事件，则不得既用轮次项衰减又把同一事件重复计入E-D冲击。

推荐部署策略：**实时`Δt`每轮必计算，交互轮次用于事件标识和候选建模；轮次独立衰减项默认关闭，只有验证后启用。**

## 15. E-D：事件评价—人格条件化情绪反应

由内部Qwen/API产生候选评价（包括新颖性、目标相关性、目标一致性、责任归因、控制感、规范冲突、损失、关系等），必须保存来源及未知项。再由可训练数值函数计算：

```math
j_t=f_\phi(q_t,\theta_i^{(H)},\theta_i^{(V)},\theta_i^{(D)},r_t,m_t,e_t^-),
```

```math
e_t^+ = \operatorname{Link}^{-1}\!\left(
\operatorname{Link}(e_t^-)+j_t\right).
```

其中`Link`表示有界状态到潜在尺度的映射（如logit或atanh），`j_t`为潜在状态下的事件冲击。模型结构可用分块网络/低秩交互参数；符合Scherer的评价顺序思想，但**不是Scherer原文的指定神经公式**。

**不能默认**“违约事件使愤怒+0.3”。而应记录事件理解、主体对事件的评价、个体长期倾向与当前状态，利用外部监督逐渐训练响应强度与方向。

## 16. E-E：心境与短期情绪的分层动力学

推荐区分快速情绪`e_t`和较慢心境`m_t`：

```math
de_t=-K_e(e_t-\mu_e)dt+B_ej_tdt+\Sigma_e^{1/2}dW_t^{(e)},
```

```math
dm_t=-K_m(m_t-\mu_m)dt+C\,\Pi(e_t-\mu_e)dt+\Sigma_m^{1/2}dW_t^{(m)}.
```

`K_m`预期对应比`K_e`更慢的特征时间尺度，但不应固定认定所有心境均为48小时；数据驱动标定。`C`代表情绪对慢变心境的累积联系，`Π`只选择有定义的共同情感轴；不能把所有24类情绪概率直接不加区分地积分进心境。

**数学实现注记：** 上述`j_t`若是离散事件的跳变，不应同时写成连续`B_ej_tdt`与16节的离散跳变。程序实际采用**区间内OU传播＋事件时刻一次性跳变**（operator splitting）。连续表达中的`B_ej_tdt`仅用于连续事件输入版本，两者二选一，以免双重计权。心境可采用慢速OU或已知区间的低通累积，但需避免对同一事件双重注入。

## 17. E-F：细粒度情绪类别，不等同于连续情感坐标

现有24类标签保留兼容，用多标签概率头：

```math
p_t^{(label)}=\operatorname{sigmoid}(W_\ell[e_t,q_t,h_t]+b_\ell).
```

多标签允许愤怒与失望同时出现；各输出需单独校准，不应把全部24个值加起来强制等于1。24标签是项目现有工程目录，**不可声称直接复制了Cowen & Keltner的27类验证结果**。若标签缺少合格观测，可标记为未校准，不得人工把输出作为绝对“真实感受”。

## 18. E-G：认知重评、表达抑制和调节策略

Gross的过程模型意味着**调节策略发生的位置不同**：

```math
u_t\sim \pi_\rho(u\mid e_t^-,q_t,\theta_{ERQ},\theta_{BEQ},goal_t),
```

**重评（reappraisal）**作用于评价阶段：

```math
q'_t=\operatorname{Reappraise}_\rho(q_t,context_t,goals_t),\quad
j'_t=f_\phi(q'_t,\theta,r,m,e^-).
```

**表达抑制（suppression）**主要作用于可观察表达：

```math
\mathrm{expression}_t=g_\omega(e_t^+,u_t,\theta_{BEQ},social_t),
```

- 表达抑制不得默认直接让内部愤怒衰减固定比例。
- 长期ERQ分数是策略使用倾向，而非“重评必然有效率0.6”；重评是否成功要看评价变化是否带来合格观测支持的结果。
- 重评策略可能重新解释同一事实，但**不允许修改事件客观记录本身**；事实和评价要分离。
- 可保留`none / cognitive_reappraisal / expressive_suppression`初版接口，后续再扩展Gross框架中的其他策略。

## 19. 情绪运算什么时候执行？

| 计算 | 触发时机 | 持久状态变化 |
|---|---|---|
| E-A人格→动态参数 | 加载已发布模型及长期人格版本变化时缓存或重算 | 改参数候选需审核 |
| E-B/E-C真实时间传播 | 每次新交互前按现实时间推进；非交互投影只读 | 在事件事务中提交一次 |
| E-D事件情绪冲击 | 发生新的有效事件，并经过评价 | 可以改变短期情绪 |
| E-E慢心境演化 | 时间推进及有合格事件时 | 可以改变心境，但不是改稳定人格 |
| E-F多标签情绪 | 每轮推断或展示读投影 | 不单独修改长期人格 |
| E-G策略与表达 | 评价与表达阶段 | 调节和表达记录保留；不自动改变ERQ/BEQ长期字段 |
| 动态参数网络训练 | 独立观测标签满足条件后 | 更新候选模型，校准/发布后生效 |

**重放/重试原则：** 同一`event_id`只进行一次情绪冲击、一次随机采样及一次正式状态提交；UI反复刷新不重复抽样；同一时间和随机种子重放必须得到一致结果；角色隔离及模型版本切换要使用独立随机状态。

---

# 第三部分：人格—情绪相互作用、数据及实现

## 20. 两者如何耦合而不互相混淆

**较慢方向：** 已通过长期学习审核的人格`θ_k`影响条件反应函数、情感基线`μ`、回归`κ`、变异性`σ`及策略倾向。其影响强度由训练/校准决定。

**较快方向：** 当前`e_t,m_t`影响人格在情境中的实际表现、评价、注意和行动选择，但不因此修改稳定`θ`。

**跨长期方向：** 大量状态和行为观测可以为人格变化提供候选证据，必须经过LST-R式的测量分离、TESSERA意义上的经历积累假设检验以及独立后续测量。不能用“今天情绪很低落”推导“长期人格外向性下降”。

一个简化的单轮调用流程：

```text
General LLM / 外部事件入口
   ↓ 输入证据与时间戳
PMM读取稳定人格θ、长期倾向D、关系、记忆及上一轮心理状态
   ↓
独立API/Qwen心理推理：事实/目标/归因等候选情境评价q（不作为人格真值）
   ↓
情绪E-B/E-E：按真实Δt推进短期情绪和心境（可复现采样）
   ↓
调节E-G：必要时重评q，生成候选情绪策略
   ↓
情绪E-D/E-F：计算事件冲击、具体情绪激活
   ↓
人格P-A/P-B：长期人格×情境×当前情绪→心理反应/当轮人格状态
   ↓
PMM认知融合、策略评估、行动决策（软心理倾向不得覆盖硬边界）
   ↓
General LLM表达语言；独立表达抑制控制外在表达，不抹掉内部状态
   ↓
证据审计、幂等提交、状态版本记录
   ↓（异步调度/审核后的后续任务，不是每轮自动训练）
P-C心理机制训练；必要时P-D/P-E长期特质估计与候选审核
```

**计算循环说明：** 若需让人格神经反应反向影响API评价、情绪重评，可允许**有界的第二轮认知复核**（有限次数、明确冲突判据、带超时），而不是运行无法终止的循环。内外语言大模型作用范围不同。

## 21. 程序落地建议（对2.8最小侵入）

| 建议组件 | 对应公式 | 与现有代码关系 |
|---|---|---|
| `persona/trait_dynamics.py` | P-A/P-B | 保留2.8已实现网络；严格区分五构念块及已有16维潜变量，不再把旧版64维网络误认为同一个 |
| `persona/trait_estimator.py` / `pmm_longitudinal.py` | P-D/P-E | 保留已有HEXACO估计与候选门禁，后续在真实纵向数据上校准，不直接泛化到全部68字段 |
| 新 `persona/affect_dynamics_v2.py` | E-A/E-B/E-C/E-E | 实现可复现OU传播、人格条件化参数、短情绪/慢心境、双时钟数据接口；原`affect.py`保留Legacy |
| 新 `persona/affect_response.py` | E-D/E-F | 多构念事件反应、24标签校准、可信评价输入 |
| 新 `persona/affect_regulation.py` | E-G | 重评改评价、抑制改表达；保留可审计的策略与效果 |
| 新 `persona/affect_training.py` | E-A/E-D/E-F/E-G | 使用独立监督、掩码、多时序数据训练并发布，不将随机初始化模型作为正式权重 |
| `persona/pmm_coordinator.py` | PMM主循环 | 同轮接入内部API、神经、情绪、关系、记忆、决策；Legacy/Shadow/Active分别验收 |
| 原`persona/affect.py` /数据存储 | 数据迁移 | 原状态格式、24标签ID、历史事件完整保留并可回滚 |

**开发顺序：** 先数学正确性与接口、再状态持久化及双时钟、再情绪响应与调节、再与人格/决策真实接线、再训练与科学验证；每步都在Legacy隔离下运行测试。**不是要求所有新模块必须立即完成科学标定**。

## 22. NumPy/PyTorch中如何执行关键公式（精确约定）

### 22.1 OU离散传播

```python
import math

def ou_step(x, mu, kappa, sigma, dt_seconds, z):
    """潜在无界轴上的OU精确离散传播；z为已记录的N(0,1)采样。"""
    if dt_seconds < 0 or kappa < 0 or sigma < 0:
        raise ValueError("invalid time/dynamics")
    a = math.exp(-kappa * dt_seconds)
    if kappa > 1e-12:
        variance = sigma**2 * (-math.expm1(-2*kappa*dt_seconds)) / (2*kappa)
    else:
        variance = sigma**2 * dt_seconds
    return mu + a*(x-mu) + math.sqrt(max(variance, 0.0))*z
```

- `dt_seconds`明确为秒；如果训练数据以小时为单位必须一致换算，不能把每秒`κ`当每轮`κ`。
- `z`由事件作用域的可复现采样状态生成并写入事务；UI只读预测均值或读取已提交快照，不再重新抽样。
- 情绪实际有界时先在潜在尺度做此运算，再映射回原值域。

### 22.2 人格神经网络

```python
# 模型的结构由P-A定义：h_t=f(theta_blocks, q_t, r_t, mood_t, affect_t, h_prev)
# 只在有合格标签时执行loss.backward()与optimizer.step()
# trainable = {A,B,R,M,E,W_g,C_g,U_g,heads,subject_adapter}
# 非法数据/缺失构念必须掩码；不能直接用null→0.5作为有证据估计。
```

### 22.3 长期人格估计

```python
# theta_prior = F @ theta_old + G @ latent_state_deviation + b
# P_prior = F @ P_old @ F.T + G @ Omega @ G.T + Q  # 独立误差前提
# solve(S, ...)；Joseph covariance 更新
# 自动输出候选及不确定性，不允许绕过训练发布/证据审核门禁。
```

## 23. 训练数据最小契约

建议每个可追溯样本至少具有：

```json
{
  "subject_id": "persona_id",
  "event_id": "stable_unique_event_id",
  "timestamp_utc": "ISO-8601",
  "scope": "agent_self / relationship / external",
  "source_kind": "observed / independent_label / inferred / generated",
  "source_ids": ["source_event_id"],
  "traits_before_version": "verified_version",
  "appraisal": {"values": {}, "mask": {}, "provenance": {}},
  "state_observation": {"values": {}, "mask": {}, "measurement_protocol": null},
  "action_observation": {"label": null, "verified": false},
  "subsequent_trait_measurement": {"values": {}, "protocol": null},
  "clock": {"wall_elapsed_seconds": null, "interaction_sequence": null},
  "model_versions": {"reasoner": null, "trait": null, "affect": null},
  "train_allowed": false
}
```

这里只是结构契约示例，不代表字段无值的样本可以用于纵向训练。**尤其长期人格监督必须有独立、具有纵向可比性的测量**，不能从原程序的固定`max_step`规则自行合成真值。

## 24. 最小科学验证与工程测试

**数学单元测试：** P-A矩阵维度、NumPy/Torch输出一致、有限差分梯度；P-D/P-E手工数据可验证；OU当`σ=0`退化为确定性指数回归；`Δt=0`不变化；`κ→0`方差极限；大`Δt`趋向基线分布；多主体不同参数行为相异。

**状态与集成测试：** 同一事件重复处理不二次抽样/二次增益；UI轮询只读；现实时间推进正确；间隔一天与间隔一分钟不同；重评只改评价不改事件事实；抑制影响表达而不自动清除内部情绪；正常交互中的人格与情绪均在决策前参与；旧版数据回退可靠。

**科学验证：** 状态/情绪测量效度、纵向测量等值、情境外预测、心理构念干预、时间模型对比（OU vs 确定性指数 vs 无轮次项等）、随机扰动校准、人格变化的M0/M1/M2模型比较。**工程测试通过≠已证明AI存在人类意义的情绪或人格发展**。

**禁用越界承诺：** 训练不足时不能宣称“已经学会人格”；缺少长期人格证据时不能自动提交；没有人类/独立标签时不能宣称心理学验证成功。

---

# 第四部分：经核实的核心参考文献与链接

以下文献为可核对的真实出版物，引用只为支持各段所列理论或统计框架，**不意味着任何一篇直接给出了上述完整PMM算法**。

### 人格与长期变化

- **[P1]** Mischel, W., & Shoda, Y. (1995). A cognitive-affective system theory of personality: Reconceptualizing situations, dispositions, dynamics, and invariance in personality structure. *Psychological Review, 102*(2), 246–268. https://doi.org/10.1037/0033-295X.102.2.246
- **[P2]** Fleeson, W., & Jayawickreme, E. (2015). Whole Trait Theory. *Journal of Research in Personality, 56*, 82–92. https://doi.org/10.1016/j.jrp.2014.10.009
- **[P3]** Wrzus, C., & Roberts, B. W. (2017). Processes of Personality Development in Adulthood: The TESSERA Framework. *Personality and Social Psychology Review, 21*(3), 253–277. https://doi.org/10.1177/1088868316652279
- **[P4]** Steyer, R., Mayer, A., Geiser, C., & Cole, D. A. (2015). A Theory of States and Traits—Revised. *Annual Review of Clinical Psychology, 11*, 71–98. https://doi.org/10.1146/annurev-clinpsy-032813-153719
- **[P5]** Bader, M., Columbus, S., Zettler, I., & Mayer, A. (2025; online first 2024). Developing, evaluating, and interpreting personality state measures: A framework based on the revised latent state-trait theory. *European Journal of Personality*. https://doi.org/10.1177/08902070241246930
- **[P6]** Sosnowska, J., Kuppens, P., De Fruyt, F., & Hofmans, J. (2019). A dynamic systems approach to personality: The Personality Dynamics (PersDyn) model. *Personality and Individual Differences*. https://doi.org/10.1016/j.paid.2019.02.013
- **[P7]** Schwartz, S. H., et al. (2012). Refining the theory of basic individual values. *Journal of Personality and Social Psychology, 103*(4), 663–688. https://doi.org/10.1037/a0029393
- **[P8]** Jackson, J. J., & Wright, A. J. (2024). The process and mechanisms of personality change. *Nature Reviews Psychology, 3*, 305–318. https://doi.org/10.1038/s44159-024-00295-z
- **[P9]** Geukes, K., van Zalk, M., & Back, M. D. (2018; online first 2017). Understanding personality development: An integrative state process model. *International Journal of Behavioral Development, 42*(1), 43–51. https://doi.org/10.1177/0165025416677847
- **[P10]** Quintus, M., et al. (2021). Daily life processes predict long-term development in explicit and implicit representations of Big Five traits: Testing predictions from the TESSERA framework. *Journal of Personality and Social Psychology*. https://doi.org/10.1037/pspp0000361

### 情绪、心境与调节

- **[E1]** Russell, J. A. (1980). A circumplex model of affect. *Journal of Personality and Social Psychology, 39*(6), 1161–1178. https://doi.org/10.1037/h0077714
- **[E2]** Kuppens, P., Oravecz, Z., & Tuerlinckx, F. (2010). Feelings change: Accounting for individual differences in the temporal dynamics of affect. *Journal of Personality and Social Psychology, 99*(6), 1042–1060. https://doi.org/10.1037/a0020962
- **[E3]** Oravecz, Z., Tuerlinckx, F., & Vandekerckhove, J. (2011). A hierarchical latent stochastic differential equation model for affective dynamics. *Psychological Methods, 16*(4), 468–490. https://doi.org/10.1037/a0024375
- **[E4]** Scherer, K. R. (2009). The dynamic architecture of emotion: Evidence for the component process model. *Cognition and Emotion, 23*(7), 1307–1351. https://doi.org/10.1080/02699930902928969
- **[E5]** Cowen, A. S., & Keltner, D. (2017). Self-report captures 27 distinct categories of emotion bridged by continuous gradients. *PNAS, 114*(38), E7900–E7909. https://doi.org/10.1073/pnas.1702247114
- **[E6]** Gross, J. J. (2002). Emotion regulation: Affective, cognitive, and social consequences. *Psychophysiology, 39*(3), 281–291. https://doi.org/10.1017/S0048577201393198
- **[E7]** Gross, J. J. (2015). Emotion regulation: Current status and future prospects. *Psychological Inquiry, 26*(1), 1–26. https://doi.org/10.1080/1047840X.2014.940781
- **[E8]** Gross, J. J., & John, O. P. (2003). Individual differences in two emotion regulation processes: Implications for affect, relationships, and well-being. *Journal of Personality and Social Psychology, 85*(2), 348–362. https://doi.org/10.1037/0022-3514.85.2.348
- **[E9]** Gross, J. J., & John, O. P. (1995). Facets of emotional expressivity: Three self-report factors and their correlates. *Personality and Individual Differences, 19*(4), 555–568. https://doi.org/10.1016/0191-8869(95)00055-B
- **[E10]** Watson, D., Clark, L. A., & Tellegen, A. (1988). Development and validation of brief measures of positive and negative affect: The PANAS scales. *Journal of Personality and Social Psychology, 54*(6), 1063–1070. https://doi.org/10.1037/0022-3514.54.6.1063

---

## 25. 向开发对话交接的最短指令

> 请读取本文件作为「槐安梦客」人格与情绪计算的**理论—公式—实现基准**。本文件不代替已有2.8开发规格；若算法内容发生冲突，以本文件对数学定义、理论来源、参数可识别性及验证边界的澄清为准。完整保留2.7/2.8 Legacy，先审计实际接口，再按阶段实现情绪E-A—E-G及人格P-A—P-E的缺项。每轮推断使用已发布的心理模型，但不每轮反向传播或强制长期人格更新。工程测试、真实模型训练、心理学实证验证分别报告，禁止用模拟数据伪称心理学标定。

**本文件的角色：可执行研究设计＋文献证据映射；不是已被实证证明的统一人格—情绪定律。**
