'use strict';

const { WebSocket } = require('ws');

const ROBOT_COMMANDS = new Set([
  'connect',
  'disconnect',
  'status',
  'servo',
  'preset',
  'gripper',
  'software_stop',
  'estop',
  'ping',
]);

function sendJson(socket, message) {
  if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
}

class RobotProxy {
  constructor(robotWsUrl) {
    this.robotWsUrl = robotWsUrl;
    this.sessions = new Set();
  }

  attach(browser) {
    const upstream = new WebSocket(this.robotWsUrl);
    const session = { browser, upstream, queue: [] };
    this.sessions.add(session);

    upstream.on('open', () => {
      for (const payload of session.queue.splice(0)) upstream.send(payload);
    });
    upstream.on('message', (data, isBinary) => {
      if (browser.readyState === WebSocket.OPEN) browser.send(data, { binary: isBinary });
    });
    upstream.on('error', error => {
      sendJson(browser, {
        type: 'error',
        code: 'robot_service_unavailable',
        msg: `Robot Service unavailable: ${error.message}`,
      });
    });
    upstream.on('close', () => {
      if (browser.readyState === WebSocket.OPEN) {
        sendJson(browser, {
          type: 'connection',
          connected: false,
          reason: 'robot_service_disconnected',
        });
      }
    });

    browser.on('message', data => {
      let message;
      try {
        message = JSON.parse(data.toString('utf8'));
      } catch {
        sendJson(browser, {
          type: 'error',
          code: 'invalid_json',
          msg: 'Invalid JSON message',
        });
        return;
      }
      if (!message || !ROBOT_COMMANDS.has(message.cmd)) {
        sendJson(browser, {
          type: 'error',
          code: 'service_unavailable',
          msg: `Command ${message?.cmd || '<missing>'} has not migrated to an online service`,
        });
        return;
      }
      const payload = JSON.stringify(message);
      if (upstream.readyState === WebSocket.OPEN) upstream.send(payload);
      else if (upstream.readyState === WebSocket.CONNECTING) session.queue.push(payload);
      else {
        sendJson(browser, {
          type: 'error',
          code: 'robot_service_unavailable',
          msg: 'Robot Service is disconnected',
        });
      }
    });

    browser.on('close', () => {
      this.sessions.delete(session);
      if (upstream.readyState < WebSocket.CLOSING) upstream.close();
    });
  }

  close() {
    for (const { browser, upstream } of this.sessions) {
      browser.terminate();
      upstream.terminate();
    }
    this.sessions.clear();
  }
}

module.exports = { ROBOT_COMMANDS, RobotProxy };
