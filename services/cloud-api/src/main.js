'use strict';
const {loadCloudConfig}=require('./config');
const {createCloudApi}=require('./server');
const {createPool}=require('../../../platform/storage/src/pool');
const {createAccounts}=require('../../../platform/identity/src/accounts');
const {createSessions}=require('../../../platform/identity/src/sessions');
const {createMfa}=require('../../../platform/identity/src/mfa');
const {createMailer}=require('../../../platform/identity/src/mail');
const {createSmtpMailer}=require('../../../platform/identity/src/smtp');
const {createHistoryRepository}=require('../../../platform/storage/src/history');
const {createExportService}=require('./jobs/export-worker');
const {createCameraMediaRuntime}=require('./media/runtime');
const {createDeviceRuntime}=require('./device-runtime');

async function startCloudService(config=loadCloudConfig(),{stagingMailbox}={}){
  if(stagingMailbox&&(config.publicOrigin!=='https://staging.uiea-thirdhand.com'||config.smtp))throw Object.assign(Error('Private test inbox requires the staging origin and no SMTP'),{code:'CONFIG_ERROR'});
  const pool=createPool({connectionString:config.databaseUrl,max:4});
  let sessions,server,mail,mediaRuntime;
  try{
    if(config.production){const role=(await pool.query('SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user')).rows[0];if(role.rolsuper||role.rolcreatedb||role.rolcreaterole)throw Object.assign(Error('Runtime role must be unprivileged'),{code:'PRIVILEGED_RUNTIME_ROLE'});}
    // Migrations are a deliberate separate command and identity, never startup DDL.
    await pool.query('SELECT id FROM auth.users LIMIT 0');
    mail=stagingMailbox||(config.smtp?createSmtpMailer(config.smtp):createMailer());
    const mfa=createMfa({pool,keyId:config.mfaKeyId,keys:config.mfaKeys});
    const accounts=createAccounts({pool,mfa,mail,publicOrigin:config.publicOrigin});
    sessions=createSessions({pool,csrfKey:config.csrfKey});await sessions.start();
    if(config.deviceRuntime){mediaRuntime=createDeviceRuntime({pool,sessions,mediaConfig:config.media,config:config.deviceRuntime});await mediaRuntime.listen();}
    else if(config.media){mediaRuntime=createCameraMediaRuntime({pool,sessions,config:config.media});await mediaRuntime.listen();}
    const history=createHistoryRepository(pool,{cursorKey:config.historyCursorKey});
    const exports=config.exportRoot?createExportService({pool,history,root:config.exportRoot}):null;
    server=createCloudApi({pool,accounts,sessions,mfa,history,exports,mediaService:mediaRuntime?.mediaService,controlService:mediaRuntime?.controlService,controlChannels:mediaRuntime?.controlChannels,publicOrigin:config.publicOrigin,trustProxyLoopback:config.trustProxyLoopback});
    await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(config.port,config.host,resolve);});
    return {server,async close(){await mediaRuntime?.close();await server.controlChannel?.close();await new Promise(resolve=>{server.closeAllConnections();server.close(resolve);});await sessions.close();mail.close?.();await pool.end();}};
  }catch(error){if(server)server.close();await mediaRuntime?.close();await sessions?.close();mail?.close?.();await pool.end();throw error;}
}
if(require.main===module){startCloudService().then(service=>{
  process.stdout.write('ThirdHand cloud API started on its private loopback interface; live access requires explicit device enrollment.\n');
  for(const name of ['SIGINT','SIGTERM'])process.once(name,()=>service.close().catch(()=>{process.exitCode=1;}));
}).catch(error=>{process.stderr.write(`Cloud API startup failed: ${error.code==='CONFIG_ERROR'?error.message:error.code||'DATABASE_OR_SERVICE_UNAVAILABLE'}\n`);process.exitCode=1;});}
module.exports={startCloudService};
