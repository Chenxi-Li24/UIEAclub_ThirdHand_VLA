'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {parseHTML}=require('linkedom');
const fs=require('node:fs');
const {mountAdminControl}=require('../../../apps/web/public/js/admin-control');

test('live control UI is absent for observing sessions and never opens a socket or SDK during mount',()=>{
  for(const identity of [{role:'observer',mode:'observe'},{role:'admin',mode:'observe'},{role:'admin',mode:'admin'}]){
    const {document}=parseHTML(fs.readFileSync('apps/web/public/index.html','utf8'));
    const page=document.createElement('section');page.id='page-system';document.body.append(page);
    let sockets=0,requests=0;
    const view={WebSocket:class{constructor(){sockets++;}},crypto:{randomUUID:()=> 'test'},location:{protocol:'https:',host:'example.invalid'}};
    const mounted=mountAdminControl({document,view,identity,sessionClient:{async request(){requests++;}},arm:{getJointAngles:()=>[0,90,-90,0,0,0]}});
    const panel=document.getElementById('cloud-live-control');
    assert.equal(!!panel,identity.mode==='admin');assert.equal(sockets,0);assert.equal(requests,0);
    if(panel){const connect=[...panel.querySelectorAll('button')].find(button=>button.textContent==='Connect SDK');assert.equal(connect.disabled,true);assert.equal(panel.textContent.includes('Send model pose to robot'),false);}
    mounted.dispose();
  }
});

test('administrator read-only connection is located exclusively in Devices & diagnostics',()=>{
  const {document}=parseHTML(fs.readFileSync('apps/web/public/index.html','utf8'));
  const page=document.createElement('section');page.id='page-system';document.body.append(page);
  const mounted=mountAdminControl({document,view:{},identity:{role:'admin',mode:'admin'},sessionClient:{},arm:{}});
  try{assert.equal(document.getElementById('cloud-live-control').parentElement.id,'page-system');}
  finally{mounted.dispose();}
});
