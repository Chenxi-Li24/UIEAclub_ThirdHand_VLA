'use strict';
const {identityError}=require('../../../platform/identity/src/errors');
const {createHmac,createPrivateKey}=require('node:crypto');
const path=require('node:path');
const {normalizeRecipients}=require('../../../platform/identity/src/smtp');
function invalid(message){throw identityError('CONFIG_ERROR',message);}
function key(value,name){if(typeof value!=='string'||!/^[A-Za-z0-9+/]{43}=$/.test(value))invalid(`${name} must be a 32-byte base64 secret`);const bytes=Buffer.from(value,'base64');if(bytes.length!==32)invalid(`${name} must be a 32-byte base64 secret`);return bytes;}
function loadMediaConfig(env){
  const names=['MEDIA_ENABLED','MEDIA_EDGE_SOCKET_PATH','MEDIA_API_HOST','MEDIA_API_KEY','MEDIA_API_SECRET','MEDIA_SIGNING_KEY_ID','MEDIA_SIGNING_KEY_BASE64','MEDIA_MAX_VIEWERS'];
  if(!names.some(name=>env[name]!==undefined))return null;
  if(env.MEDIA_ENABLED!=='1'||names.some(name=>typeof env[name]!=='string'||!env[name]))invalid('Camera media requires the complete explicit configuration');
  if(!/^\/run\/thirdhand(?:-stage)?-edge\/edge\.sock$/.test(env.MEDIA_EDGE_SOCKET_PATH))invalid('Media relay requires its dedicated runtime Unix socket');
  if(env.MEDIA_API_HOST!=='http://127.0.0.1:7880')invalid('Media API must remain on its private loopback endpoint');
  if(!/^[A-Za-z0-9_-]{16,80}$/.test(env.MEDIA_API_KEY)||!/^[A-Za-z0-9_-]{32,128}$/.test(env.MEDIA_API_SECRET))invalid('Independent media API credentials are required');
  if(!/^[A-Za-z0-9_-]{1,48}$/.test(env.MEDIA_SIGNING_KEY_ID))invalid('Invalid media signing key identifier');
  let privateKey;try{
    const value=env.MEDIA_SIGNING_KEY_BASE64,bytes=Buffer.from(value,'base64');
    if(bytes.toString('base64')!==value)throw Error();
    privateKey=createPrivateKey({key:bytes,format:'der',type:'pkcs8'});
    if(privateKey.asymmetricKeyType!=='ed25519')throw Error();
  }catch{invalid('A separate Ed25519 camera lease signing key is required');}
  const maxViewers=Number(env.MEDIA_MAX_VIEWERS);if(!Number.isInteger(maxViewers)||maxViewers<1||maxViewers>10)invalid('Media viewer limit must be between 1 and 10');
  return {socketPath:env.MEDIA_EDGE_SOCKET_PATH,host:env.MEDIA_API_HOST,apiKey:env.MEDIA_API_KEY,apiSecret:env.MEDIA_API_SECRET,keyId:env.MEDIA_SIGNING_KEY_ID,privateKey,maxViewers};
}
function loadCloudConfig(env=process.env){
  let publicOrigin;try{const url=new URL(env.PUBLIC_ORIGIN);if(url.protocol!=='https:'||url.username||url.password||url.pathname!=='/'||url.search||url.hash)throw Error();publicOrigin=url.origin;}catch{invalid('PUBLIC_ORIGIN must be an HTTPS origin');}
  let databaseUrl;try{databaseUrl=new URL(env.IDENTITY_DATABASE_URL);if(!['postgresql:','postgres:'].includes(databaseUrl.protocol)||!databaseUrl.hostname||databaseUrl.pathname.length<2)throw Error();}catch{invalid('IDENTITY_DATABASE_URL is required');}
  const csrfKey=key(env.CSRF_KEY_BASE64,'CSRF_KEY_BASE64'),mfaKey=key(env.MFA_KEY_BASE64,'MFA_KEY_BASE64');
  if(csrfKey.equals(mfaKey))invalid('CSRF and MFA keys must be independent');
  const mfaKeyId=env.MFA_KEY_ID||'v1';if(!/^[a-zA-Z0-9_-]{1,48}$/.test(mfaKeyId))invalid('Invalid MFA_KEY_ID');
  const host=env.CLOUD_BIND_HOST||'127.0.0.1';if(!['127.0.0.1','::1'].includes(host))invalid('Cloud API must bind to a loopback reverse-proxy interface');
  const port=env.CLOUD_PORT===undefined?3200:Number(env.CLOUD_PORT);if(!Number.isInteger(port)||port<1024||port>65535)invalid('Invalid CLOUD_PORT');
  const registrationMode=env.REGISTRATION_MODE||'restricted';
  if(!['open','restricted'].includes(registrationMode))invalid('REGISTRATION_MODE must be open or restricted');
  let smtp=null;
  if(env.SMTP_HOST){
    if(!/^[a-zA-Z0-9.-]+$/.test(env.SMTP_HOST))invalid('SMTP_HOST must be a hostname');
    if(!env.SMTP_USER||!env.SMTP_PASSWORD)invalid('SMTP_USER and SMTP_PASSWORD are required');
    const smtpPort=Number(env.SMTP_PORT||587);if(![465,587].includes(smtpPort))invalid('SMTP_PORT must use TLS 465 or STARTTLS 587');
    if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(env.SMTP_FROM||''))invalid('SMTP_FROM is required');
    smtp={host:env.SMTP_HOST,port:smtpPort,username:env.SMTP_USER,password:env.SMTP_PASSWORD,from:env.SMTP_FROM};
    if(registrationMode==='restricted'&&publicOrigin==='https://staging.uiea-thirdhand.com'&&!env.SMTP_ALLOWED_RECIPIENTS_JSON)invalid('Staging SMTP requires explicit recipients');
    if(registrationMode==='restricted'&&env.SMTP_ALLOWED_RECIPIENTS_JSON!==undefined){
      let recipients;try{recipients=JSON.parse(env.SMTP_ALLOWED_RECIPIENTS_JSON);}catch{invalid('Invalid SMTP_ALLOWED_RECIPIENTS_JSON');}
      smtp.allowedRecipients=normalizeRecipients(recipients);
    }
  }
  const exportRoot=env.EXPORT_PRIVATE_DIRECTORY||null;if(exportRoot&&!path.isAbsolute(exportRoot))invalid('EXPORT_PRIVATE_DIRECTORY must be absolute');
  // A domain-separated subkey is not reused for cookies, MFA, or device signing.
  const historyCursorKey=createHmac('sha256',csrfKey).update('thirdhand/history-cursor/v1').digest();
  const media=loadMediaConfig(env);
  if(media&&env.TRUST_PROXY_LOOPBACK!=='1')invalid('Camera signalling requires the trusted loopback reverse proxy');
  let deviceRuntime=null;
  const deviceNames=['DEVICE_TELEMETRY_ENABLED','DEVICE_CONTROL_ENABLED','DEVICE_CONTROL_KEY_ID','DEVICE_CONTROL_KEY_BASE64'];
  if(deviceNames.some(name=>env[name]!==undefined)){
    if(!media||env.DEVICE_TELEMETRY_ENABLED!=='1'||!['0','1'].includes(env.DEVICE_CONTROL_ENABLED))invalid('Device runtime requires media and explicit telemetry/control switches');
    let control=null;
    if(env.DEVICE_CONTROL_ENABLED==='1'){
      if(!/^[A-Za-z0-9_-]{1,48}$/.test(env.DEVICE_CONTROL_KEY_ID||''))invalid('Invalid device control key identifier');
      let privateKey;try{const bytes=Buffer.from(env.DEVICE_CONTROL_KEY_BASE64||'','base64');if(bytes.toString('base64')!==env.DEVICE_CONTROL_KEY_BASE64)throw Error();privateKey=createPrivateKey({key:bytes,format:'der',type:'pkcs8'});if(privateKey.asymmetricKeyType!=='ed25519'||privateKey.export({format:'der',type:'pkcs8'}).equals(media.privateKey.export({format:'der',type:'pkcs8'})))throw Error();}catch{invalid('Independent Ed25519 control signing key required');}
      control={keyId:env.DEVICE_CONTROL_KEY_ID,privateKey};
    }else if(env.DEVICE_CONTROL_KEY_ID!==undefined||env.DEVICE_CONTROL_KEY_BASE64!==undefined)invalid('Disabled control must not load a signing key');
    deviceRuntime={telemetry:true,control};
  }
  return {publicOrigin,databaseUrl:databaseUrl.toString(),csrfKey,mfaKeyId,mfaKeys:new Map([[mfaKeyId,mfaKey]]),historyCursorKey,exportRoot,host,port,smtp,media,deviceRuntime,production:env.NODE_ENV==='production',trustProxyLoopback:env.TRUST_PROXY_LOOPBACK==='1'};
}
module.exports={loadCloudConfig};
