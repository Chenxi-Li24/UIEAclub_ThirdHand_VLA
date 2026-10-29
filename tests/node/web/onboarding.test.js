'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
const root=path.resolve(__dirname,'../../..');
const {mountWorkspace}=require(path.join(root,'apps/web/public/js/workspace-shell.js'));
function fixture({saved,language='en',blocked=false,route='overview'}={}){
 const {document,window}=parseHTML(fs.readFileSync(path.join(root,'apps/web/public/index.html'),'utf8'));
 const storage=new Map(saved?[['thirdhand.onboarding.v1',saved]]:[]);
 const i18n=vm.createContext({localStorage:{getItem:()=>language,setItem(){}}});
 for(const file of ['i18n-catalog.js','i18n-voice-catalog.js','i18n-onboarding-catalog.js','i18n.js']){
  const filename=path.join(root,'apps/web/public/js',file);if(fs.existsSync(filename))vm.runInContext(fs.readFileSync(filename,'utf8'),i18n);
 }
 document.documentElement.lang=i18n.ThirdHandI18n.locale;
 const view={ThirdHandOnboardingSpotlight:require('../../../apps/web/public/js/onboarding-spotlight.js'),location:{hash:'#'+route},history:{replaceState(_a,_b,url){view.location.hash=url;}},addEventListener(){},requestAnimationFrame(fn){queueMicrotask(fn);},MutationObserver:window.MutationObserver,
  ThirdHandI18n:i18n.ThirdHandI18n,localStorage:{getItem(key){if(blocked)throw Error('blocked');return storage.get(key);},setItem(key,value){if(blocked)throw Error('blocked');storage.set(key,value);}}};
 const shell=mountWorkspace(document,view);let busy=false,reject=false,angles=[0,0,0,0,0,0];const navigation=[];
 // Layout is absent in linkedom; lesson elements use a measured, on-screen fixture.
 for(const node of document.querySelectorAll('*'))node.getBoundingClientRect=()=>node.id==='btn-estop-top'?{x:1100,y:15,width:140,height:40}:{x:400,y:100,width:150,height:50};
 // linkedom does not implement native capture ordering. Keep the capture callback
 // for input-order tests; the real stopped-bubbling range is also checked in browser.
 let inputCapture;const jointBody=document.getElementById('joint-controls-body'),listen=jointBody.addEventListener.bind(jointBody);
 jointBody.addEventListener=(name,handler,capture)=>{if(name==='input'&&capture===true)inputCapture=handler;return listen(name,handler,capture);};
 const {mountOnboarding}=require(path.join(root,'apps/web/public/js/onboarding.js'));
 const guide=mountOnboarding(document,view,{go(page){navigation.push(page);if(reject)return false;if(view.location.hash==='#calibration'){
  const frame=document.getElementById('workspace-calibration-frame');if(frame&&!frame.contentWindow)Object.defineProperty(frame,'contentWindow',{value:{ThirdHandCalibrationNavigationState:()=>({unavailable:true})}});
 }return shell.go(page);},getContext:()=>({page:view.location.hash.slice(1),busy,statusText:'Local simulation · SDK:OK',cameraText:'Camera unavailable'}),readJointPreview:()=>angles});
 const click=id=>{const node=document.getElementById(id);assert.ok(node,`missing ${id}`);node.click();};
 const completed=id=>document.querySelector(`[data-onboarding-task="${id}"]`).dataset.complete==='true';
 return {document,window,view,shell,guide,storage,click,completed,navigation,captureInput(input){inputCapture({target:input});},setBusy(value){busy=value;guide.refresh();},rejectNavigation(){reject=true;},setAngles(value){angles=value;}};
}
test('fresh overview welcomes in English; skip saves dismissal without completing tasks',()=>{
 const f=fixture();assert.match(f.document.getElementById('onboarding-welcome-title').textContent,/Welcome/);
 f.click('onboarding-later');assert.equal(f.document.getElementById('onboarding-welcome').hidden,true);
 assert.equal(f.completed('orbit'),false);assert.equal(f.completed('preview'),false);
 const restored=fixture({saved:f.storage.get('thirdhand.onboarding.v1')});
 assert.equal(restored.document.getElementById('onboarding-welcome').hidden,true);
 assert.equal(restored.document.getElementById('onboarding-checklist').hidden,false);
});
test('tour completes informational acknowledgments without fabricating practical or physical completion',()=>{
 const f=fixture();f.click('onboarding-start');
 for(let i=0;i<6;i++)f.click('onboarding-next');
 assert.equal(f.document.getElementById('onboarding-panel').hidden,true);
 assert.equal(f.completed('status'),true);assert.equal(f.completed('vision'),true);
 assert.equal(f.completed('orbit'),false);assert.equal(f.completed('preview'),false);
 assert.equal(f.document.querySelectorAll('.onboarding-highlight').length,0);
 assert.ok(f.navigation.includes('vision'));assert.ok(f.navigation.includes('calibration'));
});
test('busy and guarded routes pause the tour without advancing it or activating controls',()=>{
 const f=fixture();let commands=0;for(const id of ['btn-connect','btn-send','btn-grasp-start','btn-estop-top','voice-mic-toggle'])f.document.getElementById(id).addEventListener('click',()=>commands++);
 f.setBusy(true);f.click('onboarding-start');assert.equal(f.navigation.length,0);
 f.setBusy(false);f.click('onboarding-start');const before=f.document.getElementById('onboarding-step').textContent;
 f.rejectNavigation();f.click('onboarding-next');assert.equal(f.document.getElementById('onboarding-step').textContent,before);
 f.setBusy(true);f.click('onboarding-next');assert.equal(f.document.querySelectorAll('.onboarding-highlight').length,0);
 assert.equal(commands,0);
});
test('skip/continue resumes its step; restart preserves actual learning progress',()=>{
 const f=fixture();f.click('onboarding-start');f.click('onboarding-next');f.click('onboarding-skip');
 const restored=fixture({saved:f.storage.get('thirdhand.onboarding.v1')});restored.click('onboarding-start');
 assert.match(restored.document.getElementById('onboarding-step').textContent,/2/);
 restored.click('onboarding-skip');restored.click('onboarding-restart');
 assert.match(restored.document.getElementById('onboarding-step').textContent,/1/);assert.equal(restored.completed('status'),true);
});
test('watching again starts at step one and paused highlights return when activity ends',()=>{
 const f=fixture();f.click('onboarding-start');for(let i=0;i<6;i++)f.click('onboarding-next');
 f.click('workspace-guide');f.click('onboarding-next');assert.match(f.document.getElementById('onboarding-step').textContent,/1/);
 f.setBusy(true);assert.equal(f.document.querySelectorAll('.onboarding-highlight').length,0);
 f.setBusy(false);assert.equal(f.document.querySelectorAll('.onboarding-highlight').length,1);
});
test('automatic camera changes do not count as orbit; user-started changed view does',()=>{
 const f=fixture(),events={};const scene={camera:{position:{toArray:()=>[x,0,0]},quaternion:{toArray:()=>[0,0,0,1]}},controls:{addEventListener(name,fn){events[name]=fn;}}};let x=0;
 f.guide.bindScene(scene);events.change();assert.equal(f.completed('orbit'),false);
 events.start();events.end();assert.equal(f.completed('orbit'),false);
 events.start();x=1;events.change();events.end();assert.equal(f.completed('orbit'),true);
});
test('joint progress requires a valid post-handler model match',async()=>{
 const f=fixture(),body=f.document.getElementById('joint-controls-body');
 const input=f.document.createElement('input');input.id='slider-j0';input.min='-162';input.max='162';input.value='10';body.appendChild(input);
 f.captureInput(input);await Promise.resolve();assert.equal(f.completed('preview'),false);
 f.captureInput(input);f.setAngles([10,0,0,0,0,0]);assert.equal(f.completed('preview'),false);await Promise.resolve();assert.equal(f.completed('preview'),true);
 const other=fixture();const invalid=other.document.createElement('input');invalid.id='jinput-0';invalid.min='-162';invalid.max='162';invalid.value='999';other.document.getElementById('joint-controls-body').appendChild(invalid);other.setAngles([999,0,0,0,0,0]);invalid.dispatchEvent(new other.window.Event('input',{bubbles:true}));await Promise.resolve();assert.equal(other.completed('preview'),false);
});
test('retyping an unchanged joint value does not complete a joint change',async()=>{
 const f=fixture(),input=f.document.createElement('input');Object.assign(input,{id:'jinput-0',min:'-162',max:'162',value:'0'});f.document.getElementById('joint-controls-body').appendChild(input);
 f.captureInput(input);await Promise.resolve();assert.equal(f.completed('preview'),false);
});
test('Escape after focus leaves the panel closes the optional guide',()=>{
 const f=fixture();f.click('onboarding-start');const event=new f.window.Event('keydown',{bubbles:true});Object.defineProperty(event,'key',{value:'Escape'});
 f.document.getElementById('btn-tool-grid').dispatchEvent(event);assert.equal(f.document.getElementById('onboarding-panel').hidden,true);assert.equal(f.document.querySelectorAll('.onboarding-highlight').length,0);
});
test('tour opens a spotlight dialog outside the scroller; busy and close remove the dimmer',()=>{
 const f=fixture();f.click('onboarding-start');const panel=f.document.getElementById('onboarding-panel'),layer=f.document.getElementById('onboarding-spotlight');
 assert.equal(panel.getAttribute('role'),'dialog');assert.equal(f.document.getElementById('workspace-pages').contains(panel),false);assert.equal(layer.dataset.dimmed,'true');
 f.setBusy(true);assert.equal(layer.dataset.dimmed,'false');assert.equal(panel.hidden,false);
 f.setBusy(false);assert.equal(layer.dataset.dimmed,'true');f.click('onboarding-skip');assert.equal(layer.hidden,true);
});
test('page help never navigates; manual route changes remove stale highlights',()=>{
 const f=fixture();f.guide.openPageHelp('vision');assert.equal(f.navigation.length,0);f.click('onboarding-help-done');assert.equal(f.completed('vision'),true);
 f.click('onboarding-start');f.guide.routeChanged('system');assert.equal(f.document.querySelectorAll('.onboarding-highlight').length,0);
});
test('a hidden guide target pauses Next rather than acknowledging a missing control',()=>{
 const f=fixture();f.document.getElementById('topbar').hidden=true;f.click('onboarding-start');
 assert.equal(f.document.getElementById('onboarding-next').disabled,true);f.click('onboarding-next');
 assert.equal(f.completed('status'),false);
 f.document.getElementById('topbar').hidden=false;f.guide.refresh();assert.equal(f.document.getElementById('onboarding-next').disabled,false);
});
test('saved Chinese and live language switch update all guide copy; corrupt or blocked storage stays usable',async()=>{
 const f=fixture({language:'zh-CN'});assert.match(f.document.getElementById('onboarding-welcome-title').textContent,/欢迎/);
 f.view.ThirdHandI18n.setLocale('en');f.document.documentElement.lang='en';await Promise.resolve();f.guide.refresh();assert.match(f.document.getElementById('onboarding-welcome-title').textContent,/Welcome/);
 for(const options of [{saved:'{invalid'},{saved:'{"version":1,"step":999,"done":["hardware","orbit"]}'},{blocked:true}]){
  const g=fixture(options);assert.doesNotThrow(()=>{g.click('onboarding-start');g.click('onboarding-skip');});
 }
});
