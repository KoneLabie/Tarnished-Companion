import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from eliminations import Eliminations


def npc(hp=100, handle='1', instance='1000', defeated=None):
    return dict(handle=handle,instance=instance,hp=hp,maxHp=100,
                defeated=hp==0 if defeated is None else defeated)


class EliminationTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.counter=Eliminations(self.directory.name)

    def tick(self,enemies,at,context='character:j1',session='game1',available=True,bosses=()):
        self.counter.update(context,session,enemies,available,boss_handles=bosses,now=at)
        return self.counter.snapshot(context)

    def test_death_counts_once_and_old_manual_settings_are_not_imported(self):
        Path(self.directory.name,'settings.json').write_text('{"enemyKills":999}')
        self.assertEqual(self.tick([npc()],0)['total'],0)
        self.assertEqual(self.tick([npc(0)],.5)['total'],1)
        self.assertEqual(self.tick([npc(0)],1)['total'],1)
        self.assertEqual(self.tick([npc(0),npc(0)],1.5)['total'],1)

    def test_already_dead_on_first_connection_is_not_counted(self):
        self.assertEqual(self.tick([npc(0)],0)['total'],0)
        self.assertEqual(self.tick([npc(0)],1)['total'],0)

    def test_zero_hp_waits_for_death_or_reward_confirmation(self):
        self.tick([npc()],0)
        self.assertEqual(self.tick([npc(0,defeated=False)],1)['total'],0)
        self.assertEqual(self.tick([npc(0,defeated=False)],2)['total'],0)
        self.assertEqual(self.tick([npc(0)],3)['total'],1)

    def test_revival_without_confirmed_death_does_not_count(self):
        self.tick([npc()],0)
        self.tick([npc(0,defeated=False)],1)
        self.assertEqual(self.tick([npc()],2)['total'],0)
        self.assertEqual(self.tick([npc(0)],3)['total'],1)

    def test_despawn_is_not_a_death_and_returning_dead_is_not_proof(self):
        self.tick([npc()],0)
        self.tick([],1)
        self.assertEqual(self.tick([npc(0)],2)['total'],0)

    def test_long_sample_gap_cannot_be_used_as_death_evidence(self):
        self.tick([npc()],0)
        self.assertEqual(self.tick([npc(0)],3)['total'],0)

    def test_rest_respawn_rearms_the_enemy(self):
        self.tick([npc()],0)
        self.tick([npc(0)],1)
        self.tick([npc()],2)
        self.assertEqual(self.tick([npc(0)],3)['total'],2)

    def test_boss_phase_deaths_are_excluded_after_hud_hides(self):
        self.tick([npc()],0,bosses=['1'])
        self.assertEqual(self.tick([npc(0)],1)['total'],0)
        self.tick([npc()],2)
        self.assertEqual(self.tick([npc(0)],3)['total'],0)

    def test_new_journey_and_character_get_separate_saved_totals(self):
        self.tick([npc()],0)
        self.tick([npc(0)],1)
        for context in ['character:j2','other-character:j1']:
            self.assertEqual(self.tick([npc(0)],2,context=context)['total'],0)
        self.assertEqual(self.tick([npc(0)],3)['total'],1)

    def test_restart_keeps_total_without_recounting_corpse(self):
        self.tick([npc()],0)
        self.tick([npc(0)],1)
        self.counter=Eliminations(self.directory.name)
        self.assertEqual(self.tick([npc(0)],2)['total'],1)

    def test_game_restart_and_reader_disconnect_reset_observation_only(self):
        self.tick([npc()],0)
        self.assertEqual(self.tick([npc(0)],1,session='game2')['total'],0)
        self.tick([npc()],2)
        self.tick([],3,available=False)
        self.assertEqual(self.tick([npc(0)],4)['total'],0)

    def test_reused_handle_with_a_new_instance_cannot_bridge_health(self):
        self.tick([npc()],0)
        self.assertEqual(self.tick([npc(0,instance='2000')],1)['total'],0)

    def test_multiple_enemy_deaths_in_one_sample_count_individually(self):
        self.tick([npc(),npc(handle='2')],0)
        self.assertEqual(self.tick([npc(0),npc(0,handle='2')],1)['total'],2)

    def test_invalid_samples_never_increment(self):
        self.tick([npc()],0)
        for bad in [dict(npc(0),hp=True),dict(npc(0),defeated=None),dict(npc(0),maxHp=0)]:
            self.assertEqual(self.tick([bad],1)['total'],0)

    def test_storage_failure_retries_without_counting_same_death_twice(self):
        self.tick([npc()],0)
        with patch.object(Path,'replace',side_effect=PermissionError('busy')):
            self.assertEqual(self.tick([npc(0)],1)['status'],'storage-error')
        self.assertEqual(self.tick([npc(0)],2)['total'],1)
        self.assertTrue(self.counter.snapshot('character:j1')['persisted'])
        self.assertEqual(json.loads(self.counter.path.read_text())['contexts']['character:j1']['total'],1)

    def test_corrupt_history_is_preserved_instead_of_silently_overwritten(self):
        path=Path(self.directory.name,'eliminations.json')
        path.write_text('{broken')
        self.counter=Eliminations(self.directory.name)
        self.assertEqual(self.tick([npc()],0)['status'],'storage-error')
        self.tick([npc(0)],1)
        self.assertEqual(path.read_text(),'{broken')
        self.assertIsNone(self.counter.snapshot('character:j1')['total'])
