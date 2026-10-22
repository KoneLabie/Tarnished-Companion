import math
from pathlib import Path
import sys
import subprocess
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop_overlay import interactive_regions, stop_owned_overlay, watch_owner_pipe, run


class OwnedOverlayLifecycleTests(unittest.TestCase):
    def test_real_child_observes_pipe_eof_without_python_stdin(self):
        # No app or window is launched. This exercises the actual Windows pipe
        # handle used when a windowed frozen executable has sys.stdin=None.
        script = ('import sys; sys.path.insert(0, sys.argv[1]); '
                  'from desktop_overlay import watch_owner_pipe; '
                  'sys.stdin=None; print("ready", flush=True); '
                  'watch_owner_pipe(lambda: print("closed", flush=True))')
        child = subprocess.Popen([sys.executable, '-c', script,
                                  str(Path(__file__).resolve().parents[1])],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertEqual(child.stdout.readline().strip(), b'ready')
            self.assertIsNone(child.poll())
            self.assertTrue(stop_owned_overlay(child))
            self.assertEqual(child.returncode, 0)
            self.assertEqual(child.stdout.read().strip(), b'closed')
        finally:
            if child.poll() is None:
                child.kill(); child.wait(timeout=5)
            child.stdin.close(); child.stdout.close(); child.stderr.close()

    def test_only_owned_child_is_reaped_with_bounded_escalation(self):
        child = Mock()
        child.poll.return_value = None
        child.wait.side_effect = [subprocess.TimeoutExpired('overlay', 5),
                                  subprocess.TimeoutExpired('overlay', 2), 0]
        self.assertTrue(stop_owned_overlay(child))
        child.stdin.close.assert_called_once()
        self.assertEqual(child.wait.call_count, 3)
        child.terminate.assert_called_once()
        child.kill.assert_called_once()

    def test_broken_owner_pipe_still_reaps_child(self):
        child = Mock()
        child.poll.return_value = None
        child.stdin.close.side_effect = OSError('already closed')
        self.assertTrue(stop_owned_overlay(child))
        child.wait.assert_called_once_with(timeout=5)
        child.terminate.assert_not_called()

    def test_no_child_and_already_exited_child_are_safe(self):
        self.assertTrue(stop_owned_overlay(None))
        child = Mock()
        child.poll.return_value = 0
        self.assertTrue(stop_owned_overlay(child))
        child.wait.assert_not_called()
        child.terminate.assert_not_called()

    def test_pipe_error_closes_instead_of_orphaning(self):
        close = Mock()
        watch_owner_pipe(close, read=Mock(side_effect=OSError('owner ended')))
        close.assert_called_once()

    def test_owner_ending_during_startup_suppresses_expected_startup_error(self):
        with patch('desktop_overlay.watch_owner_pipe', side_effect=lambda close: close()), \
                patch('desktop_overlay._run', side_effect=ConnectionRefusedError):
            self.assertIsNone(run(1, '.', owned=True))

    def test_unowned_startup_errors_are_not_suppressed(self):
        with patch('desktop_overlay._run', side_effect=ConnectionRefusedError):
            with self.assertRaises(ConnectionRefusedError):
                run(1, '.')


class InteractiveRegionsTests(unittest.TestCase):
    def test_clips_to_css_viewport_without_losing_fractional_coordinates(self):
        result = interactive_regions([
            {'x': -5, 'y': 10.5, 'width': 30, 'height': 20},
            {'x': 270, 'y': 190, 'width': 30, 'height': 30},
        ], 280, 200)
        self.assertEqual(result, ([0.0, 10.5, 25.0, 20.0, 270.0, 190.0, 10.0, 10.0], 280.0, 200.0))

    def test_offscreen_or_zero_sized_controls_are_not_click_targets(self):
        self.assertEqual(interactive_regions([
            {'x': 1000, 'y': 0, 'width': 30, 'height': 30},
            {'x': 10, 'y': 10, 'width': 0, 'height': 10},
        ], 360, 500)[0], [])

    def test_invalid_viewports_and_excessive_controls_are_rejected(self):
        for width, height in ((True, 500), (0, 500), (math.nan, 500), (360, math.inf), (10001, 500)):
            with self.subTest(width=width, height=height), self.assertRaises(ValueError):
                interactive_regions([], width, height)
        with self.assertRaises(ValueError):
            interactive_regions([{}] * 65, 360, 500)

    def test_malformed_or_nonfinite_rectangles_are_rejected(self):
        for bad in (None, {}, {'x': 0, 'y': 0, 'width': -1, 'height': 30},
                    {'x': math.nan, 'y': 0, 'width': 30, 'height': 30},
                    {'x': True, 'y': 0, 'width': 30, 'height': 30}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                interactive_regions([bad], 360, 500)


if __name__ == '__main__':
    unittest.main()
