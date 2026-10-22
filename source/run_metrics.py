"""Read-only, explicitly bounded combat estimates and local speedrun timing.

Combat samples measure visible boss HP loss, not player-attributed damage. Run
splits are observed save flags, not exact frame timings or official category IGT.
"""
from collections import deque
import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time


def _number(value):
    return type(value) in (int, float) and -1e15 < value < 1e15 and math.isfinite(value)


def _clock(value):
    result = time.monotonic() if value is None else value
    if not _number(result) or result < 0:
        raise ValueError('Invalid monotonic time.')
    return float(result)


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class CombatMetrics:
    """Estimate damage using one stable health-bar identity at a time."""
    WINDOW = 5.0
    MAX_GAP = 2.0
    NOTE = ('Estimated boss HP loss; includes summons, allies and status damage. '
            'Largest drop is one sample, not one hit. Resets after a gap or phase change.')

    def __init__(self):
        self.reset()

    def reset(self):
        self.identity = None
        self.started = self.last_at = None
        self.last_hp = self.max_hp = None
        self.name = None
        self.damage = self.largest = 0
        self.events = deque()

    def update(self, context, bars, available, now=None):
        now = _clock(now)
        bar = bars[0] if isinstance(bars, list) and bars else None
        if (not available or not isinstance(context, str) or not context or context == 'pending'
                or not isinstance(bar, dict)):
            self.reset()
            return
        hp, maximum, name, handle = (bar.get(k) for k in ('hp', 'maxHp', 'name', 'handle'))
        if (not _number(hp) or not _number(maximum) or not 0 <= hp <= maximum <= 100000000
                or maximum <= 0 or not isinstance(name, str) or not name.strip()
                or not isinstance(handle, (str, int)) or isinstance(handle, bool)):
            self.reset()
            return
        identity = (context, str(handle), name, maximum)
        # Full-health recovery can signal a new attempt, even when HUD handles are reused.
        restored = (self.last_hp is not None and hp >= maximum * .99
                    and self.last_hp < maximum * .9)
        if (identity != self.identity or self.last_at is None or now < self.last_at
                or now - self.last_at > self.MAX_GAP or restored):
            self.reset()
            self.identity, self.started = identity, now
            self.name, self.max_hp = name[:256], maximum
        elif self.last_hp is not None and now > self.last_at:
            drop = max(0, self.last_hp - hp)
            if drop:
                self.damage += drop
                self.largest = max(self.largest, drop)
                self.events.append((now, drop))
        # Healing becomes a new baseline without being counted as damage.
        self.last_hp, self.last_at = hp, now
        while self.events and self.events[0][0] <= now - self.WINDOW:
            self.events.popleft()

    def snapshot(self, now=None):
        now = _clock(now)
        empty = dict(status='waiting', rollingDps=None, averageDps=None,
                     observedDamage=None, largestDrop=None, observedSeconds=None,
                     hpPercent=None, bossName=None, note=self.NOTE)
        if self.last_at is None or now < self.last_at or now - self.last_at > self.MAX_GAP:
            return empty
        elapsed = max(0, now - self.started)
        window = min(self.WINDOW, elapsed)
        rolling = sum(drop for stamp, drop in self.events if stamp > now - self.WINDOW)
        return dict(status='tracking', rollingDps=rolling / window if window else None,
                    averageDps=self.damage / elapsed if elapsed else None,
                    observedDamage=self.damage, largestDrop=self.largest,
                    observedSeconds=elapsed, hpPercent=self.last_hp / self.max_hp * 100,
                    bossName=self.name, note=self.NOTE)


