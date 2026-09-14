#!/usr/bin/env node
'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline/promises');
const { randomUUID } = require('node:crypto');
const YAML = require('yaml');

const { loadActionConfig } = require('../../src/thirdhand_va/action/config');
const { validateActionEvidence } = require(
  '../../src/thirdhand_va/action/evidence/action_evidence'
);

const LIVE_ROBOT_ACK = 'I_ACCEPT_SUPERVISED_ROBOT_MOTION';
const SHA256 = /^sha256:[0-9a-f]{64}$/;
const USAGE = [
  'usage: validate_pick_place.js --allow-robot --calibration FILE [options]',
  '  --trials 1..100       supervised trials (default: 30)',
  '  --target-id 1..5      requested Stable ID (default: 1)',
  '  --config FILE         activated Action config',
  '  --specimens FILE      pre-registered 5+ physical bottle specimen manifest',
  '  --base-url URL        loopback VA service on 127.0.0.1',
].join('\n');

function parseArgs(argv) {
  const result = {
    allowRobot: false,
    help: false,
    trials: 30,
    targetId: 1,
    config: 'configs/action.yaml',
    calibration: null,
    specimens: null,
    visionConfig: 'configs/vision.yaml',
    baseUrl: 'http://127.0.0.1:8766',
    outputRoot: 'artifacts/validation/generic-bottle',
    pollMs: 500,
    timeoutMs: 300000,
  };
  const values = new Map([
    ['--trials', 'trials'], ['--target-id', 'targetId'],
    ['--config', 'config'], ['--calibration', 'calibration'],
    ['--specimens', 'specimens'],
    ['--vision-config', 'visionConfig'],
    ['--base-url', 'baseUrl'], ['--output-root', 'outputRoot'],
    ['--poll-ms', 'pollMs'], ['--timeout-ms', 'timeoutMs'],
  ]);
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === '--allow-robot') result.allowRobot = true;
    else if (arg === '--help') result.help = true;
    else if (values.has(arg)) {
      const value = argv[++index];
      if (!value) throw new TypeError(`missing value for ${arg}`);
      result[values.get(arg)] = value;
    } else throw new TypeError(`unknown argument: ${arg}`);
  }
  for (const key of ['trials', 'targetId', 'pollMs', 'timeoutMs']) {
    result[key] = Number(result[key]);
  }
  if (!Number.isSafeInteger(result.trials) || result.trials < 1 || result.trials > 100) {
    throw new TypeError('--trials must be an integer within [1, 100]');
  }
  if (!Number.isSafeInteger(result.targetId) || result.targetId < 1 ||
      result.targetId > 5) throw new TypeError('--target-id must be within [1, 5]');
  if (!Number.isSafeInteger(result.pollMs) || result.pollMs < 50 ||
      !Number.isSafeInteger(result.timeoutMs) || result.timeoutMs < 1000) {
    throw new TypeError('poll and timeout values are invalid');
  }
  let endpoint;
  try { endpoint = new URL(result.baseUrl); } catch {
    throw new TypeError('--base-url is invalid');
  }
  if (endpoint.protocol !== 'http:' || endpoint.hostname !== '127.0.0.1' ||
      endpoint.username || endpoint.password) {
    throw new TypeError('--base-url must be loopback HTTP on 127.0.0.1');
  }
  result.baseUrl = endpoint.href.replace(/\/$/, '');
  return Object.freeze(result);
}

function hashFile(filePath) {
  return `sha256:${crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex')}`;
}

function loadSpecimenManifest(filePath) {
  const bytes = fs.readFileSync(filePath);
  const payload = JSON.parse(bytes.toString('utf8'));
  if (!payload || typeof payload !== 'object' || Array.isArray(payload) ||
      payload.schema !== 'thirdhand-va-bottle-specimens-v1' ||
      !Array.isArray(payload.specimens) || payload.specimens.length < 5 ||
      payload.specimens.length > 100) {
    throw new TypeError('specimen manifest requires 5..100 registered bottles');
  }
  const ids = [];
  for (const specimen of payload.specimens) {
    if (!specimen || typeof specimen !== 'object' || Array.isArray(specimen) ||
        Object.keys(specimen).sort().join(',') !== 'description,specimen_id' ||
        typeof specimen.specimen_id !== 'string' ||
        !/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(specimen.specimen_id) ||
        typeof specimen.description !== 'string' ||
        specimen.description.trim().length === 0 || specimen.description.length > 200) {
      throw new TypeError('specimen manifest entry is invalid');
    }
    ids.push(specimen.specimen_id);
  }
  if (new Set(ids.map(value => value.toLowerCase())).size !== ids.length) {
    throw new TypeError('specimen IDs must be case-insensitively unique');
  }
  return Object.freeze({
    content_id: contentId(bytes),
    specimens: Object.freeze([...ids]),
  });
}

