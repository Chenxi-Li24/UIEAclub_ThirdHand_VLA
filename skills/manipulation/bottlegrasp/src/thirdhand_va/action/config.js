'use strict';

const fs = require('node:fs');
const crypto = require('node:crypto');
const path = require('node:path');
const YAML = require('yaml');

const ROOT_KEYS = [
  'schema', 'execution_enabled', 'robot', 'workflow_timeout_ms',
  'home_timeout_ms', 'workspace_m', 'status_file', 'motion', 'gripper',
  'grasp', 'place',
];
const ROBOT_KEYS = [
  'backend', 'python_executable', 'bridge_path', 'sdk_path', 'runtime_root',
  'source_manifest', 'safety_profile_id', 'safety_config_sha256',
  'runtime_manifest_id', 'can_interface', 'lock_file', 'ws_url',
  'joint_limits_deg', 'joint_max_speeds_deg_s', 'speed_scale',
  'home_tolerance_deg', 'joint_limit_stop_margin_deg', 'presets',
];
const MOTION_KEYS = [
  'pregrasp_offset_m', 'lift_height_m', 'safe_transit_z_m',
  'max_refine_step_m', 'linear_speed_m_s', 'grasp_euler_rad',
];
const GRIPPER_KEYS = [
  'physical_max_width_m', 'execution_max_width_m',
  'contact_min_width_m', 'contact_max_width_m', 'release_min_width_m',
];
const GRASP_KEYS = ['flange_offset_base_m', 'offset_validated'];
const PLACE_KEYS = [
  'strategy', 'validated', 'fixed_xy_m', 'euler_rad', 'grasp_z_range_m',
  'vertical_clearance_m', 'source_observation_path_validation_id', 'home_preset',
  'path_validation_file', 'path_validation_sha256',
];
const SHA256_ID = /^sha256:[0-9a-f]{64}$/;
const SHA256_HEX = /^[0-9a-f]{64}$/;

function isObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function assertExactKeys(value, expected, scope = '') {
  if (!isObject(value)) throw new TypeError(`${scope || 'config'} must be an object`);
  const allowed = new Set(expected);
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) {
      throw new TypeError(`unknown config key: ${scope}${key}`);
    }
  }
  for (const key of expected) {
    if (!Object.hasOwn(value, key)) throw new TypeError(`missing config key: ${scope}${key}`);
  }
}

function finitePositive(value, name, { allowZero = false } = {}) {
  if (!Number.isFinite(value) || (allowZero ? value < 0 : value <= 0)) {
    throw new TypeError(`${name} must be a finite ${allowZero ? 'non-negative' : 'positive'} number`);
  }
  return value;
}

function vector(value, name, { nullable = false } = {}) {
  if (nullable && value === null) return null;
  if (!Array.isArray(value) || value.length !== 3 || !value.every(Number.isFinite)) {
    throw new TypeError(`${name} must be a finite xyz vector`);
  }
  return [...value];
}

function vectorN(value, length, name) {
  if (!Array.isArray(value) || value.length !== length || !value.every(Number.isFinite)) {
    throw new TypeError(`${name} must contain ${length} finite numbers`);
  }
  return [...value];
}

function range(value, name) {
  if (!Array.isArray(value) || value.length !== 2 || !value.every(Number.isFinite) ||
      value[0] > value[1]) throw new TypeError(`${name} must be an ordered finite range`);
  return [...value];
}

function deepFreeze(value) {
  if (!value || typeof value !== 'object' || Object.isFrozen(value)) return value;
  for (const child of Object.values(value)) deepFreeze(child);
  return Object.freeze(value);
}

function contentId(bytes) {
  return `sha256:${crypto.createHash('sha256').update(bytes).digest('hex')}`;
}

function sameVector(left, right, length = 3) {
  return Array.isArray(left) && Array.isArray(right) && left.length === length &&
    right.length === length && left.every((value, index) =>
      Number.isFinite(value) && Number.isFinite(right[index]) &&
      Math.abs(value - right[index]) <= 1e-9
    );
}

