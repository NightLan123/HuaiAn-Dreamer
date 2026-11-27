"""Read-only structured UI 3.0 data projections for HuaiAn Dreamer V2.8.3-dev.

Never calls LLMs, never fabricates data, and never mutates persistent state.
All projections derive strictly from existing SQLite tables and metadata.
"""
from __future__ import annotations
import copy
from .common import now

SCHWARTZ_CIRCLE_ORDER = [
    ('value.self_direction_thought', '自主思想', 'openness_to_change'),
    ('value.self_direction_action', '自主行动', 'openness_to_change'),
    ('value.stimulation', '刺激与新奇', 'openness_to_change'),
    ('value.hedonism', '享乐', 'openness_to_change'),
    ('value.achievement', '成就', 'self_enhancement'),
    ('value.power_dominance', '支配权力', 'self_enhancement'),
    ('value.power_resources', '资源权力', 'self_enhancement'),
    ('value.face', '维护社会形象', 'self_enhancement'),
    ('value.security_personal', '个人安全', 'conservation'),
    ('value.security_societal', '社会安全', 'conservation'),
    ('value.tradition', '传统', 'conservation'),
    ('value.conformity_rules', '遵守规则', 'conservation'),
    ('value.conformity_interpersonal', '人际顺从', 'conservation'),
    ('value.humility', '谦卑', 'conservation'),
    ('value.benevolence_dependability', '善意—可靠', 'self_transcendence'),
    ('value.benevolence_caring', '善意—关怀', 'self_transcendence'),
    ('value.universalism_tolerance', '普世—包容', 'self_transcendence'),
    ('value.universalism_concern', '普世—关切', 'self_transcendence'),
    ('value.universalism_nature', '普世—自然', 'self_transcendence'),
]

HEXACO_DOMAIN_META = [
    ('H', '诚实—谦逊', 'Honesty-Humility', ['hexaco.h.sincerity', 'hexaco.h.fairness', 'hexaco.h.greed_avoidance', 'hexaco.h.modesty']),
    ('E', '情绪性', 'Emotionality', ['hexaco.e.fearfulness', 'hexaco.e.anxiety', 'hexaco.e.dependence', 'hexaco.e.sentimentality']),
    ('X', '外向性', 'Extraversion', ['hexaco.x.social_self_esteem', 'hexaco.x.social_boldness', 'hexaco.x.sociability', 'hexaco.x.liveliness']),
    ('A', '宜人性', 'Agreeableness', ['hexaco.a.forgivingness', 'hexaco.a.gentleness', 'hexaco.a.flexibility', 'hexaco.a.patience']),
    ('C', '尽责性', 'Conscientiousness', ['hexaco.c.organization', 'hexaco.c.diligence', 'hexaco.c.perfectionism', 'hexaco.c.prudence']),
    ('O', '开放性', 'Openness', ['hexaco.o.aesthetic_appreciation', 'hexaco.o.inquisitiveness', 'hexaco.o.creativity', 'hexaco.o.unconventionality']),
]

PROJECTION_RULES = {
    'affect_2d_space': {
        'name': '二维愉悦度—唤醒度情绪空间投影 (Valence-Arousal Circumplex Projection)',
        'x_axis': {'field': 'valence', 'range': [-1.0, 1.0], 'center': 0.0, 'svg_formula': '(valence + 1.0) / 2.0'},
        'y_axis': {'field': 'arousal', 'range': [0.0, 1.0], 'center': 0.25, 'svg_formula': '1.0 - arousal'},
        'fast_vs_slow': '快情绪 (fast emotion) 反映当前事件即时反应与调节结果；慢心境 (slow mood) 反映较长时间尺度的背景心境基调。',
        'disclaimer': '展示坐标为内部情绪动力学状态向二维界面的正式线性投影，仅表示模型内部模拟状态，不等同于已证实的主观体验。',
    },
    'interpersonal_attachment_2d_space': {
        'name': '依恋与人际倾向二维空间投影 (Attachment & Interpersonal 2D Projection)',
        'attachment_plane': {
            'x_axis': {'fields': ['hexaco.e.dependence', 'hexaco.e.sentimentality'], 'label': '情感依恋与支持需要 (0..1)'},
            'y_axis': {'fields': ['hexaco.e.anxiety'], 'label': '焦虑敏感倾向 (0..1)'},
        },
        'interpersonal_plane': {
            'x_axis': {'fields': ['social.communion'], 'label': '亲和—联结倾向 Communion (0..1)'},
            'y_axis': {'fields': ['social.agency'], 'label': '能动—支配倾向 Agency (0..1)'},
        },
        'disclaimer': '读取 construct registry 中已登记的真实构念估计值；若任一维度尚无证据（null），保持未知状态，不以 0.5 假装已完成测量。',
    },
    'schwartz_value_circle': {
        'name': 'Schwartz 19 项精细价值环投影 (Refined Value Circumplex)',
        'quadrants': {
            'openness_to_change': '开放求变 (Openness to Change)',
            'self_enhancement': '自我提升 (Self-Enhancement)',
            'conservation': '保守秩序 (Conservation)',
            'self_transcendence': '自我超越 (Self-Transcendence)',
        },
        'disclaimer': '按理论相容与冲突环形顺序排列，半径反映当前构念估计值（0..1），未知项以虚线扇区标示。',
    },
}


