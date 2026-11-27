/**
 * Empty preview adapter for the public source release.
 * Retains every envelope expected by the UI, without fictional runtime records.
 * Real connection errors must remain errors; never use preview as a LIVE fallback.
 */
(function (global) {
  class MockAdapter {
    constructor() { this.adapterName = 'MockAdapter'; this.mode = 'mock'; }
    getAllMockEnvelopes() {
      const E = global.DataEnvelopeFactory;
      const D = global.__HUAIAN_MOCK_DEMO_BUNDLE__ || {};
      const mock = (data, endpoint) => E.mock(data, 'mock://' + endpoint, '空白预览，未附带数据');
      const palette = global.deriveAffectColorPalette(null, null, false);
      return {
        mode: 'mock', overall_status: 'mock', ok_endpoints_count: 0, error_endpoints_count: 0,
        total_endpoints_count: 0, fetched_at: global.nowFetchedAt(),
        characterProfile: mock(D.persona || {}, 'persona'),
        personality: mock(D.personality || {}, 'personality'),
        emotion: mock({ ...D.emotion, palette }, 'emotion'),
        psychological: mock({ known: false, badge: '尚无记录', headline: '尚无心理状态记录', desc: '请连接后端并创建自己的角色。', palette }, 'psychological'),
        expressionDrive: mock(D.drive || { has_active_stream: false }, 'expressive-drive'),
        memories: mock({ total_count: 0, by_kind_counts: {}, items: [], relation_graph: { nodes: [], edges: [] } }, 'memories'),
        experiences: mock({ total_count: 0, items: [], autobiographical_table_source: 'unavailable' }, 'experiences'),
        learning: mock({ jobs: [], items: [], total_jobs: 0, activities: [], candidates: [] }, 'learning'),
        socialGraph: mock({ scope: 'private:web:owner', nodes: [], edges: [], claims: [], people: [], relations: [] }, 'social-graph'),
        connections: mock({ overall_badge: '空白预览 · 未连接后端', overall_healthy: false, nodes: {}, user_summary_rows: [] }, 'connections'),
        decisions: mock({ general_llm: {}, api_pmm: {}, learned_pmm: {}, fusion: { has_trace: false }, traces_count: 0, traces: [] }, 'decisions')
      };
    }
  }
  global.MockAdapter = MockAdapter;
})(typeof window !== 'undefined' ? window : globalThis);
