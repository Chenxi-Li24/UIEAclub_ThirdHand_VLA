'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');

const { VisionServiceClient } = require(
  '../../../src/thirdhand_va/action/adapters/vision_service_client'
);

class FakeWebSocket extends EventEmitter {
  static OPEN = 1;

  constructor(url) {
    super();
    this.url = url;
    this.readyState = FakeWebSocket.OPEN;
    this.sent = [];
    FakeWebSocket.last = this;
  }

  send(payload) {
    this.sent.push(JSON.parse(payload));
  }

  close() {
    this.readyState = 3;
    this.emit('close');
  }
}

test('vision service adapter reuses 3100 events and translates skill commands', () => {
  const client = new VisionServiceClient({
    WebSocketImpl: FakeWebSocket,
    wsUrl: 'ws://127.0.0.1:3100/ws',
    httpUrl: 'http://127.0.0.1:3100',
  });
  const detections = [];
  client.on('detection_result', event => detections.push(event));

  assert.equal(client.start(), true);
  const socket = FakeWebSocket.last;
  socket.emit('open');
  socket.emit('message', Buffer.from(JSON.stringify({
    type: 'runtime_status',
    camera: { status: 'ready' },
    inference: { status: 'ready' },
  })));
  socket.emit('message', Buffer.from(JSON.stringify({
    type: 'detection_result',
    frame_id: 8,
    targets: [{ stable_id: 4 }],
  })));

  assert.equal(client.getInfo().ready, true);
  assert.equal(client.getInfo().source, 'vision-service');
  assert.equal(detections.length, 1);
  assert.equal(client.send({
    type: 'select_bottle', stable_id: 4, request_id: 'pick-4',
  }), true);
  assert.deepEqual(socket.sent.at(-1), {
    type: 'select_target', stableId: 4, requestId: 'pick-4',
  });
  assert.equal(client.send({
    type: 'release_bottle', request_id: 'pick-4',
  }), true);
  assert.deepEqual(socket.sent.at(-1), {
    type: 'release_target', requestId: 'pick-4',
  });

  client.shutdown();
  assert.equal(client.connected, false);
});

test('vision service adapter reconnects after the 3100 socket closes', async () => {
  const client = new VisionServiceClient({
    WebSocketImpl: FakeWebSocket,
    reconnectDelayMs: 10,
  });

  assert.equal(client.start(), true);
  const first = FakeWebSocket.last;
  first.emit('open');
  first.close();

  await new Promise(resolve => setTimeout(resolve, 30));
  assert.notEqual(FakeWebSocket.last, first);
  assert.equal(FakeWebSocket.last.url, 'ws://127.0.0.1:3100/ws');

  client.shutdown();
});
