'use strict';

const fs = require('node:fs/promises');
const path = require('node:path');
const { createHash } = require('node:crypto');

async function migrate(pool, { directory = path.resolve(__dirname, '../migrations') } = {}) {
  const client = await pool.connect();
  try {
    // Session lock spans individual committed migration transactions.
    await client.query('SELECT pg_advisory_lock(240103, 1)');
    await client.query(`CREATE TABLE IF NOT EXISTS public.thirdhand_schema_migrations (
      version text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())`);
    const names = (await fs.readdir(directory)).filter(name => /^\d{3}-[a-z0-9-]+\.sql$/.test(name)).sort();
    for (const name of names) {
      const sql = await fs.readFile(path.join(directory, name), 'utf8');
      const checksum = createHash('sha256').update(sql).digest('hex');
      const existing = await client.query('SELECT checksum FROM public.thirdhand_schema_migrations WHERE version=$1', [name]);
      if (existing.rowCount) {
        if (existing.rows[0].checksum !== checksum) throw new Error(`Migration checksum changed: ${name}; use a new forward migration`);
        continue;
      }
      await client.query('BEGIN');
      try {
        await client.query(sql);
        await client.query('INSERT INTO public.thirdhand_schema_migrations(version,checksum) VALUES($1,$2)', [name, checksum]);
        await client.query('COMMIT');
      } catch (error) { await client.query('ROLLBACK'); throw error; }
    }
  } finally {
    await client.query('SELECT pg_advisory_unlock(240103, 1)').catch(() => {});
    client.release();
  }
}

module.exports = { migrate };
