'use strict';
const fs=require('node:fs/promises');
const path=require('node:path');
const {createHash}=require('node:crypto');
const {serveWorkspacePage,protectedHtml}=require('./workspace-pages');
const serveCamera=require('./guest-camera').createGuestCamera();
const root=path.resolve(__dirname,'../../../apps/web/public');
const guestFiles=new Set(['js/guest-workspace.js','js/workspace-shell.js','js/camera-lighting.js','js/model-resources.js','js/robot-viewer.js','js/model-waypoints.js']);
function guestAssetAllowed(file){return guestFiles.has(file)||/^css\/[a-z0-9-]+\.css$/.test(file)||/^js\/lib\/(?:[a-zA-Z0-9_-]+\/)*[a-zA-Z0-9_.-]+\.js$/.test(file)||/^models\/startouch-v3\/(?:FastTouchV3\.SLDASM\.urdf|web\/robot-visuals\.glb)$/.test(file);}
async function serveGuestPage(request,response,pathname,{publicOrigin}={}){
 if(await serveCamera(request,response,pathname))return true;
 if(!['GET','HEAD'].includes(request.method))return false;
 if(pathname==='/guest'){
  let source=await fs.readFile(path.join(root,'index.html'),'utf8');
  source=source.replace(/<script\b(?![^>]*type="importmap")[^>]*>[\s\S]*?<\/script>/g,'');
  source=source.replace('</body>','<script src="/js/camera-lighting.js"></script><script src="/js/workspace-shell.js"></script><script type="module" src="/js/guest-workspace.js"></script></body>');
  const rendered=protectedHtml(source,{publicOrigin});
  const html=rendered.html.replaceAll('/control-assets/','/guest-assets/');
  const map=/<script\b[^>]*type="importmap"[^>]*>([\s\S]*?)<\/script>/.exec(html)[1];
  const hash=createHash('sha256').update(map).digest('base64');
  const csp=rendered.csp.replace(/'sha256-[^']+'/g,`'sha256-${hash}'`);
  response.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','Content-Security-Policy':csp});
  response.end(request.method==='HEAD'?undefined:html);return true;
 }
 if(!pathname.startsWith('/guest-assets/'))return false;
 const file=pathname.slice('/guest-assets/'.length);
 if(!guestAssetAllowed(file)){response.writeHead(404);response.end();return true;}
 return serveWorkspacePage(request,response,'/control-assets/'+file,{publicOrigin});
}
module.exports={serveGuestPage,guestAssetAllowed};
