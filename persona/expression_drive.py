"""Expressive Drive (表达欲动态中介机制) — V2.8.3 core state, dynamics, and persistence.

Models how stable personality constructs, fast emotion, slow mood, cognitive
appraisal, interpersonal relationship, dialogue floor context, and prior
unfinished expressive motives jointly form and evolve an agent's dynamic
motivation to express (Activation, Urgency, Persistence) and map to six
expressive behavioral intentions:
    LISTEN, BACKCHANNEL, TAKE_TURN, DEFER, CLOSE, INITIATE.

All initial parameter matrices are explicit, replaceable engineering priors
marked as uncalibrated, never claimed as empirically validated psychological
constants. Reading state, advancing real time, evaluating an event jump, and
committing state after execution/delivery receipts are strictly separated.
"""
from __future__ import annotations
import copy, math, re
import numpy as np
from .common import now, uid, clamp
from .registry import digest, APPRAISAL_IDS
from .affect_dynamics_v2 import seconds, iso
from .pmm_contracts import BLOCK_IDS, construct_blocks, validate_blocks

KEY = 'pmm283_expression_drive'
SCHEMA = 'expressive-drive/2.8.3'
MODEL_FORMAT = 'expressive-drive-model/2.8.3'

INTENTS = ('LISTEN', 'BACKCHANNEL', 'TAKE_TURN', 'DEFER', 'CLOSE', 'INITIATE')
MOTIVE_STATUSES = ('pending', 'deferred', 'partially_satisfied', 'satisfied', 'abandoned')

ALL_CONSTRUCT_IDS = tuple(
    cid for block in ('H', 'V', 'I', 'L', 'D') for cid in BLOCK_IDS[block]
)
N_THETA = len(ALL_CONSTRUCT_IDS)  # 68 canonical long-term constructs
N_EMOTION = 7                     # valence, arousal, dominance, stress, engagement, suppression, reappraisal
N_MOOD = 3                        # mood valence, arousal, dominance
N_APPRAISAL = 11                  # goal_rel, personal_rel, novelty, urgency, emotional_sal, conflict, consequence, needs_answer, task, disengagement, trait_topic_resonance
N_RELATION = 5                    # trust, familiarity, affection, interaction_density, conflict_flag
N_CONTEXT = 6                     # turn_complete, addressed, is_private, partner_closing, obligation, interruption_cost
N_RESIDUAL = 5                    # max_act, max_urg, max_pers, topic_overlap, deferred_pressure

SHAPES = {
    'b0': (3,),
    'W_theta': (3, N_THETA),
    'W_e': (3, N_EMOTION),
    'W_m': (3, N_MOOD),
    'W_q': (3, N_APPRAISAL),
    'W_r': (3, N_RELATION),
    'W_c': (3, N_CONTEXT),
    'W_u': (3, N_RESIDUAL),
}


def _sigmoid(x):
    x = np.clip(np.asarray(x, dtype=float), -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-x))


def _logit(p, eps=1e-6):
    p = min(1.0 - eps, max(eps, float(p)))
    return math.log(p / (1.0 - p))


def seal_model(model):
    out = copy.deepcopy(model)
    out.pop('sha256', None)
    out['sha256'] = digest(out)
    return out


def initial_model(subject_id):
    """Create replaceable initial parameter matrices conditioned on existing constructs.

    Unobserved traits stay masked (0 contribution). Coefficients are explicit
    engineering initializations, not calibrated psychometric laws.
    """
    if not isinstance(subject_id, str) or not subject_id:
        raise ValueError('ExpressiveDrive model requires subject_id')
    idx = {cid: i for i, cid in enumerate(ALL_CONSTRUCT_IDS)}
    w_theta = np.zeros((3, N_THETA), dtype=float)

    # Row 0: Activation baseline weights; Row 1: Urgency weights; Row 2: Persistence weights
    trait_priors = {
        'hexaco.x.sociability':        (0.32,  0.18,  0.10),
        'hexaco.x.liveliness':         (0.28,  0.22,  0.12),
        'hexaco.x.social_boldness':    (0.26,  0.24,  0.08),
        'hexaco.x.expressiveness':     (0.30,  0.20,  0.06),
        'hexaco.o.inquisitiveness':    (0.28,  0.10,  0.30),
        'hexaco.o.creativity':         (0.16,  0.05,  0.18),
        'hexaco.c.prudence':           (-0.08, -0.32, 0.15),
        'hexaco.c.diligence':          (0.12,  0.04,  0.34),
        'hexaco.c.organization':       (0.06, -0.06,  0.22),
        'hexaco.a.patience':           (-0.05, -0.30, 0.16),
        'hexaco.a.gentleness':         (0.04, -0.18,  0.08),
        'hexaco.e.anxiety':            (0.06,  0.16,  0.20),
        'hexaco.e.sentimentality':     (0.18,  0.10,  0.22),
        'hexaco.altruism':             (0.16,  0.08,  0.20),
        'value.self_direction_thought':(0.22,  0.08,  0.28),
        'value.stimulation':           (0.20,  0.18,  0.06),
        'value.benevolence_care':      (0.20,  0.12,  0.24),
        'value.benevolence_dependability': (0.14, 0.06, 0.28),
        'value.conformity_interpersonal': (-0.12, -0.24, 0.04),
        'social.agency':               (0.30,  0.26,  0.20),
        'social.communion':            (0.26,  0.12,  0.26),
        'style.initiation_rate':       (0.34,  0.24,  0.18),
        'style.verbosity':             (0.22,  0.10,  0.14),
        'style.directness':            (0.18,  0.24,  0.10),
        'style.warmth':                (0.18,  0.08,  0.16),
        'style.question_rate':         (0.16,  0.14,  0.16),
        'beq.positive_expressivity':   (0.26,  0.16,  0.10),
        'beq.negative_expressivity':   (0.22,  0.20,  0.14),
        'beq.impulse_strength':        (0.28,  0.36,  0.12),
        'erq.cognitive_reappraisal':   (0.04, -0.18,  0.14),
        'erq.expressive_suppression':  (-0.24, -0.38, 0.22),
        'panas.positive_affect':       (0.24,  0.14,  0.16),
        'panas.negative_affect':       (0.08,  0.12,  0.20),
    }
    for cid, (wa, wu, wp) in trait_priors.items():
        if cid in idx:
            j = idx[cid]
            w_theta[0, j] = wa
            w_theta[1, j] = wu
            w_theta[2, j] = wp

    # Emotion weights: [valence, arousal_dev, dominance_dev, stress_dev, engagement_dev, suppression, reappraisal]
    w_e = np.array([
        [ 0.18,  0.55,  0.22, -0.18,  0.68, -0.28, -0.06],  # Activation
        [ 0.08,  0.65,  0.28, -0.25,  0.52, -0.62, -0.22],  # Urgency (suppression strongly lowers urgency)
        [ 0.10,  0.30,  0.18,  0.16,  0.58,  0.32,  0.12],  # Persistence (suppression/stress keeps unexpressed motive alive)
    ], dtype=float)

    # Mood weights: [valence, arousal_dev, dominance_dev]
    w_m = np.array([
        [ 0.22,  0.25,  0.16],
        [ 0.12,  0.22,  0.14],
        [ 0.16,  0.18,  0.20],
    ], dtype=float)

    # Appraisal weights:
    # [goal_rel, personal_rel, novelty, urgency, emotional_sal, conflict, consequence, needs_answer, task, disengagement, trait_topic_resonance]
    w_q = np.array([
        [ 0.48,  0.62,  0.34,  0.32,  0.44,  0.18,  0.20,  0.52,  0.42, -0.75,  0.65],  # Activation
        [ 0.36,  0.42,  0.22,  0.68,  0.46, -0.20, -0.16,  0.60,  0.38, -0.80,  0.42],  # Urgency
        [ 0.52,  0.60,  0.28,  0.24,  0.42,  0.34,  0.38,  0.44,  0.46, -0.65,  0.58],  # Persistence
    ], dtype=float)

    # Relationship weights: [trust_dev, familiarity, affection_dev, interaction_density, conflict_flag]
    w_r = np.array([
        [ 0.28,  0.35,  0.30,  0.18, -0.16],
        [ 0.18,  0.24,  0.20,  0.12, -0.28],
        [ 0.26,  0.32,  0.28,  0.20,  0.14],
    ], dtype=float)

    # Context weights: [turn_complete, addressed, is_private, partner_closing, obligation, interruption_cost]
    w_c = np.array([
        [ 0.24,  0.46,  0.18, -0.55,  0.48, -0.32],
        [ 0.56,  0.52,  0.22, -0.65,  0.54, -0.72],
        [ 0.08,  0.28,  0.14, -0.42,  0.36,  0.18],
    ], dtype=float)

    # Residual unfinished motive weights: [max_act, max_urg, max_pers, topic_overlap, deferred_pressure]
    w_u = np.array([
        [ 0.45,  0.18,  0.22,  0.52,  0.26],
        [ 0.28,  0.46,  0.18,  0.48,  0.32],
        [ 0.30,  0.14,  0.54,  0.42,  0.28],
    ], dtype=float)

    params = {
        'b0': [-0.35, -0.55, -0.20],
        'W_theta': w_theta.tolist(),
        'W_e': w_e.tolist(),
        'W_m': w_m.tolist(),
        'W_q': w_q.tolist(),
        'W_r': w_r.tolist(),
        'W_c': w_c.tolist(),
        'W_u': w_u.tolist(),
    }
    return seal_model({
        'format': MODEL_FORMAT,
        'subject_id': subject_id,
        'revision': 0,
        'steps': 0,
        'parameters': params,
        'calibration': {
            'status': 'uncalibrated_engineering_initial',
            'psychometric_claim': False,
            'note': 'Initial replaceable parameterization; personality baseline read from existing 68 constructs with missingness mask.'
        }
    })


def validate_model(model, subject_id):
    if not isinstance(model, dict) or model.get('format') != MODEL_FORMAT or model.get('subject_id') != subject_id:
        raise ValueError('表达欲模型格式或主体不匹配')
    if seal_model(model)['sha256'] != model.get('sha256'):
        raise ValueError('表达欲模型摘要校验失败')
    params = model.get('parameters')
    if not isinstance(params, dict) or set(params) != set(SHAPES):
        raise ValueError('表达欲模型参数块不完整')
    for k, shape in SHAPES.items():
        arr = np.asarray(params[k], dtype=float)
        if arr.shape != shape or not np.isfinite(arr).all() or np.abs(arr).max(initial=0.0) > 1e4:
            raise ValueError('表达欲模型参数维度或数值无效: ' + k)
    return model


def stream_key(subject_id, scope, person=None):
    if not isinstance(subject_id, str) or not subject_id or not isinstance(scope, str) or not scope:
        raise ValueError('表达欲流标识缺少 subject_id 或 scope')
    person_id = str(person or scope)
    return digest([subject_id, scope, person_id])


def stable_event_id(scope, person, source_event_ids=(), fallback_id=None):
    """Deterministic event identity from scope, person, and ordered raw message IDs.

    Prevents repeated Cognition.assess(), arbitration reviews, or TurnTaking retries
    on the same message set from generating distinct random event IDs.
    """
    ids = [str(x).strip() for x in (source_event_ids or []) if str(x).strip()]
    if ids:
        return 'ev:' + digest([str(scope or ''), str(person or ''), ids])[:24]
    if isinstance(fallback_id, str) and fallback_id.strip():
        return fallback_id.strip()
    return 'ev:' + uid()[:24]


def empty_state(subject_id):
    model = initial_model(subject_id)
    return {
        'schema': SCHEMA,
        'subject_id': subject_id,
        'revision': 0,
        'model': model,
        'streams': {},
        'history': [],
    }


def _motive_source_ids(motive):
    if not isinstance(motive, dict):
        return set()
    ids = {str(x).strip() for x in (motive.get('source_event_ids') or []) if str(x).strip()}
    ids |= {
        str(e.get('ref')).strip()
        for e in (motive.get('source_evidence') or [])
        if isinstance(e, dict) and str(e.get('ref') or '').strip()
    }
    return ids


def _sync_satisfied_source_records(row):
    """Ensure satisfied_proactive_record_ids only contains source IDs that have
    at least one terminal motive/turn and ZERO unfinished motives (Round 4 Issue 2)."""
    motives = row.get('motives') or {}
    unfinished_srcs = set()
    terminal_srcs = set()
    for m in motives.values():
        if not isinstance(m, dict):
            continue
        m_srcs = _motive_source_ids(m)
        if m.get('status') in ('pending', 'deferred', 'partially_satisfied'):
            unfinished_srcs |= m_srcs
        elif m.get('status') in ('satisfied', 'abandoned'):
            terminal_srcs |= m_srcs
    for corr in (row.get('event_correlations') or {}).values():
        if not isinstance(corr, dict):
            continue
        c_srcs = {str(x).strip() for x in (corr.get('source_message_ids') or []) if str(x).strip()}
        c_srcs |= {str(x).strip() for x in ((corr.get('persisted_message_ids') or {}).get('user') or []) if str(x).strip()}
        c_mids = [m for m in (corr.get('expressive_motive_ids') or []) if m in motives]
        if any(motives[mid].get('status') in ('pending', 'deferred', 'partially_satisfied') for mid in c_mids):
            unfinished_srcs |= c_srcs
        elif c_mids and all(motives[mid].get('status') in ('satisfied', 'abandoned') for mid in c_mids):
            terminal_srcs |= c_srcs
    existing_sat = [str(x).strip() for x in (row.get('satisfied_proactive_record_ids') or []) if str(x).strip()]
    merged = list(dict.fromkeys([x for x in existing_sat if x not in unfinished_srcs] + [x for x in terminal_srcs if x not in unfinished_srcs]))
    row['satisfied_proactive_record_ids'] = merged
    return merged


def validate_motive(motive, owner):
    if not isinstance(motive, dict):
        raise ValueError('表达动机必须是对象')
    if not isinstance(motive.get('motive_id'), str) or not motive['motive_id']:
        raise ValueError('表达动机缺少 motive_id')
    if not motive.get('subject_id'):
        motive['subject_id'] = owner
    elif motive['subject_id'] != owner:
        raise ValueError('表达动机所属主体与当前主体不一致')
    if motive.get('status') not in MOTIVE_STATUSES:
        raise ValueError('表达动机状态无效')
    target = motive.get('target')
    if not isinstance(target, dict) or not isinstance(target.get('scope'), str) or not target['scope']:
        raise ValueError('表达动机缺少有效 target')
    anchor = motive.get('content_anchor')
    if not isinstance(anchor, dict) or not isinstance(anchor.get('topic'), str):
        raise ValueError('表达动机缺少有效 content_anchor')
    if not isinstance(motive.get('source_evidence'), list):
        raise ValueError('表达动机缺少 source_evidence 列表')
    if 'source_event_ids' not in motive or not isinstance(motive.get('source_event_ids'), list):
        motive['source_event_ids'] = [
            str(e.get('ref')).strip()
            for e in motive.get('source_evidence', [])
            if isinstance(e, dict) and str(e.get('ref') or '').strip()
        ]
    if 'delivery_outcome' not in motive or motive.get('delivery_outcome') is None:
        st_m = motive.get('status')
        motive['delivery_outcome'] = (
            'delivered_full' if st_m == 'satisfied'
            else 'delivered_partial' if st_m == 'partially_satisfied'
            else 'abandoned' if st_m == 'abandoned'
            else 'deferred_wait' if st_m == 'deferred'
            else 'pending'
        )
    for field in ('activation', 'urgency', 'persistence'):
        val = motive.get(field)
        if type(val) not in (int, float) or not math.isfinite(val) or not 0.0 <= val <= 1.0:
            raise ValueError('表达动机数值超出 0..1 范围: ' + field)
    seconds(motive.get('created_at'))
    seconds(motive.get('updated_at'))
    if type(motive.get('state_revision')) is not int or motive['state_revision'] < 0:
        raise ValueError('表达动机版本无效')
    return motive


def validate(data, owner):
    if data is None:
        return
    if not isinstance(data, dict) or data.get('schema') != SCHEMA or data.get('subject_id') != owner:
        raise ValueError('表达欲状态主体或 schema 无效')
    if type(data.get('revision')) is not int or data['revision'] < 0:
        raise ValueError('表达欲状态修订号无效')
    validate_model(data.get('model'), owner)
    streams = data.get('streams')
    if not isinstance(streams, dict):
        raise ValueError('表达欲流分区无效')
    for key, row in streams.items():
        if not isinstance(row, dict) or not isinstance(row.get('identity'), dict):
            raise ValueError('表达欲流结构无效')
        ident = row['identity']
        if key != stream_key(owner, ident.get('scope', ''), ident.get('person_id', '')):
            raise ValueError('表达欲流键与身份不匹配')
        for field in ('activation', 'urgency', 'persistence'):
            v = row.get(field)
            if type(v) not in (int, float) or not math.isfinite(v) or not 0.0 <= v <= 1.0:
                raise ValueError('表达欲流数值无效: ' + field)
        if row.get('expressive_intent') not in INTENTS:
            raise ValueError('表达欲意图枚举无效')
        seconds(row.get('updated_at'))
        if type(row.get('state_revision')) is not int or row['state_revision'] < 0:
            raise ValueError('表达欲流 state_revision 无效')
        motives = row.get('motives')
        if not isinstance(motives, dict):
            raise ValueError('表达欲流 motives 必须是字典')
        for mid, m in motives.items():
            if mid != m.get('motive_id'):
                raise ValueError('表达动机 ID 索引不一致')
            validate_motive(m, owner)
        if not isinstance(row.get('events'), dict):
            raise ValueError('表达欲事件幂等表无效')
    if not isinstance(data.get('history'), list):
        raise ValueError('表达欲历史列表无效')
    return data


def validate_metadata(meta):
    owner = (meta.get('identity') or {}).get('id')
    if KEY in meta and meta[KEY] is not None:
        validate(meta[KEY], owner)


def migrate(store):
    """Smoothly initialize ExpressiveDrive from existing V2.8.2 data without mutating traits/affect."""
    owner = store.meta('identity')['id']
    with store.lock, store.db:
        existing = store.meta(KEY)
        if existing is not None:
            validate(existing, owner)
            return existing
        state = empty_state(owner)
        store.setmeta(KEY, state)
        store.event('expressive_drive_initialized', {
            'schema': SCHEMA,
            'subject_id': owner,
            'model_sha256': state['model']['sha256'],
            'old_data_preserved': True,
        })
        return state


