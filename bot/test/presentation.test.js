'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const { fixture, validPayload } = require('./helpers');
const { decryptPackage } = require('../lib/package');
const { normalizeReport } = require('../lib/report');
const { ReportMenus, renderReport, bossRows, safeSource, delta, SECTIONS } = require('../lib/presentation');
const USER = '123456789012345678', GUILD = '234567890123456789', MESSAGE = '345678901234567890';
function report() { const f = fixture(); return normalizeReport(decryptPackage(f.bytes, f.rawPrivate, f.fingerprint)); }
function comparison() {
  return { published: { status: 'fresh', categoryId: 'any-glitchless', categoryName: 'Any% Glitchless', timingKey: 'pc-soulsplitter-game-time', timing: 'Published PC category time',
    checkedAt: new Date().toISOString(), scope: 'PC category; all accepted versions/routes/FPS', sourceUrl: 'https://www.speedrun.com/eldenring', bestSeconds: 1000,
    notice: 'Latest accepted leaderboard records.', bossTimesAvailable: false,
    runs: Array.from({ length: 20 }, (_, i) => ({ rank: i + 1, runner: `Runner ${i + 1}`, seconds: 1000 + i * 10, url: `https://www.speedrun.com/eldenring/runs/abc${i}` })) },
    peers: { status: 'available', sampleCount: 3, runBestSeconds: 1100, runAverageSeconds: 1200,
      bosses: [{ bossId: 10000800, sampleCount: 3, bestFightSeconds: 170, averageFightSeconds: 190 }], notice: 'Unreviewed submitted reports; same category and journey; route/build may differ' } };
}
function total(embed) { return (embed.title?.length || 0) + (embed.description?.length || 0) + (embed.author?.name?.length || 0) + (embed.footer?.text?.length || 0) + (embed.fields || []).reduce((n, f) => n + f.name.length + f.value.length, 0); }
function checkBounds(message) {
  assert.ok(total(message.embeds[0]) <= 6000); assert.ok(message.embeds[0].fields.length <= 25);
  for (const f of message.embeds[0].fields) { assert.ok(f.name.length <= 256); assert.ok(f.value.length >= 1 && f.value.length <= 1024); }
  for (const row of message.components) for (const c of row.components) { assert.ok(c.custom_id.length <= 100); if (c.options) assert.ok(c.options.length <= 25); }
  assert.deepEqual(message.allowedMentions, { parse: [] });
}
function interaction(token, action, values = [], changes = {}) {
  const result = { replies: [], edits: [], deferred: 0, customId: `tlrun:${token}:${action}`, values,
    user: { id: USER }, guildId: GUILD, message: { id: MESSAGE },
    isButton: () => action !== 'section', isStringSelectMenu: () => action === 'section',
    async reply(value) { this.replies.push(value); }, async deferUpdate() { this.deferred++; }, async editReply(value) { this.edits.push(value); }, ...changes };
  return result;
}

test('organized report separates encounter durations, cumulative splits and submitted peer results', () => {
  const r = report(); r.comparison = comparison(); r.attempts[0].eligibleForBenchmark = true;
  const boss = renderReport(r, 'bosses'); checkBounds(boss);
  const text = JSON.stringify(boss.embeds);
  assert.match(text, /00:03:00.000/); assert.match(text, /00:15:00.000/); assert.match(text, /Submitted best/); assert.match(text, /00:02:50.000/);
  assert.match(text, /Submitted average/); assert.match(text, /00:03:10.000/); assert.match(text, /3 submitted reports/);
  assert.match(text, /00:00:10.000/);
  assert.equal(bossRows(r).length, 1);
  const overview = renderReport(r); assert.match(JSON.stringify(overview.embeds), /Review required/); assert.match(JSON.stringify(overview.embeds), /Fastest observed victory/);
  delete r.comparison.peers.bosses[0].averageFightSeconds;
  assert.doesNotMatch(JSON.stringify(renderReport(r, 'bosses').embeds[0].fields), /Submitted average/);
});

test('published record comparison uses exact category and timing, labels stale data, and paginates twenty runners', () => {
  const r = report(); r.comparison = comparison();
  const first = renderReport(r, 'comparison'); checkBounds(first);
  assert.match(JSON.stringify(first.embeds), /Overall run pace/); assert.match(JSON.stringify(first.embeds), /00:03:54.500/);
  const third = renderReport(r, 'comparison', 2); assert.match(third.embeds[0].footer.text, /Page 3\/3/); assert.match(JSON.stringify(third), /Runner 20/);
  assert.equal(third.components[1].components[1].disabled, true);
  r.comparison.published.status = 'stale'; assert.match(JSON.stringify(renderReport(r, 'comparison').embeds), /Cached records/);
  r.comparison.published.categoryId = 'all-remembrances'; assert.doesNotMatch(JSON.stringify(renderReport(r, 'comparison').embeds), /Overall run pace/);
  r.comparison.published.categoryId = r.category.id; r.comparison.published.timingKey = 'realtime'; assert.doesNotMatch(JSON.stringify(renderReport(r, 'comparison').embeds), /Overall run pace/);
  r.comparison.published.timingKey = 'pc-soulsplitter-game-time'; r.comparison.published.checkedAt = '2000-01-01T00:00:00Z'; assert.doesNotMatch(JSON.stringify(renderReport(r, 'comparison').embeds), /Overall run pace/);
  r.comparison.published.checkedAt = new Date().toISOString(); r.journey = 2; assert.doesNotMatch(JSON.stringify(renderReport(r, 'comparison').embeds), /Overall run pace/);
});

