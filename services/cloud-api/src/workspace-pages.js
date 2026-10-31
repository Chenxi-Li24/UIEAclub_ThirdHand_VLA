'use strict';
const fs=require('node:fs');
const fsp=require('node:fs/promises');
const path=require('node:path');
const {createHash}=require('node:crypto');
const {assetPath,isolateAssets}=require('./asset-paths');
const root=path.resolve(__dirname,'../../../apps/web/public'),models=path.resolve(__dirname,'../../../assets/robot');
const files=new Set([
  'css/auth.css','js/preferences.js','js/i18n.js','js/i18n-catalog.js','js/i18n-auth-catalog.js',
  'css/classic-source.css','js/classic-shell.js',
  'js/workspace-startup.js','js/model-resources.js','css/workspace-layouts.css',
  'js/model-waypoints.js','css/model-waypoints.css',
  'css/style.css','css/i18n.css','css/workspace.css','css/workspace-polish.css','css/onboarding.css','css/account-settings.css','css/workspace-surfaces.css','css/status-lights.css','css/cloud-workspace.css',
  'js/cloud-workspace.js','js/robot-viewer.js','js/workspace-session.js','js/simulation-controller.js','js/tutorial-adapter.js','js/camera-lighting.js','js/onboarding-spotlight.js','js/onboarding.js','js/account-settings.js','js/admin-access.js','js/account-security.js','js/admin-control.js','js/status-lights.js','js/workspace-shell.js',
  'js/i18n-voice-catalog.js','js/i18n-onboarding-catalog.js','js/i18n-account-catalog.js','js/i18n-status-catalog.js','js/i18n-cloud-catalog.js','js/history-page.js','js/history-dates.js','js/history-replay.js','js/i18n-history-catalog.js','css/history.css','js/camera-view.js','js/lib/livekit-frame-metadata.worker.mjs'
]);
const modelFile=/^models\/startouch-v3\/(?:FastTouchV3\.SLDASM\.urdf|web\/robot-visuals\.glb|meshes\/(?:base_link|link[1-5]|gripper_base|gripper_link[12])\.STL)$/;
const bundles={'js/lib/livekit-client.umd.js':()=>require.resolve('livekit-client'),'js/lib/livekit-frame-metadata.worker.mjs':()=>require.resolve('livekit-client/frame-metadata-worker')};
let releasePromise;const etags=new Map();
function filenameFor(file){return bundles[file]?bundles[file]():modelFile.test(file)?path.join(models,file.slice('models/'.length)):path.join(root,file);}
function assetRelease(){
  return releasePromise||=(async()=>{
    const names=new Set([...files,...Object.keys(bundles),'models/startouch-v3/FastTouchV3.SLDASM.urdf','models/startouch-v3/web/robot-visuals.glb']);
    for(const name of await fsp.readdir(path.join(root,'js/lib'),{recursive:true}))if(/\.(?:js|mjs)$/.test(name))names.add('js/lib/'+name.replaceAll('\\','/'));
    for(const name of ['base_link','link1','link2','link3','link4','link5','gripper_base','gripper_link1','gripper_link2'])names.add(`models/startouch-v3/meshes/${name}.STL`);
    const hash=createHash('sha256');
    for(const name of [...names].sort()){
      let raw;try{raw=await fsp.readFile(filenameFor(name));}catch(error){if(error.code==='ENOENT')continue;throw error;}
      const digest=createHash('sha256').update(raw).digest('hex');etags.set(name,`"${digest}"`);hash.update(name+'\0'+digest+'\n');
    }
    return hash.digest('hex').slice(0,32);
  })();
}
function isWorkspacePath(pathname){pathname=assetPath(pathname);const file=pathname.slice(1);return ['/control','/history'].includes(pathname)||files.has(file)||/^js\/lib\/(?:[a-zA-Z0-9_-]+\/)*[a-zA-Z0-9_.-]+\.js$/.test(file)||modelFile.test(file);}
function workspaceHtml(source,options={}){
  const {bootstrap,assetVersion}=options,prefs=bootstrap?.preferences||{};
  const classic=prefs.layoutId==='classic';
  // HTML parsing normalizes CRLF/CR before CSP hashes are checked in the browser.
  source=source.replace(/\r\n?/g,'\n');
  let html=source.replace(/<script\b[^>]*\bsrc=["']js\/(?:dummy-control|runtime-endpoints)\.js[^"']*["'][^>]*>\s*<\/script>/g,'');
  if(classic)html=html.replace('css/style.css','css/classic-source.css');
  if(classic)html=html.replace('<script defer src="js/i18n.js','<script defer src="/js/i18n-onboarding-catalog.js"></script><script defer src="/js/i18n-account-catalog.js"></script><script defer src="/js/i18n-status-catalog.js"></script><script defer src="js/i18n.js');
  html=html.replace(/<script type="module" src="js\/main\.js[^\"]*"><\/script>/,
    '<script src="/js/preferences.js"></script><script src="/js/simulation-controller.js"></script><script src="/js/tutorial-adapter.js"></script><script src="/js/lib/qrcode-generator-2.0.4.js"></script><script src="/js/admin-access.js"></script><script src="/js/account-security.js"></script><script src="/js/admin-control.js"></script><script src="/js/camera-view.js"></script><script src="/js/workspace-session.js"></script><script src="/js/workspace-startup.js"></script><script type="module" src="/js/cloud-workspace.js"></script>');
  if(!html.includes('/js/cloud-workspace.js')||html.includes('src="js/main.js'))throw new Error('Cloud entry replacement failed');
  if(classic)html=html.replace('<script src="/js/preferences.js">','<script src="/js/camera-lighting.js"></script><script src="/js/onboarding-spotlight.js"></script><script src="/js/onboarding.js"></script><script src="/js/account-settings.js"></script><script src="/js/status-lights.js"></script><script src="/js/classic-shell.js"></script><script src="/js/preferences.js">');
  html=html.replace('<script defer src="js/i18n.js','<script defer src="/js/i18n-auth-catalog.js"></script><script defer src="/js/i18n-cloud-catalog.js"></script><script defer src="/js/i18n-history-catalog.js"></script><script defer src="js/i18n.js');
  const locale=prefs.locale==='zh-CN'?'zh-CN':'en',layout=classic?'classic':'workspace',classicTheme=['deepspace','industrial','cyber','dark','green','blue','purple','orange','light'].includes(prefs.classicThemeId)?prefs.classicThemeId:'deepspace';
  const appearance=classic?(classicTheme==='light'?'light':'dark'):prefs.themeId==='dark'?'dark':'light';
  html=html.replace('<html lang="en">',`<html lang="${locale}" data-theme="${classic?classicTheme:'workspace'}" data-layout="${layout}" data-appearance="${appearance}" data-access-mode="${bootstrap?.identity?.mode==='admin'?'admin':'observe'}">`)
    .replace('<div id="app">',`<div id="app" class="${classic?'classic-console':'workspace'}" data-ready="false">`);
  const boot=JSON.stringify({...bootstrap,assetBase:'/control-assets'+(assetVersion?`/v${assetVersion}`:'')}).replace(/</g,'\\u003c');
  html=html.replace('</head>',(classic?'<link rel="stylesheet" href="/css/account-settings.css"><link rel="stylesheet" href="/css/status-lights.css"><link rel="stylesheet" href="/css/onboarding.css">':'')+'<link rel="stylesheet" href="/css/cloud-workspace.css"><link rel="stylesheet" href="/css/model-waypoints.css"><link rel="stylesheet" href="/css/workspace-layouts.css"></head>')
    .replace('<body>',`<body><script type="application/json" id="workspace-bootstrap">${boot}</script><div id="workspace-opening" role="status">${locale==='zh-CN'?'正在打开工作台…':'Opening workspace…'}</div>`);
  return protectedHtml(html,options);
}
function protectedHtml(html,{publicOrigin,assetVersion}={}){
  html=isolateAssets(html.replace(/\r\n?/g,'\n'),{version:assetVersion});
  const importmap=/<script\b[^>]*\btype="importmap"[^>]*>([\s\S]*?)<\/script>/.exec(html);
  if(!importmap)throw new Error('Cloud import map missing');
  const hash=createHash('sha256').update(importmap[1]).digest('base64');
  // Existing workspace markup uses inline style attributes; no inline event handlers are allowed.
  let streamOrigin='';if(publicOrigin){const parsed=new URL(publicOrigin);if(parsed.protocol!=='https:'||parsed.origin!==publicOrigin)throw Error('Exact HTTPS workspace origin required');streamOrigin=' '+publicOrigin.replace(/^https:/,'wss:');}
  const csp=`default-src 'none'; script-src 'self' 'wasm-unsafe-eval' 'sha256-${hash}'; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; connect-src 'self'${streamOrigin}; media-src 'self' blob:; img-src 'self' data: blob:; font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`;
  return {html,csp};
}
async function serveWorkspacePage(request,response,pathname,options={}){
  const version=await assetRelease(),requestedVersion=/^\/control-assets\/v([a-f0-9]{32})\//.exec(pathname)?.[1];
  if(requestedVersion&&requestedVersion!==version){response.writeHead(404,{'Cache-Control':'no-store'});response.end();return true;}
  pathname=assetPath(pathname);
  if(!['GET','HEAD'].includes(request.method)||!isWorkspacePath(pathname))return false;
  if(['/control','/history'].includes(pathname)){
    const source=await fsp.readFile(path.join(root,pathname==='/history'?'history.html':options.bootstrap?.preferences?.layoutId==='classic'?'classic.html':'index.html'),'utf8');
    const {html,csp}=pathname==='/history'?protectedHtml(source,{...options,assetVersion:version}):workspaceHtml(source,{...options,assetVersion:version});
    response.writeHead(200,{'Content-Type':'text/html; charset=utf-8','Cache-Control':'no-store','Content-Security-Policy':csp});response.end(request.method==='HEAD'?undefined:html);return true;
  }
  const file=pathname.slice(1),model=modelFile.test(file);let filename=filenameFor(file);
  let stat;try{stat=await fsp.stat(filename);}catch(error){if(error.code==='ENOENT')return false;throw error;}
  if(!stat.isFile())return false;
  if(model&&stat.size<256){const content=await fsp.readFile(filename,'utf8');if(content.startsWith('version https://git-lfs.github.com')){
    response.writeHead(503,{'Content-Type':'application/json','Cache-Control':'no-store'});response.end(JSON.stringify({error:'MODEL_ASSET_NOT_RESTORED'}));return true;
  }}
  const extension=path.extname(filename).toLowerCase(),type={'.js':'text/javascript; charset=utf-8','.mjs':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.urdf':'application/xml; charset=utf-8','.stl':'model/stl','.glb':'model/gltf-binary'}[extension]||'application/octet-stream';
  let encoding;
  if(extension==='.glb'&&(request.headers['accept-encoding']||'').split(',').some(value=>/^\s*gzip\s*(?:;\s*q=(?!0(?:\.0*)?\s*$)[\d.]+)?\s*$/.test(value))){
    try{const compressed=await fsp.stat(filename+'.gz');if(compressed.size<256)throw Error('Compressed model not restored');filename+='.gz';stat=compressed;encoding='gzip';}catch(error){if(error.code!=='ENOENT')throw error;}
  }
  const cache=requestedVersion?'private, max-age=31536000, immutable':'no-store',etag=etags.get(file)?.replace(/"$/,encoding?'-gzip"':'"');
  const headers={'Content-Type':type,'Cache-Control':cache,'Cross-Origin-Resource-Policy':'same-origin',Vary:'Accept-Encoding',...(encoding?{'Content-Encoding':encoding}:{}),...(etag?{ETag:etag}:{})};
  if(requestedVersion&&etag&&request.headers['if-none-match']===etag){response.writeHead(304,headers);response.end();return true;}
  response.writeHead(200,{...headers,'Content-Length':stat.size});
  if(request.method==='HEAD')response.end();else{const stream=fs.createReadStream(filename);stream.on('error',()=>response.destroy());stream.pipe(response);}return true;
}
module.exports={isWorkspacePath,serveWorkspacePage,workspaceHtml};
