'use strict';
// Existing synthetic account only; never enroll or mutate the owner's authenticator.
const fs=require('node:fs'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {request}=require('/var/backups/thirdhand/access-C2-20261030T125221Z/staging_history_smoke.cjs');
const root='/var/backups/thirdhand/access-C2e-mfa-20261031';
async function main(){
  assert.equal(process.getuid(),0);assert.equal(fs.existsSync(root+'/api-acceptance.json'),false);
  const actor=JSON.parse(fs.readFileSync('/var/backups/thirdhand/access-C2-20261030T125221Z/review-accounts.private.json')).accounts.find(x=>x.username==='c2_admin');
  const delta=JSON.parse(fs.readFileSync(root+'/release-delta.json'));
  let r=await request('/api/v1/auth/login',{body:{login:actor.username,password:actor.password,requestedMode:'observe'}});assert.equal(r.status,200);
  const session={cookie:r.headers['set-cookie'][0].split(';')[0],csrf:r.json.csrfToken};
  try{
    r=await request('/api/v1/mfa/prepare',{...session,csrf:'invalid',body:{password:actor.password}});assert.equal(r.status,403);
    r=await request('/api/v1/mfa/prepare',{...session,body:{password:'Wrong synthetic password'}});assert.equal(r.status,401);assert.equal(r.json.error,'INVALID_CREDENTIALS');
    r=await request('/api/v1/mfa/prepare',{...session,body:{password:actor.password}});assert.equal(r.status,200);assert.deepEqual(r.json,{enrolled:true});
    const page=await request('/control',session);assert.equal(page.status,200);
    const html=page.bytes.toString();assert.ok(html.indexOf('qrcode-generator-2.0.4.js')<html.indexOf('account-security.js'));assert.ok(html.includes('qrcode-generator-2.0.4.js'));
    for(const file of ['apps/web/public/js/account-security.js','apps/web/public/js/i18n-cloud-catalog.js','apps/web/public/css/cloud-workspace.css','apps/web/public/js/lib/qrcode-generator-2.0.4.js']){
      r=await request('/control-assets/'+file.slice('apps/web/public/'.length),session);assert.equal(r.status,200);
      assert.equal(crypto.createHash('sha256').update(r.bytes).digest('hex'),delta.fileHashes[file]);
    }
    const result={success:true,checkedAt:new Date().toISOString(),syntheticAccountOnly:true,wrongPasswordRejected:true,csrfRequired:true,enrolledKeyPreserved:true,scriptOrderCorrect:true,protectedAssetsHashMatched:true,ownerMfaUntouched:true,hardwareCalls:0};
    fs.writeFileSync(root+'/api-acceptance.json',JSON.stringify(result,null,2),{mode:0o600});console.log(JSON.stringify(result,null,2));
  }finally{assert.equal((await request('/api/v1/session/logout',{...session,body:{}})).status,200);}
}
main().catch(()=>{console.error('MFA_API_ACCEPTANCE_FAILED');process.exitCode=1;});
