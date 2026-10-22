"""Category objective lineups using verified bundled encounter IDs.

These are suggested routes, not timing endpoints or claims of mandatory order.
The caller filters defeated bosses using the active character/journey and uses
its existing custom route outside Speedrun view or for a Custom category.
"""

# Names pin the meaning of IDs so catalog changes cannot silently mislabel a route.
ENCOUNTERS = {
    10000850: 'Margit, the Fell Omen', 10000800: 'Godrick the Grafted',
    14000850: 'Red Wolf of Radagon', 14000800: 'Rennala, Queen of the Full Moon',
    1252380800: 'Starscourge Radahn', 12020850: 'Mimic Tear',
    12090800: 'Regal Ancestor Spirit', 12020800: 'Valiant Gargoyles',
    12030850: 'Lichdragon Fortissax', 12040800: 'Astel, Naturalborn of the Void',
    16000850: 'Godskin Noble', 16000800: 'Rykard, Lord of Blasphemy',
    1045520800: 'Draconic Tree Sentinel', 11000850: 'Godfrey, First Elden Lord (Golden Shade)',
    11000800: 'Morgott, the Omen King', 1051570800: 'Commander Niall',
    15000850: 'Loretta, Knight of the Haligtree', 15000800: 'Malenia, Blade of Miquella',
    12050800: 'Mohg, Lord of Blood', 1052520800: 'Fire Giant',
    13000850: 'Godskin Duo', 13000830: 'Dragonlord Placidusax',
    13000800: 'Maliketh, the Black Blade', 11050850: 'Sir Gideon Ofnir, the All-Knowing',
    11050800: 'Hoarah Loux, Warrior', 19000800: 'Elden Beast',
    20000800: 'Divine Beast Dancing Lion', 2048440800: 'Rellana, Twin Moon Knight',
    21000850: 'Golden Hippopotamus', 2049480800: 'Commander Gaius',
    2050480800: 'Scadutree Avatar', 21010800: 'Messmer the Impaler',
    22000800: 'Putrescent Knight', 2052430800: 'Jori, Elder Inquisitor',
    28000800: 'Midra, Lord of Frenzied Flame', 25000800: 'Metyr, Mother of Fingers',
    43010800: 'Ancient Dragon-Man', 2054390800: 'Bayle the Dread',
    2044450800: 'Romina, Saint of the Bud', 20010800: 'Radahn, Consort of Miquella',
}

ANY_PERCENT = (10000850, 10000800, 14000850, 14000800, 1045520800, 11000850,
               11000800, 1052520800, 13000850, 13000800, 11050850, 11050800, 19000800)

BASE_REMEMBRANCES = frozenset((10000800, 14000800, 1252380800, 12090800, 12030850,
    12040800, 16000800, 11000800, 15000800, 12050800, 1052520800, 13000830,
    13000800, 11050800, 19000800))
DLC_REMEMBRANCES = frozenset((20000800, 2048440800, 2049480800, 2050480800,
    21010800, 22000800, 28000800, 25000800, 2044450800, 20010800))

BASE_ALL = (10000850, 10000800, 14000850, 14000800, 1252380800, 12020850,
    12090800, 12020800, 12030850, 12040800, 16000850, 16000800, 1045520800,
    11000850, 11000800, 1051570800, 15000850, 15000800, 12050800, 1052520800,
    13000850, 13000830, 13000800, 11050850, 11050800, 19000800)
DLC_ALL = (20000800, 2048440800, 21000850, 2049480800, 2050480800, 21010800,
    22000800, 2052430800, 28000800, 25000800, 43010800, 2054390800, 2044450800, 20010800)
CONSORT = (1252380800, 12050800, 21010800, 2044450800, 20010800)

ROUTES = {
    'any-percent-glitchless': ANY_PERCENT,
    'all-remembrances-no-dlc-glitchless': BASE_ALL,
    'all-remembrances-glitchless': BASE_ALL[:-1] + DLC_ALL + BASE_ALL[-1:],
    'defeat-consort-glitchless': CONSORT,
}
NOTES = {
    'any-percent-glitchless': 'Suggested Godrick/Rennala two-Great-Rune route, then the capital and ending bosses. Other legal routes can differ; the category ends at credits, not the final boss defeat.',
    'all-remembrances-no-dlc-glitchless': 'All 15 base-game Remembrance bosses plus suggested access encounters, using the Nokron/Deeproot branch for underground objectives. Item/quest steps and credits still matter.',
    'all-remembrances-glitchless': 'All 25 base-game/DLC Remembrance bosses, Heart of Bayle and suggested access encounters. This is an objective lineup; the run still finishes at credits after the required collections.',
    'defeat-consort-glitchless': 'Fresh-character objective route: Starscourge Radahn and Mohg open DLC access, then Messmer, Romina and Consort. Access/quest/NPC steps are not all boss icons. Finish after Circlet of Light and the required main-menu quitout.',
}
COMMON_NOTE = ' Boss order is a suggestion; actual saved defeats are filtered for the active character and journey.'


def category_route(category_id, bosses):
    """Return encounter IDs; None for unknown/custom means use caller route."""
    if category_id not in ROUTES:
        return None
    if not isinstance(bosses, (list, tuple)):
        return []
    catalog = {boss['id']: boss.get('name') for boss in bosses
               if isinstance(boss, dict) and type(boss.get('id')) is int}
    planned = ROUTES[category_id]
    return list(dict.fromkeys(boss for boss in planned if catalog.get(boss) == ENCOUNTERS[boss]))


def category_route_note(category_id, bosses=None):
    if category_id not in ROUTES:
        return 'Use the custom character route; no predefined category objective lineup is selected.'
    note = NOTES[category_id] + COMMON_NOTE
    if bosses is not None and len(category_route(category_id, bosses)) != len(ROUTES[category_id]):
        note += ' Some catalog encounters could not be verified and were omitted.'
    return note
