'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {ManualJointOrchestrator}=require('../../../apps/web/src/language/manual-joint-control');
const {DirectionalJointOrchestrator}=require('../../../apps/web/src/language/directional-joint-control');
const limits=[[-162,162],[-12,201],[-183,0],[-98,98],[-98,98],[-164,164]];
for(const params of [
  {action:'joint.set',joint:1,targetDeg:90},
  {action:'joint.multi',moves:[{joint:1,targetDeg:90},{joint:2,targetDeg:90}]},
  {action:'robot.home'},
]){
  test(params.action+' waits for SDK trajectory completion, retaining bounded stop',()=>{
    const timers=[],sent=[];let stops=0;
    const state={connected:true,stateFresh:true,ageMs:0,stateName:'IDLE',motionActive:false,jointsDeg:[0,0,0,0,0,0]};
    const orchestrator=new ManualJointOrchestrator({enabled:true,
      getRobotState:()=>state,getHomeTarget:()=>[90,90,-90,90,0,0],jointLimitsDeg:limits,
      moveTimeFor:()=>6,sendRobot:command=>{sent.push(command);return true;},
      softwareStop:()=>{stops++;},now:()=>2000,
      schedule:(fn,ms)=>{timers.push({fn,ms});return timers.length;},cancelSchedule:()=>{}});
    const candidate={candidateId:'wait',traceId:'trace',sourceText:'测试关节运动',skill:'manual_joint_control@1',intent:params.action,
      createdAt:1000,expiresAt:120000,requiresConfirmation:true,payload:{params}};
    orchestrator.register('browser',candidate);
    orchestrator.decide('browser',{candidateId:'wait',traceId:'trace',decision:'approve'});
    assert.equal(sent.length,1);
    assert.equal(timers[0].ms,45000);
    assert.equal('time_sec' in sent[0],false);
    assert.equal(stops,0);
    timers[0].fn();
    assert.equal(stops,1);
  });
}

test('directional movement uses bounded shared completion wait, not endpoint estimate',()=>{
  const timers=[],sent=[];let stops=0;
  const state={connected:true,stateFresh:true,ageMs:0,stateName:'IDLE',motionActive:false,jointsDeg:[0,0,0,0,0,0]};
  const controller=new DirectionalJointOrchestrator({enabled:true,realControlEnabled:true,
    getRobotState:()=>state,jointLimitsDeg:limits,forwardKinematics:()=>[.45,0,.3],
    moveTimeFor:()=>6,sendRobot:command=>{sent.push(command);return true;},
    softwareStop:()=>{stops++;},now:()=>2000,
    schedule:(fn,ms)=>{timers.push({fn,ms});return timers.length;},cancelSchedule:()=>{}});
  controller._execute('browser',{candidateId:'direction',traceId:'trace',sourceText:'左转',skill:'directional_joint_control@1',
    payload:{params:{action:'turn.left',deltaDeg:20}}},{action:'turn.left',deltaDeg:20});
  assert.equal(sent.length,1);
  assert.equal(timers[0].ms,45000);
  assert.equal('time_sec' in sent[0],false);
  assert.equal(stops,0);
  timers[0].fn();
  assert.equal(stops,1);
});
