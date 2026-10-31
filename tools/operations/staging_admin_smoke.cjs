'use strict';
// C2 synthetic user disable/re-enable through the deployed, MFA-protected API.
const fs=require('node:fs'),assert=require('node:assert/strict');
const {request}=require('./staging_history_smoke.cjs');
const base='/var/backups/thirdhand/access-C2-20261030T125221Z',privateFile=base+'/review-accounts.private.json';
let step='preflight';
async function main(){
  assert.equal(process.getuid(),0);assert.equal(fs.existsSync(base+'/C2-admin-revocation.json'),false);
  const state=JSON.parse(fs.readFileSync(privateFile)),a=state.accounts.find(x=>x.username==='c2_admin'),o=state.accounts.find(x=>x.username==='c2_observer2');
  assert.ok(a.recoveryCodes.length>=3);
  const proof=()=>{const recoveryCode=a.recoveryCodes.shift();fs.writeFileSync(privateFile,JSON.stringify(state,null,2),{mode:0o600});return recoveryCode;};
  step='admin-login';let r=await request('/api/v1/auth/login',{body:{login:a.username,password:a.password,requestedMode:'admin',recoveryCode:proof()}});assert.equal(r.status,200);
  const admin={cookie:r.headers['set-cookie'][0].split(';')[0],csrf:r.json.csrfToken};
  r=await request('/api/v1/auth/login',{body:{login:o.username,password:o.password,requestedMode:'observe'}});assert.equal(r.status,200);const observer={cookie:r.headers['set-cookie'][0].split(';')[0]};
  r=await request('/api/v1/admin/users',admin);assert.equal(r.status,200);assert.equal(r.json.users.length,4);let user=r.json.users.find(x=>x.username===o.username);assert.equal(user.status,'active');
  step='disable';r=await request('/api/v1/admin/users/'+user.id+'/status',{...admin,body:{status:'disabled',expectedVersion:user.roleVersion,reason:'C2 synthetic session revocation acceptance',password:a.password,recoveryCode:proof()}});assert.equal(r.status,200);const version=r.json.roleVersion;
  assert.equal((await request('/api/v1/session',observer)).status,401);
  assert.equal((await request('/api/v1/auth/login',{body:{login:o.username,password:o.password,requestedMode:'observe'}})).status,401);
  step='reenable';r=await request('/api/v1/admin/users/'+user.id+'/status',{...admin,body:{status:'active',expectedVersion:version,reason:'C2 synthetic fixture returned to review state',password:a.password,recoveryCode:proof()}});assert.equal(r.status,200);
  assert.equal((await request('/api/v1/session',observer)).status,401);
  assert.equal((await request('/api/v1/auth/login',{body:{login:o.username,password:o.password,requestedMode:'observe'}})).status,200);
  const result={success:true,syntheticOnly:true,registeredVerifiedUsers:4,mfaProtectedStatusChange:true,disabledLoginDenied:true,disabledSessionRevoked:true,reenableDoesNotReviveOldSession:true,fixtureFinalStatus:'active'};
  fs.writeFileSync(base+'/C2-admin-revocation.json',JSON.stringify(result,null,2),{mode:0o600});console.log(JSON.stringify(result,null,2));
}
main().catch(e=>{console.error('C2_ADMIN_FAILED at '+step+' code '+(e.code||e.name));process.exitCode=1;});
