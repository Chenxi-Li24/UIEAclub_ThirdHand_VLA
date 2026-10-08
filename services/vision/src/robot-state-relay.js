'use strict';
const { WebSocket } = require('ws');
const {loadPolicy,normalizeRobotState}=require('./frames/robot_frame_normalization');
const clock = () => Number(process.hrtime.bigint());
const MAX_AGE_NS = 250000000;
const finiteVector = (value,length) => Array.isArray(value) && value.length===length &&
  Array.from(value).every(Number.isFinite);

function mapState(message,now=clock(),policy=null) {
  try{message=normalizeRobotState(message,policy);}catch{return null;}
  if (message?.type!=='robot_state' || message.connected!==true || message.healthy!==true ||
      message.pose_frame!=='robot_flange' || typeof message.moving!=='boolean' ||
      !Number.isSafeInteger(message.state_sequence) || message.state_sequence<0 ||
      !Number.isSafeInteger(message.producer_monotonic_ns) || message.producer_monotonic_ns<0 ||
      message.producer_monotonic_ns>now || now-message.producer_monotonic_ns>MAX_AGE_NS ||
      !finiteVector(message.flange_position_m,3) || !finiteVector(message.flange_euler_rad,3) ||
      !finiteVector(message.joints_deg,6) || !finiteVector(message.velocities_deg_s,6)) return null;
  return {type:'arm_state',pose_frame:'robot_flange',connected:true,healthy:true,
    stationary:message.moving===false && message.velocities_deg_s.every(v=>Math.abs(v)<=2),
    flange_position_m:[...message.flange_position_m],flange_euler_rad:[...message.flange_euler_rad],
    frame_normalization:{...message.frame_normalization},
    joints_deg:[...message.joints_deg],observed_monotonic_ns:message.producer_monotonic_ns};
}

function startRelay({robotUrl='ws://127.0.0.1:3000/ws',visionUrl='ws://127.0.0.1:3100/ws',policy=loadPolicy(process.env.THIRDHAND_ROBOT_FRAME_POLICY)}={}) {
  let stopped=false,robot=null,vision=null,last=null,sequence=-1,producer=-1,invalidated=true;
  const timers=new Set();
  const stats={forwarded:0,rejected:0,invalidations:0};
  const send=message=>{
    if (vision?.readyState!==WebSocket.OPEN || vision.bufferedAmount>65536) return false;
    try {vision.send(JSON.stringify(message));return true;} catch {return false;}
  };
  const invalidate=()=>{
    if (last && !invalidated) {
      send({...last,stationary:false});invalidated=true;stats.invalidations++;
    }
  };
  const retry=callback=>{
    if(stopped)return;
    const timer=setTimeout(()=>{timers.delete(timer);if(!stopped)callback();},1000);
    timers.add(timer);
  };
  function connectVision() {
    vision=new WebSocket(visionUrl,{handshakeTimeout:5000});
    vision.on('open',()=>{if(!robot && !stopped)connectRobot();});
    vision.on('error',()=>{});
    vision.on('close',()=>{invalidate();retry(connectVision);});
  }
  function connectRobot() {
    sequence=-1;producer=-1;
    robot=new WebSocket(robotUrl,{handshakeTimeout:5000});
    // This socket only subscribes. It never sends a robot command.
    robot.on('message',raw=>{
      let message;
      try {message=JSON.parse(raw);} catch {stats.rejected++;invalidate();return;}
      if(!message || typeof message!=='object' || Array.isArray(message)) {
        stats.rejected++;invalidate();return;
      }
      if(message.type!=='robot_state')return;
      const mapped=mapState(message,clock(),policy);
      if(!mapped || message.state_sequence<=sequence || message.producer_monotonic_ns<=producer) {
        stats.rejected++;invalidate();return;
      }
      sequence=message.state_sequence;producer=message.producer_monotonic_ns;
      if(send(mapped)){last=mapped;invalidated=!mapped.stationary;stats.forwarded++;}
    });
    robot.on('error',()=>invalidate());
    robot.on('close',()=>{invalidate();retry(connectRobot);});
  }
  connectVision();
  const staleTimer=setInterval(()=>{
    if(last && clock()-last.observed_monotonic_ns>MAX_AGE_NS)invalidate();
  },50);
  return {stats,close(){
    if(stopped)return;stopped=true;invalidate();clearInterval(staleTimer);
    for(const timer of timers)clearTimeout(timer);
    robot?.terminate();vision?.close();
  }};
}

if(require.main===module) {
  if(process.argv.length!==2)throw new Error('relay_accepts_no_options');
  const relay=startRelay();
  console.log(JSON.stringify({service:'robot-state-relay',readOnly:true,pid:process.pid}));
  const heartbeat=setInterval(()=>console.log(JSON.stringify(relay.stats)),10000);
  const stop=()=>{clearInterval(heartbeat);relay.close();};
  process.on('SIGTERM',stop);process.on('SIGINT',stop);
}
module.exports={mapState,startRelay};
