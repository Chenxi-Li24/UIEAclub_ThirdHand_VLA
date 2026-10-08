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
function trackingClient(change=()=>{}){
 const detection={frame_id:12,ts:1000,selected_stable_id:2,evidence_id:null,
  targets:[{stable_id:2,track_state:'confirmed',centroid_xy:[317,360],depth_valid:false,camera_xyz_m:null}],
  frame_projection:{frame_id:12,status:'invalid',reason:'robot_not_stationary_or_healthy'}};
 change(detection);
 return new VisionClient({baseUrl:'http://127.0.0.1:9983',fetchImpl:async url=>{
  assert.ok(url.endsWith('/api/vision/status'),'motion tracking must use one complete current detection frame');
  return {ok:true,text:async()=>JSON.stringify({detection})};
 }});
}
test('motion tracking uses current RGB identity without requiring stationary depth projection evidence',async()=>{
 const {observation}=await trackingClient().trackingSnapshot(2);
 assert.equal(observation.frameId,12);assert.equal(observation.observedAtMs,1000);
 assert.equal(observation.selectedStableId,2);assert.equal(observation.targets[0].track_state,'confirmed');
 assert.deepEqual(observation.targets[0].centroid_xy,[317,360]);
 assert.equal(observation.frame_projection,undefined);
});
test('motion tracking rejects switched duplicate and malformed detection frames',async()=>{
 for(const [change,code] of [[d=>d.selected_stable_id=1,'vision_target_mismatch'],
  [d=>d.targets.push({...d.targets[0]}),'vision_target_mismatch'],
  [d=>d.frame_id=null,'vision_frame_invalid'],[d=>delete d.ts,'vision_frame_invalid']]){
  await assert.rejects(trackingClient(change).trackingSnapshot(2),{code});
 }
});
