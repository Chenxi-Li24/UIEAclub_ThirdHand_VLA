'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
const datesPath='apps/web/public/js/history-dates.js';
function fixture({empty=false}={}){
  const {document}=parseHTML(fs.readFileSync('apps/web/public/history.html','utf8'));
  for(const select of document.querySelectorAll('select'))select.firstElementChild?.setAttribute('selected','');
  const requests=[],events=new Map();let monitoring=false;
  const measured={captured_at:'2026-10-31T09:47:17.437Z',received_at:'2026-10-31T09:47:18Z',sample_seq:'0',joint_position_rad:[0,1,-1,0,0,0],extra:{sourceMode:'hardware'},sdk_connected:true,moving:false};
  const session={async load(){return {userId:'reader',role:'observer',mode:'observe'};},async request(path){requests.push(path);if(path==='/api/v1/devices')return {devices:[]};if(path.startsWith('/api/v1/history?')){const p=new URL(path,'https://example.invalid').searchParams;const visible=!empty&&Date.parse(p.get('from'))<=Date.parse(measured.captured_at)&&Date.parse(p.get('to'))>Date.parse(measured.captured_at);return {kind:'samples',timeBasis:'captured_at',rows:visible?[measured]:[],nextCursor:null};}return {};},startMonitoring(){monitoring=true;},close(){}};
  const view={addEventListener:(name,fn)=>events.set(name,fn),location:{assign(){}},setInterval(){return 1;},clearInterval(){}};
  class FixedDate extends Date{constructor(...args){super(...(args.length?args:['2026-10-31T19:45:00+08:00']));}static now(){return new FixedDate().getTime();}}
  const prefs={async hydrate(){},apply(){},subscribe(){},dispose(){}};
  const context=vm.createContext({document,window:view,location:view.location,Date:FixedDate,Intl,URLSearchParams,URL,THREE:{},OrbitControls(){},STLLoader(){},ColladaLoader(){},
    ThirdHandWorkspaceSession:{createWorkspaceSession:()=>session},ThirdHandPreferences:{createPreferenceClient:()=>prefs},ThirdHandHistoryDates:fs.existsSync(datesPath)?require('../../../'+datesPath):undefined,
    ThirdHandHistoryReplay:require('../../../apps/web/public/js/history-replay'),ThirdHandRobotViewer:{createRobotViewer(){throw Error('Fixture WebGL unavailable');}}});
  const source=fs.readFileSync('apps/web/public/js/history-page.js','utf8').replace(/^import .*;\r?$/gm,'').replace('start().catch(()=>{','start().catch(error=>{globalThis.bootError=error;');
  const boot=vm.runInContext(source,context);
  return {document,requests,boot,get error(){return context.bootError;},get monitoring(){return monitoring;},dispose(){events.get('pagehide')?.();}};
}
test('history loads an older stored sample automatically even when model rendering is unavailable',async()=>{
  const f=fixture();await f.boot;for(let i=0;i<15;i++)await Promise.resolve();
  try{
    assert.ifError(f.error);
    assert.ok(f.requests.some(path=>path.startsWith('/api/v1/history?')),'History must query automatically');
    assert.equal(f.document.querySelectorAll('#history-records details').length,1,'Two-hour-old data must be included by the initial range');
    assert.equal(f.monitoring,true);
    assert.equal(f.requests.some(path=>/sdk|control\/command/.test(path)),false);
  }finally{f.dispose();}
});
test('history has independent editable date and time inputs and explains an empty result',async()=>{
  const f=fixture({empty:true});await f.boot;for(let i=0;i<15;i++)await Promise.resolve();
  try{
    assert.equal(f.document.getElementById('history-from-date')?.getAttribute('type'),'date');
    assert.equal(f.document.getElementById('history-from-time')?.getAttribute('type'),'time');
    assert.equal(f.document.getElementById('history-to-date')?.getAttribute('type'),'date');
    assert.equal(f.document.getElementById('history-to-time')?.getAttribute('type'),'time');
    assert.match(f.document.getElementById('history-records').textContent,/No records in this time range/);
  }finally{f.dispose();}
});
