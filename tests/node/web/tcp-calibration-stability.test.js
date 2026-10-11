'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { CalibrationPoseStability } = require('../../../apps/web/src/tcp-calibration/pose-stability');

function frame(i, extra = {}) {
  return { connected:true, healthy:true, moving:false, teachActive:false, stateFresh:true,
    streamId:'stream-a', stateSequence:i+1, producerMonotonicNs:1e9+i*5e7,
    jointsDeg:[3,96,-82,82,8,2], flangePositionM:[.2,.3,.4], flangeEulerRad:[0,0,0],
    stationary:false, velocitiesDegS:[.11,.11,.11,1.259,.42,-.42], ...extra };
}
test('calibration waits for a full second of fresh stable poses despite velocity quantization', () => {
  const tracker=new CalibrationPoseStability();
  for(let i=0;i<20;i++) { tracker.observe(frame(i)); assert.equal(tracker.ready(frame(i)),false); }
  tracker.observe(frame(20)); assert.equal(tracker.ready(frame(20)),true);
  assert.equal(tracker.ready(frame(20,{stateFresh:false})),false);
});
test('same-frame reads cannot manufacture a stability window', () => {
  const tracker=new CalibrationPoseStability();
  for(let i=0;i<30;i++) tracker.observe(frame(0));
  assert.equal(tracker.ready(frame(0)),false);
});
test('motion, teaching, disconnect, gaps and changed stream immediately revoke stability', () => {
  for(const change of [{moving:true},{teachActive:true},{connected:false},{healthy:false},
    {stateFresh:false},{streamId:'stream-b'},{producerMonotonicNs:4e9},
    {jointsDeg:[3,96,-82,82.1,8,2]},{flangePositionM:[.201,.3,.4]},
    {flangeEulerRad:[0,0,.01]}]) {
    const tracker=new CalibrationPoseStability();
    for(let i=0;i<=20;i++)tracker.observe(frame(i));
    tracker.observe(frame(21,change));assert.equal(tracker.ready(frame(21,change)),false);
  }
});
test('slow cumulative drift is blocked and observed single encoder-step jitter is tolerated', () => {
  const drift=new CalibrationPoseStability(), jitter=new CalibrationPoseStability();
  for(let i=0;i<=30;i++) {
    const moving=frame(i,{jointsDeg:[3,96,-82,82+i*.005,8,2]});
    drift.observe(moving);assert.equal(drift.ready(moving),false);
    const still=frame(i,{jointsDeg:[3,96,-82,82+(i%2)*.021857,8,2]});
    jitter.observe(still); if(i>=20)assert.equal(jitter.ready(still),true);
  }
});
