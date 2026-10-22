"""Mirror LiveSplit without issuing timer controls or inventing game time."""
import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
import uuid
from livesplit_reader import parse_category_variables
from build_history import history_valid


def utc():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and abs(value) < 1e12


def duration(value):
    if not finite(value):
        return 'Unavailable'
    sign = '-' if value < 0 else ''
    ms = round(abs(value) * 1000)
    seconds, ms = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f'{sign}{hours:02}:{minutes:02}:{seconds:02}.{ms:03}'


def text(value, maximum=2048, nullable=False):
    return (nullable and value is None) or (isinstance(value, str) and len(value) <= maximum)


def count(value):
    return type(value) is int and 0 <= value <= 2147483647


def identity_valid(value):
    return (isinstance(value, list) and len(value) == 3 and count(value[0])
            and text(value[1], 512) and text(value[2], 512, nullable=True))


def policy_valid(value):
    if not isinstance(value, dict):
        return False
    fields = {'eligible', 'status', 'reason', 'categoryId', 'categoryName', 'rulesUrl', 'startEvidence'}
    evidence = value.get('startEvidence')
    return (not set(value) - fields and type(value.get('eligible')) is bool
            and text(value.get('status'), 128) and text(value.get('reason'), 2048)
            and text(value.get('categoryId'), 128) and text(value.get('categoryName'), 512)
            and text(value.get('rulesUrl'), 2048) and isinstance(evidence, list)
            and len(evidence) <= 32 and all(text(item, 512) for item in evidence))


def category_metadata_valid(value):
    if value is None:
        return True
    try:
        parse_category_variables(json.dumps(value, ensure_ascii=False, allow_nan=False))
        return True
    except (ValueError, TypeError, RecursionError):
        return False


def record_valid(value):
    """Validate every field used by restore, mutation, snapshot, and export."""
    if not isinstance(value, dict):
        return False
    fields = {'schemaVersion', 'recordId', 'identity', 'contextKey', 'character', 'journey',
              'category', 'startedAt', 'endedAt', 'status', 'baseSeconds', 'baseDeaths',
              'seenKilled', 'elapsedSeconds', 'realTimeSeconds', 'igtSeconds', 'deaths',
              'splits', 'events', 'partial', 'attributionLost', 'continuityUnverified',
              'runPolicy', 'localAuditStatus', 'localAuditReasons', 'categoryVariables', 'captureStoppedReason', 'buildHistory'}
    if set(value) - fields:
        return False
    if not history_valid(value.get('buildHistory')):
        return False
    nullable_time = lambda item: item is None or finite(item)
    nonnegative = lambda item: finite(item) and item >= 0
    if not (type(value.get('schemaVersion')) is int and value['schemaVersion'] == 1
            and text(value.get('recordId'), 32) and len(value['recordId']) == 32
            and all(c in '0123456789abcdef' for c in value['recordId'])
            and text(value.get('contextKey'), 1024) and value['contextKey'] not in ('', 'pending')
            and identity_valid(value.get('identity'))
            and text(value.get('character'), 512)
            and (value.get('journey') is None or count(value['journey']))
            and text(value.get('category'), 512, nullable=True)
            and category_metadata_valid(value.get('categoryVariables'))
            and text(value.get('startedAt'), 100) and value['startedAt']
            and text(value.get('endedAt'), 100, nullable=True)
            and value.get('status') in ('running', 'paused', 'finished', 'reset', 'interrupted')
            and text(value.get('captureStoppedReason'), 512, nullable=True)
            and all(nonnegative(value.get(key)) for key in ('baseSeconds', 'baseDeaths', 'igtSeconds', 'deaths'))
            and all(nullable_time(value.get(key)) for key in ('elapsedSeconds', 'realTimeSeconds'))
            and type(value.get('partial')) is bool and type(value.get('attributionLost')) is bool
            and type(value.get('continuityUnverified', False)) is bool
            and (value.get('runPolicy') is None or policy_valid(value['runPolicy']))
            and value.get('localAuditStatus', 'no-issues-observed') in ('no-issues-observed', 'review-required', 'ineligible')
            and isinstance(value.get('localAuditReasons', []), list)
            and len(value.get('localAuditReasons', [])) <= 128
            and all(text(reason, 2048) for reason in value.get('localAuditReasons', []))
            and isinstance(value.get('seenKilled'), list) and len(value['seenKilled']) <= 10000
            and all(count(item) for item in value['seenKilled'])
            and len(value['seenKilled']) == len(set(value['seenKilled']))
            and isinstance(value.get('splits'), list) and len(value['splits']) <= 10000
            and isinstance(value.get('events'), list) and len(value['events']) <= 10000):
        return False
    seen = set(value['seenKilled'])
    split_ids = set()
    for split in value['splits']:
        if not (isinstance(split, dict) and count(split.get('bossId'))
                and not set(split) - {'bossId', 'name', 'elapsedSeconds', 'igtSeconds', 'source'}
                and split['bossId'] in seen and split['bossId'] not in split_ids
                and text(split.get('name'), 512)
                and nullable_time(split.get('elapsedSeconds'))
                and nonnegative(split.get('igtSeconds')) and text(split.get('source'), 256)):
            return False
        split_ids.add(split['bossId'])
    return all(isinstance(event, dict) and not set(event) - {'at', 'message'} and text(event.get('at'), 100)
               and text(event.get('message'), 2048) for event in value['events'])


