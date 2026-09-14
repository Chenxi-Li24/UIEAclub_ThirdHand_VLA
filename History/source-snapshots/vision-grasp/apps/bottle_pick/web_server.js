'use strict';

const http = require('node:http');
const path = require('node:path');

const { CameraBridge } = require(
  '../../src/thirdhand_va/action/adapters/camera_bridge'
);
const { createRobotClient, REAL_ACK } = require(
  '../../src/thirdhand_va/action/adapters/robot_client_factory'
);
const { loadActionConfig } = require('../../src/thirdhand_va/action/config');
const { WorkflowClient } = require('../../src/thirdhand_va/action/grasp/workflow');
const { HomeCoordinator } = require(
  '../../src/thirdhand_va/action/safety/home_coordinator'
);
const { evaluateHomeState } = require(
  '../../src/thirdhand_va/action/safety/home_gate'
);
const {
  loadApprovedRuntimeEvidence,
  sameRuntimeEvidence,
} = require('../../src/thirdhand_va/action/runtime/approved_runtime');
const { OperatorController } = require(
  '../../src/thirdhand_va/action/operator/controller'
);
const { StatusStore } = require(
  '../../src/thirdhand_va/action/operator/status_store'
);

const ROBOT_ENABLE_ACK = REAL_ACK;

function validateRuntimeAuthorization(env = process.env) {
  const cameraEnabled = env.THIRDHAND_VA_ENABLE_CAMERA === '1';
  const robotEnabled = env.THIRDHAND_VA_ENABLE_ROBOT === '1';
  if (cameraEnabled && env.THIRDHAND_VA_ALLOW_CAMERA !== '1') {
    throw new Error('camera enable requires THIRDHAND_VA_ALLOW_CAMERA=1');
  }
  if (robotEnabled && !cameraEnabled) {
    throw new Error('robot enable requires the camera bridge');
  }
  if (robotEnabled && env.THIRDHAND_ALLOW_ROBOT !== ROBOT_ENABLE_ACK) {
    throw new Error('robot enable requires the exact supervised motion acknowledgement');
  }
  if (robotEnabled && (
    typeof env.THIRDHAND_VA_HANDEYE !== 'string' || !env.THIRDHAND_VA_HANDEYE
  )) {
    throw new Error('robot enable requires THIRDHAND_VA_HANDEYE');
  }
  return Object.freeze({ cameraEnabled, robotEnabled });
}

function configuredHomeEvaluation({ robotClient, config, robotState = undefined }) {
  const homePreset = config?.place?.home_preset;
  return evaluateHomeState({
    robotState: robotState ?? robotClient?.getRobotState(),
    homeJointsDeg: config?.robot?.presets?.[homePreset],
    toleranceDeg: config?.robot?.home_tolerance_deg,
  });
}

function homeRuntimeStatus({ homeCoordinator, robotClient, config }) {
  if (!homeCoordinator || typeof homeCoordinator.snapshot !== 'function') {
    return Object.freeze({
      phase: 'disabled', ready: false, reason: 'robot_execution_disabled',
    });
  }
  const startup = homeCoordinator.snapshot();
  if (startup.phase !== 'ready') return startup;
  const current = configuredHomeEvaluation({ robotClient, config });
  if (current.allowed === true) return startup;
  return Object.freeze({
    phase: 'away', ready: false,
    reason: current.blockers[0] || 'robot_not_at_home',
    blockers: current.blockers,
  });
}

function robotRuntimeReady({
  robotClient, cameraInfo, approvedRuntimeEvidence, config, homeCoordinator,
}) {
  try {
    const state = robotClient?.getRobotState();
    const home = configuredHomeEvaluation({ robotClient, config, robotState: state });
    return homeCoordinator?.ready === true && home.allowed === true &&
      robotClient?.connected === true && robotClient?.protocolReady === true &&
      state?.poseFrame === 'robot_flange' && state.connected === true &&
      state.healthy === true && state.stateFresh === true &&
      state.stationary === true && cameraInfo?.ready === true &&
      cameraInfo.calibrationApproved === true &&
      sameRuntimeEvidence(cameraInfo.runtimeEvidence, approvedRuntimeEvidence);
  } catch {
    return false;
  }
}

