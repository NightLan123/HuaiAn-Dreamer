# 第 IV 阶段：公式 C、训练与发布

新增 pmm_trainer.py 与 test_v28_stage4.py；修改 Coordinator、evidence、formation、packages、storage、server。新数据与新模型使用原 SQLite 的独立版本元数据，证据仍引用原 learning_evidence。原 Checkpoint 不覆盖。

公式 C → masked_loss/fit；实际 PyTorch SGD，掩码加权归一化、分块正则通过验证集选择、测试集只在选定后评估。核心按主体及时间双隔离；个人 Adapter 仅用所属主体的未来窗口，明确记录这是主体内验证，不能独立冒称跨主体有效。

执行 `OPENBLAS_NUM_THREADS=1 PYTHONPATH=.:tests python3 -m unittest test_v28_stage4 test_v28_stage1 -v`：19 项，8.620 秒，全部通过。包括权重真实变化、损失下降、共享/个人冻结范围、SGD 2+2 与 4 步一致、JSON 复现、独立事件去重、泄漏拒绝、旧晋升标签拒绝、工程模型发布拒绝、真实 SQLite 的幂等任务/冻结/撤销、人格包携带新状态、撤回阻断训练及 CAS。

原始测试使用显式 controlled_fixture，不是假冒外部实测数据。训练成功只产生候选；正式发布要求不可变版本、相符的数据摘要、活跃原文、独立验证/测试指标和父版本可复算。模型的“校准”按钮不能直接写 calibrated=true。

新增独立 G 训练：fit_transition 通过前后测及 zeta 估计对角 ridge G，以未来主体/时间测试误差对比持久不变基线。fixture 的拟合误差下降，但 validated=False、validation_ref=null，因此仍不能提交稳定人格。

没有真实训练资料、真实测量尺度或合格发布模型。当前通过的是工程训练和版本管理通路。
