"""Crash-recovery hints and clean-exit handshakes, never proof of game integrity."""
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sys


SESSION_FILE = 'session-lifecycle.json'
SESSION_ENV = 'TARNISHED_SUPERVISOR_SESSION'
MARKER_ENV = 'TARNISHED_SUPERVISOR_MARKER'
STOP_ENV = 'TARNISHED_SUPERVISOR_STOP'
RECOVER_ENV = 'TARNISHED_SUPERVISOR_RECOVER'
CLEAN_REASONS = {'requested-stop', 'keyboard-interrupt', 'parent-stop', 'already-running'}
_session_path = None
_session_record = None


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _read(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > 16384:
        raise ValueError('Invalid lifecycle marker.')
    with path.open('r', encoding='utf-8') as stream:
        return json.load(stream)


def process_alive(pid):
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            # Access denied does not establish that a process has ended.
            return ctypes.get_last_error() == 5
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def begin_session(data_dir, session=None, *, is_process_alive=None):
    """Record worker startup before constructing components that need recovery.

    The caller first checks for an existing app. A previous running marker whose
    process ended permits checking a signed recovery checkpoint; it does not
    authenticate that checkpoint or distinguish a crash from force termination.
    """
    global _session_path, _session_record
    path = Path(data_dir) / SESSION_FILE
    previous_unclean = False
    previous_exit = None
    notice = ''
    alive = is_process_alive or process_alive
    try:
        previous = _read(path)
        if (not isinstance(previous, dict) or previous.get('schemaVersion') != 1
                or previous.get('status') not in ('running', 'clean')
                or type(previous.get('pid')) is not int
                or not isinstance(previous.get('session'), str)):
            raise ValueError('Invalid session history.')
        previous_exit = previous.get('reason') if previous['status'] == 'clean' else None
        if previous['status'] == 'running':
            if alive(previous['pid']):
                raise RuntimeError('Another recorded app process is still running. Close that instance before using the same data directory.')
            previous_unclean = True
            notice = 'The previous app process ended unexpectedly. Checking the last signed recovery checkpoint.'
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError, RecursionError):
        previous_unclean = True
        notice = 'The previous app session marker could not be read. Recovery requires a valid signed checkpoint.'
    token = session or os.environ.get(SESSION_ENV) or secrets.token_urlsafe(32)
    if not isinstance(token, str) or not 1 <= len(token) <= 256:
        raise ValueError('Invalid app session identifier.')
    record = dict(schemaVersion=1, session=token, pid=os.getpid(), status='running',
                  startedAt=_utc(), endedAt=None, reason=None)
    _write(path, record)
    _session_path, _session_record = path, record
    return dict(previousUnclean=previous_unclean, priorUnclean=previous_unclean,
                session=token, previousExit=previous_exit, notice=notice)


start = begin_session


def _same_executable(pid):
    """Verify a possible one-file launcher before binding it to the child PID."""
    if type(pid) is not int or pid <= 0:
        return False
    try:
        if os.name == 'nt':
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                       wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
            kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle.restype = wintypes.BOOL
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            try:
                buffer = ctypes.create_unicode_buffer(32768)
                length = wintypes.DWORD(len(buffer))
                if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
                    return False
                executable = buffer.value
            finally:
                kernel.CloseHandle(handle)
        else:
            executable = os.readlink(f'/proc/{pid}/exe')
        return os.path.normcase(str(Path(executable).resolve())) == os.path.normcase(str(Path(sys.executable).resolve()))
    except (OSError, ValueError):
        return False


def mark_clean_exit(reason='requested-stop'):
    """Call only after all owned workers and timing transactions have stopped."""
    global _session_record
    if reason not in CLEAN_REASONS:
        raise ValueError('Unsupported clean-exit reason.')
    token = os.environ.get(SESSION_ENV)
    if _session_path is not None and _session_record is not None:
        # Do not overwrite another session's marker after a replacement process.
        current = _read(_session_path)
        if current.get('session') != _session_record['session'] or current.get('pid') != os.getpid():
            raise ValueError('The active app session changed before shutdown.')
        _session_record = dict(_session_record, status='clean', endedAt=_utc(), reason=reason)
        _write(_session_path, _session_record)
        token = token or _session_record['session']
    marker = os.environ.get(MARKER_ENV)
    if marker and token:
        result = dict(schemaVersion=1, session=token, pid=os.getpid(),
                      exitCode=0, reason=reason, endedAt=_utc())
        # In one-file builds Popen can own the bootloader while Python runs in
        # its child. Inherited frozen workers may instead execute directly, so
        # keep the real worker PID and supply a separately verified parent link.
        parent = os.getppid()
        if getattr(sys, 'frozen', False) and parent != os.getpid() and _same_executable(parent):
            result.update(frozen=True, launcherPid=parent, parentPid=parent)
        _write(marker, result)
    return True


def supervisor_stop_requested():
    token, stop = os.environ.get(SESSION_ENV), os.environ.get(STOP_ENV)
    if not token or not stop:
        return False
    try:
        marker = _read(stop)
        return (isinstance(marker, dict) and marker.get('schemaVersion') == 1
                and marker.get('session') == token and marker.get('request') == 'stop')
    except (OSError, ValueError, TypeError, RecursionError):
        return False
