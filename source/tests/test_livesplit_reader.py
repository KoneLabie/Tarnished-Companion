"""Protocol fixtures verify read-only queries and fail-closed timer snapshots."""
import json
from pathlib import Path
import socket
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from livesplit_reader import LiveSplitReader, READ_COMMANDS, parse_time, parse_category_variables


QUERIES = ['getcurrenttimerphase', 'getattemptcount', 'gettimingmethod',
           'autosplitteractivated', 'getgamename', 'getcategoryname', 'getcategoryvariables',
           'getcurrentgametime', 'getcurrentrealtime', 'getsplitindex',
           'getcurrenttimerphase', 'getattemptcount']


def responses(**changes):
    result = dict(zip(QUERIES[:10], ['Running', '7', 'GameTime', 'True',
        'Elden Ring', 'All Remembrances', json.dumps(dict(region=None, platform='PC',
            usesEmulator=False, variables={'Rules': 'Glitchless'})), '00:01:23.4567000',
        '00:01:30.2500000', '2']))
    result.update(changes)
    return [result[name].encode('utf-8') + b'\r\n' for name in QUERIES]


class FixtureConnection:
    def __init__(self, replies=None, clock=None, fragment=0):
        self.replies = responses() if replies is None else replies
        self.commands = []
        self.timeouts = []
        self.pending = b''
        self.closed = False
        self.clock = clock
        self.fragment = fragment

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def sendall(self, payload):
        self.commands.append(payload)
        self.pending += self.replies[len(self.commands) - 1]

    def recv(self, length):
        if self.clock is not None:
            self.clock[0] += .04
        length = min(length, self.fragment or length)
        result, self.pending = self.pending[:length], self.pending[length:]
        return result

    def close(self):
        self.closed = True


class TimeSpanTests(unittest.TestCase):
    def test_documented_constant_formats_and_negative_offset(self):
        for value, expected in [('-', None), ('00:00:00', 0),
                ('00:00:01.0000001', 1.0000001), ('12:34:56.5', 45296.5),
                ('2.03:04:05.1234567', 183845.1234567),
                ('-00:00:10.5', -10.5), ('25:00:00', 90000)]:
            with self.subTest(value=value):
                actual = parse_time(value)
                if expected is None:
                    self.assertIsNone(actual)
                else:
                    self.assertAlmostEqual(actual, expected)

    def test_malformed_times_are_never_coerced_to_zero(self):
        for value in [None, True, 0, '', 'NaN', 'Infinity', '1:2:3',
                      '00:60:00', '00:00:60', ' 00:00:00', '00:00:00\n',
                      '00:00:00.12345678', '+00:00:00', '9' * 65]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_time(value)


