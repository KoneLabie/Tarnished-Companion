"""Local recording eligibility and auditable save observations, never certification.

The public PC rules were checked on 2026-10-22. Their fresh-save requirement
also applies to Defeat Consort; entering the DLC on a prepared save is not the
start of that category. This module cannot observe character creation, legal
gameplay, video evidence, or whether local files were edited. A candidate only
passes local capture gates. LiveSplit/SoulSplitter still owns the clock.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import time


RULES_CHECKED_AT = '2026-10-22'
GLOBAL_RULES_URL = 'https://www.speedrun.com/eldenring?h=all-remembrances-glitchless&rules=game&x=jdzzjjrd-r8rrz7r8.12vwdg4q'
FRESH_SECONDS = 30
START_SECONDS = 2
OBSERVATION_WINDOW_SECONDS = 30
LIMITATION = ('Local evidence only; character creation, gameplay, recording and rule compliance '
              'still require review. This is not anti-cheat or leaderboard verification.')
AUTOSTART_NOTE = ('SoulSplitter starts automatically when a new character\'s game clock first advances. '
                  'The companion observes LiveSplit; it does not start a stopwatch on character-menu clicks.')
MENU_NOTE = ('Menus, loading and game-process gaps follow SoulSplitter Game Time. Escape never pauses this companion clock; '
             'a flat external clock does not identify which menu or loading state is open.')

# Deliberately explicit presets, not a claim to contain every leaderboard category.
# Generic names such as "Any%" cannot establish a selected Glitchless subcategory.
CATEGORIES = (
    dict(id='any-percent-glitchless', name='Any% — Glitchless', scope='Base game',
         startNote='Fresh character; finish at the game credits. PC Game Time comes from SoulSplitter.',
         rulesUrl='https://www.speedrun.com/eldenring?h=Any-glitchless&rules=category&x=02qr00pk-7891zr5n.qj740p3q',
         official=True, requiresFresh=True,
         mainCategory='Any%',
         aliases=['Any% Glitchless', 'Any% - Glitchless', 'Any% — Glitchless']),
    dict(id='all-remembrances-no-dlc-glitchless', name='All Remembrances (No DLC) — Glitchless', scope='Base game',
         startNote='Fresh character; collect all base-game Remembrances, then reach the credits.',
         rulesUrl='https://www.speedrun.com/eldenring?h=All_Remembrances-glitchless&rules=category&x=824833gk-0nwp51r8.lr30pgml',
         official=True, requiresFresh=True,
         mainCategory='All Remembrances (No DLC)',
         aliases=['All Remembrances (No DLC) Glitchless', 'All Remembrances (No DLC) - Glitchless',
                  'All Remembrances (No DLC) — Glitchless']),
    dict(id='all-remembrances-glitchless', name='All Remembrances — Glitchless', scope='Base game + DLC',
         startNote='Fresh character; collect base-game and DLC Remembrances plus Heart of Bayle, then reach the credits.',
         rulesUrl='https://www.speedrun.com/eldenring?h=all-remembrances-glitchless&rules=category&x=jdzzjjrd-r8rrz7r8.12vwdg4q',
         official=True, requiresFresh=True,
         mainCategory='All Remembrances',
         aliases=['All Remembrances Glitchless', 'All Remembrances - Glitchless', 'All Remembrances — Glitchless']),
    dict(id='defeat-consort-glitchless', name='Defeat Consort — Glitchless', scope='DLC objective',
         startNote='Fresh character, not DLC entry. Finish in the main menu after collecting Circlet of Light and quitting out.',
         rulesUrl='https://www.speedrun.com/eldenring?h=defeat-consort-glitchless&page=2&rules=category&x=jdr4mmn2-38d90pel.lx58pm41',
         official=True, requiresFresh=True,
         mainCategory='Defeat Consort',
         aliases=['Defeat Consort Glitchless', 'Defeat Consort - Glitchless', 'Defeat Consort — Glitchless']),
    dict(id='custom', name='Custom — Local review required', scope='Local practice',
         startNote='Name the category in both apps. A witnessed fresh character is required for local capture.',
         rulesUrl=GLOBAL_RULES_URL, official=False, requiresFresh=True, aliases=[]),
)
_CATEGORIES = {c['id']: c for c in CATEGORIES}
_ID_ALIASES = {'all-remembrances': 'all-remembrances-glitchless', 'dlc': 'defeat-consort-glitchless'}
_CONTEXT = re.compile(r'^v2:([A-Za-z0-9_-]{1,128}):j([1-9][0-9]{0,4})$')


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _label(value):
    return ' '.join(str(value or '').casefold().split())


def _text(value, limit=120):
    return ' '.join(str(value or '').split())[:limit]


def _variables(sample):
    metadata = sample.get('categoryVariables')
    values = metadata.get('variables') if isinstance(metadata, dict) else None
    return values if isinstance(values, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in values.items()) else {}


def _timer_identity(sample):
    return (sample.get('attemptCount'), sample.get('gameName'), sample.get('categoryName'),
            tuple(sorted(_variables(sample).items())))


class RunPolicy:
    """Persist local history; call mark_started only after a record is created.

    observe accepts the active profile's seconds, deaths and journey plus saved
    boss IDs. observe_roster must first witness an empty slot becoming occupied
    while the game runs; a fresh-looking save on its own is insufficient. These
    witnesses exist only in this process and expire after 30 seconds. A consumed
    context remains consumed across restarts and timer resets.
    """

    def __init__(self, data_dir):
        self.path = Path(data_dir) / 'run-policy.json'
        self.selected_id = ''
        self.custom_name = ''
        self.records = {}
        self.context = None
        self.ready = False
        self._windows = {}
        self._rosters = {}
        self._births = {}
        self._approved = {}
        self._timer_last = None
        self._timer_start = None
        self._window_slots = {}
        self._storage_problem = ''
        self.capture_enabled = True
        self._read()

    def _read(self):
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or data.get('schemaVersion') != 1:
                raise ValueError('Unsupported policy history')
            selected = data.get('selectedId', '')
            if selected and selected not in _CATEGORIES:
                raise ValueError('Unknown category in policy history')
            records = data.get('records')
            if not isinstance(records, dict) or len(records) > 10000:
                raise ValueError('Invalid policy records')
            for context, record in records.items():
                if not isinstance(context, str) or not _CONTEXT.fullmatch(context) or not isinstance(record, dict):
                    raise ValueError('Invalid policy context')
                latest = record.get('latest')
                if not isinstance(latest, dict) or not all(_number(latest.get(k)) for k in ('seconds', 'deaths', 'journey')):
                    raise ValueError('Invalid policy observation')
                if not isinstance(latest.get('killed'), list) or any(type(k) is not int or k < 0 for k in latest['killed']):
                    raise ValueError('Invalid boss observation')
                if type(record.get('consumed')) is not bool or not isinstance(record.get('flags'), list):
                    raise ValueError('Invalid policy evidence')
                if record.get('startKind') not in ('fresh-candidate', 'existing-save'):
                    raise ValueError('Invalid creation evidence')
                for flag in record['flags']:
                    if not isinstance(flag, dict) or not all(isinstance(flag.get(k), str) for k in ('code', 'message')):
                        raise ValueError('Invalid integrity flag')
                record['creationWitness'] = record.get('creationWitness') is True
                record['recordingUnlocked'] = record.get('recordingUnlocked') is True
                if type(record.get('captureSuspended', False)) is not bool:
                    raise ValueError('Invalid capture history')
                if not isinstance(record.get('captureStoppedReason', ''), str) or len(record.get('captureStoppedReason', '')) > 512:
                    raise ValueError('Invalid capture reason')
                if record['recordingUnlocked'] and not (record['creationWitness'] and record['consumed']):
                    raise ValueError('Recording history is missing its creation evidence')
            self.selected_id = selected
            self.custom_name = _text(data.get('customName'))
            self.records = records
        except (OSError, ValueError, TypeError):
            self._storage_problem = 'Local run-policy history could not be read. Recording is blocked so previous evidence is not silently discarded.'

    def _write(self):
        if self._storage_problem:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(dict(schemaVersion=1, selectedId=self.selected_id,
                                                customName=self.custom_name, records=self.records),
                                            ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(self.path)
        except OSError:
            self._storage_problem = 'Local run-policy history could not be saved. Automatic recording is blocked until storage is available.'

    def select(self, category_id, custom_name=None):
        category_id = _ID_ALIASES.get(category_id, category_id)
        if category_id not in _CATEGORIES:
            raise ValueError('Choose a supported run category.')
        if category_id == 'custom' and not _text(custom_name):
            raise ValueError('Give the custom category a name matching LiveSplit.')
        self.selected_id = category_id
        self.custom_name = _text(custom_name) if category_id == 'custom' else ''
        self._approved.clear()
        self._write()
        return self.snapshot()

    def _flag(self, record, code, message, now):
        if not any(f['code'] == code for f in record['flags']):
            record['flags'].append(dict(code=code, message=message, observedAt=now))

    def set_capture_enabled(self, enabled, context=None, reason='Speedrun view was closed; this observation cannot resume.'):
        """Gate capture and revoke only an explicitly supplied active context."""
        if type(enabled) is not bool:
            raise ValueError('Capture enabled must be true or false.')
        self.capture_enabled = enabled
        if not enabled:
            self._windows.clear()
            self._rosters.clear()
            self._births.clear()
            self._approved.clear()
            self._window_slots.clear()
            self._timer_last = self._timer_start = None
            record = self.records.get(context) if isinstance(context, str) else None
            if record and record.get('recordingUnlocked'):
                record.update(recordingUnlocked=False, captureSuspended=True,
                              captureStoppedReason=_text(reason, 512))
                self._write()
        return self.capture_enabled

    def observe_roster(self, save_key, profiles, process_running=False, now=None):
        """Witness occupied-slot changes from consecutive current-process polls.

        save_key is progress_store.file_key(path), never the user's raw path.
        Feed even an empty valid roster and unchanged save polls. Disk snapshots
        from before launch and first observations cannot establish creation.
        """
        now = time.monotonic() if now is None else now
        if not self.capture_enabled:
            return []
        if not isinstance(save_key, str) or not save_key or len(save_key) > 128:
            return []
        if (process_running is not True or not isinstance(profiles, list)
                or any(not isinstance(p, dict) or type(p.get('slot')) is not int
                       or not 0 <= p['slot'] < 10 for p in profiles)):
            self._rosters.pop(save_key, None)
            for key in list(self._births):
                if key[0] == save_key:
                    del self._births[key]
            for context, key in list(self._window_slots.items()):
                if key[0] == save_key:
                    self._windows.pop(context, None)
                    self._approved.pop(context, None)
                    del self._window_slots[context]
            return []
        occupied = {p['slot'] for p in profiles}
        previous = self._rosters.get(save_key)
        created = []
        if previous and 0 <= now - previous['at'] <= OBSERVATION_WINDOW_SECONDS:
            created = sorted(occupied - previous['occupied'])
            for slot in created:
                self._births[(save_key, slot)] = now
        for key in list(self._births):
            if key[0] == save_key and (key[1] not in occupied or not 0 <= now - self._births[key] <= OBSERVATION_WINDOW_SECONDS):
                del self._births[key]
        self._rosters[save_key] = dict(occupied=occupied, at=now)
        return created

    def observe_timer(self, sample, now=None):
        """Remember an actual observed start while waiting for the next save poll.

        A fresh-looking save arriving four seconds later must not erase a timer
        start we already saw. Joining an already-running timer cannot invent an
        earlier start. The boundary is process-local, expires in 30 seconds, and
        is tied to the exact LiveSplit attempt/game/category metadata.
        """
        now = time.monotonic() if now is None else now
        if not self.capture_enabled:
            self._timer_last = self._timer_start = None
            return
        if (not isinstance(sample, dict) or sample.get('connected') is not True
                or sample.get('configured') is not True
                or type(sample.get('attemptCount')) is not int or sample['attemptCount'] < 0
                or not isinstance(sample.get('gameName'), str)
                or not isinstance(sample.get('categoryName'), str)
                or sample.get('phase') not in ('NotRunning', 'Running', 'Paused', 'Ended')):
            self._timer_last = self._timer_start = None
            self._approved.clear()
            return
        identity = _timer_identity(sample)
        phase, elapsed = sample['phase'], sample.get('gameTimeSeconds')
        previous = self._timer_last
        if (self._timer_start and (self._timer_start['identity'] != identity
                or not 0 <= now - self._timer_start['at'] <= OBSERVATION_WINDOW_SECONDS)):
            self._timer_start = None
        if phase in ('NotRunning', 'Ended'):
            self._timer_start = None
        elif phase == 'Running' and _number(elapsed):
            backward = (previous is not None and previous['identity'] == identity
                        and previous['phase'] in ('Running', 'Paused')
                        and _number(previous['elapsed']) and elapsed < previous['elapsed'])
            if backward:
                self._timer_start = None
            transition = (previous is not None and previous['phase'] == 'NotRunning'
                          and previous['identity'][1:] == identity[1:]
                          and 0 <= now - previous['at'] <= 5)
            first_early = (elapsed <= START_SECONDS and not backward
                           and (previous is None or previous['identity'] != identity
                                or previous['phase'] == 'NotRunning'))
            if not self._timer_start and elapsed <= OBSERVATION_WINDOW_SECONDS and (transition or first_early):
                self._timer_start = dict(identity=identity, elapsed=elapsed, at=now,
                                         kind='phase-transition' if transition else 'early-running-sample')
        self._timer_last = dict(identity=identity, phase=phase, elapsed=elapsed, at=now)

    def observe(self, context, stats, killed, ready, now=None, save_key=None):
        now = time.monotonic() if now is None else now
        match = _CONTEXT.fullmatch(context) if isinstance(context, str) else None
        self.context = context if match else None
        self.ready = bool(self.capture_enabled and ready and match and isinstance(stats, dict))
        if not self.ready:
            return self.snapshot()
        if (not all(_number(stats.get(k)) for k in ('seconds', 'deaths', 'journey'))
                or type(stats.get('journey')) is not int or type(stats.get('deaths')) is not int
                or (save_key is not None and (type(stats.get('slot')) is not int or not 0 <= stats['slot'] < 10))
                or stats['journey'] != int(match[2])
                or not isinstance(killed, (list, tuple, set))
                or any(type(k) is not int or k < 0 for k in killed)):
            self.ready = False
            return self.snapshot()
        latest = dict(seconds=stats['seconds'], deaths=stats['deaths'], journey=stats['journey'], killed=sorted(set(killed)))
        record = self.records.get(context)
        changed = record is None or record['latest'] != latest
        if record is None:
            identity, journey = match[1], int(match[2])
            previous = [(int(m[2]), r) for key, r in self.records.items()
                        if (m := _CONTEXT.fullmatch(key)) and m[1] == identity]
            last_journey, prior = max(previous, default=(0, None), key=lambda item: item[0])
            birth = self._births.get((save_key, stats.get('slot')))
            witnessed = birth is not None and 0 <= now - birth <= OBSERVATION_WINDOW_SECONDS
            fresh = witnessed and journey == 1 and latest['seconds'] <= FRESH_SECONDS and latest['deaths'] == 0 and not latest['killed']
            record = dict(latest=latest, first=deepcopy(latest), consumed=False, flags=[],
                          creationWitness=bool(fresh), recordingUnlocked=False, captureSuspended=False, captureStoppedReason='',
                          startKind='fresh-candidate' if fresh else 'existing-save')
            self.records[context] = record
            if fresh:
                self._windows[context] = birth
                self._window_slots[context] = (save_key, stats['slot'])
                del self._births[(save_key, stats['slot'])]
            if prior is not None and journey <= last_journey:
                self._flag(record, 'journey-moved-backward', 'A previously observed character returned to an earlier journey.', time.time())
        else:
            old = record['latest']
            if latest['seconds'] < old['seconds']:
                self._flag(record, 'playtime-moved-backward', 'Saved character playtime moved backward; a restore or replacement needs review.', time.time())
            if latest['deaths'] < old['deaths']:
                self._flag(record, 'deaths-moved-backward', 'Saved death count moved backward within this character and journey.', time.time())
            if set(old['killed']) - set(latest['killed']):
                self._flag(record, 'boss-progress-moved-backward', 'Previously observed defeated boss flags disappeared within this journey.', time.time())
            record['latest'] = latest
        if changed:
            self._write()
        return self.snapshot()

    def mark_started(self, context):
        record = self.records.get(context)
        approval = self._approved.get(context, {})
        if (not self.capture_enabled or not record or not record.get('creationWitness') or record['flags'] or record['consumed']
                or approval.get('category') != self.selected_id
                or approval.get('latest') != record['latest']
                or not 0 <= time.monotonic() - approval.get('at', -math.inf) <= START_SECONDS):
            return False
        record['consumed'] = True
        record['recordingUnlocked'] = True
        self._windows.pop(context, None)
        self._window_slots.pop(context, None)
        self._approved.pop(context, None)
        self._write()
        return not self._storage_problem

    def can_record(self, context):
        record = self.records.get(context, {})
        return bool(self.capture_enabled and not self._storage_problem and record.get('recordingUnlocked')
                    and not record.get('captureSuspended')
                    and record.get('creationWitness') and record.get('consumed') and not record.get('flags'))

    def can_export(self, context):
        """Historical observations survive view changes; integrity flags still block."""
        record = self.records.get(context, {})
        return bool(not self._storage_problem and record.get('creationWitness')
                    and record.get('consumed') and not record.get('flags'))

    def audit_for_start(self, context, timer_sample=None, now=None):
        now = time.monotonic() if now is None else now
        category = _CATEGORIES.get(self.selected_id)
        name = self.custom_name if self.selected_id == 'custom' else category['name'] if category else ''
        result = dict(eligible=False, status='blocked', reason='', categoryId=self.selected_id,
                      categoryName=name, rulesUrl=category['rulesUrl'] if category else GLOBAL_RULES_URL,
                      startEvidence=[])

        def stop(reason, status='blocked'):
            if timer_sample is not None:
                self._approved.pop(context, None)
            result.update(reason=reason, status=status)
            return result

        if not self.capture_enabled:
            return stop('Open Speedrun view before creating the new character. Timing capture is currently off.')
        if self._storage_problem:
            return stop(self._storage_problem)
        if not category:
            return stop('Choose a run category before creating a new character.', 'review-required')
        if context != self.context or not self.ready or context not in self.records:
            return stop('Waiting for a readable active character save.', 'review-required')
        record = self.records[context]
        latest = record['latest']
        if record['flags']:
            return stop(record['flags'][0]['message'])
        if record['consumed']:
            return stop('This character and journey already started a recorded run. A timer reset cannot create a fresh run on it.')
        if category['requiresFresh'] and latest['journey'] != 1:
            return stop('Recording requires a new character. Starting another journey / NG+ does not unlock recording.')
        if record['startKind'] == 'existing-save':
            return stop('Create a new character while the tracker and game are running. An existing save, prepared DLC save, or new journey does not unlock recording.')
        if record['startKind'] == 'fresh-candidate' and (latest['seconds'] > FRESH_SECONDS or latest['deaths'] != 0 or latest['killed']):
            return stop('The fresh-character capture window has passed or progress already exists. Begin with another fresh character.')
        opened = self._windows.get(context)
        if opened is None or not 0 <= now - opened <= OBSERVATION_WINDOW_SECONDS:
            return stop('The start was not observed in the current capture window. Existing or resumed runs need review.', 'review-required')
        result['startEvidence'] = [
            'Observed an absent save slot become occupied while the game and tracker were running, within 30 seconds of consecutive roster observations.',
            'Journey 1 save: at most 30 saved seconds, zero saved deaths and no defeated boss flags.',
            LIMITATION,
        ]
        if not isinstance(timer_sample, dict):
            return stop('Candidate start observed; waiting for the matching LiveSplit category to start automatically.', 'candidate')
        if timer_sample.get('connected') is not True or timer_sample.get('configured') is not True:
            return stop('Connect configured LiveSplit / SoulSplitter with Game Time before the start.', 'review-required')
        if timer_sample.get('phase') != 'Running':
            return stop('Waiting for LiveSplit / SoulSplitter to start the selected category.', 'candidate')
        elapsed = timer_sample.get('gameTimeSeconds')
        if not _number(elapsed):
            return stop('LiveSplit Game Time is unavailable; waiting for an observable start.', 'review-required')
        boundary = self._timer_start
        identity = _timer_identity(timer_sample)
        cached_start = (boundary is not None and boundary['identity'] == identity
                        and 0 <= now - boundary['at'] <= OBSERVATION_WINDOW_SECONDS
                        and boundary['elapsed'] <= elapsed <= OBSERVATION_WINDOW_SECONDS)
        late_binding = elapsed > START_SECONDS
        if late_binding and not cached_start:
            return stop('LiveSplit was already running without an observed start boundary; this partial start needs review and cannot unlock recording.', 'review-required')
        aliases = [self.custom_name] if self.selected_id == 'custom' else category['aliases']
        full_name_match = _label(timer_sample.get('categoryName')) in {_label(a) for a in aliases}
        variable_match = (bool(category.get('mainCategory'))
                          and _label(timer_sample.get('categoryName')) == _label(category['mainCategory'])
                          and 'glitchless' in {_label(v) for v in _variables(timer_sample).values()})
        if not (full_name_match or variable_match):
            return stop('The LiveSplit category name does not match the selected category and subcategory.', 'review-required')
        if variable_match:
            result['startEvidence'].append('LiveSplit declares the selected main category and an exact Glitchless category variable; these settings are user-controlled, not proof of compliance.')
        if cached_start:
            result['startEvidence'].append(f'LiveSplit start first observed at {boundary["elapsed"]:.3f}s Game Time; fresh character linked {now - boundary["at"]:.3f}s later to the same attempt and category.')
        else:
            result['startEvidence'].append('Configured LiveSplit was observed running within its first two seconds of Game Time with a matching category name.')
        if late_binding:
            result['startEvidence'].append('Character attribution arrived after the first two seconds; this is a partial local observation requiring review.')
        result.update(eligible=True, status='candidate' if category['official'] and not late_binding else 'review-required',
                      reason=('Observed timer start linked to the new character after a save polling delay; partial observation requires review. '
                              if late_binding else 'Local start evidence captured. ')
                             + (LIMITATION if category['official'] else 'Local practice only; custom rules have not been verified.'))
        self._approved[context] = dict(category=self.selected_id, latest=deepcopy(record['latest']), at=now)
        return result

    def snapshot(self):
        category = _CATEGORIES.get(self.selected_id)
        audit = self.audit_for_start(self.context)
        record = self.records.get(self.context, {})
        unlocked = self.can_record(self.context)
        if unlocked:
            audit.update(status='recording-unlocked', reason='Recording unlocked for this witnessed character. New runs require another new character.')
        return dict(categories=deepcopy(list(CATEGORIES)), selectedId=self.selected_id,
                    name=self.custom_name if self.selected_id == 'custom' else category['name'] if category else '',
                    needsSelection=not bool(category), notice=audit['reason'], context=self.context,
                    status=audit['status'], flags=deepcopy(record.get('flags', [])),
                    recordingUnlocked=unlocked,
                    captureEnabled=self.capture_enabled, exportUnlocked=self.can_export(self.context),
                    autoStartNote=AUTOSTART_NOTE, menuTimingNote=MENU_NOTE,
                    rulesCheckedAt=RULES_CHECKED_AT, globalRulesUrl=GLOBAL_RULES_URL,
                    limitation=LIMITATION, sourceVerified=False)
