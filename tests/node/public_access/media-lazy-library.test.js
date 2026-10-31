'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),{parseHTML}=require('linkedom');
const {loadVideoLibrary}=require('../../../apps/web/public/js/camera-view');
test('concurrent explicit camera starts share one versioned local library request, and failed loads can retry',async()=>{
  const {document}=parseHTML('<html><head><script id="workspace-bootstrap" type="application/json">{"assetBase":"/control-assets/v'+'a'.repeat(32)+'"}</script></head><body></body></html>');
  const view={document,setTimeout,clearTimeout};
  assert.equal(document.querySelectorAll('script[src]').length,0);
  const first=loadVideoLibrary(view),second=loadVideoLibrary(view);assert.equal(first,second);
  let script=document.querySelector('script[src]');assert.match(script.src,/^\/control-assets\/v[a-f0-9]{32}\/js\/lib\/livekit-client.umd.js$/);
  script.onerror();await assert.rejects(first,/MEDIA_LIBRARY_UNAVAILABLE/);
  const retry=loadVideoLibrary(view);assert.notEqual(first,retry);script=document.querySelector('script[src]');
  view.LivekitClient={Room:class{}};script.onload();assert.equal(await retry,view.LivekitClient);
});
