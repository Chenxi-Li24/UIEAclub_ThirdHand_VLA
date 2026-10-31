'use strict';
// Owner-designated staging account only. Never create users or bypass email/MFA.
const fs=require('node:fs'),assert=require('node:assert/strict');
const {db,request}=require('/var/backups/thirdhand/access-C2-20261030T125221Z/staging_history_smoke.cjs');
const base='/var/backups/thirdhand/access-C2c-smtp-20261030T150149Z';
const reviewFile='/var/backups/thirdhand/access-C2-20261030T125221Z/review-accounts.private.json';
let step='preflight';
async function main(){
  assert.equal(process.getuid(),0);assert.equal(process.platform,'linux');
  assert.equal(fs.existsSync(base+'/designated-admin.json'),false);
  const privateConfig=JSON.parse(fs.readFileSync('/etc/thirdhand-stage/smtp.pending.json'));
  assert.equal(privateConfig.allowedRecipients.length,1);
  const email=privateConfig.allowedRecipients[0];
  const target=db("console.log(JSON.stringify((await pool.query('SELECT id,role,status,email_verified_at,role_version FROM auth.users WHERE email=$1',["+JSON.stringify(email)+"])).rows))");
  assert.equal(target.length,1,'Owner account not registered');const user=target[0];
  assert.equal(user.status,'active','Owner account not active');assert.ok(user.email_verified_at,'Owner email not verified');
  assert.equal(user.role,'observer','Inspect an already privileged account instead of silently modifying it');
  const privateState=JSON.parse(fs.readFileSync(reviewFile));const actor=privateState.accounts.find(x=>x.username==='c2_admin2');assert.ok(actor.recoveryCodes.length>=2);
  const proof=()=>{const code=actor.recoveryCodes.shift();fs.writeFileSync(reviewFile,JSON.stringify(privateState,null,2),{mode:0o600});return code;};
  step='existing-mfa-administrator';let result=await request('/api/v1/auth/login',{body:{login:actor.username,password:actor.password,requestedMode:'admin',recoveryCode:proof()}});assert.equal(result.status,200);
  const session={cookie:result.headers['set-cookie'][0].split(';')[0],csrf:result.json.csrfToken};
  step='grant-designated-verified-owner';result=await request('/api/v1/admin/users/'+user.id+'/role',{...session,body:{role:'admin',expectedVersion:user.role_version,reason:'Owner-designated first real staging administrator; email verified.',password:actor.password,recoveryCode:proof()}});assert.equal(result.status,200);
  assert.equal(result.json.role,'admin');
  const mfa=db("console.log(JSON.stringify((await pool.query(\"SELECT count(*)::int AS n FROM auth.mfa_credentials WHERE user_id=$1 AND kind='totp' AND enabled_at IS NOT NULL AND revoked_at IS NULL\",["+JSON.stringify(user.id)+"])).rows[0].n))");
  const report={success:true,checkedAt:new Date().toISOString(),stagingOnly:true,registeredByOwner:true,emailVerified:true,role:'admin',roleVersion:result.json.roleVersion,mfaEnabled:mfa>0,ownerMustCompleteMfa:mfa===0,hardwareAuthority:false};
  fs.writeFileSync(base+'/designated-admin.json',JSON.stringify(report,null,2),{mode:0o600});console.log(JSON.stringify(report,null,2));
}
main().catch(e=>{console.error('STAGING_ADMIN_SETUP_FAILED at '+step+' code '+(e.code||e.name));process.exitCode=1;});
