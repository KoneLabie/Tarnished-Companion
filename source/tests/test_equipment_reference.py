"""Independent named-section fixtures for last-saved build evidence."""
import hashlib
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from equipment_reference import ATTRIBUTES, _catalog, resolve_equipment, saved_build
from save_reader import slot_state, STRIDE
from tests.test_save_parser import synthetic_slot, container, BOSSES, BST


def build_slot(**options):
    data, positions = synthetic_slot(**options)
    character = positions['character']
    struct.pack_into('<8I', data, character+0x34, 40, 20, 20, 20, 35, 25, 20, 19)
    # Active slots are after separately serialized player/effect/equip-index sections.
    struct.pack_into('<3I', data, character+0x1b0+208+88, 1, 0, 1)
    projectile_count = struct.unpack_from('<I', data, positions['projectiles'])[0]
    armaments = positions['projectiles']+4+projectile_count*8
    struct.pack_into('<22I', data, armaments, *([0xffffffff]*22))
    struct.pack_into('<I', data, armaments, 1000000+900+7)  # Cold Dagger +7, left 1.
    struct.pack_into('<I', data, armaments+3*4, 0x80000000 | (1010000+10))  # Black Knife +10, right 2.
    struct.pack_into('<I', data, armaments+5*4, 110000)  # Unarmed, right 3.
    struct.pack_into('<4I', data, armaments+12*4, 0x10030d40, 0x10030da4, 0x10030e08, 0x10030e6c)
    struct.pack_into('<I', data, armaments+17*4, 0x200003e8)
    return data, positions, armaments


