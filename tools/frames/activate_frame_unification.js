'use strict';
// Only restart the independent Vision and read-only state relay. No robot writes.
const fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process');
const {loadPolicy}=require('./robot_frame_normalization');
const root=path.resolve(__dirname,'../..');
const artifact=path.join(root,'artifacts/diagnostics/frame-unification-1791215001479');
const policyPath=path.join(root,'skills/manipulation/bottlegrasp/configs/calibration/sdk-tool-frame-policy-20261005.json');
const calibration=path.join(root,'skills/manipulation/bottlegrasp/configs/calibration/handeye-flange-normalized-20261005.json');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
const get=async p=>{const r=await fetch(`http://127.0.0.1:${p}/health`);if(!r.ok)throw Error('health_http');return r.json();};
function processInfo(pid,expected){
  if(!Number.isSafeInteger(pid)||pid<=1)throw Error('invalid_pid');
  const args=fs.readFileSync(`/proc/${pid}/cmdline`,'utf8').split('\0').filter(Boolean);
  if(args.length!==2||args[1]!==path.join(root,expected))throw Error('unexpected_process');
  const env=Object.fromEntries(fs.readFileSync(`/proc/${pid}/environ`,'utf8').split('\0').filter(Boolean).map(v=>{const i=v.indexOf('=');return[v.slice(0,i),v.slice(i+1)];}));
  return {pid,args,env};
}
async function stop(pid){
  try{process.kill(pid,'SIGTERM');}catch(e){if(e.code==='ESRCH')return;throw e;}
  for(let i=0;i<80;i++){try{process.kill(pid,0);}catch(e){if(e.code==='ESRCH')return;throw e;}await pause(100);}
  throw Error('process_did_not_stop');
}
function launch(info,script,env,label){
  const fd=fs.openSync(path.join(artifact,label+'.log'),'a');
  const child=spawn(info.args[0],[script],{cwd:root,env,detached:true,stdio:['ignore',fd,fd]});
  child.unref();fs.closeSync(fd);return child;
}
(async()=>{
  const policy=loadPolicy(policyPath),cal=JSON.parse(fs.readFileSync(calibration));
  if(cal.frame_normalization?.policy_id!==policy.id||cal.approved_for_bottle_grasp!==false||cal.physical_validation?.status!=='pending')throw Error('calibration_policy_mismatch');
  const vision=processInfo(Number(process.argv[2]),'tools/vision/vision_server_with_state.js');
  const relay=processInfo(Number(process.argv[3]),'tools/vision/robot_state_relay.js');
  const robot=await get(3000),prior=await get(3100);
  if(!robot.robot?.connected||!robot.robot?.stateReady||robot.robot?.moving!==false||prior.robotControlEnabled!==false||prior.detection?.motion_epoch!==0)throw Error('unsafe_restart_state');
  const rollbackRelay=path.join(artifact,'rollback/tools/vision/robot_state_relay.js');
  if(!fs.existsSync(rollbackRelay))throw Error('rollback_missing');
  fs.writeFileSync(path.join(artifact,'before.json'),JSON.stringify({robot,vision:prior},null,2));
  await stop(vision.pid);await stop(relay.pid);
  let newVision,newRelay;
  try{
    newRelay=launch(relay,relay.args[1],{...relay.env,THIRDHAND_ROBOT_FRAME_POLICY:policyPath},'relay');
    newVision=launch(vision,vision.args[1],{...vision.env,VISION_BRIDGE_SCRIPT:path.join(root,'tools/vision/camera_bridge_with_frames.py'),THIRDHAND_VA_HANDEYE:calibration},'vision');
    let ready;
    for(let i=0;i<120;i++){
      await pause(250);
      try{const s=await get(3100);
        if(s.robotControlEnabled!==false||s.runtimeEvidence?.calibration_approved===true)throw Error('unexpected_approval');
        if(s.camera?.status==='ready'&&s.inference?.status==='ready'&&s.detection?.targets?.some(t=>t.base_xyz_m&&t.base_pose_status==='ready')){ready=s;break;}
      }catch(e){if(e.message==='unexpected_approval')throw e;}
    }
    if(!ready)throw Error('normalized_projection_startup_timeout');
    fs.writeFileSync(path.join(artifact,'after.json'),JSON.stringify(ready,null,2));
    console.log(JSON.stringify({status:'ready',vision_pid:newVision.pid,relay_pid:newRelay.pid,policy_id:policy.id,calibration_id:ready.runtimeEvidence.calibration_id,robotControlEnabled:ready.robotControlEnabled}));
  }catch(error){
    if(newVision)await stop(newVision.pid);if(newRelay)await stop(newRelay.pid);
    const oldRelay=launch(relay,rollbackRelay,relay.env,'relay-rollback');
    const oldVision=launch(vision,vision.args[1],vision.env,'vision-rollback');
    console.log(JSON.stringify({status:'rolled_back',reason:error.message,vision_pid:oldVision.pid,relay_pid:oldRelay.pid}));process.exitCode=1;
  }
})().catch(e=>{console.error(e.message);process.exitCode=1;});
