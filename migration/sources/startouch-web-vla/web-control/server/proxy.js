/**
 * ThirdHand Web Control - browser WebSocket to local Startouch SDK.
 */

'use strict';

const express = require('express');
const http = require('http');
const os = require('os');
const path = require('path');
const { randomUUID } = require('crypto');
const { WebSocketServer } = require('ws');
const config = require('./config');
const { StartouchBridge } = require('./startouch-bridge');
const { CameraBridge } = require('./camera-bridge');
const { XVisionClient } = require('./xvision-client');
const { normalizeXVisionEvent } = require('./xvision-contract');
const { VisionStatusStore } = require('./vision-status');
const { ActiveViewAuditLog } = require('./active-view-audit-log');
const { loadActiveViewApproval } = require('./active-view-authorization');
const { ActiveViewController } = require('./active-view-controller');
const {
  authorizeActiveViewStart,
  parseActiveViewBrowserCommand,
} = require('./active-view-browser-protocol');
const {
  authorizeGraspPlan,
} = require('./grasp-authorization');
const { GraspController } = require('./grasp-controller');
const lumosExternalUrl = process.env.LUMOS_STREAM_URL ||
  'http://127.0.0.1:3001/camera_lumos';

const app = express();
app.use(express.static(path.join(__dirname, '..', 'web')));
const server = http.createServer(app);
const wss = new WebSocketServer({ server, path: '/ws' });
const clients = new Set();
const bridge = new StartouchBridge(config.robot);
const cameraBridge = new CameraBridge(config.camera || {});
const xvisionClient = config.xvision.enabled ? new XVisionClient(config.xvision) : null;
const visionStatus = new VisionStatusStore({ staleAfterMs: 2000, maxTargets: 256 });
let latestJointsDeg = null;
let latestTcpEuler = null;    // [rad] for camera bridge
let latestTcpPos = null;      // [m] for camera bridge
let latestRobotStateAtMs = null;
let stateReady = false;
let motionActive = false;
let connectPending = false;
let latestTrustedTarget = null;
let graspController;

function graspIsActive() {
  if (!graspController) return false;
  return !['idle', 'holding', 'aborted'].includes(graspController.snapshot().phase);
}

let activeViewAuditLog;
try {
  activeViewAuditLog = new ActiveViewAuditLog(config.activeView.auditLog);
} catch (error) {
  console.error(`[Active view] audit log unavailable; motion locked: ${error.message}`);
  activeViewAuditLog = { append: () => { throw new Error('active-view audit unavailable'); } };
}

const activeViewLimits = {
  maxSpeedScale: config.activeView.maxSpeedScale,
  maxTranslationM: config.activeView.maxTranslationM,
  maxRotationRad: config.activeView.maxRotationRad,
  maxRefinementSteps: config.activeView.maxRefinementSteps,
  requireStepConfirmation: config.activeView.requireStepConfirmation,
  robotModelId: config.activeView.robotModelId,
  jointLimitsDeg: config.jointLimitsDeg,
};

const activeView = new ActiveViewController({
  requested: config.activeView.requested,
  loadApproval: () => config.activeView.approvalFile
    ? loadActiveViewApproval(config.activeView.approvalFile)
    : null,
  limits: activeViewLimits,
  getRobotState: () => ({
    connected: bridge.connected,
    moving: motionActive,
    stateFresh: stateReady && latestRobotStateAtMs !== null &&
      Date.now() - latestRobotStateAtMs <= 250,
    graspActive: graspIsActive(),
    currentJointsDeg: latestJointsDeg,
  }),
  sendRobot: sendActiveViewRobotCommand,
  sendVision: command => cameraBridge.send(command),
  auditLog: activeViewAuditLog,
});

graspController = new GraspController({
  sendRobot(command, phase) {
    if (!latestTcpEuler || !Array.isArray(latestTcpEuler) ||
        latestTcpEuler.length !== 3 || !latestTcpEuler.every(Number.isFinite)) return false;
    if (command.cmd === 'move_l') {
      return bridge.send({
        cmd: 'move_l',
        position: command.position_m,
        euler: [...latestTcpEuler],
        time_sec: command.time_sec,
        request_id: command.request_id,
      });
    }
    if (command.cmd === 'gripper') {
      return bridge.send({ cmd: 'gripper', position: command.position });
    }
    return false;
  },
  authorizePlan(target, expectations = {}) {
    return authorizeGraspPlan({
      executionEnabled: config.visionSafety.robotExecutionEnabled,
      bridgeConnected: bridge.connected,
      armMotionActive: motionActive,
      robotStateFresh: stateReady && latestRobotStateAtMs !== null &&
        Date.now() - latestRobotStateAtMs <= 250,
      target,
      nowMs: Date.now(),
      ...expectations,
    });
  },
  canContinue() {
    if (!bridge.connected) return { approved: false, reason: 'robot_not_connected' };
    if (motionActive) return { approved: false, reason: 'arm_motion_active' };
    if (!stateReady || latestRobotStateAtMs === null || Date.now() - latestRobotStateAtMs > 250) {
      return { approved: false, reason: 'robot_state_stale' };
    }
    return { approved: true };
  },
});

