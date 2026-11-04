# 2.6 复现与现场验收

以下命令使用合成数据/固定模型，无真实供应商或 QQ 请求。在程序根目录执行；需要本项目 requirements、Python 与 Node。

```bash
OPENBLAS_NUM_THREADS=1 DE_EXPERIMENT_REPORT=de26_ablation.json PYTHONPATH=.:tests python -m unittest discover -s tests -p 'test_*.py' -v
node tests/test_ui_v222.js
node tests/test_ui_v230.js
node tests/test_ui_v240.js
node tests/test_ui_v250.js
node tests/test_ui_v251.js
node tests/test_ui_v26.js
PYTHONPATH=.:tests python tests/upgrade_de_v26.py --old-root <解压后的2.5.1源码目录>
PYTHONPATH=.:tests python tests/launcher_smoke.py
node --check web/app.js
python -m compileall -q persona scripts tests run.py launcher.py
```

`launcher_smoke.py` 使用 Linux 的进程组机制；不能作为 Windows 原生验收。Windows 用户直接双击 Start_HuaiAn.cmd，检查页面 2.6、诊断、旧主体与训练数据。

可选真实浏览器测试需 Python Playwright 及已安装 Chromium：安装后运行 `PYTHONPATH=.:tests python tests/browser_de_v26.py`。Windows 先 `set PYTHONPATH=.;tests`；可用 CHROMIUM_PATH 指定浏览器。该脚本用临时数据执行人工目标、候选应用、回合详情与 390px 宽度检查；原十栏目完整浏览器脚本 tests/browser_v251.py 仍保留。本轮 Chromium 在加载页面前因环境 socket 权限失败，未取得真实视觉结论。

现场检查应核对：两个模型分别连接与 Thinking 配置、同输入对应回合、审核前后版本与字段、关闭语言学习的门控、计划与实际气泡、部分 QQ 回执与核验、升级前后主体/权重/训练步数及备份恢复。真实云端文本变化须用授权资料重复观察，不能以本地固定措辞代替。
