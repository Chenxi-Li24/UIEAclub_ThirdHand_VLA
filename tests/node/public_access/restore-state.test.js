'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {controlFixture}=require('./control-fixture');
const {isolateStagingRestore}=require('../../../tools/operations/isolate_staging_restore');

test('a staging restore preserves records while invalidating old sessions, credentials and queued control with an external bigint epoch floor',async t=>{
  const f=await controlFixture(t),leaseId=randomUUID(),runId=randomUUID(),commandId=randomUUID();
  await f.pool.query(`INSERT INTO ops.control_leases(id,device_id,user_id,session_id,client_instance_id,boot_id,executor_epoch,lease_epoch,state,expires_at)
    VALUES($1,$2,$3,$4,$5,$6,$7,1,'active',now()+interval '1 day')`,[leaseId,f.deviceId,f.first.userId,f.first.sessionId,randomUUID(),f.context.bootId,f.context.executorEpoch]);
  await f.pool.query(`INSERT INTO ops.runs(id,device_id,boot_id,actor_user_id,actor_kind,actor_display_name,source,status)
    VALUES($1,$2,$3,$4,'user','Synthetic restore test','manual','running')`,[runId,f.deviceId,f.context.bootId,f.first.userId]);
  await f.pool.query(`INSERT INTO ops.commands(command_id,run_id,device_id,boot_id,executor_epoch,lease_epoch,sequence,opcode,schema_version,parameters,expires_at,state)
    VALUES($1,$2,$3,$4,$5,1,1,'joint_target',1,'{}',now()+interval '1 day','accepted')`,[commandId,runId,f.deviceId,f.context.bootId,f.context.executorEpoch]);
  // A database restore must not revive a recovery code consumed after its backup.
  await f.pool.query("INSERT INTO auth.mfa_credentials(user_id,kind,recovery_hash,enabled_at) VALUES($1,'recovery',repeat('d',64),now())",[f.first.userId]);
  await assert.rejects(isolateStagingRestore(f.pool,{epochFloors:{},confirmation:'ISOLATE_STAGING_RESTORE'}),{code:'RESTORE_EPOCH_FLOOR_REQUIRED'});
  assert.equal((await f.pool.query('SELECT revoked_at FROM auth.sessions WHERE id=$1',[f.first.sessionId])).rows[0].revoked_at,null);
  const floor='9007199254741001';
  await isolateStagingRestore(f.pool,{epochFloors:{[f.deviceId]:floor},confirmation:'ISOLATE_STAGING_RESTORE'});
  assert.equal(await f.sessions.resolveSession({headers:{cookie:f.cookieFor(f.first)}}),null);
  assert.equal((await f.pool.query('SELECT count(*) FROM auth.users')).rows[0].count,'2');
  const device=(await f.pool.query('SELECT enabled,control_epoch FROM ops.devices WHERE id=$1',[f.deviceId])).rows[0];
  assert.equal(device.enabled,false);assert.equal(device.control_epoch,'9007199254741002');
  assert.ok((await f.pool.query('SELECT revoked_at FROM ops.device_credentials')).rows.every(r=>r.revoked_at));
  assert.ok((await f.pool.query('SELECT revoked_at FROM auth.mfa_credentials')).rows.every(r=>r.revoked_at));
  assert.equal((await f.pool.query('SELECT state FROM ops.control_leases WHERE id=$1',[leaseId])).rows[0].state,'failed');
  assert.equal((await f.pool.query('SELECT state FROM ops.commands WHERE command_id=$1',[commandId])).rows[0].state,'unknown');
  assert.equal((await f.pool.query('SELECT status FROM ops.runs WHERE id=$1',[runId])).rows[0].status,'unknown');
  assert.equal(f.requests.length,0);
});

test('restore isolation rejects missing deliberate confirmation before mutating sessions',async t=>{
  const f=await controlFixture(t);
  await assert.rejects(isolateStagingRestore(f.pool,{epochFloors:{[f.deviceId]:'1'}}),{code:'RESTORE_CONFIRMATION_REQUIRED'});
  assert.ok(await f.sessions.resolveSession({headers:{cookie:f.cookieFor(f.first)}}));
});
