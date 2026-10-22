"""Run capture requires witnessed new-character evidence, never a manual claim."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from run_policy import CATEGORIES, RunPolicy


class RunPolicyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name)
        self.clock = 100.0
        clock = patch('run_policy.time.monotonic', side_effect=lambda: self.clock)
        clock.start()
        self.addCleanup(clock.stop)
        self.policy = RunPolicy(self.path)
        self.context = 'v2:character_a:j1'
        self.save_key = 'hash-of-save-file'
        self.stats = dict(slot=0, seconds=0, deaths=0, journey=1)
        self.timer = dict(connected=True, configured=True, phase='Running',
                          gameTimeSeconds=0.5, categoryName='Any% Glitchless',
                          attemptCount=1, gameName='Elden Ring')

    def fresh(self, select=True):
        if select:
            self.policy.select('any-percent-glitchless')
        self.policy.observe_roster(self.save_key, [], True)
        self.clock += 1
        self.policy.observe_roster(self.save_key, [self.stats], True)
        self.policy.observe(self.context, self.stats, [], True, save_key=self.save_key)

    def audit(self, **timer):
        return self.policy.audit_for_start(self.context, {**self.timer, **timer})

    def test_capture_off_cannot_witness_or_record_a_new_character(self):
        self.policy.set_capture_enabled(False)
        self.fresh()
        self.assertEqual(self.policy.records, {})
        self.assertFalse(self.audit()['eligible'])
        self.policy.set_capture_enabled(True)
        self.policy.observe_roster(self.save_key, [self.stats], True)
        self.policy.observe(self.context, self.stats, [], True, save_key=self.save_key)
        self.assertFalse(self.audit()['eligible'])

    def test_leaving_capture_revokes_active_recording_but_preserves_historical_export(self):
        self.fresh()
        self.assertTrue(self.audit()['eligible'])
        self.assertTrue(self.policy.mark_started(self.context))
        self.policy.set_capture_enabled(False, self.context)
        self.assertFalse(self.policy.can_record(self.context))
        self.assertTrue(self.policy.can_export(self.context))
        self.policy.set_capture_enabled(True)
        self.assertFalse(self.policy.can_record(self.context))
        self.assertFalse(self.audit()['eligible'])
        restored = RunPolicy(self.path)
        self.assertFalse(restored.can_record(self.context))
        self.assertTrue(restored.can_export(self.context))

    def test_disabling_without_active_context_does_not_revoke_completed_history(self):
        self.fresh()
        self.assertTrue(self.audit()['eligible'])
        self.assertTrue(self.policy.mark_started(self.context))
        self.policy.set_capture_enabled(False, None)
        self.assertFalse(self.policy.can_record(self.context))
        self.assertTrue(self.policy.can_export(self.context))
        self.assertFalse(self.policy.records[self.context].get('captureSuspended'))

    def test_capture_off_clears_unconsumed_start_window_and_timer_boundary(self):
        self.fresh()
        self.policy.observe_timer(self.timer)
        self.assertTrue(self.audit()['eligible'])
        self.policy.set_capture_enabled(False)
        self.policy.set_capture_enabled(True)
        self.assertFalse(self.audit()['eligible'])
        self.assertFalse(self.policy.mark_started(self.context))

    def test_integrity_flags_still_block_historical_export(self):
        self.fresh()
        self.assertTrue(self.audit()['eligible'])
        self.assertTrue(self.policy.mark_started(self.context))
        self.policy.observe(self.context, dict(self.stats, seconds=10), [], True, save_key=self.save_key)
        self.policy.observe(self.context, self.stats, [], True, save_key=self.save_key)
        self.assertFalse(self.policy.can_export(self.context))

    def test_category_prompt_precedes_recording(self):
        self.fresh(select=False)
        self.assertTrue(self.policy.snapshot()['needsSelection'])
        self.assertFalse(self.audit()['eligible'])
        self.policy.select('any-percent-glitchless')
        self.assertTrue(self.audit()['eligible'])

    def test_witnessed_fresh_start_candidate_then_unlock_and_consume(self):
        self.fresh()
        self.assertFalse(self.policy.can_record(self.context))
        result = self.audit()
        self.assertTrue(result['eligible'])
        self.assertEqual(result['status'], 'candidate')
        self.assertIn('not anti-cheat', ' '.join(result['startEvidence']))
        self.assertTrue(self.policy.mark_started(self.context))
        self.assertTrue(self.policy.snapshot()['recordingUnlocked'])
        self.assertEqual(self.policy.snapshot()['status'], 'recording-unlocked')
        self.assertTrue(self.policy.can_record(self.context))
        self.assertFalse(self.audit()['eligible'])
        self.assertFalse(self.policy.mark_started(self.context))

    def test_imported_zero_time_save_without_witness_is_blocked(self):
        self.policy.select('any-percent-glitchless')
        self.policy.observe_roster(self.save_key, [self.stats], True)
        self.policy.observe(self.context, self.stats, [], True, save_key=self.save_key)
        self.assertFalse(self.audit()['eligible'])
        self.assertFalse(self.policy.mark_started(self.context))

    def test_roster_must_be_observed_in_same_process(self):
        self.policy.observe_roster(self.save_key, [], True)
        self.policy = RunPolicy(self.path)
        self.policy.select('any-percent-glitchless')
        self.policy.observe_roster(self.save_key, [self.stats], True)
        self.policy.observe(self.context, self.stats, [], True, save_key=self.save_key)
        self.assertFalse(self.audit()['eligible'])

    def test_game_must_be_running_during_both_roster_samples(self):
        for first, second in ((False, True), (True, False), (False, False)):
            with self.subTest(first=first, second=second):
                policy = RunPolicy(self.path / f'{first}{second}')
                policy.select('any-percent-glitchless')
                policy.observe_roster(self.save_key, [], first)
                policy.observe_roster(self.save_key, [self.stats], second)
                policy.observe(self.context, self.stats, [], True, save_key=self.save_key)
                self.assertFalse(policy.audit_for_start(self.context, self.timer)['eligible'])

    def test_game_stop_breaks_roster_continuity(self):
        self.policy.select('any-percent-glitchless')
        self.policy.observe_roster(self.save_key, [], True)
        self.policy.observe_roster(self.save_key, [], False)
        self.policy.observe_roster(self.save_key, [self.stats], True)
        self.policy.observe(self.context, self.stats, [], True, save_key=self.save_key)
        self.assertFalse(self.audit()['eligible'])

    def test_game_stop_expires_already_bound_fresh_window(self):
        self.fresh()
        self.policy.observe_roster(self.save_key, [self.stats], False)
        self.assertFalse(self.audit()['eligible'])

    def test_roster_gap_over_thirty_seconds_does_not_witness(self):
        self.policy.select('any-percent-glitchless')
        self.policy.observe_roster(self.save_key, [], True)
        self.clock += 31
        self.policy.observe_roster(self.save_key, [self.stats], True)
        self.policy.observe(self.context, self.stats, [], True, save_key=self.save_key)
        self.assertFalse(self.audit()['eligible'])

    def test_continuous_unchanged_rosters_keep_witness_possible(self):
        self.policy.select('any-percent-glitchless')
        for _ in range(20):
            self.policy.observe_roster(self.save_key, [], True)
            self.clock += 5
        self.policy.observe_roster(self.save_key, [self.stats], True)
        self.policy.observe(self.context, self.stats, [], True, save_key=self.save_key)
        self.assertTrue(self.audit()['eligible'])

    def test_existing_occupied_slot_replacement_cannot_self_witness(self):
        self.policy.select('any-percent-glitchless')
        self.policy.observe_roster(self.save_key, [dict(slot=0, seconds=10000)], True)
        self.policy.observe_roster(self.save_key, [self.stats], True)
        self.policy.observe(self.context, self.stats, [], True, save_key=self.save_key)
        self.assertFalse(self.audit()['eligible'])

    def test_birth_is_bound_to_correct_file_and_slot(self):
        self.policy.select('any-percent-glitchless')
        self.policy.observe_roster(self.save_key, [], True)
        self.policy.observe_roster(self.save_key, [dict(slot=1)], True)
        self.policy.observe(self.context, self.stats, [], True, save_key=self.save_key)
        self.assertFalse(self.audit()['eligible'])
        self.policy.observe('v2:character_b:j1', dict(self.stats, slot=1), [], True, save_key='other-save')
        self.assertFalse(self.policy.audit_for_start('v2:character_b:j1', self.timer)['eligible'])

    def test_birth_cannot_be_reused_by_rotated_context(self):
        self.fresh()
        other = 'v2:character_b:j1'
        self.policy.observe(other, self.stats, [], True, save_key=self.save_key)
        self.assertFalse(self.policy.audit_for_start(other, self.timer)['eligible'])

    def test_saved_progress_prevents_start_even_inside_runtime_window(self):
        self.fresh()
        for changes, killed in ((dict(seconds=31), []), (dict(deaths=1), []), ({}, [123])):
            with self.subTest(changes=changes, killed=killed):
                self.policy.observe(self.context, dict(self.stats, **changes), killed, True, save_key=self.save_key)
                self.assertFalse(self.audit()['eligible'])

    def test_start_window_expires_even_when_save_stays_fresh(self):
        self.fresh()
        self.clock += 31
        self.assertFalse(self.audit()['eligible'])

    def test_timer_must_be_configured_running_and_near_start(self):
        self.fresh()
        for changes in ({'connected': False}, {'configured': False}, {'phase': 'Paused'},
                        {'phase': 'NotRunning'}, {'gameTimeSeconds': None},
                        {'gameTimeSeconds': 2.01}, {'gameTimeSeconds': -1}, {'gameTimeSeconds': float('nan')}):
            with self.subTest(changes=changes):
                self.assertFalse(self.audit(**changes)['eligible'])

    def test_category_match_is_explicit_not_fuzzy_or_prefix(self):
        self.fresh()
        for category in ('Any%', 'Any% Restricted', 'Any% Glitchless extra', 'All Remembrances Glitchless'):
            with self.subTest(category=category):
                self.assertFalse(self.audit(categoryName=category)['eligible'])
        self.assertTrue(self.audit(categoryName='  any%   GLITCHLESS  ')['eligible'])

    def test_bare_category_can_match_explicit_glitchless_variable(self):
        self.fresh()
        self.assertTrue(self.audit(categoryName='Any%', categoryVariables={'variables': {'Any% - Subcategories': 'Glitchless'}})['eligible'])
        for values in ({'Glitches': 'Restricted'}, {'Glitchless': 'No'}, {'Glitches': 'Glitchless-ish'}, {'Route': 1}):
            self.assertFalse(self.audit(categoryName='Any%', categoryVariables={'variables': values})['eligible'])

    def test_correct_variable_cannot_match_wrong_main_category(self):
        self.fresh()
        self.assertFalse(self.audit(categoryName='Defeat Consort', categoryVariables={'variables': {'Glitches': 'Glitchless'}})['eligible'])

    def test_early_timer_start_can_bind_after_save_poll_delay(self):
        self.policy.observe_timer(self.timer)
        self.clock += 3
        self.fresh()
        later = dict(self.timer, gameTimeSeconds=4.5)
        self.policy.observe_timer(later)
        result = self.policy.audit_for_start(self.context, later)
        self.assertTrue(result['eligible'])
        self.assertEqual(result['status'], 'review-required')
        self.assertIn('0.500s', ' '.join(result['startEvidence']))
        self.assertIn('partial', result['reason'])

    def test_observed_notrunning_to_running_boundary_can_bind_late(self):
        self.policy.observe_timer(dict(self.timer, phase='NotRunning', attemptCount=0, gameTimeSeconds=0))
        self.clock += 4
        self.policy.observe_timer(dict(self.timer, gameTimeSeconds=3))
        self.fresh()
        self.assertTrue(self.audit(gameTimeSeconds=5)['eligible'])

    def test_first_running_sample_at_twenty_seconds_does_not_invent_start(self):
        self.policy.observe_timer(dict(self.timer, gameTimeSeconds=20))
        self.fresh()
        self.assertFalse(self.audit(gameTimeSeconds=21)['eligible'])

    def test_cached_start_is_tied_to_exact_attempt_identity(self):
        self.policy.observe_timer(self.timer)
        self.fresh()
        for changes in ({'attemptCount': 2}, {'gameName': 'Different game'}, {'categoryName': 'Any% - Glitchless'}):
            self.assertFalse(self.audit(gameTimeSeconds=5, **changes)['eligible'])

    def test_cached_start_expires_on_disconnect_reset_or_backwards_time(self):
        for change in ({'connected': False}, {'phase': 'NotRunning'}, {'gameTimeSeconds': 0.1}):
            with self.subTest(change=change):
                self.policy.observe_timer(self.timer)
                self.fresh()
                self.policy.observe_timer(dict(self.timer, **change))
                self.assertFalse(self.audit(gameTimeSeconds=5)['eligible'])
                self.policy = RunPolicy(self.path / str(len(self.policy.records)))

    def test_cached_start_does_not_extend_on_repeated_running_samples(self):
        self.policy.observe_timer(self.timer)
        self.clock += 29
        self.policy.observe_timer(dict(self.timer, gameTimeSeconds=1))
        self.fresh()
        self.clock += 2
        self.assertFalse(self.audit(gameTimeSeconds=5)['eligible'])

    def test_subcategory_variable_change_invalidates_cached_start(self):
        initial = dict(self.timer, categoryName='Any%', categoryVariables={'variables': {'Glitches': 'Restricted'}})
        self.policy.observe_timer(initial)
        self.fresh()
        current = dict(initial, gameTimeSeconds=5, categoryVariables={'variables': {'Glitches': 'Glitchless'}})
        self.policy.observe_timer(current)
        self.assertFalse(self.policy.audit_for_start(self.context, current)['eligible'])

    def test_cannot_mark_started_without_recent_successful_audit(self):
        self.fresh()
        self.assertFalse(self.policy.mark_started(self.context))
        self.assertTrue(self.audit()['eligible'])
        self.clock += 3
        self.assertFalse(self.policy.mark_started(self.context))

    def test_changed_selection_cannot_consume_prior_approval(self):
        self.fresh()
        self.assertTrue(self.audit()['eligible'])
        self.policy.select('defeat-consort-glitchless')
        self.assertFalse(self.policy.mark_started(self.context))

    def test_failed_subsequent_audit_revokes_pending_approval(self):
        self.fresh()
        self.assertTrue(self.audit()['eligible'])
        self.assertFalse(self.audit(connected=False)['eligible'])
        self.assertFalse(self.policy.mark_started(self.context))

    def test_integrity_flags_block_further_recording_after_unlock(self):
        self.fresh()
        self.assertTrue(self.audit()['eligible'])
        self.policy.mark_started(self.context)
        self.policy.observe(self.context, dict(self.stats, seconds=100, deaths=4), [1], True)
        self.policy.observe(self.context, dict(self.stats, seconds=90, deaths=4), [1], True)
        self.assertFalse(self.policy.can_record(self.context))
        self.assertFalse(self.policy.snapshot()['recordingUnlocked'])
        self.assertEqual(self.policy.snapshot()['status'], 'blocked')
        self.assertIn('backward', self.policy.snapshot()['notice'])

    def test_new_journey_never_unlocks_recording(self):
        self.fresh()
        self.assertTrue(self.audit()['eligible'])
        self.policy.mark_started(self.context)
        next_context = 'v2:character_a:j2'
        self.policy.observe(next_context, dict(self.stats, journey=2, seconds=100000, deaths=10), [], True, save_key=self.save_key)
        self.assertFalse(self.policy.can_record(next_context))
        self.assertFalse(self.policy.audit_for_start(next_context, self.timer)['eligible'])
        self.assertIn('NG+', self.policy.snapshot()['notice'])

    def test_consumption_and_unlock_persist_but_new_start_window_does_not(self):
        self.fresh()
        self.assertTrue(self.audit()['eligible'])
        self.policy.mark_started(self.context)
        self.policy = RunPolicy(self.path)
        self.policy.observe(self.context, dict(self.stats, seconds=500), [1], True, save_key=self.save_key)
        self.assertTrue(self.policy.can_record(self.context))
        self.assertFalse(self.audit()['eligible'])

    def test_restart_does_not_renew_unconsumed_capture_window(self):
        self.fresh()
        self.policy = RunPolicy(self.path)
        self.policy.observe(self.context, self.stats, [], True, save_key=self.save_key)
        self.assertFalse(self.audit()['eligible'])
        self.assertFalse(self.policy.can_record(self.context))

    def test_same_context_backwards_save_values_produce_durable_flags(self):
        self.fresh()
        self.policy.observe(self.context, dict(self.stats, seconds=100, deaths=4), [1, 2], True)
        self.policy.observe(self.context, dict(self.stats, seconds=80, deaths=3), [1], True)
        codes = {f['code'] for f in self.policy.snapshot()['flags']}
        self.assertEqual(codes, {'playtime-moved-backward', 'deaths-moved-backward', 'boss-progress-moved-backward'})
        self.policy = RunPolicy(self.path)
        self.policy.observe(self.context, dict(self.stats, seconds=101, deaths=4), [1, 2], True)
        self.assertEqual({f['code'] for f in self.policy.snapshot()['flags']}, codes)
        self.assertFalse(self.audit()['eligible'])

    def test_flags_are_not_duplicates_on_repeated_reads(self):
        self.fresh()
        self.policy.observe(self.context, dict(self.stats, seconds=10), [], True)
        for _ in range(3):
            self.policy.observe(self.context, dict(self.stats, seconds=5), [], True)
            self.policy.observe(self.context, dict(self.stats, seconds=10), [], True)
        self.assertEqual(len(self.policy.snapshot()['flags']), 1)

    def test_custom_category_retains_name_but_is_review_required(self):
        self.fresh(select=False)
        self.policy.select('custom', 'My route')
        result = self.audit(categoryName='My route')
        self.assertTrue(result['eligible'])
        self.assertEqual(result['status'], 'review-required')
        self.assertEqual(result['categoryName'], 'My route')
        self.assertEqual(RunPolicy(self.path).snapshot()['name'], 'My route')

    def test_invalid_or_unnamed_category_cannot_override_selection(self):
        self.policy.select('any-percent-glitchless')
        for category, name in (('invented', None), ('custom', ''), ('custom', '   ')):
            with self.assertRaises(ValueError):
                self.policy.select(category, name)
        self.assertEqual(self.policy.snapshot()['selectedId'], 'any-percent-glitchless')

    def test_dlc_category_is_fresh_character_not_area_entry(self):
        self.policy.select('defeat-consort-glitchless')
        self.policy.observe_roster(self.save_key, [dict(self.stats, seconds=50000)], True)
        self.policy.observe(self.context, dict(self.stats, seconds=50000), [1, 2], True, save_key=self.save_key)
        result = self.audit(categoryName='Defeat Consort Glitchless')
        self.assertFalse(result['eligible'])
        self.assertIn('prepared DLC save', result['reason'])
        category = next(c for c in CATEGORIES if c['id'] == 'defeat-consort-glitchless')
        self.assertIn('Circlet of Light', category['startNote'])
        self.assertIn('not DLC entry', category['startNote'])

    def test_all_remembrance_scopes_are_distinct(self):
        categories = {c['id']: c for c in CATEGORIES}
        self.assertEqual(categories['all-remembrances-no-dlc-glitchless']['scope'], 'Base game')
        self.assertEqual(categories['all-remembrances-glitchless']['scope'], 'Base game + DLC')
        self.assertIn('Heart of Bayle', categories['all-remembrances-glitchless']['startNote'])

    def test_corrupt_history_is_not_silently_replaced(self):
        self.path.joinpath('run-policy.json').write_text('{broken', encoding='utf-8')
        self.policy = RunPolicy(self.path)
        self.fresh()
        self.assertFalse(self.audit()['eligible'])
        self.assertIn('could not be read', self.policy.snapshot()['notice'])
        self.assertEqual(self.path.joinpath('run-policy.json').read_text(), '{broken')

    def test_unreadable_save_does_not_start_or_erase_evidence(self):
        self.fresh()
        self.policy.observe(self.context, None, [], False)
        self.assertFalse(self.audit()['eligible'])
        self.policy.observe(self.context, self.stats, [], True, save_key=self.save_key)
        self.assertTrue(self.audit()['eligible'])

    def test_invalid_context_and_nonfinite_values_do_not_start(self):
        self.fresh()
        for stats in (dict(self.stats, seconds=float('nan')), dict(self.stats, deaths=-1),
                      dict(self.stats, journey=2), dict(self.stats, slot=[])):
            self.policy.observe(self.context, stats, [], True, save_key=self.save_key)
            self.assertFalse(self.audit()['eligible'])
        self.policy.observe('pending', self.stats, [], True)
        self.assertFalse(self.policy.audit_for_start('pending', self.timer)['eligible'])

    def test_policy_file_does_not_store_raw_save_path(self):
        self.fresh()
        data = json.loads(self.policy.path.read_text(encoding='utf-8'))
        self.assertNotIn('savePath', data)
        self.assertNotIn('rosters', data)
        self.assertEqual(data['schemaVersion'], 1)


if __name__ == '__main__':
    unittest.main()
