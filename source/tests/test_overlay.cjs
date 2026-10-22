// Run with: node source/tests/test_overlay.cjs
// Test rendered data decisions without requiring a browser or a game session.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const elements = new Map();
const animationRequests = [];
let motionChanged;
const motionPreference = {matches: false, addEventListener(name, callback) {motionChanged = callback;}};
function element(id) {
  if (!elements.has(id)) {
    const classes = new Set();
    const attributes = new Map();
    elements.set(id, {
      innerHTML: '', textContent: '', className: '',
      style: {setProperty() {}},
      classList: {
        toggle(name, enabled) {if (enabled) classes.add(name); else classes.delete(name);},
        contains(name) {return classes.has(name);},
      },
      setAttribute(name, value) {attributes.set(name, value);},
      removeAttribute(name) {attributes.delete(name);},
      getAttribute(name) {return attributes.get(name);},
      getBoundingClientRect() {return {height: 400};},
    });
  }
  return elements.get(id);
}
const sandbox = vm.createContext({
  document: {
    getElementById: element,
    querySelector: element,
    documentElement: element('document'),
    fonts: {ready: {then() {}}},
    addEventListener() {},
  },
  window: {
    innerWidth: 360, addEventListener() {}, matchMedia() {return motionPreference;},
    pywebview: {api: {set_animation_active(active) {animationRequests.push(active); return Promise.resolve();}}},
  },
  ResizeObserver: class {observe() {}},
  requestAnimationFrame() {},
  setInterval() {},
  async fetch() {throw new Error('Synthetic disconnected startup');},
});
const html = fs.readFileSync(path.join(__dirname, '..', 'overlay.html'), 'utf8');
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], sandbox);
const call = code => vm.runInContext(code, sandbox);

