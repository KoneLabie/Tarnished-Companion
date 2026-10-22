'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { peerComparison } = require('../lib/peer-comparison');
const { normalizeReport } = require('../lib/report');
const { validPayload } = require('./helpers');

const USER = '827114107491713025', OTHER = '1365847559754612807';
function setup(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'tarnished-peers-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  fs.mkdirSync(path.join(dir, 'reports'));
  const rows = [];
  const base = { recordId: 'a'.repeat(32), category: { id: 'any-percent-glitchless', startPolicy: 'candidate' }, journey: 1,
    localAuditStatus: 'no-issues-observed', timing: { source: 'Observed LiveSplit Game Time', elapsedSeconds: 3000 },
    attempts: [{ bossId: 123, name: 'Boss', outcome: 'victory', eligibleForBenchmark: true, elapsedSeconds: 180 }],
    splits: [{ bossId: 123, name: 'Boss', elapsedSeconds: 600 }] };
  function add(overrides = {}, user = OTHER) {
    const id = (rows.length + 1).toString(16).padStart(32, '0');
    const report = { ...structuredClone(base), recordId: id, ...overrides };
    const receipt = { category: report.category.id, discordUserId: user, payloadSha256: id.repeat(2), runId: id };
    rows.push(receipt);
    fs.writeFileSync(path.join(dir, 'reports', `${receipt.payloadSha256}.json`), JSON.stringify({ receipt, report }));
    fs.writeFileSync(path.join(dir, 'receipts.json'), JSON.stringify({ schemaVersion: 1, receipts: rows }));
  }
  return { dir, base, add };
}
test('peer comparisons exclude own account, other journeys/categories, uncertain starts and timing mismatches', async t => {
  const { dir, base, add } = setup(t);
  add(); add({}, USER); add({ journey: 2 }); add({ category: { id: 'different', startPolicy: 'candidate' } });
  add({ category: { id: base.category.id, startPolicy: 'review-required' } });
  add({ localAuditStatus: 'review-required' }); add({ timing: { source: 'wall clock', elapsedSeconds: 10 } });
  const result = await peerComparison(dir, base, USER);
  assert.equal(result.sampleCount, 1); assert.equal(result.runBestSeconds, 3000);
  assert.equal(result.bosses[0].bestFightSeconds, 180); assert.equal(result.bosses[0].bestSplitSeconds, 600);
  assert.match(result.notice, /Unreviewed/);
  assert.equal(JSON.stringify(result).includes(OTHER), false);
});
test('partial/unconfirmed boss fights never become peer targets and samples update on newer receipts', async t => {
  const { dir, base, add } = setup(t);
  add({ attempts: [{ bossId: 123, name: 'Boss', outcome: 'death', eligibleForBenchmark: true, elapsedSeconds: 1 }] });
  let result = await peerComparison(dir, base, USER);
  assert.equal(result.bosses[0].bestFightSeconds, null);
  add({ timing: { ...base.timing, elapsedSeconds: 2900 }, attempts: [{ ...base.attempts[0], elapsedSeconds: 150 }] });
  result = await peerComparison(dir, base, USER);
  assert.equal(result.runBestSeconds, 2900); assert.equal(result.bosses[0].bestFightSeconds, 150);
});
test('malformed/private storage and size limits provide honest empty states', async t => {
  const { dir, base, add } = setup(t);
  assert.equal((await peerComparison(dir, base, USER)).status, 'empty');
  add(); const limited = await peerComparison(dir, base, USER, { byteBudget: 1 });
  assert.equal(limited.sampleCount, 0); assert.match(limited.notice, /processing limit/);
  fs.writeFileSync(path.join(dir, 'receipts.json'), '{}');
  assert.equal((await peerComparison(dir, base, USER)).status, 'unavailable');
});
test('normalization requires complete observed victory evidence for boss comparison eligibility', () => {
  const payload = validPayload();
  const opened = { payload };
  assert.equal(normalizeReport(opened).attempts[0].eligibleForBenchmark, false);
  Object.assign(payload.attempts.records[0], { eligibleForBenchmark: true, zeroHpObserved: true, partialStart: false });
  assert.equal(normalizeReport(opened).attempts[0].eligibleForBenchmark, true);
  payload.attempts.records[0].partialStart = true;
  assert.equal(normalizeReport(opened).attempts[0].eligibleForBenchmark, false);
});
