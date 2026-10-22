"""Version 1 .tlrun: signed structured data encrypted to a recipient public key.

The client needs only the recipient's raw X25519 public key. Keep the matching
private key with the verifier/bot; this module never supplies or persists one.
A trusted signer fingerprint must be obtained independently. Encryption and
signatures do not certify gameplay, identity, freshness, or leaderboard rules.

Wire format: bounded canonical UTF-8 JSON, no archive or compression. All outer
header fields are AES-GCM AAD. The plaintext is an existing Ed25519 signed TXT
document containing a versioned, base64-encoded canonical JSON payload. This
allows the payload to include another signed TXT without footer ambiguity.
"""
import base64
import binascii
from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import os
import re

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from verify_report import BEGIN, ReportVerificationError, normalized_fingerprint, verify_bytes


FORMAT = 'TarnishedLineupRun'
PAYLOAD_FORMAT = 'TarnishedLineupRunPayload'
ALGORITHM = 'X25519-HKDF-SHA256-AES-256-GCM'
KDF_DOMAIN = b'TarnishedLineup tlrun v1\0'
MAX_PAYLOAD_BYTES = 3 * 1024 * 1024
MAX_SIGNED_BYTES = 5 * 1024 * 1024
MAX_PACKAGE_BYTES = 8 * 1024 * 1024
MAX_DEPTH = 32
MAX_NODES = 200000
MAX_SAFE_INTEGER = (1 << 53) - 1
HEADER_FIELDS = frozenset(('format', 'version', 'algorithm', 'recipientKeyId', 'ephemeralPublicKey', 'nonce'))
OUTER_FIELDS = HEADER_FIELDS | {'ciphertext'}
INNER_FIELDS = frozenset(('format', 'version', 'encoding', 'payload'))
HEX = re.compile(r'[0-9a-f]{64}\Z')


class RunPackageError(ValueError):
    pass


class PackageFormatError(RunPackageError):
    pass


class RecipientKeyError(RunPackageError):
    pass


class RecipientMismatchError(RecipientKeyError):
    pass


class PackageDecryptionError(RunPackageError):
    pass


class PackageSignatureError(RunPackageError):
    pass


class UntrustedSignerError(PackageSignatureError):
    def __init__(self, fingerprint):
        self.fingerprint = fingerprint
        super().__init__('The package signature is valid, but its signer does not match the trusted fingerprint.')


@dataclass(frozen=True)
class DecryptedPackage:
    payload: dict
    signing_fingerprint: str
    recipient_fingerprint: str
    payload_sha256: str
    trusted: bool

    @property
    def exit_code(self):
        return 0 if self.trusted else 2


def _validate_json(value):
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            raise PackageFormatError('The structured payload exceeds its nesting or item limit.')
        if item is None or type(item) is bool or type(item) is str:
            continue
        if type(item) is int:
            if abs(item) > MAX_SAFE_INTEGER:
                raise PackageFormatError('Payload integers must fit the interoperable 53-bit range.')
            continue
        if type(item) is float:
            if not math.isfinite(item) or abs(item) > MAX_SAFE_INTEGER:
                raise PackageFormatError('Payload numbers must be finite and within the supported range.')
            continue
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise PackageFormatError('Payload object keys must be strings.')
            pending.extend((entry, depth+1) for entry in item.values())
        elif type(item) is list:
            pending.extend((entry, depth+1) for entry in item)
        else:
            raise PackageFormatError('The payload contains a value that is not a JSON type.')


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                          allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, RecursionError) as error:
        raise PackageFormatError('The payload cannot be encoded as canonical UTF-8 JSON.') from error


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PackageFormatError('Duplicate JSON fields are not allowed.')
        result[key] = value
    return result


def _no_constant(value):
    raise PackageFormatError('Non-finite JSON numbers are not allowed.')


def _load(data, maximum, label):
    if type(data) is not bytes or not 0 < len(data) <= maximum:
        raise PackageFormatError(f'{label} is empty or exceeds its size limit.')
    try:
        value = json.loads(data.decode('utf-8', errors='strict'),
                           object_pairs_hook=_unique, parse_constant=_no_constant)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise PackageFormatError(f'{label} is not valid bounded UTF-8 JSON.') from error
    _validate_json(value)
    if _canonical(value) != data:
        raise PackageFormatError(f'{label} must use canonical JSON without trailing data.')
    return value


