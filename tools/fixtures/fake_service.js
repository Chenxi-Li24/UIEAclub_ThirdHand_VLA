const fs = require('node:fs');

const readyFile = process.env.THIRDHAND_READY_FILE;
if (!readyFile) throw new Error('THIRDHAND_READY_FILE is required');
fs.writeFileSync(readyFile, `${JSON.stringify({ ready: true, serviceId: process.env.THIRDHAND_SERVICE_ID })}\n`);

function stop() {
  try { fs.unlinkSync(readyFile); } catch (error) { if (error.code !== 'ENOENT') throw error; }
  process.exit(0);
}

process.on('SIGTERM', stop);
process.on('SIGINT', stop);
setInterval(() => {}, 60_000);
