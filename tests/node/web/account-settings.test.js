'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {parseHTML}=require('linkedom');
const root=path.resolve(__dirname,'../../..');
function fixture(hash='#overview'){
 const file=path.join(root,'apps/web/public/js/account-settings.js');assert.ok(fs.existsSync(file),'account workspace implementation is missing');
 const {document,window}=parseHTML(fs.readFileSync(path.join(root,'apps/web/public/index.html'),'utf8'));
 const language=document.getElementById('language-select'),view={ThirdHandStatusLights:require('../../../apps/web/public/js/status-lights.js'),ThirdHandAccountSettings:require(file),location:{hash},history:{replaceState(_a,_b,url){view.location.hash=url;}},addEventListener(){},requestAnimationFrame(fn){fn();},MutationObserver:window.MutationObserver,localStorage:{getItem(){return null;},setItem(){}}};
 const shell=require('../../../apps/web/public/js/workspace-shell.js').mountWorkspace(document,view);
 return {document,window,view,shell,language,click(id){document.getElementById(id).click();}};
}
test('account entry replaces the navigation group and Back restores the same model and draft',()=>{
 const f=fixture(),model=f.document.getElementById('workspace-model'),draft=f.document.getElementById('tcp-x');f.shell.go('vision');draft.value='321';
 f.click('workspace-account');assert.equal(f.view.location.hash,'#account-profile');assert.equal(f.document.getElementById('app').dataset.workspaceGroup,'account');assert.equal(model.hidden,true);
 assert.equal(f.document.querySelector('[data-page="vision"]').hidden,true);assert.equal(f.document.querySelector('[data-page="account-preferences"]').hidden,false);
 f.click('account-back');assert.equal(f.view.location.hash,'#vision');assert.equal(model.hidden,false);assert.equal(f.document.getElementById('workspace-model'),model);assert.equal(draft.value,'321');
});
test('account entry cannot hide active recording or teaching',()=>{
 const f=fixture();let writes=0;f.shell.bindRuntime({voice:{recording:true,openPanel(){},closePanel(){writes++;}}});f.shell.go('assistant');f.click('workspace-account');assert.equal(f.view.location.hash,'#assistant');assert.equal(writes,0);
});
test('preferences owns the original language selector and account deep links work',()=>{
 const f=fixture('#account-preferences');assert.equal(f.view.location.hash,'#account-preferences');assert.equal(f.document.querySelectorAll('#language-select').length,1);
 assert.equal(f.document.getElementById('page-account-preferences').contains(f.language),true);assert.equal(f.document.querySelector('#topbar').contains(f.language),false);
 assert.equal(f.document.getElementById('btn-estop-top').closest('[hidden]'),null);
});
test('unconfigured profile is unavailable and a supplied provider enables actual save',async()=>{
 const f=fixture('#account-profile');assert.equal(f.document.getElementById('account-save').disabled,true);assert.match(f.document.getElementById('account-profile-status').textContent,/not connected/);
 let saved;await f.shell.setAccountDataProvider({loadProfile:async()=>({displayName:'Example',email:'hello@example.test',organization:'Lab'}),saveProfile:async p=>{saved=p;return p;}});
 assert.equal(f.document.getElementById('account-display-name').value,'Example');assert.equal(f.document.getElementById('account-save').disabled,false);
 f.document.getElementById('account-display-name').value='Updated';f.document.getElementById('account-profile-form').dispatchEvent(new f.window.Event('submit',{cancelable:true}));await Promise.resolve();await Promise.resolve();
 assert.equal(saved.displayName,'Updated');assert.match(f.document.getElementById('account-profile-status').textContent,/saved/i);
});
test('late profile responses cannot overwrite a newly selected provider',async()=>{
 const f=fixture();let finish;const old=f.shell.setAccountDataProvider({loadProfile:()=>new Promise(resolve=>finish=resolve)});
 await f.shell.setAccountDataProvider({loadProfile:async()=>({displayName:'Current'})});finish({displayName:'Old'});await old;
 assert.equal(f.document.getElementById('account-display-name').value,'Current');
});
test('account and overview mirror live SDK lamps independently from Web link connectivity',()=>{
 const f=fixture('#account-connections'),listeners={},send=[];
 f.shell.bindRuntime({ws:{on(type,fn){(listeners[type]||=[]).push(fn);},send(value){send.push(value);}}});
 const emit=(type,data)=>{for(const fn of listeners[type]||[])fn(data);f.shell.refresh();};
 emit('ws_connection',{connected:true});emit('robot_state',{connected:true,healthy:true,joints:[0,90,-90,90,0,0]});
 const values=[...f.document.querySelectorAll('.account-connection-row > span')];
 assert.equal(f.document.querySelector('.overview-card-feedback').dataset.linkState,'online');assert.ok(values.some(n=>n.dataset.linkState==='online'&&n.textContent.includes('SDK')));
 emit('connection',{connected:false});assert.equal(f.document.getElementById('hb-label').dataset.linkState,'offline');assert.equal(f.document.getElementById('workspace-web-status').dataset.linkState,'online');
 emit('ws_connection',{connected:false});assert.equal(f.document.getElementById('workspace-web-status').dataset.linkState,'offline');assert.equal(send.length,0);
});