function startupJointRanges(value, jointLimits) {
  if (!Array.isArray(value) || value.length !== 6) return null;
  const copied = [];
  for (let index = 0; index < value.length; index += 1) {
    const item = value[index];
    if (!Array.isArray(item) || item.length !== 2 || !item.every(Number.isFinite) ||
        item[0] > item[1] || item[0] < jointLimits[index][0] ||
        item[1] > jointLimits[index][1]) return null;
    copied.push([...item]);
  }
  return copied;
}

function loadPathValidation(configPath, place, grasp, motion, robot) {
  if (typeof place.path_validation_file !== 'string' ||
      place.path_validation_file.length === 0 ||
      !SHA256_ID.test(place.path_validation_sha256 || '')) {
    throw new TypeError('validated place requires content-addressed path validation');
  }
  const artifactPath = path.resolve(path.dirname(path.resolve(configPath)),
    place.path_validation_file);
  const bytes = fs.readFileSync(artifactPath);
  if (contentId(bytes) !== place.path_validation_sha256) {
    throw new TypeError('path validation hash mismatch');
  }
  let artifact;
  try { artifact = JSON.parse(bytes.toString('utf8')); } catch {
    throw new TypeError('path validation artifact is invalid JSON');
  }
  const startupRanges = startupJointRanges(
    artifact?.startup_joint_ranges_deg, robot.joint_limits_deg
  );
  if (!isObject(artifact) ||
      artifact.schema !== 'thirdhand-pick-place-path-validation-v2' ||
      artifact.physically_validated !== true ||
      artifact.approved_for_execution !== true ||
      !Array.isArray(artifact.fixed_xy_m) || artifact.fixed_xy_m.length !== 2 ||
      !artifact.fixed_xy_m.every((value, index) =>
        Number.isFinite(value) && Math.abs(value - place.fixed_xy_m[index]) <= 1e-9) ||
      !Array.isArray(artifact.grasp_z_range_m) ||
      artifact.grasp_z_range_m.length !== 2 ||
      !artifact.grasp_z_range_m.every((value, index) =>
        Number.isFinite(value) && Math.abs(value - place.grasp_z_range_m[index]) <= 1e-9) ||
      !Number.isFinite(artifact.vertical_clearance_m) ||
      Math.abs(artifact.vertical_clearance_m - place.vertical_clearance_m) > 1e-9 ||
      !Number.isFinite(artifact.lift_height_m) ||
      Math.abs(artifact.lift_height_m - motion.lift_height_m) > 1e-9 ||
      !Number.isFinite(artifact.safe_transit_z_m) ||
      Math.abs(artifact.safe_transit_z_m - motion.safe_transit_z_m) > 1e-9 ||
      !sameVector(artifact.flange_offset_base_m, grasp.flange_offset_base_m) ||
      !sameVector(artifact.euler_rad, motion.grasp_euler_rad) ||
      !sameVector(artifact.place_euler_rad, place.euler_rad) ||
      !Number.isFinite(artifact.linear_speed_m_s) ||
      Math.abs(artifact.linear_speed_m_s - motion.linear_speed_m_s) > 1e-9 ||
      artifact.home_preset !== place.home_preset ||
      !sameVector(
        artifact.home_joints_deg, robot.presets[place.home_preset], 6
      ) ||
      !Number.isFinite(artifact.home_tolerance_deg) ||
      Math.abs(artifact.home_tolerance_deg - robot.home_tolerance_deg) > 1e-9 ||
      artifact.startup_home_validated !== true ||
      startupRanges === null ||
      artifact.source_observation_path_validation_id !==
        place.source_observation_path_validation_id) {
    throw new TypeError('path validation artifact does not match executable path');
  }
  return Object.freeze({
    artifactPath, id: place.path_validation_sha256,
    startupJointRangesDeg: startupRanges,
  });
}

