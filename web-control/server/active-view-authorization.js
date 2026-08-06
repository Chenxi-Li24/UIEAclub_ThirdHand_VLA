'use strict';

const crypto = require('crypto');
const fs = require('fs');

const MAX_APPROVAL_DURATION_MS = 8 * 60 * 60 * 1000;
const MAX_PROPOSAL_AGE_MS = 200;
const MAX_APPROVAL_BYTES = 64 * 1024;
const HASH_PATTERN = /^sha256:[0-9a-f]{64}$/;
const HARD_MAX_SPEED_SCALE = 0.05;
const HARD_MAX_TRANSLATION_M = 0.020;
const HARD_MAX_ROTATION_RAD = 5 * Math.PI / 180;
const HARD_MAX_REFINEMENT_STEPS = 3;

function canonicalize(value, seen = new Set()) {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new TypeError('value must be finite JSON');
    return value;
  }
  if (Array.isArray(value)) return value.map(item => canonicalize(item, seen));
  if (typeof value !== 'object' || value === undefined) {
    throw new TypeError('value must be finite JSON');
  }
  if (seen.has(value)) throw new TypeError('value must be finite JSON');
  seen.add(value);
  const result = {};
  for (const key of Object.keys(value).sort()) {
    if (value[key] === undefined) throw new TypeError('value must be finite JSON');
    result[key] = canonicalize(value[key], seen);
  }
  seen.delete(value);
  return result;
}

function canonicalJson(value) {
  return JSON.stringify(canonicalize(value));
}

function approvalContentId(payload) {
  const copy = { ...payload };
  delete copy.content_id;
  return `sha256:${crypto.createHash('sha256').update(canonicalJson(copy), 'ascii').digest('hex')}`;
}

function loadActiveViewApproval(filePath) {
  if (typeof filePath !== 'string' || filePath.length === 0 || filePath.includes('://')) return null;
  const stat = fs.lstatSync(filePath);
  if (stat.isSymbolicLink() || !stat.isFile()) throw new TypeError('approval file must be a regular non-symlink file');
  if (stat.size > MAX_APPROVAL_BYTES) throw new TypeError('approval file exceeds 64 KiB');
  const approval = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  canonicalJson(approval);
  return approval;
}

function reject(reason) {
  return { approved: false, reason };
}

function exactKeys(value, keys) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

function isFiniteVector(value, length) {
  return Array.isArray(value) && value.length === length &&
    value.every(item => typeof item === 'number' && Number.isFinite(item));
}

function isEvidenceIds(value) {
  return Array.isArray(value) && value.length > 0 && value.length <= 32 &&
    new Set(value).size === value.length && value.every(item => HASH_PATTERN.test(item));
}

function arraysEqual(left, right) {
  return Array.isArray(left) && Array.isArray(right) && left.length === right.length &&
    left.every((value, index) => value === right[index]);
}

function degreesToRadians(value) {
  return value * Math.PI / 180;
}

function validatedLimits(limits) {
  if (!limits || typeof limits !== 'object') return null;
  const jointLimits = limits.jointLimitsDeg;
  if (!Array.isArray(jointLimits) || jointLimits.length !== 6 ||
      !jointLimits.every(pair => isFiniteVector(pair, 2) && pair[0] < pair[1])) return null;
  const numeric = [
    limits.maxSpeedScale,
    limits.maxTranslationM,
    limits.maxRotationRad,
  ];
  if (!numeric.every(value => typeof value === 'number' && Number.isFinite(value))) return null;
  if (!Number.isInteger(limits.maxRefinementSteps) || limits.maxRefinementSteps < 1) return null;
  if (limits.requireStepConfirmation !== true ||
      typeof limits.robotModelId !== 'string' || limits.robotModelId.length === 0) return null;
  return limits;
}

function approvalReason(approval, nowMs, evidenceIds, limits) {
  if (!approval || typeof approval !== 'object') return 'approval_missing';
  const approvalKeys = new Set([
    'schema_version', 'issued_at_ms', 'expires_at_ms', 'operator_acknowledged',
    'robot_model_id', 'evidence_ids', 'limits', 'content_id',
  ]);
  if (!exactKeys(approval, approvalKeys) || approval.schema_version !== 1) return 'approval_schema_invalid';
  try {
    if (approvalContentId(approval) !== approval.content_id) return 'approval_integrity_invalid';
  } catch {
    return 'approval_integrity_invalid';
  }
  if (!Number.isSafeInteger(approval.issued_at_ms) || !Number.isSafeInteger(approval.expires_at_ms) ||
      approval.expires_at_ms <= approval.issued_at_ms) return 'approval_time_invalid';
  if (approval.expires_at_ms - approval.issued_at_ms > MAX_APPROVAL_DURATION_MS) {
    return 'approval_duration_invalid';
  }
  if (!Number.isFinite(nowMs) || nowMs < approval.issued_at_ms) return 'approval_not_yet_valid';
  if (nowMs >= approval.expires_at_ms) return 'approval_expired';
  if (approval.operator_acknowledged !== true) return 'approval_not_acknowledged';
  if (approval.robot_model_id !== limits.robotModelId) return 'robot_model_mismatch';
  if (!isEvidenceIds(approval.evidence_ids) || !arraysEqual(approval.evidence_ids, evidenceIds)) {
    return 'approval_evidence_mismatch';
  }
  const expectedLimits = {
    max_speed_scale: limits.maxSpeedScale,
    max_translation_m: limits.maxTranslationM,
    max_rotation_rad: limits.maxRotationRad,
    max_refinement_steps: limits.maxRefinementSteps,
    require_step_confirmation: limits.requireStepConfirmation,
  };
  if (!exactKeys(approval.limits, new Set(Object.keys(expectedLimits))) ||
      canonicalJson(approval.limits) !== canonicalJson(expectedLimits)) return 'approval_limits_mismatch';
  return null;
}

