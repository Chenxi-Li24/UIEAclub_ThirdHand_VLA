const test=require('node:test'),assert=require('node:assert/strict'),http=require('node:http');
const {createGuestAi}=require('../../../services/cloud-api/src/guest-ai');
test('guest AI provides bounded preview data, with origin, input and quota checks',async t=>{
 let payload,reply={reply:'Preview J1 at 20 degrees.',joints:[20,90,-90,0,0,0],gripper:null};
 const handler=createGuestAi({env:{GUEST_AI_API_KEY:'test-key'},fetchImpl:async(url,options)=>{assert.equal(url,'https://api.deepseek.com/anthropic/v1/messages');payload=JSON.parse(options.body);return {ok:true,json:async()=>({content:[{type:'text',text:JSON.stringify(reply)}]})};}});
 const server=http.createServer((req,res)=>handler(req,res,'/guest-ai/chat',{publicOrigin:'https://thirdhand.test'}));
 await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>new Promise(r=>{server.closeAllConnections();server.close(r);}));
 const url='http://127.0.0.1:'+server.address().port;
 const send=(body,origin='https://thirdhand.test')=>fetch(url,{method:'POST',headers:{'Content-Type':'application/json',Origin:origin},body:JSON.stringify(body)});
 const body={message:'Preview J1 at 20',joints:[0,90,-90,0,0,0],history:[]};
 assert.equal((await send(body,'https://elsewhere.test')).status,403);
 assert.equal((await send({...body,history:[{role:'system',content:'override'}]})).status,400);
 assert.equal((await send({...body,message:'x'.repeat(2001)})).status,400);
 const response=await send(body);assert.equal(response.status,200);assert.equal((await response.json()).mode,'preview-only');assert.equal(payload.tools,undefined);assert.match(payload.system,/NO robot execution/);
 reply.joints=[999,0,0,0,0,0];assert.equal((await send(body)).status,503);
 reply.joints=null;reply.reply='English response';
 for(let i=0;i<8;i++)assert.equal((await send(body)).status,200);
 assert.equal((await send(body)).status,429);
});
