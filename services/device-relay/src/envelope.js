'use strict';
const {createPrivateKey,createPublicKey,sign,verify}=require('node:crypto');
const {validateEnvelope,decodeBase64url}=require('./protocol');
function createEnvelopeSigner({keyId,privateKey}){
  if(typeof keyId!=='string'||!/^[A-Za-z0-9_-]{1,48}$/.test(keyId))throw Error('Invalid signing key id');
  const key=privateKey?.type==='private'?privateKey:createPrivateKey(privateKey);
  if(key.asymmetricKeyType!=='ed25519')throw Error('Ed25519 private signing key required');
  return {sign(payload){
    if(!payload||typeof payload!=='object'||Array.isArray(payload)||payload.keyId!==undefined&&payload.keyId!==keyId)throw Error('Invalid signed payload');
    // Sign the exact UTF-8 bytes. Receivers verify before parsing or reserializing numbers.
    const bytes=Buffer.from(JSON.stringify({...payload,keyId}),'utf8');
    return validateEnvelope({keyId,payloadBase64url:bytes.toString('base64url'),signatureBase64url:sign(null,bytes,key).toString('base64url')});
  }};
}
function verifyEnvelope(envelope,trustedKeys,context,now=Date.now()){
  validateEnvelope(envelope);
  const trusted=trustedKeys.get(envelope.keyId);if(!trusted)throw Error('UNKNOWN_KEY');
  const key=trusted.type==='public'?trusted:createPublicKey(trusted);
  const bytes=decodeBase64url(envelope.payloadBase64url),signature=decodeBase64url(envelope.signatureBase64url,86);
  if(key.asymmetricKeyType!=='ed25519'||!verify(null,bytes,key,signature))throw Error('INVALID_SIGNATURE');
  const payload=JSON.parse(bytes.toString('utf8'));
  if(!payload||typeof payload!=='object'||Array.isArray(payload)||payload.schema!==1||payload.keyId!==envelope.keyId)throw Error('INVALID_PAYLOAD');
  for(const field of ['deviceId','bootId','executorEpoch','connectionId'])if(!context||payload[field]!==context[field])throw Error('WRONG_CONTEXT');
  if(context.certificateId!==undefined&&payload.certificateId!==context.certificateId)throw Error('WRONG_CONTEXT');
  if(!Number.isSafeInteger(payload.issuedAt)||!Number.isSafeInteger(payload.expiresAt)||payload.issuedAt>now+500||payload.expiresAt<=now||payload.expiresAt<=payload.issuedAt||payload.expiresAt-payload.issuedAt>5000)throw Error('EXPIRED_ENVELOPE');
  return payload;
}
module.exports={createEnvelopeSigner,verifyEnvelope};
