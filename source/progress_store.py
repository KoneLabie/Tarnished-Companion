"""Versioned local tracking contexts, independent of boss queue order.

The save has no verified immutable character GUID. Slot generations use observed
replacement/rollback evidence, and an explicit local reset covers indistinguishable
imports. A renamed character keeps its context; no game file is ever written.
"""
import hashlib
import math
import os
from pathlib import Path
import secrets


DEFAULT_LAYOUT = dict(width=360, opacity=.72, font='Cinzel', icons=8, animateGlow=True, showBossTraits=True)


def clean_route(value, valid_ids, default):
    if not isinstance(value, list):
        return list(default)
    return list(dict.fromkeys(i for i in value if type(i) is int and i in valid_ids))


def normalize_settings(raw, valid_ids, default_route):
    raw = raw if isinstance(raw, dict) else {}
    cfg = dict(schemaVersion=2, save=raw.get('save') if isinstance(raw.get('save'), str) else '',
               slot=raw.get('slot', 0), contexts={}, characters={},
               showCharacterName=raw.get('showCharacterName', True) is not False,
               overlayView=raw.get('overlayView') if raw.get('overlayView') in ('home', 'combat', 'speedrun') else 'home',
               timingMode='livesplit',
               liveSplitPort=raw.get('liveSplitPort') if type(raw.get('liveSplitPort')) is int and 1024 <= raw['liveSplitPort'] <= 65535 else 16834,
               liveDetection=raw.get('liveDetection', True) is not False,
               layout=DEFAULT_LAYOUT.copy())
    if type(cfg['slot']) is not int or not 0 <= cfg['slot'] < 10:
        cfg['slot'] = 0
    layout = raw.get('layout')
    if isinstance(layout, dict):
        for field, valid in (
            ('width', lambda x: type(x) is int and 280 <= x <= 600),
            ('opacity', lambda x: type(x) in (int, float) and .35 <= x <= .95 and math.isfinite(x)),
            ('font', lambda x: x in ('Cinzel', 'Georgia', 'System')),
            ('icons', lambda x: type(x) is int and x in (4, 6, 8)),
            ('animateGlow', lambda x: type(x) is bool),
            ('showBossTraits', lambda x: type(x) is bool),
        ):
            if field in layout and valid(layout[field]):
                cfg['layout'][field] = layout[field]
    contexts = raw.get('contexts')
    if isinstance(contexts, dict):
        for key, value in contexts.items():
            if not isinstance(value, dict):
                continue
            kills = value.get('enemyKills', 0)
            cfg['contexts'][key] = dict(route=clean_route(value.get('route'), valid_ids, default_route),
                                       enemyKills=kills if type(kills) is int and 0 <= kills <= 999999 else 0)
    characters = raw.get('characters')
    if isinstance(characters, dict):
        for key, record in characters.items():
            if not isinstance(record, dict) or not isinstance(record.get('identity'), str):
                continue
            integer_fields = ('seconds', 'journey', 'level', 'originId', 'startingGift')
            if any(type(record.get(k)) is not int or record[k] < 0 for k in integer_fields):
                continue
            if not isinstance(record.get('context'), str):
                continue
            cfg['characters'][key] = {k: record[k] for k in integer_fields}
            cfg['characters'][key].update(identity=record['identity'], context=record['context'],
                                           active=record.get('active') is True,
                                           defeated=clean_route(record.get('defeated'), valid_ids, []))
    return cfg


def file_key(path):
    canonical = os.path.normcase(str(Path(path).resolve()))
    return hashlib.sha256(canonical.encode()).hexdigest()[:24]


def slot_key(path, slot):
    return f'{file_key(path)}:{slot}'


def resolve_context(cfg, path, profile, state, roster, default_route):
    """Select one character generation + one saved journey, resetting on evidence.

    Starting a new journey carries the lineup preference but never its kill count.
    Restoring an older save starts a fresh local generation rather than reviving
    counters earned after that snapshot. Defeated bosses always come from flags.
    """
    registry = cfg['characters']
    prefix = file_key(path) + ':'
    occupied = {p['slot'] for p in roster}
    for i in range(10):
        record = registry.get(prefix + str(i))
        if record and i not in occupied:
            record['active'] = False
    key = slot_key(path, profile['slot'])
    old = registry.get(key)
    snapshot = dict(seconds=profile['seconds'], journey=state['journey'], level=state['level'],
                    originId=state['originId'], startingGift=state['startingGift'])
    reason = ''
    if old:
        if not old['active']:
            reason = 'Fresh character tracking started. Local kills reset; boss progress comes from this save.'
        elif any(snapshot[k] != old[k] for k in ('originId', 'startingGift')):
            reason = 'Character replacement detected. Local kills reset; boss progress comes from this save.'
        elif any(snapshot[k] < old[k] for k in ('seconds', 'journey', 'level')):
            reason = 'An earlier or replaced save was loaded. Local kills restarted to avoid mixing progress.'
        elif snapshot['journey'] == old['journey'] and set(old.get('defeated', [])) - set(state['killed']):
            reason = 'Saved boss progress moved backwards. Local kills restarted to avoid mixing a restored or edited run.'
    identity = secrets.token_hex(12) if old is None or reason else old['identity']
    context = f'v2:{identity}:j{snapshot["journey"]}'
    if context not in cfg['contexts']:
        route = list(default_route)
        if old and not reason:
            route = list(cfg['contexts'].get(old['context'], {}).get('route', route))
            reason = f'Journey {snapshot["journey"]} detected. Local kills reset; boss progress follows the new journey’s save flags.'
        elif old is None:
            # Preserve a previous-version lineup, but its unscoped kill total
            # cannot be safely assigned to the current journey.
            legacy = hashlib.sha256((str(Path(path).resolve())+'|'+str(profile['slot'])+'|'+state['name']).encode()).hexdigest()[:24]
            if legacy in cfg['contexts']:
                route = list(cfg['contexts'][legacy]['route'])
                reason = 'Journey-aware tracking enabled. Your lineup was kept; the old unscoped kill count was reset.'
        cfg['contexts'][context] = dict(route=route, enemyKills=0)
    registry[key] = dict(**snapshot, identity=identity, context=context, active=True, defeated=sorted(state['killed']))
    return context, reason
