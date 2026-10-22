"""Suggested personal boss queues; category routes are managed separately."""
from run_categories import ENCOUNTERS


MAJOR = (10000850, 10000800, 14000850, 14000800, 1252380800, 11000850,
         11000800, 1052520800, 13000850, 13000800, 11050850, 11050800, 19000800)
DLC_MAIN = (20000800, 2048440800, 21000850, 21010800, 2044450800, 20010800)
OPTIONAL = (16000800, 12050800, 15000850, 15000800, 13000830, 22000800,
            25000800, 2054390800, 28000800)


def build_presets(bosses, include_dlc):
    """Return ordered {label: [catalog IDs]} with no DLC when excluded.

    Exactly four base-game choices or six DLC-inclusive choices are returned.
    Curated queue order is retained. Main routes are suggestions, not mandatory
    order or speedrun category rules. Call with detection['available'] is True.
    """
    if type(include_dlc) is not bool:
        raise ValueError('include_dlc must be a boolean.')
    catalog = []
    seen = set()
    for boss in bosses if isinstance(bosses, (list, tuple)) else []:
        if (not isinstance(boss, dict) or type(boss.get('id')) is not int or boss['id'] <= 0
                or boss['id'] in seen or not isinstance(boss.get('name'), str)
                or type(boss.get('dlc')) is not bool):
            continue
        seen.add(boss['id'])
        if include_dlc or not boss['dlc']:
            catalog.append(boss)
    by_id = {boss['id']: boss for boss in catalog}

    def verified(ids):
        return list(dict.fromkeys(i for i in ids if i in by_id and by_id[i]['name'] == ENCOUNTERS.get(i)))

    base = [boss['id'] for boss in catalog if not boss['dlc']]
    dlc = [boss['id'] for boss in catalog if boss['dlc']]
    presets = {'Major bosses': verified(MAJOR)}
    if include_dlc:
        # Keep existing curated DLC queue order.
        presets['Major bosses + DLC'] = verified(MAJOR + DLC_MAIN)
        presets['DLC main route'] = verified(DLC_MAIN)
        presets['DLC all encounters'] = dlc
        presets['Major + optional + DLC'] = verified(MAJOR + OPTIONAL + DLC_MAIN)
    else:
        presets['Major bosses + Optional'] = verified(MAJOR + OPTIONAL)
        presets['Optional'] = verified(OPTIONAL)
    presets['All encounters'] = [boss['id'] for boss in catalog]
    return presets
