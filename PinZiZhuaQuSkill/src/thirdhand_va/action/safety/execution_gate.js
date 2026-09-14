'use strict';

const { checkWorkspace } = require('./workspace_check');

const SHA256_ID = /^sha256:[0-9a-f]{64}$/;

function stableId(value) {
  return Number.isSafeInteger(value) && value >= 1 && value <= 5;
}

function evaluateExecutionGate(context = {}) {
  const blockers = [];
  if (context.executionEnabled !== true) blockers.push('execution_disabled');
  if (context.visionReady !== true) blockers.push('vision_not_ready');
  if (!stableId(context.requestedStableId) || !stableId(context.targetStableId)) {
    blockers.push('target_id_invalid');
  } else if (context.requestedStableId !== context.targetStableId) {
    blockers.push('target_identity_conflict');
  }
  if (context.trackState !== 'confirmed') blockers.push('target_not_confirmed');
  if (typeof context.evidenceId !== 'string' || !SHA256_ID.test(context.evidenceId)) {
    blockers.push('evidence_invalid');
  }
  if (!Number.isFinite(context.evidenceAgeMs) || context.evidenceAgeMs < 0 ||
      !Number.isFinite(context.maxEvidenceAgeMs) || context.maxEvidenceAgeMs <= 0) {
    blockers.push('evidence_age_invalid');
  } else if (context.evidenceAgeMs > context.maxEvidenceAgeMs) {
    blockers.push('evidence_stale');
  }
  if (!Number.isSafeInteger(context.evidenceMotionEpoch) ||
      !Number.isSafeInteger(context.motionEpoch) || context.evidenceMotionEpoch < 0 ||
      context.motionEpoch < 0) {
    blockers.push('motion_epoch_invalid');
  } else if (context.evidenceMotionEpoch !== context.motionEpoch) {
    blockers.push('motion_epoch_mismatch');
  }
  if (context.depthValid !== true) blockers.push('depth_invalid');
  if (!Array.isArray(context.posePositionStdM) || context.posePositionStdM.length !== 3 ||
      !context.posePositionStdM.every(value => Number.isFinite(value) && value >= 0) ||
      !Number.isFinite(context.maxPositionStdM) || context.maxPositionStdM <= 0) {
    blockers.push('pose_spread_invalid');
  } else if (context.posePositionStdM.some(value => value > context.maxPositionStdM)) {
    blockers.push('pose_spread_exceeded');
  }
  if (context.calibrationValidated !== true) blockers.push('calibration_not_validated');
  if (context.armStationary !== true) blockers.push('arm_not_stationary');
  if (context.safetyApproved !== true) blockers.push('safety_not_approved');
  if (context.gripperReady !== true) blockers.push('gripper_not_ready');
  if (context.placeValidated !== true) blockers.push('place_not_validated');
  if (context.graspOffsetValidated !== true) blockers.push('grasp_offset_not_validated');
  if (!Number.isFinite(context.widthM) || context.widthM <= 0 ||
      !Number.isFinite(context.maxWidthM) || context.maxWidthM <= 0 ||
      context.maxWidthM > 0.072) {
    blockers.push('grasp_width_invalid');
  } else if (context.widthM > context.maxWidthM || context.widthM > 0.072) {
    blockers.push('grasp_width_exceeded');
  }
  blockers.push(...checkWorkspace(
    context.pregraspM, context.workspace, 'pregrasp_workspace'
  ).blockers);
  blockers.push(...checkWorkspace(
    context.commandedFlangeGraspM, context.workspace, 'commanded_grasp_workspace'
  ).blockers);
  blockers.push(...checkWorkspace(
    context.liftM, context.workspace, 'lift_workspace'
  ).blockers);
  blockers.push(...checkWorkspace(
    context.prePlaceM, context.workspace, 'pre_place_workspace'
  ).blockers);
  blockers.push(...checkWorkspace(
    context.placeM, context.workspace, 'place_workspace'
  ).blockers);
  blockers.push(...checkWorkspace(
    context.retreatM, context.workspace, 'retreat_workspace'
  ).blockers);
  const allowed = blockers.length === 0;
  return Object.freeze({
    schema: 'thirdhand-action-decision-v1',
    phase: allowed ? 'approved' : 'blocked',
    allowed,
    robot_control_enabled: allowed,
    blockers: Object.freeze(blockers),
  });
}

module.exports = { evaluateExecutionGate };
