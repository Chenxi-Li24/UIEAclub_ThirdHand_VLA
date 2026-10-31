'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { parseHTML } = require('linkedom');
const { mountAuthPage } = require('../../../apps/web/public/js/auth-page');
const { createPreferenceClient } = require('../../../apps/web/public/js/preferences');

function fixture(page='login', saved=null, hash='') {
  const { document,window }=parseHTML(fs.readFileSync(path.join(__dirname,`../../../apps/web/public/${page}.html`),'utf8'));
  const stored=new Map(saved||[]), calls=[], navigations=[], timers=new Map();
  let timerId=0;
  const view={document,localStorage:{getItem:key=>stored.get(key)||null,setItem:(key,value)=>stored.set(key,value),removeItem:key=>stored.delete(key)},addEventListener(){},removeEventListener(){},location:{hash},history:{replaceState(){}},setTimeout(fn,delay){timers.set(++timerId,{fn,delay});return timerId;},clearTimeout(id){timers.delete(id);}};
  const context=vm.createContext({document,localStorage:view.localStorage,MutationObserver:window.MutationObserver});
  for(const file of ['i18n-catalog.js','i18n-auth-catalog.js','i18n.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../../../apps/web/public/js',file),'utf8'),context);
  view.ThirdHandI18n=context.ThirdHandI18n;
  const preferences=createPreferenceClient({view});
  let response={error:'ADMIN_PERMISSION_REQUIRED'};
  const request=async(route,body)=>{calls.push({route,body}); if(response.error)throw Object.assign(Error(),{code:response.error});return response;};
  const mounted=mountAuthPage(document,view,{preferences,request,navigate:path=>navigations.push(path)});
  return {document,window,view,stored,calls,navigations,timers,mounted,setResponse:value=>response=value};
}

test('verification page without a token offers an explicit resend form with a generic confirmation',async()=>{
  const f=fixture('verify-email');await f.mounted.ready;
  assert.ok(f.document.getElementById('email'));
  f.document.getElementById('email').value='pending@example.invalid';f.setResponse({accepted:true});await f.mounted.submit();
  assert.equal(f.calls[0].route,'/api/v1/auth/resend-verification');
  assert.match(f.document.getElementById('auth-message').textContent,/If this account needs verification/);
});

test('new login always selects Observer and admin permission feedback appears only after submitting credentials', async () => {
  const f=fixture(); await f.mounted.ready;
  assert.equal(f.document.documentElement.lang,'en'); assert.equal(f.document.documentElement.dataset.appearance,'light');
  assert.equal(f.document.getElementById('mode-observe').getAttribute('aria-selected'),'true');
  f.document.getElementById('mode-admin').click(); assert.equal(f.calls.length,0);
  f.document.getElementById('login').value='example';f.document.getElementById('password').value='Long test passphrase';
  await f.mounted.submit(); assert.equal(f.calls[0].body.requestedMode,'admin');
  assert.match(f.document.getElementById('auth-message').textContent,/does not have administrator access/i);
  f.document.getElementById('switch-observer').click();
  assert.equal(f.document.getElementById('mode-observe').getAttribute('aria-selected'),'true');
  assert.equal(fixture().document.getElementById('mode-observe').getAttribute('aria-selected'),'true');
  assert.ok(![...f.stored.keys()].some(key=>/password|token|mode/.test(key)));
});

test('password visibility, MFA retry and language/theme switching preserve fields without storing secrets', async () => {
  const f=fixture();await f.mounted.ready;
  const password=f.document.getElementById('password');password.value='Private test password';
  f.document.getElementById('toggle-password').click();assert.equal(password.type,'text');
  f.document.getElementById('locale-zh').click();assert.equal(f.document.documentElement.lang,'zh-CN');
  assert.equal(password.value,'Private test password');
  f.document.getElementById('theme-toggle').click();assert.equal(f.document.documentElement.dataset.appearance,'dark');
  f.document.getElementById('mode-admin').click();f.setResponse({error:'MFA_REQUIRED'});await f.mounted.submit();
  assert.equal(f.document.getElementById('mfa-fields').hidden,false);
  assert.ok(!JSON.stringify([...f.stored]).includes('Private test password'));
});

