"""Category lineups reference real encounters and cover their stated objectives."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_categories import (BASE_REMEMBRANCES, DLC_REMEMBRANCES, ENCOUNTERS,
                            ROUTES, category_route, category_route_note)


class CategoryRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bosses = json.loads((Path(__file__).resolve().parents[1] / 'data' / 'bosses.json').read_text(encoding='utf-8'))
        cls.by_id = {boss['id']: boss for boss in cls.bosses}

    def test_all_defined_encounters_match_the_actual_catalog(self):
        for identity, name in ENCOUNTERS.items():
            self.assertEqual(self.by_id[identity]['name'], name)
        for category in ROUTES:
            route = category_route(category, self.bosses)
            note = category_route_note(category, self.bosses)
            self.assertEqual(tuple(route), ROUTES[category])
            self.assertEqual(len(route), len(set(route)))
            self.assertIn('suggestion', note)

    def test_any_percent_chooses_two_runes_and_excludes_optional_dlc(self):
        route = category_route('any-percent-glitchless', self.bosses)
        note = category_route_note('any-percent-glitchless')
        self.assertIn(10000800, route)
        self.assertIn(14000800, route)
        self.assertEqual(route[-1], 19000800)
        self.assertTrue(all(not self.by_id[boss]['dlc'] for boss in route))
        self.assertNotIn(15000800, route)
        self.assertIn('Other legal routes', note)

    def test_no_dlc_remembrances_include_all_fifteen_and_access_encounters(self):
        route = category_route('all-remembrances-no-dlc-glitchless', self.bosses)
        self.assertEqual(len(BASE_REMEMBRANCES), 15)
        self.assertTrue(BASE_REMEMBRANCES.issubset(route))
        self.assertTrue({12020850, 12020800, 1051570800, 15000850}.issubset(route))
        self.assertTrue(all(not self.by_id[boss]['dlc'] for boss in route))

    def test_full_remembrances_include_all_twenty_five_and_heart_of_bayle(self):
        route = category_route('all-remembrances-glitchless', self.bosses)
        note = category_route_note('all-remembrances-glitchless')
        self.assertEqual(len(DLC_REMEMBRANCES), 10)
        self.assertTrue((BASE_REMEMBRANCES | DLC_REMEMBRANCES | {2054390800}).issubset(route))
        self.assertIn(20000800, route)  # Belurat Remembrance encounter, not Rauh duplicate.
        self.assertNotIn(2046460800, route)
        self.assertEqual(route[-1], 19000800)
        self.assertIn('Heart of Bayle', note)

    def test_consort_starts_with_base_game_access_and_preserves_nonboss_endpoint(self):
        route = category_route('defeat-consort-glitchless', self.bosses)
        note = category_route_note('defeat-consort-glitchless')
        self.assertEqual(route[:2], [1252380800, 12050800])
        self.assertEqual(route[-1], 20010800)
        self.assertIn('Circlet of Light', note)
        self.assertIn('main-menu', note)

    def test_custom_unknown_and_catalog_changes_never_invent_ids(self):
        for category in ('custom', '', 'unknown'):
            self.assertIsNone(category_route(category, self.bosses))
        changed = [dict(boss, name='changed') if boss['id'] == 10000800 else boss for boss in self.bosses]
        route = category_route('any-percent-glitchless', changed)
        note = category_route_note('any-percent-glitchless', changed)
        self.assertNotIn(10000800, route)
        self.assertIn('omitted', note)


if __name__ == '__main__':
    unittest.main()
