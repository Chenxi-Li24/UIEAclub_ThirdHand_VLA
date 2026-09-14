const WebSocket = require('ws');
const socket = new WebSocket('ws://127.0.0.1:3000/ws');
socket.on('open', () => {
  console.log(JSON.stringify({ type: 'ws_open' }));
  socket.send(JSON.stringify({ cmd: process.argv[2] || 'status' }));
  setInterval(() => socket.send(JSON.stringify({ cmd: 'status' })), 500).unref();
});
socket.on('message', buffer => {
  const message = JSON.parse(buffer);
  if (['welcome', 'system_info', 'robot_state', 'connection', 'robot_status',
    'grasp_status', 'error', 'software_stop'].includes(message.type)) {
    console.log(JSON.stringify(message));
  }
  if (message.type === 'robot_state') setTimeout(() => socket.close(), 100);
});
socket.on('error', error => console.error(JSON.stringify({ type: 'ws_error', error: error.message })));
socket.on('close', () => console.log(JSON.stringify({ type: 'ws_close' })));
setTimeout(() => socket.close(), 5000);
