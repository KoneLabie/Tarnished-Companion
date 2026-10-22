"""Tarnished Companion — local Windows companion and OBS browser source.
Copyright 2026. GPL-3.0-or-later. See ../LICENSE.txt and ../THIRD-PARTY.txt.
"""
import argparse
import copy
import hashlib
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import secrets
import sys
import subprocess
import shutil
import threading
import time
import webbrowser
from urllib.parse import urlparse, parse_qs

from save_reader import profiles, read_stable, select_profile, slot_state, load_bst
from live_reader import LiveReader, process_list
from progress_store import normalize_settings, resolve_context, slot_key, file_key
from combat_reference import CombatReference
from run_metrics import CombatMetrics, SpeedrunMetrics
from livesplit_reader import LiveSplitReader
from external_run import ExternalRun
from boss_attempts import BossAttempts
from run_policy import RunPolicy
from record_integrity import LocalIntegrity
from run_categories import category_route
from build_history import observe_build, export_build
from run_package import create_package
from report_export import load_recipient, export_status, sample_package, MIME as REPORT_MIME
from external_run import utc
from dlc_detection import detect_dlc
from lineup_presets import build_presets
from published_records import PublishedRecords
from offline_launch import OfflineLauncher, request_existing_play, prepare_installed_game
from app_paths import default_data_dir
from eliminations import Eliminations

ROOT=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
BOSSES=json.loads((ROOT/'data/bosses.json').read_text(encoding='utf-8'))
try:
    PORTRAITS=json.loads((ROOT/'data/portraits.json').read_text(encoding='utf-8'))
except (OSError,ValueError):
    PORTRAITS={}
for boss in BOSSES:
    item=PORTRAITS.get(str(boss['id']))
    boss['portrait']='/portraits/'+Path(item['src']).name if item else None
BY_ID={b['id']:b for b in BOSSES}
BOSS_NAMES={b['id']:b['name'] for b in BOSSES}
COMBAT=CombatReference(ROOT/'data'/'boss-combat.json',BOSSES)
BST=load_bst(ROOT/'data/eventflag_bst.txt')
PROFILE=json.loads((ROOT/'data/memory-profile.json').read_text())
MAJOR=[10000850,10000800,14000850,14000800,1252380800,11000850,11000800,1252520800,13000850,13000800,11050850,11050800,19000800]
# Use catalog identities for branches; no claim this route is the game's mandatory order.
def names_route(names):
    return [next(b['id'] for b in BOSSES if b['name']==n) for n in names]
MAJOR=names_route(['Margit, the Fell Omen','Godrick the Grafted','Red Wolf of Radagon','Rennala, Queen of the Full Moon','Starscourge Radahn','Godfrey, First Elden Lord (Golden Shade)','Morgott, the Omen King','Fire Giant','Godskin Duo','Maliketh, the Black Blade','Sir Gideon Ofnir, the All-Knowing','Hoarah Loux, Warrior','Elden Beast'])
DLC=names_route(['Divine Beast Dancing Lion','Rellana, Twin Moon Knight','Golden Hippopotamus','Messmer the Impaler','Romina, Saint of the Bud','Radahn, Consort of Miquella'])
OPTIONAL=names_route(['Rykard, Lord of Blasphemy','Mohg, Lord of Blood','Loretta, Knight of the Haligtree','Malenia, Blade of Miquella','Dragonlord Placidusax','Putrescent Knight','Metyr, Mother of Fingers','Bayle the Dread','Midra, Lord of Frenzied Flame'])
PRESETS={'Major bosses + DLC':list(dict.fromkeys(MAJOR+DLC)), 'DLC main route':DLC, 'DLC all encounters':[b['id'] for b in BOSSES if b['dlc']], 'Major + optional + DLC':list(dict.fromkeys(MAJOR+OPTIONAL+DLC)), 'All encounters (catalog order)':[b['id'] for b in BOSSES]}

def discover_saves():
    base=Path(os.environ.get('APPDATA',''))/'EldenRing'
    candidates=[]
    for path in base.glob('*/*'):
        if path.name.lower() in ('er0000.sl2','er0000.co2'):
            try:candidates.append((path.suffix.lower()=='.sl2',path.stat().st_mtime_ns,str(path)))
            except OSError:pass
    return [item[2] for item in sorted(candidates,reverse=True)]

def match_boss(name,route,killed):
    # Queue order is a viewing preference, never evidence of the current arena.
    # Repeated HUD names remain unresolved until a verified location is available.
    norm=lambda x: ''.join(c for c in x.casefold() if c.isalnum())
    aliases={'radagonofthegoldenorder':19000800,'maleniagoddessofrot':15000800,'baseserpentmessmer':21010800,'promisedconsortradahn':20010800,'beastclergyman':13000800,'serpentgodrykard':16000800,'goddevouringserpent':16000800}
    key=norm(name)
    if key in aliases:return aliases[key]
    if key=='godfreyfirsteldenlord':return None
    candidates=[b['id'] for b in BOSSES if norm(b['name'])==key]
    return candidates[0] if len(candidates)==1 else None

@lru_cache(maxsize=128)
def shared_boss_portrait(name):
    """A repeated boss may share artwork without establishing its arena/flag."""
    norm=lambda x: ''.join(c for c in x.casefold() if c.isalnum())
    candidates=[b for b in BOSSES if norm(b['name'])==norm(name)]
    if not candidates or any(not b.get('portrait') for b in candidates):return None
    try:
        hashes={hashlib.sha256((ROOT/'data'/'portraits'/Path(b['portrait']).name).read_bytes()).digest() for b in candidates}
    except OSError:return None
    return candidates[0]['portrait'] if len(hashes)==1 else None

