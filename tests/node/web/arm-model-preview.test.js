'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(
  path.resolve(__dirname, '../../../apps/web/public/js/main.js'),
  'utf8',
);
const { ArmModel } = require('../../../apps/web/public/js/robot-viewer').createRobotViewer({
    THREE: {
      Vector3: class Vector3 {
        constructor() {
          this.x = 0;
          this.y = 0;
          this.z = 0;
        }
      },
    },
});

const helperStart = source.indexOf('const DIRECTIONAL_PREVIEW_MAPPING');
const helperEnd = source.indexOf('// === SceneManager ===', helperStart);
assert.ok(helperStart >= 0 && helperEnd > helperStart, 'Language preview helpers are present');
const previewHelpers = vm.runInNewContext(
  source.slice(helperStart, helperEnd) +
    '\n({ manualPreviewMoves, jointLimitWarnings, boundedNumberValidation, BASE_TO_THREE_DIRECTIONS })',
  { console },
);

test('explicit multi-joint preview validates structure without inventing joints', () => {
  const candidate = {
    intent: 'joint.multi',
    payload: { params: { action: 'joint.multi', moves: [
      { joint: 1, deltaDeg: 10 }, { joint: 2, targetDeg: -10 },
    ] } },
  };
  assert.deepEqual(
    JSON.parse(JSON.stringify(previewHelpers.manualPreviewMoves(candidate))),
    candidate.payload.params.moves,
  );
  candidate.payload.params.moves[1].joint = 1;
  assert.equal(previewHelpers.manualPreviewMoves(candidate), null);
});

test('limit preview lists every violating joint with target and range', () => {
  const warnings = previewHelpers.jointLimitWarnings(
    [163, -13, -10, 0, 0, 0],
    [[-162, 162], [-12, 201], [-183, 0], [-98, 98], [-98, 98], [-164, 164]],
    [0, 1, 2, 3, 4, 5],
  );
  assert.equal(warnings.length, 2);
  assert.match(warnings[0], /J1.*163\.0.*-162.*162/);
  assert.match(warnings[1], /J2.*-13\.0.*-12.*201/);
});

test('numeric joint and gripper targets reject invalid and out-of-limit values', () => {
  const validate = previewHelpers.boundedNumberValidation;
  assert.equal(validate('-12', -12, 201, 'J2').valid, true);
  assert.equal(validate('201', -12, 201, 'J2').valid, true);
  assert.equal(validate('-12.1', -12, 201, 'J2').valid, false);
  assert.equal(validate('101', 0, 100, '夹爪开度').valid, false);
  assert.equal(validate('', 0, 100, '夹爪开度').valid, false);
});

test('base axes map robot X forward, Y left and Z up into the Three.js scene', () => {
  assert.deepEqual(
    JSON.parse(JSON.stringify(previewHelpers.BASE_TO_THREE_DIRECTIONS)),
    { x: [1, 0, 0], y: [0, 0, -1], z: [0, 1, 0] },
  );
});

test('lift preview can read end-effector position relative to the robot base', () => {
  const arm = Object.create(ArmModel.prototype);
  let matrixUpdated = false;
  arm.robot = {
    updateWorldMatrix() { matrixUpdated = true; },
    worldToLocal(point) {
      point.x -= 10;
      point.y -= 20;
      point.z -= 30;
      return point;
    },
  };
  arm.endEffector = {
    getWorldPosition(point) {
      point.x = 11;
      point.y = 22;
      point.z = 33;
    },
  };

  assert.equal(typeof arm.getEndEffectorBasePosition, 'function');
  const position = arm.getEndEffectorBasePosition();
  assert.equal(matrixUpdated, true);
  assert.deepEqual([position.x, position.y, position.z], [1000, 2000, 3000]);
});

test('TypeLJ TCP uses the measured flange-to-tool offset', () => {
  const viewerSource=fs.readFileSync(path.resolve(__dirname,'../../../apps/web/public/js/robot-viewer.js'),'utf8');
  assert.match(viewerSource, /tcpOffsetMeters\s*=\s*0\.17334/);
  assert.match(viewerSource, /endEffector\.position\.set\(this\.tcpOffsetMeters, 0, 0\)/);
});

test('measured display preserves out-of-target-range angles and restores URDF edit limits',()=>{
  const arm=Object.create(ArmModel.prototype);
  arm.jointNames=['j1','j2','j3','j4','j5','j6'];arm.jointAngles=[0,0,0,0,0,0];
  arm.jointLimits=[[-162,162],[-12,201],[-183,0],[-98,98],[-98,98],[-164,164]];
  arm.robot={joints:Object.fromEntries(arm.jointNames.map((name,i)=>[name,{ignoreLimits:false,limit:{lower:arm.jointLimits[i][0]*Math.PI/180,upper:arm.jointLimits[i][1]*Math.PI/180},setJointValue(value){this.value=this.ignoreLimits?value:Math.max(this.limit.lower,Math.min(this.limit.upper,value));}}]))};
  const actual=[-1.8,-12.21,-.54,33.04,-5.15,-7.51],limits=JSON.stringify(arm.jointLimits);
  arm.setMeasuredJointAngles(actual);assert.deepEqual(arm.getJointAngles(),actual);
  assert.ok(Math.abs(arm.robot.joints.j2.value+12.21*Math.PI/180)<1e-12);
  assert.ok(Object.values(arm.robot.joints).every(j=>j.ignoreLimits===false));assert.equal(JSON.stringify(arm.jointLimits),limits);
  arm.setJointAngles(actual);assert.equal(arm.getJointAngles()[1],-12);assert.equal(arm.robot.joints.j2.value,-12*Math.PI/180);
  const before=arm.getJointAngles();assert.throws(()=>arm.setMeasuredJointAngles([NaN,0,0,0,0,0]),/Invalid/);assert.deepEqual(arm.getJointAngles(),before);
  arm.robot.joints.j2.setJointValue=()=>{throw Error('renderer failed');};assert.throws(()=>arm.setMeasuredJointAngles(actual),/renderer failed/);assert.equal(arm.robot.joints.j2.ignoreLimits,false);
});
