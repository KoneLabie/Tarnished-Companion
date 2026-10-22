// Run with: node source/tests/test_dashboard.cjs
// Exercise polling, character switches and edits without a game or browser.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'ui.html'), 'utf8');
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
assert.equal(new Set(ids).size, ids.length, 'Markup IDs must be unique');
const elements = new Map();
function element(id) {
  assert.ok(ids.includes(id), `Missing actual dashboard element: ${id}`);
  if (!elements.has(id)) {
    let value = '';
    elements.set(id, {
      innerHTML: '', textContent: '', className: '', disabled: false, checked: false,
      hidden: false, style: {}, src: '', alt: '',
      get value() { return value; }, set value(next) { value = String(next); },
    });
  }
  return elements.get(id);
}
const sandbox = vm.createContext({
  document: {getElementById: element},
  setInterval() {}, setTimeout() {}, clearTimeout() {},
  fetch() { return new Promise(() => {}); },
});
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], sandbox);
const run = code => vm.runInContext(code, sandbox);
const read = expression => JSON.parse(run(`JSON.stringify(${expression})`));
const fixture = {
  contextKey: 'char-a:journey-1', ready: true, saveStatus: 'connected', status: 'Save connected.',
  stats: {name: 'First', journey: 1, level: 50, deaths: 7, seconds: 300},
  slot: 0, save: 'synthetic.sl2', saves: ['synthetic.sl2'],
  profiles: [{slot: 0, name: 'First', level: 50}, {slot: 1, name: 'Second', level: 10}],
  bosses: [
    {id: 1, name: 'Shared name', region: 'First area', portrait: '/1.jpg'},
    {id: 2, name: 'Shared name', region: 'Second area', portrait: '/2.jpg', dlc: true},
    {id: 3, name: 'Boss <three>', region: 'Last area', portrait: '/3.jpg'},
  ],
  catalogBossIds: [1,2,3], dlc: {available:true,include:true,status:'available',notice:'Expansion detected.'},
  presets: {Main: [1, 2], All: [1, 2, 3]}, route: [1, 2], killed: [2],
  completed: 1, total: 2, catalogKilled: 1, enemyKills: 12, upcoming: [],
  recent: [], current: null, fightSeconds: 0, showCharacterName: true,
  liveEnabled: false, liveStatus: 'Off', liveCharacterVerified: false,
  characterSelectionStatus: 'Selected character.', trackingNotice: '',
  layout: {width: 360, opacity: .72, font: 'Cinzel', icons: 8, animateGlow: true},
};
const clone = value => JSON.parse(JSON.stringify(value));
function accept(snapshot) {sandbox.snapshot = clone(snapshot); run('acceptState(snapshot)');}

