/** Empty preview data. Live data always comes from the local backend. */
(function (global) {
  global.__HUAIAN_LIVE_BUNDLE__ = null;
  global.__HUAIAN_MOCK_DEMO_BUNDLE__ = {
    _source: 'mock', _notice: '纯净源码版本未附带演示记录',
    persona: { name: '尚未载入角色', source: 'mock' },
    emotion: { known: false, valence: null, arousal: null, source: 'mock' },
    personality: { known_count: 0, total_count: 68, hexaco: [], blocks68: [], schwartz_values: [], revisions: [] },
    drive: { has_active_stream: false, activation: null, urgency: null, persistence: null, unfinished_count: 0, tendencies: [] },
    memories: [], experiences: [], learning: { jobs: [], activities: [], candidates: [] }
  };
})(typeof window !== 'undefined' ? window : globalThis);
