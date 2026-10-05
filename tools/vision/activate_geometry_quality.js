'use strict';
// Restart only the validated Vision process. Never send a robot command.
const fs=require('node:fs'), path=require('node:path'), {spawn}=require('node:child_process');
const root='/home/nieqingcao/ThirdHand/deployments/grasp-prototype-1894746-20261004';
const pid=Number(process.argv[2]);
const expected=path.join(root,'tools/vision/vision_server_with_state.js');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const get=async p=>{let r=await fetch(`http://127.0.0.1:${p}/health`);if(!r.ok)throw Error('health_http');return r.json();};
(async()=>{
  if(!Number.isSafeInteger(pid)||pid<=1)throw Error('invalid_pid');
  const args=fs.readFileSync(`/proc/${pid}/cmdline`,'utf8').split('\0').filter(Boolean);
  if(args.length!==2||args[1]!==expected)throw Error('unexpected_process');
  const robot=await get(3000),vision=await get(3100);
  if(!robot.robot?.connected||!robot.robot?.stateReady||robot.robot?.moving!==false||vision.robotControlEnabled!==false||vision.detection?.motion_epoch!==0)throw Error('unsafe_restart_state');
  const prior=Object.fromEntries(fs.readFileSync(`/proc/${pid}/environ`,'utf8').split('\0').filter(Boolean).map(v=>{let i=v.indexOf('=');return[v.slice(0,i),v.slice(i+1)];}));
  const output=path.join(root,'artifacts/diagnostics',`quality-${Date.now()}`);fs.mkdirSync(output);
  fs.writeFileSync(path.join(output,'before.json'),JSON.stringify({robot,vision},null,2));
  const launch=env=>{let fd=fs.openSync(path.join(output,'vision.log'),'a');let child=spawn(args[0],[expected],{cwd:root,env,detached:true,stdio:['ignore',fd,fd]});child.unref();fs.closeSync(fd);return child;};
  process.kill(pid,'SIGTERM');
  for(let i=0;i<100;i++){try{process.kill(pid,0);}catch{break;}await sleep(100);}
  try{process.kill(pid,0);throw Error('old_vision_still_alive');}catch(e){if(e.code!=='ESRCH')throw e;}
  const child=launch({...prior,VISION_BRIDGE_SCRIPT:path.join(root,'tools/vision/camera_bridge_with_quality.py')});
  let ready;
  for(let i=0;i<120;i++){await sleep(250);try{let s=await get(3100);if(s.camera?.status==='ready'&&s.inference?.status==='ready'){ready=s;break;}}catch{}}
  if(!ready){try{process.kill(child.pid,'SIGTERM');}catch{}await sleep(1500);const rollback=launch(prior);console.log(JSON.stringify({status:'rolled_back',pid:rollback.pid,output}));process.exitCode=1;return;}
  if(ready.robotControlEnabled!==false||ready.runtimeEvidence?.calibration_approved!==false)throw Error('unexpected_approval');
  fs.writeFileSync(path.join(output,'after.json'),JSON.stringify(ready,null,2));
  console.log(JSON.stringify({status:'ready',pid:child.pid,output,robotControlEnabled:ready.robotControlEnabled,calibration_approved:ready.runtimeEvidence?.calibration_approved}));
})().catch(e=>{console.error(e.message);process.exitCode=1;});