def _b64(value):
    return base64.b64encode(value).decode('ascii')


def _decode(value, maximum, label, exact=None):
    if not isinstance(value, str) or len(value) > 4*((maximum+2)//3):
        raise PackageFormatError(f'Invalid or oversized {label} encoding.')
    try:
        result = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise PackageFormatError(f'Invalid {label} encoding.') from error
    if len(result) > maximum or exact is not None and len(result) != exact or _b64(result) != value:
        raise PackageFormatError(f'Invalid {label} length or noncanonical Base64 encoding.')
    return result


def _public_key(value):
    if type(value) is not bytes or len(value) != 32:
        raise RecipientKeyError('Configure a recipient raw 32-byte X25519 public key. Unencrypted export is not supported.')
    return X25519PublicKey.from_public_bytes(value)


def recipient_key_id(public_key):
    _public_key(public_key)
    return hashlib.sha256(public_key).hexdigest()


def generate_recipient_keypair():
    """Generate verifier-side provisioning material; never bundle privateKey."""
    private = X25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    return dict(privateKey=private.private_bytes_raw(), publicKey=public,
                fingerprint=recipient_key_id(public))


def _derive(shared, aad, recipient_public, ephemeral_public):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=hashlib.sha256(aad).digest(),
                info=KDF_DOMAIN+recipient_public+ephemeral_public).derive(shared)


def create_package(payload, signer, recipient_public_key):
    """Sign all structured fields, then encrypt; a recipient is always required.

    signer must behave like LocalIntegrity.sign_report and sign the exact text
    supplied. The result is verified before encryption, so a faulty signer
    cannot silently substitute a different structured payload.
    """
    recipient = _public_key(recipient_public_key)
    if type(payload) is not dict:
        raise PackageFormatError('A structured run payload must be a JSON object.')
    if not callable(signer):
        raise PackageSignatureError('A report-signing callback is required.')
    _validate_json(payload)
    encoded = _canonical(payload)
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise PackageFormatError('The structured run payload exceeds the 3 MiB limit.')
    ephemeral = X25519PrivateKey.generate()
    ephemeral_public = ephemeral.public_key().public_bytes_raw()
    try:
        shared = ephemeral.exchange(recipient)
    except ValueError as error:
        raise RecipientKeyError('The recipient public key is not a usable X25519 key.') from error
    inner = _canonical(dict(format=PAYLOAD_FORMAT, version=1, encoding='base64-canonical-json', payload=_b64(encoded)))
    try:
        signed_text = signer(inner.decode('utf-8'))
        if type(signed_text) is not str:
            raise PackageSignatureError('The signer did not return a signed text report.')
        signed = signed_text.encode('utf-8')
        if len(signed) > MAX_SIGNED_BYTES:
            raise PackageSignatureError('The signed structured payload exceeds the 5 MiB limit.')
        verify_bytes(signed)
        if signed.split(BEGIN, 1)[0] != inner+b'\n':
            raise PackageSignatureError('The signer changed the structured payload.')
    except (ValueError, UnicodeError, ReportVerificationError) as error:
        if isinstance(error, PackageSignatureError):
            raise
        raise PackageSignatureError('The structured payload could not be signed and verified.') from error
    header = dict(format=FORMAT, version=1, algorithm=ALGORITHM,
                  recipientKeyId=recipient_key_id(recipient_public_key),
                  ephemeralPublicKey=_b64(ephemeral_public), nonce=_b64(os.urandom(12)))
    aad = _canonical(header)
    key = _derive(shared, aad, recipient_public_key, ephemeral_public)
    ciphertext = AESGCM(key).encrypt(base64.b64decode(header['nonce']), signed, aad)
    package = _canonical(dict(header, ciphertext=_b64(ciphertext)))
    if len(package) > MAX_PACKAGE_BYTES:
        raise PackageFormatError('The encrypted package exceeds the 8 MiB limit.')
    return package