def personality_baseline(profile, model, neural_payload=None):
    """Compute b(theta) from the 68 existing constructs with strict missingness masking."""
    blocks = construct_blocks(profile)
    p = model['parameters']
    b0 = np.asarray(p['b0'], dtype=float)
    w_theta = np.asarray(p['W_theta'], dtype=float)

    x_theta = np.zeros(N_THETA, dtype=float)
    known_ids = []
    offset = 0
    for block_name in ('H', 'V', 'I', 'L', 'D'):
        row = blocks[block_name]
        vals = row['values']
        mask = row['mask']
        unc = row['uncertainty']
        # Center V around observed mean if any V is known
        v_mean = 0.5
        if block_name == 'V' and sum(mask) > 0:
            v_mean = sum(v for v, m in zip(vals, mask) if m) / sum(mask)
        for i, cid in enumerate(row['ids']):
            if mask[i] and vals[i] is not None:
                u = float(unc[i]) if unc[i] is not None else 0.25
                conf = max(0.2, 1.0 - 0.5 * clamp(u, 0.0, 1.0))
                centered = (float(vals[i]) - (v_mean if block_name == 'V' else 0.5)) * 2.0
                x_theta[offset + i] = centered * conf
                known_ids.append(cid)
        offset += len(row['ids'])

    logits = b0 + w_theta @ x_theta
    # Optional contribution from P-B current state offset if neural dynamics ran
    neural_mod = np.zeros(3, dtype=float)
    if isinstance(neural_payload, dict) and isinstance(neural_payload.get('latent'), list) and len(neural_payload['latent']) == 16:
        h = np.asarray(neural_payload['latent'], dtype=float)
        if np.isfinite(h).all():
            # Small bounded modulation from current 16D cognitive latent state h_t
            neural_mod = np.array([
                0.08 * float(np.tanh(np.mean(h[:6]))),
                0.06 * float(np.tanh(np.mean(h[6:12]))),
                0.06 * float(np.tanh(np.mean(h[12:]))),
            ], dtype=float)
            logits = logits + neural_mod

    base_probs = _sigmoid(logits)
    return {
        'logits': logits.tolist(),
        'baseline': {
            'activation': float(base_probs[0]),
            'urgency': float(base_probs[1]),
            'persistence': float(base_probs[2]),
        },
        'known_construct_count': len(known_ids),
        'known_constructs': known_ids[:24],
        'known_mask': [int(cid in known_ids) for cid in ALL_CONSTRUCT_IDS],
        'x_theta': x_theta.tolist(),
        'neural_modulation': neural_mod.tolist(),
    }


def _topic_S(text):
    if not isinstance(text, str):
        return set()
    return {t.lower() for t in re.findall(r'[a-z0-9]{2,}|[\u3400-\u9fff]{2,4}|[\u3400-\u9fff]', text) if t.strip()}


def topic_overlap(text_a, text_b):
    sa, sb = _topic_S(text_a), _topic_S(text_b)
    if not sa or not sb:
        return 0.0
    return float(len(sa & sb)) / float(max(1, min(len(sa), len(sb))))


def _extract_emotion_mood(affect_view):
    """Extract fast emotion e_t (7D) and slow mood m_t (3D) without advancing affect."""
    affect_view = affect_view or {}
    dyn = affect_view.get('dynamics_v2') if isinstance(affect_view, dict) else None
    if not dyn and isinstance(affect_view.get('trace'), dict):
        dyn = affect_view['trace'].get('dynamics_v2')
    em = affect_view.get('emotion') or affect_view.get('state', {}).get('emotion') or affect_view.get('short') or {}
    md = affect_view.get('mood') or affect_view.get('state', {}).get('mood') or {}
    if dyn and isinstance(dyn.get('affect_observed'), dict):
        em = {**em, **dyn['affect_observed']}
    if dyn and isinstance(dyn.get('mood_observed'), dict):
        md = {**md, **dyn['mood_observed']}

    v = float(em.get('valence', 0.0) or 0.0)
    a = float(em.get('arousal', 0.25) or 0.25)
    d = float(em.get('dominance', 0.5) or 0.5)
    s = float(em.get('stress', 0.15) or 0.15)
    g = float(em.get('engagement', 0.5) or 0.5)

    reg_strategy = 'none'
    if dyn and isinstance(dyn.get('regulation'), dict):
        reg_strategy = dyn['regulation'].get('strategy', 'none')
    elif isinstance(affect_view.get('regulation_v2'), dict):
        reg_strategy = affect_view['regulation_v2'].get('strategy', 'none')
    elif isinstance(affect_view.get('expression_plan'), dict):
        reg_strategy = affect_view['expression_plan'].get('expression_strategy', 'none')

    is_supp = 1.0 if reg_strategy in ('suppression', 'expressive_suppression') else 0.0
    is_reapp = 1.0 if reg_strategy in ('reappraisal', 'cognitive_reappraisal') else 0.0

    e_vec = np.array([
        clamp(v, -1.0, 1.0),
        clamp(a, 0.0, 1.0) - 0.25,
        clamp(d, 0.0, 1.0) - 0.50,
        clamp(s, 0.0, 1.0) - 0.20,
        clamp(g, 0.0, 1.0) - 0.40,
        is_supp,
        is_reapp,
    ], dtype=float)

    mv = float(md.get('valence', 0.0) or 0.0)
    ma = float(md.get('arousal', 0.25) or 0.25)
    mdom = float(md.get('dominance', 0.5) or 0.5)
    m_vec = np.array([
        clamp(mv, -1.0, 1.0),
        clamp(ma, 0.0, 1.0) - 0.25,
        clamp(mdom, 0.0, 1.0) - 0.50,
    ], dtype=float)

    return e_vec, m_vec, {
        'fast': {'valence': v, 'arousal': a, 'dominance': d, 'stress': s, 'engagement': g},
        'mood': {'valence': mv, 'arousal': ma, 'dominance': mdom},
        'regulation_strategy': reg_strategy,
    }


def _extract_appraisal(understanding, reasoner_packet, cognition_est, profile, text):
    u = understanding or {}
    sem = u.get('semantic') or {}
    cues = cognition_est or u.get('cognitive_appraisal') or {}
    checks = (reasoner_packet or {}).get('checks') or {}

    def pick(check_key, cue_key, sem_key, default=0.0):
        val = checks.get('affect.appraisal.' + check_key) if check_key else None
        if val is None and cue_key:
            val = cues.get(cue_key)
        if val is None and sem_key:
            val = sem.get(sem_key)
        return clamp(val if type(val) in (int, float) and math.isfinite(val) else default, 0.0, 1.0)

    goal_rel = pick('goal_relevance', 'personal_relevance', 'task', 0.25)
    personal_rel = pick(None, 'personal_relevance', 'autobiographical', goal_rel)
    novelty = pick('novelty', 'novelty', 'novelty', 0.2)
    urgency = pick('urgency', None, 'urgency', 0.15)
    emotional_sal = pick(None, 'emotional_salience', 'hostility', max(goal_rel * 0.5, float(sem.get('closeness', 0.0) or 0.0) * 0.5))
    conflict = pick('norm_compatibility', 'conflict', 'value_conflict', 0.0)
    consequence = pick(None, 'consequence', 'complexity', 0.2)
    needs_answer = clamp(float(sem.get('needs_answer', 0.5 if '?' in str(text) or '？' in str(text) else 0.25) or 0.25), 0.0, 1.0)
    task_strength = clamp(max(float(sem.get('task', 0.0) or 0.0), float(sem.get('general_knowledge', 0.0) or 0.0)), 0.0, 1.0)
    disengagement = clamp(float(sem.get('disengagement', 0.0) or 0.0), 0.0, 1.0)

    # Trait-topic resonance: an introverted subject still gets strong drive on high-interest topics
    features = (profile or {}).get('psychology', {}).get('features', {})
    inquisitive = (features.get('hexaco.o.inquisitiveness') or {}).get('estimate')
    self_dir = (features.get('value.self_direction_thought') or {}).get('estimate')
    curiosity_factor = 0.5
    if inquisitive is not None:
        curiosity_factor = max(curiosity_factor, float(inquisitive))
    if self_dir is not None:
        curiosity_factor = max(curiosity_factor, float(self_dir))
    # Also check overlap with author seed / beliefs / patterns
    seed_text = str((profile or {}).get('seed', '')) + ' ' + ' '.join(
        str(b.get('statement', '')) for b in (profile or {}).get('beliefs', []) if isinstance(b, dict)
    )
    seed_overlap = topic_overlap(text, seed_text) if text else 0.0
    interest_intensity = max(personal_rel, novelty * 0.85, task_strength * 0.8, seed_overlap)
    trait_topic_resonance = clamp(interest_intensity * (0.55 + 0.45 * curiosity_factor), 0.0, 1.0)

    q_vec = np.array([
        goal_rel,
        personal_rel,
        novelty,
        urgency,
        emotional_sal,
        conflict,
        consequence,
        needs_answer,
        task_strength,
        disengagement,
        trait_topic_resonance,
    ], dtype=float)
    return q_vec, {
        'goal_relevance': goal_rel,
        'personal_relevance': personal_rel,
        'novelty': novelty,
        'urgency': urgency,
        'emotional_salience': emotional_sal,
        'conflict': conflict,
        'consequence': consequence,
        'needs_answer': needs_answer,
        'task_strength': task_strength,
        'disengagement': disengagement,
        'trait_topic_resonance': trait_topic_resonance,
    }


def _extract_relationship(relation):
    rel = relation or {}
    dyad = rel.get('dyad') if isinstance(rel.get('dyad'), dict) else rel
    trust = dyad.get('trust')
    fam = float(dyad.get('familiarity', rel.get('familiarity', 0.0)) or 0.0)
    aff = dyad.get('affiliation', dyad.get('affection'))
    interactions = int(dyad.get('interactions', rel.get('interactions', 0)) or 0)
    conflicts = len(dyad.get('conflict_history', rel.get('conflict_history', [])) or [])

    trust_dev = (float(trust) - 0.5) * 2.0 if trust is not None else 0.0
    aff_dev = (float(aff) - 0.5) * 2.0 if aff is not None else 0.0
    density = min(1.0, interactions / 40.0)
    conflict_flag = min(1.0, conflicts / 3.0)

    r_vec = np.array([
        clamp(trust_dev, -1.0, 1.0),
        clamp(fam, 0.0, 1.0),
        clamp(aff_dev, -1.0, 1.0),
        density,
        conflict_flag,
    ], dtype=float)
    return r_vec, {
        'trust': trust,
        'familiarity': fam,
        'affection': aff,
        'interactions': interactions,
        'conflict_level': conflict_flag,
    }


def _extract_context(environment, text):
    env = environment or {}
    turn_complete = clamp(float(env.get('turn_complete', 0.85) if env.get('turn_complete') is not None else 0.85), 0.0, 1.0)
    addressed = 1.0 if env.get('addressed', True) else 0.0
    scope = str(env.get('scope', 'private:web:owner'))
    is_private = 1.0 if scope.startswith('private:') else 0.0
    act = str(env.get('prior_speech_act', ''))
    partner_closing = 1.0 if act == 'closing' or env.get('partner_closing') else 0.0
    obligation = 1.0 if act in ('question', 'invitation', 'correction') or env.get('response_obligation') in ('answer', 'acknowledge') else 0.35 if addressed else 0.0
    interruption_cost = clamp((1.0 - turn_complete) * (0.65 + 0.35 * (1.0 - addressed)), 0.0, 1.0)

    c_vec = np.array([
        turn_complete - 0.5,
        addressed - 0.3,
        is_private - 0.5,
        partner_closing,
        obligation - 0.3,
        interruption_cost,
    ], dtype=float)
    return c_vec, {
        'turn_complete': turn_complete,
        'addressed': bool(addressed),
        'is_private': bool(is_private),
        'partner_closing': bool(partner_closing),
        'obligation': obligation,
        'interruption_cost': interruption_cost,
    }


def initial_stream(subject_id, scope, person, session_id, at, model, profile):
    base = personality_baseline(profile, model)['baseline']
    return {
        'identity': {
            'scope': scope,
            'person_id': str(person or scope),
            'session_id': str(session_id or scope),
        },
        'activation': base['activation'],
        'urgency': base['urgency'],
        'persistence': base['persistence'],
        'expressive_intent': 'LISTEN',
        'baseline': base,
        'updated_at': seconds(at),
        'state_revision': 0,
        'last_event_id': None,
        'consecutive_deferrals': 0,
        'active_motive_id': None,
        'motives': {},
        'events': {},
        'evaluated_source_ids': {},
        'pre_event_snapshots': {},
        'satisfied_proactive_record_ids': [],
        'event_correlations': {},
        'proactive_outcomes': {},
    }


def _evolve_stream_over_time(row, base_info, dt, current_text=''):
    """Advance stream & unfinished motives over real elapsed seconds dt.

    Time passing never causes unbounded accumulation: motives decay according
    to their individual Persistence, with a bounded pause-recovery envelope for
    high-persistence deferred motives before they expire to 'abandoned'.
    """
    dt = max(0.0, float(dt))
    base = base_info['baseline']
    motives = copy.deepcopy(row.get('motives', {}))
    active_unfinished = []
    expired_ids = []
    max_pause_recovery = 0.0

    for mid, m in motives.items():
        if m['status'] not in ('pending', 'deferred', 'partially_satisfied'):
            continue
        p_m = clamp(m['persistence'], 0.0, 1.0)
        # Half-life scales from 3 min (180s) at p=0 up to 2 hours (7200s) at p=1
        half_life = 180.0 + 7020.0 * (p_m ** 2)
        gamma = math.log(2.0) / half_life
        decayed_act = float(m['activation']) * math.exp(-gamma * dt)

        # Urgency evolution: does not grow indefinitely; for high-persistence
        # deferred motives, has a bounded readiness window after brief silence,
        # then decays monotonically with activation.
        if dt > 0:
            pause_ready = p_m * decayed_act * (1.0 - math.exp(-dt / 120.0)) * math.exp(-0.5 * gamma * dt)
            max_pause_recovery = max(max_pause_recovery, 0.30 * pause_ready)
            decayed_urg = clamp(float(m['urgency']) * math.exp(-1.15 * gamma * dt) + 0.30 * pause_ready, 0.0, 1.0)
        else:
            decayed_urg = float(m['urgency'])

        # Check topic invalidation or expiration
        max_lifetime = 3.2 * half_life
        age = max(0.0, (row['updated_at'] + dt) - m['created_at'])
        if decayed_act < 0.16 or age > max_lifetime:
            m['activation'] = round(decayed_act, 6)
            m['urgency'] = round(decayed_urg, 6)
            m['status'] = 'abandoned'
            m['delivery_outcome'] = 'abandoned'
            m['defer_reason'] = 'expired_by_time_decay'
            m['updated_at'] = row['updated_at'] + dt
            m['state_revision'] += 1
            expired_ids.append(mid)
        else:
            if dt > 0:
                m['activation'] = round(clamp(decayed_act, 0.0, 1.0), 6)
                m['urgency'] = round(clamp(decayed_urg, 0.0, 1.0), 6)
                m['updated_at'] = row['updated_at'] + dt
                m['state_revision'] += 1
            active_unfinished.append(m)

    # Stream relaxation toward resting personality baseline
    pers_stream = clamp(row.get('persistence', base['persistence']), 0.0, 1.0)
    stream_half_life = 900.0 + 7200.0 * pers_stream
    stream_decay = math.exp(-math.log(2.0) * dt / stream_half_life) if dt > 0 else 1.0
    relaxed_act = base['activation'] + stream_decay * (row['activation'] - base['activation'])
    relaxed_urg = base['urgency'] + math.exp(-math.log(2.0) * dt / max(300.0, 0.6 * stream_half_life)) * (row['urgency'] - base['urgency'])
    relaxed_pers = base['persistence'] + stream_decay * (row['persistence'] - base['persistence'])

    # Compute residual motive vector u_{t-1}
    if active_unfinished:
        active_unfinished.sort(key=lambda item: (item['activation'] * (0.6 + 0.4 * item['persistence']), item['updated_at']), reverse=True)
        top = active_unfinished[0]
        overlap = max(
            topic_overlap(current_text, str(m['content_anchor'].get('topic', '')) + ' ' + str(m['content_anchor'].get('quote', '')))
            for m in active_unfinished
        ) if current_text else 0.5
        def_pressure = min(1.0, (len(active_unfinished) * 0.25) + 0.15 * min(4, row.get('consecutive_deferrals', 0)))
        u_vec = np.array([
            top['activation'],
            top['urgency'],
            top['persistence'],
            overlap,
            def_pressure,
        ], dtype=float)
        relaxed_act = max(relaxed_act, 0.65 * top['activation'] + 0.35 * base['activation'])
    else:
        top = None
        u_vec = np.zeros(N_RESIDUAL, dtype=float)

    return {
        'motives': motives,
        'active_unfinished': active_unfinished,
        'top_motive': top,
        'expired_ids': expired_ids,
        'u_vec': u_vec,
        'relaxed': {
            'activation': clamp(relaxed_act, 0.0, 1.0),
            'urgency': clamp(relaxed_urg, 0.0, 1.0),
            'persistence': clamp(relaxed_pers, 0.0, 1.0),
        },
        'delta_seconds': dt,
        'pause_recovery_boost': round(max_pause_recovery, 6),
    }


