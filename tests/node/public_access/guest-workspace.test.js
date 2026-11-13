const test=require('node:test'),assert=require('node:assert/strict');
const {createCloudApi}=require('../../../services/cloud-api/src/server');
test('guest preview is public but private data and hardware APIs remain protected',async t=>{
 const server=createCloudApi({publicOrigin:'https://thirdhand.example.invalid',sessions:{resolveSession:async()=>null}});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>new Promise(r=>{server.closeAllConnections();server.close(r);}));
 const base='http://127.0.0.1:'+server.address().port;
 const guest=await fetch(base+'/guest');assert.equal(guest.status,200);const html=await guest.text();assert.match(html,/guest-workspace.js/);assert.ok(!html.includes('src="js/main.js'));assert.ok(!html.includes('ThirdHandWorkspace.mountWorkspace(document, window)'));
 for(const p of ['/guest-assets/js/guest-workspace.js','/guest-assets/js/model-resources.js'])assert.equal((await fetch(base+p)).status,200);
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