class ReaderTests(unittest.TestCase):
    def poll_fixture(self, connection):
        with patch('livesplit_reader.socket.create_connection', return_value=connection) as connect:
            result = LiveSplitReader().poll()
        self.assertEqual(connect.call_args.args, (('127.0.0.1', 16834),))
        self.assertTrue(connection.closed)
        return result

    def test_readonly_complete_snapshot_with_fragmented_utf8(self):
        fixture = FixtureConnection(responses(getcategoryname='Catégorie — Any%'), fragment=1)
        result = self.poll_fixture(fixture)
        self.assertTrue(result['connected'])
        self.assertTrue(result['configured'])
        self.assertFalse(result['sourceVerified'])
        self.assertEqual(result['phase'], 'Running')
        self.assertEqual(result['categoryName'], 'Catégorie — Any%')
        self.assertEqual(result['categoryVariables']['variables'], {'Rules': 'Glitchless'})
        self.assertEqual(result['categoryVariables']['platform'], 'PC')
        self.assertEqual(result['gameTimeSeconds'], 83.4567)
        self.assertEqual(result['realTimeSeconds'], 90.25)
        self.assertEqual(result['attemptCount'], 7)
        self.assertEqual(result['splitIndex'], 2)
        self.assertEqual(fixture.commands, [(name + '\r\n').encode('ascii') for name in QUERIES])
        self.assertEqual(set(QUERIES), READ_COMMANDS)
        self.assertLessEqual(max(fixture.timeouts), .45)
        self.assertGreater(min(fixture.timeouts), 0)
        self.assertIn('initialization', result['note'])

    def test_game_time_prerequisites_must_all_match(self):
        for change in [dict(getgamename='Dark Souls'), dict(gettimingmethod='RealTime'),
                       dict(autosplitteractivated='False'), dict(getcurrentgametime='-')]:
            with self.subTest(change=change):
                result = self.poll_fixture(FixtureConnection(responses(**change)))
                self.assertTrue(result['connected'])
                self.assertFalse(result['configured'])
                self.assertFalse(result['sourceVerified'])

    def test_null_strings_and_idle_split(self):
        result = self.poll_fixture(FixtureConnection(responses(getgamename='-',
            getcategoryname='-', getsplitindex='-1', getcurrentgametime='-',
            getcurrentrealtime='-', getcurrenttimerphase='NotRunning')))
        self.assertTrue(result['connected'])
        self.assertIsNone(result['gameName'])
        self.assertIsNone(result['categoryName'])
        self.assertIsNone(result['gameTimeSeconds'])
        self.assertIsNone(result['realTimeSeconds'])
        self.assertEqual(result['splitIndex'], -1)

    def test_phase_or_attempt_change_discards_mixed_snapshot(self):
        for index, replacement in [(10, b'Ended\r\n'), (11, b'8\r\n')]:
            with self.subTest(index=index):
                replies = responses()
                replies[index] = replacement
                result = self.poll_fixture(FixtureConnection(replies))
                self.assertFalse(result['connected'])
                self.assertIsNone(result['gameTimeSeconds'])
                self.assertIsNone(result['attemptCount'])
                self.assertIn('consistent', result['note'])

    def test_absent_category_metadata_is_never_inferred(self):
        result = self.poll_fixture(FixtureConnection(responses(getcategoryvariables='-')))
        self.assertTrue(result['connected'])
        self.assertIsNone(result['categoryVariables'])

    def test_category_metadata_rejects_unknown_nested_or_control_fields(self):
        valid = dict(region=None, platform='PC', usesEmulator=False, variables={'Rules': 'Glitchless'})
        for change in [dict(extra='private'), dict(variables={'Rules': ['Glitchless']}),
                       dict(variables={'Rules': 'Glitchless\n'}), dict(usesEmulator=1),
                       dict(region={}), dict(platform='x' * 257), dict(variables={'': 'Glitchless'})]:
            with self.subTest(change=change):
                encoded = json.dumps(dict(valid, **change))
                result = self.poll_fixture(FixtureConnection(responses(getcategoryvariables=encoded)))
                self.assertFalse(result['connected'])
                self.assertIsNone(result['categoryVariables'])
        for encoded in ['{}', '[]', 'not json', '{"region":null,"region":null}',
                        'x' * 2049, '{"region":null,"platform":null,"usesEmulator":false,"variables":{"Rules":"Glitchless","Rules":"Any%"}}']:
            with self.subTest(encoded=encoded[:30]), self.assertRaises(ValueError):
                parse_category_variables(encoded)

    def test_bad_protocol_disconnected_and_oversize_fail_closed(self):
        for reply in [b'', b'\xff\r\n', b'Running\x00\r\n',
                      b'x' * 5000, b'x' * 2049 + b'\r\n', b'Unknown\r\n']:
            with self.subTest(reply=reply[:20]):
                replies = responses()
                replies[0] = reply
                result = self.poll_fixture(FixtureConnection(replies))
                self.assertFalse(result['connected'])
                self.assertFalse(result['configured'])
                self.assertIsNone(result['gameTimeSeconds'])

    def test_failed_second_poll_does_not_reuse_a_previous_timer(self):
        fixture = FixtureConnection()
        reader = LiveSplitReader()
        with patch('livesplit_reader.socket.create_connection', side_effect=[fixture, OSError('closed')]):
            self.assertTrue(reader.poll()['connected'])
            result = reader.poll()
        self.assertFalse(result['connected'])
        self.assertIsNone(result['gameTimeSeconds'])
        self.assertIsNone(result['sampledAt'])

    def test_one_total_deadline_covers_all_queries(self):
        clock = [100.0]
        fixture = FixtureConnection(clock=clock)
        with patch('livesplit_reader.time.monotonic', side_effect=lambda: clock[0]), \
             patch('livesplit_reader.socket.create_connection', return_value=fixture):
            result = LiveSplitReader(timeout=.12).poll()
        self.assertFalse(result['connected'])
        self.assertLess(len(fixture.commands), len(QUERIES))
        self.assertAlmostEqual(max(fixture.timeouts), .12)
        self.assertLess(min(fixture.timeouts), .05)
        self.assertTrue(fixture.closed)

    def test_real_loopback_socket_protocol(self):
        errors, commands = [], []
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(('127.0.0.1', 0))
        server.listen(1)
        server.settimeout(2)
        port = server.getsockname()[1]

        def serve():
            try:
                connection, _ = server.accept()
                with connection, connection.makefile('rb') as stream:
                    for response in responses():
                        commands.append(stream.readline())
                        connection.sendall(response)
            except OSError as error:
                errors.append(error)
            finally:
                server.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        result = LiveSplitReader(port=port, timeout=.9).poll()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(result['configured'])
        self.assertEqual(commands, [(name + '\r\n').encode('ascii') for name in QUERIES])

    def test_invalid_configuration_is_rejected(self):
        for port in [0, 65536, True, '16834']:
            with self.subTest(port=port), self.assertRaises(ValueError):
                LiveSplitReader(port=port)
        for timeout in [0, .049, 1, float('nan'), float('inf'), True, '0.4']:
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                LiveSplitReader(timeout=timeout)


if __name__ == '__main__':
    unittest.main()