def select_expressive_intent(activation, urgency, persistence, env_info, app_info, emo_info, has_unfinished=False, mode='turn'):
    """Determine the 6-class expressive behavioral intention and continuous action terms.

    Expressive Drive is a continuous input to behavioral evaluation, never a
    hardcoded threshold rule that overrides permissions or safety boundaries.
    """
    tc = env_info['turn_complete']
    addressed = env_info['addressed']
    closing = env_info['partner_closing']
    obligation = env_info['obligation']
    interruption_cost = env_info['interruption_cost']
    disengage = app_info['disengagement']
    conflict = app_info['conflict']
    consequence = app_info['consequence']
    supp = 1.0 if emo_info['regulation_strategy'] in ('suppression', 'expressive_suppression') else 0.0
    stress = emo_info['fast']['stress']

    if mode == 'proactive':
        # Idle / no-new-message evaluation
        init_score = (
            0.52 * activation
            + 0.30 * urgency
            + 0.22 * persistence
            + (0.22 if has_unfinished else 0.04)
            - 0.35 * supp
            - 0.20 * max(0.0, stress - 0.5)
        )
        defer_score = (
            0.38 * persistence
            + 0.22 * activation
            + 0.35 * supp
            + 0.22 * (1.0 - urgency)
            if (has_unfinished or supp > 0.0) else 0.18
        )
        close_score = 0.52 * (1.0 - activation) + (0.12 if not has_unfinished and activation < 0.25 else 0.0)
        intent_scores = {
            'INITIATE': round(clamp(init_score, 0.0, 1.0), 6),
            'DEFER': round(clamp(defer_score, 0.0, 1.0), 6),
            'CLOSE': round(clamp(close_score, 0.0, 1.0), 6),
            'LISTEN': round(clamp(0.35 * (1.0 - urgency), 0.0, 1.0), 6),
            'BACKCHANNEL': 0.0,
            'TAKE_TURN': 0.0,
        }
        selected = max(('INITIATE', 'DEFER', 'CLOSE'), key=lambda k: intent_scores[k])
        return selected, intent_scores

    # Active conversation turn scores across all 6 intents
    restraint = clamp(0.45 * supp + 0.25 * max(0.0, stress - 0.4) + 0.30 * conflict * consequence, 0.0, 1.0)
    incomplete = 1.0 - tc

    listen_score = (
        0.52 * incomplete
        + 0.38 * (1.0 - urgency)
        + 0.24 * (1.0 - activation)
        + 0.25 * interruption_cost
        - 0.35 * obligation
    )
    backchannel_score = (
        0.48 * incomplete
        + 0.44 * (1.0 - abs(activation - 0.56) * 2.2)
        + 0.26 * (1.0 - abs(urgency - 0.48) * 2.0)
        + (0.20 if addressed else -0.15)
        - 0.35 * closing
        - 0.25 * obligation
    )
    take_turn_score = (
        0.46 * activation
        + 0.38 * urgency
        + 0.32 * tc
        + 0.28 * obligation
        + (0.14 if has_unfinished else 0.0)
        - 0.38 * interruption_cost * (1.0 - urgency)
        - 0.32 * restraint * (1.0 - obligation)
        - 0.40 * max(float(closing), disengage)
    )
    defer_score = (
        0.42 * activation
        + 0.40 * persistence
        + 0.46 * restraint
        + 0.34 * incomplete * (1.0 - urgency)
        - 0.36 * urgency * tc
        - 0.30 * obligation
    )
    close_score = (
        0.62 * max(float(closing), disengage)
        + 0.38 * (1.0 - activation)
        + 0.24 * (1.0 - persistence)
        - 0.42 * urgency
        - (0.25 if has_unfinished and not closing else 0.0)
    )
    initiate_score = (
        0.35 * activation * urgency * persistence * (1.0 - obligation)
        if not addressed and tc >= 0.7 else 0.05 * activation
    )

    intent_scores = {
        'LISTEN': round(clamp(listen_score, 0.0, 1.0), 6),
        'BACKCHANNEL': round(clamp(backchannel_score, 0.0, 1.0), 6),
        'TAKE_TURN': round(clamp(take_turn_score, 0.0, 1.0), 6),
        'DEFER': round(clamp(defer_score, 0.0, 1.0), 6),
        'CLOSE': round(clamp(close_score, 0.0, 1.0), 6),
        'INITIATE': round(clamp(initiate_score, 0.0, 1.0), 6),
    }
    selected = max(INTENTS, key=lambda k: intent_scores[k])
    return selected, intent_scores


def turn_taking_adjustments(drive_result, turn_complete):
    """Continuous utility adjustments for TurnTaking/Cognition (WAIT / REPLY / CLARIFY / NO_ACTION)."""
    act = drive_result['activation']
    urg = drive_result['urgency']
    pers = drive_result['persistence']
    intent = drive_result['expressive_intent']
    tc = clamp(float(turn_complete), 0.0, 1.0)

    # Continuous deltas bounded in [-0.28, +0.28]
    reply_delta = 0.22 * (0.55 * act + 0.45 * urg - 0.45)
    wait_delta = 0.20 * ((1.0 - urg) * (1.0 - tc) + (0.18 if intent in ('LISTEN', 'DEFER') else -0.12 if intent == 'TAKE_TURN' else 0.0))
    no_action_delta = 0.18 * ((0.5 - act) + (0.15 if intent in ('LISTEN', 'DEFER', 'CLOSE') and tc >= 0.7 else 0.0))
    clarify_delta = 0.08 * (act - 0.45) * (pers - 0.40)

    if intent == 'BACKCHANNEL' and tc < 0.75:
        # Backchannel permits a brief natural acknowledgment when addressed
        reply_delta += 0.14
        wait_delta -= 0.06
    elif intent == 'TAKE_TURN' and act >= 0.65 and urg >= 0.62:
        reply_delta += 0.12
        wait_delta -= 0.12
    elif intent == 'DEFER':
        wait_delta += 0.10
        reply_delta -= 0.10

    wait_sec_factor = clamp(1.0 + 0.45 * (0.5 - urg) - 0.25 * (act - 0.5), 0.45, 1.60)
    return {
        'score_deltas': {
            'WAIT': round(clamp(wait_delta, -0.28, 0.28), 6),
            'REPLY': round(clamp(reply_delta, -0.28, 0.28), 6),
            'CLARIFY': round(clamp(clarify_delta, -0.15, 0.15), 6),
            'NO_ACTION': round(clamp(no_action_delta, -0.28, 0.28), 6),
        },
        'wait_seconds_multiplier': round(wait_sec_factor, 4),
        'expressive_intent': intent,
        'backchannel_candidate': bool(intent == 'BACKCHANNEL' and tc < 0.75),
        'retain_unfinished_on_wait_or_silence': bool(act >= 0.40 and pers >= 0.35),
    }


def policy_action_terms(drive_result):
    """Continuous action score terms for policy.py / PMMCoordinator (ACTIONS enum)."""
    act = drive_result['activation']
    urg = drive_result['urgency']
    pers = drive_result['persistence']
    intent = drive_result['expressive_intent']
    drive_level = 0.55 * act + 0.45 * urg

    terms = {
        'reply': round(clamp(0.16 * (drive_level - 0.45) + (0.06 if intent in ('TAKE_TURN', 'BACKCHANNEL', 'INITIATE') else -0.05 if intent in ('DEFER', 'LISTEN') else 0.0), -0.18, 0.18), 6),
        'clarify': round(clamp(0.06 * (act - 0.5) * pers, -0.10, 0.10), 6),
        'disagree': round(clamp(0.05 * (urg - 0.55) * act, -0.08, 0.08), 6),
        'decline': 0.0,
        'unknown': 0.0,
        'silence': round(clamp(0.14 * (0.42 - drive_level) + (0.06 if intent in ('DEFER', 'LISTEN') else 0.0), -0.16, 0.16), 6),
    }
    return terms


def _synthesize_intended_expression(event, understanding, reasoner_packet, cognition_est, app_info, env_info,
                                    intent, existing_top=None, stage='provisional_wait', appraisal_summary=''):
    """Construct the AI subject's own communicative goal, distinct from the user's raw text (Fix 3).

    Explicitly separates:
    1) external_stimulus: what the interlocutor said and its grounded evidence quote;
    2) appraisal_basis: how the AI evaluated the event (relevance, novelty, uncertainty, turn completeness);
    3) intended_expression: what the AI itself wants to ask, answer, clarify, or share;
    4) resumption_policy: why expression is currently deferred and when to resume or abandon.
    """
    text = str(event.get('text', '')).strip()
    u = understanding or {}
    est = cognition_est or {}
    raw_topic = str(u.get('topic') or (u.get('keywords') or [''])[0] or u.get('intent') or '').strip()
    if not raw_topic or raw_topic in ('statement', 'question', 'greeting', 'sharing', 'other', '回应当前消息'):
        cleaned = text.replace('\n', ' ').strip()
        raw_topic = cleaned[:36] if cleaned else '当前对话事项'
    short_topic = raw_topic[:48]
    quote = (reasoner_packet or {}).get('quote') or text[:240]
    if not isinstance(quote, str) or not quote.strip() or quote not in text:
        quote = text[:240]
    ev_id = str(event.get('id') or uid())
    source_refs = [str(r) for r in (event.get('source_event_ids') or [ev_id]) if str(r).strip()]

    tc = float((env_info or {}).get('turn_complete', est.get('turn_complete', 0.85)))
    obligation = float((env_info or {}).get('obligation', 0.3))
    nov = float((app_info or {}).get('novelty', est.get('novelty', 0.3)))
    unc = float((app_info or {}).get('uncertainty', est.get('uncertainty', 0.25)))
    rel = float((app_info or {}).get('personal_relevance', est.get('personal_relevance', 0.45)))
    emo_sal = float((app_info or {}).get('emotional_salience', est.get('emotional_salience', 0.35)))
    conflict = float((app_info or {}).get('conflict', est.get('conflict', 0.1)))
    summary_text = str(appraisal_summary or u.get('intent') or (reasoner_packet or {}).get('hypothesis') or '').strip()
    if not summary_text:
        summary_text = f"相关度={rel:.2f}, 新颖度={nov:.2f}, 不确定性={unc:.2f}, 话轮完整度={tc:.2f}"

    # Determine the AI's own communicative act and goal (never a verbatim copy of user text)
    is_curious_hook = any(w in text for w in ('离谱', '奇怪', '没想到', '居然', '突然', '大事', '秘密', '猜猜', '跟你说个', '有件事', '还没说完'))
    if tc < 0.62 or is_curious_hook or (intent in ('LISTEN', 'BACKCHANNEL', 'DEFER') and (nov >= 0.35 or unc >= 0.30 or emo_sal >= 0.35)):
        speech_act = 'curious_follow_up_question' if (nov >= unc or is_curious_hook) else 'clarify_missing_detail'
        intended_goal = f"等待对方把关于「{short_topic}」的叙述讲完后，追问具体发生了什么细节并回应自身看法"
        candidate_point = f"想追问关于「{short_topic}」的具体经过、原因及后续结果，并表达关注"
        basis = f"对方当前话轮尚未完全展开或抛出高新颖度悬念（完整度={tc:.2f}, 新颖度={nov:.2f}），主体产生好奇与追问动机，但选择先倾听让轮"
    elif conflict >= 0.45:
        speech_act = 'clarify_or_state_boundary'
        intended_goal = f"围绕「{short_topic}」温和说明自身判断边界或澄清分歧点"
        candidate_point = f"针对「{short_topic}」中的冲突或边界敏感处作出克制、清晰的回应"
        basis = f"事件涉及潜在分歧或边界张力（冲突度={conflict:.2f}），需确认上下文后再完整表达立场"
    elif obligation >= 0.65 or '?' in text or '？' in text or u.get('intent') in ('question', 'invitation', 'request'):
        speech_act = 'answer_and_elaborate'
        intended_goal = f"针对对方提出的「{short_topic}」问题给出主体判断与具体解答"
        candidate_point = f"直接回应「{short_topic}」的核心疑问，并补充可核实的分析或建议"
        basis = f"对方提出明确询问或互动邀请（回应义务={obligation:.2f}），主体形成解答与回应目标"
    elif emo_sal >= 0.50:
        speech_act = 'empathic_response_and_share'
        intended_goal = f"就「{short_topic}」回应对方情绪感受，并补充主体的关心或看法"
        candidate_point = f"先共情承接对方在「{short_topic}」中的感受，再自然延展话题"
        basis = f"事件情绪显著性较高（情绪显著度={emo_sal:.2f}），主体形成共情承接与关切表达意图"
    else:
        speech_act = 'share_perspective_and_follow_up'
        intended_goal = f"围绕「{short_topic}」表达主体自身的理解与延伸提问"
        candidate_point = f"结合「{short_topic}」分享主体观点并保持自然互动衔接"
        basis = f"基于事件评价（{summary_text[:80]}）形成常规互动表达目标"

    defer_reason = (
        'speaker_turn_incomplete_waiting_for_continuation' if tc < 0.62 and intent in ('LISTEN', 'BACKCHANNEL', 'DEFER')
        else 'expressive_restraint_or_timing' if intent == 'DEFER'
        else 'active_listening_floor_yielded' if intent in ('LISTEN', 'BACKCHANNEL')
        else ''
    )

    previous_goal = None
    if existing_top and isinstance(existing_top.get('intended_expression'), dict):
        prev_ie = existing_top['intended_expression']
        previous_goal = prev_ie.get('intended_goal')
        if tc >= 0.62 and prev_ie.get('speech_act') in ('curious_follow_up_question', 'clarify_missing_detail'):
            intended_goal = f"承接此前暂缓的追问意图（{prev_ie.get('candidate_point_or_question', short_topic)}），结合对方补充的「{short_topic}」完成回应与追问"
            stage = 'resumed_and_revised'

    return {
        'stage': stage,
        'speech_act': speech_act,
        'intended_goal': intended_goal,
        'candidate_point_or_question': candidate_point,
        'formation_basis': basis,
        'previous_intended_goal': previous_goal,
        'proposal_id': None,
        'planned_strategy': None,
        'unsent_plan_steps': [],
        'epistemic_status': 'unexpressed_internal_intent_not_spoken_fact',
        'external_stimulus': {
            'speaker': str(event.get('person', '')),
            'user_topic': short_topic,
            'evidence_quote': quote[:300],
            'source_event_ids': source_refs[:6],
        },
        'appraisal_basis': {
            'summary': summary_text[:240],
            'goal_relevance': round(float((app_info or {}).get('goal_relevance', 0.45)), 4),
            'personal_relevance': round(rel, 4),
            'novelty': round(nov, 4),
            'uncertainty': round(unc, 4),
            'conflict': round(conflict, 4),
            'emotional_salience': round(emo_sal, 4),
            'turn_complete': round(tc, 4),
        },
        'resumption_policy': {
            'defer_reason': defer_reason,
            'resume_conditions': [
                'speaker_completes_turn_or_yields_floor',
                'same_or_related_topic_active',
                'idle_proactive_window_open_with_permission',
            ],
            'invalidation_conditions': [
                'partner_closes_conversation',
                'topic_shifted_with_low_persistence',
                'contact_permission_withdrawn',
                'expired_by_time_decay',
            ],
        },
    }


def reevaluate_unfinished_motive(motive, current_text, understanding=None, relation=None, env_info=None, app_info=None, at=None):
    """Re-evaluate an existing unfinished motive and its unsent_plan_steps when floor is regained (Fix 3 & Round 3 Issue 2).

    Returns a dict with:
    - decision: 'continue' | 'revise' | 'abandon'
    - reason: explanation of why the motive is continued, revised, or abandoned
    - overlap: topic overlap score in [0, 1]
    - reevaluated_steps: updated status of any unsent_plan_steps
    """
    if not isinstance(motive, dict) or motive.get('status') not in ('pending', 'deferred', 'partially_satisfied'):
        return {'decision': 'none', 'reason': 'no_active_unfinished_motive', 'overlap': 0.0, 'reevaluated_steps': []}

    env = env_info or {}
    app = app_info or {}
    rel = relation or {}
    text = str(current_text or '').strip()
    anchor = motive.get('content_anchor') or {}
    ie = motive.get('intended_expression') or {}
    unsent_steps = [copy.deepcopy(s) for s in (ie.get('unsent_plan_steps') or []) if isinstance(s, dict)]
    step_text = ' '.join(str(s.get('intended_point') or s.get('purpose') or '') for s in unsent_steps)
    ref_text = ' '.join([
        str(anchor.get('topic', '')),
        str(anchor.get('quote', '')),
        str(ie.get('intended_goal', '')),
        str(ie.get('candidate_point_or_question', '')),
        step_text,
    ])
    overlap = topic_overlap(text, ref_text) if text else 0.5

    def _mark_steps(new_status):
        out_steps = []
        for s in unsent_steps:
            s_copy = copy.deepcopy(s)
            s_copy['status'] = new_status
            out_steps.append(s_copy)
        return out_steps

    # 1. Partner explicitly closes the exchange or strongly disengages
    if env.get('partner_closing') or float(app.get('disengagement', 0.0)) >= 0.72:
        return {
            'decision': 'abandon',
            'reason': 'partner_closed_or_disengaged',
            'overlap': round(overlap, 4),
            'reevaluated_steps': _mark_steps('abandoned_partner_closed'),
        }

    # 2. Relationship trust dropped below safe threshold
    trust = rel.get('trust')
    if trust is not None and float(trust) < 0.22 and motive.get('persistence', 0.5) < 0.80:
        return {
            'decision': 'abandon',
            'reason': 'relationship_trust_dropped',
            'overlap': round(overlap, 4),
            'reevaluated_steps': _mark_steps('abandoned_relationship_shift'),
        }

    # 3. Complete topic shift to an unrelated agenda when previous motive is not high-persistence
    short_continuation = len(text) <= 14 or any(
        text.startswith(prefix) for prefix in ('而且', '然后', '结果', '后来', '就是', '其实', '另外', '不过', '所以', '对，', '是啊', '嗯')
    )
    has_deferred_reply_step = any(s.get('depends_on') in ('user_reply', 'next_speaking_opportunity') for s in unsent_steps)
    if text and overlap < 0.14 and not short_continuation and not (has_deferred_reply_step and len(text) <= 28) and float(motive.get('persistence', 0.5)) < 0.68:
        return {
            'decision': 'abandon',
            'reason': 'topic_shifted_superseded',
            'overlap': round(overlap, 4),
            'reevaluated_steps': _mark_steps('abandoned_topic_superseded'),
        }

    if text and (overlap >= 0.20 or short_continuation or has_deferred_reply_step):
        decision_kind = 'revise' if len(text) > 4 else 'continue'
        return {
            'decision': decision_kind,
            'reason': 'deferred_steps_revalidated_on_user_reply' if has_deferred_reply_step else 'same_topic_or_continuation_resumed',
            'overlap': round(max(overlap, 0.35 if (short_continuation or has_deferred_reply_step) else overlap), 4),
            'reevaluated_steps': _mark_steps('revalidated_for_current_turn'),
        }

    return {
        'decision': 'continue',
        'reason': 'high_persistence_motive_retained',
        'overlap': round(overlap, 4),
        'reevaluated_steps': _mark_steps('retained_pending_opportunity'),
    }