class SpeedrunMetrics:
    """One local run, scoped to a character generation and journey.

Active elapsed time excludes explicit pauses. The saved IGT delta spans the
character's saved clock since Start, including any gameplay during those pauses.
"""
    STATUSES = {'idle', 'running', 'paused', 'finished', 'interrupted'}
    BASE_NOTICE = ('Elapsed time excludes manual pauses. Saved IGT updates only when the '
                   'game saves. Boss splits are observed save flags and may arrive late.')

    def __init__(self, data_dir):
        self.path = Path(data_dir) / 'run-state.json'
        self.data = self._empty()
        self.running_since = None
        self.last_checkpoint = None
        self.save_unavailable = False
        self.storage_error = False
        self._load()

    @staticmethod
    def _empty():
        return dict(schemaVersion=1, status='idle', contextKey=None, character=None,
                    journey=None, startedAt=None, endedAt=None, elapsedSeconds=0.0,
                    igtSeconds=None, deaths=None, bossesDefeated=0, splits=[],
                    baseSeconds=None, baseDeaths=None, lastSeconds=None, lastDeaths=None,
                    seenKilled=[], notice=SpeedrunMetrics.BASE_NOTICE)

    def _load(self):
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(raw, dict) or raw.get('schemaVersion') != 1:
                return
            if raw.get('status') not in self.STATUSES:
                return
            if raw['status'] == 'idle':
                return
            if (not isinstance(raw.get('contextKey'), str) or not raw['contextKey']
                    or not isinstance(raw.get('character'), str)
                    or type(raw.get('journey')) is not int or raw['journey'] < 1):
                return
            for field in ('elapsedSeconds', 'igtSeconds', 'deaths', 'baseSeconds',
                          'baseDeaths', 'lastSeconds', 'lastDeaths'):
                if not _number(raw.get(field)) or raw[field] < 0:
                    return
            if not isinstance(raw.get('seenKilled'), list) or any(type(i) is not int for i in raw['seenKilled']):
                return
            if not isinstance(raw.get('splits'), list) or len(raw['splits']) > 10000:
                return
            for split in raw['splits']:
                if (not isinstance(split, dict) or type(split.get('bossId')) is not int
                        or not isinstance(split.get('name'), str)
                        or not isinstance(split.get('source'), str)
                        or not _number(split.get('elapsedSeconds')) or split['elapsedSeconds'] < 0
                        or not _number(split.get('igtSeconds')) or split['igtSeconds'] < 0):
                    return
            if any(raw.get(key) is not None and not isinstance(raw[key], str)
                   for key in ('startedAt', 'endedAt', 'notice')):
                return
            self.data = {key: copy.deepcopy(raw.get(key, default)) for key, default in self._empty().items()}
            self.data['bossesDefeated'] = len(self.data['splits'])
            if self.data['status'] == 'running':
                self.data['status'] = 'interrupted'
                self.data['notice'] = ('App restarted. Timing stopped at the last saved checkpoint '
                                       '(up to 5 seconds earlier); offline time was not added. Resume or reset.')
        except (OSError, ValueError, TypeError):
            pass

    def _elapsed(self, now):
        extra = max(0, now - self.running_since) if self.running_since is not None else 0
        return self.data['elapsedSeconds'] + extra

    def _persist(self, now):
        stored = copy.deepcopy(self.data)
        stored['elapsedSeconds'] = self._elapsed(now)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(stored, indent=2, ensure_ascii=False), encoding='utf-8')
            temporary.replace(self.path)
            self.storage_error = False
        except OSError:
            # Keep timing and save tracking alive if a disk/permission issue occurs.
            # Retry on the next checkpoint; the visible warning prevents implying durability.
            self.storage_error = True
        self.last_checkpoint = now

    @staticmethod
    def _profile(context, stats, killed):
        if (not isinstance(context, str) or not context or context == 'pending'
                or not isinstance(stats, dict) or not isinstance(stats.get('name'), str)
                or type(stats.get('journey')) is not int or stats['journey'] < 1):
            raise ValueError('Connect a valid character save before timing a run.')
        if any(not _number(stats.get(key)) or stats[key] < 0 for key in ('seconds', 'deaths')):
            raise ValueError('Saved playtime and deaths are required to start or resume a run.')
        if not isinstance(killed, (set, list, tuple)) or any(type(i) is not int for i in killed):
            raise ValueError('Valid saved boss progress is required.')
        return set(killed)

    def _freeze(self, status, now, notice=None):
        self.data['elapsedSeconds'] = self._elapsed(now)
        self.running_since = None
        self.data['status'] = status
        if status == 'finished':
            self.data['endedAt'] = _utc()
        if notice:
            self.data['notice'] = notice

    def observe(self, context, stats, killed, boss_names, ready, now=None):
        now = _clock(now)
        if self.data['status'] not in ('running', 'paused'):
            return
        self.save_unavailable = not ready
        if not ready:
            if self.data['status'] == 'running' and (self.last_checkpoint is None or now - self.last_checkpoint >= 5):
                self._persist(now)
            return
        try:
            fresh = self._profile(context, stats, killed)
        except ValueError:
            self.save_unavailable = True
            return
        if context != self.data['contextKey']:
            self._freeze('interrupted', now, 'Character or journey changed. This run was stopped; export it or reset for the new character.')
            self._persist(now)
            return
        seen = set(self.data['seenKilled'])
        if stats['seconds'] < self.data['lastSeconds'] or stats['deaths'] < self.data['lastDeaths'] or seen - fresh:
            self._freeze('interrupted', now, 'Saved progress moved backwards. This run stopped to avoid mixing restored progress; export or reset.')
            self._persist(now)
            return
        elapsed = self._elapsed(now)
        igt = stats['seconds'] - self.data['baseSeconds']
        changes = (stats['seconds'] != self.data['lastSeconds'] or stats['deaths'] != self.data['lastDeaths'] or fresh != seen)
        newly = sorted(fresh - seen)
        for bid in newly:
            name = boss_names.get(bid, boss_names.get(str(bid), f'Boss {bid}')) if isinstance(boss_names, dict) else f'Boss {bid}'
            if isinstance(name, dict):
                name = name.get('name', f'Boss {bid}')
            source = 'save flag' if self.data['status'] == 'running' else 'save flag (timer paused)'
            if len(newly) > 1:
                source += ' (same save batch; order unknown)'
            self.data['splits'].append(dict(bossId=bid, name=str(name)[:256], elapsedSeconds=elapsed,
                                            igtSeconds=igt, source=source))
        self.data.update(lastSeconds=stats['seconds'], lastDeaths=stats['deaths'],
                         igtSeconds=igt, deaths=stats['deaths'] - self.data['baseDeaths'],
                         seenKilled=sorted(fresh), bossesDefeated=len(self.data['splits']))
        if changes or self.last_checkpoint is None or now - self.last_checkpoint >= 5:
            self._persist(now)

    def action(self, op, context=None, stats=None, killed=None, boss_names=None, now=None):
        now = _clock(now)
        status = self.data['status']
        if op == 'reset':
            if status == 'running':
                raise ValueError('Pause or finish the active run before resetting it.')
            self.data = self._empty()
            self.running_since = None
            self.save_unavailable = False
        elif op == 'start':
            if status != 'idle':
                raise ValueError('Reset the existing run before starting another.')
            fresh = self._profile(context, stats, killed)
            self.data = self._empty()
            self.data.update(status='running', contextKey=context, character=stats['name'][:256],
                             journey=stats['journey'], startedAt=_utc(), baseSeconds=stats['seconds'],
                             baseDeaths=stats['deaths'], lastSeconds=stats['seconds'], lastDeaths=stats['deaths'],
                             seenKilled=sorted(fresh), igtSeconds=0, deaths=0)
            self.running_since = now
            self.save_unavailable = False
        elif op == 'pause':
            if status != 'running':
                raise ValueError('Only a running timer can be paused.')
            self._freeze('paused', now)
        elif op == 'resume':
            if status not in ('paused', 'interrupted'):
                raise ValueError('Only a paused or interrupted timer can be resumed.')
            self._profile(context, stats, killed)
            if context != self.data['contextKey']:
                raise ValueError('Return to the original character and journey, or reset for a new run.')
            if stats['seconds'] < self.data['lastSeconds'] or stats['deaths'] < self.data['lastDeaths'] or set(self.data['seenKilled']) - set(killed):
                raise ValueError('Saved progress moved backwards. Reset before starting a new run.')
            # Record progress while stopped at the frozen elapsed time, not as a timed segment.
            self.data['status'] = 'paused'
            self.observe(context, stats, killed, boss_names or {}, True, now)
            self.data['status'] = 'running'
            self.data['notice'] = self.BASE_NOTICE
            self.running_since = now
            self.save_unavailable = False
        elif op == 'finish':
            if status not in ('running', 'paused', 'interrupted'):
                raise ValueError('Start a run before finishing it.')
            self._freeze('finished', now)
        else:
            raise ValueError('Unknown speedrun action.')
        self._persist(now)

    def snapshot(self, now=None):
        now = _clock(now)
        keys = ('status', 'contextKey', 'character', 'journey', 'startedAt', 'endedAt',
                'igtSeconds', 'deaths', 'bossesDefeated', 'splits', 'notice')
        result = {key: copy.deepcopy(self.data[key]) for key in keys}
        result['elapsedSeconds'] = self._elapsed(now)
        if self.save_unavailable and self.data['status'] in ('running', 'paused'):
            result['notice'] = 'Save updates unavailable. Elapsed timing continues unless paused; saved IGT and splits are waiting for valid data.'
        if self.storage_error:
            result['notice'] += ' Run changes could not be saved to disk. Keep the app open and export a copy; checkpoint saving will retry.'
        return result

    @staticmethod
    def _format(seconds):
        if seconds is None:
            return 'Unavailable'
        milliseconds = round(max(0, seconds) * 1000)
        seconds, ms = divmod(milliseconds, 1000)
        minutes, sec = divmod(seconds, 60)
        hours, minute = divmod(minutes, 60)
        return f'{hours:02}:{minute:02}:{sec:02}.{ms:03}'

    def export_text(self, now=None):
        state = self.snapshot(now)
        if state['status'] == 'idle':
            raise ValueError('Start a run before exporting times.')
        # Strip line-control characters from save-derived names in a plain text report.
        clean = lambda value: ' '.join(str(value).split())
        lines = ['TARNISHED LINEUP — SPEEDRUN RECORD', '',
                 f'Exported (UTC): {_utc()}', f'Character: {clean(state["character"])}',
                 f'Journey: {state["journey"]}', f'Status: {state["status"]}',
                 f'Started (UTC): {state["startedAt"]}', f'Finished (UTC): {state["endedAt"] or "Not finished"}',
                 f'Active elapsed time: {self._format(state["elapsedSeconds"])}',
                 f'Saved character IGT delta: {self._format(state["igtSeconds"])}',
                 f'Deaths since Start: {state["deaths"]}',
                 f'Bosses newly defeated: {state["bossesDefeated"]}', '',
                 'BOSS SPLITS', 'Elapsed | Saved IGT | Boss | Observation']
        for split in state['splits']:
            lines.append(f'{self._format(split["elapsedSeconds"])} | {self._format(split["igtSeconds"])} | '
                         f'{clean(split["name"])} | {clean(split["source"])}')
        if not state['splits']:
            lines.append('No new boss defeat flags observed during this run.')
        lines.extend(['', 'TIMING NOTES',
                      '- Active elapsed time uses a monotonic clock and excludes manual pauses.',
                      '- Saved IGT is the selected character save-clock delta, including gameplay during manual pauses.',
                      '- Saved IGT is not a live or official category/load-removal timer.',
                      '- Automatic splits are detected from save flags, usually checked every 4 seconds, plus game save delay.',
                      '- Multiple bosses in one saved update share an observation time; their actual defeat order is unknown.',
                      '- Existing defeated bosses at Start are excluded. Character/journey changes interrupt the run.',
                      '- Restarted timers recover a checkpoint (up to 5 seconds old); offline time is excluded.',
                      f'- Current note: {clean(state["notice"])}', ''])
        return '\n'.join(lines)
