'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');
const WebSocket = require('ws');

const EDGE_CANDIDATES = [
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe'
];
const EDGE_PATH = EDGE_CANDIDATES.find(candidate => fs.existsSync(candidate));
const SERVER_ROOT = path.resolve(__dirname, '..');
const WEB_PORT = Number(process.env.LUMOS_TEST_PORT || 3110);
const VOICE_PORT = Number(process.env.VOICE_TEST_PORT || 3111);
const UNSUPPORTED_VOICE_PORT = VOICE_PORT + 1;
const OFFLINE_VOICE_PORT = VOICE_PORT + 8;
const PAGE_URL = `http://127.0.0.1:${WEB_PORT}/`;
const VOICE_ENDPOINT = `ws://127.0.0.1:${VOICE_PORT}/v1/voice`;
const UNSUPPORTED_ENDPOINT = `ws://127.0.0.1:${UNSUPPORTED_VOICE_PORT}/v1/voice`;
const DEBUG_PORT = Number(process.env.EDGE_DEBUG_PORT || 9237);
const SCREENSHOT_PATH = path.join(os.tmpdir(), 'thirdhand-lumos-voice-smoke.png');
const VOICE_SCREENSHOT_PATH = path.join(
  os.tmpdir(),
  'thirdhand-lumos-voice-panel-smoke.png'
);
const MOBILE_SCREENSHOT_PATH = path.join(
  os.tmpdir(),
  'thirdhand-lumos-voice-mobile-smoke.png'
);
const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-lumos-edge-'));
const safeTempPrefix = `${path.resolve(os.tmpdir())}${path.sep}`.toLowerCase();

if (!EDGE_PATH) {
  console.error('FAIL Microsoft Edge was not found.');
  process.exit(1);
}

let lumosServer;
let voiceMock;
let unsupportedVoiceMock;
let edge;
let cdp;
let commandId = 0;
const pending = new Map();
const exceptions = [];
const childOutput = [];

function delay(milliseconds) {
  return new Promise(resolve => setTimeout(resolve, milliseconds));
}

async function waitForHttp(url, timeoutMs = 10000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {}
    await delay(100);
  }
  throw new Error(`HTTP server did not become ready: ${url}`);
}

