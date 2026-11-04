# 2.4.0 工程验收记录

- `OPENBLAS_NUM_THREADS=1 python3 -m unittest discover -s tests -v`：476 项通过，158.396 秒。
- `node tests/test_ui_v222.js`：21 项真实本地 HTTP/结构 DOM 场景通过。
- `node tests/test_ui_v230.js`：16 项分层界面场景通过。
- `node tests/test_ui_v240.js`：14 项 CBM/数值条/人工标注/重启与导出场景通过。
- 既有 `test_ui_v211.js`、`test_ui_v220.js` 通过。
- `upgrade_cbm_v240.py` 分别使用实际归档 2.3.0 和 H2：旧训练数据、双主体、旧包/快照、重启和继续训练通过。
- `compare_cbm_h2.py`：6 项相同候选的机制比较通过，零模型请求。

原始日志与 JSON 结果保存在本目录。使用合成数据和确定性协议夹具，不是心理效度、真实模型自然度、实际 QQ 或原生 Windows 验收。启动和最终打包信息见独立 JSON。

最后补齐断点恢复时的原始气泡时间顺序，并再次运行 36 项 CBM 专项，全部通过。Linux 中文/空格路径启动器检查、受监督的真实本地 HTTP 启动、启动日志及诊断端点通过；未调用真实模型。
