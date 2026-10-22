# Tarnished Companion

Automatic eliminations record regular hostile-enemy deaths observed while the supported offline live reader is connected. Loaded NPC health and death/reward flags are checked even without a visible health bar. Boss encounters, players, friendly NPCs, summons and objects are excluded. A disappearing NPC does not count. Respawned enemies can count again after another confirmed death.

Totals are saved separately for each character and journey and survive app restarts. Legacy manual counts are never imported. Past kills and deaths missed while tracking was unavailable cannot be reconstructed. Ally or environmental enemy deaths can count; this does not identify the player's killing blow. Open info for tracking and storage status.

A standalone Elden Ring progress tracker with a translucent OBS overlay and a personal desktop overlay. It shows the current boss (or character stats when idle), progress, deaths, and an icon-only upcoming boss lineup. Uses local portrait artwork and makes installed expansion encounters available automatically.

## Quick start

1. On Windows, run `TarnishedCompanion-Setup.exe`, then open the installed **Tarnished Companion** shortcut. The installer includes automatic offline launch support, shortcuts, an uninstaller, and automatic WebView2 setup when needed. The portable `TarnishedCompanion.exe` also works.
2. The companion opens the **preview walkthrough** first. It also finds Elden Ring, opens Steam if needed, starts the supported game in offline mode, and opens your personal overlay automatically. Load your character as usual. Saved characters connect automatically, including a first save created after startup. Steam and Elden Ring must already be installed; Steam may ask you to sign in. The walkthrough's **Back to app** link opens settings whenever you need them.
3. For streaming, add an OBS Browser Source at `http://127.0.0.1:18473/overlay` with a 360 × 1200 canvas to fit the speedrun split list. Unused space is transparent. Use OBS **Interact** to click overlay controls, or use the dashboard.
4. The personal overlay opens automatically with game startup. **Open Personal Overlay** reopens it if closed. It shows the same overlay in a frameless, transparent, always-on-top window. Drag it anywhere on screen; press **Alt+F4** to close.
5. At the bottom of the dashboard, use **Overlay appearance** to adjust font, width, opacity, icon count, boss combat icons, and the animated red fight frame. The portrait card places counters and encounter details above one compact strip of upcoming boss icons. Reduced-motion preferences disable the pulse.
6. Use the top-right **sword** for combat statistics or **timer** for speedrun statistics. The active button becomes **Home**. These views stay synchronized between the desktop and OBS; the dashboard also has a view selector. Small, borderless **info** controls reveal setup and reference details.

