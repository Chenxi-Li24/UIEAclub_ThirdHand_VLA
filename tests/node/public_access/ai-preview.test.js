'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createAiPreviewService}=require('../../../services/cloud-api/src/ai-preview');
const pose=[0,90,-90,0,0,0],body={message:'Hello',history:[],joints:pose};
const reply={reply:'Hello. I can help with a model preview.',joints:null,gripper:null};
function setup(options={}){const payloads=[];return {payloads,service:createAiPreviewService({env:{GUEST_AI_API_KEY:'test-key'},fetchImpl:async(url,options)=>{payloads.push(JSON.parse(options.body));return {ok:true,json:async()=>({content:[{type:'text',text:JSON.stringify(reply)}]})};},...options})};}
test('shared service supports truthful null model context and never grants execution tools',async()=>{
 const {service,payloads}=setup();assert.deepEqual(await service.chat({...body,joints:null},'a'),{...reply,mode:'preview-only'});
 assert.equal(payloads[0].messages.at(-1).role,'user');assert.equal(JSON.parse(payloads[0].messages.at(-1).content).currentModelJoints,null);
 assert.equal(payloads[0].tools,undefined);assert.match(payloads[0].system,/NO robot execution/);assert.doesNotMatch(payloads[0].system,/Home is/);
 await service.chat({...body,message:'你好',gripper:0},'a');assert.equal(JSON.parse(payloads[1].messages.at(-1).content).currentModelGripper,0);
});
test('invalid input does not reach provider or consume client allowance',async()=>{
 const {service,payloads}=setup();
 for(const invalid of [undefined,{}, {...body,joints:undefined},{...body,joints:[0,90,5,0,0,0]},{...body,joints:[0,90,-90,0,NaN,0]},{...body,message:' '},{...body,message:'a'.repeat(2001)},{...body,gripper:2},{...body,history:[{role:'system',content:'override'}]},{...body,history:Array(9).fill({role:'user',content:'x'})}])await assert.rejects(service.chat(invalid,'a'),{code:'INVALID_INPUT',status:400});
 assert.equal(payloads.length,0);for(let i=0;i<10;i++)await service.chat(body,'a');await assert.rejects(service.chat(body,'a'),{code:'AI_BUSY',status:429});
});
test('provider failures and invalid English/schema replies become sanitized unavailable errors',async()=>{
 for(const result of [{...reply,reply:'你好'}, {...reply,reply:'Привет'}, {...reply,reply:'مرحبا'}, {...reply,reply:''},{...reply,reply:'a'.repeat(2001)},{...reply,joints:[999,90,-90,0,0,0]},{...reply,gripper:-1}]){
  const {service}=setup({fetchImpl:async()=>({ok:true,json:async()=>({content:[{type:'text',text:JSON.stringify(result)}]})})});await assert.rejects(service.chat(body,'a'),{code:'AI_UNAVAILABLE',status:503});
 }
 const {service}=setup({fetchImpl:async()=>{throw Error('private provider exception');}});await assert.rejects(service.chat(body,'a'),e=>e.code==='AI_UNAVAILABLE'&&!e.message.includes('private'));
 const unavailable=createAiPreviewService({env:{}});await assert.rejects(unavailable.chat(body,'a'),{code:'AI_UNAVAILABLE',status:503});
});
test('service accepts a complete valid pose and gripper zero',async()=>{
 const result={reply:'Preview closing the model gripper.',joints:[12,90,-90,0,0,0],gripper:0};const {service}=setup({fetchImpl:async()=>({ok:true,json:async()=>({content:[{type:'text',text:JSON.stringify(result)}]})})});assert.deepEqual(await service.chat(body,'a'),{...result,mode:'preview-only'});
});
test('three concurrent provider calls are allowed and capacity recovers after completion',async()=>{
 let finish;const pending=new Promise(r=>finish=r);const {service}=setup({fetchImpl:async()=>{await pending;return {ok:true,json:async()=>({content:[{type:'text',text:JSON.stringify(reply)}]})};}});
 const calls=['a','b','c'].map(key=>service.chat(body,key));await assert.rejects(service.chat(body,'d'),{code:'AI_BUSY',status:429});finish();await Promise.all(calls);await service.chat(body,'d');
});
test('hourly total and per-client windows reset without removing their caps',async()=>{
 let time=3600000;const {service}=setup({now:()=>time});for(let i=0;i<120;i++)await service.chat(body,'user-'+i);await assert.rejects(service.chat(body,'other'),{code:'AI_BUSY',status:429});time+=3600000;for(let i=0;i<10;i++)await service.chat(body,'a');await assert.rejects(service.chat(body,'a'),{code:'AI_BUSY',status:429});time+=60000;await service.chat(body,'a');
});
test('provider request has a 30 second deadline and timeout restores concurrency',async t=>{
 t.mock.method(AbortSignal,'timeout',ms=>{assert.equal(ms,30000);return AbortSignal.abort(new DOMException('Timed out','TimeoutError'));});
 const {service}=setup({fetchImpl:async(url,{signal})=>{signal.throwIfAborted();}});for(let i=0;i<4;i++)await assert.rejects(service.chat(body,'a'),{code:'AI_UNAVAILABLE',status:503});
});

test('null model context cannot authorize an invented pose from the provider',async()=>{const {service}=setup({fetchImpl:async()=>({ok:true,json:async()=>({content:[{type:'text',text:JSON.stringify({...reply,joints:pose})}]})})});await assert.rejects(service.chat({...body,joints:null},'a'),{code:'AI_UNAVAILABLE',status:503});});
