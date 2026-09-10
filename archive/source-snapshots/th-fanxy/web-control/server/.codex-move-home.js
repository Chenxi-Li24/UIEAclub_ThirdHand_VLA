const WebSocket = require('ws');
const socket = new WebSocket('ws://127.0.0.1:3000/ws');
let sawMotion = false;
const deadline = setTimeout(() => {
  console.error(JSON.stringify({ type: 'monitor_timeout' }));
  socket.close();
  process.exitCode = 2;
}, 30000);

socket.on('open', () => {
  console.log(JSON.stringify({ type: 'home_command_sent' }));
  socket.send(JSON.stringify({ cmd: 'preset', name: 'home' }));
});

socket.on('message', buffer => {
  const message = JSON.parse(buffer);
  if (message.type === 'robot_state') {
    if (message.stateName !== 'IDLE') sawMotion = true;
    if (sawMotion || message.stateName !== 'IDLE') {
      console.log(JSON.stringify({
        type: message.type,
        stateName: message.stateName,
        joints: message.joints,
        tcpPos: message.tcpPos,
        tcpEuler: message.tcpEuler,
      }));
    }
  }
  if (['command_accepted', 'command_complete', 'motion_complete', 'error',
    'software_stop', 'connection'].includes(message.type)) {
    console.log(JSON.stringify(message));
  }
  if (message.type === 'error' ||
      (message.type === 'command_complete' && message.command === 'move_joint')) {
    clearTimeout(deadline);
    setTimeout(() => socket.close(), 200);
  }
});

socket.on('error', error => {
  console.error(JSON.stringify({ type: 'ws_error', error: error.message }));
  clearTimeout(deadline);
  process.exitCode = 1;
});
