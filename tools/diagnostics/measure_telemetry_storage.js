'use strict';
// Synthetic capacity scenario only. Uses/drops one newly created test database.
const {Pool}=require('pg');
const {randomUUID,createHash}=require('node:crypto');
const os=require('node:os');
const {migrate}=require('../../platform/storage/src/migrate');
const {createIngestRepository}=require('../../platform/storage/src/ingest');

async function measure({samples=72000,rateHz=20}={}){
  if(!Number.isSafeInteger(samples)||samples<1||samples>1000000||!Number.isFinite(rateHz)||rateHz<1||rateHz>1000)throw Error('Invalid synthetic scenario');
  const source=new URL(process.env.TEST_DATABASE_URL||'');
  if(!/^thirdhand_test(?:_|$)/.test(source.pathname.slice(1)))throw Error('Dedicated TEST_DATABASE_URL required');
  const admin=new Pool({connectionString:source.toString(),max:1}),name=`thirdhand_test_capacity_${randomUUID().replaceAll('-','')}`;
  let pool,created=false;
  try{
    await admin.query(`CREATE DATABASE "${name}"`);created=true;
    source.pathname='/'+name;pool=new Pool({connectionString:source.toString(),max:2});await migrate(pool);
    const deviceId=randomUUID(),bootId=randomUUID(),certificateId=randomUUID(),stamp=new Date();
    await pool.query("INSERT INTO ops.devices(id,name,hardware_serial,enabled,capabilities) VALUES($1,'Synthetic capacity only',$2,true,$3)",[deviceId,deviceId,{deviceClass:'synthetic'}]);
    await pool.query("INSERT INTO ops.device_credentials(id,device_id,certificate_serial,fingerprint_sha256,public_key,not_before,expires_at) VALUES($1,$2,$6,$3,'synthetic-only',$4,$5)",[certificateId,deviceId,'f'.repeat(64),new Date(stamp.getTime()-86400000),new Date(stamp.getTime()+86400000),certificateId]);
    await pool.query('SELECT telemetry.ensure_month_partition($1::date)',[stamp.toISOString().slice(0,7)+'-01']);
    const ingest=createIngestRepository(pool),context={deviceId,certificateId,bootId};
    const storage=async()=>({bytes:Number((await pool.query('SELECT pg_database_size(current_database()) AS bytes')).rows[0].bytes),lsn:(await pool.query('SELECT pg_current_wal_insert_lsn() AS lsn')).rows[0].lsn});
    const before=await storage(),start=performance.now();let batchSeq=0,payloadBytes=0,seed=0x12345678;
    const random=()=>{seed^=seed<<13;seed^=seed>>>17;seed^=seed<<5;return (seed>>>0)/4294967296;};
    const midnight=new Date(Date.UTC(stamp.getUTCFullYear(),stamp.getUTCMonth(),stamp.getUTCDate())).getTime();
    for(let first=0;first<samples;first+=100){
      const count=Math.min(100,samples-first),batchId=randomUUID(),rows=[];
      for(let index=0;index<count;index++){
        const sequence=first+index,time=midnight+Math.round(sequence*1000/rateHz),joints=[0,Math.PI/2,-Math.PI/2,0,0,0].map((value,joint)=>value+Math.sin(sequence/71+joint)*0.015+(random()-0.5)*0.0002);
        rows.push({sequence,capturedAt:new Date(time).toISOString(),monotonicNs:String(1000000000n+BigInt(Math.round(sequence*1000000000/rateHz))),clockQuality:'estimated',
          jointPositionRad:joints,jointVelocityRadS:joints.map(()=>random()*0.003),jointTorqueNm:joints.map(()=>random()*0.1),jointCurrentA:null,jointTemperatureC:null,
          sdkConnected:true,moving:true,tcpPositionM:null,tcpFrameId:null,toolVersion:'synthetic-tool-v1',calibrationVersion:'synthetic-calibration-v1',
          fieldAvailability:{jointPositionRad:true,jointVelocityRadS:true,jointTorqueNm:true,jointCurrentA:false,jointTemperatureC:false,tcpPositionM:false},
          extra:{sourceMode:'simulation',synthetic:true,sourceSequence:sequence,flangePositionM:[0.2+random()*0.001,0,0.3],target:{jointPositionRad:joints.map(value=>value+0.01)},rawState:{type:'robot_state',joints_deg:joints.map(value=>value*180/Math.PI),ts:time,connected:true,moving:true}}});
      }
      const raw=Buffer.from(JSON.stringify({schema:1,agentVersion:'0.1.0',batchId,deviceId,bootId,streamKind:'robot_samples',batchSequence:batchSeq++,firstSequence:first,lastSequence:first+count-1,rows}));
      // This scenario intentionally uses full variable fields; select a bounded
      // batch size rather than dropping fields to fit the transport.
      if(raw.length>262144)throw Error('Synthetic batch exceeds the protocol limit; reduce batch size');
      payloadBytes+=raw.length;
      await ingest.ingestBatch(context,{batchId,digest:createHash('sha256').update(raw).digest('hex'),payloadBase64url:raw.toString('base64url')});
    }
    const after=await storage(),rows=Number((await pool.query('SELECT count(*) FROM telemetry.robot_samples')).rows[0].count),rawCount=Number((await pool.query('SELECT count(*) FROM telemetry.ingest_batch_payloads')).rows[0].count);
    const walBytes=Number((await pool.query('SELECT pg_wal_lsn_diff($1::pg_lsn,$2::pg_lsn) AS bytes',[after.lsn,before.lsn])).rows[0].bytes);
    if(rows!==samples||rawCount!==batchSeq)throw Error('Capacity run did not persist the complete sample set');
    return {kind:'synthetic_capacity_scenario',measuredOn:new Date().toISOString(),runtime:{node:process.version,os:os.platform(),architecture:os.arch()},samples:rows,batches:batchSeq,configuredScenarioHz:rateHz,representedSeconds:samples/rateHz,
      elapsedSeconds:Number(((performance.now()-start)/1000).toFixed(3)),acceptedPayloadBytes:payloadBytes,databaseGrowthBytes:after.bytes-before.bytes,clusterWalAdvanceBytes:walBytes,bytesPerSample:Number(((after.bytes-before.bytes)/samples).toFixed(2)),
      limits:['Synthetic state values; no SDK, CAN or camera was used.','The rate is a scenario input, not a measured physical publisher rate.','Windows development PostgreSQL; not a cloud latency or capacity acceptance.','WAL advance is cluster-wide and may include background work.','No raw history retention/cleanup policy was applied.']};
  }finally{
    await pool?.end();
    if(created){if(!/^thirdhand_test_capacity_[a-f0-9]{32}$/.test(name))throw Error('Invalid cleanup database');await admin.query(`DROP DATABASE "${name}" WITH (FORCE)`);}
    await admin.end();
  }
}
if(require.main===module)measure().then(value=>process.stdout.write(JSON.stringify(value,null,2)+'\n')).catch(error=>{process.stderr.write(`Synthetic storage measurement failed: ${error.code||error.message}\n`);process.exitCode=1;});
module.exports={measure};
