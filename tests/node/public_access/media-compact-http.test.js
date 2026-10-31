'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path'),https=require('node:https');
const {execFile,spawn}=require('node:child_process'),{promisify}=require('node:util'),{once,EventEmitter}=require('node:events');
const {X509Certificate,randomUUID,randomBytes,generateKeyPairSync,sign,createHash}=require('node:crypto');
const {WebSocket}=require('ws');
const {createDeviceRelay}=require('../../../services/device-relay/src/server');
const {createEnvelopeSigner}=require('../../../services/device-relay/src/envelope');
const {createMediaService}=require('../../../services/cloud-api/src/media/policy');
const {createLiveKitProvider}=require('../../../services/cloud-api/src/media/livekit-provider');
const python=process.env.EDGE_TEST_PYTHON||'python',run=promisify(execFile),BINDING=['deviceId','bootId','executorEpoch','connectionId','certificateId'];
const decode=e=>JSON.parse(Buffer.from(e.payloadBase64url,'base64url'));
const digest=p=>createHash('sha256').update(JSON.stringify(['thirdhand-media-credentials-v1',p.keyId,...BINDING.map(k=>p[k]),p.publisherId,p.room,p.identity,p.token])).digest('base64url');

async function fixture(t){
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'thirdhand-compact-'));
  t.after(async()=>{const target=path.resolve(directory);assert.ok(path.dirname(target)===path.resolve(os.tmpdir())&&path.basename(target).startsWith('thirdhand-compact-'));await fs.rm(target,{recursive:true,force:true,maxRetries:5,retryDelay:50});});
  await run(python,['tests/python/edge_agent/pki_fixture.py',directory]);
  const pem=name=>fs.readFile(path.join(directory,name));
  const certificate=new X509Certificate(await pem('device.pem')),identity={id:randomUUID(),certificateId:randomUUID(),fingerprint:certificate.fingerprint256.replaceAll(':','').toLowerCase(),publicKey:certificate.publicKey,remoteControlEnabled:false};
  const key=generateKeyPairSync('ed25519'),signer=createEnvelopeSigner({keyId:'compact-media-v1',privateKey:key.privateKey}),seen=[];
  let media;const relay=createDeviceRelay({store:{resolveCertificate:async value=>value===identity.fingerprint?identity:null},tls:{key:await pem('server.key'),cert:await pem('server.pem'),ca:await pem('ca.pem')},mediaPublisher:(context,value,negotiation)=>{seen.push(negotiation);return media.acceptPublisher(context,value,negotiation);}});
  const provider=createLiveKitProvider({apiKey:'test-media',apiSecret:randomBytes(32).toString('hex'),host:'http://127.0.0.1:7880'});provider.ensureRoom=async()=>{};
  media=createMediaService({sessions:{events:new EventEmitter(),resolveSession:async()=>null},devices:relay.devices,provider,signer,startTimer:false});
  await new Promise(resolve=>relay.server.listen(0,'127.0.0.1',resolve));
  const clientTls={key:await pem('device.key'),cert:await pem('device.pem'),ca:await pem('ca.pem')};
  const agent=new https.Agent({...clientTls,keepAlive:true,maxSockets:1});
  t.after(async()=>{agent.destroy();await media.close();await relay.close();});
  const url=`wss://127.0.0.1:${relay.server.address().port}/edge/v1/connect`,socket=new WebSocket(url,clientTls);await once(socket,'open');
  const challenge=once(socket,'message');socket.send(JSON.stringify({type:'hello',protocol:1,deviceId:identity.id,bootId:randomUUID(),executorEpoch:null,agentVersion:'0.1.0',capabilities:['probe']}));
  const value=JSON.parse((await challenge)[0]),welcome=once(socket,'message');socket.send(JSON.stringify({type:'proof',signatureBase64url:sign(null,Buffer.from(value.payloadBase64url,'base64url'),clientTls.key).toString('base64url')}));
  const context=JSON.parse((await welcome)[0]).context,publisherId=randomUUID();let sequence=0;
  async function submit(headers={}){
    const now=Date.now(),raw=Buffer.from(JSON.stringify({schema:1,purpose:'media_report',context,publisherId,sequence:++sequence,frame:null,issuedAt:now,expiresAt:now+950}));
    const body=Buffer.from(JSON.stringify({payloadBase64url:raw.toString('base64url'),signatureBase64url:sign(null,raw,clientTls.key).toString('base64url')}));
    return new Promise((resolve,reject)=>{const req=https.request(url.replace('wss:','https:').replace('/edge/v1/connect','/edge/v1/media-grant'),{method:'POST',agent,headers:{'content-type':'application/json','content-length':body.length,...headers}},res=>{const data=[];res.on('data',chunk=>data.push(chunk));res.on('end',()=>{const rawBody=Buffer.concat(data);resolve({status:res.statusCode,body:JSON.parse(rawBody),bodyBytes:rawBody.length});});});req.on('error',reject);req.end(body);});
  }
  return {submit,seen,context,key};
}

