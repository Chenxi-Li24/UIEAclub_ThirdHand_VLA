'use strict';

const { Pool } = require('pg');

function createPool({ connectionString, max = 4, ssl } = {}) {
  if (!connectionString) throw new Error('PostgreSQL connectionString required');
  if (!Number.isInteger(max) || max < 1 || max > 32) throw new Error('Invalid PostgreSQL pool size');
  return new Pool({ connectionString, max, ...(ssl === undefined ? {} : { ssl }),
    connectionTimeoutMillis: 5000, idleTimeoutMillis: 30000,
    statement_timeout: 15000, application_name: 'thirdhand-public-access' });
}

async function transaction(pool, operation) {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    const result = await operation(client);
    await client.query('COMMIT');
    return result;
  } catch (error) {
    await client.query('ROLLBACK').catch(() => {});
    throw error;
  } finally { client.release(); }
}

module.exports = { createPool, transaction };
