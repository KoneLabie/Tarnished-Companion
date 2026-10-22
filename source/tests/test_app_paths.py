from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app_paths import default_data_dir


class BrandingDataTests(unittest.TestCase):
    def test_new_install_uses_companion_name(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(default_data_dir(folder),Path(folder)/'TarnishedCompanion')

    def test_existing_history_is_reused_without_copying_or_resetting(self):
        with tempfile.TemporaryDirectory() as folder:
            old=Path(folder)/'TarnishedLineup';old.mkdir()
            history=old/'record-integrity.json';history.write_bytes(b'signed history fixture')
            (Path(folder)/'TarnishedCompanion').mkdir() # renderer logs alone are not a new profile
            self.assertEqual(default_data_dir(folder),old)
            self.assertEqual(history.read_bytes(),b'signed history fixture')

    def test_existing_companion_profile_takes_precedence(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ('TarnishedLineup','TarnishedCompanion'):
                directory=Path(folder)/name;directory.mkdir();(directory/'settings.json').write_text('{}')
            self.assertEqual(default_data_dir(folder),Path(folder)/'TarnishedCompanion')


if __name__=='__main__':unittest.main()
