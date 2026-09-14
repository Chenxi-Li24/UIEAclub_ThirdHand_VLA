'use strict';

const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');
const express = require('express');
const WebSocket = require('ws');
const { WebSocketServer } = WebSocket;

const EDGE = [
  process.env.EDGE_PATH,
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  '/usr/bin/microsoft-edge',
  '/usr/bin/google-chrome',
].filter(Boolean).find(fs.existsSync);
if (!EDGE) throw new Error('Microsoft Edge or Google Chrome was not found');

const PORT = Number(process.env.LANGUAGE_BROWSER_PORT || 3130);
const DEBUG_PORT = Number(process.env.LANGUAGE_BROWSER_DEBUG_PORT || 9240);
const ROOT = path.resolve(__dirname, '..', '..');
const WEB_ROOT = path.join(ROOT, 'web');
const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-language-edge-'));
const browserMessages = [];
const voiceMessages = [];
const exceptions = [];
let edge;
let cdp;
let server;
let browserWss;
let voiceWss;
let commandId = 0;
const pending = new Map();

function delay(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }

async function waitFor(fn, timeoutMs = 8000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await fn()) return;
    await delay(75);
  }
  throw new Error('condition timed out');
}

function cdpCommand(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++commandId;
    pending.set(id, { resolve, reject });
    cdp.send(JSON.stringify({ id, method, params }));
  });
}

