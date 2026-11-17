'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {parseHTML}=require('linkedom');
const fs=require('node:fs');
const {mountAdminControl}=require('../../../apps/web/public/js/admin-control');

test('read-only device capability never hides a lost connection authorization',()=>{
  const {document}=parseHTML('<html><body><section id="page-system"></section></body></html>');
  const stateStore={subscribe(callback){callback({devices:[{id:'device-test',name:'Lab',readOnly:true}],deviceId:null});return ()=>{};}};
  const mounted=mountAdminControl({document,view:{},identity:{role:'observer',mode:'observe'},sessionClient:{},stateStore});
  document.querySelector('option').selected=true;
  mounted.client.close('BROWSER_STALE');
  assert.equal(document.querySelector('[role="status"]').textContent,'Browser heartbeat expired. Check device state before requesting again.');
  for(const text of ['Connect SDK','Disconnect SDK','Release SDK connection'])assert.equal([...document.querySelectorAll('button')].find(b=>b.textContent===text).disabled,true);
  mounted.dispose();
});

test('background visibility explains channel closure without reconnecting or sending commands',()=>{
  const {document,window}=parseHTML('<html><body><section id="page-system"></section></body></html>');
  let requests=0,sockets=0;
  const mounted=mountAdminControl({document,view:{WebSocket:class{constructor(){sockets++;}}},identity:{role:'observer',mode:'observe'},sessionClient:{request(){requests++;}}});
  document.visibilityState='hidden';document.dispatchEvent(new window.Event('visibilitychange'));
  assert.equal(mounted.client.state().disconnectReason,'PAGE_HIDDEN');
  assert.match(document.querySelector('[role="status"]').textContent,/background.*authorization channel/);
  document.visibilityState='visible';document.dispatchEvent(new window.Event('visibilitychange'));
  assert.equal(requests,0);assert.equal(sockets,0);
  mounted.client.close('CONTROL_DISCONNECTED');
  assert.match(document.querySelector('[role="status"]').textContent,/channel was interrupted/);
  assert.doesNotMatch(document.querySelector('[role="status"]').textContent,/heartbeat expired/);
  mounted.dispose();
});

test('SDK authorization shows pending state, blocks duplicate clicks and reports device refusal',async()=>{
  const {document}=parseHTML('<html><body><section id="page-system"></section></body></html>');
  const stateStore={subscribe(callback){callback({devices:[{id:'device-test',name:'Lab',readOnly:true}],deviceId:null});return ()=>{};}};
  const mounted=mountAdminControl({document,view:{},identity:{role:'observer',mode:'observe'},sessionClient:{},stateStore});
  document.querySelector('option').selected=true;
  let reject,calls=0;
  mounted.client.acquire=()=>{calls++;return new Promise((_,fail)=>{reject=fail;});};
  const button=[...document.querySelectorAll('button')].find(b=>b.textContent==='Request SDK connection');
  button.click();button.click();await new Promise(setImmediate);
  assert.equal(calls,1);assert.equal(button.disabled,true);assert.equal(button.getAttribute('aria-busy'),'true');
  assert.match(button.textContent,/Requesting/);assert.match(document.querySelector('[role="status"]').textContent,/Request sent/);
  assert.equal(document.querySelector('select').disabled,true);
  reject(Object.assign(Error(),{code:'LEASE_UNCONFIRMED'}));await new Promise(setImmediate);
  assert.equal(button.disabled,false);assert.equal(button.hasAttribute('aria-busy'),false);
  assert.equal(document.querySelector('select').disabled,false);
  assert.match(document.querySelector('[role="status"]').textContent,/device did not accept.*not initialized/);
  assert.equal([...document.querySelectorAll('button')].find(b=>b.textContent==='Connect SDK').disabled,true);
  mounted.dispose();
});

