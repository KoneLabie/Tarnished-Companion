'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const { fixture, validPayload } = require('./helpers');
const { decryptPackage } = require('../lib/package');
const { normalizeReport, renderText, summary } = require('../lib/report');
const { ReceiptStore, enroll, readTrust, acquireLock, readJson } = require('../lib/storage');
const { submit, downloadAttachment, safeUrl } = require('../lib/submission');
const USER = '123456789012345678', OTHER = '987654321098765432';
function directory(t) { const d = fs.mkdtempSync(path.join(os.tmpdir(), 'tl-bot-test-')); t.after(() => fs.rmSync(d, { recursive: true, force: true })); return d; }
function opened(payload = validPayload()) { const f = fixture(payload); return decryptPackage(f.bytes, f.rawPrivate, f.fingerprint); }
test('complete report normalizes category, observed splits/attempts and explicit unavailable build', () => {
  const r = normalizeReport(opened());
  assert.equal(r.category.name, 'Any% Glitchless'); assert.equal(r.splits.length, 1); assert.equal(r.attempts[0].elapsedSeconds, 180);
  assert.equal(r.build.final, null); assert.match(renderText(r), /Build unavailable; no equipment is inferred/);
  assert.match(summary(r), /REVIEW REQUIRED/); assert.match(renderText(r), /not official leaderboard approval/);
});
test('simulation, incomplete, ineligible, uncertain and malformed identity results are rejected', () => {
  const mutations = [p => p.simulation = true, p => delete p.simulation, p => p.run.status = 'running', p => p.run.partial = true,
    p => p.run.attributionLost = true, p => p.run.continuityUnverified = true, p => delete p.run.continuityUnverified,
    p => p.run.runPolicy.eligible = false, p => p.run.localAuditStatus = 'ineligible', p => p.run.endedAt = null,
    p => p.run.elapsedSeconds = -1, p => p.run.recordId = '../escape', p => p.application.sha256 = 'bad',
    p => p.attempts.character = 'Different character', p => p.attempts.records[0].categoryId = 'another-category',
    p => p.attempts.records[0].startedAt = '2026-10-22T09:00:00Z', p => p.attempts.records[0].endedAt = '2026-10-22T12:00:00Z',
    p => p.run.splits.push(p.run.splits[0]), p => p.run.splits[0].elapsedSeconds = 99999];
  for (const mutate of mutations) { const p = validPayload(); mutate(p); assert.throws(() => normalizeReport(opened(p)), { code: 'INELIGIBLE' }); }
});
test('review-required complete reports stay review-required; boss attempt at run end cannot borrow later duration', () => {
  const p = validPayload(); p.run.runPolicy.status = 'review-required'; p.run.localAuditStatus = 'review-required';
  const a = p.attempts.records[0]; a.outcome = 'in-progress-at-run-end'; a.elapsedSeconds = null; a.endedAt = '2026-10-22T12:00:00Z';
  const r = normalizeReport(opened(p)); assert.equal(r.attempts[0].elapsedSeconds, null); assert.equal(r.attempts[0].endedAt, null);
  a.elapsedSeconds = 360; assert.throws(() => normalizeReport(opened(p)));
});
test('final equipment and history are normalized without inventing unidentified names', () => {
  const p = validPayload();
  const snapshot = { status: 'partial', source: 'checksum-validated-save', character: 'Test Tarnished', level: 30, class: 'Hero', attributes: { vigor: 20 },
    equipment: { weapons: [{ slot: 'rightHand1', rawItemId: 123, itemId: 123, name: 'Longsword', status: 'resolved', active: true, upgradeLevel: 3 }, { slot: 'leftHand1', rawItemId: 999, itemId: 999, name: null, status: 'unavailable' }], armor: [], talismans: [] }, notice: 'Some names unavailable' };
  p.build = { status: 'partial', source: 'save', initial: snapshot, final: snapshot, observations: [{ observedAt: '2026-10-22T10:30:00Z', savedAt: null, elapsedSeconds: 100, snapshot }], truncated: false };
  const r = normalizeReport(opened(p)); assert.equal(r.build.observations.length, 1); assert.equal(r.build.final.equipment.weapons[1].name, 'Unavailable');
  assert.match(renderText(r), /Longsword \(active\) \+3/); assert.match(renderText(r), /leftHand1: Unavailable/);
});
test('unknown and mismatched signers never auto-enroll or create replay receipts', async t => {
  const d = directory(t), f = fixture(), store = new ReceiptStore(d);
  await assert.rejects(submit(f.bytes, USER, f.rawPrivate, store), { code: 'UNTRUSTED' });
  assert.deepEqual(readTrust(d).signers, {}); assert.equal(fs.existsSync(path.join(d, 'receipts.json')), false);
  enroll(d, f.fingerprint, OTHER);
  await assert.rejects(submit(f.bytes, USER, f.rawPrivate, store), { code: 'IDENTITY' });
  assert.equal(fs.existsSync(path.join(d, 'receipts.json')), false);
});
test('enrolled submission commits durable results and deduplicates concurrent, repeated and re-exported runs', async t => {
  const d = directory(t), f = fixture(), store = new ReceiptStore(d); enroll(d, f.fingerprint, USER);
  const result = await Promise.allSettled([submit(f.bytes, USER, f.rawPrivate, store), submit(f.bytes, USER, f.rawPrivate, store)]);
  assert.equal(result.filter(x => x.status === 'fulfilled').length, 1); assert.equal(result.find(x => x.status === 'rejected').reason.code, 'REPLAY');
  const restored = new ReceiptStore(d); await assert.rejects(submit(f.bytes, USER, f.rawPrivate, restored), { code: 'REPLAY' });
  const open = decryptPackage(f.bytes, f.rawPrivate), report = normalizeReport(open);
  await assert.rejects(restored.commit({ ...open, payloadSha256: 'f'.repeat(64) }, report, USER), { code: 'REPLAY' });
  const state = readJson(path.join(d, 'receipts.json'), 1024 * 1024); assert.equal(state.receipts.length, 1);
  assert.equal(fs.readdirSync(path.join(d, 'reports')).length, 1); assert.equal(fs.readdirSync(d).some(name => name.endsWith('.tmp')), false);
});
test('malformed storage fails closed and enrollment cannot silently reassign a signer', async t => {
  const d = directory(t), f = fixture(), store = new ReceiptStore(d); enroll(d, f.fingerprint, USER);
  assert.throws(() => enroll(d, f.fingerprint, OTHER));
  fs.writeFileSync(path.join(d, 'receipts.json'), '{"schemaVersion":1,"receipts":[{}]}');
  await assert.rejects(submit(f.bytes, USER, f.rawPrivate, store), { code: 'STORAGE' });
  const unlock = acquireLock(d); assert.throws(() => acquireLock(d), { code: 'LOCKED' }); unlock();
  const again = acquireLock(d); again();
});
test('Discord download confines redirects, metadata and streaming bodies to bounded CDN attachments', async () => {
  const bytes = Buffer.from('package'), a = { name: 'run.tlrun', size: bytes.length, url: 'https://cdn.discordapp.com/attachments/123/456/run.tlrun' };
  assert.deepEqual(await downloadAttachment(a, async () => new Response(bytes)), bytes);
  for (const url of ['http://cdn.discordapp.com/attachments/x', 'https://evil.example/attachments/x', 'https://cdn.discordapp.com@evil.example/attachments/x', 'https://cdn.discordapp.com:444/attachments/x', 'https://cdn.discordapp.com/not-attachment']) assert.throws(() => safeUrl(url));
  await assert.rejects(downloadAttachment(a, async () => new Response(null, { status: 302, headers: { location: 'https://evil.example/' } })), { code: 'DOWNLOAD' });
  await assert.rejects(downloadAttachment({ ...a, size: 1 }, async () => new Response(bytes)), { code: 'DOWNLOAD' });
  await assert.rejects(downloadAttachment(a, async () => new Response(bytes, { headers: { 'content-length': '999999999' } })), { code: 'DOWNLOAD' });
  await assert.rejects(downloadAttachment({ ...a, size: 9 * 1024 * 1024 }, async () => new Response(bytes)), { code: 'DOWNLOAD' });
});
test('Discord command definition needs only an attachment; no privileged gateway intent or token at import', () => {
  const commands = require('../commands').commands(); assert.equal(commands.length, 1); assert.equal(commands[0].name, 'submit'); assert.equal(commands[0].options[0].type, 11);
  assert.equal(typeof require('../index').main, 'function');
});
test('receipt history remains readable beyond the untrusted payload node limit', async t => {
  const d = directory(t), f = fixture(); enroll(d, f.fingerprint, USER);
  const receipts = Array.from({ length: 22223 }, (_, i) => ({ receivedAt: '2026-10-22T10:00:00Z', discordUserId: USER,
    signingFingerprint: '1'.repeat(64), payloadSha256: i.toString(16).padStart(64, '0'), runId: i.toString(16).padStart(32, '0'),
    category: 'test', elapsedSeconds: 100, reviewStatus: 'REVIEW REQUIRED' }));
  fs.writeFileSync(path.join(d, 'receipts.json'), JSON.stringify({ schemaVersion: 1, receipts }));
  await submit(f.bytes, USER, f.rawPrivate, new ReceiptStore(d));
  const result = readJson(path.join(d, 'receipts.json'), 64 * 1024 * 1024, undefined, { maxNodes: 1200000 });
  assert.equal(result.receipts.length, 22224);
});
test('lost receipts fail closed when saved reports exist; unavailable empty attempts remain explicit', async t => {
  const d = directory(t), f = fixture(); enroll(d, f.fingerprint, USER);
  await submit(f.bytes, USER, f.rawPrivate, new ReceiptStore(d));
  fs.unlinkSync(path.join(d, 'receipts.json'));
  await assert.rejects(submit(f.bytes, USER, f.rawPrivate, new ReceiptStore(d)), { code: 'STORAGE' });
  const p = validPayload(); p.attempts = { contextKey: p.run.contextKey, character: 'Unavailable', journey: null, records: [] };
  assert.equal(normalizeReport(opened(p)).attempts.length, 0);
});
test('a demonstrably exited worker lock is recovered while an active lock remains protected', t => {
  const d = directory(t);
  const child = require('node:child_process').spawnSync(process.execPath, ['-e', ''], { windowsHide: true });
  assert.equal(child.status, 0);
  fs.writeFileSync(path.join(d, 'bot.lock'), JSON.stringify({ pid: child.pid, token: 'old-owner', processStart: null }));
  const unlock = acquireLock(d); assert.throws(() => acquireLock(d), { code: 'LOCKED' }); unlock();
});
