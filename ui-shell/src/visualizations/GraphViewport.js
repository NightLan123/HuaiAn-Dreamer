/* Reusable SVG viewport: display transforms only, no inferred data or edges. */
(function (global) {
  'use strict';
  class GraphViewport {
    constructor() { this.view = { x: 0, y: 0, k: 1 }; this.svg = null; this.abort = null; this.suppressUntil = 0; }
    attach(svg) {
      if (this.svg === svg) return;
      this.detach(); if (!svg) return;
      this.svg = svg; this.abort = new AbortController(); const signal = this.abort.signal;
      const point = e => new DOMPoint(e.clientX, e.clientY).matrixTransform(svg.getScreenCTM().inverse());
      let drag;
      svg.addEventListener('pointerdown', e => { if (e.button !== 0 || e.target.closest('[data-psych-detail]')) return; const p = point(e); drag = { x: p.x, y: p.y, ox: this.view.x, oy: this.view.y, id: e.pointerId }; svg.setPointerCapture(e.pointerId); }, { signal });
      svg.addEventListener('pointermove', e => { if (!drag || drag.id !== e.pointerId) return; const p = point(e), x = p.x - drag.x, y = p.y - drag.y; drag.moved ||= Math.abs(x) + Math.abs(y) > 5; this.view.x = drag.ox + x; this.view.y = drag.oy + y; this.apply(); }, { signal });
      const finish = () => { if (drag?.moved) this.suppressUntil = Date.now() + 250; drag = null; };
      for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) svg.addEventListener(type, finish, { signal });
      svg.addEventListener('wheel', e => { e.preventDefault(); const p = point(e); this.zoom(e.deltaY < 0 ? 1.12 : 1 / 1.12, p.x, p.y); }, { signal, passive: false });
      svg.addEventListener('keydown', e => { if (e.target !== svg) return; if (['+', '='].includes(e.key)) this.zoom(1.2); else if (e.key === '-') this.zoom(1 / 1.2); else if (e.key === 'Home') this.reset(); else if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) { this.view.x += e.key === 'ArrowLeft' ? 30 : e.key === 'ArrowRight' ? -30 : 0; this.view.y += e.key === 'ArrowUp' ? 30 : e.key === 'ArrowDown' ? -30 : 0; this.apply(); } else return; e.preventDefault(); }, { signal });
      this.apply();
    }
    apply() { this.svg?.querySelector('[data-graph-world]')?.setAttribute('transform', `translate(${this.view.x} ${this.view.y}) scale(${this.view.k})`); }
    zoom(f, x = 450, y = 270) { const k = Math.min(4, Math.max(.15, this.view.k * f)), r = k / this.view.k; this.view = { k, x: x - (x - this.view.x) * r, y: y - (y - this.view.y) * r }; this.apply(); }
    reset() { this.view = { x: 0, y: 0, k: 1 }; this.apply(); }
    fit(points) { if (!points.length) return this.reset(); const xs = points.map(p => p.x), ys = points.map(p => p.y), l = Math.min(...xs) - 75, r = Math.max(...xs) + 75, t = Math.min(...ys) - 55, b = Math.max(...ys) + 55, k = Math.min(2, 900 / (r - l), 540 / (b - t)); this.view = { k, x: 450 - (l + r) / 2 * k, y: 270 - (t + b) / 2 * k }; this.apply(); }
    detach() { this.abort?.abort(); this.abort = null; this.svg = null; }
  }
  global.GraphViewport = GraphViewport;
})(window);
