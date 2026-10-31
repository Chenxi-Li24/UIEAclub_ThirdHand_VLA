'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createWorkspaceSession}=require('../../../apps/web/public/js/workspace-session');
test('a failed MFA challenge does not masquerade as logout; actual unauthenticated responses revoke the workspace',async()=>{
  let error='MFA_INVALID',revoked=0;
  const view={fetch:async()=>({ok:false,status:401,json:async()=>({error})})};
  const client=createWorkspaceSession({view,onRevoked:()=>revoked++});
  await assert.rejects(client.request('/api/v1/mfa/confirm',{totp:'invalid'}),{code:'MFA_INVALID'});assert.equal(revoked,0);
  error='UNAUTHENTICATED';await assert.rejects(client.request('/api/v1/session'),{code:'UNAUTHENTICATED'});assert.equal(revoked,1);
});
test('session monitoring is read-only while actual human input alone submits activity with CSRF',async()=>{
  const requests=[],listeners=new Map();let tick;
  const view={document:{visibilityState:'visible',addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:name=>listeners.delete(name)},setInterval(fn){tick=fn;return 1;},clearInterval(){},fetch:async(path,options)=>{requests.push({path,options});return {ok:true,status:200,json:async()=>({userId:'a',sessionId:'s',role:'observer',mode:'observe',csrfToken:'csrf'})};}};
  const client=createWorkspaceSession({view});await client.load();client.startMonitoring();tick();await Promise.resolve();await Promise.resolve();
  assert.ok(requests.every(request=>request.options.method==='GET'));
  listeners.get('pointerdown')();await Promise.resolve();assert.equal(requests.at(-1).path,'/api/v1/session/activity');assert.equal(requests.at(-1).options.headers['X-CSRF-Token'],'csrf');
  assert.equal(requests.at(-1).options.body,'{}');client.close();assert.equal(listeners.size,0);
});
