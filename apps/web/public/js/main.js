console.log('[main.js] Loading modules...');
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { ColladaLoader } from 'three/addons/loaders/ColladaLoader.js';
import { PlanChannel } from './plan-channel.mjs';
import { VoiceControl } from './voice-control.js?v=9';
console.log('[main.js] Modules imported, THREE keys:', Object.keys(THREE).length);

// === SceneManager ===
class SceneManager {
  constructor(container) {
    this.container = container;
    this.scene = null;
    this.camera = null;
    this.renderer = null;
    this.controls = null;
    this.grid = null;
    this.axes = null;
    this.showGrid = true;
    this.showAxes = true;
    this._init();
  }

  _init() {
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;

    this.scene = new THREE.Scene();
    // 背景色跟随 CSS --bg-primary（通过计算样式获取），默认深空色
    const bgColor = this._getComputedBgColor();
    this.scene.background = bgColor;
    this.scene.fog = new THREE.Fog(bgColor.getHex(), 800, 3000);

    this.camera = new THREE.PerspectiveCamera(50, w / h, 1, 5000);
    this.camera.position.set(600, 400, 600);
    this.camera.lookAt(0, 200, 0);

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setSize(w, h);
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.container.appendChild(this.renderer.domElement);

    if (OrbitControls) {
      this.controls = new OrbitControls(this.camera, this.renderer.domElement);
      this.controls.enableDamping = true;
      this.controls.dampingFactor = 0.08;
      this.controls.target.set(0, 250, 0);
      this.controls.minDistance = 200;
      this.controls.maxDistance = 2000;
    }

    this.scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 0.4));

    const dirLight1 = new THREE.DirectionalLight(0xffffff, 0.8);
    dirLight1.position.set(500, 800, 500);
    this.scene.add(dirLight1);

    const dirLight2 = new THREE.DirectionalLight(0xffffff, 0.4);
    dirLight2.position.set(-500, 400, -300);
    this.scene.add(dirLight2);

    const dirLight3 = new THREE.DirectionalLight(0xffffff, 0.3);
    dirLight3.position.set(0, -200, 500);
    this.scene.add(dirLight3);

    this.grid = new THREE.GridHelper(1200, 24, 0x2d3a5c, 0x1a2340);
    this.scene.add(this.grid);

    this.axes = new THREE.AxesHelper(250);
    this.scene.add(this.axes);

    window.addEventListener('resize', () => this._onResize());
    // 监听主题切换更新背景色
    const observer = new MutationObserver(() => this._updateBgColor());
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

    this._animate();
  }

  _getComputedBgColor() {
    const style = getComputedStyle(document.documentElement);
    const bg = style.getPropertyValue('--bg-primary').trim();
    // 解析 css var，从 computedStyle 获取实际值
    const computed = document.documentElement.style.getPropertyValue('--bg-primary');
    if (computed) {
      const el = document.createElement('div');
      el.style.color = computed;
      document.body.appendChild(el);
      const color = getComputedStyle(el).color;
      document.body.removeChild(el);
      const m = color.match(/(\d+),\s*(\d+),\s*(\d+)/);
      if (m) return new THREE.Color(+m[1]/255, +m[2]/255, +m[3]/255);
    }
    return new THREE.Color(0x0a0e1a);
  }

  _updateBgColor() {
    const bgColor = this._getComputedBgColor();
    if (this.scene) {
      this.scene.background = bgColor;
      this.scene.fog.color = bgColor;
    }
  }

  _onResize() {
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  }

  _animate() {
    requestAnimationFrame(() => this._animate());
    if (this.controls) this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  toggleGrid() {
    this.showGrid = !this.showGrid;
    this.grid.visible = this.showGrid;
    return this.showGrid;
  }

  toggleAxes() {
    this.showAxes = !this.showAxes;
    this.axes.visible = this.showAxes;
    return this.showAxes;
  }

  resetView() {
    this.camera.position.set(600, 400, 600);
    if (this.controls) {
      this.controls.target.set(0, 250, 0);
      this.controls.update();
    }
  }
}


// === ArmModel ===
class ArmModel {
  constructor(scene) {
    this.scene = scene;
    this.mount = new THREE.Group();
    this.scene.add(this.mount);
    this.robot = null;
    this.jointAngles = [0, 0, 0, 0, 0, 0];
    this.gripperPosition = 1;
    this.jointNames = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'joint6'];
    this.loaded = false;
    this.installMode = 'floor';
    this.jointLimits = [
      [-162, 162], [-12, 201], [-183, 0],
      [-98, 98], [-98, 98], [-164, 164],
    ];
    this.loadingPromise = this._loadModel();
  }

  async _loadModel() {
    // The bundled URDF loader is UMD, so expose the module build of Three.js to it.
    globalThis.THREE = { ...THREE, STLLoader, ColladaLoader };
    await import('./lib/URDFLoader.js');

    const loader = new globalThis.URDFLoader();
    loader.packages = {
      'FastTouchV3.SLDASM': './models/startouch-v3',
    };
    const robot = await loader.loadAsync('./models/startouch-v3/FastTouchV3.SLDASM.urdf');
    robot.name = 'Startouch FastTouchV3';
    robot.scale.setScalar(1000);
    robot.rotation.x = -Math.PI / 2;
    robot.traverse(object => {
      if (object.isMesh) {
        object.castShadow = true;
        object.receiveShadow = true;
      }
    });

    this.robot = robot;
    this.mount.add(robot);
    this.setJointLimits(this.jointLimits);

    this.endEffector = new THREE.Group();
    this.endEffector.position.set(0.15584, 0, 0);
    robot.links.gripper_base.add(this.endEffector);
    this.loaded = true;
    console.log('[ArmModel] Startouch FastTouchV3 URDF model ready');
  }

  setJointAngles(angles) {
    if (!this.robot || !angles) return;
    const clampedAngles = this.jointAngles.slice();
    for (let i = 0; i < this.jointNames.length && i < angles.length; i++) {
      const [mn, mx] = this.jointLimits[i] || [-180, 180];
      const clamped = Math.max(mn, Math.min(mx, angles[i]));
      this.robot.joints[this.jointNames[i]].setJointValue(clamped * Math.PI / 180);
      clampedAngles[i] = clamped;
    }
    this.jointAngles = clampedAngles;
  }

  getJointAngles() { return this.jointAngles.slice(); }

  setJointLimits(limits) {
    if (!Array.isArray(limits) || limits.length !== 6) return;
    this.jointLimits = limits.map(limit => [Number(limit[0]), Number(limit[1])]);
    if (!this.robot) return;
    this.jointNames.forEach((name, index) => {
      const joint = this.robot.joints[name];
      if (!joint) throw new Error(`URDF joint missing: ${name}`);
      joint.limit.lower = this.jointLimits[index][0] * Math.PI / 180;
      joint.limit.upper = this.jointLimits[index][1] * Math.PI / 180;
    });
    this.setJointAngles(this.jointAngles);
  }

  setGripperPosition(position) {
    if (!this.robot || !Number.isFinite(position)) return;
    this.gripperPosition = Math.max(0, Math.min(1, position));
    const opening = this.gripperPosition * 0.0425;
    this.robot.joints.gripper_joint1?.setJointValue(-opening);
    this.robot.joints.gripper_joint2?.setJointValue(opening);
  }

  getGripperPosition() {
    return this.gripperPosition;
  }

  setInstallMode(mode) {
    if (!this.mount) return;
    this.installMode = mode;
    if (mode === 'floor') {
      this.mount.rotation.set(0, 0, 0);
    } else {
      this.mount.rotation.set(0, 0, Math.PI / 2);
    }
    console.log('[ArmModel] Install mode:', mode);
  }

  goHome() {
    this.setJointAngles(new Array(this.jointNames.length).fill(0));
  }

  getEndEffectorPosition() {
    if (!this.robot) return { x: 0, y: 0, z: 0 };
    const p = new THREE.Vector3();
    if (this.endEffector) this.endEffector.getWorldPosition(p);
    return { x: p.x, y: p.y, z: p.z };
  }
}


