"""Independent Ed25519 fixtures test trust pinning and exact-byte verification."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verify_report import (BEGIN, END, DOMAIN, ReportVerificationError,
                           normalized_fingerprint, verify_bytes, verify_file)


class VerifyReportTests(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes_raw()
        self.fingerprint = hashlib.sha256(self.public).hexdigest()
        self.payload = 'TARNISHED COMPANION\nCharacter: Tarnished é\nTime: 00:01:23.456\n'.encode('utf-8')
        self.metadata = dict(schemaVersion=1, algorithm='Ed25519',
            publicKey=base64.b64encode(self.public).decode('ascii'), fingerprint=self.fingerprint,
            payloadSha256=hashlib.sha256(self.payload).hexdigest(),
            signature=base64.b64encode(self.key.sign(DOMAIN + self.payload)).decode('ascii'))
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'report.txt'

    def report(self, metadata=None, payload=None):
        return ((self.payload if payload is None else payload) + BEGIN
            + json.dumps(self.metadata if metadata is None else metadata,
                         sort_keys=True, separators=(',', ':')).encode('utf-8') + END)

    def assert_invalid(self, data):
        with self.assertRaises(ReportVerificationError):
            verify_bytes(data, self.fingerprint)

    def test_valid_signature_requires_independently_pinned_key_for_success(self):
        untrusted = verify_bytes(self.report())
        self.assertFalse(untrusted.trusted)
        self.assertEqual(untrusted.exit_code, 2)
        trusted = verify_bytes(self.report(), self.fingerprint.upper())
        self.assertTrue(trusted.trusted)
        self.assertEqual(trusted.exit_code, 0)
        self.assertEqual(trusted.payload_sha256, hashlib.sha256(self.payload).hexdigest())

    def test_wrong_trusted_fingerprint_does_not_accept_embedded_key(self):
        result = verify_bytes(self.report(), '0' * 64)
        self.assertFalse(result.trusted)
        self.assertEqual(result.exit_code, 2)

    def test_payload_modification_and_line_ending_conversion_are_detected(self):
        self.assert_invalid(self.report().replace(b'00:01:23.456', b'00:00:01.000'))
        self.assert_invalid(self.report().replace(b'\n', b'\r\n'))
        self.assert_invalid(self.report(payload=self.payload + b'Extra result\n'))

    def test_replacing_hash_after_modification_cannot_forge_signature(self):
        tampered = self.payload.replace(b'00:01:23.456', b'00:00:01.000')
        metadata = dict(self.metadata, payloadSha256=hashlib.sha256(tampered).hexdigest())
        self.assert_invalid(self.report(metadata, tampered))

    def test_signature_bit_change_is_detected(self):
        signature = bytearray(base64.b64decode(self.metadata['signature']))
        signature[0] ^= 1
        self.assert_invalid(self.report(dict(self.metadata, signature=base64.b64encode(signature).decode('ascii'))))

    def test_new_self_signed_key_cannot_impersonate_pinned_key(self):
        other = Ed25519PrivateKey.generate()
        public = other.public_key().public_bytes_raw()
        metadata = dict(self.metadata, publicKey=base64.b64encode(public).decode('ascii'),
            fingerprint=hashlib.sha256(public).hexdigest(),
            signature=base64.b64encode(other.sign(DOMAIN + self.payload)).decode('ascii'))
        self.assertFalse(verify_bytes(self.report(metadata), self.fingerprint).trusted)

    def test_domain_separation_rejects_signature_over_raw_payload(self):
        signature = base64.b64encode(self.key.sign(self.payload)).decode('ascii')
        self.assert_invalid(self.report(dict(self.metadata, signature=signature)))

    def test_duplicate_or_unknown_fields_are_rejected(self):
        metadata = dict(self.metadata, trusted=True)
        self.assert_invalid(self.report(metadata))
        envelope = json.dumps(self.metadata, separators=(',', ':')).encode('utf-8')
        envelope = envelope[:-1] + b',"algorithm":"Ed25519"}'
        self.assert_invalid(self.payload + BEGIN + envelope + END)

    def test_unsupported_algorithm_versions_and_types_are_rejected(self):
        for change in [dict(schemaVersion=True), dict(schemaVersion=2), dict(algorithm='none'),
                       dict(algorithm={}), dict(fingerprint=[]), dict(payloadSha256='A' * 64)]:
            with self.subTest(change=change):
                self.assert_invalid(self.report(dict(self.metadata, **change)))

    def test_invalid_base64_lengths_and_noncanonical_padding_are_rejected(self):
        for field, value in [('signature', '!'), ('publicKey', 'AA=='),
                             ('signature', self.metadata['signature'] + '='),
                             ('publicKey', self.metadata['publicKey'] + '\n')]:
            with self.subTest(field=field, value=value):
                self.assert_invalid(self.report(dict(self.metadata, **{field: value})))

    def test_fingerprint_and_hash_must_match_payload_and_key(self):
        self.assert_invalid(self.report(dict(self.metadata, fingerprint='0' * 64)))
        self.assert_invalid(self.report(dict(self.metadata, payloadSha256='0' * 64)))

    def test_duplicate_markers_trailing_text_and_unsigned_reports_are_rejected(self):
        for data in [self.payload, self.report() + b'Unsigned afterword\n',
                     self.report() + END, self.report() + BEGIN,
                     BEGIN + self.report(), self.report().rstrip(b'\n')]:
            with self.subTest(data=data[-80:]):
                self.assert_invalid(data)

    def test_utf8_payload_required_even_with_valid_signature(self):
        payload = b'Invalid: \xff\n'
        metadata = dict(self.metadata, payloadSha256=hashlib.sha256(payload).hexdigest(),
            signature=base64.b64encode(self.key.sign(DOMAIN + payload)).decode('ascii'))
        self.assert_invalid(self.report(metadata, payload))

    def test_envelope_must_be_bounded_single_line_json(self):
        self.assert_invalid(self.payload + BEGIN + b'{}\n{}' + END)
        self.assert_invalid(self.payload + BEGIN + b' ' * 4097 + END)
        self.assert_invalid(self.payload + BEGIN + b'not json' + END)
        self.assert_invalid(self.payload + BEGIN + b'[]' + END)

    def test_file_read_preserves_exact_bytes(self):
        self.path.write_bytes(self.report())
        self.assertTrue(verify_file(self.path, self.fingerprint).trusted)

    def test_cli_exit_status_and_messages_distinguish_integrity_and_trust(self):
        script = str(Path(__file__).resolve().parents[1] / 'verify_report.py')
        self.path.write_bytes(self.report())
        for args, expected in [([], 2), (['--trusted-fingerprint', self.fingerprint], 0),
                               (['--trusted-fingerprint', '0' * 64], 2)]:
            with self.subTest(args=args):
                completed = subprocess.run([sys.executable, script, str(self.path)] + args,
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(completed.returncode, expected, completed.stderr)
                self.assertIn('SIGNATURE VALID', completed.stdout)
                self.assertIn('not gameplay', completed.stdout)
        self.path.write_bytes(self.report().replace(b'TARNISHED COMPANION', b'CHANGED REPORT!!', 1))
        completed = subprocess.run([sys.executable, script, str(self.path)], capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 1)
        self.assertIn('INVALID REPORT', completed.stderr)
        missing = subprocess.run([sys.executable, script, str(self.path.with_name('missing.txt'))],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(missing.returncode, 3)

    def test_trusted_fingerprint_is_strictly_validated(self):
        self.assertEqual(normalized_fingerprint('  ' + self.fingerprint.upper() + '  '), self.fingerprint)
        for value in [None, True, '', 'g' * 64, '0' * 63, '0' * 65, '00:' * 32]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalized_fingerprint(value)


if __name__ == '__main__':
    unittest.main()
