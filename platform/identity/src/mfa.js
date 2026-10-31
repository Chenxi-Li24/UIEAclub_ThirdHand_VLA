'use strict';
const { randomBytes, createCipheriv, createDecipheriv } = require('node:crypto');
const OTPAuth = require('otpauth');
const { transaction } = require('../../storage/src/pool');
const { digestToken } = require('./tokens');
const { identityError } = require('./errors');
const { createRateLimits } = require('./rate-limits');

function createMfa({ pool, keyId, keys, clock = { now: () => new Date() } }) {
  const limits=createRateLimits({pool,clock});
  if (!/^[a-zA-Z0-9_-]{1,48}$/.test(keyId || '') || !Buffer.isBuffer(keys?.get(keyId)) || keys.get(keyId).length !== 32) throw identityError('CONFIG_ERROR', 'Separate 32-byte MFA encryption key required');
  function cryptSecret(userId, secret, stored = null, storedKeyId = keyId) {
    const key = keys.get(storedKeyId);
    if (!key) throw identityError('MFA_KEY_UNAVAILABLE', 'MFA encryption key unavailable');
    const aad = Buffer.from(`thirdhand:mfa:${userId}:${storedKeyId}`);
    if (stored) {
      const [iv, body, tag] = stored.split('.').map(s => Buffer.from(s, 'base64url'));
      const decipher = createDecipheriv('aes-256-gcm', key, iv); decipher.setAAD(aad); decipher.setAuthTag(tag);
      return Buffer.concat([decipher.update(body), decipher.final()]).toString('utf8');
    }
    const iv = randomBytes(12), cipher = createCipheriv('aes-256-gcm', key, iv); cipher.setAAD(aad);
    const body = Buffer.concat([cipher.update(secret, 'utf8'), cipher.final()]);
    return [iv, body, cipher.getAuthTag()].map(b => b.toString('base64url')).join('.');
  }
  function totp(secret, label = 'ThirdHand') {
    return new OTPAuth.TOTP({ issuer: 'ThirdHand', label, algorithm: 'SHA1', digits: 6, period: 30, secret: OTPAuth.Secret.fromBase32(secret) });
  }
  function stepFor(row, token, now) {
    if (typeof token !== 'string' || !/^\d{6}$/.test(token)) return null;
    const secret = cryptSecret(row.user_id, null, row.encrypted_secret, row.secret_key_id);
    const delta = totp(secret).validate({ token, timestamp: now.getTime(), window: 1 });
    if (delta === null) return null;
    const step = Math.floor(now.getTime() / 30000) + delta;
    if (row.last_used_step !== null && step <= Number(row.last_used_step)) return null;
    return step;
  }
  return {
    async beginEnrollment({ userId, label }) {
      const secret = new OTPAuth.Secret({ size: 20 }).base32;
      return transaction(pool, async client => {
        await client.query('SELECT id FROM auth.users WHERE id=$1 FOR UPDATE', [userId]);
        const old = (await client.query("SELECT enabled_at FROM auth.mfa_credentials WHERE user_id=$1 AND kind='totp' AND revoked_at IS NULL", [userId])).rows[0];
        if (old?.enabled_at) throw identityError('MFA_ALREADY_ENABLED');
        await client.query("UPDATE auth.mfa_credentials SET revoked_at=$2 WHERE user_id=$1 AND kind='totp' AND revoked_at IS NULL", [userId, clock.now()]);
        await client.query("INSERT INTO auth.mfa_credentials(user_id,kind,encrypted_secret,secret_key_id,created_at) VALUES($1,'totp',$2,$3,$4)", [userId, cryptSecret(userId, secret), keyId, clock.now()]);
        return { uri: totp(secret, label).toString() };
      });
    },
    async hasEnabled(userId) {
      return (await pool.query("SELECT 1 FROM auth.mfa_credentials WHERE user_id=$1 AND kind='totp' AND enabled_at IS NOT NULL AND revoked_at IS NULL", [userId])).rowCount > 0;
    },
    async confirmEnrollment({ userId, totp: token }) {
      await limits.consume(`mfa-confirm:${userId}`,{limit:8,windowMs:15*60000});
      return transaction(pool, async client => {
        const row = (await client.query("SELECT * FROM auth.mfa_credentials WHERE user_id=$1 AND kind='totp' AND revoked_at IS NULL FOR UPDATE", [userId])).rows[0];
        if (!row || row.enabled_at || clock.now().getTime() - row.created_at.getTime() > 10 * 60000) throw identityError('MFA_SETUP_EXPIRED');
        const step = stepFor(row, token, clock.now());
        if (step === null) throw identityError('MFA_INVALID');
        await client.query('UPDATE auth.mfa_credentials SET enabled_at=$2,last_used_step=$3 WHERE id=$1', [row.id, clock.now(), step]);
        const recoveryCodes = Array.from({ length: 10 }, () => randomBytes(16).toString('hex'));
        for (const code of recoveryCodes) await client.query("INSERT INTO auth.mfa_credentials(user_id,kind,recovery_hash,enabled_at) VALUES($1,'recovery',$2,$3)", [userId, digestToken(code), clock.now()]);
        return { recoveryCodes };
      });
    },
    async verify({ userId, totp: token, recoveryCode }) {
      return transaction(pool, async client => {
        const row = (await client.query("SELECT * FROM auth.mfa_credentials WHERE user_id=$1 AND kind='totp' AND enabled_at IS NOT NULL AND revoked_at IS NULL FOR UPDATE", [userId])).rows[0];
        if (!row) throw identityError('MFA_ENROLLMENT_REQUIRED');
        if (!token && !recoveryCode) throw identityError('MFA_REQUIRED');
        if (recoveryCode) {
          if (typeof recoveryCode !== 'string' || recoveryCode.length > 128) throw identityError('MFA_INVALID');
          const used = await client.query("UPDATE auth.mfa_credentials SET revoked_at=$3 WHERE user_id=$1 AND kind='recovery' AND recovery_hash=$2 AND revoked_at IS NULL AND enabled_at IS NOT NULL RETURNING id", [userId, digestToken(recoveryCode), clock.now()]);
          if (!used.rowCount) throw identityError('MFA_INVALID');
        } else {
          const step = stepFor(row, token, clock.now());
          if (step === null) throw identityError('MFA_INVALID');
          await client.query('UPDATE auth.mfa_credentials SET last_used_step=$2 WHERE id=$1', [row.id, step]);
        }
        return { verifiedAt: clock.now() };
      });
    }
  };
}
module.exports = { createMfa };
