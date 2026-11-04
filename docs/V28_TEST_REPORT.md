# 槐安梦客 2.8：独立验收报告

验收日期：2026-11-03（项目交付日期，Asia/Shanghai）。依据唯一规格 `docs/V28_SPEC.md`。报告与原始日志分开提供；所有结果均来自本次实际执行，不引用旧 README 的通过数字代替重跑。

## 最终结果

| 验收组 | 实际结果 | 日志 |
|---|---|---|
| 原始 2.7 基线重跑 | 580 项 Python，252.401 秒；107 项 HTTP/结构 DOM，通过 | `reports/v28/stage0/` |
| 2.8 对继承代码的回归 | 580 项，224.810 秒，0 失败、0 错误、0 跳过 | `stage6/inherited_python.log` |
| 2.8 新增测试 | 75 项，21.775 秒，0 失败、0 错误、0 跳过 | `stage6/v28_python.log` |
| 最终 Python 总数 | **655 项通过**，不累加开发过程复测 | `stage6/python_summary.json` |
| 旧与新 HTTP/结构 DOM | **116 项通过**：原 107 + 新 9 | `stage6/http_summary.json`、`http_v*.log` |
| 2.7→2.8→原 2.7 | 两份实际旧版生成的已训练合成库通过 | `stage6/upgrade_v27_to_v28.json` |
| Linux 启动 | 中文/空格目录、真实启动器与 HTTP、诊断、位置记录通过 | `stage6/launcher.json` |
| 八类工程演示 | 实际 Engine、SQLite、NumPy、Torch 路径执行通过 | `stage6/demo.log`、`examples/v28_demo/` |
| 源码语法 | Python compileall 与 JavaScript node --check 通过 | 本次命令 exit 0 |

运行环境：Python 3.12.14、NumPy 2.3.5、Torch 2.15.0+cpu、Node 24.22.1，Linux。CPU 训练使用 float64；没有调用真实云模型或 QQ 发送。

## 阶段验收记录

| 阶段 | 当时实际验收 | 内容 |
|---|---|---|
| 0 | 580 Python + 107 HTTP/DOM | 351 文件核对、归档备份、旧权重与双主体基线 |
| I | 7 新测试；另 22 项兼容检查 | 统一契约、同轮双路径、Shadow 不重复输出 |
| II | 16 项（含 I 的 7 项） | A/B 手算、NumPy/Torch 一致、有限差分与 gradcheck、五块干预 |
| III | 10 项 | D/E 手算、G 禁用、误差精度、缺失、病态、序数近似 |
| IV | 19 项（含 I 的 7 项） | 实际反向传播、续训、数据切分、候选版本、来源撤回、发布拒绝 |
| V | 59 项整合；新增尺度检查后 19 项定向；9 HTTP/DOM | Active、长周期 CAS、下一轮读取、回退、六项消融、部分尺度绑定 |
| VI | 最终 655 Python + 116 HTTP/DOM，迁移/启动/八场景 | 全跨模块回归；后续补强全部纳入最终 75 项新增测试 |

这些阶段数字包含重叠检查，不能相加。阶段报告位于 `reports/v28/stage0` 至 `stage6`。

## 新增测试验证什么

- 七类契约/同轮路径检查，九类 A/B 数值/梯度检查，十类 D/E 数值检查。
- 十二类训练与持久化检查：权重实际改变、SGD 2+2 与 4 步恢复、核心/Adapter 冻结范围、原文去重、泄漏和伪监督拒绝、候选包与 CAS。
- 十五类 Active/消融/故障检查：内部服务初始化、首请求、后续行动评估、复核、请求期限、负面事件稳定人格不变、发布权限不足回退。
- 六类纵向校准与事务检查、六类部分尺度/环形结构/参数许可检查。
- 十类最终跨模块检查：重启、跨范围隐私、双主体、并发训练、重复事件、组件异常、发布/撤销/回退事务、CLI 进程锁、实际本地 HTTP 连接拒绝、禁用长期估计。

正向正式发布事务和人格提交接线使用显式验证服务注入，只用来检查真实 SQLite/Policy 的行为。真实门禁另行拒绝未验证、合成或伪造资料。没有把注入的资格当作真实校准结果。

## 原测试适配与失败处理

原 `test_numeric_boundary_uses_general_cues_and_actual_head` 假定数值模式永远不调用 API。2.8 默认 Shadow 要求同轮调用，首轮因此出现 1 条断言失败。该旧断言现在显式设置 `pmm28.mode=legacy`，保留全部原断言；新的 Learned+API 同轮路径由独立测试验证。三个旧 UI 文件仅将版本期待值从 2.7 改为 2.8。

真实连接失败补测发现 transport code 在 Provider 中被包装到 `call.response`，最初的 Shadow 回退识别没有取到它。修复后单项与最终整套测试重跑。先前失败日志和通过前的快照均保留，最终状态只看 `python_summary.json` 和无后缀主日志。

续接环境缺少可选 Torch 时，训练测试真实报错；安装独立测试依赖后重跑。Chromium 安装收到无效压缩包，真实浏览器视觉验收未执行。这些环境结果不计为功能通过。

## 迁移、发送与科学验证的边界

实际归档 2.7 创建的数据在升级前后逐项比较全部旧 meta/表，原权重摘要不变；继续训练从 3 到 5 步。2.8 新候选可重启，旧包/快照可恢复，原 2.7 真正读回 2.8 中新增的已确认消息。此验证没有使用用户生产数据库。

QQ 多气泡的回归使用已有实际 Outbox、幂等与事务代码，但网络对端和回执为夹具。正常 Reasoner 输出是明确的模拟传输；实际内部 HTTP 连接拒绝测试只验证断网回退。没有宣称真实 Windows、QQ、Qwen 或完整心理学效度通过。

## 重跑命令

```text
python -m pip install -r requirements-learning.txt
python tests/run_v28_regression.py
node tests/test_ui_v222.js
node tests/test_ui_v230.js
node tests/test_ui_v240.js
node tests/test_ui_v250.js
node tests/test_ui_v251.js
node tests/test_ui_v26.js
node tests/test_ui_v27.js
node tests/test_ui_v28.js
python tests/upgrade_v28.py --old-root /path/to/original-2.7
python tests/launcher_smoke.py
python scripts/demo_v28.py
```

实际环境设置 `OPENBLAS_NUM_THREADS=1`；从其他目录调用时把项目与 tests 加入 PYTHONPATH。当前测试的 Torch 放在隔离的测试依赖目录，因此运行命令显式追加该目录；它不随程序交付。用户安装到自己的 Python 环境后无需该测试路径。
