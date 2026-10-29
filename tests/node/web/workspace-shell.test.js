'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { parseHTML } = require('linkedom');
const root = path.resolve(__dirname, '../../..');
function fixture({navPreference,narrow=false,storageBlocked=false}={}) {
  const { document, window } = parseHTML(fs.readFileSync(path.join(root, 'apps/web/public/index.html'), 'utf8'));
  const preferences=new Map(navPreference?[['thirdhand.nav-state',navPreference]]:[]);
  const media={matches:!narrow,addEventListener(_event,handler){this.changed=handler;}};
  const view = { location: { hash: '' }, history: { replaceState(_a, _b, hash) { view.location.hash = hash; } },
    addEventListener() {}, requestAnimationFrame(fn) { fn(); }, MutationObserver: window.MutationObserver,
    matchMedia(){return media;},localStorage:{getItem(key){if(storageBlocked)throw Error('blocked');return preferences.get(key);},setItem(key,value){if(storageBlocked)throw Error('blocked');preferences.set(key,value);}}};
  const { mountWorkspace } = require(path.join(root, 'apps/web/public/js/workspace-shell.js'));
  return { document, window, shell: mountWorkspace(document, view), mountWorkspace, view, preferences, media };
}
test('sidebar toggle changes only navigation width, retains calibration/model state and sends no commands',()=>{
 const {document,shell,preferences,view}=fixture(),app=document.getElementById('app');
 const toggle=document.getElementById('workspace-nav-toggle');assert.ok(toggle,'a visible collapse control is required');
 let writes=0,resizes=0;shell.bindRuntime({ws:{on(){},send(){writes++;},connect(){writes++;}},scene:{_onResize(){resizes++;}}});
 shell.go('calibration');const frame=document.getElementById('workspace-calibration-frame'),model=document.getElementById('viewport');
 Object.defineProperty(frame,'contentWindow',{value:{ThirdHandCalibrationNavigationState:()=>({known:true,teachActive:true})}});
 const before=resizes;toggle.click();
 assert.equal(app.dataset.navState,'collapsed');assert.equal(toggle.getAttribute('aria-expanded'),'false');
 assert.equal(toggle.getAttribute('aria-label'),'Expand menu');assert.equal(preferences.get('thirdhand.nav-state'),'collapsed');
 assert.equal(view.location.hash,'#calibration');assert.equal(document.getElementById('workspace-calibration-frame'),frame);
 assert.equal(document.getElementById('viewport'),model);assert.equal(document.getElementById('page-calibration').hidden,false);
 toggle.click();assert.equal(app.dataset.navState,'expanded');assert.equal(toggle.getAttribute('aria-expanded'),'true');
 assert.equal(preferences.get('thirdhand.nav-state'),'expanded');assert.ok(resizes>before);assert.equal(writes,0);
});
test('sidebar restores the explicit preference and follows viewport changes only until the user chooses',()=>{
 const restored=fixture({navPreference:'collapsed'});assert.equal(restored.document.getElementById('app').dataset.navState,'collapsed');
 const {document,media,preferences}=fixture();const app=document.getElementById('app');
 media.changed({matches:false});assert.equal(app.dataset.navState,'collapsed');assert.equal(preferences.size,0);
 document.getElementById('workspace-nav-toggle').click();assert.equal(app.dataset.navState,'expanded');
 media.changed({matches:false});assert.equal(app.dataset.navState,'expanded');
 assert.equal(fixture({navPreference:preferences.get('thirdhand.nav-state'),narrow:true}).document.getElementById('app').dataset.navState,'expanded');
});
test('blocked browser storage cannot prevent sidebar navigation or toggling',()=>{
 const {document,shell}=fixture({storageBlocked:true,narrow:true});
 assert.equal(document.getElementById('app').dataset.navState,'collapsed');
 document.getElementById('workspace-nav-toggle').click();
 assert.equal(document.getElementById('app').dataset.navState,'expanded');assert.equal(shell.go('vision'),true);
});
test('onboarding respects MOVING feedback and does not switch a pending TCP tab',()=>{
 const {document,shell}=fixture(),handlers={},selections=[];let commands=0;
 shell.bindRuntime({ws:{on(name,fn){handlers[name]=fn;},send(){commands++;}},ui:{selectWorkspaceControl:tab=>selections.push(tab),arm:{getJointAngles:()=>[0,0,0,0,0,0]}}});
 shell.selectControl('tcp');const guide=shell.installOnboarding(require('../../../apps/web/public/js/onboarding.js'));const before=selections.length;
 document.getElementById('onboarding-start').click();document.getElementById('onboarding-next').click();document.getElementById('onboarding-next').click();
 assert.equal(document.getElementById('pane-tcp').hidden,false);assert.equal(selections.length,before);
 const step=document.getElementById('onboarding-step').textContent;handlers.robot_state({moving:false,stateName:'MOVING'});
 document.getElementById('onboarding-next').click();assert.equal(document.getElementById('onboarding-step').textContent,step);assert.equal(commands,0);assert.ok(guide);
});
test('onboarding pauses unknown teaching and a configured but failed snapshot',()=>{
 const {document,shell}=fixture();shell.go('calibration');const frame=document.getElementById('workspace-calibration-frame');let state={loaded:true,known:false,teachActive:false};
 Object.defineProperty(frame,'contentWindow',{value:{ThirdHandCalibrationNavigationState:()=>state}});shell.installOnboarding(require('../../../apps/web/public/js/onboarding.js'));
 document.getElementById('workspace-guide').click();assert.equal(document.getElementById('onboarding-next').disabled,true);
 state={unavailable:true,bound:true};shell.refresh();assert.equal(document.getElementById('onboarding-next').disabled,true);
 state={unavailable:true,bound:false};shell.refresh();assert.equal(document.getElementById('onboarding-next').disabled,false);
});
test('workspace preserves actual controls, input state and listeners across six pages and three tabs', () => {
  const { document, shell, mountWorkspace, view } = fixture();
  const input = document.getElementById('tcp-x'), send = document.getElementById('btn-send');
  document.getElementById('workspace-pages').scrollTop=120;
  input.value = '321'; let clicks = 0; send.addEventListener('click', () => clicks++);
  for (const page of ['vision', 'calibration', 'assistant', 'system', 'overview', 'control']) {
    assert.equal(shell.go(page), true);
    if(page==='calibration')Object.defineProperty(document.getElementById('workspace-calibration-frame'),'contentWindow',{value:{ThirdHandCalibrationNavigationState:()=>({known:true,teachActive:false,teachPending:false})}});
    assert.equal(document.querySelectorAll('.workspace-page:not([hidden])').length, 1);
    assert.equal(document.getElementById('btn-estop-top').closest('[hidden]'), null);
  }
  assert.equal(document.getElementById('workspace-pages').scrollTop,120);
  for (const tab of ['tcp', 'gripper', 'joints']) shell.selectControl(tab);
  shell.selectControl('tcp'); assert.equal(send.closest('[hidden]'), null);
  assert.equal(document.getElementById('tcp-x'), input); assert.equal(input.value, '321');
  send.click(); assert.equal(clicks, 1);
  assert.equal(mountWorkspace(document, view), shell);
  const ids = [...document.querySelectorAll('[id]')].map(node => node.id);
  assert.equal(new Set(ids).size, ids.length);
  assert.equal(document.querySelectorAll('[role="tabpanel"]:not([hidden])').length, 1);
});
test('the same model stays visible beside every page and receives resize without transport writes', () => {
  const {document,shell}=fixture();const viewport=document.getElementById('viewport');
  const container=document.getElementById('three-container'),canvas=document.createElement('canvas');container.appendChild(canvas);
  let resizes=0,writes=0;
  shell.bindRuntime({scene:{_onResize(){resizes++;}},ws:{on(){},send(){writes++;},connect(){writes++;}}});
  assert.ok(!container.closest('.workspace-page'),'the model must be outside the routed pages');
  for(const page of ['vision','calibration','assistant','system','overview','control']){
    const before=resizes;assert.equal(shell.go(page),true);
    if(page==='calibration')Object.defineProperty(document.getElementById('workspace-calibration-frame'),'contentWindow',{value:{ThirdHandCalibrationNavigationState:()=>({known:true,teachActive:false,teachPending:false})}});
    assert.equal(viewport.closest('[hidden]'),null,`model hidden on ${page}`);
    assert.equal(document.getElementById('three-container').firstChild,canvas);
    assert.equal(document.getElementById('viewport'),viewport);
    assert.ok(resizes>before,`model not resized on ${page}`);
  }
  assert.equal(writes,0);
});
test('camera placeholder yields to a real frame and returns on image failure without changing the feed',()=>{
 const {document,window}=fixture(),feed=document.getElementById('xvision-feed');
 const placeholder=document.querySelector('.camera-empty');
 assert.ok(placeholder,'offline camera should have an honest empty state');
 feed.setAttribute('src','/camera/feed');Object.defineProperty(feed,'naturalWidth',{value:640});
 feed.dispatchEvent(new window.Event('load'));
 assert.equal(placeholder.hidden,true);assert.equal(feed.getAttribute('src'),'/camera/feed');
 feed.dispatchEvent(new window.Event('error'));
 assert.equal(placeholder.hidden,false);assert.equal(feed.getAttribute('src'),'/camera/feed');
});
test('route switches never write robot commands or reconnect clients; real config drives mode', () => {
  const { document, shell } = fixture(); const handlers = {}; let writes = 0;
  const channel = { on(name, fn) { handlers[name] = fn; }, send() { writes++; }, connect() { writes++; } };
  shell.bindRuntime({ ws: channel });
  assert.match(document.getElementById('workspace-mode').textContent, /Unknown/);
  handlers.config({ connection: { simulated: true } });
  assert.match(document.getElementById('workspace-mode').textContent, /simulation/);
  handlers.robot_state({ moving: true });
  for (const page of ['vision', 'system', 'control', 'overview']) shell.go(page);
  assert.equal(writes, 0);
  assert.equal(document.getElementById('workspace-task').hidden, false);
  assert.match(document.getElementById('workspace-task').textContent, /motion/i);
});
test('assistant remains visible while recording or starting and navigation never starts recording', () => {
  const { shell } = fixture(); let opens = 0, closes = 0;
  const voice = { recording: false, starting: false, openPanel() { opens++; }, closePanel() { closes++; } };
  shell.bindRuntime({ voice }); shell.go('assistant');
  voice.starting = true; assert.equal(shell.go('control'), false);
  voice.starting = false; voice.recording = true; assert.equal(shell.go('vision'), false);
  voice.recording = false; assert.equal(shell.go('control'), true);
  assert.equal(opens, 1); assert.equal(closes, 1);
});
test('Escape cannot hide or inert the assistant while recording', () => {
  const { document, window, shell } = fixture(); const panel = document.getElementById('voice-panel');
  const voice = { recording: true, openPanel() { panel.inert = false; }, closePanel() { panel.inert = true; } };
  shell.bindRuntime({ voice }); shell.go('assistant');
  panel.addEventListener('keydown', event => { if (event.key === 'Escape') voice.closePanel(); });
  const event = new window.Event('keydown', { bubbles: true, cancelable: true });
  Object.defineProperty(event, 'key', { value: 'Escape' }); panel.dispatchEvent(event);
  assert.equal(panel.inert, false); assert.equal(document.getElementById('page-assistant').hidden, false);
});
test('the visible manual tab owns send dispatch and gripper has no hidden arm send action', () => {
  const { document, shell } = fixture(); const choices = [];
  shell.bindRuntime({ ui: { selectWorkspaceControl: value => choices.push(value) } });
  shell.selectControl('tcp'); shell.selectControl('joints'); shell.selectControl('gripper');
  assert.deepEqual(choices, ['joints', 'tcp', 'joints', 'gripper']);
  assert.equal(document.getElementById('sec-actions').hidden, true);
});
test('calibration iframe is persistent and active/pending teaching blocks leaving until confirmed locked', () => {
  const { document, shell } = fixture(); shell.go('calibration');
  const frame = document.getElementById('workspace-calibration-frame');
  assert.equal(shell.go('control'),false,'initial loading cannot hide a wizard that may restore teaching');
  let state = { teachActive: true, teachPending: false, known: true };
  Object.defineProperty(frame, 'contentWindow', { value: { ThirdHandCalibrationNavigationState: () => state } });
  assert.equal(shell.go('control'), false);
  state = { known: false }; assert.equal(shell.go('system'), false);
  state = { known: true, teachActive: false, teachPending: true }; assert.equal(shell.go('vision'), false);
  state = { known: true, teachActive: false, teachPending: false }; assert.equal(shell.go('control'), true);
  shell.go('calibration'); assert.equal(document.getElementById('workspace-calibration-frame'), frame);
  assert.equal(document.querySelectorAll('iframe').length, 1);
});
test('an explicitly unavailable calibration service allows leaving its idle wizard',()=>{
 const {document,shell}=fixture();shell.go('calibration');
 Object.defineProperty(document.getElementById('workspace-calibration-frame'),'contentWindow',{value:{ThirdHandCalibrationNavigationState:()=>({known:false,unavailable:true,teachActive:false,teachPending:false})}});
 assert.equal(shell.go('control'),true);
});
test('a loaded disconnected idle calibration snapshot permits leaving without clearing an unsafe latch',()=>{
 const {document,shell}=fixture();shell.go('calibration');let state={loaded:true,known:false,teachActive:false};
 Object.defineProperty(document.getElementById('workspace-calibration-frame'),'contentWindow',{value:{ThirdHandCalibrationNavigationState:()=>state}});
 assert.equal(shell.go('control'),true);shell.go('calibration');state={loaded:true,known:true,teachActive:true};
 assert.equal(shell.go('control'),false);state={loaded:true,known:false,teachActive:false};
 assert.equal(shell.go('control'),false);
});
test('a confirmed teaching lock resumes the guide while unknown feedback retains its pause',()=>{
 const {document,shell}=fixture();shell.go('calibration');let state={loaded:true,known:true,teachActive:true};
 Object.defineProperty(document.getElementById('workspace-calibration-frame'),'contentWindow',{value:{ThirdHandCalibrationNavigationState:()=>state}});
 shell.installOnboarding(require('../../../apps/web/public/js/onboarding.js'));
 assert.equal(shell.go('control'),false);document.getElementById('workspace-guide').click();
 state={loaded:true,known:false,teachActive:false};shell.refresh();assert.equal(document.getElementById('onboarding-next').disabled,true);
 state={loaded:true,known:true,teachActive:false,teachPending:false};shell.refresh();assert.equal(document.getElementById('onboarding-next').disabled,false);
});
test('unavailable services stay unknown and real grasp status remains visible outside vision page', () => {
  const { document, shell } = fixture(); const ui = { webGraspStatus: { active: true, phase: 'approach' } };
  shell.bindRuntime({ ui }); shell.go('overview'); shell.refresh();
  assert.equal(document.getElementById('workspace-task').hidden, false);
  assert.match(document.getElementById('workspace-task').textContent, /approach/);
  assert.match(document.getElementById('workspace-summary-connection').textContent, /未连接|Disconnected/);
});
test('overview includes camera readiness and ongoing depth/following work off-page', () => {
  const { document, shell } = fixture(); const ui = { activeDepthStatus: { active: true, phase: 'observing' } };
  document.getElementById('cam-label').textContent = 'Camera offline';
  document.getElementById('vision-lock-reason').textContent = 'Workflow configured';
  shell.bindRuntime({ ui }); shell.go('overview');
  assert.match(document.getElementById('workspace-summary-vision').textContent, /Camera offline/);
  assert.equal(document.getElementById('workspace-task').hidden, false);
  assert.match(document.getElementById('workspace-task').textContent, /observing/);
  ui.activeDepthStatus.active=false; document.getElementById('sec-dummy').dataset.running='true'; shell.refresh();
  assert.equal(document.getElementById('workspace-task').hidden, false);
  assert.match(document.getElementById('workspace-task').textContent, /following/i);
  document.getElementById('sec-dummy').dataset.running='false';ui.activeDepthStatus={active:false,phase:'uncertain'};shell.refresh();
  assert.equal(document.getElementById('workspace-task').hidden,false);
  assert.match(document.getElementById('workspace-task').textContent,/uncertain/i);
});
