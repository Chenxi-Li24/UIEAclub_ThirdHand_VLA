'use strict';
const {randomUUID,createHash}=require('node:crypto');
const {transaction}=require('./pool');
const fail=code=>Object.assign(Error(code),{code});
const COLUMNS=`l.id,l.device_id AS "deviceId",l.user_id AS "userId",l.session_id AS "sessionId",l.client_instance_id AS "clientInstanceId",
 l.browser_connection_id AS "connectionId",l.device_connection_id AS "deviceConnectionId",l.certificate_id AS "certificateId",
 l.boot_id AS "bootId",l.executor_epoch AS "executorEpoch",l.lease_epoch::float8 AS "leaseEpoch",l.state,l.expires_at AS "expiresAt",l.renewal_sequence::float8 AS "renewalSequence"`;
const digest=value=>createHash('sha256').update(value).digest('hex');
async function assertPrincipal(client,principal,now){
  if(principal?.role!=='admin'||principal.mode!=='admin'||!principal.mfaVerifiedAt)throw fail('FORBIDDEN');
  const row=(await client.query(`SELECT u.display_name AS "displayName" FROM auth.sessions s JOIN auth.users u ON u.id=s.user_id
    WHERE s.id=$1 AND s.user_id=$2 AND s.mode='admin' AND s.revoked_at IS NULL AND s.role_version=u.role_version AND s.role_version=$3
    AND u.role='admin' AND u.status='active' AND s.mfa_verified_at IS NOT NULL AND s.mfa_verified_at<=$4
    AND s.idle_expires_at>$4 AND s.absolute_expires_at>$4 FOR SHARE OF s,u`,[principal.sessionId,principal.userId,principal.roleVersion,now])).rows[0];
  if(!row)throw fail('FORBIDDEN');return row;
}
function createLeasesRepository(pool,{clock={now:()=>new Date()}}={}){
  async function lockedDevice(client,deviceId){const device=(await client.query('SELECT id,enabled,control_epoch FROM ops.devices WHERE id=$1 FOR UPDATE',[deviceId])).rows[0];if(!device?.enabled)throw fail('DEVICE_UNAVAILABLE');return device;}
  async function reserve(client,principal,{context,clientInstanceId,connectionId},device){
    await assertPrincipal(client,principal,clock.now());
    device=device||await lockedDevice(client,context.deviceId);
    if((await client.query("SELECT id FROM ops.control_leases WHERE device_id=$1 AND state IN ('requested','active','revoking')",[context.deviceId])).rowCount)throw fail('LEASE_BUSY');
    const bound=await client.query(`SELECT 1 FROM ops.execution_instances e JOIN ops.device_credentials c ON c.device_id=e.device_id
      WHERE e.device_id=$1 AND e.boot_id=$2 AND e.executor_epoch=$3 AND e.ended_at IS NULL AND c.id=$4 AND c.control_enabled
      AND c.revoked_at IS NULL AND c.not_before<=$5 AND c.expires_at>$5`,[context.deviceId,context.bootId,context.executorEpoch,context.certificateId,clock.now()]);
    if(!bound.rowCount)throw fail('DEVICE_UNAVAILABLE');
    const epoch=BigInt(device.control_epoch)+1n;if(epoch>BigInt(Number.MAX_SAFE_INTEGER))throw fail('EPOCH_EXHAUSTED');
    await client.query('UPDATE ops.devices SET control_epoch=$2 WHERE id=$1',[context.deviceId,epoch.toString()]);
    return (await client.query(`INSERT INTO ops.control_leases AS l(device_id,user_id,session_id,client_instance_id,browser_connection_id,device_connection_id,certificate_id,boot_id,executor_epoch,lease_epoch,state,requested_at)
      VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'requested',$11) RETURNING ${COLUMNS}`,[context.deviceId,principal.userId,principal.sessionId,clientInstanceId,connectionId,context.connectionId,context.certificateId,context.bootId,context.executorEpoch,epoch.toString(),clock.now()])).rows[0];
  }
  const api={
    async listDevices(){return (await pool.query("SELECT id,name,coalesce(capabilities->>'camera'='true',false) AS camera,coalesce(capabilities->>'remoteControlEnabled'='true',false) AS controllable FROM ops.devices WHERE enabled ORDER BY name,id LIMIT 100")).rows;},
    validatePrincipal:principal=>assertPrincipal(pool,principal,clock.now()),
    reserve:(principal,input)=>transaction(pool,client=>reserve(client,principal,input)),
    async find(id){return (await pool.query(`SELECT ${COLUMNS} FROM ops.control_leases l WHERE l.id=$1`,[id])).rows[0]||null;},
    async current(deviceId){return (await pool.query(`SELECT ${COLUMNS} FROM ops.control_leases l WHERE l.device_id=$1 AND l.state IN ('requested','active','revoking')`,[deviceId])).rows[0]||null;},
    async confirm(principal,leaseId){return transaction(pool,async client=>{
      await assertPrincipal(client,principal,clock.now());
      const row=(await client.query(`UPDATE ops.control_leases AS l SET state='active',confirmed_at=$3,expires_at=$4
        WHERE l.id=$1 AND l.session_id=$2 AND l.state='requested' RETURNING ${COLUMNS}`,[leaseId,principal.sessionId,clock.now(),new Date(clock.now().getTime()+1000)])).rows[0];
      if(!row)throw fail('LEASE_CHANGED');return row;
    });},
    async markRevoking(leaseId,reason){await pool.query("UPDATE ops.control_leases SET state='revoking',release_reason=$2 WHERE id=$1 AND state IN ('requested','active')",[leaseId,reason]);},
    async completeStop(leaseId,reason){await pool.query("UPDATE ops.control_leases SET state='released',released_at=$3,release_reason=$2 WHERE id=$1 AND state IN ('requested','active','revoking')",[leaseId,reason,clock.now()]);},
    async renew(principal,leaseId){return transaction(pool,async client=>{
      await assertPrincipal(client,principal,clock.now());
      const result=(await client.query(`UPDATE ops.control_leases AS l SET renewal_sequence=renewal_sequence+1,expires_at=$3
        WHERE id=$1 AND session_id=$2 AND state='active' AND expires_at>$4 RETURNING ${COLUMNS}`,[leaseId,principal.sessionId,new Date(clock.now().getTime()+1000),clock.now()])).rows[0];if(!result)throw fail('LEASE_CHANGED');return result;
    });},
    async requestTakeover(principal,{deviceId,targetEpoch,clientInstanceId,connectionId,nonceHash}){return transaction(pool,async client=>{
      await assertPrincipal(client,principal,clock.now());await lockedDevice(client,deviceId);
      const current=(await client.query(`SELECT ${COLUMNS},u.display_name AS "holderName" FROM ops.control_leases l JOIN auth.users u ON u.id=l.user_id
        WHERE l.device_id=$1 AND l.state='active'`,[deviceId])).rows[0];
      if(!current||current.leaseEpoch!==targetEpoch)throw fail('LEASE_CHANGED');
      const request=(await client.query(`INSERT INTO ops.control_takeovers(device_id,user_id,session_id,client_instance_id,browser_connection_id,target_lease_id,target_epoch,nonce_hash,state,created_at,expires_at)
        VALUES($1,$2,$3,$4,$5,$6,$7,$8,'pending',$9,$10) RETURNING id`,[deviceId,principal.userId,principal.sessionId,clientInstanceId,connectionId,current.id,targetEpoch,nonceHash,clock.now(),new Date(clock.now().getTime()+30000)])).rows[0];
      return {requestId:request.id,holderName:current.holderName,targetEpoch};
    });},
    async beginTakeover(principal,{requestId,nonceHash,clientInstanceId,connectionId}){return transaction(pool,async client=>{
      await assertPrincipal(client,principal,clock.now());
      const peek=(await client.query('SELECT device_id FROM ops.control_takeovers WHERE id=$1',[requestId])).rows[0];if(!peek)throw fail('TAKEOVER_INVALID');
      await lockedDevice(client,peek.device_id);
      const request=(await client.query(`SELECT * FROM ops.control_takeovers WHERE id=$1 AND session_id=$2 AND user_id=$3 AND client_instance_id=$4 AND browser_connection_id=$5
        AND nonce_hash=$6 AND state='pending' AND expires_at>$7 FOR UPDATE`,[requestId,principal.sessionId,principal.userId,clientInstanceId,connectionId,nonceHash,clock.now()])).rows[0];if(!request)throw fail('TAKEOVER_INVALID');
      const lease=(await client.query(`SELECT ${COLUMNS} FROM ops.control_leases l WHERE l.id=$1 AND l.state='active' AND l.lease_epoch=$2 FOR UPDATE`,[request.target_lease_id,request.target_epoch])).rows[0];if(!lease)throw fail('LEASE_CHANGED');
      await client.query("UPDATE ops.control_takeovers SET state='stopping',confirmed_at=$2 WHERE id=$1",[requestId,clock.now()]);
      await client.query("UPDATE ops.control_leases SET state='revoking',release_reason='takeover' WHERE id=$1",[lease.id]);return lease;
    });},
    async finishTakeover(principal,{requestId,oldLease,context,clientInstanceId,connectionId}){return transaction(pool,async client=>{
      await assertPrincipal(client,principal,clock.now());const device=await lockedDevice(client,oldLease.deviceId);
      const request=(await client.query("SELECT id FROM ops.control_takeovers WHERE id=$1 AND state='stopping' AND target_lease_id=$2 AND session_id=$3 FOR UPDATE",[requestId,oldLease.id,principal.sessionId])).rows[0];
      const old=(await client.query("SELECT id FROM ops.control_leases WHERE id=$1 AND state='revoking' FOR UPDATE",[oldLease.id])).rows[0];
      if(!request||!old||BigInt(device.control_epoch)!==BigInt(oldLease.leaseEpoch))throw fail('LEASE_CHANGED');
      await client.query("UPDATE ops.control_leases SET state='released',released_at=$2 WHERE id=$1",[oldLease.id,clock.now()]);
      const lease=await reserve(client,principal,{context,clientInstanceId,connectionId},device);
      await client.query("UPDATE ops.control_takeovers SET stop_result=$2,granted_lease_id=$3 WHERE id=$1",[requestId,{state:'stopped'},lease.id]);return lease;
    });},
    async completeTakeover(id,leaseId){const result=await pool.query("UPDATE ops.control_takeovers SET state='granted' WHERE id=$1 AND state='stopping' AND granted_lease_id=$2",[id,leaseId]);if(!result.rowCount)throw fail('TAKEOVER_INVALID');},
    async failTakeover(id,code){await pool.query("UPDATE ops.control_takeovers SET state='failed',stop_result=$2 WHERE id=$1 AND state='stopping'",[id,{code}]);},
    async recordCommand(principal,{leaseId,clientInstanceId,connectionId,commandId,opcode,parameters,expiresAt}){return transaction(pool,async client=>{
      const actor=await assertPrincipal(client,principal,clock.now());
      const lease=(await client.query(`SELECT ${COLUMNS} FROM ops.control_leases l WHERE l.id=$1 FOR UPDATE`,[leaseId])).rows[0];
      if(!lease||lease.state!=='active'||lease.sessionId!==principal.sessionId||lease.clientInstanceId!==clientInstanceId||lease.connectionId!==connectionId)throw fail('FORBIDDEN');
      const requestDigest=digest(JSON.stringify({leaseId,opcode,parameters}));
      const previous=(await client.query('SELECT command_id AS "commandId",run_id AS "runId",session_id AS "sessionId",request_digest,state,result FROM ops.commands WHERE command_id=$1',[commandId])).rows[0];
      if(previous){if(previous.sessionId!==principal.sessionId||previous.request_digest!==requestDigest)throw fail('COMMAND_ID_CONFLICT');return {fresh:false,receipt:{commandId:previous.commandId,runId:previous.runId,state:previous.state,...previous.result}};}
      const sequence=Number((await client.query('SELECT COALESCE(MAX(sequence),0)+1 AS sequence FROM ops.commands WHERE device_id=$1 AND lease_epoch=$2',[lease.deviceId,lease.leaseEpoch])).rows[0].sequence);
      if(!Number.isSafeInteger(sequence))throw fail('SEQUENCE_EXHAUSTED');
      const runId=randomUUID();
      await client.query(`INSERT INTO ops.runs(id,device_id,boot_id,actor_user_id,actor_kind,actor_display_name,source,status,started_at)
        VALUES($1,$2,$3,$4,'user',$5,$6,'requested',$7)`,[runId,lease.deviceId,lease.bootId,principal.userId,actor.displayName,opcode==='preset'?'preset':'manual',clock.now()]);
      await client.query(`INSERT INTO ops.commands(command_id,run_id,device_id,boot_id,session_id,lease_id,executor_epoch,lease_epoch,sequence,opcode,schema_version,parameters,expires_at,state,request_digest,created_at)
        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,1,$11,$12,'unknown',$13,$14)`,[commandId,runId,lease.deviceId,lease.bootId,principal.sessionId,lease.id,lease.executorEpoch,lease.leaseEpoch,sequence,opcode,parameters,expiresAt,requestDigest,clock.now()]);
      return {fresh:true,lease,sequence,receipt:{commandId,runId,state:'unknown'}};
    });},
    async finishCommand(receipt,result){await transaction(pool,async client=>{
      await client.query('UPDATE ops.commands SET state=$2,result=$3 WHERE command_id=$1',[receipt.commandId,result.state,result]);
      const status={accepted:'running',started:'running',completed:'completed',stopped:'stopped',rejected:'rejected',failed:'failed',unknown:'unknown'}[result.state];
      await client.query('UPDATE ops.runs SET status=$2,ended_at=$3 WHERE id=$1',[receipt.runId,status,['accepted','started'].includes(result.state)?null:clock.now()]);
    });}
  };
  return api;
}
module.exports={createLeasesRepository,assertPrincipal};
