const VOICE_PROTOCOL = 'thirdhand.voice.v1';
const GPU_ENDPOINT = window.ThirdHandRuntimeEndpoints.voiceEndpoint(3002, window.location);
const CPU_ENDPOINT = window.ThirdHandRuntimeEndpoints.voiceEndpoint(3001, window.location);
const DEFAULT_ENDPOINT = GPU_ENDPOINT;
const LEGACY_DEFAULT_ENDPOINT = 'ws://127.0.0.1:3001/v1/voice';
const ENDPOINT_MIGRATION_KEY = 'voiceAiEndpointDefaultV4';
const TARGET_SAMPLE_RATE = 16000;
const FRAME_MS = 100;
const FRAME_SAMPLES = TARGET_SAMPLE_RATE * FRAME_MS / 1000;
const MAX_RECORDING_MS = 30000;
const MAX_BUFFERED_BYTES = 1024 * 1024;
const SESSION_READY_TIMEOUT_MS = 5000;

const INTENT_VALIDATORS = {
  'robot.estop': () => true,
  'robot.status': () => true,
  'robot.preset': args => args?.name === 'home',
  'gripper.open': () => true,
  'gripper.close': () => true,
  'gripper.grip': () => true,
  'gripper.set_position': args =>
    Number.isInteger(args?.position) && args.position >= 0 && args.position <= 3800
};

