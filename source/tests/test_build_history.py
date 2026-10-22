import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_history import (observe_build, export_build, history_valid, MAX_OBSERVATIONS,
                           MAX_HISTORY_BYTES, MAX_SNAPSHOT_BYTES, snapshot_valid)
from report_export import sample_package, load_recipient
from run_package import generate_recipient_keypair, decrypt_package


class BuildHistoryTests(unittest.TestCase):
    def setUp(self):
        self.record = dict(contextKey='character:j1', status='running', elapsedSeconds=1)
        self.stats = dict(name='Test', build=dict(status='available', source='checksum-validated-save',
            level=9, attributes={'vigor':15}, equipment={'weapons':[{'slot':'right1','name':'Longsword'}]}))

    def observe(self, **kwargs):
        return observe_build(self.record, self.stats, 'character:j1', True, **kwargs)

    def test_records_initial_and_changed_loadout_only(self):
        self.assertTrue(self.observe(saved_at=0))
        self.assertFalse(self.observe(saved_at=1))
        self.stats['build']['equipment']['weapons'][0]['name'] = 'Claymore'
        self.assertTrue(self.observe(saved_at=2))
        result = export_build(self.record)
        self.assertEqual(len(result['observations']), 2)
        self.assertEqual(result['initial']['equipment']['weapons'][0]['name'], 'Longsword')
        self.assertEqual(result['final']['equipment']['weapons'][0]['name'], 'Claymore')
        result['final']['level'] = 999
        self.assertEqual(self.record['buildHistory']['observations'][-1]['snapshot']['level'], 9)
        self.assertTrue(history_valid(self.record['buildHistory']))

    def test_wrong_character_or_stale_save_never_attaches_loadout(self):
        self.assertFalse(observe_build(self.record, self.stats, 'other:j2', True))
        self.assertFalse(observe_build(self.record, self.stats, 'character:j1', False))
        self.assertNotIn('buildHistory', self.record)

    def test_finish_boundary_freezes_build(self):
        self.observe()
        self.record['status'] = 'finished'
        self.stats['build']['level'] = 10
        self.assertTrue(self.observe(allow_finished=True))
        self.stats['build']['level'] = 99
        self.assertFalse(self.observe())
        self.assertEqual(export_build(self.record)['final']['level'], 10)

    def test_bounded_history_preserves_first_and_latest(self):
        for level in range(MAX_OBSERVATIONS + 3):
            self.stats['build']['level'] = level
            self.observe()
        result = export_build(self.record)
        self.assertTrue(result['truncated'])
        self.assertEqual(len(result['observations']), MAX_OBSERVATIONS)
        self.assertEqual(result['initial']['level'], 0)
        self.assertEqual(result['final']['level'], MAX_OBSERVATIONS + 2)

    def test_aggregate_byte_limit_keeps_initial_and_latest_snapshot(self):
        self.stats['build']['notice'] = 'Large observed reference note. ' * 300
        for index in range(100):
            self.stats['build']['level'] = index
            self.observe()
        history = self.record['buildHistory']
        self.assertLessEqual(len(json.dumps(history, ensure_ascii=False, separators=(',', ':')).encode()), MAX_HISTORY_BYTES)
        self.assertLess(len(history['observations']), 100)
        self.assertTrue(history['truncated'])
        self.assertTrue(history_valid(history))
        self.assertEqual(history['observations'][0]['snapshot']['level'], 0)
        self.assertEqual(history['observations'][-1]['snapshot']['level'], 99)
        # Restore must reject oversized data even when every individual row is valid.
        oversized = copy.deepcopy(history)
        oversized['observations'] *= 3
        self.assertFalse(history_valid(oversized))

    def test_character_added_to_snapshot_cannot_exceed_snapshot_budget(self):
        self.stats['build'] = dict(source='checksum-validated-save', notice='x'*(MAX_SNAPSHOT_BYTES-80))
        self.stats['name'] = 'T'*256
        self.assertTrue(snapshot_valid(self.stats['build']))
        self.assertFalse(self.observe())
        self.assertNotIn('buildHistory', self.record)

    def test_disconnected_timer_does_not_attach_a_stale_elapsed_time(self):
        self.record['elapsedSeconds'] = 60
        self.assertTrue(self.observe(timer_current=False))
        self.assertIsNone(export_build(self.record)['observations'][0]['elapsedSeconds'])
        self.stats['build']['level'] = 10
        self.record['elapsedSeconds'] = 91
        self.assertTrue(self.observe(timer_current=True))
        self.assertEqual(export_build(self.record)['observations'][-1]['elapsedSeconds'], 91)

    def test_invalid_observation_times_cannot_break_history_limits(self):
        for kwargs in ({'observed_at':'x'*(MAX_HISTORY_BYTES+1)}, {'observed_at':12},
                       {'saved_at':float('nan')}, {'saved_at':float('inf')}, {'saved_at':1e100}):
            with self.subTest(kwargs=kwargs):
                self.assertFalse(self.observe(**kwargs))
                self.assertNotIn('buildHistory', self.record)

    def test_malformed_recipient_configuration_disables_export(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'recipient.json'
            for value in ([], None, 1, 'config', {}, {'schemaVersion':True, 'algorithm':'X25519'},
                          {'schemaVersion':1,'algorithm':'X25519','publicKey':None}):
                with self.subTest(value=value):
                    path.write_text(json.dumps(value), encoding='utf-8')
                    self.assertIsNone(load_recipient(path))

    def test_unavailable_and_malformed_builds_do_not_invent_values(self):
        self.stats['build'] = None
        self.assertFalse(self.observe())
        self.assertIsNone(export_build(self.record)['final'])
        self.assertFalse(history_valid({'observations':'bad','truncated':False}))
        self.assertFalse(history_valid({'observations':[],'truncated':0}))

    def test_preview_package_is_encrypted_simulated_and_untrusted(self):
        keys = generate_recipient_keypair()
        package = sample_package(keys['publicKey'], {'speedrun':{'character':'Demo'},'bossAttempts':{}})
        self.assertNotIn(b'Demo', package)
        opened = decrypt_package(package, keys['privateKey'])
        self.assertTrue(opened.payload['simulation'])
        self.assertFalse(opened.trusted)


if __name__ == '__main__':
    unittest.main()
