'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {parseHTML}=require('linkedom');
const flush=async()=>{for(let n=0;n<40;n++)await Promise.resolve();};
function fixture({request,ready=true,viewOptions={}}={}){
  const {document,window}=parseHTML('<html lang="en"><body><div id="sec-presets"></div></body></html>');
  const calls=[],stored=[],arm={joints:[10,90,-90,0,0,0],gripper:.4,getJointAngles(){return [...this.joints];},getGripperPosition(){return this.gripper;}};
  let state={playing:false},listener,resolvePlay;
  const simulation={getState:()=>state,subscribe(fn){listener=fn;return ()=>{listener=null;};},async playSequence(steps){calls.push({steps});state={playing:true,outcome:'playing'};listener?.(state);return new Promise(resolve=>{resolvePlay=resolve;});},stop(){state={playing:false,outcome:'stopped'};listener?.(state);resolvePlay?.({completed:false});}};
  const sessionClient={request:request||(async(path,body)=>{calls.push({path,body});if(path.endsWith('/delete')){stored.splice(stored.findIndex(x=>x.id===body.id),1);return {deleted:true};}if(body){const item={...body,id:'saved-model',source:'model',modelVersion:'startouch-v3-model-v1',available:true,updatedAt:'2026-11-01T00:00:00Z'};stored.push(item);return item;}return {waypoints:stored.slice()};})};
  const panel=require('../../../apps/web/public/js/model-waypoints').mountModelWaypoints({document,view:{MutationObserver:window.MutationObserver,...viewOptions},sessionClient,arm,simulation,ready});
  return {document,window,calls,stored,panel,arm,simulation,finish(){state={playing:false,outcome:'completed'};listener?.(state);resolvePlay?.({completed:true});}};
}

test('real simulation callbacks keep the active waypoint status playing until stopped',async()=>{
  const {document,window}=parseHTML('<html lang="en"><body><div id="sec-presets"></div></body></html>');
  const arm={jointLimits:[[-162,162],[-12,201],[-183,0],[-98,98],[-98,98],[-164,164]],joints:[0,90,-90,0,0,0],gripper:1,getJointAngles(){return [...this.joints];},setJointAngles(v){this.joints=[...v];},getGripperPosition(){return this.gripper;},setGripperPosition(v){this.gripper=v;}};
  let release;const simulation=require('../../../apps/web/public/js/simulation-controller').createSimulationController({armModel:arm,clock:{now:()=>0,sleep:()=>new Promise(resolve=>{release=resolve;})}});
  const point={id:'fixture',name:'Pose',available:true,source:'model',modelVersion:'startouch-v3-model-v1',joints:[10,90,-90,0,0,0],gripper:.4,updatedAt:'2026-11-01T00:00:00Z'};
  const panel=require('../../../apps/web/public/js/model-waypoints').mountModelWaypoints({document,view:{MutationObserver:window.MutationObserver},sessionClient:{request:async()=>({waypoints:[point]})},arm,simulation,ready:true});
  await flush();document.querySelector('[data-recall]').click();await flush();
  assert.match(document.getElementById('model-waypoint-status').textContent,/Playing/);
  simulation.stop();release();await flush();assert.match(document.getElementById('model-waypoint-status').textContent,/stopped/);panel.dispose();
});
test('personal waypoint panel saves model pose, reloads server data and recalls without control endpoints',async()=>{
  const f=fixture();await flush();const byId=id=>f.document.getElementById(id);
  byId('waypoint-name').value='My desk';byId('save-model-waypoint').click();await flush();
  assert.deepEqual(f.stored[0].joints,f.arm.joints);assert.equal(f.stored[0].gripper,.4);assert.match(byId('model-waypoint-status').textContent,/saved/i);
  f.document.querySelector('[data-recall]').click();await flush();assert.equal(f.calls.at(-1).steps[0].gripper,.4);f.finish();await flush();assert.match(byId('model-waypoint-status').textContent,/reached/i);
  byId('reload-model-waypoints').click();await flush();assert.equal(f.document.querySelectorAll('[data-waypoint-id]').length,1);
  assert.equal(f.calls.some(x=>/control|sdk|voice/.test(x.path||'')),false);f.panel.dispose();
});
test('model readiness and playback prevent accidental save; stopping is explicit',async()=>{
  const f=fixture({ready:false});await flush();const save=f.document.getElementById('save-model-waypoint');assert.equal(save.disabled,true);f.panel.setReady(true);assert.equal(save.disabled,false);
  f.document.getElementById('waypoint-name').value='Pose';save.click();await flush();f.document.querySelector('[data-recall]').click();await flush();assert.equal(save.disabled,true);
  f.document.getElementById('stop-waypoint-model').click();await flush();assert.match(f.document.getElementById('model-waypoint-status').textContent,/stopped/i);assert.equal(save.disabled,false);f.panel.dispose();
});
test('delete needs a second confirmation and untrusted names render as text',async()=>{
  const f=fixture();await flush();f.document.getElementById('waypoint-name').value='<img src=x onerror=alert(1)>';f.document.getElementById('save-model-waypoint').click();await flush();
  assert.equal(f.document.querySelector('img'),null);f.document.querySelector('[data-delete]').click();await flush();assert.equal(f.stored.length,1);
  f.document.querySelector('[data-confirm-delete]').click();await flush();assert.equal(f.stored.length,0);assert.match(f.document.getElementById('model-waypoint-status').textContent,/deleted/i);f.panel.dispose();
});
test('failed save is not success and a disposed panel ignores a late load',async()=>{
  let resolve;const f=fixture({request:(_path,body)=>body?Promise.reject({code:'SERVICE_UNAVAILABLE'}):new Promise(r=>{resolve=r;})});
  f.panel.dispose();resolve({waypoints:[]});await flush();assert.equal(f.document.getElementById('model-waypoints'),null);
  const g=fixture({request:async(_path,body)=>{if(body)throw {code:'SERVICE_UNAVAILABLE'};return {waypoints:[]};}});await flush();g.document.getElementById('waypoint-name').value='Pose';g.document.getElementById('save-model-waypoint').click();await flush();assert.match(g.document.getElementById('model-waypoint-status').textContent,/could not be saved/i);g.panel.dispose();
});
test('point names stay literal while panel labels change language',async()=>{
  const f=fixture();await flush();const heading=f.document.querySelector('#model-waypoints h3');assert.equal(heading.textContent,'My waypoints');
  f.document.documentElement.lang='zh-CN';await flush();assert.equal(heading.textContent,'我的点位');f.panel.dispose();
});