async function waitForDebugTarget() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json`);
      const targets = await response.json();
      const page = targets.find(target => target.type === 'page');
      if (page?.webSocketDebuggerUrl) return page;
    } catch {}
    await delay(100);
  }
  throw new Error('Edge DevTools target did not become ready.');
}

function command(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++commandId;
    pending.set(id, { resolve, reject });
    cdp.send(JSON.stringify({ id, method, params }));
  });
}

async function evaluate(expression) {
  const response = await command('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true
  });
  if (response.result?.exceptionDetails) {
    throw new Error(
      response.result.exceptionDetails.exception?.description ||
      response.result.exceptionDetails.text ||
      'Runtime evaluation failed.'
    );
  }
  return response.result?.result?.value;
}

async function waitFor(expression, timeoutMs = 8000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await evaluate(expression)) return;
    await delay(100);
  }
  throw new Error(`Condition timed out: ${expression}`);
}

function spawnChild(file, env = {}) {
  const child = spawn(process.execPath, [file], {
    cwd: SERVER_ROOT,
    env: { ...process.env, ...env },
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe']
  });
  child.stdout.on('data', chunk => childOutput.push(`[${path.basename(file)}] ${chunk}`));
  child.stderr.on('data', chunk => childOutput.push(`[${path.basename(file)}:err] ${chunk}`));
  return child;
}

async function stopChild(child) {
  if (!child || child.exitCode !== null) return;
  child.kill();
  await Promise.race([
    new Promise(resolve => child.once('exit', resolve)),
    delay(1500)
  ]);
  if (child.exitCode === null) child.kill('SIGKILL');
}

function recordChecks(checks) {
  for (const [name, passed] of Object.entries(checks)) {
    console.log(`${passed ? 'PASS' : 'FAIL'} ${name}`);
  }
  return !Object.values(checks).some(passed => !passed);
}

async function run() {
  lumosServer = spawnChild('proxy.js', {
    STARTOUCH_SIMULATE: '1',
    STARTOUCH_PYTHON: 'python',
    WEB_HOST: '127.0.0.1',
    WEB_PORT: String(WEB_PORT)
  });
  voiceMock = spawnChild(path.join('test', 'voice-mock.js'), {
    VOICE_HOST: '127.0.0.1',
    VOICE_PORT: String(VOICE_PORT),
    MOCK_INTENT: 'gripper.close',
    MOCK_TEXT: '关闭夹爪'
  });
  unsupportedVoiceMock = spawnChild(path.join('test', 'voice-mock.js'), {
    VOICE_HOST: '127.0.0.1',
    VOICE_PORT: String(UNSUPPORTED_VOICE_PORT),
    MOCK_INTENT: 'robot.move_to',
    MOCK_TEXT: '移动到桌面上方'
  });
  await waitForHttp(PAGE_URL);

  edge = spawn(EDGE_PATH, [
    '--headless=new',
    '--disable-gpu',
    '--hide-scrollbars',
    '--use-fake-device-for-media-stream',
    '--use-fake-ui-for-media-stream',
    '--autoplay-policy=no-user-gesture-required',
    `--remote-debugging-port=${DEBUG_PORT}`,
    `--user-data-dir=${profileDir}`,
    '--window-size=1440,1000',
    PAGE_URL
  ], {
    windowsHide: true,
    stdio: 'ignore'
  });

  const target = await waitForDebugTarget();
  cdp = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    cdp.once('open', resolve);
    cdp.once('error', reject);
  });
  cdp.on('message', raw => {
    const message = JSON.parse(raw.toString());
    if (message.id && pending.has(message.id)) {
      const request = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) request.reject(new Error(message.error.message));
      else request.resolve(message);
      return;
    }
    if (message.method === 'Runtime.exceptionThrown') {
      exceptions.push(
        message.params.exceptionDetails.exception?.description ||
        message.params.exceptionDetails.text
      );
    }
  });

  await command('Runtime.enable');
  await command('Page.enable');
  await waitFor(`document.readyState === 'complete'`);
  const defaultEndpoint = await evaluate(
    `document.getElementById('voice-ai-endpoint')?.value`
  );
  const defaultRouteState = await evaluate(`(() => ({
    optionCount: document.querySelectorAll('[data-voice-endpoint]').length,
    gpuPressed: document.querySelector(
      '[data-voice-endpoint="ws://192.168.58.43:3002/v1/voice"]'
    )?.getAttribute('aria-pressed'),
    cpuPressed: document.querySelector(
      '[data-voice-endpoint="ws://192.168.58.43:3001/v1/voice"]'
    )?.getAttribute('aria-pressed'),
    description: document.getElementById('voice-route-description')?.textContent
  }))()`);

  await command('Page.addScriptToEvaluateOnNewDocument', {
    source: `(() => {
      window.__thirdhandWsSends = [];
      const originalSend = WebSocket.prototype.send;
      WebSocket.prototype.send = function(data) {
        let serialized = '[binary]';
        if (typeof data === 'string') serialized = data;
        window.__thirdhandWsSends.push({
          url: this.url,
          protocol: this.protocol,
          data: serialized,
          ts: Date.now()
        });
        return originalSend.call(this, data);
      };
      const originalTimeout = window.setTimeout.bind(window);
      window.setTimeout = (callback, timeout, ...args) =>
        originalTimeout(callback, timeout === 30000 ? 1600 : timeout, ...args);
    })();`
  });
  await evaluate(`localStorage.setItem('voiceAiEndpoint', '${VOICE_ENDPOINT}')`);
  await evaluate(`localStorage.setItem('voiceAiEndpointDefaultV3', '1')`);
  await command('Page.reload', { ignoreCache: true });
  await waitFor(`document.readyState === 'complete'`);
  await waitFor(`document.querySelectorAll('#three-container canvas').length === 1`, 12000);
  await waitFor(`document.getElementById('voice-ai-status')?.textContent === 'AI 已连接'`);

  await evaluate(`document.getElementById('btn-voice-toggle').click()`);
  await waitFor(`document.getElementById('voice-panel').classList.contains('open')`);
  const overlayState = await evaluate(`(() => ({
    drawerCollapsed: document.getElementById('control-drawer').classList.contains('collapsed'),
    logClosed: !document.getElementById('log-panel').classList.contains('open')
  }))()`);

  const emptyTextDisabled = await evaluate(
    `document.getElementById('voice-text-send').disabled`
  );
  const keyboardGuards = await evaluate(`(() => {
    const input = document.getElementById('voice-text-input');
    const form = document.getElementById('voice-text-form');
    const send = document.getElementById('voice-text-send');
    input.focus();
    input.value = '第一行';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    const shiftAllowed = input.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Enter', shiftKey: true, bubbles: true, cancelable: true
    }));
    const shiftDidNotSubmit = shiftAllowed && form.getAttribute('aria-busy') === 'false';
    input.dispatchEvent(new CompositionEvent('compositionstart', {
      bubbles: true, data: '输入法测试'
    }));
    input.value = '输入法测试';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    const compositionClickBlocked = send.disabled;
    send.click();
    input.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Enter', bubbles: true, cancelable: true
    }));
    input.dispatchEvent(new CompositionEvent('compositionend', {
      bubbles: true, data: '输入法测试'
    }));
    input.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Enter', bubbles: true, cancelable: true
    }));
    return {
      shiftDidNotSubmit,
      compositionClickBlocked,
      imeDidNotSubmit:
        form.getAttribute('aria-busy') === 'false' &&
        document.querySelector('.voice-empty') !== null &&
        input.value === '输入法测试'
    };
  })()`);

  await delay(130);
  await evaluate(`(() => {
    const input = document.getElementById('voice-text-input');
    input.value = '回到初始位置';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Enter', bubbles: true, cancelable: true
    }));
  })()`);
  const busyState = await evaluate(`(() => ({
    formBusy: document.getElementById('voice-text-form').getAttribute('aria-busy'),
    sendDisabled: document.getElementById('voice-text-send').disabled,
    recordDisabled: document.getElementById('voice-record-toggle').disabled,
    routesDisabled: [...document.querySelectorAll('[data-voice-endpoint]')]
      .every(button => button.disabled)
  }))()`);
  await waitFor(
    `document.getElementById('voice-intent-source').textContent.includes('回到初始位置')`
  );
  const textResult = await evaluate(`(() => ({
    conversation: document.getElementById('voice-conversation').textContent,
    source: document.getElementById('voice-intent-source').textContent,
    inputValue: document.getElementById('voice-text-input').value,
    inputFocused: document.activeElement === document.getElementById('voice-text-input'),
    thinkingCount: document.querySelectorAll('.voice-message--thinking').length,
    formBusy: document.getElementById('voice-text-form').getAttribute('aria-busy')
  }))()`);
  const pendingGuard = await evaluate(`(async () => {
    const input = document.getElementById('voice-text-input');
    const send = document.getElementById('voice-text-send');
    const before = document.querySelectorAll('.voice-message--user').length;
    input.value = '这条不应发送';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    const disabledWhilePending = send.disabled;
    input.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Enter', bubbles: true, cancelable: true
    }));
    await new Promise(resolve => setTimeout(resolve, 80));
    return {
      disabledWhilePending,
      routesDisabledWhilePending:
        [...document.querySelectorAll('[data-voice-endpoint]')]
          .every(button => button.disabled),
      candidateStillVisible: !document.getElementById('voice-intent-card').hidden,
      draftPreserved: input.value === '这条不应发送',
      userMessageCountUnchanged:
        document.querySelectorAll('.voice-message--user').length === before
    };
  })()`);
  await evaluate(`document.getElementById('voice-intent-cancel').click()`);
  await waitFor(`document.getElementById('voice-intent-card').hidden`);
  const textLimitState = await evaluate(`(async () => {
    const input = document.getElementById('voice-text-input');
    const before = window.__thirdhandWsSends.filter(entry => {
      if (entry.data === '[binary]') return false;
      try { return JSON.parse(entry.data).type === 'text.submit'; }
      catch { return false; }
    }).length;
    input.value = '字'.repeat(2001);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    document.getElementById('voice-text-form').requestSubmit();
    await new Promise(resolve => setTimeout(resolve, 80));
    const after = window.__thirdhandWsSends.filter(entry => {
      if (entry.data === '[binary]') return false;
      try { return JSON.parse(entry.data).type === 'text.submit'; }
      catch { return false; }
    }).length;
    const result = {
      maxlength: input.maxLength,
      draftPreserved: input.value.length === 2001,
      requestNotSent: before === after,
      warningShown:
        document.getElementById('voice-conversation').textContent.includes(
          '文字指令不能超过 2000 个字符'
        )
    };
    input.value = '';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    return result;
  })()`);

  await evaluate(`document.getElementById('voice-mic-toggle').click()`);
  await waitFor(`document.getElementById('voice-mic-status').textContent === '麦克风就绪'`, 10000);
  const deviceCount = await evaluate(
    `document.getElementById('voice-device-select').options.length`
  );
  await evaluate(`document.getElementById('voice-device-select').dispatchEvent(
    new Event('change', { bubbles: true })
  )`);
  await waitFor(
    `document.getElementById('voice-conversation').textContent.includes('已切换麦克风')`,
    10000
  );

  await evaluate(`document.getElementById('voice-record-toggle').click()`);
  await waitFor(`document.getElementById('voice-session-status').textContent === '正在录音'`);
  await waitFor(
    `Number(document.getElementById('voice-level-value').textContent) > 0`,
    1200
  );
  const recordingState = await evaluate(`(() => ({
    cancelEnabled: !document.getElementById('voice-record-cancel').disabled,
    level: Number(document.getElementById('voice-level-value').textContent)
  }))()`);
  await evaluate(`document.getElementById('voice-record-cancel').click()`);
  await waitFor(
    `document.getElementById('voice-conversation').textContent.includes('本次语音会话已取消')`
  );
  const cancelledState = await evaluate(`(() => ({
    candidateHidden: document.getElementById('voice-intent-card').hidden,
    cancelDisabled: document.getElementById('voice-record-cancel').disabled
  }))()`);

  await evaluate(`document.getElementById('voice-record-toggle').click()`);
  await waitFor(`document.getElementById('voice-session-status').textContent === '正在录音'`);
  await delay(360);
  await evaluate(`document.getElementById('voice-record-toggle').click()`);
  await waitFor(`document.getElementById('voice-intent-card').hidden === false`);

  const beforeConfirm = await evaluate(`(() => {
    const controlCommands = window.__thirdhandWsSends.filter(entry => {
      if (!entry.url.endsWith('/ws') || entry.data === '[binary]') return false;
      try {
        const cmd = JSON.parse(entry.data).cmd;
        return ['servo','preset','gripper','software_stop','estop','connect','disconnect'].includes(cmd);
      } catch { return false; }
    });
    return {
      count: controlCommands.length,
      intent: document.getElementById('voice-intent-name').textContent,
      boundary: document.querySelector('.voice-intent-boundary').textContent,
      conversation: document.getElementById('voice-conversation').textContent
    };
  })()`);
  const voiceScreenshot = await command('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: false
  });
  fs.writeFileSync(
    VOICE_SCREENSHOT_PATH,
    Buffer.from(voiceScreenshot.result.data, 'base64')
  );
  await evaluate(`document.getElementById('voice-intent-confirm').click()`);
  await waitFor(`document.getElementById('voice-preview-indicator').hidden === false`);
  await delay(600);
  const afterConfirm = await evaluate(`(() => {
    const controlCommands = window.__thirdhandWsSends.filter(entry => {
      if (!entry.url.endsWith('/ws') || entry.data === '[binary]') return false;
      try {
        const cmd = JSON.parse(entry.data).cmd;
        return ['servo','preset','gripper','software_stop','estop','connect','disconnect'].includes(cmd);
      } catch { return false; }
    });
    return {
      count: controlCommands.length,
      indicatorVisible: !document.getElementById('voice-preview-indicator').hidden,
      previewGripper:
        document.getElementById('voice-preview-indicator').dataset.previewGripper,
      conversation: document.getElementById('voice-conversation').textContent,
      log: document.getElementById('log-area').textContent
    };
  })()`);
  await waitFor(`document.getElementById('voice-preview-indicator').hidden === true`, 7000);

  await evaluate(`(() => {
    const endpoint = document.getElementById('voice-ai-endpoint');
    endpoint.value = 'ws://127.0.0.1:${OFFLINE_VOICE_PORT}/v1/voice';
    document.getElementById('voice-ai-reconnect').click();
  })()`);
  await waitFor(`document.getElementById('voice-ai-status').textContent === 'AI 离线'`, 6000);
  const offlineState = await evaluate(`(() => {
    const input = document.getElementById('voice-text-input');
    input.value = '离线草稿';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    return {
      draft: input.value,
      sendDisabled: document.getElementById('voice-text-send').disabled
    };
  })()`);
  await evaluate(`(() => {
    const endpoint = document.getElementById('voice-ai-endpoint');
    endpoint.value = '${UNSUPPORTED_ENDPOINT}';
    document.getElementById('voice-ai-reconnect').click();
  })()`);
  await waitFor(`document.getElementById('voice-ai-status').textContent === 'AI 已连接'`);
  await evaluate(`(() => {
    const input = document.getElementById('voice-text-input');
    input.value = '移动到桌面上方';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    document.getElementById('voice-text-form').requestSubmit();
  })()`);
  await waitFor(`document.getElementById('voice-intent-card').hidden === false`);
  const unsupportedState = await evaluate(`(() => ({
    disabled: document.getElementById('voice-intent-confirm').disabled,
    label: document.getElementById('voice-intent-confirm').textContent
  }))()`);
  await evaluate(`document.getElementById('voice-intent-cancel').click()`);

  await evaluate(`(() => {
    const endpoint = document.getElementById('voice-ai-endpoint');
    endpoint.value = '${VOICE_ENDPOINT}';
    document.getElementById('voice-ai-reconnect').click();
  })()`);
  await waitFor(`document.getElementById('voice-ai-status').textContent === 'AI 已连接'`);
  await evaluate(`document.getElementById('voice-record-toggle').click()`);
  await waitFor(
    `document.getElementById('voice-conversation').textContent.includes('已达到30秒上限')`,
    5000
  );
  await waitFor(`document.getElementById('voice-intent-card').hidden === false`);
  const durationLimitReached = await evaluate(
    `document.getElementById('voice-conversation').textContent.includes('已达到30秒上限')`
  );
  await evaluate(`document.getElementById('voice-intent-cancel').click()`);

  await evaluate(`(() => {
    document.getElementById('btn-log-toggle').click();
    return true;
  })()`);
  const logMutualExclusion = await evaluate(`(() =>
    document.getElementById('log-panel').classList.contains('open') &&
    !document.getElementById('voice-panel').classList.contains('open')
  )()`);
  await evaluate(`document.getElementById('btn-log-close').click()`);

  await evaluate(`document.getElementById('btn-voice-toggle').click()`);
  const focusRestored = await evaluate(`(() => {
    const input = document.getElementById('voice-text-input');
    input.focus();
    document.getElementById('voice-panel-close').click();
    return document.getElementById('voice-panel').inert === true &&
      document.getElementById('voice-panel').getAttribute('aria-hidden') === 'true' &&
      document.activeElement === document.getElementById('btn-voice-toggle');
  })()`);

  await command('Emulation.setDeviceMetricsOverride', {
    width: 375,
    height: 700,
    deviceScaleFactor: 1,
    mobile: true
  });
  await evaluate(`document.getElementById('btn-voice-toggle').click()`);
  const mobileState = await evaluate(`(() => {
    const panel = document.getElementById('voice-panel').getBoundingClientRect();
    return {
      fits: panel.left >= -1 && panel.right <= innerWidth + 1 &&
        panel.top >= -1 && panel.bottom <= innerHeight + 1,
      noHorizontalOverflow: document.documentElement.scrollWidth <= innerWidth + 1
    };
  })()`);
  const mobileScreenshot = await command('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: false
  });
  fs.writeFileSync(
    MOBILE_SCREENSHOT_PATH,
    Buffer.from(mobileScreenshot.result.data, 'base64')
  );
  await command('Emulation.clearDeviceMetricsOverride');
  await evaluate(`document.getElementById('voice-panel-close').click()`);

  const manualBefore = await evaluate(`window.__thirdhandWsSends.length`);
  await evaluate(`document.getElementById('btn-connect').click()`);
  await waitFor(`document.getElementById('hb-label').textContent === 'SDK:OK'`, 10000);
  await waitFor(`document.getElementById('btn-send').disabled === false`, 10000);
  await evaluate(`document.getElementById('btn-send').click()`);
  await waitFor(`window.__thirdhandWsSends.length > ${manualBefore}`);
  const manualRegression = await evaluate(`(() => {
    const entries = window.__thirdhandWsSends.slice(${manualBefore});
    return entries.some(entry => {
      try { return entry.url.endsWith('/ws') && JSON.parse(entry.data).cmd === 'servo'; }
      catch { return false; }
    });
  })()`);

  const finalState = await evaluate(`(() => ({
    canvasCount: document.querySelectorAll('#three-container canvas').length,
    jointSliderCount:
      document.querySelectorAll('#joint-controls-body .joint-slider').length,
    audioCount: document.querySelectorAll('audio').length,
    bodyText: document.body.textContent
  }))()`);
  const screenshot = await command('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: false
  });
  fs.writeFileSync(SCREENSHOT_PATH, Buffer.from(screenshot.result.data, 'base64'));

  const checks = {
    defaultJetsonEndpoint: defaultEndpoint === 'ws://192.168.58.43:3002/v1/voice',
    cpuAndGpuRoutesAvailable:
      defaultRouteState.optionCount === 2 &&
      defaultRouteState.gpuPressed === 'true' &&
      defaultRouteState.cpuPressed === 'false' &&
      defaultRouteState.description.includes('GPU 3002'),
    voiceOpenClosesOtherPanels:
      overlayState.drawerCollapsed && overlayState.logClosed,
    textEmptyDisabled: emptyTextDisabled,
    shiftEnterDoesNotSubmit: keyboardGuards.shiftDidNotSubmit,
    imeClickDoesNotSubmit: keyboardGuards.compositionClickBlocked,
    imeEnterDoesNotSubmit: keyboardGuards.imeDidNotSubmit,
    textSubmittedWithoutMicrophone:
      textResult.conversation.includes('回到初始位置'),
    assistantResponseRendered:
      textResult.conversation.includes('好的，我已理解你的指令。'),
    textSourcePreserved: textResult.source.includes('回到初始位置'),
    textInputClearedAndFocused:
      textResult.inputValue === '' && textResult.inputFocused,
    textBusyBlocksOtherInput:
      busyState.formBusy === 'true' &&
      busyState.sendDisabled &&
      busyState.recordDisabled &&
      busyState.routesDisabled,
    textThinkingCleared:
      textResult.thinkingCount === 0 && textResult.formBusy === 'false',
    pendingCandidateCannotBeBypassed:
      Object.values(pendingGuard).every(Boolean),
    textLengthBoundary:
      textLimitState.maxlength === 2000 &&
      textLimitState.draftPreserved &&
      textLimitState.requestNotSent &&
      textLimitState.warningShown,
    microphoneEnumerated: deviceCount > 0,
    microphoneSwitchPath: true,
    inputLevelVisible: recordingState.level > 0,
    explicitRecordingCancel:
      recordingState.cancelEnabled &&
      cancelledState.candidateHidden &&
      cancelledState.cancelDisabled,
    candidateClearlyPending:
      beforeConfirm.intent.includes('本地预览') &&
      beforeConfirm.boundary.includes('不发送到 LUMOS'),
    noAutomaticExecution:
      !beforeConfirm.conversation.includes('本地模拟完成'),
    candidateSendsZeroLumosCommands:
      beforeConfirm.count === afterConfirm.count,
    localPreviewPersistsAgainstTelemetry:
      afterConfirm.indicatorVisible &&
      afterConfirm.previewGripper === 'true',
    simulationBoundaryRendered:
      afterConfirm.conversation.includes('未发送至 LUMOS') &&
      afterConfirm.log.includes('本地模拟 · 未发送至 LUMOS'),
    bridgeOfflineKeepsDraft:
      offlineState.draft === '离线草稿' && offlineState.sendDisabled,
    unsupportedIntentDisabled:
      unsupportedState.disabled && unsupportedState.label === '不支持本地模拟',
    durationLimitStopsRecording: durationLimitReached,
    logAndVoiceMutuallyExclusive: logMutualExclusion,
    closeRestoresToggleFocus: focusRestored,
    mobilePanelFitsViewport:
      mobileState.fits && mobileState.noHorizontalOverflow,
    lumosModelAndControlsPreserved:
      finalState.canvasCount === 1 && finalState.jointSliderCount === 6,
    manualLumosControlStillWorks: manualRegression,
    noTtsPlayback: finalState.audioCount === 0,
    noAmbiguousExecutionCopy:
      !finalState.bodyText.includes('执行 1 个操作'),
    noRuntimeExceptions: exceptions.length === 0
  };

  console.log(`FINAL_STATE ${JSON.stringify({
    canvasCount: finalState.canvasCount,
    jointSliderCount: finalState.jointSliderCount,
    audioCount: finalState.audioCount
  })}`);
  const passed = recordChecks(checks);
  console.log(`SCREENSHOT ${SCREENSHOT_PATH}`);
  console.log(`VOICE_SCREENSHOT ${VOICE_SCREENSHOT_PATH}`);
  console.log(`MOBILE_SCREENSHOT ${MOBILE_SCREENSHOT_PATH}`);
  if (!passed) {
    if (exceptions.length) console.error(exceptions.join('\n'));
    console.error(childOutput.join(''));
    process.exitCode = 1;
  }
}

run()
  .catch(error => {
    console.error(`FAIL ${error.stack || error.message}`);
    console.error(childOutput.join(''));
    process.exitCode = 1;
  })
  .finally(async () => {
    try { await command('Browser.close'); } catch {}
    try { cdp?.close(); } catch {}
    if (edge && edge.exitCode === null) edge.kill();
    await Promise.all([
      stopChild(unsupportedVoiceMock),
      stopChild(voiceMock),
      stopChild(lumosServer)
    ]);
    await delay(300);
    const resolvedProfile = path.resolve(profileDir).toLowerCase();
    if (resolvedProfile.startsWith(safeTempPrefix)) {
      try { fs.rmSync(profileDir, { recursive: true, force: true }); } catch {}
    }
  });
