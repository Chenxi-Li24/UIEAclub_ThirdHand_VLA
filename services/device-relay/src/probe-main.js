'use strict';
const fs=require('node:fs/promises');
const {Pool}=require('pg');
const {loadProbeConfig,assertProbeRuntime}=require('./probe-config');
const {assertProbeDatabase,createProbeRelay}=require('./probe-service');

async function startProbeService(config=loadProbeConfig()){
  assertProbeRuntime();process.umask(0o077);
  const pool=new Pool(config.database);let relay;
  try{
    await assertProbeDatabase(pool);
    relay=createProbeRelay({pool,trustedUnixProxy:true});
    await new Promise((resolve,reject)=>{relay.server.once('error',reject);relay.server.listen(config.socketPath,resolve);});
    await fs.chmod(config.socketPath,0o660);
    let closing;
    return {async close(){return closing||=(async()=>{await relay.close();await pool.end();})();}};
  }catch(error){await relay?.close();await pool.end();throw error;}
}
if(require.main===module){
  startProbeService().then(service=>{
    process.stdout.write('ThirdHand device probe relay ready; control unavailable.\n');
    for(const name of ['SIGINT','SIGTERM'])process.once(name,()=>service.close().catch(()=>{process.exitCode=1;}));
  }).catch(error=>{
    const safe=new Set(['PROBE_CONFIG_INVALID','PROBE_RUNTIME_REJECTED','PROBE_DATABASE_PRIVILEGED','EADDRINUSE','EACCES','ECONNREFUSED']);
    process.stderr.write(`Probe relay startup failed: ${safe.has(error.code)?error.code:'PROBE_STARTUP_FAILED'}\n`);
    process.exitCode=1;
  });
}
module.exports={startProbeService};