function sendJson(response, status, payload) {
  const body = Buffer.from(`${JSON.stringify(payload)}\n`);
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': body.length,
    'cache-control': 'no-store',
  });
  response.end(body);
}

function readJson(request, maxBodyBytes) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    request.on('data', chunk => {
      size += chunk.length;
      if (size > maxBodyBytes) {
        const error = new Error('request_body_too_large');
        error.statusCode = 413;
        reject(error);
        request.destroy();
        return;
      }
      chunks.push(chunk);
    });
    request.on('end', () => {
      try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8'))); } catch {
        const error = new Error('invalid_json');
        error.statusCode = 400;
        reject(error);
      }
    });
    request.on('error', reject);
  });
}

function validStart(body) {
  return body && typeof body === 'object' && !Array.isArray(body) &&
    Object.keys(body).sort().join(',') === 'cmd,request_id,schema,target_id' &&
    body.schema === 'thirdhand.va.command.v1' && body.cmd === 'start' &&
    Number.isSafeInteger(body.target_id) && body.target_id >= 1 && body.target_id <= 5 &&
    typeof body.request_id === 'string' && body.request_id.length > 0;
}

function validStop(body) {
  return body && typeof body === 'object' && !Array.isArray(body) &&
    Object.keys(body).sort().join(',') === 'cmd,request_id,schema' &&
    body.schema === 'thirdhand.va.command.v1' && body.cmd === 'stop' &&
    typeof body.request_id === 'string' && body.request_id.length > 0;
}

