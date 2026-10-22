TARNISHED COMPANION — Elden Ring progress + OBS overlay

AUTOMATIC ELIMINATIONS
The Eliminations counter records regular hostile-enemy deaths observed while the supported offline reader is connected. It checks loaded NPC health and death/reward flags even without visible health bars. Bosses, players, allies, summons and objects are excluded. Disappearance is not a death. Respawned enemies can count again after another confirmed death. Totals are saved per character and journey and survive app restarts. Past kills and unobserved deaths cannot be recovered. Legacy manual totals are never imported. Ally or environmental enemy deaths can count; this does not identify the player's killing blow. Open info for tracking and storage status.

QUICK START
1. Run TarnishedCompanion-Setup.exe, then open the installed Tarnished Companion shortcut. The installer includes automatic offline launch support and WebView2 setup when needed. The portable TarnishedCompanion.exe also works.
2. The preview walkthrough opens first. The companion finds Elden Ring, opens Steam if needed, and starts the offline game and your personal overlay automatically. Load your character as usual; its save connects automatically. Steam and Elden Ring must already be installed. Steam may require its normal sign-in. Back to app opens settings whenever needed.
3. Choose a boss lineup and arrange its order. Available encounters and presets follow detected installed content automatically.
4. Add an OBS Browser Source using http://127.0.0.1:18473/overlay. Set its canvas to 360 × 1200 to fit speedrun splits. Unused space is transparent. Use OBS Interact to click controls, or use the dashboard.
5. Keep the tracker running while OBS uses the overlay. At the bottom of the dashboard, open info > Quit app for an intentional shutdown. Closing only the dashboard tab or personal overlay window leaves the tracker running.

Open http://127.0.0.1:18473/preview while the app runs to see the preview walkthrough.
The walkthrough shows one enlarged overlay with visible explanations and numbered
details to look for. Use Previous/Next, the step dots, arrow keys or a swipe.
Scene links let you revisit any example. Characters, fights and times are simulated.
The signed/encrypted sample uses an ephemeral, untrusted preview signer; it cannot
represent a real run and never reads or changes your character records.
Small borderless info controls reveal help, reference details and timing setup.

HOW IT WORKS
The overlay shows the character name (toggleable), total boss progress and deaths. It shows the current boss during a fight; otherwise it shows level, starting class, runes and play time. The next bosses appear together in one compact portrait strip; use Overlay appearance at the bottom of the dashboard to show 4, 6 or 8. The panel background is translucent. In Overlay appearance, choose Cinzel, Georgia or System, set width and background opacity, then click Apply layout. The tracker is a standalone companion app. It is not an Elden Ring mod and does not need Vortex. It reads the selected PC save file read-only; boss progress updates after the game saves. It never uploads the save. Run reports contain selected observations that you choose to export and submit. Boss pictures are bundled locally.

The overlay stacks the character name and three counters (Bosses, Eliminations and Deaths), current fight or character stats, and an icon-only upcoming strip. During a fight, the large portrait sits beside the top-aligned boss name and health bar. A larger fight timer, character level, and runes held sit below. HP is shown only when the live reader supplies valid values. Current encounters are automatic only; there is no manual boss selector, Set fight or Clear control. The live reader runs only after verifying a supported game executable and confirming Easy Anti-Cheat is absent. Use an offline single-player session with EAC disabled. Unsupported game builds leave save-based progress available. No game files are patched and no code is injected.

Character playtime is read from one character's saved profile, never summed across slots or extended by app uptime. With multiple characters, the tracker follows a single profile whose saved playtime advances. Until a save identifies the character, or if multiple profiles change at once, it keeps the selected character. Use the Character dropdown to select explicitly. Switching characters clears the current fight and loads that character's own route and progress.

OBS / TWITCH
The overlay is a local OBS browser page, so no Twitch OAuth, bot, or channel-points integration is needed for the progress display. In OBS, add a Browser Source and use the URL above. This is the part that puts the tracker on a Twitch stream. Twitch chat interaction is not included. The manual enemy-kill counter and its editing controls have been removed.

SAVE LOCATION
Steam and Seamless Co-op saves are usually under %APPDATA%\EldenRing\<long-number>\ER0000.sl2 or ER0000.co2. The dashboard can find them automatically, or use Browse. Back up saves normally before playing; this program only reads them.