class EquipmentReferenceTests(unittest.TestCase):
    def test_dynamic_saved_build_resolves_attributes_and_equipment(self):
        data, _, _ = build_slot()
        build = slot_state(container(data), 0, BOSSES, BST)['build']
        self.assertEqual(build['status'], 'available')
        self.assertEqual((build['level'], build['class'], build['saveSlot']), (120, 'Hero', 0))
        self.assertEqual(build['attributes']['vigor'], 40)
        self.assertEqual(build['attributes']['arcane'], 19)
        weapons = build['equipment']['weapons']
        self.assertEqual((weapons[0]['name'], weapons[0]['upgradeLevel'], weapons[0]['affinity'], weapons[0]['active']),
                         ('Dagger', 7, 'Cold', True))
        self.assertEqual((weapons[3]['name'], weapons[3]['upgradeLevel'], weapons[3]['active']), ('Black Knife', 10, True))
        self.assertEqual(weapons[3]['rawItemId'], 0x80000000 | (1010000+10))
        self.assertEqual(build['equipment']['armor'][0]['name'], 'Banished Knight Helm')
        self.assertEqual(build['equipment']['armor'][3]['name'], 'Banished Knight Greaves')
        self.assertEqual(build['equipment']['talismans'][0]['name'], 'Crimson Amber Medallion')

    def test_projectile_lengths_and_older_versions_do_not_shift_loadout(self):
        for version, count in ((81, 0), (82, 7), (262, 31)):
            with self.subTest(version=version, count=count):
                data, _, _ = build_slot(version=version, projectiles=count)
                build = slot_state(container(data), 0, BOSSES, BST)['build']
                self.assertEqual(build['equipment']['weapons'][0]['name'], 'Dagger')
                self.assertEqual(build['equipment']['armor'][0]['name'], 'Banished Knight Helm')

    def test_full_armaments_block_used_instead_of_header_values(self):
        data, positions, _ = build_slot()
        header = positions['character']+0x1b0+208+88+28
        struct.pack_into('<22I', data, header, *([0xdeadbeef]*22))
        build = slot_state(container(data), 0, BOSSES, BST)['build']
        self.assertEqual(build['equipment']['weapons'][0]['name'], 'Dagger')

    def test_selected_slot_build_does_not_bleed_from_another_character(self):
        first, _, _ = build_slot()
        second, positions, armaments = build_slot(origin=7)
        struct.pack_into('<I', second, positions['character']+0x34, 60)
        struct.pack_into('<I', second, armaments, 110000)
        full = bytes(0x300) + hashlib.md5(first).digest() + first + hashlib.md5(second).digest() + second
        self.assertEqual(len(full), 0x310+STRIDE+len(second))
        one = slot_state(full, 0, BOSSES, BST)['build']
        two = slot_state(full, 1, BOSSES, BST)['build']
        self.assertEqual((one['saveSlot'], one['class'], one['attributes']['vigor']), (0, 'Hero', 40))
        self.assertEqual((two['saveSlot'], two['class'], two['attributes']['vigor']), (1, 'Samurai', 60))
        self.assertEqual(two['equipment']['weapons'][0]['name'], 'Unarmed')

    def test_invalid_attributes_and_active_slots_are_explicitly_unavailable(self):
        data, positions, _ = build_slot()
        char = positions['character']
        struct.pack_into('<I', data, char+0x34, 0xffffffff)
        struct.pack_into('<I', data, char+0x1b0+208+88+4, 9)
        build = slot_state(container(data), 0, BOSSES, BST)['build']
        self.assertEqual(build['status'], 'partial')
        self.assertIsNone(build['attributes']['vigor'])
        self.assertIsNone(build['equipment']['weapons'][0]['active'])
        self.assertIsNone(build['equipment']['activeWeaponSlots']['left'])
        self.assertEqual(build['attributes']['mind'], 20)

    def test_unknown_wrong_slot_and_impossible_upgrade_do_not_get_guessed_names(self):
        for raw, group in ((123456789, 'weapon'), (1010000+11, 'weapon'),
                           (1010000+900, 'weapon'), (0x10030d40, 'weapon'),
                           (0x10030d40, 'legs'), (0, 'head')):
            with self.subTest(raw=raw, group=group):
                item = resolve_equipment(raw, group, 'fixture')
                self.assertEqual(item['status'], 'unavailable')
                self.assertIsNone(item['name'])
                self.assertEqual(item['rawItemId'], raw)

    def test_empty_sentinels_and_unarmed_are_distinct_from_unknown(self):
        self.assertEqual(resolve_equipment(0xffffffff, 'head', 'head')['status'], 'empty')
        unarmed = resolve_equipment(110000, 'weapon', 'left-hand-1')
        self.assertEqual((unarmed['status'], unarmed['name']), ('empty', 'Unarmed'))
        self.assertEqual(resolve_equipment(0, 'weapon', 'left-hand-1')['status'], 'unavailable')

    def test_missing_reference_keeps_saved_ids_and_marks_names_unavailable(self):
        data, _, _ = build_slot()
        with patch('equipment_reference._catalog', return_value=({}, {})):
            build = slot_state(container(data), 0, BOSSES, BST)['build']
        self.assertEqual(build['status'], 'partial')
        self.assertEqual(build['equipment']['weapons'][0]['itemId'], 1000907)
        self.assertIsNone(build['equipment']['weapons'][0]['name'])
        self.assertEqual(build['attributes']['vigor'], 40)

    def test_corrupt_or_truncated_save_never_yields_build(self):
        data, _, _ = build_slot()
        complete = bytearray(container(data))
        with self.assertRaises(ValueError):
            slot_state(complete[:-1], 0, BOSSES, BST)
        complete[1000] ^= 1
        with self.assertRaisesRegex(ValueError, 'checksum'):
            slot_state(complete, 0, BOSSES, BST)
        with self.assertRaisesRegex(ValueError, 'truncated'):
            saved_build(b'\0'*64, 0, 40, slot=0, level=1, origin='Wretch')

    def test_read_only_snapshot_contains_no_inventory_or_password_fields(self):
        data, _, _ = build_slot()
        before = bytes(data)
        build = slot_state(container(data), 0, BOSSES, BST)['build']
        self.assertEqual(bytes(data), before)
        self.assertEqual(set(build), {'status','source','saveSlot','level','class','attributes','equipment','notice','issues'})
        self.assertEqual(set(build['attributes']), set(ATTRIBUTES))
        self.assertEqual(set(build['equipment']), {'weapons','armor','talismans','activeWeaponSlots'})

    def test_reference_has_bounded_entries_sources_and_dlc_names(self):
        items, anchors = _catalog()
        self.assertGreater(len(items), 1500)
        self.assertGreater(len(anchors), 3000)
        self.assertEqual(items[0x105071c0]['name'], 'Circlet of Light')
        raw = json.loads((Path(__file__).resolve().parents[1]/'data'/'equipment-catalog.json').read_text(encoding='utf-8'))
        self.assertEqual(len(raw['sources']), 9)
        self.assertEqual(raw['license'], 'GPL-3.0')
        self.assertTrue(all(len(value['sha256']) == 64 for value in raw['sources'].values()))


if __name__ == '__main__':
    unittest.main()
