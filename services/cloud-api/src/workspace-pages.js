'use strict';
const fs=require('node:fs');
const fsp=require('node:fs/promises');
const path=require('node:path');
const {createHash}=require('node:crypto');
const {assetPath,isolateAssets}=require('./asset-paths');
const root=path.resolve(__dirname,'../../../apps/web/public'),models=path.resolve(__dirname,'../../../assets/robot');
const files=new Set([
  'js/model-waypoints.js','css/model-waypoints.css',
  'css/style.css','css/i18n.css','css/workspace.css','css/workspace-polish.css','css/onboarding.css','css/account-settings.css','css/workspace-surfaces.css','css/status-lights.css','css/cloud-workspace.css',
  'js/cloud-workspace.js','js/robot-viewer.js','js/workspace-session.js','js/simulation-controller.js','js/tutorial-adapter.js','js/camera-lighting.js','js/onboarding-spotlight.js','js/onboarding.js','js/account-settings.js','js/admin-access.js','js/account-security.js','js/admin-control.js','js/status-lights.js','js/workspace-shell.js',
  'js/i18n-voice-catalog.js','js/i18n-onboarding-catalog.js','js/i18n-account-catalog.js','js/i18n-status-catalog.js','js/i18n-cloud-catalog.js','js/history-page.js','js/history-dates.js','js/history-replay.js','js/i18n-history-catalog.js','css/history.css','js/camera-view.js','js/lib/livekit-frame-metadata.worker.mjs'
]);
const modelFile=/^models\/startouch-v3\/(?:FastTouchV3\.SLDASM\.urdf|meshes\/(?:base_link|link[1-5]|gripper_base|gripper_link[12])\.STL)$/;
function isWorkspacePath(pathname){pathname=assetPath(pathname);const file=pathname.slice(1);return ['/control','/history'].includes(pathname)||files.has(file)||/^js\/lib\/(?:[a-zA-Z0-9_-]+\/)*[a-zA-Z0-9_.-]+\.js$/.test(file)||modelFile.test(file);}
function workspaceHtml(source,{publicOrigin}={}){
  // HTML parsing normalizes CRLF/CR before CSP hashes are checked in the browser.
  source=source.replace(/\r\n?/g,'\n');
  let html=source.replace(/<script\b[^>]*\bsrc=["']js\/(?:dummy-control|runtime-endpoints)\.js[^"']*["'][^>]*>\s*<\/script>/g,'');
  html=html.replace(/<script type="module" src="js\/main\.js[^\"]*"><\/script>/,
    '<script src="/js/preferences.js"></script><script src="/js/simulation-controller.js"></script><script src="/js/tutorial-adapter.js"></script><script src="/js/lib/qrcode-generator-2.0.4.js"></script><script src="/js/admin-access.js"></script><script src="/js/account-security.js"></script><script src="/js/admin-control.js"></script><script src="/js/lib/livekit-client.umd.js"></script><script src="/js/camera-view.js"></script><script src="/js/workspace-session.js"></script><script type="module" src="/js/cloud-workspace.js"></script>');
  if(!html.includes('/js/cloud-workspace.js')||html.includes('src="js/main.js'))throw new Error('Cloud entry replacement failed');
  html=html.replace('<script defer src="js/i18n.js','<script defer src="/js/i18n-auth-catalog.js"></script><script defer src="/js/i18n-cloud-catalog.js"></script><script defer src="/js/i18n-history-catalog.js"></script><script defer src="js/i18n.js');
  html=html.replace('</head>','<link rel="stylesheet" href="/css/cloud-workspace.css"><link rel="stylesheet" href="/css/model-waypoints.css"></head>');
  return protectedHtml(isolateAssets(html),{publicOrigin});
}
function protectedHtml(html,{publicOrigin}={}){
  html=isolateAssets(html.replace(/\r\n?/g,'\n'));
  const importmap=/<script\b[^>]*\btype="importmap"[^>]*>([\s\S]*?)<\/script>/.exec(html);
  if(!importmap)throw new Error('Cloud import map missing');
  const hash=createHash('sha256').update(importmap[1]).digest('base64');
  // Existing workspace markup uses inline style attributes; no inline event handlers are allowed.
  let streamOrigin='';if(publicOrigin){const parsed=new URL(publicOrigin);if(parsed.protocol!=='https:'||parsed.origin!==publicOrigin)throw Error('Exact HTTPS workspace origin required');streamOrigin=' '+publicOrigin.replace(/^https:/,'wss:');}
  const csp=`default-src 'none'; script-src 'self' 'sha256-${hash}'; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; connect-src 'self'${streamOrigin}; media-src 'self' blob:; img-src 'self' data: blob:; font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`;
  return {html,csp};
}
async function serveWorkspacePage(request,response,pathname,options={}){
  pathname=assetPath(pathname);
  if(!['GET','HEAD'].includes(request.method)||!isWorkspacePath(pathname))return false;
  if(['/control','/history'].includes(pathname)){
    const source=await fsp.readFile(path.join(root,pathname==='/history'?'history.html':'index.html'),'utf8');
    const {html,csp}=pathname==='/history'?protectedHtml(source,options):workspaceHtml(source,options);
    response.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','Content-Security-Policy':csp});response.end(request.method==='HEAD'?undefined:html);return true;
  }
  const file=pathname.slice(1),model=modelFile.test(file),bundles={'js/lib/livekit-client.umd.js':()=>require.resolve('livekit-client'),'js/lib/livekit-frame-metadata.worker.mjs':()=>require.resolve('livekit-client/frame-metadata-worker')},filename=bundles[file]?bundles[file]():model?path.join(models,file.slice('models/'.length)):path.join(root,file);
  let stat;try{stat=await fsp.stat(filename);}catch(error){if(error.code==='ENOENT')return false;throw error;}
  if(!stat.isFile())return false;
  if(model&&stat.size<256){const content=await fsp.readFile(filename,'utf8');if(content.startsWith('version https://git-lfs.github.com')){
    response.writeHead(503,{'Content-Type':'application/json','Cache-Control':'no-store'});response.end(JSON.stringify({error:'MODEL_ASSET_NOT_RESTORED'}));return true;
  }}
  const extension=path.extname(filename).toLowerCase(),type={'.js':'text/javascript; charset=utf-8','.mjs':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.urdf':'application/xml; charset=utf-8','.stl':'model/stl'}[extension]||'application/octet-stream';
  response.writeHead(200,{'Content-Type':type,'Content-Length':stat.size,'Cache-Control':'no-store','Cross-Origin-Resource-Policy':'same-origin'});
  if(request.method==='HEAD')response.end();else{const stream=fs.createReadStream(filename);stream.on('error',()=>response.destroy());stream.pipe(response);}return true;
}
module.exports={isWorkspacePath,serveWorkspacePage,workspaceHtml};
