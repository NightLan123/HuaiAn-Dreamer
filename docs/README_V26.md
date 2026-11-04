# 槐安梦客 / HuaiAn Dreamer 2.6

2.6 按 D＋E 联合规划更新：人类语言证据与人工审核、情绪/心境的真实时间演化、情境化表达策略，以及每轮实际发送结果追踪。稳定人格、语言习惯、短期情绪分别保存；旧训练成果保留。

Windows 解压后双击 **Start_HuaiAn.cmd**；不需要手输命令。Linux/macOS 执行 `sh start_mac_linux.sh`。升级前正常退出旧程序并备份数据，按 [迁移说明](docs/MIGRATION_NOTES.md) 沿用原目录或导入旧完整主体备份。

- 「语言习惯」查看来源、候选与审核、计划气泡和实际确认内容；「情绪」查看状态/事件前后；「蒸馏」查看人工审核记录。数值用条形与数值显示，未知保留未知。
- 人工反馈至少有两次独立事件且审核通过才应用为语言倾向；AI 输出本身不当训练目标。情绪不越过主动沉默、权限、边界和最终发送检查。
- 双模型独立 API、Thinking、原十栏目和已训练模型继续使用；语用神经头仍显示 not_trained。内置图库保持移除，QQ 收图与基础视觉保留。

[逐项更新](docs/DE_IMPLEMENTATION_20261031.md) · [测试证据](docs/TEST_REPORT.md) · [实现边界](docs/IMPLEMENTATION_STATUS.md) · [完整代码索引](review/HuaiAn_Dreamer_Code_Index.md)

后台诊断记录可导出本机完整源码与索引供其他对话检查，review 目录也有对应版本；源码包不含用户数据/密钥。533 项 Python 与 97 项 HTTP/结构 DOM 本地检查通过，2.5.1 合成旧库迁移及 Linux 实际启动通过。真实浏览器、原生 Windows/macOS、云模型/QQ、生产库和心理学效度尚未验证。