def _build_motive_candidate(event, at, activation, urgency, persistence, intent, understanding, reasoner_packet,
                            existing_top=None, cognition_est=None, app_info=None, env_info=None, appraisal_summary='',
                            reevaluation=None, existing_motives=None):
    text = str(event.get('text', '')).strip()
    u = understanding or {}
    raw_topic = str(u.get('topic') or (u.get('keywords') or [''])[0] or u.get('intent') or '').strip()
    if not raw_topic or raw_topic in ('statement', 'question', 'greeting', 'sharing', 'other', '回应当前消息'):
        raw_topic = text.replace('\n', ' ').strip()[:36] or '当前对话议题'
    topic = raw_topic[:160]
    quote = (reasoner_packet or {}).get('quote') or text[:240]
    if not isinstance(quote, str) or not quote.strip() or quote not in text:
        quote = text[:240]
    ev_id = str(event.get('id') or uid())
    source_refs = list(dict.fromkeys(str(r).strip() for r in (event.get('source_event_ids') or [ev_id]) if str(r).strip()))
    evidence = [{'ref': str(r), 'kind': 'event', 'quote': quote[:300]} for r in source_refs[:6]]

    # Check if this continues or revises an existing unfinished motive
    continuing = False
    prior_unsent_steps = []
    if existing_top and existing_top.get('status') in ('pending', 'deferred', 'partially_satisfied') and not event.get('independent_motive'):
        prev_ie = existing_top.get('intended_expression') or {}
        prior_unsent_steps = [copy.deepcopy(s) for s in (prev_ie.get('unsent_plan_steps') or []) if isinstance(s, dict)]
        ov = topic_overlap(text + ' ' + topic, str(existing_top['content_anchor'].get('topic', '')) + ' ' + str(existing_top['content_anchor'].get('quote', '')))
        short_cont = len(text) <= 14 or any(text.startswith(p) for p in ('而且', '然后', '结果', '后来', '就是', '其实', '不过', '所以', '嗯'))
        same_ev_id = ev_id == existing_top['content_anchor'].get('event_id')
        if ov >= 0.20 or short_cont or bool(prior_unsent_steps) or same_ev_id:
            continuing = True

    intended = _synthesize_intended_expression(
        event, understanding, reasoner_packet, cognition_est, app_info, env_info,
        intent, existing_top=existing_top if continuing else None,
        stage='resumed_and_revised' if continuing else 'provisional_wait',
        appraisal_summary=appraisal_summary
    )
    if continuing and prior_unsent_steps:
        reval_steps = (reevaluation or {}).get('reevaluated_steps') or prior_unsent_steps
        intended['unsent_plan_steps'] = copy.deepcopy(reval_steps)
        first_pt = str(reval_steps[0].get('intended_point') or reval_steps[0].get('purpose') or '').strip()
        if first_pt:
            intended['candidate_point_or_question'] = f"结合对方新回应，继续完成待表达步骤：{first_pt[:140]}"

    if continuing:
        mid = existing_top['motive_id']
        created_at = existing_top['created_at']
        rev = existing_top['state_revision'] + 1
        prior_ev = [e for e in existing_top.get('source_evidence', []) if isinstance(e, dict)]
        seen_refs = {e.get('ref') for e in prior_ev}
        for e in evidence:
            if e['ref'] not in seen_refs:
                prior_ev.append(e)
        evidence = prior_ev[-8:]
        merged_src_ids = list(dict.fromkeys(list(existing_top.get('source_event_ids') or []) + source_refs))[:12]
        proactive_defers = int(existing_top.get('proactive_defer_count', 0))
    else:
        default_mid = str(event.get('motive_id') or '').strip() or ('motive:' + digest([event.get('scope', ''), event.get('person', ''), source_refs or [ev_id]])[:24])
        if isinstance(existing_motives, dict) and default_mid in existing_motives:
            mid = 'motive:' + digest([event.get('scope', ''), event.get('person', ''), source_refs or [ev_id], ev_id, topic])[:24]
        else:
            mid = default_mid
        created_at = seconds(at)
        rev = 1
        merged_src_ids = source_refs[:12]
        proactive_defers = 0

    status = 'deferred' if intent in ('DEFER', 'LISTEN') else 'pending'
    defer_reason = intended['resumption_policy']['defer_reason']
    return {
        'motive_id': mid,
        'subject_id': str(event.get('subject_id') or ''),
        'source_event_ids': merged_src_ids,
        'target': {
            'scope': str(event.get('scope', '')),
            'person_id': str(event.get('person', '')),
            'session_id': str(event.get('session_id', event.get('scope', ''))),
        },
        'content_anchor': {
            'topic': topic or '当前对话议题',
            'summary': intended['intended_goal'],
            'intended_goal': intended['intended_goal'],
            'candidate_point_or_question': intended['candidate_point_or_question'],
            'speech_act': intended['speech_act'],
            'formation_basis': intended['formation_basis'],
            'quote': quote[:300],
            'event_id': ev_id,
            'epistemic_status': 'unexpressed_internal_intent_not_spoken_fact',
        },
        'intended_expression': intended,
        'source_evidence': evidence,
        'status': status,
        'delivery_outcome': 'deferred_wait' if status == 'deferred' else 'pending',
        'defer_reason': defer_reason,
        'proactive_defer_count': proactive_defers,
        'activation': round(clamp(activation, 0.0, 1.0), 6),
        'urgency': round(clamp(urgency, 0.0, 1.0), 6),
        'persistence': round(clamp(persistence, 0.0, 1.0), 6),
        'created_at': seconds(created_at),
        'updated_at': seconds(at),
        'state_revision': rev,
    }


def _build_secondary_motives(event, at, activation, urgency, persistence, understanding, existing_motives, primary_motive):
    """When an inbound message contains multiple distinct sub-events/topics, create independent motives per sub-goal (Requirement 2.2.6)."""
    u = understanding or {}
    sub_events = u.get('events') if isinstance(u.get('events'), list) else []
    if len(sub_events) <= 1:
        return []
    created = []
    ev_id = str(event.get('id') or uid())
    scope = str(event.get('scope', ''))
    person = str(event.get('person', ''))
    session_id = str(event.get('session_id', scope))
    primary_quote = primary_motive['content_anchor'].get('quote', '')
    for idx_sub, sub in enumerate(sub_events[1:4], start=1):
        if not isinstance(sub, dict):
            continue
        sub_summary = str(sub.get('summary') or sub.get('kind') or '').strip()
        sub_quote = str(sub.get('quote') or '').strip()
        if not sub_summary and not sub_quote:
            continue
        if sub_quote and topic_overlap(sub_quote, primary_quote) >= 0.70 and topic_overlap(sub_summary, primary_motive['content_anchor'].get('topic', '')) >= 0.70:
            continue
        sub_mid = 'motive:' + digest([scope, person, ev_id, 'sub', idx_sub, sub_quote or sub_summary])[:24]
        if sub_mid == primary_motive['motive_id']:
            continue
        sub_act = round(clamp(activation * 0.88, 0.20, 1.0), 6)
        sub_urg = round(clamp(urgency * 0.82, 0.15, 1.0), 6)
        sub_pers = round(clamp(persistence * 0.92, 0.25, 1.0), 6)
        sub_goal = f"针对同一消息中的另一独立事项「{(sub_summary or sub_quote)[:40]}」进行回应或跟进"
        sub_motive = {
            'motive_id': sub_mid,
            'subject_id': str(event.get('subject_id') or ''),
            'source_event_ids': list(dict.fromkeys(str(r).strip() for r in (event.get('source_event_ids') or [ev_id]) if str(r).strip()))[:12],
            'parent_event_id': ev_id,
            'sub_event_index': idx_sub,
            'target': {'scope': scope, 'person_id': person, 'session_id': session_id},
            'content_anchor': {
                'topic': (sub_summary or sub_quote)[:120],
                'summary': sub_goal,
                'intended_goal': sub_goal,
                'candidate_point_or_question': f"回应或追问「{(sub_summary or sub_quote)[:60]}」",
                'speech_act': 'follow_up_secondary_sub_event',
                'formation_basis': f"同一输入包含多个独立子事件（第 {idx_sub + 1} 项：{sub.get('kind', 'event')}）",
                'quote': (sub_quote or sub_summary)[:300],
                'event_id': ev_id,
                'epistemic_status': 'unexpressed_internal_intent_not_spoken_fact',
            },
            'intended_expression': {
                'stage': 'provisional_secondary_motive',
                'speech_act': 'follow_up_secondary_sub_event',
                'intended_goal': sub_goal,
                'candidate_point_or_question': f"回应或追问「{(sub_summary or sub_quote)[:60]}」",
                'formation_basis': f"同一输入包含多个独立子事件（第 {idx_sub + 1} 项）",
                'previous_intended_goal': None,
                'proposal_id': None,
                'planned_strategy': None,
                'unsent_plan_steps': [],
                'epistemic_status': 'unexpressed_internal_intent_not_spoken_fact',
                'external_stimulus': {
                    'speaker': person,
                    'user_topic': (sub_summary or sub_quote)[:48],
                    'evidence_quote': (sub_quote or sub_summary)[:300],
                    'source_event_ids': list(event.get('source_event_ids') or [ev_id])[:6],
                },
                'appraisal_basis': {'summary': sub_summary[:200]},
                'resumption_policy': {
                    'defer_reason': 'secondary_sub_event_tracked_independently',
                    'resume_conditions': ['primary_point_completed_or_topic_revisited'],
                    'invalidation_conditions': ['partner_closes_conversation', 'expired_by_time_decay'],
                },
            },
            'source_evidence': [{'ref': str(r), 'kind': 'sub_event', 'quote': (sub_quote or sub_summary)[:300]} for r in (event.get('source_event_ids') or [ev_id])[:4]],
            'status': 'deferred',
            'delivery_outcome': 'deferred_wait',
            'defer_reason': 'secondary_sub_event_tracked_independently',
            'proactive_defer_count': 0,
            'activation': sub_act,
            'urgency': sub_urg,
            'persistence': sub_pers,
            'created_at': seconds(at),
            'updated_at': seconds(at),
            'state_revision': 1,
        }
        created.append(sub_motive)
    return created


def bind_turn_correlation(draft_state, scope, person, *,
                          source_message_ids=(), cognitive_event_id=None, pmm_event_id=None,
                          turn_id=None, persisted_user_ids=(), persisted_assistant_ids=(),
                          motive_ids=(), motive_outcomes=None, delivery_outcome=None,
                          user_text='', at=None):
    """Create or update a durable event correlation record linking all message/turn/motive IDs (Round 3 Issue 1).

    Chain:
    source_message_ids -> cognitive_event_id -> pmm_event_id -> turn_id
      -> persisted_message_ids (user / assistant) -> expressive_motive_ids -> delivery_outcome
    """
    if draft_state is None:
        return draft_state, None
    state = copy.deepcopy(draft_state)
    owner = state['subject_id']
    skey = stream_key(owner, scope, person)
    row = state['streams'].get(skey)
    if not row:
        return state, None
    ts = seconds(at if at is not None else max(now(), row['updated_at']))
    correlations = row.setdefault('event_correlations', {})

    src_list = [str(x).strip() for x in (source_message_ids or []) if str(x).strip()]
    p_user = [str(x).strip() for x in (persisted_user_ids or []) if str(x).strip()]
    p_asst = [str(x).strip() for x in (persisted_assistant_ids or []) if str(x).strip()]
    m_ids = [str(x).strip() for x in (motive_ids or []) if str(x).strip()]
    cog_id = str(cognitive_event_id).strip() if cognitive_event_id else None
    pmm_id = str(pmm_event_id).strip() if pmm_event_id else None
    t_id = str(turn_id).strip() if turn_id else None

    # Find any existing correlation entry that shares source_message_ids, cognitive_event_id, pmm_event_id, turn_id, or user message IDs
    matched_key = None
    for ck, cval in correlations.items():
        if not isinstance(cval, dict):
            continue
        if (t_id and cval.get('turn_id') == t_id) or (pmm_id and cval.get('pmm_event_id') == pmm_id) or (cog_id and cval.get('cognitive_event_id') == cog_id):
            matched_key = ck
            break
        if src_list and set(src_list).intersection(cval.get('source_message_ids') or []):
            matched_key = ck
            break
        if p_user and set(p_user).intersection((cval.get('persisted_message_ids') or {}).get('user') or []):
            matched_key = ck
            break

    if matched_key is None:
        anchor_basis = t_id or pmm_id or cog_id or (src_list[0] if src_list else uid())
        matched_key = 'corr:' + digest([scope, person, anchor_basis])[:24]
        entry = {
            'correlation_id': matched_key,
            'scope': scope,
            'person_id': str(person),
            'source_message_ids': [],
            'cognitive_event_id': None,
            'pmm_event_id': None,
            'turn_id': None,
            'persisted_message_ids': {'user': [], 'assistant': []},
            'expressive_motive_ids': [],
            'motive_outcomes': {},
            'delivery_outcome': None,
            'text_sha256': digest(user_text.strip()) if user_text else None,
            'created_at': ts,
            'updated_at': ts,
        }
    else:
        entry = copy.deepcopy(correlations[matched_key])

    for s in src_list:
        if s not in entry['source_message_ids']:
            entry['source_message_ids'].append(s)
    if cog_id:
        entry['cognitive_event_id'] = cog_id
    if pmm_id:
        entry['pmm_event_id'] = pmm_id
    if t_id:
        entry['turn_id'] = t_id
    for u_id in p_user:
        if u_id not in entry['persisted_message_ids']['user']:
            entry['persisted_message_ids']['user'].append(u_id)
    for a_id in p_asst:
        if a_id not in entry['persisted_message_ids']['assistant']:
            entry['persisted_message_ids']['assistant'].append(a_id)
    for mid in m_ids:
        if mid not in entry['expressive_motive_ids']:
            entry['expressive_motive_ids'].append(mid)
    if user_text and not entry.get('text_sha256'):
        entry['text_sha256'] = digest(user_text.strip())
    if delivery_outcome:
        entry['delivery_outcome'] = delivery_outcome

    # Synchronize per-motive statuses from row['motives'] and explicit motive_outcomes
    outcomes_map = dict(entry.get('motive_outcomes') or {})
    for mid in entry['expressive_motive_ids']:
        if mid in row.get('motives', {}):
            outcomes_map[mid] = row['motives'][mid]['status']
    if isinstance(motive_outcomes, dict):
        outcomes_map.update(motive_outcomes)
    entry['motive_outcomes'] = outcomes_map
    entry['all_motives_terminal'] = bool(outcomes_map) and all(
        st_val in ('satisfied', 'abandoned') for st_val in outcomes_map.values()
    )
    entry['updated_at'] = ts
    correlations[matched_key] = entry

    # Also keep satisfied_proactive_record_ids synchronized with all user/source IDs when all motives are terminal
    if entry['all_motives_terminal'] and entry.get('delivery_outcome') in ('delivered_full', 'abandoned'):
        sat_ids = row.setdefault('satisfied_proactive_record_ids', [])
        for ref_id in entry['source_message_ids'] + entry['persisted_message_ids']['user'] + ([entry['turn_id']] if entry.get('turn_id') else []):
            if ref_id and ref_id not in sat_ids:
                sat_ids.append(ref_id)
        if len(sat_ids) > 160:
            row['satisfied_proactive_record_ids'] = sat_ids[-160:]

    if len(correlations) > 80:
        for old_ck in list(correlations)[:-80]:
            correlations.pop(old_ck, None)

    return state, copy.deepcopy(entry)