class Tracker:
    def __init__(self,data_dir,recover_interrupted=False):
        self.dir=Path(data_dir);self.dir.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.stop=threading.Event();self.token=secrets.token_urlsafe(24)
        # Preserve unsigned history from older releases; never adopt it as trusted timing.
        if not any((self.dir/name).exists() for name in ('record-integrity-key.json','record-integrity.json')):
            legacy=[self.dir/name for name in ('external-run.json','boss-attempts.json','run-policy.json','run-state.json','run-records') if (self.dir/name).exists()]
            if legacy:
                archive=self.dir/'legacy-unsigned'/secrets.token_hex(8)
                archive.mkdir(parents=True)
                for path in legacy:
                    if path.is_symlink() or path.resolve().parent!=self.dir.resolve():raise ValueError('Unexpected timing history path.')
                    shutil.move(str(path),str(archive/path.name))
                (archive/'README.txt').write_text('Unsigned history from an older release. Preserved for reference only; not eligible for signed timing export.\n',encoding='utf-8')
        self.integrity=LocalIntegrity(self.dir,recover_interrupted=recover_interrupted)
        if getattr(sys,'frozen',False):
            self.build_fingerprint=hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
            self.build_kind='Windows executable'
        else:
            digest=hashlib.sha256()
            for source in sorted(Path(__file__).parent.glob('*.py')):
                digest.update(source.name.encode());digest.update(source.read_bytes())
            self.build_fingerprint=digest.hexdigest();self.build_kind='Python source (local development)'
        raw={}
        try:raw=json.loads((self.dir/'settings.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):pass
        self._refresh_catalog()
        self.cfg=normalize_settings(raw,BY_ID,self.default_route)
        if not self.cfg['save']:
            saves=discover_saves()
            if saves:self.cfg['save']=saves[0]
        self.profiles=[];self.killed=set();self.stats=None;self.context='pending'
        self.status='Waiting for the save reader.';self.updated=None;self.signature=None
        self.save_status='waiting';self.tracking_notice=''
        self.profile_snapshot=None;self.profile_snapshot_path=None;self.save_generation=0
        self.character_selection_source='waiting';self.character_selection_status='Choose a save to load character playtime.'
        self.live=LiveReader(PROFILE);self.live_enabled=self.cfg['liveDetection'];self.live_status='Checking offline session…' if self.live_enabled else 'Off — use only with EAC disabled and the game offline.'
        self.bars=[];self.manual=None;self.fight_since=None;self.fight_id=None;self.last_seen=0
        self.recent=[];self.server=None;self.port=18473;self.overlay_process=None
        trusted_start=self.integrity.begin_update()
        self.combat_metrics=CombatMetrics();self.speedrun=SpeedrunMetrics(self.dir)
        self.eliminations=Eliminations(self.dir)
        self.external_run=ExternalRun(self.dir);self.attempts=BossAttempts(self.dir,recover_interrupted=trusted_start)
        self.run_policy=RunPolicy(self.dir)
        self.published_records=PublishedRecords(self.dir)
        if trusted_start:
            self.run_policy.set_capture_enabled(self.cfg['overlayView']=='speedrun',
                context=(self.external_run.record or {}).get('contextKey') if self.cfg['overlayView']!='speedrun' and (self.external_run.record or {}).get('status') in ('running','paused') else None)
            if self.cfg['overlayView']!='speedrun':self.external_run.suspend_capture('The speedrun view is not selected.')
            self.integrity.seal()
        self.external_timer={'connected':False,'configured':False,'note':'Waiting for LiveSplit. Start its local TCP server with SoulSplitter active and Game Time selected.'}
        self.external_sequence=0;self.external_observed=-1;self.timing_generation=0
        self.game_process='unknown'
        self.last_game_clock=None;self.game_clock_changed_at=None
        self.recovery_requested=bool(recover_interrupted)
        self.shutdown_reason='unexpected'
        self.overlay_restart_times=[]
        self.launcher=OfflineLauncher(self.dir,PROFILE,process_list,installation=self.dlc,cancelled=self.stop.is_set)
    def capture_enabled(self):
        return self.cfg.get('overlayView')=='speedrun'
    def close_personal_overlay(self):
        from desktop_overlay import stop_owned_overlay
        with self.lock:
            process=self.overlay_process
            self.overlay_process=None
        return stop_owned_overlay(process)
    def _refresh_catalog(self):
        detected=detect_dlc()
        include=detected.get('available') is True
        self.dlc={**detected,'include':include}
        self.catalog=[boss for boss in BOSSES if include or not boss['dlc']]
        self.catalog_ids={boss['id'] for boss in self.catalog}
        self.presets=build_presets(BOSSES,include)
        self.default_route=list(self.presets['Major bosses + DLC' if include else 'Major bosses'])
    def available_run_policy(self):
        policy=self.run_policy.snapshot()
        policy['categories']=[category for category in policy['categories']
            if self.dlc['include'] or 'dlc' not in category.get('scope','').casefold()]
        unavailable=bool(policy.get('selectedId')) and not any(
            category['id']==policy['selectedId'] for category in policy['categories'])
        policy['selectedUnavailable']=unavailable
        if unavailable:
            policy.update(selectedId='',name='',needsSelection=True,
                notice='Choose an available category before creating a new character.')
        return policy
    def display_route(self):
        route=self.context_cfg()['route']
        if self.capture_enabled():
            policy=self.available_run_policy()
            if policy['selectedUnavailable']:return []
            planned=category_route(policy.get('selectedId'),self.catalog)
            if planned is not None:route=planned
        return [boss_id for boss_id in route if boss_id in self.catalog_ids]
    def persist(self):
        temp=self.dir/'settings.tmp'
        temp.write_text(json.dumps(self.cfg,indent=2),encoding='utf-8')
        temp.replace(self.dir/'settings.json')
    def context_cfg(self):
        result=self.cfg['contexts'].setdefault(self.context,{'route':self.default_route.copy()})
        result.setdefault('route',self.default_route.copy())
        result.setdefault('enemyKills',0)
        return result
    def read_save(self):
        with self.lock:
            path=self.cfg['save'];slot=self.cfg['slot'];requested_slot=slot;generation=self.save_generation
            previous=self.profile_snapshot if self.profile_snapshot_path==path else None
        if not path:
            discovered=discover_saves()
            with self.lock:
                if discovered and not self.cfg['save']:
                    self.cfg['save']=discovered[0];self.persist()
                    self.status='Character save found automatically. Connecting…'
                else:self.status='Waiting for Elden Ring to create your character save. Load or create a character in game.'
                self.save_status='waiting'
            return
        try:
            st=Path(path).stat();sig=(path,slot,st.st_mtime_ns,st.st_size)
            if sig==self.signature:
                with self.lock:
                    if self.integrity.begin_update():
                        self.run_policy.observe_roster(file_key(path),self.profiles,process_running=self.game_process=='running')
                        self.integrity.seal()
                return
            data=read_stable(path);ps=profiles(data)
            if not ps:
                with self.lock:
                    if path!=self.cfg['save'] or generation!=self.save_generation:return
                    prefix=file_key(path)+':'
                    for key,record in self.cfg['characters'].items():
                        if key.startswith(prefix):record['active']=False
                    self.stats=None;self.killed=set();self.profiles=[];self.recent=[];self.context='pending'
                    self.manual=None;self.bars=[];self.fight_since=None;self.fight_id=None
                    self.profile_snapshot=[];self.profile_snapshot_path=path;self.updated=None;self.signature=sig
                    self.save_status='waiting';self.status='No saved characters. Create or select a character, then let the game save.'
                    self.tracking_notice='';self.persist()
                    if self.integrity.begin_update():
                        self.run_policy.observe_roster(file_key(path),[],process_running=self.game_process=='running')
                        self.integrity.seal()
                return
            profile,selection_source,selection_status=select_profile(ps,slot,previous)
            slot=profile['slot']
            state=slot_state(data,slot,BOSSES,BST)
            if state['name']!=profile['name'] or state['level']!=profile['level']:
                raise ValueError('Character and profile disagree; waiting for a complete save.')
            with self.lock:
                if path!=self.cfg['save'] or self.cfg['slot']!=requested_slot or generation!=self.save_generation:return
                ctx,notice=resolve_context(self.cfg,path,profile,state,ps,self.default_route)
                if ctx!=self.context:
                    self.killed=set();self.recent=[];self.manual=None;self.bars=[];self.fight_since=None;self.fight_id=None
                    self.combat_metrics.reset()
                    self.tracking_notice=notice
                elif notice:self.tracking_notice=notice
                fresh=set(state['killed'])
                if self.stats is not None and ctx==self.context:
                    newly_killed=fresh-self.killed
                    self.recent=[i for i in dict.fromkeys(sorted(newly_killed)+self.recent) if i in fresh][:4]
                    if self.manual in newly_killed:
                        self.manual=None;self.fight_since=None;self.fight_id=None
                self.context=ctx;self.cfg['slot']=slot;self.profiles=ps;self.killed=fresh
                # Character playtime comes only from this profile's saved clock.
                self.stats={**profile,**state};self.signature=(path,slot,st.st_mtime_ns,st.st_size);self.updated=time.time()
                self.profile_snapshot=ps;self.profile_snapshot_path=path
                if selection_source!='unchanged':
                    self.character_selection_source=selection_source;self.character_selection_status=selection_status
                self.status='Save connected — updates after Elden Ring saves.'
                self.save_status='connected'
                self.context_cfg();self.persist()
                if self.integrity.begin_update():
                    self.run_policy.observe_roster(file_key(path),ps,process_running=self.game_process=='running')
                    self.integrity.seal()
        except Exception as e:
            # A new format or partial write must pause, not terminate the worker
            # or silently replace a good snapshot with guessed progress.
            with self.lock:
                if path!=self.cfg['save'] or generation!=self.save_generation:return
                self.status='Save tracking paused: '+str(e);self.save_status='error';self.signature=None
                self.bars=[];self.manual=None;self.fight_since=None;self.fight_id=None
    def live_tick(self):
        if not self.live_enabled or self.save_status!='connected':
            with self.lock:
                self.combat_metrics.reset();self.eliminations.pause()
            self.live.close();return
        observed_context=self.context
        try:bars,status=self.live.poll()
        except Exception as e:
            self.live.close();bars=[];status='Live reader paused: '+str(e)
        with self.lock:
            if not self.live_enabled or self.save_status!='connected':return
            if observed_context!=self.context:
                self.eliminations.pause();return
            self.live_status=status;self.bars=bars
            npc_status=getattr(self.live,'npc_status',None)
            self.eliminations.update(self.context,getattr(self.live,'npc_session',None),
                getattr(self.live,'npc_samples',None),available=npc_status=='Live enemy data connected.',
                boss_handles=[bar['handle'] for bar in bars])
            targets=getattr(self.live,'combat_bars',None)
            if not isinstance(targets,list) or not targets:targets=bars
            self.combat_metrics.update(self.context,targets,available=self.manual is None and status in ('Live boss data connected.','Live enemy data connected.','Connected — no active boss health bar.'))
            if self.manual is not None:return
            if bars:
                self.last_seen=time.monotonic()
                route=self.display_route()
                identity=match_boss(bars[0]['name'],route,self.killed) or bars[0]['name']
                if identity!=self.fight_id:self.fight_id=identity;self.fight_since=time.monotonic()
            elif time.monotonic()-self.last_seen>2:
                self.fight_id=None;self.fight_since=None
    def external_worker(self):
        reader=None
        try:
            while not self.stop.is_set():
                with self.lock:
                    mode=self.cfg['timingMode'];port=self.cfg['liveSplitPort'];generation=self.timing_generation
                try:
                    game_process='running' if any(name=='eldenring.exe' for _,name in process_list()) else 'absent'
                except Exception:game_process='unknown'
                sample={'connected':False,'configured':False,'note':'Practice timer selected.'}
                if mode=='livesplit':
                    if reader is None or reader.port!=port:
                        if reader:reader.close()
                        reader=LiveSplitReader(port)
                    try:sample=reader.poll()
                    except Exception:sample={'connected':False,'configured':False,'note':'LiveSplit reader unavailable; retrying.'}
                with self.lock:
                    if generation==self.timing_generation:
                        self.external_timer=sample;self.game_process=game_process;self.external_sequence+=1
                        if sample.get('connected') and sample.get('configured'):
                            value=sample.get('gameTimeSeconds')
                            if value!=self.last_game_clock:
                                self.last_game_clock=value;self.game_clock_changed_at=time.monotonic()
                self.stop.wait(.5)
        finally:
            if reader:reader.close()
    def published_category(self, policy=None):
        record=self.external_run.record or {}
        if self.capture_enabled() and record.get('status') in ('running','paused','finished'):
            return record.get('runPolicy',{}).get('categoryId')
        return (policy or self.available_run_policy()).get('selectedId')
    def setup_worker(self):
        while not self.stop.is_set():
            self.launcher.refresh()
            if self.launcher.automatic_tick(lambda:os.startfile('steam://open/main')):
                with self.lock:
                    self.live_enabled=True;self.cfg['liveDetection']=True;self.persist()
                try:self.action({'action':'personalOverlay'})
                except Exception:logging.warning('The game started but the desktop overlay could not be opened. Use Open Personal Overlay in the dashboard.')
            self.stop.wait(1)
    def published_worker(self):
        """Public reference refreshes never hold the game/timing lock during I/O."""
        while not self.stop.is_set():
            with self.lock:
                categories=list(dict.fromkeys([self.published_category(),self.available_run_policy().get('selectedId')]))
            for category in categories:
                if self.stop.is_set():break
                if category:
                    try:self.published_records.refresh(category)
                    except Exception:
                        logging.warning('Published leaderboard refresh is unavailable; timing capture continues.')
            self.stop.wait(1)
    def run_state(self):
        result=self.external_run.snapshot()
        record=self.external_run.record or {}
        result['exportAvailable']=bool(self.recipient_key() is not None and self.cfg['timingMode']=='livesplit' and record.get('runPolicy',{}).get('eligible')
            and self.run_policy.can_export(record.get('contextKey'))
            and not self.integrity.tainted and record.get('localAuditStatus')!='ineligible')
        if not self.capture_enabled():
            result.update(captureStatus='off',captureNotice='The speedrun view is off. No run or boss-attempt times are being recorded.')
        elif self.game_process=='absent' and record.get('status') in ('running','paused'):
            result.update(captureStatus='game-closed',captureNotice='Game closed. LiveSplit/SoulSplitter owns the paused game clock; no offline time is added here.')
        elif result.get('status')=='disconnected' and self.recovery_requested and record:
            result.update(captureStatus='recovering',captureNotice='Restored the last verified record. Waiting for the external timer; missing observations remain marked for review.')
        elif (result.get('status')=='running' and self.game_clock_changed_at is not None
                and time.monotonic()-self.game_clock_changed_at>2):
            result.update(captureStatus='game-time-paused',captureNotice='The external game clock is not advancing. This can occur in menus or loading; the overlay does not guess which screen is open.')
        if not self.run_policy.can_record(self.context):
            result['notice']=(result.get('notice','')+' Recording locked until an observed new character starts the selected run.').strip()
        if self.integrity.tainted:
            result.update(localAuditStatus='ineligible',notice=self.integrity.notice,exportAvailable=False,captureStatus='blocked',captureNotice=self.integrity.notice)
        if self.available_run_policy().get('selectedUnavailable') and record.get('status') != 'finished':
            result.update(captureStatus='blocked', captureNotice='Choose an available run category before recording.')
        return result
    def recipient_key(self):
        return load_recipient(ROOT/'data'/'report-recipient.json')
    def export_run(self):
        if not self.integrity.verify():raise ValueError(self.integrity.notice)
        record=self.external_run.record
        if (self.cfg['timingMode']!='livesplit' or not record or not record.get('runPolicy',{}).get('eligible')
                or not self.run_policy.can_export(record.get('contextKey'))):
            raise ValueError('Timing export is locked. Create a new character while tracking, then begin the selected automatic run.')
        if record.get('localAuditStatus')=='ineligible':
            raise ValueError('This run is locally ineligible. Timing export is blocked; review the recorded integrity events.')
        report=self.external_run.export_text()+'\n'+self.attempts.export_text(
            context=record.get('contextKey'),since=record.get('startedAt'),until=record.get('endedAt'))
        report+='\nPublisher: this local Windows installation. A trusted key fingerprint must be exchanged independently.\n'
        report+=f'Application: {self.build_kind}\nApplication SHA-256: {self.build_fingerprint}\n'
        report+='This signature detects report edits; it does not prove unmodified software, game files or legitimate gameplay.\n'
        if self.integrity.recovery_notice:report+=self.integrity.recovery_notice+'\n'
        public_record=copy.deepcopy(record)
        public_record.pop('buildHistory',None)
        payload=dict(schemaVersion=1,format='tarnished-run',simulation=False,exportedAt=utc(),
            run=public_record,
            attempts=self.attempts.export_records(context=record.get('contextKey'),since=record.get('startedAt'),until=record.get('endedAt')),
            build=export_build(record),reportText=report,
            publishedRecord=self.published_records.snapshot(record.get('runPolicy',{}).get('categoryId')),
            application=dict(kind=self.build_kind,sha256=self.build_fingerprint))
        return create_package(payload,self.integrity.sign_report,self.recipient_key())
    def run(self):
        next_save=0
        while not self.stop.is_set():
            try:
                if time.monotonic()>=next_save:
                    self.read_save();next_save=time.monotonic()+4
                self.live_tick()
            except Exception:
                logging.exception('Tracker cycle paused; retrying')
                with self.lock:
                    self.save_status='error';self.signature=None;self.bars=[]
                    self.status='Tracking paused after an unexpected reader error. Retrying automatically.'
                    self.combat_metrics.reset()
            with self.lock:
                trusted=self.integrity.begin_update()
                if not trusted:
                    self.stop.wait(.5)
                    continue
                ready=self.stats is not None and self.save_status=='connected'
                self.run_policy.observe(self.context,self.stats,self.killed,ready,save_key=file_key(self.cfg['save']) if self.cfg['save'] else None)
                ready=self.stats is not None and self.save_status=='connected'
                try:
                    if self.external_sequence!=self.external_observed:
                        self.external_observed=self.external_sequence
                        if self.cfg['timingMode']=='livesplit':
                            self.run_policy.observe_timer(self.external_timer)
                            previous_record=(self.external_run.record or {}).get('recordId')
                            previous_status=(self.external_run.record or {}).get('status')
                            category_available=not self.available_run_policy().get('selectedUnavailable')
                            self.external_run.observe(self.external_timer,self.context,self.stats,self.killed,BOSS_NAMES,
                                ready,self.game_process,start_audit=self.run_policy.audit_for_start(self.context,self.external_timer),
                                capture_enabled=self.capture_enabled() and category_available)
                            if self.external_run.record and self.external_run.record['recordId']!=previous_record:
                                self.run_policy.mark_started(self.context)
                            if self.capture_enabled() and category_available and observe_build(
                                    self.external_run.record,self.stats,self.context,ready,saved_at=self.updated,
                                    allow_finished=previous_status in ('running','paused'),
                                    timer_current=ExternalRun._sample_valid(self.external_timer) and
                                        [self.external_timer.get(k) for k in ('attemptCount','gameName','categoryName')]
                                        ==(self.external_run.record or {}).get('identity')):
                                self.external_run._save(time.monotonic())
                    if self.capture_enabled() and self.run_policy.can_record(self.context) and (self.external_run.record or {}).get('status') in ('running','paused'):
                        self.attempts.observe(self.context,self.stats,self.killed,self.bars,ready,
                            live_available=self.live_enabled and self.manual is None and self.live_status in ('Live boss data connected.','Connected — no active boss health bar.'),
                            process_state=self.game_process,boss_resolver=lambda name:match_boss(name,[],self.killed),boss_names=BOSS_NAMES,
                            category_key=self.run_policy.snapshot().get('selectedId'))
                    elif self.attempts.snapshot().get('active'):
                        self.attempts.interrupt('Recording context changed or eligibility was lost.')
                except Exception:logging.exception('Encounter observations paused; keeping save tracking active.')
                self.integrity.seal()
            self.stop.wait(.5)
        with self.lock:
            if self.integrity.begin_update():
                self.attempts.interrupt('Tracker closed; attempt timing stopped without inferring a result.')
                if self.shutdown_reason!='unexpected':
                    record=self.external_run.record or {}
                    active_context=record.get('contextKey') if record.get('status') in ('running','paused') else None
                    self.external_run.suspend_capture('The app was closed intentionally. Observation ended; a new recording requires a fresh character.')
                    self.run_policy.set_capture_enabled(False,context=active_context)
                self.integrity.seal()
        self.live.close()
    def state(self):
        with self.lock:
            route=self.display_route();current=None;policy=self.available_run_policy()
            if self.live_enabled and self.bars and self.save_status=='connected':
                bar=self.bars[0];bid=match_boss(bar['name'],route,self.killed)
                current={**(BY_ID.get(bid,{}) if bid else {}),**bar,'source':'Live game data'}
                current['combat']=COMBAT.for_boss(bid,bar['name']) if bid else COMBAT.for_live_name(bar['name'])
                if bid is None:
                    current['identityStatus']='Boss name and HP are live; the exact catalog encounter is ambiguous.'
                    current['portrait']=shared_boss_portrait(bar['name'])
            current_id=current.get('id') if current else None
            next_ids=[i for i in route if i not in self.killed and i!=current_id]
            return dict(bosses=self.catalog,catalogBossIds=list(BY_ID),presets=self.presets,
                route=route if self.capture_enabled() else list(self.context_cfg()['route']),
                killed=sorted(self.killed & self.catalog_ids),dlc=dict(self.dlc),
                stats=self.stats,profiles=self.profiles,save=self.cfg['save'],slot=self.cfg['slot'],
                characterSelectionSource=self.character_selection_source,characterSelectionStatus=self.character_selection_status,
                status=self.status,saveStatus=self.save_status,contextKey=self.context,trackingNotice=self.tracking_notice,
                updated=self.updated,liveEnabled=self.live_enabled,liveStatus=self.live_status,
                setup=self.launcher.snapshot(),
                liveCharacterVerified=False,
                current=current,otherBars=self.bars[1:] if self.live_enabled else [],
                fightSeconds=int(time.monotonic()-self.fight_since) if self.fight_since and current else 0,
                upcoming=[BY_ID[i] for i in next_ids[:8]] if self.save_status=='connected' else [],recent=[BY_ID[i] for i in self.recent if i in self.catalog_ids],
                completed=sum(i in self.killed for i in route),total=len(route),catalogKilled=len(self.killed & self.catalog_ids),
                enemyKills=self.eliminations.snapshot(self.context)['total'],eliminations=self.eliminations.snapshot(self.context),
                eliminationReaderStatus=getattr(self.live,'npc_status',None) if isinstance(getattr(self.live,'npc_status',None),str) else 'Waiting for live enemy data.',
                showCharacterName=bool(self.cfg.get('showCharacterName',True)),
                overlayView=self.cfg.get('overlayView','home'),combatMetrics=self.combat_metrics.snapshot(),speedrun=self.run_state(),
                bossAttempts=self.attempts.snapshot() if self.capture_enabled() and self.run_policy.can_export(self.context) and not self.integrity.tainted else {},
                routeManaged=self.capture_enabled() and bool(self.run_policy.snapshot().get('selectedId')),
                runPolicy=policy,publishedRecord=self.published_records.snapshot(self.published_category(policy)),
                recordIntegrity=dict(locked=self.integrity.tainted,notice=self.integrity.notice,fingerprint=self.integrity.public_fingerprint),
                timingMode=self.cfg['timingMode'],liveSplitPort=self.cfg['liveSplitPort'],reportExport=export_status(self.recipient_key()),
                externalTimer=self.external_timer,gameProcess=self.game_process,
                layout=self.cfg.get('layout',{'width':360,'opacity':0.72,'font':'Cinzel','icons':8}),
                saves=discover_saves(),ready=self.stats is not None and self.save_status=='connected',liveVersion=PROFILE['version'])
    def action(self,payload):
        # Game startup/file dialogs must not hold the timing or integrity lock.
        if isinstance(payload,dict) and payload.get('action') in ('requestPlay','launchOffline','locateGame','rescanSetup','openSteam','openGameFolder'):
            op=payload['action']
            if self.stop.is_set():raise ValueError('The companion is closing.')
            if op=='requestPlay':
                self.launcher.request_play()
            elif op=='launchOffline':
                self.launcher.launch()
                with self.lock:
                    self.live_enabled=True;self.cfg['liveDetection']=True;self.live_status='Checking the launched session…';self.persist()
            elif op=='locateGame':
                import tkinter as tk
                from tkinter import filedialog
                root=tk.Tk();root.withdraw();root.attributes('-topmost',True)
                try:path=filedialog.askopenfilename(title='Locate installed Elden Ring',filetypes=[('Elden Ring','eldenring.exe')])
                finally:root.destroy()
                if path:self.launcher.select(path)
            elif op=='rescanSetup':
                self.launcher.use_installation(detect_dlc());self.launcher.refresh()
            elif op=='openSteam':
                os.startfile('steam://open/main')
            elif op=='openGameFolder':
                folder=self.launcher.snapshot().get('gamePath')
                if not folder or not Path(folder).is_dir():raise ValueError('Locate Elden Ring first.')
                os.startfile(folder)
            return
        with self.lock:
            trusted=self.integrity.begin_update()
            if not trusted and isinstance(payload,dict) and payload.get('action') in ('speedrun','runCategory','timingMode'):
                raise ValueError(self.integrity.notice)
            try:return self._action(payload)
            finally:
                if trusted:self.integrity.seal()
    def _action(self,payload):
        with self.lock:
            if not isinstance(payload,dict):raise ValueError('Expected a JSON action object.')
            op=payload.get('action')
            if op in ('save','browse','live','resetTracking'):self.combat_metrics.reset()
            if op in ('route','enemyKills','resetTracking'):
                if not self.stats or self.save_status!='connected':raise ValueError('Connect a valid save before changing character tracking.')
                if payload.get('contextKey',self.context)!=self.context:raise ValueError('The character or journey changed. Review the current character before saving.')
            if op=='overlayView':
                view=payload.get('view')
                if view not in ('home','combat','speedrun'):raise ValueError('Choose a valid overlay view.')
                if view!=self.cfg.get('overlayView'):
                    record=self.external_run.record or {}
                    active_context=record.get('contextKey') if record.get('status') in ('running','paused') else None
                    if not self.integrity.tainted:
                        self.run_policy.set_capture_enabled(view=='speedrun',context=active_context)
                        if view!='speedrun':
                            self.external_run.suspend_capture('Speedrun view closed. Timing observation ended automatically.')
                            self.attempts.interrupt('Speedrun view closed. Attempt observation ended.')
                    self.cfg['overlayView']=view;self.persist()
            elif op=='openDashboard':
                webbrowser.open(f'http://127.0.0.1:{self.port}/#speedrun-category')
            elif op=='runCategory':
                record=self.external_run.record
                if record and record.get('status') in ('running','paused'):
                    raise ValueError('The category is fixed for this run. Finish or reset in LiveSplit before selecting another.')
                requested=payload.get('categoryId')
                category=next((item for item in self.run_policy.snapshot()['categories'] if item['id']==requested),None)
                if category and not self.dlc['include'] and 'dlc' in category.get('scope','').casefold():
                    raise ValueError('Choose a category available for the detected game content.')
                self.run_policy.select(payload.get('categoryId'),payload.get('customName'))
            elif op=='timingMode':
                mode=payload.get('mode');port=payload.get('port',self.cfg['liveSplitPort'])
                if mode!='livesplit':raise ValueError('Only automatic LiveSplit/SoulSplitter timing is supported.')
                if type(port) is not int or not 1024<=port<=65535:raise ValueError('LiveSplit port must be between 1024 and 65535.')
                self.cfg['timingMode']=mode;self.cfg['liveSplitPort']=port;self.timing_generation+=1
                self.external_timer={'connected':False,'configured':False,'note':'Timing source changed; waiting for a fresh connection.'}
                self.external_sequence+=1;self.persist()
            elif op=='speedrun':
                raise ValueError('LiveSplit controls this timer automatically. Manual timer actions are disabled.')
            elif op=='save':
                path=str(payload.get('path','')).strip().strip('"')
                if Path(path).suffix.lower() not in ('.sl2','.co2'):raise ValueError('Choose a .sl2 or .co2 file.')
                if not Path(path).is_file():raise ValueError('Save file not found.')
                slot=payload.get('slot',0)
                if type(slot) is not int or not 0<=slot<10:raise ValueError('Choose a valid character slot.')
                self.cfg['save']=path;self.cfg['slot']=slot
                self.signature=None;self.stats=None;self.killed=set();self.profiles=[];self.context='pending';self.manual=None
                self.profile_snapshot=None;self.profile_snapshot_path=None;self.save_generation+=1
                self.character_selection_source='selected-character';self.character_selection_status='Loading the selected character. Automatic following begins with the next saved playtime change.'
                self.live_enabled=self.cfg['liveDetection'];self.bars=[];self.fight_id=None;self.fight_since=None
                self.status='Loading selected save…';self.save_status='waiting';self.updated=None;self.recent=[];self.tracking_notice='';self.persist()
            elif op=='browse':
                import tkinter as tk
                from tkinter import filedialog
                root=tk.Tk();root.withdraw();root.attributes('-topmost',True)
                try:path=filedialog.askopenfilename(title='Choose Elden Ring save',filetypes=[('Elden Ring saves','*.sl2 *.co2'),('All files','*.*')])
                finally:root.destroy()
                if path:
                    self.cfg['save']=path;self.cfg['slot']=int(payload.get('slot',0))
                    self.signature=None;self.stats=None;self.killed=set();self.profiles=[];self.context='pending';self.manual=None
                    self.profile_snapshot=None;self.profile_snapshot_path=None;self.save_generation+=1
                    self.character_selection_source='selected-character';self.character_selection_status='Loading the selected character. Automatic following begins with the next saved playtime change.'
                    self.live_enabled=self.cfg['liveDetection'];self.bars=[];self.fight_id=None;self.fight_since=None
                    self.status='Loading selected save…';self.save_status='waiting';self.updated=None;self.recent=[];self.tracking_notice='';self.persist()
            elif op=='route':
                if self.capture_enabled():raise ValueError('The speedrun category controls this lineup. Switch to Home to edit your personal lineup.')
                route=payload.get('route')
                if not isinstance(route,list) or len(route)>len(BOSSES) or any(type(i)!=int or i not in BY_ID for i in route) or len(set(route))!=len(route):raise ValueError('Route contains invalid or duplicate bosses.')
                if not self.stats:raise ValueError('Connect a valid save before editing a character route.')
                previous=set(self.context_cfg()['route'])
                if any(i not in self.catalog_ids and i not in previous for i in route):
                    raise ValueError('Only currently available encounters can be added to the lineup.')
                self.context_cfg()['route']=list(route);self.persist()
            elif op=='rescanDlc':
                self._refresh_catalog()
            elif op=='live':
                self.live_enabled=bool(payload.get('enabled'));self.manual=None;self.bars=[];self.fight_since=None;self.fight_id=None
                self.cfg['liveDetection']=self.live_enabled;self.persist()
                self.live_status='Checking offline session…' if self.live_enabled else 'Off — use only with EAC disabled and the game offline.'
            elif op=='manual':
                raise ValueError('Boss encounters are detected automatically. Manual fight actions are disabled.')
            elif op=='enemyKills':
                raise ValueError('Manual enemy kill counting has been removed.')
            elif op=='resetTracking':
                record=self.cfg['characters'].get(slot_key(self.cfg['save'],self.cfg['slot']))
                if record:record['active']=False
                self.save_generation+=1;self.signature=None;self.profile_snapshot=None
                self.manual=None;self.bars=[];self.fight_since=None;self.fight_id=None;self.recent=[]
                self.save_status='waiting';self.status='Starting fresh local tracking from the selected character’s save…';self.persist()
            elif op=='showCharacterName':
                self.cfg['showCharacterName']=bool(payload.get('enabled'));self.persist()
            elif op=='personalOverlay':
                if self.stop.is_set():raise ValueError('The app is closing.')
                if self.overlay_process is None or self.overlay_process.poll() is not None:
                    if self.overlay_process is not None and self.overlay_process.stdin is not None:self.overlay_process.stdin.close()
                    if getattr(sys,'frozen',False):cmd=[sys.executable,'--personal-overlay','--port',str(self.port)]
                    else:cmd=[sys.executable,str(Path(__file__).resolve()),'--personal-overlay','--port',str(self.port)]
                    cmd.append('--owned-overlay')
                    self.overlay_process=subprocess.Popen(cmd,close_fds=True,stdin=subprocess.PIPE,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            elif op=='layout':
                layout=payload.get('layout',{})
                width=layout.get('width');opacity=layout.get('opacity');font=layout.get('font');icons=layout.get('icons')
                if type(width)!=int or not 280<=width<=600:raise ValueError('Panel width must be 280–600 pixels.')
                if type(opacity) not in (int,float) or not 0.35<=opacity<=0.95:raise ValueError('Opacity must be between 35% and 95%.')
                if font not in ('Cinzel','Georgia','System'):raise ValueError('Choose a supported font.')
                if type(icons)!=int or icons not in (4,6,8):raise ValueError('Choose 4, 6, or 8 lineup icons.')
                animate=layout.get('animateGlow',self.cfg['layout'].get('animateGlow',True))
                if type(animate) is not bool:raise ValueError('Animation setting must be on or off.')
                traits=layout.get('showBossTraits',self.cfg['layout'].get('showBossTraits',True))
                if type(traits) is not bool:raise ValueError('Boss traits setting must be on or off.')
                self.cfg['layout']={'width':width,'opacity':float(opacity),'font':font,'icons':icons,'animateGlow':animate,'showBossTraits':traits};self.persist()
            elif op=='refresh':self.signature=None
            elif op=='stop':self.shutdown_reason='requested-stop';self.stop.set()
            else:raise ValueError('Unknown action.')

def serve(tracker,port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def allowed(self):return self.headers.get('Host') in (f'127.0.0.1:{port}',f'localhost:{port}')
        def reply(self,code,body,kind='application/json'):
            raw=body.encode('utf-8') if isinstance(body,str) else body
            self.send_response(code);self.send_header('Content-Type',kind+'; charset=utf-8')
            self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
            try:self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError):pass
        def do_GET(self):
            if not self.allowed():return self.reply(403,'{}')
            path=urlparse(self.path).path
            if path=='/preview':return self.reply(200,(ROOT/'preview.html').read_text(encoding='utf-8'),'text/html')
            if path in ('/preview/overlay','/api/preview/state'):
                from preview_states import preview_state, SCENES
                scene=parse_qs(urlparse(self.path).query).get('scene',['home'])[0]
                try:state=preview_state(scene,tracker.catalog)
                except ValueError:return self.reply(404,'{}')
                if path=='/api/preview/state':return self.reply(200,json.dumps(state))
                html=(ROOT/'overlay.html').read_text(encoding='utf-8').replace('__TOKEN__','preview-only')
                html=html.replace('/api/state','/api/preview/state?scene='+scene)
                html=html.replace('/api/speedrun/export','/api/preview/export')
                return self.reply(200,html,'text/html')
            if path=='/api/preview/export':
                from preview_states import preview_state
                try:report=sample_package(tracker.recipient_key(),preview_state('finished',tracker.catalog))
                except ValueError as error:return self.reply(400,json.dumps({'error':str(error)}))
                return self.reply(200,report,REPORT_MIME)
            if path in ('/app-icon.svg','/favicon.ico'):
                name='app-icon.svg' if path.endswith('.svg') else 'app-icon.ico'
                return self.reply(200,(ROOT/'assets'/name).read_bytes(),'image/svg+xml' if name.endswith('.svg') else 'image/x-icon')
            if path=='/api/state':return self.reply(200,json.dumps(tracker.state()))
            if path=='/api/speedrun/export':
                try:
                    with tracker.lock:report=tracker.export_run()
                except ValueError as error:return self.reply(400,json.dumps({'error':str(error)}))
                return self.reply(200,report,REPORT_MIME)
            if path=='/health':return self.reply(200,'{"app":"TarnishedCompanion"}')
            if path.startswith('/portraits/'):
                name=Path(path).name
                if name not in {Path(v['src']).name for v in PORTRAITS.values()}:return self.reply(404,'{}')
                image=ROOT/'data'/'portraits'/name
                if not image.is_file():return self.reply(404,'{}')
                return self.reply(200,image.read_bytes(),'image/jpeg' if image.suffix.lower()=='.jpg' else 'image/png')
            if path in ('/fonts/Cinzel.ttf','/fonts/OFL.txt'):
                font=ROOT/'fonts'/Path(path).name
                if not font.is_file():return self.reply(404,'{}')
                return self.reply(200,font.read_bytes(),'font/ttf' if font.suffix.lower()=='.ttf' else 'text/plain')
            if path in ('/','/overlay'):
                file='ui.html' if path=='/' else 'overlay.html'
                html=(ROOT/file).read_text(encoding='utf-8').replace('__TOKEN__',tracker.token)
                if file=='ui.html':
                    legend=ROOT/'data'/'combat-icon-legend.html'
                    html=html.replace('__COMBAT_LEGEND__',legend.read_text(encoding='utf-8') if legend.is_file() else '')
                return self.reply(200,html,'text/html')
            self.reply(404,'{}')
        def do_POST(self):
            if not self.allowed() or self.path!='/api/action' or self.headers.get('X-Tracker-Token')!=tracker.token:return self.reply(403,'{}')
            origin=self.headers.get('Origin')
            if origin and origin not in (f'http://127.0.0.1:{port}',f'http://localhost:{port}'):return self.reply(403,'{}')
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=16384:raise ValueError('Invalid request size.')
                tracker.action(json.loads(self.rfile.read(length)))
                self.reply(200,'{"ok":true}')
            except (ValueError,TypeError,KeyError,OSError) as e:self.reply(400,json.dumps({'error':str(e)}))
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True
    return server

def run_personal_overlay(port,owned=False):
    """Show the exact OBS overlay page in a frameless, transparent, always-on-top window."""
    try:
        from desktop_overlay import run
        run(port,ROOT,owned=owned)
    except Exception as error:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,
            'Personal Overlay could not start. Make sure Microsoft Edge WebView2 Runtime is installed.\n\n'+str(error),
            'Tarnished Companion',0x10)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--no-browser',action='store_true');parser.add_argument('--port',type=int,default=18473);parser.add_argument('--data-dir');parser.add_argument('--personal-overlay',action='store_true')
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--recover',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--owned-overlay',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--no-game-launch',action='store_true',help='Open the dashboard without automatically launching Elden Ring (development/testing).')
    parser.add_argument('--prepare-offline-setup',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.prepare_offline_setup:
        try:prepare_installed_game(PROFILE,detect_dlc());return 0
        except (OSError,ValueError):return 2
    if args.personal_overlay:
        run_personal_overlay(args.port,owned=args.owned_overlay);return 0
    d=args.data_dir or str(default_data_dir())
    from app_supervisor import run_supervised, existing_instance
    from app_lifecycle import begin_session, mark_clean_exit, supervisor_stop_requested, RECOVER_ENV
    if existing_instance(args.port):
        if not args.worker and not args.no_game_launch:request_existing_play(args.port)
        if not args.no_browser:webbrowser.open(f'http://127.0.0.1:{args.port}/preview')
        if args.worker:mark_clean_exit('already-running')
        return 0
    if not args.worker:
        command=[sys.executable]
        if not getattr(sys,'frozen',False):command.append(str(Path(__file__).resolve()))
        command.extend(sys.argv[1:]);command.append('--worker')
        return run_supervised(command,args.port,d)
    session=begin_session(d)
    recover=args.recover or session['previousUnclean'] or os.environ.get(RECOVER_ENV)=='1'
    tracker=Tracker(d,recover_interrupted=recover)
    tracker.port=args.port
    if not args.no_game_launch:tracker.launcher.request_play()
    try:server=serve(tracker,args.port)
    except OSError:
        if existing_instance(args.port):
            mark_clean_exit('already-running');return 0
        logging.exception('The local port %s is unavailable.',args.port)
        return 1
    tracking_thread=threading.Thread(target=tracker.run,daemon=True);tracking_thread.start()
    external_thread=threading.Thread(target=tracker.external_worker,daemon=True);external_thread.start()
    published_thread=threading.Thread(target=tracker.published_worker,daemon=True);published_thread.start()
    setup_thread=threading.Thread(target=tracker.setup_worker,daemon=True);setup_thread.start()
    server_thread=threading.Thread(target=server.serve_forever,daemon=True);server_thread.start()
    if not args.no_browser:webbrowser.open(f'http://127.0.0.1:{args.port}/preview')
    try:
        while not tracker.stop.wait(.5):
            if supervisor_stop_requested():
                tracker.shutdown_reason='parent-stop';tracker.stop.set();break
            if not all(thread.is_alive() for thread in (tracking_thread,external_thread,server_thread)):
                raise RuntimeError('An app worker stopped unexpectedly.')
    except KeyboardInterrupt:
        tracker.shutdown_reason='keyboard-interrupt';tracker.stop.set()
    except Exception:
        logging.exception('App worker ended unexpectedly; requesting supervised recovery.')
    finally:
        tracker.stop.set()
        overlay_stopped=tracker.close_personal_overlay()
        server.shutdown();server.server_close()
        tracking_thread.join(timeout=10);external_thread.join(timeout=3);server_thread.join(timeout=2)
        published_thread.join(timeout=6)
        setup_thread.join(timeout=2)
    if overlay_stopped and tracker.shutdown_reason!='unexpected' and not any(thread.is_alive() for thread in (tracking_thread,external_thread,server_thread)):
        mark_clean_exit(tracker.shutdown_reason);return 0
    return 1

if __name__=='__main__':sys.exit(main())
