'use strict';
const ASSET_PREFIX='/control-assets';
function assetPath(pathname){return pathname.startsWith(ASSET_PREFIX+'/')?pathname.slice(ASSET_PREFIX.length).replace(/^\/v[a-f0-9]{32}(?=\/)/,''):pathname;}
function isolateAssets(html,{version}={}){
  const prefix=ASSET_PREFIX+(version?`/v${version}`:'');
  return html.replace(/\b(src|href)=(['"])(?:\.\/|\/)?((?:js|css|models)\/[^'"]+)\2/g,(_,attribute,quote,file)=>`${attribute}=${quote}${prefix}/${file}${quote}`).replace(/"\.\/js\//g,`"${prefix}/js/`);
}
module.exports={ASSET_PREFIX,assetPath,isolateAssets};
