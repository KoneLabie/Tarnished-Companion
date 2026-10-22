"""Restart decisions without launching or terminating any real processes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app_lifecycle import SESSION_ENV, MARKER_ENV, STOP_ENV, RECOVER_ENV
from app_supervisor import run_supervised, _clean_exit, EXIT_RESTART_LIMIT, EXIT_LAUNCH_FAILED


class FakeChild:
    def __init__(self, pid, env, code=0, marker='valid', interrupt=False, stubborn=False):
        self.pid, self.env, self.code, self.marker = pid, env, code, marker
        self.interrupt, self.stubborn = interrupt, stubborn
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.stop_seen = False

    def wait(self, timeout=None):
        if timeout is None and self.interrupt:
            self.interrupt = False
            raise KeyboardInterrupt()
        if timeout is not None:
            stop = json.loads(Path(self.env[STOP_ENV]).read_text())
            self.stop_seen = stop['session'] == self.env[SESSION_ENV] and stop['request'] == 'stop'
            if self.stubborn and not self.terminated:
                raise subprocess.TimeoutExpired('owned worker', timeout)
        if self.marker:
            value = dict(schemaVersion=1, session=self.env[SESSION_ENV], pid=self.pid,
                         exitCode=0, reason='requested-stop')
            if self.marker == 'wrong-token':
                value['session'] = 'stale-session'
            if self.marker == 'wrong-pid':
                value['pid'] += 1
            Path(self.env[MARKER_ENV]).write_text(json.dumps(value))
        self.returncode = self.code
        return self.code

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.now = 100.0
        self.delays = []
        self.commands = []
        self.children = []
        self.behaviors = []
        self.command = ['python', 'app.py', '--worker', '--port', '18473']
        for name in ('warning', 'error'):
            logger = patch('app_supervisor.logging.' + name)
            logger.start()
            self.addCleanup(logger.stop)

    def spawn(self, command, **options):
        self.commands.append((command, options))
        child = FakeChild(30000+len(self.children), options['env'], **self.behaviors.pop(0))
        self.children.append(child)
        return child

    def sleep(self, delay):
        self.delays.append(delay)
        self.now += delay

    def run_supervisor(self, **overrides):
        options = dict(spawn=self.spawn, health_check=lambda port: False,
                       monotonic=lambda: self.now, sleep=self.sleep)
        options.update(overrides)
        return run_supervised(self.command, 18473, self.directory, **options)

    def test_clean_stop_requires_matching_marker_and_does_not_restart(self):
        self.behaviors = [dict(code=0, marker='valid')]
        self.assertEqual(self.run_supervisor(), 0)
        self.assertEqual(len(self.children), 1)
        self.assertEqual(self.delays, [])

    def test_zero_exit_without_clean_handshake_is_restarted(self):
        self.behaviors = [dict(code=0, marker=None), dict(code=0, marker='valid')]
        self.assertEqual(self.run_supervisor(), 0)
        self.assertEqual(self.delays, [1])
        initial, restarted = self.commands
        self.assertNotIn('--no-browser', initial[0])
        self.assertNotIn(RECOVER_ENV, initial[1]['env'])
        self.assertIn('--recover', restarted[0])
        self.assertIn('--no-browser', restarted[0])
        self.assertEqual(restarted[1]['env'][RECOVER_ENV], '1')
        self.assertNotEqual(initial[1]['env'][SESSION_ENV], restarted[1]['env'][SESSION_ENV])

    def test_nonzero_exit_is_not_accepted_even_with_clean_marker(self):
        self.behaviors = [dict(code=1, marker='valid'), dict(code=0, marker='valid')]
        self.assertEqual(self.run_supervisor(), 0)
        self.assertEqual(len(self.children), 2)

    def test_stale_pid_and_session_markers_are_rejected(self):
        self.behaviors = [dict(marker='wrong-token'), dict(marker='wrong-pid'), dict(marker='valid')]
        self.assertEqual(self.run_supervisor(), 0)
        self.assertEqual(self.delays, [1, 2])

    def test_frozen_bootloader_exit_accepts_verified_worker_pid_binding(self):
        marker = self.directory / 'frozen-exit.json'
        payload = dict(schemaVersion=1, session='owned', pid=456, launcherPid=123,
                       parentPid=123, frozen=True, exitCode=0, reason='requested-stop')
        marker.write_text(json.dumps(payload))
        self.assertTrue(_clean_exit(marker, 'owned', 123, 0, allow_frozen_launcher=True))
        self.assertFalse(_clean_exit(marker, 'owned', 123, 0))
        self.assertFalse(_clean_exit(marker, 'stale', 123, 0, allow_frozen_launcher=True))
        self.assertFalse(_clean_exit(marker, 'owned', 999, 0, allow_frozen_launcher=True))
        self.assertFalse(_clean_exit(marker, 'owned', 123, 1, allow_frozen_launcher=True))
        payload['pid'] = -1
        marker.write_text(json.dumps(payload))
        self.assertFalse(_clean_exit(marker, 'owned', 123, 0, allow_frozen_launcher=True))

    def test_frozen_direct_worker_still_uses_its_exact_popen_pid(self):
        marker = self.directory / 'direct-exit.json'
        marker.write_text(json.dumps(dict(schemaVersion=1, session='owned', pid=456,
            parentPid=123, launcherPid=123, frozen=True, exitCode=0, reason='requested-stop')))
        self.assertTrue(_clean_exit(marker, 'owned', 456, 0, allow_frozen_launcher=True))

    def test_restart_limit_stops_after_three_retries_in_two_minutes(self):
        self.behaviors = [dict(code=1, marker=None) for _ in range(4)]
        self.assertEqual(self.run_supervisor(), EXIT_RESTART_LIMIT)
        self.assertEqual(len(self.children), 4)
        self.assertEqual(self.delays, [1, 2, 4])

    def test_stable_interval_resets_rolling_restart_budget(self):
        self.behaviors = [dict(code=1, marker=None) for _ in range(4)] + [dict(marker='valid')]
        readings = iter([100, 101, 102, 230])
        self.assertEqual(self.run_supervisor(monotonic=lambda: next(readings)), 0)
        self.assertEqual(self.delays, [1, 2, 4, 1])

    def test_existing_instance_prevents_worker_launch(self):
        spawn = Mock()
        self.assertEqual(self.run_supervisor(spawn=spawn, health_check=lambda port: True), 0)
        spawn.assert_not_called()

    def test_another_healthy_instance_can_take_over_during_backoff(self):
        self.behaviors = [dict(code=1, marker=None)]
        health = Mock(side_effect=[False, True])
        self.assertEqual(self.run_supervisor(health_check=health), 0)
        self.assertEqual(len(self.children), 1)

    def test_parent_interrupt_requests_graceful_stop_without_restart(self):
        self.behaviors = [dict(interrupt=True)]
        self.assertEqual(self.run_supervisor(), 130)
        child = self.children[0]
        self.assertTrue(child.stop_seen)
        self.assertFalse(child.terminated)
        self.assertFalse(child.killed)
        self.assertEqual(len(self.children), 1)

    def test_unresponsive_owned_child_is_terminated_after_grace_period(self):
        self.behaviors = [dict(interrupt=True, stubborn=True)]
        self.assertEqual(self.run_supervisor(), 130)
        child = self.children[0]
        self.assertTrue(child.stop_seen)
        self.assertTrue(child.terminated)
        self.assertFalse(child.killed)

    def test_console_close_stops_owned_child_and_never_restarts(self):
        captured = {}
        restore = Mock()

        def install(callback):
            captured['stop'] = callback
            return restore

        class ClosingChild(FakeChild):
            def wait(self, timeout=None):
                if timeout is None:
                    captured['stop']()
                    return self.returncode
                return super().wait(timeout)

        def spawn(command, **options):
            child = ClosingChild(40000, options['env'])
            self.children.append(child)
            return child

        with patch('app_supervisor._install_console_handler', side_effect=install):
            self.assertEqual(self.run_supervisor(spawn=spawn), 130)
        self.assertTrue(self.children[0].stop_seen)
        self.assertEqual(len(self.children), 1)
        restore.assert_called_once()

    def test_spawn_failure_stops_without_retry_loop(self):
        spawn = Mock(side_effect=OSError('missing executable'))
        self.assertEqual(self.run_supervisor(spawn=spawn), EXIT_LAUNCH_FAILED)
        self.assertEqual(spawn.call_count, 1)

    def test_cleanup_removes_only_this_invocations_handshake_files(self):
        other = self.directory / 'supervisor' / 'unrelated.json'
        other.parent.mkdir()
        other.write_text('preserve')
        self.behaviors = [dict(marker='valid')]
        self.assertEqual(self.run_supervisor(), 0)
        self.assertEqual(list(other.parent.iterdir()), [other])
        self.assertEqual(other.read_text(), 'preserve')

    @unittest.skipUnless(os.name == 'nt', 'Windows process flags')
    def test_windows_worker_is_hidden_and_owns_a_process_group(self):
        self.behaviors = [dict(marker='valid')]
        self.run_supervisor()
        options = self.commands[0][1]
        self.assertTrue(options['creationflags'] & subprocess.CREATE_NO_WINDOW)
        self.assertTrue(options['creationflags'] & subprocess.CREATE_NEW_PROCESS_GROUP)
        self.assertEqual(options['startupinfo'].wShowWindow, subprocess.SW_HIDE)


if __name__ == '__main__':
    unittest.main()
