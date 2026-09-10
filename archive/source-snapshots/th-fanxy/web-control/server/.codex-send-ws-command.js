const WebSocket = require('ws');
const command = JSON.parse(process.argv[2]);
const socket = new WebSocket('ws://127.0.0.1:3000/ws');
const timeout = setTimeout(() => {
  console.error('command_send_timeout');
  process.exitCode = 2;
  socket.close();
}, 3000);
socket.on('open', () => {
  socket.send(JSON.stringify(command), error => {
    clearTimeout(timeout);
    if (error) {
      console.error(error.message);
      process.exitCode = 1;
    } else {
      console.log(JSON.stringify({ sent: true, command }));
    }
    setTimeout(() => socket.close(), 200);
  });
});
socket.on('error', error => {
  clearTimeout(timeout);
  console.error(error.message);
  process.exitCode = 1;
});
