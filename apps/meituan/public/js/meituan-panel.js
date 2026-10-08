import { VoiceSocket, MicrophoneManager, StreamingPcmEncoder, VoiceControl } from './voice-control.js?v=12';
import { BatteryVisionUI } from './meituan-vision.js?v=1';

const CAMERA_PATHS = {
  raw: '/camera/xvisio/raw',
  recognition: '/camera/xvisio/vision'
};
const ASR_MODEL = 'paraformer-streaming';
const AUDIO = { encoding: 'pcm_s16le', sampleRate: 16000, channels: 1, frameMs: 100 };

function newSessionId() {
  return globalThis.crypto?.randomUUID?.() || `meituan-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export class MeituanPanel {
  constructor(root = document, options = {}) {
    this.root = root;
    this.closing = false;
    this.robotChannel = options.robotChannel || { isReady: () => false, canConfirm: () => false, send: () => false };
    this.candidateSimulator = options.candidateSimulator || { supports: () => false, simulate: () => ({ ok: false }) };
    this.otherActionPending = options.otherActionPending || (() => false);
    this.pendingCandidate = null;
    this.executionPending = false;
    this.executionCandidateId = null;
    this.candidatePreviewReady = false;
    this.candidatePreviewError = null;
    this.candidatePreviewSummary = null;
    this.ownedCandidateIds = new Set();
    this.panel = root.getElementById('meituan-panel');
    this.toggle = root.getElementById('btn-meituan-toggle');
    this.closeButton = root.getElementById('meituan-panel-close');
    this.handle = root.getElementById('meituan-drag-handle');
    this.camera = root.getElementById('meituan-camera');
    this.cameraStatus = root.getElementById('meituan-camera-status');
    this.cameraLabel = root.getElementById('meituan-camera-label');
    this.rawButton = root.getElementById('meituan-stream-raw');
    this.recognitionButton = root.getElementById('meituan-stream-recognition');
    this.cameraMode = 'raw';
    this.vision = options.batteryVision || new BatteryVisionUI(root);
    this.aiStatus = root.getElementById('meituan-ai-status');
    this.micButton = root.getElementById('meituan-mic-toggle');
    this.conversation = root.getElementById('meituan-conversation');
    this.form = root.getElementById('meituan-text-form');
    this.input = root.getElementById('meituan-text-input');
    this.sendButton = root.getElementById('meituan-text-send');
    this.notice = root.getElementById('meituan-notice');
    this.sessionId = null;
    this.requestMode = null;
    this.starting = false;
    this.recording = false;
    this.pendingVoice = false;
    this.switchRequested = false;
    this.modelStatus = null;
    this.enablingVoice = false;
    this.voiceGeneration = 0;
    this.encoder = new StreamingPcmEncoder();
    this.recordTimer = 0;
    this.prepareTimer = 0;
    this.socket = new VoiceSocket({
      onState: state => this.onSocketState(state),
      onMessage: message => this.onMessage(message),
      onError: message => this.showNotice(message)
    });
    this.microphone = new MicrophoneManager({
      onSamples: (samples, rate) => this.onSamples(samples, rate),
      onDeviceLost: () => this.cancelVoice('麦克风已断开')
    });
  }

  init() {
    if (!this.panel || !this.toggle) return;
    this.toggle.addEventListener('click', () => this.panel.classList.contains('open') ? this.close() : this.open());
    this.closeButton.addEventListener('click', () => this.close());
    this.panel.addEventListener('keydown', event => {
      if (event.key === 'Escape') this.close();
    });
    this.rawButton.addEventListener('click', () => this.setCameraMode('raw'));
    this.recognitionButton.addEventListener('click', () => this.setCameraMode('recognition'));
    this.camera.addEventListener('load', () => {
      if (this.cameraMode === 'raw') this.cameraStatus.textContent = '';
    });
    this.camera.addEventListener('error', () => {
      if (this.cameraMode === 'raw') this.cameraStatus.textContent = '1035 视频暂时不可用';
    });
    this.form.addEventListener('submit', event => {
      event.preventDefault();
      this.submitText();
    });
    this.input.addEventListener('input', () => this.renderControls());
    this.input.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        this.submitText();
      }
    });
    this.micButton.addEventListener('click', () => this.toggleVoice());
    this.root.getElementById('meituan-intent-confirm').addEventListener('click', () => this.confirmCandidate());
    this.root.getElementById('meituan-intent-cancel').addEventListener('click', () => this.cancelCandidate());
    this.root.getElementById('meituan-intent-guide').addEventListener('click', () => this.cancelCandidate('正在生成操作引导；不执行真机动作。', 'guide'));
    this.renderCandidate();
    this.vision.init();
    this.initDrag();
    this.renderControls();
  }

  open() {
    this.closing = false;
    this.panel.classList.add('open');
    this.panel.inert = false;
    this.panel.setAttribute('aria-hidden', 'false');
    this.toggle.setAttribute('aria-expanded', 'true');
    this.vision.open();
    this.setCameraMode(this.cameraMode);
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    this.socket.connect(`${protocol}//${location.host}/voice`);
  }

  setCameraMode(mode) {
    if (!Object.hasOwn(CAMERA_PATHS, mode)) return;
    this.cameraMode = mode;
    for (const [kind, button] of [['raw', this.rawButton], ['recognition', this.recognitionButton]]) {
      button.classList[mode === kind ? 'add' : 'remove']('active');
      button.setAttribute('aria-pressed', String(mode === kind));
    }
    const url = new URL(CAMERA_PATHS[mode], location.href);
    url.port = '1035';
    this.camera.dataset.streamUrl = url.href;
    this.camera.removeAttribute('src');
    this.camera.hidden = mode === 'recognition';
    this.cameraLabel.textContent = mode === 'raw' ? '1035 · 原始视频' : '1035 · 电池识别';
    this.vision.setMode(mode);
    if (mode === 'recognition') return;
    this.cameraStatus.textContent = '正在连接 1035 视频…';
    url.searchParams.set('stream', Date.now());
    this.camera.src = url.href;
  }

  async close() {
    this.closing = true;
    this.vision.close();
    this.cancelCandidate('弹窗已关闭，未确认候选已失效。');
    await this.cancelVoice();
    this.socket.disconnect();
    this.sessionId = null;
    this.requestMode = null;
    this.camera.removeAttribute('src');
    this.panel.classList.remove('open');
    this.panel.inert = true;
    this.panel.setAttribute('aria-hidden', 'true');
    this.toggle.setAttribute('aria-expanded', 'false');
    this.cameraStatus.textContent = '打开面板后连接视频';
  }

  initDrag() {
    let drag = null;
    this.handle.addEventListener('pointerdown', event => {
      if (event.button !== 0 || event.target.closest('button')) return;
      const rect = this.panel.getBoundingClientRect();
      drag = { x: event.clientX, y: event.clientY, left: rect.left, top: rect.top };
      this.handle.setPointerCapture(event.pointerId);
    });
    this.handle.addEventListener('pointermove', event => {
      if (!drag) return;
      const rect = this.panel.getBoundingClientRect();
      this.panel.style.left = `${Math.max(0, Math.min(innerWidth - rect.width, drag.left + event.clientX - drag.x))}px`;
      this.panel.style.top = `${Math.max(0, Math.min(innerHeight - rect.height, drag.top + event.clientY - drag.y))}px`;
    });
    for (const name of ['pointerup', 'pointercancel', 'lostpointercapture']) {
      this.handle.addEventListener(name, () => { drag = null; });
    }
  }

  onSocketState(state) {
    if (state === 'offline') this.cancelCandidate('AI连接中断，未确认候选已失效。');
    this.aiStatus.textContent = state === 'ready' ? 'AI 已连接' : state === 'connecting' ? '连接中' : 'AI 离线';
    this.aiStatus.dataset.state = state;
    if (state === 'ready') this.socket.sendJson('model.list', null);
    else {
      this.modelStatus = null;
      this.switchRequested = false;
    }
    if (state === 'offline' && (this.requestMode || this.pendingVoice || this.enablingVoice)) {
      if (this.requestMode === 'text') this.requestMode = null;
      else this.cancelVoice();
      this.showNotice('AI 连接中断，请重新发送。');
    }
    this.renderControls();
  }

  showNotice(message) { this.notice.textContent = message || ''; }

  appendMessage(kind, content) {
    if (!content) return;
    if (this.conversation.firstElementChild?.tagName === 'P' &&
        !this.conversation.firstElementChild.className) this.conversation.textContent = '';
    const p = document.createElement('p');
    p.className = `from-${kind}`;
    p.textContent = `${kind === 'user' ? '你' : kind === 'ai' ? 'AI' : '系统'}：${content}`;
    this.conversation.appendChild(p);
    this.conversation.scrollTop = this.conversation.scrollHeight;
  }

  submitText() {
    const text = this.input.value.trim();
    if (!text || this.requestMode || this.pendingCandidate || this.executionPending || this.otherActionPending() || !this.socket.isReady()) {
      if (text && !this.socket.isReady()) this.showNotice('3004 未连接，文字草稿已保留。');
      return;
    }
    this.sessionId = newSessionId();
    if (!this.socket.sendJson('text.submit', this.sessionId, { text })) return;
    this.requestMode = 'text';
    this.appendMessage('user', text);
    this.input.value = '';
    this.showNotice('AI 正在回复…');
    this.renderControls();
  }

  async toggleVoice() {
    if (this.enablingVoice || this.pendingVoice || this.recording || this.starting) {
      if (this.recording || this.starting) await this.finishVoice();
      else await this.cancelVoice('语音输入已取消');
      return;
    }
    if (this.requestMode || this.pendingCandidate || this.executionPending || this.otherActionPending()) { this.showNotice('请先完成或取消当前对话和动作。'); return; }
    if (!this.socket.isReady()) { this.showNotice('请先等待 3004 连接。'); return; }
    const generation = ++this.voiceGeneration;
    this.enablingVoice = true;
    this.renderControls();
    try {
      await this.microphone.enable();
    } catch (error) {
      this.enablingVoice = false;
      this.showNotice(error?.message || '麦克风不可用；请用 HTTPS 或 localhost 打开页面并授予权限。');
      await this.microphone.disable();
      return;
    }
    if (generation !== this.voiceGeneration) {
      await this.microphone.disable();
      return;
    }
    this.enablingVoice = false;
    this.renderControls();
    this.pendingVoice = true;
    this.switchRequested = false;
    this.showNotice('正在准备 Paraformer…');
    this.prepareTimer = setTimeout(() => this.cancelVoice('Paraformer 准备超时'), 20000);
    this.ensureParaformer();
    this.renderControls();
  }

  ensureParaformer() {
    if (!this.pendingVoice || !this.socket.isReady()) return;
    if (this.modelStatus?.state === 'READY' && this.modelStatus.activeModelId === ASR_MODEL) {
      clearTimeout(this.prepareTimer);
      this.startVoice();
    } else if (this.modelStatus && !this.switchRequested &&
               !['LOADING', 'SWITCHING'].includes(this.modelStatus.state)) {
      this.switchRequested = this.socket.sendJson('model.select', null, { modelId: 'paraformer-streaming' });
    } else if (!this.modelStatus) {
      this.socket.sendJson('model.list', null);
    }
  }

  startVoice() {
    if (!this.pendingVoice || !this.microphone.ready) return;
    this.pendingVoice = false;
    this.starting = true;
    this.requestMode = 'audio';
    this.sessionId = newSessionId();
    this.encoder.reset(this.microphone.audioContext?.sampleRate || 48000);
    if (!this.socket.sendJson('session.start', this.sessionId, { audio: AUDIO })) {
      this.cancelVoice('语音会话发送失败');
      return;
    }
    this.prepareTimer = setTimeout(() => this.cancelVoice('AI 未准备好录音'), 5000);
    this.showNotice('正在建立录音会话…');
    this.renderControls();
  }

  onSamples(samples, rate) {
    if (!this.recording) return;
    if (this.encoder.sequence === 0 && this.encoder.inputSampleRate !== rate) this.encoder.reset(rate);
    for (const frame of this.encoder.push(samples)) {
      if (!this.socket.sendAudio(frame)) { this.cancelVoice('音频发送过慢，录音已停止'); return; }
    }
  }

  async finishVoice() {
    if (this.recording) {
      for (const frame of this.encoder.flush()) this.socket.sendAudio(frame);
      this.socket.sendJson('session.stop', this.sessionId, { reason: 'user_stop' });
      this.requestMode = 'audio-processing';
      this.showNotice('正在识别并回复…');
    } else if (this.starting) {
      this.socket.sendJson('session.cancel', this.sessionId, { reason: 'user_cancel' });
      this.requestMode = null;
    }
    clearTimeout(this.prepareTimer);
    clearTimeout(this.recordTimer);
    this.pendingVoice = false;
    this.starting = false;
    this.recording = false;
    await this.microphone.disable();
    this.renderControls();
  }

  async cancelVoice(reason = '') {
    this.voiceGeneration += 1;
    this.enablingVoice = false;
    clearTimeout(this.prepareTimer);
    clearTimeout(this.recordTimer);
    if (this.requestMode === 'audio' && this.socket.isReady()) {
      this.socket.sendJson('session.cancel', this.sessionId, { reason: 'panel_cancel' });
    }
    this.pendingVoice = false;
    this.starting = false;
    this.recording = false;
    if (this.requestMode !== 'text') this.requestMode = null;
    await this.microphone.disable();
    if (reason) this.showNotice(reason);
    this.renderControls();
  }

  onMessage(message) {
    if (this.closing) return;
    if (message.type === 'model.list' || message.type === 'model.status') {
      this.modelStatus = message.type === 'model.list' ? message.payload?.status : message.payload;
      if (this.pendingVoice && this.modelStatus?.state === 'ERROR') this.cancelVoice('Paraformer 加载失败');
      else this.ensureParaformer();
      return;
    }
    if (message.sessionId && message.sessionId !== this.sessionId) return;
    switch (message.type) {
      case 'session.ready':
        if (!this.starting) break;
        clearTimeout(this.prepareTimer);
        this.starting = false;
        this.recording = true;
        this.recordTimer = setTimeout(() => this.finishVoice(), 30000);
        this.showNotice('正在录音；再次点击可停止并识别。');
        this.renderControls();
        break;
      case 'transcript.final':
        this.finalTranscript = message.payload?.text || '';
        this.appendMessage('user', message.payload?.text || '');
        break;
      case 'assistant.response':
        this.appendMessage('ai', message.payload?.text || '');
        break;
      case 'intent.candidate':
        this.receiveCandidate(message.payload);
        break;
      case 'session.completed':
      case 'session.cancelled':
        this.requestMode = null;
        if (!this.pendingCandidate && !this.executionPending) this.showNotice('可以继续对话。');
        this.renderControls();
        break;
      case 'error':
        this.showNotice(message.payload?.message || 'AI 请求失败');
        if (this.pendingVoice || this.recording || this.starting) this.cancelVoice();
        else { this.requestMode = null; this.renderControls(); }
        break;
    }
  }


  // Keep P2's allow-list, payload validation and labels; never add another robot executor.
  _isAllowedCandidate(candidate) {
    if (candidate?.skill === 'meituan_battery_pnp@1') {
      const p = candidate.payload?.params;
      return this.candidatePreviewReady && candidate.intent === 'meituan.battery_transfer' &&
        candidate.requiresConfirmation === true && p &&
        Object.keys(p).sort().join(',') === 'destination,source' &&
        ['A','B','C','D'].includes(p.source) && ['T0','P1','P2','P3'].includes(p.destination) &&
        (p.destination !== 'T0' || p.source === 'A');
    }
    return VoiceControl.prototype._isAllowedCandidate.call(this, candidate);
  }

  _intentLabel(intent, params) {
    if (intent === 'meituan.battery_transfer') return `电池 ${params?.source} → ${params?.destination}（整条路线）`;
    return VoiceControl.prototype._intentLabel.call(this, intent, params);
  }

  receiveCandidate(candidate) {
    if (!candidate?.candidateId || !candidate?.traceId || this.pendingCandidate ||
        this.executionPending || this.otherActionPending()) {
      this.showNotice('请先处理当前动作；新候选未注册。');
      return;
    }
    if (!this.robotChannel.isReady()) {
      this.showNotice('3000 控制通道未连接，候选不能执行。');
      return;
    }
    this.ownedCandidateIds.add(candidate.candidateId);
    this.pendingCandidate = candidate;
    this.candidatePreviewReady = false;
    this.candidatePreviewError = null;
    this.candidatePreviewSummary = null;
    if (!this.robotChannel.send({ type: 'skill.candidate', candidate })) {
      this.resetCandidate();
      this.showNotice('候选注册发送失败，未执行动作。');
      return;
    }
    // Preserve P2's existing immediate software-stop exception.
    if (candidate.intent === 'safety.stop.request' && candidate.requiresConfirmation === false) {
      this.executionCandidateId = candidate.candidateId;
      this.executionPending = true;
      this.resetCandidate();
      this.showNotice('已提交软件停止请求；软件停止不等于物理急停。');
      return;
    }
    this.renderCandidate();
    if (candidate.skill === 'meituan_battery_pnp@1') {
      this.showNotice('正在检查整条路线的 SDK 位姿和可达性；尚未运动。');
      this.renderControls();
      return;
    }
    const finish = preview => {
      if (this.pendingCandidate !== candidate) return;
      this.candidatePreviewReady = preview?.ok === true;
      this.candidatePreviewError = this.candidatePreviewReady ? null :
        (preview?.message || '3D 预览未通过，禁止执行。');
      this.renderCandidate();
      this.showNotice(this.candidatePreviewReady ? '已预览，等待人工确认。' : this.candidatePreviewError);
      this.renderControls();
    };
    try {
      const preview = this.candidateSimulator.simulate(candidate);
      if (preview?.then) preview.then(finish).catch(error => finish({ ok: false, message: error?.message }));
      else finish(preview);
    } catch (error) {
      finish({ ok: false, message: error?.message });
    }
    this.renderControls();
  }

  renderCandidate() {
    const candidate = this.pendingCandidate;
    const card = this.root.getElementById('meituan-intent-card');
    card.hidden = !candidate;
    const confirm = this.root.getElementById('meituan-intent-confirm');
    confirm.disabled = !candidate || !this._isAllowedCandidate(candidate) ||
      !this.robotChannel.isReady() || !this.robotChannel.canConfirm() ||
      this.executionPending || this.otherActionPending();
    if (!candidate) return;
    this.root.getElementById('meituan-intent-name').textContent =
      this._intentLabel(candidate.intent, candidate.payload?.params);
    this.root.getElementById('meituan-intent-source').textContent =
      `来自：“${candidate.sourceText || this.finalTranscript || '—'}”`;
    this.root.getElementById('meituan-intent-confidence').textContent =
      Number.isFinite(candidate.confidence) ? `${Math.round(candidate.confidence * 100)}%` : '--';
    const warning = this.root.getElementById('meituan-intent-warning');
    warning.hidden = !(this.candidatePreviewError || this.candidatePreviewSummary);
    warning.textContent = this.candidatePreviewError || this.candidatePreviewSummary || '';
    confirm.textContent = !confirm.disabled ?
      (candidate.skill === 'meituan_battery_pnp@1' ? '确认并执行整条路线' : '确认并执行真机') :
      this.candidatePreviewError ? '预览未通过，禁止执行' : '等待预览或控制状态就绪';
  }

  resetCandidate() {
    this.pendingCandidate = null;
    this.candidatePreviewReady = false;
    this.candidatePreviewError = null;
    this.candidatePreviewSummary = null;
    this.renderCandidate();
    this.renderControls();
  }

  confirmCandidate() {
    const candidate = this.pendingCandidate;
    if (!candidate || this.executionPending || this.otherActionPending() ||
        !this._isAllowedCandidate(candidate)) return;
    if (!this.socket.isReady() || !this.robotChannel.isReady() || !this.robotChannel.canConfirm()) {
      this.renderCandidate();
      this.showNotice('需要3000、SDK、IDLE和新鲜状态全部就绪后才能确认。');
      return;
    }
    // Lock before sending so re-entrant/rapid clicks cannot submit another approval.
    this.executionPending = true;
    this.executionCandidateId = candidate.candidateId;
    if (!this.robotChannel.send({
      type: 'confirmation.decision', candidateId: candidate.candidateId,
      traceId: candidate.traceId, decision: 'approve'
    })) {
      this.executionPending = false;
      this.executionCandidateId = null;
      this.renderCandidate();
      this.showNotice('确认消息发送失败，未执行动作。');
      return;
    }
    this.appendMessage('system', `已确认：${this._intentLabel(candidate.intent, candidate.payload?.params)}；等待真实硬件反馈。`);
    this.resetCandidate();
    this.showNotice('真机执行验证中；尚未报告完成。');
  }

  cancelCandidate(reason = '已取消候选，未发送运动指令。', action = 'reject') {
    const candidate = this.pendingCandidate;
    if (!candidate) return;
    if (this.robotChannel.isReady()) this.robotChannel.send({
      type: 'confirmation.decision', candidateId: candidate.candidateId,
      traceId: candidate.traceId, decision: 'reject'
    });
    if (this.socket.isReady()) this.socket.sendJson('candidate.action', this.sessionId, {
      candidateId: candidate.candidateId, action
    });
    this.candidateSimulator.clear?.(reason);
    this.requestMode = action === 'guide' ? 'candidate' : null;
    this.resetCandidate();
    this.showNotice(reason);
  }

  ownsRobotMessage(message) {
    return this.ownedCandidateIds.has(message?.candidateId);
  }

  handleRobotMessage(message) {
    if (message?.type === 'ws_connection') {
      if (!message.connected) {
        this.cancelCandidate('控制通道断开；候选已失效，请重新发送。');
        if (this.executionPending) {
          this.executionPending = false;
          this.executionCandidateId = null;
          this.showNotice('执行中控制通道断开，结果未知；不会自动重试。');
        }
      }
      this.renderCandidate();
      this.renderControls();
      return;
    }
    if (message?.type === 'runtime-readiness') {
      this.renderCandidate();
      return;
    }
    if (!this.ownsRobotMessage(message)) return;
    if (message.type === 'skill.candidate.preview' &&
        this.pendingCandidate?.skill === 'meituan_battery_pnp@1' &&
        message.candidateId === this.pendingCandidate.candidateId &&
        message.traceId === this.pendingCandidate.traceId) {
      this.candidatePreviewReady = message.ok === true;
      this.candidatePreviewError = message.ok ? null : (message.reason || '路线预览失败');
      this.candidatePreviewSummary = message.ok && typeof message.summary === 'string' && message.summary ?
        '安全段调整：'+message.summary : null;
      this.renderCandidate();
      this.showNotice(message.ok ? '整条路线已检查，等待你确认一次。' : this.candidatePreviewError);
      return;
    }
    if (message.type === 'skill.execution.status') {
      if (message.candidateId === this.executionCandidateId) this.showNotice(message.message || message.step);
      return;
    }
    if (message.type === 'skill.candidate.rejected') {
      this.cancelCandidate(message.message || message.reason || '候选被控制服务拒绝。');
      return;
    }
    if (message.type !== 'skill.result') return;
    this.ownedCandidateIds.delete(message.candidateId);
    if (message.candidateId !== this.executionCandidateId) return;
    this.executionPending = false;
    this.executionCandidateId = null;
    this.candidateSimulator.clear?.('真实执行结果已返回');
    const text = message.message || (message.success === true ?
      '真机动作已验证完成。' : '真机动作失败或结果不确定。');
    this.appendMessage('system', text);
    this.showNotice(text);
    this.renderControls();
  }

  renderControls() {
    this.micButton.setAttribute('aria-pressed', String(this.enablingVoice || this.pendingVoice || this.recording || this.starting));
    this.micButton.textContent = this.recording ? '停止并识别' :
      this.enablingVoice || this.pendingVoice || this.starting ? '取消语音输入' : '开启语音输入';
    this.micButton.disabled = !!this.pendingCandidate || this.executionPending || this.otherActionPending() || (!this.socket.isReady() && !this.enablingVoice && !this.pendingVoice && !this.recording && !this.starting);
    this.sendButton.disabled = !this.socket.isReady() || !!this.requestMode || !!this.pendingCandidate || this.executionPending || this.otherActionPending() || !this.input.value.trim();
  }
}
