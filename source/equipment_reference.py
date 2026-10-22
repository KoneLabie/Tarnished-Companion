"""Read-only saved build snapshots; no live-buff or continuous-equipment claims.

The caller supplies dynamically parsed offsets from a checksum-validated slot.
See data/equipment-catalog-sources.md for layouts and the GPL-3.0 name reference.
"""
from functools import lru_cache
import json
from pathlib import Path
import struct


ATTRIBUTES = ('vigor', 'mind', 'endurance', 'strength', 'dexterity', 'intelligence', 'faith', 'arcane')
AFFINITIES = ('Standard', 'Heavy', 'Keen', 'Quality', 'Fire', 'Flame Art', 'Lightning',
              'Sacred', 'Magic', 'Cold', 'Poison', 'Blood', 'Occult')
WEAPON_SLOTS = ('left-hand-1', 'right-hand-1', 'left-hand-2', 'right-hand-2', 'left-hand-3', 'right-hand-3')
ARMOR_SLOTS = ('head', 'chest', 'arms', 'legs')
NOTICE = ('Last saved character build; changes appear only after a game save. '
          'This does not capture every live equipment swap, buffs, or prove gameplay compliance.')


@lru_cache(maxsize=1)
def _catalog():
    path = Path(__file__).parent / 'data' / 'equipment-catalog.json'
    try:
        if path.stat().st_size > 1024*1024:
            return {}, {}
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('schemaVersion') != 1 or not isinstance(data.get('items'), dict) or not isinstance(data.get('weaponAnchors'), dict):
            return {}, {}
        if len(data['items']) > 10000 or len(data['weaponAnchors']) > 10000:
            return {}, {}
        items = {}
        for key, value in data['items'].items():
            if (not key.isascii() or not key.isdigit() or not 0 <= int(key) < 0x80000000
                    or not isinstance(value, dict) or not isinstance(value.get('name'), str)
                    or not 1 <= len(value['name']) <= 160 or any(ord(c)<32 for c in value['name'])
                    or value.get('group') not in ('weapon', 'head', 'chest', 'arms', 'legs', 'talismans')
                    or type(value.get('maxUpgrade')) is not int or not 0 <= value['maxUpgrade'] <= 25):
                return {}, {}
            items[int(key)] = value
        anchors = {}
        for key, value in data['weaponAnchors'].items():
            if (not key.isascii() or not key.isdigit() or type(value) is not int
                    or value not in items or items[value]['group'] != 'weapon'
                    or not 0 <= int(key)-value <= 1200 or (int(key)-value) % 100):
                return {}, {}
            anchors[int(key)] = value
        return items, anchors
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        return {}, {}


def resolve_equipment(raw_id, group, slot, *, active=None):
    """Preserve exact saved IDs; resolve only catalog-confirmed identities."""
    if type(raw_id) is not int or not 0 <= raw_id <= 0xffffffff:
        raise ValueError('Invalid saved equipment ID.')
    item = dict(slot=slot, rawItemId=raw_id, itemId=None, name=None, status='unavailable')
    if active is not None:
        item['active'] = active
    if raw_id == 0xffffffff:
        item['status'] = 'empty'
        return item
    # The full armaments block includes item category bits. Some layouts set
    # the high equipment bit; removing it retains weapon/armor/talisman type.
    item_id = raw_id & 0x7fffffff
    item['itemId'] = item_id
    items, anchors = _catalog()
    if group == 'weapon' and item_id == 110000:
        return dict(item, name='Unarmed', status='empty', upgradeLevel=0, affinity='Standard')
    if group == 'weapon':
        if item_id & 0xf0000000:
            return item
        anchor = item_id-item_id % 100
        base = anchors.get(anchor)
        reference = items.get(base)
        level = item_id % 100
        if reference and level <= reference['maxUpgrade']:
            return dict(item, name=reference['name'], status='resolved', baseItemId=base,
                        upgradeLevel=level, affinity=AFFINITIES[(anchor-base)//100])
    else:
        reference = items.get(item_id)
        if reference and reference['group'] == group:
            return dict(item, name=reference['name'], status='resolved')
    return item


def saved_build(data, character_offset, armaments_offset, *, slot, level, origin):
    """Extract selected-slot base attributes and last-saved loadout.

    All buffers/offsets must come from the same accepted save. Partial optional
    build fields stay explicit and never replace authoritative boss progress.
    No account identifier, password, inventory, or unrelated slot is copied.
    """
    def u32(offset):
        if type(offset) is not int or offset < 0 or offset+4 > len(data):
            raise ValueError('Saved build section is truncated.')
        return struct.unpack_from('<I', data, offset)[0]

    attributes, issues = {}, []
    for index, name in enumerate(ATTRIBUTES):
        value = u32(character_offset+0x34+index*4)
        attributes[name] = value if 1 <= value <= 99 else None
        if attributes[name] is None:
            issues.append(f'Saved {name} is outside supported attribute bounds.')
    # PlayerGameData (0x1b0), 13 effects (16 bytes), equip indexes (88 bytes).
    active_offset = character_offset + 0x1b0 + 13*16 + 88
    left, right = u32(active_offset+4), u32(active_offset+8)
    if left > 2:
        left = None
        issues.append('Saved active left-hand slot is unavailable.')
    if right > 2:
        right = None
        issues.append('Saved active right-hand slot is unavailable.')
    weapons = []
    for index, name in enumerate(WEAPON_SLOTS):
        selected = left if index % 2 == 0 else right
        entry = resolve_equipment(u32(armaments_offset+index*4), 'weapon', name,
                                  active=(index//2 == selected) if selected is not None else None)
        if selected is None:
            entry['active'] = None
        weapons.append(entry)
    armor = [resolve_equipment(u32(armaments_offset+(12+index)*4), name, name)
             for index, name in enumerate(ARMOR_SLOTS)]
    talismans = [resolve_equipment(u32(armaments_offset+(17+index)*4), 'talismans', f'talisman-{index+1}')
                for index in range(4)]
    if any(item['status'] == 'unavailable' for item in weapons+armor+talismans):
        issues.append('Some equipment names or encodings are unavailable; exact saved IDs are retained.')
    return dict(status='partial' if issues else 'available', source='checksum-validated-save',
                saveSlot=slot, level=level, **{'class': origin}, attributes=attributes,
                equipment=dict(weapons=weapons, armor=armor, talismans=talismans,
                               activeWeaponSlots=dict(left=left, right=right)),
                notice=NOTICE, issues=issues)