def enrich_motive_from_planning(draft_state, drive_result, scope, person, *,
                                deliberation=None, decision=None, interaction_plan=None,
                                generated_parts=None, unsent_parts=None, at=None, phase='planning'):
    """Upgrade the active motive's intended_expression across 3 explicit stages (Round 3 Issue 2):

    - phase='planning' (before REALIZE generation): records provisional goals from Deliberation & ExpressionPlan.
    - phase='generated' (after REALIZE & parse_message_parts): records actual generated steps and structured
      deferred_user_reply_steps (steps with depends_on='user_reply').
    - phase='delivery' (after ACK / partial delivery): records unsent suffix bubbles & deferred steps.
    """
    if draft_state is None or not isinstance(drive_result, dict):
        return draft_state, drive_result
    from .expression_plan import normalize_deferred_steps
    state = copy.deepcopy(draft_state)
    res = copy.deepcopy(drive_result)
    owner = state['subject_id']
    skey = stream_key(owner, scope, person)
    row = state['streams'].get(skey)
    if not row:
        return state, res
    mid = row.get('active_motive_id') or res.get('active_motive_id')
    motive = row['motives'].get(mid) if mid else None
    if not motive:
        return state, res

    ie = motive.setdefault('intended_expression', {})
    anchor = motive.setdefault('content_anchor', {})

    if isinstance(deliberation, dict):
        sel_id = deliberation.get('selected_proposal_id')
        sel_prop = deliberation.get('selected_proposal') or next(
            (p for p in (deliberation.get('proposals') or []) if isinstance(p, dict) and p.get('id') == sel_id),
            None
        )
        if isinstance(sel_prop, dict):
            if phase == 'planning':
                ie['stage'] = 'planned_before_generation'
            ie['proposal_id'] = sel_prop.get('id')
            if sel_prop.get('content_goal'):
                ie['intended_goal'] = str(sel_prop['content_goal'])[:300]
                anchor['intended_goal'] = ie['intended_goal']
                anchor['summary'] = ie['intended_goal']
            if sel_prop.get('task_handling'):
                ie['candidate_point_or_question'] = str(sel_prop['task_handling'])[:300]
                anchor['candidate_point_or_question'] = ie['candidate_point_or_question']
            if sel_prop.get('social_strategy'):
                ie['social_strategy'] = str(sel_prop['social_strategy'])[:240]

    if isinstance(decision, dict) and decision.get('action'):
        ie['selected_policy_action'] = decision['action']

    if isinstance(interaction_plan, dict):
        ie['planned_strategy'] = interaction_plan.get('selected_strategy') or interaction_plan.get('candidate_strategy') or interaction_plan.get('strategy')
        if interaction_plan.get('local_goal') and interaction_plan['local_goal'] not in ('回应当前消息',):
            ie['intended_goal'] = str(interaction_plan['local_goal'])[:300]
            anchor['intended_goal'] = ie['intended_goal']
            anchor['summary'] = ie['intended_goal']

        if phase == 'planning':
            ie['stage'] = 'planned_before_generation'
            follow_need = str(interaction_plan.get('follow_up_need') or '').strip()
            if follow_need:
                ie['planned_steps'] = [{
                    'step_id': 'plan_followup_01',
                    'purpose': follow_need[:240],
                    'intended_point': follow_need[:240],
                    'depends_on': 'current_input',
                    'status': 'planned',
                }]
        elif phase in ('generated', 'delivery'):
            ie['stage'] = 'generated_awaiting_delivery' if phase == 'generated' else ie.get('stage', 'planned_expression')
            realization_steps = interaction_plan.get('realization_steps') if isinstance(interaction_plan.get('realization_steps'), list) else []
            parts_list = list(generated_parts) if isinstance(generated_parts, list) else []
            gen_steps = []
            for idx_p, part_text in enumerate(parts_list[:4]):
                step_meta = realization_steps[idx_p] if idx_p < len(realization_steps) and isinstance(realization_steps[idx_p], dict) else {}
                gen_steps.append({
                    'step_id': str(step_meta.get('step_id') or f'step_{idx_p+1:02d}'),
                    'act': str(step_meta.get('act') or 'unspecified'),
                    'purpose': str(step_meta.get('purpose') or f'第 {idx_p+1} 条计划发送内容')[:300],
                    'intended_point': str(part_text).strip()[:240],
                    'depends_on': str(step_meta.get('depends_on') or 'current_input'),
                    'status': 'generated_pending_ack',
                    'epistemic_status': 'unexpressed_internal_intent_not_spoken_fact',
                })
            ie['generated_steps'] = gen_steps

            def_steps, def_count = normalize_deferred_steps(interaction_plan.get('deferred_user_reply_steps'))
            ie['deferred_user_reply_steps'] = [
                {**s, 'epistemic_status': 'unexpressed_internal_intent_not_spoken_fact'}
                for s in def_steps
            ]
            ie['deferred_user_reply_step_count'] = def_count
            if def_steps:
                ie['unsent_plan_steps'] = copy.deepcopy(ie['deferred_user_reply_steps'])
                ie['candidate_point_or_question'] = f"待对方回复后继续：{def_steps[0]['intended_point'][:120]}"
                anchor['candidate_point_or_question'] = ie['candidate_point_or_question']

    if unsent_parts:
        ie['stage'] = 'planned_expression_partially_unsent'
        unsent_objs = [
            {
                'step_id': f'unsent_part_{i+1:02d}',
                'act': 'unspecified',
                'purpose': f'待补发第 {i+1} 条未送达内容',
                'intended_point': str(part)[:240],
                'depends_on': 'next_speaking_opportunity',
                'status': 'deferred',
                'epistemic_status': 'unexpressed_internal_intent_not_spoken_fact',
            }
            for i, part in enumerate(unsent_parts[:4]) if str(part).strip()
        ]
        for ds in (ie.get('deferred_user_reply_steps') or []):
            if isinstance(ds, dict):
                unsent_objs.append({**copy.deepcopy(ds), 'epistemic_status': 'unexpressed_internal_intent_not_spoken_fact'})
        ie['unsent_plan_steps'] = unsent_objs
        if unsent_objs:
            ie['candidate_point_or_question'] = f"待继续表达未发完的要点：{unsent_objs[0]['intended_point'][:120]}"
            anchor['candidate_point_or_question'] = ie['candidate_point_or_question']

    ie['epistemic_status'] = 'unexpressed_internal_intent_not_spoken_fact'
    if at is not None:
        motive['updated_at'] = seconds(at)
    res['active_motive'] = copy.deepcopy(motive)
    res['content_anchor'] = copy.deepcopy(anchor)
    res['intended_expression'] = copy.deepcopy(ie)
    if row.get('last_event_id') and row['last_event_id'] in row['events']:
        row['events'][row['last_event_id']]['result']['active_motive'] = copy.deepcopy(motive)
        row['events'][row['last_event_id']]['result']['content_anchor'] = copy.deepcopy(anchor)
        row['events'][row['last_event_id']]['result']['intended_expression'] = copy.deepcopy(ie)
    return state, res


def evaluate_event(base_state, profile, event, at, understanding=None, affect_view=None, relation=None,
                   reasoner_packet=None, cognition_est=None, neural_payload=None, environment=None,
                   *, revise_draft=False, incremental_records=None, appraisal_summary=''):
    """Pure, event-idempotent draft computation of ExpressiveDrive for an inbound event."""
    owner = profile['id']
    state = copy.deepcopy(base_state) if base_state is not None else empty_state(owner)
    validate(state, owner)
    model = state['model']
    at = seconds(at)
    scope = str(event.get('scope', 'private:web:owner'))
    person = str(event.get('person', 'web:owner'))
    session_id = str(event.get('session_id', scope))
    raw_src_ids = [str(x).strip() for x in (event.get('source_event_ids') or []) if str(x).strip()]
    raw_ev_id = str(event.get('id') or '')
    if raw_src_ids and (not raw_ev_id or raw_ev_id.startswith(('cognition:', 'tt:', 'input:'))):
        ev_id = stable_event_id(scope, person, raw_src_ids, raw_ev_id)
    else:
        ev_id = raw_ev_id or stable_event_id(scope, person, raw_src_ids)
    text = str(event.get('text', ''))

    skey = stream_key(owner, scope, person)
    row = state['streams'].setdefault(
        skey,
        initial_stream(owner, scope, person, session_id, at, model, profile)
    )
    row['identity']['session_id'] = session_id
    eval_src_map = row.setdefault('evaluated_source_ids', {})
    snapshots = row.setdefault('pre_event_snapshots', {})

    fingerprint = digest([text, ev_id, scope, person])

    all_src_already_evaluated = bool(raw_src_ids) and all(sid in eval_src_map for sid in raw_src_ids)
    if ev_id in row['events'] and not revise_draft:
        prev = row['events'][ev_id]
        if prev['content_sha256'] == fingerprint or all_src_already_evaluated:
            cached = copy.deepcopy(prev['result'])
            cached.update(updated=False, replayed=True)
            return state, cached
    elif all_src_already_evaluated and not revise_draft and row.get('last_event_id') in row['events']:
        prev_ev_id = eval_src_map[raw_src_ids[-1]].get('event_id') or row['last_event_id']
        if prev_ev_id in row['events']:
            prev_res = row['events'][prev_ev_id]['result']
            u_topic = str((understanding or {}).get('topic') or '').strip()
            prev_topic = str((prev_res.get('content_anchor') or {}).get('topic') or '').strip()
            is_distinct_explicit_event = bool(
                raw_ev_id and not raw_ev_id.startswith(('cognition:', 'tt:', 'input:', 'ev:'))
                and raw_ev_id != prev_ev_id
                and (event.get('independent_motive') or (u_topic and u_topic != prev_topic) or row['events'][prev_ev_id]['content_sha256'] != fingerprint)
            )
            if not is_distinct_explicit_event:
                cached = copy.deepcopy(prev_res)
                cached.update(updated=False, replayed=True)
                return state, cached

    restored_from_snapshot = False
    snap_key = ev_id if ev_id in snapshots else (eval_src_map[raw_src_ids[-1]].get('event_id') if all_src_already_evaluated and raw_src_ids else None)
    if revise_draft and snap_key and snap_key in snapshots:
        snap = copy.deepcopy(snapshots[snap_key])
        row.update(
            activation=snap['activation'],
            urgency=snap['urgency'],
            persistence=snap['persistence'],
            expressive_intent=snap['expressive_intent'],
            updated_at=snap['updated_at'],
            state_revision=snap['state_revision'],
            active_motive_id=snap['active_motive_id'],
            motives=snap['motives'],
            evaluated_source_ids=snap['evaluated_source_ids'],
        )
        eval_src_map = row['evaluated_source_ids']
        state['revision'] = max(0, state['revision'] - 1)
        if state.get('history') and state['history'][-1].get('event_id') == snap_key:
            state['history'].pop()
        restored_from_snapshot = True

    snapshots[ev_id] = {
        'activation': row['activation'],
        'urgency': row['urgency'],
        'persistence': row['persistence'],
        'expressive_intent': row['expressive_intent'],
        'updated_at': row['updated_at'],
        'state_revision': row['state_revision'],
        'active_motive_id': row.get('active_motive_id'),
        'motives': copy.deepcopy(row['motives']),
        'evaluated_source_ids': copy.deepcopy(eval_src_map),
    }
    if len(snapshots) > 16:
        for old_sk in list(snapshots)[:-16]:
            snapshots.pop(old_sk, None)

    new_src_ids = [sid for sid in raw_src_ids if sid not in eval_src_map] if raw_src_ids else []
    prior_src_ids = [sid for sid in raw_src_ids if sid in eval_src_map] if raw_src_ids else []
    stimulus_text = text
    if prior_src_ids and new_src_ids:
        if isinstance(incremental_records, list) and incremental_records:
            inc_lines = [str(r.get('text', '')) for r in incremental_records if isinstance(r, dict) and str(r.get('id', '')) in new_src_ids]
            if inc_lines:
                stimulus_text = '\n'.join(inc_lines)
        else:
            lines = text.splitlines()
            if len(lines) >= len(raw_src_ids):
                stimulus_text = '\n'.join(lines[-len(new_src_ids):])

    effective_at = max(at, row['updated_at'])
    dt = effective_at - row['updated_at']

    if event.get('origin')!='memory_reflection':
        for prior in row['motives'].values():
            if prior.get('origin')=='memory_reflection' and prior.get('status') in ('pending','deferred','partially_satisfied'):
                prior.update(status='abandoned',delivery_outcome='abandoned',defer_reason='new_input_requires_fresh_reflection',
                             updated_at=effective_at,state_revision=prior['state_revision']+1)
    base_info = personality_baseline(profile, model, neural_payload=neural_payload)
    evolved = _evolve_stream_over_time(row, base_info, dt, current_text=text)
    motives = evolved['motives']

    e_vec, m_vec, emo_info = _extract_emotion_mood(affect_view)
    q_vec, app_info = _extract_appraisal(understanding, reasoner_packet, cognition_est, profile, stimulus_text)
    r_vec, rel_info = _extract_relationship(relation)
    c_vec, env_info = _extract_context({**(environment or {}), 'scope': scope}, text)
    u_vec = evolved['u_vec']

    active_top = evolved['top_motive']
    shares_same_source_diff_event = bool(
        active_top and raw_src_ids
        and (set(raw_src_ids) & _motive_source_ids(active_top))
        and ev_id != active_top['content_anchor'].get('event_id')
    )
    if shares_same_source_diff_event:
        motive_reeval = {
            'decision': 'continue',
            'reason': 'parallel_motive_from_shared_source',
            'overlap': 0.0,
            'reevaluated_steps': [],
        }
    else:
        motive_reeval = reevaluate_unfinished_motive(
            active_top, text, understanding=understanding,
            relation=relation, env_info=env_info, app_info=app_info, at=effective_at
        )
    if motive_reeval['decision'] == 'abandon' and active_top and not shares_same_source_diff_event:
        ab_id = active_top['motive_id']
        if ab_id in motives:
            motives[ab_id]['status'] = 'abandoned'
            motives[ab_id]['delivery_outcome'] = 'abandoned'
            motives[ab_id]['defer_reason'] = motive_reeval['reason']
            if motive_reeval.get('reevaluated_steps'):
                motives[ab_id].setdefault('intended_expression', {})['unsent_plan_steps'] = motive_reeval['reevaluated_steps']
            motives[ab_id]['updated_at'] = effective_at
            motives[ab_id]['state_revision'] += 1
            evolved['expired_ids'].append(ab_id)
        active_top = None
        u_vec = np.zeros(N_RESIDUAL, dtype=float)

    p = model['parameters']
    b_theta = np.asarray(base_info['logits'], dtype=float)
    term_e = np.asarray(p['W_e'], dtype=float) @ e_vec
    term_m = np.asarray(p['W_m'], dtype=float) @ m_vec
    term_q = np.asarray(p['W_q'], dtype=float) @ q_vec
    term_r = np.asarray(p['W_r'], dtype=float) @ r_vec
    term_c = np.asarray(p['W_c'], dtype=float) @ c_vec
    term_u = np.asarray(p['W_u'], dtype=float) @ u_vec

    total_logits = b_theta + term_e + term_m + term_q + term_r + term_c + term_u
    probs = _sigmoid(total_logits)
    activation = float(probs[0])
    urgency = float(probs[1])
    persistence = float(probs[2])

    has_unfinished = active_top is not None
    intent, intent_scores = select_expressive_intent(
        activation, urgency, persistence, env_info, app_info, emo_info,
        has_unfinished=has_unfinished, mode='turn'
    )

    motive_event = {**event, 'id': ev_id, 'subject_id': owner, 'source_event_ids': raw_src_ids or [ev_id]}
    if shares_same_source_diff_event:
        motive_event['independent_motive'] = True
    motive = _build_motive_candidate(
        motive_event, effective_at, activation, urgency, persistence, intent,
        understanding, reasoner_packet, existing_top=None if shares_same_source_diff_event else active_top,
        cognition_est=cognition_est, app_info=app_info, env_info=env_info,
        appraisal_summary=appraisal_summary, reevaluation=motive_reeval,
        existing_motives=motives
    )
    motive['reevaluation'] = motive_reeval
    motives[motive['motive_id']] = motive

    # Support multiple independent motives from a multi-event message (Requirement 2.2.6)
    secondary_motives = _build_secondary_motives(
        motive_event, effective_at, activation, urgency, persistence, understanding, motives, motive
    )
    event_motive_ids = [motive['motive_id']]
    for sec_m in secondary_motives:
        motives[sec_m['motive_id']] = sec_m
        event_motive_ids.append(sec_m['motive_id'])

    for sid in (new_src_ids or raw_src_ids):
        eval_src_map[sid] = {'event_id': ev_id, 'at': effective_at}
    if len(eval_src_map) > 120:
        for old_sid in list(eval_src_map)[:-120]:
            eval_src_map.pop(old_sid, None)

    if len(motives) > 24:
        ordered = sorted(motives.values(), key=lambda x: (x['status'] in ('pending', 'deferred', 'partially_satisfied'), x['updated_at']))
        for stale in ordered[:-24]:
            motives.pop(stale['motive_id'], None)

    tt_adj = turn_taking_adjustments({
        'activation': activation,
        'urgency': urgency,
        'persistence': persistence,
        'expressive_intent': intent,
    }, env_info['turn_complete'])
    act_terms = policy_action_terms({
        'activation': activation,
        'urgency': urgency,
        'persistence': persistence,
        'expressive_intent': intent,
    })

    next_rev = row['state_revision'] + 1
    resumed_motive = active_top if (
        active_top and active_top['motive_id'] == motive['motive_id'] and row['state_revision'] > 0
    ) else None

    result = {
        'schema': SCHEMA,
        'subject_id': owner,
        'event_id': ev_id,
        'scope': scope,
        'person_id': person,
        'session_id': session_id,
        'at': iso(effective_at),
        'updated_at': effective_at,
        'delta_seconds': round(dt, 3),
        'state_revision': next_rev,
        'catalog_revision': state['revision'] + 1,
        'activation': round(activation, 6),
        'urgency': round(urgency, 6),
        'persistence': round(persistence, 6),
        'expressive_intent': intent,
        'intent_scores': intent_scores,
        'target': copy.deepcopy(motive['target']),
        'content_anchor': copy.deepcopy(motive['content_anchor']),
        'intended_expression': copy.deepcopy(motive['intended_expression']),
        'motive_reevaluation': copy.deepcopy(motive_reeval),
        'source_evidence': copy.deepcopy(motive['source_evidence']),
        'status': motive['status'],
        'active_motive_id': motive['motive_id'],
        'active_motive': copy.deepcopy(motive),
        'motive_ids': event_motive_ids,
        'secondary_motive_ids': [m['motive_id'] for m in secondary_motives],
        'resumed_motive': copy.deepcopy(resumed_motive),
        'pending_motives_count': sum(1 for m in motives.values() if m['status'] in ('pending', 'deferred', 'partially_satisfied')),
        'expired_motive_ids': evolved['expired_ids'],
        'incremental_evaluation': {
            'prior_source_ids': prior_src_ids,
            'new_source_ids': new_src_ids,
            'stimulus_chars': len(stimulus_text),
            'revised_in_place': restored_from_snapshot,
        },
        'channel_contributions': {
            'personality_b_theta': [round(float(x), 6) for x in b_theta],
            'fast_emotion': [round(float(x), 6) for x in term_e],
            'slow_mood': [round(float(x), 6) for x in term_m],
            'cognitive_appraisal': [round(float(x), 6) for x in term_q],
            'relationship': [round(float(x), 6) for x in term_r],
            'dialogue_context': [round(float(x), 6) for x in term_c],
            'residual_motive': [round(float(x), 6) for x in term_u],
        },
        'frozen_numeric_inputs': {'theta':base_info['x_theta'],'emotion':e_vec.tolist(),'mood':m_vec.tolist(),
            'appraisal':q_vec.tolist(),'relationship':r_vec.tolist(),'context':c_vec.tolist(),'residual':u_vec.tolist(),
            'theta_mask':base_info['known_mask']},
        'inputs_summary': {
            'personality_baseline': base_info['baseline'],
            'known_construct_count': base_info['known_construct_count'],
            'emotion': emo_info,
            'appraisal': app_info,
            'relationship': rel_info,
            'environment': env_info,
        },
        'turn_taking_influence': tt_adj,
        'policy_score_terms': act_terms,
        'model_version': model['sha256'],
        'calibration_status': model['calibration']['status'],
        'updated': True,
        'replayed': False,
    }

    row.update(
        activation=result['activation'],
        urgency=result['urgency'],
        persistence=result['persistence'],
        expressive_intent=intent,
        baseline=base_info['baseline'],
        updated_at=effective_at,
        state_revision=next_rev,
        last_event_id=ev_id,
        active_motive_id=motive['motive_id'],
        motives=motives,
    )
    row['events'][ev_id] = {'content_sha256': fingerprint, 'result': copy.deepcopy(result)}
    if len(row['events']) > 60:
        for old_k in list(row['events'])[:-60]:
            row['events'].pop(old_k, None)

    # Register initial correlation binding for this event
    state, corr_entry = bind_turn_correlation(
        state, scope, person,
        source_message_ids=raw_src_ids or [ev_id],
        cognitive_event_id=ev_id if raw_ev_id.startswith(('cognition:', 'tt:', 'ev:')) else None,
        pmm_event_id=ev_id,
        motive_ids=event_motive_ids,
        delivery_outcome=motive['status'],
        user_text=text,
        at=effective_at,
    )
    result['event_correlation'] = corr_entry
    state['streams'][skey]['events'][ev_id]['result']['event_correlation'] = copy.deepcopy(corr_entry)

    state['revision'] += 1
    state['history'] = state.get('history', [])[-79:] + [{
        'event_id': ev_id,
        'scope': scope,
        'person_id': person,
        'at': effective_at,
        'activation': result['activation'],
        'urgency': result['urgency'],
        'persistence': result['persistence'],
        'expressive_intent': intent,
        'motive_id': motive['motive_id'],
        'motive_ids': event_motive_ids,
        'status': motive['status'],
        'state_revision': next_rev,
    }]
    validate(state, owner)
    return state, result


