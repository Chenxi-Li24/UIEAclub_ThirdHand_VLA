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

const app = express();
app.use(express.static(path.join(__dirname, '..', 'web')));
const server = http.createServer(app);
const wss = new WebSocketServer({ server, path: '/ws' });
const clients = new Set();
const bridge = new StartouchBridge(config.robot);
let latestJointsDeg = null;
let stateReady = false;
let motionActive = false;
let connectPending = false;

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

bridge.on('robot_state', message => {
  const jointsDeg = radiansToDegrees(message.joints_rad);
  if (jointsDeg.length !== 6 || !jointsDeg.every(Number.isFinite)) {
    broadcast({ type: 'error', msg: 'SDK 返回了无效关节状态，已忽略' });
    return;
  }
  latestJointsDeg = jointsDeg;
  stateReady = true;
  broadcast({
    type: 'robot_state',
    joints: latestJointsDeg,
    velocities: radiansToDegrees(message.velocities_rad_s),
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
  bridge.start();
});

function shutdown() {
  console.log('\n[shutdown] closing...');
  bridge.shutdown();
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 1000).unref();
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
