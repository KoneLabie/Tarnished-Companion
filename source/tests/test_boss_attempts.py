"""Synthetic observed boss lifecycles, without game memory or real save data."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from boss_attempts import BossAttempts


def bar(hp=1000, name='Boss A', handle='1', maximum=1000):
    return dict(name=name, handle=handle, hp=hp, maxHp=maximum)


class BossAttemptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.tracker = BossAttempts(self.directory)
        self.context = 'character-a:j1'
        self.stats = dict(name='Tarnished', journey=1, deaths=0, seconds=100)
        self.killed = set()
        self.names = {1: 'Boss A', 2: 'Boss B'}
        self.resolve = lambda name: {'Boss A': 1, 'Boss A phase two': 1, 'Boss B': 2}.get(name)
        self.sample(0, [])

    def sample(self, stamp, bars=None, ready=True, live=True, process='running', category=None, **stats):
        self.stats.update(stats)
        self.tracker.observe(self.context, self.stats, self.killed, [] if bars is None else bars,
                             ready, live, process, self.resolve, self.names, stamp, category_key=category)
        return self.tracker.snapshot(stamp)

    def complete(self, duration, context=None, journey=None, category=None):
        if context is not None:
            self.context = context
        if journey is not None:
            self.stats['journey'] = journey
        self.killed = set()
        self.sample(0, [], category=category)
        self.sample(0, [bar()], category=category)
        for second in range(1, duration):
            self.sample(second, [bar(500)], category=category)
        self.killed = {1}
        return self.sample(duration, [bar(0)], category=category)

    def test_automatic_start_and_saved_victory(self):
        self.assertIsNone(self.sample(0)['active'])
        state = self.sample(1, [bar()])
        self.assertEqual(state['active']['attemptNumber'], 1)
        self.assertEqual(state['active']['elapsedSeconds'], 0)
        self.sample(2, [bar(500)])
        self.sample(3, [bar(0)])
        self.killed = {1}
        state = self.sample(5, [])
        self.assertIsNone(state['active'])
        self.assertEqual(state['lastAttempt']['outcome'], 'victory')
        self.assertEqual(state['lastAttempt']['elapsedSeconds'], 2)
        self.assertEqual(state['benchmarks']['bestSeconds'], 2)

    def test_zero_hp_is_not_victory_and_phase_change_keeps_timer(self):
        self.sample(0, [bar()])
        self.sample(1, [bar(0)])
        self.assertIsNone(self.tracker.snapshot(1)['lastAttempt'])
        self.sample(2, [])
        state = self.sample(3, [bar(name='Boss A phase two', handle='2', maximum=2000, hp=2000)])
        self.assertEqual(state['active']['elapsedSeconds'], 3)
        self.assertEqual(state['active']['attemptNumber'], 1)
        self.assertEqual(state['active']['phases'], ['Boss A', 'Boss A phase two'])
        self.killed = {1}
        state = self.sample(4, [bar(0, name='Boss A phase two', handle='2', maximum=2000)])
        self.assertEqual(state['lastAttempt']['elapsedSeconds'], 4)

    def test_unchanged_name_phase_health_refill_is_not_new_attempt(self):
        self.sample(0, [bar()])
        self.sample(1, [bar(0)])
        self.sample(2, [])
        state = self.sample(3, [bar(handle='second-phase')])
        self.assertEqual(state['active']['attemptNumber'], 1)
        self.assertEqual(state['active']['elapsedSeconds'], 3)
        self.assertEqual(state['records'], [])

    def test_saved_death_resets_and_lingering_bar_cannot_restart(self):
        self.sample(0, [bar()])
        self.sample(1, [bar(500)])
        state = self.sample(2, [bar(500)], deaths=1)
        self.assertIsNone(state['active'])
        self.assertEqual(state['lastAttempt']['outcome'], 'death')
        self.assertEqual(state['lastAttempt']['elapsedSeconds'], 2)
        self.assertIsNone(self.sample(3, [bar(500)])['active'])
        self.sample(4, [])
        state = self.sample(5, [bar()])
        self.assertEqual(state['active']['attemptNumber'], 2)
        self.assertEqual(state['active']['elapsedSeconds'], 0)

    def test_saved_death_after_new_full_bar_can_start_next_attempt(self):
        self.sample(0, [bar()])
        self.sample(1, [bar(400)])
        state = self.sample(2, [bar()], deaths=1)
        self.assertEqual(state['lastAttempt']['outcome'], 'death')
        self.assertEqual(state['active']['attemptNumber'], 2)
        self.assertEqual(state['active']['elapsedSeconds'], 0)

    def test_short_hidden_bar_is_not_death_or_restart(self):
        self.sample(0, [bar()])
        self.sample(1, [bar(500)])
        state = self.sample(2, [])
        self.assertEqual(state['active']['status'], 'awaiting-result')
        self.assertEqual(state['active']['elapsedSeconds'], 1)
        self.sample(3, [])
        state = self.sample(4, [bar(500)])
        self.assertEqual(state['active']['elapsedSeconds'], 4)
        self.assertEqual(state['records'], [])

    def test_disappeared_bar_unconfirmed_then_delayed_saved_victory(self):
        self.sample(0, [bar()])
        self.sample(1, [bar(0)])
        for second in range(2, 8):
            self.sample(second, [])
        state = self.tracker.snapshot(7)
        self.assertEqual(state['lastAttempt']['outcome'], 'unconfirmed')
        self.assertEqual(state['benchmarks']['sampleCount'], 0)
        self.killed = {1}
        state = self.sample(8, [])
        self.assertEqual(state['lastAttempt']['outcome'], 'victory')
        self.assertEqual(state['lastAttempt']['elapsedSeconds'], 1)

    def test_delayed_saved_death_can_reconcile_within_window(self):
        self.sample(0, [bar()])
        self.sample(1, [bar(500)])
        for second in range(2, 8):
            self.sample(second, [])
        state = self.sample(8, [], deaths=1)
        self.assertEqual(state['lastAttempt']['outcome'], 'death')
        self.assertEqual(state['lastAttempt']['elapsedSeconds'], 1)

    def test_late_results_outside_window_do_not_rewrite_history(self):
        self.sample(0, [bar()])
        self.sample(1, [bar(0)])
        for second in range(2, 40):
            self.sample(second, [])
        self.killed = {1}
        state = self.sample(40, [])
        self.assertEqual(state['lastAttempt']['outcome'], 'unconfirmed')

    def test_missing_zero_hp_endpoint_never_becomes_false_personal_best(self):
        self.sample(0, [bar()])
        self.sample(1, [bar(500)])
        for second in range(2, 8):
            self.sample(second, [])
        self.killed = {1}
        state = self.sample(8, [])
        self.assertEqual(state['lastAttempt']['outcome'], 'victory')
        self.assertEqual(state['benchmarks']['sampleCount'], 0)
        self.assertFalse(state['lastAttempt']['eligibleForBenchmark'])

    def test_connecting_mid_fight_is_partial_even_at_full_hp(self):
        tracker = BossAttempts(self.directory / 'midfight')
        tracker.observe(self.context, self.stats, set(), [bar()], True, True, 'running', self.resolve, self.names, 0)
        state = tracker.snapshot(0)
        self.assertTrue(state['active']['partialStart'])
        self.assertIn('already visible', state['active']['note'])
        tracker.observe(self.context, self.stats, {1}, [bar(0)], True, True, 'running', self.resolve, self.names, 1)
        self.assertEqual(tracker.snapshot(1)['benchmarks']['sampleCount'], 0)

    def test_late_result_spanning_two_attempts_stays_unconfirmed(self):
        self.sample(0, [bar()])
        self.sample(1, [bar(500)])
        for second in range(2, 8):
            self.sample(second, [])
        self.sample(8, [bar(handle='new')])
        state = self.sample(9, [bar(500, handle='new')], deaths=1)
        self.assertIsNone(state['active'])
        self.assertEqual([r['outcome'] for r in state['records']], ['unconfirmed', 'unconfirmed'])
        self.assertEqual(state['benchmarks']['sampleCount'], 0)

    def test_process_exit_and_reader_disconnect_are_interrupted_not_death(self):
        for process, live in [('absent', False), ('running', False)]:
            with self.subTest(process=process):
                tracker = BossAttempts(self.directory / process)
                tracker.observe(self.context, self.stats, set(), [bar()], True, True, 'running', self.resolve, self.names, 0)
                tracker.observe(self.context, self.stats, set(), [], True, live, process, self.resolve, self.names, 1)
                state = tracker.snapshot(1)
                self.assertEqual(state['lastAttempt']['outcome'], 'interrupted')
                self.assertIsNone(state['active'])

    def test_sample_gap_and_invalid_save_do_not_bridge_attempt(self):
        self.sample(0, [bar()])
        state = self.sample(10, [bar(500)])
        self.assertEqual(state['lastAttempt']['outcome'], 'interrupted')
        self.assertIsNone(state['active'])
        self.sample(11, [])
        self.sample(12, [bar()])
        state = self.sample(13, ready=False)
        self.assertEqual(state['lastAttempt']['outcome'], 'interrupted')

    def test_character_changes_keep_histories_separate(self):
        self.sample(0, [bar()])
        old = self.context
        self.context = 'character-b:j1'
        state = self.sample(1, [bar()], name='Second')
        self.assertEqual(state['active']['attemptNumber'], 1)
        self.assertEqual(state['records'], [])
        self.assertEqual(self.tracker.contexts[old]['records'][0]['outcome'], 'interrupted')

    def test_multiple_bars_reordering_keeps_original_encounter(self):
        self.sample(0, [bar(), bar(name='Boss B', handle='2')])
        state = self.sample(1, [bar(name='Boss B', handle='2'), bar(500)])
        self.assertEqual(state['active']['bossId'], 1)
        self.assertEqual(state['active']['elapsedSeconds'], 1)

    def test_ambiguous_arenas_never_gain_benchmarks_or_shared_attempt_number(self):
        state = self.sample(0, [bar(name='Repeated boss')])
        self.assertIsNone(state['active']['bossId'])
        self.assertIsNone(state['active']['attemptNumber'])
        self.killed = {1}
        state = self.sample(1, [bar(0, name='Repeated boss')])
        self.assertIsNone(state['lastAttempt'])
        self.assertEqual(state['benchmarks']['sampleCount'], 0)
        self.assertIn('unresolved', state['notice'])

    def test_manual_disabled_invalid_and_dead_bars_do_not_start(self):
        self.assertIsNone(self.sample(0, [bar()], live=False)['active'])
        for hp in (0, -1, 1001, True, float('nan')):
            self.assertIsNone(self.sample(1, [bar(hp)])['active'])

    def test_existing_defeat_is_not_new_live_attempt(self):
        self.killed = {1}
        self.assertIsNone(self.sample(0, [bar()])['active'])

    def test_duration_beyond_fifteen_minutes_is_preserved(self):
        self.sample(0, [bar()])
        for stamp in range(1, 1002):
            self.sample(stamp, [bar(500)])
        state = self.tracker.snapshot(1001)
        self.assertEqual(state['active']['elapsedSeconds'], 1001)
        self.assertEqual(state['benchmarks']['scaleSeconds'], 900)
        self.assertIn('00:16:41.000', self.tracker.export_text(now=1001))

    def test_benchmarks_share_exact_id_and_journey_but_not_partial_starts(self):
        for index, duration in enumerate([10, 20, 30, 40, 50]):
            self.complete(duration, context=f'character-{index}:j1')
        self.complete(1, context='character-ng:j2', journey=2)
        self.context = 'character-partial:j1'
        self.stats['journey'] = 1
        self.killed = set()
        self.sample(0, [bar(500)])
        self.killed = {1}
        state = self.sample(1, [bar(0)])
        self.assertFalse(state['lastAttempt']['eligibleForBenchmark'])
        self.assertEqual(state['benchmarks']['sampleCount'], 5)
        self.assertEqual(state['benchmarks']['bestSeconds'], 10)
        self.assertEqual(state['benchmarks']['nearBestSeconds'], 15)
        self.assertEqual(state['benchmarks']['averageSeconds'], 30)
        self.assertEqual(state['benchmarks']['scope'], 'Personal history · Journey 1')

    def test_small_history_benchmark_bands_remain_ordered(self):
        self.complete(10, context='first:j1')
        state = self.complete(100, context='second:j1')
        benchmark = state['benchmarks']
        self.assertLessEqual(benchmark['bestSeconds'], benchmark['nearBestSeconds'])
        self.assertLessEqual(benchmark['nearBestSeconds'], benchmark['averageSeconds'])

    def test_categories_do_not_mix_benchmarks_or_unclassified_history(self):
        self.complete(10, context='legacy:j1')
        self.complete(20, context='first-category:j1', category='any-glitchless')
        state = self.complete(30, context='second-category:j1', category='all-remembrances')
        self.assertEqual(state['benchmarks']['sampleCount'], 1)
        self.assertEqual(state['benchmarks']['bestSeconds'], 30)
        self.assertEqual(state['benchmarks']['categoryId'], 'all-remembrances')
        self.assertEqual(state['lastAttempt']['categoryId'], 'all-remembrances')
        report = self.tracker.export_text(now=30)
        self.assertIn('| all-remembrances |', report)

    def test_changing_category_interrupts_and_cannot_relabel_current_attempt(self):
        self.sample(0, [], category='first')
        self.sample(1, [bar()], category='first')
        state = self.sample(2, [bar()], category='second')
        self.assertIsNone(state['active'])
        self.assertEqual(state['records'], [])
        old = self.tracker.contexts[self.context]['records'][0]
        self.assertEqual(old['categoryId'], 'first')
        self.assertEqual(old['outcome'], 'interrupted')

    def test_restart_keeps_history_and_marks_active_checkpoint_interrupted(self):
        self.sample(0, [bar()])
        for stamp in range(1, 7):
            self.sample(stamp, [bar(500)])
        restarted = BossAttempts(self.directory)
        restarted.observe(self.context, self.stats, set(), [], True, False, 'unknown', self.resolve, self.names, 100)
        state = restarted.snapshot(100)
        self.assertIsNone(state['active'])
        self.assertEqual(state['lastAttempt']['outcome'], 'interrupted')
        self.assertEqual(state['lastAttempt']['elapsedSeconds'], 5)
        self.assertIn('checkpoint', state['lastAttempt']['note'])

    def test_malformed_history_is_preserved(self):
        path = self.directory / 'boss-attempts.json'
        path.write_text('{not json', encoding='utf-8')
        self.tracker = BossAttempts(self.directory)
        self.sample(0, [bar()])
        self.assertEqual(path.read_text(), '{not json')
        self.assertIn('preserved', self.tracker.snapshot(0)['notice'])

    def test_disk_errors_do_not_stop_observation(self):
        with patch.object(Path, 'replace', side_effect=OSError('read only')):
            state = self.sample(0, [bar()])
        self.assertIn('could not be saved', state['notice'])
        for stamp in range(1, 7):
            state = self.sample(stamp, [bar(500)])
        self.assertNotIn('could not be saved', state['notice'])

    def test_snapshot_does_not_mutate_stored_history(self):
        state = self.complete(2)
        state['records'][0]['outcome'] = 'death'
        self.assertEqual(self.tracker.snapshot(2)['records'][0]['outcome'], 'victory')

    def test_export_has_counts_durations_outcomes_and_scope_filter(self):
        with patch('boss_attempts._utc', return_value='2026-10-22T12:00:00+00:00'):
            self.sample(0, [bar()])
            self.sample(1, [bar(500)], deaths=1)
            self.sample(2, [])
        with patch('boss_attempts._utc', return_value='2026-10-22T13:00:00+00:00'):
            self.sample(3, [bar()])
            self.killed = {1}
            self.sample(4, [bar(0)])
        report = self.tracker.export_text(now=4)
        self.assertIn('Boss A | 2 | 1 | 1 | 0', report)
        self.assertIn('Boss A | 1 | 00:00:01.000 | death', report)
        self.assertIn('Boss A | 2 | 00:00:01.000 | victory', report)
        filtered = self.tracker.export_text(since='2026-10-22T12:30:00+00:00', now=4)
        self.assertNotIn('| death |', filtered)
        self.assertIn('| victory |', filtered)

    def test_export_end_bound_excludes_later_attempts_and_later_outcomes(self):
        with patch('boss_attempts._utc', return_value='2026-10-22T12:00:00+00:00'):
            self.sample(0, [bar()])
        with patch('boss_attempts._utc', return_value='2026-10-22T12:10:00+00:00'):
            self.sample(1, [bar(500)], deaths=1)
            self.sample(2, [])
        with patch('boss_attempts._utc', return_value='2026-10-22T13:00:00+00:00'):
            self.sample(3, [bar()])
            self.killed = {1}
            self.sample(4, [bar(0)])
        report = self.tracker.export_text(until='2026-10-22T12:05:00+00:00', now=4)
        self.assertIn('in-progress-at-run-end', report)
        self.assertIn('Not recorded at run end', report)
        self.assertNotIn('| victory |', report)
        self.assertNotIn('| death |', report)
        self.assertNotIn('2026-10-22T13:00:00', report)
        report = self.tracker.export_text(until='2026-10-22T12:30:00+00:00', now=4)
        self.assertIn('| death |', report)
        self.assertNotIn('| victory |', report)


if __name__ == '__main__':
    unittest.main()