// === WSClient ===
class WSClient {
  constructor(pathname = "/ws", label = "WS", protocol = null) {
    this.pathname = pathname;
    this.label = label;
    this.protocol = protocol;
    this.ws = null;
    this.connected = false;
    this.listeners = {};
    this._reconnectDelay = 1000;
    this._maxDelay = 5000;
    this._reconnectTimer = null;
  }

  connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${proto}://${location.host}${this.pathname}`;
    console.log(`[${this.label}] connecting to ${url}...`);

    this.ws = this.protocol ? new WebSocket(url, this.protocol) : new WebSocket(url);

    this.ws.onopen = () => {
      this.connected = true;
      this._reconnectDelay = 1000;
      console.log('[WS] connected');
      this._emit('ws_connection', { connected: true });
    };

    this.ws.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data);
        this._emit('message', data);
        if (data.type) this._emit(data.type, data);
      } catch (e) {
        console.warn('[WS] bad JSON:', e);
      }
    };

    this.ws.onclose = () => {
      this.connected = false;
      console.log('[WS] disconnected');
      this._emit('ws_connection', { connected: false });
      this._scheduleReconnect();
    };

    this.ws.onerror = (err) => {
      console.error('[WS] error:', err);
    };
  }

  _scheduleReconnect() {
    if (this._reconnectTimer) return;
    console.log(`[WS] reconnecting in ${this._reconnectDelay}ms...`);
    this._reconnectTimer = setTimeout(() => {
      this._reconnectTimer = null;
      this._reconnectDelay = Math.min(this._reconnectDelay * 1.5, this._maxDelay);
      this.connect();
    }, this._reconnectDelay);
  }

  send(data) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('[WS] not connected, cannot send');
      return false;
    }
    this.ws.send(JSON.stringify(data));
    return true;
  }

  on(event, callback) {
    if (!this.listeners[event]) this.listeners[event] = [];
    this.listeners[event].push(callback);
  }

  _emit(event, data) {
    const cbs = this.listeners[event];
    if (cbs) cbs.forEach(cb => cb(data));
  }
}


// === UIControls ===
class UIControls {
  constructor(wsClient, visionWsClient, armModel) {
    this.visionWs = visionWsClient;
    this.ws = wsClient;
    this.arm = armModel;
    this.sliders = [];
    this.inputs = [];
    this.syncMode = true;
    this._draggingSlider = false;
    this.presets = {};
    this.robotStateReady = false;
    this.gripperTargetEdited = false;
    this.visionConfigExecutionEnabled = false;
    this.visionTargetExecutionEnabled = false;
    this.selectedVisionTarget = null;
    this.graspMode = 'step';
    this.graspPhase = 'idle';
    this._drawerCollapsed = false;
    this.drawer = null;
    this.logPanel = null;
    this.logButton = null;
    this.gripperSlider = null;
    this.lastRobotState = {
      joints: null,
      gripperPosition: null,
      stateName: null
    };
    this.localVoicePreview = {
      joints: false,
      gripper: false,
      timer: 0,
      baselineJoints: null,
      baselineGripperPosition: null
    };
  }

