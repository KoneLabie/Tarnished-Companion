"""Read-only loopback client for LiveSplit's built-in TCP server.

Protocol: https://github.com/LiveSplit/LiveSplit#the-livesplit-server
Only display/query commands are sent. This module never starts, pauses, resets,
splits, initializes or changes the official timer. LiveSplit's game-time command
falls back to real time when game time is uninitialized; the protocol does not
expose that initialization flag or prove which autosplitter is active.
"""
import json
import math
import re
import socket
import time


PHASES = frozenset(('NotRunning', 'Running', 'Paused', 'Ended'))
READ_COMMANDS = frozenset(('getcurrenttimerphase', 'getattemptcount',
    'gettimingmethod', 'autosplitteractivated', 'getgamename', 'getcategoryname', 'getcategoryvariables',
    'getcurrentgametime', 'getcurrentrealtime', 'getsplitindex'))
TIME_PATTERN = re.compile(r'(?P<sign>-?)(?:(?P<days>\d+)\.)?(?P<hours>\d{1,10}):(?P<minutes>\d{2}):(?P<seconds>\d{2})(?:\.(?P<fraction>\d{1,7}))?\Z')


def parse_time(value):
    """Parse the server's documented C# constant TimeSpan output, or null '-'."""
    if value == '-':
        return None
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError('Invalid LiveSplit time.')
    match = TIME_PATTERN.fullmatch(value)
    if not match:
        raise ValueError('Invalid LiveSplit time.')
    parts = match.groupdict()
    minutes, seconds = int(parts['minutes']), int(parts['seconds'])
    if minutes >= 60 or seconds >= 60:
        raise ValueError('Invalid LiveSplit time fields.')
    duration = int(parts['days'] or 0) * 86400 + int(parts['hours']) * 3600 + minutes * 60 + seconds
    duration += float('0.' + (parts['fraction'] or '0'))
    if parts['sign']:
        duration = -duration
    if not math.isfinite(duration) or abs(duration) > 1e12:
        raise ValueError('LiveSplit time exceeds supported bounds.')
    return duration


def _integer(value, minimum=0):
    if not isinstance(value, str) or not re.fullmatch(r'-?\d{1,10}', value):
        raise ValueError('Invalid LiveSplit integer.')
    number = int(value)
    if not minimum <= number <= 2147483647:
        raise ValueError('LiveSplit integer outside supported bounds.')
    return number


def parse_category_variables(value):
    """Read only the documented CategoryMetadata fields; do not infer rules."""
    if value == '-':
        return None
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('Invalid LiveSplit category metadata.')

    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError('Duplicate LiveSplit category metadata field.')
            result[key] = item
        return result

    def clean(item, maximum):
        return isinstance(item, str) and len(item) <= maximum and not any(ord(char) < 32 or ord(char) == 127 for char in item)

    metadata = json.loads(value, object_pairs_hook=unique)
    if (not isinstance(metadata, dict) or set(metadata) != {'region', 'platform', 'usesEmulator', 'variables'}
            or not all(metadata[key] is None or clean(metadata[key], 256) for key in ('region', 'platform'))
            or type(metadata['usesEmulator']) is not bool
            or not isinstance(metadata['variables'], dict) or len(metadata['variables']) > 32
            or not all(clean(key, 128) and key and clean(item, 512) for key, item in metadata['variables'].items())):
        raise ValueError('Unsupported LiveSplit category metadata fields.')
    return metadata


def _empty(note):
    return dict(connected=False, phase=None, timingMethod=None, autoSplitterActive=None,
                gameName=None, categoryName=None, categoryVariables=None, gameTimeSeconds=None, realTimeSeconds=None,
                splitIndex=None, attemptCount=None, configured=False, sourceVerified=False,
                note=note, sampledAt=None)


class LiveSplitReader:
    """One bounded snapshot per poll; no stale values survive a failed query."""
    def __init__(self, port=16834, timeout=.45):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('Choose a LiveSplit port between 1 and 65535.')
        if type(timeout) not in (int, float) or not .05 <= timeout <= .9 or not math.isfinite(timeout):
            raise ValueError('LiveSplit timeout must be between 0.05 and 0.9 seconds.')
        self.port, self.timeout = port, float(timeout)
        self.connection = None

    def close(self):
        connection, self.connection = self.connection, None
        if connection is not None:
            try:
                connection.close()
            except OSError:
                pass

    def poll(self):
        deadline = time.monotonic() + self.timeout
        self.close()
        buffer = bytearray()

        def remaining():
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError('LiveSplit snapshot deadline exceeded.')
            return left

        def query(command):
            if command not in READ_COMMANDS:
                raise ValueError('Only read-only LiveSplit queries are supported.')
            connection.settimeout(remaining())
            connection.sendall((command + '\r\n').encode('ascii'))
            while b'\n' not in buffer:
                connection.settimeout(remaining())
                chunk = connection.recv(2048)
                if not chunk:
                    raise OSError('LiveSplit closed the connection.')
                buffer.extend(chunk)
                if len(buffer) > 4096:
                    raise ValueError('LiveSplit response is too long.')
            end = buffer.index(b'\n')
            line = bytes(buffer[:end]).removesuffix(b'\r')
            del buffer[:end + 1]
            if len(line) > 2048:
                raise ValueError('LiveSplit response is too long.')
            text = line.decode('utf-8')
            if any(ord(char) < 32 or ord(char) == 127 for char in text):
                raise ValueError('LiveSplit response contains control characters.')
            return text

        try:
            connection = socket.create_connection(('127.0.0.1', self.port), timeout=remaining())
            self.connection = connection
            phase = query('getcurrenttimerphase')
            attempt = _integer(query('getattemptcount'))
            method = query('gettimingmethod')
            active_raw = query('autosplitteractivated')
            game = query('getgamename')
            category = query('getcategoryname')
            category_variables = parse_category_variables(query('getcategoryvariables'))
            game_time = parse_time(query('getcurrentgametime'))
            real_time = parse_time(query('getcurrentrealtime'))
            split_index = _integer(query('getsplitindex'), -1)
            final_phase = query('getcurrenttimerphase')
            final_attempt = _integer(query('getattemptcount'))
            if phase not in PHASES or method not in ('GameTime', 'RealTime') or active_raw not in ('True', 'False'):
                raise ValueError('LiveSplit returned an unsupported timer state.')
            if phase != final_phase or attempt != final_attempt:
                return _empty('LiveSplit changed runs during the update. Waiting for a consistent timer snapshot.')
            active = active_raw == 'True'
            configured = game.casefold() == 'elden ring' and method == 'GameTime' and active and game_time is not None
            if not configured:
                note = 'Select Elden Ring, activate SoulSplitter, and select Game Time in LiveSplit.'
            else:
                note = ('Mirroring LiveSplit Game Time output. The server cannot verify SoulSplitter identity '
                        'or game-time initialization; confirm the official timer setup before a run.')
            return dict(connected=True, phase=phase, timingMethod=method, autoSplitterActive=active,
                        gameName=None if game == '-' else game, categoryName=None if category == '-' else category,
                        categoryVariables=category_variables,
                        gameTimeSeconds=game_time, realTimeSeconds=real_time, splitIndex=split_index,
                        attemptCount=attempt, configured=configured, sourceVerified=False,
                        note=note, sampledAt=time.time())
        except (OSError, ValueError, UnicodeError, RecursionError):
            return _empty('LiveSplit unavailable or incompatible. Start its TCP server on the configured local port; timer values are not estimated.')
        finally:
            self.close()
