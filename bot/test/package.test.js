'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), path = require('node:path'), fs = require('node:fs');
const { spawnSync } = require('node:child_process');
const { fixture, validPayload } = require('./helpers');
const { decryptPackage, generateRecipient, b64, MAX_PACKAGE, MAX_PAYLOAD } = require('../lib/package');
const { canonical, parseJson } = require('../lib/strict-json');
test('valid encrypted report is untrusted without an independent signer pin', () => {
  const f = fixture();
  const open = decryptPackage(f.bytes, f.rawPrivate);
  assert.equal(open.trusted, false); assert.equal(open.payload.run.recordId, f.payload.run.recordId);
  assert.equal(open.payloadSha256, f.payloadSha256);
  assert.equal(decryptPackage(f.bytes, f.rawPrivate, f.fingerprint.toUpperCase()).trusted, true);
  assert.throws(() => decryptPackage(f.bytes, f.rawPrivate, '0'.repeat(64)), { code: 'UNTRUSTED' });
});
test('Python production package decrypts and verifies in Node without changing signed float bytes', t => {
  const source = path.resolve(__dirname, '../../source');
  if (!fs.existsSync(path.join(source, 'run_package.py'))) return t.skip('Python app source is not present in this bot-only deployment.');
  const result = spawnSync(process.env.TARNISHED_TEST_PYTHON || 'python', [path.join(__dirname, 'python_fixture.py'), source], { input: JSON.stringify(validPayload()), encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 });
  if (result.error?.code === 'ENOENT') return t.skip('Set TARNISHED_TEST_PYTHON to Python with cryptography installed.');
  assert.equal(result.status, 0, result.stderr);
  const f = JSON.parse(result.stdout), opened = decryptPackage(Buffer.from(f.package, 'base64'), Buffer.from(f.privateKey, 'base64'), f.fingerprint);
  assert.equal(opened.trusted, true); assert.equal(opened.payloadSha256, f.payloadSha256);
  assert.equal(opened.payload.run.elapsedSeconds, 1234); assert.equal(opened.payload.unicodeInteroperability, 'Malenia — 剣 🗡');
  assert.deepEqual(opened.payload.numericInteroperability, [0, -0, 1e-7, 1e12, 2.5]);
  const normalized = require('../lib/report').normalizeReport(opened);
  assert.equal(normalized.build.final.equipment.weapons[0].name, 'Dagger');
  assert.equal(normalized.build.final.equipment.weapons[0].affinity, 'Cold');
  assert.equal(normalized.build.final.equipment.weapons[0].upgradeLevel, 7);
  assert.equal(normalized.build.final.equipment.weapons[3].name, 'Black Knife');
});
test('wrong recipient is distinct from authenticated ciphertext or header corruption', () => {
  const f = fixture();
  assert.throws(() => decryptPackage(f.bytes, Buffer.from(generateRecipient().privateKey, 'base64')), { code: 'RECIPIENT' });
  for (const field of ['ciphertext', 'nonce', 'ephemeralPublicKey']) {
    const outer = JSON.parse(f.bytes), value = Buffer.from(outer[field], 'base64'); value[0] ^= 1; outer[field] = value.toString('base64');
    assert.throws(() => decryptPackage(Buffer.from(canonical(outer)), f.rawPrivate), { code: 'DECRYPTION' });
  }
});
test('valid encryption cannot substitute for an invalid or ambiguous signature', () => {
  const bad = fixture(undefined, { badSignature: true });
  assert.throws(() => decryptPackage(bad.bytes, bad.rawPrivate), { code: 'SIGNATURE' });
  for (const transform of [b => Buffer.concat([b, Buffer.from('extra')]), b => Buffer.from(b.toString().replaceAll('\n', '\r\n')), b => Buffer.concat([Buffer.from('----- BEGIN TARNISHED LINEUP SIGNATURE -----'), b])]) {
    const f = fixture(undefined, { signedTransform: transform });
    assert.throws(() => decryptPackage(f.bytes, f.rawPrivate));
  }
});
test('outer envelope rejects duplicate, unknown, noncanonical and oversized data', () => {
  const f = fixture(), outer = JSON.parse(f.bytes);
  for (const bad of [Buffer.concat([f.bytes, Buffer.from('\n')]), Buffer.from(f.bytes.toString().replace('{', '{"version":1,')), Buffer.from(canonical({ ...outer, newField: true })), Buffer.alloc(MAX_PACKAGE + 1)]) assert.throws(() => decryptPackage(bad, f.rawPrivate));
  outer.nonce = outer.nonce.replace(/=$/, ''); assert.throws(() => decryptPackage(Buffer.from(canonical({ ...outer, nonce: 'not-base64' })), f.rawPrivate));
});
test('strict JSON rejects duplicate escaped keys, malformed strings, prototype tricks, unsafe numbers and excess depth', () => {
  for (const raw of ['{"a":1,"\\u0061":2}', '{"a":"\\q"}', '[1e999]', '[9007199254740992]', '[NaN]', '[01]', '{"x":1,}', '['.repeat(34) + '0' + ']'.repeat(34), '\ufeff{}']) assert.throws(() => parseJson(Buffer.from(raw), 1024));
  const value = parseJson(Buffer.from('{"__proto__":{"polluted":true}}'), 1024);
  assert.equal(Object.getPrototypeOf(value), null); assert.equal({}.polluted, undefined);
});
test('signed inner payload rejects duplicate fields and bad roots; large base64 is bounded without recursion failure', () => {
  for (const raw of ['{"x":1,"x":2}', '[]', '{"x":1e999}']) {
    const f = fixture(undefined, { payloadText: raw }); assert.throws(() => decryptPackage(f.bytes, f.rawPrivate));
  }
  const content = Buffer.alloc(MAX_PAYLOAD, 65), encoded = content.toString('base64');
  assert.equal(b64(encoded, MAX_PAYLOAD).length, content.length);
  assert.throws(() => b64(encoded + 'AAAA', MAX_PAYLOAD));
});
