"""External timing observations remain separate from timer control and save time."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from external_run import ExternalRun, duration


def sample(**changes):
    result = dict(connected=True, configured=True, phase='Running', attemptCount=7,
        gameName='Elden Ring', categoryName='Any%', gameTimeSeconds=1.0,
        realTimeSeconds=1.5, note='Fixture timer')
    result.update(changes)
    return result


def stats(**changes):
    result = dict(name='First character', journey=1, seconds=1000, deaths=10)
    result.update(changes)
    return result


def policy(**changes):
    result = dict(eligible=True, status='candidate', reason='Observed fresh character.',
        categoryId='any-percent', categoryName='Any%',
        rulesUrl='https://www.speedrun.com/eldenring',
        startEvidence=['Fresh character observed', 'LiveSplit auto-start observed'])
    result.update(changes)
    return result


class ExternalRunTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.run = ExternalRun(self.directory)

    def observe(self, timer=None, profile=None, context='first:j1', killed=None,
                ready=True, process='running', now=0, audit=None, capture=True):
        self.run.observe(sample() if timer is None else timer, context,
            stats() if profile is None else profile, set() if killed is None else killed,
            {1: 'Margit', 2: 'Godrick'}, ready, process, now, start_audit=audit, capture_enabled=capture)

    def test_record_waits_for_running_and_valid_active_character(self):
        for phase in ['NotRunning', 'Paused', 'Ended']:
            self.observe(sample(phase=phase))
            self.assertIsNone(self.run.record)
            snapshot = self.run.snapshot(0)
            self.assertFalse(snapshot['exportAvailable'])
            self.assertIn('No running attempt', snapshot['notice'])
        self.observe(ready=False)
        self.assertIsNone(self.run.record)
        self.assertIn('active-character save', self.run.snapshot(0)['notice'])
        self.observe(context='pending')
        self.assertIsNone(self.run.record)
        self.observe(profile=stats(seconds=float('nan')))
        self.assertIsNone(self.run.record)
        self.observe()
        self.assertEqual(self.run.record['status'], 'running')
        self.assertTrue(self.run.snapshot(0)['exportAvailable'])

    def test_first_connection_ended_cannot_create_a_historical_result(self):
        self.observe(sample(phase='Ended', gameTimeSeconds=1000))
        self.assertIsNone(self.run.record)
        with self.assertRaisesRegex(ValueError, 'No LiveSplit run'):
            self.run.export_text()

    def test_timer_is_copied_without_extrapolation_or_save_clock_substitution(self):
        self.observe(sample(gameTimeSeconds=10), stats(seconds=9000))
        self.assertEqual(self.run.snapshot(2)['elapsedSeconds'], 10)
        self.assertIsNone(self.run.snapshot(3)['elapsedSeconds'])
        self.assertIn('stale', self.run.snapshot(3)['notice'])
        self.observe(sample(gameTimeSeconds=12, phase='Paused'), stats(seconds=12000), now=4)
        self.assertEqual(self.run.snapshot(5)['elapsedSeconds'], 12)
        self.assertEqual(self.run.snapshot(5)['status'], 'paused')
        self.assertEqual(self.run.record['igtSeconds'], 3000)
        self.assertFalse(self.run.snapshot(5)['sourceVerified'])
        self.assertTrue(self.run.snapshot(5)['controlsLocked'])

    def test_disconnect_withholds_time_and_reconnects_without_estimating_gap(self):
        self.observe(sample(gameTimeSeconds=10))
        self.observe(dict(connected=False, configured=False, note='Disconnected'), now=1)
        self.assertIsNone(self.run.snapshot(1)['elapsedSeconds'])
        self.assertEqual(self.run.record['elapsedSeconds'], 10)
        self.observe(sample(gameTimeSeconds=20), now=2)
        self.assertEqual(self.run.record['elapsedSeconds'], 20)
        messages = [event['message'] for event in self.run.record['events']]
        self.assertTrue(any('lost' in message for message in messages))
        self.assertTrue(any('restored' in message for message in messages))

    def test_process_disappearance_does_not_pause_or_diagnose_a_crash(self):
        self.observe()
        self.observe(sample(gameTimeSeconds=3), process='exited', now=1)
        self.assertEqual(self.run.record['status'], 'running')
        self.assertEqual(self.run.record['elapsedSeconds'], 3)
        messages = [event['message'] for event in self.run.record['events']]
        self.assertTrue(any('cause unknown' in message for message in messages))
        self.observe(sample(gameTimeSeconds=8), process='running', now=2)
        self.assertEqual(self.run.record['elapsedSeconds'], 8)

    def test_defeats_and_deaths_cover_only_this_observation(self):
        self.observe(killed={1})
        self.observe(sample(gameTimeSeconds=8), stats(seconds=1010, deaths=12), killed={1, 2}, now=1)
        self.assertEqual(self.run.record['deaths'], 2)
        self.assertEqual(self.run.record['igtSeconds'], 10)
        self.assertEqual([row['bossId'] for row in self.run.record['splits']], [2])
        self.assertEqual(self.run.record['splits'][0]['elapsedSeconds'], 8)

    def test_finished_results_do_not_change_with_later_saves_or_timer_edits(self):
        self.observe()
        self.observe(sample(phase='Ended', gameTimeSeconds=10), stats(seconds=1020, deaths=11), killed={1}, now=1)
        completed = copy.deepcopy(self.run.record)
        self.observe(sample(phase='Ended', gameTimeSeconds=20), stats(seconds=1050, deaths=15),
                     context='second:j2', killed={1, 2}, now=2)
        self.assertEqual(self.run.record, completed)
        self.assertIn('00:00:10.000', self.run.export_text())

    def test_new_attempt_archives_old_record_and_rebinds_character(self):
        self.observe()
        previous = self.run.record['recordId']
        self.observe(sample(attemptCount=8), stats(name='Second character', journey=2, seconds=50, deaths=2),
                     context='second:j2', killed={2}, now=1)
        archive = json.loads((self.directory / 'run-records' / (previous + '.json')).read_text(encoding='utf-8'))
        self.assertEqual(archive['contextKey'], 'first:j1')
        self.assertNotEqual(self.run.record['recordId'], previous)
        self.assertEqual(self.run.record['contextKey'], 'second:j2')
        self.assertEqual(self.run.record['deaths'], 0)
        self.assertEqual(self.run.record['splits'], [])

    def test_character_or_journey_change_stops_save_attribution_for_whole_attempt(self):
        self.observe()
        self.observe(sample(gameTimeSeconds=5), stats(seconds=1010, deaths=11), killed={1}, now=1)
        self.observe(sample(gameTimeSeconds=7), stats(seconds=9999, deaths=100), context='first:j2', killed={1, 2}, now=2)
        self.observe(sample(gameTimeSeconds=9), stats(seconds=1020, deaths=12), killed={1, 2}, now=3)
        self.assertTrue(self.run.record['attributionLost'])
        self.assertEqual(self.run.record['deaths'], 1)
        self.assertEqual(len(self.run.record['splits']), 1)
        self.assertEqual(self.run.record['elapsedSeconds'], 9)

    def test_save_regression_is_detected_against_last_sample_not_only_baseline(self):
        self.observe()
        self.observe(sample(gameTimeSeconds=5), stats(seconds=1020, deaths=12), now=1)
        self.observe(sample(gameTimeSeconds=7), stats(seconds=1010, deaths=11), now=2)
        self.assertTrue(self.run.record['attributionLost'])
        self.assertEqual(self.run.record['igtSeconds'], 20)
        self.assertEqual(self.run.record['deaths'], 2)

    def test_reset_retains_old_result_until_a_new_running_attempt_even_if_id_reused(self):
        self.observe(sample(gameTimeSeconds=10))
        previous = self.run.record['recordId']
        self.observe(sample(phase='NotRunning', gameTimeSeconds=0), now=1)
        self.assertEqual(self.run.record['status'], 'reset')
        self.assertEqual(self.run.record['elapsedSeconds'], 10)
        self.observe(sample(phase='Paused', gameTimeSeconds=0), now=2)
        self.assertEqual(self.run.record['recordId'], previous)
        self.observe(sample(gameTimeSeconds=0), now=3)
        self.assertNotEqual(self.run.record['recordId'], previous)
        self.assertEqual(self.run.record['status'], 'running')

    def test_different_attempt_without_character_does_not_display_old_statistics(self):
        self.observe()
        self.observe(sample(gameTimeSeconds=5), stats(seconds=1010, deaths=12), killed={1}, now=1)
        self.observe(sample(attemptCount=8, gameTimeSeconds=1), context='pending', ready=False, now=2)
        result = self.run.snapshot(2)
        self.assertEqual(result['elapsedSeconds'], 1)
        self.assertIsNone(result['contextKey'])
        self.assertIsNone(result['deaths'])
        self.assertEqual(result['splits'], [])
        self.assertFalse(result['recordMatchesTimer'])
        self.assertTrue(result['exportAvailable'])
        self.assertIn('previously observed run', result['notice'])

    def test_restart_retains_record_but_does_not_assume_unobserved_continuity(self):
        self.observe(sample(gameTimeSeconds=10))
        previous = self.run.record['recordId']
        self.run = ExternalRun(self.directory)
        self.assertIsNone(self.run.snapshot(0)['elapsedSeconds'])
        self.assertTrue(self.run.record['continuityUnverified'])
        self.observe(sample(gameTimeSeconds=20), now=1)
        self.assertEqual(self.run.record['recordId'], previous)
        self.assertEqual(self.run.record['elapsedSeconds'], 20)
        self.assertTrue(self.run.record['partial'])

    def test_reused_attempt_identifier_with_lower_time_after_restart_gets_separate_record(self):
        self.observe(sample(gameTimeSeconds=20))
        previous = self.run.record['recordId']
        self.run = ExternalRun(self.directory)
        self.observe(sample(phase='Paused', gameTimeSeconds=1), now=1)
        self.assertEqual(self.run.record['elapsedSeconds'], 20)
        self.observe(sample(gameTimeSeconds=2), now=2)
        self.assertNotEqual(self.run.record['recordId'], previous)
        self.assertTrue(self.run.record['continuityUnverified'])
        self.assertEqual(self.run.record['elapsedSeconds'], 2)

    def test_malformed_nested_persistence_is_rejected_before_use(self):
        self.observe()
        valid = copy.deepcopy(self.run.record)
        mutations = [dict(identity=[True, 'Elden Ring', 'Any%']), dict(baseDeaths='10'),
            dict(splits=[{}]), dict(events=[{}]), dict(events=[dict(at=[], message={})]),
            dict(status={}), dict(seenKilled=[1, 1]), dict(seenKilled=[False]),
            dict(elapsedSeconds=float('nan')), dict(partial='false'), dict(recordId='../' * 10),
            dict(character={'nested': []}), dict(igtSeconds=-1), dict(continuityUnverified=1)]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                corrupted = copy.deepcopy(valid)
                corrupted.update(mutation)
                self.run.path.write_text(json.dumps(corrupted), encoding='utf-8')
                restored = ExternalRun(self.directory)
                self.assertIsNone(restored.record)
                self.assertTrue(restored.load_error)
                self.assertFalse(restored.snapshot(0)['exportAvailable'])

    def test_failed_archives_are_not_overwritten_and_remain_in_export_until_retry(self):
        self.observe()
        first = self.run.record['recordId']
        original_write = self.run._write
        def fail_archive(record, target):
            return False if target.parent.name == 'run-records' else original_write(record, target)
        with patch.object(self.run, '_write', side_effect=fail_archive):
            self.observe(sample(attemptCount=8), stats(name='Second'), now=1)
            second = self.run.record['recordId']
            self.observe(sample(attemptCount=9), stats(name='Third'), now=2)
            self.assertEqual(len(self.run.pending_archives), 2)
            self.assertTrue(self.run.storage_error)
            persisted = json.loads(self.run.path.read_text(encoding='utf-8'))
            self.assertEqual(persisted['recordId'], first)
            exported = self.run.export_text()
            self.assertIn(first, exported)
            self.assertIn(second, exported)
            self.assertIn(self.run.record['recordId'], exported)
            self.assertIn('2 pending archive', self.run.snapshot(2)['notice'])
        self.observe(sample(attemptCount=9, gameTimeSeconds=3), now=8)
        self.assertFalse(self.run.storage_error)
        self.assertEqual(self.run.pending_archives, [])
        self.assertTrue((self.directory / 'run-records' / (first + '.json')).is_file())
        self.assertTrue((self.directory / 'run-records' / (second + '.json')).is_file())
        self.assertEqual(json.loads(self.run.path.read_text(encoding='utf-8'))['recordId'], self.run.record['recordId'])

    def test_storage_failure_is_nonfatal_and_export_stays_available(self):
        with patch('external_run.Path.write_text', side_effect=PermissionError('read-only')):
            self.observe()
        self.assertTrue(self.run.storage_error)
        self.assertTrue(self.run.snapshot(0)['exportAvailable'])
        self.assertIn('could not be saved', self.run.snapshot(0)['notice'])
        report = self.run.export_text()
        self.assertIn('source initialization unverified', report)
        self.assertIn('no timer-control commands', report)
        self.assertIn('not proof of a leaderboard-valid run', report)

    def test_snapshots_and_inputs_cannot_mutate_internal_records(self):
        timer = sample()
        self.observe(timer)
        timer['gameTimeSeconds'] = 999
        result = self.run.snapshot(0)
        result['events'].clear()
        self.assertEqual(self.run.snapshot(0)['elapsedSeconds'], 1)
        self.assertNotEqual(self.run.record['events'], [])

    def test_invalid_external_time_is_withheld(self):
        for invalid in [float('nan'), float('inf'), True, '1', None]:
            with self.subTest(invalid=invalid):
                self.observe(sample(gameTimeSeconds=invalid))
                self.assertIsNone(self.run.record)
                self.assertIsNone(self.run.snapshot(0)['elapsedSeconds'])

    def test_duration_handles_offsets_and_invalid_values(self):
        self.assertEqual(duration(-1.25), '-00:00:01.250')
        self.assertEqual(duration(90061.5), '25:01:01.500')
        self.assertEqual(duration(float('nan')), 'Unavailable')

    def test_ineligible_start_policy_keeps_external_display_without_creating_record(self):
        self.observe(audit=policy(eligible=False, status='blocked', reason='No fresh-character evidence.'))
        self.assertIsNone(self.run.record)
        snapshot = self.run.snapshot(0)
        self.assertEqual(snapshot['elapsedSeconds'], 1)
        self.assertFalse(snapshot['exportAvailable'])
        self.assertIn('No fresh-character evidence.', snapshot['notice'])
        self.assertEqual(snapshot['localAuditStatus'], 'not-started')

    def test_policy_is_frozen_and_later_ineligible_start_audit_does_not_discard_run(self):
        audit = policy()
        self.observe(audit=audit)
        record_id = self.run.record['recordId']
        audit['startEvidence'].clear()
        self.observe(sample(gameTimeSeconds=5), audit=policy(eligible=False, status='blocked',
            reason='A start is no longer fresh.'), now=1)
        self.assertEqual(self.run.record['recordId'], record_id)
        self.assertEqual(self.run.record['elapsedSeconds'], 5)
        self.assertEqual(self.run.record['runPolicy'], policy())
        report = self.run.export_text()
        self.assertIn('Declared category: Any%', report)
        self.assertIn('Category rules: https://www.speedrun.com/eldenring', report)
        self.assertIn('Fresh character observed', report)
        self.assertIn('not establish cheating or an official disqualification', report)

    def test_malformed_start_policy_fails_closed_and_malformed_saved_policy_is_rejected(self):
        self.observe(audit={'eligible': True, 'startEvidence': [{'nested': {}}]})
        self.assertIsNone(self.run.record)
        self.assertIn('malformed', self.run.snapshot(0)['notice'])
        self.observe(audit=policy())
        value = copy.deepcopy(self.run.record)
        value['runPolicy']['startEvidence'] = [{}]
        self.run.path.write_text(json.dumps(value), encoding='utf-8')
        self.assertIsNone(ExternalRun(self.directory).record)

    def test_local_audit_escalates_without_calling_it_an_official_ruling(self):
        self.observe()
        self.assertEqual(self.run.record['localAuditStatus'], 'no-issues-observed')
        self.observe(sample(gameTimeSeconds=4), process='exited', now=1)
        self.assertEqual(self.run.record['localAuditStatus'], 'review-required')
        self.observe(sample(gameTimeSeconds=2), now=2)
        self.assertEqual(self.run.record['localAuditStatus'], 'ineligible')
        self.observe(sample(gameTimeSeconds=6), process='running', now=3)
        self.assertEqual(self.run.record['localAuditStatus'], 'ineligible')
        self.assertIn('not an official leaderboard ruling', self.run.snapshot(3)['notice'])

    def test_partial_start_and_disconnect_require_local_review(self):
        self.observe(sample(gameTimeSeconds=20))
        self.assertEqual(self.run.record['localAuditStatus'], 'review-required')
        self.observe(dict(connected=False), now=1)
        self.assertTrue(any('connection' in reason for reason in self.run.record['localAuditReasons']))

    def test_category_metadata_edit_cannot_silently_replace_same_attempt_record(self):
        self.observe(audit=policy())
        record_id = self.run.record['recordId']
        self.observe(sample(categoryName='All Remembrances', gameTimeSeconds=5), audit=policy(), now=1)
        self.assertEqual(self.run.record['recordId'], record_id)
        self.assertEqual(self.run.record['category'], 'Any%')
        self.assertEqual(self.run.record['localAuditStatus'], 'ineligible')
        self.assertEqual(self.run.record['runPolicy']['categoryName'], 'Any%')

    def test_policy_and_local_audit_round_trip_through_validated_storage(self):
        self.observe(audit=policy())
        self.observe(sample(phase='Ended', gameTimeSeconds=5), audit=policy(), now=1)
        restored = ExternalRun(self.directory)
        self.assertIsNotNone(restored.record)
        self.assertEqual(restored.record['runPolicy'], policy())
        self.assertEqual(restored.record['localAuditStatus'], 'no-issues-observed')

    def test_category_variables_are_frozen_and_changes_flag_same_attempt(self):
        metadata = dict(region=None, platform='PC', usesEmulator=False, variables={'Rules': 'Glitchless'})
        self.observe(sample(categoryVariables=metadata), audit=policy())
        metadata['variables']['Rules'] = 'Unrestricted'
        self.observe(sample(categoryVariables=metadata, gameTimeSeconds=5), audit=policy(), now=1)
        self.assertEqual(self.run.record['categoryVariables']['variables'], {'Rules': 'Glitchless'})
        self.assertEqual(self.run.record['localAuditStatus'], 'ineligible')
        self.assertEqual(self.run.record['elapsedSeconds'], 1)
        self.assertEqual(self.run.snapshot(1)['localAuditStatus'], 'ineligible')
        self.assertFalse(self.run.snapshot(1)['recordMatchesTimer'])
        self.assertIn('Glitchless', self.run.export_text())
        restored = ExternalRun(self.directory)
        self.assertIsNotNone(restored.record)
        self.assertEqual(restored.record['categoryVariables']['variables'], {'Rules': 'Glitchless'})

    def test_reset_observation_has_an_end_bound_for_attempt_exports(self):
        self.observe()
        self.observe(sample(phase='NotRunning', gameTimeSeconds=0), now=1)
        self.assertEqual(self.run.record['status'], 'reset')
        self.assertIsNotNone(self.run.record['endedAt'])

    def test_unobserved_reset_closes_previous_attempt_when_next_start_is_blocked(self):
        self.observe(audit=policy())
        previous = self.run.record['recordId']
        self.observe(sample(attemptCount=8), audit=policy(eligible=False, status='blocked'), now=1)
        self.assertEqual(self.run.record['recordId'], previous)
        self.assertEqual(self.run.record['status'], 'reset')
        self.assertIsNotNone(self.run.record['endedAt'])
        self.assertEqual(self.run.record['localAuditStatus'], 'review-required')

    def test_capture_disabled_never_creates_records_but_can_mirror_external_time(self):
        self.observe(sample(gameTimeSeconds=1), audit=policy(), capture=False)
        self.assertIsNone(self.run.record)
        self.assertFalse(self.run.path.exists())
        self.assertEqual(self.run.snapshot(0)['elapsedSeconds'], 1)
        self.assertEqual(self.run.snapshot(0)['captureStatus'], 'off')
        self.run.suspend_capture()
        self.assertFalse(self.run.path.exists())

    def test_leaving_capture_closes_once_and_never_collects_hidden_updates(self):
        self.observe(sample(gameTimeSeconds=1), audit=policy())
        self.observe(sample(gameTimeSeconds=10), stats(seconds=1010, deaths=11), killed={1}, now=1)
        self.observe(sample(gameTimeSeconds=20), stats(seconds=1050, deaths=15), killed={1, 2}, now=2, capture=False)
        closed = copy.deepcopy(self.run.record)
        self.assertEqual(closed['status'], 'interrupted')
        self.assertIsNotNone(closed['endedAt'])
        self.assertEqual(closed['elapsedSeconds'], 10)
        self.assertEqual(closed['deaths'], 1)
        self.assertEqual(closed['localAuditStatus'], 'review-required')
        self.observe(sample(gameTimeSeconds=30), stats(seconds=1070, deaths=20), killed={1, 2}, process='absent', now=5, capture=False)
        self.assertEqual(self.run.record, closed)
        self.assertEqual(self.run.snapshot(5)['elapsedSeconds'], 30)

    def test_reentering_capture_cannot_resume_same_character_even_with_timer_reset(self):
        self.observe(audit=policy())
        self.run.suspend_capture(now=1)
        record_id = self.run.record['recordId']
        self.observe(sample(gameTimeSeconds=4), now=2, audit=policy())
        self.observe(sample(attemptCount=8, gameTimeSeconds=1), now=3, audit=policy())
        self.assertEqual(self.run.record['recordId'], record_id)
        self.assertEqual(self.run.record['status'], 'interrupted')
        self.assertEqual(self.run.record['elapsedSeconds'], 1)
        self.assertEqual(self.run.snapshot(3)['captureStatus'], 'interrupted')
        self.observe(sample(attemptCount=9, gameTimeSeconds=1), context='new:j1', now=4, audit=policy())
        self.assertNotEqual(self.run.record['recordId'], record_id)

    def test_finished_result_is_unchanged_when_capture_is_disabled(self):
        self.observe()
        self.observe(sample(phase='Ended', gameTimeSeconds=5), now=1)
        completed = copy.deepcopy(self.run.record)
        self.run.suspend_capture(now=2)
        self.assertEqual(self.run.record, completed)
        self.assertTrue(self.run.snapshot(2)['exportAvailable'])

    def test_capture_interruption_survives_restore_and_preserves_export_boundary(self):
        self.observe()
        self.run.suspend_capture(now=1)
        boundary = self.run.record['endedAt']
        self.run = ExternalRun(self.directory)
        self.observe(sample(gameTimeSeconds=8), audit=policy(), now=2)
        self.assertEqual(self.run.record['status'], 'interrupted')
        self.assertEqual(self.run.record['endedAt'], boundary)
        self.assertIn('Capture interruption:', self.run.export_text())


if __name__ == '__main__':
    unittest.main()
