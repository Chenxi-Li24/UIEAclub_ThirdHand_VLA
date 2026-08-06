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
const { VisionStatusStore } = require('./vision-status');
const {
  authorizeGrasp,
  trustedTargetFromDetection,
} = require('./grasp-authorization');
const lumosExternalUrl = process.env.LUMOS_STREAM_URL ||
  'http://127.0.0.1:3001/camera_lumos';

const app = express();
app.use(express.static(path.join(__dirname, '..', 'web')));
const server = http.createServer(app);
const wss = new WebSocketServer({ server, path: '/ws' });
const clients = new Set();
const bridge = new StartouchBridge(config.robot);
const cameraBridge = new CameraBridge(config.camera || {});
const visionStatus = new VisionStatusStore({ staleAfterMs: 2000, maxTargets: 256 });
let latestJointsDeg = null;
let latestTcpEuler = null;    // [rad] for camera bridge
let latestTcpPos = null;      // [m] for camera bridge
let stateReady = false;
let motionActive = false;
let connectPending = false;
let latestVisionTargets = new Map();

// Grasp state machine
let graspState = null;  // { tid, bx, by, phase, ... }

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

bridge.on('connection', message => {
  latestJointsDeg = null;
  stateReady = false;
  motionActive = false;
  connectPending = false;
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

app.get('/api/vision/status', (_req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  res.json(visionStatus.snapshot(Date.now()));
});

// ── Camera bridge events ────────────────────────────────────
cameraBridge.on('detection_result', message => {
  visionStatus.updateTargets(message);
  latestVisionTargets = new Map(
    (message.objects || []).map(target => {
      const trusted = trustedTargetFromDetection(target);
      return [trusted.id, trusted];
    })
  );
  broadcast(message);
});

cameraBridge.on('camera_status', message => {
  visionStatus.updateCamera(message);
  broadcast(message);
});

cameraBridge.on('camera_error', message => {
  visionStatus.updateCamera(message);
  broadcast({ type: 'camera_error', msg: message.message });
});

cameraBridge.on('vision_status', message => {
  visionStatus.updateStatus(message);
  broadcast(message);
});

cameraBridge.on('vision_error', message => {
  visionStatus.updateStatus(message);
  broadcast(message);
});

cameraBridge.on('log', message => {
  console.warn(`[Camera] ${message.message}`);
});

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
  broadcast({ type: 'motion_state', stateName: message.state, ts: message.ts });
});

bridge.on('command_accepted', message => {
  broadcast({ ...message, type: 'command_status', status: 'accepted' });
});

bridge.on('command_complete', message => {
  broadcast({ ...message, type: 'command_status', status: 'complete' });
});

bridge.on('error', message => {
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
      if (!bridge.connected) {
        send(ws, { type: 'error', msg: 'Startouch SDK 尚未连接' });
        return;
      }
      bridge.send({ cmd: 'gripper', position: message.position });
      break;

    case 'software_stop':
    case 'estop':
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

    case 'grasp_object':
      if (graspState) {
        send(ws, { type: 'error', msg: '抓取动作正在进行中' });
        return;
      }
      {
        const targetId = Number(message.id);
        const authorization = authorizeGrasp({
          executionEnabled: config.visionSafety.robotExecutionEnabled,
          bridgeConnected: bridge.connected,
          armMotionActive: motionActive,
          target: latestVisionTargets.get(targetId),
          nowMs: Date.now(),
        });
        if (!authorization.approved) {
          send(ws, {
            type: 'error',
            msg: `抓取已被视觉安全门禁拒绝: ${authorization.reason}`,
          });
          return;
        }
        startGrasp(targetId, authorization.positionM);
      }
      break;

    case 'estop_camera':
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

// ── Grasp state machine ─────────────────────────────────────
function startGrasp(tid, positionM) {
  const [bx, by, bz] = positionM;
  const hoverZ = Math.max(bz + 0.10, 0.15);
  const graspZ = Math.max(bz + 0.01, 0.03);
  const liftZ = Math.max(bz + 0.15, 0.20);

  if (!latestTcpEuler) {
    broadcast({ type: 'error', msg: 'No arm orientation data available' });
    return;
  }

  graspState = {
    tid,
    bx, by, bz,
    hoverZ, graspZ, liftZ,
    euler: [...latestTcpEuler],
    phase: 'hover',
  };

  broadcast({ type: 'grasp_status', tid, status: 'hover',
    msg: `Moving to hover (${bx.toFixed(3)}, ${by.toFixed(3)}, ${hoverZ.toFixed(3)})` });

  bridge.send({
    cmd: 'move_l',
    position: [bx, by, hoverZ],
    euler: graspState.euler,
    time_sec: 2.5,
    request_id: `grasp_${tid}_hover`,
  });
}

function advanceGrasp() {
  if (!graspState) return;

  switch (graspState.phase) {
    case 'hover':
      graspState.phase = 'descend';
      broadcast({ type: 'grasp_status', tid: graspState.tid, status: 'descend',
        msg: `Descending to grasp Z=${graspState.graspZ.toFixed(3)}` });
      bridge.send({
        cmd: 'move_l',
        position: [graspState.bx, graspState.by, graspState.graspZ],
        euler: graspState.euler,
        time_sec: 1.5,
        request_id: `grasp_${graspState.tid}_descend`,
      });
      break;

    case 'descend':
      graspState.phase = 'close';
      broadcast({ type: 'grasp_status', tid: graspState.tid, status: 'close',
        msg: 'Closing gripper' });
      bridge.send({ cmd: 'gripper', position: 0.15 });
      break;

    case 'close':
      graspState.phase = 'lift';
      broadcast({ type: 'grasp_status', tid: graspState.tid, status: 'lift',
        msg: `Lifting to Z=${graspState.liftZ.toFixed(3)}` });
      bridge.send({
        cmd: 'move_l',
        position: [graspState.bx, graspState.by, graspState.liftZ],
        euler: graspState.euler,
        time_sec: 2.0,
        request_id: `grasp_${graspState.tid}_lift`,
      });
      break;

    case 'lift':
      graspState.phase = 'home';
      broadcast({ type: 'grasp_status', tid: graspState.tid, status: 'home',
        msg: 'Going home' });
      bridge.send({ cmd: 'go_home' });
      break;

    case 'home':
      broadcast({ type: 'grasp_status', tid: graspState.tid, status: 'open',
        msg: 'Opening gripper' });
      bridge.send({ cmd: 'gripper', position: 1.0 });
      graspState.phase = 'done';
      break;

    case 'done':
      broadcast({ type: 'grasp_status', tid: graspState.tid, status: 'complete',
        msg: 'Grasp complete!' });
      graspState = null;
      break;

    default:
      graspState = null;
  }
}

// Hook into command_complete to advance grasp sequence
bridge.on('command_complete', message => {
  if (graspState && message.command && !message.command.startsWith('gripper')) {
    advanceGrasp();
  }
});

// Gripper completion must also advance
bridge.on('command_complete', message => {
  if (graspState && message.command === 'gripper') {
    // Small delay to let gripper settle
    setTimeout(() => advanceGrasp(), 400);
  }
});

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
  // Lumos disabled until USB hardware issue resolved
  // startLumosStream();
  bridge.start();
});

function shutdown() {
  console.log('\n[shutdown] closing...');
  if (lumosChild) { lumosChild.kill('SIGTERM'); lumosChild = null; }
  cameraBridge.shutdown();
  bridge.shutdown();
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 1000).unref();
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
