'use strict';
const crypto = require('node:crypto');
const { canonical } = require('../lib/strict-json');
const { generateRecipient, hash } = require('../lib/package');
function validPayload() {
  return {
    schemaVersion: 1, format: 'tarnished-run', simulation: false,
    run: { schemaVersion: 1, recordId: 'a'.repeat(32), contextKey: 'save:0:journey:1', character: 'Test Tarnished', journey: 1,
      category: 'Any% Glitchless', startedAt: '2026-10-22T10:00:00.000+00:00', endedAt: '2026-10-22T11:00:00.000+00:00',
      status: 'finished', elapsedSeconds: 1234.5, realTimeSeconds: 1300, igtSeconds: 1250, deaths: 2,
      partial: false, attributionLost: false, continuityUnverified: false,
      runPolicy: { eligible: true, status: 'candidate', categoryId: 'any-glitchless', categoryName: 'Any% Glitchless', startEvidence: ['Fresh character witnessed'], reason: 'Observed start', rulesUrl: 'https://www.speedrun.com/eldenring' },
      localAuditStatus: 'no-issues-observed', localAuditReasons: [],
      splits: [{ bossId: 10000800, name: 'Margit', elapsedSeconds: 900, igtSeconds: 901, source: 'save flag observed; not an official split' }],
    },
    attempts: { contextKey: 'save:0:journey:1', character: 'Test Tarnished', journey: 1, records: [
      { recordId: 'b'.repeat(16), contextKey: 'save:0:journey:1', categoryId: 'any-glitchless', name: 'Margit', bossId: 10000800, attemptNumber: 1, startedAt: '2026-10-22T10:02:00.000+00:00', endedAt: '2026-10-22T10:05:00.000+00:00', outcome: 'victory', elapsedSeconds: 180.0 },
    ] },
    build: { status: 'unavailable', source: 'checksum-validated-save', notice: 'Build not available', initial: null, final: null, observations: [], truncated: false },
    application: { kind: 'source', sha256: 'c'.repeat(64) }, exportedAt: '2026-10-22T11:00:02.000+00:00', reportText: 'Human report — Malenia',
  };
}
function fixture(payload = validPayload(), options = {}) {
  const recipient = generateRecipient(), privateRaw = Buffer.from(recipient.privateKey, 'base64');
  const recipientPublic = Buffer.from(recipient.publicKey, 'base64');
  const signing = crypto.generateKeyPairSync('ed25519'), signingRaw = signing.publicKey.export({ format: 'der', type: 'spki' }).subarray(-32);
  const payloadBytes = Buffer.from(options.payloadText || canonical(payload));
  const inner = Buffer.from(canonical({ format: 'TarnishedLineupRunPayload', version: 1, encoding: 'base64-canonical-json', payload: payloadBytes.toString('base64') }) + '\n');
  const footer = { schemaVersion: 1, algorithm: 'Ed25519', publicKey: signingRaw.toString('base64'), fingerprint: hash(signingRaw), payloadSha256: hash(inner), signature: crypto.sign(null, Buffer.concat([Buffer.from('TarnishedLineup report v1\0'), inner]), signing.privateKey).toString('base64') };
  if (options.badSignature) footer.signature = Buffer.alloc(64).toString('base64');
  let signed = Buffer.concat([inner, Buffer.from('\n----- BEGIN TARNISHED LINEUP SIGNATURE -----\n' + canonical(footer) + '\n----- END TARNISHED LINEUP SIGNATURE -----\n')]);
  if (options.signedTransform) signed = options.signedTransform(signed);
  const ep = crypto.generateKeyPairSync('x25519'), ephemeralRaw = ep.publicKey.export({ format: 'der', type: 'spki' }).subarray(-32), nonce = crypto.randomBytes(12);
  const header = { format: 'TarnishedLineupRun', version: 1, algorithm: 'X25519-HKDF-SHA256-AES-256-GCM', recipientKeyId: recipient.fingerprint, ephemeralPublicKey: ephemeralRaw.toString('base64'), nonce: nonce.toString('base64') };
  const aad = Buffer.from(canonical(header)), pub = crypto.createPublicKey({ key: Buffer.concat([Buffer.from('302a300506032b656e032100', 'hex'), recipientPublic]), format: 'der', type: 'spki' });
  const shared = crypto.diffieHellman({ privateKey: ep.privateKey, publicKey: pub });
  const key = Buffer.from(crypto.hkdfSync('sha256', shared, Buffer.from(hash(aad), 'hex'), Buffer.concat([Buffer.from('TarnishedLineup tlrun v1\0'), recipientPublic, ephemeralRaw]), 32));
  const cipher = crypto.createCipheriv('aes-256-gcm', key, nonce); cipher.setAAD(aad);
  const ciphertext = Buffer.concat([cipher.update(signed), cipher.final(), cipher.getAuthTag()]);
  return { bytes: Buffer.from(canonical({ ...header, ciphertext: ciphertext.toString('base64') })), rawPrivate: privateRaw, fingerprint: footer.fingerprint, payload, recipient, payloadSha256: hash(payloadBytes) };
}
module.exports = { fixture, validPayload };
