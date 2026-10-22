"""A local parent process that restarts only its own unexpectedly ended worker."""
from collections import deque
import ctypes
from ctypes import wintypes
import json
import logging
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
from urllib.request import urlopen

from app_lifecycle import (CLEAN_REASONS, SESSION_ENV, MARKER_ENV, STOP_ENV, RECOVER_ENV,
                           _read, _write)


MAX_RESTARTS = 3
RESTART_WINDOW_SECONDS = 120
EXIT_RESTART_LIMIT = 70
EXIT_LAUNCH_FAILED = 71


def existing_instance(port):
    """Check only the loopback app endpoint; an occupied unrelated port is false."""
    try:
        with urlopen(f'http://127.0.0.1:{port}/health', timeout=.5) as response:
            return json.loads(response.read(4096)).get('app') in ('TarnishedCompanion','TarnishedLineup')
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def _clean_exit(marker, token, pid, exit_code, allow_frozen_launcher=False):
    if exit_code != 0:
        return False
    try:
        record = _read(marker)
        worker_pid = record.get('pid') if isinstance(record, dict) else None
        pid_matches = type(worker_pid) is int and worker_pid > 0 and worker_pid == pid
        # The worker verifies that this parent runs the same frozen executable.
        # Only a frozen supervisor accepts this explicit bootloader relationship;
        # session, real worker PID, launcher PID and process status all stay bound.
        if (allow_frozen_launcher and type(worker_pid) is int and worker_pid > 0
                and worker_pid != pid and isinstance(record, dict) and record.get('frozen') is True
                and type(record.get('launcherPid')) is int and record['launcherPid'] == pid
                and type(record.get('parentPid')) is int and record['parentPid'] == pid):
            pid_matches = True
        return (isinstance(record, dict) and record.get('schemaVersion') == 1
                and record.get('session') == token and type(record.get('pid')) is int
                and pid_matches and type(record.get('exitCode')) is int
                and record['exitCode'] == 0 and record.get('reason') in CLEAN_REASONS)
    except (OSError, ValueError, TypeError, RecursionError):
        return False


def _request_stop(child, stop_path, token, grace_seconds=8, terminate_seconds=2):
    """Ask for a clean shutdown; escalation is limited to this Popen child."""
    if child is None or child.poll() is not None:
        return
    try:
        _write(stop_path, dict(schemaVersion=1, session=token, request='stop'))
    except OSError:
        pass
    try:
        child.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        child.terminate()
    try:
        child.wait(timeout=terminate_seconds)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=terminate_seconds)


def _install_console_handler(stop):
    """Handle console-close/logoff too; regular Ctrl+C stays with Python."""
    if os.name != 'nt':
        return lambda: None
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    handler_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    kernel.SetConsoleCtrlHandler.argtypes = [handler_type, wintypes.BOOL]
    kernel.SetConsoleCtrlHandler.restype = wintypes.BOOL

    @handler_type
    def handler(event):
        if event not in (1, 2, 5, 6):
            return False
        stop()
        return True

    if not kernel.SetConsoleCtrlHandler(handler, True):
        # A windowed executable can have no console; normal app stop still works.
        return lambda: None

    def restore():
        kernel.SetConsoleCtrlHandler(handler, False)
    return restore  # Retains the callback until it is unregistered.


def _spawn_options(environment):
    options = dict(env=environment, close_fds=True)
    if os.name == 'nt':
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        options.update(startupinfo=startup,
                       creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    return options


def run_supervised(command, port, data_dir, *, spawn=None, health_check=None,
                   monotonic=None, sleep=None):
    """Run a command containing --worker, restarting up to 3 times in 120 s.

    Both a matching PID/session clean marker and exit code zero are required to
    stop normally. Unexpected zero exits are recoverable failures too. Restarts
    use 1/2/4-second backoff and suppress additional browser windows. Exit 70
    means the restart limit was reached; 71 means the worker could not launch;
    130 means the parent received Ctrl+C. No service or login task is installed.
    """
    if (not isinstance(command, (list, tuple)) or not command
            or any(not isinstance(item, str) or not item for item in command)
            or '--worker' not in command):
        raise ValueError('A worker command including --worker is required.')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('A valid app port is required.')
    spawn = spawn or subprocess.Popen
    health_check = health_check or existing_instance
    monotonic = monotonic or time.monotonic
    sleep = sleep or time.sleep
    if health_check(port):
        return 0
    directory = Path(data_dir) / 'supervisor'
    if directory.is_symlink():
        raise ValueError('The supervisor directory must be a local directory.')
    directory.mkdir(parents=True, exist_ok=True)
    invocation = secrets.token_hex(16)
    marker = directory / (invocation + '.exit.json')
    stop_path = directory / (invocation + '.stop.json')
    restarts = deque()
    attempt = 0
    child = None
    token = ''
    parent_stop = threading.Event()

    def console_stop():
        parent_stop.set()
        try:
            _request_stop(child, stop_path, token, grace_seconds=3, terminate_seconds=1)
        except (OSError, subprocess.TimeoutExpired):
            pass

    restore_console = _install_console_handler(console_stop)
    try:
        while True:
            if parent_stop.is_set():
                return 130
            if attempt and health_check(port):
                # Another launch may have taken over while the worker was down.
                return 0
            marker.unlink(missing_ok=True)
            stop_path.unlink(missing_ok=True)
            token = secrets.token_urlsafe(32)
            environment = os.environ.copy()
            environment.update({SESSION_ENV: token, MARKER_ENV: str(marker), STOP_ENV: str(stop_path)})
            environment.pop(RECOVER_ENV, None)
            child_command = list(command)
            if attempt:
                environment[RECOVER_ENV] = '1'
                for flag in ('--no-browser', '--recover'):
                    if flag not in child_command:
                        child_command.append(flag)
            try:
                child = spawn(child_command, **_spawn_options(environment))
            except OSError:
                logging.error('The app worker could not start. Automatic restart stopped.')
                return EXIT_LAUNCH_FAILED
            exit_code = child.wait()
            if parent_stop.is_set():
                return 130
            if _clean_exit(marker, token, child.pid, exit_code,
                           allow_frozen_launcher=bool(getattr(sys, 'frozen', False))):
                return 0
            now = monotonic()
            while restarts and now-restarts[0] >= RESTART_WINDOW_SECONDS:
                restarts.popleft()
            if len(restarts) >= MAX_RESTARTS:
                logging.error('The app worker ended unexpectedly too often. Automatic restart stopped; reopen the app after reviewing its log.')
                return EXIT_RESTART_LIMIT
            delay = min(2 ** len(restarts), 10)
            restarts.append(now)
            attempt += 1
            logging.warning('The app worker ended unexpectedly (exit %s). Restarting in %s seconds.', exit_code, delay)
            sleep(delay)
    except KeyboardInterrupt:
        try:
            _request_stop(child, stop_path, token)
        except (OSError, subprocess.TimeoutExpired):
            logging.error('The app worker did not finish shutdown before the timeout.')
        return 130
    finally:
        restore_console()
        # Only this invocation's two handshake files are removed.
        for path in (marker, stop_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
