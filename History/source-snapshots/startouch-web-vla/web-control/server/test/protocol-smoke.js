'use strict';

const { WebSocketServer, WebSocket } = require('ws');

const HOST = '127.0.0.1';
const PORT = Number(process.env.VOICE_TEST_PORT || 3001);
const PATH = '/v1/voice';
const PROTOCOL = 'thirdhand.voice.v1';
const AUDIO_SESSION_ID = 'smoke-audio-v1';
const TEXT_SESSION_ID = 'smoke-text-v1';
const EXPECTED_AUDIO_EVENTS = [
  'session.ready',
  'transcript.partial',
  'session.processing',
  'transcript.final',
  'assistant.response',
  'intent.candidate',
  'session.completed'
];
const EXPECTED_TEXT_EVENTS = [
  'session.processing',
  'assistant.response',
  'intent.candidate',
  'session.completed'
];

let server;
let client;
let finished = false;
const events = [];
let phase = 'audio';
const timeout = setTimeout(() => finish(new Error('Timed out after 5 seconds.')), 5000);

function finish(error) {
  if (finished) return;
  finished = true;
  clearTimeout(timeout);
  try { client?.close(); } catch {}
  try { server?.close(); } catch {}

  if (error) {
    console.error(`FAIL ${error.message}`);
    process.exitCode = 1;
  }
}

function message(type, payload = {}, sessionId = AUDIO_SESSION_ID, replyTo = null) {
  return JSON.stringify({
    v: 1,
    type,
    messageId: `${type}-1`,
    replyTo,
    sessionId,
    ts: Date.now(),
    payload
  });
}

server = new WebSocketServer({
    host: HOST,
    port: PORT,
    path: PATH,
    handleProtocols: protocols => protocols.has(PROTOCOL) ? PROTOCOL : false
  });

  server.on('error', finish);
  server.on('connection', socket => {
    let audioBytes = 0;

    socket.on('message', (data, isBinary) => {
      if (isBinary) {
        if (data.subarray(0, 4).toString('ascii') !== 'THV1') {
          finish(new Error('Invalid binary audio header.'));
          return;
        }
        audioBytes += data.length - 12;
        return;
      }

      const incoming = JSON.parse(data.toString());
      if (incoming.type === 'session.start') {
        audioBytes = 0;
        socket.send(message('session.ready', {}, incoming.sessionId));
        socket.send(message('transcript.partial', { text: '打开', revision: 1 }, incoming.sessionId));
      }
      if (incoming.type === 'session.stop') {
        if (audioBytes !== 3200) {
          finish(new Error(`Expected 3200 audio bytes, received ${audioBytes}.`));
          return;
        }
        socket.send(message('session.processing', { inputMode: 'audio' }, incoming.sessionId));
        socket.send(message('transcript.final', { text: '打开夹爪', confidence: 0.97 }, incoming.sessionId));
        socket.send(message('assistant.response', { text: '好的，我已理解你的指令。' }, incoming.sessionId));
        socket.send(message('intent.candidate', {
          intent: 'gripper.open',
          sourceText: '打开夹爪',
          confidence: 0.95,
          requiresConfirmation: true,
          args: {}
        }, incoming.sessionId));
        socket.send(message('session.completed', { inputMode: 'audio' }, incoming.sessionId));
      }
      if (incoming.type === 'text.submit') {
        if (incoming.payload?.text !== '回到初始位置') {
          finish(new Error('Text command payload was not preserved.'));
          return;
        }
        socket.send(message(
          'session.processing',
          { inputMode: 'text' },
          incoming.sessionId,
          incoming.messageId
        ));
        socket.send(message('assistant.response', {
          inputMode: 'text',
          text: '收到文字指令。'
        }, incoming.sessionId, incoming.messageId));
        socket.send(message('intent.candidate', {
          intent: 'robot.preset',
          sourceText: incoming.payload.text,
          requiresConfirmation: true,
          args: { name: 'home' }
        }, incoming.sessionId, incoming.messageId));
        socket.send(message(
          'session.completed',
          { inputMode: 'text' },
          incoming.sessionId,
          incoming.messageId
        ));
      }
    });
  });

  server.on('listening', () => {
    client = new WebSocket(`ws://${HOST}:${PORT}${PATH}`, PROTOCOL);
    client.on('error', finish);
    client.on('open', () => {
      client.send(message('session.start', {
        audio: {
          encoding: 'pcm_s16le',
          sampleRate: 16000,
          channels: 1,
          frameMs: 100
        }
      }, AUDIO_SESSION_ID));

      const audioFrame = Buffer.alloc(12 + 3200);
      audioFrame.write('THV1', 0, 'ascii');
      audioFrame.writeUInt32LE(0, 4);
      audioFrame.writeUInt32LE(0, 8);
      client.send(audioFrame);
      client.send(message('session.stop', {}, AUDIO_SESSION_ID));
    });

    client.on('message', data => {
      const incoming = JSON.parse(data.toString());
      if (phase === 'text' && incoming.replyTo !== 'text.submit-1') {
        finish(new Error(`${incoming.type} did not preserve text.submit replyTo.`));
        return;
      }
      events.push(incoming.type);
      console.log(`PASS ${phase} received ${incoming.type}`);

      if (incoming.type === 'session.completed') {
        const expected = phase === 'audio'
          ? EXPECTED_AUDIO_EVENTS
          : EXPECTED_TEXT_EVENTS;
        const ordered = expected.length === events.length &&
          expected.every((event, index) => events[index] === event);
        if (!ordered) {
          finish(new Error(`Unexpected ${phase} event order: ${events.join(', ')}`));
          return;
        }
        if (phase === 'audio') {
          console.log('PASS audio round trip completed');
          phase = 'text';
          events.length = 0;
          client.send(message(
            'text.submit',
            { text: '回到初始位置' },
            TEXT_SESSION_ID
          ));
        } else {
          console.log('PASS text round trip completed without ASR or hardware access');
          finish();
        }
      }
    });
  });
