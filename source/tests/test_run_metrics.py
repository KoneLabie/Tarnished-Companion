"""Synthetic HUD/save samples verify estimates without accessing the game."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_metrics import CombatMetrics, SpeedrunMetrics


def bar(hp=1000, **overrides):
    return dict(name='Test boss', handle='20', hp=hp, maxHp=1000, **overrides)


class CombatMetricsTests(unittest.TestCase):
    def setUp(self):
        self.metrics = CombatMetrics()

    def sample(self, hp, now, **changes):
        sample = bar(hp)
        sample.update(changes)
        self.metrics.update('character:j1', [sample], True, now)

    def test_waiting_never_fabricates_zero_dps(self):
        self.assertIsNone(self.metrics.snapshot(0)['rollingDps'])
        self.sample(1000, 0)
        state = self.metrics.snapshot(0)
        self.assertEqual(state['status'], 'tracking')
        self.assertIsNone(state['averageDps'])

    def test_positive_hp_loss_reports_sample_drop_not_hit(self):
        self.sample(1000, 0)
        self.sample(900, .5)
        self.sample(650, 1)
        state = self.metrics.snapshot(1)
        self.assertEqual(state['observedDamage'], 350)
        self.assertEqual(state['averageDps'], 350)
        self.assertEqual(state['rollingDps'], 350)
        self.assertEqual(state['largestDrop'], 250)
        self.assertEqual(state['hpPercent'], 65)

    def test_rolling_window_expires_old_samples(self):
        self.sample(1000, 0)
        self.sample(900, 1)
        for stamp in range(2, 7):
            self.sample(900, stamp)
        state = self.metrics.snapshot(6)
        self.assertEqual(state['rollingDps'], 0)
        self.assertAlmostEqual(state['averageDps'], 100 / 6)

    def test_heal_is_not_counted_as_damage(self):
        self.sample(800, 0)
        self.sample(600, 1)
        self.sample(700, 2)
        self.sample(650, 3)
        self.assertEqual(self.metrics.snapshot(3)['observedDamage'], 250)

    def test_full_recovery_restarts_attempt(self):
        self.sample(800, 0)
        self.sample(700, 1)
        self.sample(1000, 2)
        state = self.metrics.snapshot(2)
        self.assertEqual(state['observedDamage'], 0)
        self.assertEqual(state['observedSeconds'], 0)

    def test_stale_snapshot_and_gap_do_not_bridge_missing_damage(self):
        self.sample(1000, 0)
        self.sample(900, 1)
        self.assertEqual(self.metrics.snapshot(3.1)['status'], 'waiting')
        self.sample(100, 4)
        self.assertEqual(self.metrics.snapshot(4)['observedDamage'], 0)

    def test_phase_handle_context_and_disable_reset(self):
        for change in ({'name': 'Second phase'}, {'handle': '21'}, {'maxHp': 2000}):
            self.sample(1000, 0)
            self.sample(800, 1)
            self.sample(500, 2, **change)
            self.assertEqual(self.metrics.snapshot(2)['observedDamage'], 0)
            self.metrics.reset()
        self.sample(1000, 0)
        self.metrics.update('character:j2', [bar(200)], True, 1)
        self.assertEqual(self.metrics.snapshot(1)['observedDamage'], 0)
        self.metrics.update('character:j2', [bar(100)], False, 2)
        self.assertEqual(self.metrics.snapshot(2)['status'], 'waiting')

    def test_invalid_and_out_of_order_samples_fail_closed(self):
        for invalid in (float('nan'), float('inf'), -1, 1001, True):
            self.sample(1000, 0)
            self.sample(invalid, 1)
            self.assertIsNone(self.metrics.snapshot(1)['observedDamage'])
        self.sample(1000, 10)
        self.sample(900, 9)
        self.assertEqual(self.metrics.snapshot(9)['observedDamage'], 0)

    def test_duplicate_timestamp_only_updates_baseline(self):
        self.sample(1000, 1)
        self.sample(800, 1)
        self.sample(700, 2)
        state = self.metrics.snapshot(2)
        self.assertEqual(state['observedDamage'], 100)
        self.assertEqual(state['averageDps'], 100)


class SpeedrunMetricsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.metrics = SpeedrunMetrics(self.directory)
        self.stats = dict(name='Tarnished', journey=1, seconds=1000, deaths=7)
        self.names = {1: 'First boss', 2: 'Second boss', 3: 'Third boss'}

    def start(self, now=0, killed=(1,)):
        self.metrics.action('start', 'character:j1', self.stats, killed, self.names, now)

    def observe(self, now, killed=(1,), context='character:j1', ready=True, **changes):
        self.stats.update(changes)
        self.metrics.observe(context, self.stats, killed, self.names, ready, now)

    def test_start_excludes_existing_bosses_and_baselines(self):
        self.start()
        self.observe(3, seconds=1003, deaths=8)
        state = self.metrics.snapshot(3)
        self.assertEqual(state['elapsedSeconds'], 3)
        self.assertEqual(state['igtSeconds'], 3)
        self.assertEqual(state['deaths'], 1)
        self.assertEqual(state['splits'], [])

    def test_new_defeats_split_once_in_any_order(self):
        self.start()
        self.observe(4, killed=(1, 3), seconds=1004)
        self.observe(8, killed=(1, 3), seconds=1008)
        self.observe(12, killed=(1, 2, 3), seconds=1012)
        state = self.metrics.snapshot(12)
        self.assertEqual([s['bossId'] for s in state['splits']], [3, 2])
        self.assertEqual([s['elapsedSeconds'] for s in state['splits']], [4, 12])
        self.assertEqual(state['bossesDefeated'], 2)

    def test_pause_excludes_elapsed_but_saved_clock_remains_explicit(self):
        self.start()
        self.metrics.action('pause', now=5)
        self.observe(10, killed=(1, 2), seconds=1010)
        paused = self.metrics.snapshot(20)
        self.assertEqual(paused['elapsedSeconds'], 5)
        self.assertEqual(paused['igtSeconds'], 10)
        self.assertIn('paused', paused['splits'][0]['source'])
        self.metrics.action('resume', 'character:j1', self.stats, (1, 2), self.names, 20)
        self.assertEqual(self.metrics.snapshot(23)['elapsedSeconds'], 8)

    def test_finish_freezes_time_and_saved_statistics(self):
        self.start()
        self.observe(5, seconds=1005)
        self.metrics.action('finish', now=5)
        self.observe(10, killed=(1, 2), seconds=1010)
        state = self.metrics.snapshot(100)
        self.assertEqual(state['elapsedSeconds'], 5)
        self.assertEqual(state['igtSeconds'], 5)
        self.assertEqual(state['bossesDefeated'], 0)
        self.assertIsNotNone(state['endedAt'])

    def test_context_change_interrupts_without_importing_new_stats(self):
        self.start()
        self.observe(4, seconds=1004)
        self.observe(8, killed=(), context='character:j2', seconds=1100, deaths=50, journey=2)
        state = self.metrics.snapshot(50)
        self.assertEqual(state['status'], 'interrupted')
        self.assertEqual(state['elapsedSeconds'], 8)
        self.assertEqual(state['journey'], 1)
        self.assertEqual(state['igtSeconds'], 4)
        with self.assertRaises(ValueError):
            self.metrics.action('resume', 'character:j2', self.stats, (), self.names, 60)

    def test_temporary_save_failure_does_not_change_context_or_stop_clock(self):
        self.start()
        self.metrics.observe('pending', None, set(), self.names, False, 4)
        state = self.metrics.snapshot(6)
        self.assertEqual(state['status'], 'running')
        self.assertEqual(state['elapsedSeconds'], 6)
        self.assertEqual(state['contextKey'], 'character:j1')
        self.assertIn('unavailable', state['notice'])
        self.observe(8, killed=(1, 2), seconds=1008)
        self.assertEqual(self.metrics.snapshot(8)['bossesDefeated'], 1)

    def test_pause_and_finish_work_during_save_failure(self):
        self.start()
        self.metrics.observe('pending', None, (), self.names, False, 2)
        self.metrics.action('pause', now=3)
        self.metrics.action('finish', now=10)
        self.assertEqual(self.metrics.snapshot(20)['elapsedSeconds'], 3)

    def test_restart_recovers_checkpoint_without_offline_elapsed(self):
        self.start()
        self.observe(5, seconds=1005)
        restarted = SpeedrunMetrics(self.directory)
        state = restarted.snapshot(10000)
        self.assertEqual(state['status'], 'interrupted')
        self.assertEqual(state['elapsedSeconds'], 5)
        restarted.action('resume', 'character:j1', self.stats, (1,), self.names, 10000)
        self.assertEqual(restarted.snapshot(10002)['elapsedSeconds'], 7)

    def test_rollback_interrupts_and_cannot_resume_before_reset(self):
        self.start()
        self.observe(4, killed=(1, 2), seconds=1004)
        self.observe(8, killed=(1,), seconds=1002)
        self.assertEqual(self.metrics.snapshot(8)['status'], 'interrupted')
        with self.assertRaises(ValueError):
            self.metrics.action('resume', 'character:j1', self.stats, (1,), self.names, 10)
        self.metrics.action('reset', now=10)
        self.start(11)
        self.assertEqual(self.metrics.snapshot(11)['status'], 'running')

    def test_multi_defeat_batch_marks_unknown_order(self):
        self.start(killed=())
        self.observe(4, killed=(3, 1), seconds=1004)
        splits = self.metrics.snapshot(4)['splits']
        self.assertTrue(all('order unknown' in s['source'] for s in splits))
        self.assertEqual(splits[0]['elapsedSeconds'], splits[1]['elapsedSeconds'])

    def test_existing_run_cannot_be_overwritten_by_start(self):
        self.start()
        with self.assertRaises(ValueError):
            self.start(1)
        with self.assertRaises(ValueError):
            self.metrics.action('reset', now=1)
        self.metrics.action('finish', now=2)
        with self.assertRaises(ValueError):
            self.start(3)

    def test_export_is_plain_text_with_timing_limitations(self):
        self.stats['name'] = 'Name\nwith line'
        self.start()
        self.observe(4, killed=(1, 2), seconds=1004)
        report = self.metrics.export_text(4)
        self.assertIn('Character: Name with line', report)
        self.assertIn('Second boss', report)
        self.assertIn('00:00:04.000', report)
        self.assertIn('4 seconds', report)
        self.assertIn('not a live or official', report)
        self.assertIn('manual pauses', report)

    def test_snapshots_cannot_mutate_internal_state(self):
        self.start()
        self.observe(4, killed=(1, 2))
        result = self.metrics.snapshot(4)
        result['splits'][0]['name'] = 'Corrupted'
        self.assertEqual(self.metrics.snapshot(4)['splits'][0]['name'], 'Second boss')

    def test_malformed_saved_state_and_invalid_start_fail_safely(self):
        self.metrics.path.write_text('{incomplete', encoding='utf-8')
        self.assertEqual(SpeedrunMetrics(self.directory).snapshot(0)['status'], 'idle')
        self.start()
        raw = json.loads(self.metrics.path.read_text(encoding='utf-8'))
        raw['elapsedSeconds'] = float('nan')
        self.metrics.path.write_text(json.dumps(raw), encoding='utf-8')
        self.assertEqual(SpeedrunMetrics(self.directory).snapshot(0)['status'], 'idle')
        self.metrics.action('pause', now=1)
        self.metrics.action('reset', now=1)
        with self.assertRaises(ValueError):
            self.metrics.action('start', 'pending', self.stats, (), self.names, 2)
        with self.assertRaises(ValueError):
            self.metrics.export_text(2)

    def test_disk_failure_keeps_timer_alive_and_recovers_on_checkpoint(self):
        self.start()
        with patch.object(Path, 'write_text', side_effect=OSError('Disk full')):
            self.observe(5, seconds=1005)
        state = self.metrics.snapshot(6)
        self.assertEqual(state['status'], 'running')
        self.assertEqual(state['elapsedSeconds'], 6)
        self.assertIn('could not be saved', state['notice'])
        self.observe(10, seconds=1010)
        self.assertNotIn('could not be saved', self.metrics.snapshot(10)['notice'])
        self.assertEqual(SpeedrunMetrics(self.directory).snapshot(11)['elapsedSeconds'], 10)


if __name__ == '__main__':
    unittest.main()
