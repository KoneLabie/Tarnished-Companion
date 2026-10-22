"""Guided launch using SoulSplitter's documented direct-executable method.

Creates only steam_appid.txt (1245620) when absent, without replacing game files,
injecting DLLs, stopping EAC, or changing Steam's normal protected launch.
https://github.com/FrankvdStam/SoulSplitter/wiki/Elden-Ring
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import threading
import time
import re
from urllib.request import Request, urlopen

from live_reader import eac_present

APP_ID = '1245620'


def request_existing_play(port):
    """A second shortcut click asks the existing local instance to start play."""
    try:
        base = f'http://127.0.0.1:{int(port)}'
        with urlopen(base+'/', timeout=2) as response:
            html = response.read(512*1024).decode('utf-8')
        token = re.search(r"const TOKEN='([A-Za-z0-9_-]{24,128})'", html).group(1)
        with urlopen(Request(base+'/api/action', data=b'{"action":"requestPlay"}',
                            headers={'Content-Type': 'application/json', 'X-Tracker-Token': token}), timeout=3):
            return True
    except (OSError, ValueError, AttributeError):
        return False


def local_game(value):
    if not isinstance(value, (str, os.PathLike)):
        raise ValueError('Choose the installed eldenring.exe file.')
    text = os.fspath(value)
    if not text or len(text) > 4096 or '\x00' in text or text.startswith(('\\\\', '//')):
        raise ValueError('Choose Elden Ring on a local drive.')
    path = Path(text)
    if not path.is_absolute():
        raise ValueError('Choose the full path to eldenring.exe.')
    if path.name.casefold() != 'eldenring.exe':
        raise ValueError('Choose eldenring.exe, not the protected launcher or a mod launcher.')
    info = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_size == 0:
        raise ValueError('The game executable is missing or is not a regular file.')
    return path.resolve(strict=True)


def prepare_app_id(game):
    """Never overwrite an existing file, including another tool's configuration."""
    path = game.parent/'steam_appid.txt'
    try:
        with path.open('xb') as stream:
            stream.write((APP_ID+'\n').encode('ascii'))
        return True
    except FileExistsError:
        info = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_size > 64:
            raise ValueError('An unexpected steam_appid.txt already exists. Use info → game folder to review it.')
        with path.open('rb') as stream:
            existing = stream.read(65)
        if existing.strip() != APP_ID.encode('ascii'):
            raise ValueError('steam_appid.txt belongs to a different setup. It was preserved; contact support before changing it.')
        return False
    except PermissionError as error:
        raise ValueError('Windows blocked setup in the game folder. Run the bundled installer again to prepare this Steam installation automatically, then reopen the companion.') from error


def prepare_installed_game(profile, installation):
    """Installer preflight, with its install-time permissions; never starts a game."""
    folder = installation.get('gamePath')
    if not folder:
        return False
    game = local_game(Path(folder)/'eldenring.exe')
    with game.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != profile.get('sha256'):
            raise ValueError('Unsupported installed game build; live tracking remains blocked.')
    prepare_app_id(game)
    return True


