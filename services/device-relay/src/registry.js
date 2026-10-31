'use strict';
const {createPublicKey}=require('node:crypto');
const {transaction}=require('../../../platform/storage/src/pool');
const {UUID}=require('./protocol');
function createDeviceRegistry({pool,clock={now:()=>new Date()}}){
  return {async resolveCertificate(fingerprint){
    if(!/^[a-f0-9]{64}$/.test(fingerprint))return null;
    const row=(await pool.query(`SELECT d.id,c.id AS "certificateId",c.public_key AS "publicKey",c.fingerprint_sha256 AS fingerprint,
      coalesce((d.capabilities->>'remoteControlEnabled')='true',false) AND c.control_enabled AS "remoteControlEnabled",
      c.control_mode='read-only' AS "readOnly"
      FROM ops.device_credentials c JOIN ops.devices d ON d.id=c.device_id
      WHERE c.fingerprint_sha256=$1 AND d.enabled AND c.revoked_at IS NULL
      AND c.not_before<=$2 AND c.expires_at>$2`,[fingerprint,clock.now()])).rows[0];
    if(!row)return null;
    const key=createPublicKey(row.publicKey);if(key.asymmetricKeyType!=='ed25519')return null;
    return Object.freeze({...row,publicKey:key});
  },async registerExecution(context,hardwareFingerprint,previousStop=null){
    if(!/^[a-f0-9]{64}$/.test(hardwareFingerprint))throw Error('INVALID_BINDING');
    if(previousStop!==null){
      const keys=['deviceId','bootId','executorEpoch','connectionId','certificateId','leaseId','leaseEpoch','hardwareFingerprint','state','stopCommandId','stoppedAt'];
      if(!previousStop||typeof previousStop!=='object'||Array.isArray(previousStop)||Object.keys(previousStop).length!==keys.length||!Object.keys(previousStop).every(key=>keys.includes(key))||previousStop.state!=='stopped'||previousStop.deviceId!==context.deviceId||previousStop.hardwareFingerprint!==hardwareFingerprint||!['deviceId','bootId','executorEpoch','connectionId','certificateId','leaseId','stopCommandId'].every(key=>UUID.test(previousStop[key]))||!Number.isSafeInteger(previousStop.leaseEpoch)||previousStop.leaseEpoch<1||!Number.isSafeInteger(previousStop.stoppedAt)||previousStop.stoppedAt<0||previousStop.stoppedAt>clock.now().getTime()+500)throw Error('INVALID_STOP_EVIDENCE');
    }
    return transaction(pool,async client=>{
      const allowed=await client.query(`SELECT 1 FROM ops.devices d JOIN ops.device_credentials c ON c.device_id=d.id
        WHERE d.id=$1 AND c.id=$2 AND d.enabled AND c.control_enabled AND c.revoked_at IS NULL AND c.not_before<=$3 AND c.expires_at>$3 AND d.capabilities->>'remoteControlEnabled'='true' FOR SHARE OF d`,[context.deviceId,context.certificateId,clock.now()]);
      if(!allowed.rowCount)throw Error('CONTROL_DISABLED');
      await client.query("INSERT INTO ops.device_boots(boot_id,device_id,agent_version) VALUES($1,$2,'0.1.0') ON CONFLICT(boot_id) DO NOTHING",[context.bootId,context.deviceId]);
      const boot=(await client.query('SELECT device_id FROM ops.device_boots WHERE boot_id=$1',[context.bootId])).rows[0];if(boot.device_id!==context.deviceId)throw Error('BOOT_CONFLICT');
      const inserted=await client.query(`INSERT INTO ops.execution_instances(executor_epoch,device_id,boot_id,worker_instance_id,hardware_identity,binding_confirmation)
        VALUES($1,$2,$3,$6,$4,$5) ON CONFLICT(executor_epoch) DO UPDATE SET binding_confirmation=excluded.binding_confirmation
        WHERE execution_instances.device_id=excluded.device_id AND execution_instances.boot_id=excluded.boot_id AND execution_instances.ended_at IS NULL
        AND execution_instances.hardware_identity=excluded.hardware_identity`,[context.executorEpoch,context.deviceId,context.bootId,{bindingFingerprint:hardwareFingerprint},{certificateId:context.certificateId,connectionId:context.connectionId,confirmedAt:clock.now().toISOString(),previousStop},hardwareFingerprint]);
      if(!inserted.rowCount)throw Error('EXECUTOR_CONFLICT');
      if(previousStop){
        await client.query(`UPDATE ops.control_leases l SET state='released',released_at=$9,release_reason='device_confirmed_prior_stop'
          FROM ops.execution_instances e WHERE l.id=$1 AND l.device_id=$2 AND l.boot_id=$3 AND l.executor_epoch=$4 AND l.device_connection_id=$5
          AND l.certificate_id=$6 AND l.lease_epoch=$7 AND l.state IN ('requested','active','revoking')
          AND e.executor_epoch=l.executor_epoch AND e.hardware_identity->>'bindingFingerprint'=$8`,[previousStop.leaseId,context.deviceId,previousStop.bootId,previousStop.executorEpoch,previousStop.connectionId,previousStop.certificateId,previousStop.leaseEpoch,hardwareFingerprint,clock.now()]);
        const remaining=await client.query("SELECT id FROM ops.control_leases WHERE device_id=$1 AND state IN ('requested','active','revoking')",[context.deviceId]);
        if(remaining.rowCount)throw Error('UNRESOLVED_PRIOR_LEASE');
      }
      return true;
    });
  }};
}
module.exports={createDeviceRegistry};