test('SDK connection UI is available for observing sessions and never opens a socket or SDK during mount',()=>{
  for(const identity of [{role:'observer',mode:'observe'},{role:'admin',mode:'observe'},{role:'admin',mode:'admin'}]){
    const {document}=parseHTML(fs.readFileSync('apps/web/public/index.html','utf8'));
    const page=document.createElement('section');page.id='page-system';document.body.append(page);
    let sockets=0,requests=0;
    const view={WebSocket:class{constructor(){sockets++;}},crypto:{randomUUID:()=> 'test'},location:{protocol:'https:',host:'example.invalid'}};
    const mounted=mountAdminControl({document,view,identity,sessionClient:{async request(){requests++;}},arm:{getJointAngles:()=>[0,90,-90,0,0,0]}});
    const panel=document.getElementById('cloud-live-control');
    assert.equal(!!panel,true);assert.equal(sockets,0);assert.equal(requests,0);
    if(panel){const connect=[...panel.querySelectorAll('button')].find(button=>button.textContent==='Connect SDK');assert.equal(connect.disabled,true);assert.equal(panel.textContent.includes('Send model pose to robot'),false);}
    mounted.dispose();
  }
});

test('administrator read-only connection is located exclusively in Devices & diagnostics',()=>{
  const {document}=parseHTML(fs.readFileSync('apps/web/public/index.html','utf8'));
  const page=document.createElement('section');page.id='page-system';document.body.append(page);
  const log=document.createElement('div');log.id='log-panel';page.append(log);
  const mounted=mountAdminControl({document,view:{confirm:()=>true},identity:{role:'admin',mode:'admin'},sessionClient:{},arm:{}});
  try{assert.equal(document.getElementById('cloud-live-control').parentElement.id,'page-system');assert.equal(log.previousElementSibling.id,'cloud-live-control');}
  finally{mounted.dispose();}
});

test('failed and successful SDK requests both settle pending state and refresh measured feedback',async()=>{
  for(const fails of [true,false]){
    const {document}=parseHTML('<html><body><section id="page-system"></section></body></html>');
    const attempt={},calls=[];
    const stateStore={subscribe(){return ()=>{};},connecting(){calls.push('pending');return attempt;},connectionSettled(value){assert.equal(value,attempt);calls.push('settled');},async refresh(){calls.push('refresh');}};
    const mounted=mountAdminControl({document,view:{confirm:()=>true},identity:{role:'admin',mode:'admin'},sessionClient:{},stateStore});
    mounted.client.command=async()=>{if(fails)throw Object.assign(Error(),{code:'COMMAND_RESULT_UNKNOWN'});return {state:'completed'};};
    const button=[...document.querySelectorAll('button')].find(b=>b.textContent==='Connect SDK');button.disabled=false;button.click();
    await new Promise(resolve=>setImmediate(resolve));
    assert.deepEqual(calls,[],'no initialization before explicit DOM confirmation');
    const dialog=document.querySelector('[role="alertdialog"]');assert.equal(dialog.hidden,false);
    dialog.querySelector('button').click();
    await new Promise(resolve=>setImmediate(resolve));
    assert.deepEqual(calls,['pending','settled','refresh']);
    assert.match(document.querySelector('[role="status"]').textContent,fails?/result is unknown/:/Command completed/);
    mounted.dispose();
  }
});

test('SDK confirmation never blocks browser heartbeat callbacks; cancel and lost lease never connect',async()=>{
  for(const action of ['cancel','lost-lease','dispose']){
    const {document}=parseHTML('<html><body><section id="page-system"></section></body></html>');
    let commands=0,heartbeatRan=false;
    const mounted=mountAdminControl({document,view:{confirm(){throw Error('native modal blocks heartbeat');}},identity:{role:'observer',mode:'observe'},sessionClient:{}});
    mounted.client.command=async()=>{commands++;};
    const button=[...document.querySelectorAll('button')].find(b=>b.textContent==='Connect SDK');button.disabled=false;button.click();
    await new Promise(resolve=>setImmediate(()=>{heartbeatRan=true;resolve();}));
    const dialog=document.querySelector('[role="alertdialog"]');assert.equal(dialog.hidden,false);assert.equal(heartbeatRan,true);assert.equal(commands,0);
    if(action==='cancel')dialog.querySelectorAll('button')[1].click();
    else if(action==='lost-lease')mounted.client.close();
    else mounted.dispose();
    await new Promise(resolve=>setImmediate(resolve));assert.equal(dialog.hidden,true);assert.equal(commands,0);
    mounted.dispose();
  }
});