function authorizeActiveViewMove({ requested, approval, proposal, robot, session, nowMs, limits }) {
  if (requested !== true) return reject('active_view_execution_disabled');
  const safeLimits = validatedLimits(limits);
  if (!safeLimits) return reject('authorization_limits_invalid');
  if (safeLimits.maxSpeedScale > HARD_MAX_SPEED_SCALE) return reject('speed_scale_exceeds_hard_limit');
  if (safeLimits.maxTranslationM > HARD_MAX_TRANSLATION_M) return reject('translation_limit_exceeds_hard_limit');
  if (safeLimits.maxRotationRad > HARD_MAX_ROTATION_RAD) return reject('rotation_limit_exceeds_hard_limit');
  if (safeLimits.maxRefinementSteps > HARD_MAX_REFINEMENT_STEPS) return reject('refinement_limit_exceeds_hard_limit');
  if (!proposal || proposal.trusted !== true || !session) return reject('trusted_proposal_missing');
  if (!isEvidenceIds(proposal.evidenceIds) || !arraysEqual(proposal.evidenceIds, session.evidenceIds)) {
    return reject('session_evidence_mismatch');
  }
  const approvalFailure = approvalReason(approval, nowMs, proposal.evidenceIds, safeLimits);
  if (approvalFailure) return reject(approvalFailure);
  if (session.sessionId !== proposal.sessionId) return reject('session_mismatch');
  if (session.identityId !== proposal.identityId) return reject('identity_mismatch');
  if (session.proposalId !== proposal.proposalId) return reject('proposal_mismatch');
  if (!Number.isFinite(nowMs) || !Number.isFinite(proposal.receivedAtMs) ||
      nowMs < proposal.receivedAtMs || nowMs - proposal.receivedAtMs > MAX_PROPOSAL_AGE_MS) {
    return reject('proposal_stale');
  }
  if (!Number.isFinite(proposal.expiresAtMs) || nowMs >= proposal.expiresAtMs) {
    return reject('proposal_expired');
  }
  if (!robot || robot.connected !== true) return reject('robot_not_connected');
  if (robot.moving === true) return reject('robot_motion_active');
  if (robot.stateFresh !== true) return reject('robot_state_stale');
  if (robot.graspActive === true) return reject('grasp_active');
  if (session.activeMotion === true) return reject('active_view_motion_active');
  if (safeLimits.requireStepConfirmation && session.operatorConfirmed !== true) {
    return reject('operator_confirmation_required');
  }

  if (proposal.kind === 'coarse') {
    if (!isFiniteVector(proposal.jointsDeg, 6)) return reject('joint_target_invalid');
    if (proposal.jointsDeg.every(value => Math.abs(value) < 0.05)) {
      return reject('all_zero_joint_target_forbidden');
    }
    for (let index = 0; index < 6; index += 1) {
      const [minimum, maximum] = safeLimits.jointLimitsDeg[index];
      if (proposal.jointsDeg[index] < minimum || proposal.jointsDeg[index] > maximum) {
        return reject('joint_target_out_of_bounds');
      }
    }
    return {
      approved: true,
      reason: 'authorized',
      command: {
        cmd: 'move_joint',
        joints_rad: proposal.jointsDeg.map(degreesToRadians),
        speed_scale: safeLimits.maxSpeedScale,
        source: 'active_view:coarse',
      },
    };
  }

  if (proposal.kind === 'refine_delta') {
    if (session.refinementSteps >= safeLimits.maxRefinementSteps) return reject('refinement_limit_reached');
    if (!isFiniteVector(proposal.deltaBaseM, 3) || !isFiniteVector(proposal.opticalAxisBase, 3) ||
        !isFiniteVector(proposal.rotationDeltaRad, 3)) return reject('refinement_delta_invalid');
    const translation = Math.hypot(...proposal.deltaBaseM);
    if (translation > safeLimits.maxTranslationM + 1e-12) {
      return reject('refinement_translation_exceeds_limit');
    }
    const opticalNorm = Math.hypot(...proposal.opticalAxisBase);
    if (Math.abs(opticalNorm - 1) > 1e-6) return reject('optical_axis_invalid');
    const axial = proposal.deltaBaseM.reduce(
      (sum, value, index) => sum + value * proposal.opticalAxisBase[index], 0
    );
    if (Math.abs(axial) > 1e-6) return reject('optical_axis_refinement_forbidden');
    if (Math.hypot(...proposal.rotationDeltaRad) > 1e-12) {
      return reject('refinement_rotation_forbidden');
    }
    return {
      approved: true,
      reason: 'authorized',
      command: {
        cmd: 'move_l_delta',
        delta_base_m: [...proposal.deltaBaseM],
        rotation_delta_rad: [...proposal.rotationDeltaRad],
        speed_scale: safeLimits.maxSpeedScale,
        source: 'active_view:refine',
      },
    };
  }
  return reject('proposal_kind_invalid');
}

module.exports = {
  HARD_MAX_REFINEMENT_STEPS,
  HARD_MAX_ROTATION_RAD,
  HARD_MAX_SPEED_SCALE,
  HARD_MAX_TRANSLATION_M,
  MAX_APPROVAL_DURATION_MS,
  MAX_PROPOSAL_AGE_MS,
  approvalContentId,
  authorizeActiveViewMove,
  canonicalJson,
  degreesToRadians,
  loadActiveViewApproval,
};
