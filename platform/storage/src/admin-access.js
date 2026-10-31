'use strict';
const {transaction}=require('./pool');
const {writeAudit}=require('./audit');
const fail=code=>Object.assign(Error(code),{code});
const reasonValid=value=>typeof value==='string'&&value.trim().length>0&&value.length<=500;
const columns='id,user_id AS "userId",role_version AS "roleVersion",reason,status,reviewer_id AS "reviewerId",review_reason AS "reviewReason",created_at AS "createdAt",reviewed_at AS "reviewedAt"';
const lock=client=>client.query('SELECT pg_advisory_xact_lock(240103, 2)');

async function promote(client,user,actorId,reason){
  const changed=(await client.query("UPDATE auth.users SET role='admin',role_version=role_version+1,updated_at=now() WHERE id=$1 RETURNING id,role,status,role_version AS \"roleVersion\"",[user.id])).rows[0];
  await client.query("INSERT INTO auth.role_changes(target_user_id,previous_role,new_role,actor_user_id,reason) VALUES($1,'observer','admin',$2,$3)",[user.id,actorId,reason]);
  await client.query("UPDATE auth.sessions SET revoked_at=now(),revocation_reason='role_changed' WHERE user_id=$1 AND revoked_at IS NULL",[user.id]);
  await writeAudit(client,{actorUserId:actorId,eventCode:'identity.user.role_changed',objectId:user.id,outcome:'success'});
  return changed;
}

async function applyInitialAdmins(pool,{emails}){
  if(!Array.isArray(emails)||emails.length<1||emails.length>100)throw fail('INVALID_INPUT');
  const list=emails.map(value=>typeof value==='string'?value.trim().toLowerCase():'');
  if(new Set(list).size!==list.length||list.some(value=>value.length>254||!/^\S+@[^\s@]+\.[^\s@]+$/.test(value)))throw fail('INVALID_INPUT');
  return transaction(pool,async client=>{
    await lock(client);
    if((await client.query('SELECT 1 FROM auth.initial_admin_batch')).rowCount)throw fail('BOOTSTRAP_CLOSED');
    for(const email of list)await client.query('INSERT INTO auth.initial_admin_allowlist(email) VALUES($1)',[email]);
    const users=(await client.query('SELECT id FROM auth.users WHERE email=ANY($1::text[]) ORDER BY id FOR UPDATE',[list])).rows;
    let promoted=0;
    for(const user of users)if(await claimInitialAdmin(client,user.id))promoted++;
    await client.query('INSERT INTO auth.initial_admin_batch(member_count) VALUES($1)',[list.length]);
    await writeAudit(client,{eventCode:'identity.admin.initial_batch',outcome:'success',context:{count:list.length}});
    return {count:list.length,promoted,sealed:true};
  });
}

async function claimInitialAdmin(client,userId){
  await lock(client);
  const user=(await client.query('SELECT id,email,role,status,email_verified_at FROM auth.users WHERE id=$1 FOR UPDATE',[userId])).rows[0];
  if(!user||user.status!=='active'||!user.email_verified_at)return false;
  const entry=await client.query('UPDATE auth.initial_admin_allowlist SET user_id=$2,consumed_at=now() WHERE email=$1 AND user_id IS NULL RETURNING email',[user.email,user.id]);
  if(!entry.rowCount)return false;
  if(user.role!=='admin')await promote(client,user,null,'initial administrator allowlist');
  await client.query("UPDATE auth.admin_applications SET status='superseded',review_reason='initial administrator allowlist',reviewed_at=now() WHERE user_id=$1 AND status='pending'",[user.id]);
  await writeAudit(client,{eventCode:'identity.admin.initial_claim',objectId:user.id,outcome:'success'});
  return true;
}

async function requestAdmin(pool,{userId,reason}){
  if(!reasonValid(reason))throw fail('INVALID_INPUT');
  return transaction(pool,async client=>{
    await lock(client);
    const user=(await client.query('SELECT role,status,email_verified_at,role_version FROM auth.users WHERE id=$1 FOR UPDATE',[userId])).rows[0];
    if(!user||user.role!=='observer'||user.status!=='active'||!user.email_verified_at)throw fail('INVALID_STATE');
    if((await client.query("SELECT 1 FROM auth.admin_applications WHERE user_id=$1 AND status='pending'",[userId])).rowCount)throw fail('CONFLICT');
    const application=(await client.query(`INSERT INTO auth.admin_applications(user_id,role_version,reason) VALUES($1,$2,$3) RETURNING ${columns}`,[userId,user.role_version,reason.trim()])).rows[0];
    await writeAudit(client,{actorUserId:userId,eventCode:'identity.admin.requested',objectId:application.id,outcome:'success'});
    return application;
  });
}

async function decideInTransaction(client,{actorId,requestId,userId,expectedVersion,decision,reason}){
  if(!['approved','rejected'].includes(decision)||!reasonValid(reason))throw fail('INVALID_INPUT');
  await lock(client);
  const actor=(await client.query('SELECT role,status,email_verified_at FROM auth.users WHERE id=$1',[actorId])).rows[0];
  if(!actor||actor.role!=='admin'||actor.status!=='active'||!actor.email_verified_at)throw fail('FORBIDDEN');
  const application=(await client.query(`SELECT ${columns} FROM auth.admin_applications WHERE ${requestId?'id=$1':"user_id=$1 AND status='pending'"} FOR UPDATE`,[requestId||userId])).rows[0];
  if(!application)throw fail(requestId?'NOT_FOUND':'ADMIN_REQUEST_REQUIRED');
  if(actorId===application.userId)throw fail('FORBIDDEN');
  if(application.status!=='pending')throw fail('CONFLICT');
  const user=(await client.query('SELECT id,role,status,email_verified_at,role_version FROM auth.users WHERE id=$1 FOR UPDATE',[application.userId])).rows[0];
  let changed;
  if(decision==='approved'){
    if(!user||user.role!=='observer'||user.status!=='active'||!user.email_verified_at||user.role_version!==application.roleVersion||expectedVersion!==undefined&&expectedVersion!==user.role_version)throw fail('CONFLICT');
    changed=await promote(client,user,actorId,reason.trim());
  }
  const result=(await client.query(`UPDATE auth.admin_applications SET status=$2,reviewer_id=$3,review_reason=$4,reviewed_at=now() WHERE id=$1 RETURNING ${columns}`,[application.id,decision,actorId,reason.trim()])).rows[0];
  await writeAudit(client,{actorUserId:actorId,eventCode:`identity.admin.${decision}`,objectId:application.id,outcome:'success'});
  return changed||result;
}

function createAdminAccess(pool){return {
  applyInitialAdmins:input=>applyInitialAdmins(pool,input),
  requestAdmin:input=>requestAdmin(pool,input),
  async adminRequest({userId}){return (await pool.query(`SELECT ${columns} FROM auth.admin_applications WHERE user_id=$1 ORDER BY created_at DESC,id DESC LIMIT 1`,[userId])).rows[0]||null;},
  async pendingAdminRequests({cursor=null}={}){return (await pool.query(`SELECT a.id,a.user_id AS "userId",a.reason,a.status,a.created_at AS "createdAt",u.username,u.email FROM auth.admin_applications a JOIN auth.users u ON u.id=a.user_id WHERE a.status='pending' AND ($1::uuid IS NULL OR a.id>$1::uuid) ORDER BY a.id LIMIT 100`,[cursor])).rows;},
  decideAdmin:input=>transaction(pool,client=>decideInTransaction(client,input))
};}
module.exports={createAdminAccess,claimInitialAdmin};
