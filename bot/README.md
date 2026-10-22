# Tarnished Lineup Discord verifier

This bot accepts encrypted `.tlrun` exports through `/submit report:<attachment>`. It decrypts the file, verifies its Ed25519 signature, checks the signer against an independently enrolled Discord account, rejects incomplete/ineligible/simulation results, and saves a replay-protected receipt. The private reply includes category, time, observed boss splits and attempts, and available character equipment. The JSON attachment includes the saved-loadout timeline.

The private reply presents a gold-accent report with a section menu: **Run overview**, **Boss times**, **Every attempt**, **Character build**, and **Record comparison**. Long lists paginate eight entries at a time. The boss page keeps encounter duration separate from cumulative run splits, and labels other submitted reports as unreviewed. It shows the submitted best and average fight time with the number of reports: each report contributes its fastest complete, confirmed victory for that boss, so extra attempts do not overweight the average. Comparisons use exact category/timing matches and show the source, scope and successful-check date; missing boss records are not invented from overall leaderboard times. Final published differences require a completed normalized first-journey report using observed LiveSplit Game Time. The Comparison section refreshes its data when revisited and offers **Refresh records**. TXT and JSON receipts remain attached to the message.

Interactive menus are bound to the original submitter, guild and Discord message, and expire after 30 minutes or when the bounded menu cache is full or the service restarts. An open Comparison view can update its published-record bar automatically when the bot's cached record changes. Automatic edits use the current Discord interaction webhook for at most 14 minutes; using the menu again renews that edit window. Expired webhooks stop automatic edits without posting another message. Menu expiration does not delete the receipt or saved report. Do not re-submit an identical run to reopen its menu; the administrator can retrieve its saved receipt. Report observations are calculated from the data, without sending character or run data to an AI provider.

Every accepted report is **review required**, never official leaderboard approval. A signature establishes unchanged bytes and an enrolled signing key. It does not establish unmodified software, legitimate gameplay, precise boss split timing, or compliance with speedrun rules. Preserve the original video and LiveSplit evidence for review.

## Hosting panel setup

1. Upload `index.js`, `cli.js`, `commands.js`, `lib/`, `resources/`, `package.json`, and `package-lock.json`. Tests and this guide may also be included. Do not upload local `node_modules` or `.tools`; install for the host's OS/architecture.
2. Use `index.js` as the start file and allow the panel to run `npm install`. Keep dependency install scripts enabled. Prefer a Node 22 or 24 LTS image.
3. If the panel only offers an old Node image such as Node 19, the pinned `node@24.22.1` package installs a supported runtime. `index.js` launches that local binary before loading Discord. This requires outbound npm access and a supported host platform. Node 19 is used only to bootstrap. Missing/failed runtime installation stops startup rather than running the bot on it.
4. Copy `config.example.json` to **`config.json`** on the host and enter the Discord bot token there. Keep it private; the bot never prints it. Configure a persistent private `dataDir` and the recipient private-key file. Relative paths resolve against `config.json`.
5. Invite the application to the configured server with the `bot` and `applications.commands` scopes. No administrator privilege or privileged Message Content intent is needed. The bot needs access to the channel where the slash command is used and permission to send its response/files.
6. Set `registerCommandsOnStart` to `true` if the panel has no separate CLI. After connecting to Discord, the bot creates/updates `/submit` in the configured guild without deleting unrelated commands. It can remain true. With a shell, `node cli.js register` does the same explicitly.

If Discord reports `50001 Missing Access` or `50013 Missing Permissions`, the bot stays connected and logs that installation/permissions are pending. Authorize it for the configured server with `bot` and `applications.commands` scopes. It retries once automatically when it joins that server, including when the join occurs during the first registration request. If an existing installation's permissions change, restart the bot to retry. Other registration failures are logged without credentials and do not create a retry loop; authentication failure (`401`) still stops the service. A “connected” log confirms login; the separate “command registered” log confirms `/submit` is available.

