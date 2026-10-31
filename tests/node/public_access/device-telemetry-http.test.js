'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),{randomBytes,randomUUID}=require('node:crypto');
const {identityFixture}=require('./identity-fixture');
const {createSessions}=require('../../../platform/identity/src/sessions');
const {createCloudApi}=require('../../../services/cloud-api/src/server');
test('authenticated latest-state view distinguishes missing data and actual measured samples without SDK calls',async t=>{
  const f=await identityFixture(t),user=await f.verified('telemetry_view'),sessions=createSessions({pool:f.pool,csrfKey:randomBytes(32),clock:f.clock});
  const server=createCloudApi({...f,sessions,publicOrigin:'https://thirdhand.example.invalid'});await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));t.after(()=>new Promise(resolve=>{server.closeAllConnections();server.close(resolve);}));
  const base=`http://127.0.0.1:${server.address().port}`,issued=await sessions.issue({userId:user.userId}),headers={cookie:issued.cookie.split(';')[0]};
  const deviceId=(await f.pool.query("INSERT INTO ops.devices(name,hardware_serial,enabled) VALUES('Measured arm','measured-fixture',true) RETURNING id")).rows[0].id;
  const url=base+'/api/v1/devices/'+deviceId+'/telemetry';assert.equal((await fetch(url)).status,401);
  const empty=await fetch(url,{headers});assert.equal(empty.status,200);assert.equal((await empty.json()).sample,null);
  const bootId=randomUUID();await f.pool.query("INSERT INTO ops.device_boots(boot_id,device_id,agent_version) VALUES($1,$2,'test')",[bootId,deviceId]);
  await f.pool.query(`INSERT INTO telemetry.robot_samples(device_id,boot_id,sample_seq,captured_at,monotonic_ns,clock_quality,schema_version,joint_position_rad,sdk_connected,moving,extra)
    VALUES($1,$2,42,now(),123,'estimated',1,ARRAY[0.1,0.2,0.3,0.4,0.5,0.6],true,false,'{"sourceMode":"hardware"}')`,[deviceId,bootId]);
  const measured=await fetch(url,{headers}).then(r=>r.json());assert.equal(measured.purpose,'display-only');assert.equal(measured.sample.sample_seq,'42');assert.equal(measured.sample.source_mode,'hardware');assert.deepEqual(measured.sample.joint_position_rad,[0.1,0.2,0.3,0.4,0.5,0.6]);assert.equal(measured.sample.sdk_connected,true);
  const unavailable=await fetch(base+'/api/v1/devices/00000000-0000-4000-8000-000000000000/telemetry',{headers});assert.equal(unavailable.status,404);
});
