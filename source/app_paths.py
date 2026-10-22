"""New product paths with an automatic, lossless legacy-data fallback."""
import os
from pathlib import Path


def default_data_dir(local_app_data=None):
    base=Path(local_app_data or os.environ.get('LOCALAPPDATA',str(Path.home())))
    current=base/'TarnishedCompanion'
    previous=base/'TarnishedLineup'
    def has_history(path):
        return any((path/name).exists() for name in ('settings.json','record-integrity.json','record-integrity-key.json'))
    # Reuse existing data in place. Moving signed history while another version
    # is running can lose observations, and a cosmetic rename must not reset it.
    if not has_history(current) and has_history(previous):return previous
    return current
