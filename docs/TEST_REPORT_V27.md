# 槐安梦客 2.7 独立测试报告

执行日期：2026-11-01（Asia/Shanghai）。测试对象为2.7完整源码，基线为2.6。本文与修改记录分开交付，提供独立可复跑的脚本和原始输出；测试由本开发会话执行，不冒充第三方审计或心理测量验证。

## 本次最终结果

| 检查 | 实际结果 | 原始证据 |
|---|---|---|
| 全量Python单元/集成回归 | 580项通过，耗时259.032秒，0失败/0错误 | V27_FULL_REGRESSION.txt |
| 本轮新增测试 | 阶段I 13、阶段II 23、阶段III 11，共47项，包含在580项内 | tests/test_v27_stage1.py、test_v27_stage2.py、test_v27_stage3.py |
| 七套实际HTTP/结构DOM场景 | 21＋16＋14＋18＋18＋10＋10＝107项，通过 | V27_HTTP_DOM.txt |
| 归档2.6实际运行并迁移 | 两份已训练合成主体；旧表/meta/权重保留、重启幂等、旧包和快照恢复、训练3→5步通过 | V27_FINAL_UPGRADE.json |
| Linux启动器 | 中文和空格路径、环境检查、受管理HTTP进程、诊断接口、启动日志通过；无真实模型调用 | V27_LAUNCHER.json |
| 实际Engine固定条件 | API-PMM/Learned-PMM各8个条件，共16个；读取状态摘要符合实际先验 | V27_ABLATION.json |
| 分因素消融 | 每种PMM分别以高耐心/高信任/高重评为基线，各6个冻结条件，共36个；重复一致且无数据库写回 | V27_ABLATION_REPORT.md、V27_ACTIVE_ABLATION_TESTS.txt |

最终全量已纳入分别对非零人格、关系、调节贡献做消融的补充断言。HTTP场景与Python套件中的部分子流程有覆盖重叠；上述数量不能相加为互不重复的独立功能。各阶段复跑次数也不累加为测试数量。

## 逐项验收映射

| 用户验收项 | 检查与可观测断言 | 结论与范围 |
|---|---|---|
| 1 同事件手动/自动不重复贡献 | Stage I automatic_then_manual、manual_then_automatic、duplicate_hypotheses；同事件多条评价/记录与旧签名回执 | 本地真实SQLite通过；独立事件计数及稳定晋升均检查 |
| 2 人物、范围隔离 | Stage II PeopleCases；Stage III scoped_conditions；身份恶意包/越界原文；实际传入模型的提示不含另一私聊唯一文本 | 通过；身份标识不等于现实身份认证 |
| 3 图式证据、版本、不确定性 | role_norm_expectation_trace_dedupe_and_retraction、inference_cannot_masquerade；身份和图式HTTP操作 | 通过，原文陈述与推断分开；历史可查询 |
| 4 同事件同对象可复现对照 | 相同初始权重/时间/输入/人物/范围；实际Engine16条件＋局部冻结36条件 | 三种活动因素分别有差异，未映射面向及零贡献消融如实无差异 |
| 5 长期更新追溯原文及前后值 | three_independent_experiences、fresh_events、withdraw、原始证据与promotion_history校验 | 通过；无依据/单事件多评价/反例/主人种子保护同时检查 |
| 6 实时情绪与长期倾向隔离 | dispositions_learn_without_affect_write、current_emotion_and_wrong_timeframe；2.3分层回归 | 通过；习惯更新不写即时情绪，当前情绪入口不能写成稳定真值 |
| 7 重启/失败/迁移一致 | 事务写后故障注入、任务重复提交、收据恢复、旧完整包及两份归档训练库迁移 | 通过；未使用用户生产库，不宣称修复其具体数据 |
| 8 下一轮PMM真实读取 | newly_learned_traits_and_habits_read_in_next_pmm_turn；关系图式进入UNDERSTAND；实际trace版本/摘要/贡献 | API及Learned路径通过；真实外部LLM语义效果仍未测 |
| 9 兼容2.6语言/情绪/QQ/人物/记忆/UI | 全量580＋七套HTTP场景；D/E候选审核、部分QQ回执及重试、双模型协议/Thinking、来源导出等既有回归 | 本地可控条件通过；真实QQ/模型/视觉布局未实测 |

## 阶段先后顺序

阶段I先通过204项定向检查及归档2.6迁移，再进入阶段II。阶段II通过224项定向检查、9项新增HTTP场景、旧D/E10项和再次迁移后进入阶段III。阶段III先完成47项新增专项及10项HTTP场景，随后补足各活动因素的单独消融并通过11项阶段III复测，最终统一执行580项。

封存的阶段日志和变更列表分别为 `V27_STAGE_I_*`、`V27_STAGE_II_*`、`V27_STAGE_III_*`。最终补充验证单列 `V27_ACTIVE_ABLATION_TESTS.txt`，不改写早期封存记录。

## 复跑方式

环境：Linux，Python 3.12.14，NumPy 2.3.5，Node.js 24.22.1。安装requirements后在源码根目录运行。Python命令在Windows需相应设置PYTHONPATH，界面使用仍可双击启动。

```sh
OPENBLAS_NUM_THREADS=1 PYTHONPATH=.:tests python3 -m unittest discover -s tests -v
OPENBLAS_NUM_THREADS=1 PYTHONPATH=.:tests python3 -m unittest test_v27_stage1 test_v27_stage2 test_v27_stage3 -v
node tests/test_ui_v222.js
node tests/test_ui_v230.js
node tests/test_ui_v240.js
node tests/test_ui_v250.js
node tests/test_ui_v251.js
node tests/test_ui_v26.js
node tests/test_ui_v27.js
OPENBLAS_NUM_THREADS=1 python3 scripts/evaluate_v27.py --output exports/V27_ABLATION_rerun.json
OPENBLAS_NUM_THREADS=1 python3 tests/upgrade_v27.py --old-root /path/to/extracted_v26 --phase final
python3 tests/launcher_smoke.py
```

归档迁移复跑需要另行保留2.6源码；2.7包没有重复嵌入整个旧版。对照脚本会创建临时测试主体，不要求真实接口密钥。每次独立运行会有新的测试事件ID和时间；“可复现”指同一冻结输入重复得到相同结果，以及同组条件内时间、身份、权重等固定，不宣称所有运行日志逐字相同。

## 失败记录与边界

开发期间的旧语言缓存夹具、默认学习强度期望、带导出时间的快照比较、API兼容占位模型训练夹具已修正，原失败证据保留，详见IMPLEMENTATION_STATUS.md。当前测试没有以跳过失败断言、清空旧训练成果或伪造真实API成功来通过。

未提供真实模型凭据、QQ账号或用户生产库；未完成原生Windows/macOS和真实浏览器视觉验收。DOM脚本验证绑定和真实HTTP返回，不等于屏幕截图或视觉排版验收。门槛、系数和工程不确定性仍未校准，测试结果不证明完整心理学效度。

最终全量回归后只补齐报告、版本结果和源码说明；另复验6项启动/源码导出/下载接口检查通过（V27_SOURCE_EXPORT_TESTS.txt）。打包逐文件比对ZIP字节、源码行区间、SHA256、版本和运行数据排除；结果及最终文件摘要见DELIVERY_MANIFEST.json。
