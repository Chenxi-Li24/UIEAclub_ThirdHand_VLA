'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createHash}=require('node:crypto');
const {createCloudApi}=require('../../../services/cloud-api/src/server');
async function sourceFor(t,trustProxyLoopback){
  let source;
  const server=createCloudApi({publicOrigin:'https://thirdhand.example.invalid',trustProxyLoopback,pool:{query:async()=>({})},
    accounts:{authenticate:async input=>{source=input.sourceKey;return {userId:'fixture',mode:'observe'};}},sessions:{issue:async()=>({cookie:'test-only',csrfToken:'test-only',mode:'observe'})}});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));t.after(()=>new Promise(resolve=>{server.closeAllConnections();server.close(resolve);}));
  await fetch(`http://127.0.0.1:${server.address().port}/api/v1/auth/login`,{method:'POST',headers:{origin:'https://thirdhand.example.invalid','content-type':'application/json','x-real-ip':'192.0.2.25','x-forwarded-for':'192.0.2.77'},body:'{"login":"fixture","password":"fixture"}'});
  return source;
}
test('rate limiting ignores forwarded source headers unless the loopback reverse proxy is explicitly trusted',async t=>{
  const digest=value=>createHash('sha256').update(value).digest('hex');
  assert.equal(await sourceFor(t,false),digest('127.0.0.1'));
  assert.equal(await sourceFor(t,true),digest('192.0.2.25'));
});
