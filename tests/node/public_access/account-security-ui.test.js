'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {parseHTML}=require('linkedom');
const {mountAccountSecurity}=require('../../../apps/web/public/js/account-security');
const qrcode=require('../../../apps/web/public/js/lib/qrcode-generator-2.0.4'),jsQR=require('jsqr');
test('administrator enrollment displays a one-time key and recovery codes without browser persistence',async()=>{
  const {document,window}=parseHTML('<section id="page-account-profile"></section>');const calls=[];
  const uri='otpauth://totp/ThirdHand:test?secret=JBSWY3DPEHPK3PXP&issuer=ThirdHand';
  const client={request:async(path,body)=>{calls.push({path,body});return path.endsWith('/prepare')?{enrolled:false,uri}:{recoveryCodes:Array.from({length:10},(_,i)=>String(i).padStart(32,'a'))};}};
  const api=mountAccountSecurity({document,view:{qrcode,location:{reload(){}}},identity:{userId:'admin-user',role:'admin',mode:'observe'},sessionClient:client});
  assert.ok(document.getElementById('security-code-field').hidden);
  assert.ok(document.getElementById('mfa-enrollment').hidden);
  document.getElementById('security-password').value='Private test password';await api.beginEnrollment();
  assert.equal(calls[0].path,'/api/v1/mfa/prepare');assert.equal(calls[0].body.password,'Private test password');assert.equal(document.getElementById('mfa-secret').value,'JBSWY3DPEHPK3PXP');
  assert.equal(document.getElementById('security-code-field').hidden,false);
  assert.equal(document.querySelector('label[for="security-password"]').hidden,true,'Password step must disappear after verification');
  const svg=document.querySelector('#mfa-qr svg');assert.ok(svg,'QR must be available after password verification');
  const size=Number(svg.getAttribute('viewBox').split(' ')[2]),scale=5,width=size*scale,pixels=new Uint8ClampedArray(width*width*4).fill(255);
  for(const rect of svg.querySelectorAll('rect[fill="#000"]'))for(let y=Number(rect.getAttribute('y'))*scale;y<(Number(rect.getAttribute('y'))+1)*scale;y++)for(let x=Number(rect.getAttribute('x'))*scale;x<(Number(rect.getAttribute('x'))+1)*scale;x++){const i=(y*width+x)*4;pixels[i]=pixels[i+1]=pixels[i+2]=0;}
  assert.equal(jsQR(pixels,width,width).data,uri,'Independent decoder must recover the complete authenticator URI');
  document.getElementById('security-totp').value='123456';await api.confirmEnrollment();
  assert.equal(document.getElementById('mfa-secret').value,'');assert.equal(document.getElementById('security-password').value,'');assert.equal(document.getElementById('mfa-recovery-codes').value.split('\n').length,10);
  assert.equal(document.querySelector('#mfa-qr svg'),null);
  assert.equal(document.querySelector('label[for="security-password"]').hidden,true,'Saving recovery codes must not ask for a password');
  assert.equal(document.getElementById('security-code-field').hidden,true);
  document.getElementById('mfa-recovery-continue').click();
  assert.equal(document.getElementById('mfa-recovery-codes').hidden,true);
  assert.equal(document.getElementById('mfa-recovery-codes').value,'');
  assert.equal(document.querySelector('label[for="security-password"]').hidden,false);
  assert.equal(document.getElementById('admin-user-directory'),null);assert.equal(api.role,'admin');
});

test('incorrect password never reveals MFA fields; an enrolled account gets code entry without replacing its key',async()=>{
  const {document,window}=parseHTML('<section id="page-account-profile"></section>');let enrolled=false,reject=true;
  const api=mountAccountSecurity({document,view:{qrcode,location:{reload(){}}},identity:{role:'admin',mode:'observe'},sessionClient:{async request(){if(reject)throw Object.assign(Error(),{code:'INVALID_CREDENTIALS'});return {enrolled};}}});
  document.getElementById('security-password').value='wrong';await api.beginEnrollment();
  assert.ok(document.getElementById('security-code-field').hidden);assert.ok(document.getElementById('mfa-enrollment').hidden);
  reject=false;enrolled=true;document.getElementById('security-password').value='correct test password';await api.beginEnrollment();
  assert.equal(document.getElementById('security-code-field').hidden,false);assert.ok(document.getElementById('mfa-enrollment').hidden);assert.equal(document.querySelector('#mfa-qr svg'),null);
  assert.equal(document.querySelector('label[for="security-password"]').hidden,true);
  document.getElementById('security-back').click();
  assert.ok(document.getElementById('security-code-field').hidden,'Returning to the password step invalidates the first proof');
  assert.equal(document.querySelector('label[for="security-password"]').hidden,false);
});
test('observers do not receive administrator controls or trigger an administrator data request',()=>{
  const {document}=parseHTML('<section id="page-account-profile"></section>');const calls=[];
  mountAccountSecurity({document,view:{},identity:{role:'observer',mode:'observe'},sessionClient:{async request(path){calls.push(path);return {application:null};}}});
  assert.equal(document.getElementById('account-security'),null);assert.deepEqual(calls,['/api/v1/me/admin-application']);
});

test('administrator member rows load immediately without an extra Load button click',async()=>{
  const {document}=parseHTML('<section id="page-account-profile"></section>');const calls=[];
  mountAccountSecurity({document,view:{},identity:{role:'admin',mode:'admin'},sessionClient:{async request(path){calls.push(path);return {users:[{id:'member',username:'alice',displayName:'Alice',email:'alice@example.invalid',organization:'Lab',role:'observer',status:'active'}],nextCursor:null};}}});
  for(let i=0;i<10;i++)await Promise.resolve();
  assert.deepEqual(calls,['/api/v1/admin/applications','/api/v1/admin/users']);
  assert.equal(document.querySelectorAll('#admin-user-directory tbody tr').length,1);
  assert.match(document.querySelector('#admin-user-directory tbody').textContent,/Alice/);
});
