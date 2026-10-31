'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {generateKeyPairSync}=require('node:crypto');
const {identityFixture}=require('./identity-fixture');
const {createDeviceRegistry}=require('../../../services/device-relay/src/registry');

test('enabling physical control never upgrades an existing camera certificate',async t=>{
  const f=await identityFixture(t),registry=createDeviceRegistry({pool:f.pool,clock:f.clock});
  const device=(await f.pool.query("INSERT INTO ops.devices(name,hardware_serial,enabled,capabilities) VALUES('Scoped device','scope-test',true,'{\"camera\":true,\"remoteControlEnabled\":true}') RETURNING id")).rows[0].id;
  const publicKey=generateKeyPairSync('ed25519').publicKey.export({type:'spki',format:'pem'});
  const credentials=[];
  for(const [serial,fingerprint]of [['camera','a'.repeat(64)],['control','b'.repeat(64)]]){
    credentials.push((await f.pool.query(`INSERT INTO ops.device_credentials(device_id,certificate_serial,fingerprint_sha256,public_key,not_before,expires_at)
      VALUES($1,$2,$3,$4,$5,$6) RETURNING id`,[device,serial,fingerprint,publicKey,new Date(f.clock.value-1000),new Date(f.clock.value+60000)])).rows[0].id);
  }
  assert.equal((await registry.resolveCertificate('a'.repeat(64))).remoteControlEnabled,false);
  await f.pool.query('UPDATE ops.device_credentials SET control_enabled=true WHERE id=$1',[credentials[1]]);
  assert.equal((await registry.resolveCertificate('b'.repeat(64))).remoteControlEnabled,true);
  assert.equal((await registry.resolveCertificate('a'.repeat(64))).remoteControlEnabled,false);
});

test('device runtime composes signed ingest and optional control; camera-only mode has no control service',async t=>{
  const {EventEmitter}=require('node:events');
  const {createDeviceRuntime}=require('../../../services/cloud-api/src/device-runtime');
  const f=await identityFixture(t),key=generateKeyPairSync('ed25519');
  const sessions={events:new EventEmitter(),resolveSession:async()=>null};
  const config={socketPath:'/unused/test.sock',host:'http://127.0.0.1:7880',apiKey:'test-only-api-key',apiSecret:'test-only-secret-123456789012345678',keyId:'media-test',privateKey:key.privateKey,maxViewers:2};
  const data=createDeviceRuntime({pool:f.pool,sessions,mediaConfig:config,config:{telemetry:true,control:null}});
  t.after(()=>data.close());assert.equal(data.controlService,null);assert.equal(data.controlChannels,null);assert.ok(data.relay);
  const control=createDeviceRuntime({pool:f.pool,sessions,mediaConfig:config,config:{telemetry:true,control:{keyId:'control-test',privateKey:generateKeyPairSync('ed25519').privateKey}}});
  t.after(()=>control.close());assert.ok(control.controlService);assert.ok(control.controlChannels);
  assert.throws(()=>createDeviceRuntime({pool:f.pool,sessions,mediaConfig:config,config:{telemetry:false,control:{keyId:'test',privateKey:key.privateKey}}}),/CONTROL_REQUIRES_TELEMETRY/);
});
