'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),{EventEmitter}=require('node:events');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {createWebGateway}=require('../../../apps/web/src/server');
class Controller extends EventEmitter{
 constructor(){super();this.s={type:'grasp.status',active:false,phase:'idle',sessionId:null,gripOffsetM:0.06};this.starts=0;}
 status(){return {...this.s};}async start(id,request){if(this.request===request)return this.status();this.starts++;this.request=request;this.s={...this.s,stableId:id,active:true,phase:'depth_acquiring',sessionId:'s1'};this.emit('status',this.s);return this.status();}
 async stop(id){this.s={...this.s,active:false,phase:'stopped'};return this.status();}async close(){}
}
async function setup(t,controller){
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'grasp-gateway-'));const proxy={getRobotState:()=>null,broadcast:()=>{},attach:()=>{},close:()=>{},setGraspInterlock:fn=>proxy.interlock=fn};
 const visionProxy={attach(){},close(){}};
 const gateway=createWebGateway({host:'127.0.0.1',port:0,readyFile:path.join(temp,'ready'),robotProxy:proxy,
  visionProxy,voiceProxy:{attach(){},close(){}},coordinator:{on(){},status(){return {active:false};},async close(){}},graspController:controller,env:{}});
 const address=await gateway.start();t.after(async()=>{await gateway.close();fs.rmSync(temp,{recursive:true,force:true});});
 return {url:`http://127.0.0.1:${address.port}`,proxy,visionProxy};
}
const post=(url,p,body,origin)=>fetch(url+p,{method:'POST',headers:{'content-type':'application/json',...(origin?{origin}: {})},body:JSON.stringify(body)});
test('grasp routes are explicitly unavailable without experiment controller',async t=>{
 const {url}=await setup(t);const r=await post(url,'/api/grasp/start',{stableId:2,requestId:'r1'});assert.equal(r.status,503);
 const s=await (await fetch(url+'/api/grasp/status')).json();assert.equal(s.active,false);
});
test('selection release and vision websocket mutations are locked during a grasp',async t=>{
 const c=new Controller(),{url,visionProxy}=await setup(t,c);await post(url,'/api/grasp/start',{stableId:2,requestId:'lock-target'});
 for(const route of ['/api/vision/select','/api/vision/release'])assert.equal((await post(url,route,{stableId:1})).status,409);
 const replies=[],browser={OPEN:1,readyState:1,send:raw=>replies.push(JSON.parse(raw))};
 assert.equal(visionProxy.canForward(browser),false);assert.equal(replies[0].code,'grasp_active');
});
test('an existing queued or language executor prevents acquiring grasp ownership',async t=>{
 const c=new Controller(),{url,proxy}=await setup(t,c);proxy.hasActiveControl=()=>true;
 const r=await post(url,'/api/grasp/start',{stableId:2,requestId:'busy'});assert.equal(r.status,409);assert.equal(c.starts,0);
});
test('one start exposes 60mm runtime and installs active motion ownership',async t=>{
 const c=new Controller(),{url,proxy}=await setup(t,c);
 const r=await post(url,'/api/grasp/start',{stableId:2,requestId:'r1'});assert.equal(r.status,202);
 assert.equal((await r.json()).sessionId,'s1');assert.equal(proxy.interlock().active,true);
 await post(url,'/api/grasp/start',{stableId:2,requestId:'r1'});assert.equal(c.starts,1);
 const runtime=await (await fetch(url+'/api/runtime-config')).json();assert.equal(runtime.grasp.gripOffsetM,0.06);assert.equal(runtime.grasp.legacyGraspEnabled,false);
});
test('foreign origins and extra motion fields cannot start an autonomous grasp',async t=>{
 const c=new Controller(),{url}=await setup(t,c);
 assert.equal((await post(url,'/api/grasp/start',{stableId:2,requestId:'r1'},'https://attacker.invalid')).status,403);
 assert.equal((await post(url,'/api/grasp/start',{stableId:2,requestId:'r1',offset:0.3})).status,400);assert.equal(c.starts,0);
});
test('separate depth start is rejected while a grasp owns the arm',async t=>{
 const c=new Controller(),{url}=await setup(t,c);await post(url,'/api/grasp/start',{stableId:2,requestId:'r1'});
 assert.equal((await post(url,'/api/active-depth/start',{stableId:2})).status,409);
 assert.equal((await post(url,'/api/grasp/stop',{sessionId:'s1'})).status,200);
});
