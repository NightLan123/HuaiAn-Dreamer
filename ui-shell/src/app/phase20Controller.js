/**
 * 槐安梦客 UI Shell Phase 2.3 — Real Backend-Driven Controller (phase20Controller.js)
 * 完整实现 Batch A (P0-01 ~ P0-04)、Batch B (P1-01 ~ P1-04) 与 Batch C (全部 24 个独立领域子页)：
 * 1. P0-01：会客室真实会话创建、消息发送、
 *          真实异步任务轮询 (GET /api/jobs/<job_id>)、按会话读取真实聊天记录 (GET /api/messages?session=<id>) 及跨会话隔离。
 * 2. P0-02：人格构念修改从后端注册表加载 68 项可编辑构念，携带真实 expected_version (trait_profile.version)、
 *          feature_id、source_type='owner_seed'（主人设定）及 PANAS 必需的 timeframe='generally'，支持两步确认与版本冲突拦截。
 * 3. P0-03：表达欲推进仅传后端支持的 {scope, person, session_id, at, commit} 并回显真实计算结果；“新增动机”显式标为 PLANNED/UNAVAILABLE。
 * 4. P0-04：LIVE 模式下所有写输入框默认 value=""（绝不预填演示文本）；学习任务强制经过 preview → 勾选授权 → create。
 * 5. P1-01：完整 HTML5 鼠标拖放 (dragstart/dragover/dragenter/dragleave/drop/dragend)，支持保存、取消回滚 (#btnCancelLayout)、恢复默认。
 * 6. P1-02：无损低频轮询刷新——轮询仅更新只读数据槽位 ([data-readonly-slot]) 与徽章，绝不重建正在输入的子页表单或销毁焦点/草稿。
 * 7. P2：全部 24 个子页均具备各自独立的领域组件、数据源与交互逻辑，杜绝共用三张泛用卡片。
 */
