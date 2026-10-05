'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),{EventEmitter}=require('node:events');
const {GraspCoordinator}=require('../../../apps/web/src/grasp/coordinator');
const {fixture}=require('./grasp-geometry.test');
const pause=()=>new Promise(r=>setImmediate(r));
async function setup(options={}){
 const f=fixture(),events=[];let frame=10,sequence=1;
 const config={...f.config,stepIntervalMs:0,commandTimeoutMs:1000,maxIkStepDeg:5,positionToleranceM:0.015,
  orientationToleranceRad:0.1,contactMinM:0.008,contactMaxM:0.070};
 const state={...f.robot,connected:true,healthy:true,moving:false,stateName:'IDLE',gripper_width_m:0.003,
  state_sequence:sequence,observedAtMs:1000};
 const robot=new EventEmitter();robot.pending=null;robot.ownerTag=null;
 robot.state=()=>({...state,state_sequence:++sequence,joints_deg:[...state.joints_deg],flange_position_m:[...state.flange_position_m]});
 robot.ready=async()=>robot.state();robot.preview=async pose=>({ok:true,joints_deg:[0,0,-1,0,0,0]});
 robot.command=async command=>{events.push(command);if(options.command)return options.command(command,state,robot);
  if(command.cmd==='move_l')state.flange_position_m=[...command.position];
  if(command.cmd==='gripper')state.gripper_width_m=command.position===0?(options.contactWidth??0.03):0.08;
  return {reached:command.cmd!=='gripper'||command.position!==0,actual_width_m:state.gripper_width_m};};
 robot.stop=async()=>{events.push({cmd:'software_stop'});return {status:'interrupted'};};robot.close=()=>events.push({cmd:'transport_close'});
 const vision={snapshot:async()=>({observation:{...f.observation,frame_id:++frame,selectedStableId:options.switchTarget?1:2},runtimeEvidence:{}})};
 const depth={start:async()=>{},status:()=>({phase:'depth_acquired',active:false}),stop:async()=>{},close:async()=>{}};
 const c=new GraspCoordinator({config,robotClient:robot,visionClient:vision,depthCoordinator:depth,now:()=>1000,sleep:async()=>{await pause();}});
 return {c,events,robot,state};
}
async function finish(c){for(let i=0;i<1000&&c.status().active;i++)await pause();return c.status();}
test('one start runs depth through contact and lift without confirmations or release',async()=>{
 const {c,events}=await setup();await c.start(2,'run-1');const s=await finish(c);
 assert.equal(s.phase,'complete',s.reason);assert.equal(s.holding,true);
 assert.deepEqual(events.filter(e=>e.cmd==='gripper').map(e=>e.position),[1,0]);
 assert.deepEqual(events.filter(e=>e.cmd==='move_l').at(-1).position,[0.51334,0,0.25]);
 assert.equal(events.some(e=>['connect','disconnect','software_stop'].includes(e.cmd)),false);
});
test('duplicate request never repeats real commands',async()=>{
 const {c,events}=await setup();await c.start(2,'same');await finish(c);const before=events.length;
 await c.start(2,'same');await pause();assert.equal(events.length,before);
 await assert.rejects(c.start(1,'same'),/request_id_conflict/);
});
test('target switch ends idle session without dropping holding torque',async()=>{
 const {c,events}=await setup({switchTarget:true});await c.start(2,'switched');const s=await finish(c);
 assert.equal(s.phase,'failed');assert.equal(events.length,0);
});
test('empty close does not lift or release the gripper',async()=>{
 const {c,events}=await setup({contactWidth:0.003});await c.start(2,'no-contact');const s=await finish(c);
 assert.equal(s.phase,'failed');assert.equal(s.reason,'contact_not_observed');
 const closing=events.findIndex(e=>e.cmd==='gripper'&&e.position===0);
 assert.equal(events.slice(closing+1).some(e=>e.cmd==='move_l'),false);
 assert.equal(events.some(e=>e.cmd==='software_stop'),false);
});
test('stop while an actuator command is in flight sends one stop and stays terminal',async()=>{
 let unblock;const {c,events,robot}=await setup({command:async(cmd,state)=>{if(cmd.cmd==='gripper'){state.gripper_width_m=0.08;return {reached:true};}return new Promise(r=>{unblock=r;});}});
 await c.start(2,'stop-run');for(let i=0;i<100&&!unblock;i++)await pause();
 assert.ok(unblock);await c.stop(c.status().sessionId);unblock({reached:true});await pause();
 assert.equal(c.status().phase,'stopped');assert.equal(events.filter(e=>e.cmd==='software_stop').length,1);
});
test('unreachable contact path is rejected before any gripper movement',async()=>{
 const {c,events,robot}=await setup();robot.preview=async()=>{throw new Error('ik_invalid');};
 await c.start(2,'bad-ik');const s=await finish(c);assert.equal(s.phase,'failed');assert.equal(events.length,0);
});
test('completion preceding the final IDLE feedback waits instead of dropping the sequence',async()=>{
 const {c,robot,state}=await setup();let late=false;const originalState=robot.state,originalCommand=robot.command;
 robot.command=async cmd=>{const r=await originalCommand(cmd);late=true;return r;};
 robot.state=options=>{if(late){late=false;if(options?.idle){const e=new Error('robot_not_stationary');e.code=e.message;throw e;}return {...originalState(),moving:true,stateName:'MOVING'};}return originalState();};
 await c.start(2,'late-idle');const s=await finish(c);assert.equal(s.phase,'complete',s.reason);
});
test('selection lost while opening prevents even the first preapproach segment',async()=>{
 const options={},v=await setup(options),original=v.robot.command;
 v.robot.command=async cmd=>{const r=await original(cmd);if(cmd.cmd==='gripper'&&cmd.position===1)options.switchTarget=true;return r;};
 await v.c.start(2,'lost-opening');const status=await finish(v.c);
 assert.equal(status.phase,'failed');assert.equal(v.events.some(e=>e.cmd==='move_l'),false);
});
test('failed stop confirmation keeps uncertain motion owned and interlocked',async()=>{
 const {c,robot}=await setup({command:async cmd=>{if(cmd.cmd==='gripper')return {reached:true};const e=new Error('robot_error');e.code='robot_error';e.motionUncertain=true;throw e;}});
 const state=robot.state();robot.state=()=>({...state,gripper_width_m:0.08,state_sequence:++state.state_sequence});robot.stop=async()=>{throw Error('stop_unconfirmed');};
 await c.start(2,'uncertain-stop');for(let i=0;i<1000&&c.status().phase!=='uncertain';i++)await pause();
 assert.equal(c.status().phase,'uncertain');assert.equal(c.status().active,true);assert.ok(robot.ownerTag);
 await assert.rejects(c.start(2,'no-reentry'),/grasp_active/);
});
test('motion epoch clears transient visual evidence and waits idle for the next correlated frame',async()=>{
 const {c,events}=await setup();const snapshot=c.visionClient.snapshot;let missing=2;
 c.visionClient.snapshot=async id=>{if(c.status().phase==='preapproach'&&missing-->0){const e=new Error('status detection is updating');e.code='vision_evidence_mismatch';throw e;}return snapshot(id);};
 await c.start(2,'epoch-switch');const s=await finish(c);assert.equal(s.phase,'complete',s.reason);
 assert.equal(events.some(e=>e.cmd==='software_stop'),false);
});
test('persistent missing visual evidence expires before preapproach motion without dropping SDK',async()=>{
 const {c,events}=await setup();const snapshot=c.visionClient.snapshot;
 c.visionClient.snapshot=async id=>{if(c.status().phase==='preapproach'){const e=new Error('status detection is updating');e.code='vision_evidence_mismatch';throw e;}return snapshot(id);};
 await c.start(2,'epoch-expired');const s=await finish(c);assert.equal(s.reason,'vision_evidence_timeout');
 assert.equal(events.some(e=>e.cmd==='move_l'||e.cmd==='software_stop'),false);
});
