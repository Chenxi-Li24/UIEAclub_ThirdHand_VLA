'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {RobotController}=require('../../../services/robot/src/robot-controller');

function readyController() {
  const robot=new RobotController({speedScale:1,minMoveTimeSec:.5,maxMoveTimeSec:30,simulate:true});
  robot.bridge.connected=true;
  robot.stateReady=true;
  robot.latestJointsDeg=[1,1,-1,1,1,1];
  robot.latestRobotStateAtMs=Date.now();
  robot.bridge.send=command=>{robot.sent=command;return true;};
  return robot;
}
test('manual, fixed and named joint targets cannot bypass caps with time mode',()=>{
  for(const source of ['servo','meituan:fixed','preset:zero','preset:home','preset:observe']){
    const robot=readyController();
    robot._sendJointMotion([2,2,-2,2,2,2],source,error=>assert.fail(JSON.stringify(error)),'speed-test','move_joint',.001);
    assert.equal(robot.sent.speed_percent,.05);
    assert.equal('time_sec' in robot.sent,false);
    assert.deepEqual(robot.sent.joints_rad,[2,2,-2,2,2,2].map(v=>v*Math.PI/180));
  }
});
test('Cartesian target accepts no duration and cannot accelerate with supplied duration',()=>{
  for(const time_sec of [undefined,.001,100]){
    const robot=readyController();
    robot._sendLinearMotion({position:[.4,0,.3],euler:[0,0,0],time_sec},error=>assert.fail(JSON.stringify(error)));
    assert.equal(robot.sent.cmd,'move_l');
    assert.equal(robot.sent.speed_percent,.05);
    assert.equal('time_sec' in robot.sent,false);
  }
});
test('published policy describes effective caps even with oversized configured scale',()=>{
  const policy=readyController().configMessage().motion;
  assert.deepEqual(policy.commandedSpeedsDegS,[15,15,15,50,50,50]);
  assert.equal(policy.planningMode,'sdk_joint_speed');
});
