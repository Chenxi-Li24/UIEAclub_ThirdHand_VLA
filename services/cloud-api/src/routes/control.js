'use strict';
const {json,requireFields}=require('../http');
const {authorize}=require('../../../../platform/identity/src/policy');
const {identityError}=require('../../../../platform/identity/src/errors');
const {UUID}=require('../../../device-relay/src/protocol');
const routes=new Map([
  ['/api/v1/control/lease',{method:'requestLease',fields:['deviceId','clientInstanceId','connectionId']}],
  ['/api/v1/control/command',{method:'dispatchRealCommand',fields:['deviceId','clientInstanceId','connectionId','leaseId','commandId','opcode','parameters']}],
  ['/api/v1/control/stop',{method:'stop',fields:['deviceId','clientInstanceId','connectionId']}],
  ['/api/v1/control/takeover-request',{method:'requestTakeover',fields:['deviceId','clientInstanceId','connectionId','targetEpoch']}],
  ['/api/v1/control/takeover-confirm',{method:'confirmTakeover',fields:['requestId','clientInstanceId','connectionId','nonce']}]
]);
async function controlRoute({path,request,response,body,principal,controlService,pool}){
  if(path==='/api/v1/devices'&&request.method==='GET'){
    if(!authorize(principal,'telemetry.read').ok)throw identityError('FORBIDDEN');
    return json(response,200,{devices:controlService?await controlService.listDevices(principal):(await pool.query("SELECT id,name,coalesce(capabilities->>'camera'='true',false) AS camera,coalesce(capabilities->>'remoteControlEnabled'='true',false) AS controllable FROM ops.devices WHERE enabled ORDER BY name,id")).rows});
  }
  const telemetry=/^\/api\/v1\/devices\/([0-9a-f-]{36})\/telemetry$/i.exec(path);
  if(telemetry&&request.method==='GET'){
    if(!authorize(principal,'telemetry.read').ok)throw identityError('FORBIDDEN');
    if(!UUID.test(telemetry[1]))throw identityError('INVALID_INPUT');
    const device=(await pool.query('SELECT id,name FROM ops.devices WHERE id=$1 AND enabled',[telemetry[1]])).rows[0];
    if(!device)throw identityError('NOT_FOUND');
    const sample=(await pool.query(`SELECT sample_seq::text,captured_at,received_at,joint_position_rad,tcp_position_m,tcp_orientation_xyzw,
      sdk_connected,moving,fault_code,field_availability,state_age_ms,clock_quality,quality_flags,extra->>'sourceMode' AS source_mode
      FROM telemetry.robot_samples WHERE device_id=$1 ORDER BY captured_at DESC,sample_seq DESC LIMIT 1`,[device.id])).rows[0]||null;
    return json(response,200,{device,sample,serverTime:new Date().toISOString(),purpose:'display-only'});
  }
  if(path==='/api/v1/control/status'&&request.method==='GET'&&controlService){
    const deviceId=new URL(request.url,'http://localhost').searchParams.get('deviceId');if(!UUID.test(deviceId))throw identityError('INVALID_INPUT');
    return json(response,200,await controlService.status(principal,deviceId));
  }
  const route=routes.get(path);if(!route||!controlService)return false;
  if(!authorize(principal,route.method==='stop'?'control.stop':'control.request').ok)throw identityError('FORBIDDEN');
  if(request.method!=='POST')return json(response,405,{error:'METHOD_NOT_ALLOWED'});
  requireFields(body,route.fields);
  for(const key of route.fields)if(key.endsWith('Id')&&!UUID.test(body[key]))throw identityError('INVALID_INPUT');
  return json(response,200,await controlService[route.method](principal,body));
}
module.exports={controlRoute};
