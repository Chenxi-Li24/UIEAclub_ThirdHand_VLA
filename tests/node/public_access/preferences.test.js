'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { identityFixture } = require('./identity-fixture');
const { createPreferences } = require('../../../platform/identity/src/preferences');
const { createPreferenceClient } = require('../../../apps/web/public/js/preferences');

test('account preferences are versioned, validated and isolated; only explicit guest fields override account settings', async t => {
  const f = await identityFixture(t), a = await f.verified('pref_a'), b = await f.verified('pref_b');
  const preferences = createPreferences({ pool:f.pool });
  const principal = userId => ({ userId });
  const initial = await preferences.load({ principal:principal(a.userId) });
  assert.equal(initial.locale,'en'); assert.equal(initial.themeId,'light');
  const saved = await preferences.save({ principal:principal(a.userId),value:{ locale:'zh-CN',themeId:'dark',backgroundConfig:{ kind:'plain',color:'#fef8f0' } },expectedRevision:initial.revision });
  await assert.rejects(preferences.save({principal:principal(a.userId),value:{...saved,locale:'en'},expectedRevision:initial.revision}),{code:'CONFLICT'});
  const bValue = await preferences.load({principal:principal(b.userId),guestSelection:{value:saved,changed:[]}});
  assert.equal(bValue.locale,'en'); assert.equal(bValue.themeId,'light');
  const override = await preferences.load({principal:principal(a.userId),guestSelection:{value:{locale:'en',themeId:'light'},changed:['locale']}});
  assert.equal(override.locale,'en'); assert.equal(override.themeId,'dark');
  await assert.rejects(preferences.save({principal:principal(a.userId),value:{locale:'en',themeId:'light',backgroundConfig:{kind:'url',url:'javascript:alert(1)'}},expectedRevision:override.revision}),{code:'INVALID_INPUT'});
});

test('blocked browser storage still uses safe defaults and authenticated hydration never copies the previous account cache', async () => {
  const storage = new Map([['thirdhand.preferences.guest.v1',JSON.stringify({locale:'zh-CN',themeId:'dark',backgroundConfig:{kind:'soft',color:'#fff8ee'}})]]);
  const writes = [];
  const view = {localStorage:{getItem:key=>storage.get(key)||null,setItem(key,value){storage.set(key,value);}},addEventListener(){},removeEventListener(){}};
  const client = createPreferenceClient({view,request:async(path,body)=>{writes.push([path,body]);return {locale:'en',themeId:'light',backgroundConfig:{kind:'soft',color:'#fffcf9'},revision:1};}});
  assert.equal(client.current().locale,'zh-CN');
  await client.hydrate({userId:'account-b',csrfToken:'test'});
  assert.equal(client.current().locale,'en'); assert.equal(client.current().themeId,'light');
  assert.ok(writes.every(([,body])=>body===undefined));
  assert.deepEqual(client.explicitSelection().changed,[]);
  const blocked=createPreferenceClient({view:{localStorage:{getItem(){throw Error();},setItem(){throw Error();}},addEventListener(){},removeEventListener(){}}});
  assert.equal(blocked.current().locale,'en'); assert.equal(blocked.current().themeId,'light');
  await blocked.choose({locale:'zh-CN'}); assert.equal(blocked.current().locale,'zh-CN');
});

test('an in-flight preference response cannot contaminate a newer account identity', async () => {
  let finish; const callbacks=[];
  const client=createPreferenceClient({view:{addEventListener(){},removeEventListener(){}},request:(_path,_body,session)=>session.userId==='old'?new Promise(resolve=>{finish=resolve;}):Promise.resolve({locale:'en',themeId:'light',backgroundConfig:{kind:'soft',color:'#fffcf9'},revision:2})});
  client.subscribe(value=>callbacks.push(value));
  const old=client.hydrate({userId:'old',csrfToken:'old'}); await client.hydrate({userId:'new',csrfToken:'new'});
  finish({locale:'zh-CN',themeId:'dark',backgroundConfig:{kind:'soft',color:'#000000'},revision:9}); await old;
  assert.equal(client.current().locale,'en'); assert.equal(client.current().revision,2);
});

test('an unfinished authenticated save is never treated as a new visitor choice for another account',async()=>{
  let finishSave;const calls=[];
  const initial={locale:'en',themeId:'light',backgroundConfig:{kind:'soft',color:'#fffcf9'},revision:1};
  const client=createPreferenceClient({view:{addEventListener(){},removeEventListener(){}},request:(path,body,session)=>{
    calls.push({path,body,userId:session.userId});
    if(session.userId==='old'&&body)return new Promise(resolve=>{finishSave=resolve;});
    return Promise.resolve(initial);
  }});
  await client.hydrate({userId:'old'});const saving=client.choose({locale:'zh-CN'});
  await client.hydrate({userId:'new'});
  assert.equal(calls.at(-1).path,'/api/v1/me/preferences');assert.equal(calls.at(-1).body,undefined);
  finishSave({...initial,locale:'zh-CN',revision:2});await saving;
  assert.equal(client.current().locale,'en');assert.deepEqual(client.explicitSelection().changed,[]);
});
