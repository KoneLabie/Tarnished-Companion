"""Session continuity and child-parent exit markers in temporary directories."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app_lifecycle as lifecycle


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        path = patch.object(lifecycle, '_session_path', None)
        state = patch.object(lifecycle, '_session_record', None)
        path.start()
        state.start()
        self.addCleanup(path.stop)
        self.addCleanup(state.stop)

    def test_new_session_clean_close_and_next_launch(self):
        first = lifecycle.begin_session(self.directory)
        self.assertFalse(first['previousUnclean'])
        lifecycle.mark_clean_exit('requested-stop')
        second = lifecycle.begin_session(self.directory)
        self.assertFalse(second['previousUnclean'])
        self.assertEqual(second['previousExit'], 'requested-stop')
        self.assertNotEqual(first['session'], second['session'])

    def test_dead_running_session_requests_recovery_without_calling_it_a_crash(self):
        lifecycle.begin_session(self.directory)
        next_session = lifecycle.begin_session(self.directory, is_process_alive=lambda pid: False)
        self.assertTrue(next_session['previousUnclean'])
        self.assertIn('unexpectedly', next_session['notice'])
        self.assertNotIn('crash', next_session['notice'])

    def test_live_previous_instance_is_not_overwritten(self):
        lifecycle.begin_session(self.directory)
        path = self.directory / lifecycle.SESSION_FILE
        original = path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'still running'):
            lifecycle.begin_session(self.directory, is_process_alive=lambda pid: True)
        self.assertEqual(path.read_bytes(), original)

    def test_malformed_previous_marker_is_recovery_hint_only(self):
        (self.directory / lifecycle.SESSION_FILE).write_text('{partial')
        result = lifecycle.begin_session(self.directory)
        self.assertTrue(result['previousUnclean'])
        self.assertIn('valid signed checkpoint', result['notice'])

    def test_clean_exit_marker_contains_current_pid_and_parent_session(self):
        marker = self.directory / 'parent-exit.json'
        with patch.dict(os.environ, {lifecycle.SESSION_ENV: 'parent-token', lifecycle.MARKER_ENV: str(marker)}):
            lifecycle.begin_session(self.directory)
            lifecycle.mark_clean_exit('parent-stop')
        payload = json.loads(marker.read_text())
        self.assertEqual(payload['pid'], os.getpid())
        self.assertEqual(payload['session'], 'parent-token')
        self.assertEqual(payload['exitCode'], 0)
        self.assertEqual(payload['reason'], 'parent-stop')
        self.assertEqual(json.loads((self.directory / lifecycle.SESSION_FILE).read_text())['status'], 'clean')

    def test_clean_exit_does_not_overwrite_replaced_session(self):
        lifecycle.begin_session(self.directory)
        path = self.directory / lifecycle.SESSION_FILE
        record = json.loads(path.read_text())
        record['session'] = 'another-session'
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'session changed'):
            lifecycle.mark_clean_exit()
        self.assertEqual(json.loads(path.read_text())['status'], 'running')

    def test_unexpected_failure_cannot_be_marked_as_clean(self):
        lifecycle.begin_session(self.directory)
        with self.assertRaises(ValueError):
            lifecycle.mark_clean_exit('crash')
        self.assertEqual(json.loads((self.directory / lifecycle.SESSION_FILE).read_text())['status'], 'running')

    def test_parent_stop_request_requires_matching_session(self):
        path = self.directory / 'stop.json'
        with patch.dict(os.environ, {lifecycle.SESSION_ENV: 'owned-session', lifecycle.STOP_ENV: str(path)}):
            self.assertFalse(lifecycle.supervisor_stop_requested())
            path.write_text(json.dumps(dict(schemaVersion=1, session='other-session', request='stop')))
            self.assertFalse(lifecycle.supervisor_stop_requested())
            path.write_text(json.dumps(dict(schemaVersion=1, session='owned-session', request='stop')))
            self.assertTrue(lifecycle.supervisor_stop_requested())

    def test_process_liveness_accepts_current_pid_and_rejects_invalid_pid(self):
        self.assertTrue(lifecycle.process_alive(os.getpid()))
        self.assertFalse(lifecycle.process_alive(-1))
        self.assertFalse(lifecycle.process_alive('1'))

    def test_frozen_worker_marker_binds_verified_bootloader_and_real_worker(self):
        marker = self.directory / 'frozen-exit.json'
        with patch.dict(os.environ, {lifecycle.SESSION_ENV: 'frozen-token', lifecycle.MARKER_ENV: str(marker)}), \
                patch.object(lifecycle.sys, 'frozen', True, create=True), \
                patch.object(lifecycle, '_same_executable', return_value=True) as same:
            lifecycle.mark_clean_exit()
        record = json.loads(marker.read_text())
        self.assertEqual(record['pid'], os.getpid())
        self.assertEqual(record['launcherPid'], os.getppid())
        self.assertEqual(record['parentPid'], os.getppid())
        self.assertTrue(record['frozen'])
        same.assert_called_once_with(os.getppid())

    def test_unverified_parent_never_gets_a_frozen_launcher_binding(self):
        marker = self.directory / 'unverified-exit.json'
        with patch.dict(os.environ, {lifecycle.SESSION_ENV: 'token', lifecycle.MARKER_ENV: str(marker)}), \
                patch.object(lifecycle.sys, 'frozen', True, create=True), \
                patch.object(lifecycle, '_same_executable', return_value=False):
            lifecycle.mark_clean_exit()
        self.assertNotIn('launcherPid', json.loads(marker.read_text()))

    def test_executable_identity_checks_the_actual_current_process(self):
        self.assertTrue(lifecycle._same_executable(os.getpid()))
        self.assertFalse(lifecycle._same_executable(-1))


if __name__ == '__main__':
    unittest.main()
