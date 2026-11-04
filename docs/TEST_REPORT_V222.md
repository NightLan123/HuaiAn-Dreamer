# 2.2.2 测试报告

日期：2026-10-27（Asia/Shanghai）。Linux，Python 3.12.14、NumPy 2.3.5。所有数据为临时合成数据；没有用户生产数据库、真实云模型请求或 QQ 消息发送。

| 验证 | 结果 | 证据 |
|---|---|---|
| 全套 Python 单元、集成、本机 HTTP 回归 | **361 项通过，149.835 秒**；前版 340 项，本轮增加 21 项 | test-v222-results.txt |
| 复核后的相关 Python 回归 | **30 项通过，26.371 秒**，覆盖目录登记优先、同版本目录重建备份、错误响应及全部关键 API | test-v222-post-review.txt |
| 新启动 / HTTP / DOM 结构联调 | **14 场景通过**；实际 app.js 自动启动、表单 POST、Cookie、后端重启、历史分页 | ui-v222-results.txt；test_ui_v222.js |
| 既有 JS UI 合约 | 通过；旧控件断言按明确移除要求更新，其余表单/标签/转义保持 | ui-v222-structural.txt |
| 真实旧版到新版数据升级 | 未修改的 2.2.1 程序创建合成旧档，2.2.2 自动升级后身份、人格、权重、历史、关系和连接保持 | upgrade-v221-v222.json；upgrade_v221_smoke.py |
| Linux 启动器 | 中文/空格目录，真实受监督 HTTP、日志、版本与诊断端点通过；登记位置隔离 | launcher-smoke-v222.txt |
| Python 编译、JS 语法、CMD 编码/换行、压缩包和源码索引 | 交付前静态校验 | package-validation.json |
| 真实浏览器、Windows、用户原库、QQ/云服务 | **未验收** | E2E_TESTS.md；DATA_RECOVERY_REPORT.md |

## 新故障覆盖

初始 GET 延迟/500/null/坏 JSON、局部日志/边界故障、错误经筛选后仍可见、缺失 bootstrap、Cookie 过期与双端口隔离、构建不一致；外部模型全部断开时本地可用；角色/边界刷新和重启保存；44 个会话及 2010 条消息可访问。

数据测试覆盖多个原主体、私聊/群聊、原权重与连接、完整目录丢失/损坏、孤立历史、空人格和坏权重、错数据路径、多来源歧义、持久位置优先、WAL 已提交内容、执行库独立快照、同数量内容篡改检测和幂等重启。缺失核心数据时停止，不通过随机初始化让测试“成功”。

全套初次回归发现一处旧测试仍硬编码 2.2.1 诊断版本，已改为当前版本契约后重跑通过；没有忽略失败。被用户继续消息中断的未完成运行不计通过。最后复核修改了目录登记优先、同版本目录重建的备份条件和统一错误字段，对应 30 项相关测试重新通过。

## 关键限制

旧 JS 测试跳过首次 refresh，不能证明实际启动成功；新增测试执行启动链，但使用的是轻量 DOM 结构模拟，仍不等于真实浏览器排版/焦点/下载 E2E。浏览器运行文件安装失败，未提供冒充实机的截图。

合成旧库的通过不等于用户旧数据已恢复。原始首个失败请求和真实库尚未取得；ROOT_CAUSE.md 区分截图事实、复现缺陷和未知归因。2.2.1 已有真实 QQ/云端/心理效度限制继续成立，没有把工程机制测试换成研究有效性结论。

## 重复运行

```bash
python -m unittest discover -s tests -v
node tests/test_ui_v211.js
node tests/test_ui_v220.js
node tests/test_ui_v222.js
python tests/launcher_smoke.py
python tests/upgrade_v221_smoke.py --old-root /path/to/unchanged/v221
python scripts/export_sources.py
```

升级烟测依赖另存的未修改 2.2.1 源码，不把旧版整套代码重复塞进本包。运行测试不需要真实 API key。测试已完成后只整理文档、版本、源码与交付一致性，不再修改功能代码。
