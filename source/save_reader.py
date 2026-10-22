"""Read-only PC save reader. Layout adapted from zebbedaja/er-save-parser (MIT).
No write handles to game files. No heuristic searching for event flags.
"""
import hashlib
import struct
from pathlib import Path
from equipment_reference import saved_build

FLAGS_SIZE = 0x1BF99F
STRIDE = 0x280010
SLOT_SIZE = 0x280000
PROFILE_DATA_START = 0x19003B0
PROFILE_DATA_SIZE = 0x60000
CLASS_NAMES = ('Vagabond', 'Warrior', 'Hero', 'Bandit', 'Astrologer',
               'Prophet', 'Confessor', 'Samurai', 'Prisoner', 'Wretch',
               'Idus Knight', 'Heavy Knight')


def require_range(data, pos, size):
    if (type(pos) is not int or type(size) is not int or pos < 0 or size < 0
            or pos > len(data) or size > len(data) - pos):
        raise ValueError('Character data is truncated or uses an unsupported layout.')


def u8(data, pos):
    require_range(data, pos, 1)
    return data[pos]

def u32(data, pos):
    require_range(data, pos, 4)
    return struct.unpack_from('<I', data, pos)[0]


def character_name(data, pos):
    require_range(data, pos, 32)
    try:
        return bytes(data[pos:pos + 32]).decode('utf-16-le').split('\0')[0]
    except UnicodeDecodeError as error:
        raise ValueError('Character name is invalid; waiting for a complete supported save.') from error


def profiles(data):
    if len(data) < PROFILE_DATA_START + PROFILE_DATA_SIZE:
        raise ValueError('Save is truncated or uses an unsupported format.')
    if data[:4] not in (b'BND4', b'SL2\0'):
        raise ValueError('Expected an Elden Ring PC .sl2 or .co2 save.')
    # USER_DATA_10 has its own checksum; slot checksums do not cover occupancy
    # or saved playtime. Never use partially written metadata to switch runs.
    payload = memoryview(data)[PROFILE_DATA_START:PROFILE_DATA_START + PROFILE_DATA_SIZE]
    expected = data[PROFILE_DATA_START - 16:PROFILE_DATA_START]
    if hashlib.md5(payload).digest() != expected:
        raise ValueError('Profile summary checksum is invalid; waiting for a complete save.')
    result = []
    for i in range(10):
        occupied = u8(data, 0x19003B0 + 0x1954 + i)
        if occupied not in (0, 1):
            raise ValueError('Invalid character profile metadata; waiting for a complete save.')
        if not occupied:
            continue
        p = 0x19003B0 + 0x195E + i * 0x24C
        name = character_name(data, p)
        level = u32(data,p+0x22)
        if not 1 <= level <= 713:
            raise ValueError('Invalid character profile level; waiting for a complete save.')
        result.append(dict(slot=i, name=name, level=level, seconds=u32(data,p+0x26)))
    return result

def select_profile(current, selected_slot, previous=None):
    """Follow saved playtime evidence, never the largest total or an occupancy flag.

    The documented profile summary has no verified current-character field. A
    single occupied slot is unambiguous; otherwise we can follow one existing
    character whose playtime advanced since our last successful save snapshot.
    On startup, a changed roster, a rollback, or several changed clocks, retain
    the selected slot. The caller preserves previous provenance for 'unchanged'.
    """
    if not current:
        raise ValueError('No active characters were found.')
    slots = [p.get('slot') for p in current]
    if (any(type(s) is not int or not 0 <= s < 10 for s in slots)
            or len(set(slots)) != len(slots)
            or any(not isinstance(p.get('name'), str)
                   or type(p.get('seconds')) is not int
                   or not 0 <= p['seconds'] <= 0xFFFFFFFF for p in current)):
        raise ValueError('Invalid character profile metadata; waiting for a complete save.')
    selected = next((p for p in current if p['slot'] == selected_slot), current[0])
    if len(current) == 1:
        return selected, 'single-character', 'Showing the only saved character. Playtime updates when the game saves.'
    if selected['slot'] != selected_slot:
        return selected, 'selected-character', 'The selected slot is empty. Showing the first saved character; choose your character below.'
    if previous is None:
        return selected, 'selected-character', 'Showing the selected character until one character\'s saved playtime advances.'
    before = {(p['slot'], p['name']): p['seconds'] for p in previous}
    after = {(p['slot'], p['name']): p['seconds'] for p in current}
    if before.keys() != after.keys():
        return selected, 'ambiguous-save', 'Character slots changed. Keeping the selected character; choose the character you are playing.'
    changed = [key for key in after if after[key] != before[key]]
    if not changed:
        return selected, 'unchanged', ''
    if len(changed) == 1 and after[changed[0]] > before[changed[0]]:
        slot, name = changed[0]
        profile = next(p for p in current if p['slot'] == slot)
        return profile, 'observed-save', 'Following the character whose saved playtime advanced. Character switches appear after the game saves.'
    return selected, 'ambiguous-save', 'Several playtimes changed or a save was restored. Keeping the selected character; choose the character you are playing.'

