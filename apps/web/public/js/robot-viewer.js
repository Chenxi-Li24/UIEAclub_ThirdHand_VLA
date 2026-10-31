/* Reusable Three.js rendering only. No SDK, transport or application bootstrap. */
'use strict';
(function(root,factory){const api={createRobotViewer:factory};if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandRobotViewer=api;})(globalThis,function({THREE,OrbitControls,STLLoader,ColladaLoader,baseDirections,assetBase='.'}={}){
  const BASE_TO_THREE_DIRECTIONS=baseDirections||Object.freeze({x:[1,0,0],y:[0,0,-1],z:[0,1,0]});
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
    const w = this.container.clientWidth || 640;
    const h = this.container.clientHeight || 480;

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

    this.scene.add(new THREE.AmbientLight(0xffffff, 0.7));
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0xd2d7de, 0.65));
    this.viewLightRig = globalThis.ThirdHandCameraLighting.installCameraLighting(THREE, this.scene, this.camera);

    this.grid = new THREE.GridHelper(1200, 24, 0xd8dde4, 0xedf0f4);
    this.scene.add(this.grid);

    this.axes = new THREE.Group();
    this.axes.name = 'startouch-base-coordinate-axes';
    const baseAxisLength = 250;
    const baseAxisHeadLength = 24;
    const baseAxisHeadWidth = 12;
    [
      ['x', 0xff4545],
      ['y', 0x45d483],
      ['z', 0x438cff],
    ].forEach(([axis, color]) => {
      const direction = BASE_TO_THREE_DIRECTIONS[axis];
      this.axes.add(new THREE.ArrowHelper(
        new THREE.Vector3(...direction),
        new THREE.Vector3(0, 0, 0),
        baseAxisLength,
        color,
        baseAxisHeadLength,
        baseAxisHeadWidth,
      ));
    });
    this.scene.add(this.axes);

    window.addEventListener('resize', () => this._onResize());
    this.resizeObserver = new ResizeObserver(() => this._onResize());
    this.resizeObserver.observe(this.container);
    // 监听主题切换更新背景色
    const observer = new MutationObserver(() => this._updateBgColor());
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

    this._animate();
  }

  _getComputedBgColor() {
    return globalThis.ThirdHandCameraLighting.sceneBackground(THREE, getComputedStyle(document.documentElement));
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
    if (w < 1 || h < 1) return;
    const changed = w !== this.viewWidth || h !== this.viewHeight;
    this.viewWidth = w; this.viewHeight = h;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
    if (changed && this.modelObject) this.fitModel();
  }

  fitModel(object = this.modelObject) {
    if (!object) return;
    this.modelObject = object;
    globalThis.ThirdHandCameraLighting.frameCamera(THREE, this.camera, this.controls, object);
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
    if (this.modelObject) { this.fitModel(); return; }
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
    this.tcpOffsetMeters = 0.17334;
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

    const manager = new THREE.LoadingManager();
    this.geometryReady = new Promise(resolve => { manager.onLoad = resolve; });
    const loader = new globalThis.URDFLoader(manager);
    globalThis.ThirdHandCameraLighting.configureModelMaterials(loader);
    loader.packages = {
      'FastTouchV3.SLDASM': `${assetBase}/models/startouch-v3`,
    };
    const robot = await loader.loadAsync(`${assetBase}/models/startouch-v3/FastTouchV3.SLDASM.urdf`);
    robot.name = 'Startouch FastTouchV3';
    robot.scale.setScalar(1000);
    robot.rotation.x = -Math.PI / 2;

    this.robot = robot;
    this.mount.add(robot);
    this.setJointLimits(this.jointLimits);

    this.endEffector = new THREE.Group();
    this.endEffector.name = 'type-lj-tcp';
    this.endEffector.position.set(this.tcpOffsetMeters, 0, 0);
    this.tcpAxes = new THREE.AxesHelper(0.08);
    this.tcpAxes.name = 'type-lj-tcp-axes';
    this.endEffector.add(this.tcpAxes);
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

  getEndEffectorBasePosition() {
    if (!this.robot || !this.endEffector) return { x: 0, y: 0, z: 0 };
    this.robot.updateWorldMatrix(true, true);
    const position = new THREE.Vector3();
    this.endEffector.getWorldPosition(position);
    this.robot.worldToLocal(position);
    return { x: position.x * 1000, y: position.y * 1000, z: position.z * 1000 };
  }

  getEndEffectorBaseEuler() {
    if (!this.robot || !this.endEffector) return { rx: 0, ry: 0, rz: 0 };
    this.robot.updateWorldMatrix(true, true);
    const robotQuaternion = new THREE.Quaternion();
    const tcpQuaternion = new THREE.Quaternion();
    this.robot.getWorldQuaternion(robotQuaternion);
    this.endEffector.getWorldQuaternion(tcpQuaternion);
    const relativeQuaternion = robotQuaternion.invert().multiply(tcpQuaternion);
    const euler = new THREE.Euler().setFromQuaternion(relativeQuaternion, 'XYZ');
    return {
      rx: THREE.MathUtils.radToDeg(euler.x),
      ry: THREE.MathUtils.radToDeg(euler.y),
      rz: THREE.MathUtils.radToDeg(euler.z),
    };
  }

  getEndEffectorBasePose() {
    return {
      positionMm: this.getEndEffectorBasePosition(),
      eulerDeg: this.getEndEffectorBaseEuler(),
    };
  }
}



return {SceneManager,ArmModel};
});
