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
const start = source.indexOf('class ArmModel {');
const end = source.indexOf('// === WSClient ===', start);
assert.ok(start >= 0 && end > start, 'ArmModel source is present');
const ArmModel = vm.runInNewContext(
  source.slice(start, end) + '\nArmModel',
  {
    THREE: {
      Vector3: class Vector3 {
        constructor() {
          this.x = 0;
          this.y = 0;
          this.z = 0;
        }
      },
    },
    console,
  },
);

const helperStart = source.indexOf('const DIRECTIONAL_PREVIEW_MAPPING');
const helperEnd = source.indexOf('// === SceneManager ===', helperStart);
assert.ok(helperStart >= 0 && helperEnd > helperStart, 'Language preview helpers are present');
const previewHelpers = vm.runInNewContext(
  source.slice(helperStart, helperEnd) + '\n({ manualPreviewMoves, jointLimitWarnings })',
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
  assert.deepEqual([position.x, position.y, position.z], [1, 2, 3]);
});
