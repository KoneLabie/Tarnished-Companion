"""Isolated presentation fixtures. Never reads player saves or tracking records.

Only bundled boss metadata/artwork and combat reference data are used. Every
number, character and run below is simulated. Sample .tlrun packages may be
signed and encrypted with ephemeral, untrusted preview identities; they are
never evidence of a real run. The preview handler must reject all action POSTs.
"""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import sys

from combat_reference import clean_reference, unknown_combat
from run_categories import ENCOUNTERS, category_route


SCENES = (
    'home', 'fight', 'combat', 'armed', 'running', 'death', 'paused',
    'game-closed', 'recovered', 'finished', 'blocked',
)
CONTEXT = 'v2:simulated_preview_character:j1'
CATEGORY_ID = 'all-remembrances-glitchless'
CATEGORY_NAME = 'All Remembrances — Glitchless'
BASE_CATEGORY_ID = 'any-percent-glitchless'
BASE_CATEGORY_NAME = 'Any% — Glitchless'
SIMULATION = 'Simulated preview. These values do not describe a real character or recorded run.'


@lru_cache(maxsize=1)
def _references():
    """Use bundled source-backed traits instead of inventing boss weaknesses."""
    try:
        root = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
        data = json.loads((root / 'data' / 'boss-combat.json').read_text(encoding='utf-8'))
        return data.get('entries', {}) if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def preview_state(scene, bosses):
    """Return a fresh JSON-compatible actual-overlay state for a whitelisted scene.

    ``bosses`` is the application's available catalog with local portrait URLs.
    Returned dictionaries are detached from the catalog, and scene validation is
    intentionally strict because the HTTP handler embeds the scene in a URL.
    """
    if not isinstance(scene, str) or scene not in SCENES:
        raise ValueError('Unknown preview scene.')
    catalog = deepcopy([b for b in bosses if isinstance(b, dict) and type(b.get('id')) is int]) if isinstance(bosses, (list, tuple)) else []
    if not catalog:
        raise ValueError('Preview requires the bundled boss catalog.')
    by_id = {b['id']: b for b in catalog}
    include_dlc = any(b.get('dlc') is True for b in catalog)
    category_id = CATEGORY_ID if include_dlc else BASE_CATEGORY_ID
    category_name = CATEGORY_NAME if include_dlc else BASE_CATEGORY_NAME

    def boss(name):
        expected = next((boss_id for boss_id, verified_name in ENCOUNTERS.items() if verified_name == name), None)
        entry = by_id.get(expected)
        if entry is None or entry.get('name') != name:
            raise ValueError('Preview catalog is missing the verified encounter: ' + name)
        return deepcopy(entry)

    route = category_route(category_id, catalog)
    if not route:
        raise ValueError('Preview requires verified encounters for its selected category.')
    running_boss = boss('Messmer the Impaler' if include_dlc else 'Maliketh, the Black Blade')
    current_boss = boss('Malenia, Blade of Miquella') if scene == 'fight' else boss('Rellana, Twin Moon Knight' if include_dlc else 'Rennala, Queen of the Full Moon') if scene == 'combat' else running_boss
    pivot = route.index(running_boss['id'])
    remaining = set(route[pivot:]) | {current_boss['id']}
    defeated = set(route[:pivot]) - remaining
    # The count includes optional encounters without removing the upcoming queue.
    for item in catalog:
        if len(defeated) >= 58:
            break
        if item['id'] not in remaining:
            defeated.add(item['id'])
    elapsed = 5666
    status = 'running'
    capture = 'running'
    view = 'home' if scene in ('home', 'fight') else 'combat' if scene == 'combat' else 'speedrun'
    show_fight = scene in ('fight', 'combat', 'running')
    current = None
    if show_fight:
        current = current_boss
        current.update(source='Live game data', hp=14882, maxHp=24000,
                       combat=clean_reference(_references()[str(current['id'])])
                       if str(current['id']) in _references() else unknown_combat())
    stats = dict(name='Preview Tarnished', level=117, origin='Vagabond', originId=0,
                 startingGift=0, journey=1, runes=123450, deaths=8, seconds=6029, slot=0)
    notice = SIMULATION
    available = view == 'speedrun' and scene not in ('armed', 'blocked')
    review = 'no-issues-observed'
    if view != 'speedrun':
        capture, status, available = 'off', 'idle', False
    if scene == 'armed':
        defeated = set()
        stats.update(level=9, deaths=0, seconds=0, runes=0)
        elapsed, status, capture = None, 'armed', 'armed'
        notice += ' Category selected. Waiting to observe a new character and the external timer start.'
    elif scene == 'death':
        stats['deaths'] = 9
        notice += ' Saved death confirmed. The completed attempt remains visible; the next fight starts at zero.'
    elif scene == 'paused':
        status, capture = 'paused', 'game-time-paused'
        notice += ' External Game Time is not advancing. Menu and loading states are not inferred.'
    elif scene == 'game-closed':
        status, capture = 'paused', 'game-closed'
        notice += ' The game process ended. No offline time is added.'
    elif scene == 'recovered':
        elapsed, review = 5744, 'review-required'
        notice += ' Reconnected to the same timer after an unexpected tracker restart. Missing observations remain marked for review.'
    elif scene == 'finished':
        elapsed, status, capture = 11211, 'finished', 'finished'
        stats.update(seconds=11642, deaths=12, level=160)
        defeated.update(route)
        notice += ' LiveSplit reported the category finish. The sample export contains simulated data only.'
    elif scene == 'blocked':
        capture, review = 'blocked', 'ineligible'
        elapsed = None
        notice += ' Example integrity failure: a protected local record no longer matches its signature. Recording and export are locked.'
    upcoming = [deepcopy(by_id[i]) for i in route if i not in defeated and i != (current or {}).get('id')][:8]
    category = dict(id=category_id, name=category_name, scope='Base game + DLC' if include_dlc else 'Base game',
                    startNote='Fresh character; all base-game and DLC Remembrances plus Heart of Bayle, then game credits.' if include_dlc else 'Fresh character; complete the selected ending and reach the game credits.',
                    rulesUrl='https://www.speedrun.com/eldenring?rules=category')
    speedrun = dict(status=status, captureStatus=capture, captureNotice=notice,
                    timingSource='livesplit', timingLabel='LiveSplit Game Time', controlsLocked=True,
                    elapsedSeconds=elapsed, realTimeSeconds=None if elapsed is None else elapsed + 143,
                    igtSeconds=None if elapsed is None else stats['seconds'],
                    deaths=0 if scene == 'armed' else stats['deaths'],
                    bossesDefeated=sum(i in defeated for i in route),
                    character=stats['name'], journey=1, contextKey=CONTEXT,
                    category=category_name, declaredCategory=category_name,
                    localAuditStatus=review, localAuditReasons=[] if review == 'no-issues-observed' else [notice],
                    exportAvailable=available, sourceVerified=False, notice=notice,
                    startedAt=None if scene == 'armed' or view != 'speedrun' else '2026-10-22T12:00:00+00:00',
                    upcoming=deepcopy(upcoming), splits=[])
    speedrun['runPolicy'] = dict(categoryId=category_id, categoryName=category_name)
    # Presentation-only values: no network call or claim about a real record.
    sample_times = ([10800, 11160, 11400, 12000, 12600, 13200, 13800, 14400]
                    if include_dlc else [5400, 5580, 5760, 6000, 6300, 6600, 6900, 7200])
    published = dict(source='speedrun.com', status='fresh', simulation=True,
                     categoryId=category_id, categoryName=category_name,
                     scope='Simulated PC category snapshot', timing='Published PC category time',
                     timingKey='pc-soulsplitter-game-time',
                     checkedAt='2026-10-22T12:05:00+00:00', lastAttemptAt='2026-10-22T12:05:00+00:00',
                     nextRefreshAt='2026-10-22T12:20:00+00:00',
                     sourceUrl='https://www.speedrun.com/eldenring',
                     bestSeconds=sample_times[0], nearBestSeconds=sum(sample_times[:2])/2,
                     averageSeconds=sum(sample_times)/len(sample_times), sampleCount=len(sample_times),
                     runs=[], bossTimesAvailable=False,
                     notice='Simulated record data and example check time. These are not actual leaderboard records. The real app checks the configured published category automatically.')
    split_names = ['Divine Beast Dancing Lion', 'Rellana, Twin Moon Knight', 'Golden Hippopotamus'] if include_dlc else ['Morgott, the Omen King', 'Fire Giant', 'Godskin Duo']
    if scene == 'finished':
        split_names = ['Bayle the Dread', 'Romina, Saint of the Bud', 'Radahn, Consort of Miquella', 'Elden Beast'] if include_dlc else ['Maliketh, the Black Blade', 'Sir Gideon Ofnir, the All-Knowing', 'Hoarah Loux, Warrior', 'Elden Beast']
    if scene != 'armed' and view == 'speedrun':
        for index, name in enumerate(split_names):
            entry = boss(name)
            speedrun['splits'].append(dict(bossId=entry['id'], name=entry['name'],
                                          elapsedSeconds=(elapsed or 5666) - (len(split_names) - index) * 340,
                                          igtSeconds=5000 + index * 300, source='simulated save flag'))
    attempts = {}
    if scene in ('running', 'death'):
        attempt = dict(name=running_boss['name'], bossId=running_boss['id'], attemptNumber=3,
                       elapsedSeconds=192 if scene == 'running' else 201,
                       status='fighting', categoryId=category_id)
        attempts = dict(contextKey=CONTEXT, categoryId=category_id,
                        active=attempt if scene == 'running' else None,
                        lastAttempt=None if scene == 'running' else dict(attempt, outcome='death'),
                        benchmarks=dict(bestSeconds=185, nearBestSeconds=218, averageSeconds=310,
                                        sampleCount=8, scaleSeconds=900, scope='Simulated personal history · Journey 1'),
                        notice=SIMULATION, records=[])
    return dict(preview=True, previewScene=scene, simulation=True, bosses=catalog, presets={},
                route=route, killed=sorted(defeated), stats=stats, profiles=[deepcopy(stats)],
                save='', saves=[], slot=0, contextKey=CONTEXT, ready=True,
                status=SIMULATION, saveStatus='connected',
                trackingNotice='', updated=None, current=current, otherBars=[],
                fightSeconds=192 if current else 0, upcoming=upcoming,
                recent=[deepcopy(by_id[i]) for i in route if i in defeated][-3:],
                completed=sum(i in defeated for i in route), total=len(route), catalogKilled=len(defeated),
                enemyKills=0 if scene == 'armed' else 438,
                eliminations=dict(total=0 if scene=='armed' else 438,status='tracking',note='Simulated automatic elimination total; no real character data.'),
                eliminationReaderStatus='Simulated live enemy data',showCharacterName=True,
                overlayView=view, routeManaged=view == 'speedrun',
                layout=dict(width=360, opacity=.72, font='Cinzel', icons=8, animateGlow=True, showBossTraits=True),
                liveEnabled=True, liveStatus='Simulated live data', liveCharacterVerified=False,
                combatMetrics=dict(status='tracking' if scene == 'combat' else 'unavailable',
                                   bossName=current_boss['name'], rollingDps=286.4, averageDps=174.8,
                                   observedDamage=9118, largestDrop=1176, observedSeconds=52.2, hpPercent=62.0,
                                   note=SIMULATION),
                speedrun=speedrun, bossAttempts=attempts, publishedRecord=published,
                runPolicy=dict(categories=[category], selectedId=category_id, name=category_name,
                               needsSelection=False, recordingUnlocked=scene not in ('armed', 'blocked') and view == 'speedrun',
                               status='blocked' if scene == 'blocked' else 'candidate' if scene == 'armed' else 'recording-unlocked',
                               notice=notice, limitation=SIMULATION, sourceVerified=False),
                recordIntegrity=dict(locked=scene == 'blocked', notice=notice,
                                     fingerprint='SIMULATED PREVIEW — EPHEMERAL, UNTRUSTED SIGNER'),
                reportExport=dict(extension='.tlrun', encrypted=True,
                                  notice='Simulated sample package, signed and encrypted using ephemeral preview identities. Its signer is untrusted; this is not a real run record.'),
                timingMode='livesplit', liveSplitPort=16834,
                externalTimer=dict(connected=True, configured=True, phase='NotRunning' if scene == 'armed' else 'Ended' if scene == 'finished' else 'Paused' if scene in ('paused', 'game-closed') else 'Running',
                                   timingMethod='GameTime', autoSplitterActive=True, gameName='Elden Ring',
                                   categoryName='All Remembrances' if include_dlc else 'Any%', gameTimeSeconds=elapsed,
                                   categoryVariables={'variables': {'Glitches': 'Glitchless'}}, note=SIMULATION,
                                   attemptCount=1, sourceVerified=False),
                gameProcess='stopped' if scene == 'game-closed' else 'running')
