'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {identityFixture}=require('./identity-fixture');
const {createUsersRepository}=require('../../../platform/storage/src/users');

test('initial administrator batch is private, atomic, case insensitive and permanently sealed',async t=>{
  const f=await identityFixture(t),users=createUsersRepository(f.pool);
  assert.equal(typeof users.applyInitialAdmins,'function');
  const a=await f.verified('initial_a'),b=await f.verified('initial_b');
  await assert.rejects(users.applyInitialAdmins({emails:['initial_a@example.invalid','INITIAL_A@example.invalid']}),{code:'INVALID_INPUT'});
  assert.equal((await users.findById(a.userId)).role,'observer');
  const result=await users.applyInitialAdmins({emails:['INITIAL_A@example.invalid','initial_b@example.invalid']});
  assert.equal(result.count,2);
  assert.equal((await users.findById(b.userId)).role,'admin');
  await assert.rejects(users.applyInitialAdmins({emails:['initial_a@example.invalid']}),{code:'BOOTSTRAP_CLOSED'});
  await assert.rejects(users.bootstrapAdmin({verifiedUserId:a.userId}),{code:'BOOTSTRAP_CLOSED'});
});

test('sealed initial list grants only after email verification and cannot be reclaimed after revocation',async t=>{
  const f=await identityFixture(t),users=createUsersRepository(f.pool);
  const batch=await users.applyInitialAdmins({emails:['Initial.Later@example.invalid']});
  assert.equal(batch.promoted,0);
  const registered=await f.accounts.register({username:'initial_later',email:'INITIAL.LATER@example.invalid',displayName:'Later',password:f.password});
  assert.equal((await users.findById(registered.userId)).role,'observer');
  await assert.rejects(f.accounts.register({username:'duplicate_case',email:'initial.later@example.invalid',displayName:'Duplicate',password:f.password}),{code:'23505'});
  await f.accounts.verifyEmail({token:f.token(f.mailbox.at(-1))});
  const stored=await users.findByLogin('Initial.Later@example.invalid');assert.equal(stored.id,registered.userId);assert.equal(stored.role,'admin');
  const a=await f.verified('later_reviewer');await users.requestAdmin({userId:a.userId,reason:'review'});await users.setRole({actorId:stored.id,userId:a.userId,role:'admin',expectedVersion:1,reason:'review'});
  await users.setRole({actorId:a.userId,userId:stored.id,role:'observer',expectedVersion:stored.roleVersion,reason:'revoke'});
  const {transaction}=require('../../../platform/storage/src/pool');
  const {claimInitialAdmin}=require('../../../platform/storage/src/admin-access');
  assert.equal(await transaction(f.pool,client=>claimInitialAdmin(client,stored.id)),false);
  assert.equal((await users.findById(stored.id)).role,'observer');
});

test('approval requires an application and a distinct administrator and invalidates old sessions',async t=>{
  const f=await identityFixture(t),users=createUsersRepository(f.pool);
  assert.equal(typeof users.requestAdmin,'function');
  const a=await f.verified('reviewer'),b=await f.verified('applicant');
  await users.bootstrapAdmin({verifiedUserId:a.userId});
  const grant={actorId:a.userId,userId:b.userId,role:'admin',expectedVersion:1,reason:'approved for lab'};
  await assert.rejects(users.setRole(grant),{code:'ADMIN_REQUEST_REQUIRED'});
  const application=await users.requestAdmin({userId:b.userId,reason:'lab administration'});
  await assert.rejects(users.requestAdmin({userId:b.userId,reason:'duplicate'}),{code:'CONFLICT'});
  await assert.rejects(users.decideAdmin({actorId:b.userId,requestId:application.id,decision:'approved',reason:'self'}),{code:'FORBIDDEN'});
  await f.pool.query(`INSERT INTO auth.sessions(user_id,token_hash,role_version,created_at,last_user_activity_at,idle_expires_at,absolute_expires_at)
    VALUES($1,$2,1,now(),now(),now()+interval '1 hour',now()+interval '1 day')`,[b.userId,'f'.repeat(64)]);
  await users.decideAdmin({actorId:a.userId,requestId:application.id,decision:'approved',reason:'approved for lab'});
  assert.equal((await users.findById(b.userId)).role,'admin');
  assert.ok((await f.pool.query('SELECT revoked_at FROM auth.sessions WHERE user_id=$1',[b.userId])).rows[0].revoked_at);
  await assert.rejects(users.decideAdmin({actorId:a.userId,requestId:application.id,decision:'rejected',reason:'late'}),{code:'CONFLICT'});
});