test('only exact compact headers reach mTLS media negotiation; unsupported or missing versions remain full',async t=>{
  const f=await fixture(t),legacy=await f.submit();assert.equal(legacy.status,200);assert.equal(decode(legacy.body.envelope).purpose,'media_publish');
  const first=await f.submit({'x-thirdhand-media-grant':'compact-v1'});assert.equal(first.status,200);assert.equal(decode(first.body.envelope).purpose,'media_publish');
  assert.deepEqual(f.seen.at(-1),{format:'compact-v1',credentialDigest:null});
  const next=await f.submit({'x-thirdhand-media-grant':'compact-v1','x-thirdhand-media-credentials':digest(decode(first.body.envelope))});
  assert.equal(next.status,200);assert.equal(decode(next.body.envelope).purpose,'media_renewal');assert.ok(next.bodyBytes<first.bodyBytes);
  for(const headers of [{'x-thirdhand-media-grant':'compact-v1, compact-v1'},{'x-thirdhand-media-grant':'compact-v1','x-thirdhand-media-credentials':'invalid'},{'x-thirdhand-media-grant':'compact-v1','x-thirdhand-media-credentials':'B'.repeat(43)},{'x-thirdhand-media-credentials':'A'.repeat(43)}]){const before=f.seen.length;assert.equal((await f.submit(headers)).status,403);assert.equal(f.seen.length,before);}
  const unsupported=await f.submit({'x-thirdhand-media-grant':'future-v2'});assert.equal(unsupported.status,200);assert.equal(decode(unsupported.body.envelope).purpose,'media_publish');
  assert.equal((await f.submit({'x-thirdhand-media-grant':'compact-v1',origin:'https://thirdhand.invalid'})).status,403);
});

test('real LiveKit full grant and compact mTLS renewal verify across Node and Python without altering signed bytes',async t=>{
  const f=await fixture(t),full=await f.submit({'x-thirdhand-media-grant':'compact-v1'}),p=decode(full.body.envelope);
  const renewal=await f.submit({'x-thirdhand-media-grant':'compact-v1','x-thirdhand-media-credentials':digest(p)});
  assert.equal(decode(renewal.body.envelope).purpose,'media_renewal');
  const script="import sys,json,base64\nfrom thirdhand_edge.media_publisher import MediaLeaseGate\nv=json.load(sys.stdin)\np=json.loads(base64.urlsafe_b64decode(v['full']['payloadBase64url']+'=='))\ng=MediaLeaseGate(publisher_id=p['publisherId'],trusted_keys={v['full']['keyId']:v['publicKey']},wall_ms=lambda:p['issuedAt'],monotonic=lambda:1.0,allow_compact=True)\na=g.accept(v['full'],v['context'],expected_sequence=p['sequence'])\nr=json.loads(base64.urlsafe_b64decode(v['renewal']['payloadBase64url']+'=='))\nb=g.accept(v['renewal'],v['context'],expected_sequence=r['sequence'])\nif a['token']!=b['token'] or a['room']!=b['room'] or a['identity']!=b['identity'] or g.credential_hint()['digest']!=r['credentialDigest']: raise SystemExit(2)\nprint('compact-cross-language-verified')";
  const child=spawn(python,['-c',script],{env:{...process.env,PYTHONPATH:path.resolve('services/edge-agent/src')},stdio:['pipe','pipe','pipe']});let stdout='';child.stdout.on('data',data=>stdout+=data);child.stderr.resume();
  const exited=once(child,'exit');child.stdin.end(JSON.stringify({full:full.body.envelope,renewal:renewal.body.envelope,context:f.context,publicKey:f.key.publicKey.export({type:'spki',format:'pem'})}));
  const [code]=await exited;assert.equal(code,0,'Compact cross-language validation failed (private vectors suppressed)');assert.equal(stdout.trim(),'compact-cross-language-verified');
});
