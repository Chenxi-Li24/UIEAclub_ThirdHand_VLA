'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createCloudApi}=require('../../../services/cloud-api/src/server');
const {workspaceHtml}=require('../../../services/cloud-api/src/workspace-pages');
test('CSP import-map hash matches browser-normalized Windows newlines',()=>{
  const source='<!doctype html><html><head></head><body><script type="importmap">\r\n{"imports":{"three":"/js/lib/three.module.js"}}\r\n</script><script type="module" src="js/main.js"></script></body></html>';
  const rendered=workspaceHtml(source);
  // Independently calculated over the LF text actually exposed by the browser DOM.
  assert.ok(rendered.csp.includes('sha256-tKoQ2+6gZPcA5tIHo4kfHcHNJJhbgos80z3oGwz51hw='));
});
test('auth pages serve only their public resources, with a strict CSP and no access to workspace source or config',async t=>{
  const server=createCloudApi({publicOrigin:'https://thirdhand.example.invalid'});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(()=>new Promise(resolve=>{server.closeAllConnections();server.close(resolve);}));
  const base=`http://127.0.0.1:${server.address().port}`;
  for(const [route,title]of [['/login','Welcome back'],['/register','Create account'],['/forgot-password','Reset your password'],['/verify-email','Verify your email'],['/reset-password','Choose a new password']]){
    const result=await fetch(base+route);assert.equal(result.status,200);assert.match(result.headers.get('content-type'),/text\/html/);
    assert.ok((await result.text()).includes(title));assert.ok(result.headers.get('content-security-policy').includes("frame-ancestors 'none'"));
  }
  assert.equal((await fetch(base+'/css/auth.css')).status,200);assert.equal((await fetch(base+'/js/auth-page.js')).status,200);
  for(const route of ['/package.json','/.env','/src/server.js','/js/main.js','/index.html','/assets/../../package.json'])assert.equal((await fetch(base+route)).status,404);
});
