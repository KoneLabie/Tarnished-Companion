"""Synthetic combat reference tests; no game install, save, or network required."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from combat_reference import CombatReference, DAMAGE_TYPES, clean_reference, unknown_combat


def negations(**changes):
    values = dict.fromkeys(DAMAGE_TYPES, 20)
    values.update(changes)
    return values


class CombatReferenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'combat.json'
        self.bosses = [
            dict(id=101, name='Shared Beast', location='First arena'),
            dict(id=102, name='Shared Beast', location='Second arena'),
            dict(id=103, name='First Form', location='Another arena'),
            dict(id=104, name='Unverified Encounter', location='No reference'),
        ]

    def load(self, entries, **extra):
        self.path.write_text(json.dumps(dict(schemaVersion=1, entries=entries, **extra)), encoding='utf-8')
        return CombatReference(self.path, self.bosses)

    def test_negation_derives_relative_weakness_without_trusting_declared_weakness(self):
        entry = clean_reference(dict(
            deals=['fire'], inflicts=['frost'],
            negation=negations(slash=-10, pierce=-10), weakTo=['holy'],
        ))
        self.assertEqual(entry['weakTo'], ['slash', 'pierce'])
        self.assertEqual(entry['negation']['slash'], -10)
        self.assertEqual(entry['deals'], ['fire'])
        self.assertEqual(entry['inflicts'], ['frost'])

    def test_equal_negation_is_no_relative_weakness_including_zero(self):
        for value in (-10, 0, 20, 100):
            with self.subTest(value=value):
                entry = clean_reference(dict(negation=dict.fromkeys(DAMAGE_TYPES, value)))
                self.assertEqual(entry['weakTo'], [])
                self.assertIsNone(entry['deals'])
                self.assertIsNone(entry['inflicts'])

    def test_unknown_is_not_equivalent_to_verified_empty(self):
        unverified = clean_reference({})
        known_empty = clean_reference(dict(deals=[], inflicts=[], weakTo=[]))
        for field in ('deals', 'inflicts', 'weakTo'):
            self.assertIsNone(unverified[field])
            self.assertEqual(known_empty[field], [])
        self.assertIsNone(unknown_combat()['negation'])

    def test_damage_and_status_domains_never_cross(self):
        correct = clean_reference(dict(deals=['physical', 'fire', 'fire'], inflicts=['bleed', 'frost'], weakTo=['magic', 'magic']))
        self.assertEqual(correct['deals'], ['physical', 'fire'])
        self.assertEqual(correct['inflicts'], ['bleed', 'frost'])
        self.assertEqual(correct['weakTo'], ['magic'])
        for field, values in [('deals', ['fire', 'frost']), ('inflicts', ['fire']),
                              ('weakTo', ['bleed']), ('deals', ['newElement']),
                              ('weakTo', [None]), ('inflicts', 'frost')]:
            with self.subTest(field=field, values=values):
                self.assertIsNone(clean_reference({field: values})[field])

    def test_incomplete_or_invalid_negation_stays_unknown(self):
        for invalid in (None, [], {}, {'fire': 0}, negations(fire=True), negations(fire='0'),
                        negations(fire=float('nan')), negations(fire=float('inf')),
                        negations(fire=101), negations(fire=10**400)):
            with self.subTest(invalid=invalid):
                result = clean_reference(dict(negation=invalid))
                self.assertIsNone(result['negation'])
                self.assertIsNone(result['weakTo'])

    def test_phase_match_does_not_inherit_base_weakness_or_status(self):
        reference = self.load({'103': dict(
            deals=['physical'], inflicts=['bleed'], negation=negations(fire=0),
            note='First form only', sources=['https://example.com/base'],
            phaseVariants=[dict(matchNames=['Second Form'], deals=['magic'], phaseLabel='Second phase', sources=['https://example.com/phase'])],
        )})
        base = reference.for_boss(103)
        self.assertEqual(base['weakTo'], ['fire'])
        phase = reference.for_boss(103, 'Second Form')
        self.assertEqual(phase['deals'], ['magic'])
        self.assertEqual(phase['phaseLabel'], 'Second phase')
        self.assertIsNone(phase['weakTo'])
        self.assertIsNone(phase['inflicts'])
        self.assertIsNone(phase['negation'])
        self.assertEqual(phase['note'], '')
        self.assertEqual(phase['sources'], ['https://example.com/phase'])
        unknown = reference.for_boss(103, 'Unrecognized Third Form')
        self.assertIsNone(unknown['deals'])
        self.assertIsNone(unknown['weakTo'])
        self.assertIn('phase', unknown['note'])
        self.assertEqual(reference.for_boss(103, 'First Form')['weakTo'], ['fire'])

    def test_phase_name_normalization_is_exact_not_substring_or_fuzzy(self):
        reference = self.load({'103': dict(
            deals=['physical'], weakTo=['slash'],
            phaseVariants=[dict(matchNames=['Second Form, Unbound'], deals=['holy'], weakTo=['fire'])],
        )})
        self.assertEqual(reference.for_boss(103, 'SECOND FORM — UNBOUND')['deals'], ['holy'])
        for name in ('Second Form', 'Another Second Form Unbound', 'Second Form Unbound Again'):
            with self.subTest(name=name):
                self.assertIsNone(reference.for_boss(103, name)['deals'])

    def test_ambiguous_name_keeps_only_fields_common_to_every_arena(self):
        first = dict(deals=['physical'], inflicts=['frost'], negation=negations(fire=0), sources=['https://example.com/a'])
        second = dict(deals=['physical'], inflicts=['poison'], negation=negations(magic=0), sources=['https://example.com/b'])
        reference = self.load({'101': first, '102': second})
        shared = reference.for_live_name('Shared Beast')
        self.assertEqual(shared['deals'], ['physical'])
        self.assertIsNone(shared['inflicts'])
        self.assertIsNone(shared['weakTo'])
        self.assertIsNone(shared['negation'])
        self.assertEqual(shared['sources'], ['https://example.com/a', 'https://example.com/b'])
        self.assertIn('arena unconfirmed', shared['note'])
        # Identical received-damage data can survive the unresolved arena.
        second['negation'] = first['negation']
        reference = self.load({'101': first, '102': second})
        self.assertEqual(reference.for_live_name('Shared Beast')['weakTo'], ['fire'])

    def test_missing_duplicate_reference_prevents_borrowing_other_arena_data(self):
        reference = self.load({'101': dict(deals=['physical'], inflicts=[], negation=negations(fire=0))})
        shared = reference.for_live_name('Shared Beast')
        self.assertIsNone(shared['deals'])
        self.assertIsNone(shared['inflicts'])
        self.assertIsNone(shared['weakTo'])
        self.assertIsNone(reference.for_boss(104)['deals'])
        self.assertIsNone(reference.for_live_name('Not in catalog')['weakTo'])

    def test_returned_references_cannot_mutate_the_reference_store(self):
        reference = self.load({'103': dict(deals=['fire'], negation=negations(holy=0), sources=['https://example.com/ref'])})
        snapshot = reference.for_boss(103)
        snapshot['deals'].append('magic')
        snapshot['negation']['holy'] = 100
        snapshot['sources'].clear()
        fresh = reference.for_boss(103)
        self.assertEqual(fresh['deals'], ['fire'])
        self.assertEqual(fresh['weakTo'], ['holy'])
        self.assertEqual(fresh['negation']['holy'], 0)
        self.assertEqual(fresh['sources'], ['https://example.com/ref'])

    def test_missing_or_malformed_file_disables_only_reference(self):
        invalid_files = ('', '{broken', '[]', 'null', '{"schemaVersion":2,"entries":{}}',
                         '{"schemaVersion":1,"entries":[]}', '{"schemaVersion":1,"entries":null}')
        reference = CombatReference(self.path, self.bosses)
        self.assertEqual(reference.entries, {})
        for data in invalid_files:
            with self.subTest(data=data):
                self.path.write_text(data, encoding='utf-8')
                reference = CombatReference(self.path, self.bosses)
                self.assertEqual(reference.entries, {})
                self.assertIsNone(reference.for_boss(103)['weakTo'])

    def test_invalid_entries_and_variants_are_ignored_without_breaking_good_entries(self):
        reference = self.load({
            'not-an-id': dict(deals=['fire']), '999': dict(deals=['fire']), '101': [],
            '103': dict(deals=['physical'], weakTo=['magic'], phaseVariants=[
                None, [], {}, dict(matchNames=[]), dict(matchNames='Second Form'),
                dict(matchNames=[123]), dict(matchNames=['Second Form'], deals=['holy']),
            ]),
        }, referenceVersion='synthetic-test')
        self.assertEqual(reference.version, 'synthetic-test')
        self.assertEqual(set(reference.entries), {103})
        self.assertEqual(reference.for_boss(103)['weakTo'], ['magic'])
        self.assertEqual(reference.for_boss(103, 'Second Form')['deals'], ['holy'])


if __name__ == '__main__':
    unittest.main()
