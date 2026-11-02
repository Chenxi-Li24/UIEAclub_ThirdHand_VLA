'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const {parseHTML}=require('linkedom');
const {mountDeviceState}=require('../../../apps/web/public/js/device-state');

for(const layout of ['workspace','classic'])test(`${layout}: real angles expand once and measured feedback never overwrites editable drafts`,async()=>{
  const {document,window}=parseHTML(fs.readFileSync('apps/web/public/index.html','utf8'));
  // Linkedom omits HTMLSelectElement.value's browser setter.
  Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return [...this.options].find(o=>o.selected)?.value||this.options[0]?.value||'';},set(value){for(const option of this.options)option.selected=option.value===value;}});
  const view={MutationObserver:window.MutationObserver,location:{hash:'#control'},history:{replaceState(){}},addEventListener(){},requestAnimationFrame(fn){fn();},localStorage:{getItem(){return null;}},performance:{now:()=>0},setInterval(){return 1;},clearInterval(){},setTimeout(){return 2;},clearTimeout(){}};
  view.ThirdHandAccountSettings=require('../../../apps/web/public/js/account-settings');
  const shell=require('../../../apps/web/public/js/'+(layout==='classic'?'classic-shell':'workspace-shell')).mountWorkspace(document,view,{calibrationEntry:null});
  let sequence=1;
  const requests=[],sample={sourceMode:'hardware',sdkConnected:true,jointPositionRad:[.1,1,-1,0,0,0],gripper:{positionRatio:.4},tcpPositionM:[.2,.3,.4]};
  const mounted=mountDeviceState({document,view,shell,sessionClient:{async request(path,body){requests.push({path,body});return path==='/api/v1/devices'?{devices:[{id:'device',name:'Lab',controllable:true}]}:{schema:1,purpose:'display-only',deviceId:'device',gatewayOnline:true,epochCurrent:true,fresh:true,ageMs:0,sequence:sequence++,context:{connectionId:'test'},sample};}}});
  try{
    await new Promise(setImmediate);
    const section=document.getElementById('sec-rt-angles'),toggle=section.querySelector('.sec-toggle');
    section.classList.add('collapsed');toggle.click();assert.equal(section.classList.contains('collapsed'),false);assert.equal(toggle.getAttribute('aria-expanded'),'true');
    toggle.click();assert.equal(section.classList.contains('collapsed'),true);assert.equal(toggle.getAttribute('aria-expanded'),'false');
    assert.match(document.getElementById('rt-j1').textContent,/5.73°/);
    assert.equal(document.getElementById('stcp').textContent,'TCP: 200.00 mm · 300.00 mm · 400.00 mm');
    document.getElementById('tcp-x').value='555';document.getElementById('gripper-input').value='70';
    sample.jointPositionRad[0]=.2;sample.gripper.positionRatio=.5;sample.tcpPositionM=null;await mounted.store.refresh();
    assert.match(document.getElementById('rt-j1').textContent,/11.46°/);assert.match(document.getElementById('gripper-actual').textContent,/50.00%/);
    assert.equal(document.getElementById('tcp-x').value,'555');assert.equal(document.getElementById('gripper-input').value,'70');assert.equal(document.getElementById('stcp').textContent,'TCP: Not provided');
    assert.ok(requests.every(r=>r.body===undefined&&/^\/api\/v1\/devices(?:\/device\/state)?$/.test(r.path)));
  }finally{mounted.dispose();}
});