def apply_delivery_outcome(draft_state, scope, person, outcome, *, at=None, reason='', delivered_parts=0, planned_parts=0,
                           has_deferred_step=False, unsent_parts=None, deferred_steps=None, target_motive_id=None,
                           turn_id=None, source_message_ids=(), persisted_user_ids=(), persisted_assistant_ids=(),
                           cognitive_event_id=None, pmm_event_id=None, user_text='', interaction_kind='final_reply'):
    """Update the draft ExpressiveDrive state according to the actual turn execution / ACK outcome (Round 3 & Round 4)."""
    from .expression_plan import normalize_deferred_steps
    state = copy.deepcopy(draft_state)
    owner = state['subject_id']
    skey = stream_key(owner, scope, person)
    row = state['streams'].get(skey)
    if not row:
        return state, None
    ts = seconds(at if at is not None else max(now(), row['updated_at']))
    prior_active_id = row.get('active_motive_id')
    mid = target_motive_id if target_motive_id is not None else prior_active_id
    motive = row['motives'].get(mid) if mid else None

    norm_def_steps, norm_def_count = normalize_deferred_steps(
        deferred_steps if deferred_steps is not None else ((motive or {}).get('intended_expression') or {}).get('deferred_user_reply_steps')
    )
    effective_has_deferred = bool(has_deferred_step or norm_def_count > 0)

    if outcome == 'delivered_full' and interaction_kind == 'backchannel':
        outcome = 'backchannel_delivered'
    if outcome == 'backchannel_delivered':
        if motive:
            motive.update(status='partially_satisfied', delivery_outcome=outcome,
                          defer_reason='listening_after_acknowledgement', updated_at=ts,
                          state_revision=motive['state_revision'] + 1)
            ie = motive.setdefault('intended_expression', {})
            ie.update(stage='acknowledged_listening', epistemic_status='partially_delivered_intent_not_verified_fact')
            for step in ie.get('generated_steps', []):
                if isinstance(step, dict):
                    step.update(status='delivered_ack', epistemic_status='delivered_utterance_not_verified_fact')
            # No unsent sentence is invented. Later input must be evaluated anew.
        row['expressive_intent'] = 'LISTEN'
    elif outcome == 'delivered_full':
        if motive:
            ie = motive.setdefault('intended_expression', {})
            for gs in (ie.get('generated_steps') or []):
                if isinstance(gs, dict):
                    gs['status'] = 'delivered_ack'
                    gs['epistemic_status'] = 'delivered_utterance_not_verified_fact'
            if effective_has_deferred:
                motive['status'] = 'partially_satisfied'
                motive['delivery_outcome'] = 'delivered_partial'
                motive['defer_reason'] = reason or 'awaiting_user_reply_for_next_step'
                motive['activation'] = round(clamp(motive['activation'] * 0.58, 0.15, 1.0), 6)
                motive['urgency'] = round(clamp(motive['urgency'] * 0.42, 0.10, 1.0), 6)
                ie['stage'] = 'partially_expressed_awaiting_reply'
                ie['epistemic_status'] = 'partially_delivered_intent_not_verified_fact'
                if norm_def_steps:
                    ie['unsent_plan_steps'] = [
                        {**copy.deepcopy(s), 'status': 'deferred', 'epistemic_status': 'unexpressed_internal_intent_not_spoken_fact'}
                        for s in norm_def_steps
                    ]
                    ie['candidate_point_or_question'] = f"待对方回复后继续：{norm_def_steps[0]['intended_point'][:120]}"
                    motive['content_anchor']['candidate_point_or_question'] = ie['candidate_point_or_question']
            else:
                motive['status'] = 'satisfied'
                motive['delivery_outcome'] = 'delivered_full'
                motive['defer_reason'] = ''
                if turn_id:
                    motive['completed_by_turn_id'] = str(turn_id)
                motive['activation'] = round(clamp(motive['activation'] * 0.28, 0.0, 1.0), 6)
                motive['urgency'] = round(clamp(motive['urgency'] * 0.20, 0.0, 1.0), 6)
                ie['stage'] = 'expressed_and_acknowledged'
                ie['epistemic_status'] = 'delivered_utterance_not_verified_fact'
                ie['unsent_plan_steps'] = []
            motive['updated_at'] = ts
            motive['state_revision'] += 1
        # Independent lifecycle rule (Round 4 Issue 2): updating one motive NEVER auto-modifies other motives.
        remaining_unfinished = [
            m for m in row['motives'].values()
            if m['status'] in ('pending', 'deferred', 'partially_satisfied')
        ]
        # Preserve prior_active_id if active motive switched to another unfinished motive B while A was in flight (Round 4 Issue 1)
        prior_active_m = row['motives'].get(prior_active_id) if prior_active_id else None
        if prior_active_id and prior_active_id != mid and isinstance(prior_active_m, dict) and prior_active_m.get('status') in ('pending', 'deferred', 'partially_satisfied'):
            row['active_motive_id'] = prior_active_id
            ref_m = prior_active_m
        elif remaining_unfinished:
            remaining_unfinished.sort(key=lambda m: (m['activation'], m['updated_at']), reverse=True)
            row['active_motive_id'] = remaining_unfinished[0]['motive_id']
            ref_m = remaining_unfinished[0]
        else:
            row['active_motive_id'] = mid if (motive and motive['status'] in ('pending', 'deferred', 'partially_satisfied')) else None
            ref_m = motive
        row['activation'] = round(clamp(0.45 * row['baseline']['activation'] + 0.55 * (ref_m['activation'] if ref_m else row['activation'] * 0.4), 0.0, 1.0), 6)
        row['urgency'] = round(clamp(0.40 * row['baseline']['urgency'] + 0.60 * (ref_m['urgency'] if ref_m else row['urgency'] * 0.3), 0.0, 1.0), 6)
        row['consecutive_deferrals'] = 0
        if row['expressive_intent'] == 'TAKE_TURN' and not effective_has_deferred and not remaining_unfinished:
            row['expressive_intent'] = 'CLOSE' if row['activation'] < 0.32 else 'TAKE_TURN'
    elif outcome == 'delivered_partial':
        if motive:
            motive['status'] = 'partially_satisfied'
            motive['delivery_outcome'] = 'delivered_partial'
            motive['defer_reason'] = reason or f'partial_delivery_{delivered_parts}_of_{max(planned_parts, delivered_parts + 1)}'
            motive['activation'] = round(clamp(motive['activation'] * 0.75, 0.18, 1.0), 6)
            motive['urgency'] = round(clamp(motive['urgency'] * 0.68, 0.15, 1.0), 6)
            motive['updated_at'] = ts
            motive['state_revision'] += 1
            ie = motive.setdefault('intended_expression', {})
            ie['stage'] = 'planned_expression_partially_unsent'
            ie['epistemic_status'] = 'partially_delivered_intent_not_verified_fact' if delivered_parts else 'unexpressed_internal_intent_not_spoken_fact'
            gen_steps = ie.get('generated_steps') if isinstance(ie.get('generated_steps'), list) else []
            for idx_g, gs in enumerate(gen_steps):
                if isinstance(gs, dict):
                    gs['status'] = 'delivered_ack' if idx_g < delivered_parts else 'unsent_after_interruption'
                    gs['epistemic_status'] = 'delivered_utterance_not_verified_fact' if idx_g < delivered_parts else 'unexpressed_internal_intent_not_spoken_fact'
            unsent_step_objs = []
            if len(gen_steps) > delivered_parts:
                for idx_rem, rem_s in enumerate(gen_steps[delivered_parts:], start=delivered_parts + 1):
                    if isinstance(rem_s, dict):
                        pt = str(rem_s.get('intended_point') or '').strip()
                        if not pt and unsent_parts and (idx_rem - delivered_parts - 1) < len(unsent_parts):
                            pt = str(unsent_parts[idx_rem - delivered_parts - 1]).strip()
                        unsent_step_objs.append({
                            **copy.deepcopy(rem_s),
                            'intended_point': pt[:240] or rem_s.get('purpose', ''),
                            'depends_on': 'next_speaking_opportunity',
                            'status': 'deferred',
                            'epistemic_status': 'unexpressed_internal_intent_not_spoken_fact',
                        })
            elif unsent_parts:
                for i, p_text in enumerate(unsent_parts[:4]):
                    if str(p_text).strip():
                        unsent_step_objs.append({
                            'step_id': f'step_{delivered_parts + i + 1:02d}',
                            'act': 'unspecified',
                            'purpose': f'待补发第 {delivered_parts + i + 1} 条未送达内容',
                            'intended_point': str(p_text).strip()[:240],
                            'depends_on': 'next_speaking_opportunity',
                            'status': 'deferred',
                            'epistemic_status': 'unexpressed_internal_intent_not_spoken_fact',
                        })
            for ds in norm_def_steps:
                unsent_step_objs.append({
                    **copy.deepcopy(ds),
                    'status': 'deferred',
                    'epistemic_status': 'unexpressed_internal_intent_not_spoken_fact',
                })
            ie['unsent_plan_steps'] = unsent_step_objs
            if unsent_step_objs:
                ie['candidate_point_or_question'] = f"待继续表达未发完的要点：{unsent_step_objs[0]['intended_point'][:120]}"
                motive['content_anchor']['candidate_point_or_question'] = ie['candidate_point_or_question']
        row['consecutive_deferrals'] = row.get('consecutive_deferrals', 0) + 1
        row['expressive_intent'] = 'DEFER'
    elif outcome in ('deferred_wait', 'policy_silence'):
        if motive:
            if motive['activation'] >= 0.28 and motive['persistence'] >= 0.25:
                motive['status'] = 'deferred'
                motive['delivery_outcome'] = outcome
                motive['defer_reason'] = reason or ('turn_taking_wait' if outcome == 'deferred_wait' else 'policy_or_regulation_restraint')
                ie = motive.setdefault('intended_expression', {})
                ie.setdefault('resumption_policy', {})['defer_reason'] = motive['defer_reason']
            else:
                motive['status'] = 'abandoned'
                motive['delivery_outcome'] = 'abandoned'
                motive['defer_reason'] = reason or 'low_drive_no_need_to_retain'
            motive['updated_at'] = ts
            motive['state_revision'] += 1
        row['consecutive_deferrals'] = row.get('consecutive_deferrals', 0) + 1
        if row['expressive_intent'] not in ('LISTEN', 'DEFER', 'CLOSE'):
            row['expressive_intent'] = 'DEFER' if (motive and motive['status'] == 'deferred') else 'LISTEN'
    elif outcome == 'abandoned':
        if target_motive_id and target_motive_id in row['motives']:
            tm = row['motives'][target_motive_id]
            tm['status'] = 'abandoned'
            tm['delivery_outcome'] = 'abandoned'
            tm['defer_reason'] = reason or 'explicitly_abandoned'
            tm['updated_at'] = ts
            tm['state_revision'] += 1
            if row.get('active_motive_id') == target_motive_id:
                rem = [m for m in row['motives'].values() if m['status'] in ('pending', 'deferred', 'partially_satisfied')]
                rem.sort(key=lambda m: (m['activation'], m['updated_at']), reverse=True)
                row['active_motive_id'] = rem[0]['motive_id'] if rem else None
        else:
            for m in row['motives'].values():
                if m['status'] in ('pending', 'deferred', 'partially_satisfied'):
                    m['status'] = 'abandoned'
                    m['delivery_outcome'] = 'abandoned'
                    m['defer_reason'] = reason or 'explicitly_abandoned'
                    m['updated_at'] = ts
                    m['state_revision'] += 1
            row['active_motive_id'] = None
            row['consecutive_deferrals'] = 0
            row['expressive_intent'] = 'CLOSE'

    row['updated_at'] = max(row['updated_at'], ts)
    _sync_satisfied_source_records(row)

    # Bind correlation across source_message_ids, turn_id, persisted_message_ids, and all motives sharing this source/event
    ev_src_ids = list(source_message_ids) or list(_motive_source_ids(motive))
    ev_motive_ids = [motive['motive_id']] if motive else []
    ev_anchor = motive['content_anchor'].get('event_id') if motive else None
    for om in row['motives'].values():
        if not isinstance(om, dict):
            continue
        if (ev_anchor and (om.get('parent_event_id') == ev_anchor or om['content_anchor'].get('event_id') == ev_anchor)) or (ev_src_ids and (_motive_source_ids(om) & set(ev_src_ids))):
            if om['motive_id'] not in ev_motive_ids:
                ev_motive_ids.append(om['motive_id'])
    state, corr_entry = bind_turn_correlation(
        state, scope, person,
        source_message_ids=ev_src_ids,
        cognitive_event_id=cognitive_event_id,
        pmm_event_id=pmm_event_id or (motive['content_anchor'].get('event_id') if motive else row.get('last_event_id')),
        turn_id=turn_id,
        persisted_user_ids=persisted_user_ids,
        persisted_assistant_ids=persisted_assistant_ids,
        motive_ids=ev_motive_ids,
        delivery_outcome=outcome,
        user_text=user_text,
        at=ts,
    )
    row = state['streams'][skey]
    _sync_satisfied_source_records(row)
    motive = row['motives'].get(mid) if mid else None

    if row.get('last_event_id') and row['last_event_id'] in row['events']:
        ev_res = row['events'][row['last_event_id']]['result']
        ev_res['post_execution_outcome'] = outcome
        ev_res['post_execution_status'] = motive['status'] if motive else 'none'
        ev_res['event_correlation'] = corr_entry
        if motive:
            ev_res['active_motive'] = copy.deepcopy(motive)
            ev_res['intended_expression'] = copy.deepcopy(motive.get('intended_expression'))
            ev_res['status'] = motive['status']
    validate(state, owner)
    return state, copy.deepcopy(motive)


def feedback_to_emotion_appraisal(drive_result, outcome, understanding=None, relation=None, *, feedback_id=None, obstructed=False):
    """Bidirectional coupling (Fix 1): ExpressiveDrive outcome -> emotion appraisal checks."""
    if not isinstance(drive_result, dict):
        return {'applied': False, 'checks_delta': {}, 'reason': 'no_drive_result'}
    act = float(drive_result.get('activation', 0.45))
    urg = float(drive_result.get('urgency', 0.40))
    pers = float(drive_result.get('persistence', 0.45))
    intent = str(drive_result.get('expressive_intent', 'TAKE_TURN'))
    u = understanding or {}
    sem = u.get('semantic') or {}
    congruence = float(sem.get('goal_congruence', 0.55) if sem.get('goal_congruence') is not None else 0.55)
    hostility = float(sem.get('hostility', 0.0) or 0.0)
    fam = float((relation or {}).get('familiarity', 0.2) or 0.2)

    deltas = {}
    internal_kind = 'neutral_expression_outcome'
    rationale = 'neutral_expression_outcome'
    delivered_externally = False

    if outcome == 'delivered_full':
        delivered_externally = True
        internal_kind = 'delivered_full_expression'
        direction = (congruence - 0.42) * (1.0 - 0.75 * hostility) * (0.75 + 0.25 * fam)
        if abs(direction) < 0.03:
            direction = 0.06 if hostility < 0.3 else -0.06
        deltas['affect.appraisal.goal_conduciveness'] = round(clamp(0.22 * max(0.3, act) * direction, -0.18, 0.18), 6)
        deltas['affect.appraisal.control'] = round(clamp(0.14 * max(0.3, act) * (0.60 - hostility), -0.12, 0.14), 6)
        deltas['affect.appraisal.urgency'] = round(clamp(-0.12 * urg, -0.15, -0.02), 6)
        deltas['affect.appraisal.goal_relevance'] = round(clamp(0.08 * act * (1.0 - 0.5 * hostility), 0.01, 0.10), 6)
        rationale = 'expression_delivered_and_acknowledged_modulated_by_congruence'
    elif outcome == 'delivered_partial':
        delivered_externally = True
        internal_kind = 'interrupted_partial_expression'
        obstruct = max(0.12, act * 0.55 + urg * 0.45)
        deltas['affect.appraisal.control'] = round(clamp(-0.22 * obstruct, -0.20, -0.04), 6)
        deltas['affect.appraisal.goal_conduciveness'] = round(clamp(-0.18 * obstruct, -0.16, -0.03), 6)
        deltas['affect.appraisal.urgency'] = round(clamp(0.14 * obstruct, 0.03, 0.16), 6)
        rationale = 'partial_expression_interrupted_before_completion'
    elif obstructed or outcome == 'obstructed_expression' or (outcome in ('deferred_wait', 'policy_silence') and act >= 0.58 and urg >= 0.52 and intent == 'TAKE_TURN'):
        delivered_externally = False
        internal_kind = 'obstructed_or_suppressed_expression'
        obstruct = max(0.10, (act - 0.35) * 0.6 + (urg - 0.35) * 0.4)
        deltas['affect.appraisal.control'] = round(clamp(-0.20 * obstruct, -0.18, -0.03), 6)
        deltas['affect.appraisal.goal_conduciveness'] = round(clamp(-0.15 * obstruct, -0.14, -0.02), 6)
        deltas['affect.appraisal.urgency'] = round(clamp(0.10 * obstruct, 0.02, 0.12), 6)
        rationale = 'high_urgency_expression_obstructed_or_involuntarily_delayed'
    elif outcome in ('deferred_wait', 'policy_silence', 'proactive_deferred'):
        delivered_externally = False
        internal_kind = 'voluntary_restraint_or_listening'
        deltas['affect.appraisal.control'] = round(clamp(0.10 * max(0.3, pers) + 0.04 * (1.0 - urg), 0.02, 0.12), 6)
        deltas['affect.appraisal.urgency'] = round(clamp(-0.08 * max(0.25, 1.0 - urg), -0.10, -0.01), 6)
        deltas['affect.appraisal.goal_conduciveness'] = round(clamp(0.05 * (pers - 0.35), -0.03, 0.06), 6)
        rationale = 'voluntary_attentive_listening_or_measured_deferral'

    return {
        'applied': bool(deltas),
        'feedback_id': feedback_id or f"efb:{drive_result.get('event_id', 'idle')}:{internal_kind}",
        'outcome': outcome,
        'internal_event_kind': internal_kind,
        'delivered_externally': delivered_externally,
        'checks_delta': deltas,
        'rationale': rationale,
        'hardcoded_valence_rule_used': False,
    }


