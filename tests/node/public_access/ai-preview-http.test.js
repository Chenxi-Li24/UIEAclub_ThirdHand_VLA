'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createCloudApi}=require('../../../services/cloud-api/src/server');
const {createAiPreviewService}=require('../../../services/cloud-api/src/ai-preview');
const origin='https://thirdhand.example.invalid';
const body={message:'Hello',history:[],joints:null,gripper:null};
const reply={reply:'Hello from the model assistant.',joints:null,gripper:null,mode:'preview-only'};
async function fixture(t,previewAi){
 const sessions={resolveSession:async req=>{
  const mode=req.headers.cookie;if(!mode)return null;
  return {userId:'http-user',sessionId:'http-session',role:mode==='observe'?'observer':'admin',mode:mode==='observe'?'observe':'admin',mfaVerifiedAt:mode==='admin'?new Date():null,csrfToken:'fixture'};
 },verifyCsrf:req=>req.headers['x-csrf-token']==='fixture'};
 const pool={query:async()=>({rows:[{displayName:'用户原名',locale:'zh-CN',layoutId:'classic',themeId:'dark',revision:3}]})};
 const server=createCloudApi({publicOrigin:origin,sessions,previewAi,pool});await new Promise(r=>server.listen(0,'127.0.0.1',r));
 t.after(()=>new Promise(r=>{server.closeAllConnections();server.close(r);}));
 return (path,options={})=>fetch(`http://127.0.0.1:${server.address().port}`+path,options);
}
const options=(headers={})=>({method:'POST',headers:{origin,'content-type':'application/json',cookie:'admin','x-csrf-token':'fixture',...headers},body:JSON.stringify(body)});
test('real middleware denies anonymous, Observer, missing MFA, bad Origin and CSRF before shared AI',async t=>{
 const calls=[];const request=await fixture(t,{chat:async(...args)=>{calls.push(args);return reply;}});
 for(const [headers,status]of [[{cookie:''},401],[{cookie:'observe'},403],[{cookie:'no-mfa'},403],[{origin:'https://other.invalid'},403],[{'x-csrf-token':''},403],[{'sec-fetch-site':'cross-site'},403]]){
  assert.equal((await request('/api/v1/ai/preview',options(headers))).status,status);
 }
 assert.equal(calls.length,0);
 const result=await request('/api/v1/ai/preview',options());assert.equal(result.status,200);assert.deepEqual(await result.json(),reply);assert.deepEqual(calls,[[body,'http-user']]);
 const wrong=await request('/api/v1/ai/preview',{headers:{cookie:'admin'}});assert.equal(wrong.status,405);assert.equal(wrong.headers.get('allow'),'POST');
 for(const path of ['/ws','/execution','/execution/run','/voice','/voice/chat','/vision','/api/v1/ai/preview/execute','/api/v1/voice'])assert.equal((await request(path,options())).status,404);
 assert.equal(calls.length,1);
});
test('Guest and authenticated handlers consume the exact same provider quota instance',async t=>{
 let providerCalls=0;
 const service=createAiPreviewService({env:{GUEST_AI_API_KEY:'fixture-only'},fetchImpl:async()=>{providerCalls++;return {ok:true,json:async()=>({content:[{type:'text',text:JSON.stringify(reply)}]})};}});
 const request=await fixture(t,service);
 // Ten authenticated calls plus 110 distinct public clients exhaust one hourly pool.
 for(let i=0;i<10;i++)assert.equal((await request('/api/v1/ai/preview',options())).status,200);
 for(let i=0;i<110;i++)assert.equal((await request('/guest-ai/chat',options({'x-real-ip':`10.1.0.${i+1}`}))).status,200);
 assert.equal(providerCalls,120);
 assert.equal((await request('/api/v1/ai/preview',options())).status,429);
 assert.equal((await request('/guest-ai/chat',options({'x-real-ip':'10.2.0.1'}))).status,429);assert.equal(providerCalls,120);
});
test('presenter asset is protected for authenticated pages and explicitly public for Guest',async t=>{
 const request=await fixture(t,{chat:async()=>reply});
 assert.equal((await request('/control-assets/js/ai-preview-chat.js')).status,401);
 assert.equal((await request('/control-assets/js/ai-preview-chat.js',{headers:{cookie:'admin'}})).status,200);
 assert.equal((await request('/guest-assets/js/ai-preview-chat.js')).status,200);
 const control=await request('/control',{headers:{cookie:'admin'}});assert.equal(control.status,200);const protectedHtml=await control.text();assert.match(protectedHtml,/<html lang="en"/);assert.match(protectedHtml,/control-assets\/v[a-f0-9]{32}\/js\/ai-preview-chat.js/);
 assert.match(protectedHtml,/data-layout="classic"/);assert.match(protectedHtml,/Opening workspace…/);
 const html=await (await request('/guest')).text();assert.match(html,/guest-assets\/js\/ai-preview-chat.js/);
});