TROUBLESHOOTING
- If the dashboard does not open, visit http://127.0.0.1:18473/ while the app runs. Port 18473 may be occupied; close another copy first.
- If the automatic save list is empty, click Browse and select ER0000.sl2 (or a Seamless Co-op .co2 file).
- If progress looks stale, wait for an in-game save or press “Refresh save.”
- Boss portraits are bundled; a few duplicate or paired encounters share related artwork. Missing encounter identity is not guessed from a picture.
- If automatic fight detection is unavailable, open its info status and check the supported offline game build. Save-based progress remains available.

See THIRD-PARTY.txt for code, data and image attribution. See LICENSE.txt for the GPL-3.0-or-later license.

PERSONAL OVERLAY
The personal overlay opens automatically with game startup. Open Personal Overlay in the dashboard reopens it if closed. It shows the same /overlay page in a frameless, transparent, always-on-top desktop window. The window fits the visible panel automatically, including when the lineup gets shorter. Empty space is transparent; text and portraits stay opaque. Drag anywhere on the panel to move it; press Alt+F4 to close. The installer supplies Microsoft WebView2 setup automatically if needed; that prerequisite needs internet. Borderless or windowed game mode is recommended; exclusive fullscreen may cover desktop overlays. See source/installer/README.md for launch, troubleshooting and build details.


INSTALLED CONTENT AND PRESETS
Installed-content evidence is checked automatically. Detected Shadow of the
Erdtree content enables its encounters and categories. There is no force-enable
override. To check again, use Character & tracking > info > Rescan installed
content. Rescanning keeps saved lineup preferences.

The ordinary four presets are:
- Major bosses
- Major bosses + Optional
- Optional
- All encounters

With the expansion detected, the six presets are:
- Major bosses
- Major bosses + DLC
- DLC main route
- DLC all encounters
- Major + optional + DLC
- All encounters

Search, area and defeated-state filters help build a queue. A content filter is
available when applicable. These are personal suggested queues; speedrun
category lineups are managed separately.

CHARACTERS, JOURNEYS, AND ORDER
Boss completion comes from the current character and journey's saved event flags, never lineup order. A defeat outside your queue still counts, and any defeated queue entry is skipped. The full-catalog editor shows saved defeated status and location; you can add, remove, and reorder encounters. Draft edits survive polling until you save/revert or change character/journey.

The save's actual journey counter selects a separate tracking context for Journey 1, Journey 2 and later runs. Starting a new journey loads its own boss progress and keeps your lineup preference. Bosses already defeated in the new journey stay marked. Deaths and playtime remain the character's saved totals. Switching characters restores each character's own context.

The save exposes no verified immutable character ID. Renaming preserves tracking. Observed slot reuse, changed creation metadata, or backwards playtime/progress starts fresh local tracking and retains old contexts in settings. Some imported replacements may be indistinguishable. Use Start fresh tracking for this character to reset the local lineup if needed; actual defeated bosses are always reread from the untouched game save.

Live boss HP and saved character progress are separate sources. With multiple characters, choose your character until its next save confirms a switch. Ambiguous boss names are never assigned to arenas from queue order.

RED FIGHT FRAME AND RECOVERY
The current portrait has a red frame with an optional animated glow. Overlay appearance lets you disable the animation, and reduced-motion system/browser settings also disable it. The desktop capture increases to approximately 15 FPS while the glow is active and slows to 2 FPS when idle.

The overlay marks save problems and connection loss. Checksum validation, bounded parsing and settings normalization guard against partial writes, malformed preferences and unsupported layouts. Valid data is retried automatically. Future game patches may still require a reader update; unsupported live game builds pause detection.

Developer regression checks and verified format sources are included in source/tests and source/data/save-format-notes.md. GitHub Actions runs the synthetic tests on Windows after the project is uploaded. Tests do not use real save files.

BOSS DAMAGE AND WEAKNESS ICONS
The current boss shows a compact combat reference below its health bar. Deals means physical/elemental attack damage; Inflicts means status effects such as frostbite or bleed. Weak to means the lowest damage negation compared with that boss's other damage defenses, not a guaranteed damage bonus. Matching physical categories share one Physical icon.

Named phases use their own verified data where available. A health bar cannot identify cycling stances or terrain effects. Unknown references remain Unverified instead of being guessed. Equal negation across all damage types displays No clear weakness. All data is bundled locally, independent of live save and memory readings.

Turn these icons off in Overlay appearance if you prefer. Open its info control in the dashboard for the icon legend and weakness guide. This is particularly useful on the desktop overlay, which does not display browser hover tooltips. See source/data/boss-combat-sources.md for sources, coverage and version notes.

