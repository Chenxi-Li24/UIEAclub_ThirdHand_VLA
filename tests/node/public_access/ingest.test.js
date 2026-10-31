'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {randomUUID,createHash}=require('node:crypto');
const {identityFixture}=require('./identity-fixture');
const {createIngestRepository}=require('../../../platform/storage/src/ingest');

function batch(context,{first=0,count=2,batchSequence=0,batchId=randomUUID(),rows,streamKind='robot_samples',at='2026-10-30T09:00:00.000Z'}={}){
  const records=rows||Array.from({length:count},(_,index)=>({sequence:first+index,capturedAt:at,monotonicNs:String(1000000000+index),clockQuality:'estimated',jointPositionRad:[0,1.57,-1.57,0,0,0],sdkConnected:true,moving:false,extra:{sourceSequence:first+index}}));
  const payload=Buffer.from(JSON.stringify({schema:1,agentVersion:'0.1.0',batchId,deviceId:context.deviceId,bootId:context.bootId,streamKind,batchSequence,firstSequence:first,lastSequence:first+records.length-1,rows:records}));
  return {batchId,digest:createHash('sha256').update(payload).digest('hex'),payloadBase64url:payload.toString('base64url')};
}
async function fixture(t){const f=await identityFixture(t);const deviceId=(await f.pool.query("INSERT INTO ops.devices(name,hardware_serial,enabled) VALUES('ingest','ingest-only',true) RETURNING id")).rows[0].id;const certificateId=(await f.pool.query("INSERT INTO ops.device_credentials(device_id,certificate_serial,fingerprint_sha256,public_key,not_before,expires_at) VALUES($1,'ingest-only',$2,'test-only',$3,$4) RETURNING id",[deviceId,'e'.repeat(64),new Date(f.clock.value-1000),new Date(f.clock.value+86400000)])).rows[0].id;return {...f,context:{deviceId,bootId:randomUUID(),certificateId},ingest:createIngestRepository(f.pool,{clock:f.clock})};}

test('immutable batch ACK means complete committed ledger plus all raw samples; replay cannot duplicate',async t=>{
  const f=await fixture(t),value=batch(f.context);
  await f.pool.query("SELECT telemetry.ensure_month_partition('2026-10-01'::date)");
  const ack=await f.ingest.ingestBatch(f.context,value);assert.deepEqual(ack,{batchId:value.batchId,digest:value.digest,persisted:true});
  assert.deepEqual(await f.ingest.ingestBatch(f.context,value),ack);
  assert.equal((await f.pool.query('SELECT count(*) FROM telemetry.robot_samples')).rows[0].count,'2');
  const raw=(await f.pool.query('SELECT payload_bytes FROM telemetry.ingest_batch_payloads WHERE batch_id=$1',[value.batchId])).rows[0].payload_bytes;
  assert.equal(createHash('sha256').update(raw).digest('hex'),value.digest);
  await assert.rejects(f.ingest.ingestBatch(f.context,{...value,digest:'0'.repeat(64)}),{code:'BATCH_DIGEST_MISMATCH'});
});

test('overlapping source sequence conflicts across new batch IDs and timestamps, including concurrent upload',async t=>{
  const f=await fixture(t);await f.pool.query("SELECT telemetry.ensure_month_partition('2026-10-01'::date)");
  const outcomes=await Promise.allSettled([f.ingest.ingestBatch(f.context,batch(f.context,{first:0,count:3})),f.ingest.ingestBatch(f.context,batch(f.context,{first:2,count:3,batchSequence:1,at:'2026-10-30T10:00:00.000Z'}))]);
  assert.equal(outcomes.filter(x=>x.status==='fulfilled').length,1);assert.equal(outcomes.find(x=>x.status==='rejected').reason.code,'BATCH_CONFLICT');
  assert.equal((await f.pool.query('SELECT count(*) FROM telemetry.robot_samples')).rows[0].count,'3');
});

test('missing partition rolls back ledger and gives no ACK; invalid numeric shape is retained separately',async t=>{
  const f=await fixture(t),outOfWindow=batch(f.context,{at:'2040-01-01T00:00:00.000Z'});
  await assert.rejects(f.ingest.ingestBatch(f.context,outOfWindow));
  assert.equal((await f.pool.query('SELECT count(*) FROM telemetry.ingest_batches')).rows[0].count,'0');
  await f.pool.query("SELECT telemetry.ensure_month_partition('2026-10-01'::date)");
  const rows=[{sequence:0,capturedAt:'2026-10-30T09:00:00.000Z',monotonicNs:'100',clockQuality:'estimated',jointPositionRad:[1,2],sdkConnected:true,moving:false,extra:{}}];
  const invalid=batch(f.context,{rows});assert.equal((await f.ingest.ingestBatch(f.context,invalid)).persisted,true);
  assert.equal((await f.pool.query('SELECT count(*) FROM telemetry.invalid_samples')).rows[0].count,'1');
  assert.equal((await f.pool.query('SELECT count(*) FROM telemetry.robot_samples')).rows[0].count,'0');
});
module.exports={batch};

test('device and command events preserve outcomes and cannot roll a completed command back to accepted',async t=>{
  const f=await fixture(t),actor=await f.verified('event_actor'),runId=randomUUID(),commandId=randomUUID(),executorEpoch=randomUUID();
  await f.pool.query("INSERT INTO ops.device_boots(boot_id,device_id,agent_version) VALUES($1,$2,'0.1.0')",[f.context.bootId,f.context.deviceId]);
  await f.pool.query("INSERT INTO ops.execution_instances(executor_epoch,device_id,boot_id,worker_instance_id) VALUES($1,$2,$3,'fake-event-worker')",[executorEpoch,f.context.deviceId,f.context.bootId]);
  await f.pool.query("INSERT INTO ops.runs(id,device_id,boot_id,actor_user_id,actor_kind,actor_display_name,source,status) VALUES($1,$2,$3,$4,'user','Event actor','manual','unknown')",[runId,f.context.deviceId,f.context.bootId,actor.userId]);
  await f.pool.query("INSERT INTO ops.commands(command_id,run_id,device_id,boot_id,executor_epoch,lease_epoch,sequence,opcode,schema_version,parameters,expires_at,state) VALUES($1,$2,$3,$4,$5,1,1,'move_joint',1,$6,$7,'unknown')",[commandId,runId,f.context.deviceId,f.context.bootId,executorEpoch,{joints:[10,80,-80,0,0,0]},new Date(f.clock.value+1000)]);
  const rows=['completed','accepted'].map((state,sequence)=>({sequence,eventId:randomUUID(),commandId,state,eventCode:'command.outcome',capturedAt:'2026-10-30T09:00:00.000Z',details:{state}}));
  await f.ingest.ingestBatch(f.context,batch(f.context,{streamKind:'command_events',rows}));
  assert.equal((await f.pool.query('SELECT state FROM ops.commands WHERE command_id=$1',[commandId])).rows[0].state,'completed');
  assert.equal((await f.pool.query('SELECT count(*) FROM ops.command_events')).rows[0].count,'2');
  const events=[{sequence:0,eventId:randomUUID(),eventCode:'capture.source_gap',capturedAt:'2026-10-30T09:00:00.000Z',level:'error',details:{firstSourceSequence:10,lastSourceSequence:12}}];
  assert.equal((await f.ingest.ingestBatch(f.context,batch(f.context,{streamKind:'device_events',rows:events}))).persisted,true);
  assert.equal((await f.pool.query('SELECT count(*) FROM ops.device_events')).rows[0].count,'1');
});
