'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { PublishedRecords, CATEGORIES, validateBoard, apiUrl, officialUrl, fetchJson } = require('../lib/published-records');
const MAPPING = require('../resources/published-records.json');
const CATEGORY = 'any-percent-glitchless';
function fixture(times = [100, 110, 120, 130]) {
  const c = CATEGORIES[CATEGORY], values = { [c.variableId]: c.valueId };
  return { data: { game: MAPPING.gameId, category: c.categoryId, level: null, platform: MAPPING.platformId,
    timing: 'realtime', values, players: { data: [{ id: 'abcdefgh', names: { international: 'Runner' } }] },
    runs: times.map((seconds, i) => ({ place: i + 1, run: { id: String(i).padStart(8, '0'), game: MAPPING.gameId,
      category: c.categoryId, level: null, system: { platform: MAPPING.platformId }, status: { status: 'verified' },
      values: { ...values }, players: [{ rel: 'user', id: 'abcdefgh' }], date: '2026-10-01',
      times: { primary_t: seconds, realtime_t: seconds, ingame_t: 0 }, weblink: 'https://untrusted.invalid/' } })) } };
}
function setup(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'tarnished-public-records-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const state = { now: 1800000000, payload: fixture(), calls: 0, directory };
  state.options = { clock: () => state.now, fetcher: async url => {
    state.calls++; assert.equal(url, apiUrl(CATEGORY));
    if (state.payload instanceof Error) throw state.payload;
    return structuredClone(state.payload);
  } };
  state.client = new PublishedRecords(directory, state.options);
  return state;
}
test('new records replace cache and sample means do not claim entire community', async t => {
  const s = setup(t), first = await s.client.refresh(CATEGORY);
  assert.equal(first.status, 'fresh'); assert.equal(first.bestSeconds, 100);
  assert.equal(first.nearBestSeconds, 105); assert.equal(first.averageSeconds, 115);
  assert.equal(first.timingKey, 'pc-soulsplitter-game-time'); assert.equal(first.bossTimesAvailable, false);
  assert.match(first.runs[0].url, /^https:\/\/www.speedrun.com\/eldenring\/runs\//);
  s.now += 901; s.payload = fixture([90, 100, 110]);
  const second = await s.client.refresh(CATEGORY);
  assert.equal(second.bestSeconds, 90); assert.notEqual(second.checkedAt, first.checkedAt);
  const restored = new PublishedRecords(s.directory, s.options);
  assert.equal(restored.snapshot(CATEGORY).bestSeconds, 90); assert.equal(s.calls, 2);
});
test('restart expires cache and failure preserves last success with minimum retry interval', async t => {
  const s = setup(t), first = await s.client.refresh(CATEGORY);
  s.now += 901;
  const restored = new PublishedRecords(s.directory, s.options);
  assert.equal(restored.snapshot(CATEGORY).status, 'stale');
  s.payload = new Error('offline');
  const result = await restored.refresh(CATEGORY);
  assert.equal(result.status, 'stale'); assert.equal(result.checkedAt, first.checkedAt); assert.equal(result.bestSeconds, 100);
  assert.notEqual(result.lastAttemptAt, result.checkedAt);
  await restored.refresh(CATEGORY, { force: true }); assert.equal(s.calls, 2);
  s.now += 60; await restored.refresh(CATEGORY, { force: true }); assert.equal(s.calls, 3);
});
test('explicit refresh is still limited to once per minute', async t => {
  const s = setup(t); await s.client.refresh(CATEGORY); s.now += 59;
  await s.client.refresh(CATEGORY, { force: true }); assert.equal(s.calls, 1);
  s.now++; await s.client.refresh(CATEGORY, { force: true }); assert.equal(s.calls, 2);
});
test('valid empty leaderboard clears previous benchmarks', async t => {
  const s = setup(t); await s.client.refresh(CATEGORY); s.now += 901; s.payload = fixture([]);
  const result = await s.client.refresh(CATEGORY);
  assert.equal(result.status, 'fresh'); assert.equal(result.sampleCount, 0); assert.equal(result.bestSeconds, null);
});
test('unsupported category does not fetch', async t => {
  const s = setup(t); assert.equal((await s.client.refresh('custom')).status, 'unsupported'); assert.equal(s.calls, 0);
});
test('mismatched filters and invalid run samples are rejected', () => {
  for (const change of [d => d.platform = 'console', d => d.timing = 'ingame', d => d.values = {}, d => d.level = 'abcdefgh',
    d => d.runs[0].run.status.status = 'new', d => d.runs[0].run.values = {}, d => d.runs[0].run.times.primary_t = 0,
    d => d.runs[0].run.times.primary_t = NaN, d => d.runs[0].run.times.primary_t = true,
    d => d.runs[0].run.times.realtime_t = 101, d => d.runs[0].run.players = [null]]) {
    const bad = fixture(); change(bad.data); assert.throws(() => validateBoard(bad, CATEGORY));
  }
});
test('malformed response cannot replace valid cache', async t => {
  const s = setup(t), first = await s.client.refresh(CATEGORY);
  for (const malformed of ['<html>Unavailable</html>', {}, { data: null }]) {
    s.now += 901; s.payload = malformed;
    const result = await s.client.refresh(CATEGORY);
    assert.equal(result.status, 'stale'); assert.equal(result.checkedAt, first.checkedAt); assert.equal(result.bestSeconds, 100);
  }
});
test('snapshot remains immediate during pending fetch and cannot mutate internal records', async t => {
  const s = setup(t); await s.client.refresh(CATEGORY); s.now += 901;
  let release; s.client.fetcher = () => new Promise(resolve => release = resolve);
  const pending = s.client.refresh(CATEGORY), snapshot = s.client.snapshot(CATEGORY);
  assert.equal(snapshot.bestSeconds, 100); snapshot.runs[0].seconds = 1;
  assert.equal(s.client.snapshot(CATEGORY).bestSeconds, 100);
  release(fixture([90])); await pending; assert.equal(s.client.snapshot(CATEGORY).bestSeconds, 90);
});
test('only official HTTPS API URLs are accepted, including redirect targets', async () => {
  for (const url of ['http://www.speedrun.com/api/v1/x', 'https://evil.invalid/api/v1/x',
    'https://www.speedrun.com:444/api/v1/x', 'https://user@www.speedrun.com/api/v1/x', 'https://www.speedrun.com/login']) {
    assert.throws(() => officialUrl(url)); await assert.rejects(fetchJson(url));
  }
});
test('HTTP reads reject HTML, oversized bodies and external redirects', async () => {
  const https = require('node:https'), { EventEmitter } = require('node:events'), { Readable } = require('node:stream');
  const original = https.get;
  try {
    for (const [status, headers, body] of [
      [200, { 'content-type': 'text/html' }, '<html>'],
      [200, { 'content-type': 'application/json', 'content-length': '1048577' }, '{}'],
      [200, { 'content-type': 'application/json' }, Buffer.alloc(1048577, 32)],
      [302, { location: 'https://evil.invalid/api/v1/data' }, '']]) {
      https.get = (url, options, callback) => {
        const request = new EventEmitter(); request.destroy = () => {};
        const response = Readable.from([Buffer.from(body)]); response.statusCode = status; response.headers = headers;
        setImmediate(() => callback(response)); return request;
      };
      await assert.rejects(fetchJson(apiUrl(CATEGORY)));
    }
  } finally { https.get = original; }
});