function contentId(bytes) {
  return `sha256:${crypto.createHash('sha256').update(bytes).digest('hex')}`;
}

function rigidTransform(value) {
  if (!Array.isArray(value) || value.length !== 4 ||
      value.some(row => !Array.isArray(row) || row.length !== 4 ||
        !row.every(Number.isFinite)) ||
      value[3].some((item, index) => Math.abs(item - [0, 0, 0, 1][index]) > 1e-9)) {
    return false;
  }
  const rotation = value.slice(0, 3).map(row => row.slice(0, 3));
  for (let left = 0; left < 3; left += 1) {
    for (let right = 0; right < 3; right += 1) {
      const dot = rotation.reduce(
        (sum, row) => sum + row[left] * row[right], 0
      );
      if (Math.abs(dot - (left === right ? 1 : 0)) > 1e-7) return false;
    }
  }
  const [a, b, c] = rotation;
  const determinant = a[0] * (b[1] * c[2] - b[2] * c[1]) -
    a[1] * (b[0] * c[2] - b[2] * c[0]) +
    a[2] * (b[0] * c[1] - b[1] * c[0]);
  return Math.abs(determinant - 1) <= 1e-7;
}

function loadCalibration(filePath, expected = {}) {
  const payload = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  const physical = payload.physical_validation;
  const measured = physical?.measured_error_m;
  const limit = physical?.required_3d_point_or_grasp_error_m_max;
  const camera = payload.camera;
  const identityValid = payload.schema === 'thirdhand-handeye-calibration-v3' &&
    payload.robot_state_semantics === 'T_base_flange' &&
    payload.extrinsic_semantics === 'T_flange_camera' &&
    rigidTransform(payload.T_flange_camera?.matrix_4x4) &&
    typeof camera?.camera_serial === 'string' && camera.camera_serial &&
    typeof camera?.registration_id === 'string' && camera.registration_id &&
    typeof camera?.camera_mount_id === 'string' && camera.camera_mount_id &&
    (!expected.camera_serial || camera.camera_serial === expected.camera_serial) &&
    (!expected.registration_id || camera.registration_id === expected.registration_id) &&
    (!expected.camera_mount_id || camera.camera_mount_id === expected.camera_mount_id) &&
    payload.camera_mount_id_activation === true &&
    payload.activated_camera_mount_id === camera.camera_mount_id;
  const valid = Boolean(identityValid && payload.numerically_validated === true &&
    payload.camera_mount_id_activation === true &&
    payload.approved_for_bottle_grasp === true &&
    physical?.status === 'passed' && Number.isFinite(measured) && measured >= 0 &&
    Number.isFinite(limit) && limit > 0 && limit <= 0.010 &&
    measured <= limit && measured <= 0.010);
  return Object.freeze({
    numerically_validated: payload.numerically_validated === true,
    physically_validated: valid,
    approved_for_bottle_grasp: valid,
    camera_serial: camera?.camera_serial ?? null,
    registration_id: camera?.registration_id ?? null,
    camera_mount_id: camera?.camera_mount_id ?? null,
    calibration_id: hashFile(filePath),
  });
}

