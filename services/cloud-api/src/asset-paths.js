'use strict';
const ASSET_PREFIX='/control-assets';
function assetPath(pathname){return pathname.startsWith(ASSET_PREFIX+'/')?pathname.slice(ASSET_PREFIX.length):pathname;}
function isolateAssets(html){return html.replace(/\b(src|href)=(['"])(?:\.\/|\/)?((?:js|css|models)\/[^'"]+)\2/g,(_,attribute,quote,file)=>`${attribute}=${quote}${ASSET_PREFIX}/${file}${quote}`).replace(/"\.\/js\//g,`"${ASSET_PREFIX}/js/`);}
module.exports={ASSET_PREFIX,assetPath,isolateAssets};
