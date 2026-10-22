"""Verify a signed report without importing or running the overlay application.

Exit 0: signature valid and matches the separately trusted fingerprint.
Exit 1: malformed or modified report. Exit 2: signature valid, signer untrusted.
Exit 3: file or dependency error. A signature proves neither gameplay nor rules compliance.
"""
import argparse
import base64
import binascii
from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
import re
import sys


DOMAIN = b'TarnishedLineup report v1\0'
BEGIN = b'\n----- BEGIN TARNISHED LINEUP SIGNATURE -----\n'
END = b'\n----- END TARNISHED LINEUP SIGNATURE -----\n'
BEGIN_LINE = BEGIN.strip(b'\n')
END_LINE = END.strip(b'\n')
MAX_REPORT_BYTES = 32 * 1024 * 1024
FIELDS = frozenset(('schemaVersion', 'algorithm', 'publicKey', 'fingerprint', 'payloadSha256', 'signature'))
HEX = re.compile(r'[0-9a-f]{64}\Z')


class ReportVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class VerificationResult:
    fingerprint: str
    payload_sha256: str
    trusted: bool

    @property
    def exit_code(self):
        return 0 if self.trusted else 2


def normalized_fingerprint(value):
    if not isinstance(value, str) or not HEX.fullmatch(value.strip().lower()):
        raise ValueError('A trusted fingerprint must contain exactly 64 hexadecimal characters.')
    return value.strip().lower()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReportVerificationError('Duplicate signature-envelope fields are not allowed.')
        result[key] = value
    return result


def _decode_base64(value, length, label):
    if not isinstance(value, str) or len(value) > 128:
        raise ReportVerificationError(f'Invalid {label} encoding.')
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ReportVerificationError(f'Invalid {label} encoding.') from error
    if len(decoded) != length or base64.b64encode(decoded).decode('ascii') != value:
        raise ReportVerificationError(f'Invalid {label} length or noncanonical encoding.')
    return decoded


def verify_bytes(data, trusted_fingerprint=None):
    """Verify exact signed bytes; trust requires a fingerprint obtained separately."""
    # Imported here so the CLI can explain a missing optional verifier dependency.
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    pin = normalized_fingerprint(trusted_fingerprint) if trusted_fingerprint is not None else None
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_REPORT_BYTES:
        raise ReportVerificationError('Report is empty or exceeds the 32 MiB verification limit.')
    if data.count(BEGIN_LINE) != 1 or data.count(END_LINE) != 1 or data.count(BEGIN) != 1 or not data.endswith(END):
        raise ReportVerificationError('Missing, duplicated, malformed, or misplaced signature footer.')
    payload, envelope = data.split(BEGIN, 1)
    if not payload.endswith(b'\n'):
        raise ReportVerificationError('The signed report payload must end with LF.')
    envelope = envelope[:-len(END)]
    if not 0 < len(envelope) <= 4096 or b'\n' in envelope or b'\r' in envelope:
        raise ReportVerificationError('Signature envelope must be one bounded JSON line.')
    try:
        payload.decode('utf-8', errors='strict')
        metadata = json.loads(envelope.decode('utf-8', errors='strict'), object_pairs_hook=_unique_object)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ReportVerificationError('Invalid UTF-8 report or signature JSON.') from error
    if not isinstance(metadata, dict) or set(metadata) != FIELDS:
        raise ReportVerificationError('Unexpected or missing signature-envelope fields.')
    if type(metadata['schemaVersion']) is not int or metadata['schemaVersion'] != 1 or metadata['algorithm'] != 'Ed25519':
        raise ReportVerificationError('Unsupported report signature version or algorithm.')
    for field in ('fingerprint', 'payloadSha256'):
        if not isinstance(metadata[field], str) or not HEX.fullmatch(metadata[field]):
            raise ReportVerificationError(f'Invalid {field}.')
    public_key = _decode_base64(metadata['publicKey'], 32, 'public key')
    signature = _decode_base64(metadata['signature'], 64, 'signature')
    fingerprint = hashlib.sha256(public_key).hexdigest()
    payload_hash = hashlib.sha256(payload).hexdigest()
    if not hmac.compare_digest(fingerprint, metadata['fingerprint']):
        raise ReportVerificationError('Embedded public-key fingerprint does not match its key.')
    if not hmac.compare_digest(payload_hash, metadata['payloadSha256']):
        raise ReportVerificationError('Report content hash does not match the signed export.')
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, DOMAIN + payload)
    except (InvalidSignature, ValueError) as error:
        raise ReportVerificationError('Report signature is invalid; its content or signature was changed.') from error
    return VerificationResult(fingerprint, payload_hash,
                              pin is not None and hmac.compare_digest(pin, fingerprint))


def verify_file(path, trusted_fingerprint=None):
    with Path(path).open('rb') as report:
        data = report.read(MAX_REPORT_BYTES + 1)
    return verify_bytes(data, trusted_fingerprint)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Verify exact bytes of a signed Tarnished Lineup report.')
    parser.add_argument('report', type=Path, help='Signed UTF-8 .txt report')
    parser.add_argument('--trusted-fingerprint', type=normalized_fingerprint,
        help='SHA-256 public-key fingerprint obtained separately before trusting the report')
    args = parser.parse_args(argv)
    try:
        result = verify_file(args.report, args.trusted_fingerprint)
    except ReportVerificationError as error:
        print(f'INVALID REPORT: {error}', file=sys.stderr)
        return 1
    except OSError as error:
        print(f'COULD NOT READ REPORT: {error}', file=sys.stderr)
        return 3
    except ImportError:
        print('VERIFIER DEPENDENCY MISSING: install cryptography==50.0.2 or source/requirements.txt.', file=sys.stderr)
        return 3
    if result.trusted:
        print('SIGNATURE VALID; TRUSTED FINGERPRINT MATCHED. Report bytes are unchanged.')
    elif args.trusted_fingerprint:
        print('SIGNATURE VALID; SIGNER UNTRUSTED. The key does not match the supplied trusted fingerprint.')
    else:
        print('SIGNATURE VALID; SIGNER UNTRUSTED. No independently trusted fingerprint was supplied.')
    print(f'Public-key fingerprint: {result.fingerprint}')
    print(f'Signed payload SHA-256: {result.payload_sha256}')
    print('This checks report integrity and the pinned key, not gameplay, identity, or leaderboard eligibility.')
    return result.exit_code


if __name__ == '__main__':
    raise SystemExit(main())
