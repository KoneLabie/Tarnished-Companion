import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from record_integrity import LocalIntegrity, RECOVERY_FILE, MANIFEST_FILE
from test_record_integrity import TestProtector


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)
        self.engine=LocalIntegrity(self.directory,TestProtector())
        self.path=self.directory/'external-run.json';self.path.write_text('{"time":10}')
        self.engine.seal()

    def reopen(self):
        return LocalIntegrity(self.directory,TestProtector(),recover_interrupted=True)

    def test_interrupted_write_restores_signed_before_image_and_keeps_uncommitted_bytes(self):
        self.assertTrue(self.engine.begin_update())
        self.path.write_text('{"time":999}')
        extra=self.directory/'run-records'/'new.json';extra.parent.mkdir();extra.write_text('{"new":true}')
        restored=self.reopen()
        self.assertFalse(restored.tainted,restored.notice);self.assertTrue(restored.recovered)
        self.assertEqual(json.loads(self.path.read_text())['time'],10)
        self.assertFalse(extra.exists())
        kept=list((self.directory/'recovery-uncommitted').rglob('external-run.json'))
        self.assertEqual(len(kept),1);self.assertEqual(json.loads(kept[0].read_text())['time'],999)
        self.assertTrue(restored.verify())

    def test_no_checkpoint_never_uses_crash_as_excuse_to_trust_changes(self):
        self.path.write_text('{"time":999}')
        self.assertTrue(self.reopen().tainted)

    def test_changed_checkpoint_is_rejected(self):
        self.engine.begin_update();self.path.write_text('{"time":999}')
        p=self.directory/RECOVERY_FILE;data=json.loads(p.read_text());data['payload']['files']['external-run.json']='e30='
        p.write_text(json.dumps(data));self.assertTrue(self.reopen().tainted)

    def test_deleted_previously_sealed_archive_blocks_recovery(self):
        self.engine.begin_update()
        archive=self.directory/'run-records'/'old.json';archive.parent.mkdir();archive.write_text('{}')
        self.engine.seal();self.engine.begin_update();archive.unlink()
        self.assertTrue(self.reopen().tainted)

    def test_committed_data_is_retained_if_cleanup_did_not_run(self):
        self.engine.begin_update();pending=(self.directory/RECOVERY_FILE).read_bytes()
        self.path.write_text('{"time":11}');self.engine.seal()
        (self.directory/RECOVERY_FILE).write_bytes(pending)
        restored=self.reopen();self.assertFalse(restored.tainted,restored.notice)
        self.assertEqual(json.loads(self.path.read_text())['time'],11)
        self.assertFalse((self.directory/RECOVERY_FILE).exists())

    def test_clean_reopen_does_not_silently_repair_edited_records(self):
        self.engine.begin_update();self.path.write_text('{"time":999}')
        self.assertTrue(LocalIntegrity(self.directory,TestProtector()).tainted)

    def deny_checkpoint_cleanup(self):
        original = Path.unlink
        checkpoint = self.directory / RECOVERY_FILE

        def denied(path, *args, **kwargs):
            if path == checkpoint:
                raise PermissionError('simulated Windows sharing violation')
            return original(path, *args, **kwargs)
        return patch.object(Path, 'unlink', denied)

    def test_cleanup_permission_error_does_not_taint_committed_records(self):
        self.assertTrue(self.engine.begin_update())
        self.path.write_text('{"time":11}')
        with self.deny_checkpoint_cleanup():
            self.assertTrue(self.engine.seal())
            self.assertFalse(self.engine.tainted)
            self.assertIn('cleanup is deferred', self.engine.recovery_notice)
            self.assertTrue(self.engine.verify())
            self.assertIn('TARNISHED LINEUP SIGNATURE', self.engine.sign_report('Committed time: 11'))
            # Startup cleanup can hit the same sharing violation safely.
            restored = self.reopen()
            self.assertFalse(restored.tainted, restored.notice)
            self.assertEqual(json.loads(self.path.read_text())['time'], 11)
            self.assertTrue((self.directory / RECOVERY_FILE).exists())
        restored = self.reopen()
        self.assertTrue(restored.verify())
        self.assertFalse((self.directory / RECOVERY_FILE).exists())

    def test_restored_snapshot_remains_valid_when_checkpoint_cleanup_is_locked(self):
        self.assertTrue(self.engine.begin_update())
        self.path.write_text('{"time":999}')
        with self.deny_checkpoint_cleanup():
            restored = self.reopen()
            self.assertTrue(restored.recovered)
            self.assertFalse(restored.tainted, restored.notice)
            self.assertEqual(json.loads(self.path.read_text())['time'], 10)
            self.assertTrue(restored.verify())
            self.assertIn('cleanup is deferred', restored.recovery_notice)
        self.assertTrue(self.reopen().verify())

    def test_serialized_checkpoint_limit_includes_json_and_signature_overhead(self):
        self.assertTrue(self.engine.begin_update())
        checkpoint = self.directory / RECOVERY_FILE
        prior = checkpoint.read_bytes()
        manifest = (self.directory / MANIFEST_FILE).read_bytes()
        primary = self.path.read_bytes()
        # The encoded history still fits; the complete envelope is one byte too large.
        with patch('record_integrity.MAX_RECOVERY_BYTES', len(prior)-1):
            self.assertFalse(self.engine.begin_update())
        self.assertIn('exceeds the supported size', self.engine.notice)
        self.assertFalse(self.engine._verified_transaction)
        self.assertEqual(checkpoint.read_bytes(), prior)
        self.assertEqual((self.directory / MANIFEST_FILE).read_bytes(), manifest)
        self.assertEqual(self.path.read_bytes(), primary)

    def test_checkpoint_at_exact_limit_can_be_written_and_recovered(self):
        self.assertTrue(self.engine.begin_update())
        size = (self.directory / RECOVERY_FILE).stat().st_size
        with patch('record_integrity.MAX_RECOVERY_BYTES', size):
            self.assertTrue(self.engine.begin_update())
            self.assertEqual((self.directory / RECOVERY_FILE).stat().st_size, size)
            self.path.write_text('{"time":999}')
            restored = self.reopen()
            self.assertFalse(restored.tainted, restored.notice)
            self.assertTrue(restored.recovered)
            self.assertEqual(json.loads(self.path.read_text())['time'], 10)


if __name__=='__main__':unittest.main()