function loadVisionEvidence(configPath) {
  const raw = YAML.parse(fs.readFileSync(configPath, 'utf8'));
  if (!raw || typeof raw !== 'object' || Array.isArray(raw) ||
      typeof raw.hf_home !== 'string' || !raw.hf_home) {
    throw new TypeError('vision model cache is not configured');
  }
  for (const field of ['camera_serial', 'camera_registration_id', 'camera_mount_id']) {
    if (typeof raw[field] !== 'string' || !raw[field]) {
      throw new TypeError(`${field} is invalid`);
    }
  }
  const cacheHome = path.resolve(raw.hf_home);
  const models = [];
  for (const [field, revisionField, hashField] of [
    ['grounding_model', 'grounding_revision', 'grounding_weights_sha256'],
    ['sam_model', 'sam_revision', 'sam_weights_sha256'],
  ]) {
    const modelId = raw[field];
    if (typeof modelId !== 'string' || !modelId.includes('/')) {
      throw new TypeError(`${field} is invalid`);
    }
    const repository = path.join(
      cacheHome, 'hub', `models--${modelId.replaceAll('/', '--')}`
    );
    const revision = raw[revisionField];
    if (!/^[0-9a-f]{40}$/.test(revision)) {
      throw new TypeError(`${field} revision is invalid`);
    }
    const snapshot = path.join(repository, 'snapshots', revision);
    const weightName = [
      'model.safetensors', 'pytorch_model.bin', 'sam2.1_hiera_tiny.pt',
    ].find(name => fs.existsSync(path.join(snapshot, name)));
    if (!weightName) throw new TypeError(`${field} weights are missing`);
    const realWeight = fs.realpathSync(path.join(snapshot, weightName));
    const weightsSha256 = hashFile(realWeight);
    if (weightsSha256 !== raw[hashField]) {
      throw new TypeError(`${field} pinned weight hash mismatch`);
    }
    models.push(Object.freeze({
      model_id: modelId,
      revision,
      weights_sha256: weightsSha256,
    }));
  }
  return Object.freeze({
    vision_config_id: hashFile(configPath),
    camera_serial: raw.camera_serial,
    registration_id: raw.camera_registration_id,
    camera_mount_id: raw.camera_mount_id,
    models: Object.freeze(models),
  });
}

function writeReport(filePath, report) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const temporary = `${filePath}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(report, null, 2)}\n`);
  fs.renameSync(temporary, filePath);
}

async function promptYes(message) {
  const terminal = readline.createInterface({ input: process.stdin, output: process.stdout });
  try {
    return (await terminal.question(`${message} [y/N] `)).trim().toLowerCase() === 'y';
  } finally {
    terminal.close();
  }
}

async function promptText(message) {
  const terminal = readline.createInterface({ input: process.stdin, output: process.stdout });
  try {
    return (await terminal.question(`${message}: `)).trim();
  } finally {
    terminal.close();
  }
}

async function defaultBeforeTrial({ index, total, targetId, specimenIds }) {
  const specimenId = await promptText(
    `Trial ${index}/${total}: 输入预登记实体瓶 ID（可选：${specimenIds.join(', ')}）`
  );
  const positionLabel = await promptText(
    '输入本次随机桌面位置标签（每次必须唯一，例如 grid-C4）'
  );
  const approved = await promptYes(
    `Trial ${index}/${total}: 将编号 ${targetId} 的直立不透明瓶放在允许桌面随机位置，` +
    '确认人员/障碍已清空后继续'
  );
  return { approved, specimenId, positionLabel };
}

async function defaultConfirmTrial() {
  const upright = await promptYes('瓶子是否完整抓取、在固定点直立放下并回 Home？');
  const wrongPick = await promptYes('是否抓错编号？');
  const idSwitch = await promptYes('过程中是否发生身份切换？');
  return { upright, wrongPick, idSwitch };
}

function validTrialSetup(value, allowedSpecimens) {
  return value && typeof value === 'object' && !Array.isArray(value) &&
    value.approved === true && typeof value.specimenId === 'string' &&
    allowedSpecimens.has(value.specimenId) &&
    typeof value.positionLabel === 'string' &&
    value.positionLabel.trim().length > 0 && value.positionLabel.trim().length <= 100;
}

