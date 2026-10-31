'use strict';
// Read-only owner status audit; frontend hash checks use an existing synthetic account.
const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {db,request}=require('/var/backups/thirdhand/access-C2-20261030T125221Z/staging_history_smoke.cjs');
const base='/var/backups/thirdhand/access-C2f-mfa-layout-20261031';
async function main(){
  assert.equal(process.getuid(),0);assert.equal(fs.existsSync(base+'/acceptance.json'),false);
  const delta=JSON.parse(fs.readFileSync(base+'/release-delta.json'));
  const actor=JSON.parse(fs.readFileSync('/var/backups/thirdhand/access-C2-20261030T125221Z/review-accounts.private.json')).accounts.find(x=>x.username==='c2_admin');
  const login=await request('/api/v1/auth/login',{body:{login:actor.username,password:actor.password,requestedMode:'observe'}});assert.equal(login.status,200);
  const session={cookie:login.headers['set-cookie'][0].split(';')[0],csrf:login.json.csrfToken};
  try{
    assert.equal((await request('/control',session)).status,200);
    for(const file of Object.keys(delta.files)){
      const r=await request('/control-assets/'+file.slice('apps/web/public/'.length),session);assert.equal(r.status,200);
      assert.equal(crypto.createHash('sha256').update(r.bytes).digest('hex'),delta.fileHashes[file]);
    }
  }finally{assert.equal((await request('/api/v1/session/logout',{...session,body:{}})).status,200);}
  const config=JSON.parse(fs.readFileSync('/etc/thirdhand-stage/smtp.pending.json'));assert.equal(config.allowedRecipients.length,1);
  const owner=db("console.log(JSON.stringify((await pool.query(\"SELECT role,status,email_verified_at IS NOT NULL AS email_verified,EXISTS(SELECT 1 FROM auth.mfa_credentials m WHERE m.user_id=u.id AND kind='totp' AND enabled_at IS NOT NULL AND revoked_at IS NULL) AS mfa_enabled,EXISTS(SELECT 1 FROM auth.sessions s WHERE s.user_id=u.id AND mode='admin' AND mfa_verified_at IS NOT NULL) AS admin_mode_completed FROM auth.users u WHERE email=$1\",["+JSON.stringify(config.allowedRecipients[0])+"])).rows))");
  assert.equal(owner.length,1);
  const result={success:true,checkedAt:new Date().toISOString(),protectedAssetsHashMatched:true,syntheticSessionClosed:true,ownerStatus:owner[0],ownerAuditReadOnly:true,hardwareCalls:0};
  fs.writeFileSync(base+'/acceptance.json',JSON.stringify(result,null,2),{mode:0o600});console.log(JSON.stringify(result,null,2));
}
main().catch(()=>{console.error('MFA_LAYOUT_ACCEPTANCE_FAILED');process.exitCode=1;});
