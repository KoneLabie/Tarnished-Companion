"""HUD layout replay and read-access boundaries; never opens the real game."""
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from live_reader import LiveReader, unpack_tags, unpack_enemy_tags, unpack_world_enemies


class HudReplayTests(unittest.TestCase):
    def setUp(self):
        self.fe = 0x100000
        self.base = 0x140000000
        self.vtable = 0x2000
        self.memory = bytearray(0x9000)
        struct.pack_into('<Q', self.memory, 0, self.base + self.vtable)
        self.memory[0x78] = 3

    def read(self, address, size):
        offset = address - self.fe
        if not 0 <= offset < len(self.memory) or offset + size > len(self.memory):
            raise OSError('Outside replay')
        return bytes(self.memory[offset:offset + size])

    def tag(self, boss=False, slot=0, hp=700, maximum=1000, handle=42):
        offset = (0x1B90 if boss else 0x1250) + 0x128 * slot
        self.memory[offset] = 1
        struct.pack_into('<Q', self.memory, offset + 8, handle)
        struct.pack_into('<I', self.memory, offset + 0x18, hp)
        struct.pack_into('<II', self.memory, offset + 0x20, 0, maximum)
        if boss:
            struct.pack_into('<Q', self.memory, 0x5BF0 + slot * 0x20 + 8, handle)
            text = 'Test boss\0'.encode('utf-16-le')
            self.memory[0x8500:0x8500 + len(text)] = text
            struct.pack_into('<Q', self.memory, offset + 0x28, self.fe + 0x8500)
        else:
            struct.pack_into('<Q', self.memory, 0x59F0 + slot * 0x40, handle)
            self.memory[0x59F0 + slot * 0x40 + 0x34] = 1
        return offset

    def test_boss_identity_and_health_are_decoded(self):
        self.tag(boss=True)
        self.assertEqual(unpack_tags(self.read, self.fe, self.base, self.vtable),
                         [dict(name='Test boss', hp=700, maxHp=1000, handle='42')])

    def test_enemy_slots_exclude_boss_and_friendly_slots(self):
        self.tag(slot=0, hp=300, maximum=500, handle=12)
        self.tag(boss=True, hp=50000, maximum=60000, handle=45)
        self.assertEqual(unpack_enemy_tags(self.read, self.fe),
                         [dict(name='Enemy target', hp=300, maxHp=500,
                               handle='12', kind='enemy')])

    def test_enemy_requires_matching_visible_display_and_valid_health(self):
        tag = self.tag()
        self.memory[0x59F0 + 0x34] = 0
        self.assertEqual(unpack_enemy_tags(self.read, self.fe), [])
        self.memory[0x59F0 + 0x34] = 1
        struct.pack_into('<Q', self.memory, tag + 8, 43)
        self.assertEqual(unpack_enemy_tags(self.read, self.fe), [])
        struct.pack_into('<Q', self.memory, tag + 8, 42)
        struct.pack_into('<I', self.memory, tag + 0x18, 1001)
        self.assertEqual(unpack_enemy_tags(self.read, self.fe), [])

    def test_display_reordering_keeps_combat_target_stable(self):
        self.tag(slot=0, handle=21)
        self.tag(slot=1, handle=42)
        reader = LiveReader(dict(vtable=self.vtable))
        reader.pid = 1
        reader.fe, reader.base = self.fe, self.base
        reader.combat_handle = '42'
        with patch('live_reader.process_list', return_value=[(1, 'eldenring.exe')]), \
                patch.object(reader, 'read', side_effect=self.read):
            bosses, status = reader.poll()
        self.assertEqual(bosses, [], 'Ordinary enemies cannot start a boss fight')
        self.assertEqual(status, 'Live enemy data connected.')
        self.assertEqual(reader.combat_bars[0]['handle'], '42')

    def test_boss_priority_and_missing_targets_clear_stale_combat(self):
        self.tag(handle=21)
        self.tag(boss=True, handle=42)
        reader = LiveReader(dict(vtable=self.vtable))
        reader.pid = 1
        reader.fe, reader.base = self.fe, self.base
        reader.combat_handle = '21'
        with patch('live_reader.process_list', return_value=[(1, 'eldenring.exe')]), \
                patch.object(reader, 'read', side_effect=self.read):
            bosses, status = reader.poll()
            self.assertEqual(reader.combat_bars, bosses)
            self.assertEqual(status, 'Live boss data connected.')
            self.memory[0x1B90] = self.memory[0x1250] = 0
            reader.poll()
        self.assertEqual(reader.combat_bars, [])
        self.assertIsNone(reader.combat_handle)

    def test_protected_session_is_rejected_before_opening_or_reading(self):
        reader = LiveReader({})
        reader.combat_bars = [dict(hp=50)]
        with patch('live_reader.process_list', return_value=[(1, 'eldenring.exe'),
                    (2, 'start_protected_game.exe')]), \
                patch('live_reader.K.OpenProcess') as open_process, \
                patch.object(reader, 'read') as read:
            bars, status = reader.poll()
        self.assertIn('BLOCKED', status)
        self.assertEqual(bars, [])
        self.assertEqual(reader.combat_bars, [])
        open_process.assert_not_called()
        read.assert_not_called()

    def test_lingering_dead_enemy_cannot_replace_observed_target(self):
        self.tag(slot=0, handle=21, hp=0)
        self.tag(slot=1, handle=42, hp=0)
        reader = LiveReader(dict(vtable=self.vtable))
        reader.pid = 1
        reader.fe, reader.base = self.fe, self.base
        reader.combat_handle = '21'
        with patch('live_reader.process_list', return_value=[(1, 'eldenring.exe')]), \
                patch.object(reader, 'read', side_effect=self.read):
            reader.poll()
            self.assertEqual([b['handle'] for b in reader.combat_bars], ['21'])
            self.memory[0x1250] = 0
            reader.poll()
            self.assertEqual(reader.combat_bars, [])
            self.assertIsNone(reader.combat_handle)


