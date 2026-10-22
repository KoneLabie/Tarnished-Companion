"""Automatic startup must not block capture or need manual save selection."""
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class StartupIntegrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        with patch('app.discover_saves', return_value=[]), patch('app.detect_dlc', return_value={'available': False}), patch('app.LiveReader', return_value=Mock()):
            self.tracker = app.Tracker(directory.name)

    def test_first_character_save_connects_automatically_after_game_creates_it(self):
        path = 'synthetic-first-character.sl2'
        with patch('app.discover_saves', return_value=[path]):
            self.tracker.read_save()
        self.assertEqual(self.tracker.cfg['save'], path)
        self.assertIn('automatically', self.tracker.status)

    def test_launch_preparation_keeps_timing_lock_responsive_and_does_not_start_timer(self):
        acquired = []
        def launch():
            def probe():
                held = self.tracker.lock.acquire(timeout=.5)
                acquired.append(held)
                if held:self.tracker.lock.release()
            worker = threading.Thread(target=probe);worker.start();worker.join(2)
        with patch.object(self.tracker.launcher, 'launch', side_effect=launch):
            self.tracker.action({'action': 'launchOffline'})
        self.assertEqual(acquired, [True])
        self.assertIsNone(self.tracker.external_run.record)
        self.assertTrue(self.tracker.integrity.verify())

    def test_shortcut_request_arms_only_automatic_startup(self):
        self.tracker.action({'action': 'requestPlay'})
        self.assertTrue(self.tracker.launcher.snapshot()['automaticStart'])
        self.assertIsNone(self.tracker.external_run.record)
        self.assertTrue(self.tracker.integrity.verify())

    def test_reopening_executable_lands_on_walkthrough(self):
        with patch('sys.argv',['app.py','--no-game-launch']), patch('app_supervisor.existing_instance',return_value=True), patch('app.webbrowser.open') as browser:
            self.assertEqual(app.main(),0)
        browser.assert_called_once_with('http://127.0.0.1:18473/preview')


if __name__=='__main__':unittest.main()
