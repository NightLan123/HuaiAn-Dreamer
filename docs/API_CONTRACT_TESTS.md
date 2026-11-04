# 2.2.3 API 合约更新

旧 P0 合约继续适用，历史说明见 API_CONTRACT_TESTS_V222.md。本轮实际 HTTP 测试增加：

- `/api/config` 的错误分区/类型返回 400 / INVALID_REQUEST；启用主动联系的错误含 failed_fields；失败前后配置一致。
- 部分更新的 `extra_headers:null` 仍代表保留已存请求头；换域名先清除原密钥和头，不让凭据跟随新主机。
- `/api/persona/clone` 接受 `{name}`，返回切换后的新身份状态；它不继承历史、关系、连接凭据和数值权重。
- `/api/state` 增加 capabilities；未完成的研究机制不标成已实现。
- 模型调用诊断记录 OUTPUT_LIMIT、CONTENT_FILTER、UNSUPPORTED_TOOL_CALL 等内部失败类别；外层失败仍保留 request_id/stage。

结果：396 项 Python、21 个 HTTP/结构 DOM 场景通过，见 TEST_REPORT.md。
