'use strict';

const { randomUUID } = require('crypto');
const { WebSocketServer } = require('ws');

const HOST = process.env.VOICE_HOST || '127.0.0.1';
const PORT = Number(process.env.VOICE_PORT || 3001);
const PATH = '/v1/voice';
const PROTOCOL = 'thirdhand.voice.v1';
const MOCK_TEXT = process.env.MOCK_TEXT || '打开夹爪';
const MOCK_REPLY = process.env.MOCK_REPLY || '好的，我已理解你的指令。';
const MOCK_INTENT = process.env.MOCK_INTENT || 'gripper.close';
const MOCK_DELAY_MS = Number(process.env.MOCK_DELAY_MS || 180);
let MOCK_ARGS = {};
try {
  MOCK_ARGS = JSON.parse(process.env.MOCK_ARGS_JSON || '{}');
} catch {
  console.error('[voice mock] MOCK_ARGS_JSON must be valid JSON.');
  process.exit(1);
}

function envelope(type, sessionId, payload = {}, replyTo = null) {
  return {
    v: 1,
    type,
    messageId: randomUUID(),
    replyTo,
    sessionId: sessionId || null,
    ts: Date.now(),
    payload
  };
}

function sendJson(socket, type, sessionId, payload = {}, replyTo = null) {
  if (socket.readyState !== 1) return;
  socket.send(JSON.stringify(envelope(type, sessionId, payload, replyTo)));
}

function sendError(socket, sessionId, code, message, recoverable = true, replyTo = null) {
  sendJson(socket, 'error', sessionId, { code, message, recoverable }, replyTo);
}

function mockCandidate(sourceText) {
  const now = Date.now();
  return {
    candidateId: randomUUID(),
    traceId: randomUUID(),
    sourceText,
    skill: 'manual_joint_control@1',
    createdAt: now,
    expiresAt: now + 120000,
    requiresConfirmation: MOCK_INTENT !== 'safety.stop.request',
    intent: MOCK_INTENT,
    confidence: 0.95,
    payload: { params: { action: MOCK_INTENT, ...MOCK_ARGS } }
  };
}

const server = new WebSocketServer({
  host: HOST,
  port: PORT,
  path: PATH,
  handleProtocols(protocols) {
    return protocols.has(PROTOCOL) ? PROTOCOL : false;
  }
});