COMBAT AND SPEEDRUN VIEWS
Use the sword or timer icon at the overlay's top right. The active icon becomes
Home; clicking it restores the boss lineup. View changes synchronize across OBS
and the personal overlay. You can also switch views from the dashboard.

Only Speedrun view records run times and boss attempts. Home and combat show
information without adding timing history. Leaving Speedrun view closes an
unfinished observation as interrupted. Returning cannot resume it as a clean
recording on the same character. Existing eligible completed or partial reports
remain available. Changing views never controls LiveSplit.

Sword: rolling five-second and average estimated boss DPS, observed HP loss,
largest sampled HP drop, and observation time. This requires supported live HP
samples. It includes damage from all sources, not player-only damage; sampled HP
drops are not individual hits. The app cannot attribute these measurements to the player alone.

AUTOMATIC RUN TIMING
Select your intended category in the dashboard; it saves automatically. A custom
name saves when you finish editing it. In LiveSplit, configure Elden Ring and that
category, activate SoulSplitter with Start automatically, choose Game Time, and
use Control > Start TCP Server (default 16834). The app reads this local server. It never starts,
pauses, resets, or finishes LiveSplit and never pauses when Escape opens a menu.
SoulSplitter starts when the new character's game clock first advances, not when
you begin browsing character-creation options. Menu/loading behavior follows the
external game-time clock; the companion never invents a pause or missing time.
Keep LiveSplit visible in recordings; check the current category rules:
https://www.speedrun.com/eldenring?rules=game
https://github.com/FrankvdStam/SoulSplitter/wiki/Elden-Ring

A disconnected/stale timer displays unavailable. Recovery uses LiveSplit's current
output. A game-process exit is logged without assuming whether it was a crash or
normal quit. The protocol does not prove SoulSplitter identity or initialized mIGT.
This overlay and its export do not certify leaderboard eligibility.

Speedrun presets supply category boss lineups. Any% suggests Godrick/Rennala for
two Great Runes. Remembrance presets include their base-game or base-game/DLC
objectives. Defeat Consort includes Radahn/Mohg for DLC access. Saved defeats are
filtered for the active character and journey. These are suggested routes, not
mandatory boss orders or all quest/item requirements. Category endpoints follow
the current rules. Home and custom categories retain your personal lineup.

Saved character playtime is separate and only changes after a save. A flat clock
does not establish which menu/loading state is open; no Escape pause is inferred.

APP SHUTDOWN AND RECOVERY
Use info > Quit app at the bottom of the dashboard to close unfinished
observations intentionally. Reopening cannot turn that same character into a
new clean recording. Closing only the dashboard tab or personal overlay leaves
the tracker and OBS source running.

The launcher restarts its own worker after an unexpected exit, limited to three
restarts in 120 seconds. It does not install a startup service or restart a
stopped supervisor, and cannot guarantee recovery after a PC shutdown. After an
unclean exit, a valid signed checkpoint can recover the last committed record;
uncommitted data is preserved separately. Missing observations are not invented.
Recovered gaps remain marked for review; time is read again from LiveSplit.
Game-process exit and app-worker exit are separate events. A missing game process
cannot distinguish a crash from normal quitting.

BOSS ATTEMPTS
Automatic attempts require active Speedrun recording, supported live boss health bars and saved results. Saved
deaths reset the timer for the next attempt. A bar disappearing, zero HP alone, or
a game exit never becomes a guessed victory. Partial/interrupted attempts remain
in the report and do not set benchmark times. Saved results may arrive late.

The bar stays fixed at 0 to 15 minutes: green to best, yellow to near-best average,
orange to overall average, then red. Near-best uses the fastest quarter, minimum
two completions. With no qualifying history the bar is neutral. Time continues
beyond 15 minutes. Benchmarks match exact boss, journey number and chosen category;
they require an observed full start and final zero HP with saved victory.

The separate Published category times bar compares the whole-run clock with a
supported published PC category. Its scale adapts to the category. The info text
shows the source and check/refresh times; cached values are labelled. This does
not substitute full-run records for boss-fight targets or claim an unfinished run
is ahead of a completed record. Preview record data is explicitly simulated.

The app and bot refresh supported PC Glitchless leaderboards every 15 minutes.
New uploads appear after moderator acceptance. Whole-run averages describe up
to 20 returned results; Discord boss averages use complete observed victories
from other submitted reports and show their sample count as unreviewed data.
See source/data/published-records-sources.md for scope and timing details.

