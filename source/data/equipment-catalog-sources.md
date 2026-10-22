# Saved build reference

Reviewed and generated 2026-10-22. A build is taken from the same selected,
checksum-validated character slot as boss progress. The eight base attributes
occupy PlayerGameData +0x34 through +0x50. Level and class use the reader's existing
validated fields. Attributes outside 1–99 are unavailable rather than clamped.
The dynamically located equipped-armaments block follows the variable-length
projectile list. It supplies six hand slots, four armor slots and four talismans.
The saved active hand indexes come from the earlier active-slot block.

Layout references:

- [ER-Save-Lib UserDataX](https://github.com/ClayAmore/ER-Save-Lib/blob/master/src/save/user_data_x.rs): PlayerGameData, ActiveWeaponSlotsAndArmStyle and EquippedArmamentsAndItems.
- [SaveForge's read-only equipment reader](https://github.com/oisis/EldenRing-SaveForge/blob/ee1042d7a5bd933f91e6f8a0162e0e0237a1c4c5/backend/core/equipment_reader.go): the full armaments block is the item-ID source; the earlier equipment header can use different encodings.

`equipment-catalog.json` is a reduced, modified reference derived from
[EldenRing-SaveForge](https://github.com/oisis/EldenRing-SaveForge), commit
`ee1042d7a5bd933f91e6f8a0162e0e0237a1c4c5`, by oisis and contributors, under
[GNU GPL version 3](https://github.com/oisis/EldenRing-SaveForge/blob/ee1042d7a5bd933f91e6f8a0162e0e0237a1c4c5/LICENSE).
The distribution includes GPL-3.0 in the project's LICENSE.txt. Modifications on
2026-10-22 reduce tables to names, equipment groups, upgrade bounds and confirmed
weapon-family anchors. Each input URL and SHA-256 is recorded in the JSON.
`build-equipment-catalog.py` regenerates it from pinned sources. No art is copied.
Game item names remain the property of their respective owners.

Weapons resolve through explicit materialized family anchors, following
[SaveForge's identity rules](https://github.com/oisis/EldenRing-SaveForge/blob/ee1042d7a5bd933f91e6f8a0162e0e0237a1c4c5/backend/db/weapon_identity.go).
Unknown IDs, unsupported upgrades, absent tables or wrong item categories retain
the raw value with an unavailable name. There is no nearest-name guess. Empty
sentinels and the known Unarmed placeholder are explicit. Named items are not
evidence that their use was legal in a category.

Snapshots describe last-saved state. They do not capture every live quick swap,
temporary buff, damage scaling or resistance. The caller timestamps observations
and binds them to its selected-character identity. No Steam ID, multiplayer
password, unrelated character, or complete inventory is copied into a build.
