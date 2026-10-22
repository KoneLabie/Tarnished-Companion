'use strict';
const { object } = require('./strict-json');
const { PackageError } = require('./package');
const fail = message => { throw new PackageError('INELIGIBLE', message); };
const text = (v, max = 512) => typeof v === 'string' && v.length <= max;
const number = v => typeof v === 'number' && Number.isFinite(v) && v >= 0 && v < 1e12;
const integer = v => Number.isSafeInteger(v) && v >= 0;
const date = v => text(v, 100) && /T.*(?:Z|[+-]\d\d:\d\d)$/.test(v) && Number.isFinite(Date.parse(v));
const clean = (v, max = 512) => String(v ?? 'Unavailable').replace(/[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u206f]/g, ' ').slice(0, max);
function duration(v) {
  if (!number(v)) return 'Unavailable';
  let ms = Math.round(v * 1000);
  const hours = Math.floor(ms / 3600000); ms %= 3600000;
  const minutes = Math.floor(ms / 60000); ms %= 60000;
  const seconds = Math.floor(ms / 1000); ms %= 1000;
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
}
function boundedArray(v, maximum, label) {
  if (!Array.isArray(v) || v.length > maximum) fail(`${label} must be a bounded list.`);
  return v;
}
function buildSnapshot(snapshot) {
  if (snapshot == null) return null;
  if (!object(snapshot)) fail('Build snapshot is malformed.');
  const equipment = object(snapshot.equipment) ? snapshot.equipment : {};
  function items(key, maximum) {
    if (equipment[key] == null) return [];
    return boundedArray(equipment[key], maximum, `Build ${key}`).map(item => {
      if (!object(item) || !text(item.slot, 64) || !['resolved', 'empty', 'unavailable'].includes(item.status)
          || !(item.itemId == null || integer(item.itemId)) || !(item.rawItemId == null || integer(item.rawItemId))
          || !(item.name == null || text(item.name, 512))) fail('Build equipment item is malformed.');
      return {
        slot: clean(item.slot, 64), status: item.status,
        name: item.status === 'resolved' && item.name ? clean(item.name) : item.status === 'empty' ? 'Empty' : 'Unavailable',
        itemId: item.itemId ?? null, rawItemId: item.rawItemId ?? null,
        active: typeof item.active === 'boolean' ? item.active : null,
        upgradeLevel: integer(item.upgradeLevel) ? item.upgradeLevel : null,
        baseItemId: integer(item.baseItemId) ? item.baseItemId : null,
        affinity: text(item.affinity, 128) ? clean(item.affinity, 128) : null,
      };
    });
  }
  const attributes = {};
  for (const name of ['vigor', 'mind', 'endurance', 'strength', 'dexterity', 'intelligence', 'faith', 'arcane']) {
    const value = snapshot.attributes?.[name];
    attributes[name] = integer(value) && value <= 999 ? value : null;
  }
  return {
    status: clean(snapshot.status, 64), source: clean(snapshot.source, 128),
    character: clean(snapshot.character ?? snapshot.name), saveSlot: integer(snapshot.saveSlot) ? snapshot.saveSlot : null,
    level: integer(snapshot.level) ? snapshot.level : null,
    class: text(snapshot.class) ? clean(snapshot.class) : 'Unavailable', attributes,
    equipment: { weapons: items('weapons', 6), armor: items('armor', 4), talismans: items('talismans', 4),
      activeWeaponSlots: { left: integer(equipment.activeWeaponSlots?.left) ? equipment.activeWeaponSlots.left : null, right: integer(equipment.activeWeaponSlots?.right) ? equipment.activeWeaponSlots.right : null } },
    notice: clean(snapshot.notice ?? '', 2048),
    issues: boundedArray(snapshot.issues ?? [], 128, 'Build issues').map(issue => clean(issue, 2048)),
  };
}
function normalizeBuild(build) {
  if (!object(build)) return { status: 'unavailable', notice: 'No build snapshot was included.', initial: null, final: null, observations: [], truncated: false };
  const observations = boundedArray(build.observations ?? [], 10000, 'Build observations').map(entry => {
    if (!object(entry) || !date(entry.observedAt) || !(entry.savedAt == null || date(entry.savedAt)) || !(entry.elapsedSeconds == null || number(entry.elapsedSeconds))) fail('Build observation is malformed.');
    return { observedAt: entry.observedAt, savedAt: entry.savedAt ?? null, elapsedSeconds: entry.elapsedSeconds ?? null, snapshot: buildSnapshot(entry.snapshot) };
  });
  return { status: clean(build.status, 64), source: clean(build.source, 128), notice: clean(build.notice ?? '', 2048), initial: buildSnapshot(build.initial), final: buildSnapshot(build.final), observations, truncated: build.truncated === true };
}
function normalizeReport(opened) {
  const p = opened.payload, run = p.run;
  if (p.schemaVersion !== 1 || p.format !== 'tarnished-run' || p.simulation !== false) fail('Only genuine-format, non-simulation run exports are accepted.');
  if (!object(run) || run.schemaVersion !== 1 || !/^[0-9a-f]{32}$/.test(run.recordId) || !text(run.contextKey, 1024) || !run.contextKey || !text(run.character) || !integer(run.journey) || run.journey < 1) fail('Run identity or character information is invalid.');
  if (run.status !== 'finished' || !date(run.startedAt) || !date(run.endedAt) || Date.parse(run.endedAt) < Date.parse(run.startedAt)) fail('Only a finished run with a valid observed start and end can be submitted.');
  if (run.partial !== false || run.attributionLost !== false || run.continuityUnverified !== false) fail('Partial, interrupted, or uncertain-continuity observations cannot be submitted as complete results.');
  if (!object(run.runPolicy) || run.runPolicy.eligible !== true || !['candidate', 'review-required'].includes(run.runPolicy.status) || !text(run.runPolicy.categoryId, 128) || !run.runPolicy.categoryId || !text(run.runPolicy.categoryName) || !run.runPolicy.categoryName) fail('The report lacks eligible witnessed-start/category evidence.');
  if (!['no-issues-observed', 'review-required'].includes(run.localAuditStatus)) fail('The run failed its local audit or has no recognized local audit.');
  if (!number(run.elapsedSeconds) || !(run.realTimeSeconds == null || number(run.realTimeSeconds)) || !number(run.igtSeconds) || !integer(run.deaths)) fail('Run time or death statistics are invalid.');
  if (!date(p.exportedAt) || !object(p.application) || !text(p.application.kind, 64) || !/^[0-9a-f]{64}$/.test(p.application.sha256)) fail('Export provenance is missing or malformed.');
  const start = Date.parse(run.startedAt), end = Date.parse(run.endedAt);
  const seen = new Set();
  const splits = boundedArray(run.splits, 10000, 'Boss splits').map(split => {
    if (!object(split) || !integer(split.bossId) || seen.has(split.bossId) || !text(split.name) || !(split.elapsedSeconds == null || number(split.elapsedSeconds)) || !number(split.igtSeconds) || !text(split.source)) fail('An observed boss split is invalid.');
    if (split.elapsedSeconds > run.elapsedSeconds + 0.1) fail('A boss split exceeds the final observed game time.');
    seen.add(split.bossId);
    return { bossId: split.bossId, name: clean(split.name), elapsedSeconds: split.elapsedSeconds, savedCharacterSeconds: split.igtSeconds, source: clean(split.source) };
  });
  const attemptsInfo = p.attempts;
  const noAttemptObservations = object(attemptsInfo) && Array.isArray(attemptsInfo.records) && attemptsInfo.records.length === 0 && attemptsInfo.character === 'Unavailable' && attemptsInfo.journey === null;
  if (!object(attemptsInfo) || attemptsInfo.contextKey !== run.contextKey || (!noAttemptObservations && (attemptsInfo.character !== run.character || attemptsInfo.journey !== run.journey))) fail('Boss attempts do not belong to the submitted character and journey.');
  const attemptIds = new Set();
  const attempts = boundedArray(attemptsInfo.records, 10000, 'Boss attempts').map(attempt => {
    if (!object(attempt) || !text(attempt.recordId, 128) || !attempt.recordId || attemptIds.has(attempt.recordId)
        || attempt.contextKey !== run.contextKey || !text(attempt.name)
        || !(attempt.bossId == null || integer(attempt.bossId))
        || !(attempt.attemptNumber == null || (integer(attempt.attemptNumber) && attempt.attemptNumber > 0))
        || (attempt.categoryId != null && attempt.categoryId !== run.runPolicy.categoryId)
        || !['victory', 'death', 'unconfirmed', 'interrupted', 'in-progress-at-run-end'].includes(attempt.outcome)
        || !date(attempt.startedAt) || Date.parse(attempt.startedAt) < start || Date.parse(attempt.startedAt) > end
        || !(attempt.elapsedSeconds == null || number(attempt.elapsedSeconds))) fail('A boss attempt is malformed or belongs outside this run.');
    if (attempt.outcome !== 'in-progress-at-run-end' && (!date(attempt.endedAt) || Date.parse(attempt.endedAt) > end || Date.parse(attempt.endedAt) < Date.parse(attempt.startedAt))) fail('Boss attempt outcome falls outside the run bounds.');
    if (attempt.outcome === 'in-progress-at-run-end' && attempt.elapsedSeconds !== null) fail('An unfinished attempt must not claim a final duration.');
    attemptIds.add(attempt.recordId);
    return { recordId: attempt.recordId, bossId: attempt.bossId, name: clean(attempt.name), attemptNumber: attempt.attemptNumber, outcome: attempt.outcome, elapsedSeconds: attempt.elapsedSeconds, startedAt: attempt.startedAt, endedAt: attempt.outcome === 'in-progress-at-run-end' ? null : attempt.endedAt, note: clean(attempt.note ?? '', 2048),
      eligibleForBenchmark: attempt.eligibleForBenchmark === true && attempt.zeroHpObserved === true
        && attempt.partialStart === false && attempt.outcome === 'victory' && number(attempt.elapsedSeconds)
        && attempt.elapsedSeconds > 0 && integer(attempt.bossId) };
  });
  const auditReasons = boundedArray(run.localAuditReasons ?? [], 128, 'Audit reasons').map(reason => {
    if (!text(reason, 2048)) fail('Audit reason is invalid.'); return clean(reason, 2048);
  });
  return {
    schemaVersion: 1, reviewStatus: 'REVIEW REQUIRED — not official leaderboard approval',
    verification: { signingFingerprint: opened.signingFingerprint, payloadSha256: opened.payloadSha256, recipientFingerprint: opened.recipientFingerprint },
    recordId: run.recordId, character: clean(run.character), journey: run.journey,
    category: { id: clean(run.runPolicy.categoryId, 128), name: clean(run.runPolicy.categoryName), liveSplitName: clean(run.category), startPolicy: run.runPolicy.status },
    startedAt: run.startedAt, endedAt: run.endedAt, exportedAt: p.exportedAt,
    timing: { source: 'Observed LiveSplit Game Time', elapsedSeconds: run.elapsedSeconds, realTimeSeconds: run.realTimeSeconds, savedCharacterSeconds: run.igtSeconds },
    deaths: run.deaths, localAuditStatus: run.localAuditStatus, auditReasons, splits, attempts,
    build: normalizeBuild(p.build), application: { kind: clean(p.application.kind, 64), sha256: p.application.sha256 },
    limitations: 'A valid signature checks unchanged bytes and the enrolled signing key. It does not prove gameplay, anti-cheat status, category compliance, or the actual executable used. Original video and leaderboard review are still required.',
  };
}
function renderText(report) {
  const b = report.build.final || report.build.initial;
  const lines = ['TARNISHED COMPANION — VERIFIED REPORT RECEIPT', report.reviewStatus,
    `Category: ${report.category.name}`, `Character: ${report.character} | Journey ${report.journey}`,
    `LiveSplit Game Time: ${duration(report.timing.elapsedSeconds)}`, `Real Time: ${duration(report.timing.realTimeSeconds)}`,
    `Observed deaths: ${report.deaths} | Boss defeats: ${report.splits.length} | Boss attempts: ${report.attempts.length}`,
    `Local audit: ${report.localAuditStatus}`, ...report.auditReasons.map(r => `Audit: ${r}`), '', 'OBSERVED BOSS SPLITS (save flags; not official splits)'];
  lines.push(...report.splits.map((s, i) => `${i + 1}. ${s.name} [${s.bossId}] — ${duration(s.elapsedSeconds)}`));
  if (!report.splits.length) lines.push('No boss splits recorded.');
  lines.push('', 'OBSERVED BOSS ATTEMPTS');
  lines.push(...report.attempts.map(a => `${a.name} [${a.bossId ?? 'unresolved arena'}] | Attempt ${a.attemptNumber ?? '?'} | ${a.outcome} | ${duration(a.elapsedSeconds)}`));
  if (!report.attempts.length) lines.push('No live boss attempts recorded.');
  lines.push('', 'BUILD / EQUIPMENT', `Build snapshots: ${report.build.observations.length}${report.build.truncated ? ' (history truncated)' : ''}`, report.build.notice);
  if (!b) lines.push('Build unavailable; no equipment is inferred.');
  else {
    lines.push(`Level ${b.level ?? 'Unavailable'} | ${b.class} | ${b.source}`, b.notice);
    lines.push(Object.entries(b.attributes).map(([key, value]) => `${key}: ${value ?? 'Unavailable'}`).join(' | '));
    for (const group of ['weapons', 'armor', 'talismans']) {
      lines.push(`${group}:`);
      lines.push(...b.equipment[group].map(item => `  ${item.slot}: ${item.name}${item.active === true ? ' (active)' : ''}${item.upgradeLevel !== null ? ` +${item.upgradeLevel}` : ''}${item.affinity ? ` | ${item.affinity}` : ''}`));
      if (!b.equipment[group].length) lines.push('  Unavailable');
    }
  }
  lines.push('', `Run ID: ${report.recordId}`, `Signer: ${report.verification.signingFingerprint}`, `Payload SHA-256: ${report.verification.payloadSha256}`, `Application file SHA-256 (client reported): ${report.application.sha256}`, '', report.limitations);
  return lines.join('\n') + '\n';
}
function summary(report) {
  const b = report.build.final || report.build.initial;
  const md = (value, limit) => clean(value, limit).replace(/[\\`*_{}\[\]()<>#+.!|~>-]/g, '\\$&');
  return ['Report signature verified; enrolled Discord account matched.',
    '**REVIEW REQUIRED — not official leaderboard approval.**',
    `Category: ${md(report.category.name, 200)}`, `Character: ${md(report.character, 100)} · Journey ${report.journey}`,
    `Game Time: ${duration(report.timing.elapsedSeconds)} · Deaths: ${report.deaths}`,
    `Observed boss defeats: ${report.splits.length} · Attempts: ${report.attempts.length}`,
    `Build: ${b ? `level ${b.level ?? '?'} ${md(b.class, 80)}` : 'unavailable'} · Snapshots: ${report.build.observations.length}`,
    `Local audit: ${report.localAuditStatus}`, 'Full splits, attempts, and equipment are attached. The JSON includes the observed loadout timeline.',
    `Receipt run ID: ${report.recordId}`].join('\n');
}
module.exports = { normalizeReport, renderText, summary, duration, clean };
