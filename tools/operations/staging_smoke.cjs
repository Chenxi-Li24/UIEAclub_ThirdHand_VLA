'use strict';
// Operator-only synthetic C2 acceptance. No SDK imports and no real recipients.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),cp=require('node:child_process'),https=require('node:https'),assert=require('node:assert/strict');
const base='/var/backups/thirdhand/access-C2-20261030T125221Z',release='/opt/thirdhand-stage/current',node='/opt/thirdhand-stage/node-v24.22.1/bin/node';
const host='staging.uiea-thirdhand.com',origin='https://'+host;
let step='preflight';
function db(script){
  const code=`const {Pool}=require('${release}/node_modules/pg');const pool=new Pool({host:'/run/thirdhand-stage-db',port:55440,database:'thirdhand_stage',user:'postgres',max:1});(async()=>{try{${script}}finally{await pool.end()}})().catch(()=>{process.stderr.write('C2_DB_FIXTURE_FAILED');process.exitCode=1});`;
  return JSON.parse(cp.execFileSync('runuser',['-u','postgres','--',node,'-'],{input:code,cwd:release,encoding:'utf8'}));
}
function request(endpoint,{body,cookie,csrf}={}){return new Promise((resolve,reject)=>{
  const bytes=body===undefined?null:Buffer.from(JSON.stringify(body)),headers={Host:host,...(bytes?{'Content-Type':'application/json','Content-Length':bytes.length,Origin:origin}:{}),...(cookie?{Cookie:cookie}:{}),...(csrf?{'X-CSRF-Token':csrf}:{})};
  const req=https.request({hostname:'127.0.0.1',port:443,servername:host,path:endpoint,method:bytes?'POST':'GET',headers,timeout:15000},res=>{const parts=[];res.on('data',x=>parts.push(x));res.on('end',()=>{const data=Buffer.concat(parts);let json;try{json=JSON.parse(data)}catch{}resolve({status:res.statusCode,headers:res.headers,bytes:data,json});});});
  req.on('timeout',()=>req.destroy(Error('C2_HTTP_TIMEOUT')));req.on('error',reject);req.end(bytes);
});}
const privateFile=path.join(base,'review-accounts.private.json');
function persist(accounts){fs.writeFileSync(privateFile,JSON.stringify({origin,accounts},null,2),{mode:0o600});}
function message(to,purpose){return fs.readdirSync('/var/lib/thirdhand-stage/mail').map(name=>{const file=path.join('/var/lib/thirdhand-stage/mail',name);return {...JSON.parse(fs.readFileSync(file)),at:fs.statSync(file).mtimeMs};}).filter(x=>x.to===to&&x.purpose===purpose).sort((a,b)=>b.at-a.at)[0];}
function token(mail){return new URLSearchParams(new URL(mail.url).hash.slice(1)).get('token');}
async function login(account,mode='observe'){
  const body={login:account.username,password:account.password,requestedMode:mode};
  if(mode==='admin'){body.recoveryCode=account.recoveryCodes.shift();}
  const r=await request('/api/v1/auth/login',{body});assert.equal(r.status,200,'Login failed');
  assert.ok(r.headers['set-cookie'][0].includes('Secure'));assert.ok(r.headers['set-cookie'][0].includes('HttpOnly'));
  return {cookie:r.headers['set-cookie'][0].split(';')[0],csrf:r.json.csrfToken,userId:r.json.userId,mode:r.json.mode};
}
async function enroll(account,session){
  let r=await request('/api/v1/mfa/setup',{...session,body:{password:account.password}});assert.equal(r.status,200,'MFA setup failed');
  account.authenticatorUri=r.json.uri;
  const OTPAuth=require(release+'/node_modules/otpauth'),otp=OTPAuth.URI.parse(account.authenticatorUri);
  r=await request('/api/v1/mfa/confirm',{...session,body:{totp:otp.generate()}});assert.equal(r.status,200,'MFA confirmation failed');
  account.recoveryCodes=r.json.recoveryCodes;
}
async function main(){
  assert.equal(process.getuid(),0);assert.equal(process.platform,'linux');assert.equal(fs.existsSync(privateFile),false,'Existing private acceptance state requires inspection');
  assert.equal(db("console.log(JSON.stringify((await pool.query('SELECT count(*)::int n FROM auth.users')).rows[0].n))"),0,'Unexpected existing staging users');
  const accounts=['admin','admin2','observer','observer2'].map(name=>({username:'c2_'+name,email:name+'@example.invalid',displayName:'C2 Synthetic '+name,password:crypto.randomBytes(24).toString('base64url')+'9!'}));persist(accounts);
  for(const account of accounts.slice(0,3)){
    step='register-'+account.username;let r=await request('/api/v1/auth/register',{body:{...account,locale:'en',role:'admin'}});assert.equal(r.status,201,'Registration failed');account.userId=r.json.userId;persist(accounts);
    r=await request('/api/v1/auth/verify-email',{body:{token:token(message(account.email,'verify_email'))}});assert.equal(r.status,200,'Email verification failed');
    assert.equal((await request('/api/v1/auth/verify-email',{body:{token:token(message(account.email,'verify_email'))}})).status,400,'Verification replay accepted');
  }
  const [a,b,o]=accounts;step='bootstrap-synthetic-admin';
  cp.execFileSync('runuser',['-u','thirdhand-stage-migrate','--','env','IDENTITY_DATABASE_URL=postgresql://thirdhand-stage-migrate@localhost:55440/thirdhand_stage?host=/run/thirdhand-stage-db',node,release+'/platform/identity/src/bootstrap-admin.js',a.userId,'--confirm-first-admin'],{cwd:release,stdio:'pipe'});
  const aObserve=await login(a);assert.equal((await request('/api/v1/admin/users',aObserve)).status,403);await enroll(a,aObserve);persist(accounts);
  const aAdmin=await login(a,'admin');persist(accounts);step='grant-second-synthetic-admin';
  let r=await request('/api/v1/admin/users/'+b.userId+'/role',{...aAdmin,body:{role:'admin',expectedVersion:1,reason:'C2 synthetic multi-admin acceptance',password:a.password,recoveryCode:a.recoveryCodes.shift()}});assert.equal(r.status,200,'Admin role grant failed');persist(accounts);
  const bObserve=await login(b);await enroll(b,bObserve);persist(accounts);const bAdmin=await login(b,'admin');persist(accounts);
  assert.equal((await request('/api/v1/session',aAdmin)).status,200);assert.equal((await request('/api/v1/session',bAdmin)).status,200);
  assert.equal(db("console.log(JSON.stringify((await pool.query('SELECT count(*)::int n FROM ops.control_leases')).rows[0].n))"),0);
  const observer=await login(o);assert.equal(observer.mode,'observe');assert.equal((await request('/api/v1/admin/users',observer)).status,403);
  assert.equal((await request('/api/v1/auth/login',{body:{login:o.username,password:o.password,requestedMode:'admin'}})).status,403);
  assert.equal((await request('/api/v1/sdk/connect',{...observer,body:{}})).status,403);
  assert.equal((await request('/api/v1/sdk/connect',{...aAdmin,body:{}})).status,503);
  for(const p of ['/ws','/execution','/voice','/vision','/internal/','/media/'])assert.equal((await request(p)).status,404);
  for(const p of ['/control','/history'])assert.equal((await request(p,observer)).status,200);
  step='model-assets';
  const files=['FastTouchV3.SLDASM.urdf',...['base_link','link1','link2','link3','link4','link5','gripper_base','gripper_link1','gripper_link2'].map(x=>'meshes/'+x+'.STL')];
  for(const file of files){r=await request('/control-assets/models/startouch-v3/'+file,observer);assert.equal(r.status,200,'Model resource missing');assert.equal(crypto.createHash('sha256').update(r.bytes).digest('hex'),crypto.createHash('sha256').update(fs.readFileSync(release+'/assets/robot/startouch-v3/'+file)).digest('hex'));}
  step='private-password-reset';assert.equal((await request('/api/v1/auth/forgot-password',{body:{email:o.email}})).status,202);
  o.password=crypto.randomBytes(24).toString('base64url')+'9!';persist(accounts);
  assert.equal((await request('/api/v1/auth/reset-password',{body:{token:token(message(o.email,'reset_password')),password:o.password}})).status,200);
  assert.equal((await request('/api/v1/session',observer)).status,401);await login(o);persist(accounts);
  const directory=await request('/api/v1/admin/users',aAdmin);assert.equal(directory.status,200);assert.equal(directory.json.users.length,3);assert.ok(!directory.bytes.includes(Buffer.from('password_hash')));
  const permissions=db("console.log(JSON.stringify((await pool.query(\"SELECT has_database_privilege('thirdhand-stage','thirdhand_stage','CREATE') db_create,has_schema_privilege('thirdhand-stage','auth','CREATE') schema_create,has_table_privilege('thirdhand-stage','ops.commands','INSERT,UPDATE,DELETE') command_write,has_table_privilege('thirdhand-stage','telemetry.robot_samples','INSERT,UPDATE,DELETE') telemetry_write,has_table_privilege('thirdhand-stage','auth.users','DELETE') user_delete,has_table_privilege('thirdhand-stage-export','auth.users','SELECT') export_user_read\")).rows[0]))");
  assert.ok(Object.values(permissions).every(x=>x===false));
  const result={success:true,checkedAt:new Date().toISOString(),registeredVerifiedUsers:3,mail:'private-synthetic-only',externalEmailSent:false,mfaAdministrators:2,concurrentAdminSessions:true,loginDidNotAcquireControl:true,observerDefault:true,observerAdminDenied:true,sdkObserver403Admin503:true,modelResourcesVerified:files.length,passwordResetRevokesSession:true,verificationOneUse:true,permissions,deviceControl:false};
  fs.writeFileSync(path.join(base,'C2-business-smoke.json'),JSON.stringify(result,null,2),{mode:0o600});
  console.log(JSON.stringify(result,null,2));
}
if(require.main===module)main().catch(error=>{console.error('C2_SMOKE_FAILED at '+step+' code '+(error.code||error.name));process.exitCode=1;});
