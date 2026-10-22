import json
from pathlib import Path
import unittest

from lineup_presets import build_presets, MAJOR, DLC_MAIN, OPTIONAL


BOSSES = json.loads((Path(__file__).resolve().parents[1]/'data'/'bosses.json').read_text(encoding='utf-8'))


class LineupPresetTests(unittest.TestCase):
    def test_exclusion_removes_dlc_from_every_option(self):
        presets = build_presets(BOSSES, False)
        dlc_ids = {boss['id'] for boss in BOSSES if boss['dlc']}
        self.assertEqual(list(presets), ['Major bosses', 'Major bosses + Optional', 'Optional', 'All encounters'])
        for label, ids in presets.items():
            self.assertFalse(dlc_ids.intersection(ids), label)
            self.assertNotIn('DLC', label)
        self.assertEqual(len(presets['All encounters']), 166)

    def test_legacy_inclusive_routes_and_names_preserved(self):
        presets = build_presets(BOSSES, True)
        self.assertEqual(list(presets), ['Major bosses', 'Major bosses + DLC', 'DLC main route',
                                        'DLC all encounters', 'Major + optional + DLC', 'All encounters'])
        self.assertEqual(presets['Major bosses + DLC'], list(dict.fromkeys(MAJOR+DLC_MAIN)))
        self.assertEqual(presets['DLC main route'], list(DLC_MAIN))
        self.assertEqual(presets['Major + optional + DLC'], list(dict.fromkeys(MAJOR+OPTIONAL+DLC_MAIN)))
        self.assertEqual(len(presets['DLC all encounters']), 42)
        self.assertEqual(len(presets['All encounters']), 208)

    def test_major_route_and_optional_choices_match_curated_base_encounters(self):
        presets = build_presets(BOSSES, False)
        base_ids = {boss['id'] for boss in BOSSES if not boss['dlc']}
        self.assertEqual(presets['Major bosses'], list(MAJOR))
        self.assertEqual(presets['Optional'], [i for i in OPTIONAL if i in base_ids])
        self.assertEqual(presets['Major bosses + Optional'], list(dict.fromkeys(MAJOR+tuple(i for i in OPTIONAL if i in base_ids))))
        self.assertEqual(build_presets(BOSSES, True)['Major bosses'], list(MAJOR))

    def test_curated_ids_require_catalog_identity_match(self):
        changed = [dict(b) for b in BOSSES]
        changed[0]['name'] = 'Unrelated encounter'
        presets = build_presets(changed, True)
        self.assertNotIn(changed[0]['id'], presets['Major bosses'])

    def test_invalid_catalog_entries_and_duplicates_are_omitted(self):
        fixtures = [BOSSES[0], BOSSES[0], None, {'id': True, 'name': 'invalid', 'dlc': False},
                    {'id': 9, 'name': 'unknown DLC membership'}, {'id': 10, 'name': 'bad', 'dlc': 'false'}]
        result = build_presets(fixtures, False)
        self.assertEqual(result['All encounters'], [BOSSES[0]['id']])

    def test_presets_do_not_mutate_catalog(self):
        before = json.dumps(BOSSES, sort_keys=True)
        for include in (True, False):
            for ids in build_presets(BOSSES, include).values():
                self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(before, json.dumps(BOSSES, sort_keys=True))


if __name__ == '__main__':
    unittest.main()
