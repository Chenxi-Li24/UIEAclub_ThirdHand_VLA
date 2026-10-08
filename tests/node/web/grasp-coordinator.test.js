'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),{EventEmitter}=require('node:events');
const {GraspCoordinator}=require('../../../apps/web/src/grasp/coordinator');
const {fixture}=require('./grasp-geometry.test');
const pause=()=>new Promise(r=>setImmediate(r));
async function setup(options={}){
 const f=fixture(),events=[];let frame=10,sequence=1;
 const config={...f.config,...options.config,stepIntervalMs:0,commandTimeoutMs:1000,maxIkStepDeg:5,positionToleranceM:0.015,
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
test('phase-linear mode executes three native trajectories while checking every 5mm sample',async()=>{
 const {c,events,robot}=await setup({config:{executionMode:'phase_linear',orientationMode:'horizontal',horizontalToleranceRad:.05}});
 let previews=0;const preview=robot.preview;robot.preview=async pose=>{previews++;return preview(pose);};
 await c.start(2,'continuous-horizontal');const s=await finish(c);
 assert.equal(s.phase,'complete',s.reason);
 assert.deepEqual(events.filter(e=>e.cmd==='move_l').map(e=>e.position),[[.41334,0,.2],[.51334,0,.2],[.51334,0,.25]]);
 assert.ok(previews>30,'IK sampling must not be replaced with endpoint-only checking');
 assert.equal(s.completedSegments,3);
});
test('horizontal depth delegates acquisition to the horizontal coordinator before any grasp command',async()=>{
 const {c,events}=await setup({config:{orientationMode:'horizontal',horizontalToleranceRad:.05}});
 const snapshot=c.visionClient.snapshot;let observations=0,alignment=0;
 c.visionClient.snapshot=async id=>{const s=await snapshot(id);if(++observations<=2)s.observation.targets=s.observation.targets.map(t=>({...t,depth_valid:false}));return s;};
 c.depthCoordinator.start=async()=>{alignment++;};
 await c.start(2,'static-depth');const s=await finish(c);
 assert.equal(s.phase,'complete',s.reason);assert.equal(alignment,1);
 assert.equal(events.some(e=>e.cmd==='servo'),false);
});
test('grasp freezes the heading reached by horizontal depth rather than rotating back to the pre-acquisition heading',async()=>{
 const {c,state,events}=await setup({config:{orientationMode:'horizontal',executionMode:'phase_linear'}});
 const snapshot=c.visionClient.snapshot;let observations=0;
 c.visionClient.snapshot=async id=>{const s=await snapshot(id);if(++observations===1)s.observation.targets=s.observation.targets.map(t=>({...t,depth_valid:false}));return s;};
 c.depthCoordinator.start=async()=>{state.flange_euler_rad=[0,0,.017];};
 await c.start(2,'depth-heading');const s=await finish(c);assert.equal(s.phase,'complete',s.reason);
 assert.ok(events.filter(e=>e.cmd==='move_l').every(e=>Math.abs(e.euler[2]-.017)<1e-9));
});
test('pitched start in horizontal mode never opens the gripper or moves the robot',async()=>{
 const {c,state,events}=await setup({config:{orientationMode:'horizontal',horizontalToleranceRad:.05}});
 state.flange_euler_rad=[0,.49,0];
 await c.start(2,'pitched-start');const s=await finish(c);
 assert.equal(s.reason,'tool_not_horizontal');assert.deepEqual(events,[]);
});
test('checkpoint depth reacquisition refreshes horizontal heading for approach and lift',async()=>{
 const {c,state,events}=await setup({config:{orientationMode:'horizontal',executionMode:'phase_linear'}});
 const snapshot=c.visionClient.snapshot;let alignment=0;
 c.visionClient.snapshot=async id=>{const r=await snapshot(id);if(c.status().phase==='target_refresh'&&!alignment)r.observation.targets=r.observation.targets.map(t=>({...t,depth_valid:false}));return r;};
 c.depthCoordinator.start=async()=>{alignment++;state.flange_euler_rad=[0,0,.017];};
 await c.start(2,'checkpoint-depth-heading');assert.equal((await finish(c)).phase,'complete');assert.equal(alignment,1);
 const moves=events.filter(e=>e.cmd==='move_l');assert.equal(moves[0].euler[2],0);
 assert.ok(moves.slice(1).every(e=>Math.abs(e.euler[2]-.017)<1e-9));
});
test('loss of selected target during a continuous preapproach stops the in-flight trajectory',async()=>{
 let moving=false,unblock;
 const {c,events,robot}=await setup({config:{executionMode:'phase_linear',orientationMode:'horizontal'},
  command:async(cmd,state)=>{if(cmd.cmd==='gripper'){state.gripper_width_m=.08;return {reached:true};}
   moving=true;return new Promise(resolve=>{unblock=resolve;});}});
 const snapshot=c.visionClient.snapshot;
 c.visionClient.snapshot=async id=>{const result=await snapshot(id);if(moving)result.observation.targets=[];return result;};
 await c.start(2,'continuous-target-loss');const s=await finish(c);
 if(unblock)unblock({reached:false});
 assert.equal(s.phase,'failed',s.reason);assert.equal(s.reason,'target_lost');
 assert.equal(events.filter(e=>e.cmd==='software_stop').length,1);
 assert.equal(events.filter(e=>e.cmd==='move_l').length,1);
});
test('continuous phase previews the fresh actual-start line rather than an obsolete nominal line',async()=>{
 let opened=false;const checked=[];
 const {c,robot,state}=await setup({config:{executionMode:'phase_linear',orientationMode:'horizontal'}});
 const command=robot.command,preview=robot.preview;
 robot.command=async cmd=>{const result=await command(cmd);if(cmd.cmd==='gripper'&&cmd.position===1){opened=true;state.flange_position_m[1]=.012;}return result;};
 robot.preview=async pose=>{if(opened)checked.push(structuredClone(pose));return preview(pose);};
 await c.start(2,'fresh-start-path');const s=await finish(c);assert.equal(s.phase,'complete',s.reason);
 assert.ok(checked[0].position[1]>.01,'fresh lateral offset must be present in actual trajectory samples');
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
test('visibility-preserving farther checkpoint executes its bounded final approach',async()=>{
 const {c}=await setup({config:{preapproachM:0.18,maxApproachM:0.22,keepPreapproachSdkHeight:true}});
 await c.start(2,'farther-checkpoint');const s=await finish(c);assert.equal(s.phase,'complete',s.reason);
});
test('fresh 60mm bottle contact is usable even when visual width underestimates it',async()=>{
 const {c}=await setup({contactWidth:0.060});await c.start(2,'wide-contact');const s=await finish(c);
 assert.equal(s.phase,'complete',s.reason);assert.equal(s.result.gripperWidthM,0.060);
});

test('one grasp freezes measured TCP across activation changes and publishes plan progress',async()=>{
 const {c}=await setup({config:{forwardBackoffM:.06,calibratedForwardBackoffM:0}});
 let active={id:'tcp-A',source:'measured',T_flange_grasp_tcp:[[1,0,0,.09],[0,1,0,.02],[0,0,1,.01],[0,0,0,1]]};
 c.resolveTcp=()=>active;
 const statuses=[];c.on('status',s=>{statuses.push(s);if(s.phase==='depth_acquiring')active={...active,id:'tcp-B',T_flange_grasp_tcp:[[1,0,0,.16],[0,1,0,0],[0,0,1,0],[0,0,0,1]]};});
 await c.start(2,'freeze-tcp');const result=await finish(c);
 assert.equal(result.phase,'complete',result.reason);assert.equal(result.tcp.id,'tcp-A');
 assert.equal(result.tcp.forwardBackoffM,0);assert.deepEqual(result.result.actualGripM,[.4,0,.25]);
 assert.deepEqual(result.plan.contact.position,[.48334,-.02,.19]);
 assert.ok(statuses.some(s=>s.progress?.completed>0&&s.progress.total>=s.progress.completed));
 assert.equal(c.tcpConfiguration().id,'tcp-B');
});
test('invalid active calibration refuses grasp before ownership or any actuator command',async()=>{
 const {c,events}=await setup();c.resolveTcp=()=>{throw Error('artifact_hash_mismatch');};
 await assert.rejects(c.start(2,'bad-tcp'),/artifact_hash_mismatch/);
 assert.equal(c.status().active,false);assert.equal(events.length,0);
});

async function stoppingHarness(){
 const {WebRobotClient}=require('../../../apps/web/src/grasp/robot-client');
 const {c,state}=await setup();const wire=[];
 const client=new WebRobotClient({url:'ws://127.0.0.1:9983/ws',deferConnect:true,now:()=>1000});
 client.last=state;client.receivedAt=1000;
 client.socket={readyState:1,send(raw){const command=JSON.parse(raw);wire.push(command);
  if(command.cmd==='gripper'){
   client._message(JSON.stringify({type:'command_status',status:'complete',request_id:command.request_id,reached:true}));
   client._message(JSON.stringify({...client.last,type:'robot_state',gripper_width_m:.08,state_sequence:client.last.state_sequence+1}));
  }
 }};
 client.ready=async()=>client.state();client.preview=async()=>({ok:true,joints_deg:[0,0,-1,0,0,0]});
 const actualState=client.state.bind(client);client.state=options=>{client.last.state_sequence++;return actualState(options);};
 c.robotClient=client;
 await c.start(2,'stop-real-client');
 for(let i=0;i<1000&&!wire.some(m=>m.cmd==='move_l');i++)await pause();
 assert.ok(wire.some(m=>m.cmd==='move_l'),c.status().reason);
 return {c,client,wire};
}
test('real client operator-stop rejection retains ownership until delayed stop acknowledgement',async()=>{
 const {c,client,wire}=await stoppingHarness();const stopping=c.stop(c.status().sessionId);
 await pause();assert.equal(c.status().phase,'stopping');assert.equal(c.status().active,true);assert.ok(client.ownerTag);
 const stop=wire.find(m=>m.cmd==='software_stop');assert.ok(stop);
 client._message(JSON.stringify({type:'command_status',status:'complete',request_id:stop.request_id,stopped:true}));
 await stopping;assert.equal(c.status().phase,'stopped');assert.equal(c.status().active,false);assert.equal(client.ownerTag,null);
});
test('real client rejected stop acknowledgement remains uncertain and owned',async()=>{
 const {c,client,wire}=await stoppingHarness();const stopping=c.stop(c.status().sessionId);
 await pause();const stop=wire.find(m=>m.cmd==='software_stop');
 client._message(JSON.stringify({type:'command_status',status:'complete',request_id:stop.request_id,stopped:false}));
 await stopping;assert.equal(c.status().phase,'uncertain');assert.equal(c.status().active,true);assert.ok(client.ownerTag);
});
test('uncertain nested depth command awaits shared stop before releasing parent ownership',async()=>{
 const {c,robot}=await setup();let rejectStop;
 c.visionClient.snapshot=async()=>({observation:{...fixture().observation,frame_id:11,selectedStableId:2,
  targets:fixture().observation.targets.map(t=>({...t,depth_valid:false}))}});
 c.depthCoordinator.start=async()=>{robot.lastStopAt=1000;robot.lastStopPromise=new Promise((_,reject)=>{rejectStop=reject;});};
 c.depthCoordinator.status=()=>({phase:'uncertain',active:false,reason:'feedback_invalid'});
 await c.start(2,'uncertain-depth');await pause();assert.equal(c.status().active,true);assert.ok(robot.ownerTag);
 rejectStop(Error('stop_unconfirmed'));await pause();await pause();
 assert.equal(c.status().phase,'uncertain');assert.equal(c.status().active,true);assert.ok(robot.ownerTag);
});
test('uncertain nested depth stop cannot publish inactive parent stopped',async()=>{
 const {c,robot}=await setup();let started=false;
 c.visionClient.snapshot=async()=>({observation:{...fixture().observation,frame_id:11,selectedStableId:2,
  targets:fixture().observation.targets.map(t=>({...t,depth_valid:false}))}});
 c.depthCoordinator.start=async()=>{started=true;};
 c.depthCoordinator.status=()=>({phase:'moving',active:true,sessionId:'depth'});
 c.depthCoordinator.stop=async()=>({phase:'uncertain',active:false});
 robot.stop=async()=>{throw Error('stop_unconfirmed');};
 await c.start(2,'depth-stop');for(let i=0;i<1000&&!started;i++)await pause();
 await c.stop(c.status().sessionId);
 assert.equal(c.status().phase,'uncertain');assert.equal(c.status().active,true);assert.ok(robot.ownerTag);
});
test('operator cancellation supersedes a failure handler already awaiting the automatic stop',async()=>{
 const {c,robot}=await setup();const command=robot.command;let confirm;
 robot.command=async cmd=>{if(cmd.cmd==='move_l'){const error=Error('feedback_stale');error.motionUncertain=true;throw error;}return command(cmd);};
 robot.stop=()=>{robot.lastStopAt=1000;return robot.lastStopPromise=new Promise(r=>{confirm=r;});};
 await c.start(2,'cancel-during-autostop');for(let i=0;i<1000&&!confirm;i++)await pause();assert.ok(confirm);
 const canceled=c.stop(c.status().sessionId);confirm({status:'interrupted'});await canceled;
 assert.equal(c.status().phase,'stopped');assert.equal(robot.ownerTag,null);
});
