'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os');
const {randomUUID}=require('node:crypto');
const {promisify}=require('node:util');
const run=promisify(require('node:child_process').execFile);
const {isolatedDatabase}=require('./database-fixture');
const {migrate}=require('../../../platform/storage/src/migrate');
const {enrollProbeCredential}=require('../../../services/device-relay/src/probe-enroll');

test('probe enrollment verifies CA, Ed25519 client purpose and bound URI; a revoked record cannot be reactivated',async t=>{
  const pool=await isolatedDatabase(t);await migrate(pool);
  const deviceId=randomUUID(),dir=await fs.mkdtemp(path.join(os.tmpdir(),'thirdhand-probe-enroll-'));
  try{
    await run(process.env.EDGE_TEST_PYTHON||'python',['tests/python/edge_agent/pki_fixture.py',dir,deviceId]);
    const caPem=await fs.readFile(path.join(dir,'ca.pem'));
    const certificatePem=await fs.readFile(path.join(dir,'device.pem'));
    for(const value of [{deviceId:randomUUID(),certificatePem},{deviceId,certificatePem:await fs.readFile(path.join(dir,'server.pem'))},
      {deviceId,certificatePem:await fs.readFile(path.join(dir,'unknown.pem'))}]){
      await assert.rejects(enrollProbeCredential({pool,caPem,...value}),{code:'PROBE_CERTIFICATE_REJECTED'});
    }
    const result=await enrollProbeCredential({pool,caPem,certificatePem,deviceId});
    assert.equal(result.deviceId,deviceId);
    const row=(await pool.query('SELECT enabled,capabilities,hardware_serial FROM ops.devices WHERE id=$1',[deviceId])).rows[0];
    assert.equal(row.enabled,true);assert.equal(row.capabilities.remoteControlEnabled,false);assert.equal(row.capabilities.probeOnly,true);
    assert.equal(row.hardware_serial,`probe-only:${deviceId}`);
    await pool.query('UPDATE ops.devices SET enabled=false WHERE id=$1',[deviceId]);
    await pool.query('UPDATE ops.device_credentials SET revoked_at=now() WHERE id=$1',[result.certificateId]);
    await assert.rejects(enrollProbeCredential({pool,caPem,certificatePem,deviceId}),{code:'23505'});
    assert.equal((await pool.query('SELECT enabled FROM ops.devices WHERE id=$1',[deviceId])).rows[0].enabled,false);
  }finally{
    const target=path.resolve(dir);assert.equal(path.dirname(target),path.resolve(os.tmpdir()));
    assert.ok(path.basename(target).startsWith('thirdhand-probe-enroll-'));
    await fs.rm(target,{recursive:true,force:true,maxRetries:5,retryDelay:50});
  }
});
