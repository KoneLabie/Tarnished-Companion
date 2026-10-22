# Elimination reader

This original external reader uses the existing read-only process handle. It
does not inject code, install hooks or write to game memory. The executable SHA
in `memory-profile.json` must match before any process reads are allowed.

For the pinned Windows 2.7.2.0 executable, the WorldChrManImp singleton and vtable
were resolved from its registration references and RTTI and validated against a
running offline session on 2026-10-22. The distance-list offset is pinned in the
profile. It is not inferred for unknown builds.

Layout references: [fromsoftware-rs](https://github.com/vswarte/fromsoftware-rs),
WorldChrMan, ChrIns, CSChrDataModule (MIT OR Apache-2.0). Hostile-team IDs reference
the [Elden Ring EMEDF TeamType enum](https://soulsmods.github.io/emedf/er-emedf.html#TeamType).

The reader validates the world vtable, vector bounds, character/data vtables,
data-module ownership and health ranges. Snapshots are capped at 1,024 characters
and individual reads at 4,096 bytes. Friendly teams, players, spirit allies,
objects and unverified character types are excluded. Unloading an object simply
removes its observation.

Counting requires observing a live hostile NPC, then zero health with a death
or death-reward flag. Delayed confirmation is allowed while the same NPC stays
observed. Boss HUD identities stay excluded across phase transitions. Repeated
corpse samples do not increment the counter. New instances, reader reconnects,
character/journey changes and sample gaps above two seconds discard outstanding
observations. Respawned live enemies can be armed for another death.

Only observed deaths are counted. There is no inferred historical total and no
reconstruction from rune gains. Counts are not player-attributed killing blows,
official speedrun evidence or a guarantee that every world death was observed.
