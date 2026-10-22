"""Bundled reference contracts and phase regressions; no network/game needed."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from combat_reference import CombatReference, ATTACK_TYPES, STATUS_TYPES, clean_reference


class CombatDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bosses = json.loads((ROOT / 'data/bosses.json').read_text(encoding='utf-8'))
        cls.raw = json.loads((ROOT / 'data/boss-combat.json').read_text(encoding='utf-8'))
        cls.reference = CombatReference(ROOT / 'data/boss-combat.json', cls.bosses)

    def test_every_catalog_id_has_explicit_sourced_reference_or_unknowns(self):
        self.assertEqual(set(self.raw['entries']), {str(b['id']) for b in self.bosses})
        self.assertTrue(self.raw['referenceVersion'])
        for boss_id, raw in self.raw['entries'].items():
            for entry in [raw, *raw.get('phaseVariants', [])]:
                with self.subTest(boss=boss_id, phase=entry.get('matchNames')):
                    self.assertTrue(entry['sources'])
                    self.assertTrue(all(s.startswith('https://') for s in entry['sources']))
                    for key, valid in [('deals', ATTACK_TYPES), ('weakTo', ATTACK_TYPES), ('inflicts', STATUS_TYPES)]:
                        self.assertIn(key, entry)
                        if entry[key] is not None:
                            self.assertIsInstance(entry[key], list)
                            self.assertTrue(set(entry[key]) <= valid)
                    parsed = clean_reference(entry)
                    self.assertEqual(set(parsed['weakTo'] or []), set(entry['weakTo'] or []))
                    if entry.get('negation') is not None:
                        self.assertEqual(parsed['negation'], entry['negation'])

    def test_radagon_does_not_reuse_elden_beast_weakness(self):
        radagon = self.reference.for_boss(19000800, 'Radagon of the Golden Order')
        beast = self.reference.for_boss(19000800, 'Elden Beast')
        self.assertEqual(radagon['weakTo'], ['fire'])
        self.assertEqual(set(beast['weakTo']), {'standard', 'strike', 'slash', 'pierce'})

    def test_lion_damage_status_and_duplicate_arena_handling(self):
        belurat = self.reference.for_boss(20000800)
        rauh = self.reference.for_boss(2046460800)
        self.assertEqual(set(belurat['deals']), {'physical', 'magic', 'lightning'})
        self.assertEqual(belurat['inflicts'], ['frost'])
        self.assertIn('deathBlight', rauh['inflicts'])
        self.assertEqual(set(belurat['weakTo']), {'pierce', 'fire'})
        shared = self.reference.for_live_name('Divine Beast Dancing Lion')
        self.assertEqual(shared['weakTo'], belurat['weakTo'])
        self.assertIsNone(shared['inflicts'], 'An unresolved arena must not imply death blight or its absence')

    def test_player_copy_encounters_do_not_claim_fixed_defenses(self):
        for boss_id in (12020850, 30202800):
            with self.subTest(boss=boss_id):
                entry = self.reference.for_boss(boss_id)
                self.assertIsNone(entry['negation'])
                self.assertIsNone(entry['weakTo'])


if __name__ == '__main__':
    unittest.main()