Export run .tlrun creates a signed, encrypted timing and saved-build package.
It includes the chosen category, timing source, character/journey, per-boss
attempts, durations/outcomes, observed splits and review notes. Finished reports
exclude later attempts. No plaintext TXT export or unencrypted fallback exists.
See the report section below and source/data/speedrun-timing-sources.md.

NEW-CHARACTER RECORDING LOCK
Choose a category and keep Speedrun view selected before starting. Keep tracker,
game and LiveSplit/SoulSplitter running before creating a new character in an absent save slot. An existing save,
NG+, prepared DLC character or timer reset cannot unlock recording/export. The
fresh save must be observed within 30 seconds, with no deaths/defeated bosses.
Late binding to a previously observed timer start is labeled for review.

SIGNED RECORDS AND ENCRYPTED REPORTS
Stored timing records have a signed manifest. Edited, deleted or injected records
lock recording/export. The local signing key is protected by Windows current-user
DPAPI. Progress rollback, a character/journey switch or backwards external time
can make the local record ineligible. Uncertain observations remain marked for
review. Older unsigned history is kept separately in legacy-unsigned.

Export run .tlrun signs the structured record with Ed25519 and encrypts it for
the verifier using X25519/HKDF-SHA256/AES-256-GCM. The recipient PUBLIC configuration
belongs at source/data/report-recipient.json and must be bundled when building
the Windows executable. The matching PRIVATE key stays only with the verifier/
bot host. Never put it, bot credentials or personal records in the client ZIP.
Export stays unavailable until the recipient public key and run evidence are
valid. There is no unprotected export fallback.

SAVED CHARACTER BUILDS
Reports include level, class, eight base attributes, six weapon slots, four armor
slots and four talismans when the checksum-validated selected-character save
supports them. Unknown item IDs remain unnamed rather than receiving a guess.
Initial/final builds and a bounded change history are signed with the run.
History is capped at 512 observations or 512 KiB, whichever comes first. The
initial and newest observations are retained, and truncation is marked.

These are last-saved loadouts. They do not capture every live quick swap,
temporary buff, damage multiplier or resistance. Timestamps show when the app
read a saved loadout, not the exact moment of an equipment change. The report
does not include a complete inventory, other characters, Steam identifiers or
multiplayer passwords. The observation window freezes at the recorded endpoint.
Oversized exports fail explicitly instead of silently dropping other records.
See source/data/equipment-catalog-sources.md for names, field sources and limits.

COMMUNITY VERIFIER / DISCORD BOT
The bot is supplied as source code. This package does not mean a service is
already deployed. The administrator must configure hosting, bot credentials,
recipient keys and independent signer enrollment. Read bot/README.md.

Use supported Node.js 22 or 24, preferably the current LTS release. Node.js 19
is end-of-life: https://nodejs.org/en/about/previous-releases
The bot includes a pinned local Node.js 24.22.1 runtime dependency and bootstrap
for an older panel launcher. Enable npm installation scripts so that local
runtime is installed; the bot process then runs on supported Node instead of 19.
The bot guide describes its exact startup command.

Once verifier configuration is ready, an authorized operator can check a package:
node bot/cli.js verify report.tlrun --key "C:\PrivateVerifier\recipient-key.json" --trusted-fingerprint "INDEPENDENTLY_CONFIRMED_SIGNER_FINGERPRINT"

The recipient private key is required to decrypt. An independently enrolled
signer fingerprint can be bound to a Discord account. A self-signed report is not
automatically trusted. The server checks the package and supplies readable
timing/build details for community review; simulations and incomplete records
cannot become complete submissions.

A receipt is not official leaderboard approval or proof of honest gameplay,
category compliance or an unmodified app. Original recordings and the category
review process remain necessary. Keep the .tlrun bytes unchanged.

source/verify_report.py checks legacy/internal signed TXT envelopes. It is not
the .tlrun decryption tool and is no longer the normal export workflow.
Personal saves, signing keys, reports, recovery checkpoints and host credentials
must remain outside public repositories and distribution ZIPs.

If you have problems contact Koné Labie:
https://discord.com/users/827114107491713025

COMBAT STATISTICS
The sword view prioritizes a detected boss, then follows a visible enemy target. DPS uses consecutive observed health samples and includes all damage sources. Damage dealt before the target health bar appears cannot be reconstructed. Changing targets, losing live data, or starting another phase resets measurements. Current live-reader status appears in the combat view while measurements are unavailable.
