'use strict';
// Test-only delivery. No HTTP reader, external recipients or SMTP fallback.
const fs=require('node:fs/promises'),path=require('node:path');
const {randomUUID}=require('node:crypto');
const fail=code=>Object.assign(Error(code),{code});
async function createStagingMailbox({directory,publicOrigin,allowedRecipients}){
  if(publicOrigin!=='https://staging.uiea-thirdhand.com'||!path.isAbsolute(directory||'')||
    !Array.isArray(allowedRecipients)||!allowedRecipients.length||allowedRecipients.length>10||
    !allowedRecipients.every(x=>typeof x==='string'&&/^[a-z0-9_.-]{1,64}@example\.invalid$/.test(x)))throw fail('CONFIG_ERROR');
  await fs.mkdir(directory,{recursive:true,mode:0o700});
  const stat=await fs.lstat(directory);
  if(!stat.isDirectory()||stat.isSymbolicLink()||process.platform!=='win32'&&(stat.mode&0o077||stat.uid!==process.getuid()))throw fail('CONFIG_ERROR');
  const allowed=new Set(allowedRecipients);
  function ensureAvailable({to}={}){if(to!==undefined&&!allowed.has(String(to).trim().toLowerCase()))throw fail('MAIL_UNAVAILABLE');}
  return {ensureAvailable,async send(message){
    ensureAvailable({to:message.to});
    let url;try{url=new URL(message.url);}catch{throw fail('MAIL_UNAVAILABLE');}
    if(!['verify_email','reset_password'].includes(message.purpose)||url.origin!==publicOrigin||
      url.pathname!==(message.purpose==='verify_email'?'/verify-email':'/reset-password')||
      !/^#token=[A-Za-z0-9_-]{43}$/.test(url.hash)||url.search||!allowed.has(message.to))throw fail('MAIL_UNAVAILABLE');
    if((await fs.readdir(directory)).length>=500)throw fail('MAIL_UNAVAILABLE');
    const handle=await fs.open(path.join(directory,randomUUID()+'.json'),'wx',0o600);
    try{await handle.writeFile(JSON.stringify({to:message.to,purpose:message.purpose,locale:message.locale,url:url.toString()}));await handle.sync();}
    finally{await handle.close();}
  }};
}
module.exports={createStagingMailbox};