function createId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `voice-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function createEnvelope(type, sessionId, payload = {}, replyTo = null) {
  return {
    v: 1,
    type,
    messageId: createId(),
    replyTo,
    sessionId: sessionId || null,
    ts: Date.now(),
    payload
  };
}

function formatDuration(milliseconds) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return `00:${String(seconds).padStart(2, '0')}`;
}

function formatMicError(error) {
  const messages = {
    NotAllowedError: '麦克风权限被拒绝。请在浏览器地址栏重新允许麦克风。',
    NotFoundError: '没有检测到可用麦克风。',
    NotReadableError: '麦克风正被其他程序占用，或系统无法读取该设备。',
    OverconstrainedError: '所选麦克风已不可用，已尝试回退到默认设备。',
    SecurityError: '当前页面不允许使用麦克风。',
    AbortError: '麦克风启动被系统中断。'
  };
  return messages[error?.name] || error?.message || '麦克风启动失败。';
}

class StreamingPcmEncoder {
  constructor() {
    this.reset(48000);
  }

  reset(inputSampleRate) {
    this.inputSampleRate = inputSampleRate || 48000;
    this.ratio = this.inputSampleRate / TARGET_SAMPLE_RATE;
    this.sourceRemainder = new Float32Array(0);
    this.sourcePosition = 0;
    this.targetQueue = [];
    this.sequence = 0;
  }

  push(samples) {
    if (!(samples instanceof Float32Array) || samples.length === 0) return [];

    const combined = new Float32Array(this.sourceRemainder.length + samples.length);
    combined.set(this.sourceRemainder);
    combined.set(samples, this.sourceRemainder.length);

    const output = [];
    let position = this.sourcePosition;
    while (position < combined.length - 1) {
      const index = Math.floor(position);
      const fraction = position - index;
      const value = combined[index] + (combined[index + 1] - combined[index]) * fraction;
      output.push(value);
      position += this.ratio;
    }

    const consumed = Math.floor(position);
    this.sourceRemainder = combined.slice(consumed);
    this.sourcePosition = position - consumed;
    this.targetQueue.push(...output);

    const frames = [];
    while (this.targetQueue.length >= FRAME_SAMPLES) {
      frames.push(this._encode(this.targetQueue.splice(0, FRAME_SAMPLES)));
    }
    return frames;
  }

  flush() {
    if (this.targetQueue.length === 0) return [];
    const samples = this.targetQueue.splice(0, FRAME_SAMPLES);
    while (samples.length < FRAME_SAMPLES) samples.push(0);
    return [this._encode(samples)];
  }

  _encode(samples) {
    const buffer = new ArrayBuffer(12 + FRAME_SAMPLES * 2);
    const bytes = new Uint8Array(buffer);
    const view = new DataView(buffer);
    bytes.set([0x54, 0x48, 0x56, 0x31], 0); // THV1
    view.setUint32(4, this.sequence, true);
    view.setUint32(8, this.sequence * FRAME_MS, true);

    for (let index = 0; index < samples.length; index += 1) {
      const clamped = Math.max(-1, Math.min(1, samples[index]));
      const pcm = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
      view.setInt16(12 + index * 2, Math.round(pcm), true);
    }

    this.sequence += 1;
    return buffer;
  }
}

class MicrophoneManager {
  constructor(callbacks = {}) {
    this.callbacks = callbacks;
    this.stream = null;
    this.audioContext = null;
    this.sourceNode = null;
    this.analyserNode = null;
    this.workletNode = null;
    this.silentGain = null;
    this.meterFrame = 0;
    this.currentDeviceId = '';
    this.ready = false;
    this._deviceChangeHandler = () => this.refreshDevices();
    navigator.mediaDevices?.addEventListener?.('devicechange', this._deviceChangeHandler);
  }

  async enable(deviceId = '') {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('浏览器未提供麦克风接口。请使用本机 Edge/Chrome，并通过 localhost 或 HTTPS 打开。');
    }

    await this.disable();
    this.callbacks.onState?.('requesting');

    const audioConstraints = {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true
    };
    if (deviceId) audioConstraints.deviceId = { exact: deviceId };

    const stream = await navigator.mediaDevices.getUserMedia({
      audio: audioConstraints,
      video: false
    });

    this.stream = stream;
    const track = stream.getAudioTracks()[0];
    this.currentDeviceId = track?.getSettings?.().deviceId || deviceId || '';
    track?.addEventListener('ended', () => {
      if (this.stream === stream) {
        this.ready = false;
        this.callbacks.onDeviceLost?.();
      }
    });

    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    this.audioContext = new AudioContextClass();
    await this.audioContext.resume();
    await this.audioContext.audioWorklet.addModule(new URL('./pcm-worklet.js', import.meta.url));

    this.sourceNode = this.audioContext.createMediaStreamSource(stream);
    this.analyserNode = this.audioContext.createAnalyser();
    this.analyserNode.fftSize = 512;
    this.analyserNode.smoothingTimeConstant = 0.72;
    this.workletNode = new AudioWorkletNode(this.audioContext, 'thirdhand-pcm-capture');
    this.silentGain = this.audioContext.createGain();
    this.silentGain.gain.value = 0;

    this.sourceNode.connect(this.analyserNode);
    this.sourceNode.connect(this.workletNode);
    this.workletNode.connect(this.silentGain);
    this.silentGain.connect(this.audioContext.destination);
    this.workletNode.port.onmessage = event => {
      this.callbacks.onSamples?.(event.data.samples, this.audioContext?.sampleRate || 48000);
    };

    this.ready = true;
    this._startMeter();
    await this.refreshDevices();
    this.callbacks.onState?.('ready');
    return this.currentDeviceId;
  }

  async refreshDevices() {
    if (!navigator.mediaDevices?.enumerateDevices) return [];
    const devices = (await navigator.mediaDevices.enumerateDevices())
      .filter(device => device.kind === 'audioinput');
    this.callbacks.onDevices?.(devices, this.currentDeviceId);
    return devices;
  }

  async switchDevice(deviceId) {
    return this.enable(deviceId);
  }

  async disable() {
    this.ready = false;
    cancelAnimationFrame(this.meterFrame);
    this.meterFrame = 0;

    const stream = this.stream;
    this.stream = null;
    stream?.getTracks().forEach(track => track.stop());

    for (const node of [this.sourceNode, this.analyserNode, this.workletNode, this.silentGain]) {
      try { node?.disconnect(); } catch {}
    }

    this.sourceNode = null;
    this.analyserNode = null;
    this.workletNode = null;
    this.silentGain = null;

    const context = this.audioContext;
    this.audioContext = null;
    if (context && context.state !== 'closed') {
      try { await context.close(); } catch {}
    }

    this.callbacks.onLevel?.(0);
    this.callbacks.onState?.('off');
  }

  dispose() {
    navigator.mediaDevices?.removeEventListener?.('devicechange', this._deviceChangeHandler);
    return this.disable();
  }

  _startMeter() {
    const data = new Float32Array(this.analyserNode.fftSize);
    const tick = () => {
      if (!this.analyserNode || !this.ready) return;
      this.analyserNode.getFloatTimeDomainData(data);
      let energy = 0;
      for (const sample of data) energy += sample * sample;
      const rms = Math.sqrt(energy / data.length);
      this.callbacks.onLevel?.(Math.min(1, rms * 7));
      this.meterFrame = requestAnimationFrame(tick);
    };
    tick();
  }
}

class VoiceSocket {
  constructor(callbacks = {}) {
    this.callbacks = callbacks;
    this.socket = null;
    this.endpoint = '';
    this.state = 'offline';
    this.manualClose = false;
    this.reconnectTimer = 0;
    this.heartbeatTimer = 0;
    this.missedPongs = 0;
  }

  connect(endpoint) {
    this.endpoint = endpoint;
    this.manualClose = false;
    clearTimeout(this.reconnectTimer);
    this._closeSocket();
    this._setState('connecting');

    let socket;
    try {
      socket = new WebSocket(endpoint, VOICE_PROTOCOL);
    } catch (error) {
      this.callbacks.onError?.(error.message);
      this._setState('offline');
      this._scheduleReconnect();
      return;
    }

    this.socket = socket;
    socket.binaryType = 'arraybuffer';
    socket.addEventListener('open', () => {
      this.missedPongs = 0;
      this._setState('ready');
      this._startHeartbeat();
    });
    socket.addEventListener('message', event => {
      if (typeof event.data !== 'string') return;
      try {
        const message = JSON.parse(event.data);
        if (message.type === 'pong') this.missedPongs = 0;
        this.callbacks.onMessage?.(message);
      } catch {
        this.callbacks.onError?.('AI 返回了无法解析的消息。');
      }
    });
    socket.addEventListener('error', () => {
      this.callbacks.onError?.('无法连接所选本地 AI 通道。');
    });
    socket.addEventListener('close', () => {
      if (this.socket !== socket) return;
      this._stopHeartbeat();
      this.socket = null;
      this._setState('offline');
      if (!this.manualClose) this._scheduleReconnect();
    });
  }

  sendJson(type, sessionId, payload = {}) {
    if (!this.isReady()) return false;
    this.socket.send(JSON.stringify(createEnvelope(type, sessionId, payload)));
    return true;
  }

  sendAudio(buffer) {
    if (!this.isReady() || this.socket.bufferedAmount > MAX_BUFFERED_BYTES) return false;
    this.socket.send(buffer);
    return true;
  }

  isReady() {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  disconnect() {
    this.manualClose = true;
    clearTimeout(this.reconnectTimer);
    this._stopHeartbeat();
    this._closeSocket();
    this._setState('offline');
  }

  _closeSocket() {
    const socket = this.socket;
    this.socket = null;
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close();
  }

  _scheduleReconnect() {
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => {
      if (!this.manualClose && this.endpoint) this.connect(this.endpoint);
    }, 2500);
  }

  _startHeartbeat() {
    this._stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this.missedPongs >= 2) {
        this.callbacks.onError?.('AI 心跳超时，正在重新连接。');
        this.socket?.close();
        return;
      }
      this.missedPongs += 1;
      this.sendJson('ping', null);
    }, 15000);
  }

  _stopHeartbeat() {
    clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = 0;
  }

  _setState(state) {
    this.state = state;
    this.callbacks.onState?.(state);
  }
}

export class VoiceControl {
  constructor(options = {}) {
    this.panel = document.getElementById('voice-panel');
    this.toggleButton = document.getElementById('btn-voice-toggle');
    this.endpointInput = document.getElementById('voice-ai-endpoint');
    this.endpointButtons = [...document.querySelectorAll('[data-voice-endpoint]')];
    this.endpointButtons.forEach(button => {
      const port = Number(button.dataset.voicePort);
      if (port === 3002) button.dataset.voiceEndpoint = GPU_ENDPOINT;
      if (port === 3001) button.dataset.voiceEndpoint = CPU_ENDPOINT;
    });
    this.endpointDescription = document.getElementById('voice-route-description');
    this.reconnectButton = document.getElementById('voice-ai-reconnect');
    this.deviceSelect = document.getElementById('voice-device-select');
    this.micButton = document.getElementById('voice-mic-toggle');
    this.recordButton = document.getElementById('voice-record-toggle');
    this.recordCancelButton = document.getElementById('voice-record-cancel');
    this.textForm = document.getElementById('voice-text-form');
    this.textInput = document.getElementById('voice-text-input');
    this.textSendButton = document.getElementById('voice-text-send');
    this.candidateSimulator = options.candidateSimulator || Object.freeze({
      supports: () => false,
      simulate: () => ({ ok: false, message: '本地模拟器尚未准备好。' })
    });
    this.onPanelOpen = options.onPanelOpen;
    this.onPanelClose = options.onPanelClose;
    this.encoder = new StreamingPcmEncoder();
    this.sessionId = null;
    this.requestMode = null;
    this.recording = false;
    this.starting = false;
    this.recordingStartedAt = 0;
    this.recordingTimer = 0;
    this.recordingLimitTimer = 0;
    this.sessionReadyTimer = 0;
    this.pendingCandidate = null;
    this.finalTranscript = '';
    this.lastSocketErrorAt = 0;
    this.textComposing = false;
    this.compositionEndedAt = Number.NEGATIVE_INFINITY;
    if (this.panel) this.panel.inert = true;

    this.microphone = new MicrophoneManager({
      onState: state => this._renderMicState(state),
      onDevices: (devices, currentDeviceId) => this._renderDevices(devices, currentDeviceId),
      onLevel: level => this._renderLevel(level),
      onSamples: (samples, sampleRate) => this._handleSamples(samples, sampleRate),
      onDeviceLost: () => this._handleDeviceLost()
    });

    this.voiceSocket = new VoiceSocket({
      onState: state => this._renderAiState(state),
      onMessage: message => this._handleVoiceMessage(message),
      onError: message => this._handleSocketError(message)
    });
  }

  init() {
    if (!this.panel || !this.toggleButton) return;

    const storedEndpoint = localStorage.getItem('voiceAiEndpoint');
    const endpointMigrationComplete =
      localStorage.getItem(ENDPOINT_MIGRATION_KEY) === '1';
    const storedEndpointIsValid =
      typeof storedEndpoint === 'string' &&
      /^wss?:\/\//i.test(storedEndpoint);
    const savedEndpoint = endpointMigrationComplete && storedEndpointIsValid
      ? storedEndpoint
      : DEFAULT_ENDPOINT;
    localStorage.setItem(ENDPOINT_MIGRATION_KEY, '1');
    localStorage.setItem('voiceAiEndpoint', savedEndpoint);
    this.endpointInput.value = savedEndpoint;
    this._renderEndpointRoute(savedEndpoint);

    this.toggleButton.addEventListener('click', () => this.togglePanel());
    document.getElementById('voice-panel-close').addEventListener('click', () => this.closePanel());
    this.reconnectButton.addEventListener('click', () => this._connectAi());
    this.endpointButtons.forEach(button => {
      button.addEventListener('click', () => {
        this._selectAiRoute(button.dataset.voiceEndpoint);
      });
    });
    this.micButton.addEventListener('click', () => this._toggleMicrophone());
    this.deviceSelect.addEventListener('change', () => this._changeMicrophone());
    this.recordButton.addEventListener('click', () => {
      if (this.recording || this.starting) this.stopRecording();
      else this.startRecording();
    });
    this.recordCancelButton.addEventListener('click', () => this.cancelRecording());
    this.textForm.addEventListener('submit', event => {
      event.preventDefault();
      this.submitText();
    });
    this.textInput.addEventListener('input', () => {
      this._resizeTextInput();
      this._renderTextComposer();
    });
    this.textInput.addEventListener('compositionstart', () => {
      this.textComposing = true;
      this._renderTextComposer();
    });
    this.textInput.addEventListener('compositionend', () => {
      this.textComposing = false;
      this.compositionEndedAt = performance.now();
      this._renderTextComposer();
    });
    this.textInput.addEventListener('keydown', event => {
      const composing =
        this.textComposing ||
        event.isComposing ||
        event.keyCode === 229 ||
        performance.now() - this.compositionEndedAt < 100;
      if (event.key === 'Enter' && !event.shiftKey && !composing) {
        event.preventDefault();
        this.submitText();
      }
    });
    this.panel.addEventListener('keydown', event => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      this.closePanel();
    });
    document.getElementById('voice-intent-confirm').addEventListener('click', () => this._confirmCandidate());
    document.getElementById('voice-intent-cancel').addEventListener('click', () => this._cancelCandidate());
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden && this.microphone.ready) this.microphone.refreshDevices();
    });
    window.addEventListener('pagehide', () => this.dispose(), { once: true });

    this._renderMicState('off');
    this._renderAiState('offline');
    this._renderTextComposer();
    this._connectAi();
  }

  togglePanel() {
    if (this.panel.classList.contains('open')) this.closePanel();
    else this.openPanel();
  }

  openPanel() {
    this.onPanelOpen?.();
    this.panel.inert = false;
    this.panel.classList.add('open');
    this.panel.setAttribute('aria-hidden', 'false');
    this.toggleButton.setAttribute('aria-expanded', 'true');
    if (!this.voiceSocket.isReady()) this._connectAi();
    if (this.microphone.ready) this.microphone.refreshDevices();
  }

  closePanel() {
    const restoreFocus = this.panel.contains(document.activeElement);
    this.panel.classList.remove('open');
    this.toggleButton.setAttribute('aria-expanded', 'false');
    if (restoreFocus) this.toggleButton.focus();
    this.panel.inert = true;
    this.panel.setAttribute('aria-hidden', 'true');
    this.onPanelClose?.();
  }

  async dispose() {
    clearInterval(this.recordingTimer);
    clearTimeout(this.recordingLimitTimer);
    clearTimeout(this.sessionReadyTimer);
    this.voiceSocket.disconnect();
    await this.microphone.dispose();
  }

  async startRecording() {
    if (this.requestMode !== null) {
      this._showNotice('请等待当前 AI 请求完成。', 'warning');
      return;
    }
    if (this.pendingCandidate) {
      this._showNotice('请先确认或取消当前候选动作。', 'warning');
      return;
    }
    if (!this.microphone.ready) {
      this._showNotice('请先启用并选择麦克风。', 'warning');
      return;
    }
    if (!this.voiceSocket.isReady()) {
      this._showNotice('所选本地 AI 通道未连接，无法发送语音。', 'warning');
      return;
    }

    this.sessionId = createId();
    this.requestMode = 'audio';
    this.encoder.reset(this.microphone.audioContext?.sampleRate || 48000);
    this.starting = true;
    this.finalTranscript = '';
    this._setSessionState('starting', '准备录音');

    const sent = this.voiceSocket.sendJson('session.start', this.sessionId, {
      audio: {
        encoding: 'pcm_s16le',
        sampleRate: TARGET_SAMPLE_RATE,
        channels: 1,
        frameMs: FRAME_MS
      }
    });

    if (!sent) {
      this.starting = false;
      this.requestMode = null;
      this._setSessionState('error', '发送失败');
      this._renderControls();
      return;
    }
    this._renderControls();

    clearTimeout(this.sessionReadyTimer);
    this.sessionReadyTimer = setTimeout(() => {
      if (!this.starting) return;
      this.voiceSocket.sendJson('session.cancel', this.sessionId, { reason: 'ready_timeout' });
      this._abortRecording('AI 未在5秒内准备好录音会话。');
    }, SESSION_READY_TIMEOUT_MS);
  }

  stopRecording(reason = 'user_stop') {
    if (!this.recording && !this.starting) return;
    if (!this.voiceSocket.isReady()) {
      this._abortRecording('AI 连接已中断，录音未发送。');
      return;
    }
    this.starting = false;
    this.recording = false;
    clearInterval(this.recordingTimer);
    clearTimeout(this.recordingLimitTimer);
    clearTimeout(this.sessionReadyTimer);

    for (const frame of this.encoder.flush()) {
      if (!this.voiceSocket.sendAudio(frame)) {
        this._showNotice('音频发送队列过大，录音已停止。', 'error');
        break;
      }
    }

    this.voiceSocket.sendJson('session.stop', this.sessionId, { reason });
    this._setSessionState('processing', '正在识别');
    this._renderControls();
  }

  cancelRecording(reason = 'user_cancel') {
    if (this.requestMode !== 'audio') return;

    if (this.voiceSocket.isReady() && this.sessionId) {
      this.voiceSocket.sendJson('session.cancel', this.sessionId, { reason });
    }

    this._haltRecordingLocally();
    this.requestMode = null;
    this.encoder.reset(this.microphone.audioContext?.sampleRate || 48000);
    this.panel.querySelector('.voice-message--partial')?.remove();
    this._removeThinking();
    this._createMessage(
      'system',
      '本次语音会话已取消。',
      '未继续识别 · 未产生候选动作'
    );
    this._setSessionState('ready', '录音已取消');
    this._renderControls();
  }

  submitText() {
    if (this.textComposing) {
      this._renderTextComposer();
      return;
    }
    const text = this.textInput.value.trim();
    if (!text) {
      this._renderTextComposer();
      return;
    }
    if (text.length > 2000) {
      this._showNotice('文字指令不能超过 2000 个字符。', 'warning');
      return;
    }
    if (this.requestMode !== null) {
      this._showNotice('请等待当前 AI 请求完成。', 'warning');
      return;
    }
    if (this.pendingCandidate) {
      this._showNotice('请先确认或取消当前候选动作。', 'warning');
      return;
    }
    if (!this.voiceSocket.isReady()) {
      this._showNotice('所选本地 AI 通道未连接，文字草稿已保留。', 'warning');
      return;
    }

    this.sessionId = createId();
    this.finalTranscript = text;
    this.requestMode = 'text';
    const sent = this.voiceSocket.sendJson('text.submit', this.sessionId, { text });
    if (!sent) {
      this.requestMode = null;
      this._setSessionState('error', '发送失败');
      this._renderControls();
      return;
    }

    this._createMessage('user', text, '文字指令');
    this.textInput.value = '';
    this._resizeTextInput();
    this._renderThinking();
    this._setSessionState('thinking', 'AI 正在理解');
    this._renderControls();
    this.textInput.focus();
  }

  _connectAi() {
    const requestedEndpoint = this.endpointInput.value.trim();
    const endpoint = /^wss?:\/\//i.test(requestedEndpoint)
      ? requestedEndpoint
      : DEFAULT_ENDPOINT;
    this.endpointInput.value = endpoint;
    localStorage.setItem('voiceAiEndpoint', endpoint);
    this._renderEndpointRoute(endpoint);
    this.voiceSocket.connect(endpoint);
  }

  _selectAiRoute(endpoint) {
    if (this.requestMode !== null || this.pendingCandidate) {
      this._showNotice('请先完成或取消当前 AI 会话，再切换计算路径。', 'warning');
      return;
    }
    this.endpointInput.value = endpoint;
    this._connectAi();
  }

  _renderEndpointRoute(endpoint) {
    this.endpointButtons.forEach(button => {
      const active = button.dataset.voiceEndpoint === endpoint;
      button.dataset.active = String(active);
      button.setAttribute('aria-pressed', String(active));
    });

    if (this.endpointDescription) {
      if (endpoint === GPU_ENDPOINT) {
        this.endpointDescription.textContent = 'GPU 3002 · CUDA / float16';
      } else if (endpoint === CPU_ENDPOINT || endpoint === LEGACY_DEFAULT_ENDPOINT) {
        this.endpointDescription.textContent = 'CPU 3001 · int8 兼容回退';
      } else {
        this.endpointDescription.textContent = '测试或自定义 AI 通道';
      }
    }
  }

  async _toggleMicrophone() {
    if (this.recording || this.starting) {
      this._showNotice('请先停止当前录音。', 'warning');
      return;
    }

    if (this.microphone.ready) {
      await this.microphone.disable();
      return;
    }

    try {
      await this.microphone.enable(this.deviceSelect.value);
      this._showNotice('麦克风已启用，音频仅在点击“开始录音”后发送。', 'success');
    } catch (error) {
      this._renderMicState('error');
      this._showNotice(formatMicError(error), 'error');
      if (error?.name === 'OverconstrainedError') {
        try { await this.microphone.enable(''); } catch {}
      }
    }
  }

  async _changeMicrophone() {
    if (!this.microphone.ready || this.recording || this.starting) return;
    this.deviceSelect.disabled = true;
    try {
      await this.microphone.switchDevice(this.deviceSelect.value);
      this._showNotice('已切换麦克风。', 'success');
    } catch (error) {
      this._showNotice(formatMicError(error), 'error');
    } finally {
      this.deviceSelect.disabled = !this.microphone.ready;
    }
  }

  _handleSamples(samples, sampleRate) {
    if (!this.recording) return;
    if (this.encoder.inputSampleRate !== sampleRate && this.encoder.sequence === 0) {
      this.encoder.reset(sampleRate);
    }
    for (const frame of this.encoder.push(samples)) {
      if (!this.voiceSocket.sendAudio(frame)) {
        this._abortRecording('AI 接收速度不足，录音已安全停止。');
        return;
      }
    }
  }

  _handleVoiceMessage(message) {
    if (message.type !== 'pong' && message.sessionId && message.sessionId !== this.sessionId) return;

    switch (message.type) {
      case 'session.ready':
        clearTimeout(this.sessionReadyTimer);
        this.starting = false;
        this.recording = true;
        this.recordingStartedAt = performance.now();
        this._setSessionState('recording', '正在录音');
        this._renderRecordButton();
        this.recordingTimer = setInterval(() => {
          const elapsed = performance.now() - this.recordingStartedAt;
          document.getElementById('voice-recording-time').textContent = formatDuration(elapsed);
        }, 200);
        this.recordingLimitTimer = setTimeout(() => {
          this.stopRecording('duration_limit');
          this._showNotice('已达到30秒上限，开始识别。', 'warning');
        }, MAX_RECORDING_MS);
        break;

      case 'transcript.partial':
        this._renderPartial(message.payload?.text || '', message.payload?.revision || 0);
        break;

      case 'session.processing':
        if (message.payload?.inputMode === 'text' || this.requestMode === 'text') {
          this._setSessionState('thinking', 'AI 正在理解');
        } else {
          this._setSessionState('processing', '正在识别');
        }
        break;

      case 'transcript.final':
        this.finalTranscript = message.payload?.text || '';
        this._renderFinalTranscript(this.finalTranscript, message.payload?.confidence);
        break;

      case 'assistant.response':
        this._removeThinking();
        this._renderAssistantResponse(message.payload?.text || '');
        break;

      case 'intent.candidate':
        this._removeThinking();
        this.pendingCandidate = message.payload;
        this._renderCandidate(message.payload);
        this._setSessionState('confirm', 'AI 已理解，等待确认');
        break;

      case 'session.completed':
        this.requestMode = null;
        this._removeThinking();
        this._renderControls();
        if (!this.pendingCandidate) this._setSessionState('ready', '可以输入或录音');
        break;

      case 'session.cancelled':
        this.requestMode = null;
        this._removeThinking();
        this._renderControls();
        this._setSessionState('ready', '已取消');
        break;

      case 'error': {
        const code = message.payload?.code || 'UNKNOWN';
        const completionWillFollow =
          code === 'ASR_FAILED' || code === 'LLM_UNAVAILABLE';
        const serverSessionStillActive =
          code === 'BAD_AUDIO_FRAME' || code === 'AUDIO_SEQUENCE_GAP';

        if (
          !completionWillFollow &&
          this.requestMode === 'audio' &&
          (this.recording || this.starting)
        ) {
          this._haltRecordingLocally();
          const waitingForCancel =
            serverSessionStillActive &&
            this.voiceSocket.isReady() &&
            this.voiceSocket.sendJson(
              'session.cancel',
              this.sessionId,
              { reason: 'protocol_error' }
            );
          if (!waitingForCancel) this.requestMode = null;
        } else if (!completionWillFollow) {
          this.starting = false;
          this.requestMode = null;
        }

        this._removeThinking();
        this._renderControls();
        this._setSessionState('error', '协议错误');
        this._showNotice(message.payload?.message || 'Voice Protocol 返回错误。', 'error');
        break;
      }
    }
  }

  _renderAiState(state) {
    const status = document.getElementById('voice-ai-status');
    const led = document.getElementById('voice-toggle-led');
    const labels = {
      offline: 'AI 离线',
      connecting: 'AI 连接中',
      ready: 'AI 已连接'
    };
    status.textContent = labels[state] || state;
    status.dataset.state = state;
    led.dataset.state = state;
    if (state === 'offline' && (this.recording || this.starting)) {
      this._abortRecording('AI 连接已中断，录音已停止。');
    } else if (state === 'offline' && this.requestMode === 'text') {
      this.requestMode = null;
      this._removeThinking();
      this._setSessionState('error', '文字请求已中断');
      this._showNotice('AI 连接已中断，文字草稿之外的请求未重发。', 'error');
    }
    this._renderControls();
  }

  _renderMicState(state) {
    const status = document.getElementById('voice-mic-status');
    const labels = {
      off: '麦克风关闭',
      requesting: '等待授权',
      ready: '麦克风就绪',
      error: '麦克风异常'
    };
    status.textContent = labels[state] || state;
    status.dataset.state = state;
    this.micButton.textContent = state === 'ready' ? '关闭麦克风' : '启用麦克风';
    this.deviceSelect.disabled = state !== 'ready' || this.recording || this.starting;
    this._renderRecordButton();
  }

  _renderDevices(devices, currentDeviceId) {
    const previous = currentDeviceId || this.deviceSelect.value;
    this.deviceSelect.replaceChildren();

    if (devices.length === 0) {
      const option = new Option('未检测到麦克风', '');
      this.deviceSelect.add(option);
      this.deviceSelect.disabled = true;
      return;
    }

    devices.forEach((device, index) => {
      const label = device.label || `麦克风 ${index + 1}`;
      this.deviceSelect.add(new Option(label, device.deviceId));
    });

    if ([...this.deviceSelect.options].some(option => option.value === previous)) {
      this.deviceSelect.value = previous;
    }
    this.deviceSelect.disabled = !this.microphone.ready || this.recording || this.starting;
  }

  _renderLevel(level) {
    const percent = Math.round(level * 100);
    document.getElementById('voice-level-fill').style.width = `${percent}%`;
    document.getElementById('voice-level-value').textContent = `${percent}`;
    this.panel.style.setProperty('--voice-level', `${percent}%`);
  }

  _renderRecordButton() {
    const canStart = this.microphone.ready &&
      this.voiceSocket.isReady() &&
      this.requestMode === null &&
      !this.pendingCandidate &&
      !this.textComposing;
    this.recordButton.disabled =
      !this.recording && !this.starting && !canStart;
    this.recordButton.classList.toggle('is-recording', this.recording || this.starting);
    this.recordButton.querySelector('span:last-child').textContent =
      this.recording || this.starting ? '停止并识别' : '开始录音';
    this.recordCancelButton.disabled = this.requestMode !== 'audio';
    this.deviceSelect.disabled = !this.microphone.ready || this.recording || this.starting;
  }

  _renderTextComposer() {
    const text = this.textInput.value;
    document.getElementById('voice-text-count').textContent =
      `${text.length} / 2000`;
    const canSend =
      text.trim().length > 0 &&
      this.voiceSocket.isReady() &&
      this.requestMode === null &&
      !this.pendingCandidate &&
      !this.textComposing;
    this.textSendButton.disabled = !canSend;
    this.textForm.setAttribute('aria-busy', String(this.requestMode === 'text'));
    this.textSendButton.querySelector('span:first-child').textContent =
      this.requestMode === 'text' ? '处理中' : '发送';
  }

  _renderControls() {
    const routeLocked = this.requestMode !== null || Boolean(this.pendingCandidate);
    this.endpointButtons.forEach(button => {
      button.disabled = routeLocked;
    });
    this.reconnectButton.disabled = routeLocked;
    this._renderRecordButton();
    this._renderTextComposer();
  }

  _resizeTextInput() {
    this.textInput.style.height = 'auto';
    this.textInput.style.height = `${Math.min(this.textInput.scrollHeight, 96)}px`;
  }

  _setSessionState(state, label) {
    const status = document.getElementById('voice-session-status');
    status.textContent = label;
    status.dataset.state = state;
    this.panel.dataset.sessionState = state;
    if (state !== 'recording') {
      document.getElementById('voice-recording-time').textContent = '00:00';
    }
  }

  _renderPartial(text, revision) {
    if (!text) return;
    let message = this.panel.querySelector('.voice-message--partial');
    if (!message) {
      message = this._createMessage('ai', '', '正在识别');
      message.classList.add('voice-message--partial');
    }
    if (revision >= Number(message.dataset.revision || 0)) {
      message.dataset.revision = revision;
      message.querySelector('.voice-message-text').textContent = text;
    }
  }

  _renderFinalTranscript(text, confidence) {
    this.panel.querySelector('.voice-message--partial')?.remove();
    const meta = Number.isFinite(confidence) ? `最终文字 · ${Math.round(confidence * 100)}%` : '最终文字';
    this._createMessage('user', text || '未识别到文字', meta);
  }

  _renderAssistantResponse(text) {
    if (!text) return;
    this._createMessage('ai', text, 'AI 回复');
  }

  _renderThinking() {
    this._removeThinking();
    const message = this._createMessage('ai', '', 'AI 处理中');
    message.classList.add('voice-message--thinking');
    const content = message.querySelector('.voice-message-text');
    for (let index = 0; index < 3; index += 1) {
      const dot = document.createElement('span');
      dot.className = 'voice-thinking-dot';
      content.appendChild(dot);
    }
  }

  _removeThinking() {
    this.panel.querySelector('.voice-message--thinking')?.remove();
  }

  _renderCandidate(candidate) {
    const card = document.getElementById('voice-intent-card');
    const supported = this._isAllowedCandidate(candidate);
    const intentLabel = this._intentLabel(candidate.intent, candidate.args);
    document.getElementById('voice-intent-name').textContent = intentLabel;
    document.getElementById('voice-intent-source').textContent =
      `来自：“${candidate.sourceText || this.finalTranscript || '—'}”`;
    document.getElementById('voice-intent-confidence').textContent =
      Number.isFinite(candidate.confidence) ? `${Math.round(candidate.confidence * 100)}%` : '--';
    const confirmButton = document.getElementById('voice-intent-confirm');
    confirmButton.disabled = !supported;
    confirmButton.textContent = supported ? '确认本地模拟' : '不支持本地模拟';
    card.hidden = false;
    this.panel.classList.add('has-candidate');
  }

  _confirmCandidate() {
    if (!this.pendingCandidate || !this._isAllowedCandidate(this.pendingCandidate)) return;
    try {
      const result = this.candidateSimulator.simulate(this.pendingCandidate) || {};
      if (result.ok === false) {
        this._showNotice(result.message || '本地模拟失败，没有发送控制指令。', 'error');
        return;
      }
      const label = this._intentLabel(this.pendingCandidate.intent, this.pendingCandidate.args);
      this._createMessage(
        'system',
        result.message || `已完成本地模拟：${label}`,
        '仅更新本地 3D 模型和日志 · 未发送至 LUMOS'
      );
      this._resetCandidate();
      this._setSessionState('ready', '本地模拟完成');
    } catch (error) {
      this._showNotice(error?.message || '本地模拟失败，没有发送控制指令。', 'error');
    }
  }

  _cancelCandidate() {
    if (!this.pendingCandidate) return;
    this._createMessage('system', `已取消：${this._intentLabel(this.pendingCandidate.intent, this.pendingCandidate.args)}`, '没有发送控制指令');
    this._resetCandidate();
    this._setSessionState('ready', '可以输入或录音');
  }

  _resetCandidate() {
    this.pendingCandidate = null;
    document.getElementById('voice-intent-card').hidden = true;
    this.panel.classList.remove('has-candidate');
    const confirmButton = document.getElementById('voice-intent-confirm');
    confirmButton.disabled = false;
    confirmButton.textContent = '确认本地模拟';
    this._renderControls();
  }

  _createMessage(role, text, meta) {
    const list = document.getElementById('voice-conversation');
    list.querySelector('.voice-empty')?.remove();

    const message = document.createElement('article');
    message.className = `voice-message voice-message--${role}`;

    const label = document.createElement('div');
    label.className = 'voice-message-meta';
    label.textContent = meta;

    const content = document.createElement('div');
    content.className = 'voice-message-text';
    content.textContent = text;

    message.append(label, content);
    list.appendChild(message);
    list.scrollTop = list.scrollHeight;
    return message;
  }

  _showNotice(message, tone = 'info') {
    this._createMessage('system', message, tone === 'error' ? '需要处理' : '系统提示');
  }

  _handleSocketError(message) {
    const now = Date.now();
    if (now - this.lastSocketErrorAt < 15000) return;
    this.lastSocketErrorAt = now;
    this._showNotice(message, 'error');
  }

  _haltRecordingLocally() {
    this.starting = false;
    this.recording = false;
    clearInterval(this.recordingTimer);
    clearTimeout(this.recordingLimitTimer);
    clearTimeout(this.sessionReadyTimer);
  }

  _abortRecording(message) {
    if (this.requestMode === 'audio' && this.voiceSocket.isReady() && this.sessionId) {
      this.voiceSocket.sendJson('session.cancel', this.sessionId, { reason: 'client_abort' });
    }
    this._haltRecordingLocally();
    this.requestMode = null;
    this._setSessionState('error', '录音已停止');
    this._renderControls();
    if (message) this._showNotice(message, 'error');
  }

  _isAllowedCandidate(candidate) {
    const validator = INTENT_VALIDATORS[candidate?.intent];
    return Boolean(
      validator &&
      validator(candidate?.args || {}) &&
      this.candidateSimulator.supports?.(candidate)
    );
  }

  _intentLabel(intent, args = {}) {
    const labels = {
      'robot.estop': '模拟机械臂停止意图',
      'robot.status': '读取本地模型状态',
      'robot.preset': `本地预览预设位 ${args?.name || ''}`.trim(),
      'gripper.open': '本地预览：打开夹爪',
      'gripper.close': '本地预览：关闭夹爪',
      'gripper.grip': '本地预览：夹取',
      'gripper.set_position': `本地预览：夹爪位置 ${args?.position ?? '--'}`
    };
    return labels[intent] || `不支持的动作：${intent || 'unknown'}`;
  }

  async _handleDeviceLost() {
    this.stopRecording('device_lost');
    this._showNotice('当前麦克风已断开，正在尝试使用默认设备。', 'warning');
    try {
      await this.microphone.enable('');
    } catch (error) {
      this._renderMicState('error');
      this._showNotice(formatMicError(error), 'error');
    }
  }
}