(function () {
  const esc = window.escapeHtml || function (s) {
    if (s === null || s === undefined) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
      .replace(/`/g, '&#96;');
  };

  const fmtLocal = window.formatLocalDisplayTime || function (ts) {
    return ts ? String(ts) : '—';
  };

  const pmmAdapter = new window.PMMAdapter('');
  const mockAdapter = new window.MockAdapter();

  let currentMode = 'user';          // 'user' | 'developer'
  let currentUserNav = 'observe';
  let currentDevNav = 'overview';
  let dataSourceMode = 'live';       // 'live' | 'mock'
  let personaViewMode = 'hexaco';    // 'hexaco' | 'blocks68'
  let emotionRangeMode = 'events';   // 'events' | '24h' | '7d'
  let emotionExpanded = false;
  let layoutEditActive = false;
  let layoutSnapshotBeforeEdit = null;
  let draggedCardId = null;
  let suppressClickUntil = 0;

  let lastHydrationError = null;
  let activeScope = 'private:web:owner';
  let memoryKindFilter = 'all';
  let memorySearchQuery = '';
  let logStatusFilter = 'all';

  // P0-01: Parlor Session & Async Job State (Isolated per persona & session)
  let parlorSessionId = '';
  let parlorSessionsByPersona = {};
  let parlorMessagesBySession = {};
  let parlorJobState = { active: false, job_id: null, status: null, phase: '', error: null };

  // P0-02: Construct Edit Confirmation State
  let pendingDispositionEdit = null;

  // P0-04: Learning Preview Confirmation State
  let pendingLearningPreview = null;
  let pendingTraitReview = null;

  // Phase 2.3.1 P0 & P1: Concurrency Generation Tokens, Role Switch Lock, Modal Key & Centralized Write Guard
  let hydrateSeq = 0;
  let latestAppliedHydrateSeq = 0;
  let contextEpoch = 0;
  let activeHydrateCount = 0;
  let personaSwitchInFlight = false;
  let currentOpenModalKey = null;
  let pendingHighRiskConfirm = null;
  const mockBlockedWriteLog = [];

  window.__HUAIAN_DATA_SOURCE_MODE__ = dataSourceMode;

  function clearPendingTransientConfirmations() {
    pendingDispositionEdit = null;
    pendingLearningPreview = null;
    pendingTraitReview = null;
    pendingHighRiskConfirm = null;
    const dBox = document.getElementById('dispositionConfirmBox');
    if (dBox) dBox.style.display = 'none';
    const lBox = document.getElementById('learningPreviewConfirmBox');
    if (lBox) lBox.style.display = 'none';
    const rBox = document.getElementById('versionRollbackConfirmBox');
    if (rBox) rBox.style.display = 'none';
    const jBox = document.getElementById('distillHighRiskConfirmBox');
    if (jBox) jBox.style.display = 'none';
  }

  function guardWrite(actionId, context = {}) {
    if (dataSourceMode === 'mock' || window.__HUAIAN_DATA_SOURCE_MODE__ === 'mock') {
      const msg = `【MOCK 演示模式】演示模式不修改真实数据，已拦截写操作 (${actionId}${context.endpoint ? ' → ' + context.endpoint : ''})。`;
      mockBlockedWriteLog.unshift({
        actionId,
        endpoint: context.endpoint || '',
        targetId: context.targetId || '',
        at: window.nowFetchedAt ? window.nowFetchedAt() : new Date().toISOString(),
        reason: msg
      });
      if (context.feedbackEl) {
        context.feedbackEl.style.color = '#8A5A14';
        context.feedbackEl.textContent = msg;
      }
      return { allowed: false, reason: msg };
    }
    if (personaSwitchInFlight && actionId !== 'persona_switch') {
      const msg = '正在切换角色并同步数据中，请等待当前角色切换完成后再执行此操作。';
      if (context.feedbackEl) {
        context.feedbackEl.style.color = '#8A5A14';
        context.feedbackEl.textContent = msg;
      }
      return { allowed: false, reason: msg };
    }
    return { allowed: true, reason: null };
  }

  let activeEnvelopes = mockAdapter.getAllMockEnvelopes();

  const domainFaults = {
    emotion: 'normal',
    emotion_trend: 'normal',
    personality: 'normal',
    expression_drive: 'normal',
    memories: 'normal',
    experiences: 'normal',
    learning: 'normal',
    social: 'normal',
    connections: 'normal',
    decisions: 'normal'
  };

  // ---------------------------------------------------------------------------
  // P1-02: Non-Destructive Low-Frequency Polling Scheduler
  // ---------------------------------------------------------------------------
  const pollingScheduler = {
    enabled: true,
    baseIntervalMs: 15000,
    timerId: null,
    isHydrating: false,
    consecutiveFailures: 0,
    lastTickAt: null,
    lastSuccessAt: null,
    tickCount: 0,

    getEffectiveIntervalMs() {
      if (!this.enabled || this.baseIntervalMs <= 0 || dataSourceMode === 'mock') return 0;
      if (this.consecutiveFailures === 0) return this.baseIntervalMs;
      const factor = Math.min(8, Math.pow(2, this.consecutiveFailures));
      return Math.min(120000, this.baseIntervalMs * factor);
    },

    getStatusSummary() {
      if (dataSourceMode === 'mock') return '已暂停 (当前为 MOCK 演示模式)';
      if (!this.enabled || this.baseIntervalMs <= 0) return '手动刷新模式 (定时轮询已关闭)';
      const eff = this.getEffectiveIntervalMs();
      const hiddenNote = (typeof document !== 'undefined' && document.hidden) ? ' · 页面隐藏节流中' : '';
      const backoffNote = this.consecutiveFailures > 0 ? ` · 错误退避×${Math.min(8, Math.pow(2, this.consecutiveFailures))} (失败${this.consecutiveFailures}次)` : '';
      return `低频轮询已开启 (间隔 ${Math.round(eff / 1000)}s · 已轮询 ${this.tickCount} 次${hiddenNote}${backoffNote})`;
    },

    scheduleNext() {
      if (this.timerId) {
        clearTimeout(this.timerId);
        this.timerId = null;
      }
      const waitMs = this.getEffectiveIntervalMs();
      if (waitMs <= 0) return;
      this.timerId = setTimeout(() => this.tick('periodic_timer'), waitMs);
    },

    async tick(reason = 'periodic_timer') {
      if (this.timerId) {
        clearTimeout(this.timerId);
        this.timerId = null;
      }
      if (dataSourceMode === 'mock') return;
      if (reason === 'periodic_timer' && typeof document !== 'undefined' && document.hidden) {
        this.scheduleNext();
        return;
      }
      if (this.isHydrating) {
        this.scheduleNext();
        return;
      }
      this.lastTickAt = window.nowFetchedAt ? window.nowFetchedAt() : new Date().toISOString();
      this.tickCount += 1;
      // P1-02: Periodic polling passes preserveSubpageDom: true so active forms/inputs are NEVER destroyed!
      const res = await tryHydrateFromLiveServer(activeScope, { fromPoller: true, preserveSubpageDom: true, reason });
      if (res && res.ok) {
        this.consecutiveFailures = 0;
        this.lastSuccessAt = this.lastTickAt;
      } else {
        this.consecutiveFailures += 1;
      }
      this.scheduleNext();
      return res;
    },

    start(intervalMs) {
      if (typeof intervalMs === 'number' && intervalMs > 0) {
        this.baseIntervalMs = intervalMs;
      }
      this.enabled = true;
      this.consecutiveFailures = 0;
      this.scheduleNext();
      refreshAllViews({ preserveSubpageDom: true });
    },

    stop() {
      this.enabled = false;
      if (this.timerId) {
        clearTimeout(this.timerId);
        this.timerId = null;
      }
      refreshAllViews({ preserveSubpageDom: true });
    },

    setIntervalMs(ms) {
      const n = Number(ms);
      if (!n || n <= 0) {
        this.stop();
      } else {
        this.start(n);
      }
    }
  };

  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && pollingScheduler.enabled && dataSourceMode === 'live') {
        pollingScheduler.tick('visibility_resume');
      } else {
        refreshAllViews({ preserveSubpageDom: true });
      }
    });
  }

  window.__HUAIAN_POLLING_CONTROLLER__ = pollingScheduler;

  // ---------------------------------------------------------------------------
  // Core Live Hydration via PMMAdapter
  // ---------------------------------------------------------------------------
  async function tryHydrateFromLiveServer(scope = activeScope, opts = {}) {
    if ((activeHydrateCount > 0 || personaSwitchInFlight) && opts.fromPoller) {
      return { ok: false, skipped: true, reason: 'already_hydrating' };
    }
    if (dataSourceMode === 'mock' && opts.fromPoller) {
      return { ok: false, skipped: true, reason: 'mock_mode_active' };
    }
    const reqSeq = ++hydrateSeq;
    const reqEpoch = contextEpoch;
    activeHydrateCount += 1;
    pollingScheduler.isHydrating = true;
    activeScope = scope || activeScope || 'private:web:owner';
    try {
      const prevPersonaId = currentPersonaId();
      const res = await pmmAdapter.fetchAllLiveContracts(activeScope);

      // Phase 2.3.1 P1: Discard stale response if a newer request already applied or contextEpoch changed (e.g. role/mode switch)
      if (reqEpoch !== contextEpoch || reqSeq < latestAppliedHydrateSeq) {
        return { ok: false, skipped: true, reason: 'stale_response_discarded', reqSeq, latestAppliedHydrateSeq };
      }
      latestAppliedHydrateSeq = reqSeq;

      if (res.envelopes) {
        activeEnvelopes = res.envelopes;
        dataSourceMode = 'live';
        window.__HUAIAN_DATA_SOURCE_MODE__ = 'live';
        lastHydrationError = res.ok ? null : (res.error || '部分或全部接口请求异常');
        window.__HUAIAN_LIVE_HTTP_CONNECTED__ = Boolean(res.backend_reachable);

        const newPersonaId = currentPersonaId();
        const personaChanged = Boolean(newPersonaId && newPersonaId !== prevPersonaId);
        if (personaChanged || opts.forceFullRefresh) {
          // Persona switched: isolate session state & clear pending confirmations
          parlorSessionId = parlorSessionsByPersona[newPersonaId] || '';
          clearPendingTransientConfirmations();
        }
        // Sync available web sessions for active persona
        const backendSessions = (activeEnvelopes.characterProfile?.data?.sessions || []).filter(
          s => s && s.scope === 'private:web:owner'
        );
        const validInCurrentPersona = backendSessions.some(s => s.id === parlorSessionId) || Boolean(parlorSessionId && window.ParlorView.thread(parlorContext()).registered);
        if ((!parlorSessionId || !validInCurrentPersona) && backendSessions.length > 0) {
          parlorSessionId = backendSessions[0].id;
          parlorSessionsByPersona[newPersonaId] = parlorSessionId;
        } else if (!validInCurrentPersona && backendSessions.length === 0) {
          parlorSessionId = '';
        }
        if (parlorSessionId && !opts.skipSessionMessages) {
          const messageSession = parlorSessionId, messageContext = parlorContext();
          const mRes = await pmmAdapter.fetchSessionMessages(messageSession);
          if (reqEpoch !== contextEpoch || reqSeq < latestAppliedHydrateSeq) return { ok: false, skipped: true, reason: 'stale_messages_discarded' };
          window.ParlorView.observeMessages(messageContext, mRes);
          if (mRes.ok) parlorMessagesBySession[messageSession] = mRes.messages;
        }

        const preserveDom = personaChanged || opts.forceFullRefresh ? false : Boolean(opts.preserveSubpageDom);
        refreshAllViews({ preserveSubpageDom: preserveDom });
        return {
          ok: Boolean(res.ok),
          mode: 'live',
          reqSeq,
          persona_id: newPersonaId,
          overall_status: res.overall_status,
          ok_endpoints_count: res.ok_endpoints_count,
          error_endpoints_count: res.error_endpoints_count,
          envelopes: activeEnvelopes,
          callLog: pmmAdapter.callLog
        };
      } else {
        window.__HUAIAN_LIVE_HTTP_CONNECTED__ = Boolean(res.backend_reachable);
        lastHydrationError = res.error || '尚未完成连接检查';
        const E = window.DataEnvelopeFactory;
        const errCode = res.error_code || 'NETWORK_ERROR';
        activeEnvelopes = {
          mode: 'live',
          overall_status: 'error',
          ok_endpoints_count: 0,
          error_endpoints_count: 0,
          not_requested_endpoints_count: 17,
          backend_reachable: Boolean(res.backend_reachable),
          connection_state: res.connection_state,
          connection_error: lastHydrationError,
          total_endpoints_count: 17,
          fetched_at: window.nowFetchedAt(),
          characterProfile: E.unavailable('/api/state', '尚未读取：' + lastHydrationError),
          personality: E.unavailable('/api/ui3/overview', '尚未读取：' + lastHydrationError),
          emotion: E.unavailable('/api/affect', '尚未读取：' + lastHydrationError),
          psychological: E.unavailable('/api/affect', '尚未读取：' + lastHydrationError),
          expressionDrive: E.unavailable('/api/pmm283/expressive-drive', '尚未读取：' + lastHydrationError),
          memories: E.unavailable('/api/memories', '尚未读取：' + lastHydrationError),
          experiences: E.unavailable('/api/de/turns', '尚未读取：' + lastHydrationError),
          learning: E.unavailable('/api/learning', '尚未读取：' + lastHydrationError),
          socialGraph: E.unavailable('/api/social-graph', '尚未读取：' + lastHydrationError),
          connections: E.unavailable('/api/state', '尚未读取：' + lastHydrationError),
          decisions: E.unavailable('/api/pmm281/status', '尚未读取：' + lastHydrationError)
        };
        refreshAllViews({ preserveSubpageDom: Boolean(opts.preserveSubpageDom) });
        return { ok: false, mode: 'live', overall_status: 'error', error: lastHydrationError, error_code: errCode, callLog: pmmAdapter.callLog };
      }
    } finally {
      activeHydrateCount = Math.max(0, activeHydrateCount - 1);
      pollingScheduler.isHydrating = activeHydrateCount > 0;
    }
  }

  function switchDataSourceMode(targetMode) {
    window.PsychViz?.close();
    contextEpoch += 1;
    clearPendingTransientConfirmations();
    if (targetMode === 'mock') {
      dataSourceMode = 'mock';
      window.__HUAIAN_DATA_SOURCE_MODE__ = 'mock';
      pmmAdapter.clearEndpointFaultOverrides();
      Object.keys(domainFaults).forEach(k => { domainFaults[k] = 'normal'; });
      activeEnvelopes = mockAdapter.getAllMockEnvelopes();
      refreshAllViews({ preserveSubpageDom: false });
      return Promise.resolve({ ok: true, mode: 'mock', envelopes: activeEnvelopes });
    }
    dataSourceMode = 'live';
    window.__HUAIAN_DATA_SOURCE_MODE__ = 'live';
    return tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: false, forceFullRefresh: true });
  }

  async function switchActivePersona(targetId, feedbackEl = null) {
    if (!targetId) return { ok: false, error: '未指定目标角色 ID' };
    const guard = guardWrite('persona_switch', {
      endpoint: '/api/persona/activate',
      targetId,
      feedbackEl
    });
    if (!guard.allowed) {
      return { ok: false, blocked: true, error: guard.reason };
    }
    if (personaSwitchInFlight) {
      return { ok: false, error: '角色切换进行中，请勿重复点击' };
    }
    const prevId = currentPersonaId();
    if (targetId === prevId) {
      if (feedbackEl) {
        feedbackEl.style.color = '#3E5626';
        feedbackEl.textContent = '当前已处于该角色状态。';
      }
      return { ok: true, active_id: prevId, unchanged: true };
    }

    personaSwitchInFlight = true;
    window.PsychViz?.close();
    contextEpoch += 1;
    clearPendingTransientConfirmations();
    document.querySelectorAll('[data-switch-persona]').forEach(btn => { btn.disabled = true; });
    if (feedbackEl) {
      feedbackEl.style.color = '#3E5626';
      feedbackEl.textContent = `正在切换至目标角色 (${targetId.slice(0, 10)}…) 并同步全量数据...`;
    }

    try {
      const res = await pmmAdapter.postJson('/api/persona/activate', { id: targetId });
      if (res.status !== 'success') {
        if (feedbackEl) {
          feedbackEl.style.color = '#B83B2A';
          feedbackEl.textContent = `✗ 角色切换失败（已保留原角色）：${res.error || '后端拒绝切换'}`;
        }
        return { ok: false, error: res.error || '角色切换失败' };
      }

      // Clear transient per-persona state before hydrating new persona
      parlorSessionId = parlorSessionsByPersona[targetId] || '';
      parlorJobState = { active: false, job_id: null, status: null, phase: '', error: null };
      memorySearchQuery = '';
      memoryKindFilter = 'all';

      const hRes = await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: false, forceFullRefresh: true });
      const actualId = currentPersonaId();
      const actualName = activeEnvelopes.characterProfile?.data?.name || targetId;

      if (actualId !== targetId) {
        const msg = `✗ 角色切换校验未通过：期望角色 ${targetId}，实际返回 ${actualId}`;
        if (feedbackEl) {
          feedbackEl.style.color = '#B83B2A';
          feedbackEl.textContent = msg;
        }
        return { ok: false, error: msg, actual_id: actualId };
      }

      if (feedbackEl) {
        feedbackEl.style.color = '#2E4418';
        feedbackEl.textContent = `✓ 已切换至角色「${actualName}」(${actualId.slice(0, 10)}…)，全部领域数据与会话已同步更新。`;
      }
      return { ok: true, active_id: actualId, active_name: actualName, hydration: hRes };
    } finally {
      personaSwitchInFlight = false;
      document.querySelectorAll('[data-switch-persona]').forEach(btn => { btn.disabled = false; });
      if (['role_switcher', 'persona_manager'].includes(currentOpenModalKey)) {
        openModal(currentOpenModalKey);
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Per-Module Envelope Lookup & Badge Calculator (P1-04)
  // ---------------------------------------------------------------------------
  function getDomainEnvelope(domainKey) {
    const env = activeEnvelopes || {};
    switch (domainKey) {
      case 'profile':
      case 'characterProfile':
        return env.characterProfile;
      case 'personality':
        return env.personality;
      case 'cognition':
        return env.characterProfile?.data?.cognition_envelope || null;
      case 'emotion':
      case 'emotion_trend':
        return env.emotion;
      case 'psychological':
        return env.psychological;
      case 'expression_drive':
      case 'expressionDrive':
        return env.expressionDrive;
      case 'memories':
        return env.memories;
      case 'experiences':
        return env.experiences;
      case 'learning':
        return env.learning;
      case 'social':
      case 'socialGraph':
        return env.socialGraph;
      case 'connections':
        return env.connections;
      case 'decisions':
        return env.decisions;
      default:
        return env[domainKey] || null;
    }
  }

  function computeDomainBadgeSpec(domainKey) {
    const manualFault = domainFaults[domainKey];
    if (manualFault && manualFault !== 'normal') {
      if (manualFault === 'unavailable' || manualFault === 'empty') {
        return { cls: 'unavailable', text: `UNAVAILABLE · ${manualFault.toUpperCase()}`, title: '手动演练状态' };
      }
      return { cls: 'error', text: `ERROR · ${manualFault.toUpperCase()}`, title: '手动故障演练状态' };
    }

    const dEnv = getDomainEnvelope(domainKey);
    if (!dEnv) {
      return { cls: 'unavailable', text: 'UNAVAILABLE', title: '无对应数据信封' };
    }
    if (dEnv.status === 'error') {
      return {
        cls: 'error',
        text: `ERROR · ${dEnv.error_code || '请求失败'}`,
        title: `接口: ${dEnv.endpoint} | 错误: ${dEnv.error || ''} | 采集(UTC): ${dEnv.fetched_at || ''}`
      };
    }
    if (dEnv.source === 'mock') {
      return {
        cls: 'mock',
        text: 'MOCK 演示',
        title: `演示数据源 (${dEnv.endpoint}) | 采集(UTC): ${dEnv.fetched_at || ''}`
      };
    }
    if (domainKey === 'emotion_trend' && emotionRangeMode !== 'events') {
      return {
        cls: 'live',
        text: '已保存采样 · 按需读取',
        title: '读取实际保存的事件与时间演化点，未采样时段保留空白'
      };
    }
    if (dEnv.status === 'unavailable' || dEnv.source === 'unavailable') {
      if (domainKey === 'expression_drive' && dEnv.data && dEnv.data.has_active_stream === false) {
        return {
          cls: 'unavailable',
          text: 'LIVE · 暂无话题',
          title: `接口返回 streams=[] (无活跃流，数值为 null) | 采集(UTC): ${dEnv.fetched_at || ''}`
        };
      }
      return {
        cls: 'unavailable',
        text: 'UNAVAILABLE',
        title: dEnv.error || '原版后端暂未实现或无数据流'
      };
    }
    if (dEnv.status === 'empty') {
      if (domainKey === 'emotion') {
        return { cls: 'unavailable', text: 'LIVE · 待观察', title: `known=false, valence=null | 采集(UTC): ${dEnv.fetched_at || ''}` };
      }
      if (domainKey === 'emotion_trend') {
        return { cls: 'unavailable', text: 'LIVE · 0 轨迹点', title: `trajectory=[] | 采集(UTC): ${dEnv.fetched_at || ''}` };
      }
      if (domainKey === 'expression_drive') {
        return { cls: 'unavailable', text: 'LIVE · 暂无话题', title: `streams=[] | 采集(UTC): ${dEnv.fetched_at || ''}` };
      }
      return {
        cls: 'live',
        text: 'LIVE · 空(0)',
        title: `接口正常返回 0 条记录 (updated_at=null) | 采集(UTC): ${dEnv.fetched_at || ''}`
      };
    }
    if (dEnv.status === 'degraded') {
      return {
        cls: 'mock',
        text: 'DEGRADED · 部分异常',
        title: `部分子接口异常 | 采集(UTC): ${dEnv.fetched_at || ''}`
      };
    }
    const updInfo = dEnv.updated_at ? `业务更新(本地): ${fmtLocal(dEnv.updated_at)} (UTC: ${dEnv.updated_at})` : '业务更新: null (无事件)';
    return {
      cls: 'live',
      text: 'LIVE 实测',
      title: `${updInfo} | 采集(UTC): ${dEnv.fetched_at || ''} | 接口: ${dEnv.endpoint || ''}`
    };
  }

  function updateAllDomainBadges() {
    const env = activeEnvelopes || {};
    const overallStatus = env.overall_status || (env.mode === 'mock' ? 'mock' : 'live');
    const uTopBadge = document.getElementById('userTopSourceBadge');
    const dTopBadge = document.getElementById('devTopSourceBadge');

    if (uTopBadge) {
      if (env.mode === 'mock') {
        uTopBadge.className = 'envelope-badge mock';
        uTopBadge.textContent = 'MOCK 演示模式';
      } else if (overallStatus === 'error') {
        uTopBadge.className = 'envelope-badge error';
        uTopBadge.textContent = env.backend_reachable ? '服务可达 · 数据待刷新' : '连接待确认';
        uTopBadge.title = env.connection_error || lastHydrationError || '数据读取未完成，不代表后台任务失败';
      } else if (overallStatus === 'partial') {
        uTopBadge.className = 'envelope-badge mock';
        uTopBadge.textContent = `PARTIAL (${env.ok_endpoints_count}/${env.total_endpoints_count} 可达)`;
      } else {
        uTopBadge.className = 'envelope-badge live';
        uTopBadge.textContent = `LIVE (${env.ok_endpoints_count || 17}/${env.total_endpoints_count || 17} 接口)`;
      }
    }

    if (dTopBadge) {
      const connVer = env.connections?.data?.version || '2.8.3-dev';
      if (env.mode === 'mock') {
        dTopBadge.className = 'envelope-badge mock';
        dTopBadge.textContent = 'MOCK 演示';
      } else if (overallStatus === 'error') {
        dTopBadge.className = 'envelope-badge error';
        dTopBadge.textContent = env.backend_reachable ? '服务可达 · 读取异常' : '连接待确认';
        dTopBadge.title = env.connection_error || lastHydrationError || '请查看具体请求状态';
      } else if (overallStatus === 'partial') {
        dTopBadge.className = 'envelope-badge mock';
        dTopBadge.textContent = `PARTIAL ${connVer}`;
      } else {
        dTopBadge.className = 'envelope-badge live';
        dTopBadge.textContent = `LIVE ${connVer}`;
      }
    }

    document.querySelectorAll('.js-domain-badge').forEach(b => {
      const domain = b.dataset.domain || 'profile';
      const spec = computeDomainBadgeSpec(domain);
      b.className = `envelope-badge ${spec.cls} js-domain-badge`;
      b.textContent = spec.text;
      if (spec.title) b.title = spec.title;
    });
  }

  function renderFaultBannerIfAny(domainKey, isDeveloper) {
    const manualFault = domainFaults[domainKey] || 'normal';
    const dEnv = getDomainEnvelope(domainKey);

    if (manualFault === 'loading' || (dEnv && dEnv.status === 'loading')) {
      return `
        <div style="display:flex;flex-direction:column;gap:8px;padding:10px 0;">
          <div class="skeleton-shimmer" style="width:68%;"></div>
          <div class="skeleton-shimmer" style="width:92%;height:42px;"></div>
          <div style="font-size:11.5px;color:#6E7266;">正在通过 PMMAdapter 请求原版后端 <code>${esc(domainKey)}</code> 接口...</div>
        </div>
      `;
    }

    if (dEnv && dEnv.status === 'error') {
      return `
        <div class="card-state-banner error">
          <div>
            <strong>模块接口异常 [${esc(dEnv.error_code || 'ERROR')}]</strong>
            <div>接口 <code>${esc(dEnv.endpoint)}</code>：${esc(dEnv.error || '请求失败')}（采集时间：${esc(fmtLocal(dEnv.fetched_at))}）。本卡片已独立隔离错误，绝不冒充 LIVE。</div>
          </div>
          <button type="button" class="mini-tab-btn active" data-retry-domain="${esc(domainKey)}">重试该模块</button>
        </div>
      `;
    }

    if (dEnv && dEnv.status === 'unavailable' && domainKey !== 'expression_drive') {
      return `
        <div class="card-state-banner unavailable">
          <div>
            <strong>接口或功能未实现 (UNAVAILABLE)</strong>
            <div>接口 <code>${esc(dEnv.endpoint)}</code>：${esc(dEnv.error || '原版 v2.8.3 暂未实现')}。</div>
          </div>
          <button type="button" class="mini-tab-btn active" data-retry-domain="${esc(domainKey)}">重新检测</button>
        </div>
      `;
    }

    if (manualFault === 'normal') return null;

    if (manualFault === 'empty') {
      return `
        <div class="card-state-banner unavailable">
          <div>
            <strong>当前模块数据为空 (EMPTY)</strong>
            <div>原版后端返回空记录 <code>[]</code>，系统保持真实空状态，不虚构展示数据。</div>
          </div>
          <button type="button" class="mini-tab-btn active" data-clear-fault="${esc(domainKey)}">恢复</button>
        </div>
      `;
    }
    if (manualFault === 'unavailable') {
      return `
        <div class="card-state-banner unavailable">
          <div>
            <strong>待接入 · 原版后端尚未实现此接口 (UNAVAILABLE / HTTP 404)</strong>
            <div>${isDeveloper ? `模块 <code>${esc(domainKey)}</code> 对应的聚合接口未实现，已登记至 FUTURE_FEATURES_BACKLOG.md。` : '该项高阶聚合功能尚未在后端实现，将在后续版本接入。'}</div>
          </div>
          <button type="button" class="mini-tab-btn active" data-clear-fault="${esc(domainKey)}">恢复</button>
        </div>
      `;
    }
    const errMap = {
      network_error: ['暂时无法读取', '请确认本地程序仍在运行，再刷新状态；后台任务结果需另行确认。'],
      timeout: ['请求超时 (AbortController TIMEOUT)', '读取该接口超时，已触发单卡错误隔离，不影响页面其余卡片。'],
      schema_error: ['数据格式校验失败 (SCHEMA_MISMATCH)', 'DataEnvelope 字段校验未通过，已拦截异常数值渲染。']
    };
    const [title, desc] = errMap[manualFault] || ['模块读取异常', '请稍后重试'];
    return `
      <div class="card-state-banner error">
        <div>
          <strong>${esc(title)}</strong>
          <div>${isDeveloper ? `[组件域: ${esc(domainKey)}] ${esc(desc)}` : esc(desc)}</div>
        </div>
        <button type="button" class="mini-tab-btn active" data-clear-fault="${esc(domainKey)}">重试恢复</button>
      </div>
    `;
  }

  function buildRadarSvg(hexList, size = 138) {
    const cx = size / 2;
    const cy = size / 2;
    const rMax = size * 0.36;
    const angles = [-90, -30, 30, 90, 150, 210].map(a => (a * Math.PI) / 180);

    let gridPolys = '';
    [0.33, 0.66, 1.0].forEach(level => {
      const pts = angles.map(ang => `${(cx + rMax * level * Math.cos(ang)).toFixed(1)},${(cy + rMax * level * Math.sin(ang)).toFixed(1)}`).join(' ');
      gridPolys += `<polygon points="${pts}" fill="none" stroke="rgba(128,136,114,0.28)" stroke-width="1" ${level === 0.66 ? 'stroke-dasharray="2 2"' : ''}/>`;
    });

    let axes = '';
    let labels = '';
    const validPts = [];
    (hexList || []).forEach((item, idx) => {
      const ang = angles[idx] || 0;
      const xEnd = cx + rMax * Math.cos(ang);
      const yEnd = cy + rMax * Math.sin(ang);
      axes += `<line x1="${cx}" y1="${cy}" x2="${xEnd.toFixed(1)}" y2="${yEnd.toFixed(1)}" stroke="rgba(128,136,114,0.25)" stroke-width="1"/>`;
      const lx = cx + (rMax + 16) * Math.cos(ang);
      const ly = cy + (rMax + 13) * Math.sin(ang);
      labels += `<text x="${lx.toFixed(1)}" y="${(ly + 3).toFixed(1)}" text-anchor="middle" font-size="10.5" fill="#43473D" font-weight="600">${esc(item.code)}</text>`;
      if (item.val !== null && item.val !== undefined) {
        const clampedVal = Math.max(0, Math.min(1, Number(item.val)));
        const px = cx + rMax * clampedVal * Math.cos(ang);
        const py = cy + rMax * clampedVal * Math.sin(ang);
        validPts.push({ x: px, y: py, val: clampedVal });
      }
    });

    let dataShape = '';
    if (validPts.length >= 3) {
      const polyStr = validPts.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
      dataShape = `<polygon points="${polyStr}" fill="rgba(126, 152, 94, 0.28)" stroke="#688247" stroke-width="2"/>`;
      validPts.forEach(p => {
        dataShape += `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="3" fill="#688247"/>`;
      });
    } else {
      dataShape = `<circle cx="${cx}" cy="${cy}" r="${rMax * 0.45}" fill="none" stroke="#9AA092" stroke-width="1.5" stroke-dasharray="4 3"/>
                   <text x="${cx}" y="${cy + 4}" text-anchor="middle" font-size="10" fill="#6E7266">未知 (${validPts.length}/6域)</text>`;
    }

    return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}" style="flex-shrink:0;">${gridPolys}${axes}${dataShape}${labels}</svg>`;
  }

  function renderConnectionStateBadge(state) {
    const map = {
      healthy: { bg: '#6E8B4E', color: '#fff', text: '✓ 在线已验证 (healthy)' },
      reachable: { bg: '#5B7C66', color: '#fff', text: '✓ 本地可达 (reachable)' },
      running: { bg: '#3E6E8C', color: '#fff', text: '↻ 运行中 (running)' },
      configured: { bg: '#C68B39', color: '#fff', text: '? 已配置/未验证 (configured)' },
      unknown: { bg: '#8B8E82', color: '#fff', text: '? 状态未知 (unknown)' },
      unavailable: { bg: 'rgba(140,142,132,0.24)', color: '#52564B', text: '— 未配置/未启用 (unavailable)' }
    };
    const item = map[state] || map.unknown;
    return `<span style="display:inline-flex;align-items:center;padding:2px 8px;border-radius:999px;font-size:10.5px;font-weight:700;background:${item.bg};color:${item.color};">${esc(item.text)}</span>`;
  }

  function serviceDotColor(state) {
    if (state === 'healthy' || state === 'reachable') return '#6E8B4E';
    if (state === 'running') return '#3E6E8C';
    if (state === 'configured') return '#D48E3B';
    return '#9A9D90';
  }

  function sourceTypeBadgeLabel(st) {
    if (st === 'owner_seed') return '主人设定 (owner_seed)';
    if (st === 'questionnaire') return '量表记录 (questionnaire)';
    if (st === 'distilled' || st === 'promoted') return '证据晋升 (promoted)';
    return '未设定 (unknown)';
  }

  // ---------------------------------------------------------------------------
  // Render User Mode Home (100% Escaped & Per-Module Isolated)
  // ---------------------------------------------------------------------------
  function renderUserHomeDynamicCards() {
    const env = activeEnvelopes;
    const isLive = env.mode === 'live';

    const charData = (env.characterProfile && env.characterProfile.data) || {};
    const persData = (env.personality && env.personality.data) || {};
    const emoData = (env.emotion && env.emotion.data) || {};
    const driveData = (env.expressionDrive && env.expressionDrive.data) || {};
    const memData = (env.memories && env.memories.data) || {};
    const expData = (env.experiences && env.experiences.data) || {};
    const learnData = (env.learning && env.learning.data) || {};
    const connData = (env.connections && env.connections.data) || {};

    document.querySelectorAll('.js-persona-name').forEach(el => {
      el.textContent = charData.name || (env.characterProfile?.status === 'error' ? '后端未连接' : '未命名');
    });
    document.querySelectorAll('.js-trait-ver').forEach(el => {
      el.textContent = String(persData.version ?? 0);
    });

    updateAllDomainBadges();

    // 1. 此刻心境 Card
    const emoFault = renderFaultBannerIfAny('emotion', false);
    const moodHeadline = document.getElementById('userMoodHeadline');
    const moodDesc = document.getElementById('userMoodDescLines');
    const moodPills = document.getElementById('userMoodDimPills');
    const moodOrb = document.getElementById('userMoodCloudOrb');
    const moodBadge = document.getElementById('userMoodBadgeText');
    const pal = emoData.palette || { primary: '#9BA396', secondary: '#CED3C8', glow: 'rgba(155,163,150,0.3)', rule: '' };

    if (moodBadge) moodBadge.textContent = emoFault ? '模块异常' : (emoData.badge || '未知');
    if (moodOrb) {
      moodOrb.style.background = `radial-gradient(circle at 35% 35%, ${pal.secondary} 0%, ${pal.primary} 68%, ${pal.glow} 100%)`;
    }
    if (emoFault && moodDesc) {
      if (moodHeadline) moodHeadline.textContent = '无法读取此刻心境';
      moodDesc.innerHTML = emoFault;
      if (moodPills) moodPills.innerHTML = '';
    } else if (moodHeadline && moodDesc && moodPills) {
      moodHeadline.textContent = emoData.headline || '尚未产生情绪观测';
      moodDesc.innerHTML = `<div>${esc(emoData.desc || '')}</div>`;
      moodPills.innerHTML = `
        <span class="mood-dim-pill">愉悦度： <strong>${emoData.valence !== null && emoData.valence !== undefined ? (emoData.valence >= 0 ? '+' : '') + Number(emoData.valence).toFixed(3) : '待观察'}</strong></span>
        <span class="mood-dim-pill">活跃度： <strong>${emoData.arousal !== null && emoData.arousal !== undefined ? Number(emoData.arousal).toFixed(3) : '待观察'}</strong></span>
        <span class="mood-dim-pill">背景心境： <strong>${emoData.mood_valence !== null && emoData.mood_valence !== undefined ? (emoData.mood_valence >= 0 ? '+' : '') + Number(emoData.mood_valence).toFixed(3) : '待观察'}</strong></span>
        <span class="mood-dim-pill" style="color:#5B703E;">${esc(emoData.delta_label || '0 点')}</span>
      `;
    }

    // 2. 想说的话 Card
    const driveFault = renderFaultBannerIfAny('expression_drive', false);
    const thoughtLine = document.getElementById('userThoughtTextLine');
    const thoughtBadge = document.getElementById('userThoughtMotiveBadge');
    if (thoughtLine) {
      if (driveFault) {
        thoughtLine.innerHTML = driveFault;
      } else {
        thoughtLine.innerHTML = `${esc(driveData.thought_quote || '（暂时没有想继续表达的话题）')}<span class="thoughts-quote-inline-close">”</span>`;
      }
    }
    if (thoughtBadge) {
      if (driveFault) {
        thoughtBadge.textContent = 'ERROR';
      } else {
        thoughtBadge.textContent = driveData.motive_id
          ? `还有想说的话 · 激活 ${((driveData.motive_activation ?? driveData.activation ?? 0) * 100).toFixed(0)}%`
          : `待表达话题： ${driveData.unfinished_count ?? 0} 条`;
      }
    }

    // 3. 最近经历 Card
    const expFault = renderFaultBannerIfAny('experiences', false);
    const expListEl = document.getElementById('userRecentExpList');
    if (expListEl) {
      if (expFault) {
        expListEl.innerHTML = `<li class="exp-list-item">${expFault}</li>`;
      } else {
        const expItems = expData.items || [];
        if (expItems.length === 0) {
          expListEl.innerHTML = `<li class="exp-list-item"><span class="exp-item-left"><i class="green-bullet-dot"></i><span>当前数据库尚无已完成认知评价的对话回合（<code>/api/de/turns</code> rows=0）</span></span><span class="exp-item-time">空(0)</span></li>`;
        } else {
          expListEl.innerHTML = expItems.slice(0, 3).map(it => `
            <li class="exp-list-item">
              <span class="exp-item-left"><i class="green-bullet-dot"></i><span>${esc(String(it.title || '').slice(0, 28))} <small style="color:#6D8351;">[${esc(it.emo)}]</small></span></span>
              <span class="exp-item-time">${esc(it.display_time || fmtLocal(it.time, false))}</span>
            </li>
          `).join('');
        }
      }
    }

    // 4. 记忆摘要 Card
    const memFault = renderFaultBannerIfAny('memories', false);
    const memCountEl = document.getElementById('userMemoryCountText');
    const memListEl = document.getElementById('userMemoryBulletList');
    if (memCountEl) {
      memCountEl.textContent = memFault ? '读取异常' : `${isLive ? '当前库' : 'MOCK'} 共 ${memData.total_count ?? 0} 条`;
    }
    if (memListEl) {
      if (memFault) {
        memListEl.innerHTML = `<li class="memory-bullet-item">${memFault}</li>`;
      } else {
        const memItems = memData.items || [];
        if (memItems.length === 0) {
          memListEl.innerHTML = `<li class="memory-bullet-item"><i class="green-bullet-dot"></i><span>还没有留下记忆，之后的交流会逐渐积累。</span></li>`;
        } else {
          memListEl.innerHTML = memItems.slice(0, 3).map(m => `
            <li class="memory-bullet-item"><i class="green-bullet-dot"></i><span><small>${esc(window.DisplayText.label(m.kind))}</small> · ${esc(String(m.content || '').slice(0, 55))}</span></li>
          `).join('');
        }
      }
    }

    // 5. 人格特征 Card
    const pBody = document.getElementById('userPersonaCardBody');
    if (pBody) {
      const pFault = renderFaultBannerIfAny('personality', false);
      if (pFault) {
        pBody.innerHTML = pFault;
      } else if (personaViewMode === 'hexaco') {
        const hexArr = persData.hexaco || [];
        const barsHtml = hexArr.map(item => {
          const hasVal = item.val !== null && item.val !== undefined;
          const pct = hasVal ? Math.max(0, Math.min(100, Math.round(Number(item.val) * 100))) : 0;
          const valStr = hasVal ? Number(item.val).toFixed(2) : 'null(未知)';
          return `
            <div class="drive-tendency-row" style="margin-bottom:4px;">
              <span style="width:78px;font-size:11.5px;font-weight:600;">${esc(item.name)} (${esc(item.code)})</span>
              <div class="drive-tendency-bar">
                <div class="drive-tendency-fill" style="width:${pct}%;${!hasVal ? 'background:transparent;' : ''}"></div>
              </div>
              <span style="width:68px;text-align:right;font-size:11px;color:#54584D;">${esc(valStr)} <small>(${esc(item.known)})</small></span>
            </div>
          `;
        }).join('');
        pBody.innerHTML = `
          <div style="display:flex;align-items:center;gap:12px;" data-user-nav="persona_analysis">
            ${buildRadarSvg(hexArr, 134)}
            <div style="flex:1;min-width:0;">${barsHtml}</div>
          </div>
          <div style="margin-top:6px;padding-top:5px;border-top:1px solid rgba(155,153,140,0.2);display:flex;justify-content:space-between;font-size:11px;color:#5B6054;">
            <span>已建档构念：<strong>${persData.known_count ?? 0}/${persData.total_count ?? 68}</strong> 项（其余保持 null 未知）</span>
            <span style="color:#5B733E;font-weight:600;" data-user-nav="persona_analysis">完整分析 →</span>
          </div>
        `;
      } else {
        const bList = persData.blocks68 || [];
        pBody.innerHTML = `
          <div style="display:flex;flex-direction:column;gap:5px;">
            ${bList.map(b => `
              <div style="padding:5px 8px;border-radius:8px;background:rgba(255,255,255,0.52);border:1px solid rgba(155,153,140,0.18);">
                <div style="display:flex;justify-content:space-between;font-size:11.5px;font-weight:700;">
                  <span>[${esc(b.code)}] ${esc(b.name)}</span>
                  <span style="color:#4F6835;">已建档 ${b.known}/${b.total} · 均值 ${b.mean !== null && b.mean !== undefined ? Number(b.mean).toFixed(2) : 'null'}</span>
                </div>
                <div style="font-size:10.5px;color:#62665A;">${esc(b.note)}</div>
              </div>
            `).join('')}
          </div>
        `;
      }
    }

    // 6. 情绪变化 Card
    const eBody = document.getElementById('userEmotionTrendBody');
    if (eBody) {
      const eFault = renderFaultBannerIfAny('emotion_trend', false);
      if (eFault) {
        eBody.innerHTML = eFault;
      } else if (isLive && (emotionRangeMode === '24h' || emotionRangeMode === '7d')) {
        eBody.innerHTML = window.SampleView.html(visualContext(),'home',emotionRangeMode);
      } else {
        const pts = emoData.events_points || [];
        if (pts.length === 0) {
          eBody.innerHTML = `
            <div class="card-state-banner unavailable" style="margin-top:6px;">
              <div>
                <strong>当前尚无情绪轨迹节点 (trajectory = [])</strong>
                <div>原版后端 <code>/api/ui3/overview → affect_2d.trajectory</code> 当前为空列表。在发起真实对话回合后将自动记录事件跳跃节点。</div>
              </div>
            </div>
          `;
        } else {
          const w = 360, h = emotionExpanded ? 145 : 108, padL = 28, padR = 16, padT = 14, padB = 22;
          const plotW = w - padL - padR, plotH = h - padT - padB;
          const vCoords = pts.map((p, i) => {
            const x = pts.length === 1 ? padL + plotW / 2 : padL + (i / (pts.length - 1)) * plotW;
            const vNorm = Math.max(0, Math.min(1, (Number(p.v) + 1) / 2));
            return { x, y: padT + (1 - vNorm) * plotH, v: Number(p.v), a: Number(p.a), label: p.t };
          });
          const aCoords = pts.map((p, i) => {
            const x = pts.length === 1 ? padL + plotW / 2 : padL + (i / (pts.length - 1)) * plotW;
            const aNorm = Math.max(0, Math.min(1, Number(p.a)));
            return { x, y: padT + (1 - aNorm) * plotH };
          });
          const vLine = vCoords.length > 1 ? `<polyline points="${vCoords.map(c => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ')}" fill="none" stroke="#6E8953" stroke-width="2.4"/>` : '';
          const aLine = aCoords.length > 1 ? `<polyline points="${aCoords.map(c => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ')}" fill="none" stroke="#DF9B52" stroke-width="2" stroke-dasharray="4 2"/>` : '';
          const dots = vCoords.map((c, i) => `
            <circle cx="${c.x.toFixed(1)}" cy="${c.y.toFixed(1)}" r="4" fill="#48632B" stroke="#fff" stroke-width="1.2"/>
            <text x="${c.x.toFixed(1)}" y="${h - 5}" text-anchor="middle" font-size="9.5" fill="#5B6054">#${i + 1}(${c.v >= 0 ? '+' : ''}${c.v.toFixed(2)})</text>
          `).join('');
          eBody.innerHTML = `
            <svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" style="display:block;">
              <line x1="${padL}" y1="${padT}" x2="${w - padR}" y2="${padT}" stroke="rgba(145,144,132,0.22)" stroke-dasharray="3 3"/>
              <line x1="${padL}" y1="${padT + plotH / 2}" x2="${w - padR}" y2="${padT + plotH / 2}" stroke="rgba(145,144,132,0.22)" stroke-dasharray="3 3"/>
              <line x1="${padL}" y1="${padT + plotH}" x2="${w - padR}" y2="${padT + plotH}" stroke="rgba(145,144,132,0.3)"/>
              ${vLine}${aLine}${dots}
            </svg>
            <div style="font-size:11px;color:#55594E;margin-top:3px;display:flex;justify-content:space-between;">
              <span>● 绿实线：愉悦度 Valence &nbsp; ● 橙虚线：唤醒度 Arousal</span>
              <span>共 ${pts.length} 个真实事件节点</span>
            </div>
          `;
        }
      }
    }

    // 7. 表达状态 Card
    const dBody = document.getElementById('userExpressionDriveBody');
    if (dBody) {
      if (driveFault) {
        dBody.innerHTML = driveFault;
      } else if (!driveData.has_active_stream || driveData.activation === null || driveData.activation === undefined) {
        const tendHtml = (driveData.tendencies || []).map(t => `
          <div class="drive-tendency-row" style="margin-bottom:4px;" title="${esc(t.note)}">
            <span style="width:78px;font-weight:600;">${esc(t.label)}</span>
            <div class="drive-tendency-bar"><div class="drive-tendency-fill" style="width:0%;background:transparent;"></div></div>
            <strong style="width:58px;text-align:right;font-size:10.5px;color:#7A7E72;">无流(null)</strong>
          </div>
        `).join('');
        dBody.innerHTML = `
          <div style="display:flex;align-items:center;gap:14px;" data-user-nav="emo_drive">
            <svg width="82" height="82" viewBox="0 0 92 92" style="flex-shrink:0;">
              <circle cx="46" cy="46" r="36" fill="none" stroke="rgba(155,153,140,0.32)" stroke-width="6" stroke-dasharray="5 4"/>
              <text x="46" y="43" text-anchor="middle" font-family="var(--font-serif)" font-size="14" font-weight="700" fill="#686C60">无活跃流</text>
              <text x="46" y="58" text-anchor="middle" font-size="9.5" fill="#7A7E72">等待新话题</text>
            </svg>
            <div style="flex:1;min-width:0;">${tendHtml}</div>
          </div>
          <div style="margin-top:5px;padding-top:5px;border-top:1px solid rgba(155,153,140,0.2);font-size:10.5px;color:#585C50;">
            ${esc(driveData.influence_note || '当前没有活跃话题，等待下一次互动。')}
          </div>
        `;
      } else {
        const actPct = Math.max(0, Math.min(100, Math.round(Number(driveData.activation) * 100)));
        const offset = Math.round(226 * (1 - actPct / 100));
        const tendHtml = (driveData.tendencies || []).map(t => {
          const tPct = Math.max(0, Math.min(100, Number(t.pct ?? 0)));
          return `
            <div class="drive-tendency-row" style="margin-bottom:4px;" title="${esc(t.note)}">
              <span style="width:78px;font-weight:600;">${esc(t.label)}</span>
              <div class="drive-tendency-bar"><div class="drive-tendency-fill" style="width:${tPct}%"></div></div>
              <strong style="width:36px;text-align:right;font-size:11px;">${tPct}%</strong>
            </div>
          `;
        }).join('');
        dBody.innerHTML = `
          <div style="display:flex;align-items:center;gap:14px;" data-user-nav="emo_drive">
            <svg width="82" height="82" viewBox="0 0 92 92" style="flex-shrink:0;">
              <circle cx="46" cy="46" r="36" fill="none" stroke="rgba(155,153,140,0.22)" stroke-width="8"/>
              <circle cx="46" cy="46" r="36" fill="none" stroke="#768F58" stroke-width="8" stroke-linecap="round"
                transform="rotate(-90 46 46)" stroke-dasharray="226" stroke-dashoffset="${offset}"/>
              <text x="46" y="44" text-anchor="middle" font-family="var(--font-serif)" font-size="18" font-weight="700" fill="#292D25">${actPct}%</text>
              <text x="46" y="59" text-anchor="middle" font-size="9.5" fill="#657746">${esc(window.DisplayText.label(driveData.intent || 'LISTEN'))}</text>
            </svg>
            <div style="flex:1;min-width:0;">${tendHtml}</div>
          </div>
          <div style="margin-top:5px;padding-top:5px;border-top:1px solid rgba(155,153,140,0.2);font-size:10.5px;color:#585C50;">
            ${esc(driveData.influence_note || '')}
          </div>
        `;
      }
    }

    // 8. 成长工作室、会客室、连接状态 Cards
    const studioDesc = document.querySelector('.card-studio-desc');
    if (studioDesc) {
      const lFault = renderFaultBannerIfAny('learning', false);
      if (lFault) {
        studioDesc.innerHTML = lFault;
      } else {
        studioDesc.innerHTML = `
          <div>已建档构念：<strong>${persData.known_count ?? 0}/${persData.total_count ?? 68}</strong> 项（版本 v${persData.version ?? 0}）</div>
          <div>学习任务队列：<strong>${learnData.total_jobs ?? (learnData.jobs || []).length}</strong> 项 · 待审阅特质候选：<strong>${(learnData.candidates || []).length}</strong> 项</div>
        `;
      }
    }
    const parlorDesc = document.querySelector('.card-parlor-desc');
    if (parlorDesc) {
      const curMsgs = parlorSessionId ? (parlorMessagesBySession[parlorSessionId] || []).length : 0;
      parlorDesc.innerHTML = `
        <div>当前会话消息：<strong>${curMsgs}</strong> 条 · 评价回合：<strong>${expData.total_count ?? 0}</strong> 轮</div>
        <div>还想说的话题：<strong>${driveData.unfinished_count ?? 0}</strong> 条 · ${esc(driveData.has_active_stream ? window.DisplayText.label(driveData.intent || 'LISTEN') : '当前没有活跃话题')}</div>
      `;
    }

    const connBadge = document.getElementById('userConnOverallBadge');
    const connRows = document.getElementById('userConnRows');
    const cFault = renderFaultBannerIfAny('connections', false);
    if (connBadge) {
      connBadge.textContent = cFault ? '连接状态待刷新' : (connData.overall_badge || '状态待检');
    }
    if (connRows) {
      if (cFault) {
        connRows.innerHTML = cFault;
      } else if (Array.isArray(connData.user_summary_rows)) {
        connRows.innerHTML = connData.user_summary_rows.map(r => {
          const st = r.state || 'unknown';
          const bg = (st === 'healthy' || st === 'reachable') ? '#7E9860' : (st === 'running' ? '#3E6E8C' : (st === 'configured' ? '#C68B39' : '#95988B'));
          const symbol = (st === 'healthy' || st === 'reachable') ? '✓' : (st === 'running' ? '↻' : (st === 'configured' ? '?' : '—'));
          return `
            <div class="conn-row-item" title="状态: ${esc(window.DisplayText.state(st))} | 已连接: ${String(r.healthy)}">
              <span class="conn-row-left">
                <i class="conn-check-badge" style="background:${bg};color:#fff;font-style:normal;font-size:10px;font-weight:700;">${symbol}</i>
                <span>${esc(r.label)}</span>
              </span>
              <span class="conn-row-val">${esc(r.value)}</span>
            </div>
          `;
        }).join('');
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Render Developer Mode Overview
  // ---------------------------------------------------------------------------
  function renderDeveloperOverviewDynamicCards() {
    const env = activeEnvelopes;

    const charData = (env.characterProfile && env.characterProfile.data) || {};
    const persData = (env.personality && env.personality.data) || {};
    const emoData = (env.emotion && env.emotion.data) || {};
    const driveData = (env.expressionDrive && env.expressionDrive.data) || {};
    const memData = (env.memories && env.memories.data) || {};
    const learnData = (env.learning && env.learning.data) || {};
    const connData = (env.connections && env.connections.data) || {};
    const decData = (env.decisions && env.decisions.data) || {};

    updateAllDomainBadges();

    const greetTitle = document.getElementById('devGreetingTitle');
    const greetMeta = document.getElementById('devGreetingMeta');
    if (greetTitle) {
      if (env.overall_status === 'error') {
        greetTitle.textContent = '后端服务连接中断，请检查原版 Python Server 状态';
      } else {
        greetTitle.innerHTML = `开发者控制台就绪，当前主体：<span class="js-persona-name">${esc(charData.name || '未命名')}</span> (rev ${esc(charData.revision ?? 0)})`;
      }
    }
    if (greetMeta) {
      const uptimeStr = connData.uptime_seconds != null
        ? `进程已运行 ${Math.round(Number(connData.uptime_seconds) / 60)} 分钟`
        : '运行时间待获取（原版后端未提供进程启动时间戳）';
      const epStr = env.mode === 'mock'
        ? '当前处于显式 MOCK 演示模式'
        : `接口采集：${env.ok_endpoints_count ?? 0}/${env.total_endpoints_count ?? 17} 成功 · 本地显示时间：${fmtLocal(env.fetched_at)} (UTC: ${env.fetched_at || '--'})`;
      greetMeta.textContent = `${uptimeStr} · ${epStr} · ${pollingScheduler.getStatusSummary()}`;
    }

    const srvGrid = document.querySelector('[data-layout-grid="dev_overview_services"]');
    if (srvGrid && connData.nodes) {
      const n = connData.nodes;
      const cards = srvGrid.querySelectorAll('.dev-service-card');
      const applySrvCard = (card, node, badgeTextOverride, subTextOverride) => {
        if (!card || !node) return;
        const dot = card.querySelector('.dev-service-dot');
        const span = card.querySelector('.dev-service-badge span');
        const sub = card.querySelector('.dev-service-sub');
        if (dot) dot.style.background = serviceDotColor(node.status);
        if (span) span.textContent = badgeTextOverride || node.status_text;
        if (sub) sub.textContent = subTextOverride || node.detail;
      };
      applySrvCard(cards[0], n.general_llm);
      applySrvCard(
        cards[1],
        n.api_pmm,
        `轨迹 ${decData.traces_count ?? 0} 条 · A:${n.api_pmm?.status} / B:${n.learned_pmm?.status}`,
        `API-PMM: ${n.api_pmm?.status_text} | Learned-PMM: ${n.learned_pmm?.status_text}`
      );
      applySrvCard(cards[2], n.qq_channel);
      applySrvCard(
        cards[3],
        n.learning_service,
        n.learning_service?.status_text,
        `任务 ${learnData.total_jobs ?? 0} 项 · 记忆 ${memData.total_count ?? 0} 条 · 构念 v${persData.version ?? 0}`
      );
    }

    const dualBox = document.getElementById('devDualPmmTrackerBody');
    if (dualBox) {
      const decFault = renderFaultBannerIfAny('decisions', true);
      if (decFault) {
        dualBox.innerHTML = decFault;
      } else if (decData.api_pmm && decData.learned_pmm && decData.fusion) {
        const api = decData.api_pmm;
        const lrn = decData.learned_pmm;
        const fus = decData.fusion;
        const apiProbsStr = api.probs
          ? Object.entries(api.probs).map(([k, v]) => `${esc(k)}:${(Number(v) * 100).toFixed(0)}%`).slice(0, 4).join(', ')
          : '尚无回合调用';
        const lrnProbsStr = lrn.probs
          ? Object.entries(lrn.probs).map(([k, v]) => `${esc(k)}:${(Number(v) * 100).toFixed(0)}%`).slice(0, 4).join(', ')
          : '尚无前向输出';

        dualBox.innerHTML = `
          <div class="pmm-dual-grid">
            <div class="pmm-unit-box api-pmm">
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <strong style="font-size:12.5px;color:#3A4E24;">组件 A · API-PMM (${esc(api.version)})</strong>
                <span class="envelope-badge ${api.participated ? 'live' : 'unavailable'}">
                  ${api.participated ? `本轮已参与 · ${esc(api.elapsed_ms)}ms` : `未触发 (${esc(api.status)})`}
                </span>
              </div>
              <div style="font-size:11.5px;color:#4C5045;line-height:1.5;">
                <div><strong>连接与配置状态：</strong><code>${esc(api.connection_state || api.status)}</code> (${esc(api.provider_model)})</div>
                <div><strong>认知评价输出：</strong>${esc(api.appraisal_summary)}</div>
                <div><strong>原文证据锚点：</strong>${api.quote ? `“${esc(String(api.quote).slice(0, 44))}”` : '无 (尚无回合)'}</div>
                <div><strong>独立决策先验：</strong>首选动作 <code>${esc(api.preferred_action || 'none')}</code> (${apiProbsStr})</div>
              </div>
            </div>

            <div class="pmm-unit-box learned-pmm">
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <strong style="font-size:12.5px;color:#2C5263;">组件 B · Learned-PMM (${esc(lrn.version)})</strong>
                <span class="envelope-badge ${lrn.participated ? 'live' : 'unavailable'}">
                  ${lrn.participated ? `本轮已参与 · ${esc(lrn.status)}` : `权重已载入 · 未校准 (${esc(lrn.status)})`}
                </span>
              </div>
              <div style="font-size:11.5px;color:#4C5045;line-height:1.5;">
                <div><strong>参数与架构：</strong>核心 θ + 角色适配器 Δ (RANK=${esc(lrn.rank)}, LATENT=${esc(lrn.latent_dim)}, 步数=${esc(lrn.steps)}, 权重=${esc(lrn.checkpoint)})</div>
                <div><strong>有效构念掩码：</strong>${esc(lrn.known_constructs)}/${esc(lrn.total_constructs)} 项已知构念参与计算 · 门禁: <code>${esc(lrn.release_gate)}</code></div>
                <div><strong>独立决策预测：</strong>首选动作 <code>${esc(lrn.preferred_action || 'none')}</code> (${lrnProbsStr})</div>
              </div>
            </div>
          </div>

          <div class="pmm-fusion-strip">
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
              <span><strong>同轮协作与仲裁融合 (${esc(fus.turn_id)})：</strong>分歧检测 <code>disagreement=${esc(fus.disagreement)}</code> · 规则：<code>${esc(fus.rule)}</code></span>
              <span class="envelope-badge ${fus.has_trace ? 'live' : 'unavailable'}">最终决策：${esc(fus.final_action)}</span>
            </div>
            <div style="font-size:11px;color:#52564A;">
              仲裁结果：<code>${esc(fus.arbitration)}</code>（绝不将 API-PMM 与 Learned-PMM 简单平均合并） | 表达欲叠加：${esc(fus.drive_contrib)} | 验证回执：<code>${esc(fus.receipt_summary)}</code>
            </div>
          </div>
        `;
      }
    }

    const devPsychTitle = document.getElementById('devPsychStateTitle');
    const devPsychDesc = document.getElementById('devPsychDesc');
    const devBarVal = document.getElementById('devBarValence');
    const devTxtVal = document.getElementById('devTextValence');
    const devBarAro = document.getElementById('devBarArousal');
    const devTxtAro = document.getElementById('devTextArousal');
    const devEmoFault = renderFaultBannerIfAny('emotion', true);
    if (devEmoFault && devPsychDesc) {
      if (devPsychTitle) devPsychTitle.textContent = '模块读取异常';
      devPsychDesc.innerHTML = devEmoFault;
    } else {
      if (devPsychTitle) devPsychTitle.textContent = emoData.badge || '未知 · 尚无观测';
      if (devPsychDesc) {
        devPsychDesc.innerHTML = emoData.known
          ? `<div>快情绪 Valence ${emoData.valence >= 0 ? '+' : ''}${Number(emoData.valence).toFixed(3)} / Arousal ${Number(emoData.arousal).toFixed(3)}</div><div>慢心境 Valence ${emoData.mood_valence !== null && emoData.mood_valence !== undefined ? Number(emoData.mood_valence).toFixed(3) : 'null'} · 未竟动机 ${driveData.unfinished_count ?? 0} 条</div>`
          : `<div>原版后端返回 affect_2d.fast_emotion.known = false (valence=null, arousal=null)</div><div>尚未执行对话回合，保持真实未知状态。</div>`;
      }
    }
    const vPct = !devEmoFault && emoData.known && emoData.valence !== null ? Math.max(0, Math.min(100, Math.round(((Number(emoData.valence) + 1) / 2) * 100))) : 0;
    const aPct = !devEmoFault && emoData.known && emoData.arousal !== null ? Math.max(0, Math.min(100, Math.round(Number(emoData.arousal) * 100))) : 0;
    if (devBarVal) devBarVal.style.width = `${vPct}%`;
    if (devTxtVal) devTxtVal.textContent = !devEmoFault && emoData.known && emoData.valence !== null ? Number(emoData.valence).toFixed(2) : 'null';
    if (devBarAro) devBarAro.style.width = `${aPct}%`;
    if (devTxtAro) devTxtAro.textContent = !devEmoFault && emoData.known && emoData.arousal !== null ? Number(emoData.arousal).toFixed(2) : 'null';

    const devHex = document.getElementById('devHexacoBody');
    if (devHex) {
      const pFault = renderFaultBannerIfAny('personality', true);
      if (pFault) {
        devHex.innerHTML = pFault;
      } else {
        const hexArr = persData.hexaco || [];
        const bars = hexArr.map(item => {
          const hasVal = item.val !== null && item.val !== undefined;
          const pct = hasVal ? Math.max(0, Math.min(100, Math.round(Number(item.val) * 100))) : 0;
          return `
            <div class="dev-hex-bar-row">
              <span class="dev-hex-label">${esc(item.name)} (${esc(item.code)})</span>
              <div class="dev-hex-track"><div class="dev-hex-fill" style="width:${pct}%"></div></div>
              <strong class="dev-hex-val">${hasVal ? Number(item.val).toFixed(2) : 'null'}</strong>
            </div>
          `;
        }).join('');
        devHex.innerHTML = `
          ${buildRadarSvg(hexArr, 142)}
          <div class="dev-hexaco-bars">${bars}</div>
        `;
      }
    }

    const devCurve = document.getElementById('devEmotionCurveContainer');
    if (devCurve) {
      const eFault = renderFaultBannerIfAny('emotion_trend', true);
      const pts = emoData.events_points || [];
      if (eFault) {
        devCurve.innerHTML = eFault;
      } else if (pts.length === 0) {
        devCurve.innerHTML = `
          <div class="card-state-banner unavailable" style="margin-top:8px;">
            <div>
              <strong>暂无实测情绪轨迹节点 (affect_2d.trajectory = [])</strong>
              <div>当前角色尚无历史情绪跃迁点；原版后端未实现 24h 连续采样表，LIVE 模式下绝不根据单点或空状态捏造趋势曲线。</div>
            </div>
          </div>
        `;
      } else {
        const w = 440, h = 128, padL = 36, padR = 24, padT = 16, padB = 24;
        const plotW = w - padL - padR, plotH = h - padT - padB;
        const vCoords = pts.map((p, i) => ({
          x: pts.length === 1 ? padL + plotW / 2 : padL + (i / (pts.length - 1)) * plotW,
          y: padT + (1 - Math.max(0, Math.min(1, (Number(p.v) + 1) / 2))) * plotH,
          v: Number(p.v), a: Number(p.a)
        }));
        const aCoords = pts.map((p, i) => ({
          x: pts.length === 1 ? padL + plotW / 2 : padL + (i / (pts.length - 1)) * plotW,
          y: padT + (1 - Math.max(0, Math.min(1, Number(p.a)))) * plotH
        }));
        const vPoly = vCoords.length > 1 ? `<polyline points="${vCoords.map(c => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ')}" fill="none" stroke="#7A9460" stroke-width="2.5"/>` : '';
        const aPoly = aCoords.length > 1 ? `<polyline points="${aCoords.map(c => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ')}" fill="none" stroke="#DF9B52" stroke-width="2.2" stroke-dasharray="4 2"/>` : '';
        const circles = vCoords.map((c, i) => `
          <circle cx="${c.x.toFixed(1)}" cy="${c.y.toFixed(1)}" r="4" fill="#48632B" stroke="#fff" stroke-width="1.2"/>
          <text x="${c.x.toFixed(1)}" y="${h - 6}" text-anchor="middle" font-size="10" fill="#5D6156">事件#${i + 1}(${c.v >= 0 ? '+' : ''}${c.v.toFixed(2)})</text>
        `).join('');
        devCurve.innerHTML = `
          <svg class="dev-curve-svg" viewBox="0 0 ${w} ${h}">
            <line x1="${padL}" y1="${padT}" x2="${w - padR}" y2="${padT}" stroke="rgba(145,144,132,0.22)" stroke-dasharray="3 3"/>
            <line x1="${padL}" y1="${padT + plotH / 2}" x2="${w - padR}" y2="${padT + plotH / 2}" stroke="rgba(145,144,132,0.22)" stroke-dasharray="3 3"/>
            <line x1="${padL}" y1="${padT + plotH}" x2="${w - padR}" y2="${padT + plotH}" stroke="rgba(145,144,132,0.32)"/>
            <text x="30" y="${padT + 4}" text-anchor="end" font-size="10" fill="#77776D">+1.0</text>
            <text x="30" y="${padT + plotH / 2 + 4}" text-anchor="end" font-size="10" fill="#77776D">0.0</text>
            <text x="30" y="${padT + plotH + 4}" text-anchor="end" font-size="10" fill="#77776D">-1.0</text>
            ${vPoly}${aPoly}${circles}
          </svg>
        `;
      }
    }

    const devDrive = document.getElementById('devDriveBody');
    if (devDrive) {
      const dFault = renderFaultBannerIfAny('expression_drive', true);
      if (dFault) {
        devDrive.innerHTML = dFault;
      } else if (!driveData.has_active_stream || driveData.activation === null || driveData.activation === undefined) {
        devDrive.innerHTML = `
          <div class="dev-drive-gauge-wrap">
            <svg width="92" height="92" viewBox="0 0 100 100">
              <circle cx="50" cy="50" r="40" fill="none" stroke="rgba(155,153,140,0.32)" stroke-width="7" stroke-dasharray="6 4" />
              <text x="50" y="47" text-anchor="middle" font-family="var(--font-serif)" font-size="14" font-weight="700" fill="#686C60">无活跃流</text>
              <text x="50" y="63" text-anchor="middle" font-size="10" fill="#7A7E72">等待新话题</text>
            </svg>
          </div>
          <div class="dev-drive-info">
            <div class="dev-drive-level">尚无活跃话题</div>
            <div class="dev-drive-desc">
              <div>Activation: <code>null</code> · Urgency: <code>null</code> · Persistence: <code>null</code></div>
              <div>原版后端当前未产生任何会话表达流，严格保持未知状态 (null)，不以 0% 代替未知。</div>
            </div>
            <div class="dev-drive-tag">
              <i style="width:6px;height:6px;border-radius:999px;background:#9A9D90;display:inline-block;"></i>
              <span>待表达话题： ${driveData.unfinished_count ?? 0} 条</span>
            </div>
          </div>
        `;
      } else {
        const actPct = Math.max(0, Math.min(100, Math.round(Number(driveData.activation) * 100)));
        const offset = Math.round(251.2 * (1 - actPct / 100));
        const t0 = driveData.tendencies?.[0]?.pct ?? 0;
        const t1 = driveData.tendencies?.[1]?.pct ?? 0;
        const t2 = driveData.tendencies?.[2]?.pct ?? 0;
        devDrive.innerHTML = `
          <div class="dev-drive-gauge-wrap">
            <svg width="92" height="92" viewBox="0 0 100 100">
              <circle cx="50" cy="50" r="40" fill="none" stroke="rgba(155,153,140,0.22)" stroke-width="9" />
              <circle cx="50" cy="50" r="40" fill="none" stroke="#7A965C" stroke-width="9" stroke-linecap="round"
                transform="rotate(-90 50 50)" stroke-dasharray="251.2" stroke-dashoffset="${offset}" />
              <text x="50" y="48" text-anchor="middle" font-family="var(--font-serif)" font-size="21" font-weight="700" fill="#292D25">${actPct}%</text>
              <text x="50" y="64" text-anchor="middle" font-size="10" fill="#6E7065">${esc(window.DisplayText.label(driveData.intent || 'LISTEN'))}</text>
            </svg>
          </div>
          <div class="dev-drive-info">
            <div class="dev-drive-level">${esc(driveData.level_label || '活跃流')}</div>
            <div class="dev-drive-desc">
              <div>Activation ${(Number(driveData.activation) * 100).toFixed(1)}% · Urgency ${(Number(driveData.urgency || 0) * 100).toFixed(1)}% · Persistence ${(Number(driveData.persistence || 0) * 100).toFixed(1)}%</div>
              <div>[派生] 主动发言 ${t0}% · 补充表达 ${t1}% · 主动追问 ${t2}%</div>
            </div>
            <div class="dev-drive-tag">
              <i style="width:6px;height:6px;border-radius:999px;background:#7A965C;display:inline-block;"></i>
              <span>${driveData.motive_id ? `待表达话题： ${esc(String(driveData.motive_id).slice(0, 14))} (${esc(driveData.motive_status)})` : `待表达话题： ${driveData.unfinished_count ?? 0} 条`}</span>
            </div>
          </div>
        `;
      }
    }

    const actListEl = document.getElementById('devActivityList');
    if (actListEl) {
      const expErr = renderFaultBannerIfAny('experiences', true);
      if (expErr) {
        actListEl.innerHTML = expErr;
      } else {
        const rows = [];
        if (decData.fusion && decData.fusion.has_trace) {
          rows.push({
            t: '最新回合',
            html: `完成 PMM 双组件同轮协作 (<code>${esc(decData.fusion.turn_id)}</code>)：API-PMM(<code>${esc(decData.api_pmm?.preferred_action)}</code>) vs Learned-PMM(<code>${esc(decData.learned_pmm?.preferred_action)}</code>) → 决策 <code>${esc(decData.fusion.final_action)}</code>`
          });
        }
        if (driveData.motive_id) {
          rows.push({
            t: '表达动机',
            html: `Expressive Drive 存在未竟表达动机 <code>${esc(driveData.motive_id)}</code>（话题：${esc(driveData.motive_topic)} · 状态：${esc(driveData.motive_status)}）`
          });
        }
        if ((memData.items || []).length > 0) {
          rows.push({
            t: '记忆存储',
            html: `SQLite 记忆库当前存有 <strong>${memData.total_count}</strong> 条记忆，最新：「${esc(String(memData.items[0].content || '').slice(0, 36))}」`
          });
        }
        if (rows.length === 0) {
          rows.push({
            t: '空状态',
            html: `当前角色（${esc(charData.name)}）尚无对话回合与记忆记录（构念已建档 ${persData.known_count ?? 0}/${persData.total_count ?? 68} 项）。`
          });
        }
        actListEl.innerHTML = rows.map(r => `
          <div class="dev-activity-row">
            <span class="dev-act-time">${esc(r.t)}</span>
            <i class="dev-act-dot"></i>
            <span class="dev-act-text">${r.html}</span>
          </div>
        `).join('');
      }
    }

    const taskCard = document.querySelector('[data-layout-card="dev_card_tasks"]');
    if (taskCard) {
      const existingItems = taskCard.querySelectorAll('.dev-task-item, .card-state-banner');
      existingItems.forEach(el => el.remove());
      const lFault = renderFaultBannerIfAny('learning', true);
      if (lFault) {
        taskCard.insertAdjacentHTML('beforeend', lFault);
      } else {
        const jobs = Array.isArray(learnData.jobs) ? learnData.jobs : [];
        const realJobsCount = learnData.total_jobs ?? jobs.length;
        const learnSpec = computeDomainBadgeSpec('learning');

        let jobsHtml = '';
        if (realJobsCount > 0 && jobs.length > 0) {
          jobsHtml = jobs.slice(0, 3).map((job, idx) => {
            const pct = Math.max(0, Math.min(100, Number(job.progress ?? 0)));
            const dashOffset = Math.round(69 * (1 - pct / 100));
            return `
              <div class="dev-task-item clickable" data-dev-nav="distill_task" data-job-id="${esc(job.id)}">
                <div class="dev-task-left">
                  <svg width="26" height="26" viewBox="0 0 28 28" style="flex-shrink:0;margin-top:2px;">
                    <circle cx="14" cy="14" r="11" fill="none" stroke="rgba(155,153,140,0.25)" stroke-width="3"/>
                    <circle cx="14" cy="14" r="11" fill="none" stroke="#7E9860" stroke-width="3" stroke-linecap="round" transform="rotate(-90 14 14)" stroke-dasharray="69" stroke-dashoffset="${dashOffset}"/>
                  </svg>
                  <div style="flex:1;">
                    <div class="dev-task-title">${esc(job.title)}</div>
                    <div class="dev-task-sub">进度 ${pct}% · ${esc(job.phase)}</div>
                    <div class="dev-task-bar-track"><div class="dev-task-bar-fill" style="width:${pct}%"></div></div>
                  </div>
                </div>
                <span class="envelope-badge ${learnSpec.cls}">${esc(job.status)}</span>
              </div>
            `;
          }).join('');
        } else {
          jobsHtml = `
            <div class="dev-task-item clickable" data-dev-nav="data_import">
              <div class="dev-task-left">
                <span style="width:24px;height:24px;border-radius:999px;background:rgba(126,152,96,0.16);color:#4A6031;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:2px;font-size:11px;font-weight:700;">0</span>
                <div style="flex:1;">
                  <div class="dev-task-title">学习与蒸馏队列</div>
                  <div class="dev-task-sub">当前无学习任务记录 (jobs=0 · 待审阅候选 ${(learnData.candidates || []).length} 项)</div>
                </div>
              </div>
              <span class="envelope-badge ${learnSpec.cls}">空(0)</span>
            </div>`;
        }

        const memSpec = computeDomainBadgeSpec('memories');
        const memRowHtml = `
          <div class="dev-task-item clickable" data-dev-nav="learn_record">
            <div class="dev-task-left">
              <span style="width:24px;height:24px;border-radius:999px;background:#7E9860;color:#fff;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:2px;">
                <svg class="lucide-icon" width="13" height="13" viewBox="0 0 24 24" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
              </span>
              <div>
                <div class="dev-task-title">SQLite 长期记忆与构念索引</div>
                <div class="dev-task-sub">可达 · ${memData.total_count ?? 0} 条核心记忆 / ${persData.known_count ?? 0} 项已建档构念 (v${persData.version ?? 0})</div>
              </div>
            </div>
            <span class="envelope-badge ${memSpec.cls}">${esc(memSpec.text)}</span>
          </div>`;

        const cronRowHtml = `
          <div class="dev-task-item clickable" data-open-modal="dev_task_cron">
            <div class="dev-task-left">
              <span style="width:24px;height:24px;border-radius:999px;background:rgba(155,153,140,0.25);color:#596A3E;display:inline-flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:2px;">
                <svg class="lucide-icon" width="14" height="14" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15 15"/></svg>
              </span>
              <div>
                <div class="dev-task-title">周期性后台状态分析调度器</div>
                <div class="dev-task-sub">独立调度 · 查看触发条件、执行记录与自主整理设置</div>
              </div>
            </div>
            <span class="envelope-badge unavailable">UNAVAILABLE</span>
          </div>`;

        taskCard.insertAdjacentHTML('beforeend', jobsHtml + memRowHtml + cronRowHtml);
      }
    }
  }

  // ---------------------------------------------------------------------------
  // P1-01: Global LayoutManager (Real HTML5 Drag & Drop, 3-Size Resize, Cancel Rollback & Persistence)
  // ---------------------------------------------------------------------------
  const memoryLayoutStore = {};
  function getLayoutStorageKey(mode, page, personaId) {
    return `huaian_layout_v23_${mode}_${page}_${personaId}`;
  }
  function readSavedLayout(key) {
    try {
      const raw = localStorage.getItem(key);
      if (raw) return JSON.parse(raw);
    } catch (_) {}
    return memoryLayoutStore[key] ? JSON.parse(JSON.stringify(memoryLayoutStore[key])) : null;
  }
  function writeSavedLayout(key, obj) {
    memoryLayoutStore[key] = JSON.parse(JSON.stringify(obj));
    try {
      localStorage.setItem(key, JSON.stringify(obj));
    } catch (_) {}
  }
  function deleteSavedLayout(key) {
    delete memoryLayoutStore[key];
    try { localStorage.removeItem(key); } catch (_) {}
  }

  function currentPersonaId() {
    return (activeEnvelopes.characterProfile && activeEnvelopes.characterProfile.data && activeEnvelopes.characterProfile.data.id) || 'default';
  }

  function captureCurrentDomLayoutSnapshot() {
    const snap = {};
    document.querySelectorAll('[data-layout-grid]').forEach(grid => {
      const gridId = grid.dataset.layoutGrid;
      snap[gridId] = Array.from(grid.querySelectorAll(':scope > [data-layout-card]')).map((c, idx) => ({
        id: c.dataset.layoutCard,
        order: idx,
        size: c.dataset.cardSize || 'standard',
        visible: true
      }));
    });
    return snap;
  }

  function applyLayoutMapToDom(specMap) {
    if (!specMap) return;
    document.querySelectorAll('[data-layout-grid]').forEach(grid => {
      const gridId = grid.dataset.layoutGrid;
      const specList = specMap[gridId];
      if (!Array.isArray(specList)) return;
      const currentCards = Array.from(grid.querySelectorAll(':scope > [data-layout-card]'));
      const cardMap = {};
      currentCards.forEach(c => {
        cardMap[c.dataset.layoutCard] = c;
      });
      const currentOrderStr = currentCards.map(c => c.dataset.layoutCard).join('|');
      const targetOrderStr = specList.map(item => item.id).filter(id => cardMap[id]).join('|');
      const needsReorder = currentOrderStr !== targetOrderStr;
      specList.forEach(item => {
        const el = cardMap[item.id];
        if (el) {
          el.dataset.cardSize = item.size || 'standard';
          el.querySelectorAll('.layout-size-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.sizeVal === el.dataset.cardSize);
          });
          if (needsReorder) {
            grid.appendChild(el);
          }
        }
      });
    });
  }

  function ensureEditOverlaysOnCards() {
    document.querySelectorAll('[data-layout-card]').forEach(card => {
      if (!card.querySelector('.layout-card-edit-overlay')) {
        const cardId = card.dataset.layoutCard;
        const curSize = card.dataset.cardSize || 'standard';
        const overlay = document.createElement('div');
        overlay.className = 'layout-card-edit-overlay';
        overlay.innerHTML = `
          <span class="layout-drag-handle" title="按住鼠标拖拽此卡片到同网格其他卡片上交换位置">⠿ 拖拽</span>
          <button type="button" class="layout-move-btn" data-move-dir="-1" data-target-card="${esc(cardId)}" title="向前移动 (键盘辅助)">◀</button>
          <button type="button" class="layout-move-btn" data-move-dir="1" data-target-card="${esc(cardId)}" title="向后移动 (键盘辅助)">▶</button>
          <button type="button" class="layout-size-btn ${curSize === 'standard' ? 'active' : ''}" data-resize-card="${esc(cardId)}" data-size-val="standard">标准</button>
          <button type="button" class="layout-size-btn ${curSize === 'wide' ? 'active' : ''}" data-resize-card="${esc(cardId)}" data-size-val="wide">宽卡</button>
          <button type="button" class="layout-size-btn ${curSize === 'tall' ? 'active' : ''}" data-resize-card="${esc(cardId)}" data-size-val="tall">高卡</button>
        `;
        card.appendChild(overlay);
      }
      const handleOnly = Boolean(card.closest('.psych-viz-page, .dev-viz-page'));
      card.setAttribute('draggable', layoutEditActive && !handleOnly ? 'true' : 'false');
      card.querySelector('.layout-drag-handle')?.setAttribute('draggable', layoutEditActive && handleOnly ? 'true' : 'false');
    });
  }

  function applySavedLayoutsForCurrentView() {
    const page = currentMode === 'user' ? currentUserNav : currentDevNav;
    const key = getLayoutStorageKey(currentMode, page, currentPersonaId());
    const savedMap = readSavedLayout(key);

    document.querySelectorAll('[data-layout-grid]').forEach(grid => {
      const gridId = grid.dataset.layoutGrid;
      if (!grid.dataset.defaultOrder) {
        const defaultSpec = Array.from(grid.querySelectorAll(':scope > [data-layout-card]')).map((c, idx) => ({
          id: c.dataset.layoutCard,
          order: idx,
          size: c.dataset.cardSize || 'standard',
          visible: true
        }));
        grid.dataset.defaultOrder = JSON.stringify(defaultSpec);
      }
      const specList = (savedMap && savedMap[gridId]) ? savedMap[gridId] : JSON.parse(grid.dataset.defaultOrder);
      const currentCards = Array.from(grid.querySelectorAll(':scope > [data-layout-card]'));
      const cardMap = {};
      currentCards.forEach(c => {
        cardMap[c.dataset.layoutCard] = c;
      });
      const currentOrderStr = currentCards.map(c => c.dataset.layoutCard).join('|');
      const targetOrderStr = specList.map(item => item.id).filter(id => cardMap[id]).join('|');
      const needsReorder = currentOrderStr !== targetOrderStr;
      specList.forEach(item => {
        const el = cardMap[item.id];
        if (el) {
          el.dataset.cardSize = item.size || 'standard';
          el.querySelectorAll('.layout-size-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.sizeVal === el.dataset.cardSize);
          });
          if (needsReorder) {
            grid.appendChild(el);
          }
        }
      });
    });
  }

  function saveCurrentLayout() {
    const page = currentMode === 'user' ? currentUserNav : currentDevNav;
    const key = getLayoutStorageKey(currentMode, page, currentPersonaId());
    const payload = {};
    const rootScope = currentMode === 'user' ? document.getElementById('userShellViewport') : document.getElementById('devShellViewport');
    rootScope.querySelectorAll('[data-layout-grid]').forEach(grid => {
      const gridId = grid.dataset.layoutGrid;
      payload[gridId] = Array.from(grid.querySelectorAll(':scope > [data-layout-card]')).map((c, idx) => ({
        id: c.dataset.layoutCard,
        order: idx,
        size: c.dataset.cardSize || 'standard',
        visible: true
      }));
    });
    writeSavedLayout(key, payload);
    layoutSnapshotBeforeEdit = captureCurrentDomLayoutSnapshot();
    return { key, payload };
  }

  function cancelUnsavedLayoutEdits() {
    if (layoutSnapshotBeforeEdit) {
      applyLayoutMapToDom(layoutSnapshotBeforeEdit);
    }
    toggleLayoutEditMode(false);
    return true;
  }

  function resetCurrentLayout() {
    const page = currentMode === 'user' ? currentUserNav : currentDevNav;
    const key = getLayoutStorageKey(currentMode, page, currentPersonaId());
    deleteSavedLayout(key);
    applySavedLayoutsForCurrentView();
    layoutSnapshotBeforeEdit = captureCurrentDomLayoutSnapshot();
    return key;
  }

  function toggleLayoutEditMode(forceState) {
    const nextState = typeof forceState === 'boolean' ? forceState : !layoutEditActive;
    if (nextState && !layoutEditActive) {
      layoutSnapshotBeforeEdit = captureCurrentDomLayoutSnapshot();
    }
    layoutEditActive = nextState;
    document.body.classList.toggle('layout-edit-active', layoutEditActive);
    const bar = document.getElementById('layoutEditFloatingBar');
    if (bar) bar.hidden = !layoutEditActive;
    document.querySelectorAll('.js-toggle-layout-edit').forEach(btn => {
      btn.classList.toggle('active-edit', layoutEditActive);
    });
    const scopeLbl = document.getElementById('layoutEditScopeLabel');
    if (scopeLbl) {
      const page = currentMode === 'user' ? currentUserNav : currentDevNav;
      const pName = activeEnvelopes.characterProfile?.data?.name || '当前角色';
      scopeLbl.textContent = `布局编辑模式：${currentMode === 'user' ? '用户端' : '开发端'} · 页面 [${page}] · 角色：${pName}`;
    }
    ensureEditOverlaysOnCards();
    document.querySelectorAll('[data-layout-card]').forEach(c => {
      const handleOnly = Boolean(c.closest('.psych-viz-page, .dev-viz-page'));
      c.setAttribute('draggable', layoutEditActive && !handleOnly ? 'true' : 'false');
      c.querySelector('.layout-drag-handle')?.setAttribute('draggable', layoutEditActive && handleOnly ? 'true' : 'false');
      c.classList.remove('dragging-card', 'drop-target-hover');
    });
  }

  function swapCardsInGrid(cardIdA, cardIdB) {
    const elA = document.querySelector(`[data-layout-card="${cardIdA}"]`);
    const elB = document.querySelector(`[data-layout-card="${cardIdB}"]`);
    if (!elA || !elB || elA === elB || elA.parentElement !== elB.parentElement) return false;
    const parent = elA.parentElement;
    const nextA = elA.nextSibling;
    const nextB = elB.nextSibling;
    if (nextA === elB) parent.insertBefore(elB, elA);
    else if (nextB === elA) parent.insertBefore(elA, elB);
    else {
      parent.insertBefore(elA, nextB);
      parent.insertBefore(elB, nextA);
    }
    return true;
  }

  function resizeCard(cardId, sizeVal) {
    const el = document.querySelector(`[data-layout-card="${cardId}"]`);
    if (!el) return false;
    el.dataset.cardSize = sizeVal;
    el.querySelectorAll('.layout-size-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.sizeVal === sizeVal);
    });
    return true;
  }

  // ---------------------------------------------------------------------------
  // P2: All 24 Distinct Subpages (Zero Shared Generic Fallback!)
  // ---------------------------------------------------------------------------
  const SUBPAGE_META = {
    psych_state: { title: '心理状态', domain: 'emotion', desc: '观察此刻情绪与背景心境，理解已产生的认知记录。' },
    emo_drive: { title: '情绪与表达', domain: 'expression_drive', desc: '看看此刻想说什么、何时想说，以及有哪些尚未表达的想法。' },
    persona_analysis: { title: '人格分析', domain: 'personality', desc: '从已知的人格轮廓、价值方向与人际倾向，了解当前角色。' },
    memories: { title: '记忆', domain: 'memories', desc: '浏览留下的记忆，寻找它们之间已有的联系。' },
    experiences: { title: '经历', domain: 'experiences', desc: '回看一次互动如何被理解、回应，以及它留下了哪些记录。' },
    growth: { title: '成长', domain: 'learning', desc: '从已记录的变化与候选证据，观察人格的发展。' },
    rel_net: { title: '关系网络', domain: 'social', desc: '选择联系人或群聊，看看彼此的互动与已有关系记录。' },
    parlor: { title: '会客室', domain: 'profile', desc: '选一段会话，在这里继续交流。' },
    settings: { title: '显示设置', domain: 'connections', desc: '调整页面密度、刷新频率和布局。' },
    role_info: { title: '角色资料', domain: 'profile', desc: '查看、编辑角色介绍，或切换到另一位角色。' },
    persona_set: { title: '人格设定', domain: 'personality', desc: '查看当前倾向，核对并保存你希望调整的设定。' },
    archives: { title: '资料与档案', domain: 'profile', desc: '阅读原始资料、边界与相关依据。' },
    model_cfg: { title: '模型连接', domain: 'connections', desc: '在这里设置对话模型和 PMM 内部模型；常用设置可直接填写。' },
    pmm_sys: { title: 'PMM 系统', domain: 'decisions', desc: '设置心理处理模型，并查看每次互动中各部分的工作记录。' },
    qq_conn: { title: 'QQ 连接', domain: 'connections', desc: '连接机器人，设置允许接收的联系人与群聊。' },
    run_state: { title: '运行状态', domain: 'connections', desc: '查看各项连接和正在进行的任务。' },
    data_import: { title: '导入资料', domain: 'learning', desc: '先查看导入内容，再选择是否开始学习。' },
    distill_task: { title: '学习任务', domain: 'learning', desc: '查看进度，暂停、继续或取消已有任务。' },
    learn_record: { title: '学习记录', domain: 'learning', desc: '了解哪些内容被学习，以及哪些变化仍在等待复核。' },
    version_mgmt: { title: '版本记录', domain: 'personality', desc: '保存检查点、比较已有记录，或恢复到先前版本。' },
    behavior_event: { title: '行为与事件', domain: 'experiences', desc: '回看一次互动的理解、行动选择和最终表达。' },
    session_trace: { title: '会话追踪', domain: 'decisions', desc: '按回合查看心理处理过程与结果。' },
    logs_monitor: { title: '请求记录', domain: 'connections', desc: '查看本次浏览器会话中的请求结果和耗时。' },
    api_tools: { title: '开发工具', domain: 'connections', desc: '需要诊断时，手动选择要使用的工具。' }
  };

  // Helper to render filtered memories list without touching #inputSubpageMemSearch
  function buildMemoriesFilteredListHtml() {
    const memData = activeEnvelopes.memories?.data || {};
    const allItems = memData.items || [];
    const filtered = allItems.filter(m => {
      if (memoryKindFilter !== 'all' && m.kind !== memoryKindFilter) return false;
      if (memorySearchQuery && !String(m.content || '').toLowerCase().includes(memorySearchQuery.toLowerCase())) return false;
      return true;
    });
    if (filtered.length === 0) {
      return '<div style="color:#6E7266;font-size:12.5px;padding:8px 0;">无匹配的记忆条目（当前筛选结果为空）。</div>';
    }
    return filtered.map(m => `
      <div style="padding:8px 12px;border-radius:8px;background:rgba(255,255,255,0.72);border:1px solid rgba(155,153,140,0.22);">
        <div style="display:flex;justify-content:space-between;font-size:11.5px;color:#55594E;margin-bottom:3px;flex-wrap:wrap;gap:6px;">
          <span><strong>[${esc(m.kind)}]</strong> ID: <code>${esc(String(m.id).slice(0, 16))}</code> · 范围: <code>${esc(m.scope)}</code> · 对象: <code>${esc(m.person)}</code></span>
          <span>重要度 <strong>${Number(m.importance).toFixed(2)}</strong> · 置信度 ${Number(m.confidence).toFixed(2)} · 本地时间: ${esc(fmtLocal(m.updated_at || m.created_at))}</span>
        </div>
        <div style="font-size:13px;font-weight:600;color:#292D25;">${esc(m.content)}</div>
        ${m.evidence ? `<div style="font-size:11px;color:#686C60;margin-top:2px;">原文依据：${esc(m.evidence)}</div>` : ''}
      </div>
    `).join('');
  }

  // Helper to render Parlor chat messages list strictly from GET /api/messages?session=<parlorSessionId>
  function buildParlorMessagesListHtml() {
    const charName = activeEnvelopes.characterProfile?.data?.name || '角色';
    if (!parlorSessionId) {
      return '<div style="color:#6E7266;font-size:12.5px;">当前尚未创建或选择会话。请点击上方「+ 新建会话」或在下方直接发送消息自动创建会话。</div>';
    }
    const msgs = parlorMessagesBySession[parlorSessionId] || [];
    if (msgs.length === 0) {
      return `<div style="color:#6E7266;font-size:12.5px;">会话 <code>${esc(parlorSessionId)}</code> 当前尚无聊天记录 (<code>GET /api/messages?session=${esc(parlorSessionId)}</code> 返回 0 条)。</div>`;
    }
    return msgs.map(m => {
      const isUser = m.role === 'user';
      return `
        <div class="parlor-msg-row ${isUser ? 'user-msg' : 'assistant-msg'}" style="padding:8px 12px;border-radius:10px;background:${isUser ? 'rgba(126,152,96,0.16)' : 'rgba(255,255,255,0.88)'};border:1px solid rgba(140,148,124,0.28);align-self:${isUser ? 'flex-end' : 'flex-start'};max-width:88%;">
          <div style="font-size:11px;color:#5A5E52;margin-bottom:3px;display:flex;justify-content:space-between;gap:12px;">
            <strong>${isUser ? '你 (User)' : esc(charName) + ' (Assistant)'}</strong>
            <span>${esc(m.display_time || fmtLocal(m.created_at))} ${m.turn_id ? `· Turn:${esc(String(m.turn_id).slice(0, 8))}` : ''}</span>
          </div>
          <div style="font-size:13px;color:#262A22;white-space:pre-wrap;word-break:break-word;">${esc(m.content)}</div>
        </div>
      `;
    }).join('');
  }

  function visualContext() {
    return { personaId: currentPersonaId(), source: dataSourceMode, scope: activeScope, sessionId: parlorSessionId, epoch: contextEpoch };
  }
  function sampleServices() {
    const epoch=contextEpoch,owner=currentPersonaId(),mode=currentMode,nav=currentMode==='developer'?currentDevNav:currentUserNav;
    return {adapter:pmmAdapter,context:visualContext(),render:()=>{renderUserHomeDynamicCards();renderActiveSubpage();},
      isCurrent:()=>epoch===contextEpoch&&owner===currentPersonaId()&&dataSourceMode==='live'&&mode===currentMode&&nav===(currentMode==='developer'?currentDevNav:currentUserNav)};
  }
  function parlorContext() { return { ...visualContext(), sessionId: parlorSessionId }; }
  function refreshParlorView() {
    if (currentMode === 'user' && currentUserNav === 'parlor') renderSubpage('user', 'parlor', { preserveSubpageDom: true });
  }
  async function readParlorMessages() {
    if (!parlorSessionId || dataSourceMode !== 'live') return;
    const ctx = parlorContext(), result = await pmmAdapter.fetchSessionMessages(ctx.sessionId);
    if (ctx.epoch !== contextEpoch || ctx.personaId !== currentPersonaId() || ctx.source !== dataSourceMode) return;
    window.ParlorView.observeMessages(ctx, result);
    if (result.ok) parlorMessagesBySession[ctx.sessionId] = result.messages;
    refreshParlorView();
  }
  async function runParlorChat(resume = false) {
    let ctx = parlorContext(), t = window.ParlorView.thread(ctx);
    const samePersona = () => ctx.epoch === contextEpoch && ctx.personaId === currentPersonaId() && ctx.source === dataSourceMode;
    if (t.active) return;
    const feedback = document.getElementById('parlorSendStatus');
    const text = (document.getElementById('inputParlorMessage')?.value ?? t.draft).trim();
    if (!resume && !text) { if (feedback) feedback.textContent = '请先写下要发送的内容。'; return; }
    if (!resume && t.job_id && ['pending', 'timeout', 'observation_paused'].includes(t.status)) return;
    if (!guardWrite('parlor_send_chat', { endpoint: resume ? '/api/jobs' : '/api/chat', feedbackEl: feedback }).allowed) return;
    if (resume && !t.job_id) return;
    const started = performance.now();
    if (!resume) t.draft = document.getElementById('inputParlorMessage')?.value ?? t.draft;
    const submittedDraft = t.draft;
    t.active = true; t.status = resume ? 'running' : 'submitting'; t.notice = ''; t.error = null;
    parlorJobState = t; refreshParlorView();
    try {
      if (!ctx.sessionId) {
        const result = await pmmAdapter.createSession();
        if (!samePersona()) { t.status = 'observation_paused'; return; }
        if (!result.ok || !result.session_id) throw new Error(result.error || '无法创建会话');
        t.active = false; t.status = 'idle'; t.draft = '';
        const stillSelected = parlorSessionId === ctx.sessionId;
        ctx = { ...ctx, sessionId: result.session_id };
        if (stillSelected) { parlorSessionId = ctx.sessionId; parlorSessionsByPersona[ctx.personaId] = ctx.sessionId; }
        t = window.ParlorView.thread(ctx); Object.assign(t, { draft: submittedDraft, active: true, status: 'submitting', registered: true }); parlorJobState = t;
        refreshParlorView();
      }
      if (!resume) {
        if (!t.attempt || t.attempt.text !== text) t.attempt = { text, eventId: `web_evt_${Date.now()}_${Math.random().toString(36).slice(2, 9)}` };
        const result = await pmmAdapter.sendChatMessage(ctx.sessionId, text, t.attempt.eventId);
        t.submitEnvelope = result.envelope;
        if (!result.ok || !result.job_id) throw new Error(result.error || '消息提交未取得任务结果');
        t.job_id = result.job_id; t.submittedDraft = submittedDraft; t.status = 'queued';
        if (!samePersona()) { t.status = 'observation_paused'; return; }
        refreshParlorView();
      }
      const result = await pmmAdapter.pollJobUntilDone(t.job_id, (job, envelope) => {
        t.job = job; t.status = job.status; t.phase = job.phase; t.jobEnvelope = envelope;
        if (samePersona()) refreshParlorView();
      }, 25000, samePersona);
      t.jobEnvelope = result.envelope; t.job = result.job || t.job;
      if (!result.ok) {
        t.error = result.error;
        t.status = result.status === 'observation_paused' ? 'observation_paused' : result.status === 'timeout' ? 'timeout' : result.job ? 'failed' : 'pending';
        return;
      }
      t.status = 'done';
      if (t.draft === (t.submittedDraft ?? submittedDraft)) t.draft = '';
      t.attempt = null;
      const messages = await pmmAdapter.fetchSessionMessages(ctx.sessionId);
      if (!samePersona()) return;
      window.ParlorView.observeMessages(ctx, messages);
      if (messages.ok) parlorMessagesBySession[ctx.sessionId] = messages.messages;
      else t.notice = '处理已完成，但消息历史暂时读取失败；可点击刷新历史。';
      await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: true, skipSessionMessages: true });
    } catch (error) {
      t.status = 'failed'; t.error = error.message || String(error); t.notice = `处理失败，草稿已保留：${t.error}`;
    } finally {
      t.active = false; t.elapsed_ms = Math.round(performance.now() - started);
      if (samePersona()) { parlorJobState = window.ParlorView.thread(parlorContext()); refreshParlorView(); }
    }
  }
  function buildDomainSpecificCards(mode, navKey) {
    if (['model_cfg', 'qq_conn'].includes(navKey)) return window.ModelSettings.cards(activeEnvelopes, mode, navKey);
    const cards = buildExistingDomainCards(mode, navKey);
    if (mode === 'developer' && ['distill_task', 'learn_record'].includes(navKey)) cards.unshift(window.LifeViews.learningCard(activeEnvelopes, mode));
    if (mode !== 'developer' && navKey !== 'settings') return cards;
    const enhanced = window.DeveloperViews.enhance(navKey, cards, activeEnvelopes, {
      ...visualContext(), callLog: pmmAdapter.callLog, faultOverrides: pmmAdapter.endpointFaultOverrides,
      learningPreview: pendingLearningPreview, getLearningPreview: () => pendingLearningPreview,
      polling: { summary: pollingScheduler.getStatusSummary(), enabled: pollingScheduler.enabled }
    });
    if (mode === 'developer' && ['logs_monitor', 'run_state'].includes(navKey)) enhanced.push(...window.TokenView.cards(visualContext()));
    if (mode === 'developer' && navKey === 'run_state') enhanced.push(window.SchedulerView.card(visualContext()));
    if (mode === 'developer' && navKey === 'api_tools') enhanced.push(window.ResearchView.card(visualContext()));
    return enhanced;
  }
  function renderActiveSubpage() {
    renderSubpage(currentMode, currentMode === 'developer' ? currentDevNav : currentUserNav, { preserveSubpageDom: true });
  }
  function connectionServices() {
    const roleKey = role => role === 'general' ? 'general' : role === 'A' ? 'pmm' : role === 'qq' ? 'qq' : null;
    return {
      guard: feedbackEl => {
        if (!guardWrite('connection_save', { endpoint: '/api/config', feedbackEl }).allowed) return false;
        if (!['success', 'empty'].includes(activeEnvelopes.characterProfile?.status)) { feedbackEl.textContent = '请先等待当前角色的配置读取完成。'; return false; }
        return true;
      },
      context: () => `${currentPersonaId()}:${dataSourceMode}:${contextEpoch}`,
      post: (endpoint, body, timeout) => pmmAdapter.postJson(endpoint, body, timeout),
      invalidate: role => { const key = roleKey(role); if (key) pmmAdapter.connectionAdapter.recordProbeResult(key, null, '配置已修改'); },
      probed: (role, ok) => { const key = roleKey(role); if (key) pmmAdapter.connectionAdapter.recordProbeResult(key, ok, ok ? '连接检查通过' : '连接检查未通过'); },
      refresh: () => tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: true })
    };
  }
  async function selectRelationshipScope(scope) {
    const scopes = activeEnvelopes.socialGraph?.data?.available_scopes || [];
    if (dataSourceMode !== 'live' || !scope || scope === '*' || !scopes.includes(scope)) return;
    window.PsychViz.close();
    activeScope = scope;
    await tryHydrateFromLiveServer(scope, { preserveSubpageDom: false });
  }
  function buildExistingDomainCards(mode, navKey) {
    const env = activeEnvelopes;
    const isMock = env.mode === 'mock';
    const charData = env.characterProfile?.data || {};
    const persData = env.personality?.data || {};
    const emoData = env.emotion?.data || {};
    const driveData = env.expressionDrive?.data || {};
    const memData = env.memories?.data || {};
    const expData = env.experiences?.data || {};
    const learnData = env.learning?.data || {};
    const socialData = env.socialGraph?.data || {};
    const connData = env.connections?.data || {};
    const decData = env.decisions?.data || {};
    if (navKey === 'emo_drive') return window.DriveView.cards(env, mode, visualContext());
    if (mode === 'user' && navKey === 'memories') return window.MemoryGraphView.cards(env, mode, visualContext());
    if (mode === 'user' && navKey === 'experiences') return window.LifeViews.experienceCards(env, mode, visualContext());
    if (mode === 'user' && navKey === 'growth') return window.LifeViews.growthCards(env, mode, visualContext());
    if (navKey === 'rel_net') return window.RelationView.cards(env, mode, visualContext());
    if (mode === 'user' && navKey === 'parlor') return window.ParlorView.cards(env, mode, parlorContext(), parlorMessagesBySession[parlorSessionId] || []);

    // -------------------------------------------------------------------------
    // 1. psych_state: 当前心理状态（快慢层结构 + 认知状态 + 24类目录）
    // -------------------------------------------------------------------------
    if (navKey === 'psych_state') {
      return [...window.EmotionView.cards(env, mode), window.SampleView.card(visualContext())];
    }

    // -------------------------------------------------------------------------
    // 2. emo_drive: 情绪历史与表达欲状态分区 + 推进操作 + PLANNED 动机登记 (P0-03 & P0-04)
    // -------------------------------------------------------------------------
    if (navKey === 'emo_drive') {
      const motives = driveData.unfinished_motives || [];
      const pts = emoData.events_points || [];
      return [
        {
          id: `${mode}_drive_c1`,
          domain: 'expression_drive',
          title: 'v2.8.3 表达欲动力学状态与基于现有状态推进',
          size: 'wide',
          body: `
            <div data-readonly-slot="drive_metrics">
              ${renderFaultBannerIfAny('expression_drive', mode === 'developer') || `
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:10px;">
                  <div style="padding:10px;border-radius:10px;background:rgba(255,255,255,0.65);">
                    <div style="font-size:11px;color:#666A5E;">活跃表达流 (has_active_stream)</div>
                    <strong style="font-size:15px;">${driveData.has_active_stream ? `是 (${driveData.streams_count}条流)` : '否 (streams=[])'}</strong>
                  </div>
                  <div style="padding:10px;border-radius:10px;background:rgba(255,255,255,0.65);">
                    <div style="font-size:11px;color:#666A5E;">Activation (激活度)</div>
                    <strong style="font-size:15px;">${driveData.activation != null ? (Number(driveData.activation) * 100).toFixed(1) + '%' : 'null (无活跃流)'}</strong>
                  </div>
                  <div style="padding:10px;border-radius:10px;background:rgba(255,255,255,0.65);">
                    <div style="font-size:11px;color:#666A5E;">Urgency / Persistence</div>
                    <strong style="font-size:14px;">U: ${driveData.urgency != null ? (Number(driveData.urgency) * 100).toFixed(1) + '%' : 'null'} / P: ${driveData.persistence != null ? (Number(driveData.persistence) * 100).toFixed(1) + '%' : 'null'}</strong>
                  </div>
                  <div style="padding:10px;border-radius:10px;background:rgba(255,255,255,0.65);">
                    <div style="font-size:11px;color:#666A5E;">话轮意图 & 校准状态</div>
                    <strong style="font-size:13px;">${esc(driveData.intent || 'null')} · <code>${esc(driveData.calibration_status)}</code></strong>
                  </div>
                </div>
              `}
            </div>
            <div style="padding:10px 12px;border-radius:10px;background:rgba(126,152,96,0.12);border:1px solid rgba(126,152,96,0.3);margin-top:8px;">
              <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
                <div>
                  <strong>基于现有状态推进表达欲</strong>
                  <div style="font-size:11.5px;color:#52564A;">仅传递原版路由真实支持的 <code>{ scope, person, session_id, commit: true }</code>，绝不夹带未实现的新增动机参数。</div>
                </div>
                <button type="button" class="layout-bar-btn save" id="btnTriggerDriveAdvance">基于现有状态推进表达欲</button>
              </div>
              <div id="driveAdvanceFeedback" style="font-size:11.5px;color:#2E4418;margin-top:6px;"></div>
            </div>
          `
        },
        {
          id: `${mode}_drive_c2`,
          domain: 'expression_drive',
          title: `未完成内部表达动机池 (unfinished_motives: ${motives.length} 条) & 受控新建动机入口`,
          body: `
            <div data-readonly-slot="drive_motives_list" style="font-size:12px;display:flex;flex-direction:column;gap:8px;max-height:150px;overflow-y:auto;margin-bottom:10px;">
              ${motives.length === 0
                ? '<div style="color:#6E7266;">当前 <code>unfinished_motives = []</code>（0 条挂起动机）。动机由真实对话回合事件自动生成。</div>'
                : motives.map(m => `
                  <div style="padding:8px 10px;border-radius:8px;background:rgba(255,255,255,0.68);border:1px solid rgba(155,153,140,0.25);">
                    <div><strong>ID: <code>${esc(m.motive_id)}</code></strong> · 状态: <span class="envelope-badge live">${esc(m.status)}</span> · 激活度: <strong>${(Number(m.activation || 0) * 100).toFixed(1)}%</strong></div>
                    <div>话题：<strong>${esc(m.content_anchor?.topic || m.topic || '')}</strong> · 目标：${esc(m.intended_expression?.intended_goal || m.intended_goal || '')}</div>
                  </div>
                `).join('')}
            </div>
            <div style="padding:8px 10px;border-radius:8px;background:rgba(130,134,124,0.12);border:1px dashed rgba(130,134,124,0.45);">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                <strong style="font-size:12px;">手工登记新表达动机</strong>
                <span class="envelope-badge unavailable">PLANNED / 暂未接入 (Backlog F-06)</span>
              </div>
              <div style="display:flex;gap:6px;align-items:center;">
                <input type="text" id="inputDriveTopic" value="" placeholder="原版 v2.8.3 暂未提供独立手工创建动机 API..." style="flex:1;padding:5px 8px;border-radius:6px;border:1px solid rgba(130,136,118,0.35);font-size:11.5px;" />
                <button type="button" class="mini-tab-btn" id="btnPlannedRegisterMotive">登记动机 (暂未接入)</button>
              </div>
              <div id="plannedMotiveNotice" style="font-size:11px;color:#686C60;margin-top:4px;">说明：原版后端仅在对话回合或存在未回应历史记录时自动生成动机，不支持前端直接注入任意动机话题。</div>
            </div>
          `
        },
        {
          id: `${mode}_drive_c3`,
          domain: 'emotion_trend',
          title: `离散情绪历史轨迹点 (${pts.length} 点) vs 24h 连续曲线状态`,
          body: `
            <div data-readonly-slot="drive_trajectory" style="font-size:12px;line-height:1.65;">
              <div style="margin-bottom:6px;">24h / 7d 连续采样曲线状态：<span class="envelope-badge unavailable">按需开启 · 在研究工作区读取已记录的采样点</span></div>
              ${pts.length === 0
                ? '<div style="color:#6E7266;">当前无离散轨迹点 (<code>trajectory=[]</code>)，绝不捏造趋势曲线。</div>'
                : pts.slice(0, 6).map(p => `<div style="padding:3px 0;border-bottom:1px dashed rgba(155,153,140,0.2);">● #${p.index} ${esc(p.t)} (${esc(p.time_str)}) → V:${Number(p.v).toFixed(3)}, A:${Number(p.a).toFixed(3)}</div>`).join('')}
            </div>
          `
        }
      ];
    }

    // -------------------------------------------------------------------------
    // 3. persona_analysis: 用户端只读 68 构念分组、HEXACO、Schwartz 19 价值与人际二维坐标
    // -------------------------------------------------------------------------
    if (mode === 'user' && navKey === 'persona_analysis') {
      return window.PersonalityView.cards(env, mode);
    }

    // -------------------------------------------------------------------------
    // 4. memories: 记忆列表、无损关键词搜索、类型筛选与关联图 (P1-02)
    // -------------------------------------------------------------------------
    if (navKey === 'memories') {
      const allItems = memData.items || [];
      const graphNodes = memData.relation_graph?.nodes || [];
      const graphEdges = memData.relation_graph?.edges || [];
      return [
        {
          id: `${mode}_mem_c1`,
          domain: 'memories',
          title: `SQLite 长期记忆库检索与分类浏览 (共 ${allItems.length} 条)`,
          size: 'wide',
          body: renderFaultBannerIfAny('memories', mode === 'developer') || `
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;">
              ${['all', 'episode', 'fact', 'preference', 'boundary'].map(k => `
                <button type="button" class="mini-tab-btn ${memoryKindFilter === k ? 'active' : ''}" data-mem-filter="${k}">
                  ${k === 'all' ? '全部' : k} (${k === 'all' ? allItems.length : (memData.by_kind_counts?.[k] ?? 0)})
                </button>
              `).join('')}
              <input type="search" id="inputSubpageMemSearch" placeholder="输入关键词实时过滤记忆（连续输入不丢失焦点）..." value="${esc(memorySearchQuery)}" style="flex:1;min-width:180px;padding:5px 10px;border-radius:8px;border:1px solid rgba(130,136,118,0.4);font-size:12px;"/>
            </div>
            <div id="memoriesFilteredListBox" data-readonly-slot="memories_list" style="display:flex;flex-direction:column;gap:8px;max-height:280px;overflow-y:auto;">
              ${buildMemoriesFilteredListHtml()}
            </div>
          `
        },
        {
          id: `${mode}_mem_c2`,
          domain: 'memories',
          title: `记忆关联图谱 (memory_relation_graph: ${graphNodes.length} 节点 / ${graphEdges.length} 边)`,
          body: `
            <div data-readonly-slot="memories_graph" style="font-size:12px;line-height:1.7;">
              <div>向量 Embedding 语义相似度检索：<span class="envelope-badge unavailable">UNAVAILABLE (见 Backlog F-05)</span></div>
              <div style="margin-top:6px;">真实存储节点：<strong>${graphNodes.length}</strong> 个，共现/证据关联边：<strong>${graphEdges.length}</strong> 条（区分真实原文引用与可视化布局）。</div>
              <div style="margin-top:8px;max-height:160px;overflow-y:auto;">
                ${graphNodes.slice(0, 10).map(n => `<div style="padding:3px 0;border-bottom:1px dashed rgba(155,153,140,0.2);">● [${esc(n.kind || 'memory')}] ${esc(n.label || n.id)}</div>`).join('') || '<div style="color:#6E7266;">当前暂无记忆关联图节点</div>'}
              </div>
            </div>
          `
        }
      ];
    }

    // -------------------------------------------------------------------------
    // 5. experiences: 经历时间线 (严格对应 /api/de/turns，区别于会客室消息)
    // -------------------------------------------------------------------------
    if (navKey === 'experiences') {
      const items = expData.items || [];
      return [
        {
          id: `${mode}_exp_c1`,
          domain: 'experiences',
          title: `认知评价与联合表达经历时间线`,
          size: 'wide',
          body: `<div data-readonly-slot="experiences_list">${renderFaultBannerIfAny('experiences', false) || `
            <div style="font-size:12px;color:#55594E;margin-bottom:8px;">
              说明：本页展示经由 PMM 认知评价归档的回合经历事件（<code>/api/de/turns</code>），包含事件引用、情绪效价与表达策略；会客室原始聊天气泡请前往「会客室」查看（<code>/api/messages</code>）。
            </div>
            <div style="display:flex;flex-direction:column;gap:8px;max-height:300px;overflow-y:auto;">
              ${items.length === 0 ? '<div style="color:#6E7266;font-size:12.5px;">当前数据库尚无已完成评价的对话回合 (rows=0)。</div>' : items.map(it => `
                <div style="padding:10px 12px;border-radius:10px;background:rgba(255,255,255,0.72);border:1px solid rgba(155,153,140,0.22);">
                  <div style="display:flex;justify-content:space-between;font-size:11.5px;color:#55594E;margin-bottom:4px;">
                    <span>事件 Turn ID: <code>${esc(it.id)}</code> · 作用域: <code>${esc(it.scope)}</code></span>
                    <span><strong style="color:#4F6835;">${esc(it.emo)}</strong> · 本地时间: ${esc(fmtLocal(it.time))}</span>
                  </div>
                  <div style="font-size:13px;"><strong>触发事件原文：</strong>「${esc(it.title)}」</div>
                  <div style="font-size:12.5px;color:#3E5626;margin-top:3px;"><strong>联合表达策略 (${esc(it.strategy)})：</strong>「${esc(it.reply)}」 <small>[回执: ${esc(it.delivery)}]</small></div>
                </div>
              `).join('')}
            </div>
          `}</div>`
        },
        {
          id: `${mode}_exp_c2`,
          domain: 'experiences',
          title: '跨月自传式人生阶段聚合表',
          body: `
            <div class="card-state-banner unavailable">
              <div>
                <strong>UNAVAILABLE · 长期自传式人生章节表尚未实现 (Backlog F-07)</strong>
                <div>原版 v2.8.3 后端仅在 <code>/api/de/turns</code> 保存逐轮评价记录，未建立跨月人生阶段汇总表。</div>
              </div>
            </div>
          `
        }
      ];
    }

    // -------------------------------------------------------------------------
    // 6. growth: 用户端个体成长总览 (构念晋升历史 promotion_history + 学习统计)
    // -------------------------------------------------------------------------
    if (navKey === 'growth') {
      const promo = persData.promotion_history || [];
      const acts = learnData.activities || [];
      return [
        {
          id: `${mode}_growth_c1`,
          domain: 'personality',
          title: `构念变更与设定晋升历史 (promotion_history · 共 ${promo.length} 条记录)`,
          size: 'wide',
          body: `
            <div data-readonly-slot="growth_promotions" style="font-size:12px;max-height:260px;overflow-y:auto;display:flex;flex-direction:column;gap:8px;">
              ${promo.length === 0
                ? '<div style="color:#6E7266;">当前角色尚无构念设定或晋升变更记录 (promotion_history=[])。</div>'
                : promo.slice().reverse().map(p => `
                  <div style="padding:8px 12px;border-radius:8px;background:rgba(255,255,255,0.72);border:1px solid rgba(155,153,140,0.22);">
                    <div style="display:flex;justify-content:space-between;font-size:11.5px;color:#55594E;">
                      <strong>构念: <code>${esc(p.feature_id)}</code> (v${esc(p.trait_version)})</strong>
                      <span>方式: <code>${esc(p.method)}</code> · ${esc(fmtLocal(p.at))}</span>
                    </div>
                    <div style="margin-top:3px;">变更前: <code>${p.before?.estimate != null ? Number(p.before.estimate).toFixed(2) : 'null'}</code> (${esc(p.before?.source_type || 'unknown')}) → <strong>变更后: <code>${p.after?.estimate != null ? Number(p.after.estimate).toFixed(2) : 'null'}</code> (${esc(sourceTypeBadgeLabel(p.after?.source_type))})</strong></div>
                  </div>
                `).join('')}
            </div>
          `
        },
        {
          id: `${mode}_growth_c2`,
          domain: 'learning',
          title: `成长学习活动摘要 (${acts.length} 条活动) & 长期成长趋势预留`,
          body: `
            <div data-readonly-slot="growth_summary" style="font-size:12px;line-height:1.7;">
              <div>● 累计学习任务：<strong>${learnData.total_jobs ?? 0}</strong> 项 · 已处理原文游标：<strong>${learnData.processed_sources ?? 0}</strong> 条</div>
              <div>● 待复核特质候选：<strong>${(learnData.candidates || []).length}</strong> 项</div>
              <div style="margin-top:8px;" class="card-state-banner unavailable">
                <div>
                  <strong>UNAVAILABLE · 跨周期纵向心理成长曲线待接入</strong>
                  <div>原版 <code>/api/pmm28/longitudinal</code> 当前为预留结构 (revision=0)，无纵向时间序列曲线。</div>
                </div>
              </div>
            </div>
          `
        }
      ];
    }

    // -------------------------------------------------------------------------
    // 7. rel_net: 关系网络与范围切换
    // -------------------------------------------------------------------------
    if (navKey === 'rel_net') {
      const nodes = socialData.nodes || [];
      const edges = socialData.edges || [];
      const claims = socialData.claims || [];
      const people = socialData.people || [];
      const rels = socialData.relations || [];
      return [
        {
          id: `${mode}_soc_c1`,
          domain: 'social',
          title: `社会关系网络与人物档案})`,
          size: 'wide',
          body: renderFaultBannerIfAny('social', mode === 'developer') || `
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:8px;">
              <span data-readonly-slot="social_summary_bar">当前必选会话范围 (Scope)：<code>${esc(socialData.scope || activeScope)}</code> · 实测节点 <strong>${nodes.length}</strong> 个 · 有向边 <strong>${edges.length}</strong> 条 · 关系陈述 <strong>${claims.length}</strong> 条</span>
              <div style="display:flex;gap:6px;">
                <input type="text" id="inputSocialScope" value="${esc(activeScope)}" placeholder="输入范围如 private:web:owner" style="padding:4px 8px;border-radius:6px;border:1px solid rgba(130,136,118,0.4);font-size:12px;"/>
                <button type="button" class="mini-tab-btn active" id="btnSwitchSocialScope">切换范围查询</button>
              </div>
            </div>
            <div data-readonly-slot="social_panels" style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
              <div style="padding:10px;border-radius:8px;background:rgba(255,255,255,0.68);">
                <strong>范围内人物档案</strong>
                <div style="font-size:12px;margin-top:6px;max-height:170px;overflow-y:auto;">
                  ${people.map(p => `<div style="padding:3px 0;border-bottom:1px dashed rgba(155,153,140,0.2);">● <strong>${esc(p.display_name || p.person_id || p.id)}</strong> (互动 ${esc(p.interaction_count ?? p.count ?? 0)} 次)</div>`).join('') || '<div style="color:#6E7266;">当前范围暂无已登记人物</div>'}
                </div>
              </div>
              <div style="padding:10px;border-radius:8px;background:rgba(255,255,255,0.68);">
                <strong>双边关系亲密度与信任度</strong>
                <div style="font-size:12px;margin-top:6px;max-height:170px;overflow-y:auto;">
                  ${rels.map(r => {
                    const d = r.data || r;
                    return `<div style="padding:3px 0;border-bottom:1px dashed rgba(155,153,140,0.2);">● <code>${esc(r.id || r.target_id || r.person || r.scope)}</code>：信任度 ${Number(d.trust ?? 0.5).toFixed(2)} · 熟悉度 ${Number(d.familiarity ?? 0).toFixed(2)}</div>`;
                  }).join('') || '<div style="color:#6E7266;">当前暂无双边关系评估记录</div>'}
                </div>
              </div>
            </div>
          `
        }
      ];
    }

    // -------------------------------------------------------------------------
    // 8. parlor: 会客室 (P0-01 真实会话创建、消息列表隔离、POST /api/chat {session_id, text} 与 /api/jobs/<id> 轮询)
    // -------------------------------------------------------------------------
    if (navKey === 'parlor') {
      const webSessions = (charData.sessions || []).filter(s => s && s.scope === 'private:web:owner');
      const hasCurrentInList = webSessions.some(s => s.id === parlorSessionId);
      const sessionOptions = [
        ...(parlorSessionId && !hasCurrentInList ? [{ id: parlorSessionId, created_at: null }] : []),
        ...webSessions
      ];
      return [
        {
          id: `${mode}_parlor_c1`,
          domain: 'experiences',
          title: `会客室实时对话 (${esc(charData.name)} · 独立会话隔离与真实异步作业闭环)`,
          size: 'wide',
          body: `
            <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:10px;padding:8px 12px;border-radius:10px;background:rgba(126,152,96,0.12);">
              <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                <strong style="font-size:12.5px;">当前会话 (Session)：</strong>
                <select id="selectParlorSession" style="padding:5px 10px;border-radius:6px;border:1px solid rgba(120,130,105,0.45);font-size:12px;">
                  ${sessionOptions.length === 0
                    ? '<option value="">（尚无会话，点击右侧新建或直接发送消息）</option>'
                    : sessionOptions.map(s => `<option value="${esc(s.id)}" ${s.id === parlorSessionId ? 'selected' : ''}>会话 ${esc(String(s.id).slice(0, 12))} (${esc(s.scope || 'private:web:owner')})</option>`).join('')}
                </select>
                <span class="envelope-badge live" id="parlorSessionBadge">${parlorSessionId ? `ID: ${esc(String(parlorSessionId).slice(0, 10))}` : '待创建'}</span>
              </div>
              <div style="display:flex;gap:6px;">
                <button type="button" class="mini-tab-btn active" id="btnNewParlorSession">+ 新建独立会话</button>
                <button type="button" class="mini-tab-btn" id="btnRefreshParlorMessages">刷新本会话历史</button>
              </div>
            </div>

            <div id="parlorChatHistoryBox" data-readonly-slot="parlor_messages" style="min-height:160px;max-height:250px;overflow-y:auto;padding:12px;border-radius:10px;background:rgba(255,255,255,0.75);border:1px solid rgba(155,153,140,0.26);display:flex;flex-direction:column;gap:8px;margin-bottom:10px;">
              ${buildParlorMessagesListHtml()}
            </div>

            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
              <input type="text" id="inputParlorMessage" value="${isMock ? 'MOCK 演示问候' : ''}" placeholder="输入要发送给角色的真实对话内容 (LIVE 模式下默认空白，绝不预填演示文本)..." style="flex:1;min-width:240px;padding:8px 12px;border-radius:8px;border:1px solid rgba(130,136,118,0.5);font-size:13px;" ${parlorJobState.active ? 'disabled' : ''}/>
              <button type="button" class="mini-tab-btn" id="btnFillParlorDemoText" title="显式填入一句测试问候语">填入测试示例</button>
              <button type="button" class="layout-bar-btn save" id="btnSendParlorChat" ${parlorJobState.active ? 'disabled' : ''}>
                ${parlorJobState.active ? `处理中 (${esc(parlorJobState.phase || parlorJobState.status)})...` : '发送对话'}
              </button>
            </div>
            <div id="parlorSendStatus" style="font-size:12px;color:#3E5626;margin-top:6px;min-height:18px;"></div>
          `
        }
      ];
    }

    // -------------------------------------------------------------------------
    // 9. settings: 本地界面设置与刷新策略（严格与角色人格设定分离）
    // -------------------------------------------------------------------------
    if (navKey === 'settings') {
      return [
        {
          id: `${mode}_settings_c1`,
          domain: 'connections',
          title: '本地 UI 刷新策略与低频轮询器设置 (仅影响浏览器端，不修改后端人格数据)',
          size: 'wide',
          body: `
            <div style="font-size:12.5px;line-height:1.8;">
              <div data-readonly-slot="polling_status"><strong>当前轮询状态：</strong>${esc(pollingScheduler.getStatusSummary())}</div>
              <div style="font-size:12px;color:#55594E;margin-top:4px;">说明：轮询采用无损增量更新策略（P1-02），在您编辑任何输入框或搜索框时绝不重建表单 DOM 或打断焦点。</div>
              <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;">
                <button type="button" class="mini-tab-btn ${!pollingScheduler.enabled ? 'active' : ''}" data-poll-ms="0">手动刷新 (关闭定时轮询)</button>
                <button type="button" class="mini-tab-btn ${pollingScheduler.enabled && pollingScheduler.baseIntervalMs === 10000 ? 'active' : ''}" data-poll-ms="10000">10s 低频轮询</button>
                <button type="button" class="mini-tab-btn ${pollingScheduler.enabled && pollingScheduler.baseIntervalMs === 15000 ? 'active' : ''}" data-poll-ms="15000">15s 低频轮询 (默认)</button>
                <button type="button" class="mini-tab-btn ${pollingScheduler.enabled && pollingScheduler.baseIntervalMs === 30000 ? 'active' : ''}" data-poll-ms="30000">30s 低频轮询</button>
                <button type="button" class="mini-tab-btn ${pollingScheduler.enabled && pollingScheduler.baseIntervalMs === 60000 ? 'active' : ''}" data-poll-ms="60000">60s 低频轮询</button>
              </div>
            </div>
          `
        },
        {
          id: `${mode}_settings_c2`,
          domain: 'connections',
          title: '本地卡片布局与模式偏好管理 (localStorage)',
          body: `
            <div style="font-size:12px;line-height:1.8;">
              <div>当前界面模式：<code>${esc(currentMode)}</code> · 数据源模式：<code>${esc(dataSourceMode)}</code></div>
              <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;">
                <button type="button" class="layout-bar-btn reset" id="btnClearAllSavedLayouts">清除全部本地保存的卡片布局</button>
                <button type="button" class="layout-bar-btn" data-dev-nav="role_info">前往角色档案设定 (开发端) →</button>
              </div>
              <div id="localSettingsFeedback" style="font-size:11.5px;color:#48632B;margin-top:6px;"></div>
            </div>
          `
        }
      ];
    }

    // -------------------------------------------------------------------------
    // 10. role_info: 角色身份、主体列表切换与角色资料编辑
    // -------------------------------------------------------------------------
    if (navKey === 'role_info') {
      const catalog = charData.personas_catalog || [];
      return [
        {
          id: `${mode}_role_c1`,
          domain: 'profile',
          title: `当前角色身份与资料编辑 (${esc(charData.name)} · revision ${esc(charData.revision ?? 0)})`,
          size: 'wide',
          body: `
            <div data-readonly-slot="role_header" style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;font-size:12px;padding:8px 10px;border-radius:8px;background:rgba(255,255,255,0.65);">
              <div>主体 ID：<code>${esc(charData.id)}</code> · 档案修订号 (expected_revision)：<code>${esc(charData.revision ?? 0)}</code></div>
              <div>特质版本：<code>v${esc(persData.version ?? 0)}</code> · 业务更新：<code>${esc(fmtLocal(env.characterProfile?.updated_at))}</code></div>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:8px;">
              <div>
                <label style="font-size:11.5px;font-weight:600;display:block;margin-bottom:3px;">角色名称 (name)：</label>
                <input type="text" id="inputRoleNameEdit" value="${esc(charData.name || '')}" style="width:100%;padding:6px 10px;border-radius:6px;border:1px solid rgba(130,136,118,0.45);font-size:12.5px;"/>
              </div>
              <div>
                <label style="font-size:11.5px;font-weight:600;display:block;margin-bottom:3px;">自称代词 (self_reference)：</label>
                <input type="text" id="inputRoleSelfRefEdit" value="${esc(charData.character?.self_reference || '我')}" style="width:100%;padding:6px 10px;border-radius:6px;border:1px solid rgba(130,136,118,0.45);font-size:12.5px;"/>
              </div>
            </div>
            <div style="margin-bottom:8px;">
              <label style="font-size:11.5px;font-weight:600;display:block;margin-bottom:3px;">初始性格概述 (initial_personality)：</label>
              <input type="text" id="inputRoleInitPersEdit" value="${esc(charData.character?.initial_personality || '')}" placeholder="输入角色性格特征概述..." style="width:100%;padding:6px 10px;border-radius:6px;border:1px solid rgba(130,136,118,0.45);font-size:12.5px;"/>
            </div>
            <div style="margin-bottom:10px;">
              <label style="font-size:11.5px;font-weight:600;display:block;margin-bottom:3px;">核心背景设定 (seed)：</label>
              <input type="text" id="inputRoleSeedEdit" value="${esc(charData.seed || '')}" style="width:100%;padding:6px 10px;border-radius:6px;border:1px solid rgba(130,136,118,0.45);font-size:12.5px;"/>
            </div>
            <div style="display:flex;gap:8px;align-items:center;">
              <button type="button" class="layout-bar-btn save" id="btnSavePersonaSettings">保存角色资料</button>
              <span id="roleSaveFeedback" style="font-size:12px;color:#3E5626;"></span>
            </div>
          `
        },
        {
          id: `${mode}_role_c2`,
          domain: 'profile',
          title: `多主体目录切换与新建 (${catalog.length} 个主体)`,
          body: `
            <div id="personaCatalogList" data-readonly-slot="role_catalog_list" style="display:flex;flex-direction:column;gap:6px;margin-bottom:10px;max-height:150px;overflow-y:auto;">
              ${catalog.map(item => `
                <div style="display:flex;justify-content:space-between;align-items:center;padding:6px 10px;border-radius:8px;background:rgba(255,255,255,0.7);border:1px solid rgba(155,153,140,0.24);">
                  <span><strong>${esc(item.name)}</strong> (<code>${esc(String(item.id).slice(0, 10))}…</code>)</span>
                  ${item.id === charData.id
                    ? '<span class="envelope-badge live">当前激活</span>'
                    : `<button type="button" class="mini-tab-btn active" data-switch-persona="${esc(item.id)}">切换至此主体</button>`}
                </div>
              `).join('')}
            </div>
            <div style="padding-top:8px;border-top:1px solid rgba(155,153,140,0.22);display:flex;gap:6px;">
              <input type="text" id="inputNewPersonaName" value="" placeholder="新角色名称 (1-60字)..." style="flex:1;padding:5px 8px;border-radius:6px;border:1px solid rgba(130,136,118,0.4);font-size:12px;"/>
              <button type="button" class="mini-tab-btn active" id="btnCreateNewPersona">+ 新建主体</button>
            </div>
            <div id="roleCreateFeedback" style="font-size:11.5px;color:#2E4418;margin-top:6px;"></div>
          `
        }
      ];
    }

    // -------------------------------------------------------------------------
    // 11. persona_set: 正式人格构念与倾向设定 (P0-02 乐观并发 expected_version + owner_seed + 二次确认)
    // -------------------------------------------------------------------------
    if (navKey === 'persona_set') {
      const editables = persData.editable_constructs || [];
      return [
        {
          id: `${mode}_pset_c1`,
          domain: 'personality',
          title: `正式人格构念与情绪倾向设定`,
          size: 'wide',
          body: `
            <div style="font-size:12px;color:#4E5246;margin-bottom:10px;padding:8px 10px;border-radius:8px;background:rgba(126,152,96,0.12);">
              <div>这里保存的是你的人工设定。提交前会核对当前版本，避免覆盖同时发生的变化；情绪倾向代表通常表现。</div>
            </div>
            <div style="display:grid;grid-template-columns:2fr 1fr 1fr;gap:8px;margin-bottom:8px;">
              <div>
                <label style="font-size:11.5px;font-weight:600;display:block;margin-bottom:3px;">选择倾向（共 ${editables.length} 项）：</label>
                <select id="selectDispositionField" style="width:100%;padding:6px 8px;border-radius:6px;border:1px solid rgba(130,136,118,0.45);font-size:12px;">
                  ${editables.map(f => `
                    <option value="${esc(f.id)}" data-cur-est="${f.estimate != null ? f.estimate : 'null'}" data-cur-src="${esc(f.source_type)}" data-name-zh="${esc(f.name_zh)}">
                      ${esc(f.name_zh)} — 当前：${f.estimate != null ? Number(f.estimate).toFixed(2) : '待观察'} · ${esc(window.DisplayText.label(f.source_type))}
                    </option>
                  `).join('')}
                </select>
              </div>
              <div>
                <label style="font-size:11.5px;font-weight:600;display:block;margin-bottom:3px;">设定值（0 至 1）：</label>
                <input type="number" id="inputDispositionVal" step="0.05" min="0" max="1" value="0.78" style="width:100%;padding:6px 8px;border-radius:6px;border:1px solid rgba(130,136,118,0.45);font-size:12.5px;"/>
              </div>
              <div>
                <label style="font-size:11.5px;font-weight:600;display:block;margin-bottom:3px;">来源：</label>
                <input type="text" value="人工设定" disabled style="width:100%;padding:6px 8px;border-radius:6px;background:rgba(0,0,0,0.04);border:1px solid rgba(130,136,118,0.3);font-size:12px;color:#484C42;"/>
              </div>
            </div>
            <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;">
              <input type="text" id="inputDispositionNote" value="" placeholder="可选设定备注说明 (LIVE 模式默认空白)..." style="flex:1;padding:6px 10px;border-radius:6px;border:1px solid rgba(130,136,118,0.45);font-size:12px;"/>
              <button type="button" class="layout-bar-btn" id="btnPreviewDisposition">1. 核对设定变更</button>
              <button type="button" class="layout-bar-btn save" id="btnSaveDisposition">直接确认写入 (owner_seed)</button>
            </div>
            <div id="dispositionConfirmBox" style="display:none;padding:10px 12px;border-radius:8px;background:rgba(255,252,240,0.92);border:1.5px solid #6F8455;margin-bottom:8px;font-size:12px;"></div>
            <div id="dispositionFeedback" style="font-size:12px;color:#2E4418;min-height:18px;"></div>
          `
        },
        {
          id: `${mode}_pset_c2`,
          domain: 'personality',
          title: `7 项长期情绪倾向当前状态 (dispositions · v${persData.version ?? 0})`,
          body: `<div data-readonly-slot="dispositions_table" style="font-size:12px;line-height:1.75;">
            ${(persData.dispositions || []).map(d => `
              <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px dashed rgba(155,153,140,0.22);">
                <span><strong>${esc(d.label)}</strong> (<code>${esc(d.id)}</code>)</span>
                <span><strong>${d.estimate != null ? Number(d.estimate).toFixed(2) : 'null'}</strong> · <small>${esc(sourceTypeBadgeLabel(d.source_type))}</small></span>
              </div>
            `).join('')}
          </div>`
        }
      ];
    }

    // -------------------------------------------------------------------------
    // 12. archives: 原始资料、证据与边界档案 (/api/state -> source_records, boundary_model, pragmatics, evidence_trace)
    // -------------------------------------------------------------------------
    if (navKey === 'archives') {
      const srcRecs = charData.source_records || [];
      const bList = charData.boundary_model?.boundaries || [];
      const evTrace = charData.evidence_trace?.items || [];
      return [
        {
          id: `${mode}_arch_c1`,
          domain: 'profile',
          title: `原始证据记录与语用统计 (source_records: ${srcRecs.length} 条 · evidence_trace: ${evTrace.length} 条)`,
          size: 'wide',
          body: `
            <div data-readonly-slot="archives_sources" style="font-size:12px;max-height:240px;overflow-y:auto;display:flex;flex-direction:column;gap:6px;">
              ${srcRecs.length === 0
                ? '<div style="color:#6E7266;">当前角色尚无已归档的原始示范或证据记录 (source_records=[])。</div>'
                : srcRecs.slice(0, 15).map(r => `
                  <div style="padding:6px 10px;border-radius:8px;background:rgba(255,255,255,0.7);border:1px solid rgba(155,153,140,0.2);">
                    <div style="display:flex;justify-content:space-between;font-size:11px;color:#55594E;">
                      <span>ID: <code>${esc(r.id)}</code> · 来源: <code>${esc(r.source)}</code> · 说话人: <code>${esc(r.speaker)}</code></span>
                      <span>${esc(fmtLocal(r.timestamp))}</span>
                    </div>
                    <div style="font-size:12.5px;margin-top:2px;">${esc(r.text)}</div>
                  </div>
                `).join('')}
            </div>
          `
        },
        {
          id: `${mode}_arch_c2`,
          domain: 'profile',
          title: `个人边界模型档案`,
          body: `
            <div data-readonly-slot="archives_boundaries" style="font-size:12px;max-height:200px;overflow-y:auto;">
              ${bList.length === 0
                ? '<div style="color:#6E7266;">当前无特殊边界限制条目。</div>'
                : bList.map(b => `
                  <div style="padding:5px 0;border-bottom:1px dashed rgba(155,153,140,0.22);">
                    <strong>${esc(b.topic || b.id)}</strong> · 状态: <code>${esc(b.status)}</code> · 来源: <code>${esc(b.origin)}</code>
                  </div>
                `).join('')}
            </div>
          `
        }
      ];
    }

    // -------------------------------------------------------------------------
    // 13. model_cfg: 外部对话模型配置与连通探测 (General LLM — 独立于 PMM)
    // -------------------------------------------------------------------------
    if (navKey === 'model_cfg') {
      const cfg = charData.config || {};
      const gNode = connData.nodes?.general_llm || {};
      return [
        {
          id: `${mode}_mcfg_c1`,
          domain: 'connections',
          title: '外部对话模型 (General LLM) 独立配置与连通性验证',
          size: 'wide',
          body: `
            <div data-readonly-slot="model_cfg_status" style="display:flex;justify-content:space-between;align-items:center;padding:8px 12px;border-radius:8px;background:rgba(255,255,255,0.68);margin-bottom:10px;">
              <div>
                <strong>当前状态：${esc(gNode.status_text || '未配置')}</strong>
                <div style="font-size:11.5px;color:#55594E;">严格遵循 P0-1：仅保存模型名称属于 <code>configured</code>（已配置/未验证），只有点击「主动探测 General LLM」收到成功回执才标为 <code>healthy</code>。</div>
              </div>
              ${renderConnectionStateBadge(gNode.status || 'unavailable')}
            </div>
            <div style="display:grid;grid-template-columns:1fr 2fr 1.5fr;gap:8px;margin-bottom:10px;">
              <div>
                <label style="font-size:11.5px;font-weight:600;display:block;margin-bottom:3px;">协议 (provider)：</label>
                <select id="selectGenProvider" style="width:100%;padding:6px 8px;border-radius:6px;font-size:12px;">
                  ${['ollama', 'chat_completions', 'responses', 'anthropic', 'gemini'].map(p => `<option value="${p}" ${cfg.provider === p ? 'selected' : ''}>${p}</option>`).join('')}
                </select>
              </div>
              <div>
                <label style="font-size:11.5px;font-weight:600;display:block;margin-bottom:3px;">接口地址 (base_url)：</label>
                <input type="text" id="inputGenBaseUrl" value="${esc(cfg.base_url || 'http://127.0.0.1:11434')}" style="width:100%;padding:6px 8px;border-radius:6px;border:1px solid rgba(130,136,118,0.45);font-size:12px;"/>
              </div>
              <div>
                <label style="font-size:11.5px;font-weight:600;display:block;margin-bottom:3px;">模型名称 (model)：</label>
                <input type="text" id="inputGenModelName" value="${esc(cfg.model || '')}" placeholder="如 qwen2.5:14b" style="width:100%;padding:6px 8px;border-radius:6px;border:1px solid rgba(130,136,118,0.45);font-size:12px;"/>
              </div>
            </div>
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
              <button type="button" class="layout-bar-btn save" id="btnSaveGeneralLlmConfig">保存 General LLM 配置</button>
              <button type="button" class="layout-bar-btn" id="btnTestGeneralLlm">主动探测 General LLM</button>
              <span id="connProbeFeedback" style="font-size:12px;color:#2E4418;"></span>
            </div>
          `
        }
      ];
    }

    // -------------------------------------------------------------------------
    // 14. pmm_sys: PMM 双组件系统分栏监控 (API-PMM vs Learned-PMM)
    // -------------------------------------------------------------------------
    if (navKey === 'pmm_sys') {
      return [
        {
          id: `${mode}_pmmsys_c1`,
          domain: 'decisions',
          title: 'API-PMM (组件 A) 与 Learned-PMM (组件 B) 独立状态分栏监控与融合仲裁',
          size: 'wide',
          body: `
            <div data-readonly-slot="pmm_dual_body">${document.getElementById('devDualPmmTrackerBody')?.innerHTML || ''}</div>
            <div style="display:flex;gap:8px;align-items:center;margin-top:10px;padding-top:8px;border-top:1px solid rgba(155,153,140,0.22);">
              <button type="button" class="layout-bar-btn" id="btnTestPmmConn">主动探测 API-PMM 连接</button>
              <span id="connProbeFeedback" style="font-size:12px;color:#2E4418;"></span>
            </div>
          `
        }
      ];
    }

    // -------------------------------------------------------------------------
    // 15. qq_conn: QQ / OneBot 通道配置、白名单与测试
    // -------------------------------------------------------------------------
    if (navKey === 'qq_conn') {
      const qCfg = charData.config?.qq || {};
      const qNode = connData.nodes?.qq_channel || {};
      return [
        {
          id: `${mode}_qq_c1`,
          domain: 'connections',
          title: 'QQ / OneBot v11 通道状态、白名单路由与连通探测',
          size: 'wide',
          body: `
            <div data-readonly-slot="qq_conn_status" style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;border-radius:8px;background:rgba(255,255,255,0.68);margin-bottom:10px;">
              <div>
                <strong>通道状态：${esc(qNode.status_text || '未启用')}</strong>
                <div style="font-size:11.5px;color:#55594E;">OneBot HTTP API：<code>${esc(qCfg.api_url || 'http://127.0.0.1:3000')}</code> · 机器人 QQ (self_id)：<code>${esc(qCfg.self_id || '未设置')}</code> · 仅群 @ 回复：<code>${String(qCfg.group_mention_only ?? true)}</code></div>
              </div>
              ${renderConnectionStateBadge(qNode.status || 'unavailable')}
            </div>
            <div style="font-size:12px;margin-bottom:10px;">
              <div>● 授权私聊白名单用户 (${(qCfg.allowed_users || []).length})：<code>${esc((qCfg.allowed_users || []).join(', ') || '空 (默认不接收未授权私聊)')}</code></div>
              <div>● 授权群组白名单 (${(qCfg.allowed_groups || []).length})：<code>${esc((qCfg.allowed_groups || []).join(', ') || '空')}</code></div>
            </div>
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
              <button type="button" class="layout-bar-btn" id="btnTestQqConn">探测 OneBot 接口</button>
              <button type="button" class="layout-bar-btn" id="btnFetchQqWebhookUrl">获取事件回调地址</button>
              <span id="connProbeFeedback" style="font-size:12px;color:#2E4418;"></span>
            </div>
          `
        }
      ];
    }

    // -------------------------------------------------------------------------
    // 16. run_state: 总体六态健康矩阵、真实后台任务表与轮询监控
    // -------------------------------------------------------------------------
    if (navKey === 'run_state') {
      const nodes = connData.nodes || {};
      const activeJobs = connData.active_jobs || [];
      return [
        {
          id: `${mode}_run_c1`,
          domain: 'connections',
          title: '七大服务节点六态健康矩阵 (healthy / reachable / running / configured / unknown / unavailable)',
          size: 'wide',
          body: `<div data-readonly-slot="runstate_matrix">${renderFaultBannerIfAny('connections', true) || `
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px;">
              ${Object.values(nodes).map(n => `
                <div style="padding:10px 12px;border-radius:10px;background:rgba(255,255,255,0.72);border:1px solid rgba(155,153,140,0.25);">
                  <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;margin-bottom:4px;">
                    <strong style="font-size:12.5px;">${esc(n.name)}</strong>
                    ${renderConnectionStateBadge(n.status)}
                  </div>
                  <div style="font-size:12px;color:#2E3229;">状态描述：${esc(n.status_text)} (healthy=${esc(String(n.healthy))})</div>
                  <div style="font-size:11px;color:#62665A;margin-top:2px;">${esc(n.detail)} · 探测源: <code>${esc(n.endpoint_probe)}</code></div>
                </div>
              `).join('')}
            </div>
          `}</div>`
        },
        {
          id: `${mode}_run_c2`,
          domain: 'connections',
          title: `后台活动作业队列 (active_jobs: ${activeJobs.length} 个) & 轮询健康度`,
          body: `
            <div data-readonly-slot="runstate_jobs" style="font-size:12px;line-height:1.75;">
              <div><strong>轮询调度器：</strong>${esc(pollingScheduler.getStatusSummary())}</div>
              <div><strong>活动作业列表：</strong>${activeJobs.length === 0 ? '当前空闲 (0 个排队或运行中任务)' : activeJobs.map(j => `<code>${esc(j.id)} (${esc(j.kind)}: ${esc(j.status)})</code>`).join(', ')}</div>
            </div>
          `
        }
      ];
    }

    // -------------------------------------------------------------------------
    // 17. data_import: 原始资料导入、预览、显式勾选授权与创建任务 (P0-04)
    // -------------------------------------------------------------------------
    if (navKey === 'data_import') {
      return [
        {
          id: `${mode}_import_c1`,
          domain: 'learning',
          title: '原始资料导入与两步预览授权创建学习任务',
          size: 'wide',
          body: `
            <div style="font-size:12px;color:#4E5246;margin-bottom:10px;padding:8px 10px;border-radius:8px;background:rgba(126,152,96,0.12);">
              输入你允许使用的原文，先预览内容，再决定是否创建学习任务。
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:8px;">
              <div>
                <label style="font-size:11.5px;font-weight:600;display:block;margin-bottom:3px;">学习目标：</label>
                <select id="selectLearnTarget" style="width:100%;padding:6px 8px;border-radius:6px;font-size:12px;">
                  <option value="self">人格倾向</option>
                  <option value="language">表达风格</option>
                  <option value="memory">事件记忆</option>
                </select>
              </div>
              <div>
                <label style="font-size:11.5px;font-weight:600;display:block;margin-bottom:3px;">学习方式：</label>
                <select id="selectLearnIntent" style="width:100%;padding:6px 8px;border-radius:6px;font-size:12px;">
                  <option value="review">生成候选，等待审阅</option>
                  <option value="analysis">仅分析</option>
                  <option value="apply">符合条件后应用</option>
                </select>
              </div>
              <div>
                <label style="font-size:11.5px;font-weight:600;display:block;margin-bottom:3px;">资料归属：</label>
                <input type="text" id="inputLearnScope" value="self:imported" style="width:100%;padding:6px 8px;border-radius:6px;border:1px solid rgba(130,136,118,0.45);font-size:12px;"/>
              </div>
            </div>
            <div style="margin-bottom:8px;">
              <label style="font-size:11.5px;font-weight:600;display:block;margin-bottom:3px;">真人示范原文 (每行一条记录，LIVE 模式默认空白)：</label>
              <textarea id="inputLearnSampleText" rows="3" placeholder="请输入真人示范或历史原文（每行作为一条独立记录导入；LIVE 模式默认空白）..." style="width:100%;padding:8px 10px;border-radius:8px;border:1px solid rgba(130,136,118,0.45);font-size:12.5px;">${isMock ? 'MOCK 演示示范原文：喜欢安静观察午后街景。' : ''}</textarea>
            </div>
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px;">
              <button type="button" class="mini-tab-btn" id="btnFillLearnDemoText">填入测试示例原文</button>
              <button type="button" class="layout-bar-btn save" id="btnPreviewLearningJob">1. 预览学习来源与风险</button>
            </div>
            <div id="learningPreviewConfirmBox" style="display:none;padding:12px;border-radius:10px;background:rgba(255,252,240,0.95);border:1.5px solid #6F8455;margin-bottom:8px;font-size:12px;"></div>
            <div id="learnJobCreateFeedback" style="font-size:12px;color:#2E4418;min-height:18px;"></div>
          `
        }
      ];
    }

    // -------------------------------------------------------------------------
    // 18. distill_task: 蒸馏与学习作业队列控制
    // -------------------------------------------------------------------------
    if (navKey === 'distill_task') {
      const jobs = learnData.jobs || [];
      return [
        {
          id: `${mode}_distill_c1`,
          domain: 'learning',
          title: `蒸馏与学习作业队列控制`,
          size: 'wide',
          body: `<div id="distillJobsListContainer" data-readonly-slot="distill_jobs">${renderFaultBannerIfAny('learning', true) || `
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
              <span style="font-size:12px;color:#52564A;">支持对队列中的任务执行暂停 (pause)、恢复 (resume)、取消 (cancel) 与回滚 (rollback)。</span>
              <button type="button" class="mini-tab-btn active" data-dev-nav="data_import">+ 前往「数据导入」新建任务</button>
            </div>
            <div style="display:flex;flex-direction:column;gap:8px;max-height:320px;overflow-y:auto;">
              ${jobs.length === 0
                ? '<div style="color:#6E7266;font-size:12.5px;">当前 <code>learning_center.jobs = []</code>（0 项任务）。请前往「数据导入」经过预览与授权创建任务。</div>'
                : jobs.map(j => `
                  <div style="padding:10px 12px;border-radius:10px;background:rgba(255,255,255,0.75);border:1px solid rgba(155,153,140,0.25);">
                    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
                      <strong>${esc(j.title)}</strong>
                      <div style="display:flex;gap:6px;align-items:center;">
                        <span class="envelope-badge live">${esc(j.status)} · ${Number(j.progress ?? 0)}%</span>
                        <button type="button" class="mini-tab-btn" data-job-control="pause" data-job-id="${esc(j.id)}">暂停</button>
                        <button type="button" class="mini-tab-btn" data-job-control="resume" data-job-id="${esc(j.id)}">恢复</button>
                        <button type="button" class="mini-tab-btn" data-job-control="cancel" data-job-id="${esc(j.id)}">取消</button>
                      </div>
                    </div>
                    <div style="font-size:11.5px;color:#52564A;margin-top:4px;">
                      任务 ID: <code>${esc(j.id)}</code> · 目标域: <code>${esc(j.target)}</code> · 模式: <code>${esc(j.intent)}</code> · 阶段: ${esc(j.phase)} · 创建时间: ${esc(fmtLocal(j.created_at))}
                    </div>
                    <div class="dev-task-bar-track" style="margin-top:6px;"><div class="dev-task-bar-fill" style="width:${Number(j.progress ?? 0)}%"></div></div>
                  </div>
                `).join('')}
            </div>
          `}</div>
          <div id="distillHighRiskConfirmBox" style="display:none;padding:10px 12px;border-radius:8px;background:rgba(255,245,238,0.96);border:1.5px solid #B83B2A;margin-top:8px;font-size:12px;"></div>
          <div id="distillControlFeedback" style="font-size:12px;color:#2E4418;margin-top:6px;"></div>`
        }
      ];
    }

    // -------------------------------------------------------------------------
    // 19. learn_record: 学习活动流水、交谈对象状态与候选特质复核
    // -------------------------------------------------------------------------
    if (navKey === 'learn_record') {
      const acts = learnData.activities || [];
      const others = learnData.other_status || [];
      const cands = learnData.candidates || [];
      return [
        {
          id: `${mode}_lrec_c1`,
          domain: 'learning',
          title: `学习活动审计流水`,
          size: 'wide',
          body: `
            <div data-readonly-slot="learn_record_activities" style="font-size:12px;max-height:220px;overflow-y:auto;display:flex;flex-direction:column;gap:6px;">
              ${acts.length === 0
                ? '<div style="color:#6E7266;">当前尚无学习活动流水事件。在对话回合或蒸馏任务执行后将自动记录。</div>'
                : acts.map(a => `
                  <div style="padding:6px 10px;border-radius:8px;background:rgba(255,255,255,0.7);border:1px solid rgba(155,153,140,0.2);">
                    <div style="display:flex;justify-content:space-between;font-size:11px;color:#55594E;">
                      <strong>事件类型: <code>${esc(a.kind)}</code> · ID: <code>${esc(String(a.id).slice(0, 18))}</code></strong>
                      <span>本地时间: ${esc(fmtLocal(a.created_at))}</span>
                    </div>
                    <div style="font-size:11.5px;margin-top:2px;">范围: <code>${esc(a.payload?.scope || '--')}</code> · 修订号变更: <code>rev ${esc(a.payload?.profile_revision_before ?? '--')} → ${esc(a.payload?.profile_revision_after ?? '--')}</code></div>
                  </div>
                `).join('')}
            </div>
          `
        },
        {
          id: `${mode}_lrec_c2`,
          domain: 'learning',
          title: `候选特质复核 (${cands.length} 项) & 交谈对象建模状态 (${others.length} 人)`,
          body: `
            <div data-readonly-slot="learn_record_candidates" style="font-size:12px;line-height:1.7;">
              <div><strong>待复核候选特质：</strong>${cands.length} 项</div>
              <div style="margin-top:6px;"><strong>交谈对象观察状态 (other_status)：</strong></div>
              ${others.map(o => `<div style="padding:3px 0;border-bottom:1px dashed rgba(155,153,140,0.2);">● <code>${esc(o.person)}</code> (${esc(o.scope)})：已观察 ${o.observed} 条 · ${esc(o.status)}</div>`).join('') || '<div style="color:#6E7266;">暂无交谈对象记录</div>'}
            </div>
          `
        }
      ];
    }

    // -------------------------------------------------------------------------
    // 20. version_mgmt: 人格检查点列表、创建检查点与回滚恢复
    // -------------------------------------------------------------------------
    if (navKey === 'version_mgmt') {
      const revs = persData.revisions || [];
      return [
        {
          id: `${mode}_ver_c1`,
          domain: 'personality',
          title: `人格版本检查点管理与状态恢复`,
          size: 'wide',
          body: `
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px;padding:10px;border-radius:8px;background:rgba(126,152,96,0.12);">
              <input type="text" id="inputCheckpointLabel" value="" placeholder="输入检查点备注名称 (LIVE 模式默认空白，不填则使用默认名)..." style="flex:1;min-width:220px;padding:6px 10px;border-radius:6px;border:1px solid rgba(130,136,118,0.45);font-size:12.5px;"/>
              <button type="button" class="layout-bar-btn save" id="btnCreateCheckpoint">创建人格版本检查点</button>
            </div>
            <div id="versionRollbackConfirmBox" style="display:none;padding:10px 12px;border-radius:8px;background:rgba(255,245,238,0.96);border:1.5px solid #B83B2A;margin-bottom:8px;font-size:12px;"></div>
            <div id="versionMgmtFeedback" style="font-size:12px;color:#2E4418;margin-bottom:8px;"></div>
            <div id="revisionListContainer" data-readonly-slot="revisions_list" style="display:flex;flex-direction:column;gap:6px;max-height:260px;overflow-y:auto;">
              ${revs.length === 0
                ? '<div style="color:#6E7266;font-size:12.5px;">当前尚无历史检查点记录。</div>'
                : revs.map(r => `
                  <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 12px;border-radius:8px;background:rgba(255,255,255,0.72);border:1px solid rgba(155,153,140,0.24);font-size:12px;">
                    <div>
                      <strong>${esc(r.label || r.id)}</strong> (ID: <code>${esc(r.id)}</code>)
                      <div style="font-size:11px;color:#55594E;">创建时间：${esc(fmtLocal(r.created_at || r.updated_at))} (UTC: <code>${esc(window.formatBusinessTimestamp(r.created_at || r.updated_at) || '--')}</code>)</div>
                    </div>
                    <button type="button" class="mini-tab-btn" data-rollback-rev="${esc(r.id)}">恢复至此检查点</button>
                  </div>
                `).join('')}
            </div>
          `
        }
      ];
    }

    // -------------------------------------------------------------------------
    // 21. behavior_event: 逐轮行动/表达策略、条件评分与回执审计
    // -------------------------------------------------------------------------
    if (navKey === 'behavior_event') {
      const items = expData.items || [];
      return [
        {
          id: `${mode}_behev_c1`,
          domain: 'experiences',
          title: `逐轮行动策略、表达条件评分与送达回执审计 (de-expression/1 · 共 ${items.length} 轮)`,
          size: 'wide',
          body: `
            <div style="font-size:12px;color:#52564A;margin-bottom:8px;">
              重点审计每轮的行动策略 (<code>strategy</code>)、规划气泡数 (<code>planned_bubbles</code>)、确认送达数 (<code>actual_confirmed</code>) 及内部条件评分 (<code>joint.usage</code>)，区别于纯聊天气泡。
            </div>
            <div data-readonly-slot="behavior_event_list" style="display:flex;flex-direction:column;gap:8px;max-height:310px;overflow-y:auto;">
              ${items.length === 0
                ? '<div style="color:#6E7266;">尚无行动与联合表达审计记录。</div>'
                : items.map(it => `
                  <div style="padding:10px 12px;border-radius:10px;background:rgba(255,255,255,0.75);border:1px solid rgba(155,153,140,0.25);font-size:12px;">
                    <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                      <strong>Turn <code>${esc(it.id)}</code> · 策略: <code>${esc(it.strategy)}</code></strong>
                      <span class="envelope-badge live">回执: ${esc(it.delivery)} (规划 ${esc(it.planned_bubbles)} / 确认 ${esc(it.actual_confirmed)})</span>
                    </div>
                    <div>情绪与表达欲条件：<code>${esc(it.emo)}</code> · 时间：${esc(fmtLocal(it.time))}</div>
                    <div style="font-size:11px;color:#55594E;margin-top:4px;">
                      条件评估项 (${(it.usage || []).length})：${(it.usage || []).map(u => `<code>${esc(u.condition)}:${esc(u.status)}</code>`).join(', ') || '无'}
                    </div>
                  </div>
                `).join('')}
            </div>
          `
        }
      ];
    }

    // -------------------------------------------------------------------------
    // 22. session_trace: API-PMM 与 Learned-PMM 逐轮推理轨迹与融合校验
    // -------------------------------------------------------------------------
    if (navKey === 'session_trace') {
      const traces = decData.traces || [];
      return [
        {
          id: `${mode}_strace_c1`,
          domain: 'decisions',
          title: `API-PMM 与 Learned-PMM 逐轮推理轨迹与事务回执账本`,
          size: 'wide',
          body: `
            <div data-readonly-slot="session_trace_list" style="display:flex;flex-direction:column;gap:8px;max-height:330px;overflow-y:auto;">
              ${traces.length === 0
                ? '<div style="color:#6E7266;font-size:12.5px;">当前 <code>traces = []</code>（0 条轨迹）。在会客室发起真实对话后将逐轮记录双组件独立输出与仲裁回执。</div>'
                : traces.map(t => {
                  const r = t.components?.reasoner || {};
                  const n = t.components?.neural || {};
                  const d = t.components?.decision?.payload || {};
                  const rec = t.commit_receipt || {};
                  return `
                    <div style="padding:10px 12px;border-radius:10px;background:rgba(255,255,255,0.75);border:1px solid rgba(155,153,140,0.25);font-size:12px;">
                      <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
                        <strong>Turn ID: <code>${esc(t.turn_id)}</code> · Scope: <code>${esc(t.scope)}</code></strong>
                        <span>本地时间: ${esc(fmtLocal(t.timestamp))}</span>
                      </div>
                      <div>事件输入：「${esc(t.text || '')}」</div>
                      <div style="margin-top:3px;">● <strong>API-PMM (${esc(r.status || 'none')})：</strong>executed=${esc(String(r.executed))} · 耗时 ${esc(r.elapsed_ms ?? '--')}ms · 首选动作 <code>${esc(d.api_preference || '--')}</code></div>
                      <div>● <strong>Learned-PMM (${esc(n.payload?.calibration || 'uncalibrated')})：</strong>executed=${esc(String(n.executed))} · 首选动作 <code>${esc(d.neural_preference || '--')}</code> · 门禁 <code>${esc(n.payload?.release_gate || '--')}</code></div>
                      <div style="margin-top:3px;color:#2E4418;">● <strong>融合仲裁：</strong>disagreement=<code>${esc(String(d.disagreement))}</code> · 采纳动作=<strong><code>${esc(d.official_action || 'reply')}</code></strong> · 回执版本: <code>profile_rev=${esc(rec.profile_revision ?? '--')}, trait_v=${esc(rec.trait_version ?? '--')}</code></div>
                    </div>
                  `;
                }).join('')}
            </div>
          `
        }
      ];
    }

    // -------------------------------------------------------------------------
    // 23. logs_monitor: HTTP 请求时序日志、耗时、状态码过滤与 UTC/本地时间戳核验
    // -------------------------------------------------------------------------
    if (navKey === 'logs_monitor') {
      const logs = pmmAdapter.callLog.filter(c => {
        if (logStatusFilter === 'ok') return c.ok;
        if (logStatusFilter === 'error') return !c.ok;
        return true;
      });
      return [
        {
          id: `${mode}_logs_c1`,
          domain: 'connections',
          title: `HTTP 请求与时序审计日志 (总记录 ${pmmAdapter.callLog.length} 条 · 当前显示 ${logs.length} 条)`,
          size: 'wide',
          body: `
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;flex-wrap:wrap;gap:8px;">
              <div style="display:flex;gap:6px;">
                <button type="button" class="mini-tab-btn ${logStatusFilter === 'all' ? 'active' : ''}" data-log-filter="all">全部 (${pmmAdapter.callLog.length})</button>
                <button type="button" class="mini-tab-btn ${logStatusFilter === 'ok' ? 'active' : ''}" data-log-filter="ok">仅成功 (200 OK)</button>
                <button type="button" class="mini-tab-btn ${logStatusFilter === 'error' ? 'active' : ''}" data-log-filter="error">仅错误 (4xx/5xx/Timeout)</button>
              </div>
              <span style="font-size:11.5px;color:#55594E;">时间戳严格保留 ISO 8601 UTC (带 Z) 并附本地时区转换</span>
            </div>
            <div id="httpCallAuditLedgerBox" data-readonly-slot="logs_ledger" style="font-family:var(--font-mono);font-size:11px;max-height:280px;overflow-y:auto;background:rgba(255,255,255,0.78);padding:10px;border-radius:10px;">
              ${logs.slice(0, 40).map(c => `
                <div style="padding:3px 0;border-bottom:1px dashed rgba(155,153,140,0.2);">
                  [本地:${esc(fmtLocal(c.at, false))} | UTC:<code>${esc(c.at)}</code>] <strong>${esc(c.method)} ${esc(c.endpoint)}</strong> → HTTP ${esc(c.status)} (${esc(c.elapsed_ms)}ms) ${c.ok ? '<span style="color:#3E6B1F;">✓ OK</span>' : `<span style="color:#B83B2A;">✗ ${esc(c.error || c.code || 'ERR')}</span>`}
                </div>
              `).join('') || '<div>暂无匹配日志记录</div>'}
            </div>
          `
        }
      ];
    }

    // -------------------------------------------------------------------------
    // 24. api_tools: 受限故障注入、连接探测与数据源切换工具 (不修改真实心理数据库)
    // -------------------------------------------------------------------------
    return [
      {
        id: `${mode}_tools_c1`,
        domain: 'connections',
        title: '受限模块级故障注入与数据源切换测试工具 (仅用于开发端容错测试，不污染长期心理记录)',
        size: 'wide',
        body: `
          <div style="font-size:12px;color:#52564A;margin-bottom:8px;">
            针对单个原版后端接口注入 404 / 500 / TIMEOUT / DISCONNECT，验证「仅故障模块显示 ERROR，其余模块保持真实 LIVE 状态」。
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;">
            <button type="button" class="mini-tab-btn" data-inject-ep="/api/affect" data-inject-type="500">模拟 /api/affect HTTP 500</button>
            <button type="button" class="mini-tab-btn" data-inject-ep="/api/memories" data-inject-type="timeout">模拟 /api/memories TIMEOUT</button>
            <button type="button" class="mini-tab-btn" data-inject-ep="/api/pmm283/expressive-drive" data-inject-type="404">模拟 /api/pmm283/expressive-drive 404</button>
            <button type="button" class="mini-tab-btn" data-inject-ep="/api/learning" data-inject-type="500">模拟 /api/learning HTTP 500</button>
            <button type="button" class="mini-tab-btn active" id="btnClearAllEndpointFaults">清除全部故障注入并恢复 LIVE</button>
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;">
            <button type="button" class="layout-bar-btn" id="btnSubpageProbe404">向原版后端发起真实 404 请求</button>
            <button type="button" class="layout-bar-btn" data-switch-datasource="mock">切换至显式 MOCK 演示数据</button>
            <button type="button" class="layout-bar-btn save" data-switch-datasource="live">重新同步 LIVE 原版后端</button>
          </div>
          <div id="apiToolsFeedbackBox" style="margin-top:8px;font-family:var(--font-mono);font-size:11.5px;color:#3E4238;"></div>
        `
      }
    ];
  }

  // ---------------------------------------------------------------------------
  // P1-02: Non-Destructive Subpage Render & Read-Only Slot Updater
  // ---------------------------------------------------------------------------
  function renderSubpage(mode, navKey, opts = {}) {
    const box = mode === 'user' ? document.getElementById('userSubpageContainer') : document.getElementById('devSubpageContainer');
    if (!box) return;
    const mountSignature = `${mode}:${navKey}:${currentPersonaId()}:${dataSourceMode}:${navKey === 'parlor' ? parlorSessionId : ''}`;
    const visualPage = ['psych_state', 'emo_drive', 'rel_net'].includes(navKey) || mode === 'user' && ['persona_analysis', 'memories', 'experiences', 'growth', 'parlor', 'settings'].includes(navKey);
    box.classList.toggle('psych-viz-page', visualPage);
    box.classList.toggle('dev-viz-page', mode === 'developer');

    // P1-02: If preserveSubpageDom is true and the exact same subpage is already mounted,
    // ONLY update the read-only slots & badges without touching any <input>/<textarea>/<select> or focus!
    if (opts.preserveSubpageDom && box.dataset.mountedSignature === mountSignature && !box.hidden) {
      updateAllDomainBadges();
      const freshCards = buildDomainSpecificCards(mode, navKey);
      freshCards.forEach(c => {
        const titleEl = box.querySelector(`[data-card-title-slot="${c.id}"]`);
        if (titleEl) titleEl.textContent = c.title;
      });
      const tempDiv = document.createElement('div');
      tempDiv.innerHTML = freshCards.map(c => c.body).join('');
      tempDiv.querySelectorAll('[data-readonly-slot]').forEach(freshSlot => {
        const slotName = freshSlot.dataset.readonlySlot;
        const liveSlot = box.querySelector(`[data-readonly-slot="${slotName}"]`);
        if (liveSlot) {
          const prevScroll = liveSlot.scrollTop;
          const atChatEnd = slotName === 'parlor_messages' && liveSlot.scrollHeight - liveSlot.clientHeight - liveSlot.scrollTop < 45;
          const expanded = [...liveSlot.querySelectorAll('details[open][data-life-expand]')].map(d => d.dataset.lifeExpand);
          // Controls outside slots remain mounted. Chart buttons inside a changed
          // slot retain their keyboard focus by stable data attributes.
          if (liveSlot.innerHTML === freshSlot.innerHTML) return;
          const focused = liveSlot.contains(document.activeElement) ? document.activeElement : null;
          const focusAttrs = focused ? [...focused.attributes].filter(a => a.name === 'id' || a.name.startsWith('data-')) : [];
          liveSlot.innerHTML = freshSlot.innerHTML;
          liveSlot.scrollTop = atChatEnd ? liveSlot.scrollHeight : prevScroll;
          for (const d of liveSlot.querySelectorAll('details[data-life-expand]')) if (expanded.includes(d.dataset.lifeExpand)) d.open = true;
          if (focusAttrs.length) {
            const replacement = [...liveSlot.querySelectorAll('button, [tabindex], summary')].find(el => focusAttrs.every(a => el.getAttribute(a.name) === a.value));
            replacement?.focus({ preventScroll: true });
          }
        }
      });
      window.PersonalityView?.syncControls?.(box);
      window.EmotionView?.syncControls?.(box);
      if (navKey === 'emo_drive') window.DriveView.syncControls(box);
      if (mode === 'user' && navKey === 'memories') window.MemoryGraphView.afterRender(box);
      if (mode === 'user' && ['experiences', 'growth'].includes(navKey)) window.LifeViews.syncControls(box);
      if (navKey === 'rel_net') window.RelationView.afterRender(box);
      if (mode === 'user' && navKey === 'parlor') window.ParlorView.syncControls(box);
      window.DeveloperViews.syncControls(box);
      return;
    }

    const meta = SUBPAGE_META[navKey] || { title: navKey, domain: 'profile', desc: '领域子页面' };
    const spec = computeDomainBadgeSpec(meta.domain);
    const gridId = `${mode}_subpage_${navKey}_grid`;
    const cards = buildDomainSpecificCards(mode, navKey);

    box.dataset.mountedSignature = mountSignature;
    box.innerHTML = `
      <div class="subpage-header-bar">
        <div>
          <div style="display:flex;align-items:center;gap:10px;">
            <h2 style="font-family:var(--font-serif);font-size:22px;font-weight:700;">${esc(meta.title)}</h2>
            <span class="envelope-badge ${spec.cls} js-domain-badge" data-domain="${esc(meta.domain)}">${esc(spec.text)}</span>
          </div>
          <p style="font-size:12.5px;color:#5E6256;margin-top:4px;">${esc(meta.desc)}</p>
        </div>
        <div style="display:flex;align-items:center;gap:8px;">
          ${navKey === 'role_info' ? '<button type="button" class="layout-bar-btn save" data-open-modal="persona_manager">管理角色 · 新建 / 导入 / 导出 / 回收站</button>' : ''}
          <button type="button" class="topbar-chip-btn js-toggle-layout-edit ${layoutEditActive ? 'active-edit' : ''}">✦ 编辑本页布局</button>
          <button type="button" class="layout-bar-btn save" ${mode === 'user' ? 'data-user-nav="observe"' : 'data-dev-nav="overview"'}>
            ← 返回${mode === 'user' ? '观察首页' : '开发端总览'}
          </button>
        </div>
      </div>
      <div class="subpage-card-grid" data-layout-grid="${esc(gridId)}">
        ${cards.map(c => {
          const cSpec = computeDomainBadgeSpec(c.domain || meta.domain);
          return `
            <section class="${mode === 'user' ? 'ui-frosted-card' : 'dev-frosted-card'}" style="padding:16px 20px;" data-layout-card="${esc(c.id)}" data-card-size="${esc(c.size || 'standard')}">
              <div class="card-header-row" style="margin-bottom:8px;">
                <h3 data-card-title-slot="${esc(c.id)}" style="font-family:var(--font-serif);font-size:17px;font-weight:700;">${esc(c.title)}</h3>
                <span class="envelope-badge ${cSpec.cls} js-domain-badge" data-domain="${esc(c.domain || meta.domain)}">${esc(cSpec.text)}</span>
              </div>
              <div>${c.body}</div>
            </section>
          `;
        }).join('')}
      </div>
    `;
    ensureEditOverlaysOnCards();
    applySavedLayoutsForCurrentView();
    if (navKey === 'emo_drive') window.DriveView.syncControls(box);
    if (mode === 'user' && navKey === 'memories') window.MemoryGraphView.afterRender(box);
    if (mode === 'user' && ['experiences', 'growth'].includes(navKey)) window.LifeViews.syncControls(box);
    if (navKey === 'rel_net') window.RelationView.afterRender(box);
    if (mode === 'user' && navKey === 'parlor') { window.ParlorView.syncControls(box); const history = box.querySelector('#parlorChatHistoryBox'); if (history) history.scrollTop = history.scrollHeight; }
    window.DeveloperViews.syncControls(box);
  }

  function switchMode(mode, persist = true) {
    window.PsychViz?.close();
    window.MemoryGraphView?.unmount();
    window.RelationView?.unmount();
    currentMode = mode === 'developer' ? 'developer' : 'user';
    // Shared page controls have the same IDs in both modes. Unmount the hidden
    // page so event handlers cannot find stale controls in the other workspace.
    const inactivePage = document.getElementById(currentMode === 'user' ? 'devSubpageContainer' : 'userSubpageContainer');
    if (inactivePage) { inactivePage.replaceChildren(); delete inactivePage.dataset.mountedSignature; }
    const userShell = document.getElementById('userShellViewport');
    const devShell = document.getElementById('devShellViewport');
    if (userShell) userShell.hidden = currentMode !== 'user';
    if (devShell) devShell.hidden = currentMode !== 'developer';

    document.querySelectorAll('.frosted-mode-switcher').forEach(sw => {
      sw.dataset.activeMode = currentMode;
      sw.querySelectorAll('.frosted-mode-tab').forEach(tab => {
        const isAct = tab.dataset.switchMode === currentMode;
        tab.classList.toggle('active', isAct);
        tab.setAttribute('aria-selected', isAct ? 'true' : 'false');
      });
    });

    if (persist) {
      try { localStorage.setItem('huaian_ui_shell_mode', currentMode); } catch (_) {}
    }
    refreshAllViews({ preserveSubpageDom: false });
  }

  async function switchUserNav(target) {
    window.MemoryGraphView?.unmount();
    window.RelationView?.unmount();
    window.PsychViz?.close();
    currentUserNav = target || 'observe';
    document.querySelectorAll('[data-user-nav]').forEach(btn => {
      if (btn.classList.contains('user-nav-item')) {
        btn.classList.toggle('active', btn.dataset.userNav === currentUserNav);
      }
    });
    const observeView = document.getElementById('observeHomeView');
    const userSubpageBox = document.getElementById('userSubpageContainer');
    if (currentUserNav === 'observe') {
      if (observeView) observeView.hidden = false;
      if (userSubpageBox) userSubpageBox.hidden = true;
      renderUserHomeDynamicCards();
      ensureEditOverlaysOnCards();
      applySavedLayoutsForCurrentView();
    } else {
      if (observeView) observeView.hidden = true;
      if (userSubpageBox) userSubpageBox.hidden = false;
      if (currentUserNav === 'parlor' && dataSourceMode === 'live' && parlorSessionId) {
        await readParlorMessages();
      }
      renderSubpage('user', currentUserNav, { preserveSubpageDom: false });
    }
  }

  function switchDevNav(target) {
    window.MemoryGraphView?.unmount();
    window.RelationView?.unmount();
    window.PsychViz.close();
    currentDevNav = target || 'overview';
    document.querySelectorAll('.dev-overview-pill, .dev-nav-link').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.devNav === currentDevNav);
    });
    const devOverviewView = document.getElementById('devOverviewView');
    const devSubpageBox = document.getElementById('devSubpageContainer');
    if (currentDevNav === 'overview') {
      if (devOverviewView) devOverviewView.hidden = false;
      if (devSubpageBox) devSubpageBox.hidden = true;
      renderDeveloperOverviewDynamicCards();
      ensureEditOverlaysOnCards();
      applySavedLayoutsForCurrentView();
    } else {
      if (devOverviewView) devOverviewView.hidden = true;
      if (devSubpageBox) devSubpageBox.hidden = false;
      renderSubpage('developer', currentDevNav, { preserveSubpageDom: false });
    }
  }

  function setDomainFault(domain, faultState) {
    if (domain === 'all') {
      Object.keys(domainFaults).forEach(k => { domainFaults[k] = 'normal'; });
      pmmAdapter.clearEndpointFaultOverrides();
    } else if (domain in domainFaults) {
      domainFaults[domain] = faultState || 'normal';
    }
    refreshAllViews({ preserveSubpageDom: true });
  }

  function refreshAllViews(opts = {}) {
    renderUserHomeDynamicCards();
    renderDeveloperOverviewDynamicCards();
    if (currentMode === 'user' && currentUserNav !== 'observe') {
      renderSubpage('user', currentUserNav, { preserveSubpageDom: Boolean(opts.preserveSubpageDom) });
    }
    if (currentMode === 'developer' && currentDevNav !== 'overview') {
      renderSubpage('developer', currentDevNav, { preserveSubpageDom: Boolean(opts.preserveSubpageDom) });
    }
    ensureEditOverlaysOnCards();
    applySavedLayoutsForCurrentView();
    window.PsychViz?.refresh(activeEnvelopes, `${currentPersonaId()}:${dataSourceMode}:${contextEpoch}`);
  }

  function resolvePsychDetail(kind, id, domain, envelopes) {
    if (kind === 'provenance') {
      const envelope = domain === 'cognition' ? envelopes.characterProfile?.data?.cognition_envelope : domain === 'memoryGraph' ? envelopes.memories?.data?.relation_graph_envelope : envelopes[domain];
      return { title: '数据来源与映射', id, field: id, envelope,
        description: '图形位置来自现有状态字段。LIVE 为本地接口返回；DERIVED 为显示投影；MOCK 为演示；UNAVAILABLE 为缺失。',
        fields: [{ label: '数据状态', value: window.PsychViz.source(envelope, id) }],
        raw: { field_sources: envelope?.field_sources, derivations: envelope?.derivations } };
    }
    return window.PersonalityView.detail(kind, id, envelopes) || window.EmotionView.detail(kind, id, envelopes) || window.DriveView.detail(kind, id, envelopes) || window.MemoryGraphView.detail(kind, id, envelopes) || window.LifeViews.detail(kind, id, envelopes) || window.RelationView.detail(kind, id, envelopes) || window.ParlorView.detail(kind, id) || window.PmmFlow.detail(kind, id, envelopes) || window.DeveloperViews.detail(kind, id, envelopes);
  }

  function personaManagementServices() {
    return {
      adapter: pmmAdapter,
      profile: () => activeEnvelopes.characterProfile?.data,
      context: () => ({ owner: currentPersonaId(), epoch: contextEpoch, source: dataSourceMode }),
      isCurrent: c => c.owner === currentPersonaId() && c.epoch === contextEpoch && c.source === dataSourceMode,
      guard: () => guardWrite('persona_manage', { feedbackEl: document.getElementById('personaManagerFeedback') }).allowed,
      setBusy: value => { personaSwitchInFlight = value; },
      changed: async () => {
        contextEpoch += 1;
        clearPendingTransientConfirmations();
        const result = await tryHydrateFromLiveServer(activeScope, { forceFullRefresh: true });
        if (currentOpenModalKey === 'persona_manager') openModal('persona_manager');
        return result.ok && activeEnvelopes.characterProfile?.status === 'success';
      }
    };
  }

  const MODAL_HANDLERS = {
    persona_manager(env) {
      return { title: '管理角色', badgeClass: env.mode === 'mock' ? 'mock' : 'live',
        badgeText: env.mode === 'mock' ? '演示模式' : '本地角色档案', html: window.PersonaManager.render(env) };
    },
    role_switcher(env) {
      const charData = env.characterProfile?.data || {};
      const persData = env.personality?.data || {};
      const catalog = Array.isArray(charData.personas_catalog) ? charData.personas_catalog : [];
      const isMock = env.mode === 'mock';
      return {
        title: '切换角色',
        badgeClass: isMock ? 'mock' : 'live',
        badgeText: isMock ? 'MOCK 演示角色目录' : `LIVE 角色目录 (${catalog.length} 个主体)`,
        html: `
          <div style="display:flex;flex-direction:column;gap:12px;" data-modal-key="role_switcher">
            <div style="padding:10px 12px;border-radius:10px;background:rgba(126,152,96,0.12);border:1px solid rgba(126,152,96,0.3);font-size:12.5px;">
              <div><strong>当前激活主体：</strong><span style="color:#2E4418;font-weight:700;">${esc(charData.name || '未命名')}</span> (ID: <code>${esc(charData.id || '--')}</code> · 档案 rev <code>${esc(charData.revision ?? 0)}</code> · 构念版本 <code>v${esc(persData.version ?? 0)}</code>)</div>
              <div style="font-size:11.5px;color:#55594E;margin-top:3px;">说明：角色列表直接读取自后端 <code>/api/state → personas</code>。切换角色将调用 <code>POST /api/persona/activate</code> 并重新同步人格、情绪、表达欲、记忆、经历与会话缓存。</div>
            </div>
            <div id="modalRoleListContainer" style="display:flex;flex-direction:column;gap:8px;max-height:260px;overflow-y:auto;">
              ${catalog.length === 0
                ? '<div style="color:#6E7266;font-size:12.5px;">当前未读取到可用角色目录。</div>'
                : catalog.map(item => {
                  const isActive = item.id === charData.id;
                  return `
                    <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 14px;border-radius:10px;background:${isActive ? 'rgba(126,152,96,0.18)' : 'rgba(255,255,255,0.78)'};border:1px solid ${isActive ? '#6E8953' : 'rgba(155,153,140,0.28)'};">
                      <div style="display:flex;align-items:center;gap:10px;">
                        <img src="/public/assets/character/user_header_avatar.png" alt="${esc(item.name)}" style="width:36px;height:36px;border-radius:999px;object-fit:cover;border:1.5px solid rgba(126,152,96,0.5);" />
                        <div>
                          <div style="font-size:14px;font-weight:700;color:#262A22;">${esc(item.name || item.id)}</div>
                          <div style="font-size:11px;color:#5B6054;">ID: <code>${esc(item.id)}</code> ${item.updated_at ? `· 更新: ${esc(fmtLocal(item.updated_at))}` : ''}</div>
                        </div>
                      </div>
                      <div>
                        ${isActive
                          ? '<span class="envelope-badge live">✓ 当前激活</span>'
                          : `<button type="button" class="layout-bar-btn save" data-switch-persona="${esc(item.id)}" ${personaSwitchInFlight ? 'disabled' : ''}>切换至此角色</button>`}
                      </div>
                    </div>
                  `;
                }).join('')}
            </div>
            <div id="modalRoleSwitchFeedback" style="font-size:12px;color:#2E4418;min-height:18px;"></div>
            <div style="padding-top:8px;border-top:1px solid rgba(155,153,140,0.22);display:flex;justify-content:space-between;align-items:center;">
              <button type="button" class="layout-bar-btn save" data-open-modal="persona_manager">管理角色 · 新建、导入与导出</button>
              <button type="button" class="mini-tab-btn active" data-modal-goto-dev="role_info">前往「角色信息」管理页 →</button>
            </div>
          </div>
        `
      };
    },

    data_bus_inspector(env) {
      return {
        title: '统一数据信封与接口健康检查器 (DataEnvelope Inspector — 开发工具)',
        badgeClass: env.mode === 'mock' ? 'mock' : (env.overall_status === 'error' ? 'error' : 'live'),
        badgeText: env.mode === 'mock' ? 'MOCK 演示模式' : `LIVE (${env.ok_endpoints_count ?? 0}/${env.total_endpoints_count ?? 17} 接口正常)`,
        html: `
          <div style="display:flex;flex-direction:column;gap:12px;" data-modal-key="data_bus_inspector">
            <div style="padding:12px;border-radius:12px;background:rgba(126,152,96,0.12);border:1px solid rgba(126,152,96,0.3);">
              <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
                <div>
                  <strong>当前数据源模式：<code>${esc((env.mode || 'live').toUpperCase())}</code> (${esc(env.overall_status || 'live')})</strong>
                  <div style="font-size:12px;color:#54584C;">${esc(pollingScheduler.getStatusSummary())} · 请求代数 seq=${hydrateSeq}</div>
                </div>
                <div style="display:flex;gap:8px;">
                  <button type="button" class="mini-tab-btn ${env.mode === 'live' ? 'active' : ''}" data-switch-datasource="live">LIVE 实时原版后端</button>
                  <button type="button" class="mini-tab-btn ${env.mode === 'mock' ? 'active' : ''}" data-switch-datasource="mock">MOCK 演示数据</button>
                  <button type="button" class="mini-tab-btn active" id="btnModalRefreshLive">立即刷新原版后端</button>
                </div>
              </div>
            </div>
            <div style="padding:12px;border-radius:12px;background:rgba(255,255,255,0.75);border:1px solid rgba(155,153,140,0.24);">
              <strong>10 大领域 DataEnvelope 独立状态与时间戳核验 (UTC ISO 8601 带 Z vs 本地时间)：</strong>
              <div style="font-family:var(--font-mono);font-size:11px;max-height:220px;overflow-y:auto;margin-top:6px;">
                ${['characterProfile', 'personality', 'emotion', 'expressionDrive', 'memories', 'experiences', 'learning', 'socialGraph', 'connections', 'decisions'].map(k => {
                  const e = env[k] || {};
                  return `<div style="padding:3px 0;border-bottom:1px dashed rgba(155,153,140,0.2);"><strong>${esc(k)}</strong>: status=<code>${esc(e.status)}</code> | source=<code>${esc(e.source)}</code> | updated_at=<code>${esc(String(e.updated_at))}</code> (本地:${esc(fmtLocal(e.updated_at))}) | fetched_at=<code>${esc(e.fetched_at || '--')}</code></div>`;
                }).join('')}
              </div>
            </div>
          </div>
        `
      };
    },

    fault_injector(env) {
      return {
        title: '开发端模块级故障注入与容错测试台 (Fault Injector)',
        badgeClass: env.overall_status === 'partial' || env.overall_status === 'error' ? 'error' : 'live',
        badgeText: `容错测试 (${env.overall_status || 'live'})`,
        html: `
          <div style="display:flex;flex-direction:column;gap:12px;" data-modal-key="fault_injector">
            <div style="padding:12px;border-radius:12px;background:rgba(214,140,69,0.1);border:1px solid rgba(214,140,69,0.3);">
              <strong>逐模块接口故障注入测试 (验证局部 404/500/超时仅标红对应模块，不污染其他模块)：</strong>
              <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px;">
                <button type="button" class="mini-tab-btn" id="btnTest404Endpoint">真实请求不存在接口 (HTTP 404)</button>
                <button type="button" class="mini-tab-btn" id="btnTestTimeoutEndpoint">模拟请求超时 (TIMEOUT)</button>
                <button type="button" class="mini-tab-btn" id="btnTestDisconnectEndpoint">模拟后端断开连接 (DISCONNECTED)</button>
                <button type="button" class="mini-tab-btn" data-inject-ep="/api/affect" data-inject-type="500">注入 /api/affect 500</button>
                <button type="button" class="mini-tab-btn" data-inject-ep="/api/memories" data-inject-type="404">注入 /api/memories 404</button>
                <button type="button" class="mini-tab-btn active" data-fault-domain="all" data-fault-val="normal">恢复全部正常状态</button>
              </div>
              <div id="liveFaultTestResultBox" style="margin-top:8px;font-family:var(--font-mono);font-size:11.5px;color:#3E4238;"></div>
            </div>
          </div>
        `
      };
    },

    notif_center(env) {
      return { title: '站内通知', badgeClass: 'live', badgeText: '按需读取实际记录', html: window.NotificationView.html() };
    },

    dev_search(env) {
      const memItems = env.memories?.data?.items || [];
      const expItems = env.experiences?.data?.items || [];
      const constructs = env.personality?.data?.editable_constructs || [];
      return {
        title: '开发端跨模块检索与快速导航 (Developer Search)',
        badgeClass: 'unavailable',
        badgeText: '本地只读过滤 / 后端全文检索待接入',
        html: `
          <div style="display:flex;flex-direction:column;gap:12px;" data-modal-key="dev_search">
            <div class="card-state-banner unavailable">
              <div>
                <strong>跨表全文检索路由尚未接入 (UNAVAILABLE)</strong>
                <div>原版后端暂未提供跨 SQLite 全表的统一搜索 API；下方提供基于当前已加载内存快照（记忆 ${memItems.length} 条、经历 ${expItems.length} 轮、构念 ${constructs.length} 项）的即时只读检索与子页跳转。</div>
              </div>
            </div>
            <input type="search" id="inputModalDevSearch" placeholder="输入关键词匹配当前角色记忆、经历或 68 项构念名称..." style="width:100%;padding:8px 12px;border-radius:8px;border:1px solid rgba(130,136,118,0.45);font-size:13px;" />
            <div id="modalDevSearchResults" style="font-size:12px;max-height:180px;overflow-y:auto;padding:8px;border-radius:8px;background:rgba(255,255,255,0.72);">
              输入关键词后将在此显示匹配结果。
            </div>
            <div style="display:flex;gap:6px;flex-wrap:wrap;">
              <button type="button" class="mini-tab-btn" data-modal-goto-user="memories">前往记忆库检索 →</button>
              <button type="button" class="mini-tab-btn" data-modal-goto-dev="archives">前往原始资料档案 →</button>
              <button type="button" class="mini-tab-btn" data-modal-goto-dev="session_trace">前往会话推理轨迹 →</button>
              <button type="button" class="mini-tab-btn" data-modal-goto-dev="logs_monitor">前往请求日志监控 →</button>
            </div>
          </div>
        `
      };
    },

    color_mapping_legend(env) {
      const emoData = env.emotion?.data || {};
      const pal = emoData.palette || {};
      return {
        title: '此刻心境 V/A 维度与色彩派生规则图例 (只读)',
        badgeClass: env.mode === 'mock' ? 'mock' : 'live',
        badgeText: `${(env.mode || 'live').toUpperCase()} · /api/affect`,
        html: `
          <div style="display:flex;flex-direction:column;gap:10px;font-size:12.5px;" data-modal-key="color_mapping_legend">
            <div style="padding:10px 12px;border-radius:10px;background:rgba(255,255,255,0.78);border:1px solid rgba(155,153,140,0.25);">
              <div><strong>当前实测情绪值 (known=${String(emoData.known)})：</strong></div>
              <div style="margin-top:4px;">● 快情绪 Valence (愉悦度)：<code>${emoData.valence != null ? Number(emoData.valence).toFixed(4) : '待观察'}</code> · Arousal (唤醒度)：<code>${emoData.arousal != null ? Number(emoData.arousal).toFixed(4) : '待观察'}</code></div>
              <div>● 慢心境 Mood Valence：<code>${emoData.mood_valence != null ? Number(emoData.mood_valence).toFixed(4) : 'null'}</code> · Mood Arousal：<code>${emoData.mood_arousal != null ? Number(emoData.mood_arousal).toFixed(4) : 'null'}</code></div>
              <div>● 数据来源：<code>/api/affect</code> + <code>/api/ui3/overview → affect_2d</code> · 业务更新：<code>${esc(fmtLocal(env.emotion?.updated_at))}</code></div>
            </div>
            <div style="padding:10px 12px;border-radius:10px;background:rgba(126,152,96,0.12);border:1px solid rgba(126,152,96,0.28);">
              <div><strong>当前派生色板象限：</strong>${esc(pal.quadrant_label || '未知')} (主色 <code>${esc(pal.primary || '--')}</code> / 辅色 <code>${esc(pal.secondary || '--')}</code>)</div>
              <div style="margin-top:4px;"><strong>派生规则说明：</strong>${esc(pal.rule || '')}</div>
              <div style="font-size:11.5px;color:#55594E;margin-top:4px;">公式：<code>${esc(pal.formula || 'piecewise_quadrant_interpolation')}</code>（当 <code>known=false</code> 或 <code>valence=null</code> 时严格保持中性灰阶，绝不伪造色相）。</div>
            </div>
          </div>
        `
      };
    },

    user_thoughts(env) {
      const driveData = env.expressionDrive?.data || {};
      const motives = driveData.unfinished_motives || [];
      return {
        title: '角色表达欲与未竟动机详情 (只读)',
        badgeClass: env.mode === 'mock' ? 'mock' : 'live',
        badgeText: `${(env.mode || 'live').toUpperCase()} · /api/pmm283/expressive-drive`,
        html: `
          <div style="display:flex;flex-direction:column;gap:10px;font-size:12.5px;" data-modal-key="user_thoughts">
            <div style="padding:10px 12px;border-radius:10px;background:rgba(255,255,255,0.78);border:1px solid rgba(155,153,140,0.25);">
              <div><strong>活跃表达流状态：</strong><code>has_active_stream = ${String(driveData.has_active_stream)}</code> (${driveData.streams_count ?? 0} 条流)</div>
              <div style="margin-top:4px;">● Activation：<code>${driveData.activation != null ? (Number(driveData.activation) * 100).toFixed(1) + '%' : 'null (无流)'}</code> · Urgency：<code>${driveData.urgency != null ? (Number(driveData.urgency) * 100).toFixed(1) + '%' : 'null'}</code> · Persistence：<code>${driveData.persistence != null ? (Number(driveData.persistence) * 100).toFixed(1) + '%' : 'null'}</code></div>
              <div>● 话轮意图：<code>${esc(driveData.intent || 'null')}</code> · 校准标记：<code>${esc(driveData.calibration_status || 'uncalibrated')}</code></div>
            </div>
            <div style="padding:10px 12px;border-radius:10px;background:rgba(126,152,96,0.12);border:1px solid rgba(126,152,96,0.28);">
              <strong>未竟表达动机列表 (unfinished_motives: ${motives.length} 条)：</strong>
              <div style="margin-top:6px;display:flex;flex-direction:column;gap:6px;max-height:180px;overflow-y:auto;">
                ${motives.length === 0
                  ? '<div style="color:#666A5E;">当前 <code>unfinished_motives = []</code>（无挂起的内部表达动机）。</div>'
                  : motives.map(m => `
                    <div style="padding:6px 10px;border-radius:8px;background:rgba(255,255,255,0.8);">
                      <div><strong>ID: <code>${esc(m.motive_id)}</code></strong> · 状态: <code>${esc(m.status)}</code> · 激活度: <strong>${(Number(m.activation || 0) * 100).toFixed(1)}%</strong></div>
                      <div>话题：${esc(m.content_anchor?.topic || m.topic || '')} · 目标：${esc(m.intended_expression?.intended_goal || m.intended_goal || '')}</div>
                    </div>
                  `).join('')}
              </div>
            </div>
            <div style="display:flex;justify-content:flex-end;">
              <button type="button" class="mini-tab-btn active" data-modal-goto-user="emo_drive">前往「情绪与表达」子页推进或检视 →</button>
            </div>
          </div>
        `
      };
    },

    user_conn(env) {
      const connData = env.connections?.data || {};
      const nodes = Object.values(connData.nodes || {});
      const probeCache = pmmAdapter.connectionAdapter?.probeCache || {};
      return {
        title: '系统与模型连接状态详情 (只读)',
        badgeClass: connData.overall_healthy ? 'live' : 'unavailable',
        badgeText: connData.overall_badge || '连接状态核验',
        html: `
          <div style="display:flex;flex-direction:column;gap:10px;font-size:12px;" data-modal-key="user_conn">
            <div style="padding:8px 12px;border-radius:8px;background:rgba(126,152,96,0.12);">
              说明：严格区分 <code>healthy / reachable / running / configured / unknown / unavailable</code> 六态。未经过主动探测的模型节点保持 <code>configured (healthy=null)</code>，绝不伪造已连通。
            </div>
            <div style="display:flex;flex-direction:column;gap:6px;max-height:240px;overflow-y:auto;">
              ${nodes.map(n => `
                <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 10px;border-radius:8px;background:rgba(255,255,255,0.78);border:1px solid rgba(155,153,140,0.24);">
                  <div>
                    <strong>${esc(n.name)}</strong>
                    <div style="font-size:11px;color:#55594E;">${esc(n.status_text)} · <code>healthy=${esc(String(n.healthy))}</code></div>
                  </div>
                  ${renderConnectionStateBadge(n.status)}
                </div>
              `).join('')}
            </div>
            <div style="font-size:11px;color:#55594E;">
              最近主动探测记录：General LLM = <code>${esc(probeCache.general?.at || '未探测')}</code> | API-PMM = <code>${esc(probeCache.pmm?.at || '未探测')}</code> | QQ = <code>${esc(probeCache.qq?.at || '未探测')}</code>
            </div>
          </div>
        `
      };
    },

    dev_task_cron() {
      return { title: '后台任务调度', badgeClass: 'live', badgeText: '运行状态按需读取',
        html: `<p>后台调度独立于 QQ 收件。每次只检查原任务的触发条件，是否调用模型仍由开关、权限和预算决定。</p><button type="button" class="viz-button" data-dev-nav="run_state">查看后台状态与自主候选设置</button>` };
    }
  };

  ['dev_task_1', 'dev_task_2', 'dev_task_3'].forEach(taskKey => {
    MODAL_HANDLERS[taskKey] = function (env) {
      const jobs = env.learning?.data?.jobs || [];
      const memData = env.memories?.data || {};
      return {
        title: `后台学习与记忆任务详情 (${taskKey})`,
        badgeClass: env.mode === 'mock' ? 'mock' : 'live',
        badgeText: `${jobs.length} 项学习任务`,
        html: `
          <div style="display:flex;flex-direction:column;gap:10px;font-size:12.5px;" data-modal-key="${esc(taskKey)}">
            <div><strong>当前学习与蒸馏任务队列：</strong></div>
            ${jobs.length === 0
              ? '<div style="color:#666A5E;">当前队列为空 (<code>jobs = []</code>)。可前往「数据导入」经过预览与授权创建任务。</div>'
              : jobs.map(j => `
                <div style="padding:8px 10px;border-radius:8px;background:rgba(255,255,255,0.78);border:1px solid rgba(155,153,140,0.25);">
                  <div><strong>${esc(j.title)}</strong> (<code>${esc(j.id)}</code>) · 状态: <code>${esc(j.status)}</code> · 进度: <strong>${Number(j.progress ?? 0)}%</strong></div>
                  <div style="font-size:11px;color:#55594E;">目标域: <code>${esc(j.target)}</code> · 阶段: ${esc(j.phase)}</div>
                </div>
              `).join('')}
            <div style="padding:8px 10px;border-radius:8px;background:rgba(126,152,96,0.12);">
              SQLite 长期记忆索引状态：当前共 <strong>${memData.total_count ?? 0}</strong> 条记忆条目。
            </div>
            <div style="display:flex;justify-content:flex-end;">
              <button type="button" class="mini-tab-btn active" data-modal-goto-dev="distill_task">前往「蒸馏任务」子页管理 →</button>
            </div>
          </div>
        `
      };
    };
  });

  function openModal(key) {
    const backdrop = document.getElementById('shellModalBackdrop');
    const titleEl = document.getElementById('shellModalTitle');
    const bodyEl = document.getElementById('shellModalBody');
    const badgeEl = document.getElementById('shellModalBadge');
    if (!backdrop || !titleEl || !bodyEl) return;

    currentOpenModalKey = key || 'unknown';
    const env = activeEnvelopes || {};
    const handler = MODAL_HANDLERS[key];

    if (!handler) {
      console.warn('[UI Shell Phase 2.3.1] Unregistered modal key:', key);
      titleEl.textContent = `功能入口尚未接入 (${key})`;
      if (badgeEl) {
        badgeEl.className = 'envelope-badge unavailable';
        badgeEl.textContent = 'UNAVAILABLE · 尚未接入';
      }
      bodyEl.innerHTML = `
        <div class="card-state-banner unavailable" data-modal-key="${esc(key)}">
          <div>
            <strong>功能入口 <code>${esc(key)}</code> 尚未接入后端实现</strong>
            <div>该入口未绑定对应的业务处理器，已按 Phase 2.3.1 规范拦截，绝不误跳入调试面板。</div>
          </div>
        </div>
      `;
      backdrop.hidden = false;
      return;
    }

    const spec = handler(env);
    titleEl.textContent = spec.title;
    if (badgeEl) {
      badgeEl.className = `envelope-badge ${spec.badgeClass || 'live'}`;
      badgeEl.textContent = spec.badgeText || 'LIVE';
    }
    bodyEl.innerHTML = spec.html;
    backdrop.hidden = false;
  }

  function closeModal() {
    currentOpenModalKey = null;
    const backdrop = document.getElementById('shellModalBackdrop');
    if (backdrop) backdrop.hidden = true;
  }

  // ---------------------------------------------------------------------------
  // Event Delegation, Real HTML5 Drag & Drop, and Real Backend Write Flows
  // ---------------------------------------------------------------------------
  function initEventListeners() {
    document.addEventListener('submit', async e => {
      if (e.target.id === 'experienceLearningForm') {
        e.preventDefault();
        const form=e.target, feedback=document.getElementById('experienceLearningFeedback');
        if (!guardWrite('experience_policy', { endpoint:'/api/learning/policy', feedbackEl:feedback }).allowed) return;
        const policy=JSON.parse(JSON.stringify(activeEnvelopes.learning?.data?.policy || {}));
        if (!policy.domains?.self || !policy.experience) { feedback.textContent='请等待学习设置读取完成。'; return; }
        const fields=new FormData(form), enabled=fields.has('enabled'), persona=currentPersonaId();
        policy.experience.enabled=enabled; policy.experience.new_memories=Number(fields.get('new_memories'));
        Object.assign(policy.domains.self,{enabled,mode:fields.get('mode'),strength:Number(fields.get('strength'))/100});
        const response=await pmmAdapter.postJson('/api/learning/policy',{persona_id:persona,expected_version:policy.version,policy});
        if (persona!==currentPersonaId()) return;
        feedback.textContent=response.status==='success'?'已保存；按新增完整经历触发整理。':response.error || '保存失败';
        if (response.status==='success') await tryHydrateFromLiveServer(activeScope,{preserveSubpageDom:true});
        return;
      }
      const form = e.target.closest('.connection-form');
      if (!form) return;
      e.preventDefault();
      await window.ModelSettings.save(form, false, connectionServices());
    });
    // P1-01: Real HTML5 Drag & Drop for Cards in Layout Edit Mode
    document.addEventListener('dragstart', e => {
      if (!layoutEditActive) {
        e.preventDefault();
        return;
      }
      const card = e.target.closest('[data-layout-card]');
      if (!card) return;
      draggedCardId = card.dataset.layoutCard;
      card.classList.add('dragging-card');
      if (e.dataTransfer) {
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', draggedCardId);
      }
    });

    document.addEventListener('dragover', e => {
      if (!layoutEditActive || !draggedCardId) return;
      const targetCard = e.target.closest('[data-layout-card]');
      const srcCard = document.querySelector(`[data-layout-card="${draggedCardId}"]`);
      if (!targetCard || !srcCard || targetCard === srcCard) return;
      // Only allow dragging within the same grid container
      if (targetCard.parentElement !== srcCard.parentElement) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
      targetCard.classList.add('drop-target-hover');
    });

    document.addEventListener('dragleave', e => {
      const targetCard = e.target.closest('[data-layout-card]');
      if (targetCard) targetCard.classList.remove('drop-target-hover');
    });

    document.addEventListener('drop', e => {
      if (!layoutEditActive || !draggedCardId) return;
      const targetCard = e.target.closest('[data-layout-card]');
      const srcCard = document.querySelector(`[data-layout-card="${draggedCardId}"]`);
      document.querySelectorAll('[data-layout-card]').forEach(c => c.classList.remove('drop-target-hover', 'dragging-card'));
      if (!targetCard || !srcCard || targetCard === srcCard || targetCard.parentElement !== srcCard.parentElement) {
        draggedCardId = null;
        return;
      }
      e.preventDefault();
      e.stopPropagation();
      swapCardsInGrid(draggedCardId, targetCard.dataset.layoutCard);
      suppressClickUntil = Date.now() + 200;
      draggedCardId = null;
    });

    document.addEventListener('dragend', () => {
      draggedCardId = null;
      document.querySelectorAll('[data-layout-card]').forEach(c => c.classList.remove('drop-target-hover', 'dragging-card'));
    });

    // Main Click Delegation
    document.addEventListener('click', async e => {
      if (await window.PersonaManager.click(e.target, personaManagementServices())) return;
      const experienceControl=e.target.closest('[data-experience-control]');
      if (experienceControl) {
        const feedback=document.getElementById('experienceLearningFeedback'), endpoint='/api/learning/experiences/control';
        if (!guardWrite('experience_control',{endpoint,feedbackEl:feedback}).allowed) return;
        experienceControl.disabled=true;
        try {
          const persona=currentPersonaId(), response=await pmmAdapter.postJson(endpoint,{persona_id:persona,action:experienceControl.dataset.experienceControl});
          if (persona!==currentPersonaId()) return;
          feedback.textContent=response.status==='success'?'操作已保存。':response.error || '操作失败';
          if (response.status==='success') await tryHydrateFromLiveServer(activeScope,{preserveSubpageDom:true});
        } finally { experienceControl.disabled=false; }
        return;
      }
      const connectionProbe = e.target.closest('[data-connection-probe]');
      if (connectionProbe) { await window.ModelSettings.save(connectionProbe.closest('form'), connectionProbe.dataset.operation || 'connect', connectionServices()); return; }
      const scopeChoice = e.target.closest('[data-relationship-scope]');
      if (scopeChoice) { await selectRelationshipScope(scopeChoice.dataset.relationshipScope); return; }
      if (e.target.closest('#memoryGraphCanvas') && window.MemoryGraphView.isDragging()) return;
      if (e.target.closest('#relationGraphCanvas') && window.RelationView.suppressClick()) return;
      if ((currentMode === 'developer' || currentUserNav === 'settings') && e.target.closest('.dev-viz-page, .psych-viz-page') &&
          (window.PmmFlow.handleClick(e.target) || window.DeveloperViews.handleClick(e.target))) {
        if (e.target.closest('[data-wb-feature]')) {
          pendingDispositionEdit = null;
          const confirm = document.getElementById('dispositionConfirmBox'); if (confirm) confirm.style.display = 'none';
        }
        renderSubpage(currentMode, currentMode === 'developer' ? currentDevNav : currentUserNav, { preserveSubpageDom: true });
        return;
      }
      if (e.target.closest('[data-viz-action="memory-locate"]') && window.MemoryGraphView.handleClick(e.target)) {
        renderActiveSubpage();
        return;
      }
      if (e.target.closest('[data-sample-action]')) {await window.SampleView.handleClick(e.target,sampleServices());return;}
      if (e.target.closest('[data-token-action], [data-reasoning-load], [data-scheduler-action], [data-research-action], [data-notification-action]')) {
        const epoch = contextEpoch, owner = currentPersonaId(), mode = currentMode, nav = currentMode === 'developer' ? currentDevNav : currentUserNav;
        const services = { adapter: pmmAdapter, context: visualContext(), render: renderActiveSubpage,
          guard: endpoint => guardWrite('background_settings', { endpoint }).allowed,
          remount: () => renderSubpage(currentMode, currentMode === 'developer' ? currentDevNav : currentUserNav, { preserveSubpageDom: false }),
          isCurrent: () => epoch === contextEpoch && owner === currentPersonaId() && dataSourceMode === 'live' && mode === currentMode && nav === (currentMode === 'developer' ? currentDevNav : currentUserNav) };
        if (e.target.closest('[data-token-action]')) await window.TokenView.handleClick(e.target, services);
        else if (e.target.closest('[data-research-action]')) await window.ResearchView.handleClick(e.target, services);
        else if (e.target.closest('[data-notification-action]')) await window.NotificationView.handleClick(e.target, services);
        else if (e.target.closest('[data-scheduler-action]')) await window.SchedulerView.handleClick(e.target, services);
        else await window.ReasoningView.handleClick(e.target, services);
        return;
      }
      const historyAction = e.target.closest('[data-viz-action^="drive-history-"]');
      if (historyAction) {
        const epoch = contextEpoch, owner = currentPersonaId();
        const current = () => epoch === contextEpoch && owner === currentPersonaId() && dataSourceMode === 'live';
        historyAction.disabled = true;
        await window.DriveView.loadHistory(historyAction.dataset.actionId, historyAction.dataset.vizAction === 'drive-history-more', pmmAdapter, current);
        if (current()) window.PsychViz.refresh(activeEnvelopes, `${owner}:${dataSourceMode}:${epoch}`);
        historyAction.disabled = false;
        return;
      }
      const detailTrigger = e.target.closest('[data-psych-detail]');
      if (detailTrigger) {
        const { psychDetail: kind, detailId: id, detailDomain: domain } = detailTrigger.dataset;
        if (kind === 'relation-person') { window.RelationView.select(id); renderActiveSubpage(); }
        if (kind.startsWith('memory-')) {
          window.MemoryGraphView.selectDetail(kind, id);
          renderActiveSubpage();
        }
        const resolve = envelopes => resolvePsychDetail(kind, id, domain, envelopes);
        window.PsychViz.show(resolve(activeEnvelopes), detailTrigger, resolve, `${currentPersonaId()}:${dataSourceMode}:${contextEpoch}`);
        return;
      }
      if (e.target.closest('.psych-viz-page') &&
          (window.PersonalityView.handleClick(e.target, activeEnvelopes) || window.EmotionView.handleClick(e.target, activeEnvelopes) || window.DriveView.handleClick(e.target) || window.MemoryGraphView.handleClick(e.target) || window.LifeViews.handleClick(e.target) || window.RelationView.handleClick(e.target))) {
        renderActiveSubpage();
        return;
      }
      if (Date.now() < suppressClickUntil && !e.target.closest("#layoutEditFloatingBar") && !e.target.closest(".layout-card-edit-overlay")) {
        e.stopPropagation();
        return;
      }

      const modeTab = e.target.closest('[data-switch-mode]');
      if (modeTab) {
        switchMode(modeTab.dataset.switchMode);
        return;
      }

      const dsBtn = e.target.closest('[data-switch-datasource]');
      if (dsBtn) {
        await switchDataSourceMode(dsBtn.dataset.switchDatasource);
        return;
      }

      const pollBtn = e.target.closest('[data-poll-ms]');
      if (pollBtn) {
        pollingScheduler.setIntervalMs(Number(pollBtn.dataset.pollMs));
        return;
      }

      if (e.target.closest('#btnManualPollNow') || e.target.closest('#btnModalRefreshLive')) {
        await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: true });
        return;
      }

      const retryBtn = e.target.closest('[data-retry-domain]');
      if (retryBtn) {
        const dom = retryBtn.dataset.retryDomain;
        domainFaults[dom] = 'normal';
        pmmAdapter.clearEndpointFaultOverrides();
        await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: true });
        return;
      }

      const injectBtn = e.target.closest('[data-inject-ep]');
      if (injectBtn) {
        const ep = injectBtn.dataset.injectEp;
        const fType = injectBtn.dataset.injectType;
        pmmAdapter.setEndpointFaultOverride(ep, fType);
        await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: true });
        return;
      }

      if (e.target.closest('#btnClearAllEndpointFaults')) {
        pmmAdapter.clearEndpointFaultOverrides();
        setDomainFault('all', 'normal');
        await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: true });
        return;
      }

      if (e.target.closest('#btnTest404Endpoint') || e.target.closest('#btnSubpageProbe404')) {
        const res = await pmmAdapter.fetchJson('/api/non_existent_phase23_route_probe', 4000);
        const box = document.getElementById('liveFaultTestResultBox') || document.getElementById('apiToolsFeedbackBox');
        if (box) {
          box.innerHTML = `<div style="color:#A63A2B;">[真实 404 测试完成] 请求 <code>GET /api/non_existent_phase23_route_probe</code> → status=${esc(res.status)}, code=${esc(res.error_code)}, message="${esc(res.error)}"</div>`;
        }
        pmmAdapter.setEndpointFaultOverride('/api/pmm283/expressive-drive', '404');
        await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: true });
        return;
      }

      if (e.target.closest('#btnTestTimeoutEndpoint')) {
        const res = await pmmAdapter.fetchJson('/api/state', 1);
        const box = document.getElementById('liveFaultTestResultBox');
        if (box) {
          box.innerHTML = `<div style="color:#B85D19;">[超时测试完成] AbortController 1ms 触发中断 → status=${esc(res.status)}, error="${esc(res.error)}"</div>`;
        }
        pmmAdapter.setEndpointFaultOverride('/api/memories', 'timeout');
        await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: true });
        return;
      }

      if (e.target.closest('#btnTestDisconnectEndpoint')) {
        const res = await pmmAdapter.fetchJson('/api/state', 1500, 'http://127.0.0.1:19999');
        const box = document.getElementById('liveFaultTestResultBox');
        if (box) {
          box.innerHTML = `<div style="color:#B83B2A;">[断连测试完成] 请求不可达端口 127.0.0.1:19999 → status=${esc(res.status)}, error="${esc(res.error)}"</div>`;
        }
        setDomainFault('emotion', 'network_error');
        return;
      }

      // -----------------------------------------------------------------------
      // P0-01: Parlor Session Creation, Switching & Real Chat Message Sending
      // -----------------------------------------------------------------------
      if (e.target.closest('#btnFillParlorDemoText')) {
        const inp = document.getElementById('inputParlorMessage');
        const t = window.ParlorView.thread(parlorContext());
        if (inp && !t.active) {
          inp.value = '你好，今天在夏日廊下看到远处的云，你在想什么呢？';
          t.draft = inp.value; inp.focus();
        }
        return;
      }
      if (e.target.closest('#btnNewParlorSession')) {
        const ctx = parlorContext(), t = window.ParlorView.thread(ctx);
        if (t.creating) return;
        const statusEl = document.getElementById('parlorSendStatus');
        if (!guardWrite('parlor_create_session', { endpoint: '/api/session', feedbackEl: statusEl }).allowed) return;
        t.creating = true; refreshParlorView();
        try {
          const res = await pmmAdapter.createSession();
          if (ctx.epoch !== contextEpoch || ctx.personaId !== currentPersonaId() || ctx.source !== dataSourceMode) return;
          if (!res.ok || !res.session_id) { t.notice = `创建会话失败：${res.error || '未取得会话标识'}`; return; }
          parlorSessionId = res.session_id;
          parlorSessionsByPersona[ctx.personaId] = res.session_id;
          parlorMessagesBySession[res.session_id] = [];
          window.ParlorView.thread(parlorContext()).registered = true;
          window.PsychViz.close();
          refreshParlorView();
        } catch (error) { t.notice = `创建会话失败：${error.message || error}`; }
        finally { t.creating = false; if (ctx.epoch === contextEpoch) refreshParlorView(); }
        return;
      }
      if (e.target.closest('#btnRefreshParlorMessages')) { await readParlorMessages(); return; }
      if (e.target.closest('#btnSendParlorChat')) { await runParlorChat(false); return; }
      if (e.target.closest('#btnResumeParlorJob')) { await runParlorChat(true); return; }

      // -----------------------------------------------------------------------
      // P0-02: Construct Disposition Preview & Optimistic Concurrency Save
      // -----------------------------------------------------------------------
      if (e.target.closest('#btnPreviewDisposition')) {
        const fSel = document.getElementById('selectDispositionField');
        const vInp = document.getElementById('inputDispositionVal');
        const nInp = document.getElementById('inputDispositionNote');
        const cBox = document.getElementById('dispositionConfirmBox');
        const fb = document.getElementById('dispositionFeedback');
        if (!fSel || !vInp || !cBox) return;

        const opt = fSel.options[fSel.selectedIndex];
        const fid = fSel.value;
        const nameZh = opt ? opt.dataset.nameZh : fid;
        const oldEst = opt ? opt.dataset.curEst : 'null';
        const oldSrc = opt ? opt.dataset.curSrc : 'unknown';
        if (!vInp.value.trim()) { if (fb) fb.textContent = '请先输入要设定的目标值。'; return; }
        const newEst = Number(vInp.value);
        const curVer = activeEnvelopes.personality?.data?.version ?? 0;

        if (!isFinite(newEst) || newEst < 0 || newEst > 1) {
          if (fb) {
            fb.style.color = '#B83B2A';
            fb.textContent = '✗ 设定值必须在 0.00 到 1.00 之间。';
          }
          return;
        }

        pendingDispositionEdit = {
          persona_id: currentPersonaId(),
          feature_id: fid,
          expected_version: curVer,
          estimate: newEst,
          source_type: 'owner_seed',
          timeframe: fid.startsWith('panas.') ? 'generally' : null,
          note: nInp ? nInp.value.trim() : ''
        };

        cBox.style.display = 'block';
        cBox.innerHTML = `
          <div style="font-weight:700;color:#2E4418;margin-bottom:4px;">请确认长期构念人工设定变更：</div>
          <div>目标角色：<strong>${esc(activeEnvelopes.characterProfile?.data?.name)}</strong></div>
          <div>调整项目：<strong>${esc(nameZh)}</strong></div>
          <div>当前值 ${esc(oldEst)} → <strong>设定值 ${newEst.toFixed(2)}</strong>（人工设定）</div>
          <div>按当前第 ${curVer} 版保存${fid.startsWith('panas.') ? '，表示通常的情绪倾向' : ''}。</div>
          <div style="display:flex;gap:8px;margin-top:8px;">
            <button type="button" class="layout-bar-btn save" id="btnConfirmSaveDisposition">确认提交写入</button>
            <button type="button" class="layout-bar-btn cancel" id="btnCancelDispositionPreview">取消</button>
          </div>
        `;
        return;
      }

      if (e.target.closest('#btnCancelDispositionPreview')) {
        pendingDispositionEdit = null;
        const cBox = document.getElementById('dispositionConfirmBox');
        if (cBox) cBox.style.display = 'none';
        return;
      }

      if (e.target.closest('#btnConfirmSaveDisposition') || e.target.closest('#btnSaveDisposition')) {
        if (e.target.closest('#btnSaveDisposition')) { document.getElementById('btnPreviewDisposition')?.click(); return; }
        if (!pendingDispositionEdit) return;
        const fb = document.getElementById('dispositionFeedback');
        if (!guardWrite('disposition_save', { endpoint: '/api/traits/disposition', feedbackEl: fb }).allowed) {
          return;
        }
        let payload = pendingDispositionEdit;
        if (!payload) {
          const fSel = document.getElementById('selectDispositionField');
          const vInp = document.getElementById('inputDispositionVal');
          const nInp = document.getElementById('inputDispositionNote');
          if (!fSel || !vInp) return;
          const fid = fSel.value;
          payload = {
            persona_id: currentPersonaId(),
            feature_id: fid,
            expected_version: activeEnvelopes.personality?.data?.version ?? 0,
            estimate: Number(vInp.value),
            source_type: 'owner_seed',
            timeframe: fid.startsWith('panas.') ? 'generally' : null,
            note: nInp ? nInp.value.trim() : ''
          };
        }
        const res = await pmmAdapter.saveConstructDisposition(payload);
        if (res.ok) {
          pendingDispositionEdit = null;
          const cBox = document.getElementById('dispositionConfirmBox');
          if (cBox) cBox.style.display = 'none';
          await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: false });
          const fbAfter = document.getElementById('dispositionFeedback');
          if (fbAfter) {
            fbAfter.style.color = '#2E4418';
            fbAfter.textContent = `✓ 主人设定 (owner_seed) 已成功写入：${payload.feature_id} = ${payload.estimate}，trait_profile.version 已递增至 v${res.new_version}。`;
          }
        } else if (fb) {
          fb.style.color = '#B83B2A';
          fb.textContent = `✗ 写入失败：${res.error || ''}`;
        }
        return;
      }

      // -----------------------------------------------------------------------
      // P0-03: Expressive Drive Advance vs. Planned Motive Creation
      // -----------------------------------------------------------------------
      if (e.target.closest('#btnTriggerDriveAdvance')) {
        const fb = document.getElementById('driveAdvanceFeedback');
        const button = e.target.closest('#btnTriggerDriveAdvance');
        if (button.disabled) return;
        if (!guardWrite('drive_advance', { endpoint: '/api/pmm283/expressive-drive/advance', feedbackEl: fb }).allowed) {
          return;
        }
        const target = window.DriveView.getAdvanceTarget(activeEnvelopes, visualContext());
        if (!target) { if (fb) fb.textContent = '当前没有可推进的有效会话数据，请先刷新。'; return; }
        const requestContext = `${currentPersonaId()}:${dataSourceMode}:${contextEpoch}`;
        const sameContext = () => requestContext === `${currentPersonaId()}:${dataSourceMode}:${contextEpoch}`;
        const selector = document.getElementById('selectDriveStream');
        button.disabled = true;
        if (selector) selector.disabled = true;
        if (fb) fb.textContent = '正在推进所选会话的表达状态…';
        try {
          const res = await pmmAdapter.advanceExpressiveDrive({ scope: target.scope, person: target.person, session_id: target.session_id, commit: true });
          if (!sameContext()) return;
          if (res.ok && res.evaluation && target.context) window.DriveView.recordEvaluation(res.evaluation, target, res.envelope);
          await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: true });
          if (!sameContext()) return;
          const fbAfter = document.getElementById('driveAdvanceFeedback');
          if (fbAfter) fbAfter.textContent = res.ok && res.evaluation
            ? `已推进 ${target.person} 的表达状态。${res.evaluation.proactive_eligible === true ? '本次允许发起表达' : res.evaluation.proactive_eligible === false ? '本次暂不发起表达' : '门控结果未提供'}；此操作不发送消息。`
            : `推进失败：${res.error || '未取得后端结果'}`;
        } catch (error) {
          if (sameContext() && fb?.isConnected) fb.textContent = `推进失败：${error.message || '请稍后重试'}`;
        } finally {
          if (button.isConnected) button.disabled = false;
          if (selector?.isConnected) selector.disabled = false;
        }
        return;
      }

      if (e.target.closest('#btnPlannedRegisterMotive')) {
        const notice = document.getElementById('plannedMotiveNotice');
        if (notice) {
          notice.style.color = '#983225';
          notice.textContent = '【PLANNED / 暂未接入】原版 v2.8.3 后端暂未实现手工注册表达动机路由，已拦截伪提交并登记于 FUTURE_FEATURES_BACKLOG.md (F-06)。';
        }
        return;
      }

      // -----------------------------------------------------------------------
      // P0-04: Two-Step Learning Preview -> Explicit Authorize -> Create
      // -----------------------------------------------------------------------
      if (e.target.closest('#btnFillLearnDemoText')) {
        const txt = document.getElementById('inputLearnSampleText');
        if (txt) {
          txt.value = '我在夏日午后喜欢安静观察廊下风铃与远处云层变化，习惯认真倾听。\n遇到复杂问题时会先梳理脉络再回答，不迎合也不敷衍。';
          txt.focus();
        }
        return;
      }

      if (e.target.closest('#btnPreviewLearningJob')) {
        const targetSel = document.getElementById('selectLearnTarget');
        const intentSel = document.getElementById('selectLearnIntent');
        const scopeInp = document.getElementById('inputLearnScope');
        const textInp = document.getElementById('inputLearnSampleText');
        const pBox = document.getElementById('learningPreviewConfirmBox');
        const fb = document.getElementById('learnJobCreateFeedback');

        if (!guardWrite('learning_preview', { endpoint: '/api/learning/preview', feedbackEl: fb }).allowed) {
          return;
        }

        const rawLines = (textInp ? textInp.value : '').split('\n').map(s => s.trim()).filter(Boolean);
        if (rawLines.length === 0) {
          if (fb) {
            fb.style.color = '#B83B2A';
            fb.textContent = '✗ 原文输入不能为空，请先输入至少 1 条真人示范原文。';
          }
          return;
        }

        const scopeVal = (scopeInp && scopeInp.value.trim()) || 'self:imported';
        const records = rawLines.map((line, idx) => ({
          id: `rec_${Date.now()}_${idx + 1}`,
          text: line,
          speaker: 'owner',
          source: 'human',
          scope: scopeVal
        }));

        const res = await pmmAdapter.previewLearningJob({
          persona_id: currentPersonaId(),
          target: targetSel ? targetSel.value : 'self',
          source: 'import',
          scopes: [scopeVal],
          records
        });

        if (!res.ok || !res.preview) {
          if (fb) {
            fb.style.color = '#B83B2A';
            fb.textContent = `✗ 预览校验未通过：${res.error || ''}`;
          }
          return;
        }

        pendingLearningPreview = {
          request_body: res.request_body,
          preview: res.preview,
          intent: intentSel ? intentSel.value : 'review'
        };

        if (pBox) {
          const pv = res.preview;
          pBox.style.display = 'block';
          pBox.innerHTML = `
            <div style="font-weight:700;color:#2E4418;margin-bottom:4px;">学习任务原文预览回执：</div>
            <div>● 目标角色：<strong>${esc(activeEnvelopes.characterProfile?.data?.name)}</strong> · 学习目标域：<code>${esc(pv.target)}</code> · 模式：<code>${esc(pendingLearningPreview.intent)}</code></div>
            <div>● 有效新原文数：<strong>${esc(pv.source_count)}</strong> 条（重复跳过 ${esc(pv.duplicate_count)} 条 · 排除 ${esc(pv.excluded_count)} 条）</div>
            <div>● 原文摘要指纹 (source_digest)：<code>${esc(String(pv.source_digest).slice(0, 24))}…</code> · 策略版本：<code>v${esc(pv.policy_version)}</code></div>
            <div>● 预估调用次数：<code>${esc(pv.estimated_calls)}</code> 次 · 预估 Token：<code>${esc(pv.estimated_tokens)}</code></div>
            ${pv.self_source_rule ? `<div style="color:#5B703E;margin-top:2px;">● 安全规则：${esc(pv.self_source_rule)}</div>` : ''}
            <label style="display:flex;align-items:center;gap:6px;margin-top:8px;font-weight:700;cursor:pointer;">
              <input type="checkbox" id="chkAuthorizeLearningJob" />
              <span>我已核对上述具体原文范围与目标角色，明确授权创建此学习任务 (authorized: true)</span>
            </label>
            <div style="display:flex;gap:8px;margin-top:8px;">
              <button type="button" class="layout-bar-btn save" id="btnConfirmCreateLearningJob">2. 确认授权并创建任务</button>
              <button type="button" class="layout-bar-btn cancel" id="btnCancelLearningPreview">取消</button>
            </div>
          `;
        }
        return;
      }

      if (e.target.closest('#btnCancelLearningPreview')) {
        pendingLearningPreview = null;
        const pBox = document.getElementById('learningPreviewConfirmBox');
        if (pBox) pBox.style.display = 'none';
        return;
      }

      if (e.target.closest('#btnConfirmCreateLearningJob')) {
        const chk = document.getElementById('chkAuthorizeLearningJob');
        const fb = document.getElementById('learnJobCreateFeedback');
        if (!guardWrite('learning_create', { endpoint: '/api/learning/create', feedbackEl: fb }).allowed) {
          return;
        }
        if (!pendingLearningPreview) {
          if (fb) fb.textContent = '✗ 请先执行步骤 1 预览。';
          return;
        }
        if (!chk || !chk.checked) {
          if (fb) {
            fb.style.color = '#B83B2A';
            fb.textContent = '✗ 请先勾选“明确授权创建此学习任务”复选框后再提交。';
          }
          return;
        }
        const cRes = await pmmAdapter.createAuthorizedLearningJob(
          pendingLearningPreview.request_body,
          pendingLearningPreview.preview,
          true,
          pendingLearningPreview.intent
        );
        if (cRes.ok && cRes.job) {
          pendingLearningPreview = null;
          const pBox = document.getElementById('learningPreviewConfirmBox');
          if (pBox) pBox.style.display = 'none';
          const textInp = document.getElementById('inputLearnSampleText');
          if (textInp) textInp.value = '';
          await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: true });
          if (fb) {
            fb.style.color = '#2E4418';
            fb.textContent = `✓ 学习任务已成功创建 (job_id=${cRes.job.id}, status=${cRes.job.status})！可前往「蒸馏任务」查看与控制。`;
          }
        } else if (fb) {
          fb.style.color = '#B83B2A';
          fb.textContent = `✗ 创建失败：${cRes.error || ''}`;
        }
        return;
      }

      // Modal Quick Navigation Shortcuts
      const modalGotoDev = e.target.closest('[data-modal-goto-dev]');
      if (modalGotoDev) {
        const target = modalGotoDev.dataset.modalGotoDev;
        closeModal();
        switchMode('developer');
        switchDevNav(target);
        return;
      }
      const modalGotoUser = e.target.closest('[data-modal-goto-user]');
      if (modalGotoUser) {
        const target = modalGotoUser.dataset.modalGotoUser;
        closeModal();
        switchMode('user');
        await switchUserNav(target);
        return;
      }

      // Learning Job Control (pause / resume / cancel / rollback) — Centralized guardWrite + High-Risk Confirmation
      if (e.target.closest('#btnCancelTraitReview')) {
        pendingTraitReview = null; const box = document.getElementById('traitReviewConfirmBox'); if (box) box.hidden = true; return;
      }
      if (e.target.closest('#btnPreviewTraitReview') || e.target.closest('#btnPrepareTraitApply')) {
        const feedback = document.getElementById('traitReviewFeedback');
        if (!guardWrite('trait_review_preview', { endpoint: '/api/traits/review', feedbackEl: feedback }).allowed) return;
        const persona = currentPersonaId(), epoch = contextEpoch;
        const applyRequested = Boolean(e.target.closest('#btnPrepareTraitApply'));
        const result = await pmmAdapter.postJson('/api/traits/review', { persona_id: persona, apply: false });
        if (persona !== currentPersonaId() || epoch !== contextEpoch) return;
        if (result.status !== 'success') { if (feedback) feedback.textContent = `读取复核结果失败：${result.error || '未返回结果'}`; return; }
        await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: true });
        if (persona !== currentPersonaId() || epoch !== contextEpoch) return;
        const candidates = Array.isArray(result.data?.candidates) ? result.data.candidates : [];
        const eligible = candidates.filter(c => c.eligible === true);
        const box = document.getElementById('traitReviewConfirmBox');
        const fb = document.getElementById('traitReviewFeedback');
        if (fb) fb.textContent = `已读取 ${candidates.length} 项候选，${eligible.length} 项被后端标记符合条件；尚未执行晋升。`;
        pendingTraitReview = null;
        if (applyRequested && box) {
          pendingTraitReview = { persona_id: persona, epoch, version: result.data?.trait_version ?? activeEnvelopes.personality?.data?.version };
          box.hidden = false;
          box.innerHTML = `<div class="wb-review-confirm"><h4>核对候选晋升</h4><p>当前角色：${esc(activeEnvelopes.characterProfile?.data?.name)}。将交由原有后端复核规则处理符合条件的候选，并可能修改正式人格。Active 模式的限制仍由原后端执行。</p><ul>${eligible.map(c => `<li>${esc(c.feature_id)} · ${esc(c.independent_events ?? '未知')} 个独立事件</li>`).join('') || '<li>当前没有符合条件的候选。</li>'}</ul><button type="button" class="viz-button" id="btnConfirmTraitApply" ${eligible.length ? '' : 'disabled'}>确认按原规则晋升</button><button type="button" class="viz-button" id="btnCancelTraitReview">取消</button></div>`;
        }
        return;
      }
      if (e.target.closest('#btnConfirmTraitApply')) {
        const pending = pendingTraitReview, feedback = document.getElementById('traitReviewFeedback');
        if (!pending || pending.persona_id !== currentPersonaId() || pending.epoch !== contextEpoch) return;
        if (pending.version !== activeEnvelopes.personality?.data?.version) { if (feedback) feedback.textContent = '人格版本已变化，请重新核对候选。'; pendingTraitReview = null; return; }
        if (!guardWrite('trait_review_apply', { endpoint: '/api/traits/review', feedbackEl: feedback }).allowed) return;
        pendingTraitReview = null;
        const button = e.target.closest('#btnConfirmTraitApply'); button.disabled = true;
        const result = await pmmAdapter.postJson('/api/traits/review', { persona_id: pending.persona_id, apply: true });
        if (pending.persona_id !== currentPersonaId() || pending.epoch !== contextEpoch) return;
        await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: true });
        if (pending.persona_id !== currentPersonaId() || pending.epoch !== contextEpoch) return;
        const box = document.getElementById('traitReviewConfirmBox'); if (box) box.hidden = true;
        const fb = document.getElementById('traitReviewFeedback');
        if (fb) fb.textContent = result.status === 'success' ? `后端复核完成，实际晋升 ${result.data?.promoted ?? '未提供数量'} 项。` : `未完成晋升：${result.error || '未取得结果'}`;
        return;
      }
      const jobCtrlBtn = e.target.closest('[data-job-control]');
      if (jobCtrlBtn) {
        const action = jobCtrlBtn.dataset.jobControl;
        const jobId = jobCtrlBtn.dataset.jobId;
        const fb = document.getElementById('distillControlFeedback');
        const guard = guardWrite(`learning_control_${action}`, { endpoint: '/api/learning/control', targetId: jobId, feedbackEl: fb });
        if (!guard.allowed) return;

        if (action === 'cancel' || action === 'rollback') {
          const cBox = document.getElementById('distillHighRiskConfirmBox');
          pendingHighRiskConfirm = { type: 'learning_control', jobId, action, persona_id: currentPersonaId() };
          if (cBox) {
            cBox.style.display = 'block';
            cBox.innerHTML = `
              <div style="font-weight:700;color:#982B1E;margin-bottom:4px;">⚠ 高风险学习任务操作二次确认 (${esc(action.toUpperCase())})：</div>
              <div>● 目标任务 ID：<code>${esc(jobId)}</code> · 所属角色：<strong>${esc(activeEnvelopes.characterProfile?.data?.name)}</strong> (<code>${esc(currentPersonaId())}</code>)</div>
              <div>● 动作后果：${action === 'cancel' ? '取消该学习任务并停止后续蒸馏执行' : '回滚该任务已应用的构念变更'}</div>
              <div style="display:flex;gap:8px;margin-top:8px;">
                <button type="button" class="layout-bar-btn save" id="btnConfirmDistillHighRisk" style="background:#B83B2A;">确认执行 ${esc(action)}</button>
                <button type="button" class="layout-bar-btn cancel" id="btnCancelDistillHighRisk">取消</button>
              </div>
            `;
          }
          return;
        }

        const res = await pmmAdapter.postJson('/api/learning/control', {
          persona_id: currentPersonaId(),
          id: jobId,
          action
        });
        await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: true });
        const fb2 = document.getElementById('distillControlFeedback');
        if (fb2) {
          fb2.style.color = res.status === 'success' ? '#2E4418' : '#B83B2A';
          fb2.textContent = res.status === 'success'
            ? `✓ 已对任务 ${jobId} 执行 ${action}，当前状态：${res.data?.status}`
            : `✗ 操作失败：${res.error || ''}`;
        }
        return;
      }

      if (e.target.closest('#btnCancelDistillHighRisk')) {
        pendingHighRiskConfirm = null;
        const cBox = document.getElementById('distillHighRiskConfirmBox');
        if (cBox) cBox.style.display = 'none';
        return;
      }

      if (e.target.closest('#btnConfirmDistillHighRisk')) {
        const fb = document.getElementById('distillControlFeedback');
        if (!pendingHighRiskConfirm || pendingHighRiskConfirm.type !== 'learning_control') return;
        const { jobId, action, persona_id } = pendingHighRiskConfirm;
        const guard = guardWrite(`learning_control_${action}`, { endpoint: '/api/learning/control', targetId: jobId, feedbackEl: fb });
        if (!guard.allowed) return;
        pendingHighRiskConfirm = null;
        const cBox = document.getElementById('distillHighRiskConfirmBox');
        if (cBox) cBox.style.display = 'none';
        const res = await pmmAdapter.postJson('/api/learning/control', { persona_id, id: jobId, action });
        await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: true });
        const fb2 = document.getElementById('distillControlFeedback');
        if (fb2) {
          fb2.style.color = res.status === 'success' ? '#2E4418' : '#B83B2A';
          fb2.textContent = res.status === 'success'
            ? `✓ 已确认并对任务 ${jobId} 执行 ${action}，当前状态：${res.data?.status}`
            : `✗ 操作失败：${res.error || ''}`;
        }
        return;
      }

      // Persona Settings, New Persona, Switch Persona, Checkpoints & Rollback
      if (e.target.closest('#btnSavePersonaSettings')) {
        const nameInp = document.getElementById('inputRoleNameEdit');
        const seedInp = document.getElementById('inputRoleSeedEdit');
        const selfRefInp = document.getElementById('inputRoleSelfRefEdit');
        const initPersInp = document.getElementById('inputRoleInitPersEdit');
        const fb = document.getElementById('roleSaveFeedback');
        const guard = guardWrite('persona_save_settings', { endpoint: '/api/persona/settings', targetId: currentPersonaId(), feedbackEl: fb });
        if (!guard.allowed) return;
        const curRev = activeEnvelopes.characterProfile?.data?.revision ?? 0;
        const res = await pmmAdapter.postJson('/api/persona/settings', {
          expected_revision: curRev,
          name: nameInp ? nameInp.value.trim() : '',
          seed: seedInp ? seedInp.value.trim() : '',
          self_reference: selfRefInp ? selfRefInp.value.trim() : '我',
          initial_personality: initPersInp ? initPersInp.value.trim() : ''
        });
        if (res.status === 'success') {
          await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: true });
          const fb2 = document.getElementById('roleSaveFeedback');
          if (fb2) {
            fb2.style.color = '#2E4418';
            fb2.textContent = `✓ 角色设定已保存 (新 revision = ${res.data?.profile?.revision})`;
          }
        } else if (fb) {
          fb.style.color = '#B83B2A';
          fb.textContent = `✗ 保存失败：${res.error || ''}`;
        }
        return;
      }

      if (e.target.closest('#btnCreateNewPersona')) {
        const nameInp = document.getElementById('inputNewPersonaName');
        const fb = document.getElementById('roleCreateFeedback') || document.getElementById('roleSaveFeedback');
        const guard = guardWrite('persona_create', { endpoint: '/api/persona/new', feedbackEl: fb });
        if (!guard.allowed) return;
        const name = nameInp ? nameInp.value.trim() : '';
        if (!name) {
          if (fb) {
            fb.style.color = '#B83B2A';
            fb.textContent = '✗ 请输入新角色名称 (1-60字)。';
          }
          return;
        }
        const res = await pmmAdapter.postJson('/api/persona/new', { name, seed: '' });
        if (res.status === 'success') {
          if (nameInp) nameInp.value = '';
          contextEpoch += 1;
          clearPendingTransientConfirmations();
          await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: false, forceFullRefresh: true });
          const fb2 = document.getElementById('roleCreateFeedback') || document.getElementById('roleSaveFeedback');
          if (fb2) {
            fb2.style.color = '#2E4418';
            fb2.textContent = `✓ 已创建并切换至新角色：${name}`;
          }
        } else if (fb) {
          fb.style.color = '#B83B2A';
          fb.textContent = `✗ 创建角色失败：${res.error || ''}`;
        }
        return;
      }

      const swPersonaBtn = e.target.closest('[data-switch-persona]');
      if (swPersonaBtn) {
        const targetId = swPersonaBtn.dataset.switchPersona;
        const fb = document.getElementById('modalRoleSwitchFeedback') || document.getElementById('roleCreateFeedback') || document.getElementById('roleSaveFeedback');
        await switchActivePersona(targetId, fb);
        return;
      }

      if (e.target.closest('#btnCreateCheckpoint')) {
        const lblInp = document.getElementById('inputCheckpointLabel');
        const fb = document.getElementById('versionMgmtFeedback');
        const guard = guardWrite('persona_checkpoint', { endpoint: '/api/persona/checkpoint', targetId: currentPersonaId(), feedbackEl: fb });
        if (!guard.allowed) return;
        const label = (lblInp && lblInp.value.trim()) || '手动人格检查点';
        const res = await pmmAdapter.postJson('/api/persona/checkpoint', { label });
        if (res.status === 'success') {
          if (lblInp) lblInp.value = '';
          await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: true });
          const fb2 = document.getElementById('versionMgmtFeedback');
          if (fb2) {
            fb2.style.color = '#2E4418';
            fb2.textContent = `✓ 已创建检查点：${res.data?.label || label} (${res.data?.id || ''})`;
          }
        } else if (fb) {
          fb.style.color = '#B83B2A';
          fb.textContent = `✗ 创建检查点失败：${res.error || ''}`;
        }
        return;
      }

      const rbBtn = e.target.closest('[data-rollback-rev]');
      if (rbBtn) {
        const revId = rbBtn.dataset.rollbackRev;
        const fb = document.getElementById('versionMgmtFeedback');
        const guard = guardWrite('persona_rollback', { endpoint: '/api/persona/rollback', targetId: revId, feedbackEl: fb });
        if (!guard.allowed) return;

        // High-Risk Two-Step Confirmation for Persona Rollback
        pendingHighRiskConfirm = { type: 'persona_rollback', revId, persona_id: currentPersonaId() };
        const cBox = document.getElementById('versionRollbackConfirmBox');
        if (cBox) {
          cBox.style.display = 'block';
          cBox.innerHTML = `
            <div style="font-weight:700;color:#982B1E;margin-bottom:4px;">⚠ 高风险操作确认：恢复历史人格检查点</div>
            <div>● 目标检查点 ID：<code>${esc(revId)}</code></div>
            <div>● 所属角色：<strong>${esc(activeEnvelopes.characterProfile?.data?.name)}</strong> (<code>${esc(currentPersonaId())}</code>)</div>
            <div>● 动作后果：将用该检查点快照覆盖当前角色的人格构念、情绪基线与修订版本状态（回滚前系统会自动生成安全备份）。</div>
            <div style="display:flex;gap:8px;margin-top:8px;">
              <button type="button" class="layout-bar-btn save" id="btnConfirmExecuteRollback" style="background:#B83B2A;">确认恢复至此检查点</button>
              <button type="button" class="layout-bar-btn cancel" id="btnCancelExecuteRollback">取消</button>
            </div>
          `;
        }
        return;
      }

      if (e.target.closest('#btnCancelExecuteRollback')) {
        pendingHighRiskConfirm = null;
        const cBox = document.getElementById('versionRollbackConfirmBox');
        if (cBox) cBox.style.display = 'none';
        return;
      }

      if (e.target.closest('#btnConfirmExecuteRollback')) {
        const fb = document.getElementById('versionMgmtFeedback');
        if (!pendingHighRiskConfirm || pendingHighRiskConfirm.type !== 'persona_rollback') return;
        const { revId } = pendingHighRiskConfirm;
        const guard = guardWrite('persona_rollback', { endpoint: '/api/persona/rollback', targetId: revId, feedbackEl: fb });
        if (!guard.allowed) return;
        pendingHighRiskConfirm = null;
        const cBox = document.getElementById('versionRollbackConfirmBox');
        if (cBox) cBox.style.display = 'none';
        const res = await pmmAdapter.postJson('/api/persona/rollback', { id: revId });
        if (res.status === 'success') {
          await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: true });
          const fb2 = document.getElementById('versionMgmtFeedback');
          if (fb2) {
            fb2.style.color = '#2E4418';
            fb2.textContent = `✓ 已恢复至检查点 ${revId}：${res.data?.message || ''}`;
          }
        } else if (fb) {
          fb.style.color = '#B83B2A';
          fb.textContent = `✗ 恢复失败：${res.error || ''}`;
        }
        return;
      }

      // General LLM Config Save & Probes
      if (e.target.closest('#btnSaveGeneralLlmConfig')) {
        const pSel = document.getElementById('selectGenProvider');
        const uInp = document.getElementById('inputGenBaseUrl');
        const mInp = document.getElementById('inputGenModelName');
        const fb = document.getElementById('connProbeFeedback');
        const guard = guardWrite('config_save_general_llm', { endpoint: '/api/config', feedbackEl: fb });
        if (!guard.allowed) return;
        const res = await pmmAdapter.postJson('/api/config', {
          provider: pSel ? pSel.value : 'ollama',
          base_url: uInp ? uInp.value.trim() : 'http://127.0.0.1:11434',
          model: mInp ? mInp.value.trim() : ''
        });
        if (res.status === 'success') {
          pmmAdapter.connectionAdapter.recordProbeResult('general', null, '配置已更改，待重新探测');
          await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: false });
          const fb2 = document.getElementById('connProbeFeedback');
          if (fb2) fb2.textContent = '✓ 配置已保存（状态为 configured 已配置/未验证，请点击主动探测验证连通性）。';
        } else if (fb) {
          fb.textContent = `✗ 配置保存失败：${res.error || ''}`;
        }
        return;
      }

      if (e.target.closest('#btnTestGeneralLlm') || e.target.closest('#btnTestPmmConn') || e.target.closest('#btnTestQqConn')) {
        const isGen = Boolean(e.target.closest('#btnTestGeneralLlm'));
        const isPmm = Boolean(e.target.closest('#btnTestPmmConn'));
        const ep = isGen ? '/api/test-model' : (isPmm ? '/api/pmm281/connection' : '/api/qq/test');
        const role = isGen ? 'general' : (isPmm ? 'pmm' : 'qq');
        const fb = document.getElementById('connProbeFeedback');
        const guard = guardWrite(`probe_${role}`, { endpoint: ep, feedbackEl: fb });
        if (!guard.allowed) return;
        const persona = currentPersonaId();
        if (fb) fb.textContent = isPmm ? '正在用示例事件检查 A 的实际评价能力…' : '正在检查连接…';
        const res = await pmmAdapter.postJson(ep, isPmm ? {role:'A',operation:'invoke',persona_id:persona} : {});
        if (currentPersonaId() !== persona) return;
        const ok = res.status === 'success' && (isPmm ? res.data?.ok === true : res.data?.ok !== false);
        pmmAdapter.connectionAdapter.recordProbeResult(role, ok, ok ? '探测成功' : (res.error || '探测失败'));
        await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: true });
        const fb2 = document.getElementById('connProbeFeedback');
        if (fb2) {
          fb2.style.color = ok ? '#2E4418' : '#B83B2A';
          fb2.textContent = ok
            ? (isPmm ? 'A 已返回符合要求的事件评价。' : '连接检查成功。')
            : `检查失败。${res.data?.failure_reason || res.error || '请检查模型与连接设置。'}`;
        }
        return;
      }

      if (e.target.closest('#btnFetchQqWebhookUrl')) {
        const fb = document.getElementById('connProbeFeedback');
        const guard = guardWrite('qq_setup', { endpoint: '/api/qq/setup', feedbackEl: fb });
        if (!guard.allowed) return;
        const res = await pmmAdapter.postJson('/api/qq/setup', {});
        if (fb) {
          fb.textContent = res.status === 'success'
            ? `OneBot 事件回调 URL: ${res.data?.event_url || ''}`
            : `获取失败：${res.error || ''}`;
        }
        return;
      }

      if (e.target.closest('#btnSwitchSocialScope')) {
        const sInp = document.getElementById('inputSocialScope');
        if (sInp && sInp.value.trim()) {
          if (sInp.value.trim() === '*' || dataSourceMode !== 'live') {
            sInp.setCustomValidity(dataSourceMode !== 'live' ? '请先切换到 LIVE，再读取真实范围。' : '请填写一个明确范围，不支持通配查询。');
            sInp.reportValidity();
            return;
          }
          sInp.setCustomValidity('');
          window.PsychViz.close();
          activeScope = sInp.value.trim();
          await tryHydrateFromLiveServer(activeScope, { preserveSubpageDom: false });
        }
        return;
      }

      // Memory Filter & Log Filter
      const memFilterBtn = e.target.closest('[data-mem-filter]');
      if (memFilterBtn) {
        memoryKindFilter = memFilterBtn.dataset.memFilter || 'all';
        document.querySelectorAll('[data-mem-filter]').forEach(b => {
          b.classList.toggle('active', b.dataset.memFilter === memoryKindFilter);
        });
        const listBox = document.getElementById('memoriesFilteredListBox');
        if (listBox) listBox.innerHTML = buildMemoriesFilteredListHtml();
        return;
      }

      const logFilterBtn = e.target.closest('[data-log-filter]');
      if (logFilterBtn) {
        logStatusFilter = logFilterBtn.dataset.logFilter || 'all';
        renderSubpage(currentMode, 'logs_monitor', { preserveSubpageDom: false });
        return;
      }

      // P1-01: Layout Edit Mode Controls (#btnSaveLayout, #btnResetLayout, #btnCancelLayout, #btnExitLayoutEdit)
      const editBtn = e.target.closest('.js-toggle-layout-edit');
      if (editBtn) {
        toggleLayoutEditMode();
        return;
      }
      if (e.target.closest('#btnSaveLayout')) {
        saveCurrentLayout();
        toggleLayoutEditMode(false);
        return;
      }
      if (e.target.closest('#btnResetLayout')) {
        resetCurrentLayout();
        return;
      }
      if (e.target.closest('#btnCancelLayout') || e.target.closest('#btnExitLayoutEdit')) {
        cancelUnsavedLayoutEdits();
        return;
      }
      if (e.target.closest('#btnClearAllSavedLayouts')) {
        Object.keys(memoryLayoutStore).forEach(k => delete memoryLayoutStore[k]);
        try {
          Object.keys(localStorage).forEach(k => {
            if (k.startsWith('huaian_layout_')) localStorage.removeItem(k);
          });
        } catch (_) {}
        const fb = document.getElementById('localSettingsFeedback');
        if (fb) fb.textContent = '✓ 已清除所有保存的自定义卡片布局并恢复默认。';
        return;
      }

      const resizeBtn = e.target.closest('[data-resize-card]');
      if (resizeBtn) {
        e.stopPropagation();
        resizeCard(resizeBtn.dataset.resizeCard, resizeBtn.dataset.sizeVal);
        return;
      }

      const moveBtn = e.target.closest('[data-move-dir]');
      if (moveBtn) {
        e.stopPropagation();
        const cardId = moveBtn.dataset.targetCard;
        const dir = parseInt(moveBtn.dataset.moveDir, 10);
        const cardEl = document.querySelector(`[data-layout-card="${cardId}"]`);
        if (cardEl && cardEl.parentElement) {
          const siblings = Array.from(cardEl.parentElement.querySelectorAll(':scope > [data-layout-card]'));
          const idx = siblings.indexOf(cardEl);
          const targetIdx = idx + dir;
          if (targetIdx >= 0 && targetIdx < siblings.length) {
            swapCardsInGrid(cardId, siblings[targetIdx].dataset.layoutCard);
          }
        }
        return;
      }

      const pModeBtn = e.target.closest('[data-persona-view-mode]');
      if (pModeBtn) {
        personaViewMode = pModeBtn.dataset.personaViewMode;
        document.querySelectorAll('[data-persona-view-mode]').forEach(b => {
          b.classList.toggle('active', b.dataset.personaViewMode === personaViewMode);
        });
        renderUserHomeDynamicCards();
        return;
      }

      const eRangeBtn = e.target.closest('[data-emo-range]');
      if (eRangeBtn) {
        emotionRangeMode = eRangeBtn.dataset.emoRange;
        document.querySelectorAll('[data-emo-range]').forEach(b => {
          b.classList.toggle('active', b.dataset.emoRange === emotionRangeMode);
        });
        renderUserHomeDynamicCards();
        if(dataSourceMode==='live'&&emotionRangeMode!=='events')await window.SampleView.read(sampleServices(),'home',emotionRangeMode);
        return;
      }

      if (e.target.closest('#btnExpandEmotionCard')) {
        emotionExpanded = !emotionExpanded;
        renderUserHomeDynamicCards();
        return;
      }

      const clearBtn = e.target.closest('[data-clear-fault]');
      if (clearBtn) {
        setDomainFault(clearBtn.dataset.clearFault, 'normal');
        return;
      }

      const faultBtn = e.target.closest('[data-fault-domain]');
      if (faultBtn) {
        setDomainFault(faultBtn.dataset.faultDomain, faultBtn.dataset.faultVal);
        return;
      }

      const uNav = e.target.closest('[data-user-nav]');
      if (uNav && !layoutEditActive) {
        if (currentMode !== 'user') switchMode('user');
        await switchUserNav(uNav.dataset.userNav);
        return;
      }

      const dNav = e.target.closest('[data-dev-nav]');
      if (dNav && !layoutEditActive) {
        if (currentMode !== 'developer') switchMode('developer');
        switchDevNav(dNav.dataset.devNav);
        return;
      }

      const qAct = e.target.closest('[data-quick-action="parlor"]');
      if (qAct) {
        switchMode('user');
        await switchUserNav('parlor');
        return;
      }

      const modalTrigger = e.target.closest('[data-open-modal]');
      if (modalTrigger && !layoutEditActive) {
        openModal(modalTrigger.dataset.openModal);
        return;
      }

      if (e.target.closest('#shellModalCloseBtn') || e.target.id === 'shellModalBackdrop') {
        closeModal();
      }
    });

    // Escape key closes open modal
    document.addEventListener('keydown', e => {
      if (e.target.id === 'inputParlorMessage' && e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !e.isComposing) {
        e.preventDefault(); document.getElementById('btnSendParlorChat')?.click(); return;
      }
      // SVG controls use button semantics for both keyboard activation keys.
      const svgButton = e.target.closest('svg [role="button"]');
      if (svgButton && (e.key === 'Enter' || e.key === ' ')) {
        e.preventDefault();
        svgButton.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        return;
      }
      if (e.key === 'Escape' && currentOpenModalKey) {
        closeModal();
      }
    });

    // P1-02: Non-Destructive Input & Change Listeners (Never destroys input element or loses focus!)
    document.addEventListener('input', e => {
      if (window.ModelSettings.change(e.target)) return;
      if (['selectDispositionField', 'inputDispositionVal', 'inputDispositionNote'].includes(e.target.id)) {
        pendingDispositionEdit = null; const box = document.getElementById('dispositionConfirmBox'); if (box) box.style.display = 'none';
      }
      if (window.ParlorView.handleChange(e.target)) return;
      if ((currentMode === 'developer' || currentUserNav === 'settings') && e.target.closest('.dev-viz-page, .psych-viz-page') &&
          (window.PmmFlow.handleChange(e.target) || window.DeveloperViews.handleChange(e.target))) {
        renderSubpage(currentMode, currentMode === 'developer' ? currentDevNav : currentUserNav, { preserveSubpageDom: true });
        return;
      }
      if (e.target.closest('.psych-viz-page') &&
          (window.PersonalityView.handleChange(e.target, activeEnvelopes) || window.EmotionView.handleChange(e.target, activeEnvelopes) || window.DriveView.handleChange(e.target) || window.MemoryGraphView.handleChange(e.target) || window.LifeViews.handleChange(e.target) || window.RelationView.handleChange(e.target))) {
        renderActiveSubpage();
        return;
      }
      if (e.target && e.target.id === 'inputSubpageMemSearch') {
        memorySearchQuery = e.target.value || '';
        const listBox = document.getElementById('memoriesFilteredListBox');
        if (listBox) {
          listBox.innerHTML = buildMemoriesFilteredListHtml();
        }
      } else if (e.target && e.target.id === 'inputModalDevSearch') {
        const q = (e.target.value || '').trim().toLowerCase();
        const rBox = document.getElementById('modalDevSearchResults');
        if (!rBox) return;
        if (!q) {
          rBox.innerHTML = '输入关键词后将在此显示匹配结果。';
          return;
        }
        const env = activeEnvelopes || {};
        const memHits = (env.memories?.data?.items || []).filter(m => String(m.content || '').toLowerCase().includes(q));
        const expHits = (env.experiences?.data?.items || []).filter(it => String(it.title || '').toLowerCase().includes(q) || String(it.reply || '').toLowerCase().includes(q));
        const conHits = (env.personality?.data?.editable_constructs || []).filter(c => String(c.id || '').toLowerCase().includes(q) || String(c.name_zh || '').toLowerCase().includes(q));
        rBox.innerHTML = `
          <div><strong>记忆匹配 (${memHits.length})：</strong>${memHits.slice(0, 3).map(m => esc(m.content)).join(' | ') || '无'}</div>
          <div style="margin-top:4px;"><strong>经历匹配 (${expHits.length})：</strong>${expHits.slice(0, 3).map(it => esc(it.title)).join(' | ') || '无'}</div>
          <div style="margin-top:4px;"><strong>构念匹配 (${conHits.length})：</strong>${conHits.slice(0, 5).map(c => `${esc(c.name_zh)}(${esc(c.id)})`).join(', ') || '无'}</div>
        `;
      }
    });

    document.addEventListener('change', async e => {
      if (await window.PersonaManager.change(e.target, personaManagementServices())) return;
      if (window.SampleView?.handleChange(e.target)) {sampleServices().render();return;}
      if (window.ResearchView?.handleChange(e.target)) return;
      if (window.ModelSettings.change(e.target)) return;
      if (e.target.id === 'inputSocialScope' && e.target.tagName === 'SELECT') { await selectRelationshipScope(e.target.value); return; }
      if (['selectDispositionField', 'inputDispositionVal', 'inputDispositionNote'].includes(e.target.id)) {
        pendingDispositionEdit = null; const box = document.getElementById('dispositionConfirmBox'); if (box) box.style.display = 'none';
      }
      if (window.ParlorView.handleChange(e.target)) return;
      if ((currentMode === 'developer' || currentUserNav === 'settings') && e.target.closest('.dev-viz-page, .psych-viz-page') &&
          (window.PmmFlow.handleChange(e.target) || window.DeveloperViews.handleChange(e.target))) {
        renderSubpage(currentMode, currentMode === 'developer' ? currentDevNav : currentUserNav, { preserveSubpageDom: true });
        return;
      }
      if (e.target.closest('.psych-viz-page') &&
          (window.PersonalityView.handleChange(e.target, activeEnvelopes) || window.EmotionView.handleChange(e.target, activeEnvelopes) || window.DriveView.handleChange(e.target) || window.MemoryGraphView.handleChange(e.target) || window.LifeViews.handleChange(e.target) || window.RelationView.handleChange(e.target))) {
        renderActiveSubpage();
        return;
      }
      if (e.target && e.target.id === 'selectParlorSession') {
        window.PsychViz.close();
        parlorSessionId = e.target.value || '';
        parlorSessionsByPersona[currentPersonaId()] = parlorSessionId;
        parlorJobState = window.ParlorView.thread(parlorContext());
        refreshParlorView();
        await readParlorMessages();
      }
    });
  }

  window.__HUAIAN_PHASE20_SHELL__ = {
    version: '3.0-ui-repair1',
    baseline: '2.3.1-minfix-handoff',
    pmmAdapter,
    mockAdapter,
    pollingScheduler,
    SUBPAGE_META,
    MODAL_HANDLERS,
    openModal,
    closeModal,
    guardWrite,
    switchActivePersona,
    tryHydrateFromLiveServer,
    switchDataSourceMode,
    switchMode,
    switchUserNav,
    switchDevNav,
    setDomainFault,
    getDomainEnvelope,
    computeDomainBadgeSpec,
    toggleLayoutEditMode,
    swapCardsInGrid,
    resizeCard,
    saveCurrentLayout,
    cancelUnsavedLayoutEdits,
    resetCurrentLayout,
    getActiveEnvelopes: () => activeEnvelopes,
    getCallLog: () => pmmAdapter.callLog,
    getMockBlockedWriteLog: () => mockBlockedWriteLog,
    getCurrentOpenModalKey: () => currentOpenModalKey,
    getHydrationCounters: () => ({ hydrateSeq, latestAppliedHydrateSeq, contextEpoch, personaSwitchInFlight }),
    getParlorState: () => ({
      session_id: parlorSessionId,
      messages: parlorMessagesBySession[parlorSessionId] || [],
      job_state: window.ParlorView.thread(parlorContext())
    })
  };

  function boot() {
    initEventListeners();
    refreshAllViews({ preserveSubpageDom: false });
    tryHydrateFromLiveServer().then(() => {
      pollingScheduler.scheduleNext();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