async function main() {
  accept(fixture);
  assert.match(element('char').textContent, /Journey 1/);
  assert.match(element('route').innerHTML, /Available encounters/);
  assert.match(element('route').innerHTML, /Boss &lt;three&gt;/);
  assert.match(element('route').innerHTML, /Second area · DLC/);
  assert.match(element('route').innerHTML, /✓ Defeated/);
  assert.equal(element('glowChoice').checked, true);
  assert.equal(element('overlayView').value, 'home');
  assert.equal(element('speedrunSetup').hidden, true);
  assert.equal(element('categoryPrompt').hidden, true);
  assert.equal(element('runExport').hidden, true);
  assert.doesNotMatch(html,/Practice stopwatch|id="timingMode"|function runAction|id="run(Start|Pause|Resume|Finish|Reset)"/);
  assert.doesNotMatch(html,/manualBoss|manualSet|action:'manual'|Set fight|>Clear<\/button>/);
  assert.doesNotMatch(html,/id="dlcMode"|changeDlcMode|action:'dlcMode'/);
  assert.match(html,/If you have problems contact <a href="https:\/\/discord\.com\/users\/827114107491713025" target="_blank" rel="noopener">Koné Labie<\/a>/);
  assert.ok(html.indexOf('id="appearanceCard"')>html.indexOf('id="recent"'),'Appearance follows lineup and recent defeats');
  assert.match(element('catalogScope').innerHTML,/value="dlc"/);
  element('catalogScope').value='base';
  assert.deepEqual(read('routeRows().included.map(b=>b.id)'),[1]);
  element('catalogScope').value='dlc';
  assert.deepEqual(read('routeRows().included.map(b=>b.id)'),[2]);
  element('catalogScope').value='all';element('regionFilter').value='Last area';
  assert.deepEqual(read('routeRows().available.map(b=>b.id)'),[3]);
  element('regionFilter').value='';
  // Changing detected availability filters display without erasing hidden route edits.
  run('toggleRoute(3,true)');
  const noDlc=clone(fixture);noDlc.bosses=noDlc.bosses.filter(b=>!b.dlc);
  noDlc.dlc={available:false,include:false,status:'unavailable',notice:'Expansion not detected.'};
  noDlc.presets={'Major bosses':[1],'Major bosses + Optional':[1,3],Optional:[3],'All encounters':[1,3]};
  element('catalogScope').value='dlc';accept(noDlc);
  assert.deepEqual(read('route'),[1,2,3]);
  assert.equal(run('routeDirty'),true);
  assert.equal(element('catalogScope').hidden,true);
  assert.equal(element('catalogScope').value,'all');
  assert.doesNotMatch(element('catalogScope').innerHTML,/value="dlc"|Shadow/);
  assert.doesNotMatch(element('route').innerHTML,/Second area/);
  assert.equal(element('routeCount').textContent,'2 included');
  assert.match(element('preset').innerHTML,/Major bosses \+ Optional/);
  assert.equal(element('dlcNotice').textContent,'');
  assert.equal(element('dlcNotice').hidden,true);
  assert.equal(element('dlcStatus').textContent,'');
  assert.equal(element('dlcStatus').hidden,true);
  const unknownDlc=clone(noDlc);unknownDlc.dlc.available=null;accept(unknownDlc);
  assert.equal(element('catalogScope').hidden,true);
  assert.equal(element('dlcStatus').textContent,'');
  assert.equal(element('dlcStatus').hidden,true);
  accept(fixture);run('revertRoute()');
  const timed = clone(fixture);
  timed.overlayView = 'speedrun';
  timed.speedrun = {status:'running',captureStatus:'running',captureNotice:'Record only this timer view.',character:'First',elapsedSeconds:60,igtSeconds:55,bossesDefeated:2,exportAvailable:true};
  timed.runPolicy={needsSelection:true,categories:[],notice:'Choose before creating a character.'};
  timed.reportExport={extension:'.tlrun',encrypted:true,notice:'Encrypted for the configured report server.'};
  accept(timed);
  assert.equal(element('speedrunSetup').hidden,false);
  assert.equal(element('categoryPrompt').hidden,false);
  assert.equal(element('overlayView').value,'speedrun');
  assert.equal(element('runExport').hidden,false);
  assert.equal(element('runStatus').textContent,'Recording');
  assert.equal(element('runExport').textContent,'Export run .tlrun');
  assert.equal(element('runExport').download,'tarnished-speedrun.tlrun');
  assert.equal(element('reportExportStatus').textContent,'Encrypted for the configured report server.');
  assert.equal(element('runNotice').textContent,'Record only this timer view.');
  for(const [captureStatus,label] of [['recovering','Recovering'],['game-time-paused','Game paused'],['game-closed','Game closed'],['blocked','Blocked']]){
   timed.speedrun.captureStatus=captureStatus;accept(timed);
   assert.equal(element('runStatus').textContent,label);
  }
  timed.speedrun.exportAvailable=false;timed.speedrun.status='disconnected';timed.speedrun.captureStatus='disconnected';
  accept(timed);
  assert.equal(element('runExport').hidden,true);
  assert.equal(element('runStatus').textContent,'Disconnected');
  timed.routeManaged=true;
  accept(timed);
  assert.equal(element('lineupEditor').hidden,true);
  const managedRoute=read('route');
  run('toggleRoute(1,false);moveRoute(1,1);applyPreset()');
  assert.deepEqual(read('route'),managedRoute);
  timed.overlayView='home';accept(timed);
  assert.equal(element('categoryPrompt').hidden,true,'Home never prompts for a run category');
  assert.equal(element('speedrunSetup').hidden,true);
  accept(fixture);

  // Removing a boss changes only lineup membership, and it stays available to add.
  run('toggleRoute(2,false)');
  assert.deepEqual(read('route'), [1]);
  assert.deepEqual(read('state.killed'), [2]);
  assert.match(element('route').innerHTML, /onchange="toggleRoute\(2,this.checked\)"/);
  assert.equal(run('routeDirty'), true);
  run('toggleRoute(3,true); moveRoute(3,-1)');
  assert.deepEqual(read('route'), [3, 1]);

  // Regular polls update saved defeat state without discarding an unsaved order.
  const progressed = clone(fixture);
  progressed.killed = [2, 3]; progressed.catalogKilled = 2;
  accept(progressed);
  assert.deepEqual(read('route'), [3, 1]);
  assert.equal(run('routeDirty'), true);
  element('filter').value = 'second area';
  assert.deepEqual(read('routeRows().available.map(b=>b.id)'), [2]);
  element('hideDefeated').checked = true;
  assert.deepEqual(read('routeRows().available.map(b=>b.id)'), []);
  element('filter').value = ''; element('hideDefeated').checked = false;

  // A transient parse error keeps the draft and explicitly pauses editing.
  const paused = clone(progressed);
  paused.ready = false; paused.saveStatus = 'error'; paused.status = 'Unsupported save version';
  accept(paused);
  assert.deepEqual(read('route'), [3, 1]);
  assert.equal(element('saveRoute').disabled, true);
  assert.equal(element('saveStatus').className, 'status err');
  assert.match(element('upcoming').innerHTML, /paused/);

  // Appearance edits survive polls and character switches independently of route drafts.
  element('widthChoice').value = 440; element('glowChoice').checked = false;
  run('editLayout()');
  accept(fixture);
  assert.equal(element('widthChoice').value, '440');
  assert.equal(element('glowChoice').checked, false);
  const second = clone(fixture);
  second.contextKey = 'char-b:journey-2'; second.stats.name = 'Second'; second.stats.journey = 2;
  second.route = [2]; second.enemyKills = 0;
  run('killsDirty=true'); element('killsInput').value = 999;
  accept(second);
  assert.deepEqual(read('route'), [2]);
  assert.equal(run('routeDirty'), false);
  assert.equal(element('killsInput').value, '0');
  assert.equal(element('widthChoice').value, '440');
  assert.match(element('char').textContent, /Journey 2/);
  run('revertLayout()');
  assert.equal(element('widthChoice').value, '360');
  assert.equal(element('glowChoice').checked, true);

  // Reverting restores server order; plain polls can follow a saved remote change.
  run('toggleRoute(1,true); revertRoute()');
  assert.deepEqual(read('route'), [2]);
  second.route = [3, 1]; accept(second);
  assert.deepEqual(read('route'), [3, 1]);
  second.liveEnabled = true;
  second.current = {name:'Shared name', source:'Live game data', identityStatus:'Exact arena unresolved', hp:100, maxHp:200};
  accept(second);
  assert.match(element('liveCharacterStatus').textContent, /selected saved character/);
  assert.equal(element('fightBadge').textContent, 'Live game data');
  assert.equal(element('fightIdentity').textContent, 'Exact arena unresolved');
  assert.equal(element('fightIdentity').hidden, false);

  // Save carries the current context so the backend can reject cross-character edits.
  let server = clone(second), sent = [];
  sandbox.fetch = async (url, options) => {
    if (url === '/api/action') {
      const action = JSON.parse(options.body); sent.push(action);
      if (action.action === 'route') server.route = [...action.route];
      if (action.action === 'layout') server.layout = {...action.layout};
      if (action.action === 'resetTracking') {
        server.contextKey = 'char-b:journey-2:new-generation';
        server.route = [1,2]; server.enemyKills = 0;
      }
      return {ok:true, json:async()=>({ok:true})};
    }
    return {ok:true, json:async()=>clone(server)};
  };
  run('toggleRoute(2,true)');
  await run('saveRoute()');
  assert.deepEqual(sent.at(-1), {action:'route', route:[3,1,2], contextKey:second.contextKey});
  assert.equal(run('routeDirty'), false);
  element('glowChoice').checked = false; element('traitsChoice').checked = false; run('editLayout()');
  await run('saveLayout()');
  assert.equal(sent.at(-1).layout.animateGlow, false);
  assert.equal(sent.at(-1).layout.showBossTraits, false);
  assert.equal(element('traitsChoice').checked, false);
  assert.equal(run('layoutDirty'), false);

  // A newer edit made while a save is in flight must survive its older response.
  run('toggleRoute(3,false)');
  let release;
  sandbox.fetch = (url, options) => {
    if (url === '/api/action') {
      const action = JSON.parse(options.body); sent.push(action);
      server.route = [...action.route];
      return new Promise(resolve => {release = () => resolve({ok:true,json:async()=>({ok:true})});});
    }
    return Promise.resolve({ok:true,json:async()=>clone(server)});
  };
  const pending = run('saveRoute()');
  run('toggleRoute(1,false)');
  release(); await pending;
  assert.deepEqual(read('route'), [2]);
  assert.equal(run('routeDirty'), true);

  // Failure to refresh after a successful POST must not discard a draft.
  sandbox.fetch = async url => {
    if (url === '/api/action') return {ok:true,json:async()=>({ok:true})};
    throw Error('Disconnected');
  };
  await run('saveRoute()');
  assert.deepEqual(read('route'), [2]);
  assert.equal(run('routeDirty'), true);
  assert.match(element('saveStatus').textContent, /disconnected/i);

  // Local reset explicitly carries context and reloads the new generation defaults.
  sandbox.fetch = async (url, options) => {
    if (url === '/api/action') {
      const action=JSON.parse(options.body);sent.push(action);
      server.contextKey='char-b:journey-2:new-generation';server.route=[1,2];server.enemyKills=0;
      return {ok:true,json:async()=>({ok:true})};
    }
    return {ok:true,json:async()=>clone(server)};
  };
  await run('resetTracking()');
  assert.deepEqual(sent.at(-1), {action:'resetTracking',contextKey:second.contextKey});
  assert.deepEqual(read('route'), [1,2]);
  assert.equal(run('routeDirty'), false);
  assert.deepEqual(read('state.killed'), fixture.killed);
  // The only category selector autosaves; no separate confirmation or manual clock actions.
  server=clone(fixture);server.overlayView='speedrun';
  server.runPolicy={selectedId:'',needsSelection:true,categories:[{id:'any-percent-glitchless',name:'Any% Glitchless',startNote:'Create a new character.'},{id:'custom',name:'Custom'}]};
  accept(server);
  sandbox.fetch=async(url,options={})=>{
   if(url==='/api/action'){
    const action=JSON.parse(options.body);sent.push(action);
    server.runPolicy.selectedId=action.categoryId;server.runPolicy.name=action.customName||'Any% Glitchless';server.runPolicy.customName=action.customName;server.runPolicy.needsSelection=false;
    return {ok:true,json:async()=>({ok:true})};
   }
   return {ok:true,json:async()=>clone(server)};
  };
  element('categoryChoice').value='any-percent-glitchless';
  await run('categoryChanged()');
  assert.deepEqual(sent.at(-1),{action:'runCategory',categoryId:'any-percent-glitchless',customName:''});
  assert.equal(element('categoryPrompt').hidden,true);
  element('categoryChoice').value='custom';
  const beforeCustom=sent.length;
  await run('categoryChanged()');
  assert.equal(sent.length,beforeCustom,'Custom selection waits for its name, not a confirm button');
  element('customCategory').value='My <route>';
  await run('saveCategory()');
  assert.equal(sent.at(-1).customName,'My <route>');
  const afterCustom=sent.length;
  await run('saveCategory()');
  assert.equal(sent.length,afterCustom,'Change and blur must not double-submit');
  element('runInfo').hidden=true;
  run("toggleInfo('runInfo')");
  assert.equal(element('runInfo').hidden,false);
  run("toggleInfo('runInfo')");
  assert.equal(element('runInfo').hidden,true);
  assert.match(html,/class="info-button"[^>]+>info<\/button>/);
  assert.doesNotMatch(html,/Use this category|categoryDialog/);
  // Rescan is the only content action; it keeps a draft while availability updates.
  server=clone(noDlc);accept(server);run('toggleRoute(3,true)');
  sandbox.fetch=async(url,options={})=>{
   if(url==='/api/action'){sent.push(JSON.parse(options.body));server=clone(fixture);return {ok:true,json:async()=>({ok:true})};}
   return {ok:true,json:async()=>clone(server)};
  };
  await run('rescanDlc()');
  assert.deepEqual(sent.at(-1),{action:'rescanDlc'});
  assert.deepEqual(read('route'),[1,2,3]);
  assert.equal(run('routeDirty'),true);
  assert.equal(element('rescanDlc').disabled,false);
  assert.equal(element('catalogScope').hidden,false);
  console.log('Dashboard checks passed: automatic encounter UI, DLC detection/filtering, preserved hidden drafts, report export, category autosave, context resets and action races.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
