'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{EventEmitter}=require('node:events');
const WebSocket=require('ws'),{WebSocketServer}=require('ws');
const {createWebGateway}=require('../../../apps/web/src/server');
function wait(socket,predicate,send){return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{socket.off('message',on);reject(new Error('message timeout'));},1500);const on=b=>{const m=JSON.parse(b);if(predicate(m)){clearTimeout(timer);socket.off('message',on);resolve(m);}};socket.on('message',on);send();});}
test('active owner blocks competing motion but preserves stop and owner forwarding',async t=>{
 const received=[],upstream=new WebSocketServer({port:0});await new Promise(r=>upstream.once('listening',r));
 upstream.on('connection',s=>s.on('message',b=>{const m=JSON.parse(b);received.push(m);s.send(JSON.stringify(m.type==='capability_request'?{type:'capability_response',nonce:m.nonce}:{type:'test_echo',request_id:m.request_id}));}));
 const c=new EventEmitter();c.status=()=>({active:true,sessionId:'owner',phase:'approach',gripOffsetM:0.06});c.close=async()=>{};
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'grasp-owner-'));
 const gateway=createWebGateway({host:'127.0.0.1',port:0,robotWsUrl:`ws://127.0.0.1:${upstream.address().port}/ws`,graspOwnerToken:'private-test-owner',
  readyFile:path.join(temp,'ready'),graspController:c,env:{},coordinator:{on(){},status(){return {active:false};},async close(){}}});
 const a=await gateway.start(),browser=new WebSocket(`ws://127.0.0.1:${a.port}/ws`),owner=new WebSocket(`ws://127.0.0.1:${a.port}/ws`,{headers:{'x-thirdhand-grasp-owner':'private-test-owner'}});
 await Promise.all([browser,owner].map(s=>new Promise(r=>s.once('open',r))));
 t.after(async()=>{browser.terminate();owner.terminate();await gateway.close();for(const s of upstream.clients)s.terminate();await new Promise(r=>upstream.close(r));fs.rmSync(temp,{recursive:true,force:true});});
 const rejected=await wait(browser,m=>m.type==='error',()=>browser.send(JSON.stringify({cmd:'servo',joints:[0,0,-1,0,0,0],request_id:'blocked'})));
 assert.equal(rejected.code,'grasp_active');assert.equal(received.some(m=>m.request_id==='blocked'),false);
 const forged=await wait(browser,m=>m.request_id==='forged',()=>browser.send(JSON.stringify({cmd:'gripper',position:0,source:'web-grasp:owner',request_id:'forged'})));
 assert.equal(forged.code,'grasp_active');assert.equal(received.some(m=>m.request_id==='forged'),false);
 await wait(owner,m=>m.request_id==='owned',()=>owner.send(JSON.stringify({cmd:'gripper',position:0,source:'web-grasp:owner',request_id:'owned'})));
 await wait(browser,m=>m.request_id==='stop',()=>browser.send(JSON.stringify({cmd:'software_stop',request_id:'stop'})));
 await wait(browser,m=>m.type==='capability_response'&&m.nonce==='calibration-state',()=>browser.send(JSON.stringify({type:'capability_request',schema:'thirdhand-robot-capability-v1',nonce:'calibration-state'})));
 await wait(browser,m=>m.request_id==='feedback',()=>browser.send(JSON.stringify({cmd:'get_state',request_id:'feedback'})));
 assert.equal(received.some(m=>m.request_id==='owned'),true);assert.equal(received.some(m=>m.request_id==='stop'),true);
});
test('queued and language sends recheck ownership at the actual send boundary',()=>{
 const {RobotProxy}=require('../../../apps/web/src/robot-proxy');const p=Object.create(RobotProxy.prototype),sent=[],blocked=[];
 p.graspInterlock=()=>({active:true,sessionId:'owner'});p.forwardedMotion=new Map();
 p.languageController={active:null};p.directionalController={active:null};p.sessions=new Set();
 const session={browser:{readyState:1,send:s=>blocked.push(JSON.parse(s))},upstream:{readyState:1,send:s=>sent.push(JSON.parse(s))},queue:[JSON.stringify({cmd:'servo',joints:[0,0,-1,0,0,0],request_id:'queued'})],graspOwner:false};
 p._flushQueued(session);assert.equal(sent.length,0);assert.equal(blocked[0].code,'grasp_active');
 p.languageUpstream={send:m=>{sent.push(m);return true;}};
 assert.equal(p._sendLanguageRobot({cmd:'gripper',position:1}),false);assert.equal(sent.length,0);
 p.languageController.active={requestId:'already-running'};assert.equal(p.hasActiveControl(),true);
});
