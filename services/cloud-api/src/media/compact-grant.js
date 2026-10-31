'use strict';
const {createHash}=require('node:crypto');
const BINDING=['deviceId','bootId','executorEpoch','connectionId','certificateId'];
const CACHE_DOMAIN='thirdhand-media-credentials-v1';
const DIGEST=/^[A-Za-z0-9_-]{43}$/;
function compactNegotiation(value){return !!value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===2&&value.format==='compact-v1'&&(value.credentialDigest===null||typeof value.credentialDigest==='string'&&DIGEST.test(value.credentialDigest));}
function credentialDigest(payload,keyId){return createHash('sha256').update(JSON.stringify([CACHE_DOMAIN,keyId,...BINDING.map(key=>payload[key]),payload.publisherId,payload.room,payload.identity,payload.token]),'utf8').digest('base64url');}
function publicationExpiry(token,{identity,room},now){
  // The token comes only from this service's trusted provider and is carried
  // inside a signed full grant. This parser does not authenticate an inbound JWT.
  try{
    if(typeof token!=='string'||token.length>8192)return null;
    const parts=token.split('.');if(parts.length!==3||!parts.every(part=>/^[A-Za-z0-9_-]+$/.test(part)))return null;
    const header=JSON.parse(Buffer.from(parts[0],'base64url')),claims=JSON.parse(Buffer.from(parts[1],'base64url')),v=claims.video;
    if(header.alg!=='HS256'||claims.sub!==identity||!Number.isSafeInteger(claims.exp)||!Number.isSafeInteger(claims.exp*1000)||claims.exp*1000<=now||claims.nbf!==undefined&&(!Number.isSafeInteger(claims.nbf)||claims.nbf*1000>now+500)||!v||v.room!==room||v.roomJoin!==true||v.canPublish!==true||v.canSubscribe!==false||v.canPublishData!==false||v.canUpdateOwnMetadata!==false||v.roomAdmin||v.roomCreate||v.roomRecord||v.ingressAdmin||!Array.isArray(v.canPublishSources)||v.canPublishSources.length!==1||v.canPublishSources[0]!=='camera')return null;
    return claims.exp*1000;
  }catch{return null;}
}
function compactResponse({signer,payload,full,cache,negotiation,now,monotonic}){
  const expiry=publicationExpiry(payload.token,payload,now);
  if(expiry===null||expiry<payload.expiresAt)throw Object.assign(Error('MEDIA_CREDENTIALS_UNAVAILABLE'),{code:'MEDIA_CREDENTIALS_UNAVAILABLE'});
  const digest=credentialDigest(payload,full.keyId),same=cache?.digest===digest;
  const deadline=same?Math.min(cache.deadline,monotonic+expiry-now):monotonic+expiry-now;
  if(deadline<monotonic+payload.expiresAt-now)throw Object.assign(Error('MEDIA_CREDENTIALS_UNAVAILABLE'),{code:'MEDIA_CREDENTIALS_UNAVAILABLE'});
  const next=Object.freeze({digest,keyId:full.keyId,expiresAt:expiry,deadline});
  if(!same||!compactNegotiation(negotiation)||negotiation.credentialDigest!==digest)return {envelope:full,cache:next};
  return {envelope:signer.sign({schema:1,purpose:'media_renewal',context:BINDING.map(key=>payload[key]),publisherId:payload.publisherId,sequence:payload.sequence,credentialDigest:digest,sourceFresh:payload.sourceFresh,frame:payload.frame,issuedAt:payload.issuedAt,expiresAt:payload.expiresAt}),cache:next};
}
module.exports={compactNegotiation,credentialDigest,publicationExpiry,compactResponse};
