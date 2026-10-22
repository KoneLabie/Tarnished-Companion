"""Synthetic launch checks: no real Steam/game processes or installed files."""
import hashlib
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from offline_launch import OfflineLauncher, local_game, prepare_app_id, prepare_installed_game


class OfflineLaunchTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.game = self.root/'Game'/'eldenring.exe'
        self.game.parent.mkdir()
        self.game.write_bytes(b'MZ synthetic supported build')
        self.profile = {'sha256': hashlib.sha256(self.game.read_bytes()).hexdigest(), 'version': 'synthetic'}
        self.running = [(11, 'steam.exe')]
        self.spawn = Mock(return_value=Mock(poll=Mock(return_value=None)))
        self.now = 100
        self.launcher = OfflineLauncher(self.root/'data', self.profile, lambda: list(self.running),
            installation={'gamePath': str(self.game.parent)}, spawn=self.spawn, clock=lambda: self.now)

    def test_first_launch_prepares_only_app_id_and_uses_exact_game_without_shell(self):
        self.launcher.launch()
        self.assertEqual((self.game.parent/'steam_appid.txt').read_text(), '1245620\n')
        self.assertEqual(self.game.read_bytes(), b'MZ synthetic supported build')
        args, options = self.spawn.call_args
        self.assertEqual(args, ([str(self.game.resolve())],))
        self.assertEqual(options['cwd'], str(self.game.parent.resolve()))
        self.assertIs(options['shell'], False)
        self.assertEqual(options['env']['SteamAppId'], '1245620')
        self.assertEqual(self.launcher.snapshot()['status'], 'starting')

    def test_installer_prepares_supported_game_without_starting_processes(self):
        self.assertTrue(prepare_installed_game(self.profile, {'gamePath': str(self.game.parent)}))
        self.assertEqual((self.game.parent/'steam_appid.txt').read_text(), '1245620\n')
        self.spawn.assert_not_called()
        self.assertFalse(prepare_installed_game(self.profile, {}))

    def test_valid_existing_app_id_is_preserved_byte_for_byte(self):
        path = self.game.parent/'steam_appid.txt'
        path.write_bytes(b'1245620\r\n')
        self.launcher.launch()
        self.assertEqual(path.read_bytes(), b'1245620\r\n')

    def test_conflicting_or_oversized_app_id_is_never_overwritten(self):
        path = self.game.parent/'steam_appid.txt'
        for value in (b'1234', b'1'*65):
            with self.subTest(value=value[:8]):
                path.write_bytes(value)
                with self.assertRaises(ValueError): self.launcher.launch()
                self.assertEqual(path.read_bytes(), value)
        self.spawn.assert_not_called()

    def test_unknown_build_is_blocked_before_setup_or_process_start(self):
        self.game.write_bytes(b'updated or modified game')
        with self.assertRaisesRegex(ValueError, 'not supported'): self.launcher.launch()
        self.assertFalse((self.game.parent/'steam_appid.txt').exists())
        self.spawn.assert_not_called()

    def test_protected_game_or_existing_game_never_starts_second_process(self):
        for name in ('EasyAntiCheat_EOS.exe'.lower(), 'start_protected_game.exe', 'eldenring.exe'):
            with self.subTest(name=name):
                self.running = [(11, 'steam.exe'), (22, name)]
                with self.assertRaises(ValueError): self.launcher.launch()
        self.spawn.assert_not_called()
        self.assertFalse((self.game.parent/'steam_appid.txt').exists())

    def test_steam_must_remain_running_during_setup(self):
        calls = 0
        def processes():
            nonlocal calls
            calls += 1
            return [(11, 'steam.exe')] if calls == 1 else []
        self.launcher.processes = processes
        with self.assertRaisesRegex(ValueError, 'Steam closed'): self.launcher.launch()
        self.spawn.assert_not_called()

    def test_protected_launcher_appearing_during_hash_is_blocked(self):
        calls = 0
        def processes():
            nonlocal calls
            calls += 1
            return [(11, 'steam.exe')] + ([(22, 'start_protected_game.exe')] if calls > 1 else [])
        self.launcher.processes = processes
        with self.assertRaisesRegex(ValueError, 'during setup'): self.launcher.launch()
        self.spawn.assert_not_called()
        self.assertFalse((self.game.parent/'steam_appid.txt').exists())

    def test_automatic_start_opens_steam_once_then_launches_without_more_input(self):
        self.running = []
        open_steam = Mock()
        self.launcher.request_play()
        self.assertFalse(self.launcher.automatic_tick(open_steam))
        self.assertFalse(self.launcher.automatic_tick(open_steam))
        open_steam.assert_called_once()
        self.running = [(11, 'steam.exe')]
        self.assertTrue(self.launcher.automatic_tick(open_steam))
        self.assertFalse(self.launcher.automatic_tick(open_steam))
        self.spawn.assert_called_once()
        self.assertFalse(self.launcher.snapshot()['automaticStart'])

    def test_existing_unprotected_session_is_reused_without_launching(self):
        self.running.append((22, 'eldenring.exe'))
        self.launcher.request_play()
        self.assertTrue(self.launcher.automatic_tick(Mock()))
        self.spawn.assert_not_called()

    def test_auto_start_never_stops_a_protected_session(self):
        self.running.append((22, 'easyanticheat_eos.exe'))
        self.launcher.request_play()
        self.assertFalse(self.launcher.automatic_tick(Mock()))
        self.assertEqual(self.launcher.snapshot()['status'], 'protected')
        self.assertFalse(self.launcher.snapshot()['automaticStart'])
        self.spawn.assert_not_called()

    def test_failed_automatic_start_is_not_retried_in_a_loop(self):
        self.spawn.side_effect = OSError('synthetic blocked launch')
        self.launcher.request_play()
        self.assertFalse(self.launcher.automatic_tick(Mock()))
        for _ in range(5): self.assertFalse(self.launcher.automatic_tick(Mock()))
        self.spawn.assert_called_once()
        self.assertEqual(self.launcher.snapshot()['status'], 'needs-attention')

    def test_steam_wait_is_bounded_with_clear_error(self):
        self.running = []
        self.launcher.request_play()
        self.launcher.automatic_tick(Mock())
        self.now += 121
        self.assertFalse(self.launcher.automatic_tick(Mock()))
        self.assertFalse(self.launcher.snapshot()['automaticStart'])
        self.assertIn('Steam did not become ready', self.launcher.snapshot()['notice'])

    def test_hashing_does_not_block_status_and_concurrent_start_is_rejected(self):
        entered, release = threading.Event(), threading.Event()
        real_digest = hashlib.file_digest
        def delayed(stream, algorithm):
            entered.set()
            release.wait(3)
            return real_digest(stream, algorithm)
        errors = []
        def launch():
            try:self.launcher.launch()
            except Exception as error:errors.append(error)
        with patch('offline_launch.hashlib.file_digest', side_effect=delayed):
            worker = threading.Thread(target=launch)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertTrue(self.launcher.snapshot()['busy'])
                with self.assertRaisesRegex(ValueError, 'already'): self.launcher.launch()
            finally:
                release.set();worker.join(3)
        self.assertFalse(errors)
        self.spawn.assert_called_once()

    def test_chosen_installation_is_remembered_and_untrusted_launcher_names_rejected(self):
        self.launcher.select(str(self.game))
        restored = OfflineLauncher(self.root/'data', self.profile, lambda: self.running)
        self.assertEqual(restored.game, self.game.resolve())
        for path in ('eldenring.exe', '//server/game/eldenring.exe', str(self.game.parent/'start_protected_game.exe')):
            with self.assertRaises((ValueError, OSError)): local_game(path)

    def test_no_process_visibility_cannot_trigger_launch(self):
        self.launcher.processes = Mock(side_effect=OSError('synthetic inaccessible process list'))
        self.launcher.request_play()
        self.assertFalse(self.launcher.automatic_tick(Mock()))
        self.assertEqual(self.launcher.snapshot()['status'], 'unavailable')
        self.spawn.assert_not_called()

    def test_closing_companion_cancels_pending_automatic_start(self):
        self.launcher.request_play()
        self.launcher.cancelled = lambda:True
        self.assertFalse(self.launcher.automatic_tick(Mock()))
        with self.assertRaisesRegex(ValueError, 'cancelled'):self.launcher.launch()
        self.spawn.assert_not_called()
        self.assertFalse((self.game.parent/'steam_appid.txt').exists())


if __name__ == '__main__':unittest.main()