async function main() {
// Let the initial request settle, so later tests can drive normal polling.
await call('Promise.resolve()');
assert.equal(call('fightTime(75)'), '1:15');
assert.equal(call('fightTime(3600)'), '1:00:00');
assert.equal(call('fightTime(-3)'), '0:00');
assert.equal(call('fmt(271999)'), '75:33:19');
for (const value of ['null', '{hp:null,maxHp:null}', '{hp:10,maxHp:0}', '{hp:101,maxHp:100}', '{hp:-1,maxHp:100}', '{hp:NaN,maxHp:100}', '{hp:Infinity,maxHp:100}', '{hp:"65",maxHp:100}']) {
  assert.equal(call(`bossHealth(${value})`), null, `Unknown/invalid HP must not become real HP: ${value}`);
}
assert.equal(call('bossHealth({hp:0,maxHp:100}).percent'), 0);
assert.equal(call('bossHealth({hp:6500,maxHp:10000}).percent'), 65);

sandbox.state = {
  current: {id: 1, name: 'Boss <&>', portrait: '/portraits/1.jpg', source: 'Live game data', hp: 6500, maxHp: 10000},
  fightSeconds: 75,
  stats: {level: 42, runes: 12345, origin: 'Hero', seconds: 123},
};
call('renderEncounter(state)');
assert.equal(element('hpFill').style.width, '65%');
assert.equal(element('hpPercent').textContent, '65%');
assert.equal(element('hpTrack').getAttribute('aria-valuenow'), '65');
assert.equal(element('fightTime').textContent, '1:15');
assert.equal(element('fightLevel').textContent, 42);
assert.equal(element('fightRunes').textContent, (12345).toLocaleString());
assert.match(element('main').innerHTML, /Boss &lt;&amp;&gt;/);
assert.equal(element('hpNote').textContent, `${(6500).toLocaleString()} / ${(10000).toLocaleString()} HP`);

// Damage, inflicted statuses, and received-damage weaknesses remain separate.
assert.match(element('combatTraits').innerHTML, /Combat details unverified/);
sandbox.state.current.combat = {
  deals: ['standard','strike','slash','pierce','fire','fire'], inflicts: ['frost'],
  weakTo: ['pierce','magic'], phaseLabel: 'Phase <2>', note: 'Changes <&> by phase',
};
call('renderEncounter(state)');
let traits = element('combatTraits').innerHTML;
assert.match(traits, /aria-label="Deals: Physical · damage"/);
assert.doesNotMatch(traits, /Deals: (Standard|Strike|Slash|Pierce)/);
assert.equal((traits.match(/aria-label="Deals: Fire/g)||[]).length, 1, 'Duplicate damage types must not duplicate icons');
assert.match(traits, /aria-label="Inflicts: Frostbite · status effect"/);
assert.doesNotMatch(traits, /Deals: Frostbite/);
assert.match(traits, /aria-label="Weak to: Pierce · damage"/);
assert.match(traits, /aria-label="Weak to: Magic · elemental damage"/);
assert.match(traits, /Phase &lt;2&gt;/);
assert.match(traits, /Changes &lt;&amp;&gt; by phase/);
assert.match(traits, /Lowest damage negation/);
assert.match(traits, /status-effect/);

// A phase can change reference data while the catalog boss ID stays the same.
sandbox.state.current.combat = {deals:['holy'], inflicts:[], weakTo:[]};
call('renderEncounter(state)');
traits = element('combatTraits').innerHTML;
assert.match(traits, /Deals: Holy/);
assert.doesNotMatch(traits, /Deals: Fire|Frostbite|Phase &lt;2&gt;/);
assert.match(traits, /No clear weakness/);
assert.doesNotMatch(traits, />Inflicts</);
sandbox.state.current.combat.weakTo = null;
sandbox.state.current.combat.deals = null;
call('renderEncounter(state)');
assert.match(element('combatTraits').innerHTML, /Unverified/);
assert.doesNotMatch(element('combatTraits').innerHTML, /No clear weakness|<svg/);

// Only recognized keys can become SVG markup, and statuses cannot become elements.
sandbox.state.current.combat = {deals:['frost','__proto__','<img onerror="bad">'], weakTo:['bleed']};
call('renderEncounter(state)');
assert.doesNotMatch(element('combatTraits').innerHTML, /<svg|onerror|Frostbite|Hemorrhage/);
assert.match(element('combatTraits').innerHTML, /Unverified/);
sandbox.state.current.combat = {deals:['fire'], weakTo:['magic']};
sandbox.state.layout = {showBossTraits:false};
call('renderEncounter(state)');
assert.equal(element('combatTraits').hidden, true);
assert.equal(element('combatTraits').innerHTML, '');
sandbox.state.layout.showBossTraits = true;
call('renderEncounter(state)');
assert.equal(element('combatTraits').hidden, false);
assert.match(element('combatTraits').innerHTML, /Deals: Fire/);
const knownFight = sandbox.state.current;
sandbox.state.current = {id:2, name:'Unmapped boss', source:'Live game data', hp:50, maxHp:100};
call('renderEncounter(state)');
assert.match(element('combatTraits').innerHTML, /Combat details unverified/);
assert.doesNotMatch(element('combatTraits').innerHTML, /<svg|Fire|Magic/);
sandbox.state.current = knownFight;
call('renderEncounter(state)');

// Missing data must clear the previous real value rather than display 0% or retain 65%.
sandbox.state.current.hp = null;
sandbox.state.current.source = 'Manual fight';
call('renderEncounter(state)');
assert.equal(element('health').classList.contains('unavailable'), true);
assert.equal(element('hpPercent').textContent, '—');
assert.equal(element('hpTrack').getAttribute('aria-valuenow'), undefined);
assert.equal(element('hpNote').textContent, 'Manual fight · live HP unavailable');
assert.equal(element('fightLabel').textContent, 'Manual fight');

// Even accidentally provided manual-preview numbers must never masquerade as live HP.
sandbox.state.current.hp = 0;
call('renderEncounter(state)');
assert.equal(element('health').classList.contains('unavailable'), true);
assert.equal(element('hpPercent').textContent, '—');

// Zero HP from a live source is known health, unlike missing data.
sandbox.state.current.source = 'Live game data';
call('renderEncounter(state)');
assert.equal(element('health').classList.contains('unavailable'), false);
assert.equal(element('hpPercent').textContent, '0%');
assert.equal(element('hpTrack').getAttribute('aria-valuenow'), '0');

// Only the active/selected character's saved time is shown, even with other profiles and a long fight.
sandbox.state.current = null;
sandbox.state.fightSeconds = 999999;
sandbox.state.profiles = [{seconds: 888888}, {seconds: 123}];
call('renderEncounter(state)');
assert.match(element('idleDetails').innerHTML, /Character playtime 0:02:03$/);
sandbox.state.stats = {level: 7, origin: 'Warrior', runes: 0, seconds: 3601};
call('renderEncounter(state)');
assert.equal(element('idleLevel').textContent, 'Level 7 · Warrior');
assert.match(element('idleDetails').innerHTML, /Character playtime 1:00:01$/);
sandbox.state.stats = null;
call('renderEncounter(state)');
assert.equal(element('idleLevel').textContent, 'Waiting for character');
assert.equal(element('idleDetails').innerHTML, 'Connect a save file to show character stats');

// Shared page drives native capture cadence only while a portrait actually animates.
sandbox.state = {
  current: {id: 1, name: 'Boss', portrait: '/portraits/1.jpg', source: 'Live game data', hp: 65, maxHp: 100},
  fightSeconds: 75,
  stats: {name: 'Character', level: 42, runes: 12345, origin: 'Hero', seconds: 123, deaths: 4, journey: 2},
  bosses: [{id: 1}], catalogKilled: 0, enemyKills: 2, upcoming: [],
  layout: {width: 360, opacity: .72, font: 'Cinzel', icons: 8},
  saveStatus: 'connected', ready: true, updated: Math.floor(Date.now() / 1000) - 65,
};
call('renderState(state)');
assert.equal(element('.card').classList.contains('animate-glow'), true);
assert.equal(animationRequests.at(-1), true);
assert.equal(element('journey').textContent, 'Journey 2');
assert.equal(element('sourceStatus').textContent, 'Saved 1m ago');
assert.match(element('main').innerHTML, /portrait-frame/);
const requestsBeforeRepeat = animationRequests.length;
call('renderState(state)');
assert.equal(animationRequests.length, requestsBeforeRepeat, 'Unchanged mode must not spam the native bridge');

motionPreference.matches = true;
motionChanged();
assert.equal(element('.card').classList.contains('animate-glow'), false);
assert.equal(animationRequests.at(-1), false);
motionPreference.matches = false;
motionChanged();
assert.equal(animationRequests.at(-1), true);
sandbox.state.layout.animateGlow = false;
call('renderState(state)');
assert.equal(element('.card').classList.contains('animate-glow'), false);
assert.equal(animationRequests.at(-1), false);
sandbox.state.layout.animateGlow = true;
sandbox.state.current = null;
call('renderState(state)');
assert.equal(animationRequests.at(-1), false, 'Idle page stays at the low capture cadence');
sandbox.state.current = {id: 1, name: 'Boss', source: 'Live game data', hp: 65, maxHp: 100};
call('renderState(state)');
assert.equal(element('.card').classList.contains('animate-glow'), false, 'No portrait means nothing to animate');
sandbox.state.current.portrait = '/portraits/1.jpg';
call('renderState(state)');
assert.equal(animationRequests.at(-1), true);

sandbox.state.saveStatus = 'error';
sandbox.state.ready = false;
call('renderState(state)');
assert.equal(element('sourceStatus').textContent, 'Save issue');
assert.equal(element('sourceStatus').classList.contains('warning'), true);
assert.equal(element('.card').classList.contains('animate-glow'), false);
assert.equal(animationRequests.at(-1), false);
assert.equal(element('hpPercent').textContent, '—');
assert.equal(element('fightLabel').textContent, 'Last fight');
assert.match(element('lineup').innerHTML, /Tracking paused/);
assert.equal(element('bosses').textContent, '—');
sandbox.state.current.source = 'Manual fight';
call('renderState(state)');
assert.equal(element('fightLabel').textContent, 'Manual fight');
assert.equal(element('hpPercent').textContent, '—');
assert.equal(element('hpNote').textContent, 'Waiting for valid save data');
assert.equal(element('fightTime').textContent, '—');
assert.equal(element('.card').classList.contains('animate-glow'), false);
sandbox.state.current.source = 'Live game data';

// Same empty lineup must redraw when readiness changes, despite identical boss IDs.
sandbox.state.saveStatus = 'waiting';
call('renderState(state)');
assert.equal(element('sourceStatus').textContent, 'Waiting for save');
assert.match(element('lineup').innerHTML, /Waiting for save/);
assert.doesNotMatch(element('lineup').innerHTML, /Lineup complete/);
sandbox.state.saveStatus = 'connected';
call('renderState(state)');
assert.match(element('lineup').innerHTML, /Waiting for save/);
assert.equal(element('.card').classList.contains('animate-glow'), false, 'An explicit ready:false overrides a connected status');
sandbox.state.ready = true;
call('renderState(state)');
assert.match(element('lineup').innerHTML, /Lineup complete/);
assert.equal(element('bosses').textContent, '0/1');
assert.equal(element('.card').classList.contains('animate-glow'), true);

// Startup has no imported totals and cannot report route completion.
const readyState = sandbox.state;
sandbox.state = {...readyState, stats: null, current: null, ready: false, saveStatus: 'waiting'};
call('renderState(state)');
assert.equal(element('bosses').textContent, '—');
assert.equal(element('kills').textContent, '—');
assert.equal(element('deaths').textContent, '—');
assert.match(element('lineup').innerHTML, /Waiting for save/);
assert.doesNotMatch(element('lineup').innerHTML, /Lineup complete/);
sandbox.state = readyState;
call('renderState(state)');

// Network, HTTP, parse, and malformed-state failures must visibly disconnect and clear live HP.
for (const fetchFailure of [
  async () => {throw new Error('Synthetic network failure');},
  async () => ({ok: false, json: async () => sandbox.state}),
  async () => ({ok: true, json: async () => {throw new Error('Synthetic JSON failure');}}),
  async () => ({ok: true, json: async () => ({unexpected: 'data'})}),
]) {
  sandbox.fetch = fetchFailure;
  await call('update()');
  assert.equal(element('sourceStatus').textContent, 'Disconnected');
  assert.equal(element('.card').classList.contains('source-disconnected'), true);
  assert.equal(element('.card').classList.contains('animate-glow'), false);
  assert.equal(animationRequests.at(-1), false);
  assert.equal(element('fightLabel').textContent, 'Last fight');
  assert.equal(element('fightTime').textContent, '—');
  assert.equal(element('hpPercent').textContent, '—');
  assert.equal(element('hpTrack').getAttribute('aria-valuenow'), undefined);
  assert.equal(element('hpNote').textContent, 'Live connection lost');
}
sandbox.fetch = async () => ({ok: true, json: async () => sandbox.state});
await call('update()');
assert.equal(element('.card').classList.contains('source-disconnected'), false);
assert.equal(element('fightLabel').textContent, 'Fighting now');
assert.equal(element('hpPercent').textContent, '65%');
assert.equal(animationRequests.at(-1), true);

// The two mode buttons become Home only for their own active view.
sandbox.state.overlayView = 'home';
call('renderState(state)');
assert.equal(element('main').hidden, false);
assert.equal(element('combatPanel').hidden, true);
assert.equal(element('combatViewButton').getAttribute('aria-label'), 'Show combat stats');
assert.equal(element('speedrunViewButton').getAttribute('aria-label'), 'Show speedrun stats');
sandbox.state.overlayView = 'combat';
sandbox.state.combatMetrics = {status:'active', bossName:'Live boss', rollingDps:125.5, averageDps:100, observedDamage:1000, largestDrop:150, observedSeconds:10, hpPercent:75, note:'Observed HP loss.'};
call('renderState(state)');
assert.equal(element('main').hidden, true);
assert.equal(element('lineup').hidden, true);
assert.equal(element('combatPanel').hidden, false);
assert.equal(element('speedrunPanel').hidden, true);
assert.equal(element('combatViewButton').getAttribute('aria-label'), 'Return to main overlay');
assert.equal(element('speedrunViewButton').getAttribute('aria-label'), 'Show speedrun stats');
assert.equal(element('combatViewButton').innerHTML, call("iconMarkup('home')"));
assert.equal(element('rollingDps').textContent, '126');
assert.equal(element('averageDps').textContent, '100');
assert.equal(element('observedSeconds').textContent, '0:10');
assert.equal(element('combatHealth').textContent, 'Boss health remaining · 75.0%');
assert.equal(animationRequests.at(-1), false, 'Hidden home portrait must not consume animation captures');
call('renderDisconnected()');
assert.equal(element('rollingDps').textContent, '—', 'Disconnected metrics never retain a live value');
assert.equal(element('combatViewButton').disabled, true);
sandbox.state.combatMetrics = {status:'unavailable', rollingDps:null, averageDps:null, observedDamage:null, largestDrop:null, observedSeconds:null};
call('renderState(state)');
assert.equal(element('rollingDps').textContent, '—');
assert.equal(element('observedDamage').textContent, '—');
assert.equal(element('observedSeconds').textContent, '—');
assert.match(element('combatNote').textContent, /Manual fight previews do not supply DPS/);
// The server's generic caveat must not replace actionable empty-state guidance.
sandbox.state.combatMetrics.note = 'Estimated boss HP loss; includes summons, allies and status damage. Largest drop is one sample, not one hit. Resets after a gap or phase change.';
call('renderState(state)');
assert.match(element('combatNote').textContent, /Enable live tracking/);
sandbox.state.combatMetrics.status = 'tracking';
call('renderState(state)');
assert.equal(element('combatNote').hidden, true, 'Active measurements need only one concise caveat');

sandbox.state.overlayView = 'speedrun';
sandbox.state.contextKey = 'character-a:j2';
sandbox.state.speedrun = {status:'running',contextKey:'character-a:j2',elapsedSeconds:123,igtSeconds:110,deaths:2,bossesDefeated:1,character:'Runner',journey:2,exportAvailable:true,splits:[{name:'Boss <&>',elapsedSeconds:100,igtSeconds:90,source:'save flag'}]};
call('renderState(state)');
assert.equal(element('combatViewButton').getAttribute('aria-label'), 'Show combat stats');
assert.equal(element('speedrunViewButton').getAttribute('aria-label'), 'Return to main overlay');
assert.equal(element('speedrunViewButton').innerHTML, call("iconMarkup('home')"));
assert.equal(element('combatPanel').hidden, true);
assert.equal(element('speedrunPanel').hidden, false);
assert.equal(element('runTime').textContent, '0:02:03');
assert.equal(element('runIgt').textContent, '0:01:50');
assert.equal(element('runDeaths').textContent, '2');
assert.doesNotMatch(html,/id="(?:start|pause|resume|finish|reset)RunButton"|function runAction|Practice time/);
assert.equal(element('exportRunButton').disabled, false);
assert.match(element('runSplits').innerHTML, /Boss &lt;&amp;&gt;/);
assert.equal(element('runCharacter').textContent, 'Speedrun', 'Character-name toggle applies in the speedrun view too');
sandbox.state.speedrun.captureNotice='Character or journey changed. This run was stopped.';
call('renderState(state)');
assert.match(element('runNotice').textContent,/Character or journey changed/);
assert.equal(element('runStatus').textContent,'Recording');
sandbox.state.showCharacterName=true;
for(const [captureStatus,label] of [['recovering','Recovering'],['game-time-paused','Game paused'],['game-closed','Game closed'],['blocked','Blocked'],['off','Not recording']]){
 sandbox.state.speedrun.captureStatus=captureStatus;call('renderState(state)');
 assert.equal(element('runStatus').textContent,label);
}
sandbox.state.speedrun.captureStatus='finished';
sandbox.state.speedrun.status='finished';
call('renderState(state)');
assert.equal(element('runCharacter').textContent,'Runner');
element('runInfo').hidden=true;
call("toggleInfo('runInfo')");
assert.equal(element('runInfo').hidden,false);
call("toggleInfo('runInfo')");
assert.equal(element('runInfo').hidden,true);
assert.match(html,/id="runInfo" hidden/);
assert.match(html,/class="info-button"[^>]+>info<\/button>/);

// View selection and controls use authenticated actions, not local DOM-only mode changes.
const sent = [];
sandbox.fetch = async (url, options={}) => {
  if(url === '/api/action') {
    const payload = JSON.parse(options.body); sent.push({payload,headers:options.headers});
    if(payload.action === 'overlayView') sandbox.state.overlayView = payload.view;
    return {ok:true,json:async()=>({ok:true})};
  }
  return {ok:true,json:async()=>sandbox.state};
};
await call("switchView('speedrun')");
assert.equal(sent.at(-1).payload.view, 'home');
assert.equal(sent.at(-1).headers['X-Tracker-Token'], '__TOKEN__');
assert.equal(element('main').hidden, false);
await call("switchView('combat')");
assert.equal(sent.at(-1).payload.view, 'combat');
await call("openDashboard()");
assert.deepEqual(sent.at(-1).payload,{action:'openDashboard'});

// Failed changes remain visible and restore the controls.
sandbox.fetch = async () => ({ok:false,json:async()=>({error:'Run belongs to another character.'})});
await call("openDashboard()");
assert.match(element('actionMessage').textContent, /another character/);
assert.equal(element('actionMessage').classList.contains('error'), true);
assert.equal(element('combatViewButton').disabled, false);
let resolvePending;
sandbox.fetch = async url => url === '/api/action' ? new Promise(resolve => {resolvePending=resolve;}) : ({ok:true,json:async()=>sandbox.state});
const pending = call("switchView('combat')");
assert.equal(element('combatViewButton').disabled, true);
assert.equal(await call("switchView('speedrun')"), false, 'Repeated clicks cannot submit parallel actions');
resolvePending({ok:true,json:async()=>({ok:true})});
await pending;

// Native export handles success, user cancellation and file-write errors.
sandbox.state.overlayView='speedrun';sandbox.state.speedrun.exportAvailable=true;
call('renderState(state)');
sandbox.window.pywebview.api.export_speedrun = async () => ({path:'C:\\Exports\\run.tlrun'});
await call('exportSpeedrun()');
assert.equal(element('actionMessage').textContent, 'Saved: C:\\Exports\\run.tlrun');
sandbox.window.pywebview.api.export_speedrun = async () => ({cancelled:true});
await call('exportSpeedrun()');
assert.equal(element('actionMessage').hidden, true);
sandbox.window.pywebview.api.export_speedrun = async () => ({error:'Destination is not writable.'});
await call('exportSpeedrun()');
assert.match(element('actionMessage').textContent, /not writable/);
assert.equal(element('exportRunButton').disabled, false);
delete sandbox.window.pywebview.api.export_speedrun;

// Browser/OBS interaction downloads the same report as a TXT attachment.
let downloaded = null, revoked = null;
const anchor = {click(){downloaded={href:this.href,download:this.download};},remove(){}};
sandbox.document.createElement = () => anchor;
sandbox.document.body = {appendChild(){}};
sandbox.URL = {createObjectURL(){return 'blob:run-export';},revokeObjectURL(url){revoked=url;}};
sandbox.setTimeout = callback => callback();
sandbox.fetch = async () => ({ok:true,blob:async()=>({})});
await call('exportSpeedrun()');
assert.deepEqual(downloaded,{href:'blob:run-export',download:'tarnished-speedrun.tlrun'});
assert.equal(revoked, 'blob:run-export');
assert.match(element('actionMessage').textContent,/exported/);
sandbox.fetch = async () => ({ok:false});
await call('exportSpeedrun()');
assert.match(element('actionMessage').textContent,/could not be exported/);

// Native click forwarding respects visibility and disabled state.
let clicks=0;
const hitTarget={disabled:false,getClientRects:()=>[{}],click(){clicks++;}};
sandbox.document.elementFromPoint=()=>({closest:()=>hitTarget});
call('window.overlayNativeClick(5,5)');
assert.equal(clicks,1);
hitTarget.disabled=true;
call('window.overlayNativeClick(5,5)');
assert.equal(clicks,1);
hitTarget.disabled=false;hitTarget.getClientRects=()=>[];
call('window.overlayNativeClick(5,5)');
assert.equal(clicks,1);
call('window.overlayNativeClick(NaN,5)');
assert.equal(clicks,1);

// The native presenter receives visible clickable bounds, including disabled buttons.
let regionCalls=[];
sandbox.window.innerHeight=440;
sandbox.document.querySelectorAll=()=>[
 {disabled:true,getClientRects:()=>[{}],getBoundingClientRect:()=>({left:280,top:10,width:28,height:28})},
 {getClientRects:()=>[],getBoundingClientRect:()=>({left:0,top:0,width:100,height:20})},
];
sandbox.window.pywebview.api.set_interactive_regions=(regions,width,height)=>{regionCalls.push(JSON.parse(JSON.stringify({regions,width,height})));return Promise.resolve();};
call('syncNativeRegions()');
assert.deepEqual(regionCalls.at(-1),{regions:[{x:280,y:10,width:28,height:28}],width:360,height:440});
call('syncNativeRegions()');
assert.equal(regionCalls.length,1,'Unchanged regions must not repeatedly cross the native bridge');
sandbox.window.innerWidth=280;
call('syncNativeRegions()');
assert.equal(regionCalls.length,2,'Viewport changes must republish scale information');

// Observed boss attempts are shared across views and never capped at the bar's 15-minute scale.
const previousState=sandbox.state;
sandbox.state={...previousState,ready:true,saveStatus:'connected',overlayView:'home',
 current:{id:1,name:'Boss',source:'Live game data',hp:100,maxHp:100},fightSeconds:192,bossAttempts:{}};
call('renderState(state)');
assert.equal(element('fightTime').textContent,'3:12','Home keeps its display-only fight clock when recorded attempts are disabled');
assert.equal(element('homeAttempt').hidden,true);
sandbox.state={...previousState,ready:true,saveStatus:'connected',overlayView:'home',contextKey:'runner:j1',
 current:{id:1,name:'Boss <&>',source:'Live game data',hp:100,maxHp:100},fightSeconds:999,
 bossAttempts:{contextKey:'runner:j1',active:{name:'Boss <&>',bossId:1,attemptNumber:3,elapsedSeconds:450,status:'fighting'},lastAttempt:null,
  benchmarks:{bestSeconds:60,nearBestSeconds:75,averageSeconds:100,sampleCount:4,scaleSeconds:900,scope:'Personal history · Journey 1'},notice:''}};
call('renderState(state)');
assert.equal(element('fightTime').textContent,'7:30','Main fight clock follows the active attempt, not an old generic timer');
let attemptMarkup=element('homeAttempt').innerHTML;
assert.match(attemptMarkup,/Observed boss attempt #3/);
assert.match(attemptMarkup,/Boss &lt;&amp;&gt;/);
assert.match(attemptMarkup,/--pace-position:50%/);
assert.match(attemptMarkup,/aria-valuemax="900"/);
assert.match(attemptMarkup,/Personal history · Journey 1/);
for(const color of ['best','near','average','slower'])assert.match(attemptMarkup,new RegExp('pace-band '+color));
assert.equal(element('homeAttempt').hidden,false);
assert.equal(element('combatAttempt').hidden,true);
assert.equal(element('speedrunAttempt').hidden,true);
sandbox.state.overlayView='combat';
call('renderState(state)');
assert.equal(element('homeAttempt').hidden,true);
assert.equal(element('combatAttempt').hidden,false);
assert.equal(element('combatAttempt').innerHTML,attemptMarkup);
sandbox.state.overlayView='speedrun';
sandbox.state.bossAttempts.active.elapsedSeconds=1000;
call('renderState(state)');
attemptMarkup=element('speedrunAttempt').innerHTML;
assert.equal(element('speedrunAttempt').hidden,false);
assert.match(attemptMarkup,/16:40/);
assert.match(attemptMarkup,/15 min\+/);
assert.match(attemptMarkup,/--pace-position:100%/);
assert.match(attemptMarkup,/aria-valuenow="900"/);
sandbox.state.bossAttempts.benchmarks={bestSeconds:null,nearBestSeconds:null,averageSeconds:null,sampleCount:0};
call('renderState(state)');
assert.match(element('speedrunAttempt').innerHTML,/Complete this boss to build personal benchmarks/);
assert.doesNotMatch(element('speedrunAttempt').innerHTML,/class="pace-band (best|near|average|slower)"/);
sandbox.state.bossAttempts.active.status='awaiting-result';
call('renderState(state)');
assert.match(element('speedrunAttempt').innerHTML,/Awaiting saved result/);
call('renderDisconnected()');
assert.match(element('speedrunAttempt').innerHTML,/attempt-clock unavailable/);
assert.doesNotMatch(element('speedrunAttempt').innerHTML,/aria-valuenow=/);
sandbox.state.bossAttempts.lastAttempt={...sandbox.state.bossAttempts.active,outcome:'death',elapsedSeconds:1000};
sandbox.state.bossAttempts.active=null;
call('renderState(state)');
assert.equal(element('fightTime').textContent,'0:00','A saved death clears the main attempt timer even if its old HUD bar remains');
assert.match(element('speedrunAttempt').innerHTML,/Last observed attempt #3/);
assert.match(element('speedrunAttempt').innerHTML,/Death recorded/);
sandbox.state.bossAttempts.active={name:'Boss <&>',bossId:1,attemptNumber:4,elapsedSeconds:0,status:'fighting'};
call('renderState(state)');
assert.equal(element('fightTime').textContent,'0:00');
assert.match(element('speedrunAttempt').innerHTML,/Observed boss attempt #4/);
sandbox.state.current.source='Manual fight';
call('renderState(state)');
assert.equal(element('speedrunAttempt').hidden,true,'Manual previews cannot create real attempts');
sandbox.state.current.source='Live game data';sandbox.state.bossAttempts.contextKey='another-runner:j1';
call('renderState(state)');
assert.equal(element('speedrunAttempt').hidden,true,'Different character attempts cannot bleed into this overlay');
assert.equal(element('fightTime').textContent,'—');
sandbox.state=previousState;

// Timing is always automatic; only timer view exposes export and its category route.
const savedState=sandbox.state;
sandbox.state={...savedState,overlayView:'speedrun',
 speedrun:{status:'armed',captureStatus:'armed',elapsedSeconds:null,exportAvailable:false,notice:'Waiting for LiveSplit.',
 upcoming:[{id:99,name:'Category boss <&>',portrait:'/99.jpg',dlc:true}]}};
call('renderState(state)');
assert.equal(element('runTimingLabel').textContent,'LiveSplit game time');
assert.equal(element('runTime').textContent,'—');
assert.equal(element('runStatus').textContent,'Armed');
assert.match(element('runSplits').innerHTML,/No splits yet/);
assert.equal(element('exportRunButton').disabled,true);
assert.match(element('speedrunLineup').innerHTML,/Category boss &lt;&amp;&gt;/);
assert.match(element('speedrunLineup').innerHTML,/\/99.jpg/);
assert.equal(call('typeof runAction'),'undefined','The UI has no manual clock command function');
sandbox.state.speedrun={...sandbox.state.speedrun,status:'running',captureStatus:'running',elapsedSeconds:123,exportAvailable:true};
call('renderState(state)');
assert.equal(element('runTime').textContent,'0:02:03');
assert.equal(element('exportRunButton').disabled,false);
sandbox.state.overlayView='home';call('renderState(state)');
assert.equal(element('exportRunButton').disabled,true);
assert.equal(element('runStatus').textContent,'Not recording');
sandbox.state.overlayView='speedrun';sandbox.state.speedrun.status='disconnected';
call('renderState(state)');
assert.equal(element('runTime').textContent,'—','A lost connection cannot show a stale live timer');
call('renderDisconnected()');
assert.equal(element('runTime').textContent,'—');
sandbox.state=savedState;call('renderState(state)');

console.log('Overlay checks passed: traits, live data, attempt resets/benchmarks/overflow, external timer controls, modes/home icons, safe metrics, automatic recording statuses, info panels, category route, action errors/races, TXT exports, native clicks, transparency cadence and recovery.');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
