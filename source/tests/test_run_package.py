"""Encrypted run packages: independent crypto fixtures, trust and hostile inputs."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from record_integrity import LocalIntegrity
from test_record_integrity import TestProtector
from run_package import (create_package, decrypt_package, generate_recipient_keypair,
    recipient_key_id, PackageFormatError, RecipientKeyError, RecipientMismatchError,
    PackageDecryptionError, PackageSignatureError, UntrustedSignerError)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


class RunPackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.signer = LocalIntegrity(self.directory, TestProtector())
        self.recipient = X25519PrivateKey.generate()
        self.public = self.recipient.public_key().public_bytes_raw()
        self.payload = dict(run=dict(recordId='test-run-1', category='Any% Glitchless', elapsedSeconds=123.5),
                            reportText='Tarnished — Malenia\nTime: 00:02:03.500',
                            attempts=[dict(bossId=15000800, outcome='victory', elapsedSeconds=15.2)])

    def package(self, payload=None):
        return create_package(self.payload if payload is None else payload,
                              self.signer.sign_report, self.public)

    def decrypt(self, package):
        return decrypt_package(package, self.recipient, self.signer.public_fingerprint)

    def encrypted_fixture(self, signed):
        """Independent implementation of the documented v1 crypto envelope."""
        ephemeral = X25519PrivateKey.generate()
        epk = ephemeral.public_key().public_bytes_raw()
        nonce = os.urandom(12)
        header = dict(format='TarnishedLineupRun', version=1,
            algorithm='X25519-HKDF-SHA256-AES-256-GCM', recipientKeyId=hashlib.sha256(self.public).hexdigest(),
            ephemeralPublicKey=base64.b64encode(epk).decode(), nonce=base64.b64encode(nonce).decode())
        aad = canonical(header)
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=hashlib.sha256(aad).digest(),
            info=b'TarnishedLineup tlrun v1\0'+self.public+epk).derive(ephemeral.exchange(self.recipient.public_key()))
        ciphertext = AESGCM(key).encrypt(nonce, signed, aad)
        return canonical(dict(header, ciphertext=base64.b64encode(ciphertext).decode()))

    def test_round_trip_covers_structured_data_and_embedded_signed_text(self):
        self.payload['signedText'] = self.signer.sign_report('Independent human-readable report')
        package = self.package()
        self.assertNotIn(b'Tarnished', package.replace(b'TarnishedLineupRun', b''))
        self.assertNotIn(b'test-run-1', package)
        opened = decrypt_package(package, self.recipient.private_bytes_raw(), self.signer.public_fingerprint.upper())
        self.assertEqual(opened.payload, self.payload)
        self.assertTrue(opened.trusted)
        self.assertEqual(opened.exit_code, 0)
        self.assertEqual(opened.signing_fingerprint, self.signer.public_fingerprint)
        self.assertEqual(opened.recipient_fingerprint, recipient_key_id(self.public))
        self.assertEqual(opened.payload_sha256, hashlib.sha256(canonical(self.payload)).hexdigest())

    def test_valid_unpinned_signer_is_explicitly_untrusted(self):
        opened = decrypt_package(self.package(), self.recipient)
        self.assertFalse(opened.trusted)
        self.assertEqual(opened.exit_code, 2)

    def test_wrong_signer_pin_is_distinct_from_invalid_signature(self):
        with self.assertRaises(UntrustedSignerError) as error:
            decrypt_package(self.package(), self.recipient, '0'*64)
        self.assertEqual(error.exception.fingerprint, self.signer.public_fingerprint)
        with self.assertRaises(PackageSignatureError):
            decrypt_package(self.package(), self.recipient, 'malformed fingerprint')

    def test_missing_recipient_never_falls_back_to_plaintext(self):
        signer = Mock()
        for public in (None, b'', b'0'*31, b'0'*33, 'public key', b'\0'*32):
            with self.subTest(public_length=len(public) if public is not None else None):
                with self.assertRaises(RecipientKeyError):
                    create_package(self.payload, signer, public)
        signer.assert_not_called()

    def test_wrong_recipient_private_key_has_clear_distinct_error(self):
        with self.assertRaises(RecipientMismatchError):
            decrypt_package(self.package(), X25519PrivateKey.generate())
        with self.assertRaises(RecipientKeyError):
            decrypt_package(self.package(), b'not a key')

    def test_random_ephemeral_key_and_nonce_make_repeated_exports_different(self):
        first, second = self.package(), self.package()
        self.assertNotEqual(first, second)
        one, two = json.loads(first), json.loads(second)
        self.assertNotEqual(one['ephemeralPublicKey'], two['ephemeralPublicKey'])
        self.assertNotEqual(one['nonce'], two['nonce'])
        self.assertEqual(self.decrypt(first).payload_sha256, self.decrypt(second).payload_sha256)

    def test_ciphertext_nonce_and_ephemeral_key_tampering_is_rejected(self):
        original = json.loads(self.package())
        for field in ('ciphertext', 'nonce', 'ephemeralPublicKey'):
            with self.subTest(field=field):
                envelope = dict(original)
                raw = bytearray(base64.b64decode(envelope[field]))
                raw[0] ^= 1
                envelope[field] = base64.b64encode(raw).decode()
                with self.assertRaises(PackageDecryptionError):
                    self.decrypt(canonical(envelope))

    def test_recipient_header_is_checked_before_decryption(self):
        envelope = json.loads(self.package())
        envelope['recipientKeyId'] = '0'*64
        with self.assertRaises(RecipientMismatchError):
            self.decrypt(canonical(envelope))

    def test_unknown_fields_algorithm_and_version_are_rejected(self):
        original = json.loads(self.package())
        for changed in (dict(extra='untrusted'), dict(version=2), dict(version=True),
                        dict(algorithm='none'), dict(format='ZipArchive')):
            with self.subTest(changed=changed):
                with self.assertRaises(PackageFormatError):
                    self.decrypt(canonical(dict(original, **changed)))

    def test_duplicate_fields_trailing_data_and_noncanonical_encoding_are_rejected(self):
        package = self.package()
        for malformed in (package[:-1]+b',"version":1}', package+b'\n',
                          package+b'{}', b'\xff'+package, b'['+package+b']'):
            with self.subTest(length=len(malformed)):
                with self.assertRaises(PackageFormatError):
                    self.decrypt(malformed)
        envelope = json.loads(package)
        envelope['nonce'] += '='
        with self.assertRaises(PackageFormatError):
            self.decrypt(canonical(envelope))

    def test_plaintext_or_invalid_signed_content_inside_valid_encryption_is_rejected(self):
        with self.assertRaises(PackageSignatureError):
            self.decrypt(self.encrypted_fixture(b'Unsigned timing report'))
        signed = self.signer.sign_report('Signed wrong content').encode()
        with self.assertRaises(PackageFormatError):
            self.decrypt(self.encrypted_fixture(signed))
        changed = signed.replace(b'Signed wrong content', b'Forged wrong content')
        with self.assertRaises(PackageSignatureError):
            self.decrypt(self.encrypted_fixture(changed))

    def test_independent_crypto_fixture_opens_and_checks_inner_wrapper(self):
        payload = canonical(self.payload)
        wrapper = dict(format='TarnishedLineupRunPayload', version=1,
                       encoding='base64-canonical-json', payload=base64.b64encode(payload).decode())
        signed = self.signer.sign_report(canonical(wrapper).decode()).encode()
        self.assertEqual(self.decrypt(self.encrypted_fixture(signed)).payload, self.payload)
        for changed in (dict(version=2), dict(encoding='pickle'), dict(extra='unsigned schema')):
            with self.subTest(changed=changed):
                signed = self.signer.sign_report(canonical(dict(wrapper, **changed)).decode()).encode()
                with self.assertRaises(PackageFormatError):
                    self.decrypt(self.encrypted_fixture(signed))

    def test_signed_duplicate_or_nonobject_structured_payload_is_rejected(self):
        for payload in (b'{"time":1,"time":2}', b'[]', b'{"time":NaN}', b'{ "time":1}'):
            with self.subTest(payload=payload):
                wrapper = dict(format='TarnishedLineupRunPayload', version=1,
                    encoding='base64-canonical-json', payload=base64.b64encode(payload).decode())
                signed = self.signer.sign_report(canonical(wrapper).decode()).encode()
                with self.assertRaises(PackageFormatError):
                    self.decrypt(self.encrypted_fixture(signed))

    def test_faulty_signer_cannot_substitute_other_content(self):
        with self.assertRaises(PackageSignatureError):
            create_package(self.payload, lambda text: self.signer.sign_report('Substituted'), self.public)
        with self.assertRaises(PackageSignatureError):
            create_package(self.payload, lambda text: text, self.public)
        with self.assertRaises(PackageSignatureError):
            create_package(self.payload, lambda text: b'bytes instead of text', self.public)

    def test_payload_type_numeric_and_depth_limits(self):
        invalid = [[], {'time': float('nan')}, {'time': float('inf')}, {'huge': 1 << 54},
                   {1: 'not a string key'}, {'opaque': object()}, {'bad': '\ud800'}]
        deep = {}
        node = deep
        for _ in range(40):
            node['nested'] = {}
            node = node['nested']
        invalid.append(deep)
        for payload in invalid:
            with self.subTest(kind=type(payload).__name__):
                with self.assertRaises(PackageFormatError):
                    self.package(payload)

    def test_size_limits_apply_before_signing_and_before_decryption(self):
        signer = Mock()
        with patch('run_package.MAX_PAYLOAD_BYTES', 8):
            with self.assertRaises(PackageFormatError):
                create_package(self.payload, signer, self.public)
        signer.assert_not_called()
        package = self.package()
        with patch('run_package.MAX_PACKAGE_BYTES', len(package)-1):
            with self.assertRaises(PackageFormatError):
                self.decrypt(package)
        with patch('run_package.MAX_SIGNED_BYTES', 16):
            with self.assertRaises(PackageSignatureError):
                self.package()

    def test_generated_recipient_keys_are_usable_and_are_never_written(self):
        pair = generate_recipient_keypair()
        self.assertEqual(len(pair['privateKey']), 32)
        self.assertEqual(len(pair['publicKey']), 32)
        self.assertEqual(pair['fingerprint'], recipient_key_id(pair['publicKey']))
        before = sorted(path.name for path in self.directory.iterdir())
        package = create_package(self.payload, self.signer.sign_report, pair['publicKey'])
        self.assertEqual(decrypt_package(package, pair['privateKey']).payload, self.payload)
        self.assertEqual(sorted(path.name for path in self.directory.iterdir()), before)


if __name__ == '__main__':
    unittest.main()
