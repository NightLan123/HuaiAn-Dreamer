# 2.2.2 本地 API 合约验收

执行脚本：`tests/test_v222.py`、`tests/test_api.py`、`tests/test_ui_v222.js`。这些测试启动真实 loopback HTTP 服务、使用持久临时 SQLite 和真实 HTTP 请求；外部模型故障由测试明确注入，未使用真实账号。

| 请求 / 操作 | 结果 | 验证内容 |
|---|---|---|
| GET `/api/health` | 200 | 版本、构建、local_only；不访问云模型 |
| GET `/api/bootstrap` | 200 | 独立 Cookie + CSRF，不加载人格/边界聚合；跨站来源 403 |
| GET `/api/state` | 200 | 已存 identity/profile/93 字段/session/config；边界故障以 component_errors 局部报告 |
| GET `/api/events` 合成异常 | 500 | LOCAL_SERVICE_ERROR、request_id、服务日志堆栈；不带私密异常正文 |
| GET `/api/messages` | 200 | 原私聊/群聊记录；offset 分页不会丢同时间戳消息或改变 ID；非法 offset 400 |
| POST 角色 / 边界编辑 | 200 | 实际表单写入、刷新、后端重启后仍保存 |
| POST 所有外部连接断开 | 200（本地编辑） | 角色、边界和会话读写不调用外部模型；无法真实发言时仍返回原有明确错误 |
| POST 旧会话 token | 403 | SESSION_EXPIRED、没有写入；前端重连但不自动重放 POST |
| GET 重启后的旧会话 | 401 → 重连 → 200 | 不换人格、身份或数据目录 |
| POST 错客户端版本 | 409 | FRONTEND_VERSION_MISMATCH，原数据不变 |
| GET 静态资源 | 200 | 明确 HTML/JavaScript/CSS/SVG MIME、no-store、nosniff、构建标识 |
| 同主机两个端口 | 各自 200 | 同一 Cookie 容器保留两个端口独立会话，不互相覆盖 |

错误展示包含 method/path/status/code/request_id。意外服务器异常日志记录模块、行号与函数，不记录 API 密钥、查询 token 或私密异常正文。未知首个现场失败仍不填造请求编号。

完整执行结果见 `test-v222-results.txt`、`ui-v222-results.txt`、`test-v222-targeted.txt`；接口联调不等于浏览器布局或真实云服务兼容验收。既有双模型和 Thinking 适配保持原功能，本轮没有声称增加协议或完成所有厂商实测。
