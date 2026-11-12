const test=require('node:test');
const assert=require('node:assert/strict');
const {createSystemReady,prepareSystem}=require('../../../apps/web/src/system-ready');
const req=(method='GET',overrides={})=>({method,socket:{remoteAddress:'127.0.0.1'},headers:{host:'localhost:9983',origin:'http://localhost:9983','x-thirdhand-action':'prepare'},...overrides});
async function call(handler,request){let code,body;await handler(request,{writeHead(c){code=c;},end(b){body=JSON.parse(b);}},'/api/system-ready');return {code,body};}
test('preparation requires local Linux origin, rejects busy and duplicate requests',async()=>{
 let calls=0,resolve;const handler=createSystemReady({platform:'linux',prepare:()=>{calls++;return new Promise(r=>resolve=r);}});
 assert.equal((await call(handler,req('POST',{headers:{host:'evil.test'}}))).code,403);
 assert.equal((await call(handler,req('POST',{socket:{remoteAddress:'192.168.1.2'}}))).code,403);
 assert.equal((await call(handler,req('POST'))).code,202);
 assert.equal((await call(handler,req('POST'))).code,409);assert.equal(calls,1);
 resolve({overall:'ready',services:{robot:{state:'ready'}}});await new Promise(setImmediate);
 assert.equal((await call(handler,req())).body.overall,'ready');
 assert.equal((await call(createSystemReady({platform:'linux',busy:()=>true}),req('POST'))).code,409);
 assert.equal((await call(createSystemReady({platform:'win32'}),req())).body.available,false);
});
test('preparation failures are reported without unhandled rejection',async()=>{
 const handler=createSystemReady({platform:'linux',prepare:async()=>{throw Error('failed');}});
 await call(handler,req('POST'));await new Promise(setImmediate);assert.equal((await call(handler,req())).body.overall,'failed');
});
test('full recovery is refused; normal preparation excludes the serving web gateway',async()=>{
 let ensured=0,services;
 const load=()=>({can:{},services:[{id:'robot',enabled:true},{id:'speech',enabled:true},{id:'web',enabled:true}]});
 class Can{async inspect(){return {exists:true,ready:false};}async ensure(){ensured++;return {state:'ready'};}}
 class Supervisor{constructor(options){services=options.services;}async ensureAll(){return services.map(s=>({...s,state:'ready'}));}}
 const options={load,Can,Supervisor,probe:async()=>({ready:true})};
 assert.equal((await prepareSystem(options)).reason,'host_recovery_required');assert.equal(ensured,0);
 const result=await prepareSystem({...options,probe:async()=>({ready:false})});
 assert.equal(result.overall,'ready');assert.deepEqual(services.map(s=>s.id),['robot','speech']);
});
