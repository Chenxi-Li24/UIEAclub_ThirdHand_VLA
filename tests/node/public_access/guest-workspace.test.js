const test=require('node:test'),assert=require('node:assert/strict');
const {createCloudApi}=require('../../../services/cloud-api/src/server');
test('guest preview is public but private data and hardware APIs remain protected',async t=>{
 const server=createCloudApi({publicOrigin:'https://thirdhand.example.invalid',sessions:{resolveSession:async()=>null}});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>new Promise(r=>{server.closeAllConnections();server.close(r);}));
 const base='http://127.0.0.1:'+server.address().port;
 const guest=await fetch(base+'/guest');assert.equal(guest.status,200);const html=await guest.text();assert.match(html,/guest-workspace.js/);assert.ok(!html.includes('src="js/main.js'));assert.ok(!html.includes('ThirdHandWorkspace.mountWorkspace(document, window)'));
 for(const p of ['/guest-assets/js/guest-workspace.js','/guest-assets/js/model-resources.js','/guest-assets/js/onboarding.js','/guest-assets/js/onboarding-spotlight.js'])assert.equal((await fetch(base+p)).status,200);
 for(const p of ['/guest-assets/js/main.js','/guest-assets/js/workspace-session.js','/guest-assets/../.env'])assert.equal((await fetch(base+p)).status,404);
 for(const p of ['/api/v1/devices','/api/v1/me/waypoints','/api/v1/session'])assert.equal((await fetch(base+p)).status,401);
 assert.equal((await fetch(base+'/api/v1/control/lease',{method:'POST'})).status,401);
 for(const p of ['/ws','/execution','/voice'])assert.equal((await fetch(base+p)).status,404);
});

test('guest import map CSP covers the final public asset paths',async t=>{
 const server=createCloudApi({publicOrigin:'https://thirdhand.example.invalid'});await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>new Promise(r=>{server.closeAllConnections();server.close(r);}));
 const response=await fetch('http://127.0.0.1:'+server.address().port+'/guest');const html=await response.text();const map=/<script\b[^>]*type="importmap"[^>]*>([\s\S]*?)<\/script>/.exec(html)[1];
 const hash=require('node:crypto').createHash('sha256').update(map).digest('base64');assert.ok(response.headers.get('content-security-policy').includes("'sha256-"+hash+"'"));assert.match(map,/guest-assets/);
});

const fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
test('guest navigation stays available and robot actions open a permission dialog',()=>{
 const {document,window}=parseHTML(fs.readFileSync('apps/web/public/index.html','utf8'));
 const view={location:{hash:'#control'},history:{replaceState(){}},addEventListener(){},requestAnimationFrame(fn){fn();},MutationObserver:window.MutationObserver,matchMedia:()=>({matches:true,addEventListener(){}})};
 const shell=require('../../../apps/web/public/js/workspace-shell');
 const source=fs.readFileSync('apps/web/public/js/guest-workspace.js','utf8').replace(/\r\n/g,"\n").split("try{\n const {createViewer}")[0];
 vm.runInNewContext(source,{document,window:view,ThirdHandWorkspace:shell});
 assert.equal(document.querySelectorAll('#workspace-nav [data-page]').length,6);
 const dialog=document.getElementById('guest-permission');dialog.showModal=()=>dialog.setAttribute('open','');dialog.close=()=>dialog.removeAttribute('open');
 const send=document.getElementById('btn-send');assert.equal(send.disabled,false);send.click();assert.ok(dialog.hasAttribute('open'));assert.match(dialog.textContent,/Control permission required/);
 assert.equal(dialog.querySelector('a').getAttribute('href'),'/login');
});