test('unverified, disabled or changed accounts cannot obtain administrator access',async t=>{
  const f=await identityFixture(t),users=createUsersRepository(f.pool);
  assert.equal(typeof users.requestAdmin,'function');
  const a=await f.verified('strict_admin'),b=await f.verified('strict_user');
  await users.bootstrapAdmin({verifiedUserId:a.userId});
  const pending=await f.accounts.register({username:'pending_applicant',email:'pending@example.invalid',displayName:'pending',password:f.password});
  await assert.rejects(users.requestAdmin({userId:pending.userId,reason:'request'}),{code:'INVALID_STATE'});
  const application=await users.requestAdmin({userId:b.userId,reason:'request'});
  await users.setStatus({actorId:a.userId,userId:b.userId,status:'disabled',expectedVersion:1,reason:'disabled during review'});
  await assert.rejects(users.decideAdmin({actorId:a.userId,requestId:application.id,decision:'approved',reason:'approve'}),{code:'CONFLICT'});
  await users.decideAdmin({actorId:a.userId,requestId:application.id,decision:'rejected',reason:'account changed'});
  assert.equal((await users.adminRequest({userId:b.userId})).status,'rejected');
});

test('concurrent approval and rejection have exactly one winner; rejected users can apply again',async t=>{
  const f=await identityFixture(t),users=createUsersRepository(f.pool);
  assert.equal(typeof users.requestAdmin,'function');
  const a=await f.verified('race_admin'),b=await f.verified('race_user');await users.bootstrapAdmin({verifiedUserId:a.userId});
  const first=await users.requestAdmin({userId:b.userId,reason:'first'});
  await users.decideAdmin({actorId:a.userId,requestId:first.id,decision:'rejected',reason:'more context needed'});
  const second=await users.requestAdmin({userId:b.userId,reason:'more context'});
  const results=await Promise.allSettled(['approved','rejected'].map(decision=>users.decideAdmin({actorId:a.userId,requestId:second.id,decision,reason:'decision'})));
  assert.equal(results.filter(x=>x.status==='fulfilled').length,1);
  assert.equal(results.find(x=>x.status==='rejected').reason.code,'CONFLICT');
});

test('least-privilege cloud identity can claim a reservation and review applications but cannot edit the fixed initial list',async t=>{
  const f=await identityFixture(t),users=createUsersRepository(f.pool),role='approval_runtime_'+require('node:crypto').randomUUID().replaceAll('-','');
  await users.applyInitialAdmins({emails:['privilege_initial@example.invalid']});
  const pending=await f.accounts.register({username:'privilege_initial',email:'Privilege_Initial@example.invalid',displayName:'Initial',password:f.password});
  await f.pool.query(`CREATE ROLE ${role} NOLOGIN`);
  let client;
  try{
    await f.pool.query(`GRANT USAGE ON SCHEMA auth,security TO ${role}`);
    await f.pool.query(`GRANT SELECT,INSERT,UPDATE ON auth.users,auth.sessions,auth.one_time_tokens,auth.user_preferences,auth.mfa_credentials,security.rate_limits TO ${role}`);
    await f.pool.query(`GRANT SELECT,INSERT ON auth.role_changes,security.audit_events TO ${role}`);
    await f.pool.query(`GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA security TO ${role}`);
    const grants=await require('node:fs/promises').readFile('deploy/public-access/staging/grants.sql','utf8');
    for(const line of grants.split(/\r?\n/).filter(line=>/^GRANT /.test(line)&&/auth\.(?:admin_applications|initial_admin_)/.test(line)))await f.pool.query(line.replace('"thirdhand-stage"',role));
    client=await f.pool.connect();await client.query(`SET ROLE ${role}`);
    const scoped={query:(...args)=>client.query(...args),async connect(){return {query:(...args)=>client.query(...args),release(){}};}};
    const {createAccounts}=require('../../../platform/identity/src/accounts');
    const accounts=createAccounts({pool:scoped,mfa:f.mfa,clock:f.clock,publicOrigin:'https://thirdhand.example.invalid'});
    await accounts.verifyEmail({token:f.token(f.mailbox.at(-1))});
    assert.equal((await users.findById(pending.userId)).role,'admin');
    await assert.rejects(scoped.query("INSERT INTO auth.initial_admin_allowlist(email) VALUES('extra@example.invalid')"),{code:'42501'});
    await assert.rejects(scoped.query("UPDATE auth.initial_admin_allowlist SET email='other@example.invalid'"),{code:'42501'});
    await assert.rejects(scoped.query('DELETE FROM auth.initial_admin_batch'),{code:'42501'});
    const b=await f.verified('privilege_applicant'),access=createUsersRepository(scoped);
    const request=await access.requestAdmin({userId:b.userId,reason:'test runtime permissions'});
    await access.decideAdmin({actorId:pending.userId,requestId:request.id,decision:'approved',reason:'verified via runtime identity'});
    assert.equal((await users.findById(b.userId)).role,'admin');
  }finally{
    if(client){await client.query('RESET ROLE');client.release();}
    await f.pool.query(`DROP OWNED BY ${role}`);await f.pool.query(`DROP ROLE ${role}`);
  }
});
