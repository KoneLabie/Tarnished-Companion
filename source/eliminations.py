"""Automatic observed enemy deaths, scoped to a character/journey context."""
from datetime import datetime, timezone
import json
from pathlib import Path
import time


class Eliminations:
    MAX_GAP = 2.0
    NOTE = ('Automatic regular-enemy eliminations observed while the companion is connected. '
            'Past kills cannot be recovered. Bosses, players, friendly NPCs and summons are excluded. '
            'Enemy deaths from allies or the environment can count; this does not identify the killing blow.')

    def __init__(self, directory):
        self.path = Path(directory) / 'eliminations.json'
        self.contexts = {}
        self.context = self.session = None
        self.seen = {}
        self.last_at = None
        self.available = False
        self.storage_error = False
        self.load_error = False
        self.dirty = False
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(data,dict) or data.get('schemaVersion')!=1 or not isinstance(data.get('contexts'),dict):
                raise ValueError('Unsupported elimination records.')
            if data.get('schemaVersion') == 1 and isinstance(data.get('contexts'), dict):
                for key, value in data['contexts'].items():
                    if (isinstance(key, str) and isinstance(value, dict)
                            and type(value.get('total')) is int and 0 <= value['total'] <= 10**12
                            and isinstance(value.get('startedAt'), str)):
                        self.contexts[key] = dict(total=value['total'], startedAt=value['startedAt'])
                    else:
                        raise ValueError('Invalid elimination context.')
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError):
            self.contexts={};self.load_error=True

    def pause(self):
        self.available = False
        self.seen.clear()
        self.last_at = None

    def _save(self):
        if not self.dirty:
            return
        try:
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(dict(schemaVersion=1, contexts=self.contexts), indent=2), encoding='utf-8')
            temporary.replace(self.path)
            self.storage_error = self.dirty = False
        except OSError:
            self.storage_error = True

    def update(self, context, session, enemies, available, boss_handles=(), now=None):
        now = time.monotonic() if now is None else now
        if self.load_error:
            self.pause();return
        if not isinstance(context, str) or not context or context == 'pending':
            self.pause()
            return
        if context != self.context or session != self.session:
            self.pause()
            self.context, self.session = context, session
        if not available or not isinstance(session, str) or not session or not isinstance(enemies, list):
            self.pause()
            return
        if self.last_at is not None and not 0 <= now - self.last_at <= self.MAX_GAP:
            self.seen.clear()
        self.last_at, self.available = now, True
        if context not in self.contexts:
            self.contexts[context] = dict(total=0, startedAt=datetime.now(timezone.utc).isoformat(timespec='seconds'))
            self.dirty = True
        bosses = set(boss_handles)
        current = {}
        for enemy in enemies:
            if not isinstance(enemy, dict):
                continue
            handle, pointer, hp, maximum = (enemy.get(k) for k in ('handle', 'instance', 'hp', 'maxHp'))
            defeated=enemy.get('defeated')
            if (not isinstance(handle, str) or not isinstance(pointer, str)
                    or type(hp) is not int or type(maximum) is not int
                    or not 0 <= hp <= maximum <= 100000000 or maximum == 0 or type(defeated) is not bool):
                continue
            identity = (handle, pointer)
            previous = self.seen.get(identity)
            # Deduplicate entries in a world snapshot and keep boss identities
            # excluded even when the boss HUD hides during a phase transition.
            if identity in current:
                continue
            boss = handle in bosses or bool(previous and previous['boss'])
            confirmed=hp==0 and defeated
            if (previous and previous['armed'] and confirmed and not boss
                    and 0 <= now - previous['at'] <= self.MAX_GAP):
                self.contexts[context]['total'] += 1
                self.dirty = True
            armed=(hp>0 and not defeated) or bool(previous and previous['armed'] and not confirmed)
            current[identity] = dict(hp=hp, armed=armed, boss=boss, at=now)
        # Missing/despawned entries are removed, never treated as deaths.
        self.seen = current
        self._save()

    def snapshot(self, context):
        record = self.contexts.get(context)
        return dict(total=record['total'] if record else None,
                    status='storage-error' if self.storage_error or self.load_error else
                           'tracking' if self.available and context == self.context else 'paused',
                    startedAt=record['startedAt'] if record else None,
                    note=('Stored eliminations could not be read. The original file is preserved; tracking is paused. '
                          if self.load_error else '')+self.NOTE,
                    persisted=not (self.storage_error or self.load_error))
