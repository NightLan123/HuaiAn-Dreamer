# 2.8.1 情绪数据与迁移契约

状态由 owner/scope/person/session 四元组隔离，事件 ID 只在该流内应用一次；时间为 UTC Unix 秒，对外 ISO 8601 带时区。负时间/无时区时间拒绝；时钟回拨记为 rollback_no_time_reversal，effective_at 保持单调，不倒推状态；零时间不采样 OU，超长间隔直接使用稳定解析传播。UI 读取不会调用随机传播。

快情绪轴按 affect.AXES 的 valence/arousal/dominance/stress/engagement；慢心境为既有前三轴。内部无界 latent，valence 用 tanh，其余 sigmoid。历史端点逆映射 epsilon=1e-9，保留原值、缺失掩码与端点精度记录。dominance 等兼容通道属于模拟观测，不冒称独立心理测量。

E-A 网络从 HEXACO 和 D 的数值/缺失掩码学习 8 组 mu/kappa/sigma；kappa 单位秒⁻¹，sigma 单位 latent/√秒。首个模型使用保存的历史基线与时间常数，所有人格条件矩阵为零，明确 unvalidated。已有模型目录不被重新初始化。

E-B/E-E 使用分轴快慢三角 OU 的解析转移和联合协方差；驱动噪声独立但快慢状态噪声相关。近等速率使用解析矩展开避免消去误差。E-C 默认 kappa_n=0，只有显式带独立验证的版本可启用；它不制造第二段布朗时间。

E-D 输入评价值+掩码、H/V/D、关系、快情绪和慢心境。A 只能提供评价，不可把情绪增量写入状态。缺少评价时只推进时间。E-F 多标签 sigmoid 输出不归一化；未标定标签的 emotion_labels 为 null，原始 activation 单独标 uncalibrated。E-G 保存策略候选、采用状态和未知后果；重评候选必须匹配原事实摘要，抑制无内部折减。

meta.pmm281_affect 保存快慢状态、每流 RNG 状态、事件结果和模型版本；meta.pmm281_affect_models 保存候选、数据、报告、发布/撤销/冻结审计。沿用原 SQLite 事务和人格包，不建立第二套人格或记忆系统。读取旧 2.8 包时新分区可缺省；完整快照原样保存新分区。旧完整 2.8 位于 legacy 归档。

训练数据 affect-supervision/2.8.1：每行独立 event_id、subject_id、scope、at、delta_seconds、blocks、appraisal、fast_before[5]、mood_before[3]、fast_after[5]、mood_after[3]、labels[24] 和 source。缺失监督为 null。训练/验证/测试按不重叠未来时间切分。工程资料必须 engineering_only=true；真实资料需独立测量协议、参数使用许可及原文绑定。目标是掩码复合高斯边际 NLL、多标签 BCE、策略 CE，不能把复合似然解释为证明各轴条件独立。

训练、校准、发布为不同操作；合成数据不能正式发布。当前校准阈值只是可复核工程门槛，不是心理学验证。正式人格仍由既有 P-D/P-E 管理，本模块从不写 HEXACO/ERQ/BEQ。
