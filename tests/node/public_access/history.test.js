'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {randomUUID,randomBytes}=require('node:crypto');
const {identityFixture}=require('./identity-fixture');
const {createHistoryRepository}=require('../../../platform/storage/src/history');

async function historyFixture(t){
  const f=await identityFixture(t),user=await f.verified('history_reader');
  const deviceId=(await f.pool.query("INSERT INTO ops.devices(name,hardware_serial) VALUES('History fixture','history-test') RETURNING id")).rows[0].id,bootId=randomUUID();
  await f.pool.query("INSERT INTO ops.device_boots(boot_id,device_id,agent_version) VALUES($1,$2,'test')",[bootId,deviceId]);
  await f.pool.query("SELECT telemetry.ensure_month_partition('2026-10-01')");
  await f.pool.query(`INSERT INTO telemetry.robot_samples(device_id,boot_id,sample_seq,captured_at,monotonic_ns,clock_quality,schema_version,joint_position_rad,sdk_connected,moving,extra)
    SELECT $1::uuid,$2::uuid,n,'2026-10-30 09:00:00+00'::timestamptz+n*interval '0.000001 second',n,'estimated',1,ARRAY[0,1.57,-1.57,0,0,0]::float8[],true,false,'{"sourceMode":"simulation"}'::jsonb FROM generate_series(0,5) n`,[deviceId,bootId]);
  const principal={userId:user.userId,sessionId:randomUUID(),role:'observer',mode:'observe'};
  return {...f,deviceId,bootId,principal,history:createHistoryRepository(f.pool,{cursorKey:randomBytes(32)})};
}
test('observer pages every original sample with microsecond keys and a fixed insertion snapshot',async t=>{
  const f=await historyFixture(t),filter={kind:'samples',deviceId:f.deviceId,from:'2026-10-30T09:00:00Z',to:'2026-10-30T10:00:00Z'};
  const first=await f.history.queryPage(f.principal,filter,{limit:2});assert.equal(first.rows.length,2);
  // A late backfill inside the time range belongs to a new query, not this cursor.
  await f.pool.query(`INSERT INTO telemetry.robot_samples SELECT device_id,boot_id,99,captured_at+interval '1 second',received_at,monotonic_ns,clock_quality,schema_version,run_id,command_id,joint_position_rad,joint_velocity_rad_s,joint_current_a,joint_torque_nm,joint_temperature_c,field_availability,tcp_position_m,tcp_orientation_xyzw,tcp_frame_id,tool_version,calibration_version,gripper,sdk_connected,moving,fault_code,state_age_ms,quality_flags,extra FROM telemetry.robot_samples WHERE sample_seq=0`);
  let cursor=first.nextCursor,rows=[...first.rows];while(cursor){const page=await f.history.queryPage(f.principal,filter,{cursor,limit:2});rows.push(...page.rows);cursor=page.nextCursor;}
  assert.deepEqual(rows.map(row=>row.sample_seq),['0','1','2','3','4','5']);assert.equal(new Set(rows.map(row=>row.captured_at)).size,6);
  await f.pool.query("UPDATE telemetry.robot_samples SET monotonic_ns=9007199254740993 WHERE sample_seq=0");
  assert.equal((await f.history.queryPage(f.principal,filter)).rows[0].monotonic_ns,'9007199254740993');
  assert.equal((await f.history.queryPage(f.principal,{...filter,from:'2026-10-30T09:00:00.000003Z',to:'2026-10-30T09:00:00.000005Z'})).rows.length,2);
  assert.equal((await f.history.queryPage(f.principal,filter)).rows.length,7);
  await assert.rejects(f.history.queryPage({...f.principal,userId:randomUUID()},filter,{cursor:first.nextCursor}),{code:'INVALID_CURSOR'});
  await assert.rejects(f.history.queryPage(f.principal,{...filter,to:'2026-10-30T11:00:00Z'},{cursor:first.nextCursor}),{code:'INVALID_CURSOR'});
  await assert.rejects(f.history.queryPage(f.principal,filter,{cursor:first.nextCursor+'x'}),{code:'INVALID_CURSOR'});
});
test('history admits both roles, excludes identity/security tables and requires explicit timezone boundaries',async t=>{
  const f=await historyFixture(t),filter={kind:'samples',from:'2026-10-30T08:00:00+00:00',to:'2026-10-30T10:00:00Z'};
  assert.equal((await f.history.queryPage(f.principal,filter)).rows.length,6);
  assert.equal((await f.history.queryPage({...f.principal,role:'admin',mode:'admin',mfaVerifiedAt:new Date()},filter)).rows.length,6);
  for(const kind of ['users','sessions','identity_audit','device_credentials'])await assert.rejects(f.history.queryPage(f.principal,{...filter,kind}),{code:'INVALID_INPUT'});
  await assert.rejects(f.history.queryPage(null,filter),{code:'FORBIDDEN'});
  await assert.rejects(f.history.queryPage(f.principal,{...filter,from:'2026-10-30T08:00:00'}),{code:'INVALID_INPUT'});
});
test('large raw-state pages have bounded bytes and query concurrency without omitting remaining samples',async t=>{
  const f=await historyFixture(t),filter={kind:'samples',deviceId:f.deviceId,from:'2026-10-30T08:00:00Z',to:'2026-10-30T10:00:00Z'};
  await f.pool.query(`INSERT INTO telemetry.robot_samples(device_id,boot_id,sample_seq,captured_at,monotonic_ns,clock_quality,schema_version,joint_position_rad,sdk_connected,moving,extra)
    SELECT $1::uuid,$2::uuid,n,'2026-10-30 09:00:00+00'::timestamptz+n*interval '0.000001 second',n,'estimated',1,ARRAY[0,1.57,-1.57,0,0,0]::float8[],false,false,jsonb_build_object('raw',repeat('x',60000)) FROM generate_series(6,75) n`,[f.deviceId,f.bootId]);
  let cursor=null,count=0;do{const page=await f.history.queryPage(f.principal,filter,{cursor,limit:500});assert.ok(Buffer.byteLength(JSON.stringify(page))<2200000);count+=page.rows.length;cursor=page.nextCursor;}while(cursor);assert.equal(count,76);
  const results=await Promise.allSettled(Array.from({length:3},()=>f.history.queryPage(f.principal,filter,{limit:1})));assert.equal(results.filter(item=>item.status==='fulfilled').length,2);assert.equal(results.find(item=>item.status==='rejected').reason.code,'HISTORY_BUSY');
});
module.exports={historyFixture};
