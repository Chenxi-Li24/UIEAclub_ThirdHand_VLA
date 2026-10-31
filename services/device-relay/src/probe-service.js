'use strict';
const {createDeviceRegistry}=require('./registry');
const {createDeviceRelay}=require('./server');

function createProbeStore(registry){
  return Object.freeze({async resolveCertificate(fingerprint){
    const row=await registry.resolveCertificate(fingerprint);
    return row&&row.remoteControlEnabled!==true?Object.freeze({...row,remoteControlEnabled:false}):null;
  }});
}
function denied(){return Object.assign(Error('Dedicated read-only device registry role required'),{code:'PROBE_DATABASE_PRIVILEGED'});}
async function assertProbeDatabase(pool){
  const role=(await pool.query(`SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,
    has_database_privilege(current_user,current_database(),'CREATE') AS db_create,
    current_setting('default_transaction_read_only') AS read_only,
    current_setting('server_version_num')::integer AS version
    FROM pg_roles WHERE rolname=current_user`)).rows[0];
  if(!role||['rolsuper','rolcreatedb','rolcreaterole','rolreplication','rolbypassrls','db_create'].some(k=>role[k])||
    role.read_only!=='on'||role.version<170011||role.version>=180000)throw denied();
  const grants=(await pool.query(`SELECT n.nspname||'.'||c.relname AS name,
    has_table_privilege(current_user,c.oid,'SELECT') AS can_read,
    has_table_privilege(current_user,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER') AS can_write
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE c.relkind IN ('r','p','v','m','f') AND n.nspname NOT IN ('pg_catalog','information_schema')
    AND n.nspname NOT LIKE 'pg_toast%' AND n.nspname NOT LIKE 'pg_temp_%'`)).rows;
  const allowed=new Set(['ops.devices','ops.device_credentials']);
  if(grants.some(row=>row.can_write||row.can_read&&!allowed.has(row.name))||
    [...allowed].some(name=>!grants.some(row=>row.name===name&&row.can_read)))throw denied();
  const creates=(await pool.query(`SELECT 1 FROM pg_namespace WHERE nspname NOT LIKE 'pg_%'
    AND nspname<>'information_schema' AND has_schema_privilege(current_user,oid,'CREATE') LIMIT 1`)).rowCount;
  if(creates)throw denied();
  const memberships=(await pool.query(`SELECT 1 FROM pg_roles WHERE rolname<>current_user
    AND pg_has_role(current_user,oid,'MEMBER') LIMIT 1`)).rowCount;
  if(memberships)throw denied();
}
function createProbeRelay({pool,tls=null,trustedUnixProxy=false}){
  // Deliberately no signer, control channel, telemetry ingest or media adapter.
  const store=createProbeStore(createDeviceRegistry({pool}));
  const relay=createDeviceRelay({store,tls,trustedUnixProxy,maxDevices:1});
  return {server:relay.server,close:relay.close};
}
module.exports={createProbeStore,assertProbeDatabase,createProbeRelay};
