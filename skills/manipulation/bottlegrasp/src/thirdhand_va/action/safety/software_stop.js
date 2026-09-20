'use strict';

/** Send one low-level software_stop command without owning process exit behavior. */
function sendSoftwareStop({
  WebSocketImpl,
  wsUrl,
  timeoutMs = 5000,
}) {
  if (typeof WebSocketImpl !== 'function') {
    return Promise.reject(new TypeError('WebSocketImpl must be a constructor'));
  }
  if (typeof wsUrl !== 'string' || wsUrl.length === 0) {
    return Promise.reject(new TypeError('wsUrl must be a non-empty string'));
  }
  return new Promise((resolve, reject) => {
    const socket = new WebSocketImpl(wsUrl);
    let finished = false;
    const timer = setTimeout(() => finish(new Error('software_stop_timeout')), timeoutMs);

    function finish(error, message = null) {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      try { socket.close(); } catch {}
      if (error) reject(error);
      else resolve(message);
    }

    socket.on('open', () => {
      socket.send(JSON.stringify({ cmd: 'software_stop' }));
    });
    socket.on('message', raw => {
      let message;
      try {
        message = JSON.parse(raw.toString());
      } catch (error) {
        finish(error);
        return;
      }
      if (message.type === 'software_stop' || message.type === 'connection' ||
          (message.type === 'command_status' && message.status === 'complete')) {
        finish(null, message);
      }
    });
    socket.on('error', error => finish(error));
    socket.on('close', () => {
      if (!finished) finish(new Error('software_stop_socket_closed'));
    });
  });
}

module.exports = { sendSoftwareStop };
