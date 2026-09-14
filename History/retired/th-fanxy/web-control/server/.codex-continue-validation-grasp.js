'use strict';

const WebSocket = require('ws');
const socket = new WebSocket('ws://127.0.0.1:3000/ws');
const timeout = setTimeout(() => {
  console.error(JSON.stringify({ type: 'continue_timeout' }));
  socket.close();
  process.exitCode = 2;
}, 75000);

socket.on('open', () => socket.send(JSON.stringify({ cmd: 'continue_validation_grasp' })));
socket.on('message', data => {
  const message = JSON.parse(data);
  if (['continue_validation_grasp_result', 'grasp_status', 'robot_state', 'error'].includes(message.type)) {
    console.log(JSON.stringify(message));
  }
  if (message.type === 'continue_validation_grasp_result' && message.accepted !== true) {
    clearTimeout(timeout);
    socket.close();
    process.exitCode = 3;
  }
  if (message.type === 'grasp_status' && message.active === false &&
      ['complete', 'aborted'].includes(message.phase)) {
    clearTimeout(timeout);
    setTimeout(() => socket.close(), 200);
  }
});
socket.on('error', error => {
  clearTimeout(timeout);
  console.error(error.message);
  process.exitCode = 1;
});
