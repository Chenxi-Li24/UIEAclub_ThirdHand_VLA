'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {randomBytes,generateKeyPairSync,randomUUID}=require('node:crypto');
const {EventEmitter}=require('node:events');
const {loadCloudConfig}=require('../../../services/cloud-api/src/config');

function environment(){
  const {privateKey}=generateKeyPairSync('ed25519');
  return {PUBLIC_ORIGIN:'https://staging.uiea-thirdhand.com',IDENTITY_DATABASE_URL:'postgresql://test@127.0.0.1/thirdhand_test',
    CSRF_KEY_BASE64:randomBytes(32).toString('base64'),MFA_KEY_BASE64:randomBytes(32).toString('base64'),
    TRUST_PROXY_LOOPBACK:'1',MEDIA_ENABLED:'1',MEDIA_EDGE_SOCKET_PATH:'/run/thirdhand-stage-edge/edge.sock',MEDIA_API_HOST:'http://127.0.0.1:7880',
    MEDIA_API_KEY:randomBytes(18).toString('hex'),MEDIA_API_SECRET:randomBytes(32).toString('hex'),
    MEDIA_SIGNING_KEY_ID:'camera-stage-v1',MEDIA_SIGNING_KEY_BASE64:privateKey.export({format:'der',type:'pkcs8'}).toString('base64'),MEDIA_MAX_VIEWERS:'2'};
}
test('camera configuration is explicit, private, bounded, and rejects partial activation',()=>{
  const env=environment(),base={...env};for(const key of Object.keys(base))if(key.startsWith('MEDIA_'))delete base[key];
  assert.equal(loadCloudConfig(base).media,null);
  const config=loadCloudConfig(env);assert.equal(config.media.maxViewers,2);assert.equal(config.media.privateKey.asymmetricKeyType,'ed25519');
  for(const change of [{MEDIA_ENABLED:'0'},{MEDIA_API_HOST:'http://0.0.0.0:7880'},{MEDIA_API_HOST:'https://other.example.invalid'},
    {MEDIA_API_HOST:'http://127.0.0.1:7880/api'},{MEDIA_EDGE_SOCKET_PATH:'/tmp/edge.sock'},{MEDIA_MAX_VIEWERS:'0'},
    {MEDIA_MAX_VIEWERS:'11'},{MEDIA_SIGNING_KEY_BASE64:env.CSRF_KEY_BASE64},{MEDIA_API_SECRET:''}]){
    assert.throws(()=>loadCloudConfig({...env,...change}),{code:'CONFIG_ERROR'});
  }
  const partial={...env};delete partial.MEDIA_API_KEY;assert.throws(()=>loadCloudConfig(partial),{code:'CONFIG_ERROR'});
});

test('telemetry/control activation is explicit and control signing cannot reuse the camera key',()=>{
  const env=environment();assert.equal(loadCloudConfig(env).deviceRuntime,null);
  for(const change of [{DEVICE_TELEMETRY_ENABLED:'1'},{DEVICE_CONTROL_ENABLED:'1'},
    {DEVICE_TELEMETRY_ENABLED:'0',DEVICE_CONTROL_ENABLED:'0'},
    {DEVICE_TELEMETRY_ENABLED:'1',DEVICE_CONTROL_ENABLED:'1',DEVICE_CONTROL_KEY_ID:'test',DEVICE_CONTROL_KEY_BASE64:env.MEDIA_SIGNING_KEY_BASE64}]){
    assert.throws(()=>loadCloudConfig({...env,...change}),{code:'CONFIG_ERROR'});
  }
  assert.equal(loadCloudConfig({...env,DEVICE_TELEMETRY_ENABLED:'1',DEVICE_CONTROL_ENABLED:'0'}).deviceRuntime.control,null);
  const privateKey=generateKeyPairSync('ed25519').privateKey;
  const config=loadCloudConfig({...env,DEVICE_TELEMETRY_ENABLED:'1',DEVICE_CONTROL_ENABLED:'1',DEVICE_CONTROL_KEY_ID:'sdk-stage',DEVICE_CONTROL_KEY_BASE64:privateKey.export({format:'der',type:'pkcs8'}).toString('base64')});
  assert.equal(config.deviceRuntime.control.privateKey.asymmetricKeyType,'ed25519');
});

test('camera runtime composes media and a non-executing relay without opening hardware or TCP listeners',async()=>{
  const {createCameraMediaRuntime}=require('../../../services/cloud-api/src/media/runtime');
  const events=new EventEmitter(),sessions={events,resolveSession:async()=>null};
  const runtime=createCameraMediaRuntime({pool:{query:async()=>({rows:[]})},sessions,config:loadCloudConfig(environment()).media});
  try{
    assert.equal(runtime.relay.server.listening,false);
    assert.deepEqual(runtime.mediaService.status(randomUUID()).available,false);
    assert.equal(runtime.mediaService.videoReadiness(null,randomUUID()),false);
    await assert.rejects(runtime.relay.devices.request(randomUUID(),{}));
    assert.equal(events.listenerCount('revoked'),1);
  }finally{await runtime.close();}
  assert.equal(events.listenerCount('revoked'),0);
});