test('final published differences require completed normalized bounds and the exact observed timing source', () => {
  const r = report(); r.comparison = comparison();
  for (const change of [
    { timing: { ...r.timing, source: 'Saved character play time' } },
    { timing: { ...r.timing, elapsedSeconds: 0 } },
    { timing: { ...r.timing, elapsedSeconds: null } },
    { endedAt: null }, { startedAt: 'invalid' }, { endedAt: '2020-01-01T00:00:00Z' },
  ]) {
    const view = renderReport({ ...r, ...change }, 'comparison');
    assert.ok(!view.embeds[0].fields.some(field => field.name === 'Difference'));
    assert.ok(!view.embeds[0].fields.some(field => field.name === 'Overall run pace'));
  }
  for (const change of [{ status: 'running' }, { partial: true }, { continuityUnverified: true }]) {
    const payload = validPayload(); Object.assign(payload.run, change);
    const f = fixture(payload);
    assert.throws(() => normalizeReport(decryptPackage(f.bytes, f.rawPrivate, f.fingerprint)), /finished|Partial/);
  }
});

test('all sections stay within Discord limits even with large and adversarial names', () => {
  const r = report(), huge = '@everyone **[evil](https://example.com)** <@123456789012345678> '.repeat(20);
  r.character = huge; r.category.name = huge; r.comparison = comparison();
  r.comparison.published.notice = huge; r.comparison.published.scope = huge; r.comparison.peers.notice = huge;
  r.comparison.published.runs.forEach(run => { run.runner = huge; run.url = 'https://evil.example/run'; });
  r.splits = Array.from({ length: 208 }, (_, i) => ({ ...r.splits[0], bossId: i, name: huge }));
  r.attempts = Array.from({ length: 500 }, (_, i) => ({ ...r.attempts[0], bossId: i, name: huge, note: huge, recordId: String(i) }));
  r.build.final = { level: 700, class: huge, attributes: { vigor: 99 }, equipment: { weapons: [], armor: [], talismans: [] } };
  for (const kind of ['weapons', 'armor', 'talismans']) r.build.final.equipment[kind] = Array.from({ length: 6 }, () => ({ slot: huge, name: huge, affinity: huge, upgradeLevel: 25 }));
  for (const [section] of SECTIONS) for (let page = 0; page < 3; page++) {
    const view = renderReport(r, section, page); checkBounds(view); assert.doesNotMatch(JSON.stringify(view), /@everyone/); assert.doesNotMatch(JSON.stringify(view), /https:\/\/evil.example\/run/);
  }
  assert.equal(safeSource('https://speedrun.com.evil.example/run'), null); assert.equal(safeSource('https://speedrun.com@evil.example/run'), null); assert.equal(safeSource('http://speedrun.com/run'), null);
  assert.equal(delta(null, 1), 'Not comparable');
});

test('private menus reject other users, other guilds and other messages before editing', async () => {
  const menu = new ReportMenus(), created = menu.create(report(), USER, GUILD); menu.bind(created.token, MESSAGE);
  for (const change of [{ user: { id: '999999999999999999' } }, { guildId: '999999999999999999' }, { message: { id: '999999999999999999' } }]) {
    const call = interaction(created.token, 'section', ['bosses'], change);
    assert.equal(await menu.handle(call), true); assert.equal(call.deferred, 0); assert.equal(call.edits.length, 0); assert.equal(call.replies[0].flags, 64);
  }
  const valid = interaction(created.token, 'section', ['bosses']); await menu.handle(valid); assert.equal(valid.deferred, 1); assert.equal(valid.edits[0].embeds[0].title, 'Boss times');
});

test('menu pagination clamps stale clicks, invalid sections cannot mutate state, and receipts survive expiry', async () => {
  let now = 100; const menus = new ReportMenus({ now: () => now, ttlMs: 1000 });
  const r = report(); r.attempts = Array.from({ length: 10 }, (_, i) => ({ ...r.attempts[0], recordId: String(i) }));
  const created = menus.create(r, USER, GUILD); menus.bind(created.token, MESSAGE);
  const bad = interaction(created.token, 'section', ['bogus']); await menus.handle(bad); assert.equal(bad.deferred, 0);
  await menus.handle(interaction(created.token, 'section', ['attempts']));
  for (let i = 0; i < 6; i++) await menus.handle(interaction(created.token, 'next'));
  assert.equal(menus.sessions.get(created.token).page, 1);
  const back = interaction(created.token, 'previous'); await menus.handle(back); assert.match(back.edits[0].embeds[0].footer.text, /Page 1\/2/);
  now = 1100; const expired = interaction(created.token, 'next'); await menus.handle(expired); assert.match(expired.replies[0].content, /do not re-submit/); assert.equal(menus.sessions.size, 0);
});

