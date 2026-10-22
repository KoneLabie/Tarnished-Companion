'use strict';
const fs = require('node:fs/promises');
const path = require('node:path');
const { readJson } = require('./storage');
const { parseJson, object } = require('./strict-json');

const NOTICE = 'Unreviewed submitted reports from other Discord accounts, matched by category, journey and timing source. Routes, versions and builds may differ. These are community observations, not official boss records.';
const validTime = value => typeof value === 'number' && Number.isFinite(value) && value > 0 && value < 1e9;
const mean = values => values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;

async function peerComparison(directory, target, userId, { limit = 200, byteBudget = 32 * 1024 * 1024 } = {}) {
  const empty = { status: 'empty', sampleCount: 0, runBestSeconds: null, runAverageSeconds: null, bosses: [], notice: NOTICE };
  try {
    const state = readJson(path.join(directory, 'receipts.json'), 64 * 1024 * 1024,
      { schemaVersion: 1, receipts: [] }, { maxNodes: 1200000 });
    if (!object(state) || state.schemaVersion !== 1 || !Array.isArray(state.receipts) || state.receipts.length > 100000) throw new Error('Invalid comparison storage');
    const candidates = state.receipts.filter(receipt => object(receipt) && receipt.category === target.category.id
      && receipt.discordUserId !== userId && /^[0-9]{17,20}$/.test(receipt.discordUserId)
      && /^[0-9a-f]{64}$/.test(receipt.payloadSha256) && /^[0-9a-f]{32}$/.test(receipt.runId))
      .slice(-Math.min(200, Math.max(1, limit))).reverse();
    const times = [], bosses = new Map(), seen = new Set();
    let used = 0, truncated = state.receipts.filter(r => r?.category === target.category.id && r?.discordUserId !== userId).length > candidates.length;
    for (const receipt of candidates) {
      if (seen.has(receipt.payloadSha256)) continue;
      seen.add(receipt.payloadSha256);
      const file = path.join(directory, 'reports', `${receipt.payloadSha256}.json`);
      let record;
      const handle = await fs.open(file, 'r');
      try {
        const size = (await handle.stat()).size;
        if (size > 8 * 1024 * 1024 || used + size > byteBudget) { truncated = true; continue; }
        used += size;
        // Read at most the advertised bounded size plus one byte to catch growth.
        const bytes = Buffer.alloc(size + 1);
        let length = 0;
        while (length < bytes.length) {
          const result = await handle.read(bytes, length, bytes.length - length, null);
          if (!result.bytesRead) break;
          length += result.bytesRead;
        }
        if (length !== size) throw new Error('Comparison storage changed during read');
        record = parseJson(bytes.subarray(0, length), 8 * 1024 * 1024, 'Saved report', { maxNodes: 400000 });
      } finally { await handle.close(); }
      const report = record?.report;
      if (!object(report) || record.receipt?.payloadSha256 !== receipt.payloadSha256
          || record.receipt?.discordUserId !== receipt.discordUserId || report.recordId !== receipt.runId
          || report.recordId === target.recordId || report.category?.id !== target.category.id
          || report.journey !== target.journey || report.timing?.source !== target.timing.source
          || report.localAuditStatus !== 'no-issues-observed' || report.category?.startPolicy !== 'candidate'
          || !validTime(report.timing?.elapsedSeconds)) continue;
      times.push(report.timing.elapsedSeconds);
      const row = (id, name) => {
        if (!bosses.has(id)) bosses.set(id, { bossId: id, name: typeof name === 'string' ? name.slice(0, 512) : 'Boss', fights: [], splits: [] });
        return bosses.get(id);
      };
      const bestFights = new Map();
      for (const attempt of Array.isArray(report.attempts) ? report.attempts.slice(0, 10000) : []) {
        if (!Number.isSafeInteger(attempt.bossId) || attempt.bossId < 0 || attempt.outcome !== 'victory'
            || attempt.eligibleForBenchmark !== true || !validTime(attempt.elapsedSeconds)) continue;
        const previous = bestFights.get(attempt.bossId);
        if (!previous || attempt.elapsedSeconds < previous.elapsedSeconds) bestFights.set(attempt.bossId, attempt);
      }
      for (const attempt of bestFights.values()) row(attempt.bossId, attempt.name).fights.push(attempt.elapsedSeconds);
      const seenSplits = new Set();
      for (const split of Array.isArray(report.splits) ? report.splits.slice(0, 10000) : []) {
        if (!Number.isSafeInteger(split.bossId) || split.bossId < 0 || seenSplits.has(split.bossId)
            || !validTime(split.elapsedSeconds) || split.elapsedSeconds > report.timing.elapsedSeconds) continue;
        seenSplits.add(split.bossId);
        row(split.bossId, split.name).splits.push(split.elapsedSeconds);
      }
    }
    return { ...empty, status: times.length ? 'available' : 'empty', sampleCount: times.length,
      runBestSeconds: times.length ? Math.min(...times) : null, runAverageSeconds: mean(times),
      bosses: [...bosses.values()].map(b => ({ bossId: b.bossId, name: b.name, sampleCount: b.fights.length,
        bestFightSeconds: b.fights.length ? Math.min(...b.fights) : null, averageFightSeconds: mean(b.fights),
        splitSampleCount: b.splits.length, bestSplitSeconds: b.splits.length ? Math.min(...b.splits) : null })),
      notice: NOTICE + (truncated ? ' Comparison sample is limited to recent reports within the processing limit.' : '') };
  } catch {
    return { ...empty, status: 'unavailable', notice: 'Community comparison storage is unavailable. Your submitted report is still saved; no peer times are inferred.' };
  }
}

module.exports = { peerComparison };
