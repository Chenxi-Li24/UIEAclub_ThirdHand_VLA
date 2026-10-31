'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {randomBytes}=require('node:crypto');
const {loadCloudConfig}=require('../../../services/cloud-api/src/config');
function environment(){return {PUBLIC_ORIGIN:'https://uiea-thirdhand.com',IDENTITY_DATABASE_URL:'postgresql://test@127.0.0.1/thirdhand_test',CSRF_KEY_BASE64:randomBytes(32).toString('base64'),MFA_KEY_BASE64:randomBytes(32).toString('base64')};}
test('cloud configuration has no default secrets and binds only the private reverse-proxy interface',()=>{
  assert.throws(()=>loadCloudConfig({}),/PUBLIC_ORIGIN|IDENTITY_DATABASE_URL|CSRF/);
  const env=environment(),config=loadCloudConfig(env);assert.equal(config.host,'127.0.0.1');assert.equal(config.port,3200);assert.equal(config.smtp,null);
  assert.throws(()=>loadCloudConfig({...env,CSRF_KEY_BASE64:env.MFA_KEY_BASE64}),/independent/i);
  assert.throws(()=>loadCloudConfig({...env,CLOUD_BIND_HOST:'0.0.0.0'}),/loopback/i);
  assert.throws(()=>loadCloudConfig({...env,PUBLIC_ORIGIN:'http://uiea-thirdhand.com'}),/HTTPS/i);
  assert.throws(()=>loadCloudConfig({...env,SMTP_HOST:'smtp.example.invalid',SMTP_FROM:'sender@example.invalid'}),/SMTP_USER|SMTP_PASSWORD/);
});

test('staging SMTP must declare a valid explicit recipient list before enabling real delivery',()=>{
  const env={...environment(),PUBLIC_ORIGIN:'https://staging.uiea-thirdhand.com',SMTP_HOST:'smtp.example.invalid',SMTP_PORT:'465',SMTP_USER:'sender@example.invalid',SMTP_FROM:'sender@example.invalid',SMTP_PASSWORD:'test-only'};
  assert.throws(()=>loadCloudConfig(env),{code:'CONFIG_ERROR'});
  for(const value of ['invalid','[]','{}','["first,reviewer@example.invalid"]'])assert.throws(()=>loadCloudConfig({...env,SMTP_ALLOWED_RECIPIENTS_JSON:value}),{code:'CONFIG_ERROR'});
  const config=loadCloudConfig({...env,SMTP_ALLOWED_RECIPIENTS_JSON:'["Reviewer@example.invalid"]'});
  assert.deepEqual(config.smtp.allowedRecipients,['reviewer@example.invalid']);
});

test('explicit open registration permits any recipient despite an old staging list',()=>{
  const env={...environment(),PUBLIC_ORIGIN:'https://staging.uiea-thirdhand.com',REGISTRATION_MODE:'open',SMTP_HOST:'smtp.example.invalid',SMTP_PORT:'465',SMTP_USER:'sender@example.invalid',SMTP_FROM:'sender@example.invalid',SMTP_PASSWORD:'test-only'};
  assert.equal(loadCloudConfig({...env,SMTP_ALLOWED_RECIPIENTS_JSON:'["old@example.invalid"]'}).smtp.allowedRecipients,undefined);
  assert.equal(loadCloudConfig(env).smtp.allowedRecipients,undefined);
  assert.throws(()=>loadCloudConfig({...env,REGISTRATION_MODE:'anything'}),{code:'CONFIG_ERROR'});
});
