/**
 * 槐安梦客 Phase 2.3 — ConnectionAdapter (P0-1 & P1-04 严格六态连接与真实探测记录)
 * 严格区分 6 种状态：healthy / reachable / running / configured / unknown / unavailable
 * - 修复 P1-04：background_jobs.healthy 不再固定为 true（无独立健康探针时保持 null，仅标记 reachable 或 running）。
 * - 支持记录真实主动探测结果 (/api/test-model, /api/pmm/test, /api/qq/test)。
 */
(function (global) {
  class ConnectionAdapter {
    constructor() {
      this.adapterName = 'ConnectionAdapter';
      this.probeCache = {
        general: null,
        pmm: null,
        qq: null
      };
    }

    recordProbeResult(role, ok, detailText) {
      if (ok === null || ok === undefined) {
        this.probeCache[role] = null;
        return;
      }
      this.probeCache[role] = {
        ok: Boolean(ok),
        detail: detailText || '',
        at: global.nowFetchedAt ? global.nowFetchedAt() : new Date().toISOString()
      };
    }

    parseConnectionStatus(rawMap) {
      const E = global.DataEnvelopeFactory;
      const stateEnv = rawMap['/api/state'];
      if (!stateEnv || stateEnv.status !== 'success' || !stateEnv.data) {
        return E.error(
          '/api/state',
          stateEnv?.error || '连接状态暂未读取',
          stateEnv?.error_code || 'STATUS_UNAVAILABLE',
          stateEnv?.http_status || 0
        );
      }

      const st = stateEnv.data;
      const p281Env = rawMap['/api/pmm281/status'];
      const p28Env = rawMap['/api/pmm28/status'];
      const qqEnv = rawMap['/api/qq/status'];
      const learnEnv = rawMap['/api/learning'];
      const memEnv = rawMap['/api/memories'];

      const p281 = (p281Env && p281Env.status === 'success' && p281Env.data) ? p281Env.data : null;
      const p28 = (p28Env && p28Env.status === 'success' && p28Env.data) ? p28Env.data : null;
      const qq = (qqEnv && qqEnv.status === 'success' && qqEnv.data) ? qqEnv.data : null;
      const learn = (learnEnv && learnEnv.status === 'success' && learnEnv.data) ? learnEnv.data : null;

      const cfg = st.config || {};
      const modelInfo = st.model || {};
      const memLife = st.memory_lifecycle || {};
      const activeJobs = Array.isArray(st.active_jobs) ? st.active_jobs : [];

      // 1. General LLM (External Language Layer)
      const hasModelName = Boolean(cfg.model && String(cfg.model).trim());
      const genProbe = this.probeCache.general;
      let genStatus = 'unavailable';
      let genStatusText = '未配置模型 (unavailable)';
      let genHealthy = false;
      if (hasModelName) {
        if (genProbe && genProbe.ok === true) {
          genStatus = 'healthy';
          genStatusText = `在线已验证 (${cfg.model})`;
          genHealthy = true;
        } else if (genProbe && genProbe.ok === false) {
          genStatus = 'unavailable';
          genStatusText = `探测失败 (${cfg.model})`;
          genHealthy = false;
        } else {
          genStatus = 'configured';
          genStatusText = `已配置 / 未验证 (${cfg.model})`;
          genHealthy = null;
        }
      }

      // 2. API-PMM (Component A · Event Reasoner)
      const connA = (p281 && p281.connections && p281.connections.A) || null;
      let apiStatus = 'unknown';
      let apiStatusText = '状态未知 (/api/pmm281/status 未返回)';
      let apiHealthy = null;
      if (connA) {
        const rawAStatus = connA.status || 'unconfigured';
        if (rawAStatus === 'last_call_succeeded' || rawAStatus === 'tested') {
          apiStatus = 'healthy';
          apiStatusText = `最近一次任务调用成功 · ${connA.model || connA.provider}`;
          apiHealthy = true;
        } else if (rawAStatus === 'saved_not_tested' || rawAStatus === 'connected_only') {
          apiStatus = 'configured';
          apiStatusText = rawAStatus === 'connected_only' ? '服务已连通，实际任务待确认' : `已配置，等待任务调用 · ${connA.model}`;
          apiHealthy = null;
        } else if (['last_call_failed', 'failed', 'connection_failed'].includes(rawAStatus)) {
          apiStatus = 'unavailable';
          apiStatusText = rawAStatus === 'connection_failed' ? '服务连接失败' : '最近一次任务调用失败';
          apiHealthy = false;
        } else {
          apiStatus = 'unavailable';
          apiStatusText = `未配置模型 (unconfigured · ${connA.provider || 'ollama'})`;
          apiHealthy = false;
        }
      }

      // 3. Learned-PMM (Component B · Neural Dynamics)
      let lrnStatus = 'unknown';
      let lrnStatusText = '状态未知 (/api/pmm28/status 未返回)';
      let lrnHealthy = null;
      if (st.pmm_start_error) {
        lrnStatus = 'unavailable';
        lrnStatusText = `服务启动失败 (${st.pmm_start_error})`;
        lrnHealthy = false;
      } else if (p28 || p281) {
        const cal = (p28 && p28.calibration) || (p281 && p281.neural_training && p281.neural_training.calibration) || 'uncalibrated';
        const gate = (p28 && p28.release_gate) || (p281 && p281.neural_training && p281.neural_training.release_gate) || 'no_published_validated_network';
        const commitReady = Boolean((p28 && p28.long_term_commit_ready) || (p281 && p281.neural_training && p281.neural_training.long_term_commit_ready));
        if (cal === 'calibrated' && commitReady) {
          lrnStatus = 'healthy';
          lrnStatusText = `已校准就绪 (${cal})`;
          lrnHealthy = true;
        } else {
          lrnStatus = 'configured';
          lrnStatusText = `权重已加载 / 未校准 (${cal} · 门禁: ${gate})`;
          lrnHealthy = null;
        }
      }

      // 4. QQ / OneBot Channel
      const qqProbe = this.probeCache.qq;
      let qqStatus = 'unknown';
      let qqStatusText = '状态未知 (/api/qq/status 不可用)';
      let qqHealthy = null;
      if (qq) {
        if (!qq.enabled) {
          qqStatus = 'unavailable';
          qqStatusText = '未启用 (本地安全默认)';
          qqHealthy = null;
        } else if (qq.busy) {
          qqStatus = 'running';
          qqStatusText = '运行中 (正在处理消息)';
          qqHealthy = true;
        } else if ((qq.last_receipt && qq.last_receipt.ok) || (qqProbe && qqProbe.ok === true)) {
          qqStatus = 'healthy';
          qqStatusText = '已启用 · 探测或回执正常';
          qqHealthy = true;
        } else if (qqProbe && qqProbe.ok === false) {
          qqStatus = 'unavailable';
          qqStatusText = '已启用但探测失败';
          qqHealthy = false;
        } else {
          qqStatus = 'configured';
          qqStatusText = '已启用配置 / 尚无回执验证';
          qqHealthy = null;
        }
      }

      // 5. Learning & Distillation Service
      let learnStatus = 'unknown';
      let learnStatusText = '状态未知 (/api/learning 不可用)';
      let learnHealthy = null;
      if (learn) {
        if (learn.running) {
          learnStatus = 'running';
          learnStatusText = `任务运行中 (共 ${learn.total_jobs ?? 0} 项任务)`;
          learnHealthy = null;
        } else if (learn.last_failure) {
          learnStatus = 'configured';
          learnStatusText = `本地队列可达 (存在失败任务 · 共 ${learn.total_jobs ?? 0} 项)`;
          learnHealthy = false;
        } else {
          learnStatus = 'reachable';
          learnStatusText = `本地队列可达 (空闲 · 共 ${learn.total_jobs ?? 0} 项任务)`;
          learnHealthy = null;
        }
      } else if (learnEnv && learnEnv.status === 'error') {
        learnStatus = 'unavailable';
        learnStatusText = `接口异常 (${learnEnv.error_code || 'ERROR'})`;
        learnHealthy = false;
      }

      // 6. Memory Lifecycle Service
      let memStatus = 'unknown';
      let memStatusText = '状态未知 (/api/memories 不可用)';
      let memHealthy = null;
      if (memEnv && memEnv.status === 'success') {
        if (memLife.running) {
          memStatus = 'running';
          memStatusText = `整理运行中 (共 ${st.memory_count ?? 0} 条记忆)`;
          memHealthy = null;
        } else if (memLife.failed > 0) {
          memStatus = 'configured';
          memStatusText = `SQLite 可达 (失败 ${memLife.failed} 次 · 共 ${st.memory_count ?? 0} 条记忆)`;
          memHealthy = false;
        } else {
          memStatus = 'reachable';
          memStatusText = `SQLite 存储可达 (${st.memory_count ?? 0} 条记忆 · ${memLife.calibrated ? '已校准' : '实验衰减曲线'})`;
          memHealthy = memLife.calibrated ? true : null;
        }
      } else if (memEnv && memEnv.status === 'error') {
        memStatus = 'unavailable';
        memStatusText = `记忆接口异常 (${memEnv.error_code || 'ERROR'})`;
        memHealthy = false;
      }

      // 7. Background Job Queue (P1-04: Never hardcode healthy: true!)
      const hasFailedJob = activeJobs.some(j => j && j.status === 'error');
      const bgStatus = hasFailedJob ? 'unavailable' : (activeJobs.length > 0 ? 'running' : 'reachable');
      const bgStatusText = activeJobs.length > 0 ? `${activeJobs.length} 个后台任务运行中` : '本地任务表可达 (0 活动任务)';
      const bgHealthy = hasFailedJob ? false : null; // No standalone daemon health check -> null when reachable/running

      const nodes = {
        general_llm: {
          id: 'general_llm',
          name: '外部对话模型 (General LLM)',
          category: 'external_llm',
          status: genStatus,
          status_text: genStatusText,
          detail: `Provider: ${cfg.provider || 'ollama'} · BaseURL: ${cfg.base_url || '默认'} · 非 PMM 内部组件`,
          healthy: genHealthy,
          endpoint_probe: '/api/state → config.model + /api/test-model'
        },
        api_pmm: {
          id: 'api_pmm',
          name: '组件 A · API-PMM 在线推理',
          category: 'pmm_component',
          status: apiStatus,
          status_text: apiStatusText,
          detail: `组件版本: event-reasoner-A/2.8.1 · 实测轨迹数: ${(p281 && Array.isArray(p281.traces)) ? p281.traces.length : 0}`,
          healthy: apiHealthy,
          endpoint_probe: '/api/pmm281/status → connections.A'
        },
        learned_pmm: {
          id: 'learned_pmm',
          name: '组件 B · Learned-PMM 神经动力学',
          category: 'pmm_component',
          status: lrnStatus,
          status_text: lrnStatusText,
          detail: `引擎: ${(p281 && p281.default_engine) || 'NumPy forward'} · 训练步数: ${modelInfo.steps ?? 0} · 样本数: ${p28?.samples?.count ?? 0}`,
          healthy: lrnHealthy,
          endpoint_probe: '/api/pmm28/status → calibration, release_gate'
        },
        qq_channel: {
          id: 'qq_channel',
          name: 'QQ / OneBot 通道',
          category: 'channel',
          status: qqStatus,
          status_text: qqStatusText,
          detail: `白名单用户: ${qq?.allowed_users_count ?? 0} · 群组: ${qq?.allowed_groups_count ?? 0}`,
          healthy: qqHealthy,
          endpoint_probe: '/api/qq/status'
        },
        learning_service: {
          id: 'learning_service',
          name: '学习与蒸馏服务',
          category: 'internal_service',
          status: learnStatus,
          status_text: learnStatusText,
          detail: `已处理原文游标: ${learn?.processed_sources ?? 0}`,
          healthy: learnHealthy,
          endpoint_probe: '/api/learning'
        },
        memory_service: {
          id: 'memory_service',
          name: '记忆生命周期服务',
          category: 'internal_service',
          status: memStatus,
          status_text: memStatusText,
          detail: `角色版本: rev ${st.profile?.revision ?? 0} / trait v${st.profile?.trait_profile?.version ?? 0}`,
          healthy: memHealthy,
          endpoint_probe: '/api/state + /api/memories'
        },
        background_jobs: {
          id: 'background_jobs',
          name: '后台任务队列',
          category: 'internal_service',
          status: bgStatus,
          status_text: bgStatusText,
          detail: `Build ID: ${String(st.build_id || '').slice(0, 12)}…`,
          healthy: bgHealthy,
          endpoint_probe: '/api/state → active_jobs'
        }
      };

      const allVerifiedHealthy = Boolean(
        nodes.general_llm.healthy === true &&
        nodes.api_pmm.healthy === true &&
        nodes.learned_pmm.healthy === true
      );
      const anyError = [p281Env, p28Env, qqEnv, learnEnv, memEnv].some(e => e && e.status === 'error');
      const overallBadge = anyError
        ? `部分状态接口异常 (${st.version})`
        : (allVerifiedHealthy
          ? `全部在线已验证 (${st.version})`
          : `后端可达 · 模型待验证/未校准 (${st.version})`);

      return E.live({
        overall_badge: overallBadge,
        overall_healthy: allVerifiedHealthy,
        version: st.version,
        build_id: st.build_id,
        uptime_seconds: st.uptime_seconds ?? null,
        active_jobs: activeJobs,
        nodes,
        probe_results: { ...this.probeCache },
        qq_observation: qq,
        user_summary_rows: [
          {
            id: 'general_llm',
            label: '外部语言模型 (General LLM)',
            value: nodes.general_llm.status_text,
            state: nodes.general_llm.status,
            healthy: nodes.general_llm.healthy
          },
          {
            id: 'api_pmm',
            label: '组件 A · API-PMM 在线推理',
            value: nodes.api_pmm.status_text,
            state: nodes.api_pmm.status,
            healthy: nodes.api_pmm.healthy
          },
          {
            id: 'learned_pmm',
            label: '组件 B · Learned-PMM 动力学',
            value: nodes.learned_pmm.status_text,
            state: nodes.learned_pmm.status,
            healthy: nodes.learned_pmm.healthy
          },
          {
            id: 'memory_learn',
            label: '本地记忆与学习队列',
            value: `${nodes.memory_service.status_text} · ${nodes.learning_service.status_text}`,
            state: (nodes.memory_service.status === 'reachable' && (nodes.learning_service.status === 'reachable' || nodes.learning_service.status === 'running')) ? 'reachable' : 'configured',
            healthy: nodes.memory_service.healthy
          }
        ]
      }, '/api/state + /api/pmm281/status + /api/pmm28/status + /api/qq/status + /api/learning', st.profile?.updated_at, {
        general_llm: 'live',
        api_pmm: p281 ? 'live' : 'unavailable',
        learned_pmm: p28 ? 'live' : 'unavailable',
        qq_channel: qq ? 'live' : 'unavailable',
        learning_service: learn ? 'live' : 'unavailable'
      }, {}, anyError ? 'degraded' : 'success');
    }
  }

  global.ConnectionAdapter = ConnectionAdapter;
})(typeof window !== 'undefined' ? window : globalThis);
