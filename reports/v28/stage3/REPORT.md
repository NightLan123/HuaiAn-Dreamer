# 第 III 阶段：公式 D/E

新增 trait_estimator.py、test_v28_stage3.py；Coordinator 调用独立 Estimator，无测量时返回 not_ready。

公式 D → predict；公式 E → linear_gaussian（solve + Joseph）；非高斯测量 → ordinal_logit（Gauss-Hermite 积分及 ADF 矩投影）；独立分时观测汇总 → adjusted_state_summary；不写人格的候选 → LongTermEstimator.estimate。

执行 `OPENBLAS_NUM_THREADS=1 PYTHONPATH=.:tests python3 -m unittest test_v28_stage3 -v`：10 项，0.402 秒，通过。原始结果见 tests.log。

手算：mu=.4，P=.2，y=.8，H=1，R=.1 → K=2/3，mu_post=2/3，P_post=1/15。G 未验证时为零，任意 zeta 不改变均值。有效 G=.5、zeta=.2、Omega=.04、Q=.01 时，.4→.5、.1→.12。以上是受控数学 fixture，非真实心理测量。

已验证：不同观测精度、缺失值、PSD/对称性、病态矩阵拒绝、相关误差交叉协方差、重复事件、撤回、时间分离、主体与尺度隔离、ordinal 近似及积分收敛。状态偏离来自带独立情境校准的观测，不是本轮网络减去原人格。

限制：尚无用户提供的独立纵向真实数据，当前没有经过真实数据验证的 G、测量协议或人格自动提交资格。其他构念有独立接口，缺少对应误差模型时显式未就绪，不套用 HEXACO 参数。
