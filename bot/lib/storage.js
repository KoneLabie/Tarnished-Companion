'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { parseJson, object, exactFields } = require('./strict-json');
const { PackageError, fingerprint } = require('./package');
const ID = /^[0-9]{17,20}$/;
function atomicWrite(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = `${file}.${process.pid}.${crypto.randomBytes(8).toString('hex')}.tmp`;
  let handle;
  try {
    handle = fs.openSync(temporary, 'wx', 0o600);
    fs.writeFileSync(handle, data); fs.fsyncSync(handle); fs.closeSync(handle); handle = undefined;
    fs.renameSync(temporary, file);
    try { const directory = fs.openSync(path.dirname(file), 'r'); try { fs.fsyncSync(directory); } finally { fs.closeSync(directory); } } catch (error) { if (!['EINVAL', 'EPERM', 'EISDIR', 'ENOTSUP'].includes(error.code)) throw error; }
  } finally {
    if (handle !== undefined) fs.closeSync(handle);
    try { fs.unlinkSync(temporary); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
}
function readJson(file, maximum, fallback, limits) {
  try {
    const fd = fs.openSync(file, 'r');
    try {
      if (fs.fstatSync(fd).size > maximum) throw new PackageError('STORAGE', 'A verifier state file exceeds its size limit.');
      const chunks = []; let total = 0;
      while (total <= maximum) {
        const bytes = Buffer.alloc(Math.min(65536, maximum + 1 - total));
        const length = fs.readSync(fd, bytes, 0, bytes.length, null);
        if (!length) break;
        total += length; chunks.push(bytes.subarray(0, length));
      }
      return parseJson(Buffer.concat(chunks, total), maximum, 'Verifier state', limits);
    } finally { fs.closeSync(fd); }
  } catch (error) { if (error.code === 'ENOENT' && fallback !== undefined) return fallback; throw error; }
}
function readTrust(directory) {
  const data = readJson(path.join(directory, 'trusted-signers.json'), 2 * 1024 * 1024, { schemaVersion: 1, signers: {} });
  if (!exactFields(data, ['schemaVersion', 'signers']) || data.schemaVersion !== 1 || !object(data.signers)) throw new PackageError('STORAGE', 'Trusted signer registry is malformed.');
  for (const [pin, record] of Object.entries(data.signers)) {
    if (fingerprint(pin) !== pin || !exactFields(record, ['discordUserId', 'enrolledAt']) || !ID.test(record.discordUserId) || typeof record.enrolledAt !== 'string') throw new PackageError('STORAGE', 'Trusted signer registry has an invalid enrollment.');
  }
  return data;
}
function acquireLock(directory, name = 'bot.lock') {
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  const file = path.join(directory, name), token = crypto.randomBytes(24).toString('hex');
  let fd;
  function processStart(pid) {
    // Linux start ticks distinguish a stale lock after a container PID is reused.
    try { const stat = fs.readFileSync(`/proc/${pid}/stat`, 'utf8'); return stat.slice(stat.lastIndexOf(')') + 2).split(' ')[19]; } catch { return null; }
  }
  try { fd = fs.openSync(file, 'wx', 0o600); }
  catch (error) {
    if (error.code !== 'EEXIST') throw error;
    const old = readJson(file, 4096);
    let stale = false;
    if (Number.isInteger(old.pid) && old.pid > 0 && typeof old.token === 'string') {
      try { process.kill(old.pid, 0); } catch (probe) { if (probe.code === 'ESRCH') stale = true; }
      const liveStart = processStart(old.pid);
      if (old.processStart && liveStart && old.processStart !== liveStart) stale = true;
    }
    if (!stale) throw new PackageError('LOCKED', `Verifier state is locked (${name}). Stop the other process; remove an unreadable stale lock only after confirming it has exited.`);
    // Recheck ownership before replacing a stale lock; never remove a newer one.
    if (readJson(file, 4096).token !== old.token) throw new PackageError('LOCKED', 'Another verifier acquired the state lock.');
    fs.unlinkSync(file);
    fd = fs.openSync(file, 'wx', 0o600);
  }
  try { fs.writeFileSync(fd, JSON.stringify({ pid: process.pid, token, processStart: processStart(process.pid) })); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
  return () => {
    try {
      const current = readJson(file, 4096);
      if (current.token === token && current.pid === process.pid) fs.unlinkSync(file);
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
  };
}
function enroll(directory, pin, userId) {
  pin = fingerprint(pin);
  if (!ID.test(userId)) throw new PackageError('CONFIG', 'Discord user ID must be a 17–20 digit snowflake.');
  const unlock = acquireLock(directory, 'enrollment.lock');
  try {
    const registry = readTrust(directory), existing = registry.signers[pin];
    if (existing && existing.discordUserId !== userId) throw new PackageError('CONFIG', 'That signer is already enrolled to another Discord account. Remove it explicitly before reassigning.');
    if (!existing) {
      registry.signers[pin] = { discordUserId: userId, enrolledAt: new Date().toISOString() };
      atomicWrite(path.join(directory, 'trusted-signers.json'), JSON.stringify(registry, null, 2) + '\n');
    }
  } finally { unlock(); }
}
class ReceiptStore {
  constructor(directory) { this.directory = directory; this.file = path.join(directory, 'receipts.json'); this.pending = Promise.resolve(); }
  commit(opened, report, userId) {
    const action = this.pending.then(() => {
      const enrollment = readTrust(this.directory).signers[opened.signingFingerprint];
      if (!enrollment) throw new PackageError('UNTRUSTED', 'This valid signing key is not enrolled. Ask an administrator to verify your fingerprint independently.');
      if (enrollment.discordUserId !== userId) throw new PackageError('IDENTITY', 'The report signing key is enrolled to a different Discord account.');
      const state = readJson(this.file, 64 * 1024 * 1024, { schemaVersion: 1, receipts: [] }, { maxNodes: 1200000 });
      if (!exactFields(state, ['schemaVersion', 'receipts']) || state.schemaVersion !== 1 || !Array.isArray(state.receipts) || state.receipts.length > 100000) throw new PackageError('STORAGE', 'Replay receipt storage is malformed. No submissions were accepted.');
      for (const item of state.receipts) {
        if (!object(item) || !/^[0-9a-f]{64}$/.test(item.payloadSha256) || !/^[0-9a-f]{64}$/.test(item.signingFingerprint) || !/^[0-9a-f]{32}$/.test(item.runId)) throw new PackageError('STORAGE', 'Replay receipt history is malformed. No submissions were accepted.');
        if (item.payloadSha256 === opened.payloadSha256 || (item.signingFingerprint === opened.signingFingerprint && item.runId === report.recordId)) throw new PackageError('REPLAY', 'This report or run was already submitted. Re-encrypting or re-exporting it does not create another result.');
      }
      if (state.receipts.length >= 100000) throw new PackageError('STORAGE', 'Receipt capacity reached. The administrator must migrate replay history before accepting more reports.');
      if (!fs.existsSync(this.file)) {
        const reportsDirectory = path.join(this.directory, 'reports');
        if (fs.existsSync(reportsDirectory) && fs.readdirSync(reportsDirectory).length) throw new PackageError('STORAGE', 'Replay history is missing while saved reports exist. Restore the matching receipts backup before accepting submissions.');
        atomicWrite(this.file, JSON.stringify(state) + '\n');
      }
      const receipt = { receivedAt: new Date().toISOString(), discordUserId: userId, signingFingerprint: opened.signingFingerprint, payloadSha256: opened.payloadSha256, runId: report.recordId, category: report.category.id, elapsedSeconds: report.timing.elapsedSeconds, reviewStatus: report.reviewStatus };
      const reportFile = path.join(this.directory, 'reports', `${opened.payloadSha256}.json`);
      // A crash before receipt commit leaves only an orphan report. Retry is
      // safe; receipts never exist before the durable normalized report.
      atomicWrite(reportFile, JSON.stringify({ receipt, report }, null, 2) + '\n');
      state.receipts.push(receipt);
      atomicWrite(this.file, JSON.stringify(state) + '\n');
      return receipt;
    });
    this.pending = action.catch(() => {});
    return action;
  }
}
module.exports = { atomicWrite, readJson, readTrust, enroll, acquireLock, ReceiptStore, ID };