function evaluateCoverage(trials, requestedTrials, minPositionSeparationM = 0.03) {
  if (!Array.isArray(trials) || !Number.isSafeInteger(requestedTrials) ||
      requestedTrials < 1 || !Number.isFinite(minPositionSeparationM) ||
      minPositionSeparationM <= 0) throw new TypeError('coverage inputs are invalid');
  const specimens = new Set();
  const positionLabels = new Set();
  const measuredPositions = [];
  for (const trial of trials) {
    if (typeof trial?.specimen_id === 'string' && trial.specimen_id) {
      specimens.add(trial.specimen_id);
    }
    if (typeof trial?.position_label === 'string' && trial.position_label) {
      positionLabels.add(trial.position_label);
    }
    const point = trial?.measured_grasp_point_m;
    if (trial?.evidence_authorized === true && Array.isArray(point) && point.length === 3 &&
        point.every(Number.isFinite) && measuredPositions.every(existing =>
          Math.hypot(point[0] - existing[0], point[1] - existing[1]) >=
            minPositionSeparationM
        )) {
      measuredPositions.push([...point]);
    }
  }
  const requiredSpecimens = Math.min(5, requestedTrials);
  const requiredPositionLabels = requestedTrials;
  const requiredMeasuredPositions = Math.ceil(requestedTrials * 0.90);
  const result = {
    specimen_count: specimens.size,
    position_label_count: positionLabels.size,
    measured_position_count: measuredPositions.length,
    required_specimen_count: requiredSpecimens,
    required_position_label_count: requiredPositionLabels,
    required_measured_position_count: requiredMeasuredPositions,
    measured_position_separation_m: minPositionSeparationM,
  };
  return Object.freeze({
    ...result,
    passed: result.specimen_count >= requiredSpecimens &&
      result.position_label_count >= requiredPositionLabels &&
      result.measured_position_count >= requiredMeasuredPositions,
  });
}

async function jsonRequest(fetchImpl, url, options = {}, requestTimeoutMs = 5000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), requestTimeoutMs);
  timeout.unref?.();
  let response;
  try {
    response = await fetchImpl(url, { ...options, signal: controller.signal });
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error(`request_timeout:${new URL(url).pathname}`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
  let payload;
  try { payload = await response.json(); } catch {
    throw new Error(`non_json_response:${new URL(url).pathname}`);
  }
  if (response.status < 200 || response.status >= 300) {
    throw new Error(payload?.reason || `http_${response.status}`);
  }
  return payload;
}

function trialEvidenceValid(result, expected) {
  if (!result || !validateActionEvidence(result.actionEvidence, result.evidenceId)) {
    return false;
  }
  const payload = result.actionEvidence.payload;
  const expectedModels = expected.visionEvidence.models;
  const provenance = payload.model_provenance;
  return payload.request_id === expected.requestId &&
    payload.stable_id === expected.targetId &&
    payload.calibration_id === expected.calibrationId &&
    payload.vision_config_id === expected.visionConfigId &&
    payload.action_config_id === expected.actionConfigId &&
    payload.path_validation_id === expected.pathValidationId &&
    provenance?.grounding_model === expectedModels[0]?.model_id &&
    provenance?.grounding_revision === expectedModels[0]?.revision &&
    provenance?.grounding_weights_sha256 === expectedModels[0]?.weights_sha256 &&
    provenance?.sam_model === expectedModels[1]?.model_id &&
    provenance?.sam_revision === expectedModels[1]?.revision &&
    provenance?.sam_weights_sha256 === expectedModels[1]?.weights_sha256;
}

async function stopAndConfirm({
  fetchImpl, baseUrl, requestId, timeoutMs, pollMs, clockMs, delay,
}) {
  const stopRequestId = `validator-stop:${requestId}`;
  try {
    await jsonRequest(fetchImpl, `${baseUrl}/api/va/stop`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        schema: 'thirdhand.va.command.v1', cmd: 'stop', request_id: stopRequestId,
      }),
    });
  } catch (error) {
    return Object.freeze({
      requested: false, confirmed: false, stopRequestId, reason: error.message,
    });
  }
  const deadline = clockMs() + timeoutMs;
  do {
    try {
      const status = await jsonRequest(fetchImpl, `${baseUrl}/api/va/status`);
      const health = await jsonRequest(fetchImpl, `${baseUrl}/health`);
      if (status.active === false && health.robot_control_enabled === true) {
        return Object.freeze({
          requested: true, confirmed: true, stopRequestId, reason: null,
        });
      }
    } catch (error) {
      return Object.freeze({
        requested: true, confirmed: false, stopRequestId, reason: error.message,
      });
    }
    if (clockMs() >= deadline) break;
    await delay(pollMs);
  } while (clockMs() < deadline);
  return Object.freeze({
    requested: true, confirmed: false, stopRequestId, reason: 'stop_confirmation_timeout',
  });
}

