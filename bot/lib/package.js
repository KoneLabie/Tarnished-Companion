'use strict';
const crypto = require('node:crypto');
const { parseJson, FormatError, exactFields, canonical, object } = require('./strict-json');
const MAX_PACKAGE = 8 * 1024 * 1024, MAX_SIGNED = 5 * 1024 * 1024, MAX_PAYLOAD = 3 * 1024 * 1024;
const HEX = /^[0-9a-f]{64}$/;
const BEGIN = Buffer.from('\n----- BEGIN TARNISHED LINEUP SIGNATURE -----\n');
const END = Buffer.from('\n----- END TARNISHED LINEUP SIGNATURE -----\n');
const DOMAIN = Buffer.from('TarnishedLineup report v1\0');
const KDF_DOMAIN = Buffer.from('TarnishedLineup tlrun v1\0');
const HEADER = ['format', 'version', 'algorithm', 'recipientKeyId', 'ephemeralPublicKey', 'nonce'];
class PackageError extends Error { constructor(code, message) { super(message); this.name = 'PackageError'; this.code = code; } }
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
function fingerprint(value) {
  if (typeof value !== 'string' || !HEX.test(value.trim().toLowerCase())) throw new PackageError('KEY', 'Fingerprint must contain exactly 64 hexadecimal characters.');
  return value.trim().toLowerCase();
}
function b64(value, maximum, exact) {
  if (typeof value !== 'string' || value.length > 4 * Math.ceil(maximum / 3) || !/^[A-Za-z0-9+/]*={0,2}$/.test(value)) throw new FormatError('Invalid Base64 encoding.');
  const bytes = Buffer.from(value, 'base64');
  if (bytes.length > maximum || (exact !== undefined && bytes.length !== exact) || bytes.toString('base64') !== value) throw new FormatError('Invalid length or noncanonical Base64.');
  return bytes;
}
function publicKey(raw, type = 'x25519') {
  const prefix = type === 'x25519' ? '302a300506032b656e032100' : '302a300506032b6570032100';
  return crypto.createPublicKey({ key: Buffer.concat([Buffer.from(prefix, 'hex'), raw]), format: 'der', type: 'spki' });
}
function privateKey(raw) {
  if (!Buffer.isBuffer(raw) || raw.length !== 32) throw new PackageError('KEY', 'Recipient private key must be raw 32-byte X25519 key material.');
  return crypto.createPrivateKey({ key: Buffer.concat([Buffer.from('302e020100300506032b656e04220420', 'hex'), raw]), format: 'der', type: 'pkcs8' });
}
function rawPublic(key) { return crypto.createPublicKey(key).export({ format: 'der', type: 'spki' }).subarray(-32); }
function once(bytes, token) { const i = bytes.indexOf(token); return i >= 0 && bytes.indexOf(token, i + token.length) === -1; }
function verifySigned(bytes, pin) {
  if (!Buffer.isBuffer(bytes) || bytes.length > MAX_SIGNED || !once(bytes, BEGIN) || !once(bytes, BEGIN.subarray(1, -1)) || !once(bytes, END.subarray(1, -1)) || !bytes.subarray(-END.length).equals(END)) throw new PackageError('SIGNATURE', 'Missing, duplicated, or misplaced report signature.');
  const boundary = bytes.indexOf(BEGIN), payload = bytes.subarray(0, boundary);
  const footerBytes = bytes.subarray(boundary + BEGIN.length, -END.length);
  if (payload.at(-1) !== 10 || footerBytes.includes(10) || footerBytes.includes(13)) throw new PackageError('SIGNATURE', 'Report signature framing is invalid.');
  try { new TextDecoder('utf-8', { fatal: true }).decode(payload); } catch { throw new PackageError('SIGNATURE', 'Signed payload is not UTF-8.'); }
  const footer = parseJson(footerBytes, 4096, 'Signature footer');
  if (!exactFields(footer, ['schemaVersion', 'algorithm', 'publicKey', 'fingerprint', 'payloadSha256', 'signature']) || footer.schemaVersion !== 1 || footer.algorithm !== 'Ed25519' || !HEX.test(footer.fingerprint) || !HEX.test(footer.payloadSha256)) throw new PackageError('SIGNATURE', 'Unsupported report signature fields.');
  const pub = b64(footer.publicKey, 32, 32), signature = b64(footer.signature, 64, 64);
  if (hash(pub) !== footer.fingerprint || hash(payload) !== footer.payloadSha256 || !crypto.verify(null, Buffer.concat([DOMAIN, payload]), publicKey(pub, 'ed25519'), signature)) throw new PackageError('SIGNATURE', 'Report signature is invalid or the report was changed.');
  const trusted = pin !== undefined && fingerprint(pin) === footer.fingerprint;
  if (pin !== undefined && !trusted) throw new PackageError('UNTRUSTED', 'Valid signature, but signer does not match the independently trusted fingerprint.');
  return { payload, fingerprint: footer.fingerprint, trusted };
}
function decryptPackage(bytes, rawPrivate, pin) {
  const envelope = parseJson(bytes, MAX_PACKAGE, 'Run package');
  if (!exactFields(envelope, [...HEADER, 'ciphertext']) || envelope.format !== 'TarnishedLineupRun' || envelope.version !== 1 || envelope.algorithm !== 'X25519-HKDF-SHA256-AES-256-GCM' || !HEX.test(envelope.recipientKeyId) || canonical(envelope) !== bytes.toString('utf8')) throw new FormatError('Unsupported or noncanonical encrypted package.');
  const ephemeral = b64(envelope.ephemeralPublicKey, 32, 32), nonce = b64(envelope.nonce, 12, 12);
  const encrypted = b64(envelope.ciphertext, MAX_SIGNED + 16);
  if (encrypted.length < 17) throw new FormatError('Encrypted content or GCM tag is missing.');
  const key = privateKey(rawPrivate), recipient = rawPublic(key), recipientFingerprint = hash(recipient);
  if (recipientFingerprint !== envelope.recipientKeyId) throw new PackageError('RECIPIENT', 'This report was encrypted to a different recipient key.');
  const header = Object.fromEntries(HEADER.map(name => [name, envelope[name]]));
  const aad = Buffer.from(canonical(header));
  let signed;
  try {
    const shared = crypto.diffieHellman({ privateKey: key, publicKey: publicKey(ephemeral) });
    const derived = Buffer.from(crypto.hkdfSync('sha256', shared, Buffer.from(hash(aad), 'hex'), Buffer.concat([KDF_DOMAIN, recipient, ephemeral]), 32));
    const decipher = crypto.createDecipheriv('aes-256-gcm', derived, nonce);
    decipher.setAAD(aad); decipher.setAuthTag(encrypted.subarray(-16));
    signed = Buffer.concat([decipher.update(encrypted.subarray(0, -16)), decipher.final()]);
    derived.fill(0); shared.fill(0);
  } catch { throw new PackageError('DECRYPTION', 'Encrypted report authentication failed; its data or header may have changed.'); }
  const verified = verifySigned(signed, pin), innerBytes = verified.payload.subarray(0, -1);
  const wrapper = parseJson(innerBytes, MAX_SIGNED, 'Signed wrapper');
  if (!exactFields(wrapper, ['format', 'version', 'encoding', 'payload']) || wrapper.format !== 'TarnishedLineupRunPayload' || wrapper.version !== 1 || wrapper.encoding !== 'base64-canonical-json' || canonical(wrapper) !== innerBytes.toString('utf8')) throw new FormatError('Unsupported signed payload wrapper.');
  const payloadBytes = b64(wrapper.payload, MAX_PAYLOAD);
  // Preserve Python's exact signed numeric spelling (1.0, scientific notation).
  // Re-serializing in JS would change its hash. Strict parsing still rejects
  // duplicate fields, unsafe numbers, excess depth, and trailing content.
  const payload = parseJson(payloadBytes, MAX_PAYLOAD, 'Run payload');
  if (!object(payload)) throw new FormatError('Run payload must be an object.');
  return { payload, signingFingerprint: verified.fingerprint, recipientFingerprint, payloadSha256: hash(payloadBytes), trusted: verified.trusted };
}
function generateRecipient() {
  const pair = crypto.generateKeyPairSync('x25519');
  const raw = pair.privateKey.export({ format: 'der', type: 'pkcs8' }).subarray(-32), pub = rawPublic(pair.privateKey);
  return { schemaVersion: 1, algorithm: 'X25519', privateKey: raw.toString('base64'), publicKey: pub.toString('base64'), fingerprint: hash(pub) };
}
function validateRecipient(config) {
  if (!exactFields(config, ['schemaVersion', 'algorithm', 'privateKey', 'publicKey', 'fingerprint']) || config.schemaVersion !== 1 || config.algorithm !== 'X25519') throw new PackageError('KEY', 'Recipient key file has an unsupported format.');
  const raw = b64(config.privateKey, 32, 32), pub = b64(config.publicKey, 32, 32);
  if (!rawPublic(privateKey(raw)).equals(pub) || hash(pub) !== config.fingerprint) throw new PackageError('KEY', 'Recipient private key, public key, and fingerprint do not match.');
  return raw;
}
module.exports = { decryptPackage, verifySigned, generateRecipient, validateRecipient, fingerprint, hash, b64, PackageError, MAX_PACKAGE, MAX_SIGNED, MAX_PAYLOAD };
