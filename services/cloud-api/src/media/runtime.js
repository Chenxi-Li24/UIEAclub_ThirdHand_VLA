'use strict';
const fs=require('node:fs/promises');
const {createDeviceRelay}=require('../../../device-relay/src/server');
const {createDeviceRegistry}=require('../../../device-relay/src/registry');
const {createEnvelopeSigner}=require('../../../device-relay/src/envelope');
const {createLiveKitProvider}=require('./livekit-provider');
const {createMediaService}=require('./policy');

function createCameraMediaRuntime({pool,sessions,config}){
  const registry=createDeviceRegistry({pool});
  // This deployment has no execution registration, telemetry writes, or control
  // service. Even a mistakenly control-enabled database row is refused here.
  const store={async resolveCertificate(fingerprint){const row=await registry.resolveCertificate(fingerprint);return row?.remoteControlEnabled===false?row:null;}};
  let mediaService,closed=false;
  const relay=createDeviceRelay({store,trustedUnixProxy:true,maxDevices:1,mediaPublisher:(context,value)=>mediaService.acceptPublisher(context,value)});
  const signer=createEnvelopeSigner({keyId:config.keyId,privateKey:config.privateKey});
  const provider=createLiveKitProvider({apiKey:config.apiKey,apiSecret:config.apiSecret,host:config.host});
  mediaService=createMediaService({sessions,devices:relay.devices,provider,signer,maxViewers:config.maxViewers});
  return {relay,mediaService,async listen(){
    if(process.platform!=='linux'||closed)throw Error('CAMERA_UNIX_RUNTIME_REQUIRED');
    // Never unlink a pre-existing socket: it may belong to another live process.
    await new Promise((resolve,reject)=>{relay.server.once('error',reject);relay.server.listen(config.socketPath,resolve);});
    await fs.chmod(config.socketPath,0o660);
  },async close(){if(closed)return;closed=true;await mediaService.close();await relay.close();}};
}
module.exports={createCameraMediaRuntime};