async function main(argv = process.argv.slice(2), dependencies = {}) {
  const env = dependencies.env || process.env;
  const write = dependencies.write || (line => console.log(line));
  const writeError = dependencies.writeError || (line => console.error(line));
  let args;
  try { args = parseArgs(argv); } catch (error) {
    writeError(error.message);
    return 2;
  }
  if (args.help) {
    write(USAGE);
    return 0;
  }
  const authReasons = [];
  if (!args.allowRobot) authReasons.push('allow_robot_flag_missing');
  if (env.THIRDHAND_LIVE_TEST !== '1') authReasons.push('live_test_env_missing');
  if (env.THIRDHAND_ALLOW_ROBOT !== LIVE_ROBOT_ACK) {
    authReasons.push('live_robot_ack_missing');
  }
  if (authReasons.length) {
    write(JSON.stringify({
      status: 'blocked', reasons: authReasons, robot_control_enabled: false,
    }));
    return 2;
  }
  if (!args.calibration) {
    writeError('--calibration is required for live validation');
    return 2;
  }
  if (!args.specimens) {
    writeError('--specimens is required for live validation');
    return 2;
  }

  const actionLoader = dependencies.loadActionConfig || loadActionConfig;
  const calibrationLoader = dependencies.loadCalibration || loadCalibration;
  const visionEvidenceLoader = dependencies.loadVisionEvidence || loadVisionEvidence;
  const specimenLoader = dependencies.loadSpecimenManifest || loadSpecimenManifest;
  const fileHasher = dependencies.hashFile || hashFile;
  const fetchImpl = dependencies.fetchImpl || globalThis.fetch;
  const reportWriter = dependencies.writeReport || writeReport;
  const beforeTrial = dependencies.beforeTrial || defaultBeforeTrial;
  const confirmTrial = dependencies.confirmTrial || defaultConfirmTrial;
  const delay = dependencies.delay || (ms => new Promise(resolve => setTimeout(resolve, ms)));
  const idFactory = dependencies.idFactory || randomUUID;
  const now = dependencies.now || (() => new Date());
  const clockMs = dependencies.clockMs || Date.now;
  let config;
  let calibration;
  let visionEvidence;
  let specimenManifest;
  try {
    config = actionLoader(args.config);
    visionEvidence = visionEvidenceLoader(args.visionConfig);
    calibration = calibrationLoader(args.calibration, visionEvidence);
    specimenManifest = specimenLoader(args.specimens);
  } catch (error) {
    writeError(`validation input invalid: ${error.message}`);
    return 2;
  }
  const blockers = [];
  if (config.execution_enabled !== true) blockers.push('execution_disabled');
  if (config.grasp?.offset_validated !== true) blockers.push('grasp_offset_not_validated');
  if (config.place?.validated !== true) blockers.push('place_not_validated');
  if (calibration.numerically_validated !== true) blockers.push('calibration_numerical_missing');
  if (calibration.physically_validated !== true) blockers.push('calibration_physical_missing');
  if (calibration.approved_for_bottle_grasp !== true) blockers.push('calibration_not_approved');
  if (!SHA256.test(calibration.calibration_id)) blockers.push('calibration_id_invalid');
  const actionConfigId = fileHasher(args.config);
  const visionConfigId = fileHasher(args.visionConfig);
  const calibrationFileId = fileHasher(args.calibration);
  if (config.content_id && config.content_id !== actionConfigId) {
    blockers.push('action_config_id_mismatch');
  }
  if (!SHA256.test(config.place?.path_validation_id || '')) {
    blockers.push('path_validation_id_invalid');
  }
  if (visionEvidence.vision_config_id !== visionConfigId) {
    blockers.push('vision_config_id_mismatch');
  }
  if (calibration.calibration_id !== calibrationFileId) {
    blockers.push('calibration_file_id_mismatch');
  }
  if (blockers.length) {
    write(JSON.stringify({ status: 'blocked', reasons: blockers, robot_control_enabled: false }));
    return 2;
  }
  if (!Array.isArray(visionEvidence.models) || !visionEvidence.models.length ||
      visionEvidence.models.some(model => !SHA256.test(model.weights_sha256))) {
    writeError('vision model evidence is incomplete');
    return 2;
  }
  if (typeof fetchImpl !== 'function') {
    writeError('fetch implementation is unavailable');
    return 2;
  }

  let health;
  try { health = await jsonRequest(fetchImpl, `${args.baseUrl}/health`); } catch (error) {
    writeError(`VA service unavailable: ${error.message}`);
    return 2;
  }
  if (health.camera_ready !== true || health.robot_control_enabled !== true) {
    write(JSON.stringify({
      status: 'blocked', reasons: [
        ...(health.camera_ready === true ? [] : ['camera_not_ready']),
        ...(health.robot_control_enabled === true ? [] : ['robot_control_not_ready']),
      ], robot_control_enabled: false,
    }));
    return 2;
  }
  const artifacts = health.artifacts;
  const healthModels = artifacts?.model_provenance;
  const artifactsMatch = artifacts?.action_config_id === actionConfigId &&
    artifacts.path_validation_id === config.place.path_validation_id &&
    artifacts.calibration_id === calibration.calibration_id &&
    artifacts.vision_config_id === visionConfigId &&
    artifacts.camera_serial === visionEvidence.camera_serial &&
    artifacts.registration_id === visionEvidence.registration_id &&
    artifacts.camera_mount_id === visionEvidence.camera_mount_id;
  const modelHashesMatch = visionEvidence.models.every((model, index) => {
    const prefix = index === 0 ? 'grounding' : 'sam';
    return healthModels?.vision_config_id === visionConfigId &&
      healthModels?.[`${prefix}_model`] === model.model_id &&
      healthModels?.[`${prefix}_revision`] === model.revision &&
      healthModels?.[`${prefix}_weights_sha256`] === model.weights_sha256;
  });
  if (!artifactsMatch || !modelHashesMatch) {
    write(JSON.stringify({
      status: 'blocked', reasons: ['runtime_artifact_mismatch'],
      robot_control_enabled: false,
    }));
    return 2;
  }

  const startedAt = now();
  const runId = startedAt.toISOString().replace(/[:.]/g, '-');
  const reportPath = path.join(args.outputRoot, runId, 'report.json');
  const report = {
    schema: 'thirdhand-va-generic-bottle-validation-v1',
    run_id: runId,
    started_at: startedAt.toISOString(),
    finished_at: null,
    hardware_validation: 'supervised',
    robot_control_enabled: true,
    environment: {
      hostname: os.hostname(), platform: process.platform,
      node: process.version, camera_serial: calibration.camera_serial,
    },
    evidence: {
      action_config_sha256: actionConfigId,
      vision_config_sha256: visionConfigId,
      calibration_sha256: calibrationFileId,
      calibration_id: calibration.calibration_id,
      models: visionEvidence.models.map(model => ({ ...model })),
      placement_strategy: config.place.strategy,
      fixed_xy_m: [...config.place.fixed_xy_m],
      grasp_z_range_m: [...config.place.grasp_z_range_m],
      vertical_clearance_m: config.place.vertical_clearance_m,
      flange_offset_base_m: [...config.grasp.flange_offset_base_m],
      path_validation_id: config.place.path_validation_id,
      specimen_manifest_sha256: specimenManifest.content_id,
    },
    requested_trials: args.trials,
    trials: [],
    acceptance: null,
    passed: false,
  };
  const usedPositionLabels = new Set();
  const allowedSpecimens = new Set(specimenManifest.specimens);

  for (let index = 1; index <= args.trials; index += 1) {
    const setup = await beforeTrial({
      index, total: args.trials, targetId: args.targetId,
      specimenIds: specimenManifest.specimens,
    });
    if (setup?.approved === false) {
      report.trials.push({ index, target_id: args.targetId, status: 'operator_cancelled' });
      break;
    }
    if (!validTrialSetup(setup, allowedSpecimens)) {
      report.trials.push({ index, target_id: args.targetId, status: 'setup_evidence_invalid' });
      break;
    }
    const specimenId = setup.specimenId;
    const positionLabel = setup.positionLabel.trim();
    if (usedPositionLabels.has(positionLabel)) {
      report.trials.push({
        index, target_id: args.targetId, status: 'position_label_reused',
        specimen_id: specimenId, position_label: positionLabel,
      });
      break;
    }
    usedPositionLabels.add(positionLabel);
    const requestId = idFactory();
    const trial = {
      index, target_id: args.targetId, request_id: requestId,
      specimen_id: specimenId, position_label: positionLabel,
      started_at: now().toISOString(), result: null, operator_confirmation: null,
      evidence_authorized: false, measured_grasp_point_m: null,
      stop_confirmation: null,
    };
    let startAccepted = false;
    let abortRun = false;
    try {
      const startResponse = await jsonRequest(fetchImpl, `${args.baseUrl}/api/va/start`, {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          schema: 'thirdhand.va.command.v1', cmd: 'start',
          target_id: args.targetId, request_id: requestId,
        }),
      });
      startAccepted = true;
      if (startResponse.accepted !== true ||
          startResponse.request_id !== requestId ||
          startResponse.target_id !== args.targetId ||
          startResponse.robot_control_enabled !== true) {
        throw new Error('start_response_mismatch');
      }
      const deadline = clockMs() + args.timeoutMs;
      while (true) {
        const status = await jsonRequest(fetchImpl, `${args.baseUrl}/api/va/status`);
        if (status.active !== true) {
          const result = status.last_result;
          if (!result || result.requestId !== requestId || result.targetId !== args.targetId) {
            throw new Error('terminal_status_request_mismatch');
          }
          trial.result = result;
          trial.evidence_authorized = trialEvidenceValid(result, {
            requestId, targetId: args.targetId,
            calibrationId: calibration.calibration_id,
            visionConfigId, actionConfigId,
            pathValidationId: config.place.path_validation_id,
            visionEvidence,
          });
          if (trial.evidence_authorized) {
            trial.measured_grasp_point_m = [
              ...result.actionEvidence.payload.detected_grasp_point_m,
            ];
          }
          break;
        }
        if (clockMs() >= deadline) throw new Error('trial_timeout');
        await delay(args.pollMs);
      }
      trial.operator_confirmation = await confirmTrial({ trial: { ...trial } });
    } catch (error) {
      trial.result = { ok: false, phase: 'failed', reason: error.message };
      if (startAccepted) {
        trial.stop_confirmation = await stopAndConfirm({
          fetchImpl, baseUrl: args.baseUrl, requestId,
          timeoutMs: args.timeoutMs, pollMs: args.pollMs, clockMs, delay,
        });
        abortRun = true;
      }
    }
    trial.finished_at = now().toISOString();
    report.trials.push(trial);
    reportWriter(reportPath, report);
    if (abortRun) break;
  }

  const successful = report.trials.filter(trial =>
    trial.result?.ok === true && trial.result?.phase === 'complete' &&
    trial.evidence_authorized === true &&
    trial.operator_confirmation?.upright === true &&
    trial.operator_confirmation?.wrongPick === false &&
    trial.operator_confirmation?.idSwitch === false
  ).length;
  const wrongPicks = report.trials.filter(
    trial => trial.operator_confirmation?.wrongPick === true
  ).length;
  const idSwitches = report.trials.filter(
    trial => trial.operator_confirmation?.idSwitch === true
  ).length;
  const invalidEvidenceAuthorizations = report.trials.filter(trial =>
    trial.result?.ok === true && trial.result?.phase === 'complete' &&
    trial.evidence_authorized !== true
  ).length;
  const successRate = report.requested_trials === 0 ? 0 : successful / report.requested_trials;
  const coverage = evaluateCoverage(report.trials, report.requested_trials);
  report.acceptance = {
    completed_trials: report.trials.length,
    successful_trials: successful,
    success_rate: successRate,
    wrong_pick_count: wrongPicks,
    identity_switch_count: idSwitches,
    invalid_evidence_authorization_count: invalidEvidenceAuthorizations,
    required_success_rate: 0.90,
    coverage,
  };
  report.passed = report.trials.length === report.requested_trials &&
    successRate >= 0.90 && wrongPicks === 0 && idSwitches === 0 &&
    invalidEvidenceAuthorizations === 0 && coverage.passed === true;
  report.finished_at = now().toISOString();
  reportWriter(reportPath, report);
  write(JSON.stringify({
    status: report.passed ? 'passed' : 'failed',
    report: reportPath, acceptance: report.acceptance,
    robot_control_enabled: true,
  }));
  return report.passed ? 0 : 1;
}

if (require.main === module) {
  main().then(code => { process.exitCode = code; }).catch(error => {
    console.error(error.stack || error.message);
    process.exitCode = 2;
  });
}

module.exports = {
  LIVE_ROBOT_ACK, evaluateCoverage, loadCalibration, loadSpecimenManifest,
  loadVisionEvidence, main, parseArgs,
};