class ExternalRun:
    SOURCE_NOTE = ('LiveSplit output; use SoulSplitter with Game Time. The server cannot verify '
                   'mIGT initialization or certify leaderboard eligibility. Keep LiveSplit visible in the recording.')

    def __init__(self, data_dir):
        self.directory = Path(data_dir)
        self.path = self.directory / 'external-run.json'
        self.record = None
        self.sample = {}
        self.received = None
        self.last_phase = None
        self.last_process = 'unknown'
        self.last_connected = None
        self.last_persist = None
        self.storage_error = False
        self.pending_archives = []
        self.restored = False
        self.profile_ready = False
        self.load_error = False
        self.start_audit = None
        self.capture_enabled = True
        self.capture_notice = ''
        try:
            if self.path.stat().st_size > 5_000_000:
                raise ValueError('Run record is too large.')
            value = json.loads(self.path.read_text(encoding='utf-8'))
            if not record_valid(value):
                raise ValueError('Invalid saved run record.')
            self.record = value
            self.restored = True
            if self.record['status'] in ('running', 'paused'):
                self.record.update(partial=True, continuityUnverified=True)
                self._audit('review-required', 'Tracker restarted; continuous observation could not be verified.')
                self._event('Tracker restarted; external time will be read again. No offline time was synthesized.')
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, RecursionError):
            self.load_error = True

    def _event(self, message):
        if self.record is not None:
            self.record['events'].append(dict(at=utc(), message=message))
            self.record['events'] = self.record['events'][-10000:]

    def _audit(self, status, reason):
        """Local evidence flags, never an official leaderboard ruling."""
        if self.record is None:
            return
        priority = {'no-issues-observed': 0, 'review-required': 1, 'ineligible': 2}
        current = self.record.get('localAuditStatus', 'no-issues-observed')
        if priority[status] > priority[current]:
            self.record['localAuditStatus'] = status
        reasons = self.record.setdefault('localAuditReasons', [])
        if reason not in reasons:
            reasons.append(reason)
            del reasons[:-128]

    def _write(self, record, target):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_suffix('.tmp')
            temp.write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
            temp.replace(target)
            return True
        except (OSError, ValueError, TypeError):
            return False

    def _save(self, now, archive=False):
        if not self.record:
            return False
        if archive and not any(item['recordId'] == self.record['recordId'] for item in self.pending_archives):
            self.pending_archives.append(copy.deepcopy(self.record))
        # Preserve the preceding primary file if its archive cannot be written.
        # Unsaved records remain available in the export and are retried later.
        self.pending_archives = [record for record in self.pending_archives
            if not self._write(record, self.directory / 'run-records' / (record['recordId'] + '.json'))]
        success = not self.pending_archives and (archive or self._write(self.record, self.path))
        self.storage_error = not success
        self.last_persist = now
        return success

    @staticmethod
    def _sample_valid(sample):
        return (sample.get('connected') is True and sample.get('configured') is True
                and sample.get('phase') in ('NotRunning', 'Running', 'Paused', 'Ended')
                and finite(sample.get('gameTimeSeconds'))
                and (sample.get('realTimeSeconds') is None or finite(sample['realTimeSeconds']))
                and identity_valid([sample.get('attemptCount'), sample.get('gameName'), sample.get('categoryName')])
                and category_metadata_valid(sample.get('categoryVariables'))
                and sample['gameName'].casefold() == 'elden ring')

    def suspend_capture(self, reason='Speedrun view was closed; timing capture stopped.', now=None):
        """Close local observation only. Never pause or reset the external clock."""
        now = time.monotonic() if now is None else now
        reason = reason if text(reason, 512) and reason else 'Speedrun capture was disabled.'
        self.capture_enabled = False
        self.capture_notice = reason
        if self.record and self.record['status'] in ('running', 'paused'):
            self.record.update(status='interrupted', endedAt=utc(), partial=True, captureStoppedReason=reason)
            self.restored = False
            self._event(reason + ' The local observation was closed; LiveSplit was not changed.')
            self._audit('review-required', 'Speedrun capture stopped before the run endpoint; observation coverage is incomplete.')
            self._save(now)

    def observe(self, sample, context, stats, killed, boss_names, ready, process_state='unknown', now=None,
                start_audit=None, capture_enabled=True):
        now = time.monotonic() if now is None else now
        self.sample = copy.deepcopy(sample) if isinstance(sample, dict) else {}
        if start_audit is None:
            self.start_audit = None
        elif policy_valid(start_audit):
            self.start_audit = copy.deepcopy(start_audit)
        else:
            self.start_audit = dict(eligible=False, status='blocked',
                reason='Start-policy evidence was malformed; no run observation was created.',
                categoryId='', categoryName='', rulesUrl='', startEvidence=[])
        self.received = now
        if capture_enabled is not True:
            self.suspend_capture(now=now)
            return
        self.capture_enabled = True
        self.capture_notice = ''
        connected = self._sample_valid(self.sample)
        phase = self.sample.get('phase') if connected else None
        changed = False
        observing = self.record and self.record['status'] in ('running', 'paused')
        if observing and self.last_connected is not None and connected != self.last_connected:
            self._event('LiveSplit connection restored.' if connected else 'LiveSplit connection/configuration lost. Displayed timing withheld.')
            changed = True
            if not connected:
                self._audit('review-required', 'External timer connection or configuration was lost during observation.')
        self.last_connected = connected
        if observing and process_state != self.last_process:
            if process_state in ('absent', 'exited') and self.last_process == 'running':
                self._event('Game process ended: quit or crash, cause unknown. LiveSplit remains responsible for timing.')
                changed = True
                self._audit('review-required', 'The game process ended; whether this was a quit or crash is unknown.')
            elif process_state == 'running' and self.last_process in ('absent', 'exited'):
                self._event('Game process appeared again. External timer controls recovery timing.')
                changed = True
        self.last_process = process_state
        if not connected:
            if changed or (self.storage_error and (self.last_persist is None or now-self.last_persist >= 5)):
                self._save(now)
            return
        identity = [self.sample.get('attemptCount'), self.sample.get('gameName'), self.sample.get('categoryName')]
        good_profile = (bool(ready) and isinstance(stats, dict) and context not in ('', 'pending')
                        and text(context, 1024) and all(finite(stats.get(k)) and stats[k] >= 0 for k in ('seconds', 'deaths'))
                        and text(stats.get('name', ''), 512)
                        and (stats.get('journey') is None or count(stats['journey']))
                        and isinstance(killed, (set, frozenset, list, tuple)) and len(killed) <= 10000
                        and all(count(boss) for boss in killed))
        self.profile_ready = bool(good_profile)
        backwards_after_restart = (self.restored and self.record and self.record['identity'] == identity
            and finite(self.record.get('elapsedSeconds'))
            and self.sample['gameTimeSeconds'] < self.record['elapsedSeconds'] - .1)
        new = (self.record is None or self.record['identity'] != identity
               or self.record['status'] in ('reset', 'finished') or backwards_after_restart)
        if observing and self.record['identity'][0] != identity[0]:
            self.record.update(status='reset', endedAt=utc())
            self._event('A different LiveSplit attempt was observed before an Ended phase; the preceding observation was closed without inferring a finish.')
            self._audit('review-required', 'The external attempt changed before its endpoint was observed.')
            changed = True
        metadata_changed = (observing and self.record['identity'][0] == identity[0]
                            and (self.record['identity'][1:] != identity[1:]
                                 or self.record.get('categoryVariables') != self.sample.get('categoryVariables')))
        if metadata_changed:
            self._audit('ineligible', 'Game/category metadata changed during the same observed attempt; local run attribution is ineligible.')
            changed = True
        start_allowed = self.start_audit is None or self.start_audit['eligible'] is True
        interrupted_same_context = (self.record and self.record['status'] == 'interrupted'
                                    and context == self.record['contextKey'])
        if new and phase == 'Running' and good_profile and start_allowed and not metadata_changed and not interrupted_same_context:
            if self.record:
                self._event('A new LiveSplit observation began; the preceding record was queued for archival.')
                self._save(now, archive=True)
            current_time = self.sample.get('gameTimeSeconds')
            self.record = dict(schemaVersion=1, recordId=uuid.uuid4().hex, identity=identity,
                contextKey=context, character=stats.get('name', ''), journey=stats.get('journey'),
                category=self.sample.get('categoryName'), categoryVariables=copy.deepcopy(self.sample.get('categoryVariables')),
                startedAt=utc(), endedAt=None, status='running',
                baseSeconds=stats['seconds'], baseDeaths=stats['deaths'], seenKilled=sorted(killed),
                elapsedSeconds=current_time, realTimeSeconds=self.sample.get('realTimeSeconds'),
                igtSeconds=0, deaths=0, splits=[], events=[],
                partial=(current_time > 2 or bool(backwards_after_restart)), attributionLost=False,
                continuityUnverified=bool(backwards_after_restart), runPolicy=copy.deepcopy(self.start_audit),
                localAuditStatus='no-issues-observed', localAuditReasons=[], captureStoppedReason=None)
            self._event('Observing LiveSplit attempt. Boss and death counts cover observations after this record began.')
            if backwards_after_restart:
                self._event('Stored attempt time exceeded the newly connected timer; a separate observation avoids combining potentially reused attempt identifiers.')
            if self.record['partial']:
                self._audit('review-required', 'The observation began mid-run or after an ambiguous tracker restart.')
            self.restored = False
            changed = True
        record = self.record
        if record and record['identity'] == identity:
            if phase == 'NotRunning' and record['status'] not in ('reset', 'finished', 'interrupted'):
                record.update(status='reset', endedAt=utc())
                self._event('LiveSplit reset. Last observed values retained; no result was inferred.')
                changed = True
            if (phase in ('Running', 'Paused', 'Ended') and record['status'] not in ('finished', 'reset', 'interrupted')
                    and not (self.restored and backwards_after_restart) and not metadata_changed):
                self.restored = False
                for target, source in (('elapsedSeconds', 'gameTimeSeconds'), ('realTimeSeconds', 'realTimeSeconds')):
                    if finite(self.sample.get(source)):
                        previous = record.get(target)
                        if target == 'elapsedSeconds' and finite(previous) and self.sample[source] < previous - .1:
                            self._event('External game time moved backwards; review the original LiveSplit recording.')
                            record['partial'] = True
                            self._audit('ineligible', 'External game time moved backwards during this observation; local timing continuity is ineligible.')
                            changed = True
                        record[target] = self.sample[source]
                if good_profile and context != record['contextKey'] and not record['attributionLost']:
                    record['attributionLost'] = True
                    self._audit('ineligible', 'Character or journey changed during this attempt; local saved-stat attribution is ineligible.')
                    self._event('Character/journey changed; saved statistics stopped to avoid combining characters.')
                    changed = True
                if good_profile and context == record['contextKey'] and not record['attributionLost'] and record['status'] != 'finished':
                    fresh, seen = set(killed), set(record['seenKilled'])
                    if (stats['seconds']-record['baseSeconds'] < record['igtSeconds']
                            or stats['deaths']-record['baseDeaths'] < record['deaths'] or seen - fresh):
                        record['attributionLost'] = True
                        self._audit('ineligible', 'Saved progress regressed during this attempt; local saved-stat attribution is ineligible.')
                        self._event('Saved progress moved backwards; saved statistics no longer attributed.')
                        changed = True
                    else:
                        for boss in sorted(fresh - seen):
                            name = boss_names.get(boss) if isinstance(boss_names, dict) else None
                            record['splits'].append(dict(bossId=boss, name=name if text(name, 512) else str(boss),
                                elapsedSeconds=record.get('elapsedSeconds'), igtSeconds=stats['seconds']-record['baseSeconds'],
                                source='save flag observed; not an official split'))
                            changed = True
                        record.update(seenKilled=sorted(fresh), igtSeconds=stats['seconds']-record['baseSeconds'],
                                      deaths=stats['deaths']-record['baseDeaths'])
                if phase == 'Ended' and record['status'] != 'finished':
                    record.update(status='finished', endedAt=utc())
                    self._event('LiveSplit reported Ended. Category endpoint and eligibility require the original recording.')
                    changed = True
                elif phase != 'Ended' and record['status'] != 'finished':
                    record['status'] = 'running' if phase == 'Running' else 'paused'
        self.last_phase = phase
        if changed or self.last_persist is None or now-self.last_persist >= 5:
            self._save(now)

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        fresh = self.received is not None and 0 <= now-self.received <= 2.5
        valid = fresh and self._sample_valid(self.sample)
        phase = self.sample.get('phase') if valid else None
        identity = [self.sample.get('attemptCount'), self.sample.get('gameName'), self.sample.get('categoryName')]
        matches = bool(self.record and (not valid or (self.record['identity'] == identity
            and self.record.get('categoryVariables') == self.sample.get('categoryVariables'))))
        record = self.record if matches else {}
        same_attempt_metadata_changed = bool(valid and self.record
            and self.record['identity'][0] == identity[0] and (self.record['identity'][1:] != identity[1:]
                or self.record.get('categoryVariables') != self.sample.get('categoryVariables')))
        audit_record = self.record if same_attempt_metadata_changed else record
        status = {'NotRunning':'armed', 'Running':'running', 'Paused':'paused', 'Ended':'finished'}.get(phase, 'disconnected')
        fallback = 'Open LiveSplit, activate SoulSplitter, select Game Time, and start its TCP server on port 16834.'
        supplied_note = self.sample.get('note')
        note = self.SOURCE_NOTE if valid else supplied_note if text(supplied_note) and supplied_note else fallback
        if not fresh and self.received is not None:
            note = 'LiveSplit data is stale. Current time is withheld until the connection recovers.'
        if valid and not record:
            if self.record:
                note += (' LiveSplit metadata changed during the same attempt; export retains the original observation.'
                         if same_attempt_metadata_changed else ' This timer belongs to another attempt; export contains the previously observed run.')
            elif phase == 'Running' and not self.profile_ready:
                note += ' Waiting for a valid active-character save before recording this attempt.'
            else:
                note += ' No running attempt has been recorded. Recording begins when LiveSplit is Running and the active character is available.'
            if self.start_audit and self.start_audit['eligible'] is not True:
                note += ' ' + self.start_audit['reason']
        if record.get('partial'):
            note += ' Observation coverage is partial or interrupted.'
        if record.get('continuityUnverified'):
            note += ' Timer continuity across the tracker restart could not be verified.'
        if record.get('attributionLost'):
            note += ' Character changed or progress regressed; saved statistics are no longer attributed.'
        if self.storage_error:
            note += ' Run record could not be saved; export a copy while the app remains open.'
        if self.pending_archives:
            note += f' {len(self.pending_archives)} pending archive(s) are included in the text export.'
        if self.load_error:
            note += ' A saved observation was unreadable and was not used.'
        if audit_record.get('localAuditStatus') in ('review-required', 'ineligible'):
            note += ' Local audit: ' + audit_record['localAuditStatus'] + '; this is not an official leaderboard ruling.'
        if not self.capture_enabled:
            capture_status = 'off'
            capture_notice = self.capture_notice or 'Speedrun capture is off. Only the external timer display is read.'
        elif self.record and self.record['status'] == 'interrupted':
            capture_status = 'interrupted'
            capture_notice = (self.record.get('captureStoppedReason') or 'This observation was interrupted.') + ' It cannot resume; another run requires a new character.'
        elif record.get('status') in ('running', 'paused'):
            capture_status, capture_notice = 'recording', 'Capturing the observed LiveSplit run while Speedrun view is active.'
        elif record.get('status') in ('finished', 'reset'):
            capture_status, capture_notice = 'ended', 'This observation is closed; its saved result is preserved.'
        else:
            capture_status, capture_notice = 'armed', 'Waiting for a witnessed new character and the selected LiveSplit start.'
        return dict(status=status, timingSource='livesplit', timingLabel='LiveSplit Game Time', controlsLocked=True,
            sourceVerified=False, elapsedSeconds=self.sample.get('gameTimeSeconds') if valid and phase != 'NotRunning' else None,
            captureStatus=capture_status, captureNotice=capture_notice,
            realTimeSeconds=self.sample.get('realTimeSeconds') if valid and phase != 'NotRunning' else None,
            contextKey=record.get('contextKey'), character=record.get('character'), journey=record.get('journey'),
            category=self.sample.get('categoryName'), igtSeconds=record.get('igtSeconds'), deaths=record.get('deaths'),
            categoryVariables=copy.deepcopy(self.sample.get('categoryVariables')) if valid else None,
            bossesDefeated=len(record.get('splits', [])), splits=copy.deepcopy(record.get('splits', [])),
            startedAt=record.get('startedAt'), endedAt=record.get('endedAt'), notice=note,
            exportAvailable=bool(self.record), recordMatchesTimer=matches,
            runPolicy=copy.deepcopy(audit_record.get('runPolicy')), startAudit=copy.deepcopy(self.start_audit),
            localAuditStatus=audit_record.get('localAuditStatus', 'no-issues-observed' if audit_record else 'not-started'),
            localAuditReasons=copy.deepcopy(audit_record.get('localAuditReasons', [])),
            events=copy.deepcopy(record.get('events', [])))

    def export_text(self):
        if not self.record:
            raise ValueError('No LiveSplit run has been observed yet. Start the run in LiveSplit first.')
        lines = self._export_record(self.record)
        for record in self.pending_archives:
            if record['recordId'] != self.record['recordId']:
                lines.extend(['', 'PENDING ARCHIVE — INCLUDED TO PRESERVE AN UNSAVED PREVIOUS ATTEMPT', ''])
                lines.extend(self._export_record(record))
        return '\n'.join(lines)

    def _export_record(self, r):
        clean = lambda value: ' '.join(str(value).split())
        policy = r.get('runPolicy') or {}
        lines = ['TARNISHED LINEUP — EXTERNAL TIMER OBSERVATION', '',
            f'Exported UTC: {utc()}', 'Timing source: LiveSplit Game Time output (source initialization unverified)',
            f'Category: {clean(r.get("category"))}', f'Character: {clean(r.get("character"))}', f'Journey: {r.get("journey")}',
            'LiveSplit category metadata: ' + clean(json.dumps(r.get('categoryVariables'), ensure_ascii=False, sort_keys=True)),
            f'Record began UTC: {r.get("startedAt")}', f'External end observed UTC: {r.get("endedAt") or "Not observed"}',
            f'Observation ID: {r.get("recordId")}', f'LiveSplit attempt count: {r["identity"][0]}',
            f'Declared category: {clean(policy.get("categoryName") or "Not specified")}',
            f'Declared category ID: {clean(policy.get("categoryId") or "Not specified")}',
            f'Category rules: {clean(policy.get("rulesUrl") or "Not recorded")}',
            f'Start-policy status: {clean(policy.get("status") or "Not recorded")}',
            f'Start-policy reason: {clean(policy.get("reason") or "Not recorded")}',
            f'Start evidence: {clean("; ".join(policy.get("startEvidence", [])) or "Not recorded")}',
            f'Local audit status: {r.get("localAuditStatus", "no-issues-observed")}',
            f'Local audit reasons: {clean("; ".join(r.get("localAuditReasons", [])) or "No issues observed; eligibility unverified")}',
            f'Record status: {r.get("status")}', f'Last observed external game time: {duration(r.get("elapsedSeconds"))}',
            f'Capture interruption: {clean(r.get("captureStoppedReason") or "None observed")}',
            f'Last observed external real time: {duration(r.get("realTimeSeconds"))}',
            f'Saved character clock delta: {duration(r.get("igtSeconds"))}', f'Observed saved deaths: {r.get("deaths")}',
            f'Observed saved boss defeats: {len(r.get("splits", []))}',
            f'Partial/interrupted coverage: {bool(r.get("partial"))}',
            f'Restart continuity unverified: {bool(r.get("continuityUnverified"))}',
            f'Saved-stat attribution interrupted: {bool(r.get("attributionLost"))}',
            '', 'OBSERVED SAVE-FLAG SPLITS (not official split timestamps)']
        for split in r.get('splits', []):
            lines.append(f'{duration(split.get("elapsedSeconds"))} | {clean(split.get("name"))} | {clean(split.get("source"))}')
        lines.extend(['', 'CONNECTION / PROCESS EVENTS'])
        lines.extend(f'{event.get("at")} | {clean(event.get("message"))}' for event in r.get('events', []))
        lines.extend(['', 'TIMING NOTES', self.SOURCE_NOTE,
            'This companion never pauses on Escape or removes crash/quit time itself. It sends no timer-control commands.',
            'Process disappearance does not distinguish a crash from a normal exit. Reviewers decide crash eligibility.',
            'Automatic starts/ends mirror LiveSplit. Saved flags and deaths arrive after a game save; no exact death frame is available.',
            'This report is supplementary analysis, not proof of a leaderboard-valid run.', ''])
        lines.insert(-1, 'Local audit flags describe this observation only; they do not establish cheating or an official disqualification.')
        return lines
