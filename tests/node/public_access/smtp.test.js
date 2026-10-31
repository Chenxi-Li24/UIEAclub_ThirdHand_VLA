'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createSmtpMailer}=require('../../../platform/identity/src/smtp');
test('mail is formatted as one text recipient with TLS and no filesystem or URL content access',async()=>{
  let options;const sent=[];
  const mail=createSmtpMailer({host:'smtp.example.invalid',port:587,username:'test-only',password:'test-only',from:'sender@example.invalid'},settings=>{options=settings;return {sendMail:async message=>sent.push(message),close(){}};});
  await mail.send({purpose:'verify_email',to:'recipient@example.invalid',url:'https://thirdhand.example.invalid/verify-email#token=test',locale:'en'});
  assert.equal(options.requireTLS,true);assert.equal(options.tls.rejectUnauthorized,true);assert.equal(options.disableFileAccess,true);assert.equal(options.disableUrlAccess,true);assert.equal(options.logger,false);assert.equal(options.debug,false);
  assert.equal(sent[0].to,'recipient@example.invalid');assert.equal(sent[0].from,'sender@example.invalid');assert.match(sent[0].text,/verify-email#token=test/);assert.equal(sent[0].html,undefined);
  await assert.rejects(mail.send({purpose:'verify_email',to:'recipient@example.invalid\r\nBcc: other@example.invalid',url:'https://example.invalid'}),{code:'INVALID_INPUT'});assert.equal(sent.length,1);
});

test('a staged real SMTP recipient restriction rejects registration before database work and blocks unintended deliveries',async()=>{
  const {createAccounts}=require('../../../platform/identity/src/accounts');
  const sent=[];let options;
  const mail=createSmtpMailer({host:'smtp.example.invalid',port:465,username:'sender@example.invalid',password:'test-only',from:'sender@example.invalid',allowedRecipients:['reviewer@example.invalid']},value=>{options=value;return {sendMail:async message=>sent.push(message),close(){}};});
  const accounts=createAccounts({pool:{query(){throw Error('Unexpected database work');}},mail,publicOrigin:'https://staging.uiea-thirdhand.com'});
  await assert.rejects(accounts.register({email:'unapproved@example.invalid'}),{code:'MAIL_UNAVAILABLE'});
  await assert.rejects(mail.send({purpose:'verify_email',to:'unapproved@example.invalid',url:'https://staging.uiea-thirdhand.com/verify-email#token=test'}),{code:'MAIL_UNAVAILABLE'});
  await mail.send({purpose:'verify_email',to:'Reviewer@example.invalid',url:'https://staging.uiea-thirdhand.com/verify-email#token=test',locale:'en'});
  assert.equal(options.secure,true);assert.equal(options.port,465);assert.equal(sent.length,1);assert.equal(sent[0].to,'reviewer@example.invalid');
});

test('SMTP requires bare single addresses and rejects empty or malformed recipient restrictions',async()=>{
  const config={host:'smtp.example.invalid',port:465,username:'sender@example.invalid',password:'test-only',from:'sender@example.invalid'};
  const transport=()=>({sendMail:async()=>{},close(){}});
  for(const allowedRecipients of [[],['reviewer@example.invalid','reviewer@example.invalid'],['first,reviewer@example.invalid'],['reviewer@example.invalid\r\nBcc:other@example.invalid']])assert.throws(()=>createSmtpMailer({...config,allowedRecipients},transport),{code:'CONFIG_ERROR'});
  const mail=createSmtpMailer(config,transport);
  await assert.rejects(mail.send({purpose:'verify_email',to:'first,reviewer@example.invalid',url:'https://staging.uiea-thirdhand.com/verify-email#token=test'}),{code:'INVALID_INPUT'});
});
