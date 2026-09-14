'use strict';
const assert = require('node:assert/strict');
const { buildSupervisedPlan, motionDuration, verifyHold } = require('../supervised-grasp-plan');

const now = 2000;
const observation = {
  valid: true, target_id: 1, frame_id: 20, observed_at_ms: 1900,
  pixel_uv: [320, 240], camera_xyz_m: [0, 0, 0.3],
  base_xyz_m: [0.40, 0.02, 0.15], width_m: 0.055,
  calibration_id: 'sha256:' + 'a'.repeat(64),
  robot_state_ts: 1900, physical_validation: 'pending',
  supervised_base_candidate_valid: true,
  robot_pose_blockers: [],
  candidate_offset_base_m_applied: [0,0,0],
  handeye: {calibration_id:'sha256:' + 'a'.repeat(64), effective_matrix_semantics:'T_sdk_tool_camera'},
};
const settings = {
  targetId: 1, maxObservationAgeMs: 300, maxRobotAgeMs: 250,
  eulerRad: [0, 0, 0], graspOffsetM: [0, 0, 0],
  pregraspHeightM: 0.10, liftHeightM: 0.08,
  workspace: {x:[0.15,0.66],y:[-0.45,0.45],z:[0.06,0.65]},
};
const result = buildSupervisedPlan(observation, settings, now);
assert.equal(result.approved, true);
assert.deepEqual(result.plan.graspM, [0.4, 0.02, 0.15]);
assert.deepEqual(result.plan.pregraspM, [0.4, 0.02, 0.25]);
assert.deepEqual(result.plan.retreatM, [0.4, 0.02, 0.23]);
assert.equal(result.physicalValidation, 'pending');
// A fixed rule height still needs a fresh, fully validated 3D observation.
// The visible portion can move vertically in the eye-in-hand image, while
// the upright bottle's measured Base XY remains the grasp-axis estimate.
const fixedSettings = {...settings, fixedGraspBaseZM:0.13};
const highVisiblePoint = {...observation, base_xyz_m:[0.40,0.02,0.22]};
const fixed = buildSupervisedPlan(highVisiblePoint, fixedSettings, now);
assert.equal(fixed.approved, true);
assert.deepEqual(fixed.plan.graspM, [0.4,0.02,0.13]);
assert.deepEqual(fixed.plan.pregraspM, [0.4,0.02,0.23]);
assert.deepEqual(fixed.plan.retreatM, [0.4,0.02,0.21]);
assert.deepEqual(fixed.plan.estimatedCenterM, [0.4,0.02,0.22]);
assert.equal(fixed.plan.graspHeightPolicy, 'fixed_base_z');
assert.equal(fixed.plan.fixedGraspBaseZM, 0.13);
assert.equal(buildSupervisedPlan({...highVisiblePoint, observed_at_ms:700},fixedSettings,now).reason,'target_stale');
assert.equal(buildSupervisedPlan({...highVisiblePoint, valid:false, reason:'target_lost'},fixedSettings,now).reason,'target_lost');
assert.equal(buildSupervisedPlan({...highVisiblePoint, supervised_base_candidate_valid:false},fixedSettings,now).reason,'base_candidate_invalid');
assert.equal(buildSupervisedPlan({...highVisiblePoint, base_xyz_m:[0.4,0.02,NaN]},fixedSettings,now).reason,'target_pose_invalid');
assert.equal(buildSupervisedPlan({...highVisiblePoint, base_xyz_m:[0.4,0.02,0.9]},fixedSettings,now).reason,'workspace_rejected');
assert.equal(buildSupervisedPlan(highVisiblePoint,{...fixedSettings,graspHeightBaseM:0.13},now).reason,'plan_settings_invalid');
assert.equal(buildSupervisedPlan(highVisiblePoint,{...fixedSettings,fixedGraspBaseZM:NaN},now).reason,'plan_settings_invalid');
assert.equal(buildSupervisedPlan(highVisiblePoint,{...fixedSettings,fixedGraspBaseZM:0.02},now).reason,'workspace_rejected');
for (const [patch,reason] of [
  [{valid:false, reason:'target_lost'},'target_lost'],
  [{target_id:2},'target_identity_changed'],
  [{observed_at_ms:700},'target_stale'],
  [{observed_at_ms:2100},'target_timestamp_invalid'],
  [{robot_state_ts:1700},'robot_state_stale'],
  [{base_xyz_m:[0.4,NaN,0.15]},'target_pose_invalid'],
  [{base_xyz_m:[0.67,0,0.15]},'workspace_rejected'],
  [{width_m:0.10},'grasp_width_invalid'],
  [{supervised_base_candidate_valid:false},'base_candidate_invalid'],
  [{robot_pose_blockers:['sdk_tool_pose_required']},'base_candidate_invalid'],
  [{handeye:{...observation.handeye,effective_matrix_semantics:'T_flange_camera'}},'coordinate_frame_invalid'],
  [{calibration_id:'wrong'},'calibration_invalid'],
  [{robot_state_ts:1850},'pose_does_not_cover_frame_capture'],
  [{frame_id:null},'frame_id_invalid'],
  [{candidate_offset_base_m_applied:[0.0475,0.01,0]},'unverified_base_offset'],
]) assert.equal(buildSupervisedPlan({...observation,...patch},settings,now).reason,reason);
assert.equal(buildSupervisedPlan(observation,{...settings,graspOffsetM:[0.0475,0.01,0]},now).reason,'unverified_base_offset');
assert.equal(buildSupervisedPlan(observation,null,now).reason,'plan_settings_invalid');
assert.throws(()=>motionDuration([0,0,0],[0,0,1],0.02), /duration/);
assert.ok(motionDuration([0.4,0,0.2],[0.4,0,0.28],0.02)>=8.75);
assert.equal(result.executionApproved, false);
assert.equal(verifyHold({startZ:0.15,currentZ:0.23,elapsedMs:3100,contact:true}).passed,false);
assert.equal(verifyHold({startZ:0.15,currentZ:0.23,elapsedMs:3100,contact:true}).telemetryCriteriaPassed,true);
assert.equal(verifyHold({startZ:0.15,currentZ:0.23,elapsedMs:3100,contact:true,visualConfirmed:true}).passed,true);
assert.equal(verifyHold({startZ:0.15,currentZ:0.18,elapsedMs:3100,contact:true}).passed,false);
assert.equal(verifyHold({startZ:0.15,currentZ:0.23,elapsedMs:2999,contact:true}).passed,false);
assert.equal(verifyHold({startZ:0.15,currentZ:0.23,elapsedMs:3100,contact:false}).passed,false);
console.log('PASS supervised plan validates timestamps, frame provenance, workspace and human-confirmed hold');