def build_ui3_overview(app, base_state=None):
    """Build read-only structured projections for UI 3.0 views."""
    st = app.store
    engine = app.engine
    profile = base_state['profile'] if isinstance(base_state, dict) and 'profile' in base_state else engine.profile()
    owner = profile['id']
    trait_snap = (base_state or {}).get('trait_snapshot')
    if not trait_snap:
        from .traits import snapshot
        trait_snap = snapshot(profile)

    # 1. HEXACO 6-domain summary & facet details (preserving unknown when facets are unknown)
    facets = trait_snap.get('hexaco_facets') or {}
    hexaco_domains = []
    for code, name_zh, name_en, f_ids in HEXACO_DOMAIN_META:
        known_vals = [
            float(facets[fid]['estimate'])
            for fid in f_ids
            if isinstance(facets.get(fid), dict) and facets[fid].get('estimate') is not None
        ]
        domain_est = round(sum(known_vals) / len(known_vals), 4) if known_vals else None
        hexaco_domains.append({
            'code': code,
            'name_zh': name_zh,
            'name_en': name_en,
            'estimate': domain_est,
            'known_facet_count': len(known_vals),
            'total_facet_count': len(f_ids),
            'facets': [
                {
                    'id': fid,
                    **(facets.get(fid) or {'estimate': None, 'uncertainty': 1.0, 'source_type': 'unknown'}),
                }
                for fid in f_ids
            ],
        })

    # 2. Schwartz Value Circle projection
    val_map = trait_snap.get('value_priorities') or {}
    schwartz_values = []
    total_v = len(SCHWARTZ_CIRCLE_ORDER)
    for idx, (vid, label_zh, quad) in enumerate(SCHWARTZ_CIRCLE_ORDER):
        info = val_map.get(vid) or {}
        est = info.get('estimate')
        schwartz_values.append({
            'id': vid,
            'label': label_zh,
            'quadrant': quad,
            'angle_deg': round(idx * (360.0 / total_v), 2),
            'estimate': float(est) if est is not None else None,
            'uncertainty': info.get('uncertainty', 1.0),
            'source_type': info.get('source_type', 'unknown'),
        })

    # 3. Interpersonal & Attachment 2D projection
    interp = trait_snap.get('interpersonal_dispositions') or {}
    anx_info = facets.get('hexaco.e.anxiety') or {}
    dep_info = facets.get('hexaco.e.dependence') or {}
    sent_info = facets.get('hexaco.e.sentimentality') or {}
    ag_info = interp.get('social.agency') or {}
    com_info = interp.get('social.communion') or {}
    dep_vals = [float(x['estimate']) for x in (dep_info, sent_info) if x.get('estimate') is not None]
    attach_seeking = round(sum(dep_vals) / len(dep_vals), 4) if dep_vals else None
    attach_anxiety = float(anx_info['estimate']) if anx_info.get('estimate') is not None else None

    interpersonal_2d = {
        'attachment_space': {
            'anxiety': attach_anxiety,
            'seeking_closeness': attach_seeking,
            'anxiety_source': anx_info.get('source_type', 'unknown'),
            'closeness_source': dep_info.get('source_type') or sent_info.get('source_type') or 'unknown',
            'known': attach_anxiety is not None and attach_seeking is not None,
            'construct_refs': ['hexaco.e.anxiety', 'hexaco.e.dependence', 'hexaco.e.sentimentality'],
        },
        'interpersonal_circumplex': {
            'agency': float(ag_info['estimate']) if ag_info.get('estimate') is not None else None,
            'communion': float(com_info['estimate']) if com_info.get('estimate') is not None else None,
            'agency_source': ag_info.get('source_type', 'unknown'),
            'communion_source': com_info.get('source_type', 'unknown'),
            'known': ag_info.get('estimate') is not None and com_info.get('estimate') is not None,
            'construct_refs': ['social.agency', 'social.communion'],
        },
    }

    # 4. Affect 2D projection + multi-cause trajectory
    affect_state = (base_state or {}).get('affect_state') or engine.affect_state()
    p281 = st.meta('pmm281_affect') or {}
    emo = (affect_state or {}).get('emotion') or {}
    mood = (affect_state or {}).get('mood') or {}

    # Also check latest active stream in pmm281_affect if legacy emotion is None
    latest_stream_281 = None
    if isinstance(p281.get('streams'), dict) and p281['streams']:
        ordered_streams = sorted(p281['streams'].values(), key=lambda r: float(r.get('updated_at') or 0.0), reverse=True)
        latest_stream_281 = ordered_streams[0]

    fast_v = emo.get('valence')
    fast_a = emo.get('arousal')
    fast_d = emo.get('dominance')
    fast_s = emo.get('stress')
    fast_g = emo.get('engagement')
    if fast_v is None and latest_stream_281 and isinstance(latest_stream_281.get('observed'), dict):
        obs = latest_stream_281['observed']
        fast_v = obs.get('valence')
        fast_a = obs.get('arousal')
        fast_d = obs.get('dominance')
        fast_s = obs.get('stress')
        fast_g = obs.get('engagement')

    mood_v = mood.get('valence')
    mood_a = mood.get('arousal')
    mood_d = mood.get('dominance')
    if mood_v is None and latest_stream_281 and isinstance(latest_stream_281.get('mood_observed'), dict):
        mobs = latest_stream_281['mood_observed']
        mood_v = mobs.get('valence')
        mood_a = mobs.get('arousal')
        mood_d = mobs.get('dominance')

    trajectory = []
    # Collect from pmm_affect trajectory
    for pt in ((affect_state or {}).get('trajectory') or [])[-40:]:
        if isinstance(pt, dict):
            trajectory.append({
                'at': pt.get('at') or pt.get('updated_at'),
                'valence': pt.get('valence'),
                'arousal': pt.get('arousal'),
                'dominance': pt.get('dominance'),
                'mood_valence': pt.get('mood_valence'),
                'mood_arousal': pt.get('mood_arousal'),
                'cause_category': pt.get('cause') or pt.get('source_type') or 'inbound_event_reaction',
                'event_id': pt.get('event_id'),
                'summary': pt.get('reason') or pt.get('source_type') or '情绪状态更新',
            })
    # Enrich from pmm281_affect streams (events + expression_feedback_events)
    if isinstance(p281.get('streams'), dict):
        for s_row in p281['streams'].values():
            if not isinstance(s_row, dict):
                continue
            for ev_id, ev_entry in (s_row.get('events') or {}).items():
                res = (ev_entry or {}).get('result') if isinstance(ev_entry, dict) else None
                if isinstance(res, dict) and isinstance(res.get('affect_observed'), dict):
                    ao = res['affect_observed']
                    mo = res.get('mood_observed') or {}
                    trajectory.append({
                        'at': s_row.get('updated_at') or now(),
                        'valence': ao.get('valence'),
                        'arousal': ao.get('arousal'),
                        'dominance': ao.get('dominance'),
                        'stress': ao.get('stress'),
                        'engagement': ao.get('engagement'),
                        'mood_valence': mo.get('valence'),
                        'mood_arousal': mo.get('arousal'),
                        'cause_category': 'inbound_event_reaction' if res.get('appraisal_used') else 'time_propagation',
                        'event_id': ev_id,
                        'summary': '事件评价触发快情绪反应与时间演化' if res.get('appraisal_used') else '现实时间松弛演化',
                    })
            for fb_id, fb_entry in (s_row.get('expression_feedback_events') or {}).items():
                res = (fb_entry or {}).get('result') if isinstance(fb_entry, dict) else None
                if isinstance(res, dict) and isinstance(res.get('affect_observed'), dict):
                    ao = res['affect_observed']
                    mo = res.get('mood_observed') or {}
                    trajectory.append({
                        'at': fb_entry.get('at') or s_row.get('updated_at') or now(),
                        'valence': ao.get('valence'),
                        'arousal': ao.get('arousal'),
                        'dominance': ao.get('dominance'),
                        'stress': ao.get('stress'),
                        'engagement': ao.get('engagement'),
                        'mood_valence': mo.get('valence'),
                        'mood_arousal': mo.get('arousal'),
                        'cause_category': 'internal_expression_feedback',
                        'internal_event_kind': res.get('internal_event_kind'),
                        'outcome': res.get('outcome'),
                        'event_id': fb_id,
                        'summary': f"表达结果内部反馈 ({res.get('outcome', 'expression_feedback')})",
                    })
    trajectory.sort(key=lambda x: float(x.get('at') or 0.0))
    trajectory = trajectory[-48:]

    dx_val = 0.0
    dy_aro = 0.0
    if len(trajectory) >= 2 and trajectory[-1].get('valence') is not None and trajectory[-2].get('valence') is not None:
        dx_val = round(float(trajectory[-1]['valence']) - float(trajectory[-2]['valence']), 4)
        dy_aro = round(float(trajectory[-1].get('arousal') or 0.0) - float(trajectory[-2].get('arousal') or 0.0), 4)

    affect_2d = {
        'fast_emotion': {
            'known': fast_v is not None and fast_a is not None,
            'valence': fast_v,
            'arousal': fast_a,
            'dominance': fast_d,
            'stress': fast_s,
            'engagement': fast_g,
            'x_norm': round((float(fast_v) + 1.0) / 2.0, 4) if fast_v is not None else None,
            'y_norm': round(float(fast_a), 4) if fast_a is not None else None,
            'source_type': emo.get('source_type', 'unknown'),
            'last_updated': emo.get('last_updated'),
        },
        'slow_mood': {
            'known': mood_v is not None and mood_a is not None,
            'valence': mood_v,
            'arousal': mood_a,
            'dominance': mood_d,
            'x_norm': round((float(mood_v) + 1.0) / 2.0, 4) if mood_v is not None else None,
            'y_norm': round(float(mood_a), 4) if mood_a is not None else None,
            'source_type': mood.get('source_type', 'unknown'),
            'updated_at': mood.get('updated_at'),
        },
        'movement': {
            'dx_valence': dx_val,
            'dy_arousal': dy_aro,
            'latest_cause': trajectory[-1]['cause_category'] if trajectory else None,
            'latest_summary': trajectory[-1]['summary'] if trajectory else '暂无近期状态跃迁记录',
        },
        'trajectory': trajectory,
    }

    # 5. Expressive Drive detailed read-only projection
    ed_raw = st.meta('pmm283_expression_drive') or {}
    ed_streams = []
    all_unfinished_motives = []
    all_motives_list = []
    for skey, srow in (ed_raw.get('streams') or {}).items():
        if not isinstance(srow, dict):
            continue
        ident = srow.get('identity') or {}
        m_list = []
        for mid, mobj in (srow.get('motives') or {}).items():
            if not isinstance(mobj, dict):
                continue
            item = copy.deepcopy(mobj)
            item['stream_key'] = skey
            item['scope'] = ident.get('scope')
            item['person_id'] = ident.get('person_id')
            m_list.append(item)
            all_motives_list.append(item)
            if item.get('status') in ('pending', 'deferred', 'partially_satisfied'):
                all_unfinished_motives.append(item)
        m_list.sort(key=lambda x: float(x.get('updated_at') or 0.0), reverse=True)
        ed_streams.append({
            'stream_key': skey,
            'scope': ident.get('scope'),
            'person_id': ident.get('person_id'),
            'session_id': ident.get('session_id'),
            'activation': srow.get('activation'),
            'urgency': srow.get('urgency'),
            'persistence': srow.get('persistence'),
            'expressive_intent': srow.get('expressive_intent'),
            'baseline': copy.deepcopy(srow.get('baseline') or {}),
            'updated_at': srow.get('updated_at'),
            'state_revision': srow.get('state_revision'),
            'active_motive_id': srow.get('active_motive_id'),
            'motives': m_list,
            'event_correlations': list((srow.get('event_correlations') or {}).values())[-20:],
        })
    ed_streams.sort(key=lambda x: float(x.get('updated_at') or 0.0), reverse=True)
    all_unfinished_motives.sort(key=lambda x: (float(x.get('activation') or 0.0), float(x.get('updated_at') or 0.0)), reverse=True)
    all_motives_list.sort(key=lambda x: float(x.get('updated_at') or 0.0), reverse=True)

    # 6. Pending Actions (strictly real items; empty list when none)
    pending_actions = []
    cfg = (base_state or {}).get('config') or app.config.public()
    if not cfg.get('model'):
        pending_actions.append({
            'id': 'model_general_missing',
            'kind': 'config',
            'severity': 'warning',
            'title': '对话生成模型尚未配置',
            'detail': '请前往“连接与设置 → 模型配置中心”填写并测试 General LLM。',
            'target_view': 'ui3-settings',
            'target_tab': 'ui3-settings-models',
        })
    if cfg.get('pmm', {}).get('mode') == 'api' and not (cfg.get('pmm', {}).get('api') or {}).get('model'):
        pending_actions.append({
            'id': 'model_pmm_missing',
            'kind': 'config',
            'severity': 'warning',
            'title': '内部心理理解模型 (PMM) 尚未配置',
            'detail': '当前 PMM 为 API 模式，请配置 PMM 推理模型或切换至本地数值模式。',
            'target_view': 'ui3-settings',
            'target_tab': 'ui3-settings-models',
        })
    trait_rev = (base_state or {}).get('trait_review') or engine.review_traits(False)
    trait_cands = (trait_rev or {}).get('candidates') or []
    if trait_cands:
        pending_actions.append({
            'id': 'trait_candidates_pending',
            'kind': 'review',
            'severity': 'info',
            'title': f'有 {len(trait_cands)} 项长期人格倾向候选待审阅',
            'detail': '系统已根据互动经历提炼出有证据支持的人格候选，需审阅确认后才会更新长期人格。',
            'target_view': 'ui3-studio',
            'target_tab': 'ui3-studio-review',
        })
    prag = (base_state or {}).get('pragmatics') or {}
    prag_cands = [c for c in (prag.get('learning_candidates') or []) if isinstance(c, dict) and c.get('status') in (None, 'pending', 'candidate')]
    if prag_cands:
        pending_actions.append({
            'id': 'pragmatic_candidates_pending',
            'kind': 'review',
            'severity': 'info',
            'title': f'有 {len(prag_cands)} 项语言表达习惯候选待确认',
            'detail': '可在成长工作室审阅并决定是否应用到角色语言习惯。',
            'target_view': 'ui3-studio',
            'target_tab': 'ui3-studio-review',
        })
    learn_center = (base_state or {}).get('learning_center') or {}
    pending_jobs = [j for j in (learn_center.get('jobs') or []) if isinstance(j, dict) and j.get('status') in ('pending', 'paused', 'running', 'review_required')]
    if pending_jobs:
        pending_actions.append({
            'id': 'learning_jobs_pending',
            'kind': 'learning',
            'severity': 'info',
            'title': f'有 {len(pending_jobs)} 个持续学习/蒸馏任务待继续或核对',
            'detail': '前往成长工作室查看任务进度与提炼结果。',
            'target_view': 'ui3-studio',
            'target_tab': 'ui3-studio-jobs',
        })
    recoverable = engine.journal.recoverable() if hasattr(engine, 'journal') else []
    if recoverable:
        pending_actions.append({
            'id': 'execution_recoverable',
            'kind': 'Alert',
            'severity': 'warning',
            'title': f'有 {len(recoverable)} 条已收到回执的消息待恢复本地状态',
            'detail': '可在连接与设置或研究工作台中执行一键恢复，不会重复发送消息。',
            'target_view': 'ui3-settings',
            'target_tab': 'ui3-settings-qq',
        })

    # 7. Memory & Relationship Graph (Nomi-style real network projection)
    nodes = [{
        'id': 'self:' + owner,
        'kind': 'self',
        'label': profile.get('name') or '当前角色',
        'subtitle': '核心角色主体',
        'weight': 1.0,
    }]
    edges = []
    seen_nodes = {'self:' + owner}

    dyads = (base_state or {}).get('dyads') or st.meta('pmm_dyads') or {}
    interlocutors = (base_state or {}).get('interlocutors') or st.meta('pmm_interlocutors') or {}
    for dkey, dval in dyads.items():
        if not isinstance(dval, dict):
            continue
        person_id = str(dval.get('person_id') or dval.get('target_id') or dkey.split('|')[-1])
        scope_id = str(dval.get('context_id') or dkey.split('|')[0])
        nid = 'person:' + person_id
        other_prof = interlocutors.get(f'{scope_id}|{person_id}') or interlocutors.get(person_id) or {}
        if nid not in seen_nodes:
            seen_nodes.add(nid)
            nodes.append({
                'id': nid,
                'kind': 'person',
                'label': other_prof.get('name') or person_id,
                'person_id': person_id,
                'scope': scope_id,
                'trust': dval.get('trust'),
                'familiarity': dval.get('familiarity'),
                'affection': dval.get('affection', dval.get('affiliation')),
                'interactions': dval.get('interactions', 0),
                'weight': min(1.0, 0.4 + 0.05 * int(dval.get('interactions') or 0)),
            })
        edges.append({
            'source': 'self:' + owner,
            'target': nid,
            'kind': 'dyad_relation',
            'label': f"互动 {dval.get('interactions', 0)} 次",
            'strength': float(dval.get('familiarity') or 0.35),
        })

    raw_memories = st.memories()
    for mem in raw_memories[:28]:
        mid = 'mem:' + str(mem['id'])
        if mid not in seen_nodes:
            seen_nodes.add(mid)
            text_clean = str(mem.get('content') or '').replace('\n', ' ').strip()
            nodes.append({
                'id': mid,
                'memory_id': mem['id'],
                'kind': mem.get('kind') or 'episode',
                'label': text_clean[:22] + ('…' if len(text_clean) > 22 else ''),
                'content': text_clean[:300],
                'scope': mem.get('scope'),
                'importance': mem.get('importance', 0.5),
                'created_at': mem.get('created_at'),
                'weight': float(mem.get('importance') or 0.5),
            })
        # Connect memory to associated person if scope matches a person node, else to self
        linked_person = None
        m_scope = str(mem.get('scope') or '')
        for n in nodes:
            if n['kind'] == 'person' and (n.get('scope') == m_scope or (m_scope.endswith(str(n.get('person_id') or '').split(':')[-1]) and n.get('person_id'))):
                linked_person = n['id']
                break
        edges.append({
            'source': linked_person or ('self:' + owner),
            'target': mid,
            'kind': 'memory_anchor',
            'label': mem.get('kind') or 'memory',
            'strength': float(mem.get('importance') or 0.5),
        })

    for um in all_unfinished_motives[:10]:
        umid = 'motive:' + str(um['motive_id'])
        if umid not in seen_nodes:
            seen_nodes.add(umid)
            topic_lbl = (um.get('content_anchor') or {}).get('topic') or '待表达事项'
            nodes.append({
                'id': umid,
                'motive_id': um['motive_id'],
                'kind': 'motive',
                'label': topic_lbl[:20],
                'intended_goal': (um.get('intended_expression') or {}).get('intended_goal'),
                'status': um.get('status'),
                'activation': um.get('activation'),
                'weight': float(um.get('activation') or 0.5),
            })
            p_nid = 'person:' + str(um.get('person_id') or '')
            target_anchor = p_nid if p_nid in seen_nodes else ('self:' + owner)
            edges.append({
                'source': target_anchor,
                'target': umid,
                'kind': 'expressive_motive',
                'label': '待表达目标',
                'strength': float(um.get('activation') or 0.5),
            })

    return {
        'schema': 'ui3-overview/3.0',
        'projection_rules': PROJECTION_RULES,
        'hexaco_domains': hexaco_domains,
        'schwartz_values': schwartz_values,
        'interpersonal_2d': interpersonal_2d,
        'affect_2d': affect_2d,
        'expressive_drive_detail': {
            'streams': ed_streams,
            'unfinished_motives': all_unfinished_motives,
            'all_motives': all_motives_list[:30],
            'recent_history': copy.deepcopy((ed_raw.get('history') or [])[-30:]),
        },
        'pending_actions': pending_actions,
        'memory_relation_graph': {
            'nodes': nodes,
            'edges': edges,
        },
    }