function timers(){let next=0;const pending=new Map();return {pending,setTimeout(fn,ms){assert.equal(ms,10000);pending.set(++next,fn);return next;},clearTimeout(id){pending.delete(id);},fire(){const [id,fn]=pending.entries().next().value;pending.delete(id);fn();}};}
test('a stalled load has a bounded wait and Reload remains a recovery path',async()=>{
  const timer=timers();let calls=0;
  const f=fixture({viewOptions:timer,request:()=>++calls===1?new Promise(()=>{}):Promise.resolve({waypoints:[]})});
  await flush();assert.equal(timer.pending.size,1);timer.fire();await flush();
  assert.equal(f.document.getElementById('reload-model-waypoints').disabled,false);
  f.document.getElementById('reload-model-waypoints').click();await flush();assert.equal(calls,2);assert.match(f.document.getElementById('model-waypoint-status').textContent,/loaded/i);f.panel.dispose();
});
test('timed out saves report uncertainty, require a reload, never retry, and ignore late results',async()=>{
  const timer=timers();let resolveSave,posts=0;
  const f=fixture({viewOptions:timer,request:async(_path,body)=>{if(body){posts++;return new Promise(resolve=>{resolveSave=resolve;});}return {waypoints:[]};}});
  await flush();f.document.getElementById('waypoint-name').value='Uncertain';f.document.getElementById('save-model-waypoint').click();await flush();
  assert.equal(timer.pending.size,1);timer.fire();await flush();assert.match(f.document.getElementById('model-waypoint-status').textContent,/unconfirmed/i);
  assert.equal(f.document.getElementById('save-model-waypoint').disabled,true);assert.equal(f.document.getElementById('reload-model-waypoints').disabled,false);
  f.document.getElementById('reload-model-waypoints').click();await flush();
  resolveSave({id:'late',name:'Uncertain',source:'model',modelVersion:'startouch-v3-model-v1',available:true,joints:[0,90,-90,0,0,0],gripper:.5,updatedAt:'2026-11-01T00:00:00Z'});await flush();
  assert.equal(posts,1);assert.equal(f.document.querySelectorAll('[data-waypoint-id]').length,0);assert.match(f.document.getElementById('model-waypoint-status').textContent,/loaded/i);f.panel.dispose();
});
