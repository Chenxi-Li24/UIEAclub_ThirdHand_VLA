'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.resolve(__dirname, '../../../apps/web/public/js/main.js'), 'utf8',
);
const start = source.indexOf('const DIRECTIONAL_PREVIEW_MAPPING');
const end = source.indexOf('// === SceneManager ===', start);

test('TCP numeric targets convert mm and degrees to SDK units and reject invalid positions', () => {
  assert.match(source, /function tcpTargetFromValues\(/);
  const convert = vm.runInNewContext(source.slice(start, end) + '\ntcpTargetFromValues', { console });
  const valid = convert(['345.1', '209.1', '51.1', '112.8', '89.0', '-158.6']);
  assert.equal(valid.valid, true);
  assert.deepEqual(Array.from(valid.position), [0.3451, 0.2091, 0.0511]);
  assert.ok(Math.abs(valid.euler[0] - 112.8 * Math.PI / 180) < 1e-12);
  assert.equal(convert(['', '209', '51', '0', '0', '0']).valid, false);
  assert.equal(convert(['661', '209', '51', '0', '0', '0']).valid, false);
});

test('the single send action submits the edited TCP pose rather than joint servo', () => {
  const classStart = source.indexOf('class UIControls {');
  const classEnd = source.indexOf('// === App Entry ===', classStart);
  const UIControls = vm.runInNewContext(
    source.slice(start, end) + '\n' + source.slice(classStart, classEnd) + '\nUIControls',
    { console },
  );
  const ui = Object.create(UIControls.prototype);
  assert.equal(typeof ui._sendSelectedTarget, 'function');
  const sent = [];
  ui.ws = { send: command => sent.push(command) };
  ui.activeManualTarget = 'tcp';
  ui.tcpPreviewOk = true;
  ui.tcpInputs = ['345.1', '209.1', '51.1', '112.8', '89.0', '-158.6']
    .map(value => ({ value }));
  ui.lastRobotState = { tcpPos: [345.1, 209.1, 51.1], tcpEuler: [112.8, 89, -158.6], observedAt: Date.now() };
  ui._setRealtimeSync = () => {};
  ui._tcpError = () => {};
  ui._log = () => {};
  ui.clearVoicePreview = () => {};
  ui._sendSelectedTarget();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].cmd, 'move_l');
  assert.deepEqual(Array.from(sent[0].position), [0.3451, 0.2091, 0.0511]);
});

test('TCP inputs keep measured flange feedback when joint model is only a preview', () => {
  const elements = new Map();
  const document = { getElementById(id) {
    if (!elements.has(id)) elements.set(id, {});
    return elements.get(id);
  } };
  const classStart = source.indexOf('class UIControls {');
  const classEnd = source.indexOf('// === App Entry ===', classStart);
  const UIControls = vm.runInNewContext(
    source.slice(start, end) + '\n' + source.slice(classStart, classEnd) + '\nUIControls',
    { console, document },
  );
  const ui = Object.create(UIControls.prototype);
  ui.tcpDraftActive = false;
  ui.lastRobotState = {
    tcpPos: [345.1, 209.1, 51.1], tcpEuler: [112.8, 89, -158.6],
  };
  ui.arm = { getEndEffectorBasePose: () => ({
    positionMm: { x: 999, y: 999, z: 999 },
    eulerDeg: { rx: 0, ry: 0, rz: 0 },
  }) };
  ui._updateTCP();
  assert.equal(elements.get('tcp-x').value, '345.1');
  assert.equal(elements.get('tcp-rz').value, '-158.6');
});

test('separate browser sessions correlate IK preview responses independently', () => {
  const classStart = source.indexOf('class UIControls {');
  const classEnd = source.indexOf('// === App Entry ===', classStart);
  const UIControls = vm.runInNewContext(
    source.slice(start, end) + '\n' + source.slice(classStart, classEnd) + '\nUIControls',
    { console, setTimeout: callback => { callback(); return 1; }, clearTimeout: () => {} },
  );
  const requests = [];
  for (let index = 0; index < 2; index++) {
    const ui = new UIControls({ send: message => requests.push(message) }, null, {});
    ui.robotConnected = true;
    ui.robotStateReady = true;
    ui.tcpInputs = ['345.1', '209.1', '51.1', '0', '0', '0']
      .map(value => ({ value }));
    ui._tcpError = () => {};
    ui._scheduleTcpPreview();
  }
  assert.equal(requests.length, 2);
  assert.equal(requests[0].cmd, 'preview_ik');
  assert.notEqual(requests[0].request_id, requests[1].request_id);
});

test('TCP send rejects missing live pose instead of assuming a two-second move', () => {
  const classStart = source.indexOf('class UIControls {');
  const classEnd = source.indexOf('// === App Entry ===', classStart);
  const UIControls = vm.runInNewContext(
    source.slice(start, end) + '\n' + source.slice(classStart, classEnd) + '\nUIControls',
    { console },
  );
  const ui = Object.create(UIControls.prototype);
  const sent = [];
  ui.ws = { send: command => sent.push(command) };
  ui.tcpPreviewOk = true;
  ui.tcpInputs = ['345.1', '209.1', '51.1', '0', '0', '0']
    .map(value => ({ value }));
  ui.lastRobotState = { tcpPos: null, tcpEuler: null, observedAt: 0 };
  ui._tcpError = () => {};
  ui._log = () => {};
  ui._setRealtimeSync = () => {};
  ui.clearVoicePreview = () => {};
  ui._sendTcp();
  assert.equal(sent.length, 0);
});

