'use strict';
// Explicit C2g operator test. Blocks only the staging API UID's private SFU
// management connection. An independent systemd timer removes the exact rule.
// No credentials, room names, participant identities or raw media are logged.
const fs=require('node:fs'),cp=require('node:child_process'),assert=require('node:assert/strict');
const base='/var/backups/thirdhand/access-C2g-camera-20261030T182905Z';
const {RoomServiceClient}=require('/opt/thirdhand-stage/current/node_modules/livekit-server-sdk');
const cfg=JSON.parse(fs.readFileSync(base+'/media-secrets.private.json'));
const api=new RoomServiceClient('http://127.0.0.1:7880',cfg.apiKey,cfg.apiSecret,{requestTimeout:1});
const unit='thirdhand-c2g-media-removal-fault-20261031',comment='ThirdHand-C2g-removal-fault';
const run=(command,args)=>cp.execFileSync(command,args,{encoding:'utf8',timeout:4000});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function participants(){
  const rooms=(await api.listRooms()).filter(r=>r.name.startsWith('d_006e0cac-cf10-427e-a84c-42c260b3ac4e_'));
  return (await Promise.all(rooms.map(r=>api.listParticipants(r.name)))).flat();
}
async function main(){
  assert.equal(process.getuid(),0);process.umask(0o077);
  const initial=await participants(),oldViewers=new Set(initial.filter(p=>p.identity.startsWith('v_')).map(p=>p.identity));
  assert.equal(oldViewers.size,2,'TWO_CONNECTED_VIEWERS_REQUIRED');
  assert(initial.some(p=>p.identity.startsWith('p_')&&p.tracks.some(t=>t.type===1)),'LIVE_PUBLISHER_REQUIRED');
  const uid=run('/usr/bin/id',['-u','thirdhand-stage']).trim();assert(/^\d+$/.test(uid));
  assert(!run('/usr/sbin/iptables',['-S','OUTPUT']).includes(comment),'EXISTING_TEST_RULE_REQUIRES_REVIEW');
  const rule=['OUTPUT','-p','tcp','-d','127.0.0.1/32','--dport','7880','-m','owner','--uid-owner',uid,'-m','comment','--comment',comment,'-j','REJECT','--reject-with','tcp-reset'];
  const report={startedAt:new Date().toISOString(),twoConnectedViewers:true,managementOnly:true,sdkActions:0};
  let inserted=false;
  const save=()=>fs.writeFileSync(base+'/camera-removal-fault.json',JSON.stringify(report,null,2),{mode:0o600});
  try{
    run('/usr/bin/systemd-run',['--quiet','--unit='+unit,'--on-active=35s','--timer-property=AccuracySec=100ms','--timer-property=RandomizedDelaySec=0','/usr/sbin/iptables','-D',...rule]);
    run('/usr/sbin/iptables',['-I',...rule]);inserted=true;report.faultReadyAt=new Date().toISOString();save();
    console.log(JSON.stringify({event:'camera.fault.ready',at:report.faultReadyAt,autoRestoreSeconds:35}));
    const start=performance.now();let rejectedAt=null,stoppedAt=null,removedAt=null;
    while(performance.now()-start<55000){
      const rules=run('/usr/sbin/iptables',['-L','OUTPUT','-v','-x','-n']);
      const match=rules.split('\n').find(line=>line.includes(comment));
      if(match&&Number(match.trim().split(/\s+/)[0])>0&&rejectedAt===null){rejectedAt=performance.now();report.firstRejectionObservedAt=new Date().toISOString();}
      if(!match&&!report.ruleRemovalObservedAt)report.ruleRemovalObservedAt=new Date().toISOString();
      const actual=await participants();
      if(rejectedAt!==null&&stoppedAt===null&&!actual.some(p=>p.identity.startsWith('p_')&&p.tracks.some(t=>t.type===1))){stoppedAt=performance.now();report.publisherTrackRemovedAt=new Date().toISOString();}
      if(rejectedAt!==null&&removedAt===null&&!actual.some(p=>oldViewers.has(p.identity))){removedAt=performance.now();report.previousViewersRemovedAt=new Date().toISOString();}
      if(!match&&removedAt!==null&&actual.some(p=>p.identity.startsWith('p_')&&p.tracks.some(t=>t.type===1))){report.recovered=true;break;}
      await sleep(100);
    }
    report.managementRejectionObserved=rejectedAt!==null;report.publisherTrackRemoved=stoppedAt!==null;
    report.trackRemovalAfterFirstRejectedPacketMs=rejectedAt!==null&&stoppedAt!==null?Math.round(stoppedAt-rejectedAt):null;
    report.previousViewersRemoved=removedAt!==null;
    report.decoderPrivacyDeadlineVerified=false;
    report.rejectionWithinTriggerWindow=!!report.firstRejectionObservedAt&&Date.parse(report.firstRejectionObservedAt)-Date.parse(report.faultReadyAt)<10000;
    assert(report.rejectionWithinTriggerWindow,'OPERATOR_TRIGGER_NOT_SYNCHRONIZED');
    assert(report.managementRejectionObserved&&report.publisherTrackRemoved&&report.previousViewersRemoved&&report.recovered,'FAULT_ACCEPTANCE_INCOMPLETE');
    report.success=true;
  }finally{
    if(inserted){try{run('/usr/sbin/iptables',['-D',...rule]);}catch{}}
    report.exactRuleAbsent=!run('/usr/sbin/iptables',['-S','OUTPUT']).includes(comment);
    report.finishedAt=new Date().toISOString();save();
    console.log(JSON.stringify(report));
  }
}
main().catch(error=>{console.error(JSON.stringify({success:false,type:error.name,code:error.code}));process.exitCode=1;});
