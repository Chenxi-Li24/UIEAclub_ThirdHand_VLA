'use strict';

const assert = require('assert/strict');
const { EventEmitter } = require('events');
const { sendSoftwareStop } = require(
  '../../../src/thirdhand_va/action/safety/software_stop'
);

class FakeWebSocket extends EventEmitter {
  constructor(url) {
    super();
    this.url = url;
    this.messages = [];
    FakeWebSocket.latest = this;
    process.nextTick(() => this.emit('open'));
  }

  send(raw) {
    const message = JSON.parse(raw);
    this.messages.push(message);
    if (message.cmd === 'software_stop') {
      process.nextTick(() => this.emit(
        'message',
        Buffer.from(JSON.stringify({ type: 'software_stop' }))
      ));
    }
  }

  close() {}
}

(async () => {
  const result = await sendSoftwareStop({
    WebSocketImpl: FakeWebSocket,
    wsUrl: 'ws://127.0.0.1:3000/ws',
    timeoutMs: 100,
    stopDelayMs: 0,
  });

  assert.equal(result.type, 'software_stop');
  assert.deepEqual(FakeWebSocket.latest.messages, [
    { cmd: 'software_stop' },
  ]);
  console.log('PASS software stop is reusable and has no process side effects');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
