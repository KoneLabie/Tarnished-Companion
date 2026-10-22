# Public leaderboard records

The app and Discord bot read public, moderator-accepted Speedrun.com results. Pending uploads do not count until accepted and visible on the leaderboard. Supported mappings were verified against the live API on 22 October 2026. No current record is hardcoded or bundled.

## Coverage and timing

All four mappings use Elden Ring (`nd28z0ed`), PC (`8gej2n93`), and the Glitchless subcategory. Accepted versions, routes and FPS patch settings are combined, as they are on these published boards. These are complete-run results; comparisons must preserve this scope.

| Local category | API category | Subcategory variable | Glitchless value |
| --- | --- | --- | --- |
| any-percent-glitchless | 02qr00pk | 7891zr5n | qj740p3q |
| all-remembrances-no-dlc-glitchless | 824833gk | 0nwp51r8 | lr30pgml |
| all-remembrances-glitchless | jdzzjjrd | r8rrz7r8 | 12vwdg4q |
| defeat-consort-glitchless | jdr4mmn2 | 38d90pel | lx58pm41 |

API URL shape: `https://www.speedrun.com/api/v1/leaderboards/nd28z0ed/category/CATEGORY?platform=8gej2n93&timing=realtime&var-VARIABLE=VALUE&top=20&embed=players`.

The API declares `realtime` and publishes the leaderboard value in `times.primary_t` (equal to `realtime_t`). The PC game rules require LiveSplit with SoulSplitter and the Game Time/mIGT display. Accordingly the app labels this **Published PC category time**, with timing key `pc-soulsplitter-game-time`. It does not convert these values or use the API's empty `ingame_t` value. Comparisons to a local timer require matching timing semantics. This feed does not verify a local run or make it an official submission.

The checked game-levels endpoint returned no levels, and every run in the four matching PC leaderboards had `splits: null`. This feed therefore supplies **no official per-boss duration or split records** (`bossTimesAvailable: false`). Keep complete-run benchmarks separate from personal boss fight observations and separately labelled community reports.

## Refresh and failures

Clients cache successful results for 15 minutes, including across restarts. Callers schedule refreshes; constructors and snapshots never perform network requests. Explicit refresh and retries still have a minimum 60-second interval per category. Each network operation has a five-second budget and accepts bounded JSON only from official HTTPS API addresses. Results are checked against game, category, PC platform, Glitchless variable, full-game level, accepted status, timing and valid positive numbers before replacing the cache.

Failed refreshes keep previous results marked **stale**, preserve the last successful `checkedAt`, and report a separate `lastAttemptAt`. A valid empty board clears old benchmarks. Unsupported categories and unavailable data have no invented records. Local cache files are an efficiency feature, not an anti-cheat trust anchor.

Samples contain the first 20 validated ranked runs (fewer if the board is smaller). `bestSeconds` is the fastest returned time; `nearBestSeconds` averages the fastest quarter, with at least two results when available; `averageSeconds` averages only that returned sample. These are not averages of all community runs. Category labels and source links remain attached to snapshots.

## Primary sources and attribution

- [Elden Ring leaderboard and current category rules](https://www.speedrun.com/eldenring)
- [Game metadata and API timing configuration](https://www.speedrun.com/api/v1/games/eldenring)
- [Category list and category rules](https://www.speedrun.com/api/v1/games/nd28z0ed/categories)
- [Variables and values](https://www.speedrun.com/api/v1/games/nd28z0ed/variables)
- [Published game levels](https://www.speedrun.com/api/v1/games/nd28z0ed/levels)
- [Official leaderboard API documentation](https://github.com/speedruncomorg/api/blob/master/version1/leaderboards.md)
- [Official runs API documentation: primary timing, status and optional splits](https://github.com/speedruncomorg/api/blob/master/version1/runs.md)
- [API rate limits](https://github.com/speedruncomorg/api/blob/master/throttling.md)
- [Speedrun.com API terms and data attribution](https://github.com/speedruncomorg/api/blob/master/README.md): API data is attributed to Speedrun.com and its contributors under the stated CC-BY-NC 4.0 terms; this is separate from this project's source-code license.

The identical mapping JSON is shipped in `source/data` and `bot/resources`. Mapping IDs must be reviewed if the public category rules or timing system change; unknown data is rejected rather than silently reinterpreted.