function loadActionConfig(filePath, { env = process.env } = {}) {
  const configBytes = fs.readFileSync(filePath);
  const raw = YAML.parse(configBytes.toString('utf8'));
  assertExactKeys(raw, ROOT_KEYS);
  if (raw.schema !== 'thirdhand-action-config-v2') {
    throw new TypeError('unsupported action config schema');
  }
  if (typeof raw.execution_enabled !== 'boolean') {
    throw new TypeError('execution_enabled must be boolean');
  }
  assertExactKeys(raw.robot, ROBOT_KEYS, 'robot.');
  if (!['startouch_process', 'websocket'].includes(raw.robot.backend)) {
    throw new TypeError('robot.backend is invalid');
  }
  for (const field of [
    'python_executable', 'bridge_path', 'sdk_path', 'runtime_root',
    'source_manifest', 'safety_profile_id', 'can_interface', 'lock_file', 'ws_url',
  ]) {
    if (typeof raw.robot[field] !== 'string' || !raw.robot[field]) {
      throw new TypeError(`robot.${field} must be non-empty`);
    }
  }
  if (!/^[A-Za-z0-9_.:-]+$/.test(raw.robot.can_interface)) {
    throw new TypeError('robot.can_interface is invalid');
  }
  if (raw.robot.safety_profile_id !== 'thirdhand-conservative-safety-v1' ||
      !SHA256_HEX.test(raw.robot.safety_config_sha256 || '') ||
      !SHA256_ID.test(raw.robot.runtime_manifest_id || '')) {
    throw new TypeError('robot Startouch safety identity is invalid');
  }
  let endpoint;
  try { endpoint = new URL(raw.robot.ws_url); } catch {
    throw new TypeError('robot.ws_url is invalid');
  }
  if (!['ws:', 'wss:'].includes(endpoint.protocol)) throw new TypeError('ws_url must use ws or wss');
  if (!Array.isArray(raw.robot.joint_limits_deg) ||
      raw.robot.joint_limits_deg.length !== 6) {
    throw new TypeError('robot.joint_limits_deg must contain six ranges');
  }
  const jointLimitsDeg = raw.robot.joint_limits_deg.map((value, index) =>
    range(value, `robot.joint_limits_deg[${index}]`));
  const jointMaxSpeedsDegS = vectorN(
    raw.robot.joint_max_speeds_deg_s, 6, 'robot.joint_max_speeds_deg_s'
  );
  if (jointMaxSpeedsDegS.some(value => value <= 0) ||
      !Number.isFinite(raw.robot.speed_scale) || raw.robot.speed_scale <= 0 ||
      raw.robot.speed_scale > 0.10) {
    throw new TypeError('robot speed limits are invalid');
  }
  if (!Number.isFinite(raw.robot.home_tolerance_deg) ||
      raw.robot.home_tolerance_deg <= 0 || raw.robot.home_tolerance_deg > 2.0) {
    throw new TypeError('robot.home_tolerance_deg must be within (0, 2.0]');
  }
  if (!Number.isFinite(raw.robot.joint_limit_stop_margin_deg) ||
      raw.robot.joint_limit_stop_margin_deg < 3.0 ||
      raw.robot.joint_limit_stop_margin_deg > 10.0) {
    throw new TypeError('robot.joint_limit_stop_margin_deg must be within [3, 10]');
  }
  if (!isObject(raw.robot.presets) || Object.keys(raw.robot.presets).length === 0) {
    throw new TypeError('robot.presets must be a non-empty object');
  }
  const presets = Object.fromEntries(Object.entries(raw.robot.presets).map(([name, pose]) => {
    if (!name) throw new TypeError('robot preset name is invalid');
    const joints = vectorN(pose, 6, `robot.presets.${name}`);
    if (joints.some((value, index) =>
      value < jointLimitsDeg[index][0] || value > jointLimitsDeg[index][1])) {
      throw new TypeError(`robot.presets.${name} exceeds joint limits`);
    }
    return [name, joints];
  }));
  const presetStopMarginViolations = [];
  for (const [name, joints] of Object.entries(presets)) {
    joints.forEach((value, index) => {
      const [lower, upper] = jointLimitsDeg[index];
      if (value - lower <= raw.robot.joint_limit_stop_margin_deg ||
          upper - value <= raw.robot.joint_limit_stop_margin_deg) {
        presetStopMarginViolations.push(`${name}:joint_${index + 1}`);
      }
    });
  }
  const configDirectory = path.dirname(path.resolve(filePath));
  const pythonExecutable = env.THIRDHAND_VA_PYTHON || raw.robot.python_executable;
  const sdkPath = env.STARTOUCH_SDK_PATH || raw.robot.sdk_path;
  const robot = {
    backend: raw.robot.backend,
    python_executable: pythonExecutable,
    bridge_path: path.resolve(configDirectory, raw.robot.bridge_path),
    sdk_path: path.resolve(configDirectory, sdkPath),
    runtime_root: path.resolve(configDirectory, raw.robot.runtime_root),
    source_manifest: path.resolve(configDirectory, raw.robot.source_manifest),
    safety_profile_id: raw.robot.safety_profile_id,
    safety_config_sha256: raw.robot.safety_config_sha256,
    runtime_manifest_id: raw.robot.runtime_manifest_id,
    can_interface: raw.robot.can_interface,
    lock_file: path.resolve(raw.robot.lock_file),
    ws_url: raw.robot.ws_url,
    joint_limits_deg: jointLimitsDeg,
    joint_max_speeds_deg_s: jointMaxSpeedsDegS,
    speed_scale: raw.robot.speed_scale,
    home_tolerance_deg: raw.robot.home_tolerance_deg,
    joint_limit_stop_margin_deg: raw.robot.joint_limit_stop_margin_deg,
    preset_stop_margin_violations: presetStopMarginViolations,
    presets,
  };
  for (const field of ['workflow_timeout_ms', 'home_timeout_ms']) {
    if (!Number.isSafeInteger(raw[field]) || raw[field] <= 0) {
      throw new TypeError(`${field} must be a positive integer`);
    }
  }
  if (typeof raw.status_file !== 'string' || raw.status_file.length === 0) {
    throw new TypeError('status_file must be non-empty');
  }

  assertExactKeys(raw.workspace_m, ['x', 'y', 'z'], 'workspace_m.');
  const workspace = {
    x: range(raw.workspace_m.x, 'workspace_m.x'),
    y: range(raw.workspace_m.y, 'workspace_m.y'),
    z: range(raw.workspace_m.z, 'workspace_m.z'),
  };
  assertExactKeys(raw.motion, MOTION_KEYS, 'motion.');
  const motionScalarKeys = MOTION_KEYS.filter(key => key !== 'grasp_euler_rad');
  const motion = Object.fromEntries(motionScalarKeys.map(key => [
    key, finitePositive(raw.motion[key], `motion.${key}`),
  ]));
  motion.grasp_euler_rad = vector(raw.motion.grasp_euler_rad, 'motion.grasp_euler_rad');
  if (motion.max_refine_step_m > 0.005) {
    throw new TypeError('motion.max_refine_step_m exceeds 0.005 m');
  }
  if (motion.linear_speed_m_s > 0.10) {
    throw new TypeError('motion.linear_speed_m_s exceeds 0.10 m/s');
  }
  if (motion.safe_transit_z_m < workspace.z[0] ||
      motion.safe_transit_z_m > workspace.z[1]) {
    throw new TypeError('motion.safe_transit_z_m is outside workspace');
  }

  assertExactKeys(raw.gripper, GRIPPER_KEYS, 'gripper.');
  const gripper = Object.fromEntries(GRIPPER_KEYS.map(key => [
    key,
    finitePositive(raw.gripper[key], `gripper.${key}`, {
      allowZero: key === 'contact_min_width_m',
    }),
  ]));
  if (gripper.physical_max_width_m > 0.080) {
    throw new TypeError('physical gripper width exceeds TypeFZ 80 mm');
  }
  if (gripper.execution_max_width_m > 0.072 ||
      gripper.execution_max_width_m > gripper.physical_max_width_m) {
    throw new TypeError('execution gripper width exceeds 72 mm safe limit');
  }
  if (gripper.contact_min_width_m > gripper.contact_max_width_m ||
      gripper.contact_max_width_m > gripper.execution_max_width_m) {
    throw new TypeError('gripper contact width range is invalid');
  }
  if (gripper.release_min_width_m <= gripper.contact_max_width_m ||
      gripper.release_min_width_m > gripper.physical_max_width_m) {
    throw new TypeError('gripper release proof width is invalid');
  }

  assertExactKeys(raw.grasp, GRASP_KEYS, 'grasp.');
  if (typeof raw.grasp.offset_validated !== 'boolean') {
    throw new TypeError('grasp.offset_validated must be boolean');
  }
  const grasp = {
    flange_offset_base_m: vector(
      raw.grasp.flange_offset_base_m, 'grasp.flange_offset_base_m'
    ),
    offset_validated: raw.grasp.offset_validated,
  };
  if (Math.hypot(...grasp.flange_offset_base_m) > 0.20) {
    throw new TypeError('grasp flange offset exceeds 0.20 m');
  }

  assertExactKeys(raw.place, PLACE_KEYS, 'place.');
  if (typeof raw.place.validated !== 'boolean') {
    throw new TypeError('place.validated must be boolean');
  }
  const place = {
    strategy: raw.place.strategy,
    validated: raw.place.validated,
    fixed_xy_m: vectorN(raw.place.fixed_xy_m, 2, 'place.fixed_xy_m'),
    euler_rad: vector(raw.place.euler_rad, 'place.euler_rad'),
    grasp_z_range_m: raw.place.grasp_z_range_m === null
      ? null : range(raw.place.grasp_z_range_m, 'place.grasp_z_range_m'),
    vertical_clearance_m: finitePositive(
      raw.place.vertical_clearance_m, 'place.vertical_clearance_m'
    ),
    source_observation_path_validation_id:
      raw.place.source_observation_path_validation_id,
    home_preset: raw.place.home_preset,
    path_validation_file: raw.place.path_validation_file,
    path_validation_sha256: raw.place.path_validation_sha256,
    path_validation_id: null,
    startup_home_validated: false,
    startup_joint_ranges_deg: null,
  };
  if (place.strategy !== 'fixed_xy_keep_grasp_z') {
    throw new TypeError('place.strategy is invalid');
  }
  if (!SHA256_ID.test(place.source_observation_path_validation_id || '')) {
    throw new TypeError('place source observation validation ID is invalid');
  }
  if (typeof place.home_preset !== 'string' || place.home_preset.length === 0) {
    throw new TypeError('place.home_preset must be non-empty');
  }
  if (!Object.hasOwn(robot.presets, place.home_preset)) {
    throw new TypeError('place.home_preset is not configured for the robot');
  }
  if (place.validated && place.grasp_z_range_m === null) {
    throw new TypeError('validated place requires grasp_z_range_m');
  }
  if (!place.validated &&
      !(place.grasp_z_range_m === null && place.path_validation_file === null &&
        place.path_validation_sha256 === null)) {
    throw new TypeError('inactive place cannot carry active path validation');
  }
  if (place.validated) {
    const pathValidation = loadPathValidation(filePath, place, grasp, motion, robot);
    place.path_validation_file = pathValidation.artifactPath;
    place.path_validation_id = pathValidation.id;
    place.startup_home_validated = true;
    place.startup_joint_ranges_deg = pathValidation.startupJointRangesDeg;
  }
  if (raw.execution_enabled && !grasp.offset_validated) {
    throw new TypeError('grasp_offset_not_validated');
  }
  if (raw.execution_enabled && !place.validated) throw new TypeError('place_not_validated');
  if (raw.execution_enabled && presetStopMarginViolations.length > 0) {
    throw new TypeError(
      `robot_preset_inside_joint_stop_margin:${presetStopMarginViolations[0]}`
    );
  }

  return deepFreeze({
    schema: raw.schema,
    content_id: contentId(configBytes),
    execution_enabled: raw.execution_enabled,
    robot,
    workflow_timeout_ms: raw.workflow_timeout_ms,
    home_timeout_ms: raw.home_timeout_ms,
    workspace_m: workspace,
    status_file: raw.status_file,
    motion,
    gripper,
    grasp,
    place,
  });
}

module.exports = { loadActionConfig };
