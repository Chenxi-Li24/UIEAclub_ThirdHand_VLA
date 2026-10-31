'use strict';
const fs=require('node:fs/promises');
const path=require('node:path');
const {assetPath,isolateAssets}=require('./asset-paths');
const publicRoot=path.resolve(__dirname,'../../../apps/web/public');
const pages=['login','register','forgot-password','reset-password','verify-email'];
const files=new Map(pages.flatMap(name=>[[`/${name}`,`${name}.html`],[`/${name}.html`,`${name}.html`]]));
for(const file of ['css/auth.css','js/i18n-catalog.js','js/i18n-auth-catalog.js','js/i18n.js','js/preferences.js','js/auth-page.js'])files.set(`/${file}`,file);
const CSP="default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'";
async function serveAuthPage(request,response,pathname){
  pathname=assetPath(pathname);
  if(!['GET','HEAD'].includes(request.method)||!files.has(pathname))return false;
  const file=files.get(pathname),original=await fs.readFile(path.join(publicRoot,file)),bytes=file.endsWith('.html')?Buffer.from(isolateAssets(original.toString('utf8'))):original;
  const type=file.endsWith('.html')?'text/html':file.endsWith('.css')?'text/css':'text/javascript';
  response.writeHead(200,{'Content-Type':`${type}; charset=utf-8`,'Content-Length':bytes.length,'Cache-Control':'no-store','Content-Security-Policy':CSP,'Cross-Origin-Resource-Policy':'same-origin'});
  response.end(request.method==='HEAD'?undefined:bytes);return true;
}
module.exports={serveAuthPage};
