"""Bounded, read-only evidence of downloaded Steam DLC; never a license check.

Steam documents DLC depots and distinguishes installed content from ownership:
https://partner.steamgames.com/doc/store/application/depots
https://partner.steamgames.com/doc/api/ISteamApps#BIsDlcInstalled
https://store.steampowered.com/app/2778580/

The local installed appmanifest_1245620.acf (reviewed 2026-10-22) identifies
InstalledDepots/2778580 with dlcappid 2778580. That installation contains
Game/DLC.bhd and Game/DLC.bdt. Generic sd_dlc02 archives are NOT DLC evidence.
This companion does not load Steam DLLs, launch games, contact Steam, or inspect
accounts/saves. Its result is a lineup preference hint, not authorization.
"""
import os
from pathlib import Path
import re
import stat


APP_ID = '1245620'
DLC_ID = '2778580'
MAX_FILE_BYTES = 1024 * 1024
MAX_LIBRARIES = 32
MIN_ARCHIVE_BYTES = 1024**3
MIN_HEADER_BYTES = 4096
_TOKEN = re.compile(r'\s+|//[^\r\n]*|"(?:[^"\\\x00-\x1f]|\\[^\x00-\x1f])*"|[{}]')


def _parse_vdf(text):
    """Parse only the quoted KeyValues subset used by local Steam manifests."""
    if not isinstance(text, str) or len(text) > MAX_FILE_BYTES or '\x00' in text:
        raise ValueError('Invalid Steam metadata.')
    tokens, offset = [], 0
    for match in _TOKEN.finditer(text):
        if match.start() != offset:
            raise ValueError('Unsupported Steam metadata syntax.')
        offset = match.end()
        token = match.group()
        if token.isspace() or token.startswith('//'):
            continue
        if len(token) > 8194 or len(tokens) >= 20000:
            raise ValueError('Steam metadata exceeds bounds.')
        tokens.append(token)
    if offset != len(text):
        raise ValueError('Truncated Steam metadata.')
    position = 0

    def string(token):
        if not token.startswith('"'):
            raise ValueError('Expected quoted Steam metadata.')
        return re.sub(r'\\([\\"])', r'\1', token[1:-1])

    def mapping(depth=0, nested=False):
        nonlocal position
        if depth > 12:
            raise ValueError('Steam metadata is too deeply nested.')
        result = {}
        while position < len(tokens):
            token = tokens[position]
            position += 1
            if token == '}':
                if nested:
                    return result
                raise ValueError('Unexpected closing brace.')
            key = string(token).casefold()
            if key in result or position >= len(tokens):
                raise ValueError('Duplicate or incomplete Steam metadata.')
            token = tokens[position]
            position += 1
            result[key] = mapping(depth+1, True) if token == '{' else string(token)
        if nested:
            raise ValueError('Unclosed Steam metadata.')
        return result

    return mapping()


def _read_vdf(path):
    before = path.stat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
        raise ValueError('Steam metadata is not a bounded regular file.')
    with path.open('rb') as stream:
        data = stream.read(MAX_FILE_BYTES+1)
    after = path.stat()
    if (len(data) > MAX_FILE_BYTES or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns):
        raise ValueError('Steam metadata changed during detection.')
    return _parse_vdf(data.decode('utf-8-sig'))


def _local_root(value):
    if not isinstance(value, (str, os.PathLike)):
        return None
    text = os.fspath(value)
    if not isinstance(text, str) or not text or len(text) > 4096 or '\x00' in text:
        return None
    if text.startswith(('\\\\', '//')):
        return None  # Do not traverse network libraries or device namespaces.
    path = Path(text)
    return path if path.is_absolute() else None


