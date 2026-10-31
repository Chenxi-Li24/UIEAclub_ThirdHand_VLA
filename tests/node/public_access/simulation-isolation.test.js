'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');

function fixture(){
  let networkCalls=0,now=0;
  const context={module:{exports:{}},WebSocket:class{constructor(){networkCalls++;throw Error('Real control is forbidden');}},fetch(){networkCalls++;throw Error('Network is forbidden');},setTimeout,clearTimeout};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../../apps/web/public/js/simulation-controller.js'),'utf8'),context);
  const model={joints:[0,0,0,0,0,0],jointLimits:[[-162,162],[-12,201],[-183,0],[-98,98],[-98,98],[-164,164]],getJointAngles(){return this.joints.slice();},setJointAngles(value){this.joints=[...value];}};
  const controller=context.module.exports.createSimulationController({armModel:model,clock:{now:()=>now,sleep:async ms=>{now+=ms;}}});
  return {model,controller,networkCalls:()=>networkCalls};
}
test('sliders, fixed poses and sequences only mutate their own model and never create a control connection',async()=>{
  const a=fixture(),b=fixture();
  a.controller.setJoints([12,20,-30,4,5,6]);assert.deepEqual(a.model.joints,[12,20,-30,4,5,6]);assert.deepEqual(b.model.joints,[0,0,0,0,0,0]);
  await a.controller.playPreset('ready');assert.deepEqual(a.model.joints,[0,90,-90,0,0,0]);
  await a.controller.playSequence([{joints:[10,70,-80,20,0,0],durationMs:100},{joints:[0,90,-90,0,0,0],durationMs:100}]);
  assert.deepEqual(a.model.joints,[0,90,-90,0,0,0]);assert.equal(a.networkCalls(),0);assert.equal(b.networkCalls(),0);
  assert.throws(()=>a.controller.setJoints([999,0,0,0,0,0]),/limit|range/i);
  assert.throws(()=>a.controller.setJoints([NaN,0,0,0,0,0]),/finite|invalid/i);
});
test('incoming live telemetry cannot overwrite an edited simulation; stopping cancels a sequence without SDK activity',async()=>{
  const f=fixture();f.controller.setJoints([15,50,-60,0,0,0]);
  f.controller.receiveLive([0,90,-90,0,0,0]);assert.deepEqual(f.model.joints,[15,50,-60,0,0,0]);
  f.controller.followLive(true);f.controller.receiveLive([0,90,-90,0,0,0]);assert.deepEqual(f.model.joints,[0,90,-90,0,0,0]);
  f.controller.setJoints([5,40,-50,0,0,0]);f.controller.receiveLive([1,2,-3,0,0,0]);assert.deepEqual(f.model.joints,[5,40,-50,0,0,0]);
  const playing=f.controller.playSequence([{joints:[10,50,-60,0,0,0],durationMs:1000}]);f.controller.stop();
  assert.equal((await playing).completed,false);assert.equal(f.networkCalls(),0);
});
