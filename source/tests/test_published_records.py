import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from published_records import (CATEGORIES, MAPPING, PublishedRecords, api_url,
                               fetch_json, validate_board, _official_url, _json)

CATEGORY = 'any-percent-glitchless'


def fixture(times=(100, 110, 120, 130)):
    c = CATEGORIES[CATEGORY]
    values = {c['variableId']: c['valueId']}
    return {'data': {'game': MAPPING['gameId'], 'category': c['categoryId'], 'level': None,
        'platform': MAPPING['platformId'], 'timing': 'realtime', 'values': values,
        'players': {'data': [{'id': 'abcdefgh', 'names': {'international': 'Runner'}}]},
        'runs': [{'place': i + 1, 'run': {'id': f'{i:08d}', 'game': MAPPING['gameId'],
            'category': c['categoryId'], 'level': None, 'system': {'platform': MAPPING['platformId']},
            'status': {'status': 'verified'}, 'values': dict(values),
            'players': [{'rel': 'user', 'id': 'abcdefgh'}], 'date': '2026-10-01',
            'times': {'primary_t': seconds, 'realtime_t': seconds, 'ingame_t': 0},
            'weblink': 'https://untrusted.invalid/'}} for i, seconds in enumerate(times)]}}


class PublishedRecordsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.now = 1800000000
        self.payload = fixture()
        self.calls = 0
        def fetch(url):
            self.calls += 1
            self.assertEqual(url, api_url(CATEGORY))
            if isinstance(self.payload, Exception):
                raise self.payload
            return copy.deepcopy(self.payload)
        self.fetch = fetch
        self.client = PublishedRecords(self.directory.name, fetcher=fetch, clock=lambda: self.now)

    def tearDown(self):
        self.directory.cleanup()

    def test_new_record_replaces_cache_and_averages_use_only_returned_sample(self):
        first = self.client.refresh(CATEGORY)
        self.assertEqual((first['status'], first['bestSeconds'], first['nearBestSeconds'], first['averageSeconds']),
                         ('fresh', 100, 105, 115))
        self.assertFalse(first['bossTimesAvailable'])
        self.assertEqual(first['timingKey'], 'pc-soulsplitter-game-time')
        self.assertTrue(first['runs'][0]['url'].startswith('https://www.speedrun.com/eldenring/runs/'))
        self.now += 901
        self.payload = fixture((90, 100, 110))
        second = self.client.refresh(CATEGORY)
        self.assertEqual(second['bestSeconds'], 90)
        self.assertNotEqual(first['checkedAt'], second['checkedAt'])
        restored = PublishedRecords(self.directory.name, fetcher=self.fetch, clock=lambda: self.now)
        self.assertEqual(restored.snapshot(CATEGORY)['bestSeconds'], 90)
        self.assertEqual(self.calls, 2)

    def test_expired_cache_restart_and_failure_retains_last_success(self):
        first = self.client.refresh(CATEGORY)
        self.now += 901
        restored = PublishedRecords(self.directory.name, fetcher=self.fetch, clock=lambda: self.now)
        self.assertEqual(restored.snapshot(CATEGORY)['status'], 'stale')
        self.payload = OSError('offline')
        result = restored.refresh(CATEGORY)
        self.assertEqual((result['status'], result['checkedAt'], result['bestSeconds']), ('stale', first['checkedAt'], 100))
        self.assertNotEqual(result['lastAttemptAt'], result['checkedAt'])
        restored.refresh(CATEGORY, force=True)
        self.assertEqual(self.calls, 2)
        self.now += 60
        restored.refresh(CATEGORY, force=True)
        self.assertEqual(self.calls, 3)

    def test_force_still_has_minimum_60_seconds(self):
        self.client.refresh(CATEGORY)
        self.now += 59
        self.client.refresh(CATEGORY, force=True)
        self.assertEqual(self.calls, 1)
        self.now += 1
        self.client.refresh(CATEGORY, force=True)
        self.assertEqual(self.calls, 2)

    def test_empty_board_is_valid_and_replaces_old_times(self):
        self.client.refresh(CATEGORY)
        self.now += 901
        self.payload = fixture(())
        result = self.client.refresh(CATEGORY)
        self.assertEqual((result['status'], result['sampleCount'], result['bestSeconds']), ('fresh', 0, None))

    def test_unsupported_category_never_fetches(self):
        self.assertEqual(self.client.refresh('custom')['status'], 'unsupported')
        self.assertEqual(self.calls, 0)

    def test_rejects_invalid_samples_and_category_filters(self):
        for change in [lambda d: d.update(platform='console'), lambda d: d.update(timing='ingame'),
                       lambda d: d.update(values={}), lambda d: d.update(level='abcdefgh'),
                       lambda d: d['runs'][0]['run']['status'].update(status='new'),
                       lambda d: d['runs'][0]['run']['values'].clear(),
                       lambda d: d['runs'][0]['run']['times'].update(primary_t=0),
                       lambda d: d['runs'][0]['run']['times'].update(primary_t=float('nan')),
                       lambda d: d['runs'][0]['run']['times'].update(primary_t=True),
                       lambda d: d['runs'][0]['run']['times'].update(realtime_t=101),
                       lambda d: d['runs'][0]['run'].update(players=[None])]:
            with self.subTest(change=change):
                bad = fixture(); change(bad['data'])
                with self.assertRaises(ValueError):
                    validate_board(bad, CATEGORY)

    def test_malformed_response_cannot_replace_valid_cache(self):
        first = self.client.refresh(CATEGORY)
        for malformed in ['<html>Unavailable</html>', {}, {'data': None}]:
            self.now += 901; self.payload = malformed
            result = self.client.refresh(CATEGORY)
            self.assertEqual((result['status'], result['checkedAt'], result['bestSeconds']), ('stale', first['checkedAt'], 100))

    def test_snapshot_does_not_wait_for_network_and_returns_copies(self):
        self.client.refresh(CATEGORY)
        self.now += 901
        entered, release = threading.Event(), threading.Event()
        def delayed(url):
            entered.set(); release.wait(2); return fixture((90,))
        self.client.fetcher = delayed
        worker = threading.Thread(target=lambda: self.client.refresh(CATEGORY)); worker.start()
        self.assertTrue(entered.wait(1))
        began = time.monotonic(); snapshot = self.client.snapshot(CATEGORY)
        self.assertLess(time.monotonic()-began, .2)
        snapshot['runs'][0]['seconds'] = 1
        self.assertEqual(self.client.snapshot(CATEGORY)['bestSeconds'], 100)
        release.set(); worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.client.snapshot(CATEGORY)['bestSeconds'], 90)

    def test_stalled_resolver_cannot_hold_refresh(self):
        release = threading.Event()
        self.client.fetcher = lambda url: (release.wait(2), fixture())[1]
        try:
            with patch('published_records.MAX_SECONDS', .05):
                began = time.monotonic(); result = self.client.refresh(CATEGORY)
                self.assertLess(time.monotonic()-began, .3)
                self.assertEqual(result['status'], 'unavailable')
        finally:
            release.set()

    def test_official_https_only_and_strict_json(self):
        for url in ['http://www.speedrun.com/api/v1/x', 'https://evil.invalid/api/v1/x',
                    'https://www.speedrun.com:444/api/v1/x', 'https://user@www.speedrun.com/api/v1/x',
                    'https://www.speedrun.com/login']:
            with self.assertRaises(ValueError):
                _official_url(url)
        for text in ['{"data":1,"data":2}', '{"data":NaN}', '<html>']:
            with self.assertRaises(ValueError):
                _json(text)

    def test_both_distributions_use_identical_mappings(self):
        app = Path(__file__).resolve().parents[1]/'data'/'published-records.json'
        bot = Path(__file__).resolve().parents[2]/'bot'/'resources'/'published-records.json'
        self.assertEqual(json.loads(app.read_text(encoding='utf-8')), json.loads(bot.read_text(encoding='utf-8')))

    def test_http_rejects_html_oversize_and_external_redirects(self):
        class Socket:
            def settimeout(self, value):
                pass
        class Response:
            def __init__(self, status, headers):
                self.status, self.headers = status, headers
            def getheader(self, key, default=None):
                return self.headers.get(key, default)
            def read(self, size):
                return b''
        class Connection:
            sock = Socket()
            def connect(self):
                pass
            def request(self, *args, **kwargs):
                pass
            def close(self):
                pass
            def getresponse(self):
                return response
        for status, headers in [(200, {'Content-Type': 'text/html'}),
                                (200, {'Content-Type': 'application/json', 'Content-Length': '1048577'}),
                                (302, {'Location': 'https://evil.invalid/api/v1/data'})]:
            response = Response(status, headers)
            with patch('published_records.http.client.HTTPSConnection', return_value=Connection()):
                with self.assertRaises(ValueError):
                    fetch_json(api_url(CATEGORY))


if __name__ == '__main__':
    unittest.main()
