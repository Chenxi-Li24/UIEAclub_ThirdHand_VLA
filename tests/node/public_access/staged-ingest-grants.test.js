'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),{randomUUID,createHash}=require('node:crypto');
const {identityFixture}=require('./identity-fixture'),{createIngestRepository}=require('../../../platform/storage/src/ingest');
test('exact staged least-privilege grants commit measured data without credential-update authority',async t=>{
  const f=await identityFixture(t),role='ingest_'+randomUUID().replaceAll('-','');
  await f.pool.query(`CREATE ROLE "${role}" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`);
  const client=await f.pool.connect();
  try{
    await client.query(`GRANT USAGE ON SCHEMA ops,telemetry TO "${role}"; GRANT SELECT ON ALL TABLES IN SCHEMA ops,telemetry TO "${role}"`);
    const grant=await require('node:fs/promises').readFile('deploy/public-access/staging/device/runtime-grants.sql','utf8');await client.query(grant.replaceAll('"thirdhand-stage"',`"${role}"`));
    const deviceId=(await client.query("INSERT INTO ops.devices(name,hardware_serial,enabled) VALUES('Staged measured fixture','exact-grants-test',true) RETURNING id")).rows[0].id;
    const certificateId=(await client.query(`INSERT INTO ops.device_credentials(device_id,certificate_serial,fingerprint_sha256,public_key,not_before,expires_at) VALUES($1,'staged-grants',$2,'test-only',$3,$4) RETURNING id`,[deviceId,'f'.repeat(64),new Date(f.clock.value-1000),new Date(f.clock.value+60000)])).rows[0].id;
    const context={deviceId,certificateId,bootId:randomUUID()},batchId=randomUUID(),rows=[{sequence:0,capturedAt:f.clock.now().toISOString(),monotonicNs:'123',clockQuality:'estimated',jointPositionRad:[0,1,2,3,4,5],sdkConnected:true,moving:false,extra:{sourceMode:'hardware'}}];
    const bytes=Buffer.from(JSON.stringify({schema:1,agentVersion:'0.1.0',batchId,deviceId,bootId:context.bootId,streamKind:'robot_samples',batchSequence:0,firstSequence:0,lastSequence:0,rows}));
    await client.query(`SET ROLE "${role}"`);
    const restricted={connect:async()=>({query:(...args)=>client.query(...args),release(){}})};
    const value=await createIngestRepository(restricted,{clock:f.clock}).ingestBatch(context,{batchId,digest:createHash('sha256').update(bytes).digest('hex'),payloadBase64url:bytes.toString('base64url')});
    assert.equal(value.persisted,true);assert.equal((await client.query('SELECT count(*) FROM telemetry.robot_samples')).rows[0].count,'1');
    assert.equal((await client.query("SELECT has_table_privilege(current_user,'ops.device_credentials','UPDATE') AS writable")).rows[0].writable,false);
  }finally{await client.query('RESET ROLE');await client.query(`DROP OWNED BY "${role}"`);client.release();await f.pool.query(`DROP ROLE "${role}"`);}
});