def _steam_roots():
    roots = []
    if os.name == 'nt':
        import winreg
        for hive, key, field in ((winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
                                 (winreg.HKEY_LOCAL_MACHINE, r'Software\Valve\Steam', 'InstallPath')):
            for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
                try:
                    with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as handle:
                        roots.append(winreg.QueryValueEx(handle, field)[0])
                except OSError:
                    pass
        for variable in ('ProgramFiles(x86)', 'ProgramFiles'):
            folder = os.environ.get(variable)
            if folder:
                roots.append(str(Path(folder) / 'Steam'))
    return roots


def _positive_number(value):
    return isinstance(value, str) and len(value) <= 24 and value.isascii() and value.isdigit() and int(value) > 0


def _file_size(path):
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('An expected game file is not a regular file.')
    return info.st_size


def _inspect_install(library):
    manifest_path = library / 'steamapps' / f'appmanifest_{APP_ID}.acf'
    try:
        metadata = _read_vdf(manifest_path)
    except FileNotFoundError:
        return None
    state = metadata.get('appstate')
    if not isinstance(state, dict) or state.get('appid') != APP_ID:
        raise ValueError('Unrecognized Elden Ring installation metadata.')
    directory = state.get('installdir')
    if (not isinstance(directory, str) or not directory or len(directory) > 255
            or directory in ('.', '..') or any(c in directory for c in '\\/:\x00')
            or directory.endswith((' ', '.'))):
        raise ValueError('Unsafe game installation directory.')
    game = library / 'steamapps' / 'common' / directory / 'Game'
    base = dict(gamePath=str(game))
    if state.get('stateflags') != '4':
        return dict(base, available=None, status='installation-changing',
                    notice='Steam does not report a fully settled game installation. DLC detection is unknown until installation or updates finish.')
    if not (_file_size(game / 'eldenring.exe') or 0) > 0:
        return dict(base, available=None, status='incomplete-installation', notice='Steam lists Elden Ring, but its executable is missing. DLC detection is unknown.')
    depots = state.get('installeddepots')
    if not isinstance(depots, dict) or not depots:
        raise ValueError('Installed depot metadata is unavailable.')
    depot = depots.get(DLC_ID)
    archive_size = _file_size(game / 'DLC.bdt')
    header_size = _file_size(game / 'DLC.bhd')
    if depot is None and archive_size is None and header_size is None:
        return dict(base, available=False, status='not-detected',
                    notice='The settled Steam installation has no Shadow of the Erdtree depot or archive pair. DLC download was not detected; ownership is not checked.')
    depot_matches = (isinstance(depot, dict) and depot.get('dlcappid') == DLC_ID
                     and _positive_number(depot.get('manifest')) and _positive_number(depot.get('size')))
    # Reject absent/empty placeholder archives; these bounds are not file hashes.
    files_present = ((archive_size or 0) >= MIN_ARCHIVE_BYTES and (header_size or 0) >= MIN_HEADER_BYTES)
    if depot_matches and files_present:
        return dict(base, available=True, status='detected',
                    notice='Shadow of the Erdtree downloaded files and its installed Steam depot were detected. This checks local installation evidence, not ownership or file integrity.')
    return dict(base, available=None, status='inconsistent-installation',
                notice='DLC depot metadata and archive files do not provide consistent installation evidence. Finish or verify the DLC installation in Steam, then rescan. Base-game lineups are shown meanwhile.')


def detect_dlc(steam_roots=None):
    """Return {available: bool|None, status, notice, gamePath?} without writes.

    Pass a list/tuple of absolute Steam-library roots to make discovery fully
    deterministic (including [] for no installation). None reads only known
    Steam registry locations/default folders and their libraryfolders.vdf.
    Reads at most 32 libraries, each at its exact expected manifest path.
    """
    seeds = _steam_roots() if steam_roots is None else steam_roots
    if not isinstance(seeds, (list, tuple)):
        raise ValueError('steam_roots must be a list or tuple of absolute paths.')
    roots, seen, problems = [], set(), False

    def add(value):
        nonlocal problems
        path = _local_root(value)
        if path is None:
            problems = True
            return
        key = os.path.normcase(str(path))
        if key not in seen:
            if len(roots) >= MAX_LIBRARIES:
                problems = True
                return
            seen.add(key)
            roots.append(path)

    for value in seeds[:MAX_LIBRARIES]:
        add(value)
    if len(seeds) > MAX_LIBRARIES:
        problems = True
    for seed in list(roots):
        try:
            libraries = _read_vdf(seed / 'steamapps' / 'libraryfolders.vdf').get('libraryfolders')
            if not isinstance(libraries, dict):
                raise ValueError('Missing Steam library list.')
            for key, entry in libraries.items():
                if key.isdigit():
                    add(entry.get('path') if isinstance(entry, dict) else entry)
        except FileNotFoundError:
            pass
        except (OSError, ValueError, UnicodeError):
            problems = True
    results = []
    for library in roots:
        try:
            result = _inspect_install(library)
            if result:
                results.append(result)
        except (OSError, ValueError, UnicodeError):
            problems = True
    if len(results) == 1 and not problems:
        return results[0]
    if results and all(item['available'] is True for item in results) and not problems:
        return results[0]
    if len(results) > 1:
        return dict(available=None, status='multiple-installations', notice='Multiple Elden Ring installations have different or incomplete DLC evidence. Check the copy installed through Steam, then rescan. Base-game lineups are shown meanwhile.')
    if problems:
        return dict(available=None, status='unavailable', notice='Some Steam installation metadata could not be checked safely. Check Steam installation access, then rescan. Base-game lineups are shown meanwhile.')
    return dict(available=None, status='game-not-found', notice='No readable Steam Elden Ring installation was found. Check its Steam library location, then rescan. Non-Steam or moved copies cannot be confirmed; base-game lineups are shown.')
