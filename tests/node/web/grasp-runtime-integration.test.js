'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const fs=require('node:fs');
const {loadConfig}=require('../../../apps/web/src/config');
const root=path.resolve(__dirname,'../../..');

test('unified profile constructs lazy grasp and TCP wiring from portable bound evidence',async()=>{
 const profile=JSON.parse(fs.readFileSync(path.join(root,'configs/runtime/manual-control.json')));
 const env=Object.fromEntries(Object.entries(profile.services.find(s=>s.id==='web').env).map(([k,v])=>[k,v.replaceAll('${ROOT}',root)]));
 const config=loadConfig(env);
 assert.equal(config.tcpCalibrationEnabled,true);
 const factory=require('../../../apps/web/src/grasp');
 const grasp=factory.createFromFile(env.WEB_GRASP_CONFIG,{ownerToken:'offline-test'});
 try{assert.equal(grasp.status().phase,'idle');assert.equal(grasp.status().legacyGraspEnabled,false);}
 finally{await grasp.close();}
 const {loadPolicy}=require('../../../services/vision/src/frames/robot_frame_normalization');
 const policy=loadPolicy(config.tcpCalibrationFramePolicyFile);
 assert.equal(policy.T_flange_sdk_tool[0][3],0.17334);
 const handeye=JSON.parse(fs.readFileSync(path.join(root,'configs/vision/handeye-flange-normalized.json')));
 assert.equal(handeye.frame_normalization.policy_id,policy.id);
 assert.equal(handeye.physical_validation.status,'pending');
});