function createWebServer({
  cameraBridge,
  operatorController,
  host = '127.0.0.1',
  port = 8766,
  maxBodyBytes = 16 * 1024,
  robotControlEnabled = false,
  robotReady = () => false,
  homeStatus = () => null,
  runtimeEvidence = () => ({}),
} = {}) {
  if (!cameraBridge || typeof cameraBridge.subscribeMjpeg !== 'function') {
    throw new TypeError('cameraBridge.subscribeMjpeg is required');
  }
  if (!operatorController || typeof operatorController.start !== 'function' ||
      typeof operatorController.stop !== 'function' ||
      typeof operatorController.snapshot !== 'function') {
    throw new TypeError('operatorController is required');
  }
  if (typeof robotReady !== 'function') throw new TypeError('robotReady must be a function');
  if (typeof homeStatus !== 'function') throw new TypeError('homeStatus must be a function');
  if (typeof runtimeEvidence !== 'function') {
    throw new TypeError('runtimeEvidence must be a function');
  }
  const robotControlReady = () => {
    try { return robotControlEnabled === true && robotReady() === true; } catch { return false; }
  };
  const cameraReady = () => cameraBridge.getInfo?.().ready ?? cameraBridge.ready === true;
  const streamRoutes = new Map([
    ['/camera_lumos_vision', 'overlay'],
    ['/camera_xvisio_raw', 'raw'],
    ['/camera_xvisio_depth', 'depth'],
  ]);
  const server = http.createServer(async (request, response) => {
    if (request.method === 'GET' && request.url === '/health') {
      sendJson(response, 200, {
        status: 'ok',
        camera_ready: cameraReady(),
        va_active: operatorController.snapshot().active,
        robot_control_enabled: robotControlReady(),
        home: homeStatus(),
        artifacts: runtimeEvidence(),
      });
      return;
    }
    if (request.method === 'GET' && request.url === '/api/va/status') {
      sendJson(response, 200, { ...operatorController.snapshot(), home: homeStatus() });
      return;
    }
    if (request.method === 'GET' && streamRoutes.has(request.url)) {
      if (!cameraReady()) {
        sendJson(response, 503, { accepted: false, reason: 'camera_not_ready' });
        return;
      }
      response.writeHead(200, {
        'content-type': 'multipart/x-mixed-replace; boundary=frame',
        'cache-control': 'no-store, no-cache, must-revalidate',
        connection: 'close',
      });
      if (!cameraBridge.subscribeMjpeg(streamRoutes.get(request.url), response)) {
        response.end();
      }
      response.on('close', () => {
        cameraBridge.unsubscribeMjpeg?.(streamRoutes.get(request.url), response);
      });
      return;
    }
    if (request.method === 'POST' && request.url === '/api/va/start') {
      try {
        const body = await readJson(request, maxBodyBytes);
        if (!validStart(body)) {
          sendJson(response, 400, { accepted: false, reason: 'start_contract_invalid' });
          return;
        }
        // Let OperatorController preserve request idempotency while the active arm is
        // necessarily away from Home; only a brand-new request needs the Home gate.
        if (!operatorController.snapshot().active && !robotControlReady()) {
          sendJson(response, 423, {
            accepted: false, reason: 'va_runtime_not_ready',
            target_id: body.target_id, request_id: body.request_id,
            robot_control_enabled: false,
          });
          return;
        }
        const result = operatorController.start({
          targetId: body.target_id, requestId: body.request_id,
        });
        const status = result.accepted ? 202
          : result.reason === 'workflow_active' ? 409 : 423;
        sendJson(response, status, {
          accepted: result.accepted === true,
          duplicate: result.duplicate === true,
          target_id: body.target_id,
          request_id: body.request_id,
          reason: result.reason ?? null,
          robot_control_enabled: robotControlReady(),
        });
      } catch (error) {
        sendJson(response, error.statusCode || 400, {
          accepted: false, reason: error.message || 'invalid_request',
        });
      }
      return;
    }
    if (request.method === 'POST' && request.url === '/api/va/stop') {
      try {
        const body = await readJson(request, maxBodyBytes);
        if (!validStop(body)) {
          sendJson(response, 400, { accepted: false, reason: 'stop_contract_invalid' });
          return;
        }
        const result = operatorController.stop(`requested:${body.request_id}`);
        sendJson(response, result.accepted ? 202 : 409, {
          ...result,
          request_id: body.request_id,
          robot_control_enabled: robotControlReady(),
        });
      } catch (error) {
        sendJson(response, error.statusCode || 400, {
          accepted: false, reason: error.message || 'invalid_request',
        });
      }
      return;
    }
    sendJson(response, 404, { status: 'not_found', robot_control_enabled: false });
  });

  return {
    server,
    start() {
      return new Promise((resolve, reject) => {
        const onError = error => reject(error);
        server.once('error', onError);
        server.listen(port, host, () => {
          server.off('error', onError);
          resolve(server.address());
        });
      });
    },
    stop() {
      if (!server.listening) return Promise.resolve();
      return new Promise((resolve, reject) => {
        server.close(error => error ? reject(error) : resolve());
      });
    },
  };
}

function createDisabledWorkflow({ onFinish }) {
  return {
    start({ targetId, requestId }) {
      const result = {
        ok: false, targetId, requestId, phase: 'failed',
        reason: 'robot_execution_disabled',
      };
      onFinish(result);
      return { accepted: false, reason: result.reason };
    },
    cancel() { return { accepted: true, duplicate: true }; },
    snapshot() { return { active: false, phase: 'disabled' }; },
  };
}

