"""Public reference refreshes must stay separate from capture and its category."""
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


CAPTURED = 'any-percent-glitchless'
NEXT_RUN = 'all-remembrances-no-dlc-glitchless'


class PublishedIntegrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        with patch('app.discover_saves', return_value=[]), \
                patch('app.detect_dlc', return_value={'available': False}), \
                patch('app.LiveReader', return_value=Mock()):
            self.tracker = app.Tracker(directory.name)
        self.tracker.cfg['overlayView'] = 'speedrun'
        self.tracker.action({'action': 'runCategory', 'categoryId': NEXT_RUN})

    def recorded_run(self, status='finished'):
        # Only the already-captured metadata is relevant to reference selection.
        self.tracker.external_run.record = dict(status=status, journey=1,
            runPolicy={'categoryId': CAPTURED, 'eligible': False})

    def test_state_retains_captured_category_after_next_category_changes(self):
        for status in ('running', 'paused', 'finished'):
            with self.subTest(status=status):
                self.recorded_run(status)
                with patch('app.discover_saves', return_value=[]):
                    state = self.tracker.state()
                self.assertEqual(state['runPolicy']['selectedId'], NEXT_RUN)
                self.assertEqual(state['speedrun']['runPolicy']['categoryId'], CAPTURED)
                self.assertEqual(state['publishedRecord']['categoryId'], CAPTURED)
                self.assertEqual(state['publishedRecord']['timingKey'], 'pc-soulsplitter-game-time')
                self.assertEqual(state['publishedRecord']['status'], 'unavailable')

    def test_slow_public_request_does_not_hold_game_timing_lock(self):
        tracker = self.tracker
        entered, release = threading.Event(), threading.Event()

        def delayed_source(url):
            entered.set()
            release.wait(3)
            raise OSError('synthetic offline source')

        tracker.published_records.fetcher = delayed_source
        worker = threading.Thread(target=tracker.published_worker, daemon=True)
        worker.start()
        try:
            self.assertTrue(entered.wait(2), 'Public worker did not reach its fetch')
            acquired = tracker.lock.acquire(timeout=.5)
            self.assertTrue(acquired, 'Reference I/O blocked the game/timing lock')
            try:
                # State reads must also remain available while that fetch is waiting.
                with patch('app.discover_saves', return_value=[]):
                    state = tracker.state()
                self.assertEqual(state['publishedRecord']['status'], 'unavailable')
                self.assertIsNone(tracker.external_run.record)
            finally:
                if acquired:
                    tracker.lock.release()
        finally:
            tracker.stop.set()
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive(), 'Optional reference worker did not stop')
        self.assertTrue(tracker.integrity.verify(), tracker.integrity.notice)

    def test_failed_captured_refresh_still_refreshes_future_category(self):
        self.recorded_run()
        calls = []

        def refresh(category):
            calls.append(category)
            if category == CAPTURED:
                raise RuntimeError('synthetic reference service failure')
            self.tracker.stop.set()

        with patch.object(self.tracker.published_records, 'refresh', side_effect=refresh), \
                self.assertLogs(level='WARNING'):
            self.tracker.published_worker()
        self.assertEqual(calls, [CAPTURED, NEXT_RUN])
        self.assertEqual(self.tracker.external_run.record['status'], 'finished')


if __name__ == '__main__':
    unittest.main()