server.on('connection', socket => {
  const state = {
    sessionId: null,
    active: false,
    mode: null,
    pendingTimer: null,
    expectedSequence: 0,
    audioBytes: 0,
    partialSent: false
  };

  socket.on('message', (data, isBinary) => {
    if (isBinary) {
      if (!state.active || state.mode !== 'audio') {
        sendError(socket, state.sessionId, 'INVALID_STATE', 'Audio arrived before session.start.');
        return;
      }

      if (data.length !== 3212 || data.subarray(0, 4).toString('ascii') !== 'THV1') {
        sendError(socket, state.sessionId, 'BAD_AUDIO_FRAME', 'Expected THV1 header plus 3200 PCM bytes.');
        return;
      }

      const sequence = data.readUInt32LE(4);
      if (sequence !== state.expectedSequence) {
        sendError(
          socket,
          state.sessionId,
          'AUDIO_SEQUENCE_GAP',
          `Expected audio sequence ${state.expectedSequence}, received ${sequence}.`
        );
        return;
      }

      state.expectedSequence += 1;
      state.audioBytes += data.length - 12;

      if (!state.partialSent) {
        state.partialSent = true;
        sendJson(socket, 'transcript.partial', state.sessionId, {
          segmentId: 'segment-1',
          revision: 1,
          text: MOCK_TEXT.slice(0, Math.max(1, Math.ceil(MOCK_TEXT.length / 2)))
        });
      }
      return;
    }

    let message;
    try {
      message = JSON.parse(data.toString('utf8'));
    } catch {
      sendError(socket, state.sessionId, 'BAD_MESSAGE', 'Control messages must be valid JSON.');
      return;
    }

    if (message.v !== 1) {
      sendError(socket, message.sessionId, 'UNSUPPORTED_VERSION', 'Only Voice Protocol v1 is supported.', false, message.messageId);
      return;
    }

    switch (message.type) {
      case 'ping':
        sendJson(socket, 'pong', state.sessionId, {}, message.messageId);
        break;

      case 'session.start': {
        const audio = message.payload?.audio;
        const supported = audio?.encoding === 'pcm_s16le' &&
          audio?.sampleRate === 16000 &&
          audio?.channels === 1 &&
          audio?.frameMs === 100;

        if (!supported) {
          sendError(socket, message.sessionId, 'UNSUPPORTED_AUDIO', 'Use PCM S16LE, 16 kHz, mono, 100 ms frames.', false, message.messageId);
          return;
        }

        if (state.active) {
          sendError(socket, state.sessionId, 'INVALID_STATE', 'A recording session is already active.', true, message.messageId);
          return;
        }

        state.sessionId = message.sessionId;
        state.active = true;
        state.mode = 'audio';
        state.expectedSequence = 0;
        state.audioBytes = 0;
        state.partialSent = false;
        sendJson(socket, 'session.ready', state.sessionId, {
          mock: true,
          audio
        }, message.messageId);
        break;
      }

      case 'session.stop': {
        if (!state.active || state.mode !== 'audio' || message.sessionId !== state.sessionId) {
          sendError(socket, message.sessionId, 'INVALID_STATE', 'No matching recording session is active.', true, message.messageId);
          return;
        }

        state.mode = 'audio-processing';
        sendJson(socket, 'session.processing', state.sessionId, {
          inputMode: 'audio',
          receivedAudioBytes: state.audioBytes
        }, message.messageId);

        state.pendingTimer = setTimeout(() => {
          sendJson(socket, 'transcript.final', state.sessionId, {
            segmentId: 'segment-1',
            text: MOCK_TEXT,
            confidence: 0.97
          });
          sendJson(socket, 'assistant.response', state.sessionId, {
            text: MOCK_REPLY
          });
          sendJson(socket, 'intent.candidate', state.sessionId, mockCandidate(MOCK_TEXT));
          sendJson(socket, 'session.completed', state.sessionId, {
            inputMode: 'audio',
            mock: true
          });
          state.active = false;
          state.mode = null;
          state.pendingTimer = null;
        }, MOCK_DELAY_MS);
        break;
      }

      case 'text.submit': {
        if (state.active) {
          sendError(socket, message.sessionId, 'INVALID_STATE', 'Another audio or text session is active.', true, message.messageId);
          return;
        }
        const text = typeof message.payload?.text === 'string'
          ? message.payload.text.trim()
          : '';
        if (!message.sessionId || !text) {
          sendError(socket, message.sessionId, 'BAD_MESSAGE', 'payload.text and sessionId are required.', true, message.messageId);
          return;
        }
        if (text.length > 2000) {
          sendError(socket, message.sessionId, 'TEXT_TOO_LONG', 'Text input cannot exceed 2000 characters.', true, message.messageId);
          return;
        }

        state.sessionId = message.sessionId;
        state.active = true;
        state.mode = 'text';
        const replyTo = message.messageId;
        sendJson(socket, 'session.processing', state.sessionId, {
          inputMode: 'text',
          textLength: text.length
        }, replyTo);

        state.pendingTimer = setTimeout(() => {
          sendJson(socket, 'assistant.response', state.sessionId, {
            inputMode: 'text',
            text: MOCK_REPLY
          }, replyTo);
          sendJson(socket, 'intent.candidate', state.sessionId, mockCandidate(text), replyTo);
          sendJson(socket, 'session.completed', state.sessionId, {
            inputMode: 'text',
            mock: true
          }, replyTo);
          state.active = false;
          state.mode = null;
          state.pendingTimer = null;
        }, MOCK_DELAY_MS);
        break;
      }

      case 'session.cancel':
        if (!state.active || message.sessionId !== state.sessionId) {
          sendError(socket, message.sessionId, 'INVALID_STATE', 'No matching audio or text session is active.', true, message.messageId);
          return;
        }
        if (state.pendingTimer) clearTimeout(state.pendingTimer);
        state.pendingTimer = null;
        state.active = false;
        const cancelledMode = state.mode?.startsWith('audio') ? 'audio' : 'text';
        state.mode = null;
        sendJson(socket, 'session.cancelled', state.sessionId, {
          inputMode: cancelledMode,
          reason: message.payload?.reason || 'client_cancelled'
        }, message.messageId);
        break;

      default:
        sendError(socket, message.sessionId, 'UNKNOWN_MESSAGE', `Unknown message type: ${message.type}`, true, message.messageId);
    }
  });
});

server.on('listening', () => {
  console.log('');
  console.log('ThirdHand Voice Protocol v1 mock');
  console.log(`  Voice: ws://${HOST}:${PORT}${PATH}`);
  console.log(`  Mock:  "${MOCK_TEXT}" -> ${MOCK_INTENT}`);
  console.log('  Scope: voice + text replies and candidate intents; no hardware access');
  console.log('');
});

server.on('error', error => {
  console.error(`[voice mock] ${error.message}`);
  process.exitCode = 1;
});

process.on('SIGINT', () => server.close(() => process.exit(0)));
