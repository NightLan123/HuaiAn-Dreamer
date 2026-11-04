# 2.6 关口 II：联合决策与验证

前置关口 I 的 125 项检查及升级已通过并封存。关口 II 扩展 DE-05–DE-08，整合相关来源/审核/幂等加固，最终回归 **533 项 Python、97 项 HTTP/结构 DOM** 通过。

- 文件列表/差异：DE_GATE_II_FILES.json / DE_GATE_II.patch；相对于已封存关口 I，代码、测试与源代码导出器均纳入。报告和历史日志另随包提供。
- 固定例子：DE_GATE_II_EXAMPLE.json；相同 checkpoint/context/seed/time，各组重复两次，D-only/E-only/D+E/基线区分路径，并有独立 D/E 变化与 API-PMM 检查。
- 失败及复验：DE_GATE_II_INITIAL_FAILURE.txt / DE_GATE_II_INITIAL_RETEST.txt；重复短句代理评分已修复。DE_GATE_II_TEST_HARNESS_FAILURE.txt 记录导出时间误比导致的两项失败，最终 test-v26-results.txt 通过。
- 状态/发送：模拟 QQ 三条计划的一条确认、第二条超时、后续只读核验流程通过；实际已发文本、回执、情绪/训练状态及人工反馈保持一致，不重发、不重复训练。普通网页重复请求亦有持久绑定。
- UI：沿用三个既有页面，增加审核、来源、版本、数值、回合详情和分页；公共脱敏诊断不会泄漏原始 D/E 输入/反馈。
- 迁移：再次用归档 2.5.1 创建两个已训练合成主体验证；旧权重与样例/记忆/标注保留，旧包/快照、再次启动与继续训练通过，见 upgrade-v26-from-251.json 和 MIGRATION_NOTES.md。

本地验收通过不等于真实平台效果通过。确定性文本生成器只能证明可观察接口与提交路径；云模型/QQ、Windows/macOS、真实浏览器与生产库尚待验证，语用头保持 not_trained，工程常数保持未校准。详细完成边界和原始规划对照见 DE_IMPLEMENTATION_20261031.md。