async function evaluate(expression) {
  const response = await cdpCommand('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (response.result?.exceptionDetails) throw new Error(response.result.exceptionDetails.text);
  return response.result?.result?.value;
}

function sendVoice(socket, type, sessionId, payload = {}) {
  socket.send(JSON.stringify({
    v: 1, type, messageId: `mock-${Date.now()}-${Math.random()}`,
    replyTo: null, sessionId, ts: Date.now(), payload,
  }));
}

async function main() {
  const app = express();
  app.get('/api/runtime-config', (_request, response) => response.json({
    language: {
      voiceEndpoint: `ws://127.0.0.1:${PORT}/v1/voice`,
      enabled: false,
      skill: 'manual_joint_control@1',
      maxDeltaDeg: null,
      speedScale: 0.05,
      directional: {
        enabled: true,
        realControlEnabled: false,
        skill: 'directional_joint_control@1',
        defaultDeltaDeg: 20,
        speedScale: 0.05,
      },
    },
  }));
  app.use(express.static(WEB_ROOT));
  server = http.createServer(app);
  browserWss = new WebSocketServer({ noServer: true });
  voiceWss = new WebSocketServer({ noServer: true, handleProtocols: protocols => (
    protocols.has('thirdhand.voice.v1') ? 'thirdhand.voice.v1' : false
  ) });

  server.on('upgrade', (request, socket, head) => {
    const target = request.url === '/ws' ? browserWss : request.url === '/v1/voice' ? voiceWss : null;
    if (!target) return socket.destroy();
    target.handleUpgrade(request, socket, head, ws => target.emit('connection', ws, request));
  });

  browserWss.on('connection', socket => {
    const send = message => socket.readyState === WebSocket.OPEN && socket.send(JSON.stringify(message));
    send({
      type: 'config',
      connection: { connected: true, interface: 'test' },
      jointLimits: [[-162, 162], [-12, 201], [-183, 0], [-98, 98], [-98, 98], [-164, 164]],
      presets: { home: [0, 0, 0, 0, 0, 0] },
      language: {
        executionBackend: 'local-bridge',
        directional: { enabled: true, realControlEnabled: false },
      },
    });
    send({ type: 'connection', connected: true, interface: 'test' });
    const stateTimer = setInterval(() => send({
      type: 'robot_state',
      joints: [0, 0, -10, 0, 0, 0],
      gripperPosition: 0.5,
      stateName: 'IDLE',
      ts: Date.now(),
    }), 100);
    socket.on('message', raw => {
      const message = JSON.parse(raw.toString());
      browserMessages.push(message);
      if (message.type === 'skill.candidate') {
        send({
          type: 'skill.candidate.registered',
          candidateId: message.candidate.candidateId,
          traceId: message.candidate.traceId,
          expiresAt: message.candidate.expiresAt,
        });
      }
      if (message.type === 'confirmation.decision' && message.decision === 'approve') {
        send({ type: 'execution.request', candidateId: message.candidateId, traceId: message.traceId });
        setTimeout(() => send({
          type: 'skill.result',
          success: false,
          status: 'blocked',
          candidateId: message.candidateId,
          traceId: message.traceId,
          message: 'LANGUAGE_REAL_CONTROL 未启用，未发送硬件命令',
        }), 60);
      }
      if (message.type === 'confirmation.decision' && message.decision === 'reject') {
        send({
          type: 'skill.result', success: false, status: 'rejected',
          candidateId: message.candidateId, traceId: message.traceId,
          message: '用户已取消，未发送任何硬件命令',
        });
      }
    });
    socket.on('close', () => clearInterval(stateTimer));
  });

  voiceWss.on('connection', socket => {
    socket.on('message', raw => {
      const message = JSON.parse(raw.toString());
      voiceMessages.push(message);
      if (message.type === 'text.submit') {
        const now = Date.now();
        if (message.payload.text === 'raise and move left') {
          sendVoice(socket, 'session.processing', message.sessionId, { inputMode: 'text' });
          sendVoice(socket, 'assistant.response', message.sessionId, {
            text: 'Raise and move left by the default 20 degrees is ready for confirmation.',
          });
          sendVoice(socket, 'intent.candidate', message.sessionId, {
            candidateId: `candidate-directional-compound-${now}`,
            traceId: `trace-directional-compound-${now}`,
            sourceText: message.payload.text,
            skill: 'directional_joint_control@1',
            createdAt: now,
            expiresAt: now + 120000,
            requiresConfirmation: true,
            intent: 'directional.compound',
            confidence: 0.99,
            payload: { params: { moves: [
              { action: 'lift.up', deltaDeg: 20 },
              { action: 'turn.left', deltaDeg: 20 },
            ] } },
          });
          sendVoice(socket, 'session.completed', message.sessionId, { inputMode: 'text' });
          return;
        }
        if (message.payload.text === 'turn left') {
          sendVoice(socket, 'session.processing', message.sessionId, { inputMode: 'text' });
          sendVoice(socket, 'assistant.response', message.sessionId, {
            text: 'Turning left by 20 degrees is ready for confirmation.',
          });
          sendVoice(socket, 'intent.candidate', message.sessionId, {
            candidateId: `candidate-directional-${now}`,
            traceId: `trace-directional-${now}`,
            sourceText: message.payload.text,
            skill: 'directional_joint_control@1',
            createdAt: now,
            expiresAt: now + 120000,
            requiresConfirmation: true,
            intent: 'turn.left',
            confidence: 0.99,
            payload: { params: { action: 'turn.left', deltaDeg: 20 } },
          });
          sendVoice(socket, 'session.completed', message.sessionId, { inputMode: 'text' });
          return;
        }
        if (message.payload.text === 'go home') {
          sendVoice(socket, 'session.processing', message.sessionId, { inputMode: 'text' });
          sendVoice(socket, 'assistant.response', message.sessionId, {
            text: 'The existing Home preset is ready for confirmation.',
          });
          sendVoice(socket, 'intent.candidate', message.sessionId, {
            candidateId: `candidate-home-${now}`,
            traceId: `trace-home-${now}`,
            sourceText: message.payload.text,
            skill: 'manual_joint_control@1',
            createdAt: now,
            expiresAt: now + 120000,
            requiresConfirmation: true,
            intent: 'robot.home',
            confidence: 0.99,
            payload: { params: { action: 'robot.home' } },
          });
          sendVoice(socket, 'session.completed', message.sessionId, { inputMode: 'text' });
          return;
        }
        if (message.payload.text === 'pick coke') {
          sendVoice(socket, 'session.processing', message.sessionId, { inputMode: 'text' });
          sendVoice(socket, 'assistant.response', message.sessionId, {
            text: 'The predefined Coke Skill is ready for confirmation.',
          });
          sendVoice(socket, 'intent.candidate', message.sessionId, {
            candidateId: `candidate-pick-${now}`,
            traceId: `trace-pick-${now}`,
            sourceText: message.payload.text,
            skill: 'pick_and_place_bottle@1',
            createdAt: now,
            expiresAt: now + 120000,
            requiresConfirmation: true,
            intent: 'pick_and_place_bottle',
            confidence: 0.99,
            payload: {
              params: {
                object: 'coke_bottle',
                destination: { id: 'drop_zone_b', type: 'configured_drop_zone' },
              },
            },
          });
          sendVoice(socket, 'session.completed', message.sessionId, { inputMode: 'text' });
          return;
        }
        sendVoice(socket, 'session.processing', message.sessionId, { inputMode: 'text' });
        sendVoice(socket, 'assistant.response', message.sessionId, { text: '已生成夹爪候选，请先检查预览。' });
        sendVoice(socket, 'intent.candidate', message.sessionId, {
          candidateId: `candidate-${now}`,
          traceId: `trace-${now}`,
          sourceText: message.payload.text,
          skill: 'manual_joint_control@1',
          createdAt: now,
          expiresAt: now + 120000,
          requiresConfirmation: true,
          intent: 'gripper.close',
          confidence: 0.98,
          payload: { params: { action: 'gripper.close' } },
        });
        sendVoice(socket, 'session.completed', message.sessionId, { inputMode: 'text' });
      }
      if (message.type === 'candidate.action' && message.payload?.action === 'guide') {
        sendVoice(socket, 'assistant.response', message.sessionId, { text: '先清空工作区，再检查物理急停。' });
        sendVoice(socket, 'session.completed', message.sessionId, { inputMode: 'guide' });
      }
    });
  });

  await new Promise(resolve => server.listen(PORT, '127.0.0.1', resolve));
  edge = spawn(EDGE, [
    '--headless=new', '--disable-gpu', '--hide-scrollbars',
    `--remote-debugging-port=${DEBUG_PORT}`, `--user-data-dir=${profileDir}`,
    `http://127.0.0.1:${PORT}/`,
  ], { windowsHide: true, stdio: 'ignore' });

  let target;
  await waitFor(async () => {
    try {
      const response = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json`);
      const targets = await response.json();
      target = targets.find(item => item.type === 'page');
      return Boolean(target?.webSocketDebuggerUrl);
    } catch { return false; }
  });
  cdp = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { cdp.once('open', resolve); cdp.once('error', reject); });
  cdp.on('message', raw => {
    const message = JSON.parse(raw.toString());
    if (message.id && pending.has(message.id)) {
      pending.get(message.id).resolve(message);
      pending.delete(message.id);
    }
    if (message.method === 'Runtime.exceptionThrown') exceptions.push(message.params);
  });
  await cdpCommand('Runtime.enable');
  await waitFor(() => evaluate("document.getElementById('voice-ai-status')?.textContent === 'AI 已连接'"));
  await evaluate("document.getElementById('btn-voice-toggle').click()");
  await evaluate(`(() => {
    const input = document.getElementById('voice-text-input');
    input.value = '关闭夹爪';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    document.getElementById('voice-text-form').requestSubmit();
  })()`);
  await waitFor(() => evaluate("document.getElementById('voice-intent-card').hidden === false"));
  await waitFor(() => evaluate("document.getElementById('voice-intent-confirm').disabled === false"));

  const preview = await evaluate(`(() => ({
    visible: !document.getElementById('voice-preview-indicator').hidden,
    label: document.getElementById('voice-preview-label').textContent,
    confirmEnabled: !document.getElementById('voice-intent-confirm').disabled,
    endpoint: document.getElementById('voice-ai-endpoint').value,
    boundary: document.querySelector('.voice-intent-boundary').textContent,
    previewData: { ...document.getElementById('voice-preview-indicator').dataset },
    log: document.getElementById('log-area').textContent,
    speaker: Boolean(document.getElementById('voice-speaker-select')),
    guide: Boolean(document.getElementById('voice-intent-guide')),
    camera: Boolean(document.getElementById('camera-feed')),
    activeVision: Boolean(document.querySelector('a[href="/active-vision.html"]')),
    grounding: Boolean(document.getElementById('grounding-form'))
  }))()`);
  if (!preview.visible || !preview.confirmEnabled) throw new Error(`preview gate failed: ${JSON.stringify(preview)}`);
  if (browserMessages.some(item => item.type === 'confirmation.decision')) throw new Error('confirmation was sent before click');

  await evaluate("document.getElementById('voice-intent-confirm').click()");
  await waitFor(() => evaluate("document.getElementById('voice-conversation').textContent.includes('LANGUAGE_REAL_CONTROL')"));
  await waitFor(() => Promise.resolve(voiceMessages.some(item => item.type === 'tts.request')));

  const approve = browserMessages.find(item => item.type === 'confirmation.decision' && item.decision === 'approve');
  const hardwareCommands = browserMessages.filter(item => typeof item.cmd === 'string');
  const tts = voiceMessages.find(item => item.type === 'tts.request');
  await evaluate(`(() => {
    const input = document.getElementById('voice-text-input');
    input.value = 'pick coke';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    document.getElementById('voice-text-form').requestSubmit();
  })()`);
  await waitFor(() => evaluate("document.getElementById('voice-intent-card').hidden === false"));
  await waitFor(() => evaluate("document.getElementById('voice-intent-confirm').disabled === false"));
  const pickUi = await evaluate(`(() => ({
    confirmEnabled: !document.getElementById('voice-intent-confirm').disabled,
    previewVisible: !document.getElementById('voice-preview-indicator').hidden
  }))()`);
  const pickRegistration = browserMessages.find(item =>
    item.type === 'skill.candidate' && item.candidate?.skill === 'pick_and_place_bottle@1'
  );
  await evaluate("document.getElementById('voice-intent-cancel').click()");
  await evaluate(`(() => {
    const input = document.getElementById('voice-text-input');
    input.value = 'go home';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    document.getElementById('voice-text-form').requestSubmit();
  })()`);
  await waitFor(() => evaluate("document.getElementById('voice-intent-card').hidden === false"));
  await waitFor(() => evaluate("document.getElementById('voice-intent-confirm').disabled === false"));
  const homeUi = await evaluate(`(() => ({
    confirmEnabled: !document.getElementById('voice-intent-confirm').disabled,
    previewVisible: !document.getElementById('voice-preview-indicator').hidden,
    previewLabel: document.getElementById('voice-preview-label').textContent
  }))()`);
  const homeRegistration = browserMessages.find(item =>
    item.type === 'skill.candidate' && item.candidate?.intent === 'robot.home'
  );
  await evaluate("document.getElementById('voice-intent-cancel').click()");
  await evaluate(`(() => {
    const input = document.getElementById('voice-text-input');
    input.value = 'turn left';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    document.getElementById('voice-text-form').requestSubmit();
  })()`);
  await waitFor(() => evaluate("document.getElementById('voice-intent-card').hidden === false"));
  await waitFor(() => evaluate("document.getElementById('voice-intent-confirm').disabled === false"));
  const directionalUi = await evaluate(`(() => ({
    confirmEnabled: !document.getElementById('voice-intent-confirm').disabled,
    previewVisible: !document.getElementById('voice-preview-indicator').hidden,
    previewLabel: document.getElementById('voice-preview-label').textContent,
    candidateLabel: document.getElementById('voice-intent-name').textContent
  }))()`);
  const directionalRegistration = browserMessages.find(item =>
    item.type === 'skill.candidate' && item.candidate?.skill === 'directional_joint_control@1'
  );
  const directionalControlBeforeClick = browserMessages.filter(item =>
    item.type === 'confirmation.decision' && item.candidateId === directionalRegistration?.candidate?.candidateId
  );
  await evaluate("document.getElementById('voice-intent-cancel').click()");
  await evaluate(`(() => {
    const input = document.getElementById('voice-text-input');
    input.value = 'raise and move left';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    document.getElementById('voice-text-form').requestSubmit();
  })()`);
  await waitFor(() => evaluate("document.getElementById('voice-intent-card').hidden === false"));
  await waitFor(() => evaluate("document.getElementById('voice-intent-confirm').disabled === false"));
  const compoundUi = await evaluate(`(() => ({
    confirmEnabled: !document.getElementById('voice-intent-confirm').disabled,
    previewVisible: !document.getElementById('voice-preview-indicator').hidden,
    previewLabel: document.getElementById('voice-preview-label').textContent,
    candidateLabel: document.getElementById('voice-intent-name').textContent,
    cardCount: document.querySelectorAll('#voice-intent-card:not([hidden])').length
  }))()`);
  const compoundRegistration = browserMessages.find(item =>
    item.type === 'skill.candidate' && item.candidate?.intent === 'directional.compound'
  );
  const compoundControlBeforeClick = browserMessages.filter(item =>
    item.type === 'confirmation.decision' && item.candidateId === compoundRegistration?.candidate?.candidateId
  );
  await evaluate("document.getElementById('voice-intent-cancel').click()");
  const checks = {
    runtimeEndpoint: preview.endpoint === `ws://127.0.0.1:${PORT}/v1/voice`,
    previewBeforeConfirmation: preview.visible && preview.label.includes('夹爪'),
    explicitMatchingConfirmation: Boolean(approve?.candidateId && approve?.traceId),
    noHardwareCommandFromBrowser: hardwareCommands.length === 0,
    disabledFeatureReportedBlocked: await evaluate("document.getElementById('voice-conversation').textContent.includes('未发送硬件命令')"),
    exactHardwareResultSentToTts: tts?.payload?.text === 'LANGUAGE_REAL_CONTROL 未启用，未发送硬件命令',
    speakerAndGuidePresent: preview.speaker && preview.guide,
    cameraActiveVisionAndGroundingPreserved: preview.camera && preview.activeVision && preview.grounding,
    truthfulBoundary: preview.boundary.includes('真实反馈'),
    complexSkillContractHandoff: Boolean(
      pickRegistration?.candidate?.payload?.params?.object === 'coke_bottle' &&
      pickRegistration?.candidate?.payload?.params?.destination?.id === 'drop_zone_b' &&
      !('jointsRad' in pickRegistration.candidate.payload.params)
    ),
    complexSkillSummaryPreview: pickUi.confirmEnabled && !pickUi.previewVisible,
    homeUsesExistingPresetPreview: Boolean(
      homeRegistration?.candidate?.payload?.params?.action === 'robot.home' &&
      Object.keys(homeRegistration.candidate.payload.params).length === 1 &&
      homeUi.confirmEnabled && homeUi.previewVisible && homeUi.previewLabel.includes('Home')
    ),
    directionalCandidatePreview: Boolean(
      directionalRegistration?.candidate?.payload?.params?.action === 'turn.left' &&
      directionalRegistration?.candidate?.payload?.params?.deltaDeg === 20 &&
      directionalUi.confirmEnabled && directionalUi.previewVisible &&
      directionalUi.previewLabel.includes('J1') &&
      directionalUi.previewLabel.includes('+20.0°') &&
      directionalUi.candidateLabel.includes('向左') &&
      directionalControlBeforeClick.length === 0
    ),
    compoundDirectionalPreviewIsAtomic: Boolean(
      compoundRegistration?.candidate?.payload?.params?.moves?.length === 2 &&
      compoundRegistration.candidate.payload.params.moves[0].action === 'lift.up' &&
      compoundRegistration.candidate.payload.params.moves[1].action === 'turn.left' &&
      compoundUi.cardCount === 1 && compoundUi.confirmEnabled && compoundUi.previewVisible &&
      compoundUi.previewLabel.includes('J1') &&
      compoundUi.previewLabel.includes('J2') &&
      compoundUi.previewLabel.includes('J3') &&
      compoundUi.previewLabel.includes('+20.0°') &&
      compoundUi.previewLabel.includes('-20.0°') &&
      compoundUi.candidateLabel.includes('抬高') &&
      compoundUi.candidateLabel.includes('向左') &&
      compoundControlBeforeClick.length === 0
    ),
    noRuntimeExceptions: exceptions.length === 0,
  };
  for (const [name, passed] of Object.entries(checks)) console.log(`${passed ? 'PASS' : 'FAIL'} ${name}`);
  if (Object.values(checks).some(value => !value)) throw new Error('language browser smoke failed');
}

main().catch(error => {
  console.error('FAIL', error);
  process.exitCode = 1;
}).finally(async () => {
  try { await cdpCommand('Browser.close'); } catch {}
  try { cdp?.close(); } catch {}
  if (edge && edge.exitCode === null) edge.kill();
  for (const client of browserWss?.clients || []) client.terminate();
  for (const client of voiceWss?.clients || []) client.terminate();
  await new Promise(resolve => server ? server.close(resolve) : resolve());
  await delay(500);
  const resolved = path.resolve(profileDir).toLowerCase();
  const tempRoot = `${path.resolve(os.tmpdir()).toLowerCase()}${path.sep}`;
  if (resolved.startsWith(tempRoot)) {
    try {
      fs.rmSync(profileDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    } catch (error) {
      console.warn(`WARN temporary Edge profile cleanup deferred: ${error.message}`);
    }
  }
});