async function authorizedUi(request){
  const {document}=parseHTML('<html lang="en"><body><section id="page-system"></section></body></html>');
  const sockets=[];
  class Socket{constructor(){sockets.push(this);}send(){}close(){this.onclose?.();}receive(value){this.onmessage?.({data:JSON.stringify(value)});}}
  const view={WebSocket:Socket,crypto:require('node:crypto'),location:{protocol:'https:',host:'example.invalid'},performance:{now:()=>1000}};
  const mounted=mountAdminControl({document,view,identity:{role:'observer',mode:'observe'},sessionClient:{request:async(path,body,options)=>path.endsWith('/lease')?{id:'test-lease',state:'active',leaseEpoch:1}:request(path,body,options)}});
  // LinkeDOM's select.value has no setter; browsers expose a writable selection.
  Object.defineProperty(document.querySelector('select'),'value',{value:'test-device',writable:true});
  const opening=mounted.client.open(),ws=sockets[0],connectionId='test-channel';ws.onopen();
  ws.receive({type:'bound',connectionId});ws.receive({type:'challenge',connectionId,sequence:1,nonce:'x'.repeat(43)});ws.receive({type:'fresh',connectionId,sequence:1});await opening;
  await mounted.client.acquire('test-device');
  return {document,mounted};
}

test('pending SDK confirmation and submission ignore duplicate clicks and report sanitized rejected or failed device outcomes',async()=>{
  for(const [state,code,want]of [['rejected','READ_ONLY_DEVICE','READ_ONLY_DEVICE'],['failed','ROBOT_REJECTED','ROBOT_REJECTED'],['failed','PRIVATE_UPSTREAM_CODE',null]]){
    let finish,submissions=0;
    const {document,mounted}=await authorizedUi(()=>{submissions++;return new Promise(resolve=>{finish=resolve;});});
    const button=[...document.querySelectorAll('button')].find(b=>b.textContent==='Connect SDK');
    button.click();button.click();await new Promise(setImmediate);
    assert.equal(submissions,0);assert.equal(button.disabled,true);assert.equal(button.getAttribute('aria-busy'),'true');
    const confirm=document.querySelector('[role="alertdialog"] button');confirm.click();confirm.click();await new Promise(setImmediate);
    button.click();await new Promise(setImmediate);assert.equal(submissions,1);assert.equal(button.disabled,true);
    finish({state,code,reasonCode:'PRIVATE_FORGED_CODE',message:'private exception'});await new Promise(setImmediate);
    const text=document.querySelector('[role="status"]').textContent;
    assert.match(text,state==='rejected'?/device rejected/:/command failed/);
    if(want)assert.ok(text.includes(want));
    assert.doesNotMatch(text,/PRIVATE_|private/);assert.equal(button.hasAttribute('aria-busy'),false);assert.equal(button.disabled,false);
    mounted.dispose();
  }
});

test('SDK unknown and read-only denial feedback shows safe codes without raw exception text or automatic resubmission',async()=>{
  for(const [reply,pattern,want]of [
    [{state:'unknown',code:'SUBMISSION_RESULT_UNKNOWN'},/result is unknown/,'SUBMISSION_RESULT_UNKNOWN'],
    [Object.assign(Error('private cause'),{code:'REQUEST_TIMEOUT'}),/result is unknown/,'REQUEST_TIMEOUT'],
    [Object.assign(Error('private cause'),{code:'CONTROL_DISCONNECTED'}),/result is unknown/,'CONTROL_DISCONNECTED'],
    [Object.assign(Error('private cause'),{code:'READ_ONLY_DEVICE'}),/SDK connection and state reading only/,'READ_ONLY_DEVICE'],
    [Object.assign(Error('private cause'),{code:'PRIVATE_UPSTREAM_CODE',reasonCode:'PRIVATE_FORGED_CODE'}),/result is unknown/,null]
  ]){
    let submissions=0;
    const {document,mounted}=await authorizedUi(async()=>{submissions++;if(reply instanceof Error)throw reply;return reply;});
    const button=[...document.querySelectorAll('button')].find(b=>b.textContent==='Disconnect SDK');button.click();await new Promise(setImmediate);
    const text=document.querySelector('[role="status"]').textContent;assert.match(text,pattern);if(want)assert.ok(text.includes(want));
    assert.doesNotMatch(text,/private|PRIVATE_/);assert.equal(submissions,1);assert.equal(button.hasAttribute('aria-busy'),false);assert.equal(button.disabled,true);
    mounted.dispose();
  }
});