def _classify_history_record_for_proactive(rec, row, session_history=None):
    """Determine whether a historical user message record has already been answered/tracked (Round 3 Issue 1 & Round 4 Issue 2).

    First identifies all concrete motives associated with the source. A source is only classified as
    'completed' when NO associated unfinished motives remain AND delivery/terminal status is confirmed.
    Returns ('completed' | 'already_tracked_unfinished' | 'unaddressed', reason_str).
    """
    rid = str(rec.get('id') or '').strip()
    tid = str(rec.get('turn_id') or '').strip()
    if not tid and rid.endswith(':u') and len(rid) > 2:
        tid = rid[:-2]

    motives = row.get('motives') or {}
    correlations = row.get('event_correlations') or {}

    # 1. Identify all correlations and concrete motives associated with this source record
    matched_corrs = []
    corr_motive_ids = set()
    for corr in correlations.values():
        if not isinstance(corr, dict):
            continue
        p_users = (corr.get('persisted_message_ids') or {}).get('user') or []
        src_ids = corr.get('source_message_ids') or []
        if (rid and (rid in p_users or rid in src_ids)) or (tid and corr.get('turn_id') == tid):
            matched_corrs.append(corr)
            for cmid in (corr.get('expressive_motive_ids') or []):
                corr_motive_ids.add(str(cmid))

    associated_motives = []
    for mid, m_obj in motives.items():
        if not isinstance(m_obj, dict):
            continue
        m_srcs = _motive_source_ids(m_obj)
        if (rid and rid in m_srcs) or (tid and tid in m_srcs) or (mid in corr_motive_ids):
            associated_motives.append(m_obj)

    # 2. If concrete motives exist for this source, classify by their individual lifecycle states first (Round 4 Issue 2)
    if associated_motives:
        unfinished = [
            m for m in associated_motives
            if m.get('status') in ('pending', 'deferred', 'partially_satisfied')
        ]
        if unfinished:
            return 'already_tracked_unfinished', 'active_unfinished_motives_exist_for_source'
        return 'completed', 'all_associated_motives_satisfied_or_abandoned'

    # 3. No motives in row['motives'] reference this source: check correlations, history, and satisfied_proactive_record_ids
    for corr in matched_corrs:
        m_outcomes = corr.get('motive_outcomes') or {}
        if any(st in ('pending', 'deferred', 'partially_satisfied') for st in m_outcomes.values()):
            return 'already_tracked_unfinished', 'tracked_by_active_unfinished_motive'
        if corr.get('delivery_outcome') == 'backchannel_delivered':
            return 'already_tracked_unfinished', 'acknowledged_backchannel_waiting_for_continuation'
        if corr.get('all_motives_terminal') or corr.get('delivery_outcome') == 'delivered_full' or ((corr.get('persisted_message_ids') or {}).get('assistant')):
            return 'completed', 'correlated_turn_delivered_full'

    if isinstance(session_history, list) and session_history:
        assistant_turns = {
            str(h.get('turn_id')).strip()
            for h in session_history
            if isinstance(h, dict) and h.get('role') == 'assistant' and str(h.get('content') or '').strip() and h.get('turn_id')
        }
        if tid and tid in assistant_turns:
            return 'completed', 'paired_assistant_reply_exists_for_turn_id'
        for idx_h, h in enumerate(session_history):
            if isinstance(h, dict) and str(h.get('id')) == rid:
                if not tid and any(
                    isinstance(later, dict) and later.get('role') == 'assistant' and str(later.get('content') or '').strip()
                    for later in session_history[idx_h + 1:]
                ):
                    return 'completed', 'followed_by_assistant_message_in_history'
                break

    sat_ids = set(row.get('satisfied_proactive_record_ids') or [])
    if rid in sat_ids or (tid and tid in sat_ids):
        return 'completed', 'recorded_in_satisfied_proactive_record_ids'

    return 'unaddressed', 'no_completed_reply_or_existing_motive_found'


def evaluate_proactive(store, profile, scope, person=None, session_id=None, at=None,
                       affect_view=None, relation=None, recent_records=None, session_history=None, commit=False):
    """Evaluate ExpressiveDrive when NO new user message has arrived (Chain 2: idle / proactive, Fix 4, Round 3 Issue 1 & Round 4 Issue 2)."""
    owner = profile['id']
    base_state = store.meta(KEY)
    if base_state is None:
        base_state = migrate(store)
    state = copy.deepcopy(base_state)
    expected_rev = base_state['revision']
    model = state['model']
    ts = seconds(at if at is not None else now())
    person_id = str(person or ('qq:' + scope.rsplit(':', 1)[-1] if ':qq:' in scope else 'web:owner'))
    skey = stream_key(owner, scope, person_id)
    row = state['streams'].get(skey)
    if row is None:
        row = initial_stream(owner, scope, person_id, session_id or scope, ts, model, profile)
        state['streams'][skey] = row

    effective_ts = max(ts, row['updated_at'])
    dt = effective_ts - row['updated_at']
    valid_records = [r for r in (recent_records or []) if isinstance(r, dict) and str(r.get('text', '')).strip()]
    recent_text = '\n'.join(str(r['text']) for r in valid_records[-3:])

    base_info = personality_baseline(profile, model)
    evolved = _evolve_stream_over_time(row, base_info, dt, current_text=recent_text)
    motives = evolved['motives']

    e_vec, m_vec, emo_info = _extract_emotion_mood(affect_view)
    r_vec, rel_info = _extract_relationship(relation)

    # Re-evaluate all unfinished motives in idle context; only expire motives that reached defer limit or decayed
    valid_unfinished = []
    for cand_m in evolved['active_unfinished']:
        if cand_m.get('origin')=='researcher':continue
        if cand_m.get('origin')=='memory_reflection':
            from .motive_generation import sources_current
            if not sources_current(store,profile,cand_m):
                cand_m.update(status='abandoned',delivery_outcome='abandoned',defer_reason='source_evidence_changed',updated_at=effective_ts,state_revision=cand_m['state_revision']+1)
                motives[cand_m['motive_id']]=cand_m;evolved['expired_ids'].append(cand_m['motive_id']);continue
        if int(cand_m.get('proactive_defer_count', 0)) >= 3 or cand_m.get('activation', 0.0) < 0.20:
            cand_m['status'] = 'abandoned'
            cand_m['delivery_outcome'] = 'abandoned'
            cand_m['defer_reason'] = 'proactive_opportunities_exhausted_or_decayed'
            cand_m['updated_at'] = effective_ts
            cand_m['state_revision'] += 1
            motives[cand_m['motive_id']] = cand_m
            evolved['expired_ids'].append(cand_m['motive_id'])
        else:
            valid_unfinished.append(cand_m)
    evolved['active_unfinished'] = valid_unfinished
    top_motive = valid_unfinished[0] if valid_unfinished else None

    # Sync satisfied_proactive_record_ids so shared sources with remaining unfinished motives are NEVER marked completed
    row['motives'] = motives
    sat_list = _sync_satisfied_source_records(row)

    # Classify recent_records using concrete motives + event_correlations + session_history
    unaddressed_records = []
    for r in valid_records:
        rec_status, _ = _classify_history_record_for_proactive(r, row, session_history=session_history)
        if rec_status == 'completed':
            rid = str(r.get('id') or '').strip()
            if rid and rid not in sat_list:
                sat_list.append(rid)
        elif rec_status == 'unaddressed':
            unaddressed_records.append(r)

    if not unaddressed_records:
        contact = (store.meta('social_contacts') or {}).get(scope) or {}
        last_ev_key = str(contact.get('last_event_key') or '').strip()
        if last_ev_key:
            contact_text = str(contact.get('last_input_text') or (valid_records[-1]['text'] if valid_records else '')).strip()
            if contact_text:
                contact_rec = {'id': last_ev_key, 'text': contact_text}
                c_status, _ = _classify_history_record_for_proactive(contact_rec, row, session_history=None)
                if c_status == 'completed':
                    if last_ev_key not in sat_list:
                        sat_list.append(last_ev_key)
                elif c_status == 'unaddressed':
                    unaddressed_records.append(contact_rec)

    spawned_from_records = False
    if top_motive is None and unaddressed_records:
        last_rec = unaddressed_records[-1]
        rec_text = str(last_rec.get('text', '')).strip()
        rec_id = str(last_rec.get('id') or 'u0').strip()
        _, app_idle = _extract_appraisal({}, None, None, profile, rec_text)
        rec_event = {
            'id': 'proactive_seed:' + str(rec_id or digest([scope, rec_text])[:16]),
            'subject_id': owner,
            'source_event_ids': [rec_id],
            'text': rec_text,
            'scope': scope,
            'person': person_id,
            'session_id': session_id or scope,
        }
        seed_act = clamp(0.45 * base_info['baseline']['activation'] + 0.35 * app_idle['personal_relevance'] + 0.25 * app_idle['trait_topic_resonance'], 0.28, 0.85)
        seed_urg = clamp(0.40 * base_info['baseline']['urgency'] + 0.30 * app_idle['goal_relevance'] + 0.15, 0.24, 0.80)
        seed_pers = clamp(0.50 * base_info['baseline']['persistence'] + 0.35 * app_idle['personal_relevance'] + 0.15, 0.32, 0.88)
        top_motive = _build_motive_candidate(
            rec_event, effective_ts, seed_act, seed_urg, seed_pers, 'INITIATE',
            understanding={'topic': rec_text[:40], 'intent': 'proactive_followup'},
            reasoner_packet={'quote': rec_text[:200]},
            app_info=app_idle,
            env_info={'turn_complete': 1.0, 'obligation': 0.35},
            appraisal_summary='基于历史未完结的真实对话记录形成主动关怀/延续交流目标',
            existing_motives=motives
        )
        top_motive['status'] = 'deferred'
        top_motive['delivery_outcome'] = 'deferred_wait'
        top_motive['defer_reason'] = 'awaiting_proactive_window'
        top_motive['intended_expression']['stage'] = 'proactive_followup'
        motives[top_motive['motive_id']] = top_motive
        row['motives'] = motives
        evolved['active_unfinished'].insert(0, top_motive)
        state, _ = bind_turn_correlation(
            state, scope, person_id,
            source_message_ids=[rec_id],
            persisted_user_ids=[rec_id],
            motive_ids=[top_motive['motive_id']],
            delivery_outcome='deferred_wait',
            user_text=rec_text,
            at=effective_ts,
        )
        row = state['streams'][skey]
        motives = row['motives']
        spawned_from_records = True

    p = model['parameters']
    b_theta = np.asarray(base_info['logits'], dtype=float)
    term_e = np.asarray(p['W_e'], dtype=float) @ e_vec
    term_m = np.asarray(p['W_m'], dtype=float) @ m_vec
    term_r = np.asarray(p['W_r'], dtype=float) @ r_vec
    u_vec = np.array([
        top_motive['activation'],
        top_motive['urgency'],
        top_motive['persistence'],
        0.65,
        min(1.0, len(evolved['active_unfinished']) * 0.25),
    ], dtype=float) if top_motive else np.zeros(N_RESIDUAL, dtype=float)
    term_u = np.asarray(p['W_u'], dtype=float) @ u_vec

    q_idle = np.zeros(N_APPRAISAL, dtype=float)
    if top_motive:
        q_idle[0] = top_motive['activation'] * 0.75
        q_idle[1] = top_motive['persistence'] * 0.70
        q_idle[10] = top_motive['activation'] * 0.65
    term_q = np.asarray(p['W_q'], dtype=float) @ q_idle

    logits = b_theta + term_e + term_m + term_q + term_r + term_u
    probs = _sigmoid(logits)
    resting_activation = float(_sigmoid(b_theta + term_e + term_m + term_r)[0])
    activation = float(probs[0])
    urgency = float(probs[1])
    persistence = float(probs[2])

    if top_motive:
        activation = max(activation, float(top_motive['activation']))
        urgency = max(urgency, float(top_motive['urgency']))
        persistence = max(persistence, float(top_motive['persistence']))

    has_concrete_motive = bool(
        top_motive is not None
        and top_motive.get('status') in ('pending', 'deferred', 'partially_satisfied')
        and isinstance(top_motive.get('intended_expression'), dict)
        and bool(top_motive['intended_expression'].get('intended_goal'))
        and bool(top_motive.get('source_evidence'))
        and float(top_motive.get('activation', 0.0)) >= 0.22
        and float(top_motive.get('persistence', 0.0)) >= 0.24
    )

    env_idle = {
        'turn_complete': 1.0,
        'addressed': False,
        'is_private': scope.startswith('private:'),
        'partner_closing': False,
        'obligation': 0.0,
        'interruption_cost': 0.1,
    }
    app_idle_info = {'disengagement': 0.0, 'conflict': 0.0, 'consequence': 0.2}
    intent, intent_scores = select_expressive_intent(
        activation, urgency, persistence, env_idle, app_idle_info, emo_info,
        has_unfinished=has_concrete_motive, mode='proactive'
    )

    suppressed = emo_info['regulation_strategy'] in ('suppression', 'expressive_suppression')
    proactive_eligible = bool(
        has_concrete_motive
        and not suppressed
        and intent != 'CLOSE'
    )
    ineligible_reason = (
        '' if proactive_eligible
        else 'emotion_regulation_suppression' if suppressed
        else 'high_baseline_only_no_concrete_expressive_motive' if not has_concrete_motive
        else 'expressive_intent_closed'
    )

    proactive_motive_score = round(
        (0.45 * float(top_motive['activation']) + 0.30 * float(top_motive['urgency']) + 0.25 * float(top_motive['persistence']))
        if has_concrete_motive else 0.0,
        6
    )

    new_active_mid = top_motive['motive_id'] if top_motive else None
    changed = bool(dt > 0 or evolved['expired_ids'] or spawned_from_records or row.get('active_motive_id') != new_active_mid)
    next_rev = row['state_revision'] + (1 if changed else 0)
    row.update(
        activation=round(activation, 6),
        urgency=round(urgency, 6),
        persistence=round(persistence, 6),
        expressive_intent=intent,
        baseline=base_info['baseline'],
        updated_at=effective_ts,
        state_revision=next_rev,
        motives=motives,
        active_motive_id=new_active_mid,
    )
    if changed:
        state['revision'] += 1

    evaluation = {
        'schema': SCHEMA,
        'mode': 'idle_proactive_evaluation',
        'subject_id': owner,
        'scope': scope,
        'person_id': person_id,
        'at': iso(effective_ts),
        'updated_at': effective_ts,
        'delta_seconds': round(dt, 3),
        'state_revision': next_rev,
        'activation': round(activation, 6),
        'urgency': round(urgency, 6),
        'persistence': round(persistence, 6),
        'expressive_intent': intent,
        'intent_scores': intent_scores,
        'general_initiation_tendency': round(resting_activation, 6),
        'general_tendency_not_sufficient_alone': True,
        'has_concrete_motive': has_concrete_motive,
        'proactive_motive_score': proactive_motive_score,
        'proactive_eligible': proactive_eligible,
        'ineligible_reason': ineligible_reason,
        'active_motive': copy.deepcopy(top_motive),
        'intended_expression': copy.deepcopy(top_motive.get('intended_expression')) if top_motive else None,
        'unfinished_motives': [copy.deepcopy(m) for m in evolved['active_unfinished'][:4]],
        'expired_motive_ids': evolved['expired_ids'],
        'pause_recovery_boost': evolved.get('pause_recovery_boost', 0.0),
        'personality_baseline': base_info['baseline'],
        'regulation_strategy': emo_info['regulation_strategy'],
    }

    if commit and changed:
        commit_state(store, expected_rev, state, event_kind='expressive_drive_idle_advance', event_payload={
            'scope': scope,
            'person_id': person_id,
            'delta_seconds': round(dt, 3),
            'activation': evaluation['activation'],
            'urgency': evaluation['urgency'],
            'persistence': evaluation['persistence'],
            'expressive_intent': intent,
            'has_concrete_motive': has_concrete_motive,
            'proactive_eligible': proactive_eligible,
            'unfinished_count': len(evolved['active_unfinished']),
            'expired_motive_ids': evolved['expired_ids'],
        })
    return state, evaluation


def bind_proactive_send_plan(base_state, owner, scope, person, *, motive_id, turn_id, attempt_id=None, at=None):
    """Bind a selected expressive motive to a proactive send plan before transport (Round 4 Issue 1).

    Establishes the immutable identity chain: turn_id -> attempt_id -> motive_id.
    """
    if base_state is None or not motive_id:
        return base_state
    state = copy.deepcopy(base_state)
    skey = stream_key(owner, scope, person)
    row = state.get('streams', {}).get(skey)
    if not row:
        return state
    motive = (row.get('motives') or {}).get(motive_id)
    if not isinstance(motive, dict):
        return state
    ts = seconds(at if at is not None else now())
    motive['bound_proactive_plan'] = {
        'turn_id': str(turn_id),
        'attempt_id': str(attempt_id or turn_id),
        'motive_id': str(motive_id),
        'scope': str(scope),
        'person_id': str(person),
        'at': ts,
    }
    return state


