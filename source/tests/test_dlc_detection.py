import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dlc_detection import detect_dlc, _parse_vdf, MAX_FILE_BYTES


def vdf(value):
    return '\n'.join(json.dumps(str(key)) + ' ' + ('{\n' + vdf(item) + '\n}' if isinstance(item, dict) else json.dumps(str(item)))
                     for key, item in value.items())


class DlcDetectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archive_bound = patch('dlc_detection.MIN_ARCHIVE_BYTES', 32)
        self.archive_bound.start()
        self.addCleanup(self.archive_bound.stop)

    def install(self, root=None, *, dlc=True, files=True, flags='4', directory='ELDEN RING'):
        root = root or self.root
        steamapps = root / 'steamapps'
        steamapps.mkdir(parents=True, exist_ok=True)
        state = dict(appid='1245620', stateflags=flags, installdir=directory,
                     installeddepots={'1245621': dict(manifest='123', size='456')})
        if dlc:
            state['installeddepots']['2778580'] = dict(manifest='987654', size='16000000000', dlcappid='2778580')
        (steamapps / 'appmanifest_1245620.acf').write_text(vdf(dict(AppState=state)), encoding='utf-8')
        game = steamapps / 'common' / directory / 'Game'
        game.mkdir(parents=True, exist_ok=True)
        (game / 'eldenring.exe').write_bytes(b'fixture')
        if files:
            for name, size in (('DLC.bdt', 32), ('DLC.bhd', 4096)):
                with (game / name).open('wb') as stream:
                    stream.truncate(size)
        return game

    def test_installed_depot_and_archives_detected_without_reading_archives(self):
        game = self.install()
        result = detect_dlc([self.root])
        self.assertIs(result['available'], True)
        self.assertEqual(result['status'], 'detected')
        self.assertEqual(result['gamePath'], str(game))
        self.assertIn('not ownership or file integrity', result['notice'])

    def test_base_install_without_depot_or_archives_is_not_detected(self):
        self.install(dlc=False, files=False)
        self.assertIs(detect_dlc([self.root])['available'], False)

    def test_generic_base_update_dlc_named_sound_archives_do_not_count(self):
        game = self.install(dlc=False, files=False)
        (game / 'sd').mkdir()
        (game / 'sd' / 'sd_dlc02.bdt').write_bytes(b'base update')
        self.assertIs(detect_dlc([self.root])['available'], False)

    def test_missing_or_zero_archive_is_unknown(self):
        game = self.install(files=False)
        for name in ('DLC.bdt', 'DLC.bhd'):
            (game / name).write_bytes(b'')
        self.assertIsNone(detect_dlc([self.root])['available'])

    def test_archives_without_installed_depot_are_unknown(self):
        self.install(dlc=False)
        self.assertEqual(detect_dlc([self.root])['status'], 'inconsistent-installation')

    def test_other_dlc_id_not_confused_with_expansion(self):
        self.install()
        path = self.root / 'steamapps' / 'appmanifest_1245620.acf'
        path.write_text(path.read_text().replace('"dlcappid" "2778580"', '"dlcappid" "2855520"'))
        self.assertIsNone(detect_dlc([self.root])['available'])

    def test_updating_install_unknown_even_with_complete_files(self):
        self.install(flags='6')
        self.assertEqual(detect_dlc([self.root])['status'], 'installation-changing')

    def test_missing_game_executable_unknown(self):
        self.install().joinpath('eldenring.exe').unlink()
        self.assertEqual(detect_dlc([self.root])['status'], 'incomplete-installation')

    def test_secondary_library_discovery_current_and_legacy_formats(self):
        library = self.root / 'another-library'
        self.install(library)
        steamapps = self.root / 'steamapps'
        steamapps.mkdir()
        for entry in (dict(path=str(library), apps={'1245620': '123'}), str(library)):
            (steamapps / 'libraryfolders.vdf').write_text(vdf(dict(libraryfolders={'1': entry})))
            self.assertIs(detect_dlc([self.root])['available'], True)

    def test_different_installations_are_ambiguous(self):
        self.install()
        other = self.root / 'second'
        self.install(other, dlc=False, files=False)
        self.assertEqual(detect_dlc([self.root, other])['status'], 'multiple-installations')

    def test_empty_discovery_does_not_infer_no_dlc(self):
        with patch('dlc_detection._steam_roots', side_effect=AssertionError('Should not discover')):
            self.assertEqual(detect_dlc([])['status'], 'game-not-found')

    def test_default_discovery_uses_known_roots(self):
        self.install()
        with patch('dlc_detection._steam_roots', return_value=[self.root]):
            self.assertIs(detect_dlc()['available'], True)

    def test_malformed_and_oversize_metadata_unknown(self):
        self.install()
        path = self.root / 'steamapps' / 'appmanifest_1245620.acf'
        for text in ('"AppState" { "appid" "1245620"', 'x' * (MAX_FILE_BYTES+1)):
            path.write_text(text)
            self.assertIsNone(detect_dlc([self.root])['available'])

    def test_read_error_not_reported_as_missing_dlc(self):
        with patch('dlc_detection._read_vdf', side_effect=PermissionError):
            self.assertEqual(detect_dlc([self.root])['status'], 'unavailable')

    def test_install_directory_cannot_escape_library(self):
        self.install()
        path = self.root / 'steamapps' / 'appmanifest_1245620.acf'
        path.write_text(path.read_text().replace('"ELDEN RING"', '"../outside"'))
        self.assertEqual(detect_dlc([self.root])['status'], 'unavailable')

    def test_network_and_relative_roots_never_read(self):
        with patch('dlc_detection._read_vdf', side_effect=AssertionError('Must not read')):
            for root in ('relative', r'\\server\share', '//server/share'):
                self.assertIsNone(detect_dlc([root])['available'])

    def test_parser_handles_comments_escapes_but_rejects_duplicate_keys(self):
        self.assertEqual(_parse_vdf('// test\n"x" {"path" "C:\\\\Steam"}'), {'x': {'path': 'C:\\Steam'}})
        for text in ('"x" "a" "X" "b"', '"x" "a" trailing', '"x" {', '}'):
            with self.assertRaises(ValueError):
                _parse_vdf(text)

    def test_detection_does_not_modify_installation_metadata(self):
        game = self.install()
        paths = [self.root/'steamapps'/'appmanifest_1245620.acf', game/'DLC.bhd', game/'DLC.bdt']
        before = [(p.stat().st_mtime_ns, p.stat().st_size) for p in paths]
        detect_dlc([self.root])
        self.assertEqual(before, [(p.stat().st_mtime_ns, p.stat().st_size) for p in paths])


if __name__ == '__main__':
    unittest.main()
