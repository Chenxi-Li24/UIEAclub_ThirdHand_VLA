'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),http=require('node:http');
const {once}=require('node:events');
const {WebSocket,WebSocketServer}=require('ws');
const {createWebGateway}=require('../../../apps/web/src/server');
const {GraspCoordinator}=require('../../../apps/web/src/grasp/coordinator');
const {WebRobotClient}=require('../../../apps/web/src/grasp/robot-client');
const {VisionClient}=require('../../../apps/web/src/active-depth/vision-client');
const {TcpCalibrationArtifactStore}=require('../../../apps/web/src/tcp-calibration/artifact-store');
const {loadPolicy}=require('../../../services/vision/src/frames/robot_frame_normalization');
const root=path.resolve(__dirname,'../../..');
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(predicate){for(let n=0;n<500;n++){if(predicate())return;await wait(5);}assert.fail('offline pipeline timeout');}

test('HTTP target selection and one start traverse actual gateway sockets to measured TCP contact and lift',async t=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'web-grasp-tcp-e2e-'));
 const policyFile=path.join(root,'configs/vision/sdk-tool-frame-policy.json'),policyId=loadPolicy(policyFile).id;
 const config={...JSON.parse(fs.readFileSync(path.join(root,'apps/web/configs/web-grasp.json'))),
  preapproachM:.10,keepPreapproachSdkHeight:false,stepIntervalMs:0,stateMaxAgeMs:750};
 const store=new TcpCalibrationArtifactStore({root:path.join(temp,'tcp')});
 const saved=store.finalizePending({schema:'thirdhand-tcp-calibration-session-v1',sessionId:'offline-measured',revision:14,
  stage:'ready_to_finalize',framePolicyId:policyId,solveReport:{accepted:true},validationReport:{accepted:true},
  derivedTcp:{schema:'thirdhand-grasp-tcp-derived-v1',T_flange_grasp_tcp:[[1,0,0,.09],[0,1,0,.02],[0,0,1,.01],[0,0,0,1]]}});
 store.activate({candidateId:saved.candidateId,expectedActiveId:null});
 const received=[],sockets=new Set();let sequence=0;
 const state={type:'robot_state',connected:true,healthy:true,stateName:'IDLE',moving:false,pose_frame:'robot_flange',
  joints_deg:[0,0,-1,0,0,0],velocities_deg_s:[0,0,0,0,0,0],flange_position_m:[.3,0,.2],flange_euler_rad:[0,0,0],gripper_width_m:.03};
 const robot=new WebSocketServer({host:'127.0.0.1',port:0});await once(robot,'listening');
 const send=(socket,payload)=>{if(socket.readyState===WebSocket.OPEN)socket.send(JSON.stringify(payload));};
 const feedback=()=>{const value={...state,state_sequence:++sequence,producer_monotonic_ns:Number(process.hrtime.bigint())};for(const socket of sockets)send(socket,value);};
 robot.on('connection',socket=>{sockets.add(socket);socket.on('close',()=>sockets.delete(socket));socket.on('message',bytes=>{
  const command=JSON.parse(bytes);received.push(command);
  if(command.type==='capability_request'){
   send(socket,{type:'capability_response',schema:'thirdhand-robot-capability-v1',nonce:command.nonce,
    protocol_version:'thirdhand-robot-lowlevel-v1',pose_frame:'robot_flange',
    commands:['move_l','move_joint','gripper','preset','software_stop','get_state','preview_ik','fixed_tcp_demo','follow_start','follow_target','follow_stop'],
    correlated_completions:true,software_stop_ack:true,software_stop_state_boundary:true,
    state_units:{position:'m',orientation:'rad',joints:'deg',joint_velocity:'deg/s',gripper:'m'},
    state_stream:{sequence:'uint53',producer_monotonic_ns:'uint53',strictly_increasing:true},state_sequence:sequence,producer_monotonic_ns:Number(process.hrtime.bigint())});
  }else if(['get_state','status'].includes(command.cmd))feedback();
  else if(command.cmd==='preview_ik')send(socket,{type:'ik_preview',request_id:command.request_id,ok:true,joints_deg:state.joints_deg});
  else if(['move_l','gripper'].includes(command.cmd)){
   send(socket,{type:'command_status',status:'accepted',command:command.cmd,request_id:command.request_id});
   if(command.cmd==='move_l'){state.flange_position_m=command.position;state.flange_euler_rad=command.euler;}
   else state.gripper_width_m=command.position===1?.08:.03;
   send(socket,{type:'command_status',status:'complete',command:command.cmd,request_id:command.request_id,reached:true,robot_healthy:true});feedback();
  }else if(command.cmd==='software_stop')send(socket,{type:'command_status',status:'complete',command:'software_stop',request_id:command.request_id,stopped:true});
 });});
 const timer=setInterval(feedback,5);let selected=null,frame=0;
 const vision=http.createServer((request,response)=>{
  if(request.method==='POST'){
   let body='';request.on('data',data=>{body+=data;});request.on('end',()=>{selected=JSON.parse(body).stableId;response.setHeader('content-type','application/json');response.end(JSON.stringify({selectedStableId:selected}));});return;
  }
  const observation={frameId:frame,frame_id:frame,observedAtMs:Date.now(),ts:Date.now(),selectedStableId:selected,selected_stable_id:selected,
   targets:[{stable_id:2,selected:selected===2,track_state:'confirmed',depth_valid:true,camera_xyz_m:[.2,0,.2],base_xyz_m:[.4,0,.2]}],
   frame_projection:{frame_id:frame,status:'ready',robot_frame_policy_id:policyId,calibration_id:config.calibrationId,
    T_base_camera:[[1,0,0,.2],[0,1,0,0],[0,0,1,0],[0,0,0,1]]},pose:{width_m:.03},evidence_id:'sha256:'+'c'.repeat(64)};
  const payload=request.url.endsWith('/status')?{detection:observation,runtimeEvidence:{calibration_approved:false}}:observation;
  response.setHeader('content-type','application/json');response.end(JSON.stringify(payload));frame++;
 });await new Promise(r=>vision.listen(0,'127.0.0.1',r));
 const client=new WebRobotClient({url:'ws://127.0.0.1:1/ws',ownerToken:'offline-owner',deferConnect:true,jointLimits:config.jointLimits});
 const depth={status:()=>({active:false}),async close(){},async start(){throw Error('unexpected depth fallback: synthetic depth is valid');}};
 const visionClient=new VisionClient({baseUrl:'http://127.0.0.1:1'});
 const controller=new GraspCoordinator({config,robotClient:client,visionClient,depthCoordinator:depth,
  resolveTcp:()=>store.activeTcp(policyId),sleep:async()=>wait(2)});
 const statuses=[];controller.on('status',s=>statuses.push(s));
 const gateway=createWebGateway({env:{TCP_CALIBRATION_ENABLED:'1',TCP_CALIBRATION_FRAME_POLICY_FILE:policyFile,TCP_CALIBRATION_ARTIFACT_ROOT:store.root},
  host:'127.0.0.1',port:0,readyFile:path.join(temp,'ready'),robotWsUrl:`ws://127.0.0.1:${robot.address().port}/ws`,
  visionHttpUrl:`http://127.0.0.1:${vision.address().port}`,graspOwnerToken:'offline-owner',graspController:controller,
  coordinator:{on(){},status:()=>({active:false}),async close(){}},visionProxy:{attach(){},close(){}},voiceProxy:{attach(){},close(){}}});
 t.after(async()=>{clearInterval(timer);await gateway.close();for(const s of robot.clients)s.terminate();await new Promise(r=>robot.close(r));await new Promise(r=>vision.close(r));fs.rmSync(temp,{recursive:true,force:true});});
 const address=await gateway.start(),url=`http://127.0.0.1:${address.port}`;client.url=`ws://127.0.0.1:${address.port}/ws`;visionClient.baseUrl=url;
 const json=async(route,body)=>{const response=await fetch(url+route,body?{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)}:{});return {status:response.status,body:await response.json()};};
 assert.equal((await json('/api/vision/select',{stableId:2})).status,200);
 assert.equal((await json('/api/grasp/start',{stableId:2,requestId:'single-click'})).status,202);
 await until(()=>!controller.status().active);
 const final=(await json('/api/grasp/status')).body;
 assert.equal(final.phase,'complete',final.reason);assert.equal(final.tcp.id,saved.candidateId);assert.equal(final.result.physicalGraspVerified,false);
 assert.deepEqual(final.result.actualSdkM,[.48334,-.02,.24]);assert.deepEqual(final.result.actualGripM,[.4,0,.25]);
 assert.deepEqual(received.filter(m=>m.cmd==='gripper').map(m=>m.position),[1,0]);
 assert.equal(received.some(m=>['connect','disconnect','fixed_tcp_demo','teach_start'].includes(m.cmd)),false);
 assert.ok(['depth_acquiring','path_checking','preapproach','target_refresh','approach','closing','lifting','complete'].every(phase=>statuses.some(s=>s.phase===phase)));
 // The real calibration client also has to handshake through this same web port.
 await wait(1100);const calibration=await json('/api/tcp-calibration/sessions/current');
 assert.equal(calibration.status,200);assert.equal(calibration.body.robot.locked,false,calibration.body.robot.reason);
 assert.equal(calibration.body.robot.teachSupported,false);
 assert.deepEqual(calibration.body.robot.TBaseFlange.slice(0,3).map(row=>row[3]),[.31,-.02,.24]);
});
