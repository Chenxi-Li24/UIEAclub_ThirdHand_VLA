'use strict';

const { createHash } = require('node:crypto');

function vector3(value) {
  return Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
}

function createSupervisedPreview({ target, robotState, runtimeEvidence, config, nowMs, buildPlan = null }) {
  if (!Number.isFinite(nowMs) || nowMs < 0) throw new TypeError('preview_time_invalid');
  const source = target?.graspPreview ?? target?.grasp_preview ?? null;
  const blockers = new Set(Array.isArray(source?.blockers) ? source.blockers : []);
  const gripTarget = source?.grip_target_xyz_m ?? null;
  if (!Number.isSafeInteger(target?.stableId) || target.stableId < 1 || target.stableId > 5) {
    blockers.add('target_id_invalid');
  }
  if (target?.trackState !== 'confirmed') blockers.add('target_not_confirmed');
  if (target?.depthValid !== true) blockers.add('depth_invalid');
  const liftOnly = config?.workflow_mode === 'lift_only';
  if (!liftOnly && !vector3(gripTarget)) blockers.add('grip_target_unavailable');
  if (liftOnly && !vector3(target?.baseXyzM)) blockers.add('base_coordinates_unavailable');
  if (config?.execution_enabled !== true) blockers.add('execution_disabled');
  const gripTransform = config?.grasp?.grip_transform;
  if (!robotState || robotState.poseFrame !== 'robot_flange' ||
      robotState.connected !== true || robotState.healthy !== true ||
      robotState.stateFresh !== true || (!liftOnly && robotState.stationary !== true) ||
      !Number.isSafeInteger(robotState.stateSequence)) {
    blockers.add('robot_state_unverified');
  }
  if (typeof buildPlan !== 'function') blockers.add('supervised_plan_unavailable');
  else if (!liftOnly && !target?.actionEvidence) {
    blockers.add('alignment_handoff_evidence_unavailable');
  }
  const evidence = Object.freeze({
    targetId: target?.stableId ?? null,
    frameId: target?.frameId ?? null,
    visionEvidenceId: target?.evidenceId ?? null,
    motionEpoch: target?.motionEpoch ?? null,
    robotStateSequence: robotState?.stateSequence ?? null,
    visionConfigId: runtimeEvidence?.vision_config_id ?? null,
    calibrationId: runtimeEvidence?.calibration_id ?? null,
    gripValidationId: gripTransform?.validation_id ?? null,
  });
  let plan = null;
  if (blockers.size === 0) {
    try {
      plan = buildPlan(target, config);
      if (!plan || plan.schema !== 'thirdhand-execution-plan-v2') {
        plan = null;
        blockers.add('supervised_plan_invalid');
      }
    } catch (error) {
      blockers.add(error?.message || 'supervised_plan_invalid');
    }
  }
  const coordinates = Object.freeze({
    camera_xyz_m: vector3(source?.camera_xyz_m) ? Object.freeze([...source.camera_xyz_m]) : null,
    surface_xyz_m: vector3(source?.surface_xyz_m) ? Object.freeze([...source.surface_xyz_m]) : null,
    grip_target_xyz_m: vector3(gripTarget) ? Object.freeze([...gripTarget]) : null,
  });
  const expiresAtMs = nowMs + 300;
  const previewId = `sha256:${createHash('sha256').update(JSON.stringify({ evidence, coordinates, expiresAtMs })).digest('hex')}`;
  return Object.freeze({
    previewId, targetId: evidence.targetId, createdAtMs: nowMs, expiresAtMs,
    coordinates, evidence, blockers: Object.freeze([...blockers]),
    executable: blockers.size === 0, plan,
  });
}

function matchesPreview(preview, currentEvidence, nowMs) {
  if (!preview || !currentEvidence || !Number.isFinite(nowMs) ||
      nowMs < preview.createdAtMs || nowMs > preview.expiresAtMs) return false;
  return Object.keys(preview.evidence).every(key =>
    currentEvidence[key] === preview.evidence[key]
  );
}

module.exports = { createSupervisedPreview, matchesPreview };