def prepare_proactive_outcome_draft(base_drive, base_affect, affect_model, profile, scope, person, outcome, *,
                                    at=None, reason='', turn_id=None, attempt_id=None,
                                    target_motive_id=None, motive_id_explicit=False,
                                    delivery_receipt=None, persisted_message_id=None,
                                    source_message_ids=(), delivered_parts=1, planned_parts=1,
                                    unsent_parts=None, relation=None):
    """Pure, transaction-free draft calculation for proactive social outcomes (Round 3 Issue 3 & Round 4 Issue 1).

    Performs ZERO database writes. Strictly binds to the plan's target_motive_id (never silently
    falling back to active_motive_id on commit), validates motive ownership/scope/person/plan/receipt
    identity, and guarantees idempotent settlement across duplicate ACKs or recovery.
    """
    owner = profile['id']
    state = copy.deepcopy(base_drive) if base_drive is not None else empty_state(owner)
    validate(state, owner)
    ts = seconds(at if at is not None else now())
    eff_turn_id = str(turn_id or attempt_id or '').strip() or None
    eff_attempt_id = str(attempt_id or turn_id or '').strip() or None

    # Validate delivery_receipt identity binding if provided (Round 4 Issue 1.3)
    if isinstance(delivery_receipt, dict) and delivery_receipt:
        r_tid = str(delivery_receipt.get('turn_id') or '').strip()
        r_aid = str(delivery_receipt.get('attempt_id') or '').strip()
        r_mid = str(delivery_receipt.get('motive_id') or '').strip()
        if r_tid and eff_turn_id and r_tid != eff_turn_id:
            raise ValueError(f'主动联系 ACK 回执 turn_id ({r_tid}) 与发送计划 ({eff_turn_id}) 不匹配')
        if r_aid and eff_attempt_id and r_aid != eff_attempt_id:
            raise ValueError(f'主动联系 ACK 回执 attempt_id ({r_aid}) 与发送计划 ({eff_attempt_id}) 不匹配')
        if r_mid and target_motive_id is not None and r_mid != str(target_motive_id):
            raise ValueError(f'主动联系 ACK 回执 motive_id ({r_mid}) 与发送计划 ({target_motive_id}) 不匹配')

    skey = stream_key(owner, scope, person)
    row = state['streams'].setdefault(
        skey,
        initial_stream(owner, scope, person, scope, ts, state['model'], profile)
    )
    outcomes_ledger = row.setdefault('proactive_outcomes', {})
    dedupe_key = f"{eff_turn_id}:{outcome}" if eff_turn_id else None
    if dedupe_key and dedupe_key in outcomes_ledger:
        prev = outcomes_ledger[dedupe_key]
        if target_motive_id is not None and prev.get('motive_id') is not None and str(prev.get('motive_id')) != str(target_motive_id):
            raise ValueError(f'主动联系重放计划的 motive_id ({target_motive_id}) 与已提交记录 ({prev.get("motive_id")}) 冲突')
        return {
            'already_applied': True,
            'drive_draft': state,
            'affect_draft': copy.deepcopy(base_affect) if base_affect is not None else None,
            'motive': copy.deepcopy(prev.get('motive')),
            'affect_feedback': copy.deepcopy(prev.get('affect_feedback')),
        }

    # Resolve target motive without ever overwriting an explicit plan motive_id with active_motive_id (Round 4 Issue 1.2 & 1.5)
    if target_motive_id is not None:
        mid = str(target_motive_id).strip()
        motive = row['motives'].get(mid)
        if motive is None:
            for other_skey, other_row in state.get('streams', {}).items():
                if other_skey != skey and isinstance(other_row, dict) and mid in (other_row.get('motives') or {}):
                    other_id = other_row.get('identity') or {}
                    raise ValueError(
                        f'主动联系表达动机 {mid} 的 scope/person_id ({other_id.get("scope")}/{other_id.get("person_id")}) 与发送计划 ({scope}/{person}) 不一致'
                    )
            raise ValueError(f'主动联系指定的表达动机 {mid} 不存在，保留回执待核对')
        if motive.get('subject_id') and motive['subject_id'] != owner:
            raise ValueError(f'主动联系表达动机 {mid} 不属于当前人格主体 ({owner})')
        t_info = motive.get('target') or {}
        m_scope = motive.get('scope') or t_info.get('scope') or row['identity'].get('scope')
        m_person = str(motive.get('person_id') or t_info.get('person_id') or row['identity'].get('person_id'))
        if m_scope != scope or m_person != str(person):
            raise ValueError(f'主动联系表达动机 {mid} 的 scope/person_id ({m_scope}/{m_person}) 与发送计划 ({scope}/{person}) 不一致')
        bound_plan = motive.get('bound_proactive_plan')
        if isinstance(bound_plan, dict):
            if bound_plan.get('turn_id') and eff_turn_id and str(bound_plan['turn_id']) != eff_turn_id:
                raise ValueError(f'主动联系表达动机 {mid} 已绑定至其他发送计划 ({bound_plan["turn_id"]})，与当前计划 ({eff_turn_id}) 不对应')
            if bound_plan.get('attempt_id') and eff_attempt_id and str(bound_plan['attempt_id']) != eff_attempt_id:
                raise ValueError(f'主动联系表达动机 {mid} 已绑定至其他发送尝试 ({bound_plan["attempt_id"]})，与当前尝试 ({eff_attempt_id}) 不对应')
            if bound_plan.get('scope') and bound_plan['scope'] != scope:
                raise ValueError(f'主动联系表达动机 {mid} 绑定的计划 scope 与当前提交不一致')
            if bound_plan.get('person_id') and str(bound_plan['person_id']) != str(person):
                raise ValueError(f'主动联系表达动机 {mid} 绑定的计划 person_id 与当前提交不一致')
        if outcome == 'sent' and motive.get('status') == 'abandoned':
            raise ValueError(f'主动联系表达动机 {mid} 已处于 abandoned 状态，不能作为有效计划完成')
        # Requirement 2.4: If motive A was already satisfied by another flow while in flight, treat as idempotent and do not re-settle emotion feedback
        if outcome == 'sent' and motive.get('status') == 'satisfied':
            if dedupe_key:
                outcomes_ledger[dedupe_key] = {
                    'outcome': outcome,
                    'at': ts,
                    'motive_id': mid,
                    'motive': copy.deepcopy(motive),
                    'affect_feedback': None,
                }
            return {
                'already_applied': True,
                'drive_draft': state,
                'affect_draft': copy.deepcopy(base_affect) if base_affect is not None else None,
                'motive': copy.deepcopy(motive),
                'affect_feedback': None,
            }
    elif motive_id_explicit or outcome == 'sent':
        # Requirement 2.5: Legacy proactive plan without motive_id must NOT guess or hijack active_motive_id
        mid = None
        motive = None
    else:
        mid = row.get('active_motive_id')
        motive = row['motives'].get(mid) if mid else None
        if motive is None:
            unfinished = [m for m in row['motives'].values() if m['status'] in ('pending', 'deferred', 'partially_satisfied')]
            if unfinished:
                unfinished.sort(key=lambda m: (m['activation'], m['updated_at']), reverse=True)
                motive = unfinished[0]
                mid = motive['motive_id']
                row['active_motive_id'] = mid

    fb_outcome = 'proactive_deferred'
    obstructed = False
    if outcome == 'sent':
        if mid is not None:
            state, motive = apply_delivery_outcome(
                state, scope, person, 'delivered_full',
                at=ts, reason=reason or 'proactive_social_sent',
                delivered_parts=delivered_parts, planned_parts=planned_parts,
                target_motive_id=mid, turn_id=eff_turn_id,
                source_message_ids=source_message_ids,
                persisted_assistant_ids=[persisted_message_id] if persisted_message_id else ([eff_turn_id + ':a:0'] if eff_turn_id else []),
            )
            row = state['streams'][skey]
        else:
            # Legacy proactive send without motive_id: record correlation fact without touching any motive in row['motives']
            state, _ = bind_turn_correlation(
                state, scope, person,
                source_message_ids=list(source_message_ids),
                turn_id=eff_turn_id,
                persisted_assistant_ids=[persisted_message_id] if persisted_message_id else ([eff_turn_id + ':a:0'] if eff_turn_id else []),
                motive_ids=[],
                delivery_outcome='delivered_full',
                at=ts,
            )
            row = state['streams'][skey]
            row['updated_at'] = max(row['updated_at'], ts)
            row['state_revision'] += 1
        fb_outcome = 'delivered_full'
    elif outcome == 'partial':
        if mid is not None:
            state, motive = apply_delivery_outcome(
                state, scope, person, 'delivered_partial',
                at=ts, reason=reason or 'proactive_social_partial_delivery',
                delivered_parts=delivered_parts, planned_parts=planned_parts,
                unsent_parts=unsent_parts, target_motive_id=mid, turn_id=eff_turn_id,
                source_message_ids=source_message_ids,
                persisted_assistant_ids=[persisted_message_id] if persisted_message_id else [],
            )
            row = state['streams'][skey]
        fb_outcome = 'delivered_partial'
    elif outcome in ('deferred', 'no_action'):
        if motive:
            defers = int(motive.get('proactive_defer_count', 0)) + 1
            motive['proactive_defer_count'] = defers
            if defers >= 3 or motive.get('persistence', 0.5) < 0.26:
                motive['status'] = 'abandoned'
                motive['delivery_outcome'] = 'abandoned'
                motive['defer_reason'] = reason or 'proactive_defer_limit_reached'
            else:
                motive['status'] = 'deferred'
                motive['delivery_outcome'] = 'proactive_deferred'
                motive['defer_reason'] = reason or 'proactive_opportunity_deferred_for_reevaluation'
                motive['urgency'] = round(clamp(motive['urgency'] * 0.84, 0.15, 1.0), 6)
            motive['updated_at'] = ts
            motive['state_revision'] += 1
            _sync_satisfied_source_records(row)
        row['expressive_intent'] = 'DEFER' if (motive and motive['status'] == 'deferred') else 'CLOSE'
        row['updated_at'] = max(row['updated_at'], ts)
        row['state_revision'] += 1
        fb_outcome = 'proactive_deferred'
    elif outcome == 'failed':
        if motive:
            motive['status'] = 'deferred'
            motive['delivery_outcome'] = 'obstructed_expression'
            motive['defer_reason'] = reason or 'proactive_send_or_inspection_failed_retained'
            motive['updated_at'] = ts
            motive['state_revision'] += 1
            _sync_satisfied_source_records(row)
        row['expressive_intent'] = 'DEFER'
        row['updated_at'] = max(row['updated_at'], ts)
        row['state_revision'] += 1
        fb_outcome = 'obstructed_expression'
        obstructed = True

    state['revision'] += 1

    ev_id_for_fb = f"proactive:{eff_turn_id or (mid or scope)}:{mid or 'nomotive'}:{outcome}"
    drive_snap = {
        'event_id': ev_id_for_fb,
        'activation': motive['activation'] if motive else row['activation'],
        'urgency': motive['urgency'] if motive else row['urgency'],
        'persistence': motive['persistence'] if motive else row['persistence'],
        'expressive_intent': row['expressive_intent'],
    }
    ed_fb = feedback_to_emotion_appraisal(
        drive_snap, fb_outcome, relation=relation,
        feedback_id=f"efb:{ev_id_for_fb}", obstructed=obstructed
    )
    affect_draft = copy.deepcopy(base_affect) if base_affect is not None else None
    ar_res = None
    if affect_draft is not None and affect_model is not None and ed_fb.get('applied') and (motive is not None or not motive_id_explicit or outcome != 'sent'):
        from . import affect_runtime as ar
        quote_text = (motive or {}).get('content_anchor', {}).get('quote') or 'proactive_social_evaluation'
        affect_draft, ar_res = ar.apply_expression_feedback(
            affect_draft, affect_model, profile,
            {'id': ev_id_for_fb, 'text': quote_text, 'scope': scope, 'person': person, 'session_id': row['identity'].get('session_id', scope)},
            ts, ed_fb, relation=relation, standalone=True
        )

    if dedupe_key:
        outcomes_ledger = row.setdefault('proactive_outcomes', {})
        outcomes_ledger[dedupe_key] = {
            'outcome': outcome,
            'at': ts,
            'motive_id': mid,
            'motive': copy.deepcopy(motive),
            'affect_feedback': copy.deepcopy(ar_res),
        }
        if len(outcomes_ledger) > 60:
            for old_k in list(outcomes_ledger)[:-60]:
                outcomes_ledger.pop(old_k, None)

    validate(state, owner)
    return {
        'already_applied': False,
        'drive_draft': state,
        'affect_draft': affect_draft,
        'motive': copy.deepcopy(motive),
        'affect_feedback': ar_res,
    }


def apply_proactive_outcome(store, profile, scope, person, outcome, *, at=None, reason='', turn_id=None,
                            attempt_id=None, target_motive_id=None, motive_id_explicit=False,
                            delivery_receipt=None, persisted_message_id=None, source_message_ids=(), relation=None):
    """Calculate and atomically persist proactive outcome in a single store transaction."""
    from . import affect_runtime as ar
    with store.lock, store.db:
        base_drive = store.meta(KEY)
        if base_drive is None:
            base_drive = migrate(store)
        base_affect = store.meta(ar.KEY)
        affect_model = ar.model_for(store) if base_affect is not None else None
        prepared = prepare_proactive_outcome_draft(
            base_drive, base_affect, affect_model, profile, scope, person, outcome,
            at=at, reason=reason, turn_id=turn_id, attempt_id=attempt_id,
            target_motive_id=target_motive_id, motive_id_explicit=motive_id_explicit,
            delivery_receipt=delivery_receipt, persisted_message_id=persisted_message_id,
            source_message_ids=source_message_ids, relation=relation
        )
        if not prepared['already_applied']:
            validate(prepared['drive_draft'], profile['id'])
            store.setmeta(KEY, prepared['drive_draft'])
            if prepared['affect_draft'] is not None and prepared['affect_feedback'] and prepared['affect_feedback'].get('updated'):
                ar.validate(prepared['affect_draft'], profile['id'])
                store.setmeta(ar.KEY, prepared['affect_draft'])
        return prepared['drive_draft'], prepared['motive'], prepared['affect_feedback']


def read_current(store, profile, scope='private:web:owner', person='web:owner', session_id=None, at=None):
    """Pure read of ExpressiveDrive state without advancing time, sampling, or writing."""
    owner = profile['id']
    base = store.meta(KEY)
    if base is None:
        base = empty_state(owner)
    base_info = personality_baseline(profile, base['model'])
    skey = stream_key(owner, scope, person)
    row = base['streams'].get(skey)
    if row is None:
        row = initial_stream(owner, scope, person, session_id or scope, at if at is not None else now(), base['model'], profile)
    active_motives = [
        copy.deepcopy(m) for m in row['motives'].values()
        if m['status'] in ('pending', 'deferred', 'partially_satisfied')
    ]
    active_motives.sort(key=lambda m: (m['activation'], m['updated_at']), reverse=True)
    top_candidate = row['motives'].get(row.get('active_motive_id')) if row.get('active_motive_id') else None
    if isinstance(top_candidate, dict) and top_candidate.get('status') in ('pending', 'deferred', 'partially_satisfied'):
        top = copy.deepcopy(top_candidate)
    else:
        top = active_motives[0] if active_motives else copy.deepcopy(top_candidate)
    return {
        'schema': SCHEMA,
        'subject_id': owner,
        'scope': scope,
        'person_id': str(person or scope),
        'activation': row['activation'],
        'urgency': row['urgency'],
        'persistence': row['persistence'],
        'expressive_intent': row['expressive_intent'],
        'baseline': copy.deepcopy(row['baseline']),
        'updated_at': row['updated_at'],
        'state_revision': row['state_revision'],
        'active_motive_id': top['motive_id'] if isinstance(top, dict) and top.get('status') in ('pending', 'deferred', 'partially_satisfied') else row.get('active_motive_id'),
        'active_motive': top,
        'intended_expression': copy.deepcopy(top.get('intended_expression')) if isinstance(top, dict) else None,
        'unfinished_motives': active_motives,
        'event_correlations': copy.deepcopy(row.get('event_correlations', {})),
        'recorded_contributions': copy.deepcopy((row.get('events',{}).get(row.get('last_event_id')) or {}).get('result',{})),
        'total_motives': len(row['motives']),
        'known_construct_count': base_info['known_construct_count'],
    }


def commit_state(store, expected_revision, draft_state, *, event_kind=None, event_payload=None):
    owner = store.meta('identity')['id']
    validate(draft_state, owner)
    with store.lock, store.db:
        current = store.meta(KEY)
        if current is None:
            current = migrate(store)
        if expected_revision is not None and current['revision'] != expected_revision:
            raise ValueError('表达欲状态版本冲突，拒绝覆盖最新状态')
        store.setmeta(KEY, draft_state)
        if event_kind:
            store.event(event_kind, event_payload or {'revision': draft_state['revision'], 'subject_id': owner})


def status_summary(store, profile):
    """Compact diagnostic summary for Runtime.state() and PMM workspace."""
    owner = profile['id']
    base = store.meta(KEY)
    if base is None:
        base = empty_state(owner)
    streams = []
    for skey, row in base.get('streams', {}).items():
        unfinished = [
            {
                'motive_id': m['motive_id'],
                'source_event_ids': copy.deepcopy(m.get('source_event_ids', [])),
                'topic': m['content_anchor'].get('topic'),
                'intended_goal': (m.get('intended_expression') or {}).get('intended_goal') or m['content_anchor'].get('summary'),
                'candidate_point_or_question': (m.get('intended_expression') or {}).get('candidate_point_or_question'),
                'stage': (m.get('intended_expression') or {}).get('stage'),
                'unsent_plan_steps': copy.deepcopy((m.get('intended_expression') or {}).get('unsent_plan_steps', [])),
                'status': m['status'],
                'delivery_outcome': m.get('delivery_outcome'),
                'defer_reason': m.get('defer_reason', ''),
                'proactive_defer_count': m.get('proactive_defer_count', 0),
                'activation': m['activation'],
                'urgency': m['urgency'],
                'persistence': m['persistence'],
                'updated_at': m['updated_at'],
            }
            for m in row.get('motives', {}).values()
            if m.get('status') in ('pending', 'deferred', 'partially_satisfied')
        ]
        streams.append({
            'stream_key': skey,
            **copy.deepcopy(row['identity']),
            'activation': row['activation'],
            'urgency': row['urgency'],
            'persistence': row['persistence'],
            'expressive_intent': row['expressive_intent'],
            'baseline': copy.deepcopy(row.get('baseline', {})),
            'updated_at': row['updated_at'],
            'state_revision': row['state_revision'],
            'unfinished_motives': unfinished,
            'recorded_contributions': {k:copy.deepcopy(v) for k,v in ((row.get('events',{}).get(row.get('last_event_id')) or {}).get('result',{})).items() if k in ('event_id','at','channel_contributions','inputs_summary','turn_taking_influence','policy_score_terms','model_version','calibration_status')},
            'correlation_count': len(row.get('event_correlations', {})),
            'total_motives': len(row.get('motives', {})),
        })
    return {
        'schema': SCHEMA,
        'subject_id': owner,
        'revision': base['revision'],
        'model_version': base['model']['sha256'],
        'calibration_status': base['model']['calibration']['status'],
        'streams': streams,
        'recent_history': copy.deepcopy(base.get('history', [])[-20:]),
    }
