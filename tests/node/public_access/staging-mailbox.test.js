'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs/promises'),os=require('node:os'),path=require('node:path');
const {createStagingMailbox}=require('../../../platform/identity/src/staging-mailbox');
const {identityFixture}=require('./identity-fixture');
const {createAccounts}=require('../../../platform/identity/src/accounts');

test('private staging mail accepts only explicitly listed synthetic recipients and never creates an unintended real account',async t=>{
  const directory=await fs.mkdtemp(path.join(os.tmpdir(),'thirdhand-stage-mail-'));
  t.after(()=>fs.rm(directory,{recursive:true,force:true}));
  const origin='https://staging.uiea-thirdhand.com';
  const mail=await createStagingMailbox({directory,publicOrigin:origin,allowedRecipients:['observer@example.invalid']});
  const f=await identityFixture(t),accounts=createAccounts({...f,mail,publicOrigin:origin});
  await assert.rejects(accounts.register({username:'real_person',email:'real@example.com',displayName:'Not accepted',password:f.password}),{code:'MAIL_UNAVAILABLE'});
  assert.equal((await f.pool.query('SELECT count(*) FROM auth.users')).rows[0].count,'0');
  const user=await accounts.register({username:'stage_observer',email:'observer@example.invalid',displayName:'Stage Observer',password:f.password});
  const files=await fs.readdir(directory);assert.equal(files.length,1);
  const message=JSON.parse(await fs.readFile(path.join(directory,files[0]),'utf8'));
  assert.equal(message.to,'observer@example.invalid');assert.equal(message.purpose,'verify_email');
  assert.equal(new URL(message.url).origin,origin);
  const token=new URLSearchParams(new URL(message.url).hash.slice(1)).get('token');
  await accounts.verifyEmail({token});
  assert.equal((await accounts.authenticate({login:'stage_observer',password:f.password})).userId,user.userId);
  assert.equal(Object.hasOwn(user,'token'),false);
  if(process.platform!=='win32')assert.equal((await fs.stat(path.join(directory,files[0]))).mode&0o777,0o600);
  await assert.rejects(mail.send({...message,url:'https://uiea-thirdhand.com/verify-email#token=unsafe'}),{code:'MAIL_UNAVAILABLE'});
});

test('test mailbox refuses a production origin, real recipient allowlists and relative directories',async()=>{
  for(const options of [
    {directory:os.tmpdir(),publicOrigin:'https://uiea-thirdhand.com',allowedRecipients:['observer@example.invalid']},
    {directory:os.tmpdir(),publicOrigin:'https://staging.uiea-thirdhand.com',allowedRecipients:['person@example.com']},
    {directory:'relative',publicOrigin:'https://staging.uiea-thirdhand.com',allowedRecipients:['observer@example.invalid']}
  ])await assert.rejects(createStagingMailbox(options),{code:'CONFIG_ERROR'});
});
