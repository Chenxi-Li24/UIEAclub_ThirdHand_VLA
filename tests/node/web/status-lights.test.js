'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const {parseHTML}=require('linkedom');
function api(){const file=require('node:path').resolve(__dirname,'../../../apps/web/public/js/status-lights.js');assert.ok(fs.existsSync(file),'live status lamp implementation is missing');return require(file);}
const good={connected:true,healthy:true,joints:[0,90,-90,90,0,0]};
test('Web open alone is not SDK online; valid feedback completes the green state',()=>{
 const signal=api().createSdkSignal({now:()=>1000});assert.equal(signal.snapshot().state,'unknown');
 signal.receive('ws_connection',{connected:true});assert.notEqual(signal.snapshot().state,'online');
 signal.receive('config',{connection:{connected:true}});assert.equal(signal.snapshot().state,'waiting');
 signal.receive('robot_state',good);assert.equal(signal.snapshot().state,'online');
 signal.receive('connection',{connected:false});assert.equal(signal.snapshot().state,'offline');
});
test('feedback timeout turns red without a socket-close event and invalid frames cannot renew it',()=>{
 let time=1000;const signal=api().createSdkSignal({now:()=>time});signal.receive('ws_connection',{connected:true});signal.receive('robot_state',good);
 time=3000;signal.receive('robot_state',{connected:true,healthy:true,joints:[NaN,0,0,0,0,0]});
 time=3600;assert.equal(signal.snapshot().state,'offline');assert.equal(signal.snapshot().reason,'feedback_lost');
 signal.receive('robot_state',good);assert.equal(signal.snapshot().state,'online');
});
test('a silent open connection expires after 2500 ms of no robot feedback',()=>{
 let time=1000;const signal=api().createSdkSignal({now:()=>time});signal.receive('ws_connection',{connected:true});signal.receive('robot_state',good);
 time=3499;assert.equal(signal.snapshot().state,'online');time=3501;assert.equal(signal.snapshot().state,'offline');assert.equal(signal.snapshot().reason,'feedback_lost');
});
test('disconnect and reopen discard old feedback; late frames on a closed socket stay red',()=>{
 const signal=api().createSdkSignal({now:()=>1000});signal.receive('ws_connection',{connected:true});signal.receive('robot_state',good);
 signal.receive('ws_connection',{connected:false});signal.receive('robot_state',good);assert.equal(signal.snapshot().state,'offline');
 signal.receive('ws_connection',{connected:true});signal.receive('config',{connection:{connected:true}});assert.equal(signal.snapshot().state,'waiting');
 signal.receive('robot_state',good);assert.equal(signal.snapshot().state,'online');
});
test('unhealthy feedback is not online and config without connection cannot create readiness',()=>{
 const signal=api().createSdkSignal({now:()=>1000});signal.receive('ws_connection',{connected:true});signal.receive('config',{});assert.notEqual(signal.snapshot().state,'online');
 signal.receive('robot_state',{...good,healthy:false});assert.equal(signal.snapshot().state,'offline');
});
test('six joint values without an explicit boolean healthy assertion cannot turn green',()=>{
 for(const healthy of [undefined,null,0,'true',false]){const signal=api().createSdkSignal({now:()=>1000});signal.receive('ws_connection',{connected:true});signal.receive('robot_state',{...good,healthy});assert.notEqual(signal.snapshot().state,'online');}
});
test('SDK reporting connected but never producing its first valid frame also times out',()=>{
 let time=1000;const signal=api().createSdkSignal({now:()=>time});signal.receive('ws_connection',{connected:true});signal.receive('config',{connection:{connected:true}});
 assert.equal(signal.snapshot().state,'waiting');time=3000;signal.receive('config',{connection:{connected:true}});time=3501;assert.equal(signal.snapshot().state,'offline');assert.equal(signal.snapshot().reason,'feedback_lost');
});
test('preserved page history restoration retains the display expiry timer',()=>{
 const {document,window}=parseHTML('<html lang="en"><body><span id="hb-label">SDK: --</span></body></html>');let time=1000,timerActive=false,tick;const events={},handlers={};
 const view={MutationObserver:window.MutationObserver,addEventListener(name,fn){events[name]=fn;},setInterval(fn){tick=fn;timerActive=true;return 1;},clearInterval(){timerActive=false;}};
 api().mountStatusLights(document,view,{now:()=>time}).bind({on(name,fn){handlers[name]=fn;}});handlers.ws_connection({connected:true});handlers.robot_state(good);
 events.pagehide({persisted:true});document.dispatchEvent(new window.Event('visibilitychange'));time=4000;if(timerActive)tick();
 assert.equal(document.getElementById('hb-label').dataset.linkState,'offline');
});
test('DOM lamps restore the original SDK label and mirror state without issuing commands',()=>{
 const {document,window}=parseHTML('<html lang="en"><body><div class="topbar-status"><span id="hb-label">SDK: --</span></div><article class="overview-card-feedback"><span class="summary-icon"></span></article></body></html>');
 let time=1000,writes=0,tick;const handlers={},view={MutationObserver:window.MutationObserver,addEventListener(){},setInterval(fn){tick=fn;return {unref(){}};}};
 const lamps=api().mountStatusLights(document,view,{now:()=>time});lamps.bind({on(name,fn){handlers[name]=fn;},send(){writes++;},connect(){writes++;}});
 handlers.ws_connection({connected:true});handlers.robot_state(good);
 assert.equal(document.getElementById('hb-label').dataset.linkState,'online');assert.equal(document.querySelector('.overview-card-feedback').dataset.linkState,'online');
 time=4000;tick();assert.equal(document.getElementById('hb-label').dataset.linkState,'offline');assert.match(document.getElementById('hb-label').textContent,/No feedback/);
 document.getElementById('hb-label').textContent='SDK:OK';handlers.connection({connected:false});
 assert.equal(document.getElementById('hb-label').dataset.linkState,'offline');assert.match(document.getElementById('hb-label').textContent,/Offline/);
 assert.equal(document.getElementById('workspace-web-status').dataset.linkState,'online');assert.equal(writes,0);
});
