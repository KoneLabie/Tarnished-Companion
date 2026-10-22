# Boss combat reference provenance

Reviewed 2026-10-21. The JSON contains all 208 stable encounter IDs from `bosses.json`: 166 base-game encounters and 42 Shadow of the Erdtree encounters. Damage-negation advice is available for 205 encounters; outgoing damage profiles for 157; status-infliction profiles for 54. There are 7 explicit named-phase overrides. An unknown field is `null`, never a guessed family value.

## Numeric source

The numeric source is the community-maintained [ER - PvE Health/Defense/DmgNeg/Resistances/Drops/Flags spreadsheet](https://docs.google.com/spreadsheets/d/1BVwmKqB8pvuyJkSTGYOM2kAJxFMQ0jVsc6aKYz_Upes/edit), whose published title at retrieval was **App Ver. 1.17.1**. Credit belongs to the spreadsheet's maintainers and contributors. The public export did not expose individual author names; none have been inferred.

- Source tab: `NG` (`gid=0`).
- Export: `https://docs.google.com/spreadsheets/d/1BVwmKqB8pvuyJkSTGYOM2kAJxFMQ0jVsc6aKYz_Upes/export?format=csv&gid=0`.
- Retrieved: 2026-10-21.
- Export SHA-256: `c72b9a1d6888b1c395b96d835e4067aea8317ea2896158fb79c1e97837f84ac3`.
- Source rows: 3,341, excluding two header rows.
- Imported columns: the eight **Damage Negation** columns (Standard, Strike, Slash, Pierce, Magic, Fire, Lightning, Holy). Flat Defense and status resistance columns are deliberately not treated as damage negation.
- Each JSON entry records its source NpcParam ID, Chara ID, Lookup ID, row name, location, and original negations. Named-phase overrides retain separate source rows.

[smasimar/er-enemydata](https://github.com/smasimar/er-enemydata) helped locate the original spreadsheet. Its CSV has an older layout. No mirror code, artwork, or numeric CSV values were used in the shipped reference; the final numeric import uses the original current sheet directly. The mirror repository is MIT-licensed, but that does not establish a license for the separately published original spreadsheet. The original public CSV does not state a license. This reference transcribes factual numerical statistics and attack-type facts with attribution, not the source pages' prose or artwork.

## Meaning and interpretation

`weakTo` means the damage type or tied types with the lowest **reference percentage negation**, not necessarily a damage bonus and not a recommendation independent of the player's equipment. A negative value increases damage; a zero value merely does not negate that type. Weapon attack power, flat defense, part/weak-point multipliers, water, buffs, special mechanics and the player's build still matter. This is versioned reference data, not a reading of the current enemy's internal defenses.

The raw `negation` object preserves all four physical subtypes. The UI may collapse four tied physical types to one Physical icon. When all eight values are equal, `weakTo` is an empty array, meaning there is no preferred damage type in this table. An unverified reference is `null`, which is different from an empty array.

For duos or several defensive states that cannot be selected by the health-bar name, `weakTo` is the intersection of the lowest-negation types for every listed member/state. If the numeric profiles differ, `negation` is `null`; the individual original values remain in `sourceRows`. The implementation does not average incompatible profiles. This gives conservative shared advice for the Godskin Duo, Crucible Knight/Misbegotten pair, watchdog pairs, and Crystalian shell states.

`deals` lists the damage types the boss can inflict; `inflicts` lists status ailments separately. Physical subtypes are grouped as `physical` for outgoing icons. Frostbite, Hemorrhage, Poison, Scarlet Rot, Sleep, Madness and Death Blight are never labelled elemental damage. Destined Death's HP reduction/drain and Miquella's charm are not mislabeled as Death Blight or Madness. No status is called a weakness merely because the boss is susceptible to it.

## Attack and phase sources

Outgoing attack facts are primarily transcribed from the explicit **Damage** and **Inflicts** sections of [Tarnished.app's enemy database](https://tarnished.app/enemies). Each included entry links directly to the exact enemy page in `sources`. These are community references, cross-checked for important phase and encounter differences against Eldenpedia/Wiki.gg and the Elden Ring Fandom wiki. Missing or ambiguous attack descriptions remain `null`.

Notable direct sources:

- [Divine Beast Dancing Lion](https://tarnished.app/enemies/divine-beast-dancing-lion) and [Eldenpedia's variant description](https://eldenring.wiki.gg/wiki/Divine_Beast_Dancing_Lion): physical, lightning and magic/ice; Frostbite. The Rauh encounter also has Death Blight/basilisks.
- [Maliketh and Beast Clergyman](https://tarnished.app/enemies/maliketh--the-black-blade): Clergyman physical; Maliketh physical and Holy. Guides calling Maliketh's blade damage Magic were not used.
- [Radagon](https://tarnished.app/enemies/radagon-of-the-golden-order) and [Elden Beast](https://tarnished.app/enemies/elden-beast): separate named phases; Fire is lowest for Radagon, physical types for Elden Beast.
- [Messmer](https://tarnished.app/enemies/messmer-the-impaler) and [phase description](https://eldenring.fandom.com/wiki/Messmer_the_Impaler): Slash in the first phase; Slash and Holy in the serpent phase.
- [Godfrey/Hoarah Loux](https://tarnished.app/enemies/godfrey--first-elden-lord): the spreadsheet supplies separate phase negations (Pierce/Lightning for Godfrey; Slash for Hoarah Loux).
- [Rykard/God-Devouring Serpent](https://tarnished.app/enemies/rykard--lord-of-blasphemy): physical/Fire; Poison applies to the serpent phase. Serpent-Hunter's special effect is separate from damage type.
- [Malenia phases](https://eldenring.fandom.com/wiki/Malenia%2C_Blade_of_Miquella): phase two adds Holy attacks and Scarlet Rot; water modifies Fire/Lightning negation.
- [Promised Consort Radahn](https://tarnished.app/enemies/promised-consort-radahn): the Holy attack addition and the loss of the first phase's Holy weakness are kept phase-specific.
- [Crystalians](https://tarnished.app/enemies/crystalians): the Academy pair includes a staff caster; the Altus pair and single Ringblade encounter do not inherit Magic attacks from that variant.
- [Erdtree Burial Watchdog variants](https://eldenring.wiki.gg/wiki/Erdtree_Burial_Watchdog) and [Cliffbottom encounter](https://www.gamerguides.com/elden-ring/database/bosses/liurnia-of-the-lakes-bosses): distinguish Fire, scepter/Magic and Wyndham/Lightning variants.
- [Valiant Gargoyle](https://eldenring.wiki.gg/wiki/Valiant_Gargoyle): the Siofra pair's physical/Poison profile is kept separate from Black Blade Kindred. The generic page's contradictory Holy field was not used.

Phase overrides use `matchNames` for exact normalized live health-bar names. They do not infer a phase from remaining HP, and every override supplies its own complete set of nullable fields. For bosses whose name stays the same, outgoing icons describe the possible encounter attack pool. They do not promise that a particular move is active at that moment.

## Explicit limitations and exceptions

- Mimic Tear (`12020850`) and Stray Mimic Tear (`30202800`) copy player equipment; fixed weakness and damage icons are disabled. Their table rows are retained only for provenance.
- Fia's Champions (`12030800`) have variable loadouts. The available table rows are not a verified complete encounter profile, so fixed weakness/damage icons are disabled.
- Rennala's lowest-negation types describe the vulnerable phases; her first-phase shield must be broken first. The shield's 100% negation is not displayed as advice.
- Crystalian shell changes are not detectable from the unchanged health-bar name. Strike is a lowest-negation type in both source states; post-break Standard is not advertised before the shell breaks.
- Spirit-Caller Snail references describe the snail, not every spirit it summons.
- Gideon's available spells depend on progression; the note marks conditional Scarlet Rot and Hemorrhage.
- Four existing catalog entries labelled Death Rite Bird correspond to ordinary Deathbird locations. Their location-specific defenses are mapped correctly; outgoing damage is left unknown rather than borrowing the Death Rite Bird's ice attacks.
- Black Knight Edredd's copied online tables disagree with the independently described attack mechanics. His outgoing damage remains unknown rather than asserting Lightning from that uncorroborated table.
- There is no promise that these references remain correct after a balance patch, overhaul mod, randomizer, weather change, or live buff. Update the source version/hash and reviewed encounter mapping when refreshing the file.

## Outgoing damage still unverified

These entries retain useful verified weakness advice where available, but their `deals` field is `null`:

| Encounter ID | Boss | Location |
| --- | --- | --- |
| 11000850 | Godfrey, First Elden Lord (Golden Shade) | Leyndell, Royal Capital |
| 12020850 | Mimic Tear | Nokron, Eternal City |
| 12030800 | Fia's Champion | Deeproot Depths |
| 30030800 | Spirit-Caller Snail | Road's End Catacombs |
| 30090800 | Red Wolf of the Champion | Gelmir Hero's Grave |
| 30120800 | Misbegotten Warrior & Perfumer Tricia | Unsightly Catacombs |
| 30202800 | Stray Mimic Tear | Hidden Path to the Haligtree |
| 31030800 | Beastman of Farum Azula | Groveside Cave |
| 31180800 | Miranda the Blighted Bloom | Perfumer's Grotto |
| 31100800 | Beastman of Farum Azula | Dragonbarrow Cave |
| 31220800 | Spirit-Caller Snail | Spiritcaller's Cave |
| 32000800 | Scaly Misbegotten | Morne Tunnel |
| 32010800 | Stonedigger Troll | Limgrave Tunnels |
| 32040800 | Stonedigger Troll | Old Altus Tunnel |
| 1044360800 | Mad Pumpkin Head | Waypoint Ruins |
| 1043370800 | Night's Cavalry | Agheel Lake North |
| 1042380800 | Death Rite Bird | Stormgate |
| 1042360800 | Tree Sentinel | Church of Elleh |
| 1045390800 | Tibia Mariner | Summonwater Village |
| 1044320850 | Night's Cavalry | Castle Morne Approach |
| 1044320800 | Death Rite Bird | Castle Morne Approach |
| 1039430800 | Night's Cavalry | Liurnia Highway Far North |
| 1036480800 | Night's Cavalry | East Raya Lucaria Gate |
| 1037420800 | Death Rite Bird | Laskyar Ruins |
| 1039440800 | Tibia Mariner | Jarburg |
| 1038510800 | Demi-Human Queen | Lux Ruins |
| 1041510800 | Tree Sentinel Duo | Altus Plateau |
| 1044530800 | Death Rite Bird | Minor Erdtree (Capital Outskirts) |
| 1038520800 | Tibia Mariner | Wyndham Ruins |
| 1039510800 | Night's Cavalry | Altus Highway |
| 1037530800 | Demi-Human Queen | Primeval Sorcerer Azur |
| 1048370800 | Decaying Ekzykes | Caelid Highway South |
| 1049370800 | Night's Cavalry | Southern Aeonia Swamp Bank |
| 1051360800 | Crucible Knight | Redmane Castle |
| 1049390800 | Nox Priest | West Sellia |
| 1052410850 | Night's Cavalry | Dragonbarrow |
| 1051430800 | Black Blade Kindred | Bestial Sanctum |
| 1048400800 | Pumpkin Head Duo | Caelem Ruins |
| 1048510800 | Night's Cavalry | Forbidden Lands |
| 1049520800 | Black Blade Kindred | Before Grand Lift of Rold |
| 1248550800 | Night's Cavalry | Southwest Mountaintops |
| 2046410800 | Blackgaol Knight | Western Nameless Mausoleum |
| 41020800 | Lamenter | Lamenter's Gaol |
| 2049440800 | Dryleaf Dane | Moorth Ruins |
| 2049430850 | Black Knight Edredd | Fort of Reprimand |
| 2051440800 | Rakshasa | Eastern Nameless Mausoleum |
| 2050470800 | Tree Sentinel | Hinterland |
| 2050480860 | Tree Sentinel | Hinterland Bridge |
| 2051450800 | Count Ymir, Mother of Fingers | Cathedral of Manus Metyr |
| 2046380800 | Dancer of Ranah | Southern Nameless Mausoleum |
| 43010800 | Ancient Dragon-Man | Dragon's Pit |
