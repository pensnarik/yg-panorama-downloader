const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const metadata = require('../pano-monitoring-yandex/metadata.js');
const raw = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/yandex-panorama.json')));
const tick = () => new Promise(resolve => setImmediate(resolve));

function harness(initial = {}, fetchImpl) {
  const store = structuredClone(initial);
  const listeners = [];
  const alarmListeners = [];
  const filters = [];
  const posts = [];
  const context = vm.createContext({
    PanoramaMetadata: metadata, TextDecoder, AbortController, setTimeout, clearTimeout,
    console: { log() {}, warn() {}, error() {} },
    fetch: async (url, options) => {
      const capture = JSON.parse(options.body);
      posts.push(capture);
      if (fetchImpl) return fetchImpl(capture);
      return { ok: true, json: async () => ({ status: 'ok', imageId: capture.imageId }) };
    },
    browser: {
      storage: { local: {
        get: async key => structuredClone(key === null ? store : { [key]: store[key] }),
        set: async values => Object.assign(store, structuredClone(values)),
        remove: async key => { delete store[key]; }
      } },
      alarms: { create() {}, onAlarm: { addListener: fn => alarmListeners.push(fn) } },
      webRequest: {
        onBeforeRequest: { addListener: (fn, spec) => listeners.push({ fn, spec }) },
        filterResponseData: () => {
          const filter = { chunks: [], closed: false, disconnected: false,
            write(data) { this.chunks.push(Buffer.from(data)); },
            close() { this.closed = true; }, disconnect() { this.disconnected = true; }
          };
          filters.push(filter);
          return filter;
        }
      }
    }
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../pano-monitoring-yandex/background.js'), 'utf8'), context);
  function deliver(body) {
    listeners[0].fn({ tabId: 1, requestId: String(filters.length),
      url: 'https://api-maps.yandex.ru/services/panoramas/1.x/?l=stv' });
    const filter = filters.at(-1);
    const bytes = Buffer.from(body);
    // Deliberately split multi-byte Cyrillic sequences.
    for (let i = 0; i < bytes.length; i += 37) {
      filter.ondata({ data: Uint8Array.from(bytes.subarray(i, i + 37)).buffer });
    }
    filter.onstop();
    assert.equal(Buffer.concat(filter.chunks).toString(), body);
    assert.equal(filter.closed, true);
  }
  return { store, posts, deliver,
    enqueue: vm.runInContext('enqueueMetadata', context),
    retry: () => alarmListeners[0]({ name: 'retry-panorama-metadata' }) };
}

test('JSON and JSONP retain all fields without executing scripts', () => {
  assert.deepEqual(metadata.parseResponse('\uFEFF' + JSON.stringify(raw)), raw);
  assert.deepEqual(metadata.parseResponse('callback(' + JSON.stringify(raw) + ');'), raw);
  assert.throws(() => metadata.parseResponse('callback({}); alert(1)'));
  assert.throws(() => metadata.makeCapture({ status: 'error' }, '', ''));
});

test('stream forwards bytes unchanged and posts real metadata', async () => {
  const h = harness();
  await tick();
  h.deliver(JSON.stringify(raw));
  await tick();
  assert.equal(h.posts.length, 1);
  assert.deepEqual(h.posts[0].rawResponse, raw);
  assert.deepEqual(h.store, {});
});

test('server outage persists across background restart', async () => {
  const h = harness({}, async () => { throw new Error('offline'); });
  await tick();
  h.deliver(JSON.stringify(raw));
  await tick();
  assert.equal(Object.keys(h.store).length, 1);
  const restarted = harness(h.store);
  await tick();
  assert.deepEqual(restarted.store, {});
  assert.equal(restarted.posts[0].imageId, 'Z7lngTdIrFox');
});

test('new response arriving during POST is not deleted by old acknowledgement', async () => {
  let acknowledge;
  const h = harness({}, capture => new Promise(resolve => {
    acknowledge = () => resolve({ ok: true, json: async () => ({ status: 'ok', imageId: capture.imageId }) });
  }));
  await tick();
  h.deliver(JSON.stringify(raw));
  await tick();
  const newer = structuredClone(raw);
  newer.extraField = 'new response';
  h.deliver(JSON.stringify(newer));
  await tick();
  acknowledge();
  await tick();
  assert.equal(h.store['panorama-metadata:Z7lngTdIrFox'].rawResponse.extraField, 'new response');
  h.retry();
  await tick();
  acknowledge();
  await tick();
  assert.deepEqual(h.store, {});
});

test('invalid response still reaches the page without creating metadata', async () => {
  const h = harness();
  await tick();
  h.deliver('<html>Service unavailable</html>');
  await tick();
  assert.equal(h.posts.length, 0);
  assert.deepEqual(h.store, {});
});

test('late older response cannot replace newer queued metadata', async () => {
  const h = harness({}, async () => { throw new Error('offline'); });
  await tick();
  const newer = metadata.makeCapture(raw, 'https://api-maps.yandex.ru/services/panoramas/1.x/', '2026-09-23T18:00:01Z');
  const older = { ...newer, capturedAt: '2026-09-23T18:00:00Z' };
  await h.enqueue(newer);
  await h.enqueue(older);
  assert.equal(h.store['panorama-metadata:Z7lngTdIrFox'].capturedAt, newer.capturedAt);
});

test('HTTP success without matching acknowledgement retains queued data', async () => {
  const h = harness({}, async () => ({ ok: true, json: async () => ({ status: 'ok', imageId: 'wrong' }) }));
  await tick();
  h.deliver(JSON.stringify(raw));
  await tick();
  assert.equal(Object.keys(h.store).length, 1);
});
