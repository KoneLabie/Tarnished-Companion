"""Detected content filters the UI without erasing saved character routes."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class ContentIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        detector = patch('app.detect_dlc', return_value={
            'available': False, 'status': 'not-detected', 'notice': 'Synthetic content result.'
        })
        self.detector = detector.start()
        self.addCleanup(detector.stop)
        for target, result in [('app.discover_saves', []), ('app.LiveReader', Mock())]:
            mocker = patch(target, return_value=result)
            mocker.start()
            self.addCleanup(mocker.stop)
        self.tracker = self.make_tracker('first')
        self.base = next(b['id'] for b in app.BOSSES if not b['dlc'])
        self.other_base = next(b['id'] for b in app.BOSSES if not b['dlc'] and b['id'] != self.base)
        self.dlc = next(b['id'] for b in app.BOSSES if b['dlc'])

    def make_tracker(self, name):
        tracker = app.Tracker(self.root / name)
        tracker.context = 'v2:synthetic_content_character:j1'
        tracker.stats = dict(name='Synthetic Tarnished', level=10, seconds=30,
                             journey=1, deaths=0, origin='Hero', slot=0)
        tracker.save_status = 'connected'
        return tracker

    def detected(self, available):
        self.detector.return_value = {
            'available': available, 'status': 'synthetic', 'notice': 'Synthetic content result.'
        }

    def test_absent_content_has_exact_four_base_presets_and_defaults(self):
        tracker = self.tracker
        self.assertEqual(list(tracker.presets), [
            'Major bosses', 'Major bosses + Optional', 'Optional', 'All encounters'
        ])
        self.assertFalse(tracker.dlc['include'])
        self.assertTrue(all(not b['dlc'] for b in tracker.catalog))
        self.assertEqual(tracker.catalog_ids, {b['id'] for b in tracker.catalog})
        self.assertEqual(tracker.context_cfg()['route'], tracker.presets['Major bosses'])
        self.assertTrue(all(not app.BY_ID[i]['dlc'] for route in tracker.presets.values() for i in route))

    def test_confirmed_content_uses_six_presets_and_expanded_default(self):
        self.detected(True)
        tracker = self.make_tracker('with-content')
        self.assertTrue(tracker.dlc['include'])
        self.assertEqual(list(tracker.presets), [
            'Major bosses', 'Major bosses + DLC', 'DLC main route',
            'DLC all encounters', 'Major + optional + DLC', 'All encounters'
        ])
        self.assertEqual(tracker.context_cfg()['route'], tracker.presets['Major bosses + DLC'])
        self.assertEqual(tracker.catalog_ids, set(app.BY_ID))

    def test_unknown_or_nonboolean_detection_never_exposes_content(self):
        for available in (None, 1, 'true'):
            with self.subTest(available=available):
                self.detected(available)
                self.tracker.action({'action': 'rescanDlc'})
                self.assertFalse(self.tracker.dlc['include'])
                self.assertEqual(len(self.tracker.presets), 4)
                self.assertTrue(all(not b['dlc'] for b in self.tracker.state()['bosses']))

    def test_state_filters_visible_counts_but_preserves_full_route_ids(self):
        tracker = self.tracker
        saved = [self.base, self.dlc, self.other_base]
        tracker.context_cfg()['route'] = saved.copy()
        tracker.killed = {self.base, self.dlc}
        tracker.recent = [self.dlc, self.base]
        state = tracker.state()
        self.assertEqual(state['route'], saved)
        self.assertEqual(set(state['catalogBossIds']), set(app.BY_ID))
        self.assertEqual(state['killed'], [self.base])
        self.assertEqual(state['completed'], 1)
        self.assertEqual(state['total'], 2)
        self.assertEqual(state['catalogKilled'], 1)
        self.assertEqual([b['id'] for b in state['recent']], [self.base])
        self.assertEqual([b['id'] for b in state['upcoming']], [self.other_base])
        visible = tracker.display_route()
        visible.append(self.dlc)
        self.assertEqual(tracker.context_cfg()['route'], saved, 'Display routes must be fresh lists')

    def test_rescan_changes_catalog_and_future_defaults_without_rewriting_routes(self):
        tracker = self.tracker
        tracker.context_cfg()['route'] = [self.base, self.dlc]
        tracker.persist()
        settings_before = (tracker.dir / 'settings.json').read_bytes()
        self.detected(True)
        tracker.action({'action': 'rescanDlc'})
        self.assertIn(self.dlc, tracker.display_route())
        self.assertEqual(tracker.context_cfg()['route'], [self.base, self.dlc])
        self.detected(False)
        tracker.action({'action': 'rescanDlc'})
        self.assertEqual(tracker.display_route(), [self.base])
        self.assertEqual(tracker.context_cfg()['route'], [self.base, self.dlc])
        self.assertEqual((tracker.dir / 'settings.json').read_bytes(), settings_before)
        tracker.context = 'v2:another_synthetic_character:j1'
        self.assertEqual(tracker.context_cfg()['route'], tracker.presets['Major bosses'])

    def test_loading_settings_keeps_saved_hidden_content(self):
        directory = self.root / 'saved-settings'
        directory.mkdir()
        context = 'v2:synthetic_content_character:j1'
        (directory / 'settings.json').write_text(json.dumps({
            'contexts': {context: {'route': [self.base, self.dlc], 'enemyKills': 9}}
        }), encoding='utf-8')
        tracker = self.make_tracker('saved-settings')
        self.assertEqual(tracker.context_cfg()['route'], [self.base, self.dlc])
        self.assertEqual(tracker.context_cfg()['enemyKills'], 9)
        self.assertEqual(tracker.display_route(), [self.base])

    def test_route_action_preserves_existing_hidden_ids_but_rejects_new_additions(self):
        tracker = self.tracker
        tracker.context_cfg()['route'] = [self.base]
        with self.assertRaisesRegex(ValueError, 'currently available'):
            tracker.action({'action': 'route', 'route': [self.base, self.dlc]})
        self.assertEqual(tracker.context_cfg()['route'], [self.base])
        tracker.context_cfg()['route'] = [self.base, self.dlc]
        submitted = [self.dlc, self.other_base]
        tracker.action({'action': 'route', 'route': submitted})
        submitted.clear()
        self.assertEqual(tracker.context_cfg()['route'], [self.dlc, self.other_base])
        tracker.action({'action': 'route', 'route': [self.other_base]})
        with self.assertRaisesRegex(ValueError, 'currently available'):
            tracker.action({'action': 'route', 'route': [self.dlc, self.other_base]})

    def test_category_choices_and_actions_follow_detected_content(self):
        categories = self.tracker.state()['runPolicy']['categories']
        self.assertTrue(all('dlc' not in c['scope'].casefold() for c in categories))
        self.tracker.action({'action': 'runCategory', 'categoryId': 'any-percent-glitchless'})
        for category in ('all-remembrances-glitchless', 'defeat-consort-glitchless'):
            with self.subTest(category=category), self.assertRaisesRegex(ValueError, 'available'):
                self.tracker.action({'action': 'runCategory', 'categoryId': category})
        self.assertEqual(self.tracker.run_policy.selected_id, 'any-percent-glitchless')

    def test_unavailable_saved_category_prompts_without_destroying_its_selection(self):
        tracker = self.tracker
        self.detected(True)
        tracker.action({'action': 'rescanDlc'})
        tracker.action({'action': 'runCategory', 'categoryId': 'defeat-consort-glitchless'})
        tracker.action({'action': 'overlayView', 'view': 'speedrun'})
        self.assertTrue(any(app.BY_ID[i]['dlc'] for i in tracker.display_route()))
        self.detected(False)
        tracker.action({'action': 'rescanDlc'})
        policy = tracker.available_run_policy()
        self.assertTrue(policy['selectedUnavailable'])
        self.assertTrue(policy['needsSelection'])
        self.assertEqual(policy['selectedId'], '')
        self.assertEqual(policy['name'], '')
        self.assertEqual(tracker.display_route(), [])
        self.assertEqual(tracker.run_policy.selected_id, 'defeat-consort-glitchless')
        self.detected(True)
        tracker.action({'action': 'rescanDlc'})
        self.assertFalse(tracker.available_run_policy()['selectedUnavailable'])
        self.assertEqual(tracker.available_run_policy()['selectedId'], 'defeat-consort-glitchless')

    def test_actual_live_dlc_encounter_can_still_be_shown(self):
        boss = app.BY_ID[self.dlc]
        self.tracker.live_enabled = True
        self.tracker.bars = [dict(name=boss['name'], hp=100, maxHp=200)]
        state = self.tracker.state()
        self.assertEqual(state['current']['name'], boss['name'])
        self.assertEqual(state['current']['source'], 'Live game data')
        self.assertTrue(all(not b['dlc'] for b in state['bosses']))

    def test_manual_actions_are_rejected_without_changing_metrics_or_clock(self):
        self.tracker.fight_since = 123
        with patch.object(self.tracker.combat_metrics, 'reset') as reset:
            for boss_id in (self.base, None, 'invalid'):
                with self.subTest(boss_id=boss_id), self.assertRaisesRegex(ValueError, 'automatically'):
                    self.tracker.action({'action': 'manual', 'id': boss_id})
            reset.assert_not_called()
        self.assertIsNone(self.tracker.manual)
        self.assertEqual(self.tracker.fight_since, 123)

    def test_legacy_manual_field_cannot_create_a_display_encounter(self):
        self.tracker.manual = self.base
        self.tracker.bars = []
        self.assertIsNone(self.tracker.state()['current'])

    def test_read_save_gives_new_characters_the_detected_default(self):
        tracker = self.tracker
        save = self.root / 'synthetic.sl2'
        save.write_bytes(b'synthetic')
        tracker.cfg['save'] = str(save)
        roster = [dict(slot=0, name='New Synthetic', level=10, seconds=30)]
        saved = dict(name='New Synthetic', level=10, origin='Hero', originId=2,
                     startingGift=0, journey=1, runes=0, deaths=0, killed=[], version=262)
        original = app.resolve_context
        with patch('app.read_stable', return_value=b'synthetic'), \
                patch('app.profiles', return_value=copy.deepcopy(roster)), \
                patch('app.slot_state', return_value=copy.deepcopy(saved)), \
                patch('app.resolve_context', wraps=original) as resolve:
            tracker.read_save()
        self.assertEqual(tracker.save_status, 'connected', tracker.status)
        self.assertEqual(resolve.call_args.args[-1], tracker.default_route)
        self.assertEqual(tracker.context_cfg()['route'], tracker.presets['Major bosses'])


if __name__ == '__main__':
    unittest.main()

