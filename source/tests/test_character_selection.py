"""Synthetic save observations: no game processes or private save files required."""
import copy
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from save_reader import profiles, select_profile


def character(slot, name, seconds):
    return dict(slot=slot, name=name, seconds=seconds, level=100)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.initial = [character(0, 'First', 360000), character(1, 'Second', 600)]

    def test_startup_uses_selection_not_largest_clock(self):
        chosen, source, _ = select_profile(self.initial, 1)
        self.assertEqual((chosen['slot'], chosen['seconds'], source), (1, 600, 'selected-character'))

    def test_unique_advancing_clock_follows_each_character(self):
        first = copy.deepcopy(self.initial)
        first[0]['seconds'] += 10
        chosen, source, _ = select_profile(first, 1, self.initial)
        self.assertEqual((chosen['slot'], source), (0, 'observed-save'))
        second = copy.deepcopy(first)
        second[1]['seconds'] += 5
        chosen, source, _ = select_profile(second, 0, first)
        self.assertEqual((chosen['slot'], chosen['seconds'], source), (1, 605, 'observed-save'))

    def test_no_clock_change_preserves_selection(self):
        chosen, source, _ = select_profile(self.initial, 1, self.initial)
        self.assertEqual((chosen['slot'], source), (1, 'unchanged'))

    def test_multiple_changed_clocks_do_not_guess(self):
        changed = copy.deepcopy(self.initial)
        changed[0]['seconds'] += 10
        changed[1]['seconds'] += 20
        chosen, source, _ = select_profile(changed, 0, self.initial)
        self.assertEqual((chosen['slot'], source), (0, 'ambiguous-save'))

    def test_rollback_and_replaced_character_do_not_guess(self):
        for modification in ('rollback', 'rename', 'new-slot'):
            changed = copy.deepcopy(self.initial)
            if modification == 'rollback':
                changed[1]['seconds'] -= 10
            elif modification == 'rename':
                changed[1]['name'] = 'Replacement'
                changed[1]['seconds'] += 10
            else:
                changed.append(character(2, 'New', 10))
            with self.subTest(modification=modification):
                chosen, source, _ = select_profile(changed, 0, self.initial)
                self.assertEqual((chosen['slot'], source), (0, 'ambiguous-save'))

    def test_only_character_is_unambiguous(self):
        chosen, source, _ = select_profile([self.initial[1]], 0)
        self.assertEqual((chosen['slot'], source), (1, 'single-character'))

    def test_invalid_metadata_is_rejected(self):
        for key, value in [('seconds', -1), ('seconds', True), ('slot', 10), ('name', None)]:
            bad = copy.deepcopy(self.initial)
            bad[1][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                select_profile(bad, 0)
        with self.assertRaises(ValueError):
            select_profile([self.initial[0], self.initial[0]], 0)


class ProfileParserTests(unittest.TestCase):
    def test_independent_per_character_seconds_and_invalid_summary(self):
        import hashlib
        base = 0x19003B0
        data = bytearray(base + 0x60000)
        def seal_summary():
            data[base - 16:base] = hashlib.md5(data[base:base + 0x60000]).digest()
        data[:4] = b'BND4'
        for slot, name, seconds in [(0, 'First', 999999), (4, 'Second', 125)]:
            data[base + 0x1954 + slot] = 1
            pos = base + 0x195E + slot * 0x24C
            encoded = name.encode('utf-16-le')
            data[pos:pos + len(encoded)] = encoded
            struct.pack_into('<II', data, pos + 0x22, 120, seconds)
        seal_summary()
        parsed = profiles(data)
        self.assertEqual([(p['slot'], p['seconds']) for p in parsed], [(0, 999999), (4, 125)])
        data[base + 0x1954 + 1] = 2
        seal_summary()
        with self.assertRaisesRegex(ValueError, 'metadata'):
            profiles(data)
        data[base + 0x1954 + 1] = 0
        struct.pack_into('<I', data, base + 0x195E + 0x22, 0)
        seal_summary()
        with self.assertRaisesRegex(ValueError, 'level'):
            profiles(data)


class TrackerSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.save_path = self.directory / 'synthetic.sl2'
        self.save_path.write_bytes(b'synthetic only')
        self.snapshot = [character(0, 'First', 360000), character(1, 'Second', 600)]
        self.timestamp = 1700000000000000000
        for target, replacement in [
            ('app.discover_saves', lambda: []),
            ('app.LiveReader', lambda _: None),
            ('app.read_stable', lambda _: b'synthetic only'),
            ('app.profiles', lambda _: copy.deepcopy(self.snapshot)),
            ('app.slot_state', self.slot_state),
        ]:
            mocker = patch(target, replacement)
            mocker.start()
            self.addCleanup(mocker.stop)
        self.tracker = app.Tracker(self.directory / 'settings')
        self.tracker.cfg.update(save=str(self.save_path), slot=1)

    def slot_state(self, data, slot, bosses, bst):
        profile = next(p for p in self.snapshot if p['slot'] == slot)
        return dict(name=profile['name'], level=profile['level'], origin='Hero', runes=50,
                    deaths=slot + 2, killed=[], version=262, journey=1, originId=2, startingGift=3)

    def update_save(self):
        self.timestamp += 1000000000
        os.utime(self.save_path, ns=(self.timestamp, self.timestamp))
        self.tracker.read_save()

    def test_switches_keep_character_contexts_and_clear_old_fight(self):
        self.update_save()
        second_context = self.tracker.context
        second_route = [app.BOSSES[0]['id']]
        self.tracker.context_cfg().update(enemyKills=22, route=second_route)
        self.tracker.manual = app.BOSSES[0]['id']
        self.tracker.fight_since = 1
        self.tracker.bars = [{'name': 'old fight'}]
        self.snapshot[0]['seconds'] += 10
        self.update_save()
        first_context = self.tracker.context
        self.assertNotEqual(first_context, second_context)
        self.assertIsNone(self.tracker.manual)
        self.assertIsNone(self.tracker.fight_since)
        self.assertEqual(self.tracker.bars, [])
        self.assertEqual(self.tracker.context_cfg()['enemyKills'], 0)
        self.tracker.context_cfg()['enemyKills'] = 11
        self.snapshot[1]['seconds'] += 5
        self.update_save()
        self.assertEqual(self.tracker.context, second_context)
        self.assertEqual(self.tracker.context_cfg()['enemyKills'], 22)
        self.assertEqual(self.tracker.context_cfg()['route'], second_route)
        self.assertEqual(self.tracker.state()['stats']['seconds'], 605)
        self.assertEqual(self.tracker.state()['characterSelectionSource'], 'observed-save')
        self.assertEqual(self.tracker.cfg['contexts'][first_context]['enemyKills'], 11)

    def test_no_aggregation_or_uptime_increment_and_ambiguous_selection(self):
        self.update_save()
        with patch('app.time.monotonic', return_value=999999999), patch('app.time.time', return_value=999999999):
            self.assertEqual(self.tracker.state()['stats']['seconds'], 600)
        self.snapshot[0]['seconds'] += 10
        self.snapshot[1]['seconds'] += 20
        self.update_save()
        self.assertEqual(self.tracker.cfg['slot'], 1)
        self.assertEqual(self.tracker.stats['seconds'], 620)
        self.assertEqual(self.tracker.character_selection_source, 'ambiguous-save')
        # A file update without clock changes retains the warning and selection.
        self.update_save()
        self.assertEqual(self.tracker.character_selection_source, 'ambiguous-save')
        self.assertEqual(self.tracker.cfg['slot'], 1)

    def test_manual_selection_resets_evidence_baseline(self):
        self.update_save()
        self.snapshot[0]['seconds'] += 10
        self.update_save()
        self.assertEqual(self.tracker.cfg['slot'], 0)
        # Explicitly selecting Second must not reapply an old First delta.
        self.tracker.action(dict(action='save', path=str(self.save_path), slot=1))
        self.update_save()
        self.assertEqual(self.tracker.cfg['slot'], 1)
        self.assertEqual(self.tracker.stats['seconds'], 600)
        self.assertEqual(self.tracker.character_selection_source, 'selected-character')
        self.tracker.read_save()
        self.assertEqual(self.tracker.cfg['slot'], 1)
        # Later evidence can follow another character on a new save.
        self.snapshot[0]['seconds'] += 10
        self.update_save()
        self.assertEqual(self.tracker.cfg['slot'], 0)

    def test_invalid_new_snapshot_does_not_replace_valid_context(self):
        self.update_save()
        previous_context = self.tracker.context
        self.snapshot[0]['seconds'] = -1
        self.update_save()
        self.assertEqual(self.tracker.context, previous_context)
        self.assertEqual(self.tracker.stats['seconds'], 600)
        self.assertIn('Invalid character profile metadata', self.tracker.status)
        self.assertEqual(self.tracker.profile_snapshot[0]['seconds'], 360000)


if __name__ == '__main__':
    unittest.main()
