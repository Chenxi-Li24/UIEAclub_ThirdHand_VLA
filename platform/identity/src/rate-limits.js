'use strict';
const { digestToken } = require('./tokens');
const { identityError } = require('./errors');

function createRateLimits({ pool, clock }) {
  return {
    async consume(key, { limit, windowMs }) {
      const now = clock.now(), cutoff = new Date(now.getTime() - windowMs);
      const result = await pool.query(`INSERT INTO security.rate_limits(bucket_hash,window_started_at,attempts)
        VALUES($1,$2,1) ON CONFLICT(bucket_hash) DO UPDATE SET
        attempts=CASE WHEN security.rate_limits.window_started_at <= $3 THEN 1 ELSE security.rate_limits.attempts+1 END,
        window_started_at=CASE WHEN security.rate_limits.window_started_at <= $3 THEN $2 ELSE security.rate_limits.window_started_at END
        RETURNING attempts`, [digestToken(key), now, cutoff]);
      if (result.rows[0].attempts > limit) throw identityError('RATE_LIMITED');
    }
  };
}
module.exports = { createRateLimits };
