# 第 I 阶段：组件与 Shadow

修改 common.py、engine.py、server.py；新增 pmm_contracts.py、pmm_coordinator.py 和 test_v28_stage1.py。

新增独立端口、共同主体/范围/事件/版本元信息、68 项构念分块与 unknown 校验；适配既有记忆、情绪、关系和 API；同轮执行旧 Registry NumPy 前向作为阶段 I 的数值桥接，后续阶段 II 替换为新 A/B 网络。未将桥接称为已训练的 2.8 网络。

实际运行 `OPENBLAS_NUM_THREADS=1 PYTHONPATH=.:tests python3 -m unittest test_v28_stage1 -v`：7 项全部通过，见 tests.log。输入为原对话测试 fixture，API 是明确标记的本地合成传输；Engine、SQLite、数值前向、提交均实际执行。输出同一 turn/event 下 reasoner、neural、memory、affect、relationship、decision；shadow 写入既有 turn 审计事件，正式人格写入数为 0、发送数为 0。正式回复仍只有一份。

已验证版本化同轮 API 准备结果复用：原来 4 次请求仍为 4 次，additional_requests=0；该记录明确表示复用，不伪称新的 Qwen 调用。数字路径真正调用 RegistryPMM.decode。不同私聊的关系输入分别绑定范围；关闭新版则不执行新 Coordinator；Shadow 错误保留 Legacy 对话。

发现并修复：Engine 的局部 turn_id 在后半段才赋值；适配层改用已创建的 run['turn_id']，不重新生成事件。

公式 A—E 此阶段尚未实现。现有 API 并不提供已校准的数值可信度，因此 uncertainty 保持 unknown。真实 Qwen 尚未连接。
