"""Simulated scenes honor the supplied content catalog and never invent bosses."""
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import preview_states as preview
from run_categories import category_route


class PreviewStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((ROOT / 'data' / 'bosses.json').read_text(encoding='utf-8'))
        portraits = json.loads((ROOT / 'data' / 'portraits.json').read_text(encoding='utf-8'))
        for boss in cls.catalog:
            entry = portraits.get(str(boss['id']))
            boss['portrait'] = '/portraits/' + Path(entry['src']).name if entry else None
        cls.base = [deepcopy(boss) for boss in cls.catalog if not boss['dlc']]
        cls.by_id = {boss['id']: boss for boss in cls.catalog}

    def strings(self, value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from self.strings(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from self.strings(item)

    def assert_detached_json(self, state, catalog):
        json.dumps(state, allow_nan=False)
        self.assertTrue(state['simulation'])
        self.assertTrue(state['preview'])
        self.assertEqual(state['save'], '')
        self.assertEqual(state['saves'], [])
        self.assertFalse(state['speedrun']['sourceVerified'])
        self.assertEqual(state['bosses'], catalog)
        self.assertIsNot(state['bosses'], catalog)
        self.assertIsNot(state['bosses'][0], catalog[0])
        for boss in state['upcoming'] + state['recent']:
            self.assertEqual(boss['name'], self.by_id[boss['id']]['name'])
        if state['current']:
            self.assertEqual(state['current']['name'], self.by_id[state['current']['id']]['name'])
            self.assertIsNotNone(state['current']['portrait'])

    def test_every_base_scene_contains_only_available_content(self):
        original = deepcopy(self.base)
        base_ids = {boss['id'] for boss in self.base}
        excluded = re.compile(r'\bDLC\b|Shadow of the Erdtree|Messmer|Rellana|Consort of Miquella', re.I)
        for scene in preview.SCENES:
            with self.subTest(scene=scene):
                state = preview.preview_state(scene, self.base)
                self.assert_detached_json(state, self.base)
                self.assertEqual(state['runPolicy']['selectedId'], 'any-percent-glitchless')
                self.assertEqual(state['runPolicy']['name'], 'Any% — Glitchless')
                self.assertEqual(state['externalTimer']['categoryName'], 'Any%')
                self.assertEqual(state['route'], category_route('any-percent-glitchless', self.base))
                self.assertTrue(set(state['route']) <= base_ids)
                self.assertTrue(set(state['killed']) <= base_ids)
                for split in state['speedrun']['splits']:
                    self.assertIn(split['bossId'], base_ids)
                    self.assertEqual(split['name'], self.by_id[split['bossId']]['name'])
                for value in self.strings(state):
                    self.assertIsNone(excluded.search(value), value)
        self.assertEqual(self.base, original)

    def test_base_featured_bosses_and_attempts_are_explicit(self):
        expected = {
            'fight': 'Malenia, Blade of Miquella',
            'combat': 'Rennala, Queen of the Full Moon',
            'running': 'Maliketh, the Black Blade',
        }
        for scene, name in expected.items():
            with self.subTest(scene=scene):
                state = preview.preview_state(scene, self.base)
                self.assertEqual(state['current']['name'], name)
        running = preview.preview_state('running', self.base)
        self.assertEqual(running['bossAttempts']['active']['name'], expected['running'])
        self.assertEqual(running['bossAttempts']['categoryId'], 'any-percent-glitchless')
        death = preview.preview_state('death', self.base)
        self.assertIsNone(death['bossAttempts']['active'])
        self.assertEqual(death['bossAttempts']['lastAttempt']['name'], expected['running'])
        self.assertEqual(death['bossAttempts']['lastAttempt']['outcome'], 'death')

    def test_base_splits_follow_the_base_route(self):
        running = preview.preview_state('running', self.base)
        self.assertEqual([s['name'] for s in running['speedrun']['splits']], [
            'Morgott, the Omen King', 'Fire Giant', 'Godskin Duo'
        ])
        finished = preview.preview_state('finished', self.base)
        self.assertEqual([s['name'] for s in finished['speedrun']['splits']], [
            'Maliketh, the Black Blade', 'Sir Gideon Ofnir, the All-Knowing',
            'Hoarah Loux, Warrior', 'Elden Beast'
        ])
        self.assertEqual(finished['completed'], finished['total'])
        self.assertEqual(finished['speedrun']['bossesDefeated'], finished['total'])
        self.assertEqual(finished['upcoming'], [])

    def test_full_catalog_keeps_the_expansion_examples(self):
        original = deepcopy(self.catalog)
        for scene in preview.SCENES:
            with self.subTest(scene=scene):
                state = preview.preview_state(scene, self.catalog)
                self.assert_detached_json(state, self.catalog)
                self.assertEqual(state['runPolicy']['selectedId'], 'all-remembrances-glitchless')
                self.assertEqual(state['runPolicy']['name'], 'All Remembrances — Glitchless')
                self.assertEqual(state['externalTimer']['categoryName'], 'All Remembrances')
                self.assertEqual(state['route'], category_route('all-remembrances-glitchless', self.catalog))
        self.assertEqual(preview.preview_state('combat', self.catalog)['current']['name'], 'Rellana, Twin Moon Knight')
        self.assertEqual(preview.preview_state('running', self.catalog)['current']['name'], 'Messmer the Impaler')
        self.assertEqual(preview.preview_state('death', self.catalog)['bossAttempts']['lastAttempt']['name'], 'Messmer the Impaler')
        self.assertEqual(self.catalog, original)

    def test_missing_featured_boss_is_an_error_not_an_unrelated_fallback(self):
        for scene, name in [
            ('fight', 'Malenia, Blade of Miquella'),
            ('combat', 'Rennala, Queen of the Full Moon'),
            ('running', 'Maliketh, the Black Blade'),
            ('finished', 'Hoarah Loux, Warrior'),
        ]:
            with self.subTest(scene=scene):
                catalog = [boss for boss in self.base if boss['name'] != name]
                with self.assertRaisesRegex(ValueError, 'missing the verified encounter'):
                    preview.preview_state(scene, catalog)

    def test_wrong_featured_identity_is_not_accepted_by_name(self):
        altered = deepcopy(self.base)
        boss = next(b for b in altered if b['name'] == 'Maliketh, the Black Blade')
        boss['id'] = 99999999
        with self.assertRaisesRegex(ValueError, 'missing the verified encounter'):
            preview.preview_state('running', altered)

    def test_invalid_scene_is_rejected_before_loading_reference_data(self):
        with patch.object(preview, '_references', side_effect=AssertionError('Must not read data')):
            for scene in ('', '../home', 'home&token=x', '<script>', None, 1):
                with self.subTest(scene=scene), self.assertRaisesRegex(ValueError, 'Unknown preview scene'):
                    preview.preview_state(scene, self.base)

    def test_invalid_or_unrelated_catalog_does_not_become_an_arbitrary_route(self):
        for catalog in (None, [], {}, [{'id': 1, 'name': 'Unrelated', 'dlc': False}]):
            with self.subTest(catalog=catalog), self.assertRaises(ValueError):
                preview.preview_state('home', catalog)

    def test_scene_result_changes_do_not_mutate_the_next_fixture(self):
        first = preview.preview_state('running', self.base)
        first['current']['name'] = 'Changed'
        first['runPolicy']['categories'][0]['name'] = 'Changed'
        first['bosses'][0]['name'] = 'Changed'
        second = preview.preview_state('running', self.base)
        self.assertEqual(second['current']['name'], 'Maliketh, the Black Blade')
        self.assertEqual(second['runPolicy']['name'], 'Any% — Glitchless')
        self.assertNotEqual(second['bosses'][0]['name'], 'Changed')

    def test_sample_report_is_explicitly_signed_encrypted_and_untrusted(self):
        for catalog in (self.base, self.catalog):
            state = preview.preview_state('finished', catalog)
            self.assertEqual(state['reportExport']['extension'], '.tlrun')
            self.assertTrue(state['reportExport']['encrypted'])
            self.assertIn('signed and encrypted', state['reportExport']['notice'])
            self.assertIn('ephemeral', state['reportExport']['notice'])
            self.assertIn('untrusted', state['reportExport']['notice'])
            self.assertIn('UNTRUSTED', state['recordIntegrity']['fingerprint'])
            self.assertTrue(state['speedrun']['exportAvailable'])
        for scene in ('home', 'fight', 'combat', 'armed', 'blocked'):
            self.assertFalse(preview.preview_state(scene, self.base)['speedrun']['exportAvailable'])

    def test_walkthrough_copy_has_no_content_exclusion_explanation(self):
        html = (ROOT / 'preview.html').read_text(encoding='utf-8')
        self.assertNotIn('DLC', html)
        self.assertNotIn('game-content settings', html)
        self.assertIn('ephemeral, untrusted signer', html)
        self.assertIn('signed, encrypted .tlrun sample', html)
        self.assertEqual(len(re.findall(r'<iframe\b', html)), 1)

    def test_published_record_examples_are_explicitly_simulated_and_category_matched(self):
        for catalog in (self.base, self.catalog):
            for scene in preview.SCENES:
                with self.subTest(expansion=bool(catalog[-1]['dlc']), scene=scene):
                    state = preview.preview_state(scene, catalog)
                    record = state['publishedRecord']
                    self.assertTrue(record['simulation'])
                    self.assertEqual(record['categoryId'], state['runPolicy']['selectedId'])
                    self.assertEqual(record['categoryId'], state['speedrun']['runPolicy']['categoryId'])
                    self.assertEqual(record['timingKey'], 'pc-soulsplitter-game-time')
                    self.assertFalse(record['bossTimesAvailable'])
                    self.assertIn('Simulated record data', record['notice'])
                    self.assertIn('not actual leaderboard records', record['notice'])
                    self.assertGreater(record['bestSeconds'], 0)
                    self.assertLessEqual(record['bestSeconds'], record['nearBestSeconds'])
                    self.assertLessEqual(record['nearBestSeconds'], record['averageSeconds'])


if __name__ == '__main__':
    unittest.main()