async function main() {
  const projectRoot = path.resolve(__dirname, '../..');
  const { cameraEnabled, robotEnabled } = validateRuntimeAuthorization(process.env);
  const config = loadActionConfig(
    process.env.THIRDHAND_VA_ACTION_CONFIG || path.join(projectRoot, 'configs/action.yaml')
  );
  const cameraBridge = new CameraBridge({ projectRoot });
  const statusStore = new StatusStore(path.resolve(projectRoot, config.status_file));
  let robotClient = null;
  let homeCoordinator = null;
  let approvedRuntimeEvidence = null;
  let createWorkflow;
  if (robotEnabled) {
    if (config.execution_enabled !== true) {
      throw new Error('robot enable requested but action config execution is disabled');
    }
    approvedRuntimeEvidence = loadApprovedRuntimeEvidence({
      visionConfigPath: path.resolve(
        process.env.VISION_CONFIG || path.join(projectRoot, 'configs/vision.yaml')
      ),
      calibrationPath: path.resolve(process.env.THIRDHAND_VA_HANDEYE),
    });
    const robotDependencies = {
      realAuthorization: process.env.THIRDHAND_ALLOW_ROBOT,
      ...(config.robot.backend === 'websocket'
        ? { WebSocketImpl: require('ws') } : {}),
    };
    robotClient = createRobotClient(config, robotDependencies);
    homeCoordinator = new HomeCoordinator({
      robotClient,
      homePreset: config.place.home_preset,
      homeJointsDeg: config.robot.presets[config.place.home_preset],
      toleranceDeg: config.robot.home_tolerance_deg,
      startupValidated: config.place.startup_home_validated,
      startupJointRangesDeg: config.place.startup_joint_ranges_deg,
      timeoutMs: config.home_timeout_ms,
    });
    const homeStart = homeCoordinator.start();
    if (homeStart.accepted !== true) {
      throw new Error(homeStart.reason || 'startup_home_failed');
    }
    if (robotClient.connect() !== true) throw new Error('robot_start_failed');
    createWorkflow = ({ onFinish }) => new WorkflowClient({
      cameraBridge, robotClient, config, store: statusStore, onFinish,
      workflowTimeoutMs: config.workflow_timeout_ms,
      runtimeEvidence: () => cameraBridge.getInfo().runtimeEvidence,
      approvedRuntimeEvidence,
    });
  } else {
    createWorkflow = createDisabledWorkflow;
  }
  const operatorController = new OperatorController({ createWorkflow, statusStore });
  const app = createWebServer({
    cameraBridge,
    operatorController,
    host: process.env.THIRDHAND_VA_HOST || '127.0.0.1',
    port: Number(process.env.THIRDHAND_VA_PORT || 8766),
    robotControlEnabled: robotEnabled && config.execution_enabled,
    robotReady: () => robotRuntimeReady({
      robotClient,
      cameraInfo: cameraBridge.getInfo(),
      approvedRuntimeEvidence,
      config,
      homeCoordinator,
    }),
    homeStatus: () => homeRuntimeStatus({ homeCoordinator, robotClient, config }),
    runtimeEvidence: () => {
      const camera = cameraBridge.getInfo().runtimeEvidence;
      return {
        action_config_id: config.content_id,
        path_validation_id: config.place.path_validation_id,
        calibration_id: camera?.calibration_id ?? null,
        vision_config_id: camera?.vision_config_id ?? null,
        model_provenance: camera?.model_provenance ?? null,
        camera_serial: camera?.camera_serial ?? null,
        registration_id: camera?.registration_id ?? null,
        camera_mount_id: camera?.camera_mount_id ?? null,
      };
    },
  });
  if (cameraEnabled) cameraBridge.start();
  const address = await app.start();
  console.log(JSON.stringify({
    type: 'va_service_ready', address, camera_started: cameraEnabled,
    robot_started: robotEnabled,
    home_phase: homeCoordinator?.snapshot().phase ?? 'disabled',
    robot_control_enabled: false,
  }));
  const shutdown = async () => {
    cameraBridge.shutdown();
    homeCoordinator?.shutdown();
    robotClient?.shutdown();
    await app.stop();
  };
  process.once('SIGINT', shutdown);
  process.once('SIGTERM', shutdown);
  return app;
}

if (require.main === module) {
  main().catch(error => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}

module.exports = {
  ROBOT_ENABLE_ACK, createWebServer, homeRuntimeStatus, main, robotRuntimeReady,
  validStart, validStop, validateRuntimeAuthorization,
};
