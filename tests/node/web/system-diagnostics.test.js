const test = require('node:test');
const assert = require('node:assert/strict');
const { createSystemDiagnostics } = require('../../../apps/web/src/system-diagnostics');
test('SDK requires fresh feedback, service checks report actual reachability', async () => {
 let state={connected:true,stateFresh:false};
 const check=createSystemDiagnostics({getRobotState:()=>state,connect:async url=>url==='ai',voiceUrl:'ai',visionUrl:'vision'});
 assert.equal((await check('sdk')).status,'failed');state.stateFresh=true;assert.equal((await check('sdk')).status,'passed');
 assert.equal((await check('ai')).status,'passed');assert.equal((await check('vision')).status,'failed');
});
test('Wi-Fi distinguishes connected, absent, disconnected and unavailable',async()=>{
 for(const [stdout,status] of [['wifi:connected\nethernet:connected','passed'],['ethernet:connected','skipped'],['wifi:disconnected','warning']]){
  const check=createSystemDiagnostics({platform:'linux',execute:async()=>({stdout})});assert.equal((await check('wifi')).status,status);
 }
 const check=createSystemDiagnostics({platform:'linux',execute:async()=>{throw Error('missing');},interfaces:()=>({lo:[{internal:true}]})});
 assert.equal((await check('wifi')).status,'unknown');assert.equal((await check('network')).status,'failed');assert.equal((await check('invalid')).status,'unknown');
});
