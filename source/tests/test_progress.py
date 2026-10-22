"""Progress remains save-driven across routes, slot reuse, journeys, and failures."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from progress_store import normalize_settings


class ProgressTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.save = self.root / 'synthetic.sl2'
        self.save.write_bytes(b'synthetic')
        self.roster = [dict(slot=0, name='Tarnished', level=100, seconds=10000)]
        self.saved = dict(name='Tarnished', level=100, origin='Hero', originId=2,
                          startingGift=3, journey=1, runes=0, deaths=9, killed=[], version=262)
        for target, value in [
            ('app.discover_saves', lambda: []),
            ('app.LiveReader', lambda _: None),
            ('app.read_stable', lambda _: b'synthetic'),
            ('app.profiles', lambda _: copy.deepcopy(self.roster)),
            ('app.slot_state', lambda *args: copy.deepcopy(self.saved)),
        ]:
            mocker = patch(target, value)
            mocker.start()
            self.addCleanup(mocker.stop)
        self.tracker = app.Tracker(self.root / 'settings')
        self.tracker.cfg['save'] = str(self.save)
        self.refresh()
        self.initial = self.tracker.context

    def refresh(self):
        self.tracker.signature = None
        self.tracker.read_save()
        self.assertEqual(self.tracker.save_status, 'connected', self.tracker.status)

    def test_out_of_order_completion_uses_flags_not_queue_position(self):
        route = app.DLC[:3]
        self.tracker.action(dict(action='route', route=route))
        self.saved['killed'] = [route[2]]
        self.refresh()
        result = self.tracker.state()
        self.assertEqual([b['id'] for b in result['upcoming']], route[:2])
        self.assertEqual(result['completed'], 1)
        self.assertEqual(result['catalogKilled'], 1)
        # An off-route boss still contributes to overall completion.
        self.saved['killed'].append(app.MAJOR[0])
        self.refresh()
        self.assertEqual(self.tracker.state()['catalogKilled'], 2)
        self.assertEqual(self.tracker.state()['completed'], 1)

    def test_journey_change_resets_counters_and_fight_keeps_lineup(self):
        self.tracker.context_cfg().update(route=app.DLC[:3], enemyKills=123)
        self.tracker.manual = app.DLC[0]
        self.tracker.recent = [app.MAJOR[0]]
        self.tracker.killed = {app.MAJOR[0]}
        self.saved['journey'] = 2
        self.roster[0]['seconds'] += 20
        self.refresh()
        self.assertNotEqual(self.tracker.context, self.initial)
        self.assertEqual(self.tracker.context_cfg()['enemyKills'], 0)
        self.assertEqual(self.tracker.context_cfg()['route'], app.DLC[:3])
        self.assertEqual(self.tracker.killed, set())
        self.assertEqual(self.tracker.recent, [])
        self.assertIsNone(self.tracker.manual)
        self.assertEqual(self.tracker.cfg['contexts'][self.initial]['enemyKills'], 123)
        self.assertEqual(self.tracker.stats['seconds'], 10020)
        # New-journey bosses already killed before opening the app stay killed.
        self.saved['killed'] = [app.DLC[2]]
        self.refresh()
        self.assertIn(app.DLC[2], self.tracker.killed)

    def test_renaming_character_does_not_reset_tracking(self):
        self.tracker.context_cfg()['enemyKills'] = 12
        self.saved['name'] = self.roster[0]['name'] = 'Renamed'
        self.roster[0]['seconds'] += 1
        self.refresh()
        self.assertEqual(self.tracker.context, self.initial)
        self.assertEqual(self.tracker.context_cfg()['enemyKills'], 12)

    def test_same_name_slot_reuse_or_rollback_starts_fresh(self):
        self.tracker.context_cfg()['enemyKills'] = 45
        self.roster[0]['seconds'] = 12
        self.saved['level'] = self.roster[0]['level'] = 9
        self.refresh()
        self.assertNotEqual(self.tracker.context, self.initial)
        self.assertEqual(self.tracker.context_cfg()['enemyKills'], 0)
        self.assertIn('earlier or replaced', self.tracker.tracking_notice)

    def test_origin_or_gift_change_is_replacement_evidence(self):
        for key in ('originId', 'startingGift'):
            with self.subTest(key=key):
                before = self.tracker.context
                self.tracker.context_cfg()['enemyKills'] = 7
                self.saved[key] += 1
                self.roster[0]['seconds'] += 100
                self.refresh()
                self.assertNotEqual(self.tracker.context, before)
                self.assertEqual(self.tracker.context_cfg()['enemyKills'], 0)

    def test_reader_failure_preserves_snapshot_but_marks_unready_and_recovers(self):
        self.tracker.manual = app.DLC[0]
        self.tracker.signature = None
        with patch('app.slot_state', side_effect=ValueError('Unsupported save version')):
            self.tracker.read_save()
        failed = self.tracker.state()
        self.assertFalse(failed['ready'])
        self.assertEqual(failed['saveStatus'], 'error')
        self.assertIsNotNone(failed['stats'])
        self.assertIsNone(failed['current'])
        self.assertEqual(failed['upcoming'], [])
        with self.assertRaisesRegex(ValueError, 'valid save'):
            self.tracker.action(dict(action='enemyKills', value=10))
        self.refresh()
        self.assertTrue(self.tracker.state()['ready'])
        self.assertEqual(self.tracker.context, self.initial)

    def test_saved_victory_and_recent_filters_restored_flags(self):
        boss = app.DLC[0]
        with self.assertRaisesRegex(ValueError, 'automatically'):
            self.tracker.action(dict(action='manual', id=boss))
        self.saved['killed'] = [boss]
        # Refresh invalidates only the file cache, not the previous snapshot.
        self.tracker.action(dict(action='refresh'))
        self.tracker.read_save()
        self.assertIsNone(self.tracker.manual)
        self.assertEqual(self.tracker.recent, [boss])
        self.saved['killed'] = []
        self.tracker.signature = ('previous',)
        self.tracker.read_save()
        self.assertEqual(self.tracker.recent, [])

    def test_stale_context_edits_are_rejected(self):
        for action in (dict(action='route', route=[]), dict(action='enemyKills', value=7), dict(action='resetTracking')):
            with self.subTest(action=action['action']), self.assertRaisesRegex(ValueError, 'character or journey changed'):
                self.tracker.action({**action, 'contextKey': 'old-context'})

    def test_explicit_local_reset_reloads_actual_flags_and_default_lineup(self):
        self.saved['killed'] = [app.DLC[0]]
        self.tracker.context_cfg().update(enemyKills=90, route=[])
        self.tracker.action(dict(action='resetTracking', contextKey=self.initial))
        self.refresh()
        self.assertNotEqual(self.tracker.context, self.initial)
        self.assertEqual(self.tracker.context_cfg()['enemyKills'], 0)
        self.assertEqual(self.tracker.context_cfg()['route'], app.PRESETS['Major bosses + DLC'])
        self.assertEqual(self.tracker.killed, {app.DLC[0]})
        self.assertEqual(self.save.read_bytes(), b'synthetic')

    def test_restart_preserves_current_journey_counter(self):
        self.saved['journey'] = 3
        self.refresh()
        context = self.tracker.context
        self.tracker.action(dict(action='enemyKills', value=18))
        self.tracker = app.Tracker(self.root / 'settings')
        self.refresh()
        self.assertEqual(self.tracker.context, context)
        self.assertEqual(self.tracker.context_cfg()['enemyKills'], 18)

    def test_observed_empty_slot_reuse_cannot_inherit_same_name_counters(self):
        self.tracker.action(dict(action='enemyKills', value=42))
        original = copy.deepcopy(self.roster)
        self.roster.clear()
        self.tracker.signature = None
        self.tracker.read_save()
        self.assertFalse(self.tracker.state()['ready'])
        self.assertIsNone(self.tracker.stats)
        self.roster[:] = original
        # Even an imported replacement with an increased clock starts fresh.
        self.roster[0]['seconds'] += 999
        self.refresh()
        self.assertNotEqual(self.tracker.context, self.initial)
        self.assertEqual(self.tracker.context_cfg()['enemyKills'], 0)

    def test_same_journey_flag_rollback_restarts_local_counter(self):
        self.saved['killed'] = [app.DLC[0]]
        self.refresh()
        self.tracker.action(dict(action='enemyKills', value=21))
        self.saved['killed'] = []
        self.roster[0]['seconds'] += 1
        self.refresh()
        self.assertNotEqual(self.tracker.context, self.initial)
        self.assertEqual(self.tracker.context_cfg()['enemyKills'], 0)
        self.assertIn('progress moved backwards', self.tracker.tracking_notice)


class ConfigurationAndIdentityTests(unittest.TestCase):
    def test_malformed_nested_settings_and_obsolete_boss_ids_are_normalized(self):
        for raw in (None, [], {'layout': None, 'contexts': None},
                    {'layout': {'width': 'wide', 'opacity': float('nan'), 'font': []}, 'slot': True},
                    {'layout': {'opacity': 10**400}}):
            with self.subTest(raw=raw):
                cfg = normalize_settings(raw, app.BY_ID, app.DLC)
                self.assertEqual(cfg['layout']['width'], 360)
                self.assertEqual(cfg['slot'], 0)
        boss = app.DLC[0]
        cfg = normalize_settings({'contexts': {'x': {'route': [boss, -1, boss, None], 'enemyKills': '9'}}}, app.BY_ID, app.DLC)
        self.assertEqual(cfg['contexts']['x'], dict(route=[boss], enemyKills=0))

    def test_duplicate_names_never_resolve_by_lineup_order(self):
        duplicates = [b['id'] for b in app.BOSSES if b['name']=='Divine Beast Dancing Lion']
        self.assertGreater(len(duplicates), 1)
        for route in (duplicates, duplicates[::-1], duplicates[:1], []):
            self.assertIsNone(app.match_boss('Divine Beast Dancing Lion', route, set()))
            self.assertIsNone(app.match_boss('Divine Beast Dancing Lion', route, set(duplicates[:1])))
        self.assertIsNone(app.match_boss('Godfrey, First Elden Lord', app.MAJOR, set()))
        self.assertEqual(app.match_boss('Base Serpent Messmer', [], set()), 21010800)
        self.assertIsNone(app.match_boss('Unknown new boss', app.MAJOR, set()))
        # Identical artwork can be shown without choosing an arena or boss flag.
        self.assertIsNotNone(app.shared_boss_portrait('Divine Beast Dancing Lion'))
        self.assertIsNone(app.shared_boss_portrait('Unknown new boss'))


if __name__ == '__main__':
    unittest.main()
