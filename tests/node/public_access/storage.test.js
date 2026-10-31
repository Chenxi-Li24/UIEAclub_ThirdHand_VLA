'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { isolatedDatabase } = require('./database-fixture');
const { migrate } = require('../../../platform/storage/src/migrate');
const { createUsersRepository } = require('../../../platform/storage/src/users');
const { createSessionsRepository } = require('../../../platform/storage/src/sessions');

function account(suffix, extra = {}) {
  return { username: `user_${suffix}`, email: `${suffix}@example.invalid`, displayName: suffix,
    passwordHash: '$argon2id$fixture-hash', ...extra };
}

test('migrations serialize concurrent startup, can be rerun, and preserve existing accounts', async (t) => {
  const pool = await isolatedDatabase(t);
  await Promise.all([migrate(pool), migrate(pool)]);
  const users = createUsersRepository(pool);
  const original = await users.create(account('migration'));
  await migrate(pool);
  assert.equal((await users.findByLogin('user_migration')).id, original.id);
  const versions = await pool.query('SELECT version FROM public.thirdhand_schema_migrations ORDER BY version');
  assert.deepEqual(versions.rows.map(r => r.version), ['001-identity.sql', '002-devices-runs.sql', '003-telemetry.sql', '004-auth-rate-limits.sql', '005-profile-session-notifications.sql', '006-control-bindings.sql', '007-raw-batch-payloads.sql', '008-export-jobs.sql', '009-scoped-device-control.sql', '010-admin-applications.sql']);
  assert.equal((await pool.query("SELECT to_regclass('auth.user_onboarding') AS table_name")).rows[0].table_name, null);
});

test('registration normalizes identifiers, enforces uniqueness and cannot grant a role', async (t) => {
  const pool = await isolatedDatabase(t); await migrate(pool);
  const users = createUsersRepository(pool);
  const user = await users.create(account('unique', { username: '  Alice  ', email: ' Alice@Example.invalid ', role: 'admin' }));
  assert.equal(user.username, 'alice'); assert.equal(user.email, 'alice@example.invalid');
  assert.equal(user.role, 'observer'); assert.equal(user.locale, 'en'); assert.equal(user.status, 'pending_email');
  assert.equal((await users.findByLogin(' ALICE@EXAMPLE.INVALID ')).id, user.id);
  await assert.rejects(users.create(account('second', { username: 'ALICE' })), { code: '23505' });
  await assert.rejects(users.create(account('third', { email: 'ALICE@EXAMPLE.INVALID' })), { code: '23505' });
  await assert.rejects(pool.query("UPDATE auth.users SET role='operator' WHERE id=$1", [user.id]), { code: '23514' });
  await assert.rejects(users.create(account('invalid', { locale: 'fr' })), /locale/i);
  assert.equal(await users.findByLogin("' OR 1=1 --"), null);
});

test('a failed migration rolls back its DDL and can be repaired before application; applied checksums are immutable', async (t) => {
  const pool = await isolatedDatabase(t);
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'thirdhand-migrations-'));
  t.after(() => {
    const target=path.resolve(directory);
    assert.equal(path.dirname(target),path.resolve(os.tmpdir()));
    assert.ok(path.basename(target).startsWith('thirdhand-migrations-'));
    return fs.rm(target,{recursive:true,force:true});
  });
  await fs.writeFile(path.join(directory, '001-test.sql'), 'CREATE TABLE retained(id integer); INSERT INTO retained VALUES(7);');
  await fs.writeFile(path.join(directory, '002-test.sql'), 'CREATE TABLE rolled_back(id integer); SELECT 1/0;');
  await assert.rejects(migrate(pool, { directory }), { code: '22012' });
  assert.equal((await pool.query('SELECT id FROM retained')).rows[0].id, 7);
  assert.equal((await pool.query("SELECT to_regclass('rolled_back') AS name")).rows[0].name, null);
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM thirdhand_schema_migrations')).rows[0].n, 1);
  await fs.writeFile(path.join(directory, '002-test.sql'), 'CREATE TABLE repaired(id integer);');
  await migrate(pool, { directory });
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM thirdhand_schema_migrations')).rows[0].n, 2);
  await fs.writeFile(path.join(directory, '001-test.sql'), 'DROP TABLE retained;');
  await assert.rejects(migrate(pool, { directory }), /checksum changed/i);
  assert.equal((await pool.query('SELECT id FROM retained')).rows[0].id, 7);
});

