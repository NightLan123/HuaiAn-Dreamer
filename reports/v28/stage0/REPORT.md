# 第 0 阶段：实际基线与备份

执行日期：2026-11-02。唯一需求来源：docs/V28_SPEC.md。未读取其他会话。

核对归档内 351 个文件与原始 2.7 目录，全部逐字节一致。完整 2.7 归档保存在 legacy/HuaiAn_Dreamer_v2.7.zip，SHA256 `e99424d8f097eec83a67dd5cc2e98649db9f77bf5ab4f0a264383ecc9cc38dbd`。逐文件摘要见 baseline_manifest.json。只在新工作目录修改，原 2.7 不变。

实际运行：`OPENBLAS_NUM_THREADS=1 PYTHONPATH=.:tests python3 -m unittest discover -s tests -v`：580 项，252.401 秒，全部通过。见 python.log。

实际运行 2.2.2、2.3、2.4、2.5、2.5.1、2.6、2.7 共七个 Node HTTP/DOM 脚本：107 个场景全部通过，见 http_dom.log。

实际旧训练 fixture 的 2.6→2.7 迁移、两主体权重、包、快照、重启与继续训练：通过，见 trained_legacy.json。这是合成训练数据的工程兼容验证，不能代表用户的生产数据库。用户没有提供实际在用数据库，未接触或修改其数据。

已审计：engine.py 的 API/Learned 互斥解码、commit_plan 与 Outbox；registry_pmm.py 的 370 维原编码；61 长期字段 + 独立 7 倾向；traits.py 的旧晋升；affect、relationships、formation、evidence、packages 的既有契约。

适配：实际价值字段前缀为 `value.`；配置类位于 common.py，关系实现位于 relationships.py；不为建议命名重建重复实体。General LLM 独立于 PMM。2.7 的 NumPy 参数布局、93 字段排序与注册表摘要均保留。

公式 A—E：本阶段未实现，不报告为通过。真实 Qwen、QQ、Windows 与纵向心理测量未运行。