def decrypt_package(data, recipient_private_key, trusted_fingerprint=None):
    """Authenticate, decrypt and verify; unpinned valid signatures stay untrusted.

    The recipient private key may be raw 32-byte key material or an X25519 key
    object. A supplied but mismatched signer fingerprint raises a distinct
    UntrustedSignerError. No pin returns trusted=False / exit_code=2, never a
    verified identity. Callers must separately enforce run schema and replay IDs.
    """
    try:
        pin = normalized_fingerprint(trusted_fingerprint) if trusted_fingerprint is not None else None
    except ValueError as error:
        raise PackageSignatureError('The trusted signer fingerprint is malformed.') from error
    envelope = _load(data, MAX_PACKAGE_BYTES, 'Run package')
    if (type(envelope) is not dict or set(envelope) != OUTER_FIELDS
            or envelope['format'] != FORMAT or type(envelope['version']) is not int
            or envelope['version'] != 1 or envelope['algorithm'] != ALGORITHM):
        raise PackageFormatError('Unsupported package format, version, algorithm, or fields.')
    if not isinstance(envelope['recipientKeyId'], str) or not HEX.fullmatch(envelope['recipientKeyId']):
        raise PackageFormatError('The recipient key fingerprint is malformed.')
    ephemeral_public = _decode(envelope['ephemeralPublicKey'], 32, 'ephemeral public key', exact=32)
    nonce = _decode(envelope['nonce'], 12, 'nonce', exact=12)
    ciphertext = _decode(envelope['ciphertext'], MAX_SIGNED_BYTES+16, 'ciphertext')
    if len(ciphertext) < 17:
        raise PackageFormatError('The encrypted payload is missing its content or authentication tag.')
    if isinstance(recipient_private_key, X25519PrivateKey):
        private = recipient_private_key
    elif type(recipient_private_key) is bytes and len(recipient_private_key) == 32:
        private = X25519PrivateKey.from_private_bytes(recipient_private_key)
    else:
        raise RecipientKeyError('A raw 32-byte X25519 recipient private key is required to open this package.')
    recipient_public = private.public_key().public_bytes_raw()
    key_id = recipient_key_id(recipient_public)
    if not hmac.compare_digest(key_id, envelope['recipientKeyId']):
        raise RecipientMismatchError('This package is encrypted to a different recipient key.')
    header = {key: envelope[key] for key in HEADER_FIELDS}
    aad = _canonical(header)
    try:
        shared = private.exchange(X25519PublicKey.from_public_bytes(ephemeral_public))
        key = _derive(shared, aad, recipient_public, ephemeral_public)
        signed = AESGCM(key).decrypt(nonce, ciphertext, aad)
    except (InvalidTag, ValueError) as error:
        raise PackageDecryptionError('Encrypted package authentication failed; its data or header may have changed.') from error
    if not 0 < len(signed) <= MAX_SIGNED_BYTES:
        raise PackageFormatError('The decrypted signed payload exceeds its size limit.')
    try:
        signature = verify_bytes(signed, pin)
    except ReportVerificationError as error:
        raise PackageSignatureError('The encrypted content does not have a valid report signature.') from error
    if pin is not None and not signature.trusted:
        raise UntrustedSignerError(signature.fingerprint)
    inner_bytes = signed.split(BEGIN, 1)[0]
    inner = _load(inner_bytes[:-1], MAX_SIGNED_BYTES, 'Signed payload wrapper')
    if (type(inner) is not dict or set(inner) != INNER_FIELDS or inner['format'] != PAYLOAD_FORMAT
            or type(inner['version']) is not int or inner['version'] != 1
            or inner['encoding'] != 'base64-canonical-json'):
        raise PackageFormatError('Unsupported signed payload wrapper.')
    encoded = _decode(inner['payload'], MAX_PAYLOAD_BYTES, 'structured payload')
    payload = _load(encoded, MAX_PAYLOAD_BYTES, 'Structured payload')
    if type(payload) is not dict:
        raise PackageFormatError('The structured run payload must be a JSON object.')
    return DecryptedPackage(payload, signature.fingerprint, key_id,
                            hashlib.sha256(encoded).hexdigest(), signature.trusted)
