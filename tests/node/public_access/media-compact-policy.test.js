'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {randomUUID,randomBytes,generateKeyPairSync,createHash,createHmac,verify}=require('node:crypto');
const {createMediaService}=require('../../../services/cloud-api/src/media/policy');
const {createEnvelopeSigner}=require('../../../services/device-relay/src/envelope');

const BINDING=['deviceId','bootId','executorEpoch','connectionId','certificateId'];
function digest(p){return createHash('sha256').update(JSON.stringify(['thirdhand-media-credentials-v1',p.keyId,...BINDING.map(k=>p[k]),p.publisherId,p.room,p.identity,p.token])).digest('base64url');}
function payload(envelope,key){assert.ok(verify(null,Buffer.from(envelope.payloadBase64url,'base64url'),key,Buffer.from(envelope.signatureBase64url,'base64url')),'Response signature must authenticate its exact bytes');return JSON.parse(Buffer.from(envelope.payloadBase64url,'base64url'));}
function fixture(t,{bound=false,keyLength=20,jwtTtl=30}={}){
  const clock={value:Date.now(),mono:0,now(){return this.value;},monotonic(){return this.mono;}};
  const context={deviceId:randomUUID(),bootId:randomUUID(),executorEpoch:bound?randomUUID():null,connectionId:randomUUID(),certificateId:randomUUID()};
  const events=new EventEmitter(),devices={events,get:()=>context},sessions={events:new EventEmitter(),resolveSession:async r=>r.current};
  const key=generateKeyPairSync('ed25519');let keyId='k'.repeat(keyLength),tokenCount=0;
  const secret=randomBytes(32),provider={async ensureRoom(){},async publisherToken({identity,room}){
    const encoded=Buffer.from(JSON.stringify({sub:identity,iss:'test-media',nbf:Math.floor(clock.value/1000),exp:Math.floor(clock.value/1000)+jwtTtl,metadata:String(++tokenCount),video:{room,roomJoin:true,canPublish:true,canSubscribe:false,canPublishData:false,canUpdateOwnMetadata:false,canPublishSources:['camera']}})).toString('base64url');
    const value=Buffer.from(JSON.stringify({alg:'HS256',typ:'JWT'})).toString('base64url')+'.'+encoded;
    return value+'.'+createHmac('sha256',secret).update(value).digest('base64url');
  },async viewToken(){return 'test-view-only';},async removeParticipant(){}};
  const signer={sign:value=>createEnvelopeSigner({keyId,privateKey:key.privateKey}).sign(value)};
  const service=createMediaService({sessions,devices,provider,signer,clock,startTimer:false});t.after(()=>service.close());
  const publisherId=randomUUID();let sequence=0;
  const report=(negotiation,frame=null)=>service.acceptPublisher(context,{publisherId,sequence:++sequence,frame},negotiation);
  const advance=milliseconds=>{clock.value+=milliseconds;clock.mono+=milliseconds;};
  return {clock,context,key,devices,sessions,service,provider,signer,publisherId,report,advance,payload:e=>payload(e,key.publicKey),rotateKey(){keyId='n'.repeat(keyLength);}};
}

test('compact negotiation first returns a full signed grant; matching cache gets a complete bound signed renewal',async t=>{
  const f=fixture(t,{bound:true,keyLength:48}),options={format:'compact-v1',credentialDigest:null};
  const first=f.payload(await f.report(options));assert.equal(first.purpose,'media_publish');
  const hint=digest(first),frame={frameId:'9'.repeat(19),capturedAtUs:'9'.repeat(19),clockQuality:'synchronized',uncertaintyMs:60000};
  const envelope=await f.service.acceptPublisher(f.context,{publisherId:f.publisherId,sequence:Number.MAX_SAFE_INTEGER,frame},{format:'compact-v1',credentialDigest:hint});
  const next=f.payload(envelope);assert.equal(next.purpose,'media_renewal');
  assert.deepEqual(next.context,BINDING.map(k=>f.context[k]));assert.equal(next.publisherId,f.publisherId);assert.equal(next.sequence,Number.MAX_SAFE_INTEGER);
  assert.equal(next.credentialDigest,hint);assert.equal(next.expiresAt-next.issuedAt,950);assert.deepEqual(next.frame,frame);
  for(const name of ['room','identity','token'])assert.equal(Object.hasOwn(next,name),false);
  const bytes=Buffer.byteLength(JSON.stringify({envelope}));assert.ok(bytes+181+22<1300,'Worst bound response must stay below 1300 assumed wire bytes');
});

test('legacy, unsupported version and cache miss responses remain full',async t=>{
  const f=fixture(t),first=f.payload(await f.report());assert.equal(first.purpose,'media_publish');
  assert.equal(f.payload(await f.report({format:'future-v2',credentialDigest:digest(first)})).purpose,'media_publish');
  const negotiated=f.payload(await f.report({format:'compact-v1',credentialDigest:null}));
  assert.equal(f.payload(await f.report({format:'compact-v1',credentialDigest:'A'.repeat(43)})).purpose,'media_publish');
  assert.equal(f.payload(await f.report({format:'compact-v1',credentialDigest:digest(negotiated)})).purpose,'media_renewal');
});

