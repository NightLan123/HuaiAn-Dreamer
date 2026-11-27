/* Display labels only. Original identifiers stay in payloads and detail drawers. */
(function (global) {
  'use strict';
  const labels = {
    INITIATE: '想主动聊聊', LISTEN: '正在倾听', RESPOND: '准备回应', FOLLOW_UP: '想继续话题', CLARIFY: '想再问清楚', SILENT: '暂时安静', WAIT: '等待合适时机',
    TAKE_TURN: '准备接话', BACKCHANNEL: '简短回应与倾听', DEFER: '等待合适时机',
    reply: '回应', clarify: '询问确认', silence: '保持安静', defer: '稍后回应', refuse: '表达拒绝', initiate: '主动交谈',
    unconfigured: '尚未配置', saved_not_tested: '已保存，尚无任务调用记录', tested: '示例任务校验通过', connected_only: '服务已连通，实际任务待确认', connection_failed: '服务连接失败', last_call_succeeded: '最近调用成功', last_call_failed: '最近调用失败',
    current_evidence: '本轮原文有据评价', retained_previous_valid_evidence: '沿用同轮上次有效评价', local_only: '按路由使用本地判断', local_fallback: '在线评价失败，采用本地判断', no_grounded_appraisal: '本次没有有据数值评价', unrecorded: '评价来源未记录',
    adoption_unrecorded: '协调环节失败，评价采纳情况未知',
    healthy: '连接正常', configured: '已配置', unavailable: '暂不可用', unknown: '待观察', running: '进行中', success: '成功', failed: '失败', pending: '等待处理',
    uncalibrated: '尚未完成校准', uncalibrated_engineering_initial: '初始参数，尚未校准', no_published_validated_network: '尚无通过校准的已发布模型',
    pmm_component: '心理处理组件', service: '服务连接', external: '外部服务', local: '本地服务',
    platform_identifier: '已记录平台账号', local_identifier_unverified: '本地身份待确认', owner_annotated: '已注明身份', disputed: '存在争议',
    semantic: '知识', episodic: '经历', gist: '摘要', procedural: '习惯', emotional: '情绪记忆',
    friend: '朋友', family: '家人', colleague: '同事', acquaintance: '相识', conflict: '冲突', other: '其他关系',
    observed: '已有观察', confirmed: '已确认', unverified: '待核实', retracted: '已撤回', self_report: '本人陈述', third_party_report: '他人转述',
    owner_seed: '初始设定', promoted_evidence: '证据积累', experience_derived: '经历形成的倾向', role_estimate: '带不确定度的角色倾向', questionnaire: '问卷设定',
    obstructed_expression: '表达受阻', delivered: '表达已送达', partial: '部分送达', LOCAL_COMMITTED: '已保存到本地',
    active: '活跃', paused: '已暂停', completed: '已完成', cancelled: '已取消', candidate_only: '仅生成候选', shadow: '观察模式', full: '完整模式',
    delivered_full: '已完整送达', delivered_partial: '部分送达', proactive_deferred: '稍后主动表达', deferred_wait: '等待表达',
    REPLY: '准备回应', NO_ACTION: '暂不行动', VALIDATION_FAILED: '本次评估未完成', PERMISSION_WITHDRAWN: '权限已撤回',
    numerical: '数值计算', local_numeric: '本地数值计算', rule_based: '规则处理', not_executed: '未参与', skipped: '本次跳过',
    observed_presence: '在此会话中出现过', mentioned_third_party: '记录中提及的人物', ready: '已就绪', recording: '记录中',
    empty: '暂无记录', resolved: '已结束', backchannel_delivered: '附和已送达，继续倾听', listening_after_acknowledgement: '已附和，等待对方继续', satisfied: '已完成', deferred: '已暂缓', partially_satisfied: '部分完成', abandoned: '已放弃',
    emotion_regulation_suppression: '正在调节情绪，暂缓表达', high_baseline_only_no_concrete_expressive_motive: '尚无具体想说的内容', expressive_intent_closed: '当前没有发起表达的意图',
    speaker_turn_incomplete_waiting_for_continuation: '等待对方把话说完', expressive_restraint_or_timing: '等待更合适的表达时机', active_listening_floor_yielded: '正在倾听，先让对方说',
    expired_by_time_decay: '动机随时间减弱并结束', awaiting_user_reply_for_next_step: '等待对方回应后继续', turn_taking_wait: '等待接话时机', policy_or_regulation_restraint: '表达受规则或情绪调节限制',
    awaiting_proactive_window: '等待主动交谈的时机', explicitly_abandoned: '已明确放下', low_drive_no_need_to_retain: '表达意愿已减弱',
    secondary_sub_event_tracked_independently: '相关话题分别记录', proactive_opportunities_exhausted_or_decayed: '表达时机已结束或动机已减弱', proactive_defer_limit_reached: '多次暂缓后结束本次表达',
    proactive_opportunity_deferred_for_reevaluation: '暂缓后重新判断时机', proactive_send_or_inspection_failed_retained: '本次未能送达，保留待表达内容'
  };
  function label(value) {
    if (value === true) return '是';
    if (value === false) return '否';
    if (value == null || value === '') return '未提供';
    return labels[String(value)] || String(value);
  }
  function state(value) { return labels[value] || (/^[a-z][a-z0-9_-]*$/i.test(String(value || '')) ? '状态详情可查看' : label(value)); }
  function person(value) { return String(value || '').replace(/^qq:/, 'QQ ').replace(/^web:owner$/, '网页访客') || '未注明对象'; }
  function scope(value) {
    const s = String(value || '');
    if (s === 'private:web:owner') return '网页会话';
    if (s.startsWith('private:qq:')) return 'QQ 私聊 · ' + s.slice(11);
    if (s.startsWith('group:qq:')) return 'QQ 群聊 · ' + s.slice(9);
    if (s.startsWith('group:')) return '群聊 · ' + s.slice(6);
    if (s.startsWith('private:')) return '私聊 · ' + person(s.slice(8));
    return s ? '其他会话' : '未注明会话';
  }
  function endpoint(value) {
    const path = String(value || '').split('?')[0];
    const titles = { '/api/state': '角色与当前状态', '/api/ui3/overview': '首页概览', '/api/affect': '情绪观察', '/api/cognition': '认知记录', '/api/pmm283/expressive-drive': '表达欲状态', '/api/pmm283/expressive-drive/advance': '推进表达状态', '/api/pmm281/status': '心理模型状态', '/api/pmm28/status': '数值模型状态', '/api/pmm28/traces': '心理处理记录', '/api/memories': '记忆列表', '/api/learning': '学习任务', '/api/learning/activities': '学习记录', '/api/relations': '互动关系', '/api/social-graph': '关系网络', '/api/people': '人物档案', '/api/persona/revisions': '版本记录', '/api/de/turns': '互动经历', '/api/qq/status': 'QQ 状态', '/api/config': '保存设置', '/api/persona/settings': '保存角色资料', '/api/traits/disposition': '保存人格设定', '/api/session': '创建会话', '/api/messages': '读取消息', '/api/bootstrap': '连接本地服务' };
    return titles[path] || (path.startsWith('/api/jobs/') ? '任务进度' : '其他请求');
  }
  global.DisplayText = { label, state, person, scope, endpoint };
})(window);
