// Published whole-run comparisons must never become unrelated boss targets.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {innerHTML:'', hidden:false,
    classList:{toggle(){}}, getBoundingClientRect(){return {height:400};}});
  return elements.get(id);
}
const sandbox = vm.createContext({
  document:{getElementById:element,querySelector:element,documentElement:element('document'),
    fonts:{ready:{then(){}}},addEventListener(){}},
  window:{innerWidth:360,addEventListener(){},matchMedia(){return {matches:false,addEventListener(){}};}},
  ResizeObserver:class{observe(){}},requestAnimationFrame(){},setInterval(){},
});
const html=fs.readFileSync(path.join(__dirname,'..','overlay.html'),'utf8');
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1].replace('setInterval(update,1000);update();',''),sandbox);
const call=code=>vm.runInContext(code,sandbox);
const base={
  runPolicy:{selectedId:'any-percent-glitchless'},
  speedrun:{status:'running',timingSource:'livesplit',elapsedSeconds:2400,recordMatchesTimer:true,journey:1,
    runPolicy:{categoryId:'any-percent-glitchless'}},
  publishedRecord:{source:'speedrun.com',status:'fresh',categoryId:'any-percent-glitchless',
    categoryName:'Any% — Glitchless',scope:'PC',timing:'Published PC category time',
    timingKey:'pc-soulsplitter-game-time',checkedAt:'2026-10-22T12:00:00Z',
    lastAttemptAt:'2026-10-22T12:00:00Z',nextRefreshAt:'2026-10-22T12:15:00Z',
    sourceUrl:'https://www.speedrun.com/eldenring',bestSeconds:3000,nearBestSeconds:3200,
    averageSeconds:3600,sampleCount:20,notice:'Accepted category snapshot.',bossTimesAvailable:false}
};
function render(modify=()=>{},connected=true){sandbox.state=structuredClone(base);modify(sandbox.state);return call(`publishedRecordMarkup(state,${connected})`);}
let output=render();
assert.match(output,/Current snapshot/);
assert.match(output,/aria-valuemax="4140"/,'A whole-run scale must adapt beyond the boss bar’s fixed fifteen minutes');
assert.match(output,/aria-valuenow="2400"/);
assert.match(output,/0:50:00/);
assert.match(output,/0:53:20/);
assert.match(output,/1:00:00/);
assert.match(output,/last successful check/);
assert.match(output,/separate from the personal boss-fight bar/);
assert.match(output,/unfinished run.*does not mean it is ahead/);
assert.match(output,/rel="noopener noreferrer"/);

for(const mutate of [s=>delete s.publishedRecord,s=>s.publishedRecord.categoryId='another-category',
  s=>s.publishedRecord.source='untrusted.example',s=>s.publishedRecord.status='unknown',
  s=>s.publishedRecord.simulation=true,s=>s.speedrun.journey=2,s=>delete s.speedrun.journey,
  s=>{delete s.speedrun.journey;s.stats={journey:1};}]) assert.equal(render(mutate),'');
assert.match(render(s=>{delete s.speedrun.journey;s.speedrun.status='armed';s.stats={journey:1};}),/0:50:00/);

output=render(s=>{s.runPolicy.selectedId='new-category';});
assert.match(output,/0:50:00/,'A recorded category takes precedence over a newly selected future category');
assert.equal(render(s=>{s.runPolicy.selectedId='new-category';delete s.speedrun.runPolicy;}),'');

