'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { forwardKinematicsPosition, TOOL_OFFSET_M } = require('../../../apps/web/src/language/startouch-forward-kinematics');
const { forwardKinematicsFlangePose } = require('../../../apps/web/src/active-depth/flange-pose');

test('zero-angle flange pose is the sum of URDF origins', () => {
  const pose = forwardKinematicsFlangePose([0, 0, 0, 0, 0, 0]);
  assert.deepEqual(pose.rotation, [[1,0,0],[0,1,0],[0,0,1]]);
  assert.ok(Math.abs(pose.positionM[0] - 0.1275) < 1e-12);
  assert.ok(Math.abs(pose.positionM[2] - 0.17605) < 1e-12);
});

test('flange pose plus tool offset agrees with existing FK', () => {
  for (const joints of [[0,0,0,0,0,0], [10,20,-30,2,-3,4], [-20,40,-45,5,6,-7]]) {
    const pose = forwardKinematicsFlangePose(joints);
    const tool = forwardKinematicsPosition(joints);
    const predicted = pose.positionM.map((component, row) => component +
      pose.rotation[row].reduce((sum, entry, column) => sum + entry*TOOL_OFFSET_M[column], 0));
    assert.ok(Math.hypot(...tool.map((component, index) => component-predicted[index])) < 1e-12);
  }
});

test('flange FK rejects invalid joint state', () => {
  assert.throws(() => forwardKinematicsFlangePose([0,0,0]), /six finite/);
  assert.throws(() => forwardKinematicsFlangePose([0,0,0,0,0,NaN]), /six finite/);
});
