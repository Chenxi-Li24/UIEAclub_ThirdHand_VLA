'use strict';
const {loadCloudConfig}=require('./config');
const {startCloudService}=require('./main');
const {createStagingMailbox}=require('../../../platform/identity/src/staging-mailbox');
async function startStagingService(){
  const config=loadCloudConfig();
  const version=process.versions.node.split('.').map(Number);
  if(process.platform!=='linux'||process.getuid()===0||version[0]!==24||version[1]<22||version[1]===22&&version[2]<1||
    !config.production||config.publicOrigin!=='https://staging.uiea-thirdhand.com')throw Error('STAGING_RUNTIME_REJECTED');
  const stagingMailbox=config.smtp?undefined:await createStagingMailbox({directory:process.env.STAGING_PRIVATE_MAIL_DIRECTORY,
    publicOrigin:config.publicOrigin,allowedRecipients:JSON.parse(process.env.STAGING_TEST_RECIPIENTS||'[]')});
  return startCloudService(config,{stagingMailbox});
}
if(require.main===module)startStagingService().then(service=>{
  process.stdout.write('ThirdHand isolated staging API ready; motion remains unavailable.\n');
  for(const signal of ['SIGINT','SIGTERM'])process.once(signal,()=>service.close().catch(()=>{process.exitCode=1;}));
}).catch(()=>{process.stderr.write('STAGING_STARTUP_FAILED\n');process.exitCode=1;});
module.exports={startStagingService};
