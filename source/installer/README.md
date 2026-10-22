# Windows installer and automatic startup

Players run `TarnishedCompanion-Setup.exe`, then open the installed Tarnished Companion shortcut. The installed executable includes first-party offline launch support. It discovers the Steam installation, opens Steam if absent, creates `Game/steam_appid.txt` containing `1245620` only when absent, and directly launches the original supported `eldenring.exe`. The personal overlay opens automatically. No Vortex installation, third-party offline-launcher download, DLL copy, executable rename, or manual app-ID setup is required.

The launch method follows [SoulSplitter's Elden Ring documentation](https://github.com/FrankvdStam/SoulSplitter/wiki/Elden-Ring). The game binary must match the supported live-reader SHA-256. Existing conflicting files are preserved and startup stops with a clear explanation. A protected session, multiple sessions, unreadable process inventory or unknown build prevents automatic launch. Steam's normal protected launch is unchanged. No anti-cheat process is stopped or hidden. The companion's live reader independently checks EAC and the supported game profile. This is not an account-ban guarantee.

Steam and Elden Ring must already be installed, and Steam may require its normal sign-in or game-update flow. A nonstandard installation can be located once in the troubleshooting panel. New saves are found automatically after the game creates them. Closing the companion does not close the game. Reopening its shortcut requests play from an existing instance instead of launching duplicate companions or games. Steam startup waits at most two minutes; a failed game launch is not retried indefinitely.

Setup requests normal installation permission once, installs the companion, creates Start Menu and desktop shortcuts, and adds an uninstaller. Its included preflight helper prepares the detected supported game's app-ID file using install-time permissions, so a protected Steam folder does not require manual setup on first launch. It contains Microsoft's signed WebView2 Evergreen bootstrapper, automatically running it only if the Runtime is missing. That prerequisite installation needs internet. The uninstaller removes the installed application, while game saves and local tracking/report history remain intact. The app-ID file, if created for offline launch, remains in the game folder; it does not change Steam's protected launch.

## Building

1. Install Python build dependencies and run `source/build.ps1`.
2. Install the official [Inno Setup compiler](https://jrsoftware.org/isdl.php).
3. Run `source/installer/build-installer.ps1` (or pass `-Compiler` with the compiler's `ISCC.exe` path).

The script obtains WebView2 from Microsoft's official redirect if absent and verifies the Authenticode signature before building. See [Microsoft's distribution guidance](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution). Output is `TarnishedCompanion-Setup.exe` beside `TarnishedCompanion.exe` at the repository root.

GitHub Actions → **Build Windows app and installer** → **Run workflow** builds both files after regression checks and uploads the **TarnishedCompanion-Windows** artifact. A `v*` tag also triggers it. This creates downloadable build artifacts; it does not automatically publish a GitHub Release. Build compiler licensing and app code-signing are separate release-owner responsibilities.

For isolated development and automated tests, pass `--no-game-launch --no-browser --data-dir <temporary-folder> --port <unused-port>`. Installer smoke tests use `/CURRENTUSER /SKIPGAMESETUP=1 /DIR=<temporary-folder>` to avoid elevation and real game setup. Never run startup tests against a player's installed game or personal tracking directory. Test fixtures supply synthetic game binaries/process lists and mock process creation.
