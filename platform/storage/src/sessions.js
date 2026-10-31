'use strict';

const { transaction } = require('./pool');
const SESSION_COLUMNS = `s.id, s.user_id AS "userId", s.token_hash AS "tokenHash", s.csrf_hash AS "csrfHash",
  s.mode, s.role_version AS "roleVersion", s.mfa_verified_at AS "mfaVerifiedAt", s.client_label AS "clientLabel",
  s.created_at AS "createdAt", s.last_user_activity_at AS "lastUserActivityAt", s.idle_expires_at AS "idleExpiresAt",
  s.absolute_expires_at AS "absoluteExpiresAt", s.revoked_at AS "revokedAt", s.revocation_reason AS "revocationReason"`;

function createSessionsRepository(pool) {
  return {
    async create({ userId, tokenHash, csrfHash = null, mode = 'observe', mfaVerifiedAt = null, clientLabel = '', now = new Date() }) {
      if (!['observe','admin'].includes(mode)) throw new Error('Invalid session mode');
      return transaction(pool, async client => {
        const user = (await client.query('SELECT role,status,role_version FROM auth.users WHERE id=$1 FOR SHARE', [userId])).rows[0];
        if (!user || user.status !== 'active') throw new Error('Active verified account required');
        if (mode === 'admin' && (user.role !== 'admin' || !mfaVerifiedAt)) throw new Error('Administrator permission and MFA required');
        const idle = new Date(now.getTime() + (mode === 'admin' ? 15 : 60) * 60000);
        const absolute = new Date(now.getTime() + (mode === 'admin' ? 8 : 24) * 3600000);
        const result = await client.query(`INSERT INTO auth.sessions AS s
          (user_id,token_hash,csrf_hash,mode,role_version,mfa_verified_at,client_label,created_at,last_user_activity_at,idle_expires_at,absolute_expires_at)
          VALUES($1,$2,$3,$4,$5,$6,$7,$8,$8,$9,$10) RETURNING ${SESSION_COLUMNS}`,
        [userId, tokenHash, csrfHash, mode, user.role_version, mfaVerifiedAt, String(clientLabel).slice(0,120), now, idle, absolute]);
        return result.rows[0];
      });
    },
    async findByTokenHash(tokenHash) {
      return (await pool.query(`SELECT ${SESSION_COLUMNS}, u.role, u.status, u.role_version AS "currentRoleVersion"
        FROM auth.sessions s JOIN auth.users u ON u.id=s.user_id WHERE s.token_hash=$1`, [tokenHash])).rows[0] || null;
    },
    async revoke({ sessionId, reason, now = new Date() }) {
      return (await pool.query(`UPDATE auth.sessions SET revoked_at=$2,revocation_reason=$3
        WHERE id=$1 AND revoked_at IS NULL RETURNING id`, [sessionId, now, reason])).rowCount > 0;
    }
  };
}

module.exports = { createSessionsRepository, SESSION_COLUMNS };
