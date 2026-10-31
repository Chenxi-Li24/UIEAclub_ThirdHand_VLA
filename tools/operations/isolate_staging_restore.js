'use strict';
const {transaction}=require('../../platform/storage/src/pool');
const fail=code=>Object.assign(Error(code),{code});
async function isolateStagingRestore(pool,{epochFloors,confirmation}={}){
  if(confirmation!=='ISOLATE_STAGING_RESTORE')throw fail('RESTORE_CONFIRMATION_REQUIRED');
  return transaction(pool,async db=>{
    const name=(await db.query('SELECT current_database() AS name')).rows[0].name;
    if(!/^thirdhand_(?:stage_restore(?:_|$)|test_)/.test(name))throw fail('RESTORE_TARGET_REJECTED');
    await db.query('SELECT pg_advisory_xact_lock(240103,99)');
    const devices=(await db.query('SELECT id,control_epoch FROM ops.devices FOR UPDATE')).rows;
    for(const d of devices){
      const floor=epochFloors?.[d.id];
      if(typeof floor!=='string'||!/^\d{1,19}$/.test(floor)||BigInt(floor)>9223372036854775806n||BigInt(d.control_epoch)>9223372036854775806n)throw fail('RESTORE_EPOCH_FLOOR_REQUIRED');
    }
    await db.query("UPDATE auth.sessions SET revoked_at=coalesce(revoked_at,now()),revocation_reason=coalesce(revocation_reason,'staging_restore_isolated')");
    await db.query('UPDATE auth.users SET role_version=role_version+1,updated_at=now()');
    await db.query('UPDATE auth.one_time_tokens SET consumed_at=coalesce(consumed_at,now())');
    // Recovery codes and TOTP replay counters can roll back with the snapshot.
    // Keep them as evidence, but require fresh MFA enrollment after isolation.
    await db.query('UPDATE auth.mfa_credentials SET revoked_at=coalesce(revoked_at,now())');
    await db.query('UPDATE ops.device_credentials SET revoked_at=coalesce(revoked_at,now())');
    for(const d of devices)await db.query('UPDATE ops.devices SET enabled=false,control_epoch=greatest(control_epoch,$2::bigint)+1 WHERE id=$1',[d.id,epochFloors[d.id]]);
    await db.query("UPDATE ops.control_leases SET state='failed',released_at=now(),release_reason='staging_restore_isolated' WHERE state IN ('requested','active','revoking')");
    await db.query("UPDATE ops.control_takeovers SET state='failed' WHERE state IN ('pending','stopping')");
    await db.query("UPDATE ops.commands SET state='unknown',result=jsonb_build_object('code','RESTORE_RESULT_UNKNOWN') WHERE state IN ('accepted','started')");
    await db.query("UPDATE ops.runs SET status='unknown',ended_at=coalesce(ended_at,now()) WHERE status IN ('requested','running')");
    await db.query('UPDATE ops.execution_instances SET ended_at=coalesce(ended_at,now())');
    await db.query('UPDATE ops.device_boots SET ended_at=coalesce(ended_at,now())');
    await db.query("UPDATE ops.export_jobs SET status='expired',error_code='RESTORE_REAUTH_REQUIRED' WHERE status IN ('queued','running','completed')");
    await db.query("INSERT INTO security.audit_events(event_code,outcome,context) VALUES('recovery.staging.isolated','success',$1)",[{devices:devices.length,externalEpochFloor:true}]);
    return {isolated:true,devices:devices.length,controlAuthorized:false};
  });
}
if(require.main===module){(async()=>{
  const fs=require('node:fs/promises'),{createPool}=require('../../platform/storage/src/pool');
  if(process.argv.length!==4)throw fail('RESTORE_CONFIRMATION_REQUIRED');
  const floors=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
  const pool=createPool({connectionString:process.env.MIGRATION_DATABASE_URL,max:1});
  try{process.stdout.write(JSON.stringify(await isolateStagingRestore(pool,{epochFloors:floors,confirmation:process.argv[3]}))+'\n');}finally{await pool.end();}
})().catch(()=>{process.stderr.write('STAGING_RESTORE_ISOLATION_FAILED\n');process.exitCode=1;});}
module.exports={isolateStagingRestore};
