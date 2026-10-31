'use strict';
// Read-only, bounded two-viewer acceptance. Never emits media or credentials.
const fs=require('node:fs'),cp=require('node:child_process'),assert=require('node:assert/strict');
const {RoomServiceClient}=require('/opt/thirdhand-stage/current/node_modules/livekit-server-sdk');
const base='/var/backups/thirdhand/access-C2i-timing-20261031T033825Z';
const cfg=JSON.parse(fs.readFileSync('/var/backups/thirdhand/access-C2g-camera-20261030T182905Z/media-secrets.private.json'));
const api=new RoomServiceClient('http://127.0.0.1:7880',cfg.apiKey,cfg.apiSecret,{requestTimeout:1,failover:false});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const report={startedAt:new Date().toISOString(),durationSeconds:300,sdkActions:0,samples:[]};
const output=base+'/two-observer-stability-'+Date.now()+'.json';
function units(){
  return cp.execFileSync('/usr/bin/systemctl',['show','thirdhand-stage.service','thirdhand-stage-media.service','-p','MainPID','-p','NRestarts','-p','ActiveState'],{encoding:'utf8',timeout:2000}).trim();
}
async function sample(){
  const participants=[];
  for(const room of(await api.listRooms()).filter(r=>r.name.startsWith('d_006e0cac-cf10-427e-a84c-42c260b3ac4e_'))){
    participants.push(...await api.listParticipants(room.name));
  }
  const publisher=participants.filter(p=>p.identity.startsWith('p_'));
  return {at:new Date().toISOString(),viewers:participants.filter(p=>p.identity.startsWith('v_')).length,
    videoPublishers:publisher.filter(p=>p.tracks.some(t=>t.type===1&&t.width===640&&t.height===480&&!t.muted)).length,
    units:units(),apiMemoryBytes:Number(fs.readFileSync('/sys/fs/cgroup/system.slice/thirdhand-stage.service/memory.current')),
    sfuMemoryBytes:Number(fs.readFileSync('/sys/fs/cgroup/system.slice/thirdhand-stage-media.service/memory.current')),
    memoryAvailableKiB:Number(/^MemAvailable:\s+(\d+)/m.exec(fs.readFileSync('/proc/meminfo','utf8'))[1])};
}
async function main(){
  assert.equal(process.getuid(),0);process.umask(0o077);
  console.log(JSON.stringify({event:'camera.stability.started',output,durationSeconds:300}));
  const started=performance.now();
  do{
    try{report.samples.push(await sample());}catch(error){report.samples.push({at:new Date().toISOString(),errorType:error.name});}
    fs.writeFileSync(output,JSON.stringify(report,null,2),{mode:0o600});
    if(performance.now()-started>=300000)break;
    await sleep(Math.min(5000,300000-(performance.now()-started)));
  }while(true);
  report.elapsedSeconds=(performance.now()-started)/1000;
  report.success=report.samples.length>=60&&report.samples.every(s=>s.viewers===2&&s.videoPublishers===1&&s.units===report.samples[0].units);
  report.finishedAt=new Date().toISOString();fs.writeFileSync(output,JSON.stringify(report,null,2),{mode:0o600});
  console.log(JSON.stringify({success:report.success,output,elapsedSeconds:report.elapsedSeconds,samples:report.samples.length,
    badSamples:report.samples.filter(s=>s.viewers!==2||s.videoPublishers!==1||s.units!==report.samples[0].units).length}));
  if(!report.success)process.exitCode=1;
}
main().catch(error=>{console.error(JSON.stringify({errorType:error.name}));process.exitCode=1;});
