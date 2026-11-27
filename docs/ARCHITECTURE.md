# 代码结构与阅读顺序

这是当前源码的导航，不是全部机制已经有效的保证。

| 位置 | 作用 |
| --- | --- |
| `launcher.py` / `run.py` | 准备依赖、启动后端；公开版默认使用本目录的数据 |
| `persona/server.py` | HTTP 路由、后台任务、两套界面与角色操作 |
| `persona/subjects.py` / `persona/storage.py` | 角色目录、隔离存储、归档恢复与记录 |
| `persona/common.py` | 内部协议版本与未配置连接的初始值 |
| `persona/engine.py` | 对话主流程和心理、决策、回复环节的串接 |
| `persona/psychology.py` / `persona/role_context.py` | 心理条件及模型可见上下文；以实际调用处为准 |
| `persona/prompt_compiler.py` / `provider.py` | 精简提示词、语言模型请求与返回处理 |
| `persona/pmm_coordinator.py` / `pmm_event_reasoner.py` / `pmm_negotiator.py` | PMM 协调、事件评价与内部协商 |
| `persona/pmm.py` / `learned_pmm.py` / `registry_pmm.py` | 本地数值／神经计算及权重结构 |
| `persona/affect_dynamics_v2.py` / `expression_drive.py` | 情绪动力学与表达欲计算 |
| `persona/experience_learning.py` / `memory_role_changes.py` | 经历学习与受约束的慢速人设候选变化 |
| `persona/boundaries.py` / `validation.py` | 已有边界策略与候选回复检查；参见已知缺口 |
| `persona/token_ledger.py` | 模型调用用量记录 |
| `ui-shell/index.html` / `ui-shell/src/app/phase20Controller.js` | 当前界面的真实入口和控制器 |
| `ui-shell/src/adapters/PMMAdapter.js` | 后端读取、任务轮询与写入调用 |
| `ui-shell/src/visualizations/` | 各页面、可视化与角色管理组件 |
| `web/` | `/legacy` 兼容界面 |

阅读一轮对话时，沿 `server → engine → PMM 协调与语言生成 → validation → 发送及记录` 查找真实调用；不能仅看配置字段是否存在就判断机制已生效。模型的 thinking 适配集中在 `persona/thinking.py`，可用性仍取决于所配置服务。

`construct_registry.json` 与 `trait_disposition_registry.json` 是程序构念定义，不是某个角色的数值档案，所以保留在源码中。角色训练数据与检查点不随源码发布。数值推断、训练候选、正式发布以及长期人格更新是不同环节。

公开版仅改变启动时默认数据位置、清理预览内容与发布工具，不改写 PMM 的计算公式。完整模型是否遵守角色设定、边界和情绪条件，需要后续明确的行为验收。
