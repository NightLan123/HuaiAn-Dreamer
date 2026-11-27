/**
 * 槐安梦客 Phase 2.2 — ModelAdapter
 * 负责从原版后端 /api/state, /api/pmm281/status, /api/pmm28/status, /api/pmm28/traces, /api/cognition
 * 解析外部 General LLM、内部 API-PMM 与内部 Learned-PMM 的独立状态、参数、同轮协作与仲裁记录。
 * - 若 /api/pmm281/status 或 /api/pmm28/status 返回 404/500/超时，严格返回 error/unavailable 信封（修复 P1-4）。
 * - 严禁将 General LLM 归入 PMM 内部组件；严禁将未验证的配置标为在线（修复 P0-1）。
 */
(function (global) {
  class ModelAdapter {
    constructor() {
      this.adapterName = 'ModelAdapter';
    }

    parseDecisionRecords(rawMap) {
      const E = global.DataEnvelopeFactory;
      const stateEnv = rawMap['/api/state'];
      const p281Env = rawMap['/api/pmm281/status'];
      const p28Env = rawMap['/api/pmm28/status'];
      const tracesEnv = rawMap['/api/pmm28/traces'];
      const cogEnv = rawMap['/api/cognition'];

      if (!stateEnv || stateEnv.status !== 'success' || !stateEnv.data) {
        return E.error('/api/state', stateEnv?.error || '无法读取后端状态', stateEnv?.error_code || 'STATE_ERROR');
      }
      // P1-4: Do NOT mask /api/pmm281/status or /api/pmm28/status errors as LIVE
      for (const [ep, env] of [['/api/pmm281/status', p281Env], ['/api/pmm28/status', p28Env], ['/api/pmm28/traces', tracesEnv]]) {
        if (env && env.status === 'error') {
          return E.error(ep, env.error || `${ep} 请求失败`, env.error_code || 'PMM_ENDPOINT_ERROR', env.http_status);
        }
        if (env && env.status === 'unavailable') {
          return E.unavailable(ep, env.error || `${ep} 接口不可用`);
        }
      }

      const st = stateEnv.data;
      const p281 = (p281Env && p281Env.data) || {};
      const p28 = (p28Env && p28Env.data) || {};
      const tracesList = (tracesEnv && tracesEnv.data && Array.isArray(tracesEnv.data.traces))
        ? tracesEnv.data.traces
        : (Array.isArray(p281.traces) ? p281.traces : []);
      const cog = (cogEnv && cogEnv.data) || st.cognition || {};

      const cfg = st.config || {};
      const modelInfo = st.model || {};
      const connA = (p281.connections && p281.connections.A) || {};
      const connB = (p281.connections && p281.connections.B) || {};

      const latestTrace = tracesList.length > 0 ? tracesList[0] : null;
      const comps = (latestTrace && latestTrace.components) || {};
      const rNode = comps.reasoner || null;
      const nNode = comps.neural || null;
      const dNode = comps.decision || null;
      const edNode = comps.expressive_drive || null;

      const rPay = (rNode && rNode.payload) || {};
      const nPay = (nNode && nNode.payload) || {};
      const dPay = (dNode && dNode.payload) || {};
      const edPay = (edNode && edNode.payload) || {};

      const tSnap = st.trait_snapshot || {};
      const allSnapEntries = [
        ...Object.values(tSnap.hexaco_facets || {}),
        ...Object.values(tSnap.value_priorities || {}),
        ...Object.values(tSnap.interpersonal_dispositions || {}),
        ...Object.values(tSnap.behavioral_dispositions || {}),
        ...Object.values(tSnap.affective_disposition || {})
      ];
      const knownConstructsCount = allSnapEntries.filter(
        c => c && c.estimate !== null && c.estimate !== undefined
      ).length;
      const totalConstructsCount = allSnapEntries.length || 68;

      const adoptedA = rNode?.status === 'ok' && rNode.executed === true;
      const apiProbs = adoptedA && Object.keys(rPay.action_probabilities || {}).length ? rPay.action_probabilities : null;
      const neuralProbs = nPay.action_probabilities || null;

      const apiPref = (adoptedA && dPay.api_preference) || (apiProbs ? Object.keys(apiProbs).reduce((a, b) => apiProbs[a] >= apiProbs[b] ? a : b) : null);
      const neuralPref = dPay.neural_preference || (neuralProbs ? Object.keys(neuralProbs).reduce((a, b) => neuralProbs[a] >= neuralProbs[b] ? a : b) : null);

      const appraisalObj = rPay.appraisal || {};
      const appraisalText = rPay.evaluation_use ? (global.DisplayText?.state(rPay.evaluation_use.source) || '评价来源未记录') : rNode && adoptedA
        ? `Valence ${appraisalObj.valence != null ? Number(appraisalObj.valence).toFixed(3) : 'null'} | Arousal ${appraisalObj.arousal != null ? Number(appraisalObj.arousal).toFixed(3) : 'null'} | Stress ${appraisalObj.stress != null ? Number(appraisalObj.stress).toFixed(3) : 'null'} | Engagement ${appraisalObj.engagement != null ? Number(appraisalObj.engagement).toFixed(3) : 'null'}`
        : '本轮没有可归于 A 的在线评价';

      const checkpointSha = nPay.checkpoint_sha256 || p28.legacy_checkpoint_sha256 || modelInfo.checkpoint_sha256 || 'initial_seed';
      const receipt = (latestTrace && latestTrace.commit_receipt) || null;

      const hasGenModel = Boolean(cfg.model && String(cfg.model).trim());
      const genState = hasGenModel ? (cfg.last_general_test_ok ? 'healthy' : 'configured') : 'unavailable';

      const record = {
        general_llm: {
          model: hasGenModel ? String(cfg.model) : '未配置 (model="")',
          provider: cfg.provider || 'ollama',
          base_url: cfg.base_url || '',
          state: genState,
          role: '外部语言理解与语言输出组件（Strictly External — 绝不归入 PMM 内部组件）',
          status: hasGenModel ? `已配置 / 未验证连通 (${cfg.model})` : '未配置模型 (unavailable)'
        },
        api_pmm: {
          component_id: 'API-PMM',
          version: (rNode && rNode.version) || 'event-reasoner-A/2.8.1',
          status: rNode ? rNode.status : (connA.status || 'unconfigured'),
          connection_state: (connA.status === 'tested' || connA.status === 'last_call_succeeded')
            ? 'healthy'
            : (['last_call_failed','failed','connection_failed'].includes(connA.status) || !connA.configured ? 'unavailable' : 'configured'),
          participated: adoptedA,
          attempted: rNode?.executed ?? null,
          evaluation_use: rPay.evaluation_use || null,
          execution_mode: (rNode && rNode.execution) || 'standby_no_turn_yet',
          elapsed_ms: (rNode && rNode.elapsed_ms != null) ? rNode.elapsed_ms : null,
          provider_model: connA.model || (cfg.pmm && cfg.pmm.api && cfg.pmm.api.model) || '未配置 (unconfigured)',
          preferred_action: apiPref,
          probs: apiProbs,
          quote: rPay.evidence_quote || null,
          appraisal_summary: appraisalText,
          history_count: tracesList.filter(t => t.components && t.components.reasoner && t.components.reasoner.executed).length,
          recent_updates: tracesList.slice(0, 8).map(t => ({
            turn_id: t.turn_id,
            at: global.formatBusinessTimestamp(t.timestamp),
            status: t.components?.reasoner?.status || 'none',
            execution: t.components?.reasoner?.execution || 'none',
            elapsed_ms: t.components?.reasoner?.elapsed_ms ?? null
          }))
        },
        learned_pmm: {
          component_id: 'Learned-PMM',
          version: (nNode && nNode.version) || modelInfo.architecture || 'learned-pmm-v2',
          status: nPay.calibration || p28.calibration || 'uncalibrated',
          connection_state: ((nPay.calibration || p28.calibration) === 'calibrated' && p28.long_term_commit_ready) ? 'healthy' : 'configured',
          participated: Boolean(nNode && nNode.executed),
          execution_mode: (nNode && nNode.execution) || 'standby',
          elapsed_ms: (nNode && nNode.elapsed_ms != null) ? nNode.elapsed_ms : null,
          steps: modelInfo.steps != null ? modelInfo.steps : (cog.numeric_steps || 0),
          train_samples: (p28.samples && p28.samples.count) || modelInfo.train_samples || 0,
          rank: 8,
          latent_dim: (nPay.latent && nPay.latent.length) || 16,
          known_constructs: dPay.known_constructs !== undefined ? dPay.known_constructs : knownConstructsCount,
          total_constructs: totalConstructsCount,
          checkpoint: String(checkpointSha).slice(0, 16) + '…',
          checkpoint_full: String(checkpointSha),
          formal_eligible: Boolean(nPay.formal_eligible),
          release_gate: nPay.release_gate || p28.release_gate || 'no_published_validated_network',
          preferred_action: neuralPref,
          probs: neuralProbs,
          state_pred: Array.isArray(nPay.state_prediction)
            ? `状态转移预测向量 (${nPay.state_prediction.length}维): [${nPay.state_prediction.slice(0, 4).map(v => Number(v).toFixed(3)).join(', ')}...]`
            : '尚未执行前向状态预测',
          model_versions: (p28.models && p28.models.versions) || []
        },
        fusion: {
          has_trace: Boolean(latestTrace),
          turn_id: latestTrace ? latestTrace.turn_id : '暂无真实回合记录',
          event_id: latestTrace ? latestTrace.event_id : null,
          event_text: latestTrace ? latestTrace.text : null,
          disagreement: Boolean(dPay.disagreement),
          rule: dPay.rule || 'check_source_then_calibration_then_conflict; never_average_predictions',
          arbitration: dPay.arbitration || (latestTrace ? 'completed' : 'awaiting_first_turn'),
          final_action: dPay.official_action || (latestTrace ? (apiPref || 'reply') : '无 (等待首轮对话)'),
          drive_contrib: edPay && edPay.activation != null
            ? `Activation ${(Number(edPay.activation) * 100).toFixed(1)}% / Urgency ${(Number(edPay.urgency || 0) * 100).toFixed(1)}% / Persistence ${(Number(edPay.persistence || 0) * 100).toFixed(1)}% → ${edPay.expressive_intent || 'LISTEN'}`
            : '无活跃流叠加项',
          receipt_summary: receipt
            ? `${receipt.kind} · profile_rev=${receipt.profile_revision} · trait_v=${receipt.trait_version} · affect_rev=${receipt.affect_revision} · drive_rev=${receipt.expressive_drive_revision}`
            : `当前数据库版本: profile_rev=${st.profile?.revision ?? 0} · trait_v=${st.profile?.trait_profile?.version ?? 0}`,
          verified: Boolean(receipt)
        },
        traces_count: tracesList.length,
        traces: tracesList,
        // Exact endpoint observations for Stage 4; the visualizer must not use
        // legacy display defaults as execution, calibration or delivery facts.
        observability: { api_status: p281, learned_status: p28,
          api_envelope: p281Env, learned_envelope: p28Env, traces_envelope: tracesEnv }
      };

      // P2-9: updated_at is strictly the latest trace timestamp (or null if no trace exists yet!)
      const businessUpdatedAt = latestTrace ? latestTrace.timestamp : null;
      const statusOverride = tracesList.length === 0 ? 'empty' : 'success';

      return E.live(
        record,
        '/api/pmm281/status + /api/pmm28/status + /api/pmm28/traces',
        businessUpdatedAt,
        {
          general_llm: 'live',
          api_pmm: 'live',
          learned_pmm: 'live',
          fusion: 'live',
          traces: tracesEnv?.status === 'success' ? 'live' : 'unavailable'
        },
        {},
        statusOverride
      );
    }
  }

  global.ModelAdapter = ModelAdapter;
})(typeof window !== 'undefined' ? window : globalThis);
