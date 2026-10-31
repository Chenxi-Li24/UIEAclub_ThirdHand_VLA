'use strict';
const {createHash}=require('node:crypto');
const {transaction}=require('./pool');
const {UUID,decodeBase64url}=require('../../../services/device-relay/src/protocol');
const fail=code=>Object.assign(Error(code),{code});
const plain=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
function closed(value,keys){return plain(value)&&Object.keys(value).every(key=>keys.includes(key));}
function safeJson(value,depth=0){
  if(depth>8)throw fail('BATCH_SCHEMA');
  if(value===null||typeof value==='boolean')return;
  if(typeof value==='number'){if(!Number.isFinite(value))throw fail('BATCH_SCHEMA');return;}
  if(typeof value==='string'){if(value.length>2048)throw fail('BATCH_SCHEMA');return;}
  if(Array.isArray(value)){if(value.length>256)throw fail('BATCH_SCHEMA');for(const item of value)safeJson(item,depth+1);return;}
  if(!plain(value)||Object.keys(value).length>80)throw fail('BATCH_SCHEMA');
  for(const [key,item]of Object.entries(value)){if(!/^[A-Za-z0-9_.-]{1,80}$/.test(key)||['__proto__','prototype','constructor'].includes(key)||/password|token|secret|authorization|cookie|private.?key|totp|recovery.?code/i.test(key))throw fail('BATCH_SCHEMA');safeJson(item,depth+1);}
}
function timestamp(value){return typeof value==='string'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$/.test(value)&&Number.isFinite(Date.parse(value));}
function vector(value,size,required=false){return value===undefined||value===null?!required:Array.isArray(value)&&value.length===size&&value.every(Number.isFinite);}
const SAMPLE_KEYS=['sequence','capturedAt','monotonicNs','clockQuality','runId','commandId','jointPositionRad','jointVelocityRadS','jointCurrentA','jointTorqueNm','jointTemperatureC','fieldAvailability','tcpPositionM','tcpOrientationXyzw','tcpFrameId','toolVersion','calibrationVersion','gripper','sdkConnected','moving','faultCode','stateAgeMs','qualityFlags','extra'];
function normalizeSample(row,body,receivedAt){
  if(!closed(row,SAMPLE_KEYS))throw fail('BATCH_SCHEMA');
  for(const key of ['extra','fieldAvailability','gripper'])if(row[key]!==undefined){if(row[key]!==null&&!plain(row[key]))throw fail('BATCH_SCHEMA');safeJson(row[key]);}
  let reason=null;
  if(!timestamp(row.capturedAt))reason='INVALID_CAPTURE_TIME';
  else if(typeof row.monotonicNs!=='string'||!/^(0|[1-9][0-9]{0,18})$/.test(row.monotonicNs)||BigInt(row.monotonicNs)>9223372036854775807n)reason='INVALID_MONOTONIC_TIME';
  else if(!['synchronized','estimated','unreliable'].includes(row.clockQuality))reason='INVALID_CLOCK_QUALITY';
  else if(!vector(row.jointPositionRad,6,true))reason='INVALID_JOINT_POSITION';
  else if(!['jointVelocityRadS','jointCurrentA','jointTorqueNm','jointTemperatureC'].every(key=>vector(row[key],6))||!vector(row.tcpPositionM,3)||!vector(row.tcpOrientationXyzw,4))reason='INVALID_VECTOR';
  else if(typeof row.sdkConnected!=='boolean'||typeof row.moving!=='boolean')reason='INVALID_STATE';
  else if(row.stateAgeMs!==undefined&&row.stateAgeMs!==null&&(!Number.isSafeInteger(row.stateAgeMs)||row.stateAgeMs<0||row.stateAgeMs>2147483647))reason='INVALID_STATE_AGE';
  for(const key of ['runId','commandId'])if(row[key]!==undefined&&row[key]!==null&&!UUID.test(row[key]))reason='INVALID_ASSOCIATION';
  for(const key of ['tcpFrameId','toolVersion','calibrationVersion','faultCode'])if(row[key]!==undefined&&row[key]!==null&&(typeof row[key]!=='string'||!/^[A-Za-z0-9_.:@/+ -]{1,160}$/.test(row[key])))reason='INVALID_VERSION_OR_CODE';
  if(row.qualityFlags!==undefined&&(!Array.isArray(row.qualityFlags)||row.qualityFlags.length>32||!row.qualityFlags.every(item=>typeof item==='string'&&/^[A-Za-z0-9_.-]{1,64}$/.test(item))))reason='INVALID_QUALITY_FLAGS';
  if(reason)return {invalid:{sequence:row.sequence,reason,row}};
  return {value:{device_id:body.deviceId,boot_id:body.bootId,sample_seq:row.sequence,captured_at:row.capturedAt,received_at:receivedAt,
    monotonic_ns:row.monotonicNs,clock_quality:row.clockQuality,schema_version:1,run_id:row.runId??null,command_id:row.commandId??null,
    joint_position_rad:row.jointPositionRad,joint_velocity_rad_s:row.jointVelocityRadS??null,joint_current_a:row.jointCurrentA??null,joint_torque_nm:row.jointTorqueNm??null,joint_temperature_c:row.jointTemperatureC??null,
    field_availability:row.fieldAvailability||{},tcp_position_m:row.tcpPositionM??null,tcp_orientation_xyzw:row.tcpOrientationXyzw??null,tcp_frame_id:row.tcpFrameId??null,
    tool_version:row.toolVersion??null,calibration_version:row.calibrationVersion??null,gripper:row.gripper??null,sdk_connected:row.sdkConnected,moving:row.moving,
    fault_code:row.faultCode??null,state_age_ms:row.stateAgeMs??null,quality_flags:row.qualityFlags||[],extra:row.extra||{}}};
}
function parseBatch(context,envelope){
  if(!closed(envelope,['batchId','digest','payloadBase64url'])||!UUID.test(envelope.batchId)||typeof envelope.digest!=='string'||!/^[a-f0-9]{64}$/.test(envelope.digest))throw fail('BATCH_SCHEMA');
  let raw;try{raw=decodeBase64url(envelope.payloadBase64url,349526);}catch{throw fail('BATCH_SCHEMA');}
  if(raw.length>262144)throw fail('BATCH_TOO_LARGE');
  if(createHash('sha256').update(raw).digest('hex')!==envelope.digest)throw fail('BATCH_DIGEST_MISMATCH');
  let body;try{body=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));}catch{throw fail('BATCH_SCHEMA');}
  if(!closed(body,['schema','agentVersion','batchId','deviceId','bootId','streamKind','batchSequence','firstSequence','lastSequence','rows'])||body.schema!==1||body.batchId!==envelope.batchId||body.deviceId!==context?.deviceId||!UUID.test(body.deviceId)||!UUID.test(body.bootId)||!['robot_samples','device_events','command_events'].includes(body.streamKind)||typeof body.agentVersion!=='string'||!/^\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$/.test(body.agentVersion)||body.agentVersion.length>80||!Array.isArray(body.rows)||body.rows.length<1||body.rows.length>1000)throw fail('BATCH_SCHEMA');
  for(const key of ['batchSequence','firstSequence','lastSequence'])if(!Number.isSafeInteger(body[key])||body[key]<0)throw fail('BATCH_SCHEMA');
  if(body.lastSequence-body.firstSequence+1!==body.rows.length||!body.rows.every((row,index)=>plain(row)&&row.sequence===body.firstSequence+index))throw fail('BATCH_SEQUENCE_MISMATCH');
  return {raw,body};
}
function createIngestRepository(pool,{clock={now:()=>new Date()}}={}){
  return {async ingestBatch(context,envelope){
    const {raw,body}=parseBatch(context,envelope),ack={batchId:envelope.batchId,digest:envelope.digest,persisted:true};
    const valid=[],invalid=[];const receivedAt=clock.now().toISOString();
    if(body.streamKind==='robot_samples')for(const row of body.rows){const normalized=normalizeSample(row,body,receivedAt);if(normalized.invalid)invalid.push(normalized.invalid);else valid.push(normalized.value);}
    else for(const row of body.rows){
      const keys=['sequence','eventId','capturedAt','eventCode','level','details',...(body.streamKind==='command_events'?['commandId','state']:[])];
      if(!closed(row,keys)||!UUID.test(row.eventId)||!timestamp(row.capturedAt)||typeof row.eventCode!=='string'||!/^[a-zA-Z0-9_.:-]{1,100}$/.test(row.eventCode)||!plain(row.details))throw fail('BATCH_SCHEMA');safeJson(row.details);
      if(body.streamKind==='device_events'&&!['info','warning','error','critical'].includes(row.level))throw fail('BATCH_SCHEMA');
      if(body.streamKind==='command_events'&&(!UUID.test(row.commandId)||row.state!==undefined&&!['accepted','started','completed','stopped','rejected','failed','unknown'].includes(row.state)))throw fail('BATCH_SCHEMA');
    }
    try{return await transaction(pool,async client=>{
      const authorized=await client.query(`SELECT 1 FROM ops.devices d JOIN ops.device_credentials c ON c.device_id=d.id WHERE d.id=$1 AND d.enabled AND c.id=$2 AND c.revoked_at IS NULL AND c.not_before<=$3 AND c.expires_at>$3 FOR SHARE OF d`,[context.deviceId,context.certificateId,clock.now()]);if(!authorized.rowCount)throw fail('DEVICE_AUTH_REQUIRED');
      await client.query('INSERT INTO ops.device_boots(boot_id,device_id,agent_version) VALUES($1,$2,$3) ON CONFLICT(boot_id) DO NOTHING',[body.bootId,body.deviceId,body.agentVersion]);
      const boot=(await client.query('SELECT device_id FROM ops.device_boots WHERE boot_id=$1',[body.bootId])).rows[0];if(boot.device_id!==context.deviceId)throw fail('BATCH_CONFLICT');
      const inserted=await client.query(`INSERT INTO telemetry.ingest_batches(id,device_id,boot_id,stream_kind,batch_seq,first_seq,last_seq,digest,row_count,completed_at)
        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT(id) DO NOTHING`,[body.batchId,body.deviceId,body.bootId,body.streamKind,body.batchSequence,body.firstSequence,body.lastSequence,envelope.digest,body.rows.length,clock.now()]);
      if(!inserted.rowCount){const existing=(await client.query('SELECT device_id,digest FROM telemetry.ingest_batches WHERE id=$1',[body.batchId])).rows[0];if(existing.device_id!==context.deviceId||existing.digest!==envelope.digest)throw fail('BATCH_CONFLICT');return ack;}
      await client.query('INSERT INTO telemetry.ingest_batch_payloads(batch_id,payload_bytes,certificate_id) VALUES($1,$2,$3)',[body.batchId,raw,context.certificateId]);
      const runIds=[...new Set(valid.map(row=>row.run_id).filter(Boolean))],commandIds=[...new Set(valid.map(row=>row.command_id).filter(Boolean))];
      if(runIds.length&&(await client.query('SELECT id FROM ops.runs WHERE device_id=$1 AND id=ANY($2::uuid[])',[body.deviceId,runIds])).rowCount!==runIds.length)throw fail('BATCH_ASSOCIATION_MISMATCH');
      if(commandIds.length&&(await client.query('SELECT command_id FROM ops.commands WHERE device_id=$1 AND command_id=ANY($2::uuid[])',[body.deviceId,commandIds])).rowCount!==commandIds.length)throw fail('BATCH_ASSOCIATION_MISMATCH');
      if(valid.length)await client.query('INSERT INTO telemetry.robot_samples SELECT * FROM jsonb_populate_recordset(NULL::telemetry.robot_samples,$1::jsonb)',[JSON.stringify(valid)]);
      for(const item of invalid)await client.query('INSERT INTO telemetry.invalid_samples(device_id,boot_id,batch_id,sample_seq,reason_code,sanitized_fields,received_at,stream_kind) VALUES($1,$2,$3,$4,$5,$6,$7,$8)',[body.deviceId,body.bootId,body.batchId,item.sequence,item.reason,item.row,clock.now(),body.streamKind]);
      if(body.streamKind==='device_events')for(const row of body.rows)await client.query('INSERT INTO ops.device_events(device_id,boot_id,edge_event_id,event_code,level,captured_at,received_at,details) VALUES($1,$2,$3,$4,$5,$6,$7,$8)',[body.deviceId,body.bootId,row.eventId,row.eventCode,row.level,row.capturedAt,clock.now(),row.details]);
      if(body.streamKind==='command_events')for(const row of body.rows){
        const command=(await client.query('SELECT run_id FROM ops.commands WHERE command_id=$1 AND device_id=$2',[row.commandId,body.deviceId])).rows[0];if(!command)throw fail('BATCH_ASSOCIATION_MISMATCH');
        await client.query('INSERT INTO ops.command_events(command_id,edge_event_id,event_code,captured_at,received_at,details) VALUES($1,$2,$3,$4,$5,$6)',[row.commandId,row.eventId,row.eventCode,row.capturedAt,clock.now(),{...row.details,...(row.state?{state:row.state}:{})}]);
        if(row.state){const changed=await client.query("UPDATE ops.commands SET state=$2,result=$3 WHERE command_id=$1 AND state IN ('unknown','accepted','started')",[row.commandId,row.state,{state:row.state,source:'device_event'}]);if(changed.rowCount){const status={accepted:'running',started:'running',completed:'completed',stopped:'stopped',rejected:'rejected',failed:'failed',unknown:'unknown'}[row.state];await client.query('UPDATE ops.runs SET status=$2,ended_at=$3 WHERE id=$1',[command.run_id,status,['accepted','started'].includes(row.state)?null:row.capturedAt]);}}
      }
      return ack;
    });}catch(error){if(['23505','23P01'].includes(error.code))throw fail('BATCH_CONFLICT');throw error;}
  }};
}
module.exports={createIngestRepository,parseBatch,normalizeSample};
