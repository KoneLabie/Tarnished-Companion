"""Bounded, character-scoped observations of the last saved equipment.

This is a save-snapshot history, not a claim to observe every live gear swap.
It lives inside the signed external run record and freezes at its endpoint.
"""
import copy
from datetime import datetime, timezone
import json
import math

MAX_OBSERVATIONS = 512
MAX_SNAPSHOT_BYTES = 12288
MAX_HISTORY_BYTES = 512 * 1024
NOTICE = ('Equipment and base attributes come from checksum-validated character saves. '
          'Changes between saves and temporary buffs are not observed. Observation times '
          'are when the tracker read the saved loadout, not exact equipment-change times.')


def _size(value):
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False,
                          separators=(',', ':')).encode('utf-8'))


def snapshot_valid(value):
    if not isinstance(value, dict):
        return False
    try:
        return _size(value) <= MAX_SNAPSHOT_BYTES and value.get('source') == 'checksum-validated-save'
    except (ValueError, TypeError, RecursionError):
        return False


def history_valid(value):
    if value is None:
        return True
    if not isinstance(value, dict) or set(value) != {'observations', 'truncated'}:
        return False
    try:
        if _size(value) > MAX_HISTORY_BYTES:
            return False
    except (ValueError, TypeError, RecursionError):
        return False
    records = value.get('observations')
    if type(value.get('truncated')) is not bool or not isinstance(records, list) or len(records) > MAX_OBSERVATIONS:
        return False
    for row in records:
        if not isinstance(row, dict) or set(row) != {'observedAt', 'savedAt', 'elapsedSeconds', 'snapshot'}:
            return False
        if not isinstance(row['observedAt'], str) or len(row['observedAt']) > 100:
            return False
        if row['savedAt'] is not None and (not isinstance(row['savedAt'], str) or len(row['savedAt']) > 100):
            return False
        seconds = row['elapsedSeconds']
        if seconds is not None and (type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 <= seconds < 1e12):
            return False
        if not snapshot_valid(row['snapshot']):
            return False
    return True


def observe_build(record, stats, context, ready, saved_at=None, allow_finished=False, observed_at=None,
                  timer_current=True):
    if (not record or record.get('contextKey') != context or not ready or not isinstance(stats, dict)
            or record.get('status') not in (('running', 'paused', 'finished') if allow_finished else ('running', 'paused'))):
        return False
    snapshot = copy.deepcopy(stats.get('build'))
    if not snapshot_valid(snapshot):
        return False
    snapshot['character'] = str(stats.get('name', ''))[:256]
    if not snapshot_valid(snapshot):
        return False
    stamp = observed_at if observed_at is not None else datetime.now(timezone.utc).isoformat(timespec='milliseconds')
    if not isinstance(stamp, str) or not 1 <= len(stamp) <= 100:
        return False
    try:
        if saved_at is not None and (type(saved_at) not in (int, float) or not math.isfinite(saved_at)):
            return False
        saved = datetime.fromtimestamp(saved_at, timezone.utc).isoformat(timespec='milliseconds') if saved_at is not None else None
    except (ValueError, OverflowError, OSError):
        return False
    history = record.setdefault('buildHistory', dict(observations=[], truncated=False))
    rows = history['observations']
    if rows and rows[-1]['snapshot'] == snapshot:
        return False
    seconds = record.get('elapsedSeconds') if timer_current is True else None
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 <= seconds < 1e12:
        seconds = None
    row = dict(observedAt=stamp, savedAt=saved, elapsedSeconds=seconds, snapshot=snapshot)
    rows.append(row)
    while len(rows) > MAX_OBSERVATIONS or _size(history) > MAX_HISTORY_BYTES:
        # Keep the initial observation and the newest evidence. Never silently
        # claim this bounded history is an exhaustive inventory of changes.
        del rows[1]
        history['truncated'] = True
    return True


def export_build(record):
    history = copy.deepcopy((record or {}).get('buildHistory') or {})
    rows = history.get('observations', [])
    return dict(status='available' if rows else 'unavailable', source='saved-loadout-observations',
                notice=NOTICE if rows else 'No verified character loadout was observed during this recording.',
                initial=rows[0]['snapshot'] if rows else None,
                final=rows[-1]['snapshot'] if rows else None,
                observations=rows, truncated=bool(history.get('truncated')))