test('matching IK preview updates 3D joints while a stale reply is ignored', () => {
  const classStart = source.indexOf('class UIControls {');
  const classEnd = source.indexOf('// === App Entry ===', classStart);
  const UIControls = vm.runInNewContext(
    source.slice(start, end) + '\n' + source.slice(classStart, classEnd) + '\nUIControls',
    { console },
  );
  const ui = Object.create(UIControls.prototype);
  assert.equal(typeof ui._applyTcpPreview, 'function');
  const modelUpdates = [];
  ui.tcpDraftActive = true;
  ui.tcpPreviewRequestId = 'current-preview';
  ui.tcpPreviewOk = false;
  ui._tcpError = () => {};
  ui.setJointValues = joints => modelUpdates.push(Array.from(joints));
  ui._applyTcpPreview({ request_id: 'old-preview', ok: true, joints_deg: [9, 9, 9, 9, 9, 9] });
  assert.equal(modelUpdates.length, 0);
  ui._applyTcpPreview({ request_id: 'current-preview', ok: true, joints_deg: [1, 2, 3, 4, 5, 6] });
  assert.deepEqual(modelUpdates, [[1, 2, 3, 4, 5, 6]]);
  assert.equal(ui.tcpPreviewOk, true);
});

test('leaving a TCP input does not invalidate its successful preview before the first send click', () => {
  const elements = new Map();
  const document = { getElementById(id) {
    if (!elements.has(id)) {
      const listeners = {};
      elements.set(id, {
        value: '345', listeners,
        addEventListener(name, handler) { listeners[name] = handler; },
      });
    }
    return elements.get(id);
  } };
  const classStart = source.indexOf('class UIControls {');
  const classEnd = source.indexOf('// === App Entry ===', classStart);
  const UIControls = vm.runInNewContext(
    source.slice(start, end) + '\n' + source.slice(classStart, classEnd) + '\nUIControls',
    { console, document },
  );
  const ui = Object.create(UIControls.prototype);
  ui.tcpDraftActive = true;
  ui.tcpPreviewOk = true;
  let previews = 0;
  ui._scheduleTcpPreview = () => { previews++; ui.tcpPreviewOk = false; };
  ui._bindTcpInputs();
  elements.get('tcp-x').listeners.change();
  assert.equal(elements.get('tcp-x').value, '345.0');
  assert.equal(previews, 0);
  assert.equal(ui.tcpPreviewOk, true);
});


test('switching from an unexecuted TCP preview to one joint restores the other five measured joints', () => {
  const classStart = source.indexOf('class UIControls {');
  const classEnd = source.indexOf('// === App Entry ===', classStart);
  const UIControls = vm.runInNewContext(
    source.slice(start, end) + '\n' + source.slice(classStart, classEnd) + '\nUIControls',
    { console, clearTimeout: () => {} },
  );
  const ui = Object.create(UIControls.prototype);
  let model = [10, 20, 30, 40, 50, 60];
  ui.arm = {
    getJointAngles: () => [...model],
    setJointAngles: value => { model = [...value]; },
  };
  ui.inputs = Array.from({ length: 6 }, (_, index) => ({ value: String(model[index]) }));
  ui.sliders = Array.from({ length: 6 }, (_, index) => ({ value: String(model[index]) }));
  ui.lastRobotState = { joints: [1, 2, 3, 4, 5, 6] };
  ui.activeManualTarget = 'tcp';
  ui.tcpDraftActive = true;
  ui._updateTCP = () => {};
  ui.setJointValues = angles => {
    model = [...angles];
    ui.inputs.forEach((input, index) => { input.value = String(angles[index]); });
    ui.sliders.forEach((slider, index) => { slider.value = String(angles[index]); });
  };
  ui._updateArm(0, 7);
  assert.deepEqual(model, [7, 2, 3, 4, 5, 6]);
  assert.deepEqual(ui.inputs.map(input => Number(input.value)), [7, 2, 3, 4, 5, 6]);
});

test('manual TCP sends valid target without its former Cartesian duration cap',()=>{
  const classStart=source.indexOf('class UIControls {'),classEnd=source.indexOf('// === App Entry ===',classStart);
  const UIControls=vm.runInNewContext(source.slice(start,end)+'\n'+source.slice(classStart,classEnd)+'\nUIControls',{console});
  const ui=Object.create(UIControls.prototype), sent=[];
  Object.assign(ui,{ws:{send:c=>sent.push(c)},tcpPreviewOk:true,
    tcpInputs:['660','-650','650','0','0','0'].map(value=>({value})),
    lastRobotState:{tcpPos:[150,450,40],tcpEuler:[0,0,0],observedAt:Date.now()},
    _tcpError(){},_log(){},_setRealtimeSync(){},clearVoicePreview(){}});
  ui._sendTcp();
  assert.equal(sent.length,1);
  assert.equal(sent[0].cmd,'move_l');
  assert.equal('time_sec' in sent[0],false);
});
