'use strict';

const { transaction } = require('./pool');
const { writeAudit } = require('./audit');
const {createAdminAccess}=require('./admin-access');

const USER_COLUMNS = `id, username, email, display_name AS "displayName", password_hash AS "passwordHash",
  role, status, locale, role_version AS "roleVersion", email_verified_at AS "emailVerifiedAt",
  created_at AS "createdAt", updated_at AS "updatedAt"`;
const normalize = value => String(value || '').trim().toLowerCase();
const fail = (code, message) => Object.assign(new Error(message), { code });

function createUsersRepository(pool) {
  return {
    ...createAdminAccess(pool),
    async create(input) {
      const username = normalize(input.username), email = normalize(input.email);
      const displayName = String(input.displayName || '').trim(), locale = input.locale ?? 'en';
      if (!/^[a-z0-9_][a-z0-9_.-]{2,47}$/.test(username)) throw fail('INVALID_INPUT', 'Invalid username');
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 254) throw fail('INVALID_INPUT', 'Invalid email');
      if (!displayName || displayName.length > 80) throw fail('INVALID_INPUT', 'Invalid displayName');
      if (!['en','zh-CN'].includes(locale)) throw fail('INVALID_INPUT', 'Invalid locale');
      if (!input.passwordHash) throw fail('INVALID_INPUT', 'Password hash required');
      return transaction(pool, async client => {
        const result = await client.query(`INSERT INTO auth.users(username,email,display_name,password_hash,locale)
          VALUES($1,$2,$3,$4,$5) RETURNING ${USER_COLUMNS}`, [username, email, displayName, input.passwordHash, locale]);
        await client.query('INSERT INTO auth.user_preferences(user_id) VALUES($1)', [result.rows[0].id]);
        return result.rows[0];
      });
    },
    async findByLogin(login) {
      const result = await pool.query(`SELECT ${USER_COLUMNS} FROM auth.users WHERE username=$1 OR email=$1`, [normalize(login)]);
      return result.rows[0] || null;
    },
    async findById(id) {
      return (await pool.query(`SELECT ${USER_COLUMNS} FROM auth.users WHERE id=$1`, [id])).rows[0] || null;
    },
    async bootstrapAdmin({ verifiedUserId }) {
      return transaction(pool, async client => {
        await client.query('SELECT pg_advisory_xact_lock(240103, 2)');
        if((await client.query('SELECT 1 FROM auth.initial_admin_batch')).rowCount)throw fail('BOOTSTRAP_CLOSED');
        if ((await client.query("SELECT 1 FROM auth.users WHERE role='admin'")).rowCount) throw fail('BOOTSTRAP_CLOSED', 'Administrator bootstrap already closed');
        const target = (await client.query(`SELECT ${USER_COLUMNS} FROM auth.users WHERE id=$1 FOR UPDATE`, [verifiedUserId])).rows[0];
        if (!target || target.status !== 'active' || !target.emailVerifiedAt) throw fail('INVALID_STATE', 'Bootstrap requires an active verified account');
        const result = await client.query(`UPDATE auth.users SET role='admin',role_version=role_version+1,updated_at=now() WHERE id=$1 RETURNING ${USER_COLUMNS}`, [verifiedUserId]);
        await client.query("INSERT INTO auth.role_changes(target_user_id,previous_role,new_role,reason) VALUES($1,'observer','admin','controlled bootstrap')", [verifiedUserId]);
        await client.query("UPDATE auth.sessions SET revoked_at=now(),revocation_reason='role_changed' WHERE user_id=$1 AND revoked_at IS NULL", [verifiedUserId]);
        await writeAudit(client,{eventCode:'identity.admin.bootstrapped',objectId:verifiedUserId,outcome:'success'});
        return result.rows[0];
      });
    },
    async setRole({ actorId, userId, role, expectedVersion, reason }) {
      if (!['observer','admin'].includes(role) || typeof reason!=='string' || !reason.trim() || reason.length > 500) throw fail('INVALID_INPUT', 'Valid role and reason required');
      if(role==='admin')return createAdminAccess(pool).decideAdmin({actorId,userId,expectedVersion,decision:'approved',reason});
      return transaction(pool, async client => {
        await client.query('SELECT pg_advisory_xact_lock(240103, 2)');
        const actor = (await client.query('SELECT role,status FROM auth.users WHERE id=$1', [actorId])).rows[0];
        if (!actor || actor.role !== 'admin' || actor.status !== 'active') throw fail('FORBIDDEN', 'Administrator permission required');
        const target = (await client.query(`SELECT ${USER_COLUMNS} FROM auth.users WHERE id=$1 FOR UPDATE`, [userId])).rows[0];
        if (!target) throw fail('NOT_FOUND', 'User not found');
        if (target.roleVersion !== expectedVersion) throw fail('CONFLICT', 'Role version changed');
        if (target.role === role) return target;
        const result = await client.query(`UPDATE auth.users SET role=$2,role_version=role_version+1,updated_at=now() WHERE id=$1 RETURNING ${USER_COLUMNS}`, [userId, role]);
        await client.query('INSERT INTO auth.role_changes(target_user_id,previous_role,new_role,actor_user_id,reason) VALUES($1,$2,$3,$4,$5)', [userId, target.role, role, actorId, reason]);
        await client.query("UPDATE auth.sessions SET revoked_at=now(),revocation_reason='role_changed' WHERE user_id=$1 AND revoked_at IS NULL", [userId]);
        await writeAudit(client,{actorUserId:actorId,eventCode:'identity.user.role_changed',objectId:userId,outcome:'success'});
        return result.rows[0];
      });
    },
    async setStatus({actorId,userId,status,expectedVersion,reason}){
      if(!['active','disabled'].includes(status)||typeof reason!=='string'||!reason.trim()||reason.length>500)throw fail('INVALID_INPUT','Status and reason required');
      return transaction(pool,async client=>{
        await client.query('SELECT pg_advisory_xact_lock(240103, 2)');
        const actor=(await client.query('SELECT role,status FROM auth.users WHERE id=$1',[actorId])).rows[0];
        if(!actor||actor.role!=='admin'||actor.status!=='active')throw fail('FORBIDDEN','Administrator permission required');
        const target=(await client.query(`SELECT ${USER_COLUMNS} FROM auth.users WHERE id=$1 FOR UPDATE`,[userId])).rows[0];
        if(!target)throw fail('NOT_FOUND','User not found');
        if(target.roleVersion!==expectedVersion)throw fail('CONFLICT','Role version changed');
        if(target.status===status)return target;
        if(status==='active'&&!target.emailVerifiedAt)throw fail('INVALID_INPUT','Email verification required');
        const changed=(await client.query(`UPDATE auth.users SET status=$2,role_version=role_version+1,updated_at=now() WHERE id=$1 RETURNING ${USER_COLUMNS}`,[userId,status])).rows[0];
        await client.query("UPDATE auth.sessions SET revoked_at=now(),revocation_reason='account_status_changed' WHERE user_id=$1 AND revoked_at IS NULL",[userId]);
        await writeAudit(client,{actorUserId:actorId,eventCode:'identity.user.status_changed',objectId:userId,outcome:'success',context:{reason}});
        return changed;
      });
    }
  };
}

module.exports = { createUsersRepository, USER_COLUMNS };
