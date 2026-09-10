#!/usr/bin/env node
'use strict';

const fs = require('fs');
const { createRequire } = require('module');
const path = require('path');
const { URL } = require('url');
const serverRequire = createRequire(path.resolve(__dirname, '../server/package.json'));
const WebSocket = serverRequire('ws');

const MAX_FILE_BYTES = 8 * 1024 * 1024;

function parseArguments(argv) {
  const result = { allowRemote: false };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === '--allow-remote') {
      result.allowRemote = true;
      continue;
    }
    if (!['--name', '--server', '--output'].includes(argument) || index + 1 >= argv.length) {
      throw new TypeError(`unknown or incomplete argument: ${argument}`);
    }
    result[argument.slice(2)] = argv[index + 1];
    index += 1;
  }
  if (!result.name || !result.server || !result.output) {
    throw new TypeError('--name, --server, and --output are required');
  }
  if (result.name.length > 128 || !/^[A-Za-z0-9_.-]+$/.test(result.name)) {
    throw new TypeError('--name must be a bounded identifier');
  }
  const server = new URL(result.server);
  if (!['ws:', 'wss:'].includes(server.protocol)) {
    throw new TypeError('--server must be a WebSocket URL');
  }
  const loopback = ['127.0.0.1', '::1', 'localhost'].includes(server.hostname);
  if (!loopback && !result.allowRemote) {
    throw new TypeError('non-loopback server requires --allow-remote');
  }
  result.server = server.toString();
  return result;
}

function finiteVector(value, length, name) {
  if (!Array.isArray(value) || value.length !== length) {
    throw new TypeError(`${name} must contain ${length} values`);
  }
  const result = value.map(item => {
    if (typeof item !== 'number' || !Number.isFinite(item)) {
      throw new TypeError(`${name} must contain finite numbers`);
    }
    return item;
  });
  return result;
}

function captureFromRobotState(message, name, serverUrl) {
  if (!message || message.type !== 'robot_state') {
    throw new TypeError('expected one robot_state response');
  }
  const joints = finiteVector(message.joints, 6, 'joints');
  const velocities = finiteVector(message.velocities, 6, 'velocities');
  const positionMm = finiteVector(message.tcpPos, 3, 'TCP position');
  const eulerDeg = finiteVector(message.tcpEuler, 3, 'TCP Euler');
  if (joints.every(value => value === 0) || positionMm.every(value => value === 0)) {
    throw new TypeError('all-zero transient robot state is forbidden');
  }
  if (velocities.some(value => Math.abs(value) > 0.5)) {
    throw new TypeError('robot is not stationary');
  }
  const state = String(message.stateName || '').toLowerCase();
  if (!['idle', 'stationary', 'standby', 'ready'].includes(state)) {
    throw new TypeError('robot stability state is missing');
  }
  return {
    name,
    joints_deg: joints,
    tcp_position_m: positionMm.map(value => value / 1000),
    tcp_euler_rad: eulerDeg.map(value => value * Math.PI / 180),
    captured_at: new Date().toISOString(),
    server_url: serverUrl,
  };
}

function writeCaptureAtomic(outputPath, capture) {
  const destination = path.resolve(outputPath);
  let manifest = { schema_version: 1, captures: [] };
  if (fs.existsSync(destination)) {
    const stat = fs.lstatSync(destination);
    if (stat.isSymbolicLink() || !stat.isFile() || stat.size > MAX_FILE_BYTES) {
      throw new TypeError('capture output is unsafe or oversized');
    }
    manifest = JSON.parse(fs.readFileSync(destination, 'utf8'));
    if (!manifest || manifest.schema_version !== 1 || !Array.isArray(manifest.captures)) {
      throw new TypeError('existing capture manifest is invalid');
    }
  }
  if (manifest.captures.some(item => item && item.name === capture.name)) {
    throw new TypeError(`duplicate capture name: ${capture.name}`);
  }
  if (manifest.captures.length >= 64) {
    throw new TypeError('capture manifest cannot exceed 64 poses');
  }
  const updated = { schema_version: 1, captures: [...manifest.captures, capture] };
  const encoded = `${JSON.stringify(updated, null, 2)}\n`;
  if (Buffer.byteLength(encoded) > MAX_FILE_BYTES) {
    throw new TypeError('capture manifest exceeds 8 MiB');
  }
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  const temporary = `${destination}.${process.pid}.tmp`;
  try {
    fs.writeFileSync(temporary, encoded, { encoding: 'utf8', mode: 0o600, flag: 'wx' });
    fs.renameSync(temporary, destination);
  } finally {
    try { fs.unlinkSync(temporary); } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
  }
}

async function collectPose(options) {
  await new Promise((resolve, reject) => {
    const socket = new WebSocket(options.server, { maxPayload: 1024 * 1024 });
    const timeout = setTimeout(() => {
      socket.terminate();
      reject(new Error('timed out waiting for robot state'));
    }, 5000);
    let completed = false;
    socket.once('open', () => socket.send(JSON.stringify({ cmd: 'status' })));
    socket.on('message', payload => {
      if (completed) return;
      let message;
      try { message = JSON.parse(payload.toString()); } catch (_error) { return; }
      if (!message || message.type !== 'robot_state') return;
      completed = true;
      clearTimeout(timeout);
      try {
        const capture = captureFromRobotState(message, options.name, options.server);
        writeCaptureAtomic(options.output, capture);
        socket.close();
        resolve();
      } catch (error) {
        socket.terminate();
        reject(error);
      }
    });
    socket.once('error', error => {
      if (!completed) {
        clearTimeout(timeout);
        reject(error);
      }
    });
  });
}

if (require.main === module) {
  collectPose(parseArguments(process.argv.slice(2))).catch(error => {
    console.error(error.message);
    process.exitCode = 1;
  });
}

module.exports = { captureFromRobotState, collectPose, parseArguments, writeCaptureAtomic };
