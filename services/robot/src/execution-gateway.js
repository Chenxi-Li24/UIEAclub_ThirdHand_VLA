'use strict';

const { WebSocket } = require('ws');

function sendJson(socket, payload) {
  if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload));
}

function validStopControl(message) {
  return message && typeof message === 'object' && !Array.isArray(message)
    && Object.keys(message).length === 4
    && message.schema === 'thirdhand.execution-control.v1'
    && message.type === 'execution.stop'
    && typeof message.sessionId === 'string' && message.sessionId.length > 0
    && message.reason === 'operator_stop';
}

class ExecutionGateway {
  constructor(controller) {
    this.controller = controller;
    this.sockets = new Set();
  }

  attach(socket) {
    this.sockets.add(socket);
    const primitiveIds = new Set();
    socket.on('message', data => {
      let primitive;
      try {
        primitive = JSON.parse(data.toString('utf8'));
      } catch {
        sendJson(socket, { type: 'execution.status', status: 'failed', code: 'invalid_json', message: 'Invalid JSON message' });
        return;
      }
      if (primitive?.schema === 'thirdhand.execution-control.v1') {
        if (!validStopControl(primitive)) {
          sendJson(socket, {
            type: 'execution.status', status: 'failed', code: 'invalid_execution_control',
          });
          return;
        }
        this.controller.interruptSession(primitive.sessionId, primitive.reason);
        return;
      }
      if (typeof primitive?.primitiveId === 'string') primitiveIds.add(primitive.primitiveId);
      this.controller.executePrimitive(primitive, reply => {
        if (['completed', 'failed', 'uncertain', 'interrupted'].includes(reply.status)) {
          primitiveIds.delete(reply.primitiveId || primitive?.primitiveId);
        }
        sendJson(socket, reply);
      });
    });
    socket.on('close', () => {
      for (const primitiveId of primitiveIds) {
        this.controller.interruptPrimitive(primitiveId, 'execution_connection_closed');
      }
      primitiveIds.clear();
      this.sockets.delete(socket);
    });
  }

  close() {
    for (const socket of this.sockets) socket.terminate();
    this.sockets.clear();
  }
}

module.exports = { ExecutionGateway, sendJson, validStopControl };
