"""Mode actions, character binding, and HTTP export without a game or real save."""
import json
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from verify_report import verify_bytes
from run_package import generate_recipient_keypair, decrypt_package
from record_integrity import TIMING_FILES, MANIFEST_FILE


class ModeIntegrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        with patch('app.discover_saves', return_value=[]), patch('app.LiveReader', return_value=Mock()):
            self.tracker = app.Tracker(self.directory)
        self.tracker.context = 'v2:test_character:j1'
        self.tracker.stats = dict(name='Test Tarnished', seconds=300, deaths=7, journey=1,
                                  level=20, origin='Hero', runes=10, slot=0)
        self.tracker.save_status = 'connected'
        self.tracker.killed = {app.BOSSES[0]['id']}
        self.keys = generate_recipient_keypair()
        self.key_patch = patch.object(self.tracker, 'recipient_key', return_value=self.keys['publicKey'])
        self.key_patch.start()
        self.addCleanup(self.key_patch.stop)

    def decrypt(self, package):
        return decrypt_package(package, self.keys['privateKey'], self.tracker.integrity.public_fingerprint)

    def action(self, op):
        self.tracker.action(dict(action='speedrun', op=op, contextKey=self.tracker.context))

    @contextmanager
    def transaction(self):
        with self.tracker.lock:
            self.assertTrue(self.tracker.integrity.begin_update(), self.tracker.integrity.notice)
            yield
            self.assertTrue(self.tracker.integrity.seal(), self.tracker.integrity.notice)

    def cycle(self, phase, elapsed, at='2026-10-22T10:00:00.000+00:00'):
        """Run the real integration loop once; only external I/O is substituted."""
        tracker = self.tracker
        tracker.external_timer = dict(connected=True, configured=True, phase=phase,
            gameTimeSeconds=elapsed, realTimeSeconds=elapsed, attemptCount=1,
            gameName='Elden Ring', categoryName='Any% Glitchless')
        tracker.external_sequence += 1
        tracker.game_process = 'running'
        stop = Mock()
        stop.is_set.side_effect = [False, True]
        tracker.stop = stop
        with patch.object(tracker, 'read_save'), patch.object(tracker, 'live_tick'), \
                patch('external_run.utc', return_value=at):
            tracker.run()
        stop.wait.assert_called_once_with(.5)

    def fresh_run(self):
        tracker = self.tracker
        tracker.action(dict(action='timingMode', mode='livesplit'))
        tracker.action(dict(action='runCategory', categoryId='any-percent-glitchless'))
        tracker.action(dict(action='overlayView', view='speedrun'))
        tracker.cfg['save'] = str(self.directory / 'synthetic.sl2')
        tracker.context = 'v2:fresh_character:j1'
        tracker.stats = dict(tracker.stats, seconds=0, deaths=0, journey=1)
        tracker.killed = set()
        save_key = app.file_key(tracker.cfg['save'])
        with self.transaction():
            now = time.monotonic()
            tracker.run_policy.observe_roster(save_key, [], True, now=now-1)
            tracker.run_policy.observe_roster(save_key, [tracker.stats], True, now=now)
        self.cycle('NotRunning', 0)
        self.assertFalse(tracker.run_policy.can_record(tracker.context))
        self.cycle('Running', .5)
        self.assertTrue(tracker.run_policy.can_record(tracker.context))
        self.assertTrue(tracker.external_run.record['runPolicy']['eligible'])

    def observe_victory(self, boss_id, start, end, now):
        tracker = self.tracker
        boss = app.BY_ID[boss_id]
        bar = dict(handle=str(boss_id), name=boss['name'], hp=1000, maxHp=1000)
        with self.transaction():
            def observe(bars, tick):
                tracker.attempts.observe(tracker.context, tracker.stats, tracker.killed, bars,
                    ready=True, live_available=True, process_state='running',
                    boss_resolver=lambda name: app.match_boss(name, [], tracker.killed),
                    boss_names=app.BOSS_NAMES, now=tick,
                    category_key=tracker.run_policy.selected_id)
            observe([], now)
            with patch('boss_attempts._utc', return_value=start):
                observe([bar], now+1)
            observe([dict(bar, hp=0)], now+2)
            tracker.killed.add(boss_id)
            with patch('boss_attempts._utc', return_value=end):
                observe([], now+3)

    def server(self):
        server = app.serve(self.tracker, 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        # The handler's allowlist uses the requested port, including test port 0.
        return ('http://127.0.0.1:%s' % server.server_address[1], {'Host': '127.0.0.1:0'})

    def checkpoint_active_boss(self):
        self.fresh_run()
        tracker = self.tracker
        boss_id = app.MAJOR[0]
        bar = dict(handle='checkpoint-boss', name=app.BY_ID[boss_id]['name'], hp=1000, maxHp=1000)
        now = time.monotonic()
        with self.transaction():
            def observe(bars, at):
                tracker.attempts.observe(tracker.context, tracker.stats, tracker.killed, bars,
                    ready=True, live_available=True, process_state='running', now=at,
                    boss_resolver=lambda name: boss_id, boss_names=app.BOSS_NAMES,
                    category_key=tracker.run_policy.selected_id)
            observe([], now)
            for offset in (1, 3, 5, 7):
                observe([bar], now+offset)
        checkpoint = json.loads((self.directory / 'boss-attempts.json').read_text())
        self.assertIsNotNone(checkpoint['active'])
        self.assertEqual(checkpoint['active']['elapsedSeconds'], 6)
        return checkpoint['active']

    def protected_record_bytes(self):
        paths = [self.directory / name for name in (*TIMING_FILES, MANIFEST_FILE)]
        paths.extend((self.directory / 'run-records').rglob('*.json'))
        return {path.relative_to(self.directory).as_posix(): path.read_bytes()
                for path in paths if path.is_file()}

    def test_default_livesplit_timer_rejects_all_manual_timer_controls(self):
        with patch('app.discover_saves', return_value=[]), patch('app.LiveReader', return_value=Mock()):
            tracker = app.Tracker(self.directory / 'defaults')
        self.assertEqual(tracker.cfg['timingMode'], 'livesplit')
        self.assertTrue(tracker.run_state()['controlsLocked'])
        for operation in ('start', 'pause', 'resume', 'finish', 'reset'):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(ValueError, 'LiveSplit controls this timer'):
                    tracker.action(dict(action='speedrun', op=operation, contextKey=tracker.context))
        self.assertEqual(tracker.speedrun.snapshot()['status'], 'idle')
        self.assertIsNone(tracker.external_run.record)

    def test_existing_character_cannot_start_recording_or_export(self):
        self.tracker.action(dict(action='runCategory', categoryId='any-percent-glitchless'))
        self.tracker.action(dict(action='overlayView', view='speedrun'))
        self.cycle('Running', .5)
        self.assertFalse(self.tracker.run_policy.can_record(self.tracker.context))
        self.assertIsNone(self.tracker.external_run.record)
        self.assertFalse((self.directory / 'boss-attempts.json').exists())
        with self.assertRaisesRegex(ValueError, 'Manual timer actions are disabled'):
            self.action('start')
        self.assertFalse(self.tracker.run_state()['exportAvailable'])
        with self.assertRaisesRegex(ValueError, 'Timing export is locked'):
            self.tracker.export_run()

    def test_finished_run_passes_attempt_export_character_and_time_bounds(self):
        self.fresh_run()
        first_boss, later_boss = app.MAJOR[:2]
        now = time.monotonic()
        self.observe_victory(first_boss, '2026-10-22T10:05:00.000+00:00',
                             '2026-10-22T10:06:00.000+00:00', now)
        self.cycle('Ended', 600, '2026-10-22T10:10:00.000+00:00')
        record = self.tracker.external_run.record
        self.observe_victory(later_boss, '2026-10-22T10:11:00.000+00:00',
                             '2026-10-22T10:12:00.000+00:00', now+5)
        # The export must retain the completed run's character after a selection change.
        self.tracker.context = 'v2:later_character:j2'
        with patch.object(self.tracker.attempts, 'export_text', wraps=self.tracker.attempts.export_text) as attempts:
            package = self.tracker.export_run()
            report = self.decrypt(package).payload['reportText']
            self.assertIn('OBSERVED BOSS ATTEMPTS', report)
            self.assertIn(app.BY_ID[first_boss]['name'], report)
            self.assertNotIn(app.BY_ID[later_boss]['name'], report)
            self.assertEqual(attempts.call_args.kwargs['context'], record['contextKey'])
            self.assertEqual(attempts.call_args.kwargs['since'], record['startedAt'])
            self.assertEqual(attempts.call_args.kwargs['until'], record['endedAt'])
        self.assertTrue(self.decrypt(package).trusted)

    def test_existing_attempts_do_not_bypass_new_character_export_gate(self):
        with patch.object(self.tracker.attempts, 'snapshot', return_value=dict(records=[{}], active=None)):
            self.assertFalse(self.tracker.run_state()['exportAvailable'])
            with self.assertRaisesRegex(ValueError, 'Timing export is locked'):
                self.tracker.export_run()

    def test_encrypted_report_keeps_run_loadouts_after_character_switch(self):
        self.tracker.stats['build'] = dict(status='available', source='checksum-validated-save',
            level=20, attributes={'strength':24}, equipment={'weapons':[{'slot':'right1','name':'Claymore'}]})
        self.fresh_run()
        self.tracker.stats['build']['level'] = 21
        self.cycle('Running', 20)
        self.cycle('Ended', 100)
        self.tracker.stats['build']['level'] = 90
        self.tracker.context = 'different-character:j2'
        payload = self.decrypt(self.tracker.export_run()).payload
        self.assertEqual(payload['build']['initial']['level'], 20)
        self.assertEqual(payload['build']['final']['level'], 21)
        self.assertEqual(len(payload['build']['observations']), 2)
        self.assertEqual(payload['run']['contextKey'], 'v2:fresh_character:j1')
        self.assertTrue(self.tracker.integrity.verify())

    def test_recipient_configuration_is_required_without_plaintext_fallback(self):
        self.fresh_run()
        self.cycle('Ended', 100)
        with patch.object(self.tracker, 'recipient_key', return_value=None):
            self.assertFalse(self.tracker.run_state()['exportAvailable'])
            with self.assertRaises(ValueError):
                self.tracker.export_run()

    def test_home_and_combat_views_never_capture_fresh_run_or_boss_times(self):
        tracker = self.tracker
        tracker.action(dict(action='runCategory', categoryId='any-percent-glitchless'))
        tracker.cfg['save'] = str(self.directory / 'synthetic.sl2')
        tracker.stats = dict(tracker.stats, seconds=0, deaths=0, journey=1)
        tracker.killed = set()
        boss = app.BY_ID[app.MAJOR[0]]
        tracker.bars = [dict(handle='boss', name=boss['name'], hp=1000, maxHp=1000)]
        tracker.live_status = 'Live boss data connected.'
        for view in ('home', 'combat'):
            with self.subTest(view=view):
                tracker.action(dict(action='overlayView', view=view))
                tracker.context = f'v2:fresh_{view}:j1'
                with self.transaction():
                    now = time.monotonic()
                    key = app.file_key(tracker.cfg['save'])
                    tracker.run_policy.observe_roster(key, [], True, now=now-1)
                    tracker.run_policy.observe_roster(key, [tracker.stats], True, now=now)
                self.cycle('NotRunning', 0)
                self.cycle('Running', .5)
                self.assertIsNone(tracker.external_run.record)
                self.assertFalse(tracker.run_policy.can_record(tracker.context))
                self.assertEqual(tracker.run_policy.records, {})
                self.assertEqual(tracker.attempts.contexts, {})
                self.assertFalse((self.directory / 'external-run.json').exists())
                self.assertFalse((self.directory / 'boss-attempts.json').exists())

    def test_leaving_active_speedrun_closes_observation_and_never_resumes_it(self):
        self.fresh_run()
        tracker = self.tracker
        original = tracker.external_run.record['recordId']
        elapsed = tracker.external_run.record['elapsedSeconds']
        boss = app.BY_ID[app.MAJOR[0]]
        with self.transaction():
            tracker.attempts.observe(tracker.context, tracker.stats, tracker.killed,
                [dict(handle='boss', name=boss['name'], hp=1000, maxHp=1000)],
                ready=True, live_available=True, process_state='running',
                boss_resolver=lambda name: app.MAJOR[0], boss_names=app.BOSS_NAMES,
                category_key=tracker.run_policy.selected_id)
        self.assertIsNotNone(tracker.attempts.snapshot()['active'])
        tracker.action(dict(action='overlayView', view='home'))
        self.assertEqual(tracker.external_run.record['status'], 'interrupted')
        self.assertIsNone(tracker.attempts.snapshot()['active'])
        self.assertEqual(tracker.attempts.snapshot()['lastAttempt']['outcome'], 'interrupted')
        self.assertFalse(tracker.run_policy.can_record(tracker.context))
        self.cycle('Running', 3)
        tracker.action(dict(action='overlayView', view='speedrun'))
        self.cycle('Running', 5)
        self.assertEqual(tracker.external_run.record['recordId'], original)
        self.assertEqual(tracker.external_run.record['status'], 'interrupted')
        self.assertEqual(tracker.external_run.record['elapsedSeconds'], elapsed)
        self.assertFalse(tracker.run_policy.can_record(tracker.context))
        self.assertTrue(tracker.integrity.verify())

    def test_completed_run_export_remains_available_after_returning_home(self):
        self.fresh_run()
        self.cycle('Ended', 100)
        self.tracker.action(dict(action='overlayView', view='home'))
        self.assertFalse(self.tracker.run_policy.can_record(self.tracker.context))
        self.assertTrue(self.tracker.run_policy.can_export(self.tracker.context))
        self.assertTrue(self.tracker.run_state()['exportAvailable'])
        self.assertEqual(self.tracker.external_run.record['status'], 'finished')
        report = self.tracker.export_run()
        self.assertTrue(self.decrypt(report).trusted)

    def test_category_lineup_automatically_changes_and_personal_route_is_preserved(self):
        personal = [2054390800, 15000800]  # Bayle and Malenia, not the Any% route.
        self.tracker.action(dict(action='route', route=personal, contextKey=self.tracker.context))
        self.tracker.action(dict(action='runCategory', categoryId='any-percent-glitchless'))
        self.tracker.action(dict(action='overlayView', view='speedrun'))
        route = self.tracker.state()['route']
        self.assertIn(19000800, route)
        self.assertNotIn(2054390800, route)
        self.assertNotEqual(route, personal)
        with self.assertRaisesRegex(ValueError, 'category controls this lineup'):
            self.tracker.action(dict(action='route', route=personal, contextKey=self.tracker.context))
        self.tracker.action(dict(action='runCategory', categoryId='defeat-consort-glitchless'))
        self.assertEqual(self.tracker.state()['route'], [1252380800, 12050800, 21010800, 2044450800, 20010800])
        self.tracker.action(dict(action='runCategory', categoryId='custom', customName='My route'))
        self.assertEqual(self.tracker.state()['route'], personal)
        self.tracker.action(dict(action='overlayView', view='home'))
        self.assertEqual(self.tracker.state()['route'], personal)

    def test_category_is_fixed_during_active_run(self):
        self.fresh_run()
        with self.assertRaisesRegex(ValueError, 'category is fixed'):
            self.tracker.action(dict(action='runCategory', categoryId='all-remembrances-glitchless'))
        self.assertEqual(self.tracker.run_policy.selected_id, 'any-percent-glitchless')
        self.assertTrue(self.tracker.integrity.verify())

    def test_new_journey_does_not_unlock_recording(self):
        self.fresh_run()
        self.cycle('Ended', 100)
        self.tracker.context = 'v2:fresh_character:j2'
        self.tracker.stats['journey'] = 2
        self.cycle('NotRunning', 0)
        self.assertFalse(self.tracker.run_policy.can_record(self.tracker.context))
        audit = self.tracker.run_policy.audit_for_start(self.tracker.context, self.tracker.external_timer)
        self.assertFalse(audit['eligible'])
        self.assertIn('new character', audit['reason'])

    def test_record_edit_blocks_export_and_all_timing_actions(self):
        self.fresh_run()
        self.cycle('Ended', 100)
        path = self.directory / 'external-run.json'
        path.write_text(path.read_text() + ' ', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'changed, added, or removed'):
            self.tracker.export_run()
        for payload in (dict(action='speedrun', op='reset', contextKey=self.tracker.context),
                        dict(action='timingMode', mode='practice'),
                        dict(action='runCategory', categoryId='all-remembrances-glitchless')):
            with self.subTest(action=payload['action']):
                with self.assertRaises(ValueError):
                    self.tracker.action(payload)
        self.assertFalse(self.tracker.state()['speedrun']['exportAvailable'])
        self.assertTrue(self.tracker.state()['recordIntegrity']['locked'])

    def test_signed_active_checkpoint_recovers_once_inside_startup_transaction(self):
        checkpoint = self.checkpoint_active_boss()
        context = self.tracker.context
        for restart in range(2):
            with self.subTest(restart=restart):
                with patch('app.discover_saves', return_value=[]), patch('app.LiveReader', return_value=Mock()):
                    restored = app.Tracker(self.directory, recover_interrupted=True)
                self.assertFalse(restored.integrity.tainted, restored.integrity.notice)
                self.assertTrue(restored.integrity.verify())
                self.assertIsNone(restored.attempts.active)
                records = restored.attempts.contexts[context]['records']
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]['recordId'], checkpoint['recordId'])
                self.assertEqual(records[0]['outcome'], 'interrupted')
                self.assertEqual(records[0]['elapsedSeconds'], checkpoint['elapsedSeconds'])
                self.assertFalse(records[0]['eligibleForBenchmark'])
                stored = json.loads((self.directory / 'boss-attempts.json').read_text())
                self.assertIsNone(stored['active'])
                self.assertEqual(stored['contexts'][context]['records'], records)

    def test_tainted_startup_preserves_timing_files_and_allows_view_switch_and_stop(self):
        self.checkpoint_active_boss()
        history = self.directory / 'boss-attempts.json'
        history.write_bytes(history.read_bytes()+b' ')
        expected = self.protected_record_bytes()
        with patch('app.discover_saves', return_value=[]), patch('app.LiveReader', return_value=Mock()):
            restored = app.Tracker(self.directory, recover_interrupted=True)
        self.assertTrue(restored.integrity.tainted)
        self.assertEqual(self.protected_record_bytes(), expected)
        for view in ('home', 'combat', 'speedrun', 'home'):
            with self.subTest(view=view):
                restored.action(dict(action='overlayView', view=view))
                self.assertEqual(restored.cfg['overlayView'], view)
                self.assertEqual(self.protected_record_bytes(), expected)
                self.assertFalse(restored.state()['speedrun']['exportAvailable'])
        restored.action(dict(action='stop'))
        self.assertTrue(restored.stop.is_set())
        self.assertEqual(self.protected_record_bytes(), expected)

    def test_detecting_taint_during_view_change_does_not_persist_active_observations(self):
        self.checkpoint_active_boss()
        self.tracker.stop = threading.Event()
        history = self.directory / 'external-run.json'
        history.write_bytes(history.read_bytes()+b' ')
        expected = self.protected_record_bytes()
        self.assertFalse(self.tracker.integrity.tainted)
        for view in ('home', 'combat', 'speedrun'):
            self.tracker.action(dict(action='overlayView', view=view))
            self.assertTrue(self.tracker.integrity.tainted)
            self.assertEqual(self.tracker.cfg['overlayView'], view)
            self.assertEqual(self.protected_record_bytes(), expected)
        self.tracker.action(dict(action='stop'))
        self.assertTrue(self.tracker.stop.is_set())
        self.assertEqual(self.protected_record_bytes(), expected)

    def test_live_detection_defaults_on_and_preserves_preference_on_save_switch(self):
        self.assertTrue(self.tracker.cfg['liveDetection'])
        self.assertTrue(self.tracker.live_enabled)
        first = self.directory / 'first.sl2'
        second = self.directory / 'second.co2'
        first.write_bytes(b'')
        second.write_bytes(b'')
        self.tracker.action(dict(action='save', path=str(first), slot=0))
        self.assertTrue(self.tracker.live_enabled)
        self.assertTrue(json.loads((self.directory / 'settings.json').read_text())['liveDetection'])
        self.tracker.action(dict(action='live', enabled=False))
        self.tracker.action(dict(action='save', path=str(second), slot=1))
        self.assertFalse(self.tracker.live_enabled)
        self.assertFalse(json.loads((self.directory / 'settings.json').read_text())['liveDetection'])

    def test_view_is_shared_and_persists_separately_from_layout(self):
        self.tracker.action(dict(action='overlayView', view='combat'))
        self.assertEqual(self.tracker.state()['overlayView'], 'combat')
        stored = json.loads((self.directory / 'settings.json').read_text())
        self.assertEqual(stored['overlayView'], 'combat')
        with self.assertRaises(ValueError):
            self.tracker.action(dict(action='overlayView', view='unknown'))
        self.tracker.action(dict(action='overlayView', view='home'))
        self.assertEqual(self.tracker.state()['overlayView'], 'home')

    def test_practice_mode_and_manual_controls_are_disabled_for_eligible_runs_too(self):
        self.fresh_run()
        with self.assertRaisesRegex(ValueError, 'Only automatic LiveSplit'):
            self.tracker.action(dict(action='timingMode', mode='practice'))
        for operation in ('start', 'pause', 'resume', 'finish', 'reset'):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(ValueError, 'Manual timer actions are disabled'):
                    self.action(operation)
        self.assertEqual(self.tracker.cfg['timingMode'], 'livesplit')
        self.assertEqual(self.tracker.external_run.record['status'], 'running')

    def test_legacy_practice_setting_migrates_to_automatic_timing(self):
        directory = self.directory / 'legacy-settings'
        directory.mkdir()
        (directory / 'settings.json').write_text('{"timingMode":"practice"}')
        with patch('app.discover_saves', return_value=[]), patch('app.LiveReader', return_value=Mock()):
            tracker = app.Tracker(directory)
        self.assertEqual(tracker.cfg['timingMode'], 'livesplit')
        self.assertTrue(tracker.run_state()['controlsLocked'])

    def test_manual_fight_actions_cannot_override_live_detection(self):
        self.tracker.live_enabled = True
        self.tracker.live.poll.return_value = ([dict(handle='1', name='Boss', hp=1000, maxHp=1000)],
                                               'Live boss data connected.')
        self.tracker.live_tick()
        with self.assertRaisesRegex(ValueError, 'automatically'):
            self.tracker.action(dict(action='manual', id=app.BOSSES[0]['id']))
        self.tracker.live_tick()
        self.assertIsNone(self.tracker.manual)
        self.assertEqual(self.tracker.state()['current']['name'], 'Boss')

    def test_encrypted_export_and_token_protection(self):
        url, headers = self.server()
        with self.assertRaises(HTTPError) as no_run:
            urlopen(Request(url + '/api/speedrun/export', headers=headers))
        self.assertEqual(no_run.exception.code, 400)
        self.assertIn('Timing export is locked', no_run.exception.read().decode('utf-8'))
        no_run.exception.close()
        self.fresh_run()
        self.cycle('Ended', 100)
        with urlopen(Request(url + '/api/speedrun/export', headers=headers)) as response:
            self.assertEqual(response.headers.get_content_type(), 'application/vnd.tarnished-lineup.run+json')
            encoded = response.read()
            report = self.decrypt(encoded).payload['reportText']
        self.assertNotIn(b'Test Tarnished', encoded)
        self.assertIn('Test Tarnished', report)
        self.assertNotIn(str(self.directory), report)
        self.assertTrue(self.decrypt(encoded).trusted)
        body = json.dumps(dict(action='overlayView', view='speedrun')).encode()
        with self.assertRaises(HTTPError) as blocked:
            urlopen(Request(url + '/api/action', data=body, headers=headers))
        self.assertEqual(blocked.exception.code, 403)
        blocked.exception.close()
        headers['X-Tracker-Token'] = self.tracker.token
        with urlopen(Request(url + '/api/action', data=body, headers=headers)) as response:
            self.assertTrue(json.load(response)['ok'])
        self.assertEqual(self.tracker.state()['overlayView'], 'speedrun')


if __name__ == '__main__':
    unittest.main()
