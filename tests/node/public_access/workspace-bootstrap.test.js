'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const {parseHTML}=require('linkedom');
const {workspaceHtml}=require('../../../services/cloud-api/src/workspace-pages');
const {createPreferenceClient}=require('../../../apps/web/public/js/preferences');
const source=fs.readFileSync('apps/web/public/index.html','utf8');
const preferences={locale:'en',layoutId:'classic',themeId:'dark',backgroundConfig:{kind:'plain',color:'#101522'},revision:5};
test('first HTML has the authenticated layout, theme and safe bootstrap before any scripts execute',()=>{
  const bootstrap={identity:{userId:'a',mode:'observe',displayName:'</script><script>bad()</script>'},preferences};
  const {html}=workspaceHtml(source,{bootstrap,assetVersion:'a'.repeat(32)});
  const {document}=parseHTML(html);
  assert.equal(document.documentElement.dataset.layout,'classic');
  assert.equal(document.documentElement.dataset.theme,'deepspace');
  assert.equal(document.documentElement.dataset.appearance,'dark');
  assert.equal(document.getElementById('app').classList.contains('classic-console'),true);
  assert.equal(document.getElementById('app').dataset.ready,'false');
  assert.deepEqual(JSON.parse(document.getElementById('workspace-bootstrap').textContent).identity,bootstrap.identity);
  assert.equal(html.includes('<script>bad()'),false);
  assert.equal(html.includes('src="/control-assets/js/lib/livekit-client'),false);
  assert.match(html,/\/control-assets\/v[a-f0-9]{32}\/js\/cloud-workspace.js/);
});
test('trusted bootstrap hydrates the same account without a second preferences request or a default-theme emission',async()=>{
  const client=createPreferenceClient({view:{addEventListener(){},removeEventListener(){}},request:()=>{throw Error('must not fetch preferences at startup');}});
  const seen=[];await client.hydrate({userId:'a'},preferences);client.subscribe(value=>seen.push(value));
  assert.equal(client.current().layoutId,'classic');assert.equal(client.current().themeId,'dark');
  assert.equal(seen.length,1);assert.equal(seen[0].layoutId,'classic');client.dispose();
});
