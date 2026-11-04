# 2.5.1 复现与现场验收

以下命令使用合成数据与确定性模型夹具，不连接真人 QQ 或付费模型。

```bash
OPENBLAS_NUM_THREADS=1 PYTHONPATH=.:tests python -m unittest discover -s tests -p 'test_*.py' -v
node tests/test_ui_v222.js
node tests/test_ui_v230.js
node tests/test_ui_v240.js
node tests/test_ui_v250.js
node tests/test_ui_v251.js
PYTHONPATH=.:tests python tests/upgrade_ui_v251.py --old-root <解压后的2.5.0源码目录>
```

结构 DOM 测试不能替代真实浏览器。可选浏览器验收需 Node 或 Python 的 Playwright 测试环境；Python 安装 `playwright` 后运行 `python -m playwright install chromium`，再执行 `PYTHONPATH=.:tests python tests/browser_v251.py`。Windows 可先 `set PYTHONPATH=.;tests` 再 `python tests/browser_v251.py`。可用 CHROMIUM_PATH 指定已安装的浏览器；脚本使用临时数据、逐页截图和 390px 视口检查，输出到程序目录旁的 v251_browser_artifacts。

此脚本本轮因执行环境拒绝 Chromium socket 未能运行到页面；没有提供未经实际渲染的替代截图。真实 Windows、实际生产库、云模型及 QQ/SnowLuma 应另行验收，并核对多气泡、未知回执、部分发送、升级备份与回退。
