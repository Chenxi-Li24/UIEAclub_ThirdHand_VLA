'use strict';

const http = require('http');
const WebSocket = require('ws');

function getStatus() {
  return new Promise((resolve, reject) => {
    http.get('http://127.0.0.1:3000/api/vision/status', response => {
      let body = '';
      response.on('data', chunk => { body += chunk; });
      response.on('end', () => {
        try { resolve(JSON.parse(body)); } catch (error) { reject(error); }
      });
    }).on('error', reject);
  });
}

async function main() {
  const socket = new WebSocket('ws://127.0.0.1:3000/ws');
  let attempts = 0;
  let accepted = false;
  const timeout = setTimeout(() => {
    console.error(JSON.stringify({ type: 'grasp_monitor_timeout' }));
    socket.close();
    process.exitCode = 2;
  }, 90000);

  const attempt = async () => {
    attempts += 1;
    const status = await getStatus();
    const target = status.targets.find(item => Number.isSafeInteger(item.identityId) &&
      typeof item.graspPreviewId === 'string' && Array.isArray(item.graspPointM));
    if (!target || status.stale || status.sourceAgeMs > 250) {
      if (attempts < 300) return setTimeout(() => attempt().catch(console.error), 100);
      throw new Error('no fresh grasp target');
    }
    console.log(JSON.stringify({ type: 'frozen_grasp_candidate', attempt: attempts,
      identityId: target.identityId, previewId: target.graspPreviewId,
      rawGraspPointM: target.graspPointM,
      correctedGraspPointM: [target.graspPointM[0], target.graspPointM[1] + 0.017,
        target.graspPointM[2]] }));
    socket.send(JSON.stringify({ cmd: 'grasp_object', identity_id: target.identityId,
      preview_id: target.graspPreviewId }));
  };

  socket.on('open', () => attempt().catch(error => {
    console.error(error.stack || error.message);
    process.exitCode = 1;
    socket.close();
  }));
  socket.on('message', data => {
    const message = JSON.parse(data);
    if (message.type === 'grasp_command_result') {
      console.log(JSON.stringify(message));
      accepted = message.accepted === true;
      if (!accepted && ['preview_mismatch', 'target_stale'].includes(message.reason) &&
          attempts < 300) {
        return setTimeout(() => attempt().catch(console.error), 100);
      }
      if (!accepted) {
        clearTimeout(timeout);
        socket.close();
        process.exitCode = 3;
      }
    }
    if (message.type === 'grasp_status' && accepted) {
      console.log(JSON.stringify(message));
      if (message.active === false && ['complete', 'aborted'].includes(message.phase)) {
        clearTimeout(timeout);
        setTimeout(() => socket.close(), 300);
        if (message.phase !== 'complete') process.exitCode = 4;
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
