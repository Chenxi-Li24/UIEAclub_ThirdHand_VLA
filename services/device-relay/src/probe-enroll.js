'use strict';
const {X509Certificate,randomUUID}=require('node:crypto');
const {transaction}=require('../../../platform/storage/src/pool');
const {UUID}=require('./protocol');
function rejected(){return Object.assign(Error('Probe client certificate rejected'),{code:'PROBE_CERTIFICATE_REJECTED'});}
async function enrollProbeCredential({pool,certificatePem,caPem,deviceId}){
  let cert,ca;const now=Date.now();
  try{
    cert=new X509Certificate(certificatePem);ca=new X509Certificate(caPem);
    if(!UUID.test(deviceId)||cert.ca||!ca.ca||!ca.checkIssued(ca)||!ca.verify(ca.publicKey)||
      !cert.checkIssued(ca)||!cert.verify(ca.publicKey)||cert.publicKey.asymmetricKeyType!=='ed25519'||
      cert.subjectAltName!==`URI:urn:thirdhand:probe:${deviceId}`||cert.keyUsage?.length!==1||
      cert.keyUsage[0]!=='1.3.6.1.5.5.7.3.2'||
      cert.validFromDate.getTime()>now||cert.validToDate.getTime()<=now||
      cert.validToDate.getTime()-now>7*86400000+300000||
      ca.validFromDate.getTime()>now||ca.validToDate.getTime()<=cert.validToDate.getTime())throw rejected();
  }catch{throw rejected();}
  const certificateId=randomUUID();
  return transaction(pool,async client=>{
    // Deliberately no UPSERT. Existing, disabled or revoked identities require
    // a separate review rather than an import command silently reactivating them.
    await client.query(`INSERT INTO ops.devices(id,name,hardware_serial,enabled,capabilities)
      VALUES($1,'Campus Ubuntu network probe',$2,true,$3)`,[deviceId,`probe-only:${deviceId}`,
      {probeOnly:true,remoteControlEnabled:false}]);
    await client.query(`INSERT INTO ops.device_credentials(id,device_id,certificate_serial,fingerprint_sha256,public_key,not_before,expires_at)
      VALUES($1,$2,$3,$4,$5,$6,$7)`,[certificateId,deviceId,cert.serialNumber,
      cert.fingerprint256.replaceAll(':','').toLowerCase(),cert.publicKey.export({type:'spki',format:'pem'}),cert.validFromDate,cert.validToDate]);
    return {deviceId,certificateId,expiresAt:cert.validToDate.toISOString(),controlAuthorized:false};
  });
}
if(require.main===module){
  (async()=>{
    if(process.platform!=='linux'||process.getuid?.()===0||process.argv.length!==5)throw rejected();
    const fs=require('node:fs/promises'),{Pool}=require('pg');
    // Run explicitly under the local PostgreSQL administrator OS identity.
    const pool=new Pool({host:'/var/run/postgresql',database:'thirdhand_probe',user:'postgres',max:1,connectionTimeoutMillis:5000});
    try{
      const result=await enrollProbeCredential({pool,deviceId:process.argv[2],
        certificatePem:await fs.readFile(process.argv[3]),caPem:await fs.readFile(process.argv[4])});
      process.stdout.write(JSON.stringify(result)+'\n');
    }finally{await pool.end();}
  })().catch(()=>{process.stderr.write('PROBE_ENROLLMENT_FAILED\n');process.exitCode=1;});
}
module.exports={enrollProbeCredential};
