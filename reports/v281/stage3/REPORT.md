# 2.8.1 阶段 III 验收

阶段 II 门槛通过后，先完成独立连接和后端，再接入设置、运行可视化与模型训练页面。

- General LLM 仍独立。A 使用原 `pmm.api`；B 使用 `pmm281.b_api`。共用服务时只引用地址、模型、鉴权等连接字段，B 的任务、调用、Thinking、Token、超时与结果独立。旧配置无损补默认值，密钥不出现在公开设置/状态里，跨主机不沿用旧密钥。
- 本地 Ollama 与 OpenAI 兼容服务分别通过真实 loopback HTTP 接收请求；其模型回复是明确的测试替身。两个端点的列表、JSON 连接探针、各自一次任务、完整回合、故障、超时及复用均通过。23 项后台/运行测试通过，见 `gate_backend_final.log`。
- 真实系统 Chromium 通过 `tests/browser_v281.py` 运行 15 项断言，见 `browser_results.json`。点击“保存并测试整轮调用”调用实际 Provider、Engine 与数值步骤；测试库中的写入没有改变正式记录。页面完成数据导入、真实两步 PyTorch 训练。切换模式不丢设置；390px 布局无横向溢出；无浏览器 JS 异常。
- 实际截图：pmm_settings_desktop.png、pmm_runtime_desktop.png、emotion_desktop.png、training_desktop.png、pmm_mobile.png。截图数据均来自隔离合成测试，不含真实用户会话或凭据。
- 初次浏览器运行的受限套接字、CSP 不允许测试器字符串求值、早期模式保存竞态已定位。最终在桌面环境运行并基于可见 DOM 断言；保存改为单次配置回执更新，完成后再允许编辑。没有削弱应用 CSP。
- 训练、校准、发布与正式采用各自展示。未运行云账号、真实本机 Qwen 或真实 QQ，不能据协议模拟推断实际模型任务质量。

复验：安装开发测试环境的 Playwright 与 Chromium，在项目根目录运行 `python tests/browser_v281.py`（Linux 默认浏览器路径 `/usr/bin/chromium`）；原始界面行为脚本和 HTTP 服务测试均随源码提供。

结论：阶段 III 工程与浏览器门槛通过；外部真实模型及心理测量标定仍待实测。
