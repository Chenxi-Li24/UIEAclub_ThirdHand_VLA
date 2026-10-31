'use strict';
const { createUsersRepository } = require('../../storage/src/users');
const { transaction } = require('../../storage/src/pool');
const { hashPassword, verifyPassword, validatePassword } = require('./passwords');
const { randomToken, digestToken } = require('./tokens');
const { accountLink,createMailer } = require('./mail');
const {writeAudit}=require('../../storage/src/audit');
const { createRateLimits } = require('./rate-limits');
const {claimInitialAdmin}=require('../../storage/src/admin-access');
const { identityError } = require('./errors');
let dummyHash;

function createAccounts({ pool, mfa, mail=createMailer(), publicOrigin, clock = { now: () => new Date() } }) {
  const users = createUsersRepository(pool), limits = createRateLimits({ pool, clock });
  async function passwordMatches(user, password) {
    // One initialization per process, awaited even for known accounts. Do not leave
    // hidden hash jobs competing with a later login in another service instance.
    const fallbackHash = await (dummyHash ||= hashPassword(randomToken()));
    return verifyPassword(user?.passwordHash || fallbackHash, password);
  }
  const normalize = value => typeof value === 'string' ? value.trim().toLowerCase().slice(0, 254) : '';
  async function limit(purpose, identifier, sourceKey) {
    const windowMs = 15 * 60000;
    await limits.consume(`${purpose}:source:${sourceKey || 'unknown'}`, { limit: purpose === 'login' ? 40 : 10, windowMs });
    await limits.consume(`${purpose}:account:${normalize(identifier)}`, { limit: purpose === 'login' ? 8 : 3, windowMs });
  }
  async function issueToken(user, purpose, minutes) {
    const token = randomToken();
    await transaction(pool, async client => {
      await client.query('SELECT id FROM auth.users WHERE id=$1 FOR UPDATE', [user.id]);
      await client.query('UPDATE auth.one_time_tokens SET consumed_at=$3 WHERE user_id=$1 AND purpose=$2 AND consumed_at IS NULL', [user.id, purpose, clock.now()]);
      await client.query('INSERT INTO auth.one_time_tokens(user_id,purpose,token_hash,expires_at,created_at) VALUES($1,$2,$3,$4,$5)',
        [user.id, purpose, digestToken(token), new Date(clock.now().getTime() + minutes * 60000), clock.now()]);
    });
    await mail.send({ purpose, to: user.email, locale: user.locale, url: accountLink(publicOrigin, purpose, token) });
  }
  async function consumeToken(client, token, purpose) {
    if (typeof token !== 'string' || !/^[a-zA-Z0-9_-]{43}$/.test(token)) throw identityError('INVALID_TOKEN');
    const row = (await client.query(`UPDATE auth.one_time_tokens SET consumed_at=$3 WHERE token_hash=$1 AND purpose=$2
      AND consumed_at IS NULL AND expires_at>$3 RETURNING user_id`, [digestToken(token), purpose, clock.now()])).rows[0];
    if (!row) throw identityError('INVALID_TOKEN');
    return row.user_id;
  }
  async function checkMfaPassword({userId,password,sourceKey}){
    await limit('mfa_setup',userId,sourceKey);
    const user=await users.findById(userId);
    if(!await passwordMatches(user,password)||!user||user.status!=='active')throw identityError('INVALID_CREDENTIALS');
    if(user.role!=='admin')throw identityError('ADMIN_PERMISSION_REQUIRED');
    return user;
  }
  return {
    async requestAdminAccess({userId,reason,sourceKey}){
      await limit('admin_application',userId,sourceKey);
      return users.requestAdmin({userId,reason});
    },
    async register(input) {
      mail.ensureAvailable?.({to:input.email,purpose:'verify_email'});
      await limit('register', input.email, input.sourceKey);
      validatePassword(input.password);
      const user = await users.create({ username: input.username, email: input.email, displayName: input.displayName,
        locale: input.locale ?? 'en', passwordHash: await hashPassword(input.password) });
      await issueToken(user, 'verify_email', 60);
      return { userId: user.id, status: 'pending_email' };
    },
    async verifyEmail({ token }) {
      return transaction(pool, async client => {
        // Match the role mutation lock order used by the private initial batch import.
        await client.query('SELECT pg_advisory_xact_lock(240103, 2)');
        const userId = await consumeToken(client, token, 'verify_email');
        const result = await client.query("UPDATE auth.users SET email_verified_at=$2,status='active',updated_at=$2 WHERE id=$1 AND status='pending_email' RETURNING id", [userId, clock.now()]);
        if (!result.rowCount) throw identityError('INVALID_TOKEN');
        await claimInitialAdmin(client,userId);
        return { verified: true };
      });
    },
    async authenticate({ login, password, requestedMode = 'observe', totp, recoveryCode, sourceKey }) {
      if (!['observe','admin'].includes(requestedMode) || typeof login !== 'string' || login.length > 254) throw identityError('INVALID_INPUT');
      await limit('login', login, sourceKey);
      const user = await users.findByLogin(login);
      const matches = await passwordMatches(user, password);
      if (!matches || !user || user.status === 'disabled') throw identityError('INVALID_CREDENTIALS');
      if (user.status !== 'active') throw identityError('EMAIL_NOT_VERIFIED');
      let mfaVerifiedAt = null;
      if (requestedMode === 'admin') {
        if (user.role !== 'admin') throw identityError('ADMIN_PERMISSION_REQUIRED');
        mfaVerifiedAt = (await mfa.verify({ userId: user.id, totp, recoveryCode })).verifiedAt;
      }
      return { userId: user.id, role: user.role, mode: requestedMode, roleVersion: user.roleVersion, mfaVerifiedAt };
    },
    async beginMfaSetup({ userId, password, sourceKey }) {
      const user=await checkMfaPassword({userId,password,sourceKey});
      return mfa.beginEnrollment({ userId, label: user.username });
    },
    async prepareMfa({userId,password,sourceKey}){
      const user=await checkMfaPassword({userId,password,sourceKey});
      if(await mfa.hasEnabled(userId))return {enrolled:true};
      return {enrolled:false,...await mfa.beginEnrollment({userId,label:user.username})};
    },
    async requestPasswordReset({ email, sourceKey }) {
      await limit('reset', email, sourceKey);
      const user = await users.findByLogin(email);
      if (user?.status === 'active') {
        try{await issueToken(user,'reset_password',30);}catch{
          await writeAudit(pool,{actorUserId:user.id,eventCode:'identity.mail.failed',outcome:'failed',context:{code:'MAIL_UNAVAILABLE'}}).catch(()=>{});
        }
      }
      return { accepted: true };
    },
    async resendVerification({ email, sourceKey }) {
      await limit('verify_email', email, sourceKey);
      const user = await users.findByLogin(email);
      if (user?.status === 'pending_email') {
        try{await issueToken(user,'verify_email',60);}catch{
          await writeAudit(pool,{actorUserId:user.id,eventCode:'identity.mail.failed',outcome:'failed',context:{code:'MAIL_UNAVAILABLE'}}).catch(()=>{});
        }
      }
      return { accepted: true };
    },
    async resetPassword({ token, password }) {
      const hash = await hashPassword(password);
      return transaction(pool, async client => {
        const userId = await consumeToken(client, token, 'reset_password');
        const updated = await client.query("UPDATE auth.users SET password_hash=$2,role_version=role_version+1,updated_at=$3 WHERE id=$1 AND status='active' RETURNING id", [userId, hash, clock.now()]);
        if (!updated.rowCount) throw identityError('INVALID_TOKEN');
        await client.query("UPDATE auth.sessions SET revoked_at=$2,revocation_reason='password_reset' WHERE user_id=$1 AND revoked_at IS NULL", [userId, clock.now()]);
        return { reset: true };
      });
    }
  };
}
module.exports = { createAccounts };
