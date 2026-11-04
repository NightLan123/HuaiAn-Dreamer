# 2.3.0 工程测试报告

日期：2026-10-29（Asia/Shanghai）。Linux / Python 3.12.14 / NumPy 2.3.5 / Node 24.22.1。所有数据为合成数据；模型使用本地确定性协议夹具，没有调用真实云模型或发送 QQ 消息。

| 检查 | 结果 | 工程证据 |
|---|---|---|
| 最终 Python 单元/集成/本机 HTTP/训练 | **440 项通过，133.039 秒** | `test-v230-results.txt` |
| 本轮新增类型与迁移相关单元 | **44 项**，包含在上述 440 项内，不重复相加 | `tests/test_trait_affect_v230.py` |
| 既有启动/实际 HTTP/结构 DOM | **21 场景通过** | `ui-v230-http.txt` |
| 新人格/情绪页面的实际 HTTP/结构 DOM | **16 场景通过** | `ui-v230-layered.txt` |
| 既有 UI 单元与结构 | 通过 | `ui-v230-structural.txt` |
| 2.2.1 → 2.3.0 | 真实归档程序生成训练数据；升级、旧连续包导入、完整备份恢复、继续训练、重启通过 | `upgrade-v221-v230.json` |
| 2.2.2 → 2.3.0 | 同上 | `upgrade-v222-v230.json` |
| 2.2.3 → 2.3.0 | 同上 | `upgrade-v223-v230.json` |
| Linux 中文/空格目录启动 | 真实监督启动、本地 HTTP、环境检查、数据位置、诊断和日志通过 | `launcher-smoke-v230.txt` |
| Python/JavaScript 语法 | compileall / node --check 通过 | 可按下列命令复现 |

## 本轮重点覆盖

- 连续 10 次愤怒事件，当前愤怒上升而长期特质/价值/习惯不漂移。
- 两种人格 × 两种事件情绪的工程对照；稳定特质不随当前状态改变。
- ERQ 表达抑制只影响外部计划强度，不抹掉内部负性状态；重评记录真实内部效果。
- 无事件 10 秒/5 小时不同，分段推进与一次推进等价；同时间多事件不再逐次平滑 Mood；重启不重置。
- 生成内容、一次导入、单事件多引语、反例、未来时间不能自动晋升长期人格；主人设定不会被候选覆盖。
- 单独人格晋升生成类型化训练标签；旧样本保留；队列满时原子停止，不挤掉旧样本。
- 长期标签与状态标签独立掩码/损失，旧训练参数加载后导出一致并可继续训练。
- 情绪提案不能写长期字段或错误主体；错误可见并最多一次修复，失败不提交。
- ExpressionPlan 在生成前确定，ExpressionState 在实际提交后产生；有 journal 成功回执才记 QQ 已确认。
- 旧包重新导入不会混用当前更晚状态；坏实体、坏表达日志、跨主体轨迹不能进入恢复。
- 隐私范围、主体切换、清空未知、工程参数、来源说明、版本/连接表单和重启均有回归。

## 迁移测试真实做了什么

脚本先分别在**未修改的**旧 2.2.1、2.2.2、2.2.3 源码下创建两个主体、私聊/群聊历史、非空语言例子、记忆、关系、已有 HEXACO 估计与旧情绪/评价/调节记录。旧数值 PMM 实际训练 3 步，保存含心理目标的样本、待训练队列和配置。一个主体带情绪时间戳，另一个缺可信时间戳。

新版启动后逐项比较原身份、配置、四张内容表、原 profile 字段、93 列值与未知 mask、完整 Core/Adapter 检查点、回放样本、待训练队列及记忆编码；比较通过才继续训练和测试旧包/旧完整快照导入。二次启动检查存储的分层状态完全一致。检查点和待训练队列摘要写入报告；没有读取或替换用户真实生产库。

## 测试语义调整与限制

旧“单条导入立即填入稳定人格”的断言与此次方案冲突，已改为“保存候选且未知 mask 不变”；需要已知人格的测试显式用 owner_seed 设置先验。旧四维状态断言换成新实体，包版本检查更新为 /2.3。这些是要求的行为变化，并非降低故障门槛。

Node 24 本地 HTTP 夹具出现过未消费 Response 的原生解析断言，测试客户端改为完整消费响应。测试子进程退出监听也改为启动时注册，防止清理竞态让未完成测试无结论退出；最终记录要求全部场景及结束行，而非仅检查退出码。

**未验收**：原生 Windows/macOS、真实浏览器渲染、真实云模型、真实 QQ/OneBot、用户生产数据恢复。结构 DOM 不是视觉浏览器测试，本地成功回执夹具不是实际平台送达。人类量表信度/效度、情绪参数校准、四组等预算科学消融和 QQ 延迟仍未完成。上述结果只证明覆盖到的工程性质，不证明心理科学有效性或零缺陷。

## 复现

```bash
OPENBLAS_NUM_THREADS=1 python -m unittest discover -s tests -p 'test_*.py' -v
node tests/test_ui_v211.js
node tests/test_ui_v220.js
node tests/test_ui_v222.js
node tests/test_ui_v230.js
python tests/launcher_smoke.py
python tests/upgrade_trait_affect_v230.py --old-root /path/to/unchanged/v221
python tests/upgrade_trait_affect_v230.py --old-root /path/to/unchanged/v222
python tests/upgrade_trait_affect_v230.py --old-root /path/to/unchanged/v223
python -m compileall -q persona
node --check web/app.js
```

保留旧报告 `TEST_REPORT_V223.md` 作为历史对照；不会把旧版通过数量算作本轮额外成果。