def slot_state(data, slot, bosses, bst):
    if type(slot) is not int or not 0 <= slot < 10:
        raise ValueError('Invalid character slot.')
    start = 0x310 + slot * STRIDE
    b = memoryview(data)[start:start+SLOT_SIZE]
    if len(b) != SLOT_SIZE:
        raise ValueError('Incomplete character data.')
    expected = data[start-16:start]
    if hashlib.md5(b).digest() != expected:
        raise ValueError('Save is being written or its checksum is invalid; waiting for a complete save.')
    version = u32(b,0)
    if version not in (81,82,83,84,85,86,87,88,262):
        raise ValueError(f'Unsupported save version {version}; automatic progress is paused.')
    p = 32
    for _ in range(0x1400 if version > 81 else 0x13FE):
        handle = u32(b,p)
        p += 8 if handle == 0 or handle & 0xF0000000 == 0xC0000000 else (21 if handle & 0xF0000000 == 0x80000000 else 16)
    char = p
    name = character_name(b, p + 0x94)
    level = u32(b,p+0x60)
    if not 1 <= level <= 713:
        raise ValueError('Character layout is unsupported; no progress was imported.')
    p += 0xB4 + 2 + 10 + 0x18 + 0x21 + 2 + 0x15 + 6*18 + 0x34 + 13*16 + 88 + 28 + 88 + 88
    p += 16 + 12*2688 + 12*384 + 116 + 140 + 24
    n = u32(b,p)
    if n > 10000: raise ValueError('Unsupported projectile section.')
    armaments = p + 4 + n*8
    p = armaments + 156 + 12 + 303 + 16 + 12*0x780 + 12*0x80 + 256
    n = u32(b,p)
    if n > 10000: raise ValueError('Unsupported region section.')
    p += 4 + n*4 + 40 + 1 + 68
    # Saved GameDataMan clear count follows Torrent/control/BloodStain.
    # This offset is relative to the parsed regions end, never a fixed file offset.
    # See data/save-format-notes.md for the independent source cross-checks.
    new_game_count = u32(b, p)
    if new_game_count > 10000:
        raise ValueError('Unsupported journey counter; automatic progress is paused.')
    p += 4 + 4 + 4
    n = u32(b,p)
    if n > 0x10000: raise ValueError('Unsupported menu section.')
    p += 4 + n + 52 + 0x1B588 + 4
    n = u32(b,p)
    if n > 0x10000: raise ValueError('Unsupported tutorial section.')
    p += 4 + n + 3
    deaths = u32(b,p)
    p += 4 + 4 + 1 + 4 + 4 + 1 + 4 + 4
    if p + FLAGS_SIZE > len(b):
        raise ValueError('Event flags are outside the character slot.')
    flags = b[p:p+FLAGS_SIZE]
    def check(event):
        block, index = divmod(event,1000)
        if block not in bst:
            raise ValueError(f'Missing event flag block {block}.')
        pos = bst[block]*125 + index//8
        if pos >= len(flags): raise ValueError('Event flag outside supported layout.')
        return bool(flags[pos] & (1 << (7-index%8)))
    origin = u8(b, char + 0xB7)
    origin_name = CLASS_NAMES[origin] if origin<len(CLASS_NAMES) else 'Unknown'
    build = saved_build(b, char, armaments, slot=slot, level=level, origin=origin_name)
    return dict(name=name, level=level, origin=origin_name,
                originId=origin, startingGift=u8(b, char + 0xBB), journey=new_game_count + 1,
                runes=u32(b,char+0x64), deaths=deaths,
                killed=[x['id'] for x in bosses if check(x['id'])], version=version, build=build)

def read_stable(path):
    path = Path(path)
    before = path.stat()
    # read_bytes uses a read-only handle and takes an in-memory snapshot.
    data = path.read_bytes()
    after = path.stat()
    if (before.st_size,before.st_mtime_ns) != (after.st_size,after.st_mtime_ns):
        raise ValueError('Save changed during reading; retrying shortly.')
    return data

def load_bst(path):
    return {int(a):int(b) for a,b in (line.strip().split(',') for line in Path(path).read_text().splitlines() if line.strip())}
