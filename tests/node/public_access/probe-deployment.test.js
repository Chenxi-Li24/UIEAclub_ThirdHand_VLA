'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {isolatedDatabase}=require('./database-fixture');
const {migrate}=require('../../../platform/storage/src/migrate');
const {loadProbeConfig,assertProbeRuntime}=require('../../../services/device-relay/src/probe-config');
const {createProbeStore,assertProbeDatabase}=require('../../../services/device-relay/src/probe-service');

test('probe deployment accepts only a private Unix ingress and a local PostgreSQL peer identity',()=>{
  const config=loadProbeConfig({RELAY_MODE:'probe-only'});
  assert.equal(config.socketPath,'/run/thirdhand-relay/edge.sock');
  assert.equal(config.database.host,'/var/run/postgresql');
  assert.equal(config.database.user,'thirdhand-relay');
  assert.equal(config.database.database,'thirdhand_probe');
  for(const env of [{RELAY_MODE:'control'},{RELAY_SOCKET_PATH:'127.0.0.1:3201'},{RELAY_SOCKET_PATH:'/tmp/edge.sock'},
    {RELAY_PG_HOST:'0.0.0.0'},{RELAY_PG_DATABASE:'thirdhand'},{RELAY_REMOTE_CONTROL_ENABLED:'1'}]){
    assert.throws(()=>loadProbeConfig({RELAY_MODE:'probe-only',...env}),{code:'PROBE_CONFIG_INVALID'});
  }
  assert.throws(()=>assertProbeRuntime({platform:'linux',uid:0,version:'24.22.1'}),{code:'PROBE_RUNTIME_REJECTED'});
  assert.throws(()=>assertProbeRuntime({platform:'linux',uid:1001,version:'24.19.0'}),{code:'PROBE_RUNTIME_REJECTED'});
  assert.doesNotThrow(()=>assertProbeRuntime({platform:'linux',uid:1001,version:'24.22.1'}));
});

test('probe registry never exposes executor registration or accepts a control-enabled identity',async()=>{
  let row={id:randomUUID(),remoteControlEnabled:false};
  const store=createProbeStore({async resolveCertificate(){return row;},async registerExecution(){throw Error('must not be exposed');}});
  assert.equal(store.registerExecution,undefined);
  assert.equal((await store.resolveCertificate('f'.repeat(64))).remoteControlEnabled,false);
  row={...row,remoteControlEnabled:true};
  assert.equal(await store.resolveCertificate('f'.repeat(64)),null);
  row=null;assert.equal(await store.resolveCertificate('f'.repeat(64)),null);
});

test('real PostgreSQL probe role is read-only, and startup rejects inherited data or write privileges',async t=>{
  const pool=await isolatedDatabase(t);await migrate(pool);
  await assert.rejects(assertProbeDatabase(pool),{code:'PROBE_DATABASE_PRIVILEGED'});
  const role='probe_'+randomUUID().replaceAll('-','');
  await pool.query(`CREATE ROLE "${role}" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`);
  t.after(()=>pool.query(`DROP ROLE IF EXISTS "${role}"`).catch(()=>{}));
  await pool.query(`GRANT USAGE ON SCHEMA ops TO "${role}"`);
  await pool.query(`GRANT SELECT ON ops.devices,ops.device_credentials TO "${role}"`);
  const client=await pool.connect();
  try{
    await client.query(`SET ROLE "${role}"`);
    await client.query('SET default_transaction_read_only=on');
    await assert.doesNotReject(assertProbeDatabase(client));
    await assert.rejects(client.query('UPDATE ops.devices SET enabled=true'),error=>['25006','42501'].includes(error.code));
    await client.query('RESET ROLE');await client.query('SET default_transaction_read_only=off');
    await client.query(`GRANT SELECT ON auth.users TO "${role}"`);
    await client.query(`SET ROLE "${role}"`);await client.query('SET default_transaction_read_only=on');
    await assert.rejects(assertProbeDatabase(client),{code:'PROBE_DATABASE_PRIVILEGED'});
    await client.query('RESET ROLE');await client.query('SET default_transaction_read_only=off');
    await client.query(`REVOKE SELECT ON auth.users FROM "${role}"`);
    await client.query(`GRANT UPDATE ON ops.devices TO "${role}"`);
    await client.query(`SET ROLE "${role}"`);await client.query('SET default_transaction_read_only=on');
    await assert.rejects(assertProbeDatabase(client),{code:'PROBE_DATABASE_PRIVILEGED'});
  }finally{
    await client.query('RESET ROLE');await client.query('SET default_transaction_read_only=off');
    await client.query(`DROP OWNED BY "${role}"`);client.release();
    await pool.query(`DROP ROLE "${role}"`);
  }
});

test('the dedicated bootstrap schema supports the read-only registry without application or control tables',async t=>{
  const pool=await isolatedDatabase(t),role='probe_'+randomUUID().replaceAll('-','');
  const fs=require('node:fs/promises');
  const source=await fs.readFile('deploy/public-access/probe/bootstrap.sql','utf8');
  const ddl=source.slice(source.indexOf('BEGIN;')).replaceAll('AUTHORIZATION postgres','AUTHORIZATION CURRENT_USER').replaceAll('"thirdhand-relay"',`"${role}"`);
  await pool.query(`CREATE ROLE "${role}" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`);
  const client=await pool.connect();
  try{
    await client.query(ddl);
    const tables=(await client.query("SELECT tablename FROM pg_tables WHERE schemaname='ops' ORDER BY tablename")).rows;
    assert.deepEqual(tables.map(row=>row.tablename),['device_credentials','devices']);
    await client.query(`SET ROLE "${role}"`);await client.query('SET default_transaction_read_only=on');
    await assert.doesNotReject(assertProbeDatabase(client));
    assert.equal((await client.query('SELECT * FROM ops.devices')).rowCount,0);
    assert.equal((await client.query("SELECT to_regclass('ops.control_leases') AS relation")).rows[0].relation,null);
  }finally{
    await client.query('RESET ROLE');await client.query('SET default_transaction_read_only=off');
    await client.query(`DROP OWNED BY "${role}"`);client.release();
    await pool.query(`DROP ROLE "${role}"`);
  }
});
