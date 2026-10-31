'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {createHistoryReplay}=require('../../../apps/web/public/js/history-replay');
test('history replay renders only measured model poses, holds gaps and refuses incompatible or invalid samples',()=>{
  const calls=[],armModel={jointLimits:Array.from({length:6},()=>[-180,180]),setJointAngles:value=>calls.push(value)};
  const rows=[{captured_at:'2026-10-30T09:00:00Z',joint_position_rad:[0,Math.PI/2,0,0,0,0],extra:{sourceMode:'hardware'}},{captured_at:'2026-10-30T09:00:02Z',joint_position_rad:[0,1,0,0,0,0]}];
  const replay=createHistoryReplay({armModel,samples:rows,gapMs:500});
  assert.equal(replay.seek(0).state,'measured');assert.equal(calls[0][1],90);
  assert.equal(replay.seek(1000).state,'gap');assert.equal(calls.length,1);
  assert.equal(replay.seek(2000).state,'measured');assert.equal(calls.length,2);
  assert.equal(replay.seek(3000).state,'end');
  assert.equal(createHistoryReplay({armModel,samples:[{...rows[0],joint_position_rad:[9,0,0,0,0,0]}]}).seek(0).state,'invalid');
  assert.equal(createHistoryReplay({armModel,samples:rows,versions:{expectedTool:'v2'}}).seek(0).state,'incompatible');
  assert.equal(calls.length,2);
});
