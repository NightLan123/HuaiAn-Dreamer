# 2.2.2 P0 实施状态

日期：2026-10-27（Asia/Shanghai）。依据最新 P0 回归指令及已查看的现场截图。无 Git 提交；完整源码和索引以路径、行区间及 SHA256 定位。2.2.1 机制说明归档为 IMPLEMENTATION_STATUS_V221.md。

| 要求 | 已实现 / 验证 | 关键代码 | 未完成 |
|---|---|---|---|
| 空白页面与 null.profile | 首次加载禁用编辑、核心先渲染、辅助请求独立、错误不伪装零记录 | app.js: connectLocal/refresh/setDataReady/guard | 原现场第一个失败请求仍未知 |
| 本地会话独立可恢复 | bootstrap 与状态分离、端口 Cookie、过期 GET 重连、POST 不重放 | server.py: Handler；app.js: api | 真实浏览器 Cookie/布局实机 |
| 模型断开本地仍可用 | 故障注入下角色、边界、会话、历史读写成功 | Runtime.state；test_v222.HTTPRecoveryTests | 真实模型重新连通后的联合验收 |
| 数据不误建空主体 | 原路径优先、核心只读校验、目录重建有条件、坏库停止 | data_guard.py；storage.py；subjects.py；run.py | 用户实际原库未取得 |
| 自动备份、连续性 | DB/WAL/SHM 原副本 + 独立一致性快照；身份、关联、行数/内容哈希 | prepare_upgrade/complete_upgrade；upgrade_v221_smoke.py | 生产量级性能及现场恢复 |
| 全部旧会话可访问 | 移除 40 会话截断；超过 2000 消息分页，稳定排序 | renderShell/loadEarlierMessages；Store.history | 实际超大数据库视觉/性能 |
| 移除旧维度入口 | UI 移除旧维度、关键词、半衰期、基线/旧 PMM 选择；保留原档案 | web/index.html/app.js | 旧算法的全面研究替换不在本 P0 范围 |
| 错误可查 | method/path/status/code/id；脱敏模块/行号堆栈；源码可导出 | Handler.send/failure；requestError；source 导出 | 缺旧请求 body，不推断其具体坏字段 |
| Windows 双击 | 延续 Start_HuaiAn.cmd、UTF-8、持续错误窗口与日志；Linux 中文空格路径启动通过 | launcher.py/Start_HuaiAn.cmd | Windows 原生双击未测 |
| 跨对话代码可审查 | 实际完整源码、索引、SHA256、版本和测试证据同步 | scripts/export_sources.py；review/ | 其他对话仍需文件访问或用户附文件 |
| 关键交互 E2E | 完整 app.js 启动 + 真实 HTTP + DOM 结构联调 14 场景 | tests/test_ui_v222.js | 真实浏览器视觉 E2E 尚未完成 |

整体状态：本地验证通过的修复候选版；用户生产事故尚未完成验收。继续暂停新增心理/社交/视频功能。旧版 ERROR-01/BRM-01 研究边界、真实云端/QQ 未验证和数值心理效度未成立的限制保持不变。
