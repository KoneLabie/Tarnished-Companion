"""Tamper evidence, recovery failures and portable signatures in isolated storage."""
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from record_integrity import (LocalIntegrity, WindowsProtector, KEY_FILE, MANIFEST_FILE,
                              TIMING_FILES, REPORT_BEGIN, REPORT_END, REPORT_DOMAIN)


class TestProtector:
    """Test-only encryption; never injected by application production code."""
    label = 'Injected-test-protector'

    def protect(self, value):
        nonce = os.urandom(12)
        return nonce + AESGCM(b'x' * 32).encrypt(nonce, value, b'test')

    def unprotect(self, value):
        return AESGCM(b'x' * 32).decrypt(value[:12], value[12:], b'test')


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.engine = LocalIntegrity(self.directory, TestProtector())
        self.assertFalse(self.engine.tainted, self.engine.notice)

    def reopen(self):
        return LocalIntegrity(self.directory, TestProtector())

    def tracked_record(self, name='boss-attempts.json', content='{"records":[]}'):
        path = self.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        return path

    def test_bootstrap_and_authorized_updates_survive_restart(self):
        self.assertEqual(len(self.engine.public_fingerprint), 64)
        self.assertTrue(self.engine.verify())
        for name in TIMING_FILES:
            self.tracked_record(name)
        self.tracked_record('run-records/nested/run.json')
        self.assertTrue(self.engine.seal())
        restored = self.reopen()
        self.assertTrue(restored.verify(), restored.notice)
        self.assertEqual(restored.public_fingerprint, self.engine.public_fingerprint)
        self.tracked_record(content='{"records":[{"legitimate":"update"}]}')
        self.assertTrue(restored.seal())
        self.assertTrue(self.reopen().verify())

    def test_changed_record_blocks_signing_and_cannot_be_resealed(self):
        path = self.tracked_record()
        self.assertTrue(self.engine.seal())
        original = path.read_bytes()
        path.write_bytes(b'{"edited":true}')
        self.assertFalse(self.engine.verify())
        self.assertIn('changed, added, or removed', self.engine.notice)
        path.write_bytes(original)
        self.assertFalse(self.engine.verify())
        self.assertFalse(self.engine.seal())
        with self.assertRaises(ValueError):
            self.engine.sign_report('No fabricated report')
        self.assertFalse(self.reopen().verify())

    def test_deleted_record_is_detected(self):
        path = self.tracked_record()
        self.assertTrue(self.engine.seal())
        path.unlink()
        self.assertFalse(self.engine.verify())

    def test_unexpected_archive_is_detected(self):
        self.assertTrue(self.engine.seal())
        self.tracked_record('run-records/injected.json')
        self.assertFalse(self.engine.verify())

    def test_unsigned_existing_history_is_preserved_and_never_bootstrapped(self):
        legacy = self.directory / 'legacy'
        legacy.mkdir()
        history = legacy / 'run-state.json'
        history.write_bytes(b'{"previous":"unsigned"}')
        blocked = LocalIntegrity(legacy, TestProtector())
        self.assertTrue(blocked.tainted)
        self.assertFalse(blocked.verify())
        self.assertFalse(blocked.seal())
        self.assertEqual(history.read_bytes(), b'{"previous":"unsigned"}')
        self.assertFalse((legacy / KEY_FILE).exists())
        self.assertFalse((legacy / MANIFEST_FILE).exists())

    def test_missing_key_never_creates_a_replacement_for_signed_history(self):
        self.tracked_record()
        self.assertTrue(self.engine.seal())
        (self.directory / KEY_FILE).unlink()
        blocked = self.reopen()
        self.assertTrue(blocked.tainted)
        self.assertIsNone(blocked.public_fingerprint)
        self.assertFalse((self.directory / KEY_FILE).exists())

    def test_missing_manifest_blocks_even_when_key_can_be_unprotected(self):
        (self.directory / MANIFEST_FILE).unlink()
        blocked = self.reopen()
        self.assertTrue(blocked.tainted)
        self.assertFalse(blocked.seal())
        self.assertFalse((self.directory / MANIFEST_FILE).exists())

    def test_bad_manifest_signature_is_rejected_after_restart(self):
        path = self.directory / MANIFEST_FILE
        envelope = json.loads(path.read_text())
        envelope['signature'] = base64.b64encode(b'\0' * 64).decode()
        path.write_text(json.dumps(envelope))
        blocked = self.reopen()
        self.assertTrue(blocked.tainted)
        self.assertFalse(blocked.verify())

    def test_key_corruption_or_wrong_user_fails_closed(self):
        path = self.directory / KEY_FILE
        envelope = json.loads(path.read_text())
        envelope['protected'] = base64.b64encode(b'not a usable protected key').decode()
        path.write_text(json.dumps(envelope))
        blocked = self.reopen()
        self.assertTrue(blocked.tainted)
        self.assertIsNone(blocked.public_fingerprint)
        with self.assertRaises(ValueError):
            blocked.sign_report('Unavailable')

    def test_metadata_change_during_authorized_update_is_not_signed(self):
        self.assertTrue(self.engine.verify())
        self.tracked_record()
        (self.directory / MANIFEST_FILE).write_text('{}')
        self.assertFalse(self.engine.seal())

    def test_sealing_requires_a_successful_prior_verification(self):
        self.assertTrue(self.engine.seal())
        self.tracked_record()
        self.assertFalse(self.engine.seal())
        self.assertTrue(self.engine.tainted)

    def test_disk_write_failure_blocks_and_does_not_destroy_previous_manifest(self):
        self.assertTrue(self.engine.verify())
        prior = (self.directory / MANIFEST_FILE).read_bytes()
        self.tracked_record()
        with patch.object(self.engine, '_atomic', side_effect=OSError('simulated full disk')):
            self.assertFalse(self.engine.seal())
        self.assertEqual((self.directory / MANIFEST_FILE).read_bytes(), prior)
        self.assertFalse(self.engine.verify())

    def test_report_signature_covers_exact_utf8_payload_and_public_fingerprint(self):
        report = self.engine.sign_report('Tarnished — Rellana\nBoss time: 00:02:31.050')
        payload, footer = report.split(REPORT_BEGIN)
        self.assertTrue(footer.endswith(REPORT_END))
        envelope = json.loads(footer[:-len(REPORT_END)])
        public = base64.b64decode(envelope['publicKey'], validate=True)
        self.assertEqual(envelope['fingerprint'], hashlib.sha256(public).hexdigest())
        self.assertEqual(envelope['fingerprint'], self.engine.public_fingerprint)
        self.assertEqual(envelope['payloadSha256'], hashlib.sha256(payload.encode()).hexdigest())
        key = Ed25519PublicKey.from_public_bytes(public)
        key.verify(base64.b64decode(envelope['signature']), REPORT_DOMAIN + payload.encode())
        with self.assertRaises(InvalidSignature):
            key.verify(base64.b64decode(envelope['signature']),
                       REPORT_DOMAIN + payload.replace('02:31', '00:01').encode())

    def test_report_preserves_line_endings_and_rejects_nested_signature_markers(self):
        report = self.engine.sign_report('Character\r\nBoss\r\n')
        self.assertEqual(report.split(REPORT_BEGIN)[0], 'Character\r\nBoss\r\n')
        with self.assertRaises(ValueError):
            self.engine.sign_report(report)

    def test_report_round_trips_through_portable_pinned_key_verifier(self):
        from verify_report import verify_bytes, ReportVerificationError
        report = self.engine.sign_report('Tarnished — Rellana\nTime: 00:02:31.050\n').encode('utf-8')
        trusted = verify_bytes(report, self.engine.public_fingerprint)
        self.assertTrue(trusted.trusted)
        self.assertEqual(trusted.exit_code, 0)
        unpinned = verify_bytes(report)
        self.assertFalse(unpinned.trusted)
        self.assertEqual(unpinned.exit_code, 2)
        with self.assertRaises(ReportVerificationError):
            verify_bytes(report.replace(b'02:31', b'00:01'), self.engine.public_fingerprint)

    def test_settings_are_not_misrepresented_as_timing_records(self):
        self.assertTrue(self.engine.seal())
        (self.directory / 'settings.json').write_text('{"font":"Georgia"}')
        self.assertTrue(self.engine.verify())

    @unittest.skipUnless(os.name == 'nt', 'Production key protection requires Windows DPAPI')
    def test_windows_dpapi_protects_and_restores_current_user_key(self):
        protector = WindowsProtector()
        raw = b'A private signing seed for an isolated test'
        protected = protector.protect(raw)
        self.assertNotIn(raw, protected)
        self.assertEqual(protector.unprotect(protected), raw)
        production = LocalIntegrity(self.directory / 'windows')
        self.assertTrue(production.verify(), production.notice)
        fingerprint = production.public_fingerprint
        self.assertEqual(LocalIntegrity(self.directory / 'windows').public_fingerprint, fingerprint)


if __name__ == '__main__':
    unittest.main()
