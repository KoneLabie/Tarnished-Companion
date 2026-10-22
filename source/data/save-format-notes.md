# Save format evidence and limits

The reader opens saves read-only and accepts only known layout versions. It checks slot checksums, scalar bounds, UTF-16 names and variable-section sizes before importing a snapshot. Unknown versions or malformed data must preserve the last accepted progress, not manufacture an empty run.

## Profile summary checksum

The PC `USER_DATA_10` checksum occupies `[0x19003A0, 0x19003B0)`. It is MD5 of the entire `0x60000`-byte payload `[0x19003B0, 0x19603B0)`, including its padding. Profile occupancy and playtime are accepted only after this checksum passes. [ER-Save-Lib's container](https://github.com/ClayAmore/ER-Save-Lib/blob/master/src/save/save.rs) defines the PC section size as `0x60010`; [UserData10 serialization](https://github.com/ClayAmore/ER-Save-Lib/blob/master/src/save/user_data_10.rs) calls the [checksum helper](https://github.com/ClayAmore/ER-Save-Lib/blob/master/src/save/util.rs), which hashes the complete section after its 16-byte prefix. These boundaries also matched the existing local save and backup during read-only validation.

## Journey

The zero-based clear count is a little-endian `u32` immediately after the dynamically parsed regions section, Torrent (40 bytes), control byte (1 byte), and BloodStain (68 bytes). Its position is `regions_end + 0x6D`; the displayed journey is `clear_count + 1`.

Independent checks:

- [ER-Save-Lib UserDataX](https://github.com/ClayAmore/ER-Save-Lib/blob/master/src/save/user_data_x.rs) places `unk_gamedataman_0x120_or_gamedataman_0x130` directly after BloodStain.
- [SaveForge parser](https://github.com/oisis/EldenRing-SaveForge/blob/main/backend/core/structures.go) reads `ClearCountOffset`, computed from the end of regions plus `DynHorse + DynClearCount`; its [constants](https://github.com/oisis/EldenRing-SaveForge/blob/main/backend/core/offset_defs.go) are `0x29 + 0x44`.
- [fromsoftware-rs GameDataMan](https://github.com/vswarte/fromsoftware-rs/blob/main/crates/eldenring/src/cs/game_data_man.rs) identifies the runtime field at `0x120` as `ng_lvl`.

Our limit of 10,000 is a defensive plausibility check, not a claimed game limit. We preserve the raw counter without SaveForge's editor clamp at 7. The Lap flags 50–58 are not used as an unbounded journey counter. Synthetic tests cover later journeys; a full in-game NG+ transition was not performed during development.

## Character fields and identity

`originId` is the byte at PlayerGameData `+0xB7`; `startingGift` is the creation-gift byte at `+0xBB`. The [ER-Save-Lib structure](https://github.com/ClayAmore/ER-Save-Lib/blob/master/src/save/user_data_x.rs) documents their positions. [Save Manager's class table](https://github.com/Hapfel1/er-save-manager/blob/main/src/er_save_manager/data/starting_classes.py) confirms IDs 6/7/8 mean Confessor/Samurai/Prisoner and 10/11 mean Idus Knight/Heavy Knight. The latter classes were added in [official patch 1.17](https://en.bandainamcoent.eu/elden-ring/news/elden-ring-patch-notes-version-117). Other unknown class IDs remain “Unknown”.

No verified persistent character GUID is exposed. Name, slot, class and gift are supporting evidence, not globally unique identity; external editors can alter them. Header random bytes and the changing PlayerGameDataHash must not be treated as character IDs. A restored save can resemble a replacement or progress reset. The tracker must isolate counters on a detected discontinuity and retain prior data, without claiming it can distinguish every such case. Boss completion always comes from the accepted character's current event flags, never from the planned boss order or a union across saves.
