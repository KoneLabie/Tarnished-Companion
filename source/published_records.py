"""Bounded public leaderboard reads. These records contain full-run times only."""
from copy import deepcopy
from datetime import datetime, timezone
import http.client
import json
import math
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlencode, urljoin, urlsplit


MAPPING = json.loads((Path(__file__).resolve().parent/'data'/'published-records.json').read_text(encoding='utf-8'))
CATEGORIES = MAPPING['categories']
REFRESH_SECONDS = 900
RETRY_SECONDS = 60
MAX_BYTES = 1024 * 1024
MAX_CACHE_BYTES = 5 * MAX_BYTES
MAX_SECONDS = 5
_ID = re.compile(r'^[a-z0-9]{8}$')
_CONTROL = re.compile(r'[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u206f]')
_BASE_NOTICE = ('PC Glitchless results combine accepted versions, routes and FPS patch settings. '
                'These are complete-run times; this source does not publish boss fight times. '
                'The averages describe the returned sample, not every runner.')


def _iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _stamp(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError('Invalid cache timestamp')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Cache timestamp lacks timezone')
    return parsed.timestamp()


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 < value < 1e9


def _clean(value):
    return _CONTROL.sub(' ', value)[:120] if isinstance(value, str) else 'Unknown runner'


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _json(raw):
    return json.loads(raw, object_pairs_hook=_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON value')))


def source_url(category_id):
    category = CATEGORIES[category_id]
    return ('https://www.speedrun.com/eldenring?x=' + category['categoryId'] + '-'
            + category['variableId'] + '.' + category['valueId'])


def api_url(category_id):
    category = CATEGORIES[category_id]
    query = urlencode({'platform': MAPPING['platformId'], 'timing': MAPPING['apiTiming'],
                       'var-'+category['variableId']: category['valueId'], 'top': 20, 'embed': 'players'})
    return ('https://www.speedrun.com/api/v1/leaderboards/' + MAPPING['gameId']
            + '/category/' + category['categoryId'] + '?' + query)


def _official_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in ('www.speedrun.com', 'speedrun.com')
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or not parsed.path.startswith('/api/v1/')):
        raise ValueError('Unexpected record source')
    return parsed


def fetch_json(url):
    """Five-second total budget, two official redirects, bounded JSON only."""
    deadline = time.monotonic() + MAX_SECONDS
    for redirects in range(3):
        parsed = _official_url(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Record source timed out')
        connection = http.client.HTTPSConnection(parsed.hostname, timeout=remaining)
        try:
            connection.connect()
            transport = connection.sock
            transport.settimeout(max(.001, deadline-time.monotonic()))
            connection.request('GET', parsed.path + ('?' + parsed.query if parsed.query else ''),
                               headers={'User-Agent': 'TarnishedLineup/1.0', 'Accept': 'application/json',
                                        'Accept-Encoding': 'identity'})
            transport.settimeout(max(.001, deadline-time.monotonic()))
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                if redirects == 2:
                    raise ValueError('Too many record-source redirects')
                url = urljoin(url, response.getheader('Location', ''))
                _official_url(url)
                continue
            if response.status != 200:
                raise ValueError('Record source unavailable')
            if response.getheader('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
                raise ValueError('Record source did not return JSON')
            declared = response.getheader('Content-Length')
            if declared is not None and (not declared.isdigit() or int(declared) > MAX_BYTES):
                raise ValueError('Record response is too large')
            chunks, size = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Record source timed out')
                transport.settimeout(remaining)
                chunk = response.read(min(65536, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError('Record response is too large')
            return _json(b''.join(chunks).decode('utf-8'))
        finally:
            connection.close()
    raise ValueError('Record source unavailable')


def validate_board(payload, category_id):
    category = CATEGORIES[category_id]
    data = payload.get('data') if isinstance(payload, dict) else None
    expected = {category['variableId']: category['valueId']}
    if (not isinstance(data, dict) or data.get('game') != MAPPING['gameId']
            or data.get('category') != category['categoryId'] or 'level' not in data or data['level'] is not None
            or data.get('platform') != MAPPING['platformId'] or data.get('timing') != MAPPING['apiTiming']
            or data.get('values') != expected or not isinstance(data.get('runs'), list)
            or len(data['runs']) > 400):
        raise ValueError('Leaderboard filters do not match the selected category')
    names = {}
    players = data.get('players', {}).get('data', []) if isinstance(data.get('players'), dict) else []
    if not isinstance(players, list) or len(players) > 1000:
        raise ValueError('Invalid leaderboard players')
    for player in players:
        if isinstance(player, dict) and isinstance(player.get('id'), str):
            names[player['id']] = _clean(player.get('names', {}).get('international')
                                         if isinstance(player.get('names'), dict) else None)
    runs, seen = [], set()
    for entry in data['runs']:
        run = entry.get('run') if isinstance(entry, dict) else None
        rank = entry.get('place') if isinstance(entry, dict) else None
        if not isinstance(run, dict) or type(rank) is not int or not 1 <= rank <= 100000:
            raise ValueError('Malformed leaderboard run')
        run_id = run.get('id')
        times = run.get('times') if isinstance(run.get('times'), dict) else {}
        system = run.get('system') if isinstance(run.get('system'), dict) else {}
        values = run.get('values') if isinstance(run.get('values'), dict) else {}
        if (not isinstance(run_id, str) or not _ID.fullmatch(run_id) or run_id in seen
                or run.get('game') != MAPPING['gameId'] or run.get('category') != category['categoryId']
                or 'level' not in run or run['level'] is not None or system.get('platform') != MAPPING['platformId']
                or not isinstance(run.get('status'), dict) or run['status'].get('status') != 'verified'
                or values.get(category['variableId']) != category['valueId']
                or not _number(times.get('primary_t')) or not _number(times.get('realtime_t'))
                or times['primary_t'] != times['realtime_t']):
            raise ValueError('Run is not a matching published category result')
        seen.add(run_id)
        participants = run.get('players')
        if (not isinstance(participants, list) or not 1 <= len(participants) <= 20
                or any(not isinstance(p, dict) or p.get('rel') not in ('user', 'guest') for p in participants)):
            raise ValueError('Run participants unavailable')
        runner = ', '.join(names.get(p.get('id'), 'Unknown runner') if p.get('rel') == 'user'
                           else _clean(p.get('name')) for p in participants if isinstance(p, dict))[:240]
        date = run.get('date')
        if date is not None:
            if not isinstance(date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date):
                raise ValueError('Malformed run date')
            datetime.strptime(date, '%Y-%m-%d')
        runs.append(dict(id=run_id, rank=rank, runner=runner or 'Unknown runner', seconds=times['primary_t'],
                         date=date, url='https://www.speedrun.com/eldenring/runs/'+run_id))
    runs.sort(key=lambda run: (run['rank'], run['seconds'], run['id']))
    if any(runs[i]['seconds'] > runs[i+1]['seconds'] for i in range(len(runs)-1)):
        raise ValueError('Leaderboard ordering is inconsistent')
    return runs[:20]


class PublishedRecords:
    def __init__(self, data_dir, *, fetcher=None, clock=None):
        self.path = Path(data_dir)/'published-records-cache.json'
        self.fetcher, self.clock = fetcher or fetch_json, clock or time.time
        self.lock = threading.RLock()
        self.entries, self.pending = {}, set()
        self._load()

    def _load(self):
        try:
            if self.path.stat().st_size > MAX_CACHE_BYTES:
                return
            cache = _json(self.path.read_text(encoding='utf-8'))
            if not isinstance(cache, dict) or cache.get('schemaVersion') != 1 or not isinstance(cache.get('entries'), dict):
                return
            now = self.clock()
            for key, entry in cache['entries'].items():
                try:
                    if key not in CATEGORIES or not isinstance(entry, dict):
                        continue
                    checked = _stamp(entry['checkedAt'])
                    if checked < 0 or checked > now + 30:
                        continue
                    runs = validate_board(entry['payload'], key)
                    attempted = _stamp(entry.get('lastAttemptAt', entry['checkedAt']))
                    if not 0 <= attempted <= now + 30:
                        attempted = checked
                    self.entries[key] = dict(payload=entry['payload'], runs=runs, checked=checked,
                                             attempted=attempted, failed=entry.get('failed') is True)
                except (ValueError, KeyError, TypeError, OverflowError):
                    continue
        except (OSError, ValueError, TypeError, OverflowError, RecursionError):
            pass

    def _save(self):
        try:
            data = {'schemaVersion': 1, 'entries': {key: {'payload': entry['payload'],
                    'checkedAt': _iso(entry['checked']), 'lastAttemptAt': _iso(entry['attempted']),
                    'failed': entry['failed']} for key, entry in self.entries.items() if entry.get('payload') is not None}}
            encoded = json.dumps(data, ensure_ascii=False).encode('utf-8')
            if len(encoded) > MAX_CACHE_BYTES:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_bytes(encoded)
            temporary.replace(self.path)
        except (OSError, ValueError, TypeError, OverflowError):
            pass

    def snapshot(self, category_id):
        with self.lock:
            category = CATEGORIES.get(category_id)
            output = dict(schemaVersion=1, source='speedrun.com', status='unsupported', categoryId=category_id,
                          categoryName=category['name'] if category else 'Custom or unselected category',
                          scope=MAPPING['scope'], timing=MAPPING['timing'], timingKey='pc-soulsplitter-game-time',
                          checkedAt=None, lastAttemptAt=None,
                          nextRefreshAt=None, sourceUrl=source_url(category_id) if category else 'https://www.speedrun.com/eldenring',
                          bestSeconds=None, nearBestSeconds=None, averageSeconds=None, sampleCount=0, runs=[],
                          notice='No published-record mapping is available for this category.', bossTimesAvailable=False)
            if category is None:
                return output
            entry = self.entries.get(category_id, {})
            now, checked, attempted = self.clock(), entry.get('checked'), entry.get('attempted')
            runs = entry.get('runs', [])
            fresh = checked is not None and 0 <= now - checked < REFRESH_SECONDS and not entry.get('failed')
            output.update(status='fresh' if fresh else 'stale' if checked is not None else 'unavailable',
                          checkedAt=_iso(checked) if checked is not None else None,
                          lastAttemptAt=_iso(attempted) if attempted is not None else None,
                          nextRefreshAt=_iso(max(checked + REFRESH_SECONDS if fresh else now,
                                                attempted + RETRY_SECONDS if attempted is not None else now)),
                          runs=deepcopy(runs), sampleCount=len(runs))
            if runs:
                times = sorted(run['seconds'] for run in runs)
                fast_count = min(len(times), max(2, math.ceil(len(times)/4)))
                output.update(bestSeconds=times[0], nearBestSeconds=sum(times[:fast_count])/fast_count,
                              averageSeconds=sum(times)/len(times))
            prefix = (f'{len(runs)} published results (up to 20). ' if runs else 'No matching published results. ')
            if output['status'] == 'stale':
                prefix = 'Cached records: the latest refresh is overdue or failed. ' + prefix
            elif output['status'] == 'unavailable':
                prefix = 'Published records are currently unavailable. '
            output['notice'] = prefix + _BASE_NOTICE
            return output

    def refresh(self, category_id, force=False):
        with self.lock:
            if category_id not in CATEGORIES or category_id in self.pending:
                return self.snapshot(category_id)
            now = self.clock()
            entry = self.entries.get(category_id, {})
            if (entry.get('attempted') is not None and 0 <= now-entry['attempted'] < RETRY_SECONDS
                    or not force and self.snapshot(category_id)['status'] == 'fresh'):
                return self.snapshot(category_id)
            self.pending.add(category_id)
            self.entries.setdefault(category_id, {})['attempted'] = now
        try:
            # DNS resolution has no portable Python socket deadline. Isolate the
            # read in a daemon so even a stalled resolver cannot hold app shutdown.
            ready, result = threading.Event(), {}
            def fetch():
                try:
                    result['payload'] = self.fetcher(api_url(category_id))
                except Exception as error:
                    result['error'] = error
                finally:
                    ready.set()
            threading.Thread(target=fetch, daemon=True, name='public-record-request').start()
            if not ready.wait(MAX_SECONDS):
                raise TimeoutError('Record source timed out')
            if 'error' in result:
                raise result['error']
            payload = result['payload']
            runs = validate_board(payload, category_id)
            with self.lock:
                self.entries[category_id] = dict(payload=deepcopy(payload), runs=runs, checked=self.clock(),
                                                attempted=now, failed=False)
        except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError, http.client.HTTPException):
            with self.lock:
                self.entries[category_id]['failed'] = True
        finally:
            with self.lock:
                self.pending.discard(category_id)
                self._save()
        return self.snapshot(category_id)
