'use strict';
const {AccessToken,TokenVerifier,RoomServiceClient,TrackSource}=require('livekit-server-sdk');
function createLiveKitProvider({apiKey,apiSecret,host}){
  const url=new URL(host);
  if(!apiKey||typeof apiSecret!=='string'||apiSecret.length<32||url.username||url.password||url.pathname!=='/'||url.search||url.hash||!['http:','https:'].includes(url.protocol)||url.protocol==='http:'&&!['127.0.0.1','[::1]'].includes(url.hostname))throw Error('Private loopback or verified HTTPS LiveKit API and independent secret required');
  const client=new RoomServiceClient(url.origin,apiKey,apiSecret,{requestTimeout:1,failover:false}),verifier=new TokenVerifier(apiKey,apiSecret);
  async function token({identity,room},publisher){
    const access=new AccessToken(apiKey,apiSecret,{identity,ttl:30});
    access.addGrant({room,roomJoin:true,canSubscribe:!publisher,canPublish:publisher,canPublishData:false,canUpdateOwnMetadata:false,...(publisher?{canPublishSources:[TrackSource.CAMERA]}:{})});
    return access.toJwt();
  }
  return {
    viewToken:value=>token(value,false),publisherToken:value=>token(value,true),verifyToken:value=>verifier.verify(value,0),
    ensureRoom:room=>client.createRoom({name:room,maxParticipants:11,emptyTimeout:30,departureTimeout:10}),
    async removeParticipant(room,identity){try{await client.removeParticipant(room,identity);}catch(error){if(error.code!=='not_found')throw error;}}
  };
}
module.exports={createLiveKitProvider};
