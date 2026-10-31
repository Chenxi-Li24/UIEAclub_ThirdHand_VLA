'use strict';
// Synthetic observer fixture only; no email is sent and no real account is altered.
const fs=require('node:fs'),assert=require('node:assert/strict');
const {db}=require('/var/backups/thirdhand/access-C2-20261030T125221Z/staging_history_smoke.cjs');
const base='/var/backups/thirdhand/access-C2d-auth-ui-20261030';
assert.equal(process.getuid(),0);assert.equal(fs.existsSync(base+'/verification-fixture.json'),false);
const result=db(`
  const root='/opt/thirdhand-stage/current';
  const {createUsersRepository}=require(root+'/platform/storage/src/users');
  const {hashPassword}=require(root+'/platform/identity/src/passwords');
  const {randomToken,digestToken}=require(root+'/platform/identity/src/tokens');
  const user=await createUsersRepository(pool).create({username:'c2d_ui_verification',email:'c2d_ui_verification@example.invalid',displayName:'C2d Synthetic Verification Only',passwordHash:await hashPassword(randomToken())});
  await pool.query("INSERT INTO auth.one_time_tokens(user_id,purpose,token_hash,expires_at) VALUES($1,'verify_email',$2,now()+interval '10 minutes')",[user.id,digestToken('c2d-ui-verification-fixture-20261030'.padEnd(43,'0'))]);
  console.log(JSON.stringify({syntheticOnly:true,role:user.role,status:user.status,userId:user.id,emailSent:false,hardwareCalls:0}));
`);
fs.writeFileSync(base+'/verification-fixture.json',JSON.stringify(result,null,2),{mode:0o600});console.log('SYNTHETIC_VERIFICATION_FIXTURE_READY');
