'use strict';

const http = require('http');
const WebSocket = require('ws');

function getJson(path) {
  return new Promise((resolve, reject) => {
    http.get({ host: '127.0.0.1', port: 3000, path }, response => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', chunk => { body += chunk; });
      response.on('end', () => {
        try { resolve(JSON.parse(body)); } catch (error) { reject(error); }
      });
    }).on('error', reject);
  });
}

async function main() {
  const socket = new WebSocket('ws://127.0.0.1:3000/ws');
  const timeout = setTimeout(() => {
    console.error(JSON.stringify({ type: 'validation_timeout' }));
    socket.close();
    process.exitCode = 2;
  }, 30000);
  let accepted = false;
  let moved = false;
  let attempts = 0;
  const attempt = async () => {
    attempts += 1;
    const status = await getJson('/api/vision/status');
    const target = status.targets.find(item => Number.isSafeInteger(item.identityId) &&
      typeof item.graspPreviewId === 'string' && Array.isArray(item.graspPointM));
    if (!target || status.stale || status.sourceAgeMs > 250) {
      if (attempts < 20) return setTimeout(() => attempt().catch(console.error), 40);
      throw new Error(`no fresh validation target: stale=${status.stale} age=${status.sourceAgeMs}`);
    }
    console.log(JSON.stringify({ type: 'validation_target', attempt: attempts,
      identityId: target.identityId, previewId: target.graspPreviewId,
      graspPointM: target.graspPointM,
      expectedPregraspM: [target.graspPointM[0], target.graspPointM[1],
        Math.max(target.pregraspPointM[2], target.graspPointM[2] + 0.10)] }));
    socket.send(JSON.stringify({ cmd: 'validation_pregrasp',
      identity_id: target.identityId, preview_id: target.graspPreviewId }));
  };
  socket.on('open', () => attempt().catch(error => {
    console.error(error.stack || error.message);
    socket.close();
    process.exitCode = 1;
  }));
  socket.on('message', data => {
    const message = JSON.parse(data);
    if (message.type === 'validation_command_result') {
      console.log(JSON.stringify(message));
      accepted = message.accepted === true;
      if (!accepted) {
        if (message.reason === 'validation_preview_invalid' && attempts < 20) {
          setTimeout(() => attempt().catch(console.error), 40);
        } else {
          clearTimeout(timeout);
          socket.close();
          process.exitCode = 3;
        }
      }
    }
    if (message.type === 'robot_state' && accepted) {
      if (message.stateName !== 'IDLE') moved = true;
      if (moved || message.stateName !== 'IDLE') console.log(JSON.stringify({
        type: 'robot_state', stateName: message.stateName, tcpPos: message.tcpPos,
        tcpEuler: message.tcpEuler, gripperDistanceMm: message.gripperDistanceMm }));
      if (moved && message.stateName === 'IDLE') {
        clearTimeout(timeout);
        setTimeout(() => socket.close(), 200);
      }
    }
    if (message.type === 'error') console.log(JSON.stringify(message));
  });
  socket.on('error', error => {
    clearTimeout(timeout);
    console.error(error.message);
    process.exitCode = 1;
  });
}

main().catch(error => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
