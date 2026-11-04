# 2.5.0 验收范围

本地 Python、真实 loopback HTTP、结构 DOM、归档版本迁移和 Linux 启动器检查已执行，详见 TEST_REPORT.md。这里的模型输出由确定性夹具提供。

真实云模型、QQ/SnowLuma、Windows/macOS 以及用户生产库尚未连接。Chromium 启动被运行环境拒绝，桌面工具初始化也失败；未提供虚假的视觉验收截图。

可在具备浏览器的开发机使用 `tests/browser_v250.py` 进行待验收的 Playwright 渲染场景；需要额外安装开发测试依赖 Playwright，并通过 `CHROMIUM_PATH` 指定浏览器。它不是程序运行依赖，本次没有运行通过。

建议现场检查：原先导致边界错误的提问；单气泡/多气泡与中途新消息；断网时明确失败与未知送达；Windows 中文目录双击启动；旧主体 ID/记忆/训练步数；学习任务审批后真实字段差异；API Thinking 设置和供应商实际用量。
