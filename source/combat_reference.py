"""Offline, sourced combat reference; never inferred from route or boss artwork."""
import copy
import json
import math
from pathlib import Path

DAMAGE_TYPES = ('standard', 'strike', 'slash', 'pierce', 'magic', 'fire', 'lightning', 'holy')
ATTACK_TYPES = frozenset((*DAMAGE_TYPES, 'physical'))
STATUS_TYPES = frozenset(('bleed', 'frost', 'poison', 'scarletRot', 'sleep', 'madness', 'deathBlight'))


def normalized_name(value):
    return ''.join(c for c in str(value).casefold() if c.isalnum())


def unknown_combat(note='Combat reference not verified for this encounter.'):
    return dict(deals=None, inflicts=None, weakTo=None, negation=None, sources=[], note=note)


def typed_list(value, valid):
    if not isinstance(value, list) or any(not isinstance(v, str) or v not in valid for v in value):
        return None
    return list(dict.fromkeys(value))


def clean_reference(raw):
    if not isinstance(raw, dict):
        return unknown_combat()
    result = unknown_combat('')
    result['deals'] = typed_list(raw.get('deals'), ATTACK_TYPES)
    result['inflicts'] = typed_list(raw.get('inflicts'), STATUS_TYPES)
    negation = raw.get('negation')
    if (isinstance(negation, dict) and all(
            type(negation.get(k)) in (int, float) and -100 <= negation[k] <= 100
            and math.isfinite(negation[k]) for k in DAMAGE_TYPES)):
        result['negation'] = {k: negation[k] for k in DAMAGE_TYPES}
        minimum = min(result['negation'].values())
        # Equal negations provide no relative weakness, including all-zero tables.
        result['weakTo'] = ([] if len(set(result['negation'].values())) == 1 else
                            [k for k in DAMAGE_TYPES if result['negation'][k] == minimum])
    else:
        result['weakTo'] = typed_list(raw.get('weakTo'), ATTACK_TYPES)
    sources = raw.get('sources')
    if isinstance(sources, list):
        result['sources'] = list(dict.fromkeys(s for s in sources if isinstance(s, str) and s.startswith('https://')))
    for field in ('note', 'phaseLabel'):
        if isinstance(raw.get(field), str):
            result[field] = raw[field][:1000]
    return result


class CombatReference:
    def __init__(self, path, bosses):
        self.bosses = {b['id']: b for b in bosses}
        self.entries = {}
        self.version = ''
        try:
            raw = json.loads(Path(path).read_text(encoding='utf-8'))
            if not isinstance(raw, dict) or raw.get('schemaVersion') != 1:
                return
            entries = raw.get('entries')
            if not isinstance(entries, dict):
                return
            self.version = str(raw.get('referenceVersion', ''))[:100]
            for key, value in entries.items():
                if not key.isdecimal() or int(key) not in self.bosses or not isinstance(value, dict):
                    continue
                entry = clean_reference(value)
                variants = []
                for variant in value.get('phaseVariants', []) if isinstance(value.get('phaseVariants'), list) else []:
                    if not isinstance(variant, dict):
                        continue
                    names = variant.get('matchNames')
                    if not isinstance(names, list) or not names or any(not isinstance(n, str) for n in names):
                        continue
                    # Phase data is explicit. Missing fields stay unknown rather
                    # than inheriting first-phase weaknesses or status effects.
                    variants.append((set(normalized_name(n) for n in names), clean_reference(variant)))
                self.entries[int(key)] = (entry, variants)
        except (OSError, ValueError, TypeError):
            # Reference data failure must not affect save tracking or live HP.
            self.entries = {}

    def for_boss(self, boss_id, live_name=None):
        if boss_id not in self.entries:
            return unknown_combat()
        entry, variants = self.entries[boss_id]
        if live_name:
            name = normalized_name(live_name)
            for names, phase in variants:
                if name in names:
                    return copy.deepcopy(phase)
            if name != normalized_name(self.bosses[boss_id]['name']):
                return unknown_combat('Combat reference not verified for this phase.')
        return copy.deepcopy(entry)

    def for_live_name(self, live_name):
        """Only common verified fields survive an ambiguous catalog identity."""
        name = normalized_name(live_name)
        candidates = [b['id'] for b in self.bosses.values() if normalized_name(b['name']) == name]
        if not candidates:
            return unknown_combat('Exact encounter or phase is not identified.')
        entries = [self.for_boss(bid, live_name) for bid in candidates]
        common = unknown_combat('Shared traits; exact arena unconfirmed.')
        for field in ('deals', 'inflicts', 'weakTo', 'negation'):
            if all(e[field] == entries[0][field] for e in entries):
                common[field] = copy.deepcopy(entries[0][field])
        common['sources'] = list(dict.fromkeys(s for e in entries for s in e['sources']))
        return common
