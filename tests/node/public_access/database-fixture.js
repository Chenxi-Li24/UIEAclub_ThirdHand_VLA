'use strict';

const { randomUUID } = require('node:crypto');

// Tests create their own database. Never reset schemas on a supplied application DB.
async function isolatedDatabase(t) {
  const connectionString = process.env.TEST_DATABASE_URL;
  if (!connectionString) throw new Error('TEST_DATABASE_URL required: real isolated PostgreSQL tests were NOT run');
  const url = new URL(connectionString);
  if (!/^thirdhand_test(?:_|$)/.test(url.pathname.slice(1))) {
    throw new Error('TEST_DATABASE_URL must name a dedicated thirdhand_test database');
  }
  const { Pool } = require('pg');
  const admin = new Pool({ connectionString, max: 2 });
  const name = `thirdhand_test_${randomUUID().replaceAll('-', '')}`;
  await admin.query(`CREATE DATABASE "${name}"`);
  url.pathname = `/${name}`;
  const pool = new Pool({ connectionString: url.toString(), max: 6 });
  const disconnected=[];
  pool.on('connect',client=>disconnected.push(new Promise(resolve=>client.once('end',resolve))));
  t.after(async () => {
    await pool.end();
    // pg Pool.end resolves after removing its clients, before their TCP end
    // callbacks necessarily run. DROP FORCE in that gap sends 57P01 errors to
    // otherwise successfully completed tests on fast Linux runners.
    await Promise.all(disconnected);
    await admin.query(`DROP DATABASE "${name}" WITH (FORCE)`);
    await admin.end();
  });
  return pool;
}

module.exports = { isolatedDatabase };