Example private host configuration (the example IDs are this project's configured application and server; change them for your own bot):

```json
{
  "token": "ENTER_THE_TOKEN_ON_THE_HOST_ONLY",
  "applicationId": "1562709047629586482",
  "guildId": "1365847559754612807",
  "recipientKeyFile": "./private/recipient-key.json",
  "dataDir": "./data",
  "registerCommandsOnStart": true
}
```

Environment overrides: `DISCORD_TOKEN`, `DISCORD_APPLICATION_ID`, `DISCORD_GUILD_ID`, `TARNISHED_RECIPIENT_KEY_FILE`, `TARNISHED_BOT_DATA_DIR`. `TARNISHED_BOT_CONFIG` selects another config path. `.env.example` documents these names; `.env` files are not loaded automatically. On Unix, startup restricts existing config/key files to mode `0600`; storage directories/files are created with private permissions. On Windows, protect their folder using account permissions.

The repository contains no deployment token or private key. Never put either in a release ZIP, public Git repository, Discord message, or client application. `config.json`, `private/`, `data/`, `.env`, and `node_modules/` are ignored by Git; manually created ZIPs must exclude them too.

## Recipient provisioning

Provision once on an administrator-controlled computer, using Node 22/24 or the installed local runtime:

```text
node cli.js init-recipient --out /private/recipient-key.json --public-out /private/recipient-public.json
```

This command generates random X25519 keys only when invoked, refuses existing output files, and prints only the public fingerprint. Keep `recipient-key.json` on the bot host. Distribute only `recipient-public.json` to the overlay as `source/data/report-recipient.json` before building, or through its supported recipient configuration. Never distribute the private file. Old encrypted reports require the corresponding old private key after a rotation; back it up privately.

Public JSON contract: `{schemaVersion:1, algorithm:"X25519", publicKey:"BASE64_RAW_32_BYTES", fingerprint:"SHA256_PUBLIC_KEY_HEX"}`. The private file has these same fields plus `privateKey` containing Base64 raw 32-byte private key material. Values shown here are format descriptions, not keys.

## Independent signer enrollment

The recipient key and the user's signing key have different roles. Receiving a valid report **does not enroll its signer**. Obtain the user's overlay signing fingerprint through a separate trusted exchange, confirm their Discord user ID, then run:

```text
node cli.js enroll --fingerprint THEIR_64_HEX_SIGNING_FINGERPRINT --user-id THEIR_DISCORD_USER_ID
```

This updates `dataDir/trusted-signers.json`. A signer already assigned to another account cannot be silently reassigned. For a host without a CLI, run this on a protected administrator machine with a private config pointing to a staging data directory, then upload/merge the resulting registry while preserving existing enrollments. Never copy a fingerprint out of an unknown submission and automatically approve it.

Registry format:

```json
{
  "schemaVersion": 1,
  "signers": {
    "INDEPENDENTLY_VERIFIED_64_HEX_FINGERPRINT": {
      "discordUserId": "DISCORD_USER_ID",
      "enrolledAt": "2026-10-22T00:00:00.000Z"
    }
  }
}
```

## Offline verification

```text
node cli.js verify path/to/report.tlrun --trusted-fingerprint THEIR_64_HEX_SIGNING_FINGERPRINT
```

Use the configured recipient key or `--key /private/recipient-key.json`. Exit `0` means the signature matches the independently supplied pin and the local submission checks passed; exit `2` means a valid but unpinned signer; exit `1` indicates malformed, altered, ineligible, wrong-recipient or mismatched-signer data, or an operational error. Offline verification does not enroll anyone, submit to Discord, or reserve a replay receipt.

## Acceptance and storage

- Accepted results require a finished observed run, eligible witnessed-start policy, matching character/journey/category attribution, valid times, and no partial coverage, lost attribution, or unverified restart continuity. Simulations and locally ineligible runs are rejected. Complete custom/review-required categories retain their review label.
- `.tlrun` input is capped at 8 MiB, decrypted signed text at 5 MiB, and structured payload at 3 MiB. Duplicate JSON fields, unsafe numbers, excessive nesting, unknown crypto formats, changed signatures and invalid GCM tags are rejected. The downloader accepts only bounded HTTPS Discord CDN attachments and rechecks redirects.
- Two submissions can download/verify at once, with per-user throttling. Receipt commits serialize. A run cannot be accepted twice under the same signing key and run ID, even if re-exported or re-encrypted; original payload hashes are also deduplicated.
- `receipts.json`, `trusted-signers.json`, and `reports/<payload-sha256>.json` are persistent private data. Writes use temporary files, file flush, atomic replacement and directory flush where supported. Keep them backed up together. Never reset receipts to bypass replay protection. Missing/corrupt receipt history fails closed when reports exist. At 100,000 receipts, migrate history before accepting more.
- Run one bot process per data directory. A lock blocks competing processes and recovers a demonstrably dead process lock; Linux process start ticks distinguish reused PIDs. If an unreadable lock remains after an abrupt shutdown, confirm no verifier is running before removing it. Ordinary SIGINT/SIGTERM waits for active requests and releases the lock.
- Equipment is the last saved loadout, not an exhaustive log of every in-game swap. Unknown equipment remains unavailable. The normalized JSON includes retained IDs and observation times. Large output attachments are bounded; full normalized results remain in private report storage.

The signed payload and client-reported application hash cannot establish trusted execution on an owner-controlled PC. Enrollment and replay protection also depend on the host administrator protecting the registry, receipts and recipient key. These are community report-integrity checks, not anti-cheat or official speedrun adjudication.

## Development checks

```text
npm install
npm test
```

Tests run without Discord credentials or network actions. The cross-language test uses the real Python `run_package.py` and synthetic save-build fixtures if the sibling `source/` directory exists; set `TARNISHED_TEST_PYTHON` to Python with `cryptography` installed. A bot-only deployment skips that one source-dependent test. All key material in tests is ephemeral and generated in memory or temporary test folders.

Crypto wire format matches `source/run_package.py`: ephemeral X25519, HKDF-SHA256 with domain-separated context, AES-256-GCM with authenticated canonical headers, and the existing Ed25519 report footer. The verifier preserves exact signed payload bytes when hashing, including Python floating-point formatting. Dependencies are pinned in `package-lock.json`; `discord.js` 14.27.0 uses Apache-2.0 licensing. Review upgrades and refresh the pinned Node LTS runtime as security updates are released.

References: [Node crypto API](https://nodejs.org/api/crypto.html), [Discord application commands](https://discord.com/developers/docs/interactions/application-commands), [Discord message limits](https://docs.discord.com/developers/resources/message), [Discord components](https://docs.discord.com/developers/components/reference), [discord.js](https://discord.js.org/docs/packages/discord.js/14.27.0), [Node release schedule](https://nodejs.org/en/about/previous-releases).
