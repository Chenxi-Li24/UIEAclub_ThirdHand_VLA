'use strict';
function invalid(){throw Object.assign(Error('Invalid probe-only deployment configuration'),{code:'PROBE_CONFIG_INVALID'});}
function loadProbeConfig(env=process.env){
  if(env.RELAY_MODE!=='probe-only'||env.RELAY_REMOTE_CONTROL_ENABLED!==undefined)invalid();
  const socketPath=env.RELAY_SOCKET_PATH||'/run/thirdhand-relay/edge.sock';
  const host=env.RELAY_PG_HOST||'/var/run/postgresql';
  if(socketPath!=='/run/thirdhand-relay/edge.sock'||!['/var/run/postgresql','/run/postgresql'].includes(host)||
    env.RELAY_PG_DATABASE&&env.RELAY_PG_DATABASE!=='thirdhand_probe'||
    env.RELAY_PG_USER&&env.RELAY_PG_USER!=='thirdhand-relay'||env.RELAY_DATABASE_URL)invalid();
  return Object.freeze({socketPath,database:Object.freeze({host,port:5432,database:'thirdhand_probe',user:'thirdhand-relay',
    max:2,connectionTimeoutMillis:5000,idleTimeoutMillis:30000,statement_timeout:2000,
    options:'-c default_transaction_read_only=on',application_name:'thirdhand-probe-only'})});
}
function assertProbeRuntime({platform=process.platform,uid=process.getuid?.(),version=process.versions.node}={}){
  const match=/^(\d+)\.(\d+)\.(\d+)$/.exec(version);
  if(platform!=='linux'||!Number.isInteger(uid)||uid===0||!match||Number(match[1])!==24||
    Number(match[2])<22||Number(match[2])===22&&Number(match[3])<1){
    throw Object.assign(Error('Non-root Linux and patched Node24 required'),{code:'PROBE_RUNTIME_REJECTED'});
  }
}
module.exports={loadProbeConfig,assertProbeRuntime};