test('a user can keep multiple independent sessions but an administrator session requires MFA', async (t) => {
  const pool = await isolatedDatabase(t); await migrate(pool);
  const users = createUsersRepository(pool); const sessions = createSessionsRepository(pool);
  const user = await users.create(account('sessions'));
  await pool.query("UPDATE auth.users SET status='active', email_verified_at=now() WHERE id=$1", [user.id]);
  const now = new Date();
  const first = await sessions.create({ userId: user.id, tokenHash: 'a'.repeat(64), now });
  const second = await sessions.create({ userId: user.id, tokenHash: 'b'.repeat(64), now });
  assert.notEqual(first.id, second.id); assert.equal(first.mode, 'observe');
  assert.equal((await sessions.findByTokenHash('a'.repeat(64))).userId, user.id);
  await sessions.revoke({ sessionId: first.id, reason: 'logout', now });
  assert.equal((await sessions.findByTokenHash('b'.repeat(64))).revokedAt, null);
  assert.ok((await sessions.findByTokenHash('a'.repeat(64))).revokedAt);
  await assert.rejects(sessions.create({ userId: user.id, tokenHash: 'c'.repeat(64), mode: 'admin', now }), /permission|MFA/i);
});

test('bootstrap is controlled and concurrent role changes cannot remove the last active administrator', async (t) => {
  const pool = await isolatedDatabase(t); await migrate(pool);
  const users = createUsersRepository(pool);
  const a = await users.create(account('admin_a')); const b = await users.create(account('admin_b'));
  await assert.rejects(users.bootstrapAdmin({ verifiedUserId: a.id }), /verified|active/i);
  await pool.query("UPDATE auth.users SET status='active', email_verified_at=now() WHERE id=ANY($1::uuid[])", [[a.id, b.id]]);
  const adminA = await users.bootstrapAdmin({ verifiedUserId: a.id });
  await assert.rejects(users.bootstrapAdmin({ verifiedUserId: b.id }), /already|bootstrap/i);
  await users.requestAdmin({userId:b.id,reason:'test application'});
  const adminB = await users.setRole({ actorId: a.id, userId: b.id, role: 'admin', expectedVersion: 1, reason: 'test grant' });
  const attempts = await Promise.allSettled([
    users.setRole({ actorId: a.id, userId: a.id, role: 'observer', expectedVersion: adminA.roleVersion, reason: 'self downgrade' }),
    users.setRole({ actorId: b.id, userId: b.id, role: 'observer', expectedVersion: adminB.roleVersion, reason: 'self downgrade' })
  ]);
  assert.equal(attempts.filter(r => r.status === 'fulfilled').length, 1);
  const remaining = (await pool.query("SELECT id FROM auth.users WHERE role='admin' AND status='active'")).rows;
  assert.equal(remaining.length, 1);
  await assert.rejects(pool.query("UPDATE auth.users SET status='disabled' WHERE id=$1", [remaining[0].id]), /last.*administrator/i);
  assert.equal((await pool.query('SELECT count(*)::int AS n FROM auth.role_changes')).rows[0].n, 3);
});

test('user history is retained and telemetry ranges reject duplicates across batches and timestamps', async (t) => {
  const pool = await isolatedDatabase(t); await migrate(pool);
  const deviceId = randomUUID(), bootId = randomUUID(), userId = (await createUsersRepository(pool).create(account('history'))).id;
  await pool.query('INSERT INTO ops.devices (id,name,hardware_serial) VALUES ($1,$2,$3)', [deviceId, 'Fake arm', 'fake-serial']);
  await pool.query('INSERT INTO ops.device_boots (boot_id,device_id,agent_version) VALUES ($1,$2,$3)', [bootId, deviceId, 'test']);
  const run = await pool.query("INSERT INTO ops.runs(device_id,boot_id,actor_user_id,actor_kind,actor_display_name,source,status) VALUES($1,$2,$3,'user','history','manual','completed') RETURNING id", [deviceId, bootId, userId]);
  await assert.rejects(pool.query('DELETE FROM auth.users WHERE id=$1', [userId]), { code: '23503' });
  assert.ok(run.rows[0].id);
  const batch = (seq, first, last) => pool.query(`INSERT INTO telemetry.ingest_batches
    (device_id,boot_id,stream_kind,batch_seq,first_seq,last_seq,digest,row_count)
    VALUES ($1,$2,'robot_samples',$3,$4,$5,$6,$7)`, [deviceId, bootId, seq, first, last, 'a'.repeat(64), last - first + 1]);
  await batch(1, 1, 3);
  await assert.rejects(batch(2, 3, 4), { code: '23P01' });
  await assert.rejects(batch(1, 10, 12), { code: '23505' });
  const concurrent = await Promise.allSettled([batch(3, 4, 5), batch(4, 4, 5)]);
  assert.equal(concurrent.filter(r => r.status === 'fulfilled').length, 1);
  await assert.rejects(pool.query(`INSERT INTO telemetry.robot_samples
    (device_id,boot_id,sample_seq,captured_at,monotonic_ns,clock_quality,schema_version,joint_position_rad,sdk_connected,moving)
    VALUES($1,$2,1,'2026-10-30T12:00:00Z',1,'synchronized',1,ARRAY[1.,2.],false,false)`, [deviceId, bootId]), { code: '23514' });
});