  build() {
    // ── 构建关节控制区 ────────────────────────────────
    const body = document.getElementById('joint-controls-body');
    if (!body) return;

    const jointNames = this.arm.jointNames || [];
    const limits = this.arm.jointLimits || [];

    for (let i = 0; i < jointNames.length; i++) {
      const sliderMin = Math.ceil(limits[i][0] * 10) / 10;
      const sliderMax = Math.floor(limits[i][1] * 10) / 10;
      const row = document.createElement('div');
      row.className = 'joint-row';
      const label = document.createElement('div');
      label.className = 'joint-label';
      const name = document.createElement('span');
      name.className = 'joint-name';
      name.textContent = jointNames[i];
      const valEl = document.createElement('span');
      valEl.className = 'joint-value';
      valEl.id = `jval-${i}`;
      valEl.textContent = '0.0°';
      label.append(name, valEl);

      const slider = document.createElement('input');
      slider.type = 'range';
      slider.className = 'joint-slider';
      slider.id = `slider-j${i}`;
      slider.min = sliderMin;
      slider.max = sliderMax;
      slider.step = '0.1';
      slider.value = '0';
      row.append(label, slider);
      body.appendChild(row);

      this.sliders.push(slider);
      const defaultVal = 0;
      slider.value = defaultVal;
      valEl.textContent = defaultVal.toFixed(1) + '°';

      slider.addEventListener('pointerdown', () => { this._draggingSlider = true; });
      slider.addEventListener('pointerup', () => { this._draggingSlider = false; });
      slider.addEventListener('pointerleave', () => { this._draggingSlider = false; });
      slider.addEventListener('input', () => {
        this.clearVoicePreview({ restore: true, reason: '手动关节调整' });
        const val = parseFloat(slider.value);
        valEl.textContent = val.toFixed(1) + '°';
        this._updateArm(i, val);
      });
    }

    // ── 绑定各 UI 事件 ─────────────────────────────────

    // 连接按钮
    document.getElementById('btn-connect').addEventListener('click', () => {
      this.clearVoicePreview({ restore: true, reason: '连接机械臂' });
      this.ws.send({ cmd: 'connect' });
      this._log('→ 连接 Startouch SDK (can0)');
      this._setConnStatus('connecting', 'Startouch · can0');
    });

    document.getElementById('btn-disconnect').addEventListener('click', () => {
      this.clearVoicePreview({ restore: true, reason: '断开机械臂' });
      this.ws.send({ cmd: 'disconnect' });
      this._log('→ 断开连接');
      this._setConnStatus('disconnected', '');
    });
    document.getElementById('btn-stop-reconnect').addEventListener('click', () => {
      this.clearVoicePreview({ restore: true, reason: '重新连接机械臂' });
      this.ws.send({ cmd: 'connect' });
      this._log('→ 重新连接 Startouch SDK');
    });

    // 发送按钮
    document.getElementById('btn-send').addEventListener('click', () => {
      this._sendServo();
    });

    // SDK software stop. A hardware E-stop remains a separate safety device.
    document.getElementById('btn-estop-top').addEventListener('click', () => {
      this.clearVoicePreview({ restore: true, reason: '软件停止' });
      this.ws.send({ cmd: 'software_stop' });
      this._log('→ 软件停止并断开 SDK');
    });

    // Move to the all-zero joint pose; this does not redefine robot calibration.
    document.getElementById('btn-home').addEventListener('click', () => {
      this.clearVoicePreview({ restore: true, reason: '手动回零' });
      this.arm.goHome();
      const zeros = new Array(this.arm.jointNames.length).fill(0);
      this.setJointValues(zeros);
      this.ws.send({ cmd: 'preset', name: 'home' });
      this._log('→ Startouch 六轴 0° 姿态');
    });

    // 同步 3D 模型
    document.getElementById('chk-sync').addEventListener('change', (e) => {
      this.syncMode = e.target.checked;
    });

    this.gripperSlider = document.getElementById('gripper-slider');
    const sendGripperValue = value => {
      this.clearVoicePreview({ restore: true, reason: '手动夹爪控制' });
      const position = Math.max(0, Math.min(1, Number(value)));
      this._setGripperTargetValue(position);
      this.gripperTargetEdited = true;
      this.ws.send({ cmd: 'gripper', position });
      this._log(`→ 夹爪 ${(position * 100).toFixed(0)}%`);
    };
    this.gripperSlider.addEventListener('input', () => {
      this.clearVoicePreview({ restore: true, reason: '手动夹爪调整' });
      this.gripperTargetEdited = true;
      this._setGripperTargetValue(Number(this.gripperSlider.value));
    });
    document.getElementById('btn-gripper-close').addEventListener('click', () => {
      sendGripperValue(0);
    });
    document.getElementById('btn-gripper-open').addEventListener('click', () => {
      sendGripperValue(1);
    });
    document.getElementById('btn-gripper-send').addEventListener('click', () => {
      sendGripperValue(this.gripperSlider.value);
    });

    // 抽屉收起/展开
    this.drawer = document.getElementById('control-drawer');
    const handle = document.getElementById('drawer-handle');
    const toggleBtn = document.getElementById('btn-drawer-toggle');

    // handle 固定显示 ◂，仅收起时可见（CSS 控制）
    handle.textContent = '◂';
    handle.addEventListener('click', (e) => {
      e.stopPropagation();
      this.toggleDrawer();
    });
    toggleBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      this.toggleDrawer();
    });

    // section 折叠
    document.querySelectorAll('.sec-header').forEach(header => {
      header.addEventListener('click', () => {
        const section = header.closest('.drawer-section');
        section.classList.toggle('collapsed');
      });
    });

    // 抽屉内视图按钮（暂时禁止冒泡，防止触发视口交互）
    document.getElementById('btn-send').addEventListener('click', e => e.stopPropagation());
    document.getElementById('btn-home').addEventListener('click', e => e.stopPropagation());
    document.querySelectorAll('.sec-header').forEach(h => {
      h.addEventListener('click', e => e.stopPropagation());
    });
    document.querySelectorAll('.joint-slider').forEach(s => {
      s.addEventListener('input', e => e.stopPropagation());
    });

    // 抽屉内连接按钮
    document.getElementById('btn-connect').addEventListener('click', e => e.stopPropagation());
    document.getElementById('btn-disconnect').addEventListener('click', e => e.stopPropagation());

    // 日志面板（按钮在连接栏中）
    this.logPanel = document.getElementById('log-panel');
    this.logButton = document.getElementById('btn-log-toggle');
    this.logButton.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = this.logPanel.classList.toggle('open');
      this.logButton.classList.toggle('active', open);
    });
    document.getElementById('btn-log-close').addEventListener('click', () => this.closeLog());

    // WebSocket 事件监听
    this.ws.on('connection', (data) => {
      this.clearVoicePreview({ restore: false, reason: '连接状态变化' });
      if (data.connected) {
        this.gripperTargetEdited = false;
        this.robotStateReady = false;
        this._setMotionControlsEnabled(false);
        this._setConnStatus('connected', `Startouch · ${data.interface || 'can0'}`);
        const overlay = document.getElementById('estop-overlay');
        overlay.classList.remove('active');
        const hb = document.getElementById('hb-label');
        hb.textContent = 'SDK:OK';
        hb.className = 'hb-label ok';
      } else {
        this.robotStateReady = false;
        this._setMotionControlsEnabled(false);
        this._setConnStatus('disconnected', '');
        const reason = data.error || data.reason;
        if (reason) this._log(`[连接失败] ${reason}`);
        const hb = document.getElementById('hb-label');
        hb.textContent = 'SDK:OFF';
        hb.className = 'hb-label lost';
        // 断开时闪红框
        const app = document.getElementById('app');
        app.classList.remove('disconnected');
        void app.offsetWidth; // reflow
        app.classList.add('disconnected');
        setTimeout(() => app.classList.remove('disconnected'), 1100);
      }
    });

    this.ws.on('config', (data) => {
      this.clearVoicePreview({ restore: false, reason: '控制配置更新' });
      console.log('[UI] config received, presets:', data.presets ? Object.keys(data.presets) : 'none');
      if (data.presets) this._setPresets(data.presets);
      if (data.jointLimits) this._setJointLimits(data.jointLimits);
      this.visionConfigExecutionEnabled = data.visionSafety?.robotExecutionEnabled === true;
      this._updateVisionControls();
      if (data.connection) {
        this.robotStateReady = false;
        this._setMotionControlsEnabled(false);
        this._setConnStatus(
          data.connection.connected ? 'connected' : 'disconnected',
          `Startouch · ${data.connection.interface || 'can0'}`
        );
        const hb = document.getElementById('hb-label');
        hb.textContent = data.connection.connected ? 'SDK:OK' : 'SDK:OFF';
        hb.className = `hb-label ${data.connection.connected ? 'ok' : 'lost'}`;
      }
    });

    this.ws.on('robot_state', (data) => {
      if (data.joints && data.joints.length >= 6) {
        this.lastRobotState.joints = data.joints.slice(0, 6).map(Number);
      }
      if (Number.isFinite(data.gripperPosition)) {
        this.lastRobotState.gripperPosition = Number(data.gripperPosition);
      }
      if (data.stateName) {
        this.lastRobotState.stateName = data.stateName;
      }

      // 更新实时角度
      if (data.joints && data.joints.length >= 6) {
        this.robotStateReady = true;
        this._setMotionControlsEnabled(true);
        this._updateRTAngles(data.joints);
        // 同步滑块
        // Preserve manual slider or local voice preview edits until the
        // operator finishes the interaction.
        if (this.syncMode && !this._draggingSlider && !this.localVoicePreview.joints) {
          this.setJointValues(data.joints);
        }
      }
      // 更新状态徽章
      if (data.stateName) {
        this._updateStateBadge(data.stateName);
      }
      if (Array.isArray(data.tcpPos) && Array.isArray(data.tcpEuler)) {
        this._updateTCP(data.tcpPos, data.tcpEuler);
      }
      if (Number.isFinite(data.gripperPosition)) {
        if (!this.localVoicePreview.gripper) {
          this.arm.setGripperPosition(data.gripperPosition);
        }
        const actual = document.getElementById('gripper-actual');
        if (actual) {
          const distance = Number.isFinite(data.gripperDistanceMm)
            ? ` · ${data.gripperDistanceMm.toFixed(1)} mm`
            : '';
          actual.textContent = `${(data.gripperPosition * 100).toFixed(1)}%${distance}`;
        }
        if (!this.gripperTargetEdited) {
          this._setGripperTargetValue(data.gripperPosition);
        }
      }
    });

    this.ws.on('motion_state', data => {
      if (data.stateName) {
        this._updateStateBadge(data.stateName);
        if (data.stateName === 'MOVING') {
          this.robotStateReady = false;
          this._setMotionControlsEnabled(false);
        }
      }
    });

    this.ws.on('command_status', data => {
      if (data.status !== 'complete') return;
      if (data.command === 'gripper' && Number.isFinite(data.actual_position)) {
        const actual = `${(data.actual_position * 100).toFixed(1)}%`;
        this._log(
          data.reached
            ? `← 夹爪到位 ${actual}`
            : `← 夹爪未到位，反馈 ${actual}${data.moved ? '' : '（未检测到运动）'}`
        );
        return;
      }
      this._log(`← ${data.command} 完成`);
    });

    this.ws.on('software_stop', data => {
      this.clearVoicePreview({ restore: false, reason: '软件停止状态' });
      document.getElementById('estop-overlay').classList.add('active');
      const title = document.getElementById('stop-title');
      const detail = document.getElementById('stop-detail');
      if (data.complete && data.depowered) {
        title.textContent = 'SDK 已停止，电机已失能';
        detail.textContent = '机械臂将下力，请确认安全后重新连接；硬件急停仍需使用独立急停装置';
      } else if (data.depowered === false) {
        title.textContent = '无法确认电机失能';
        detail.textContent = '请立即使用硬件急停并检查 CAN 通信';
      } else {
        title.textContent = '正在停止 SDK';
        detail.textContent = '等待电机失能确认；硬件急停请使用独立急停装置';
      }
      this._log(`← ${data.msg}`);
    });
    this.ws.on('error', (data) => this._log('⚠ ' + data.msg));
    this.ws.on('sdk_log', (data) => this._log(`SDK: ${data.msg}`));

    // ── XVisio vision and grasp controls ──────────────────
    const xvisionFeed = document.getElementById('xvision-feed');
    let xvisionStream = 'vision';
    let xvisionRetryTimer = null;
    let xvisionRetryCount = 0;

    const reloadXVisionFeed = (resetBackoff = false) => {
      if (!xvisionFeed) return;
      if (resetBackoff) xvisionRetryCount = 0;
      if (xvisionRetryTimer) clearTimeout(xvisionRetryTimer);
      xvisionRetryTimer = null;
      xvisionFeed.src = `/camera/xvisio/${xvisionStream}?stream=${Date.now()}`;
    };

    if (xvisionFeed) {
      xvisionFeed.addEventListener('load', () => {
        xvisionRetryCount = 0;
        if (xvisionRetryTimer) clearTimeout(xvisionRetryTimer);
        xvisionRetryTimer = null;
        const dot = document.getElementById('cam-dot');
        const label = document.getElementById('cam-label');
        if (dot) dot.className = 'cam-dot connected';
        if (label) label.textContent = `XVisio: ${xvisionStream === 'vision' ? '识别画面' : '原始画面'}`;
      });
      xvisionFeed.addEventListener('error', () => {
        const dot = document.getElementById('cam-dot');
        const label = document.getElementById('cam-label');
        if (dot) dot.className = 'cam-dot';
        if (label) label.textContent = 'XVisio: 正在重连';
        if (xvisionRetryTimer) return;
        const delayMs = Math.min(1000 * (2 ** xvisionRetryCount), 10000);
        xvisionRetryCount += 1;
        xvisionRetryTimer = setTimeout(() => {
          xvisionRetryTimer = null;
          reloadXVisionFeed();
        }, delayMs);
      });
      reloadXVisionFeed(true);
    }

    document.querySelectorAll('[data-xvision-stream]').forEach(button => {
      button.addEventListener('click', () => {
        xvisionStream = button.dataset.xvisionStream;
        document.querySelectorAll('[data-xvision-stream]').forEach(candidate => {
          const active = candidate === button;
          candidate.classList.toggle('active', active);
          candidate.setAttribute('aria-pressed', String(active));
        });
        reloadXVisionFeed(true);
      });
    });

    this.visionWs.on("detection_result", (data) => {
      const list = document.getElementById('detection-list');
      if (!list) return;
      list.replaceChildren();
      const objects = (data.targets || data.objects || []).map(obj => {
        if (!data.targets) return obj;
        return {
          ...obj,
          id: obj.stableId,
          spatialLabel: `#${obj.stableId}`,
          conf: obj.score,
          leftOrdinal: obj.stableId,
          actionable: false,
          blockers: ["grasp_execution_not_migrated"],
        };
      });
      for (const obj of objects) {
        const item = document.createElement('div');
        item.className = 'detection-item';
        const label = document.createElement('span');
        label.className = 'det-label';
        label.textContent = `${obj.spatialLabel || `#${obj.id}`} ${obj.label}`;
        const confidence = document.createElement('span');
        confidence.className = 'det-conf';
        confidence.textContent = `${(Number(obj.conf) * 100).toFixed(0)}%`;
        const coordinates = document.createElement('div');
        coordinates.className = 'det-coords';
        coordinates.textContent = Array.isArray(obj.position_m)
          ? `base (${obj.position_m.map(value => Number(value).toFixed(3)).join(', ')})m`
          : 'base position unavailable';
        const depth = document.createElement('div');
        depth.className = 'det-depth';
        depth.textContent = obj.depth_m !== null && obj.depth_m !== undefined &&
          Number.isFinite(Number(obj.depth_m))
          ? `depth: ${Number(obj.depth_m).toFixed(3)}m`
          : 'depth: unavailable';
        const actions = document.createElement('div');
        actions.className = 'det-select-actions';
        const actionable = obj.actionable === true;
        item.classList.toggle('selected', obj.selected === true);
        for (const [side, ordinal, prefix] of [
          ['left', obj.leftOrdinal, 'L'],
          ['right', obj.rightOrdinal, 'R'],
        ]) {
          if (!Number.isInteger(ordinal)) continue;
          const btn = document.createElement('button');
          btn.className = 'det-grasp-btn';
          btn.textContent = `${obj.selected ? '已选 ' : '选择 '}${prefix}${ordinal}`;
          btn.addEventListener('click', () => {
            this.visionWs.send({ type: "select_target", stableId: obj.stableId });
            this._log(`→ 选择视觉目标 ${prefix}${ordinal}`);
          });
          actions.appendChild(btn);
        }
        const blockers = [...(obj.blockers || []), ...(obj.reasons || [])];
        if (obj.selected === true) {
          this.selectedVisionTarget = { ...obj, actionable };
          const lock = document.getElementById('vision-lock-reason');
          if (lock) {
            lock.textContent = actionable
              ? `目标 ${obj.spatialLabel || obj.id} 已通过抓取门禁`
              : `夹取锁定：${blockers.join(', ') || 'target_not_actionable'}`;
            lock.classList.toggle('ready', actionable);
          }
        }
        item.append(label, confidence, coordinates, depth, actions);
        list.appendChild(item);
      }
      if (!list.childElementCount) {
        const empty = document.createElement('div');
        empty.className = 'cam-label';
        empty.textContent = 'No objects detected';
        list.appendChild(empty);
      }
      if (!objects.some(obj => obj.selected === true)) {
        this.selectedVisionTarget = null;
      }
      this.visionTargetExecutionEnabled = data.robotExecutionEnabled === true;
      this._updateVisionControls();
    });

    const applyXVisionStatus = (data) => {
      const dot = document.getElementById('cam-dot');
      const label = document.getElementById('cam-label');
      const ready = data.connected === true || data.xvisio_ready === true ||
        data.lumos_ready === true || data.camera_ready === true;
      if (dot) dot.className = `cam-dot ${ready ? 'connected' : ''}`;
      if (label) label.textContent = ready
        ? `XVisio: ${xvisionStream === 'vision' ? '识别画面' : '原始画面'}`
        : `XVisio: ${data.error || '连接中'}`;
    };

    this.ws.on('xvision_connection', applyXVisionStatus);
    this.visionWs.on("runtime_status", data => {
      const cameraReady = data.camera?.status === "ready";
      const inferenceError = data.inference?.status === "error"
        ? data.inference.error : null;
      applyXVisionStatus({
        camera_ready: cameraReady,
        error: data.camera?.error || inferenceError,
      });
      if (cameraReady && inferenceError && xvisionStream === "vision") {
        xvisionStream = "raw";
        document.querySelectorAll("[data-xvision-stream]").forEach(button => {
          const active = button.dataset.xvisionStream === "raw";
          button.classList.toggle("active", active);
          button.setAttribute("aria-pressed", String(active));
        });
        reloadXVisionFeed(true);
        this._log(`⚠ 视觉模型不可用，已切换原始画面: ${inferenceError}`);
      }
    });
    this.ws.on('camera_status', applyXVisionStatus);

    this.ws.on('grasp_status', (data) => {
      this.graspPhase = data.phase || 'idle';
      this._updateVisionControls();
      this._log(`视觉夹取: ${this.graspPhase}${data.reason ? ` (${data.reason})` : ''}`);
    });

    this.visionWs.on("vision_warning", data => {
      this._log("⚠ Vision: " + (data.error || data.stage || "warning"));
    });
    this.ws.on('camera_error', (data) => {
      this._log('⚠ Camera: ' + (data.msg || data.message || 'error'));
    });

    // Camera refresh button
    document.getElementById('btn-camera-refresh')?.addEventListener('click', () => {
      reloadXVisionFeed(true);
    });

    document.querySelectorAll('[data-grasp-mode]').forEach(button => {
      button.addEventListener('click', () => {
        this.graspMode = button.dataset.graspMode;
        document.querySelectorAll('[data-grasp-mode]').forEach(candidate => {
          const active = candidate === button;
          candidate.classList.toggle('active', active);
          candidate.setAttribute('aria-pressed', String(active));
        });
        this._updateVisionControls();
      });
    });
    document.getElementById('btn-grasp-start')?.addEventListener('click', () => {
      this.ws.send({ cmd: 'start_vision_grasp', mode: this.graspMode });
      this._log(`→ ${this.graspMode === 'auto' ? '自动' : '分步'}视觉夹取`);
    });
    document.getElementById('btn-grasp-next')?.addEventListener('click', () => {
      this.ws.send({ cmd: 'advance_vision_grasp' });
      this._log('→ 执行夹取下一步');
    });
    document.getElementById('btn-grasp-cancel')?.addEventListener('click', () => {
      this.ws.send({ cmd: 'cancel_vision_grasp' });
      this._log('→ 取消视觉夹取');
    });

    // 如有预设提前到达，补渲染
    if (Object.keys(this.presets).length) {
      this._setPresets(this.presets);
    }
    this._setMotionControlsEnabled(false);
  }

  _updateVisionControls() {
    const start = document.getElementById('btn-grasp-start');
    const next = document.getElementById('btn-grasp-next');
    const cancel = document.getElementById('btn-grasp-cancel');
    const active = !['idle', 'aborted'].includes(this.graspPhase);
    const targetReady = this.selectedVisionTarget?.actionable === true;
    if (start) {
      start.disabled = active || !this.robotStateReady || !targetReady ||
        !this.visionConfigExecutionEnabled || !this.visionTargetExecutionEnabled;
    }
    if (next) {
      next.disabled = this.graspMode !== 'step' || this.graspPhase !== 'preview_ready';
    }
    if (cancel) cancel.disabled = !active;
  }

  collapseDrawer() {
    if (!this.drawer) this.drawer = document.getElementById('control-drawer');
    this.drawer?.classList.add('collapsed');
    this._drawerCollapsed = true;
  }

  expandDrawer() {
    if (!this.drawer) this.drawer = document.getElementById('control-drawer');
    this.drawer?.classList.remove('collapsed');
    this._drawerCollapsed = false;
  }

  toggleDrawer() {
    if (this._drawerCollapsed) this.expandDrawer();
    else this.collapseDrawer();
  }

  closeLog() {
    if (!this.logPanel) this.logPanel = document.getElementById('log-panel');
    if (!this.logButton) this.logButton = document.getElementById('btn-log-toggle');
    this.logPanel?.classList.remove('open');
    this.logButton?.classList.remove('active');
  }

  appendLocalLog(message) {
    this._log(`[本地模拟 · 未发送至 LUMOS] ${message}`);
  }

  supportsVoiceCandidate(candidate) {
    const intent = candidate?.intent;
    const args = candidate?.args || {};
    if (intent === 'robot.estop' || intent === 'robot.status') return true;
    if (!this.arm.loaded) return false;
    if (intent === 'robot.preset') return args.name === 'home';
    if (['gripper.open', 'gripper.close', 'gripper.grip'].includes(intent)) return true;
    return intent === 'gripper.set_position' &&
      Number.isInteger(args.position) &&
      args.position >= 0 &&
      args.position <= 3800;
  }

  simulateVoiceCandidate(candidate) {
    if (!this.supportsVoiceCandidate(candidate)) {
      return { ok: false, message: '该动作不支持 LUMOS 本地模拟。' };
    }

    const intent = candidate.intent;
    const args = candidate.args || {};
    if (intent === 'robot.status') {
      const joints = this.lastRobotState.joints || this.arm.getJointAngles();
      const state = this.lastRobotState.stateName || 'LOCAL';
      const message = `本地状态 ${state}；关节 ${joints.map(value => `${Number(value).toFixed(1)}°`).join(' / ')}`;
      this.appendLocalLog(message);
      return { ok: true, message };
    }

    if (intent === 'robot.estop') {
      const message = '已模拟“停止”意图；未触发软件停止，也未触发硬件急停。';
      this.appendLocalLog(message);
      return { ok: true, message };
    }

    if (intent === 'robot.preset' && args.name === 'home') {
      const joints = new Array(this.arm.jointNames.length).fill(0);
      this._startVoicePreview({ joints }, 'LUMOS 六轴零位预览');
      return { ok: true, message: '正在本地预览 LUMOS 六轴零位，5 秒后恢复实时模型。' };
    }

    let gripperPosition;
    if (intent === 'gripper.open') gripperPosition = 1;
    if (intent === 'gripper.close' || intent === 'gripper.grip') gripperPosition = 0;
    if (intent === 'gripper.set_position') gripperPosition = args.position / 3800;

    if (Number.isFinite(gripperPosition)) {
      this._startVoicePreview(
        { gripperPosition },
        `LUMOS 夹爪 ${(gripperPosition * 100).toFixed(0)}% 预览`
      );
      return {
        ok: true,
        message: `正在本地预览夹爪 ${(gripperPosition * 100).toFixed(0)}%，5 秒后恢复实时模型。`
      };
    }

    return { ok: false, message: '该动作不支持 LUMOS 本地模拟。' };
  }

  _startVoicePreview(preview, label) {
    clearTimeout(this.localVoicePreview.timer);
    if (!this.localVoicePreview.joints && !this.localVoicePreview.gripper) {
      this.localVoicePreview.baselineJoints = this.arm.getJointAngles();
      this.localVoicePreview.baselineGripperPosition = this.arm.getGripperPosition();
    }
    if (Array.isArray(preview.joints)) {
      this.localVoicePreview.joints = true;
      this.arm.setJointAngles(preview.joints);
      this._updateTCP();
    }
    if (Number.isFinite(preview.gripperPosition)) {
      this.localVoicePreview.gripper = true;
      this.arm.setGripperPosition(preview.gripperPosition);
    }
    const indicator = document.getElementById('voice-preview-indicator');
    const indicatorLabel = document.getElementById('voice-preview-label');
    if (indicatorLabel) indicatorLabel.textContent = label;
    if (indicator) {
      indicator.hidden = false;
      indicator.dataset.previewJoints = String(this.localVoicePreview.joints);
      indicator.dataset.previewGripper = String(this.localVoicePreview.gripper);
    }
    this.appendLocalLog(`${label}；5 秒后恢复实时模型`);
    this.localVoicePreview.timer = setTimeout(() => {
      this.clearVoicePreview({ restore: true, reason: '本地模拟预览结束' });
    }, 5000);
  }

  clearVoicePreview({ restore = true, reason = '' } = {}) {
    const hadPreview = this.localVoicePreview.joints || this.localVoicePreview.gripper;
    clearTimeout(this.localVoicePreview.timer);
    this.localVoicePreview.timer = 0;

    if (restore && this.localVoicePreview.joints && this.lastRobotState.joints) {
      this.arm.setJointAngles(this.lastRobotState.joints);
      this._updateTCP();
    } else if (
      restore &&
      this.localVoicePreview.joints &&
      this.localVoicePreview.baselineJoints
    ) {
      this.arm.setJointAngles(this.localVoicePreview.baselineJoints);
      this._updateTCP();
    }
    if (
      restore &&
      this.localVoicePreview.gripper &&
      Number.isFinite(this.lastRobotState.gripperPosition)
    ) {
      this.arm.setGripperPosition(this.lastRobotState.gripperPosition);
    } else if (
      restore &&
      this.localVoicePreview.gripper &&
      Number.isFinite(this.localVoicePreview.baselineGripperPosition)
    ) {
      this.arm.setGripperPosition(this.localVoicePreview.baselineGripperPosition);
    }

    this.localVoicePreview.joints = false;
    this.localVoicePreview.gripper = false;
    this.localVoicePreview.baselineJoints = null;
    this.localVoicePreview.baselineGripperPosition = null;
    const indicator = document.getElementById('voice-preview-indicator');
    if (indicator) {
      indicator.hidden = true;
      delete indicator.dataset.previewJoints;
      delete indicator.dataset.previewGripper;
    }
    if (hadPreview && reason) this.appendLocalLog(`${reason}，已退出本地预览`);
  }

  _setGripperTargetValue(value) {
    const slider = this.gripperSlider || document.getElementById('gripper-slider');
    const normalized = Math.max(0, Math.min(1, Number(value)));
    if (slider) slider.value = normalized;
    const label = document.getElementById('gripper-value');
    if (label) label.textContent = `${Math.round(normalized * 100)}%`;
  }

  _setMotionControlsEnabled(enabled) {
    [
      'btn-send',
      'btn-home',
      'btn-gripper-send',
      'btn-gripper-close',
      'btn-gripper-open',
    ].forEach(id => {
      const button = document.getElementById(id);
      if (button) button.disabled = !enabled;
    });
    document.querySelectorAll('.preset-btn').forEach(button => {
      button.disabled = !enabled;
    });
  }

  _setConnStatus(mode, info) {
    const dot = document.getElementById('conn-dot');
    const ip = document.getElementById('conn-ip');
    const btnConnect = document.getElementById('btn-connect');
    const btnDisconnect = document.getElementById('btn-disconnect');

    if (mode === 'connected') {
      dot.className = 'conn-dot connected';
      ip.textContent = info;
      btnConnect.style.display = 'none';
      btnDisconnect.style.display = '';
    } else if (mode === 'connecting') {
      dot.className = 'conn-dot connecting';
      ip.textContent = info;
      btnConnect.style.display = '';
      btnConnect.disabled = true;
      btnDisconnect.style.display = 'none';
    } else {
      dot.className = 'conn-dot';
      ip.textContent = '未连接';
      btnConnect.style.display = '';
      btnConnect.disabled = false;
      btnDisconnect.style.display = 'none';
    }
  }

  _updateStateBadge(stateName) {
    const badge = document.getElementById('state-badge');
    if (!badge) return;
    badge.textContent = stateName;
    badge.className = 'state-badge';
    const clsMap = {
      'IDLE': 'idle', 'MOVING': 'moving',
      'E-STOP': 'estop', 'ERROR': 'error', 'LOCKED': 'locked',
    };
    if (clsMap[stateName]) badge.classList.add(clsMap[stateName]);
  }

  _updateRTAngles(joints) {
    for (let i = 0; i < 6; i++) {
      const rt = document.getElementById(`rt-j${i + 1}`);
      if (rt) rt.textContent = `J${i + 1}:${joints[i].toFixed(1)}°`;
      const sj = document.getElementById(`sj${i + 1}`);
      if (sj) sj.textContent = `J${i + 1}:${joints[i].toFixed(1)}°`;
    }
    this._updateTCP();
  }

  _updateTCP(tcpPos, tcpEuler) {
    const modelPosition = this.arm.getEndEffectorPosition();
    const pos = tcpPos || [modelPosition.x, modelPosition.y, modelPosition.z];
    const euler = tcpEuler || [0, 0, 0];
    const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v.toFixed(1); };
    set('tcp-x', Number(pos[0] ?? pos.x)); set('tcp-y', Number(pos[1] ?? pos.y)); set('tcp-z', Number(pos[2] ?? pos.z));
    set('tcp-rx', Number(euler[0])); set('tcp-ry', Number(euler[1])); set('tcp-rz', Number(euler[2]));
    const stcp = document.getElementById('stcp');
    if (stcp) {
      const xyz = [Number(pos[0] ?? pos.x), Number(pos[1] ?? pos.y), Number(pos[2] ?? pos.z)];
      stcp.textContent = `TCP:${xyz.map(value => value.toFixed(0)).join(',')}`;
    }
  }

  _updateArm(index, value) {
    const angles = this.arm.getJointAngles();
    angles[index] = value;
    this.arm.setJointAngles(angles);
    this._updateTCP();
  }

  _sendServo() {
    this.clearVoicePreview({ restore: true, reason: '发送手动关节目标' });
    const joints = this.arm.getJointAngles();
    this.ws.send({ cmd: 'servo', joints: joints });
    this._log(`→ servo ${joints.map(j => j.toFixed(1)).join(' ')}`);
  }

  setJointValues(angles) {
    for (let i = 0; i < 6; i++) {
      if (this.sliders[i]) this.sliders[i].value = angles[i];
      const valEl = document.getElementById(`jval-${i}`);
      if (valEl) valEl.textContent = angles[i].toFixed(1) + '°';
    }
    this.arm.setJointAngles(angles);
    this._updateTCP();
  }

  _setJointLimits(limits) {
    this.arm.setJointLimits(limits);
    limits.forEach((limit, index) => {
      const slider = this.sliders[index];
      if (!slider) return;
      slider.min = Math.ceil(Number(limit[0]) * 10) / 10;
      slider.max = Math.floor(Number(limit[1]) * 10) / 10;
    });
    this.setJointValues(this.arm.getJointAngles());
  }

  _setPresets(presets) {
    this.presets = presets;
    const grid = document.getElementById('preset-grid');
    if (!grid) return;
    grid.innerHTML = '';
    for (const [name, joints] of Object.entries(presets)) {
      const btn = document.createElement('button');
      btn.className = 'preset-btn';
      btn.textContent = name;
      btn.title = joints.map(j => j.toFixed(1)).join(', ');
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.clearVoicePreview({ restore: true, reason: '手动预设控制' });
        this.setJointValues(joints);
        this.ws.send({ cmd: 'preset', name: name });
        this._log(`→ ${name}`);
      });
      grid.appendChild(btn);
    }
  }

  _log(text) {
    const area = document.getElementById('log-area');
    if (!area) return;
    const time = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    const line = document.createElement('div');
    line.className = 'log-line';
    line.textContent = `[${time}] ${text}`;
    area.appendChild(line);
    area.scrollTop = area.scrollHeight;
    while (area.children.length > 100) area.removeChild(area.firstChild);
  }

  bindViewControls(sceneManager) {
    const bind = (id, fn) => {
      const el = document.getElementById(id);
      if (el) el.addEventListener('click', () => fn());
    };

    bind('btn-tool-grid', () => {
      const show = sceneManager.toggleGrid();
      document.getElementById('btn-tool-grid').classList.toggle('active', show);
    });

    bind('btn-tool-axes', () => {
      const show = sceneManager.toggleAxes();
      document.getElementById('btn-tool-axes').classList.toggle('active', show);
    });

    bind('btn-tool-reset', () => sceneManager.resetView());

    bind('btn-tool-floor', () => {
      this.arm.setInstallMode('floor');
      document.getElementById('btn-tool-floor').classList.add('active');
      document.getElementById('btn-tool-wall').classList.remove('active');
    });

    bind('btn-tool-wall', () => {
      this.arm.setInstallMode('wall');
      document.getElementById('btn-tool-wall').classList.add('active');
      document.getElementById('btn-tool-floor').classList.remove('active');
    });

  }
}


