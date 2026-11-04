"""Implementation inventory, not a vendor connectivity or psychological validity claim."""
from .common import VERSION

def report(config,model):
    mode=config['pmm']['mode'];numeric=mode=='learned'
    numeric_kind='learned_weights_loaded' if numeric else 'implemented_rule'
    modules={
        'general_understanding':{'mechanisms':['api_inference']},
        'pmm_condition':{'mechanisms':['api_inference' if mode=='api' else numeric_kind],
                         'trained_steps':model.get('steps',0) if numeric else 0,
                         'trained_constructs':model.get('trained_features',0) if numeric else 0},
        'trait_affect_separation':{'mechanisms':['implemented_rule','api_inference'],'contract':'trait-affect/1','note':'人格候选独立晋升；连续时间情绪/心境；表达与内部估计分开'},
        'beq_erq_dispositions':{'mechanisms':['implemented_rule'],'neural_training_steps':0,'note':'显式长期习惯条件，不宣称旧93列神经网络已训练新增字段'},
        'emotion_catalog_24':{'mechanisms':['implemented_rule','api_inference'],'schema':'emotion-catalog/2','new_neural_heads_trained':False,'note':'独立扩展类别，未追加旧93列；未知和多类激活并存，时间参数未校准'},
        'scoped_learning_jobs':{'mechanisms':['implemented_rule','api_inference'],'schema':'learning-job/1','note':'具体原文预览、审核、预算与续跑、写入差异和受版本保护的回滚；参数训练另行选择'},
        'social_graph':{'mechanisms':['implemented_rule','api_inference'],'schema':'social-graph/1','note':'按范围存有向关系陈述、来源、争议与人工核验；共现不等于友谊'},
        'boundary_failure_isolation':{'mechanisms':['implemented_rule'],'note':'无损结构归一、一次局部重试、不可用状态；不接受伪造引用'},
        'canonical_state_update':{'mechanisms':['implemented_rule','api_inference'], 'note':'有来源的 API 提议与确定性门控；未宣称已学习长期更新函数'},
        'retrieval':{'mechanisms':['implemented_rule']+([numeric_kind] if numeric else []),'note':'范围过滤、混合打分与可选数值编码'},
        'perspective_projection':{'mechanisms':['implemented_rule']+([numeric_kind] if numeric else []),'note':'按已知构念投影，协商由独立开关控制'},
        'action_arbitration':{'mechanisms':['implemented_rule','api_inference'],'note':'效用聚合及不可绕过的知识/许可检查'},
        'language_style':{'mechanisms':['implemented_rule','api_inference']+([numeric_kind] if numeric else []),'note':'统计、授权案例和数值风格头；完整关系条件化语用模型仍不齐全'},
        'delivery_commit':{'mechanisms':['implemented_rule'],'note':'Outbox、真实回执和幂等提交'},
        'template_clone':{'mechanisms':['implemented_rule'],'note':'新身份、空关系、全新权重及连接'},
        'proactive_full_boundary_loop':{'mechanisms':['not_implemented'],'note':'现有主动发送有边界上下文与候选检查，未接完整数值 BRM 反馈闭环'},
        'semantic_group_disentanglement':{'mechanisms':['not_implemented'],'note':'目前仅支持显式引用线程和说话人聚合'},
        'video_audio_understanding':{'mechanisms':['not_implemented']},
        'training_cancel_and_evaluation_gated_publish':{'mechanisms':['not_implemented']},
        'activation_steering':{'mechanisms':['not_implemented']},
    }
    full=config.get('pmm281',{}).get('mode')=='full'
    if full:
        mode='full';numeric=True
        modules.update(pmm_condition={'mechanisms':['api_inference','numeric_forward'],'trained_steps':model.get('steps',0),'contract':'pmm-coordinator/2.8.1'},
            trait_affect_separation={'mechanisms':['latent_ou_and_event_jump','trainable_parameters'],'contract':'affect-state/2.8.1'},
            emotion_catalog_24={'mechanisms':['multilabel_sigmoid'],'schema':'emotion-catalog/2','calibration':model.get('emotion_calibration')},
            internal_negotiation_B={'mechanisms':['separate_api_task'],'shared_service':config['pmm281']['b_share_a'],'policy':config['pmm281']['b_policy']},
            affect_training={'mechanisms':['pytorch_gradient','held_out_release_gate'],'active_steps':model.get('emotion_steps',0)})
    return {'schema':'implementation-capabilities/1','version':VERSION,'pmm_mode':mode,'modules':modules,
            'state_updates_enabled':True,'parameter_training_available':numeric,
            'automatic_adapter_updates_enabled':not full and numeric and config['online_learning'],
            'mock_fallback':False,'psychological_validity_established':False,
            'note':'表示代码实现类型；加载权重不等于所有头已训练，API 配置不等于已连通，未完成真人纵向心理验证。'}