test('comparison refresh updates the displayed record, is throttled, and fails visibly without losing the report', async () => {
  let now = 100, calls = 0;
  const menus = new ReportMenus({ now: () => now, refreshComparison: async () => { calls++; if (calls === 2) throw Error('service unavailable'); const c = comparison(); c.published.bestSeconds = 900; return c; } });
  const r = report(), created = menus.create(r, USER, GUILD); menus.bind(created.token, MESSAGE);
  const visit = interaction(created.token, 'section', ['comparison']); await menus.handle(visit);
  assert.equal(calls, 1); assert.match(JSON.stringify(visit.edits), /00:15:00.000/);
  const early = interaction(created.token, 'refresh'); await menus.handle(early); assert.equal(calls, 1); assert.equal(early.deferred, 0);
  now += 16000; const retry = interaction(created.token, 'refresh'); await menus.handle(retry); assert.equal(calls, 2); assert.match(JSON.stringify(retry.edits), /latest record check failed/);
  assert.equal(r.recordId, 'a'.repeat(32)); assert.equal(r.comparison.published.status, 'stale');
});

test('report session count and total memory are bounded, with busy updates protected', async () => {
  let release; const menus = new ReportMenus({ maxSessions: 1, refreshComparison: async () => new Promise(resolve => { release = resolve; }) });
  const first = menus.create(report(), USER, GUILD), second = menus.create(report(), USER, GUILD); assert.equal(menus.sessions.size, 1); assert.equal(menus.sessions.has(first.token), false);
  menus.bind(second.token, MESSAGE);
  const progress = menus.handle(interaction(second.token, 'section', ['comparison'])); await new Promise(resolve => setImmediate(resolve));
  const concurrent = interaction(second.token, 'next'); await menus.handle(concurrent); assert.match(concurrent.replies[0].content, /updating/);
  release(comparison()); await progress;
  const tiny = new ReportMenus({ maxBytes: 10 }); assert.equal(tiny.create(report(), USER, GUILD), null);
});

test('open comparison bars update from cached published snapshots without sending new messages', async () => {
  let now = 100; const menus = new ReportMenus({ now: () => now });
  const r = report(); r.comparison = comparison();
  const created = menus.create(r, USER, GUILD), edited = [];
  menus.bind(created.token, MESSAGE, { edit: async message => edited.push(message) });
  const next = { ...comparison().published, bestSeconds: 900 };
  assert.equal(await menus.refreshPublishedSnapshots(() => next), 0); // Overview never changes itself.
  const visit = interaction(created.token, 'section', ['comparison']); await menus.handle(visit);
  assert.equal(await menus.refreshPublishedSnapshots(() => next), 1);
  assert.match(JSON.stringify(visit.edits[1]), /00:15:00.000/);
  assert.equal(visit.replies.length, 0); assert.equal(edited.length, 0); // The component supplied a fresh edit token.
  assert.equal(await menus.refreshPublishedSnapshots(() => next), 0); // Identical cache causes no edit.
  const updated = { ...next, checkedAt: new Date(Date.now() + 1000).toISOString(), bestSeconds: 850 };
  assert.equal(await menus.refreshPublishedSnapshots(() => updated), 1);
  assert.match(JSON.stringify(visit.edits[2]), /00:14:10.000/);
  assert.equal(r.comparison.peers.sampleCount, 3);
  now += 14 * 60 * 1000;
  assert.equal(await menus.refreshPublishedSnapshots(() => ({ ...updated, bestSeconds: 800 })), 0);
  assert.equal(menus.sessions.get(created.token).edit, null);
});

test('expired webhook, malformed snapshots and mismatched categories fail without repeated edits', async () => {
  const menus = new ReportMenus(), r = report(); r.comparison = comparison();
  const created = menus.create(r, USER, GUILD); let calls = 0;
  menus.sessions.get(created.token).section = 'comparison';
  menus.bind(created.token, MESSAGE, { edit: async () => { calls++; throw Error('expired webhook token'); } });
  assert.equal(await menus.refreshPublishedSnapshots(() => ({ ...comparison().published, categoryId: 'different', bestSeconds: 800 })), 0);
  assert.equal(await menus.refreshPublishedSnapshots(() => ({ ...comparison().published, notice: 'x'.repeat(300000), bestSeconds: 800 })), 0);
  assert.equal(calls, 0);
  assert.equal(await menus.refreshPublishedSnapshots(() => ({ ...comparison().published, bestSeconds: 900 })), 0);
  assert.equal(calls, 1);
  assert.equal(await menus.refreshPublishedSnapshots(() => ({ ...comparison().published, bestSeconds: 800 })), 0);
  assert.equal(calls, 1);
});
