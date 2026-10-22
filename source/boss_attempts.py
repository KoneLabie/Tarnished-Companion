"""Observed boss attempts from read-only HUD bars and saved result counters.

These are local performance estimates, not a leaderboard timer. A vanished HUD
is never a victory or death by itself; only saved flags/counters confirm those.
"""
import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import secrets
import time


def _number(value):
    return type(value) in (int, float) and 0 <= value < 1e12 and math.isfinite(value)


def _clock(value):
    value = time.monotonic() if value is None else value
    if not _number(value):
        raise ValueError('Invalid observation time.')
    return float(value)


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def _clean(value):
    return ' '.join(str(value).split())


class BossAttempts:
    """Attempt records are scoped to an exact character generation and journey.

    Personal benchmarks compare exact catalog encounters at the same journey
    number across local characters/runs. Unresolved arena names are not merged.
    """
    SCALE_SECONDS = 900
    HUD_GRACE = 5.0
    RECONCILE_WINDOW = 30.0
    MAX_SAMPLE_GAP = 3.0
    OUTCOMES = {'victory', 'death', 'unconfirmed', 'interrupted'}

    def __init__(self, data_dir, recover_interrupted=True):
        self.path = Path(data_dir) / 'boss-attempts.json'
        self.contexts = {}
        self.context = None
        self.category_key = None
        self.active = None
        self.last_deaths = None
        self.last_killed = None
        self.last_observed = None
        self.last_checkpoint = None
        self.pending = []
        self.blocked = None
        self.seen_clear = False
        self.storage_error = False
        self.notice = ''
        self.recover_interrupted = recover_interrupted
        self._load()

    def _load(self):
        try:
            if self.path.stat().st_size > 16 * 1024 * 1024:
                self.notice = 'Attempt history is too large to load safely; the original file is preserved.'
                self.storage_error = True
                self.load_failed = True
                return
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(raw, dict) or raw.get('schemaVersion') != 1 or not isinstance(raw.get('contexts'), dict):
                raise ValueError('Unrecognized attempt history format.')
            clean = {}
            for key, context in raw['contexts'].items():
                if (not isinstance(key, str) or not key or not isinstance(context, dict)
                        or not isinstance(context.get('character'), str)
                        or type(context.get('journey')) is not int or context['journey'] < 1
                        or not isinstance(context.get('records'), list)):
                    raise ValueError('Invalid attempt history context.')
                records = []
                for record in context['records']:
                    records.append(self._validated_record(record))
                clean[key] = dict(character=context['character'][:256], journey=context['journey'], records=records)
            saved_active = raw.get('active')
            if saved_active is not None:
                record = self._validated_record(saved_active, allow_active=True)
                key = record['contextKey']
                if key not in clean:
                    raise ValueError('Interrupted attempt has no character context.')
                record.update(outcome='interrupted', status='interrupted', endedAt=_utc(),
                              note='App stopped during this attempt. Duration is the last checkpoint; offline time is excluded.',
                              eligibleForBenchmark=False)
                clean[key]['records'].append(record)
            self.contexts = clean
            if saved_active is not None and self.recover_interrupted:
                # Persist the recovered interruption once; the old in-progress
                # checkpoint must not remain the only durable representation.
                self._persist(time.monotonic())
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, OverflowError):
            # Preserve incompatible histories instead of overwriting them later.
            self.notice = 'Attempt history could not be loaded; the original file is preserved. New attempts remain in memory.'
            self.storage_error = True
            self.load_failed = True

    @classmethod
    def _validated_record(cls, record, allow_active=False):
        if (not isinstance(record, dict) or not isinstance(record.get('recordId'), str)
                or not isinstance(record.get('contextKey'), str) or not isinstance(record.get('name'), str)
                or not isinstance(record.get('startedAt'), str) or not _number(record.get('elapsedSeconds'))
                or record.get('bossId') is not None and type(record.get('bossId')) is not int
                or record.get('attemptNumber') is not None and (type(record.get('attemptNumber')) is not int or record['attemptNumber'] < 1)
                or record.get('outcome') not in cls.OUTCOMES | ({'in-progress'} if allow_active else set())
                or not isinstance(record.get('phases'), list) or any(not isinstance(p, str) for p in record['phases'])
                or record.get('endedAt') is not None and not isinstance(record.get('endedAt'), str)):
            raise ValueError('Invalid attempt history record.')
        output = {key: copy.deepcopy(record.get(key)) for key in
                  ('recordId', 'contextKey', 'bossId', 'name', 'attemptNumber', 'startedAt', 'endedAt',
                   'elapsedSeconds', 'outcome', 'phases')}
        output['status'] = output['outcome']
        output['zeroHpObserved'] = record.get('zeroHpObserved') is True
        output['eligibleForBenchmark'] = (record.get('eligibleForBenchmark') is True and output['outcome'] == 'victory'
                                          and output['zeroHpObserved'])
        output['partialStart'] = record.get('partialStart') is True
        output['note'] = str(record.get('note') or '')[:1000]
        output['categoryId'] = record.get('categoryId') if isinstance(record.get('categoryId'), str) else None
        return output

    def _public_active(self, now):
        if not self.active:
            return None
        active = self.active
        # Awaiting a save result never adds speculative time after the bar vanished.
        end = active['lastSeen'] if active['missingSince'] is not None else now
        return dict(recordId=active['recordId'], contextKey=active['contextKey'], bossId=active['bossId'],
                    categoryId=active['categoryId'],
                    name=active['name'], attemptNumber=active['attemptNumber'], startedAt=active['startedAt'],
                    endedAt=None, elapsedSeconds=max(0.0, end-active['start']), outcome='in-progress',
                    status='awaiting-result' if active['missingSince'] is not None else 'fighting',
                    phases=active['phases'][:], partialStart=active['partialStart'],
                    zeroHpObserved=active['zeroAt'] is not None,
                    eligibleForBenchmark=False,
                    note=active.get('partialReason', '') if active['partialStart'] else '')

    def _persist(self, now):
        if getattr(self, 'load_failed', False):
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(dict(schemaVersion=1, contexts=self.contexts,
                                                 active=self._public_active(now)), ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(self.path)
            self.storage_error = False
        except OSError:
            self.storage_error = True
        self.last_checkpoint = now

    @staticmethod
    def _profile(context, stats, killed):
        if (not isinstance(context, str) or not context or context == 'pending'
                or not isinstance(stats, dict) or not isinstance(stats.get('name'), str)
                or type(stats.get('journey')) is not int or stats['journey'] < 1
                or not _number(stats.get('deaths'))
                or not isinstance(killed, (set, list, tuple)) or any(type(i) is not int for i in killed)):
            return None
        return set(killed)

    @staticmethod
    def _bars(bars, resolver):
        valid = []
        for bar in bars if isinstance(bars, list) else []:
            if not isinstance(bar, dict):
                continue
            hp, maximum, name, handle = (bar.get(k) for k in ('hp', 'maxHp', 'name', 'handle'))
            if (not _number(hp) or not _number(maximum) or not 0 <= hp <= maximum <= 100000000
                    or maximum <= 0 or not isinstance(name, str) or not name.strip()
                    or not isinstance(handle, (str, int)) or isinstance(handle, bool)):
                continue
            try:
                bid = resolver(name) if callable(resolver) else None
            except (KeyError, ValueError, TypeError):
                bid = None
            valid.append(dict(name=name[:256], handle=str(handle), hp=hp, maxHp=maximum,
                              bossId=bid if type(bid) is int else None))
        return valid

    @staticmethod
    def _same(active, bar):
        if active['bossId'] is not None:
            return active['bossId'] == bar['bossId']
        return bar['bossId'] is None and active['lastName'] == bar['name'] and active['lastHandle'] == bar['handle']

    def _finish(self, outcome, now, note='', duration_end=None):
        if not self.active:
            return None
        active = self.active
        record = self._public_active(now)
        end = duration_end if duration_end is not None else now
        record.update(elapsedSeconds=max(0.0, end-active['start']), endedAt=_utc(), outcome=outcome,
                      status=outcome, note=note,
                      eligibleForBenchmark=outcome == 'victory' and not active['partialStart']
                      and active['bossId'] is not None and active['zeroAt'] is not None)
        if active['partialStart']:
            record['note'] += ' Partial start; excluded from personal timing benchmarks.'
        self.contexts[active['contextKey']]['records'].append(record)
        if outcome == 'unconfirmed':
            self.pending.append((record, now, active['deathBase']))
        self.blocked = dict(context=active['contextKey'], bossId=active['bossId'], name=active['lastName'],
                            handle=active['lastHandle'], hp=active['lastHp'], maxHp=active['lastMax'])
        self.active = None
        self._persist(now)
        return record

    def interrupt(self, reason='Tracking stopped; attempt outcome is unknown.', now=None):
        now = _clock(now)
        if self.active:
            self._finish('interrupted', now, reason, self.active['lastSeen'])

    def _reconcile(self, fresh, new_kills, death_delta, deaths, now):
        remaining = []
        death_consumed = False
        self.ambiguous_result = False
        for record, ended, death_base in reversed(self.pending):
            if now-ended > self.RECONCILE_WINDOW or record['contextKey'] != self.context:
                continue
            if record['outcome'] != 'unconfirmed':
                continue
            # A late save spanning two attempts cannot identify which attempt
            # died/won. Preserve both as uncertain instead of assigning a PB.
            overlapping = self.active is not None and self.active['contextKey'] == record['contextKey']
            if overlapping and (death_delta > 0 or record['bossId'] is not None
                                and record['bossId'] == self.active['bossId'] and record['bossId'] in new_kills):
                self.ambiguous_result = True
                record['note'] = 'A saved result arrived after another attempt began; attribution is unconfirmed.'
                continue
            if record['bossId'] is not None and record['bossId'] in new_kills:
                record.update(outcome='victory', status='victory',
                              eligibleForBenchmark=not record['partialStart'] and record.get('zeroHpObserved') is True,
                              note='Victory confirmed by a later saved boss flag. Duration ends at the last observed boss bar.')
                new_kills.discard(record['bossId'])
                self._persist(now)
            elif death_delta > 0 and not death_consumed and deaths > death_base:
                record.update(outcome='death', status='death', eligibleForBenchmark=False,
                              note='Player death confirmed by a later saved death counter. Duration ends at the last observed boss bar.')
                death_consumed = True
                self._persist(now)
            else:
                remaining.append((record, ended, death_base))
        self.pending = list(reversed(remaining))
        return 0 if death_consumed else death_delta

    def _start(self, bar, stats, fresh, names, now):
        records = self.contexts[self.context]['records']
        bid = bar['bossId']
        number = 1+sum(r['bossId'] == bid and r.get('categoryId') == self.category_key for r in records) if bid is not None else None
        name = names.get(bid, names.get(str(bid), bar['name'])) if isinstance(names, dict) else bar['name']
        self.active = dict(recordId=secrets.token_hex(8), contextKey=self.context, bossId=bid, name=str(name)[:256],
                           categoryId=self.category_key,
                           attemptNumber=number, startedAt=_utc(), start=now, lastSeen=now, missingSince=None,
                           zeroAt=None, lastName=bar['name'], lastHandle=bar['handle'], lastHp=bar['hp'], lastMax=bar['maxHp'],
                           phases=[bar['name']], partialStart=not self.seen_clear or bar['hp'] < bar['maxHp']*.99,
                           partialReason=('The boss bar was already visible when observation began; its full start is unknown.'
                                          if not self.seen_clear else 'Observed after damage had already occurred.'),
                           deathBase=stats['deaths'], killedBase=fresh.copy())
        self._persist(now)
        self.seen_clear = False

    def observe(self, context, stats, killed, bars, ready, live_available, process_state,
                boss_resolver, boss_names, now=None, category_key=None):
        now = _clock(now)
        fresh = self._profile(context, stats, killed) if ready else None
        if fresh is None:
            self.interrupt('Valid character save data became unavailable; outcome is unknown.', now)
            self.seen_clear = False
            self.last_observed = now
            return
        category_key = category_key[:128] if isinstance(category_key, str) and category_key else None
        if category_key != self.category_key:
            self.interrupt('Run category changed; this attempt was interrupted.', now)
            self.category_key = category_key
            self.pending = []
            self.seen_clear = False
        if context != self.context:
            self.interrupt('Character or journey changed; this attempt was interrupted.', now)
            self.context = context
            self.last_deaths, self.last_killed = stats['deaths'], fresh.copy()
            self.pending = []
            self.blocked = None
            self.seen_clear = False
            self.last_observed = None
        self.contexts.setdefault(context, dict(character=stats['name'][:256], journey=stats['journey'], records=[]))
        self.contexts[context].update(character=stats['name'][:256], journey=stats['journey'])
        if (self.last_deaths is not None and stats['deaths'] < self.last_deaths
                or self.last_killed is not None and self.last_killed-fresh):
            self.interrupt('Saved progress moved backwards; this attempt was interrupted.', now)
            self.pending = []
        death_delta = max(0, stats['deaths']-(self.last_deaths if self.last_deaths is not None else stats['deaths']))
        new_kills = fresh-(self.last_killed if self.last_killed is not None else fresh)
        death_delta = self._reconcile(fresh, new_kills, death_delta, stats['deaths'], now)
        self.last_deaths, self.last_killed = stats['deaths'], fresh.copy()
        valid = self._bars(bars, boss_resolver) if live_available else []
        # A saved result takes priority over a simultaneously disappearing process/HUD.
        if self.active and self.ambiguous_result:
            self._finish('unconfirmed', now, 'A saved result spans this and a preceding attempt; attribution and exact completion time are unconfirmed.', self.active['lastSeen'])
            self.pending = []
        elif self.active and self.active['bossId'] is not None and self.active['bossId'] in new_kills:
            end = self.active['zeroAt'] if self.active['zeroAt'] is not None else self.active['lastSeen']
            if any(self._same(self.active, bar) and bar['hp'] == 0 for bar in valid):
                end = now if self.active['zeroAt'] is None else self.active['zeroAt']
                self.active['zeroAt'] = end
            self._finish('victory', now, 'Victory confirmed by the saved boss defeat flag; timing is observed HUD time.', end)
        elif self.active and death_delta > 0:
            end = self.active['lastSeen'] if self.active['missingSince'] is not None else now
            self._finish('death', now, 'Player death confirmed by the saved death counter; detection may be delayed.', end)
        elif self.active and (not live_available or process_state in ('absent', 'exited', 'stopped')):
            reason = 'Game process ended; a crash and a normal exit cannot be distinguished.' if process_state in ('absent', 'exited', 'stopped') else 'Live boss observation disconnected; outcome is unknown.'
            self.interrupt(reason, now)
        elif self.active and self.last_observed is not None and (now < self.last_observed or now-self.last_observed > self.MAX_SAMPLE_GAP):
            self.interrupt('Boss observation gap; this attempt is incomplete.', now)
        self.last_observed = now
        if not live_available or process_state in ('absent', 'exited', 'stopped'):
            self.blocked = None if process_state in ('absent', 'exited', 'stopped') else self.blocked
            self.seen_clear = False
            return
        if not valid:
            self.blocked = None
            self.seen_clear = True
        if self.active:
            matching = next((b for b in valid if self._same(self.active, b)), None)
            if matching is not None:
                active = self.active
                phase_changed = matching['name'] != active['lastName']
                # A refill or new handle can be an unchanged-name second phase
                # (for example Scadutree Avatar), not evidence of player death.
                active['lastSeen'] = now
                active['missingSince'] = None
                if phase_changed:
                    active['phases'].append(matching['name'])
                if matching['hp'] == 0 and active['zeroAt'] is None:
                    active['zeroAt'] = now
                elif matching['hp'] > 0:
                    active['zeroAt'] = None
                active.update(lastName=matching['name'], lastHandle=matching['handle'], lastHp=matching['hp'], lastMax=matching['maxHp'])
            else:
                if self.active['missingSince'] is None:
                    self.active['missingSince'] = now
                if now-self.active['missingSince'] >= self.HUD_GRACE:
                    end = self.active['zeroAt'] if self.active['zeroAt'] is not None else self.active['lastSeen']
                    self._finish('unconfirmed', now, 'Boss bar disappeared without a saved victory or death. Outcome unconfirmed.', end)
        if self.active is None:
            for bar in valid:
                if bar['hp'] == 0 or bar['bossId'] is not None and bar['bossId'] in fresh:
                    continue
                block = self.blocked
                if block and block['context'] == context and block['handle'] == bar['handle'] and block['name'] == bar['name']:
                    recovered = bar['hp'] >= bar['maxHp']*.99 and block['hp'] < block['maxHp']*.9
                    if not recovered:
                        continue
                self.blocked = None
                self._start(bar, stats, fresh, boss_names, now)
                break
        if (self.active or self.storage_error) and (self.last_checkpoint is None or now-self.last_checkpoint >= 5):
            self._persist(now)

    def _benchmarks(self, boss_id, journey):
        times = sorted(r['elapsedSeconds'] for context in self.contexts.values() if context['journey'] == journey
                       for r in context['records'] if boss_id is not None and r['bossId'] == boss_id
                       and r.get('categoryId') == self.category_key
                       and r['outcome'] == 'victory' and r['eligibleForBenchmark'])
        # Include the best in the fast sample so its mean cannot exceed the
        # overall mean when only two or three completions are available.
        near = times[:max(2, math.ceil(len(times)/4))] if len(times) > 1 else []
        return dict(bestSeconds=times[0] if times else None,
                    nearBestSeconds=sum(near)/len(near) if near else None,
                    averageSeconds=sum(times)/len(times) if times else None,
                    sampleCount=len(times), scaleSeconds=self.SCALE_SECONDS,
                    scope=(f'Personal history · Journey {journey}' if journey else 'Personal history')
                          +(f' · {self.category_key}' if self.category_key else ''),
                    categoryId=self.category_key,
                    nearBestDefinition='Mean of the fastest quarter of confirmed completions, using at least two samples.')

    def snapshot(self, now=None):
        now = _clock(now)
        context = self.contexts.get(self.context, {})
        records = copy.deepcopy([r for r in context.get('records', []) if r.get('categoryId') == self.category_key])
        active = self._public_active(now)
        last = records[-1] if records else None
        target = active or last
        benchmarks = self._benchmarks(target.get('bossId') if target else None, context.get('journey'))
        notice = self.notice
        if self.storage_error:
            notice += (' ' if notice else '')+'Attempt changes could not be saved to disk; export a copy before closing.'
        if target and target.get('bossId') is None:
            notice += (' ' if notice else '')+'Exact arena is unresolved; these times are excluded from personal benchmarks.'
        return dict(contextKey=self.context, categoryId=self.category_key, active=active, lastAttempt=last, benchmarks=benchmarks,
                    records=records, notice=notice)

    @staticmethod
    def _format(seconds):
        milliseconds = round(max(0, seconds)*1000)
        whole, fraction = divmod(milliseconds, 1000)
        return f'{whole//3600:02}:{whole//60%60:02}:{whole%60:02}.{fraction:03}'

    def export_records(self, context=None, since=None, now=None, until=None):
        now = _clock(now)
        key = self.context if context is None else context
        info = self.contexts.get(key, {})
        records = copy.deepcopy(info.get('records', []))
        active = self._public_active(now)
        if active and active['contextKey'] == key:
            records.append(active)
        if since or until:
            try:
                after = datetime.fromisoformat(since) if since else None
                before = datetime.fromisoformat(until) if until else None
                if after and before and before < after:
                    raise ValueError('Run end precedes its start.')
                records = [r for r in records if (after is None or datetime.fromisoformat(r['startedAt']) >= after)
                           and (before is None or datetime.fromisoformat(r['startedAt']) <= before)]
                for record in records:
                    if before is not None and (record['endedAt'] is None or datetime.fromisoformat(record['endedAt']) > before):
                        # We did not sample the boss timer at the external run's
                        # finish boundary. Do not borrow a later result/duration.
                        record.update(outcome='in-progress-at-run-end', elapsedSeconds=None,
                                      note='Attempt was unfinished at the run end. A later result or duration is not attributed to this run.')
            except (TypeError, ValueError):
                raise ValueError('Invalid run time bounds for attempt export.')
        return dict(contextKey=key, character=info.get('character', 'Unavailable'),
                    journey=info.get('journey'), records=records)

    def export_text(self, context=None, since=None, now=None, until=None):
        info = self.export_records(context=context, since=since, now=now, until=until)
        records = info['records']
        lines = ['OBSERVED BOSS ATTEMPTS', f'Character: {_clean(info.get("character", "Unavailable"))}',
                 f'Journey: {info.get("journey", "Unavailable")}', '', 'BOSS SUMMARY',
                 'Boss | Observed attempts | Victories | Deaths | Unconfirmed/interrupted | Total observed time']
        grouped = {}
        for record in records:
            identity = ('id', record['bossId'], record.get('categoryId')) if record['bossId'] is not None else ('unresolved', record['recordId'])
            grouped.setdefault(identity, []).append(record)
        for group in grouped.values():
            name = _clean(group[0]['name']) + (' [arena unresolved]' if group[0]['bossId'] is None else '')
            if group[0].get('categoryId'):
                name += f' [category: {_clean(group[0]["categoryId"])}]'
            count = lambda outcome: sum(r['outcome'] == outcome for r in group)
            total = self._format(sum(r['elapsedSeconds'] for r in group)) if all(r['elapsedSeconds'] is not None for r in group) else 'Unavailable: unfinished at run end'
            lines.append(f'{name} | {len(group)} | {count("victory")} | {count("death")} | '
                         f'{count("unconfirmed")+count("interrupted")} | {total}')
        if not records:
            lines.append('No live boss attempts observed in this scope.')
        lines.extend(['', 'ATTEMPT DETAILS', 'Boss | Attempt | Duration | Outcome | Started UTC | Category | Notes'])
        for record in records:
            duration = self._format(record['elapsedSeconds']) if record['elapsedSeconds'] is not None else 'Not recorded at run end'
            lines.append(f'{_clean(record["name"])} | {record["attemptNumber"] or "Unresolved arena"} | '
                         f'{duration} | {record["outcome"]} | '
                         f'{record["startedAt"]} | {_clean(record.get("categoryId") or "Unclassified")} | {_clean(record.get("note") or "Observed live HUD timing")}')
        lines.extend(['', 'ATTEMPT TIMING NOTES',
                      '- Boss timers use observed live HUD time, not official speedrun timing. No Escape-key pauses are applied.',
                      '- Deaths and victories require saved counters/flags. Save detection can be delayed.',
                      '- A disappearing bar alone is unconfirmed; process exit is interrupted, not proof of a crash.',
                      '- Personal benchmarks require a near-full-HP start, observed zero HP and a saved victory flag.',
                      '- Partial starts, missing finish observations and unresolved arenas are excluded from benchmarks.',
                      '- Benchmarks use exact boss IDs, journey number and category across local characters/runs.',
                      '- Unclassified historical attempts are not mixed into a selected category.',
                      '- Near-best is the mean of the fastest quarter of confirmed completions, using at least two samples.',
                      '- The progress scale ends at 15 minutes; longer durations are preserved in full.', ''])
        return '\n'.join(lines)
