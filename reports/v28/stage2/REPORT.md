# 第 II 阶段：公式 A/B

新增 trait_dynamics.py、requirements-learning.txt、test_v28_stage2.py；修改 pmm_coordinator.py 与 registry_pmm.py 的新适配入口。旧 learned-pmm/2.1 参数、维度和序列化保持原样。

公式 A/B → trait_dynamics.algebra；构念 Enc → pack_blocks/algebra；严格参数维度和身份 → validate_checkpoint；NumPy 前向 → TraitDynamics.forward；相同代数的真实 PyTorch → torch_model；实际回合 → NeuralDynamicsPort.predict。

25 H / 19 V / 2 I / 15 L / 7 D 全部参与推断。V 仅在有观测项内减均值，保留 mask，未假装价值互相独立。缺失值和缺失不确定性有独立可训练编码，不伪造观测。h=16，分块秩=4，个人 Adapter 绑定主体；JSON 摘要校验且无 pickle。过程协方差与未知测量误差分开记录。

执行 `OPENBLAS_NUM_THREADS=1 PYTHONPATH=.:tests python3 -m unittest test_v28_stage2 test_v28_stage1 -v`：16 项，6.044 秒，全部通过。包括手算 A/B、NumPy/PyTorch 逐值相等、真实 autograd 与有限差分、torch.gradcheck、五块扰动、单面向固定条件对照、mask/uncertainty、跨主体拒绝、JSON 重载。

手算输入：h_prev[0]=.1，q[0]=.3，H[0]=.4；人工参数使 h[0]=tanh(.2*.1+.5*.3+.4+.4*2*.3+.01)，state[0]=.5*.4+2*h[0]。该数值由单元测试逐项复算。

通过的是工程计算与可微分机制；参数尚未由外部有效数据标定，默认 uncalibrated，只在 Shadow 计算。数值扰动方向不声称符合人类心理。没有真实问卷尺度，latent 输出标记 engineering_latent，未生成长期监督。

第 I 阶段额外兼容检查：22 项，36.785 秒，通过，见 ../stage1/compatibility.log。