test('registration checks confirmation and never offers administrator self-registration', async () => {
  const f=fixture('register');await f.mounted.ready;
  assert.equal(f.document.querySelector('[name="role"]'),null);
  for(const [id,value]of Object.entries({username:'new_user',email:'new@example.invalid',displayName:'New User',password:'Long test passphrase',confirmPassword:'Mismatch'}))f.document.getElementById(id).value=value;
  await f.mounted.submit();assert.equal(f.calls.length,0);assert.match(f.document.getElementById('auth-message').textContent,/match/i);
  f.document.getElementById('confirmPassword').value='Long test passphrase';f.setResponse({status:'pending_email'});
  await f.mounted.submit();assert.equal(f.calls[0].route,'/api/v1/auth/register');assert.equal(f.calls[0].body.role,undefined);
  assert.match(f.document.getElementById('auth-message').textContent,/email/i);assert.equal(f.document.getElementById('password').value,'');
});

test('registration labels and placeholders use the selected language with the actual shared translator',async()=>{
  const f=fixture('register');await f.mounted.ready;f.document.getElementById('locale-zh').click();
  assert.equal(f.document.getElementById('displayName').getAttribute('placeholder'),'显示名称');
  assert.match(f.document.querySelector('label[for="displayName"]').textContent,/显示名称/);
  assert.equal(f.document.getElementById('auth-title').textContent,'创建账号');
});

test('new password feedback updates live and rechecks confirmation when the original changes',async()=>{
  const f=fixture('register'),password=f.document.getElementById('password'),confirm=f.document.getElementById('confirmPassword');
  const input=(field,value)=>{field.value=value;field.dispatchEvent(new f.window.Event('input'));};
  input(password,'short');
  assert.equal(password.getAttribute('aria-invalid'),'true');
  assert.match(f.document.getElementById('password-feedback').textContent,/at least 12/i);
  assert.match(password.getAttribute('aria-describedby'),/password-requirements/);
  assert.match(f.document.getElementById('password-requirements').textContent,/12–128/);
  input(password,'long enough password');input(confirm,'different password');
  assert.match(f.document.getElementById('confirmPassword-feedback').textContent,/do not match/i);
  input(confirm,'long enough password');assert.equal(confirm.getAttribute('aria-invalid'),'false');
  input(password,'another long password');assert.equal(confirm.getAttribute('aria-invalid'),'true');
  assert.match(f.document.getElementById('confirmPassword-feedback').textContent,/do not match/i);
  f.document.getElementById('locale-zh').click();
  assert.match(f.document.getElementById('confirmPassword-feedback').textContent,/不一致/);
  assert.match(f.document.getElementById('password-requirements').textContent,/密码要求/);
  assert.ok(!JSON.stringify([...f.stored]).includes('another long password'));
});

test('new passwords enforce server Unicode length boundaries before a request',async()=>{
  for(const page of ['register','reset-password']){
    const f=fixture(page,null,'#token=unit-test-token');f.setResponse({status:'pending_email'});
    for(const id of ['password','confirmPassword'])f.document.getElementById(id).value='😀'.repeat(129);
    await f.mounted.submit();assert.equal(f.calls.length,0);
    assert.match(f.document.getElementById('password-feedback').textContent,/at most 128/i);
    for(const id of ['password','confirmPassword'])f.document.getElementById(id).value='😀'.repeat(128);
    await f.mounted.submit();assert.equal(f.calls.length,1);
    assert.equal(f.calls[0].body.password,'😀'.repeat(128));
    assert.equal(f.document.getElementById('password-feedback').textContent,'');
  }
});

test('successful email verification shows confirmation before one automatic sign-in redirect',async()=>{
  const f=fixture('verify-email',null,'#token=unit-test-token');f.setResponse({verified:true});
  await f.mounted.submit();
  assert.match(f.document.getElementById('auth-message').textContent,/verified.*redirecting/i);
  assert.equal(f.navigations.length,0);assert.equal(f.timers.size,1);
  await f.mounted.submit();assert.equal(f.calls.length,1);
  const timer=[...f.timers.values()][0];assert.equal(timer.delay,2000);timer.fn();
  assert.deepEqual(f.navigations,['/login']);
});

test('verification failure and resend never redirect, and disposal cancels a successful redirect',async()=>{
  const failed=fixture('verify-email',null,'#token=expired');failed.setResponse({error:'INVALID_TOKEN'});
  await failed.mounted.submit();assert.equal(failed.timers.size,0);assert.match(failed.document.getElementById('auth-message').textContent,/invalid or expired/i);
  const resend=fixture('verify-email');resend.setResponse({accepted:true});resend.document.getElementById('email').value='test@example.invalid';
  await resend.mounted.submit();assert.equal(resend.timers.size,0);
  const disposed=fixture('verify-email',null,'#token=unit-test-token');disposed.setResponse({verified:true});
  await disposed.mounted.submit();disposed.mounted.dispose();assert.equal(disposed.timers.size,0);assert.deepEqual(disposed.navigations,[]);
});
