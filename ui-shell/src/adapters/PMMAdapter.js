/**
 * 槐安梦客 Phase 2.3 — PMMAdapter (真实后端读写闭环、会话历史隔离、任务轮询与全子页映射核心)
 * - P0-01：实现 createSession()、fetchSessionMessages()、sendChatMessage({session_id, text, client_event_id})、pollJobUntilDone(/api/jobs/<id>)。
 * - P0-02：从 psychology_registry 与 disposition_registry 构建全部 68 项可编辑长期构念表，saveConstructDisposition() 严格携带 feature_id、expected_version、source_type='owner_seed' 及 PANAS 必需的 timeframe='generally'。
 * - P0-03：advanceExpressiveDrive() 仅向 POST /api/pmm283/expressive-drive/advance 发送后端实际读取的 {scope, person, session_id, at, commit}，绝不伪造新增动机参数。
 * - P0-04：previewLearningJob() 与 createAuthorizedLearningJob() 强制两步预览与显式授权校验。
 */
(function (global) {
  const TARGET_LABELS = {
    self: '自我构念蒸馏',
    other: '交互对象建模',
    relationship: '双边关系归纳',
    language: '语言风格示范',
    memory: '事件记忆提炼',
    social_graph: '社交图谱抽取'
  };

  class PMMAdapter {
    constructor(baseUrl = '') {
      this.adapterName = 'PMMAdapter';
      this.baseUrl = baseUrl;
      this.csrfToken = '';
      this.clientVersion = '2.8.3-dev';
      this.buildId = '';
      this.bootstrapped = false;
      this.callLog = [];
      this.endpointFaultOverrides = {};
      this.sessionMessagesCache = {}; // Per-session message history cache keyed by session_id
      this.modelAdapter = new global.ModelAdapter();
      this.connectionAdapter = new global.ConnectionAdapter();
      this.mockAdapter = new global.MockAdapter();
    }

    logCall(entry) {
      this.callSequence = (this.callSequence || 0) + 1;
      entry.ui_id = `http_${this.callSequence}`;
      this.callLog.unshift(entry);
      if (this.callLog.length > 150) this.callLog.length = 150;
    }

    setEndpointFaultOverride(endpoint, faultType) {
      if (!faultType) {
        delete this.endpointFaultOverrides[endpoint];
      } else {
        this.endpointFaultOverrides[endpoint] = faultType;
      }
    }

    clearEndpointFaultOverrides() {
      this.endpointFaultOverrides = {};
    }

    async bootstrap(timeoutMs = 5000) {
      const env = await this.requestJson('/api/bootstrap', 'GET', undefined, timeoutMs);
      if (env.status !== 'success') { this.bootstrapped = false; return env; }
      const data = env.data;
      const csrf = data?.csrf || data?.auth?.csrf_token;
      if (!csrf || typeof csrf !== 'string') {
        this.bootstrapped = false;
        return global.DataEnvelopeFactory.error('/api/bootstrap', '服务已响应，但初始化信息不完整', 'INVALID_RESPONSE', 200);
      }
      this.csrfToken = csrf;
      this.clientVersion = data.version || data.app_version || '2.8.3-dev';
      this.buildId = data.build_id || '';
      this.bootstrapped = true;
      return env;
    }

    async requestJson(endpoint, method = 'GET', body, timeoutMs = 5500, base = this.baseUrl) {
      const E = global.DataEnvelopeFactory;
      const started = performance.now();
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      let response;
      try {
        const headers = { Accept: 'application/json' };
        if (method === 'POST') Object.assign(headers, { 'Content-Type': 'application/json', 'X-CSRF-Token': this.csrfToken, 'X-App-Client-Version': this.clientVersion });
        response = await fetch(`${base}${endpoint}`, { method, credentials: 'same-origin', headers,
          ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: controller.signal });
        let payload, invalid = false;
        try { payload = await response.json(); }
        catch (err) { if (controller.signal.aborted) throw err; invalid = true; }
        const elapsed = Math.round((performance.now() - started) * 10) / 10;
        let result;
        if (response.status === 410 || response.status === 501) {
          result = E.unavailable(endpoint, payload?.error || payload?.message || '此功能暂不可用');
        } else if (!response.ok) {
          result = E.error(endpoint, payload?.error || payload?.message || (response.status === 401 ? '会话已失效，请刷新页面重新连接' : `服务返回错误（${response.status}）`), payload?.code || `HTTP_${response.status}`, response.status);
        } else if (invalid || !payload || typeof payload !== 'object') {
          result = E.error(endpoint, '服务已响应，但返回内容不完整或格式不正确', 'INVALID_RESPONSE', response.status);
        } else {
          result = E.live(payload, endpoint, payload.updated_at ?? null);
        }
        result.http_status = response.status;
        this.logCall({ endpoint, method, status: response.status, ok: result.status === 'success', elapsed_ms: elapsed,
          at: global.nowFetchedAt(), code: result.error_code, request_id: response.headers.get('X-Request-ID') });
        return result;
      } catch (err) {
        const elapsed = Math.round((performance.now() - started) * 10) / 10;
        const code = controller.signal.aborted ? 'TIMEOUT' : response ? 'RESPONSE_INTERRUPTED' : 'NETWORK_ERROR';
        const message = code === 'TIMEOUT' ? '读取超时，服务可能正在处理任务' : response ? '响应传输中断，请重新读取状态' : '暂时无法连接本地服务，请确认程序已启动';
        this.logCall({ endpoint, method, status: response?.status || 0, ok: false, elapsed_ms: elapsed, at: global.nowFetchedAt(), error: code });
        return E.error(endpoint, message, code, response?.status || 0);
      } finally {
        clearTimeout(timer);
      }
    }

    async fetchJson(endpoint, timeoutMs = 5500, customBaseUrl = null) {
      const E = global.DataEnvelopeFactory;
      const cleanEp = endpoint.split('?')[0];
      const override = this.endpointFaultOverrides[cleanEp] || this.endpointFaultOverrides[endpoint];
      if (override === 'timeout') {
        this.logCall({ endpoint, method: 'GET', status: 0, ok: false, elapsed_ms: timeoutMs, at: global.nowFetchedAt(), error: 'TIMEOUT', injected: true });
        return E.error(endpoint, `接口请求超时 (${endpoint} > ${timeoutMs}ms)`, 'TIMEOUT', 0);
      }
      if (override === '500') {
        this.logCall({ endpoint, method: 'GET', status: 500, ok: false, elapsed_ms: 2.1, at: global.nowFetchedAt(), code: 'HTTP_500', injected: true });
        return E.error(endpoint, `后端内部错误 (${endpoint} HTTP 500)`, 'HTTP_500', 500);
      }
      if (override === '404') {
        return this.fetchJson('/api/non_existent_phase23_route_probe', timeoutMs, customBaseUrl);
      }
      if (override === 'disconnect') {
        this.logCall({ endpoint, method: 'GET', status: 0, ok: false, elapsed_ms: 1.0, at: global.nowFetchedAt(), error: 'NETWORK_ERROR', injected: true });
        return E.error(endpoint, `网络连接已断开 (${endpoint})`, 'NETWORK_ERROR', 0);
      }

      return this.requestJson(endpoint, 'GET', undefined, timeoutMs, customBaseUrl ?? this.baseUrl);
    }

    async postJson(endpoint, body = {}, timeoutMs = 12000) {
      const E = global.DataEnvelopeFactory;
      if (global.__HUAIAN_DATA_SOURCE_MODE__ === 'mock') return E.error(endpoint, '演示模式不会修改真实数据', 'MOCK_WRITE_BLOCKED', 0);
      if (!this.bootstrapped || !this.csrfToken) {
        const boot = await this.bootstrap();
        if (boot.status !== 'success') return boot;
      }
      // Never retry a write: a lost response does not mean it was not committed.
      return this.requestJson(endpoint, 'POST', body, timeoutMs);
    }

    // -------------------------------------------------------------------------
    // P0-01: Parlor Session, Real Message History (/api/messages), Chat Submit & Job Polling (/api/jobs/<id>)
    // -------------------------------------------------------------------------
    fetchMotiveHistory(options) {
      const query = new URLSearchParams(Object.entries(options).filter(([, value]) => value != null && value !== ''));
      return this.fetchJson('/api/pmm283/motives/history?' + query);
    }
    fetchTokenPage(options = {}) {
      const query = new URLSearchParams(Object.entries({ limit: 50, ...options }).filter(([, value]) => value != null && value !== ''));
      return this.fetchJson('/api/token-ledger?' + query);
    }
    fetchRunDetail(turnId) {
      return this.fetchJson('/api/pmm282/history?turn_id=' + encodeURIComponent(turnId));
    }

    async createSession() {
      const env = await this.postJson('/api/session', {});
      if (env.status !== 'success' || !env.data || !env.data.id) {
        return { ok: false, session_id: null, error: env.error || '创建会话失败', envelope: env };
      }
      const sid = env.data.id;
      if (!this.sessionMessagesCache[sid]) {
        this.sessionMessagesCache[sid] = [];
      }
      return { ok: true, session_id: sid, envelope: env };
    }

    async fetchSessionMessages(sessionId, offset = 0) {
      if (!sessionId) {
        return { ok: false, session_id: '', messages: [], error: '未指定 session_id' };
      }
      const ep = `/api/messages?session=${encodeURIComponent(sessionId)}&offset=${Number(offset) || 0}`;
      const env = await this.fetchJson(ep);
      if (env.status !== 'success' || !Array.isArray(env.data)) {
        return { ok: false, session_id: sessionId, messages: this.sessionMessagesCache[sessionId] || [], error: env.error || '读取会话消息失败', envelope: env };
      }
      const msgs = env.data.map(m => ({
        id: m.id,
        session_id: m.session_id || sessionId,
        role: m.role || 'unknown',
        content: m.content || '',
        created_at: global.formatBusinessTimestamp(m.created_at),
        display_time: global.formatLocalDisplayTime ? global.formatLocalDisplayTime(m.created_at) : String(m.created_at || ''),
        turn_id: m.turn_id || null,
        raw: m
      }));
      this.sessionMessagesCache[sessionId] = msgs;
      return { ok: true, session_id: sessionId, messages: msgs, envelope: env };
    }

    async sendChatMessage(sessionId, text, clientEventId = null) {
      const cleanText = String(text || '').trim();
      if (!sessionId) {
        return { ok: false, error: '当前没有活动会话 ID，请先创建或选择会话' };
      }
      if (!cleanText) {
        return { ok: false, error: '发送内容不能为空' };
      }
      const payload = {
        session_id: sessionId,
        text: cleanText
      };
      if (clientEventId) {
        payload.client_event_id = String(clientEventId).slice(0, 120);
      }
      const env = await this.postJson('/api/chat', payload);
      if (env.status !== 'success' || !env.data || !env.data.job_id) {
        return { ok: false, job_id: null, error: env.error || '发送对话请求失败', envelope: env };
      }
      return { ok: true, job_id: env.data.job_id, envelope: env };
    }

    async pollJobUntilDone(jobId, onProgress = null, timeoutMs = 25000, isCurrent = () => true) {
      if (!jobId) {
        return { ok: false, status: 'error', error: '缺少任务 job_id' };
      }
      const start = performance.now();
      const ep = `/api/jobs/${encodeURIComponent(jobId)}`;
      let lastReadError = null;
      while (performance.now() - start < timeoutMs) {
        if (!isCurrent()) return { ok: false, status: 'observation_paused', job_id: jobId, error: '已切换角色，暂停本地任务观察；后台任务未被取消' };
        const jEnv = await this.fetchJson(ep, 4500);
        if (!isCurrent()) return { ok: false, status: 'observation_paused', job_id: jobId, error: '已切换角色，暂停本地任务观察；后台任务未被取消' };
        if (jEnv.status !== 'success' || !jEnv.data) {
          if (['TIMEOUT', 'NETWORK_ERROR', 'RESPONSE_INTERRUPTED'].includes(jEnv.error_code)) {
            lastReadError = jEnv.error;
            await new Promise(r => setTimeout(r, 800));
            continue;
          }
          return { ok: false, status: 'error', job_id: jobId, error: jEnv.error || '查询任务状态失败', envelope: jEnv };
        }
        const job = jEnv.data;
        if (typeof onProgress === 'function') {
          try { onProgress(job, jEnv); } catch (_) {}
        }
        if (job.status === 'done') {
          return { ok: true, status: 'done', job_id: jobId, job, result: job.result, envelope: jEnv };
        }
        if (job.status === 'error' || job.status === 'failed') {
          return { ok: false, status: 'error', job_id: jobId, job, error: job.error || '后端任务执行失败', envelope: jEnv };
        }
        await new Promise(r => setTimeout(r, 180));
      }
      return { ok: false, status: 'timeout', job_id: jobId, error: lastReadError ? `${lastReadError}；任务仍待确认，请继续查看进度，不必重新发送。` : '后台任务仍在处理，可继续查看进度，不必重新发送。' };
    }

    // -------------------------------------------------------------------------
    // P0-02: Optimistic Concurrency Control & Source Type Semantics for Construct Editing
    // -------------------------------------------------------------------------
    async saveConstructDisposition({ persona_id, feature_id, expected_version, estimate, source_type = 'owner_seed', timeframe = null, note = '', measurement = null }) {
      if (!persona_id) {
        return { ok: false, error: '缺少目标角色 persona_id' };
      }
      if (!feature_id) {
        return { ok: false, error: '请选择要修改的注册心理构念 (feature_id)' };
      }
      if (typeof expected_version !== 'number' || !isFinite(expected_version)) {
        return { ok: false, error: '缺少当前人格构念版本号 expected_version，请刷新后重试' };
      }
      if (estimate !== null && (typeof estimate !== 'number' || !isFinite(estimate) || estimate < 0 || estimate > 1)) {
        return { ok: false, error: '构念设定值必须在 0.00 到 1.00 之间（或设为 null 清空）' };
      }
      const body = {
        persona_id,
        feature_id,
        expected_version: Number(expected_version),
        estimate: estimate === null ? null : Number(estimate),
        source_type: source_type || 'owner_seed',
        note: String(note || '').slice(0, 1000)
      };
      if (feature_id.startsWith('panas.')) {
        body.timeframe = timeframe || 'generally';
      } else if (timeframe) {
        body.timeframe = timeframe;
      }
      if (source_type === 'questionnaire' && measurement) {
        body.measurement = measurement;
      }
      const env = await this.postJson('/api/traits/disposition', body);
      if (env.status !== 'success' || !env.data || !env.data.ok) {
        const isConflict = String(env.error || '').includes('版本已变化');
        return {
          ok: false,
          conflict: isConflict,
          error: isConflict ? '人格版本已更新，请刷新后重新确认再保存（已拦截旧版本覆盖）' : (env.error || '构念保存失败'),
          envelope: env
        };
      }
      return {
        ok: true,
        trait_profile: env.data.trait_profile,
        new_version: env.data.trait_profile?.version,
        envelope: env
      };
    }

    // -------------------------------------------------------------------------
    // P0-03: Honest Expressive Drive Advance (Only sends supported parameters!)
    // -------------------------------------------------------------------------
    async advanceExpressiveDrive({ scope = 'private:web:owner', person = 'web:owner', session_id = null, at = null, commit = true } = {}) {
      const body = {
        scope: scope || 'private:web:owner',
        person: person || 'web:owner',
        commit: Boolean(commit)
      };
      if (session_id) body.session_id = session_id;
      if (at !== null && at !== undefined) body.at = at;
      const env = await this.postJson('/api/pmm283/expressive-drive/advance', body);
      if (env.status !== 'success' || !env.data) {
        return { ok: false, error: env.error || '推进表达欲失败', envelope: env };
      }
      return { ok: true, evaluation: env.data, envelope: env };
    }

    // -------------------------------------------------------------------------
    // P0-04: Two-Step Learning Job Preview & Explicit User Authorization
    // -------------------------------------------------------------------------
    async previewLearningJob({ persona_id, target = 'self', source = 'import', scopes = ['self:imported'], records = [], person = '' }) {
      if (!persona_id) return { ok: false, error: '缺少角色 ID (persona_id)' };
      if (!Array.isArray(records) || records.length === 0) {
        return { ok: false, error: '原文列表不能为空，请输入或导入至少 1 条真人示范原文' };
      }
      const body = { persona_id, target, source, scopes, records, person };
      const env = await this.postJson('/api/learning/preview', body);
      if (env.status !== 'success' || !env.data) {
        return { ok: false, error: env.error || '学习任务预览失败', envelope: env };
      }
      return { ok: true, preview: env.data, request_body: body, envelope: env };
    }

    async createAuthorizedLearningJob(previewRequestBody, previewData, userExplicitlyAuthorized, intent = 'review') {
      if (userExplicitlyAuthorized !== true) {
        return { ok: false, error: '必须先预览原文范围并勾选“确认授权”后才能创建学习任务' };
      }
      if (!previewData || !previewData.source_digest || previewData.policy_version === undefined) {
        return { ok: false, error: '缺少有效的预览摘要 (source_digest / policy_version)，请先执行预览' };
      }
      const createBody = {
        ...previewRequestBody,
        intent: intent || 'review',
        authorized: true,
        source_digest: previewData.source_digest,
        policy_version: previewData.policy_version
      };
      const env = await this.postJson('/api/learning/create', createBody);
      if (env.status !== 'success' || !env.data) {
        return { ok: false, error: env.error || '创建学习任务失败', envelope: env };
      }
      return { ok: true, job: env.data, envelope: env };
    }

    /**
     * 完整调用原版 17 个核心接口并将真实返回数据逐模块独立解析为 DataEnvelope
     */
    async fetchAllLiveContracts(scope = 'private:web:owner') {
      const bootEnv = await this.bootstrap();
      if (bootEnv.status !== 'success') {
        const health = await this.fetchJson('/api/health', 2000);
        const reachable = health.status === 'success' || health.http_status > 0 || bootEnv.http_status > 0;
        return { ok: false, error: bootEnv.error, error_code: bootEnv.error_code, envelopes: null,
          backend_reachable: reachable, connection_state: reachable ? 'reachable' : 'unconfirmed' };
      }

      const encodedScope = encodeURIComponent(scope);
      const endpoints = [
        '/api/state',
        '/api/ui3/overview',
        '/api/persona/revisions',
        '/api/affect',
        '/api/pmm283/expressive-drive',
        '/api/pmm281/status',
        '/api/pmm28/status',
        '/api/pmm28/traces',
        '/api/memories',
        '/api/de/turns?offset=0&limit=20',
        '/api/learning?offset=0',
        '/api/learning/activities?offset=0',
        '/api/relations',
        `/api/social-graph?scope=${encodedScope}`,
        `/api/people?scope=${encodedScope}`,
        '/api/cognition',
        '/api/qq/status'
      ];

      // Bound concurrent reads so requests do not spend their whole deadline
      // queued behind the browser's per-origin connections.
      const results = new Array(endpoints.length);
      let next = 0;
      await Promise.all(Array.from({ length: 4 }, async () => {
        while (next < endpoints.length) {
          const i = next++;
          results[i] = await this.fetchJson(endpoints[i]);
        }
      }));
      const rawMap = {};
      let okCount = 0;
      let errCount = 0;
      endpoints.forEach((ep, idx) => {
        const cleanKey = ep.split('?')[0];
        rawMap[cleanKey] = results[idx];
        rawMap[ep] = results[idx];
        if (results[idx] && results[idx].status === 'success') okCount += 1;
        else errCount += 1;
      });

      const stateEnv = rawMap['/api/state'];
      if (stateEnv && stateEnv.status === 'success' && stateEnv.data && stateEnv.data.csrf) {
        this.csrfToken = stateEnv.data.csrf;
      }

      const charEnv = this.parseCharacterProfile(rawMap);
      const persEnv = this.parsePersonalityState(rawMap);
      const emoEnv = this.parseEmotionState(rawMap);
      const driveEnv = this.parseExpressionDrive(rawMap);
      const psychEnv = this.parsePsychologicalState(emoEnv, driveEnv, rawMap);
      const memEnv = this.parseMemories(rawMap);
      const expEnv = this.parseExperiences(rawMap);
      const learnEnv = this.parseLearningTasks(rawMap);
      const socialEnv = this.parseSocialGraph(rawMap, scope);
      const connEnv = this.connectionAdapter.parseConnectionStatus(rawMap);
      const decEnv = this.modelAdapter.parseDecisionRecords(rawMap);

      const overallStatus = errCount === 0 ? 'live' : (okCount > 0 ? 'partial' : 'error');
      // The successful handshake is evidence that the service answered, even
      // when all business reads time out or reject the current session.
      let connection = { backend_reachable: true, connection_state: 'reachable' };
      if (okCount === 0) {
        const health = await this.fetchJson('/api/health', 2000);
        const reachable = health.status === 'success' || health.http_status > 0;
        connection = { backend_reachable: reachable, connection_state: reachable ? 'reachable' : 'unconfirmed' };
      }

      return {
        ...connection,
        ok: okCount > 0,
        mode: 'live',
        overall_status: overallStatus,
        ok_endpoints_count: okCount,
        error_endpoints_count: errCount,
        total_endpoints_count: endpoints.length,
        fetched_at: global.nowFetchedAt(),
        rawMap,
        envelopes: {
          ...connection,
          mode: 'live',
          overall_status: overallStatus,
          ok_endpoints_count: okCount,
          error_endpoints_count: errCount,
          total_endpoints_count: endpoints.length,
          fetched_at: global.nowFetchedAt(),
          characterProfile: charEnv,
          personality: persEnv,
          emotion: emoEnv,
          psychological: psychEnv,
          expressionDrive: driveEnv,
          memories: memEnv,
          experiences: expEnv,
          learning: learnEnv,
          socialGraph: socialEnv,
          connections: connEnv,
          decisions: decEnv
        }
      };
    }

    // 1. CharacterProfile (Includes sessions, boundary_model, pragmatics, evidence_trace, cognition for subpages)
    parseCharacterProfile(rawMap) {
      const E = global.DataEnvelopeFactory;
      const stateEnv = rawMap['/api/state'];
      if (!stateEnv || stateEnv.status !== 'success' || !stateEnv.data) {
        return E.error('/api/state', stateEnv?.error || '读取角色档案失败', stateEnv?.error_code || 'PROFILE_ERROR', stateEnv?.http_status);
      }
      const st = stateEnv.data;
      const prof = st.profile || {};
      const ident = st.identity || {};
      const personas = st.personas || { default: prof.id, active: prof.id, items: [{ id: prof.id, name: prof.name }] };
      const cog = (rawMap['/api/cognition'] && rawMap['/api/cognition'].status === 'success' && rawMap['/api/cognition'].data) || st.cognition || {};

      return E.live({
        id: prof.id || ident.id || '',
        name: prof.name || ident.name || '未命名角色',
        seed: prof.seed || '',
        character: prof.character || { self_reference: '我', initial_personality: '' },
        summary: (prof.character && (prof.character.initial_personality || prof.character.background)) || prof.seed || '（当前角色尚未填写详细背景设定）',
        revision: prof.revision ?? 0,
        trait_version: (prof.trait_profile && prof.trait_profile.version) ?? 0,
        updated_at: global.formatBusinessTimestamp(prof.updated_at),
        boundaries: prof.boundaries || [],
        boundary_model: st.boundary_model || { boundaries: [] },
        pragmatics: st.pragmatics || {},
        evidence_trace: st.evidence_trace || { items: [] },
        source_records: prof.source_records || [],
        cognition: cog,
        // Keep the endpoint's own status for psychology details; a successful
        // profile read must not conceal an unavailable cognition response.
        cognition_envelope: rawMap['/api/cognition'] || E.unavailable('/api/cognition', '尚未读取认知状态'),
        config: st.config || {},
        sessions: Array.isArray(st.sessions) ? st.sessions : [],
        style: prof.style || {},
        personas_catalog: personas.items || [],
        personas_trash: personas.trash || [],
        active_persona_id: personas.active || prof.id,
        source: 'live'
      }, '/api/state → profile, identity, personas, sessions', prof.updated_at);
    }

    // 2. PersonalityState (Includes all 68 editable constructs from psychology_registry + disposition_registry)
    parsePersonalityState(rawMap) {
      const E = global.DataEnvelopeFactory;
      const stateEnv = rawMap['/api/state'];
      const u3Env = rawMap['/api/ui3/overview'];
      const revEnv = rawMap['/api/persona/revisions'];

      for (const [ep, env] of [['/api/state', stateEnv], ['/api/ui3/overview', u3Env], ['/api/persona/revisions', revEnv]]) {
        if (!env || env.status === 'error') {
          return E.error(ep, env?.error || `${ep} 请求失败`, env?.error_code || 'PERSONALITY_ERROR', env?.http_status);
        }
        if (env.status === 'unavailable') {
          return E.unavailable(ep, env.error);
        }
      }

      const st = stateEnv.data;
      const u3 = u3Env.data || {};
      const revs = Array.isArray(revEnv.data) ? revEnv.data : [];

      const prof = st.profile || {};
      const tp = prof.trait_profile || {};
      const constructs = tp.dispositions || {};
      const psychFeatures = (prof.psychology && prof.psychology.features) || {};
      const tSnap = st.trait_snapshot || {};
      const psychRegistry = Array.isArray(st.psychology_registry) ? st.psychology_registry : [];
      const dispRegistry = (st.disposition_registry && Array.isArray(st.disposition_registry.fields)) ? st.disposition_registry.fields : [];

      let knownCount = 0;
      let totalCount = 0;

      const hexaco = (u3.hexaco_domains || []).map(d => ({
        code: d.code,
        name: d.name_zh,
        name_en: d.name_en,
        val: d.estimate !== null && d.estimate !== undefined ? Number(d.estimate) : null,
        known_facet_count: d.known_facet_count ?? 0,
        total_facet_count: d.total_facet_count ?? 4,
        known: `${d.known_facet_count ?? 0}/${d.total_facet_count ?? 4}`,
        facets: d.facets || [],
        source: 'live'
      }));

      const snapBuckets = [
        { code: 'H', name: 'HEXACO 子维度块 (hexaco_facets)', map: tSnap.hexaco_facets || {} },
        { code: 'V', name: 'Schwartz 价值块 (value_priorities)', map: tSnap.value_priorities || {} },
        { code: 'I', name: '人际倾向块 (interpersonal_dispositions)', map: tSnap.interpersonal_dispositions || {} },
        { code: 'B', name: '行为与习惯倾向块 (behavioral_dispositions)', map: tSnap.behavioral_dispositions || {} },
        { code: 'D', name: '情绪动力学倾向块 (affective_disposition)', map: tSnap.affective_disposition || {} }
      ];
      const blocks68 = snapBuckets.map(b => {
        const entries = Object.entries(b.map);
        const total = entries.length;
        const vals = [];
        const knownNames = [];
        const items = [];
        entries.forEach(([fid, entry]) => {
          const hasEst = entry && entry.estimate !== null && entry.estimate !== undefined;
          if (hasEst) {
            vals.push(Number(entry.estimate));
            knownNames.push(`${fid.split('.').pop()}=${Number(entry.estimate).toFixed(2)}`);
          }
          items.push({
            id: fid,
            label: entry?.label || fid,
            estimate: hasEst ? Number(entry.estimate) : null,
            uncertainty: entry?.uncertainty ?? null,
            source_type: entry?.source_type || 'unknown'
          });
        });
        knownCount += vals.length;
        totalCount += total;
        const mean = vals.length > 0 ? vals.reduce((a, c) => a + c, 0) / vals.length : null;
        return {
          code: b.code,
          name: `${b.name} (${total}项)`,
          known: vals.length,
          total,
          mean,
          items,
          note: vals.length > 0
            ? `已建档: ${knownNames.slice(0, 3).join(', ')}${vals.length < total ? ` (其余 ${total - vals.length} 项为 null)` : ''}`
            : `全部 ${total} 项当前为 null（尚无证据或设定，不伪装为 0.5）`,
          source: 'live'
        };
      });

      // Build unified 68 editable constructs list from backend registry (61 LONG_IDS + 7 DISPOSITIONS)
      const editableConstructs = [];
      const evidenceRecords = [...(prof.psychology?.evidence_records || []), ...(prof.source_records || [])];
      const detailFields = (cur, id, path) => {
        const refs = cur.evidence_ids || cur.evidence || [];
        const evidence = Array.isArray(refs) ? refs.map(ref => {
          const key = typeof ref === 'string' ? ref : ref?.id;
          return evidenceRecords.find(record => record.id === key) || ref;
        }) : [];
        return {
          uncertainty: cur.uncertainty ?? cur.posterior_uncertainty ?? null,
          uncertainty_semantics: cur.uncertainty_semantics ?? null,
          evidence_count: cur.evidence_count ?? (Array.isArray(refs) ? refs.length : null),
          evidence_refs: refs,
          evidence,
          updated_at: global.formatBusinessTimestamp(cur.updated_at),
          history: (tp.promotion_history || []).filter(item => item.feature_id === id),
          field_path: path,
          raw: cur
        };
      };
      psychRegistry.filter(f => f.feature_temporality === 'long').forEach(f => {
        const cur = psychFeatures[f.id] || {};
        editableConstructs.push({
          id: f.id,
          name_zh: f.name_zh || f.id,
          group: f.group || 'CONSTRUCT',
          minimum: f.minimum ?? 0,
          maximum: f.maximum ?? 1,
          estimate: cur.estimate !== undefined ? cur.estimate : null,
          source_type: cur.source_type || 'unknown',
          ...detailFields(cur, f.id, `profile.psychology.features.${f.id}`),
          requires_timeframe_generally: false
        });
      });
      dispRegistry.forEach(f => {
        const cur = constructs[f.id] || {};
        editableConstructs.push({
          id: f.id,
          name_zh: f.name_zh || f.label || f.id,
          group: f.instrument || 'DISPOSITION',
          minimum: f.minimum ?? 0,
          maximum: f.maximum ?? 1,
          estimate: cur.estimate !== undefined ? cur.estimate : null,
          source_type: cur.source_type || 'unknown',
          ...detailFields(cur, f.id, `profile.trait_profile.dispositions.${f.id}`),
          requires_timeframe_generally: f.id.startsWith('panas.')
        });
      });

      const schwartz = (u3.schwartz_values || []).map(v => ({
        id: v.id,
        label: v.label,
        quadrant: v.quadrant,
        angle_deg: v.angle_deg ?? null,
        estimate: v.estimate !== null && v.estimate !== undefined ? Number(v.estimate) : null,
        uncertainty: v.uncertainty ?? 1.0,
        source_type: v.source_type || 'unknown'
      }));

      const updatedTs = tp.updated_at || (knownCount > 0 ? prof.updated_at : null);
      const statusOverride = knownCount === 0 ? 'empty' : 'success';

      return E.live({
        source: 'live',
        version: tp.version ?? 0,
        updated_at: global.formatBusinessTimestamp(updatedTs),
        known_count: knownCount,
        total_count: totalCount,
        hexaco,
        blocks68,
        editable_constructs: editableConstructs,
        schwartz_values: schwartz,
        interpersonal_2d: u3.interpersonal_2d || {},
        dispositions: dispRegistry.map(f => ({
          id: f.id,
          label: f.name_zh || f.label || f.id,
          estimate: constructs[f.id]?.estimate ?? null,
          source_type: constructs[f.id]?.source_type || 'unknown'
        })),
        revisions: revs,
        promotion_history: tp.promotion_history || []
      }, '/api/state + /api/ui3/overview + /api/persona/revisions', updatedTs, {
        constructs_68: 'live',
        hexaco_domains: 'derived_from_live',
        schwartz_values: 'live',
        revisions: 'live',
        revision_delta_timeline: 'unavailable',
        ...Object.fromEntries(editableConstructs.map(c => [c.id, c.estimate == null ? 'unavailable' : 'live']))
      }, {
        hexaco_domains: {
          derived_from: ['state.trait_snapshot.hexaco_facets'],
          formula: 'arithmetic_mean(non_null_facets_in_domain); null_when_all_facets_null (persona/ui3_projection.py)'
        }
      }, statusOverride);
    }

    // 3. EmotionState
    parseEmotionState(rawMap) {
      const E = global.DataEnvelopeFactory;
      const stateEnv = rawMap['/api/state'];
      const affEnv = rawMap['/api/affect'];
      const u3Env = rawMap['/api/ui3/overview'];

      for (const [ep, env] of [['/api/affect', affEnv], ['/api/ui3/overview', u3Env], ['/api/state', stateEnv]]) {
        if (!env || env.status === 'error') {
          return E.error(ep, env?.error || `${ep} 请求失败`, env?.error_code || 'EMOTION_ERROR', env?.http_status);
        }
        if (env.status === 'unavailable') {
          return E.unavailable(ep, env.error);
        }
      }

      const st = stateEnv.data;
      const affRes = affEnv.data || {};
      const u3 = u3Env.data || {};

      const aff2d = u3.affect_2d || {};
      const fast = aff2d.fast_emotion || {};
      const slow = aff2d.slow_mood || {};
      const move = aff2d.movement || {};
      const rawTraj = Array.isArray(aff2d.trajectory) ? aff2d.trajectory : [];
      const emoDetails = affRes.emotion_details || st.emotion_details || [];

      const known = Boolean(fast.known && fast.valence != null && fast.arousal != null);
      const valence = known ? Number(fast.valence) : null;
      const arousal = known ? Number(fast.arousal) : null;
      const dominance = fast.dominance !== null && fast.dominance !== undefined ? Number(fast.dominance) : null;
      const stress = fast.stress !== null && fast.stress !== undefined ? Number(fast.stress) : null;
      const engagement = fast.engagement !== null && fast.engagement !== undefined ? Number(fast.engagement) : null;

      const moodKnown = Boolean(slow.known && slow.valence != null && slow.arousal != null);
      const moodValence = moodKnown ? Number(slow.valence) : null;
      const moodArousal = moodKnown ? Number(slow.arousal) : null;

      // persona.affect.label_details returns intensity/name/unknown, not score.
      const categoryValue = c => c.unknown === true || c.known === false ? null : (c.intensity ?? c.activation ?? c.score ?? null);
      const sortedCats = Array.isArray(emoDetails)
        ? [...emoDetails].sort((a, b) => Number(categoryValue(b) ?? -1) - Number(categoryValue(a) ?? -1))
        : [];
      const topCat1 = sortedCats[0] ? (sortedCats[0].name || sortedCats[0].label_zh || sortedCats[0].label || sortedCats[0].id) : null;
      const topCat2 = sortedCats[1] ? (sortedCats[1].name || sortedCats[1].label_zh || sortedCats[1].label || sortedCats[1].id) : null;

      const palette = global.deriveAffectColorPalette(valence, arousal, known);

      const eventsPoints = rawTraj.map((pt, idx) => ({
        index: idx + 1,
        event_id: pt.event_id ?? null,
        scope: pt.scope ?? null,
        person_id: pt.person_id ?? null,
        raw: pt,
        at: pt.at,
        t: pt.event_id ? `事件 ${String(pt.event_id).slice(0, 10)}` : `轨迹点 #${idx + 1}`,
        time_str: global.formatLocalDisplayTime ? global.formatLocalDisplayTime(pt.at) : global.formatBusinessTimestamp(pt.at),
        v: pt.valence !== null && pt.valence !== undefined ? Number(pt.valence) : null,
        a: pt.arousal !== null && pt.arousal !== undefined ? Number(pt.arousal) : null,
        m: pt.mood_valence !== null && pt.mood_valence !== undefined ? Number(pt.mood_valence) : null,
        cause: pt.cause_category || 'event_reaction',
        note: pt.summary || '真实情绪演化节点',
        source: 'live'
      })).filter(pt => pt.v !== null && pt.a !== null);

      const dx = Number(move.dx_valence || 0);
      const dy = Number(move.dy_arousal || 0);
      const deltaLabel = eventsPoints.length >= 2
        ? `较上一点 ΔV ${dx >= 0 ? '+' : ''}${dx.toFixed(3)} · ΔA ${dy >= 0 ? '+' : ''}${dy.toFixed(3)}`
        : (eventsPoints.length === 1 ? '首条实测情绪快照 (共 1 个离散点)' : '尚无历史轨迹点 (0 点)');

      const badge = !known
        ? '未知 · 尚无情绪观测'
        : (topCat1 ? `${topCat1}${topCat2 ? ' · ' + topCat2 : ''}` : (valence >= 0 ? '平和 · 专注' : '内省 · 沉思'));

      const headline = !known
        ? '心情还在等待观察'
        : (palette.quadrant_label || '此刻的情绪');

      const desc = !known
        ? '互动之后，可以在这里看到情绪观察；未记录的感受会保留为待观察。'
        : `最近变化：${String(move.latest_summary || '当前情绪观察已更新').replace(/\s*\([a-z_]+\)/g, '')}`;

      const updatedTs = (known ? fast.last_updated : null) || (moodKnown ? slow.updated_at : null) || (eventsPoints[eventsPoints.length - 1]?.at ?? null);
      const statusOverride = known || moodKnown ? 'success' : 'empty';

      return E.live({
        source: 'live',
        known,
        badge,
        headline,
        desc,
        valence,
        arousal,
        dominance,
        stress,
        engagement,
        mood_known: moodKnown,
        mood_valence: moodValence,
        mood_arousal: moodArousal,
        fast_emotion: fast,
        slow_mood: slow,
        delta_label: deltaLabel,
        palette,
        categorical_list: sortedCats.slice(0, 24).map(c => ({
          id: c.id || c.label,
          name: c.name || c.label_zh || c.label || c.id,
          activation: categoryValue(c) == null ? null : Number(categoryValue(c)),
          known: c.unknown === true ? false : c.known,
          source_type: c.source ?? c.source_type ?? null,
          updated_at: global.formatBusinessTimestamp(c.last_triggered_at ?? c.updated_at),
          evidence: c.evidence ?? c.evidence_refs ?? (c.source_event_id ? [{ event_id: c.source_event_id, quote: c.quote, scope: c.scope }] : null),
          raw: c
        })),
        events_points: eventsPoints,
        continuous_24h_status: 'unavailable',
        continuous_7d_status: 'unavailable'
      }, '/api/affect + /api/ui3/overview', updatedTs, {
        fast_emotion: known ? 'live' : 'unavailable',
        slow_mood: moodKnown ? 'live' : 'unavailable',
        discrete_trajectory: 'live',
        color_palette: 'derived_from_live',
        continuous_24h_series: 'unavailable',
        continuous_7d_series: 'unavailable'
      }, {
        color_palette: {
          derived_from: palette.derived_from,
          formula: palette.formula
        }
      }, statusOverride);
    }

    // 4. ExpressionDrive
    parseExpressionDrive(rawMap) {
      const E = global.DataEnvelopeFactory;
      const edEnv = rawMap['/api/pmm283/expressive-drive'];
      const u3Env = rawMap['/api/ui3/overview'];

      if (!edEnv || edEnv.status === 'error') {
        return E.error('/api/pmm283/expressive-drive', edEnv?.error || '表达欲接口请求失败', edEnv?.error_code || 'DRIVE_ERROR', edEnv?.http_status);
      }
      if (edEnv.status === 'unavailable') {
        return E.unavailable('/api/pmm283/expressive-drive', edEnv.error);
      }

      const edRes = edEnv.data || {};
      const u3 = (u3Env && u3Env.status === 'success' && u3Env.data) ? u3Env.data : {};
      const edDetail = u3.expressive_drive_detail || {};

      // Stage 2 uses the status endpoint as its source of current metrics and
      // joins richer motive records only by an actual stream/motive identifier.
      // The accepted home retains its existing projection below.
      const visualStreams = (Array.isArray(edRes.streams) ? edRes.streams : []).map(row => {
        const detail = (edDetail.streams || []).find(s => s.stream_key === row.stream_key) || {};
        const motives = new Map();
        for (const m of (Array.isArray(detail.motives) ? detail.motives : [])) {
          if (m?.motive_id) motives.set(m.motive_id, m);
        }
        for (const m of (Array.isArray(row.unfinished_motives) ? row.unfinished_motives : [])) {
          if (m?.motive_id) motives.set(m.motive_id, { ...motives.get(m.motive_id), ...m });
        }
        return { ...detail, ...row, motives: [...motives.values()],
          observed_tendencies: Array.isArray(row.tendencies) ? row.tendencies : [],
          detail_status: u3Env?.status || 'unavailable' };
      });

      const streams = Array.isArray(edDetail.streams) && edDetail.streams.length > 0
        ? edDetail.streams
        : (Array.isArray(edRes.streams) ? edRes.streams : []);
      const activeStream = streams.length > 0 ? streams[0] : null;
      const unfinished = Array.isArray(edDetail.unfinished_motives) && edDetail.unfinished_motives.length > 0
        ? edDetail.unfinished_motives
        : (Array.isArray(activeStream?.unfinished_motives) ? activeStream.unfinished_motives : (Array.isArray(edRes.unfinished_motives) ? edRes.unfinished_motives : []));
      const topMotive = unfinished.length > 0 ? unfinished[0] : null;

      const hasStream = Boolean(activeStream && activeStream.activation !== null && activeStream.activation !== undefined);
      const activation = hasStream ? Number(activeStream.activation) : null;
      const urgency = hasStream ? Number(activeStream.urgency ?? 0) : null;
      const persistence = hasStream ? Number(activeStream.persistence ?? 0) : null;
      const inhibition = hasStream && activeStream.inhibition != null ? Number(activeStream.inhibition) : null;
      const intent = hasStream ? (activeStream.expressive_intent || 'LISTEN') : null;

      const proactivePct = hasStream ? Math.round(Math.min(1, Math.max(0, 0.6 * urgency + 0.4 * activation)) * 100) : null;
      const supplementPct = hasStream ? Math.round(Math.min(1, Math.max(0, 0.65 * persistence + 0.35 * activation)) * 100) : null;
      const followUpPct = hasStream ? Math.round(Math.min(1, Math.max(0, 0.75 * activation + (unfinished.length > 0 ? 0.15 : 0))) * 100) : null;

      const motiveTopic = topMotive
        ? ((topMotive.content_anchor && topMotive.content_anchor.topic) || topMotive.topic || '未命名表达主题')
        : null;
      const motiveGoal = topMotive
        ? ((topMotive.intended_expression && topMotive.intended_expression.intended_goal) || topMotive.intended_goal || '')
        : null;

      const thoughtQuote = topMotive
        ? `关于「${motiveTopic}」：${motiveGoal || '想在合适的时候再聊聊'}`
        : (hasStream
          ? `${(global.DisplayText?.label(intent) || intent)}。暂时没有记下尚未说完的话题。`
          : '暂时没有想继续表达的话题。');

      const tendencies = [
        {
          label: '主动发言倾向',
          pct: proactivePct,
          note: hasStream ? '派生公式: round((0.6*urgency + 0.4*activation)*100)' : '无活跃流 (streams=[])，数值为 null (未知)',
          source: hasStream ? 'derived_from_live' : 'unavailable'
        },
        {
          label: '补充表达倾向',
          pct: supplementPct,
          note: hasStream ? '派生公式: round((0.65*persistence + 0.35*activation)*100)' : '无活跃流 (streams=[])，数值为 null (未知)',
          source: hasStream ? 'derived_from_live' : 'unavailable'
        },
        {
          label: '主动追问倾向',
          pct: followUpPct,
          note: hasStream ? '派生公式: round(clamp(0.75*activation + 0.15*has_unfinished_motive, 0, 1)*100)' : '无活跃流 (streams=[])，数值为 null (未知)',
          source: hasStream ? 'derived_from_live' : 'unavailable'
        }
      ];

      const streamUpdatedAt = activeStream ? (activeStream.updated_at || activeStream.last_updated_at || null) : null;
      const statusOverride = hasStream ? 'success' : 'empty';

      return E.live({
        source: hasStream ? 'live' : 'unavailable',
        has_active_stream: hasStream,
        revision: edRes.revision ?? 0,
        calibration_status: edRes.calibration_status || 'uncalibrated_engineering_initial',
        activation,
        urgency,
        persistence,
        inhibition,
        intent,
        level_label: hasStream
          ? `实测激活 ${(activation * 100).toFixed(1)}% · 意图 ${intent}`
          : '无活跃流 (streams=[] · 数值未知 null)',
        thought_quote: thoughtQuote,
        motive_id: topMotive ? topMotive.motive_id : null,
        motive_topic: motiveTopic,
        motive_status: topMotive ? topMotive.status : null,
        motive_activation: topMotive ? Number(topMotive.activation || 0) : null,
        unfinished_count: unfinished.length,
        unfinished_motives: unfinished,
        streams_count: streams.length,
        streams,
        visual_streams: visualStreams,
        observed_tendencies: Array.isArray(edRes.tendencies) ? edRes.tendencies : [],
        detail_status: u3Env?.status || 'unavailable',
        status_endpoint: edEnv.endpoint,
        recent_history: edRes.recent_history || [],
        tendencies,
        influence_note: hasStream
          ? `激活度 ${(activation * 100).toFixed(0)}% · 紧迫度 ${(urgency * 100).toFixed(0)}% · 持续度 ${(persistence * 100).toFixed(0)}%。点击详情了解当前话题。`
          : '当前没有活跃话题，表达状态等待下一次互动。'
      }, '/api/pmm283/expressive-drive + /api/ui3/overview', streamUpdatedAt, {
        has_active_stream: 'live',
        revision: 'live',
        activation: hasStream ? 'live' : 'unavailable',
        urgency: hasStream ? 'live' : 'unavailable',
        persistence: hasStream ? 'live' : 'unavailable',
        expressive_intent: hasStream ? 'live' : 'unavailable',
        unfinished_motives: 'live',
        tendencies: hasStream ? 'derived_from_live' : 'unavailable',
        visual_streams: 'live',
        observed_tendencies: visualStreams.some(s => s.observed_tendencies.length) || Array.isArray(edRes.tendencies) ? 'live' : 'unavailable',
        manual_motive_creation: 'unavailable'
      }, hasStream ? {
        tendencies: {
          derived_from: ['streams[0].activation', 'streams[0].urgency', 'streams[0].persistence', 'unfinished_motives.length'],
          formula: 'proactive=0.6*U+0.4*A; supplement=0.65*P+0.35*A; follow_up=0.75*A+0.15*(unfinished>0)'
        }
      } : {}, statusOverride);
    }

    // 5. PsychologicalState
    parsePsychologicalState(emoEnv, driveEnv, rawMap) {
      const E = global.DataEnvelopeFactory;
      if (emoEnv.status === 'error') {
        return E.error(emoEnv.endpoint, emoEnv.error, emoEnv.error_code, emoEnv.http_status);
      }
      const emo = emoEnv.data || {};
      const drv = driveEnv.data || {};
      return E.live({
        known: Boolean(emo.known),
        badge: emo.badge,
        headline: emo.headline,
        desc: emo.desc,
        palette: emo.palette,
        thought_quote: drv.thought_quote,
        motive_id: drv.motive_id
      }, '/api/ui3/overview + /api/affect + /api/pmm283/expressive-drive', emoEnv.updated_at, {
        badge: 'derived_from_live',
        palette: 'derived_from_live',
        thought_quote: driveEnv.status === 'error' ? 'unavailable' : 'live'
      }, {
        palette: {
          derived_from: ['affect_2d.fast_emotion.valence', 'affect_2d.fast_emotion.arousal'],
          formula: emo.palette?.formula || 'quadrant_interpolation'
        }
      }, emo.known ? 'success' : 'empty');
    }

    // 6. MemoryCollection
    parseMemories(rawMap) {
      const E = global.DataEnvelopeFactory;
      const memsRes = rawMap['/api/memories'];
      const u3Env = rawMap['/api/ui3/overview'];
      const u3 = u3Env?.status === 'success' ? (u3Env.data || {}) : {};
      if (!memsRes || memsRes.status === 'error') {
        return E.error('/api/memories', memsRes?.error || '读取记忆列表失败', memsRes?.error_code || 'MEMORY_ERROR', memsRes?.http_status);
      }
      if (memsRes.status === 'unavailable') {
        return E.unavailable('/api/memories', memsRes.error);
      }
      const list = Array.isArray(memsRes.data) ? memsRes.data : [];
      const counts = { episode: 0, fact: 0, preference: 0, boundary: 0, other: 0 };
      let latestUpd = null;
      list.forEach(m => {
        const k = m.kind || 'other';
        if (k in counts) counts[k] += 1;
        else counts.other += 1;
        const ts = m.updated_at || m.created_at;
        if (ts && (!latestUpd || ts > latestUpd)) latestUpd = ts;
      });
      const graphAvailable = u3Env?.status === 'success' && Array.isArray(u3.memory_relation_graph?.nodes) && Array.isArray(u3.memory_relation_graph?.edges);
      const motiveIndex = new Map((u3.expressive_drive_detail?.all_motives || []).map(m => [m.motive_id, m]));
      const graph = graphAvailable ? {
        nodes: u3.memory_relation_graph.nodes.map(node => {
          const motive = node.motive_id ? motiveIndex.get(node.motive_id) : null;
          return motive ? { ...node, scope: node.scope ?? motive.scope ?? null, person_id: node.person_id ?? motive.person_id ?? null } : node;
        }),
        edges: u3.memory_relation_graph.edges
      } : { nodes: [], edges: [] };
      const graphEnvelope = graphAvailable
        ? E.live(graph, '/api/ui3/overview → memory_relation_graph', null, { nodes: 'live', edges: 'live' })
        : (u3Env?.status === 'error' ? E.error('/api/ui3/overview', u3Env.error, u3Env.error_code, u3Env.http_status) : E.unavailable('/api/ui3/overview', '当前没有可用的记忆图谱响应'));
      return E.live({
        source: 'live',
        total_count: list.length,
        by_kind_counts: counts,
        items: list.map(m => ({
          id: m.id,
          content: m.content || '',
          kind: m.kind || 'episode',
          scope: m.scope ?? null,
          person: m.person ?? null,
          importance: m.importance == null ? null : Number(m.importance),
          confidence: m.confidence == null ? null : Number(m.confidence),
          status: m.status || 'active',
          evidence: m.evidence || m.quote || '',
          source_turn: m.source_turn ?? null,
          memory_strength: m.memory_strength ?? null,
          raw: m,
          created_at: global.formatBusinessTimestamp(m.created_at),
          updated_at: global.formatBusinessTimestamp(m.updated_at),
          display_time: global.formatLocalDisplayTime ? global.formatLocalDisplayTime(m.updated_at || m.created_at) : '',
          source: 'live'
        })),
        relation_graph: graph,
        relation_graph_envelope: graphEnvelope
      }, '/api/memories + /api/ui3/overview → memory_relation_graph', latestUpd, {
        memories: 'live',
        relation_graph: graphAvailable ? 'live' : 'unavailable'
      }, {}, list.length === 0 ? 'empty' : 'success');
    }

    // 7. ExperienceCollection (Strictly maps evaluated turns from /api/de/turns, separated from Parlor /api/messages)
    parseExperiences(rawMap) {
      const E = global.DataEnvelopeFactory;
      const deEnv = rawMap['/api/de/turns'];
      if (!deEnv || deEnv.status === 'error') {
        return E.error('/api/de/turns', deEnv?.error || '读取回合经历失败', deEnv?.error_code || 'EXPERIENCE_ERROR', deEnv?.http_status);
      }
      if (deEnv.status === 'unavailable') {
        return E.unavailable('/api/de/turns', deEnv.error);
      }
      const rows = Array.isArray(deEnv.data?.rows) ? deEnv.data.rows : [];
      let latestAt = null;
      const items = rows.map(r => {
        const joint = r.joint || {};
        const ev = joint.event || {};
        const usageList = Array.isArray(joint.usage) ? joint.usage : [];
        const emoUsage = usageList.find(u => u && u.condition === 'emotion');
        const evVal = emoUsage && emoUsage.basis && emoUsage.basis.tone_terms && emoUsage.basis.tone_terms.event_valence !== undefined
          ? Number(emoUsage.basis.tone_terms.event_valence)
          : null;
        const affAfter = (r.affect_after && r.affect_after.emotion) || r.affect_after || {};
        const v = affAfter.valence !== undefined && affAfter.valence !== null ? Number(affAfter.valence) : evVal;
        const a = affAfter.arousal !== undefined && affAfter.arousal !== null ? Number(affAfter.arousal) : null;
        const driveIntent = joint.expressive_drive_intent || '';
        const emoStr = v !== null
          ? `V:${v >= 0 ? '+' : ''}${v.toFixed(2)}${driveIntent ? ' · ' + driveIntent : ''}`
          : (driveIntent || r.strategy || '已评估回合');
        const act = r.strategy || r.action || (r.decision && r.decision.action) || 'reply';
        const quoteText = ev.quote || r.user_text || r.input || '对话互动事件';
        const replyText = Array.isArray(r.actual_parts) && r.actual_parts.length > 0
          ? r.actual_parts.join(' ')
          : (r.reply || '');
        const rawTs = r.at || r.created_at || r.timestamp || null;
        if (rawTs && (!latestAt || rawTs > latestAt)) latestAt = rawTs;
        return {
          id: r.turn_id || r.id,
          title: quoteText,
          reply: replyText,
          strategy: act,
          planned_bubbles: r.planned_bubbles ?? 1,
          actual_confirmed: r.actual_confirmed ?? 1,
          delivery: r.delivery || 'LOCAL_COMMITTED',
          usage: usageList,
          time: global.formatBusinessTimestamp(rawTs),
          display_time: global.formatLocalDisplayTime ? global.formatLocalDisplayTime(rawTs, false) : '',
          emo: emoStr,
          appraisal: `策略: ${act} (${r.delivery || 'COMMITTED'}) · 回复: “${String(replyText).slice(0, 42)}”`,
          scope: r.scope || ev.scope || 'private:web:owner',
          person: ev.person || 'web:owner',
          source: 'live'
        };
      });

      return E.live({
        source: 'live',
        total_count: deEnv.data?.total ?? items.length,
        items,
        // The new timeline keeps missing receipts unknown; legacy summary fields
        // remain available to the accepted homepages and developer views.
        visual_items: rows.map(r => ({
          id: r.turn_id || r.id, raw: r,
          text: r.joint?.event?.quote ?? r.user_text ?? r.input ?? null,
          session_id: r.session_id ?? r.joint?.event?.session_id ?? null,
          scope: r.scope ?? r.joint?.event?.scope ?? null,
          person: r.joint?.event?.person ?? r.person ?? null,
          event_type: r.joint?.event?.type ?? r.joint?.event?.kind ?? r.event_type ?? null,
          event_id: r.event_id ?? r.joint?.event?.event_id ?? r.joint?.event?.id ?? null,
          at: global.formatBusinessTimestamp(r.at ?? r.created_at ?? r.timestamp),
          strategy: r.strategy ?? r.action ?? r.decision?.action ?? null,
          actual_parts: Array.isArray(r.actual_parts) ? r.actual_parts : [],
          reply: r.reply ?? null, delivery: r.delivery ?? null,
          actual_confirmed: r.actual_confirmed ?? null,
          appraisal: r.appraisal ?? r.joint?.appraisal ?? null,
          affect_after: r.affect_after ?? null, usage: r.joint?.usage ?? [],
          trace: r.trace ?? r.trace_id ?? null, error: r.error ?? null
        })),
        autobiographical_table_source: 'unavailable'
      }, '/api/de/turns → rows', latestAt, {
        evaluated_turns: 'live',
        autobiographical_long_term_table: 'unavailable'
      }, {}, items.length === 0 ? 'empty' : 'success');
    }

    // 8. LearningTaskCollection
    parseLearningTasks(rawMap) {
      const E = global.DataEnvelopeFactory;
      const learnEnv = rawMap['/api/learning'];
      const actEnv = rawMap['/api/learning/activities'];
      const stateEnv = rawMap['/api/state'];

      if (!learnEnv || learnEnv.status === 'error') {
        return E.error('/api/learning', learnEnv?.error || '读取学习队列失败', learnEnv?.error_code || 'LEARNING_ERROR', learnEnv?.http_status);
      }
      if (learnEnv.status === 'unavailable') {
        return E.unavailable('/api/learning', learnEnv.error);
      }

      const st = (stateEnv && stateEnv.data) || {};
      const learn = learnEnv.data || {};
      const acts = (actEnv && actEnv.status === 'success' && Array.isArray(actEnv.data)) ? actEnv.data : [];
      const cands = (st.trait_review && Array.isArray(st.trait_review.candidates)) ? st.trait_review.candidates : [];

      let latestJobTs = null;
      const jobs = Array.isArray(learn.jobs) ? learn.jobs.map(j => {
        const targetKey = j.target || 'self';
        const targetLabel = TARGET_LABELS[targetKey] || `学习任务(${targetKey})`;
        const scopeStr = Array.isArray(j.scopes) && j.scopes.length > 0 ? j.scopes.join(', ') : (j.scope || 'self:imported');
        const cursor = Number(j.cursor ?? 0);
        const sourceCount = Number(j.source_count ?? 0);
        const isDone = j.status === 'completed' || j.status === 'analysis_complete' || j.status === 'awaiting_review' || j.status === 'done';
        const computedProgress = j.progress !== undefined
          ? Number(j.progress)
          : (isDone ? 100 : (sourceCount > 0 ? Math.round((cursor / sourceCount) * 100) : 0));
        const title = j.title || j.summary || `${targetLabel} · ${scopeStr} (${cursor}/${sourceCount || 1})`;
        const phase = j.phase || `${j.status || 'ready'} · 已处理 ${cursor}/${sourceCount} 条原文 (模式: ${j.intent || 'review'})`;
        const rawTs = j.updated_at || j.created_at || null;
        if (rawTs && (!latestJobTs || rawTs > latestJobTs)) latestJobTs = rawTs;
        return {
          id: j.id,
          kind: j.kind || 'learning',
          target: targetKey,
          intent: j.intent || 'review',
          title,
          name: title,
          status: j.status || 'ready',
          progress: global.clampNumber ? global.clampNumber(computedProgress, 0, 100, 0) : Math.max(0, Math.min(100, computedProgress)),
          phase,
          detail: phase,
          cursor,
          source_count: sourceCount,
          scopes: Array.isArray(j.scopes) ? j.scopes : [scopeStr],
          person: j.person || '',
          can_rollback: Boolean(j.can_rollback),
          created_at: global.formatBusinessTimestamp(j.created_at),
          updated_at: global.formatBusinessTimestamp(rawTs),
          source: 'live'
        };
      }) : [];

      return E.live({
        source: 'live',
        running: Boolean(learn.running),
        total_jobs: learn.total_jobs ?? jobs.length,
        processed_sources: learn.processed_sources ?? 0,
        available_scopes: learn.available_scopes || ['private:web:owner', 'self:imported'],
        policy: learn.policy || {},
        experience_learning: learn.experience_learning || null,
        other_status: learn.other_status || [],
        jobs,
        items: jobs,
        activities: acts,
        candidates: cands,
        activities_envelope: actEnv || E.unavailable('/api/learning/activities', '尚未读取学习活动'),
        candidates_envelope: stateEnv?.status === 'success'
          ? E.live(cands, '/api/state → trait_review.candidates', null, { candidates: 'live' })
          : stateEnv || E.unavailable('/api/state', '尚未读取候选证据'),
        raw_jobs: Array.isArray(learn.jobs) ? learn.jobs : [],
        periodic_scheduler_status: learn.experience_learning ? 'live' : 'unavailable',
        growth_summary_source: 'unavailable'
      }, '/api/learning + /api/learning/activities + /api/state → trait_review', latestJobTs, {
        jobs: 'live',
        activities: (actEnv && actEnv.status === 'success') ? 'live' : 'unavailable',
        trait_candidates: 'live',
        periodic_scheduler: 'unavailable',
        long_term_growth_summary: 'unavailable'
      });
    }

    // 9. SocialGraphCollection
    parseSocialGraph(rawMap, scope = 'private:web:owner') {
      const E = global.DataEnvelopeFactory;
      const sgEnv = rawMap['/api/social-graph'];
      const ppEnv = rawMap['/api/people'];
      const relEnv = rawMap['/api/relations'];

      for (const [ep, env] of [['/api/social-graph', sgEnv], ['/api/people', ppEnv], ['/api/relations', relEnv]]) {
        if (!env || env.status === 'error') {
          return E.error(ep, env?.error || `${ep} 请求失败`, env?.error_code || 'SOCIAL_ERROR', env?.http_status);
        }
        if (env.status === 'unavailable') {
          return E.unavailable(ep, env.error);
        }
      }

      const sg = sgEnv.data || {};
      const pp = ppEnv.data || {};
      const rels = Array.isArray(relEnv.data) ? relEnv.data : (relEnv.data?.relations || []);

      const nodes = Array.isArray(sg.nodes) ? sg.nodes : [];
      const edges = Array.isArray(sg.edges) ? sg.edges : [];
      const claims = Array.isArray(sg.claims) ? sg.claims : [];
      const people = (Array.isArray(pp.people) ? pp.people : (Array.isArray(pp) ? pp : [])).filter(p => p.scope === scope);
      // Legacy relation rows are only usable when their embedded dyad explicitly
      // belongs to this scope. Never merge a person's private and group state.
      for (const row of rels) {
        const dyad = row.data?.dyad;
        if (dyad?.context_id !== scope || !dyad.other_id || people.some(p => p.person_id === dyad.other_id)) continue;
        people.push({ person_id: dyad.other_id, scope, alias: row.name || dyad.other_id, relationship: dyad,
          direct_interaction: dyad.interactions > 0, identity_evidence: [], identity_status: 'local_identifier_unverified' });
      }
      const scopedClaims = Array.isArray(sg.relation_claims) ? sg.relation_claims.filter(c => c.scope_id === scope) : claims;
      const scopedPeople = Array.isArray(sg.people) ? sg.people : [];
      // social-graph/1 exposes people and directed claims, not nodes/edges.
      // Project those exact records; memberships alone never generate an edge.
      const topologyNodes = Array.isArray(sg.nodes) ? sg.nodes : scopedPeople.map(p => ({ ...p, id: p.person_id || p.id, label: p.display_name || p.person_id || p.id, raw: p }));
      const topologyEdges = Array.isArray(sg.edges) ? sg.edges : scopedClaims.map(c => ({ ...c, source: c.subject_person_id, target: c.object_person_id, label: c.relation_type, raw: c }));
      for (const person of people) {
        if (!topologyNodes.some(n => n.id === person.person_id)) topologyNodes.push({ id: person.person_id, label: person.alias || person.person_id, raw: person });
      }
      const st = rawMap['/api/state']?.data || {}, personaId = pp.self?.persona_id || st.identity?.id || st.profile?.id;
      const selfId = personaId ? `agent:${personaId}` : null;
      if (selfId) {
        topologyNodes.unshift({ id: selfId, label: st.profile?.name || st.identity?.name || '当前角色', entity_type: 'agent_self', raw: pp.self });
        for (const person of people) {
          const relationship = person.relationship;
          if (!relationship && !person.direct_interaction) continue;
          topologyEdges.push({ id: `dyad:${scope}:${person.person_id}`, source: selfId, target: person.person_id,
            kind: relationship ? 'dyad' : 'interaction', label: relationship ? '互动关系' : '已有交谈', status: 'observed',
            scope_id: scope, relationship: relationship || null, evidence: relationship?.belief_provenance || [],
            updated_at: relationship?.updated_at || null, raw: { person_id: person.person_id, scope, relationship, direct_interaction: person.direct_interaction } });
        }
      }
      const sessions = Array.isArray(st.sessions) ? st.sessions : [];
      const availableScopes = [...new Set([scope, ...(sg.available_scopes || []), ...sessions.map(s => s.scope).filter(Boolean), ...rels.map(r => r.data?.dyad?.context_id).filter(Boolean)])];

      return E.live({
        source: 'live',
        scope: sg.scope || scope,
        self_id: selfId,
        available_scopes: availableScopes,
        scope_options: availableScopes.map(s => ({ value: s, label: (global.DisplayText?.scope(s) || s), session_count: sessions.filter(row => row.scope === s).length })),
        nodes,
        edges,
        claims,
        people,
        relations: rels,
        topology: { nodes: topologyNodes, edges: topologyEdges, claims: scopedClaims,
          memberships: Array.isArray(sg.memberships) ? sg.memberships.filter(m => m.context_id === scope) : [],
          contexts: sg.contexts || [], version: sg.version ?? null },
        raw_graph: sg,
        summary: sg.summary || { node_count: topologyNodes.length, edge_count: topologyEdges.length }
      }, `/api/social-graph?scope=${scope} + /api/people + /api/relations`, sg.updated_at ?? null, {
        social_graph: 'live',
        people: 'live',
        relations: 'live',
        topology: 'derived_from_live'
      }, { topology: { derived_from: ['social-graph.people', 'social-graph.relation_claims', 'people.self', 'people.people.relationship', 'people.people.direct_interaction'], formula: 'exact scoped people and claims; self-to-person links only for recorded dyads or direct interaction; no inferred friendship' } }, (people.length === 0 && topologyNodes.every(n => n.entity_type === 'agent_self')) ? 'empty' : 'success');
    }
  }

  global.PMMAdapter = PMMAdapter;
})(typeof window !== 'undefined' ? window : globalThis);
