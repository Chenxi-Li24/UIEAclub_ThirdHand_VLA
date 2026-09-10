'use strict';

const WebSocket = require('ws');
const delta = JSON.parse(process.argv[2]);
const socket = new WebSocket('ws://127.0.0.1:3000/ws');
const timeout = setTimeout(() => {
  console.error(JSON.stringify({ type: 'adjust_timeout' }));
  socket.close();
  process.exitCode = 2;
}, 15000);

socket.on('open', () => socket.send(JSON.stringify({
  cmd: 'adjust_validation_grasp', dx_m: delta[0], dy_m: delta[1], dz_m: delta[2],
})));
socket.on('message', data => {
  const message = JSON.parse(data);
  if (['adjust_validation_grasp_result', 'grasp_status', 'robot_state', 'error'].includes(message.type)) {
    console.log(JSON.stringify(message));
  }
  if (message.type === 'adjust_validation_grasp_result' && message.accepted !== true) {
    clearTimeout(timeout);
    socket.close();
    process.exitCode = 3;
  }
  if (message.type === 'grasp_status' && message.phase === 'paused_before_close') {
    clearTimeout(timeout);
    setTimeout(() => socket.close(), 200);
  }
});
socket.on('error', error => {
  clearTimeout(timeout);
  console.error(error.message);
  process.exitCode = 1;
});