For a visual tour, open [the local preview walkthrough](http://127.0.0.1:18473/preview) while the app is running. One enlarged overlay sits beside visible scene explanations and numbered things to look for. Use Previous/Next, step dots, arrow keys or a horizontal swipe. Each scene can be revisited through its link. All characters, fights and timers are **simulated**; nothing in the walkthrough changes your records. Its signed, encrypted sample uses an ephemeral, untrusted signer and cannot represent a real run.

No Vortex installation or Twitch login is needed. The save is read locally and is never uploaded. Run reports contain selected observations that you choose to export and submit. Eliminations are automatic; no manual counter controls are available. Current boss identification is automatic only: there is no manual boss selector, Set fight or Clear control. Live detection is limited to supported game builds in an offline session with Easy Anti-Cheat absent. Save progress remains available when live detection is unavailable.

The installer checks Microsoft Edge WebView2 Runtime and installs it automatically if missing, using Microsoft's included bootstrapper. That prerequisite installation needs internet. The portable executable expects the Runtime already installed. The startup panel explains any blocked session; an already-running protected game is never stopped or replaced. See [installer and automatic startup details](source/installer/README.md).

## Installed content and lineup presets

The tracker checks local installed-content evidence automatically. When Shadow of the Erdtree is detected, its encounters and categories become available. There is no force-enable override. **Character & tracking → info → Rescan installed content** reruns the check without erasing saved lineup preferences.

The ordinary preset list contains exactly **Major bosses**, **Major bosses + Optional**, **Optional**, and **All encounters**.

With the expansion detected, the six choices are **Major bosses**, **Major bosses + DLC**, **DLC main route**, **DLC all encounters**, **Major + optional + DLC**, and **All encounters**.

These are suggested personal queues. Search, area filtering, defeated-state filtering and, when applicable, content filtering help you find encounters. Speedrun category routes are managed separately.

## Characters, journeys, and boss order

Boss completion is read from the selected character's current save flags. Defeating a boss anywhere in the catalog updates progress; the lineup is only your preferred upcoming order. You can search all encounters, see defeated status and location, and add, remove or reorder your lineup. Unsaved edits survive dashboard refreshes.

The saved journey counter identifies Journey 1, Journey 2 and later runs. A new journey loads its own boss progress and keeps your lineup preference. Bosses already defeated in that journey remain correctly marked. Switching characters restores their separate tracking contexts. Character playtime and deaths are that character's saved totals; playtime is never summed across slots or increased by app uptime.

With multiple characters, choose the character at startup. The tracker follows a single character whose saved playtime advances; switches therefore appear after the game saves. Live boss HP comes from the game, but the live reader does not verify character identity. Keep the selected character correct until a save confirms a switch. Repeated boss names are not assigned to a location based on lineup order.

Renaming a character preserves its local tracking. Observed slot reuse, changed creation metadata, or backwards progress starts fresh local counters and retains previous contexts in settings. Saves expose no verified immutable character ID, so an imported replacement with indistinguishable metadata cannot always be detected. **Start fresh tracking for this character** resets local counters and lineup when needed; actual boss completion is reread from the save, which is never modified.

## Boss combat icons

During a fight, the panel shows **Deals** (physical and elemental attack types), **Inflicts** (status effects), and **Weak to** (the lowest damage negation in the reference table). A relative weakness is not a promise of bonus damage: other defenses, terrain, buffs and individual moves affect the result. Bleed and frostbite are status effects, not elemental damage types. Four tied physical damage categories use one Physical icon.

These are bundled offline reference facts, not resistance readings from game memory. Named phase changes can select their own verified reference. Cycling stances and terrain effects cannot be detected from a health bar; those use an encounter reference with a note. Duplicate boss names only share fields that agree across their verified encounters. Missing data is shown as **Unverified**, and equal damage negations as **No clear weakness**.

Use **Show boss damage and weakness icons** in Overlay appearance to hide this section. Open its **info** control for the icon legend and weakness guide; this also works for the desktop overlay, where browser hover tooltips are unavailable. Data sources and coverage are documented in `source/data/boss-combat-sources.md`. No network access is needed while playing.

## Combat and speedrun views

The sword view estimates damage taken from consecutive live health-bar samples. It prioritizes the current boss and otherwise follows a visible enemy target. Ordinary enemies do not start boss timers or alter the boss lineup. Initial damage before a health bar appears cannot be reconstructed. It shows rolling five-second DPS, average DPS, observed HP loss, largest sampled HP drop, and observed fight duration. Damage includes summons, other players and status effects; the reader cannot attribute it to the player alone or identify individual hits. Healing is not counted as damage. Missing samples, a new health bar/phase, or a character change restart the observation. Brief HUD gaps of up to two seconds keep the same target observation; longer gaps start fresh measurements. When a target disappears, the last result remains visibly paused until the next target or a reader/character change. This view requires the existing supported offline live reader.

The timer view uses a read-only **LiveSplit + SoulSplitter** connection. Select your category in the dashboard before the run; the selection saves automatically. A custom name saves when you finish editing it. Configure the same category in LiveSplit, activate SoulSplitter with **Start automatically**, choose **Game Time**, and use **Control → Start TCP Server** (normally port 16834). The overlay follows its start, time, pause, reset and finish without sending timer-control commands. SoulSplitter starts on the first advance of the new character's game clock, not when you begin browsing character-creation options. No Escape-key pause is added: opening a menu must follow the accepted timer's behavior. Keep LiveSplit visible in the recording and check your category's [current rules](https://www.speedrun.com/eldenring?rules=game).

**Only Speedrun view records run times and boss attempts.** Home and combat views display information without adding timing history. Leaving Speedrun view closes an unfinished local observation as interrupted; returning cannot resume it as a clean recording on that character. Existing eligible completed or partial reports remain available. View changes never control LiveSplit.

In Speedrun view, the selected preset supplies a category boss lineup and filters encounters already defeated by the active character. Any% suggests a Godrick/Rennala route; the Remembrance presets include their base-game or base-game/DLC objectives; Defeat Consort includes Radahn and Mohg for DLC access. These are suggested routes, not mandatory boss orders or complete quest/item instructions. Category endpoints still follow the rules. Home and custom categories retain your personal lineup.

The overlay cannot verify SoulSplitter identity or whether LiveSplit has initialized its game-time clock through this protocol. It is a supplementary display, not a replacement for the required timer or an eligibility certificate. A lost connection hides current time; recovery reads the external clock again without inventing missing time. A game-process exit is logged as quit/crash unknown. The tracker cannot decide whether a crash is acceptable under a category's rules.

Saved character playtime remains a separate statistic and refreshes after a game save. A flat external clock does not reveal whether a particular menu or loading screen is open; the companion never fills missing samples with a homemade timer.

### New-character recording lock and tamper evidence

Choose a category and keep **Speedrun view** selected **before creating the character**, with the tracker and game running. The tracker must observe an absent save slot become occupied during the current session, then a fresh Journey 1 save with no deaths or defeated bosses and at most 30 saved seconds. It also needs a matching automatic LiveSplit start. Late save binding is accepted only within 30 seconds of an already-observed timer start and is marked for review. Loading an existing save, prepared DLC character, starting NG+, restarting the tracker or resetting LiveSplit cannot unlock a new recording. Progress/HP can still be displayed on an existing character, but a new run cannot be recorded or exported without the required start evidence.

The DLC **Defeat Consort** preset begins from a fresh character under the global rules; simply entering the Realm of Shadow is not treated as a new official start. The overlay knows DLC encounters from its catalog, but does not claim to detect a region-entry timing boundary. Category/subcategory metadata is checked against LiveSplit and included in reports. It remains declared metadata, not proof that the game followed those rules.

Protected local records use a signed manifest, and the signing key is protected with Windows current-user DPAPI. Changed, missing or injected records block signed exports and recording. Saved-progress rollback, a character/journey switch, or a backwards external timer makes the local run ineligible; uncertain timing or process interruptions require review. These findings apply to the recorded attempt, not an accusation against a player. Unsigned history from older versions is preserved in `legacy-unsigned` and is not adopted as trusted timing.

### Closing and recovering the app

At the bottom of the dashboard, open **info → Quit app** for an intentional shutdown. A clean quit closes any unfinished observation; reopening cannot turn it into a new clean run on the same character. Closing only the dashboard tab or personal overlay window leaves the tracker and OBS source running.

The launcher watches its own app worker and restarts it after an unexpected exit, with a limit of **three restarts in 120 seconds**. It does not install a startup service, recover a stopped supervisor, or guarantee recovery after a PC shutdown. A valid signed checkpoint can restore the last committed local record after an unclean exit; uncommitted data is preserved separately. Missing observations are never reconstructed. Restored coverage gaps remain marked for review, and external time is read again from LiveSplit. Game crashes and app crashes are separate events; a missing game process does not reveal why it ended.

### Encrypted run reports and saved builds

**Export run .tlrun** downloads a signed, encrypted package. The app does not offer a plaintext TXT export or an unencrypted fallback. Export remains unavailable until a valid verifier recipient public key is configured and the run meets the local export requirements.

The report contains category/timer metadata, character/journey, observed splits, per-boss attempt counts and durations/outcomes, review notes, application hash and signing-key fingerprint. It also includes the observed character build: level, class, eight base attributes, six weapon slots, four armor slots and four talismans where the reader can verify them.

Build snapshots come from the same checksum-validated selected-character save as progress. Initial/final builds and a bounded change history are signed with the run. History is limited to **512 observations or 512 KiB**, whichever comes first; it retains the first and newest observations and marks truncation. These are **last-saved loadouts**, not every live quick swap, temporary buff, damage multiplier or resistance. Observation timestamps record when the tracker read the save, not the exact equipment-change time. Unknown IDs retain an unavailable name rather than a guess. The build does not copy the complete inventory, unrelated characters, Steam identifiers or multiplayer passwords. Sources are in [equipment-catalog-sources.md](source/data/equipment-catalog-sources.md).

Finished reports freeze the observation window and exclude later attempts. The desktop overlay opens Save As; a browser or OBS Interact downloads the package. Oversized packages fail with an error rather than silently dropping other records.

The structured payload is signed with Ed25519 and encrypted for the verifier using X25519/HKDF-SHA256/AES-256-GCM. The client accepts only the public recipient configuration at **source/data/report-recipient.json**, which must be included when building the Windows executable. The matching private recipient key belongs only on the verifier/bot host and must never enter the client ZIP or public repository.

### Community report verification

The Discord verifier/bot is included as source. This package does not imply an already deployed service. Its administrator must configure hosting, credentials, recipient keys and independent signer enrollment. See [bot/README.md](bot/README.md) for provisioning and the CLI.

Use supported Node.js **22 or 24**, preferably the current LTS release. Node.js 19 is end-of-life; see the [official release status](https://nodejs.org/en/about/previous-releases). The bot distribution supplies a pinned local Node.js 24.22.1 runtime dependency and bootstrap for older panel launchers. Its npm installation scripts must be enabled so that runtime is installed; the bot process then uses the supported local runtime instead of Node 19. See the bot guide for the exact startup command.

After configuring the verifier, an authorized operator can decrypt and verify a package:

~~~powershell
node bot/cli.js verify report.tlrun --key "C:\PrivateVerifier\recipient-key.json" --trusted-fingerprint "INDEPENDENTLY_CONFIRMED_SIGNER_FINGERPRINT"
~~~

The server can bind an independently enrolled signing fingerprint to a Discord account, check the package and provide readable timing/build details for community review. A valid self-signed report is not automatically trusted. Simulations, malformed reports and partial/interrupted observations cannot become complete submissions. A receipt is **not official leaderboard approval**, proof of honest gameplay or proof of an unmodified client. Original recordings and the category's review process still matter.

The signing fingerprint shown in the dashboard must be exchanged independently before reports are trusted. Keep exported package bytes unchanged. **source/verify_report.py** verifies legacy/internal signed TXT envelopes; it is not the .tlrun decryption CLI and is no longer the normal export workflow. Old unsigned history remains a reference archive, not trusted timing evidence.

### Boss attempts and the 15-minute bar

Automatic attempts require active Speedrun recording, the supported live health-bar reader and a valid active-character save. The timer begins on an observed encounter, keeps a known multi-phase encounter together, and resets for the next attempt after a saved death. Results are confirmed from saved deaths/defeats; a missing health bar, zero HP or closed game alone is not treated as a victory. Interrupted, ambiguous and partial observations are retained with their limits. There are no manual encounter controls.

The fixed bar runs from **0 to 15 minutes**: green to the personal best, yellow to the near-best average, orange to the overall average, then red. Near-best means the fastest quarter of confirmed complete observations, with at least two samples. The timer and export continue beyond 15 minutes while the marker stays at the end. Without reliable history the bar stays neutral; targets are never invented. Benchmarks use the same exact boss, journey number and selected category across local characters/runs. A benchmark needs an observed full start and final zero-HP endpoint plus saved victory confirmation.

A separate **Published category times** bar compares the total run clock with the supported published PC category. Its scale adapts to the category duration. Open its borderless info control for the source, last successful check, refresh attempt and whether values are cached. A cached snapshot is not labelled current. Whole-run records never replace personal boss-fight targets, and an unfinished time below a final record is not an ahead/behind split comparison. Walkthrough record data is explicitly simulated.

The app and bot refresh supported PC Glitchless leaderboards every 15 minutes. Results appear after moderator acceptance; a newly uploaded pending run is not yet a published record. Whole-run averages describe up to 20 returned results. Discord boss averages use observed complete victories from other submitted reports, show their sample count and remain unreviewed. Source coverage and timing details are in [the record source notes](source/data/published-records-sources.md).

Use **Export run .tlrun** for the encrypted timing and saved-build report described above. Personal records, signing keys, recovery checkpoints and supervisor/session markers remain in local app data and are excluded from the distribution ZIP.

See `source/data/speedrun-timing-sources.md` for timing references and the protocol's limitations.

## Updates and checks

Save checksums and bounded parsing reject partial, corrupt, or unsupported snapshots. The overlay displays a paused/disconnected status instead of claiming current progress; reading resumes when valid data returns. Settings are normalized so malformed preferences and obsolete catalog IDs do not crash the app. Optional live detection remains pinned to a verified game build and pauses on unsupported builds. Future game patches may require reader updates; compatibility cannot be guaranteed in advance.

The source includes synthetic regression tests for journeys, out-of-order victories, character isolation, save restoration, parsing failures, draft edits, and overlay recovery. On Windows, run `python -m unittest discover -s source/tests -p "test_*.py"`, `node source/tests/test_overlay.cjs`, and `node source/tests/test_dashboard.cjs`. GitHub Actions runs these checks on pushes and pull requests. The bot has separate checks with **npm --prefix bot test** after its dependencies are installed. No real saves or game installation are needed for the tests. See `source/data/save-format-notes.md` for verified field sources and limitations.

If you have problems contact [Koné Labie](https://discord.com/users/827114107491713025).

See `README.txt` for full setup and troubleshooting, `THIRD-PARTY.txt` for attribution, `source/licenses/` for bundled dependency licenses, and `LICENSE.txt` for the project license.