// === App Entry ===
function createLocalCandidateSimulator(getUi) {
  return Object.freeze({
    supports(candidate) {
      return Boolean(getUi()?.supportsVoiceCandidate(candidate));
    },
    simulate(candidate) {
      const ui = getUi();
      if (!ui) return { ok: false, message: 'LUMOS 本地模型尚未准备好。' };
      return ui.simulateVoiceCandidate(candidate);
    }
  });
}

function startApp() {
  console.log('[App] ThirdHand Web Control starting...');

  let ui = null;
  const visionWs = new WSClient("/vision", "Vision WS");
  const ws = new WSClient();
  const planWs = new WSClient("/plan", "Plan WS", PlanChannel.protocol);
  const planChannel = new PlanChannel(planWs);
  const voice = new VoiceControl({
    candidateSimulator: createLocalCandidateSimulator(() => ui),
    planChannel,
    onPanelOpen: () => {
      if (ui) {
        ui.closeLog();
        ui.collapseDrawer();
        return;
      }
      document.getElementById('log-panel')?.classList.remove('open');
      document.getElementById('btn-log-toggle')?.classList.remove('active');
      document.getElementById('control-drawer')?.classList.add('collapsed');
    }
  });
  voice.init();

  document.getElementById('btn-log-toggle')?.addEventListener('click', () => {
    voice.closePanel();
  });
  document.getElementById('btn-drawer-toggle')?.addEventListener('click', () => {
    if (window.innerWidth <= 900) voice.closePanel();
  });
  document.getElementById('drawer-handle')?.addEventListener('click', () => {
    if (window.innerWidth <= 900) voice.closePanel();
  });

  const viewport = document.getElementById('three-container');
  const scene = new SceneManager(viewport);
  const arm = new ArmModel(scene.scene);
  ui = new UIControls(ws, visionWs, arm);

  // 主题切换
  const themeSelect = document.getElementById('theme-select');
  if (themeSelect) {
    const saved = localStorage.getItem('theme') || 'deepspace';
    if (saved !== 'deepspace') {
      document.documentElement.setAttribute('data-theme', saved);
    }
    themeSelect.value = saved;
    themeSelect.addEventListener('change', () => {
      const v = themeSelect.value;
      if (v === 'deepspace') document.documentElement.removeAttribute('data-theme');
      else document.documentElement.setAttribute('data-theme', v);
      localStorage.setItem('theme', v);
      // 延迟更新场景背景，等 CSS 变量应用
      setTimeout(() => scene._updateBgColor(), 50);
    });
  }

  arm.loadingPromise.then(() => {
    ui.build();
    ui.bindViewControls(scene);
    visionWs.connect();
    ws.connect();
    planWs.connect();
    arm.setJointAngles([0, 0, 0, 0, 0, 0]);
    ui.setJointValues([0, 0, 0, 0, 0, 0]);
    console.log('[App] Ready.');
  }).catch(e => {
    console.error('[App] Model load failed:', e);
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', startApp);
} else {
  startApp();
}
