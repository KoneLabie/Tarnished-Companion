"""Synthetic binary fixtures for character/journey parsing and corrupt-save rejection."""
import hashlib
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from save_reader import FLAGS_SIZE, PROFILE_DATA_SIZE, PROFILE_DATA_START, SLOT_SIZE, profiles, slot_state, u32


BOSSES = [{'id': 1007}, {'id': 2008}, {'id': 2010}]
BST = {0: 0, 1: 1, 2: 2}


def synthetic_slot(version=262, cycle=0, origin=2, gift=3, projectiles=2, regions=3):
    """Serialize named sections independently so moving sections exercises the reader."""
    data = bytearray(struct.pack('<II', version, 0) + bytes(24))
    count = 0x13FE if version <= 81 else 0x1400
    # Exercise each item record length before the variable character-data offset.
    data += struct.pack('<II', 0x80000001, 123) + bytes(13)
    data += struct.pack('<II', 0x90000001, 456) + bytes(8)
    data += struct.pack('<II', 0xC0000001, 789)
    data += bytes((count - 3) * 8)
    positions = {'character': len(data)}
    character = bytearray(0x1B0)
    encoded_name = 'Tarnished'.encode('utf-16-le')
    character[0x94:0x94 + len(encoded_name)] = encoded_name
    struct.pack_into('<II', character, 0x60, 120, 9876)
    character[0xB7] = origin
    character[0xBB] = gift
    data += character
    data += bytes(13 * 16)  # SP effects
    data += bytes(88 + 28 + 88 + 88)  # Equipment records
    data += bytes(16 + 12 * 2688 + 12 * 384)  # Held inventory
    data += bytes(116 + 140 + 24)  # Spells, items and gestures
    positions['projectiles'] = len(data)
    data += struct.pack('<I', projectiles) + bytes(projectiles * 8)
    data += bytes(156 + 12 + 303)  # Armaments, physics and appearance
    data += bytes(16 + 12 * 0x780 + 12 * 0x80)  # Storage
    data += bytes(256)  # Gestures
    positions['regions'] = len(data)
    data += struct.pack('<I', regions) + bytes(regions * 4)
    data += bytes(40) + b'\x01' + bytes(68)  # Torrent, control, BloodStain
    positions['cycle'] = len(data)
    data += struct.pack('<II', cycle, 0)
    positions['menu'] = len(data) + 4
    data += struct.pack('<II', 0, 17) + bytes(17)
    data += bytes(52 + 0x1B588)  # Trophy and acquired-item data
    positions['tutorial'] = len(data) + 4
    data += struct.pack('<II', 0, 9) + bytes(9)
    data += bytes(3)
    data += struct.pack('<II', 47, 0) + bytes(1) + struct.pack('<II', 8, 12345)
    data += bytes(1) + bytes(8)  # Session flag, countdown and trailing scalar
    flags = bytearray(FLAGS_SIZE)
    for event in (1007, 2008):
        block, bit = divmod(event, 1000)
        flags[BST[block] * 125 + bit // 8] |= 1 << (7 - bit % 8)
    data += flags
    data += bytes(SLOT_SIZE - len(data))
    return data, positions


def container(slot):
    return bytes(0x300) + hashlib.md5(slot).digest() + slot


def profile_container():
    data = bytearray(PROFILE_DATA_START + PROFILE_DATA_SIZE)
    data[:4] = b'BND4'
    data[PROFILE_DATA_START + 0x1954] = 1
    name = PROFILE_DATA_START + 0x195E
    data[name:name + 8] = 'Hero'.encode('utf-16-le')
    struct.pack_into('<II', data, name + 0x22, 120, 123)
    seal_profiles(data)
    return data


def seal_profiles(data):
    data[PROFILE_DATA_START - 16:PROFILE_DATA_START] = hashlib.md5(
        data[PROFILE_DATA_START:PROFILE_DATA_START + PROFILE_DATA_SIZE]).digest()


class SaveParserTests(unittest.TestCase):
    def test_character_fields_and_independent_boss_flags(self):
        slot, _ = synthetic_slot(cycle=1, origin=7, gift=4)
        parsed = slot_state(container(slot), 0, BOSSES, BST)
        self.assertEqual(parsed['name'], 'Tarnished')
        self.assertEqual(parsed['journey'], 2)
        self.assertEqual((parsed['originId'], parsed['origin'], parsed['startingGift']), (7, 'Samurai', 4))
        self.assertEqual((parsed['level'], parsed['runes'], parsed['deaths']), (120, 9876, 47))
        self.assertEqual(parsed['killed'], [1007, 2008])

    def test_journey_is_not_capped_at_scaling_limit(self):
        for cycle in (0, 1, 7, 8, 42, 10000):
            with self.subTest(cycle=cycle):
                slot, _ = synthetic_slot(cycle=cycle)
                self.assertEqual(slot_state(container(slot), 0, BOSSES, BST)['journey'], cycle + 1)

    def test_dynamic_sections_and_old_item_count_do_not_shift_journey(self):
        for version, projectiles, regions in ((81, 0, 0), (82, 1, 7), (262, 13, 31)):
            with self.subTest(version=version):
                slot, _ = synthetic_slot(version=version, cycle=3, projectiles=projectiles, regions=regions)
                parsed = slot_state(container(slot), 0, BOSSES, BST)
                self.assertEqual((parsed['journey'], parsed['deaths'], parsed['killed']), (4, 47, [1007, 2008]))

    def test_invalid_journey_and_section_lengths_fail_closed(self):
        for section, value in (('cycle', 10001), ('cycle', 0xFFFFFFFF),
                               ('projectiles', 10001), ('regions', 10001),
                               ('menu', 0x10001), ('tutorial', 0x10001)):
            with self.subTest(section=section, value=value):
                slot, offsets = synthetic_slot()
                struct.pack_into('<I', slot, offsets[section], value)
                with self.assertRaises(ValueError):
                    slot_state(container(slot), 0, BOSSES, BST)

    def test_malformed_slot_name_is_a_value_error(self):
        slot, offsets = synthetic_slot()
        slot[offsets['character'] + 0x94:offsets['character'] + 0x96] = b'\x00\xd8'
        with self.assertRaisesRegex(ValueError, 'Character name'):
            slot_state(container(slot), 0, BOSSES, BST)

    def test_truncated_checksum_and_unsupported_version_are_rejected(self):
        slot, _ = synthetic_slot()
        full = bytearray(container(slot))
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            slot_state(full[:-1], 0, BOSSES, BST)
        full[-1] ^= 1
        with self.assertRaisesRegex(ValueError, 'checksum'):
            slot_state(full, 0, BOSSES, BST)
        struct.pack_into('<I', slot, 0, 999)
        with self.assertRaisesRegex(ValueError, 'Unsupported save version'):
            slot_state(container(slot), 0, BOSSES, BST)

    def test_classes_use_saved_archetype_order_and_unknown_stays_unknown(self):
        for origin, expected in ((6, 'Confessor'), (7, 'Samurai'), (8, 'Prisoner'),
                                 (10, 'Idus Knight'), (11, 'Heavy Knight'), (255, 'Unknown')):
            with self.subTest(origin=origin):
                slot, _ = synthetic_slot(origin=origin)
                self.assertEqual(slot_state(container(slot), 0, BOSSES, BST)['origin'], expected)

    def test_scalar_bounds_and_invalid_slots_are_value_errors(self):
        for data, position in ((b'\x00' * 4, -1), (b'\x00' * 3, 0), (b'\x00' * 4, 1)):
            with self.subTest(position=position), self.assertRaises(ValueError):
                u32(data, position)
        for slot in (-1, 10, True, '0', None):
            with self.subTest(slot=slot), self.assertRaises(ValueError):
                slot_state(b'', slot, BOSSES, BST)

    def test_profile_malformed_utf16_and_truncation_are_value_errors(self):
        data = profile_container()
        name = PROFILE_DATA_START + 0x195E
        data[name:name + 2] = b'\x00\xd8'
        seal_profiles(data)
        with self.assertRaisesRegex(ValueError, 'Character name'):
            profiles(data)
        with self.assertRaisesRegex(ValueError, 'truncated'):
            profiles(data[:-1])

    def test_valid_looking_changed_profile_is_rejected_until_checksum_matches(self):
        data = profile_container()
        self.assertEqual(profiles(data)[0]['seconds'], 123)
        # Still a plausible save clock: accepting it could switch characters.
        struct.pack_into('<I', data, PROFILE_DATA_START + 0x195E + 0x26, 124)
        with self.assertRaisesRegex(ValueError, 'Profile summary checksum'):
            profiles(data)
        seal_profiles(data)
        self.assertEqual(profiles(data)[0]['seconds'], 124)

    def test_profile_checksum_covers_entire_common_payload(self):
        data = profile_container()
        data[-1] ^= 1
        with self.assertRaisesRegex(ValueError, 'Profile summary checksum'):
            profiles(data)


if __name__ == '__main__':
    unittest.main()