class LoadedEnemyTests(unittest.TestCase):
    def setUp(self):
        self.base=0x140000000
        self.world=0x100000
        self.profile=dict(vtable=0x2000,distanceVector=0x40)
        self.memory={self.world:bytearray(0x80),0x200000:bytearray(16*300)}
        struct.pack_into('<Q',self.memory[self.world],0,self.base+0x2000)

    def read(self,address,size):
        self.assertLessEqual(size,4096)
        for start,buffer in self.memory.items():
            if start<=address and address+size<=start+len(buffer):
                return bytes(buffer[address-start:address-start+size])
        raise OSError('Invalid replay address')

    def enemy(self,index,kind=5,team=6,hp=100,owner=True):
        ptr=0x300000+index*0x1000;mod=ptr+0x300;data=ptr+0x400
        c=bytearray(0x1C8);d=bytearray(0x140)
        struct.pack_into('<QQ',c,0,self.base+0x1000,index+1)
        struct.pack_into('<i',c,0x68,kind);c[0x6C]=team
        struct.pack_into('<Q',c,0x190,mod)
        struct.pack_into('<QQ',d,0,self.base+0x3000,ptr if owner else 0)
        struct.pack_into('<ii',d,0x138,hp,100)
        if hp==0:c[0x1C6]=2
        self.memory[ptr]=c;self.memory[mod]=bytearray(struct.pack('<Q',data));self.memory[data]=d
        struct.pack_into('<Q',self.memory[0x200000],index*16,ptr)
        return ptr

    def sample(self,count):
        struct.pack_into('<QQQQ',self.memory[self.world],0x40,0,0x200000,0x200000+16*count,0x200000+16*300)
        return unpack_world_enemies(self.read,self.world,self.base,0x5000000,self.profile)

    def test_filters_players_allies_friendly_npcs_and_bad_owner(self):
        self.enemy(0);self.enemy(1,kind=0);self.enemy(2,team=26)
        self.enemy(3,team=8);self.enemy(4,owner=False)
        samples=self.sample(5)
        self.assertEqual(len(samples),1)
        self.assertEqual(samples[0]['hp'],100)
        self.assertFalse(samples[0]['defeated'])

    def test_death_reward_confirmation_survives_missing_health_bar(self):
        self.enemy(0,hp=0)
        self.assertTrue(self.sample(1)[0]['defeated'])

    def test_large_snapshot_is_chunked_and_duplicate_pointers_are_ignored(self):
        pointer=self.enemy(0)
        for index in range(300):struct.pack_into('<Q',self.memory[0x200000],index*16,pointer)
        self.assertEqual(len(self.sample(300)),1)

    def test_invalid_list_bounds_fail_closed(self):
        struct.pack_into('<QQQQ',self.memory[self.world],0x40,0,0x200000,0x200010,0x200000+16*5000)
        with self.assertRaisesRegex(ValueError,'capacity'):
            unpack_world_enemies(self.read,self.world,self.base,0x5000000,self.profile)


if __name__ == '__main__':
    unittest.main()
