// Offline transport checks; no browser, network, model or user storage.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const c = { console, performance, AbortController, Response, setTimeout, clearTimeout, MockAdapter: class {} };
c.window = c;
vm.createContext(c);
for (const file of ['contracts/DataEnvelope.js', 'adapters/ModelAdapter.js', 'adapters/ConnectionAdapter.js', 'adapters/PMMAdapter.js', 'visualizations/PersonaManager.js']) {
  vm.runInContext(fs.readFileSync(path.join(root, 'ui-shell/src', file), 'utf8'), c, { filename: file });
}
(async () => {
  const a = new c.PMMAdapter();
  c.fetch = async () => new Response('', { status: 200 });
  let r = await a.bootstrap();
  assert.equal(r.error_code, 'INVALID_RESPONSE'); assert.equal(r.http_status, 200);
  c.fetch = async () => new Response('<html>expired</html>', { status: 401 });
  r = await a.fetchJson('/api/state'); assert.equal(r.error_code, 'HTTP_401');
  c.fetch = async () => { throw new TypeError('unreachable'); };
  assert.equal((await a.bootstrap()).error_code, 'NETWORK_ERROR');
  c.fetch = async (_, { signal }) => ({ ok: true, status: 200, headers: new Headers(),
    json: () => new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted')))) });
  assert.equal((await a.fetchJson('/api/state', 15)).error_code, 'TIMEOUT');
  let requests = [];
  c.fetch = async (url, options) => { requests.push(options.method); return new Response('{}'); };
  a.bootstrapped = false;
  assert.equal((await a.postJson('/api/persona/new', { name: 'synthetic' })).error_code, 'INVALID_RESPONSE');
  assert.deepEqual(requests, ['GET']); // no mutation after a failed handshake
  let active = 0, peak = 0;
  a.bootstrap = async () => c.DataEnvelopeFactory.live({ csrf: 'synthetic' }, '/api/bootstrap');
  a.fetchJson = async ep => {
    if (ep === '/api/health') return c.DataEnvelopeFactory.live({ ok: true }, ep);
    peak = Math.max(peak, ++active);
    await new Promise(resolve => setTimeout(resolve, 1)); active--;
    return c.DataEnvelopeFactory.error(ep, 'synthetic timeout', 'TIMEOUT', 0);
  };
  r = await a.fetchAllLiveContracts();
  assert.equal(r.error_endpoints_count, 17); assert.equal(r.backend_reachable, true); assert.equal(peak, 4);
  a.bootstrap = async () => c.DataEnvelopeFactory.error('/api/bootstrap', 'synthetic', 'TIMEOUT', 0);
  r = await a.fetchAllLiveContracts();
  assert.equal(r.envelopes, null); assert.equal(r.backend_reachable, true);
  const html = c.PersonaManager.render({ characterProfile: { data: { id: 'a', name: '<script>', personas_catalog: [{ id: 'a', name: '<script>' }, { id: 'b', name: 'B' }], personas_trash: [{ id: 'c', name: 'C' }] } } });
  assert(!html.includes('<script>')); assert(html.includes('data-persona-restore="c"'));
  assert(html.includes('data-persona-archive="a" disabled')); assert(html.includes('managerPersonaFile'));
  const page = fs.readFileSync(path.join(root, 'ui-shell/index.html'), 'utf8');
  assert(page.indexOf('PersonaManager.js') < page.indexOf('phase20Controller.js'));
  console.log('PASS: response classification, body deadline, handshake write guard, bounded reads, role manager rendering and script wiring');
})().catch(err => { console.error(err); process.exitCode = 1; });