test('credential or signing-key rotation requires a full response, and near-expiry credentials are never extended',async t=>{
  const f=fixture(t),first=f.payload(await f.report({format:'compact-v1',credentialDigest:null}));let hint=digest(first),sawRefresh=false;
  for(let i=0;i<100;i++){
    f.advance(200);const next=f.payload(await f.report({format:'compact-v1',credentialDigest:hint}));
    if(next.purpose==='media_publish'){assert.ok(next.token!==first.token,'Fresh credentials must be returned in full');hint=digest(next);sawRefresh=true;}
    else assert.equal(next.credentialDigest,hint);
  }
  assert.equal(sawRefresh,true);f.rotateKey();
  assert.equal(f.payload(await f.report({format:'compact-v1',credentialDigest:hint})).purpose,'media_publish');
});

test('negotiated publication expiry, disconnect, replay and revocation terminate cached renewal authority',async t=>{
  for(const failure of ['expired','disconnected','replay','revoked']){
    const f=fixture(t),first=f.payload(await f.report({format:'compact-v1',credentialDigest:null})),options={format:'compact-v1',credentialDigest:digest(first)};
    if(failure==='expired')f.advance(950);
    if(failure==='disconnected')f.devices.events.emit('disconnected',f.context);
    if(failure==='revoked')f.sessions.events.emit('unavailable');
    if(failure==='replay')await assert.rejects(f.service.acceptPublisher(f.context,{publisherId:f.publisherId,sequence:1,frame:null},options));
    await assert.rejects(f.report(options));
    await assert.rejects(f.report());
  }
});

test('a JWT nearing expiry is refreshed in full before a short renewal could outlive it',async t=>{
  const f=fixture(t,{jwtTtl:2});f.clock.value=Math.floor(f.clock.value/1000)*1000;
  const first=f.payload(await f.report({format:'compact-v1',credentialDigest:null})),hint=digest(first);let refreshed=false;
  for(let i=0;i<6;i++){f.advance(200);const next=f.payload(await f.report({format:'compact-v1',credentialDigest:hint}));if(next.purpose==='media_publish'){assert.ok(next.token!==first.token,'Impending expiry must refresh credentials');refreshed=true;break;}}
  assert.equal(refreshed,true);
});

test('a delayed credential refresh cannot revive a publication whose previous lease expired during the await',async t=>{
  const f=fixture(t),first=f.payload(await f.report({format:'compact-v1',credentialDigest:null})),options={format:'compact-v1',credentialDigest:digest(first)};
  for(let i=0;i<99;i++){f.advance(200);await f.report(options);}
  let release,entered;const blocked=new Promise(resolve=>release=resolve),started=new Promise(resolve=>entered=resolve),original=f.provider.publisherToken;
  f.provider.publisherToken=async value=>{entered();await blocked;return original(value);};
  f.advance(200);const pending=f.report(options);await started;f.advance(900);release();
  await assert.rejects(pending,{code:'MEDIA_LEASE_EXPIRED'});
  assert.equal(f.service.status(f.context.deviceId).available,false);
  await assert.rejects(f.report());
});

test('a first grant cannot commit after signing consumes its own signed lifetime',async t=>{
  const f=fixture(t),original=f.signer.sign;
  f.signer.sign=value=>{const envelope=original(value);f.advance(1000);return envelope;};
  await assert.rejects(f.report({format:'compact-v1',credentialDigest:null}),{code:'MEDIA_LEASE_EXPIRED'});
  assert.equal(f.service.status(f.context.deviceId).available,false);
});

test('a pause after sampling UTC cannot move the cloud publication deadline past its signature',async t=>{
  const f=fixture(t),base=f.clock.value;let calls=0;
  f.clock.now=function(){const value=this.value;if(++calls===3)f.advance(200);return value;};
  const first=f.payload(await f.report({format:'compact-v1',credentialDigest:null}));
  f.clock.value=first.expiresAt+1;f.clock.mono=first.expiresAt+1-base;
  assert.equal(f.service.status(f.context.deviceId).available,false);
});

test('a pause in the final UTC sample cannot cross the previous publication deadline unnoticed',async t=>{
  const f=fixture(t),first=f.payload(await f.report({format:'compact-v1',credentialDigest:null}));
  f.advance(200);let calls=0;
  f.clock.now=function(){const value=this.value;if(++calls===4)f.advance(800);return value;};
  await assert.rejects(f.report({format:'compact-v1',credentialDigest:digest(first)}),{code:'MEDIA_LEASE_EXPIRED'});
  assert.equal(f.service.status(f.context.deviceId).available,false);
});
