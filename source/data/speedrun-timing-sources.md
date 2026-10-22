# Timing references

Reviewed 2026-10-22. Rules and accepted versions can change; review the selected
category before recording or submitting a run.

- [Elden Ring game/category rules](https://www.speedrun.com/eldenring?h=all-remembrances-glitchless&rules=game&x=jdzzjjrd-r8rrz7r8.12vwdg4q): current PC guidance requires LiveSplit, active SoulSplitter and Game Time, with LiveSplit visible in the recording. Category endpoints and crash acceptance need the current rules and original recording. The overlay adds no Escape-menu timing rule.
- [SoulSplitter Elden Ring setup](https://github.com/FrankvdStam/SoulSplitter/wiki/Elden-Ring) and [project](https://github.com/FrankvdStam/SoulSplitter): accepted timing belongs to the configured external autosplitter, not saved profile playtime or a homemade load detector.
- [LiveSplit TCP server](https://github.com/LiveSplit/LiveSplit#the-livesplit-server) and [command implementation](https://github.com/LiveSplit/LiveSplit/blob/master/src/LiveSplit.Core/Server/CommandServer.cs): local read-only newline protocol. The client restricts itself to 127.0.0.1 and query commands. `getcurrentgametime` can fall back to real time when game time is uninitialized. `autosplitteractivated` does not identify which autosplitter is active. Therefore a successful connection cannot certify mIGT or SoulSplitter. `getcategoryname` returns the base category; `getcategoryvariables` supplies the declared subcategory variables. Neither proves gameplay compliance.

## Automatic start and menu behavior

The current [SoulSplitter Elden Ring implementation](https://github.com/FrankvdStam/SoulSplitter/blob/main/src/SoulSplitter/Splitters/EldenRingSplitter.cs)
waits for new-character game time greater than zero and less than 150 ms when
**Start automatically** is enabled. It resets that clock, starts LiveSplit and
begins autosplitting. This identifies the first advance of the new character's
game clock; it does not establish a timing trigger at the beginning of class
selection or character customization. Configure automatic start in SoulSplitter.
The companion sends no start, reset, pause or split commands.

While running, SoulSplitter supplies Game Time and suppresses qualifying small
black-screen increments. The companion mirrors the received time without
extrapolating. Pressing Escape does not independently pause this companion.
Loading, main-menu breaks and other menu behavior must follow the configured
external timer and current rules. A flat clock alone cannot identify which menu
is open. A missing game process means it ended; the companion cannot distinguish
a crash from a normal quit. It records the coverage gap for review and does not
pause, restart or resume the external timer.

## Local recording boundaries

Only Speedrun view collects run observations. Leaving it closes an unfinished
local observation as interrupted, freezes its final counts and marks the gap
for review. Returning to Speedrun view cannot make that same character's
interrupted observation clean or resume its recording. Existing completed and
eligible partial reports remain exportable; changing views does not erase them.
The app must witness a newly created save slot while tracking is enabled to
admit a new character. Existing characters and new journeys do not satisfy that
local fresh-character requirement. This is an additional evidence safeguard,
not a claim that a locally eligible run is accepted by moderators.

## Category objective lineups

Category routes are suggested boss objectives, not mandatory order, automatic
splits, or a complete list of quest, item and NPC requirements. Already defeated
encounters are filtered using the active character and journey. Custom routes
remain available outside Speedrun view and for a custom category.

- [Any% Glitchless](https://www.speedrun.com/eldenring?h=Any-glitchless&rules=category&x=02qr00pk-7891zr5n.qj740p3q): suggests Godrick and Rennala for two Great Runes, then the capital and ending path. The endpoint requires credits, not simply Elden Beast's defeat.
- [All Remembrances (No DLC), Glitchless](https://www.speedrun.com/eldenring?h=All_Remembrances-glitchless&rules=category&x=824833gk-0nwp51r8.lr30pgml): lists the 15 base-game Remembrance bosses and suggested access encounters; required collections and the ending remain part of the rules.
- [All Remembrances, Glitchless](https://www.speedrun.com/eldenring?h=all-remembrances-glitchless&rules=category&x=jdzzjjrd-r8rrz7r8.12vwdg4q): includes 25 base-game/DLC Remembrance bosses, Heart of Bayle and suggested access encounters. The lineup does not itself establish completion.
- [Defeat Consort, Glitchless](https://www.speedrun.com/eldenring?h=defeat-consort-glitchless&page=2&rules=category&x=jdr4mmn2-38d90pel.lx58pm41): uses a fresh character, includes Radahn/Mohg access and the DLC objective path, and requires the Circlet of Light collection followed by the specified main-menu quitout. Consort's defeat alone is not the endpoint.
- [Publisher DLC access guide](https://en.bandainamcoent.eu/elden-ring/news/elden-ring-how-enter-the-realm-of-shadow): Starscourge Radahn and Mohg, Lord of Blood are required to access the Realm of Shadow. Alternative legal access routes and category-specific restrictions still apply.

## Attempt measurements and integrity limits

Boss-attempt duration is a separate observed health-bar statistic. It includes
sample timing uncertainty and saved-result delay; it is not an official split.
Personal benchmarks exclude partial, ambiguous and interrupted observations.
No public record time or 15-minute historical limit is assumed. Longer attempts
retain their full duration.

Local integrity checks can flag evidence gaps or inconsistent observations. They
cannot prevent a modified local client/save/timer or substitute for moderator
review. Reports distinguish ineligible observations from cheating allegations.
