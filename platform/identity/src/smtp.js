'use strict';
const {identityError}=require('./errors');
const email=value=>typeof value==='string'&&/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)&&value.length<=254&&!/[<>,;:"\\()\[\]\u0000-\u001f\u007f]/.test(value);
function canonicalRecipient(value){
  if(typeof value!=='string'||/[\u0000-\u001f\u007f]/.test(value)||!email(value.trim()))throw identityError('INVALID_INPUT');
  return value.trim().toLowerCase();
}
function normalizeRecipients(value){
  if(!Array.isArray(value)||value.length<1||value.length>10)throw identityError('CONFIG_ERROR','Explicit SMTP recipients required');
  let normalized;try{normalized=value.map(canonicalRecipient);}catch{throw identityError('CONFIG_ERROR','Invalid SMTP recipient restriction');}
  if(new Set(normalized).size!==normalized.length)throw identityError('CONFIG_ERROR','Duplicate SMTP recipient restriction');
  return normalized;
}
function createSmtpMailer(config,createTransport=options=>require('nodemailer').createTransport(options)){
  if(!config||!email(config.from)||![465,587].includes(config.port))throw identityError('CONFIG_ERROR','Valid SMTP sender and TLS port required');
  const allowed=config.allowedRecipients===undefined?null:new Set(normalizeRecipients(config.allowedRecipients));
  const ensureAvailable=({to}={})=>{const recipient=canonicalRecipient(to);if(allowed&&!allowed.has(recipient))throw identityError('MAIL_UNAVAILABLE');return recipient;};
  const transporter=createTransport({host:config.host,port:config.port,secure:config.port===465,requireTLS:true,
    tls:{minVersion:'TLSv1.2',rejectUnauthorized:true},auth:{user:config.username,pass:config.password},
    pool:true,maxConnections:2,maxMessages:50,connectionTimeout:10000,greetingTimeout:10000,socketTimeout:15000,
    disableFileAccess:true,disableUrlAccess:true,maxRecipients:1,logger:false,debug:false,transactionLog:false});
  return {
    ensureAvailable,
    async send(message){
      if(!['verify_email','reset_password'].includes(message.purpose))throw identityError('INVALID_INPUT');
      const recipient=ensureAvailable({to:message.to});
      const url=new URL(message.url);if(url.protocol!=='https:')throw identityError('INVALID_INPUT');
      const verify=message.purpose==='verify_email',chinese=message.locale==='zh-CN';
      const subject=chinese?(verify?'验证 ThirdHand 邮箱':'重置 ThirdHand 密码'):(verify?'Verify your ThirdHand email':'Reset your ThirdHand password');
      const text=chinese?`${subject}\n\n${url.toString()}\n\n如非本人操作，请忽略此邮件。`:`${subject}\n\n${url.toString()}\n\nIf you did not request this, you can ignore this message.`;
      await transporter.sendMail({from:config.from,to:recipient,subject,text});
    },
    close(){transporter.close();}
  };
}
module.exports={createSmtpMailer,normalizeRecipients};
