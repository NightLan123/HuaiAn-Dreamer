/**
 * 槐安梦客 Phase 2.3 — Unified DataEnvelope<T>, ISO 8601 UTC Timestamps & Safe HTML Escaping
 * - fetched_at: 前端实际发起 HTTP 采集的 UTC ISO 8601 时间戳（严格保留末尾 'Z'，如 2026-11-11T11:20:00.123Z）
 * - updated_at: 后端业务对象真实发生变更的 UTC ISO 8601 时间戳（若后端未提供或尚无业务事件，严格保持 null）
 * - formatLocalDisplayTime: 将 ISO 8601 或秒级时间戳格式化为本地时区可读字符串供 UI 显示
 * - escapeHtml: 全局防 XSS 转义函数
 */
(function (global) {
  function nowFetchedAt() {
    return new Date().toISOString();
  }

  function formatBusinessTimestamp(ts) {
    if (ts === null || ts === undefined || ts === '') return null;
    if (typeof ts === 'number' && isFinite(ts) && ts > 0) {
      const ms = ts > 1e11 ? ts : ts * 1000;
      return new Date(ms).toISOString();
    }
    if (typeof ts === 'string') {
      const trimmed = ts.trim();
      if (!trimmed) return null;
      const parsed = Date.parse(trimmed);
      if (!isNaN(parsed)) {
        return new Date(parsed).toISOString();
      }
      return trimmed;
    }
    return null;
  }

  function formatLocalDisplayTime(ts, includeDate = true) {
    const iso = formatBusinessTimestamp(ts);
    if (!iso) return '—';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(ts);
    const pad = n => String(n).padStart(2, '0');
    const timePart = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    if (!includeDate) return timePart;
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${timePart}`;
  }

  function escapeHtml(raw) {
    if (raw === null || raw === undefined) return '';
    return String(raw)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
      .replace(/`/g, '&#96;');
  }

  function clampNumber(val, minVal = 0, maxVal = 100, fallback = 0) {
    const n = Number(val);
    if (!isFinite(n)) return fallback;
    return Math.max(minVal, Math.min(maxVal, n));
  }

  const DataEnvelopeFactory = {
    live(data, endpoint, updatedAt, fieldSources, derivations, statusOverride) {
      return {
        data,
        source: 'live',
        fetched_at: nowFetchedAt(),
        updated_at: formatBusinessTimestamp(updatedAt),
        status: statusOverride || 'success',
        error: null,
        error_code: null,
        endpoint: endpoint || '/api/state',
        field_sources: fieldSources || {},
        derivations: derivations || {}
      };
    },
    mock(data, endpoint, reason, fieldSources, updatedAt) {
      return {
        data,
        source: 'mock',
        fetched_at: nowFetchedAt(),
        updated_at: formatBusinessTimestamp(updatedAt),
        status: 'success',
        error: reason || '当前为显式切换的 MOCK 演示数据源（非实时后端返回）',
        error_code: 'MOCK_MODE',
        endpoint: endpoint || 'mock://demo',
        field_sources: fieldSources || {},
        derivations: {}
      };
    },
    unavailable(endpoint, reason, partialData) {
      return {
        data: partialData !== undefined ? partialData : null,
        source: 'unavailable',
        fetched_at: nowFetchedAt(),
        updated_at: null,
        status: 'unavailable',
        error: reason || '原版后端尚未实现此接口或当前无活跃数据流',
        error_code: 'UNAVAILABLE',
        endpoint: endpoint || 'unavailable',
        field_sources: {},
        derivations: {}
      };
    },
    error(endpoint, errorMsg, code, httpStatus) {
      return {
        data: null,
        source: 'unavailable',
        fetched_at: nowFetchedAt(),
        updated_at: null,
        status: 'error',
        error: errorMsg || '接口请求失败',
        error_code: code || 'REQUEST_FAILED',
        http_status: httpStatus || 0,
        endpoint: endpoint || '/api/state',
        field_sources: {},
        derivations: {}
      };
    },
    loading(endpoint) {
      return {
        data: null,
        source: 'unavailable',
        fetched_at: nowFetchedAt(),
        updated_at: null,
        status: 'loading',
        error: null,
        error_code: null,
        endpoint: endpoint || '/api/state',
        field_sources: {},
        derivations: {}
      };
    }
  };

  function deriveAffectColorPalette(valence, arousal, known) {
    const formula = 'piecewise_quadrant_interpolation(valence in [-1,1], arousal in [0,1]); neutral_gray_when_null';
    const derivedFrom = ['affect_2d.fast_emotion.valence', 'affect_2d.fast_emotion.arousal'];
    if (!known || valence === null || valence === undefined || arousal === null || arousal === undefined) {
      return {
        known: false,
        valence: null,
        arousal: null,
        primary: '#9BA396',
        secondary: '#CED3C8',
        glow: 'rgba(155, 163, 150, 0.30)',
        quadrant_label: '未知 · 尚无情绪观测证据',
        rule: '真实后端返回 valence=null, arousal=null（known=false），严格保持中性灰阶云团，不伪造默认情绪色相。',
        derived_from: derivedFrom,
        formula
      };
    }
    const v = Math.max(-1, Math.min(1, Number(valence)));
    const a = Math.max(0, Math.min(1, Number(arousal)));
    if (v >= 0 && a < 0.58) {
      return {
        known: true,
        valence: v,
        arousal: a,
        primary: '#89A66F',
        secondary: '#DFC584',
        glow: 'rgba(137, 166, 111, 0.42)',
        quadrant_label: '正向舒缓 · 专注安定象限',
        rule: `由真实后端 Valence (${v >= 0 ? '+' : ''}${v.toFixed(3)}) × Arousal (${a.toFixed(3)}) 派生：落入正向中低唤醒象限（鼠尾草青 #89A66F + 暖阳琥珀 #DFC584）。`,
        derived_from: derivedFrom,
        formula
      };
    }
    if (v >= 0 && a >= 0.58) {
      return {
        known: true,
        valence: v,
        arousal: a,
        primary: '#D99B52',
        secondary: '#9AB87A',
        glow: 'rgba(217, 155, 82, 0.44)',
        quadrant_label: '正向高唤醒 · 活跃期待象限',
        rule: `由真实后端 Valence (+${v.toFixed(3)}) × Arousal (${a.toFixed(3)}) 派生：落入正向高唤醒象限（暖金橘 #D99B52 + 新叶绿 #9AB87A）。`,
        derived_from: derivedFrom,
        formula
      };
    }
    if (v < 0 && a < 0.50) {
      return {
        known: true,
        valence: v,
        arousal: a,
        primary: '#7A96AA',
        secondary: '#B8C6CE',
        glow: 'rgba(122, 150, 170, 0.38)',
        quadrant_label: '内省沉思 · 低唤醒象限',
        rule: `由真实后端 Valence (${v.toFixed(3)}) × Arousal (${a.toFixed(3)}) 派生：落入负向低唤醒内省象限（雨雾蓝 #7A96AA + 浅苔灰 #B8C6CE）。`,
        derived_from: derivedFrom,
        formula
      };
    }
    return {
      known: true,
      valence: v,
      arousal: a,
      primary: '#C97A63',
      secondary: '#E0AE88',
      glow: 'rgba(201, 122, 99, 0.42)',
      quadrant_label: '警觉张力 · 高唤醒象限',
      rule: `由真实后端 Valence (${v.toFixed(3)}) × Arousal (${a.toFixed(3)}) 派生：落入负向高唤醒警觉象限（暖赭红 #C97A63 + 琥珀 #E0AE88）。`,
      derived_from: derivedFrom,
      formula
    };
  }

  global.DataEnvelopeFactory = DataEnvelopeFactory;
  global.deriveAffectColorPalette = deriveAffectColorPalette;
  global.formatBusinessTimestamp = formatBusinessTimestamp;
  global.formatLocalDisplayTime = formatLocalDisplayTime;
  global.nowFetchedAt = nowFetchedAt;
  global.formatIsoNow = formatBusinessTimestamp;
  global.escapeHtml = escapeHtml;
  global.clampNumber = clampNumber;
})(typeof window !== 'undefined' ? window : globalThis);
