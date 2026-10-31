'use strict';
const UUID=/^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
function object(value,keys){return value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).every(key=>keys.includes(key));}
function parseMessage(raw,isBinary=false){
  if(isBinary||raw.length>16384)throw Error('INVALID_MESSAGE');
  const value=JSON.parse(raw.toString('utf8'));if(!object(value,['type','protocol','deviceId','bootId','executorEpoch','agentVersion','capabilities','signatureBase64url','nonce','hardwareFingerprint','previousStop','requestId','outcome']))throw Error('INVALID_MESSAGE');return value;
}
function validateHello(value,deviceId){
  if(!object(value,['type','protocol','deviceId','bootId','executorEpoch','agentVersion','capabilities'])||value.type!=='hello'||value.protocol!==1||value.deviceId!==deviceId||!UUID.test(value.deviceId)||!UUID.test(value.bootId)||!(value.executorEpoch===null||UUID.test(value.executorEpoch))||typeof value.agentVersion!=='string'||value.agentVersion.length>80||!/^\d+\.\d+\.\d+(?:[-+][a-zA-Z0-9.-]+)?$/.test(value.agentVersion)||!Array.isArray(value.capabilities)||value.capabilities.length!==1||value.capabilities[0]!== (value.executorEpoch===null?'probe':'control'))throw Error('INVALID_HELLO');
  return value;
}
function decodeBase64url(value,max=16384){
  if(typeof value!=='string'||!value.length||value.length>max||!/^[A-Za-z0-9_-]+$/.test(value))throw Error('INVALID_ENCODING');
  const decoded=Buffer.from(value,'base64url');if(decoded.toString('base64url')!==value)throw Error('INVALID_ENCODING');return decoded;
}
function validateEnvelope(value){
  if(!object(value,['keyId','payloadBase64url','signatureBase64url'])||typeof value.keyId!=='string'||!/^[A-Za-z0-9_-]{1,48}$/.test(value.keyId))throw Error('INVALID_ENVELOPE');
  decodeBase64url(value.payloadBase64url);if(decodeBase64url(value.signatureBase64url,86).length!==64)throw Error('INVALID_ENVELOPE');return value;
}
module.exports={UUID,object,parseMessage,validateHello,decodeBase64url,validateEnvelope};
