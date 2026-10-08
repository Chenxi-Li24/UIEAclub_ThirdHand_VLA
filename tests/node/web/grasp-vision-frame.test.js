'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {VisionClient}=require('../../../apps/web/src/active-depth/vision-client');
function client(projectionFrame=9,observationFrame=9){
 const detection={frame_id:9,ts:1000,selected_stable_id:2,evidence_id:'sha256:'+'a'.repeat(64),
  targets:[{stable_id:2}],pose:{width_m:0.03},frame_projection:{frame_id:projectionFrame,status:'ready',T_base_camera:[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]}};
 const observation={frameId:observationFrame,observedAtMs:1000,selectedStableId:2,targets:detection.targets,pose:detection.pose,robotControlEnabled:false};
 return new VisionClient({baseUrl:'http://127.0.0.1:9983',fetchImpl:async url=>({ok:true,text:async()=>JSON.stringify(url.endsWith('/status')?{detection,runtimeEvidence:{calibration_approved:false}}:observation)})});
}
test('same-frame normalized observation retains correlated projection without enabling autonomy',async()=>{
 const {observation}=await client().snapshot(2);assert.equal(observation.frame_projection?.frame_id,9);
 assert.equal(observation.robotControlEnabled,false);assert.equal(observation.calibration_approved,false);
});
test('racing newer status uses its complete frame and rejects mismatched projection',async()=>{
 const {observation}=await client(9,8).snapshot(2);assert.equal(observation.frameId,9);assert.equal(observation.frame_projection.frame_id,9);
 await assert.rejects(client(8).snapshot(2),{code:'vision_projection_mismatch'});
});