graspController.on('status', status => {
  broadcast({ type: 'grasp_status', ...status, ts: Date.now() });
});

function activeViewIsActive() {
  return activeView.session !== null || activeView.pending !== null || activeView.inFlight !== null;
}

// ── Lumos streamer (separate process, no pyrealsense2 conflict) ──
let lumosChild = null;
function startLumosStream() {
  if (lumosExternalUrl) return;
  if (lumosChild) return;
  const { spawn: spawnLumos } = require('child_process');
  const lumosPy = require('path').join(__dirname, 'lumos_stream.py');
  const lumosPython = config.camera.python || process.env.STARTOUCH_PYTHON || 'python3';
  lumosChild = spawnLumos(lumosPython, ['-u', lumosPy], {
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  lumosChild.stderr.on('data', d => console.warn('[Lumos]', d.toString().trim()));
  lumosChild.on('exit', (code) => {
    console.warn(`[Lumos] exited with code ${code}, restarting in 2s...`);
    lumosChild = null;
    setTimeout(startLumosStream, 2000);
  });
}
function getLumosStream() {
  return lumosChild ? lumosChild.stdout : null;
}

function broadcast(data) {
  const json = JSON.stringify(data);
  for (const ws of clients) {
    if (ws.readyState === 1) ws.send(json);
  }
}

function send(ws, data) {
  if (ws.readyState === 1) ws.send(JSON.stringify(data));
}

function radiansToDegrees(values) {
  return values.map(value => value * 180 / Math.PI);
}

function formatJoints(values) {
  return values.map((value, index) => `J${index + 1}=${value.toFixed(2)}°`).join(' ');
}

function validateJoints(joints) {
  if (!Array.isArray(joints) || joints.length !== 6) {
    return 'joints 必须包含 J1 到 J6 六个角度值';
  }
  for (let index = 0; index < joints.length; index++) {
    const value = Number(joints[index]);
    const [min, max] = config.jointLimitsDeg[index];
    if (!Number.isFinite(value)) return `J${index + 1} 不是有效数字`;
    if (value < min || value > max) {
      return `J${index + 1} 超出 Startouch 限位 ${min.toFixed(1)}° ~ ${max.toFixed(1)}°`;
    }
  }
  return null;
}

function moveTimeFor(joints) {
  const reference = latestJointsDeg || joints.map(() => 0);
  const deltas = joints.map((value, index) => Math.abs(value - reference[index]));
  const hardMinimum = Math.max(
    ...deltas.map((delta, index) => delta / config.jointMaxSpeedsDegS[index])
  );
  const requested = Math.max(
    ...deltas.map((delta, index) => (
      delta / (config.jointMaxSpeedsDegS[index] * config.robot.speedScale)
    ))
  );
  const bounded = Math.max(
    config.robot.minMoveTimeSec,
    Math.min(config.robot.maxMoveTimeSec, requested)
  );
  return Math.max(hardMinimum, bounded);
}

function sendJointMotion(joints, ws, source = 'servo') {
  const error = validateJoints(joints);
  if (error) {
    send(ws, { type: 'error', msg: error });
    return;
  }
  if (!bridge.connected) {
    send(ws, { type: 'error', msg: 'Startouch SDK 尚未连接' });
    return;
  }
  if (!stateReady || !latestJointsDeg) {
    send(ws, { type: 'error', msg: '机械臂状态尚未稳定，禁止下发运动' });
    return;
  }
  if (motionActive) {
    send(ws, { type: 'error', msg: '上一条关节运动尚未完成' });
    return;
  }
  if (activeViewIsActive()) {
    send(ws, { type: 'error', msg: '主动观察会话进行中，普通运动已闭锁' });
    return;
  }

  const normalized = joints.map(Number);
  if (
    source !== 'preset:home'
    && normalized.every(value => Math.abs(value) < 0.05)
    && latestJointsDeg.some(value => Math.abs(value) > 2)
  ) {
    send(ws, { type: 'error', msg: '已阻止意外的全零目标；回零请使用“六轴 0° 姿态”' });
    return;
  }
  const timeSec = moveTimeFor(normalized);
  console.log(
    `[Command ${new Date().toISOString()}] ${source} `
    + `current=[${formatJoints(latestJointsDeg)}] `
    + `target=[${formatJoints(normalized)}] time=${timeSec.toFixed(3)}s`
  );
  bridge.send({
    cmd: 'move_joint',
    joints_rad: normalized.map(value => value * Math.PI / 180),
    time_sec: timeSec,
    request_id: randomUUID(),
    source,
  });
}

function sendActiveViewRobotCommand(command) {
  if (!bridge.connected || !stateReady || motionActive ||
      latestRobotStateAtMs === null || Date.now() - latestRobotStateAtMs > 250) return false;
  if (command.cmd === 'move_joint') {
    const jointsDeg = radiansToDegrees(command.joints_rad || []);
    if (validateJoints(jointsDeg) || jointsDeg.every(value => Math.abs(value) < 0.05)) return false;
    return bridge.send({
      cmd: 'move_joint',
      joints_rad: [...command.joints_rad],
      time_sec: moveTimeFor(jointsDeg),
      request_id: command.request_id,
      source: command.source,
    });
  }
  if (command.cmd === 'move_l_delta') {
    if (![latestTcpPos, latestTcpEuler, command.delta_base_m].every(
      value => Array.isArray(value) && value.length === 3 && value.every(Number.isFinite)
    )) return false;
    const position = latestTcpPos.map((value, index) => value + command.delta_base_m[index]);
    const distanceM = Math.hypot(...command.delta_base_m);
    if (!position.every(Number.isFinite) || distanceM <= 1e-12 ||
        distanceM > config.activeView.maxTranslationM + 1e-12) return false;
    return bridge.send({
      cmd: 'move_l',
      position,
      euler: [...latestTcpEuler],
      time_sec: Math.max(2.0, distanceM / 0.01),
      request_id: command.request_id,
      source: command.source,
    });
  }
  return false;
}

bridge.on('connection', message => {
  latestJointsDeg = null;
  stateReady = false;
  motionActive = false;
  connectPending = false;
  latestRobotStateAtMs = null;
  if (!message.connected) activeView.onRobotEvent(message);
  if (message.connected) {
    console.log(`[Robot ${new Date().toISOString()}] connected on ${config.robot.canInterface}`);
  } else {
    console.warn(
      `[Robot ${new Date().toISOString()}] disconnected: `
      + `${message.error || message.reason || 'unknown reason'}`
    );
  }
  broadcast({
    type: 'connection',
    mode: 'startouch',
    host: 'localhost',
    interface: config.robot.canInterface,
    ...message,
  });
});

// ── Diagnostic endpoint ─────────────────────────────────────
app.get('/diag', (req, res) => {
  const { execSync } = require('child_process');
  const diag = {
    time: new Date().toISOString(),
    can: {},
    usb: {},
    processes: {},
  };
  try {
    diag.can.interface = require('child_process')
      .execSync('ip -br link show can0 2>/dev/null || echo DOWN', { timeout: 2000 })
      .toString().trim();
  } catch (_) { diag.can.interface = 'DOWN'; }
  try {
    diag.can.lock = require('fs').existsSync('/tmp/startouch-web-can0.lock');
    if (diag.can.lock) {
      diag.can.lockPid = require('fs').readFileSync('/tmp/startouch-web-can0.lock', 'utf8').trim();
    }
  } catch (_) { diag.can.lock = 'error'; }
  try {
    const out = require('child_process')
      .execSync('for d in /sys/bus/usb/devices/*/idVendor; do d=$(dirname "$d"); id=$(cat "$d/idVendor" 2>/dev/null)$(cat "$d/idProduct" 2>/dev/null); if [ "$id" = "80860b07" ]; then echo "$(basename $d) control=$(cat $d/power/control) status=$(cat $d/power/runtime_status)"; fi; done', { timeout: 2000 })
      .toString().trim();
    diag.usb.d435 = out || 'not found';
  } catch (_) { diag.usb.d435 = 'error'; }
  diag.processes = {
    proxy: process.pid,
    startouchBridge: bridge.child ? bridge.child.pid : null,
    cameraBridge: cameraBridge.child ? cameraBridge.child.pid : null,
    armConnected: bridge.connected,
    cameraReady: cameraBridge.ready,
    lumosSource: lumosExternalUrl || 'managed_child',
  };
  res.json(diag);
});

// ── Camera MJPEG routes ─────────────────────────────────────
app.get('/camera', (req, res) => {
  const stream = cameraBridge.getMjpegStream();
  if (!stream) {
    res.status(503).send('Camera not ready');
    return;
  }
  res.setHeader('Content-Type', 'multipart/x-mixed-replace; boundary=frame');
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
  res.flushHeaders();
  stream.pipe(res);
  req.on('close', () => cameraBridge.releaseMjpegStream(stream, res));
});

app.get('/camera_lumos', (req, res) => {
  if (lumosExternalUrl) {
    let upstreamUrl;
    try {
      upstreamUrl = new URL(lumosExternalUrl);
      if (upstreamUrl.protocol !== 'http:') throw new Error('only http is allowed');
    } catch (error) {
      res.status(503).send(`Invalid Lumos stream URL: ${error.message}`);
      return;
    }
    const upstream = http.get(upstreamUrl, response => {
      if (response.statusCode !== 200) {
        response.resume();
        res.status(503).send(`Lumos upstream returned ${response.statusCode}`);
        return;
      }
      res.setHeader(
        'Content-Type',
        response.headers['content-type'] || 'multipart/x-mixed-replace; boundary=frame'
      );
      res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
      res.flushHeaders();
      response.pipe(res);
    });
    upstream.on('error', error => {
      if (!res.headersSent) res.status(503).send(`Lumos upstream unavailable: ${error.message}`);
      else res.destroy(error);
    });
    req.on('close', () => upstream.destroy());
    return;
  }
  const stream = getLumosStream();
  if (!stream) {
    res.status(503).send('Lumos camera not available');
    return;
  }
  res.setHeader('Content-Type', 'multipart/x-mixed-replace; boundary=frame');
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
  res.flushHeaders();
  stream.pipe(res);
  req.on('close', () => cameraBridge.releaseMjpegStream(stream, res));
});

app.get('/camera_lumos_vision', (req, res) => {
  const stream = cameraBridge.getVisionMjpegStream();
  if (!stream) {
    res.status(503).send('Lumos vision overlay not ready');
    return;
  }
  res.setHeader('Content-Type', 'multipart/x-mixed-replace; boundary=frame');
  res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate');
  res.flushHeaders();
  stream.pipe(res);
  req.on('close', () => cameraBridge.releaseMjpegStream(stream, res));
});

app.get('/camera/xvisio/vision', (req, res) => {
  if (!xvisionClient) {
    res.status(503).send('XVisio proxy is disabled');
    return;
  }
  xvisionClient.proxyMjpeg('/camera_lumos_vision', req, res);
});

app.get('/camera/xvisio/raw', (req, res) => {
  if (!xvisionClient) {
    res.status(503).send('XVisio proxy is disabled');
    return;
  }
  xvisionClient.proxyMjpeg('/camera_lumos', req, res);
});

app.get('/api/vision/status', (_req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  const snapshot = visionStatus.snapshot(Date.now());
  snapshot.activeViewExecutionEnabled = activeView.inFlight !== null;
  snapshot.activeViewExecutionRequested = config.activeView.requested;
  snapshot.activeView.executionEnabled = activeView.inFlight !== null;
  snapshot.activeView.executionRequested = config.activeView.requested;
  res.json(snapshot);
});

// ── Camera bridge events ────────────────────────────────────
cameraBridge.on('detection_result', message => {
  visionStatus.updateTargets(message);
  broadcast(message);
});

cameraBridge.on('camera_status', message => {
  visionStatus.updateCamera(message);
  if (message.d435_ready === false) {
    activeView.onVisionEvent({ type: 'active_view_abort', reason: 'd435_unavailable' });
  }
  broadcast(message);
});

cameraBridge.on('camera_error', message => {
  visionStatus.updateCamera(message);
  activeView.onVisionEvent({ type: 'active_view_abort', reason: 'camera_error' });
  broadcast({ type: 'camera_error', msg: message.message });
});

cameraBridge.on('vision_status', message => {
  visionStatus.updateStatus(message);
  broadcast(message);
});

cameraBridge.on('vision_error', message => {
  visionStatus.updateStatus(message);
  activeView.onVisionEvent({ type: 'active_view_abort', reason: 'vision_error' });
  broadcast(message);
});

cameraBridge.on('active_view_move_proposal', message => {
  const result = activeView.onVisionEvent(message);
  if (result.accepted !== true || !activeView.pending) {
    broadcast({
      type: 'active_view_state',
      phase: 'aborted',
      reasons: [result.reason || 'proposal_rejected'],
      moveReady: false,
      activeViewExecutionEnabled: false,
    });
    return;
  }
  const moveReady = {
    type: 'active_view_move_ready',
    sessionId: activeView.pending.sessionId,
    proposalId: activeView.pending.proposalId,
    identityId: activeView.pending.identityId,
    kind: message.kind,
    targetPoseId: activeView.pending.targetPoseId,
    evidenceIds: activeView.pending.evidenceIds,
    maxStepM: config.activeView.maxTranslationM,
    requiresConfirmation: true,
  };
  visionStatus.updateActiveViewMoveReady(moveReady);
  const control = visionStatus.snapshot(Date.now()).activeView.control;
  broadcast({ type: 'active_view_move_ready', ...control });
});

cameraBridge.on('active_view_state', message => {
  activeView.onVisionEvent(message);
  visionStatus.updateActiveViewState(message);
  const control = visionStatus.snapshot(Date.now()).activeView.control;
  broadcast({
    type: 'active_view_state',
    ...control,
    activeViewExecutionEnabled: activeView.inFlight !== null,
  });
});

cameraBridge.on('active_view_protocol_rejected', message => {
  activeView.onVisionEvent({ type: 'active_view_abort', reason: 'protocol_rejected' });
  broadcast({
    type: 'active_view_state',
    phase: 'aborted',
    reasons: [typeof message.reason === 'string' ? message.reason.slice(0, 128) : 'protocol_rejected'],
    moveReady: false,
    activeViewExecutionEnabled: false,
  });
});

cameraBridge.on('log', message => {
  console.warn(`[Camera] ${message.message}`);
});

if (xvisionClient) {
  xvisionClient.on('detection_result', message => {
    try {
      const normalized = normalizeXVisionEvent(message);
      latestTrustedTarget = normalized.trustedTarget;
      graspController.updateTarget(latestTrustedTarget);
      visionStatus.updateTargets(normalized.displayEvent);
      broadcast(normalized.displayEvent);
    } catch (error) {
      latestTrustedTarget = null;
      graspController.updateTarget(null);
      broadcast({ type: 'vision_error', msg: `XVisio event rejected: ${error.message}` });
    }
  });
  xvisionClient.on('camera_status', message => {
    visionStatus.updateCamera(message);
    broadcast(message);
  });
  xvisionClient.on('vision_status', message => {
    visionStatus.updateStatus(message);
    broadcast(message);
  });
  xvisionClient.on('selection_status', message => broadcast(message));
  xvisionClient.on('vision_error', message => {
    latestTrustedTarget = null;
    graspController.updateTarget(null);
    visionStatus.updateStatus(message);
    broadcast(message);
  });
  xvisionClient.on('connection', message => {
    if (!message.connected) {
      latestTrustedTarget = null;
      graspController.updateTarget(null);
      if (graspIsActive()) graspController.cancel('vision_disconnected');
    }
    broadcast({ type: 'xvision_connection', ...message });
  });
  xvisionClient.on('log', message => console.warn(`[XVisio] ${message.message}`));
}

// Forward arm state to camera bridge for coordinate transforms
bridge.on('robot_state', message => {
  const jointsDeg = radiansToDegrees(message.joints_rad);
  const velocitiesDeg = Array.isArray(message.velocities_rad_s)
    ? radiansToDegrees(message.velocities_rad_s)
    : [];
  if (
    jointsDeg.length !== 6 || !jointsDeg.every(Number.isFinite)
    || velocitiesDeg.length !== 6 || !velocitiesDeg.every(Number.isFinite)
  ) {
    broadcast({ type: 'error', msg: 'SDK 返回了无效关节状态，已忽略' });
    return;
  }
  latestJointsDeg = jointsDeg;
  latestTcpEuler = message.tcp_euler_rad;
  latestTcpPos = message.tcp_position_m;
  stateReady = true;
  latestRobotStateAtMs = Date.now();

  // Forward arm state to camera bridge for coordinate transforms
  if (cameraBridge.ready) {
    const stationary = !motionActive
      && message.state !== 'MOVING'
      && velocitiesDeg.every(value => Math.abs(value) <= 0.5);
    cameraBridge.sendArmState(
      message.tcp_position_m,
      message.tcp_euler_rad,
      jointsDeg,
      velocitiesDeg,
      stationary,
      process.hrtime.bigint().toString()
    );
  }

  broadcast({
    type: 'robot_state',
    joints: latestJointsDeg,
    velocities: velocitiesDeg,
    torques: message.torques_nm,
    tcpPos: message.tcp_position_m.map(value => value * 1000),
    tcpEuler: radiansToDegrees(message.tcp_euler_rad),
    gripperPosition: message.gripper_position,
    gripperDistanceMm: Number.isFinite(message.gripper_distance_m)
      ? message.gripper_distance_m * 1000
      : null,
    stateName: message.state,
    ts: message.ts,
  });
});

bridge.on('joint_log', message => {
  const jointsDeg = radiansToDegrees(message.joints_rad || []);
  if (jointsDeg.length !== 6 || !jointsDeg.every(Number.isFinite)) return;
  const targetDeg = Array.isArray(message.target_joints_rad)
    ? radiansToDegrees(message.target_joints_rad)
    : null;
  console.log(
    `[Joint ${new Date(message.ts).toISOString()}] phase=${message.phase} `
    + `actual=[${formatJoints(jointsDeg)}]`
    + `${targetDeg ? ` target=[${formatJoints(targetDeg)}]` : ''}`
  );
});

bridge.on('motion_state', message => {
  motionActive = message.state === 'MOVING';
  if (!motionActive) graspController.continueWhenIdle();
  broadcast({ type: 'motion_state', stateName: message.state, ts: message.ts });
});

bridge.on('command_accepted', message => {
  broadcast({ ...message, type: 'command_status', status: 'accepted' });
});

bridge.on('command_complete', message => {
  activeView.onRobotEvent(message);
  graspController.complete(message.command, message.request_id);
  broadcast({ ...message, type: 'command_status', status: 'complete' });
});

bridge.on('error', message => {
  activeView.onRobotEvent(message);
  if (graspIsActive()) graspController.fail(message.message || 'robot_command_failed');
  broadcast({ type: 'error', msg: message.message, requestId: message.request_id });
});

bridge.on('bridge_error', message => {
  broadcast({ type: 'error', msg: message.message });
});

bridge.on('software_stop_complete', message => {
  broadcast({
    type: 'software_stop',
    complete: true,
    depowered: true,
    msg: 'SDK cleanup 已完成，并已向全部电机发送失能命令',
    ts: message.ts || Date.now(),
  });
});

bridge.on('software_stop_timeout', message => {
  broadcast({
    type: 'software_stop',
    complete: false,
    depowered: false,
    msg: message.message,
    ts: Date.now(),
  });
});

bridge.on('log', message => {
  console.warn(`[Startouch] ${message.message}`);
  broadcast({ type: 'sdk_log', level: message.level, msg: message.message });
});

wss.on('connection', ws => {
  clients.add(ws);
  console.log(`[WS] client connected (${clients.size} total)`);
  send(ws, {
    type: 'config',
    presets: config.presets,
    jointLimits: config.jointLimitsDeg,
    model: config.model,
    connection: bridge.getInfo(),
    motion: {
      jointMaxSpeedsDegS: config.jointMaxSpeedsDegS,
      speedScale: config.robot.speedScale,
      commandedSpeedsDegS: config.jointMaxSpeedsDegS.map(
        speed => speed * config.robot.speedScale
      ),
      minMoveTimeSec: config.robot.minMoveTimeSec,
      maxMoveTimeSec: config.robot.maxMoveTimeSec,
    },
    camera: cameraBridge.getInfo(),
    visionSafety: {
      robotExecutionEnabled: config.visionSafety.robotExecutionEnabled,
      activeViewExecutionRequested: config.activeView.requested,
      activeViewExecutionEnabled: activeView.inFlight !== null,
    },
  });
  bridge.send({ cmd: 'get_state' });

  ws.on('message', data => {
    try {
      handleBrowserCommand(JSON.parse(data.toString()), ws);
    } catch (error) {
      send(ws, { type: 'error', msg: `无效消息: ${error.message}` });
    }
  });

  ws.on('close', () => {
    clients.delete(ws);
    console.log(`[WS] client disconnected (${clients.size} total)`);
  });
});

function handleBrowserCommand(message, ws) {
  console.log(`[WS cmd] ${message.cmd}`, JSON.stringify(message).slice(0, 120));
  switch (message.cmd) {
    case 'connect':
      if (bridge.connected) {
        bridge.send({ cmd: 'get_state' });
        return;
      }
      if (connectPending) {
        send(ws, { type: 'error', msg: 'Startouch SDK 正在连接，请勿重复点击' });
        return;
      }
      connectPending = true;
      if (!bridge.send({ cmd: 'connect' })) connectPending = false;
      break;

    case 'disconnect':
      activeView.onRobotEvent({ type: 'connection', connected: false });
      if (graspIsActive()) graspController.cancel('robot_disconnected');
      bridge.send({ cmd: 'disconnect' });
      break;

    case 'servo':
      sendJointMotion(message.joints, ws, 'servo');
      break;

    case 'preset': {
      const joints = config.presets[message.name];
      if (!joints) {
        send(ws, { type: 'error', msg: `未知预设位置: ${message.name}` });
        return;
      }
      sendJointMotion(joints, ws, `preset:${message.name}`);
      break;
    }

    case 'gripper':
      if (activeViewIsActive()) {
        send(ws, { type: 'error', msg: '主动观察会话进行中，夹爪控制已闭锁' });
        return;
      }
      if (graspIsActive()) {
        send(ws, { type: 'error', msg: '视觉夹取正在进行中，手动夹爪控制已闭锁' });
        return;
      }
      if (!bridge.connected) {
        send(ws, { type: 'error', msg: 'Startouch SDK 尚未连接' });
        return;
      }
      bridge.send({ cmd: 'gripper', position: message.position });
      break;

    case 'software_stop':
    case 'estop':
      activeView.onRobotEvent({ type: 'software_stop' });
      if (graspIsActive()) graspController.cancel('software_stop');
      if (bridge.softwareStop()) {
        broadcast({
          type: 'software_stop',
          complete: false,
          depowered: null,
          msg: '正在停止 SDK 并执行电机失能',
          ts: Date.now(),
        });
      } else {
        send(ws, { type: 'error', msg: 'Startouch SDK 尚未连接' });
      }
      break;

    case 'status':
      bridge.send({ cmd: 'get_state' });
      break;

    case 'ping':
      send(ws, { type: 'pong', ts: Date.now() });
      break;

    case 'select_vision_target': {
      if (!xvisionClient) {
        send(ws, { type: 'error', msg: 'XVisio 转发未启用' });
        return;
      }
      const side = message.side;
      const ordinal = Number(message.ordinal);
      if (!['left', 'right'].includes(side) || !Number.isInteger(ordinal) ||
          ordinal < 1 || ordinal > 32) {
        send(ws, { type: 'error', msg: '目标选择必须是 L1-L32 或 R1-R32' });
        return;
      }
      const accepted = xvisionClient.selectBottle({ side, ordinal, requestId: randomUUID() });
      send(ws, {
        type: 'vision_selection_result',
        accepted,
        side,
        ordinal,
        reason: accepted ? null : 'xvision_not_connected',
      });
      return;
    }

    case 'select_bottle': {
      const side = message.side;
      const ordinal = Number(message.ordinal);
      const requestId = message.request_id;
      const keys = Object.keys(message).sort().join(',');
      if (keys !== 'cmd,ordinal,request_id,side' ||
          !['left', 'right'].includes(side) ||
          !Number.isInteger(ordinal) || ordinal < 1 || ordinal > 32 ||
          typeof requestId !== 'string' || requestId.length < 1 || requestId.length > 128) {
        send(ws, { type: 'error', msg: '无效的视觉目标选择命令' });
        return;
      }
      if (!cameraBridge.send({ cmd: 'select_bottle', side, ordinal, request_id: requestId })) {
        send(ws, { type: 'error', msg: '本地视觉桥接未就绪' });
      }
      return;
    }

    case 'grasp_object':
    case 'start_vision_grasp':
      if (activeViewIsActive()) {
        send(ws, { type: 'error', msg: '主动观察会话进行中，抓取已闭锁' });
        return;
      }
      if (graspIsActive()) {
        send(ws, { type: 'error', msg: '抓取动作正在进行中' });
        return;
      }
      {
        const mode = message.mode === 'auto' ? 'auto' : 'step';
        const started = graspController.start(mode);
        if (!started.ok) {
          send(ws, {
            type: 'error',
            msg: `抓取已被视觉安全门禁拒绝: ${started.reason}`,
          });
          return;
        }
        activeView.onRobotEvent({ type: 'grasp_started' });
        send(ws, { type: 'grasp_command_result', action: 'start', ...started });
      }
      break;

    case 'advance_vision_grasp': {
      const advanced = graspController.advance();
      send(ws, { type: 'grasp_command_result', action: 'advance', ...advanced });
      break;
    }

    case 'cancel_vision_grasp': {
      const cancelled = graspController.cancel('operator_cancelled');
      send(ws, { type: 'grasp_command_result', action: 'cancel', ...cancelled });
      break;
    }

    case 'start_active_view':
    case 'confirm_active_view_step':
    case 'cancel_active_view': {
      const parsed = parseActiveViewBrowserCommand(message);
      if (!parsed.accepted) {
        send(ws, { type: 'active_view_command_result', accepted: false, reason: parsed.reason });
        return;
      }
      if (parsed.command === 'start') {
        const startGate = authorizeActiveViewStart({
          identityId: parsed.identityId,
          trustedTargets: visionStatus.trustedTargets(Date.now()),
          activeViewActive: activeViewIsActive(),
          graspActive: graspIsActive(),
          motionActive,
        });
        if (!startGate.approved) {
          send(ws, { type: 'active_view_command_result', accepted: false, reason: startGate.reason });
          return;
        }
        const started = activeView.begin({ sessionId: randomUUID(), identityId: parsed.identityId });
        send(ws, { type: 'active_view_command_result', action: 'start', ...started });
        return;
      }
      if (parsed.command === 'confirm') {
        const confirmed = activeView.confirm({
          sessionId: parsed.sessionId,
          proposalId: parsed.proposalId,
        });
        send(ws, {
          type: 'active_view_command_result',
          action: 'confirm',
          approved: confirmed.approved === true,
          reason: confirmed.reason,
          sessionId: parsed.sessionId,
          proposalId: parsed.proposalId,
          requestId: confirmed.requestId || null,
        });
        return;
      }
      const cancelled = activeView.cancel({ sessionId: parsed.sessionId });
      send(ws, { type: 'active_view_command_result', action: 'cancel', ...cancelled });
      return;
    }

    case 'estop_camera':
      activeView.onVisionEvent({ type: 'active_view_abort', reason: 'camera_stopped' });
      cameraBridge.shutdown();
      broadcast({ type: 'camera_status', d435_ready: false, calibration_loaded: false,
        error: 'E-STOP by user' });
      break;

    case 'camera_refresh':
      cameraBridge.send({ cmd: 'get_status' });
      break;

    default:
      send(ws, { type: 'error', msg: `未知命令: ${message.cmd}` });
  }
}

function getLocalIPs() {
  const addresses = [];
  for (const interfaces of Object.values(os.networkInterfaces())) {
    for (const iface of interfaces || []) {
      if (iface.family === 'IPv4' && !iface.internal) addresses.push(iface.address);
    }
  }
  return addresses;
}

server.listen(config.web.port, config.web.host, () => {
  console.log('ThirdHand Startouch Web Control');
  console.log(`Local:   http://localhost:${config.web.port}`);
  getLocalIPs().forEach(ip => console.log(`Network: http://${ip}:${config.web.port}`));
  console.log(`Robot:   Startouch SDK -> ${config.robot.canInterface}`);
  console.log(`SDK:     ${config.robot.sdkPath}`);
  if (config.robot.simulate) console.log('Mode:    simulator');
  if (config.camera && config.camera.enabled !== false) {
    console.log('Camera:  D435 bridge enabled');
    cameraBridge.start();
  }
  if (xvisionClient) {
    console.log(`Vision:  XVisio proxy -> ${config.xvision.baseUrl}`);
    xvisionClient.start();
  }
  // Lumos disabled until USB hardware issue resolved
  // startLumosStream();
  bridge.start();
});

const activeViewTimeoutTimer = setInterval(() => activeView.checkTimeout(), 250);
activeViewTimeoutTimer.unref();

function shutdown() {
  console.log('\n[shutdown] closing...');
  if (lumosChild) { lumosChild.kill('SIGTERM'); lumosChild = null; }
  clearInterval(activeViewTimeoutTimer);
  if (activeView.session) activeView.cancel({ sessionId: activeView.session.sessionId });
  if (graspIsActive()) graspController.cancel('server_shutdown');
  if (xvisionClient) xvisionClient.stop();
  cameraBridge.shutdown();
  bridge.shutdown();
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 1000).unref();
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
