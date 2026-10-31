'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createSimulationController}=require('../../../apps/web/public/js/simulation-controller');
function fixture(){let now=0;const arm={joints:[0,90,-90,0,0,0],gripper:1,jointLimits:[[-162,162],[-12,201],[-183,0],[-98,98],[-98,98],[-164,164]],getJointAngles(){return [...this.joints];},setJointAngles(v){this.joints=[...v];},getGripperPosition(){return this.gripper;},setGripperPosition(v){this.gripper=v;}};
  const simulation=createSimulationController({armModel:arm,clock:{now:()=>now,sleep:async ms=>{now+=ms;}}});return {arm,simulation};}
test('a model waypoint interpolates six joints and gripper together and reports completion',async()=>{
  const f=fixture(),states=[];assert.equal(typeof f.simulation.subscribe,'function');const unsub=f.simulation.subscribe(s=>states.push(s));
  assert.equal((await f.simulation.playSequence([{joints:[20,80,-100,10,0,0],gripper:.25,durationMs:100}])).completed,true);
  assert.deepEqual(f.arm.joints,[20,80,-100,10,0,0]);assert.equal(f.arm.gripper,.25);
  assert.ok(states.some(s=>s.gripper<1&&s.gripper>.25));assert.equal(states.at(-1).outcome,'completed');unsub();
});
test('stop freezes both model channels; invalid gripper or sparse angles change neither',async()=>{
  const f=fixture(),pending=f.simulation.playSequence([{joints:[30,80,-100,10,0,0],gripper:0,durationMs:800}]);
  f.simulation.stop();const after={joints:[...f.arm.joints],gripper:f.arm.gripper};assert.equal((await pending).completed,false);
  assert.deepEqual({joints:f.arm.joints,gripper:f.arm.gripper},after);
  await assert.rejects(f.simulation.playSequence([{joints:[0,90,-90,0,0,0],gripper:2,durationMs:100}]));
  assert.throws(()=>f.simulation.setJoints(Array(6)));assert.deepEqual(f.arm.joints,after.joints);
});