for(const mutate of [s=>s.publishedRecord.timingKey='realtime',s=>s.publishedRecord.bestSeconds=0,
  s=>s.publishedRecord.bestSeconds=NaN,s=>s.publishedRecord.bestSeconds=Infinity,
  s=>s.publishedRecord.bestSeconds='3000',s=>s.publishedRecord.sampleCount=0,
  s=>s.publishedRecord.status='unavailable',s=>s.publishedRecord.status='unsupported']) {
  output=render(mutate);
  assert.match(output,/No comparable published times/);
  assert.doesNotMatch(output,/class="pace-band |aria-valuemax=/,'Invalid or incomparable targets must never drive a bar');
}
output=render(s=>{s.publishedRecord.nearBestSeconds=2000;s.publishedRecord.averageSeconds=1000;});
const widths=[...output.matchAll(/class="pace-band \w+" style="width:([\d.]+)%"/g)].map(m=>Number(m[1]));
assert.equal(widths.length,4);
assert.ok(widths.every(n=>n>=0&&n<=100));
assert.ok(Math.abs(widths.reduce((a,b)=>a+b)-100)<1e-9);
assert.equal(widths[1],0);assert.equal(widths[2],0);
output=render(s=>{s.speedrun.elapsedSeconds=100000;});
assert.match(output,/--pace-position:100%/);
assert.match(output,/aria-valuenow="4140"/);

output=render(s=>{s.publishedRecord.status='stale';s.publishedRecord.lastAttemptAt='2026-10-22T12:15:00Z';});
assert.match(output,/data-state="stale">Cached/);
assert.match(output,/Showing a cached snapshot/);
assert.match(output,/Last refresh attempt/);
assert.doesNotMatch(output,/Current snapshot/);
output=render(()=>{},false);
assert.match(output,/Cached/);
assert.doesNotMatch(output,/aria-valuenow=|pace-marker/);
for(const mutate of [s=>s.speedrun.recordMatchesTimer=false,s=>s.speedrun.status='armed',s=>s.speedrun.elapsedSeconds=NaN])
  assert.doesNotMatch(render(mutate),/aria-valuenow=|pace-marker/);

output=render(s=>{s.simulation=true;s.publishedRecord.simulation=true;});
assert.match(output,/Simulated record data/);
assert.match(output,/example checked/);
assert.doesNotMatch(output,/Current snapshot/);
output=render(s=>{s.publishedRecord.sourceUrl='https://speedrun.com.evil.example/';
  s.publishedRecord.notice='<img src=x onerror=alert(1)>';s.publishedRecord.categoryName='Category <script>';});
assert.doesNotMatch(output,/<a href=|<img|<script>/);
assert.match(output,/&lt;img/);
assert.match(output,/Category &lt;script&gt;/);

sandbox.state=structuredClone(base);call('renderPublishedRecord(state)');
assert.equal(element('publishedRecord').hidden,false);
sandbox.state.publishedRecord.bestSeconds=2800;
sandbox.state.publishedRecord.nearBestSeconds=2900;
sandbox.state.publishedRecord.averageSeconds=3300;
sandbox.state.publishedRecord.checkedAt='2026-10-22T12:15:00Z';
call('renderPublishedRecord(state)');
assert.match(element('publishedRecord').innerHTML,/0:46:40/,'A newly fetched best must replace the previous target');
assert.doesNotMatch(element('publishedRecord').innerHTML,/0:50:00/);
sandbox.state.ready=true;sandbox.state.saveStatus='connected';sandbox.state.contextKey='runner:j1';
sandbox.state.current={id:1,name:'Boss',source:'Live game data'};
sandbox.state.bossAttempts={contextKey:'runner:j1',active:{bossId:1,name:'Boss',elapsedSeconds:45,attemptNumber:1},
  benchmarks:{bestSeconds:60,nearBestSeconds:90,averageSeconds:120,sampleCount:4}};
const bossOutput=call('bossAttemptMarkup(state)');
assert.match(bossOutput,/aria-valuemax="900"/);
assert.match(bossOutput,/Best target<b>1:00/);
assert.doesNotMatch(bossOutput,/0:46:40/,'A whole-run best cannot replace the boss encounter target');
delete sandbox.state.publishedRecord;call('renderPublishedRecord(state)');
assert.equal(element('publishedRecord').hidden,true);
assert.equal(element('publishedRecord').innerHTML,'');
console.log('Published record UI checks passed: matching category/timing, ordered bands, adaptive scale, stale/offline states, source safety and simulated previews.');
