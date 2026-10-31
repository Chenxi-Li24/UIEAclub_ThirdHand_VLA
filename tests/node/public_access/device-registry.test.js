'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {generateKeyPairSync}=require('node:crypto');
const {randomUUID}=require('node:crypto');
const {identityFixture}=require('./identity-fixture');
const {createDeviceRegistry}=require('../../../services/device-relay/src/registry');

test('registry rejects disabled, future, expired and revoked credentials; person roles never enroll devices',async t=>{
  const f=await identityFixture(t), registry=createDeviceRegistry({pool:f.pool,clock:f.clock});
  const key=generateKeyPairSync('ed25519').publicKey.export({type:'spki',format:'pem'});
  const device=(await f.pool.query("INSERT INTO ops.devices(name,hardware_serial) VALUES('test','test-only') RETURNING id")).rows[0].id;
  const fingerprint='a'.repeat(64);
  await f.pool.query(`INSERT INTO ops.device_credentials(device_id,certificate_serial,fingerprint_sha256,public_key,not_before,expires_at)
    VALUES($1,'test-serial',$2,$3,$4,$5)`,[device,fingerprint,key,new Date(f.clock.value-1000),new Date(f.clock.value+1000)]);
  assert.equal(await registry.resolveCertificate(fingerprint),null);
  await f.pool.query('UPDATE ops.devices SET enabled=true WHERE id=$1',[device]);
  const found=await registry.resolveCertificate(fingerprint);assert.equal(found.id,device);assert.equal(found.publicKey.asymmetricKeyType,'ed25519');
  assert.equal(await registry.resolveCertificate('not-a-fingerprint'),null);
  f.clock.value+=1000;assert.equal(await registry.resolveCertificate(fingerprint),null);
  f.clock.value-=3000;assert.equal(await registry.resolveCertificate(fingerprint),null);
  f.clock.value+=2000;
  await f.pool.query('UPDATE ops.device_credentials SET revoked_at=now() WHERE device_id=$1',[device]);
  assert.equal(await registry.resolveCertificate(fingerprint),null);
});

test('bound execution enrollment requires explicit device control flag and immutable hardware binding',async t=>{
  const f=await identityFixture(t),registry=createDeviceRegistry({pool:f.pool,clock:f.clock}),key=generateKeyPairSync('ed25519').publicKey.export({type:'spki',format:'pem'});
  const deviceId=(await f.pool.query("INSERT INTO ops.devices(name,hardware_serial,enabled) VALUES('bound','bound-only',true) RETURNING id")).rows[0].id;
  const certificateId=(await f.pool.query(`INSERT INTO ops.device_credentials(device_id,certificate_serial,fingerprint_sha256,public_key,not_before,expires_at) VALUES($1,'bound-serial',$2,$3,$4,$5) RETURNING id`,[deviceId,'c'.repeat(64),key,new Date(f.clock.value-1000),new Date(f.clock.value+60000)])).rows[0].id;
  const context={deviceId,certificateId,bootId:randomUUID(),executorEpoch:randomUUID(),connectionId:randomUUID()};
  await assert.rejects(registry.registerExecution(context,'d'.repeat(64)));
  await f.pool.query('UPDATE ops.devices SET capabilities=$2 WHERE id=$1',[deviceId,{remoteControlEnabled:true}]);
  await f.pool.query("UPDATE ops.device_credentials SET control_enabled=true,control_mode='full' WHERE id=$1",[certificateId]);
  assert.equal(await registry.registerExecution(context,'d'.repeat(64)),true);
  assert.equal(await registry.registerExecution({...context,connectionId:randomUUID()},'d'.repeat(64)),true);
  await assert.rejects(registry.registerExecution(context,'e'.repeat(64)));
  assert.equal((await f.pool.query('SELECT count(*) FROM ops.execution_instances')).rows[0].count,'1');
});

test('reconnect releases only the precisely matched prior lease after stopped evidence, never grants automatically',async t=>{
  const f=await require('./control-fixture').controlFixture(t),browser=f.browser(f.first),old=await f.service.requestLease(f.first,{deviceId:f.deviceId,...browser}),fingerprint='d'.repeat(64);
  await f.pool.query('UPDATE ops.devices SET capabilities=$2 WHERE id=$1',[f.deviceId,{remoteControlEnabled:true}]);
  await f.pool.query('UPDATE ops.execution_instances SET hardware_identity=$2 WHERE executor_epoch=$1',[f.context.executorEpoch,{bindingFingerprint:fingerprint}]);
  const registry=createDeviceRegistry({pool:f.pool,clock:f.clock}),context={...f.context,bootId:randomUUID(),executorEpoch:randomUUID(),connectionId:randomUUID()};
  const proof={deviceId:f.deviceId,bootId:old.bootId,executorEpoch:old.executorEpoch,connectionId:old.deviceConnectionId,certificateId:old.certificateId,leaseId:old.id,leaseEpoch:old.leaseEpoch,hardwareFingerprint:fingerprint,state:'stopped',stopCommandId:randomUUID(),stoppedAt:f.clock.value};
  await assert.rejects(registry.registerExecution(context,fingerprint,{...proof,state:'unknown'}));
  assert.equal((await f.repo.find(old.id)).state,'active');
  assert.equal(await registry.registerExecution(context,fingerprint,proof),true);
  assert.equal((await f.repo.find(old.id)).state,'released');
  assert.equal(await f.repo.current(f.deviceId),null);
  assert.equal((await f.pool.query('SELECT control_epoch FROM ops.devices WHERE id=$1',[f.deviceId])).rows[0].control_epoch,String(old.leaseEpoch));
  assert.equal(f.requests.filter(x=>x.purpose==='lease_grant').length,1);
});
