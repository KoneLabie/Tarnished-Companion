'use strict';

// Public full-run leaderboards. This source does not supply boss fight times.
const https = require('node:https');
const fs = require('node:fs');
const path = require('node:path');
const { parseJson, object } = require('./strict-json');
const MAPPING = require('../resources/published-records.json');
const CATEGORIES = MAPPING.categories;
const REFRESH_SECONDS = 900, RETRY_SECONDS = 60;
const MAX_BYTES = 1024 * 1024, MAX_CACHE_BYTES = 5 * MAX_BYTES, MAX_SECONDS = 5;
const BASE_NOTICE = 'PC Glitchless results combine accepted versions, routes and FPS patch settings. '
  + 'These are complete-run times; this source does not publish boss fight times. '
  + 'The averages describe the returned sample, not every runner.';
const clean = value => typeof value === 'string'
  ? value.replace(/[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u206f]/g, ' ').slice(0, 120)
  : 'Unknown runner';
const positive = value => typeof value === 'number' && Number.isFinite(value) && value > 0 && value < 1e9;
const iso = seconds => new Date(seconds * 1000).toISOString();
function stamp(value) {
  if (typeof value !== 'string' || value.length > 40 || !/(?:Z|[+-]\d\d:\d\d)$/.test(value)) throw new Error('Invalid cache timestamp');
  const result = Date.parse(value) / 1000;
  if (!Number.isFinite(result)) throw new Error('Invalid cache timestamp');
  return result;
}
function sourceUrl(categoryId) {
  const c = CATEGORIES[categoryId];
  return `https://www.speedrun.com/eldenring?x=${c.categoryId}-${c.variableId}.${c.valueId}`;
}
function apiUrl(categoryId) {
  const c = CATEGORIES[categoryId];
  const query = new URLSearchParams({ platform: MAPPING.platformId, timing: MAPPING.apiTiming,
    [`var-${c.variableId}`]: c.valueId, top: '20', embed: 'players' });
  return `https://www.speedrun.com/api/v1/leaderboards/${MAPPING.gameId}/category/${c.categoryId}?${query}`;
}
function officialUrl(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || !['www.speedrun.com', 'speedrun.com'].includes(url.hostname)
      || (url.port && url.port !== '443') || url.username || url.password || !url.pathname.startsWith('/api/v1/')) {
    throw new Error('Unexpected record source');
  }
  return url;
}
function fetchJson(initialUrl) {
  // The single wall-clock deadline also covers DNS, response streaming and redirects.
  return new Promise((resolve, reject) => {
    let active = null, settled = false;
    const finish = (error, value) => {
      if (settled) return;
      settled = true; clearTimeout(timer);
      if (error) { active?.destroy(); reject(error); } else resolve(value);
    };
    const timer = setTimeout(() => finish(new Error('Record source timed out')), MAX_SECONDS * 1000);
    function visit(value, redirects) {
      let url;
      try { url = officialUrl(value); } catch (error) { finish(error); return; }
      active = https.get(url, { headers: { 'User-Agent': 'TarnishedCompanion/1.0', Accept: 'application/json', 'Accept-Encoding': 'identity' } }, response => {
        if (settled) { response.destroy(); return; }
        if ([301, 302, 303, 307, 308].includes(response.statusCode)) {
          response.destroy();
          try {
            if (redirects >= 2 || !response.headers.location) throw new Error('Invalid record-source redirect');
            visit(officialUrl(new URL(response.headers.location, url)).href, redirects + 1);
          } catch (error) { finish(error); }
          return;
        }
        const declared = response.headers['content-length'];
        if (response.statusCode !== 200
            || String(response.headers['content-type'] || '').split(';')[0].trim().toLowerCase() !== 'application/json'
            || (declared !== undefined && (!/^\d+$/.test(declared) || Number(declared) > MAX_BYTES))) {
          response.destroy(); finish(new Error('Record source did not return bounded JSON')); return;
        }
        let size = 0; const chunks = [];
        response.on('data', chunk => {
          size += chunk.length;
          if (size > MAX_BYTES) { response.destroy(); finish(new Error('Record response is too large')); }
          else chunks.push(chunk);
        });
        response.on('error', error => finish(error));
        response.on('end', () => {
          try { finish(null, parseJson(Buffer.concat(chunks), MAX_BYTES, 'Public leaderboard')); }
          catch (error) { finish(error); }
        });
      });
      active.on('error', error => finish(error));
    }
    visit(initialUrl, 0);
  });
}
function validateBoard(payload, categoryId) {
  const c = CATEGORIES[categoryId], data = payload?.data;
  if (!object(data) || data.game !== MAPPING.gameId || data.category !== c.categoryId
      || !Object.hasOwn(data, 'level') || data.level !== null || data.platform !== MAPPING.platformId
      || data.timing !== MAPPING.apiTiming || !object(data.values) || Object.keys(data.values).length !== 1
      || data.values[c.variableId] !== c.valueId || !Array.isArray(data.runs) || data.runs.length > 400) {
    throw new Error('Leaderboard filters do not match the selected category');
  }
  const players = object(data.players) ? data.players.data ?? [] : [];
  if (!Array.isArray(players) || players.length > 1000) throw new Error('Invalid leaderboard players');
  const names = new Map();
  for (const player of players) if (object(player) && typeof player.id === 'string') names.set(player.id, clean(player.names?.international));
  const seen = new Set(), runs = [];
  for (const entry of data.runs) {
    const run = object(entry) ? entry.run : null, rank = entry?.place;
    if (!object(run) || !Number.isInteger(rank) || rank < 1 || rank > 100000) throw new Error('Malformed leaderboard run');
    if (typeof run.id !== 'string' || !/^[a-z0-9]{8}$/.test(run.id) || seen.has(run.id)
        || run.game !== MAPPING.gameId || run.category !== c.categoryId || !Object.hasOwn(run, 'level') || run.level !== null
        || run.system?.platform !== MAPPING.platformId || run.status?.status !== 'verified'
        || run.values?.[c.variableId] !== c.valueId || !positive(run.times?.primary_t) || !positive(run.times?.realtime_t)
        || run.times.primary_t !== run.times.realtime_t) throw new Error('Run is not a matching published category result');
    seen.add(run.id);
    if (!Array.isArray(run.players) || !run.players.length || run.players.length > 20
        || run.players.some(player => !object(player) || !['user', 'guest'].includes(player.rel))) throw new Error('Run participants unavailable');
    const runner = run.players.map(player => player.rel === 'user' ? names.get(player.id) || 'Unknown runner' : clean(player.name)).join(', ').slice(0, 240);
    const date = run.date ?? null;
    if (date !== null && (typeof date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(date)
        || !Number.isFinite(Date.parse(`${date}T00:00:00Z`)) || new Date(`${date}T00:00:00Z`).toISOString().slice(0, 10) !== date)) throw new Error('Malformed run date');
    runs.push({ id: run.id, rank, runner, seconds: run.times.primary_t, date, url: `https://www.speedrun.com/eldenring/runs/${run.id}` });
  }
  runs.sort((a, b) => a.rank - b.rank || a.seconds - b.seconds || a.id.localeCompare(b.id));
  if (runs.some((run, i) => i > 0 && runs[i - 1].seconds > run.seconds)) throw new Error('Leaderboard ordering is inconsistent');
  return runs.slice(0, 20);
}
class PublishedRecords {
  constructor(dataDir, { fetcher = fetchJson, clock = () => Date.now() / 1000 } = {}) {
    this.path = path.join(dataDir, 'published-records-cache.json');
    this.fetcher = fetcher; this.clock = clock; this.entries = new Map(); this.pending = new Set();
    this.load();
  }
  load() {
    try {
      if (fs.statSync(this.path).size > MAX_CACHE_BYTES) return;
      const cache = parseJson(fs.readFileSync(this.path), MAX_CACHE_BYTES, 'Public record cache', { maxNodes: 800000 });
      if (!object(cache) || cache.schemaVersion !== 1 || !object(cache.entries)) return;
      const now = this.clock();
      for (const [key, entry] of Object.entries(cache.entries)) {
        try {
          if (!Object.hasOwn(CATEGORIES, key) || !object(entry)) continue;
          const checked = stamp(entry.checkedAt);
          if (checked < 0 || checked > now + 30) continue;
          const runs = validateBoard(entry.payload, key);
          let attempted = stamp(entry.lastAttemptAt ?? entry.checkedAt);
          if (attempted < 0 || attempted > now + 30) attempted = checked;
          this.entries.set(key, { payload: entry.payload, runs, checked, attempted, failed: entry.failed === true });
        } catch { /* A malformed entry must never replace a validated result. */ }
      }
    } catch { /* Cache is optional; first refresh will populate it. */ }
  }
  save() {
    try {
      const entries = Object.fromEntries([...this.entries].filter(([, e]) => e.payload !== undefined).map(([key, e]) => [key,
        { payload: e.payload, checkedAt: iso(e.checked), lastAttemptAt: iso(e.attempted), failed: e.failed }]));
      const bytes = Buffer.from(JSON.stringify({ schemaVersion: 1, entries }));
      if (bytes.length > MAX_CACHE_BYTES) return;
      fs.mkdirSync(path.dirname(this.path), { recursive: true });
      fs.writeFileSync(`${this.path}.tmp`, bytes); fs.renameSync(`${this.path}.tmp`, this.path);
    } catch { /* Public data can always be fetched again. */ }
  }
  snapshot(categoryId) {
    const c = Object.hasOwn(CATEGORIES, categoryId) ? CATEGORIES[categoryId] : null;
    const output = { schemaVersion: 1, source: 'speedrun.com', status: 'unsupported', categoryId,
      categoryName: c ? c.name : 'Custom or unselected category', scope: MAPPING.scope, timing: MAPPING.timing,
      timingKey: 'pc-soulsplitter-game-time', checkedAt: null, lastAttemptAt: null, nextRefreshAt: null,
      sourceUrl: c ? sourceUrl(categoryId) : 'https://www.speedrun.com/eldenring',
      bestSeconds: null, nearBestSeconds: null, averageSeconds: null, sampleCount: 0, runs: [],
      notice: 'No published-record mapping is available for this category.', bossTimesAvailable: false };
    if (!c) return output;
    const entry = this.entries.get(categoryId) || {}, now = this.clock(), { checked, attempted } = entry;
    const runs = entry.runs || [];
    const fresh = checked !== undefined && now - checked >= 0 && now - checked < REFRESH_SECONDS && !entry.failed;
    Object.assign(output, { status: fresh ? 'fresh' : checked !== undefined ? 'stale' : 'unavailable',
      checkedAt: checked === undefined ? null : iso(checked), lastAttemptAt: attempted === undefined ? null : iso(attempted),
      nextRefreshAt: iso(Math.max(fresh ? checked + REFRESH_SECONDS : now, attempted === undefined ? now : attempted + RETRY_SECONDS)),
      runs: structuredClone(runs), sampleCount: runs.length });
    if (runs.length) {
      const times = runs.map(run => run.seconds).sort((a, b) => a - b), count = Math.min(times.length, Math.max(2, Math.ceil(times.length / 4)));
      Object.assign(output, { bestSeconds: times[0], nearBestSeconds: times.slice(0, count).reduce((a, b) => a + b, 0) / count,
        averageSeconds: times.reduce((a, b) => a + b, 0) / times.length });
    }
    let prefix = runs.length ? `${runs.length} published results (up to 20). ` : 'No matching published results. ';
    if (output.status === 'stale') prefix = 'Cached records: the latest refresh is overdue or failed. ' + prefix;
    else if (output.status === 'unavailable') prefix = 'Published records are currently unavailable. ';
    output.notice = prefix + BASE_NOTICE;
    return output;
  }
  async refresh(categoryId, { force = false } = {}) {
    if (!Object.hasOwn(CATEGORIES, categoryId) || this.pending.has(categoryId)) return this.snapshot(categoryId);
    const now = this.clock(), entry = this.entries.get(categoryId) || {};
    if ((entry.attempted !== undefined && now - entry.attempted >= 0 && now - entry.attempted < RETRY_SECONDS)
        || (!force && this.snapshot(categoryId).status === 'fresh')) return this.snapshot(categoryId);
    this.pending.add(categoryId); entry.attempted = now; this.entries.set(categoryId, entry);
    try {
      const payload = await this.fetcher(apiUrl(categoryId)), runs = validateBoard(payload, categoryId);
      this.entries.set(categoryId, { payload: structuredClone(payload), runs, checked: this.clock(), attempted: now, failed: false });
    } catch { this.entries.get(categoryId).failed = true; }
    finally { this.pending.delete(categoryId); this.save(); }
    return this.snapshot(categoryId);
  }
}
module.exports = { PublishedRecords, CATEGORIES, REFRESH_SECONDS, RETRY_SECONDS, fetchJson, validateBoard, apiUrl, sourceUrl, officialUrl };
