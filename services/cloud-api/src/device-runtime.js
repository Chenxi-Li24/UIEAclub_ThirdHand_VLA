'use strict';
const fs=require('node:fs/promises');
const {createDeviceRelay}=require('../../device-relay/src/server');
const {createDeviceRegistry}=require('../../device-relay/src/registry');
const {createEnvelopeSigner}=require('../../device-relay/src/envelope');
const {createIngestRepository}=require('../../../platform/storage/src/ingest');
const {createLeasesRepository}=require('../../../platform/storage/src/leases');
const {createBrowserControlRegistry}=require('./control/control-channel');
const {createControlService}=require('./control/leases');
const {createLiveKitProvider}=require('./media/livekit-provider');
const {createMediaService}=require('./media/policy');

// One authenticated device connection owns media and execution. Camera-only
// credentials cannot bind an executor; data uploads are independently signed.
function createDeviceRuntime({pool,sessions,mediaConfig,config}){
  if(config.control&&!config.telemetry)throw Error('CONTROL_REQUIRES_TELEMETRY');
  if(!mediaConfig)throw Error('DEVICE_MEDIA_CONFIGURATION_REQUIRED');
  const registry=createDeviceRegistry({pool}),ingest=config.telemetry?createIngestRepository(pool):null;
  const store={async resolveCertificate(fingerprint){const row=await registry.resolveCertificate(fingerprint);return row&&(!row.remoteControlEnabled||config.control)?row:null;},
    ...(config.control?{registerExecution:(...args)=>registry.registerExecution(...args)}:{})};
  let mediaService,closed=false;
  const relay=createDeviceRelay({store,trustedUnixProxy:true,maxDevices:4,
    ...(ingest?{ingestBatch:(context,envelope)=>ingest.ingestBatch(context,envelope)}:{}),
    mediaPublisher:(context,value,negotiation)=>mediaService.acceptPublisher(context,value,negotiation)});
  const provider=createLiveKitProvider({apiKey:mediaConfig.apiKey,apiSecret:mediaConfig.apiSecret,host:mediaConfig.host});
  mediaService=createMediaService({sessions,devices:relay.devices,provider,
    signer:createEnvelopeSigner({keyId:mediaConfig.keyId,privateKey:mediaConfig.privateKey}),maxViewers:mediaConfig.maxViewers});
  const controlChannels=config.control?createBrowserControlRegistry():null;
  const controlService=config.control?createControlService({repository:createLeasesRepository(pool),sessions,channels:controlChannels,devices:relay.devices,
    signer:createEnvelopeSigner(config.control),
    // Initial remote rollout is explicitly SDK read-only. Full movement stays
    // closed until physical binding, video timing and tutorial acceptance exist.
    readiness:async(_principal,id)=>relay.devices.get(id)?.readOnly===true}):null;
  return {relay,mediaService,controlChannels,controlService,async listen(){
    if(process.platform!=='linux'||closed)throw Error('DEVICE_UNIX_RUNTIME_REQUIRED');
    await new Promise((resolve,reject)=>{relay.server.once('error',reject);relay.server.listen(mediaConfig.socketPath,resolve);});
    await fs.chmod(mediaConfig.socketPath,0o660);
  },async close(){if(closed)return;closed=true;await controlService?.close();await mediaService.close();await relay.close();}};
}
module.exports={createDeviceRuntime};
