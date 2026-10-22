"""Regenerate the reduced GPL-3.0 equipment name/family reference, not game data.

Derived from oisis/EldenRing-SaveForge; see equipment-catalog-sources.md.
This developer-only script downloads pinned source tables, never reads saves.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import json
import re
from urllib.request import urlopen

COMMIT = 'ee1042d7a5bd933f91e6f8a0162e0e0237a1c4c5'
BASE = f'https://raw.githubusercontent.com/oisis/EldenRing-SaveForge/{COMMIT}/backend/db/data/'
FILES = ('melee_armaments.go', 'ranged_and_catalysts.go', 'shields.go',
         'head.go', 'chest.go', 'arms.go', 'legs.go', 'talismans.go', 'weapon_gem_mount.go')


def fetch(name):
    with urlopen(BASE+name, timeout=25) as response:
        raw = response.read(2*1024*1024+1)
    if len(raw) > 2*1024*1024:
        raise ValueError('Reference source exceeds bounds.')
    return name, raw


def main():
    sources = dict(ThreadPoolExecutor(max_workers=5).map(fetch, FILES))
    items, anchors = {}, {}
    for filename, raw in sources.items():
        for line in raw.decode('utf-8').splitlines():
            match = re.match(r'\s*(0x[0-9A-Fa-f]+):\s*\{(.*)\},?$', line)
            if not match:
                continue
            item_id, fields = int(match[1], 16), match[2]
            if filename == 'weapon_gem_mount.go':
                origin = re.search(r'OriginEquipWep:\s*(0x[0-9A-Fa-f]+|[0-9]+)', fields)
                if origin:
                    base = int(origin[1], 16 if origin[1].startswith('0x') else 10)
                    if item_id == base or 'CanChangeAffinity: true' in fields:
                        anchors[str(item_id)] = base
                continue
            name = re.search(r'Name:\s*("(?:[^"\\]|\\.)*")', fields)
            limit = re.search(r'MaxUpgrade:\s*([0-9]+)', fields)
            if not name or not limit:
                raise ValueError('Equipment reference shape changed.')
            group = filename.removesuffix('.go')
            if group in ('melee_armaments', 'ranged_and_catalysts', 'shields'):
                group = 'weapon'
            items[str(item_id)] = dict(name=json.loads(name[1]), group=group, maxUpgrade=int(limit[1]))
    anchors = {anchor: origin for anchor, origin in anchors.items()
               if str(origin) in items and items[str(origin)]['group'] == 'weapon'
               and 0 <= int(anchor)-origin <= 1200 and (int(anchor)-origin) % 100 == 0}
    output = dict(schemaVersion=1, source='oisis/EldenRing-SaveForge', commit=COMMIT,
                  license='GPL-3.0', modified='2026-10-22: reduced to names, slots and verified weapon-family anchors',
                  sources={name:dict(url=BASE+name, sha256=hashlib.sha256(raw).hexdigest()) for name,raw in sources.items()},
                  items=items, weaponAnchors=anchors)
    path = Path(__file__).with_name('equipment-catalog.json')
    path.write_text(json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(',', ':'))+'\n', encoding='utf-8')
    print(f'Wrote {len(items)} item references and {len(anchors)} weapon-family anchors ({path.stat().st_size} bytes).')


if __name__ == '__main__':
    main()