class OfflineLauncher:
    def __init__(self, data_dir, profile, processes, *, installation=None, spawn=None, clock=None, cancelled=None):
        self.path = Path(data_dir)/'launch-settings.json'
        self.profile, self.processes = profile, processes
        self.spawn, self.clock = spawn or subprocess.Popen, clock or time.monotonic
        self.cancelled = cancelled or (lambda:False)
        self.lock = threading.RLock()
        self.game = None
        self.child = None
        self.last_launch = None
        self.busy = False
        self.problem = None
        self.requested = False
        self.requested_at = None
        self.steam_requested = False
        self._state = dict(status='checking', title='Checking your setup', notice='Looking for Elden Ring and Steam.', canLaunch=False, steamRunning=False, gameRunning=False)
        try:
            if self.path.stat().st_size <= 8192:
                self.game = local_game(json.loads(self.path.read_text(encoding='utf-8'))['executable'])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.use_installation(installation or {})

    def use_installation(self, installation):
        with self.lock:
            if self.game is not None:
                return
            if installation.get('status') in ('multiple-installations', 'installation-changing', 'incomplete-installation'):
                return
            candidate = installation.get('gamePath')
            if candidate:
                try:
                    self.game = local_game(Path(candidate)/'eldenring.exe')
                except (OSError, ValueError):
                    pass

    def select(self, value):
        game = local_game(value)
        with self.lock:
            if self.busy:
                raise ValueError('Wait for the launch check to finish.')
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps({'schemaVersion': 1, 'executable': str(game)}), encoding='utf-8')
            temporary.replace(self.path)
            self.game, self.problem = game, None
        return self.refresh()

    def snapshot(self):
        with self.lock:
            result = deepcopy(self._state)
            result.update(gamePath=str(self.game.parent) if self.game else '', supportedVersion=self.profile.get('version'), busy=self.busy)
            result['automaticStart'] = self.requested
            if self.busy:
                result.update(status='launching', title='Preparing your game', notice='Checking the game build and starting Elden Ring. Keep Steam open.', canLaunch=False)
            return result

    def refresh(self):
        try:
            processes = self.processes()
        except Exception:
            processes = None
        with self.lock:
            steam = bool(processes is not None and any(name.casefold() == 'steam.exe' for _, name in processes))
            games = [] if processes is None else [pid for pid, name in processes if name.casefold() == 'eldenring.exe']
            protected = processes is not None and eac_present(processes)
            can_launch = False
            if processes is None:
                status, title, notice = 'unavailable', 'Session check unavailable', 'Windows could not inspect the running session. Live tracking stays blocked; try again after reopening the companion.'
            elif protected:
                status, title, notice = 'protected', 'Close the protected game first', 'Easy Anti-Cheat or the protected launcher is running. Close Elden Ring normally, then launch it here. The companion does not stop anti-cheat services.'
            elif games:
                status, title, notice = 'game-running', 'Elden Ring is open', 'No protected launcher was detected. Live tracking checks the supported game build before reading boss data. Load your character to continue.'
                if len(games) > 1:
                    status, title, notice = 'multiple-games', 'More than one game session', 'Close the extra Elden Ring sessions so the companion can follow one character.'
            elif self.child is not None and self.child.poll() is None:
                status, title, notice = 'starting', 'Elden Ring is starting', 'Waiting for the game process. Steam may ask you to sign in or confirm your game installation.'
            elif self.last_launch is not None and self.clock()-self.last_launch < 15:
                status, title, notice = 'starting', 'Waiting for Elden Ring', 'The launch request was sent. If Steam shows a prompt, finish it there.'
            elif self.game is None:
                status, title, notice = 'game-not-found', 'Find your Elden Ring installation', 'Choose Locate game once. Select eldenring.exe inside your installed game’s Game folder; the companion remembers it.'
            elif self.problem:
                status, title, notice = 'needs-attention', 'Launch needs attention', self.problem
                can_launch = True
            elif not steam:
                status, title, notice = 'steam-required', 'Opening Steam', 'The companion opens Steam automatically. If Steam asks you to sign in, use the account that owns Elden Ring; startup continues from there.'
            else:
                status, title, notice = 'ready', 'Ready to play', 'Opening Tarnished Companion starts your offline game and personal overlay automatically.'
                can_launch = True
                if self.last_launch is not None:
                    notice = 'Elden Ring is closed. If it exited before opening, check Steam for an error, then try again.'
            self._state = dict(status=status, title=title, notice=notice, canLaunch=can_launch,
                               steamRunning=steam, gameRunning=bool(games), eacDetected=bool(protected))
        return self.snapshot()

    def launch(self):
        with self.lock:
            if self.busy:
                raise ValueError('The launch is already being prepared.')
            self.busy = True
        try:
            if self.cancelled():raise ValueError('The companion is closing. Game startup was cancelled.')
            state = self.refresh()
            # refresh's stored fields are authoritative; snapshot marks busy for display only.
            with self.lock:
                state = dict(self._state)
            if not state['canLaunch']:
                raise ValueError(state['notice'])
            game = local_game(self.game)
            before = game.stat()
            with game.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            after = game.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError('Steam is updating Elden Ring. Wait for the update to finish, then try again.')
            if digest != self.profile.get('sha256'):
                raise ValueError('This game build is not supported for live tracking yet. Save progress still works. Contact support for a companion update; do not downgrade or replace game files.')
            if self.cancelled():raise ValueError('The companion is closing. Game startup was cancelled.')
            # Recheck after hashing, before creating setup files or launching.
            processes = self.processes()
            if eac_present(processes) or any(name.casefold() == 'eldenring.exe' for _, name in processes):
                raise ValueError('A game or protected launcher started during setup. Close it normally, then try again.')
            if not any(name.casefold() == 'steam.exe' for _, name in processes):
                raise ValueError('Steam closed during setup. Open Steam, sign in, then try again.')
            prepare_app_id(game)
            environment = os.environ.copy()
            environment.update(SteamAppId=APP_ID, SteamGameId=APP_ID)
            if self.cancelled():raise ValueError('The companion is closing. Game startup was cancelled.')
            child = self.spawn([str(game)], cwd=str(game.parent), env=environment,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               close_fds=True, shell=False)
            with self.lock:
                self.child, self.last_launch, self.problem = child, self.clock(), None
        except (OSError, ValueError) as error:
            message = str(error) if isinstance(error, ValueError) else 'Windows could not start Elden Ring. Check Steam and the game folder permissions, then try again.'
            with self.lock:
                self.problem = message
            raise ValueError(message) from error
        finally:
            with self.lock:
                self.busy = False
        return self.refresh()

    def request_play(self):
        with self.lock:
            if self.busy or self.requested:
                return
            self.requested = True
            self.requested_at = self.clock()
            self.steam_requested = False
            self.problem = None

    def automatic_tick(self, open_steam):
        """Returns True once play is running or a game was launched; no retries of failed launches."""
        with self.lock:
            if self.cancelled():
                self.requested = False
                return False
            if not self.requested or self.busy:
                return False
            expired = self.clock()-self.requested_at > 120
        state = self.refresh()
        if expired:
            with self.lock:
                self.requested = False
                self.problem = 'Steam did not become ready. Finish signing in, then reopen the companion shortcut.'
            self.refresh()
            return False
        if state['status'] == 'steam-required':
            with self.lock:
                first = not self.steam_requested
                self.steam_requested = True
            if first:
                try:
                    open_steam()
                except OSError:
                    with self.lock:
                        self.requested = False
                        self.problem = 'Steam could not be opened. Install or repair Steam, then reopen the companion.'
            return False
        if state['status'] == 'ready':
            with self.lock:
                self.requested = False
            try:
                self.launch()
                return True
            except ValueError:
                self.refresh()
                return False
        if state['status'] in ('game-running', 'protected', 'multiple-games', 'game-not-found', 'needs-attention', 'unavailable'):
            with self.lock:
                self.requested = False
            return state['status'] == 'game-running'
        return False
