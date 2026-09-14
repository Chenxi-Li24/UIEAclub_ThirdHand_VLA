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
  const status = await getJson('/api/vision/status');
  const target = status.targets.find(item => Number.isSafeInteger(item.identityId) &&
    typeof item.graspPreviewId === 'string' && Array.isArray(item.graspPointM));
  if (!target || status.stale || status.sourceAgeMs > 250) {
    throw new Error(`no fresh validation target: stale=${status.stale} age=${status.sourceAgeMs}`);
  }
  console.log(JSON.stringify({ type: 'frozen_validation_target',
    identityId: target.identityId, previewId: target.graspPreviewId,
    graspPointM: target.graspPointM, pregraspPointM: target.pregraspPointM }));

  const socket = new WebSocket('ws://127.0.0.1:3000/ws');
  const timeout = setTimeout(() => {
    console.error(JSON.stringify({ type: 'validation_timeout' }));
    socket.close();
    process.exitCode = 2;
  }, 45000);
  socket.on('open', () => socket.send(JSON.stringify({
    cmd: 'validation_grasp_pause', identity_id: target.identityId,
    preview_id: target.graspPreviewId,
  })));
  socket.on('message', data => {
    const message = JSON.parse(data);
    if (['validation_grasp_pause_result', 'grasp_status', 'robot_state', 'error'].includes(message.type)) {
      console.log(JSON.stringify(message));
    }
    if (message.type === 'validation_grasp_pause_result' && message.accepted !== true) {
      clearTimeout(timeout);
      socket.close();
      process.exitCode = 3;
    }
    if (message.type === 'grasp_status' && message.phase === 'paused_before_close') {
      clearTimeout(timeout);
      console.log(JSON.stringify({ type: 'validation_complete',
        result: 'paused_before_close', gripper_was_not_closed: true }));
      setTimeout(() => socket.close(), 200);
    }
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
