'use strict';

const assert = require('assert/strict');
const path = require('path');
const { CameraBridge } = require('../camera-bridge');

const previousScript = process.env.CAMERA_BRIDGE_SCRIPT;
const previousExecutable = process.env.XVISIO_STREAM_EXECUTABLE;

try {
  const externalScript = path.resolve('/opt/thirdhand/camera_bridge_va.py');
  process.env.CAMERA_BRIDGE_SCRIPT = externalScript;
  process.env.XVISIO_STREAM_EXECUTABLE = '/opt/thirdhand/xvisio_rgbd_stream';

  const xvisio = new CameraBridge({ python: '/opt/conda/bin/python' }).buildSpawnSpec();
  assert.deepEqual(xvisio.args, ['-u', externalScript]);
  assert.equal(xvisio.stdio.length, 7);
  assert.equal(
    xvisio.env.XVISIO_STREAM_EXECUTABLE,
    '/opt/thirdhand/xvisio_rgbd_stream'
  );

  process.env.CAMERA_BRIDGE_SCRIPT = '/tmp/not-approved.py';
  assert.throws(
    () => new CameraBridge({ python: '/opt/conda/bin/python' }).buildSpawnSpec(),
    /Unsupported camera bridge script/
  );

  delete process.env.CAMERA_BRIDGE_SCRIPT;
  const standard = new CameraBridge({ python: '/opt/conda/bin/python' }).buildSpawnSpec();
  assert.equal(path.basename(standard.args[1]), 'camera_bridge.py');
  assert.equal(standard.stdio.length, 5);
} finally {
  if (previousScript === undefined) delete process.env.CAMERA_BRIDGE_SCRIPT;
  else process.env.CAMERA_BRIDGE_SCRIPT = previousScript;
  if (previousExecutable === undefined) delete process.env.XVISIO_STREAM_EXECUTABLE;
  else process.env.XVISIO_STREAM_EXECUTABLE = previousExecutable;
}

const commandBridge = new CameraBridge({});
const writes = [];
commandBridge.child = {
  stdin: {
    writable: true,
    write: value => writes.push(JSON.parse(value)),
  },
};
assert.equal(commandBridge.send({
  cmd: 'select_bottle',
  side: 'left',
  ordinal: 2,
  request_id: 'selection-1',
}), true);
assert.deepEqual(writes, [{
  cmd: 'select_bottle',
  side: 'left',
  ordinal: 2,
  request_id: 'selection-1',
}]);
assert.equal(commandBridge.send({
  cmd: 'select_bottle',
  side: 'left',
  ordinal: 2,
  request_id: 'selection-2',
  position_m: [999, 999, 999],
}), false);

console.log('PASS camera bridge selects an approved XVisio runtime and bounded commands');
