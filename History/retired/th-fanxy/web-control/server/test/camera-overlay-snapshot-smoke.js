'use strict';

const assert = require('assert/strict');
const { createHash } = require('crypto');
const { CameraBridge, OverlaySnapshotAssembler } = require('../camera-bridge');

const JPEG = Buffer.from([0xff, 0xd8, 0x54, 0x48, 0x49, 0x52, 0x44, 0xff, 0xd9]);

function mjpeg(jpeg, frameId = 42, monotonicNs = 9_000_000, observedAtMs = 1000) {
  const digest = `sha256:${createHash('sha256').update(jpeg).digest('hex')}`;
  return Buffer.concat([
    Buffer.from(
      '--frame\r\n' +
      'Content-Type: image/jpeg\r\n' +
      `Content-Length: ${jpeg.length}\r\n` +
      `X-Thirdhand-Frame-Id: ${frameId}\r\n` +
      `X-Thirdhand-Monotonic-Ns: ${monotonicNs}\r\n` +
      `X-Thirdhand-Observed-At-Ms: ${observedAtMs}\r\n` +
      `X-Thirdhand-Image-Sha256: ${digest}\r\n\r\n`
    ),
    jpeg,
    Buffer.from('\r\n'),
  ]);
}

function detection(frameId = 42, monotonicNs = 9_000_000, ts = 1000) {
  return {
    type: 'detection_result',
    frame_id: frameId,
    monotonic_ns: monotonicNs,
    ts,
    targets: [],
  };
}

const assembler = new OverlaySnapshotAssembler({ maxJpegBytes: 32 });
assert.equal(assembler.noteDetection(detection()), true);
const stream = mjpeg(JPEG);
for (const chunk of [stream.subarray(0, 3), stream.subarray(3, 17), stream.subarray(17)]) {
  assembler.push(chunk);
}
const first = assembler.latest();
assert.equal(first.frameId, 42);
assert.equal(first.frameMonotonicNs, 9_000_000);
assert.equal(first.observedAtMs, 1000);
assert.match(first.imageSha256, /^sha256:[0-9a-f]{64}$/);
assert.deepEqual(first.jpeg, JPEG);
first.jpeg[0] = 0;
assert.equal(assembler.latest().jpeg[0], 0xff);

const wrongOrder = new OverlaySnapshotAssembler({ maxJpegBytes: 32 });
wrongOrder.push(mjpeg(JPEG));
assert.equal(wrongOrder.noteDetection(detection()), true);
assert.equal(wrongOrder.latest().frameId, 42);

// A delayed/partial old image must never consume a newer detection from fd3.
const reordered = new OverlaySnapshotAssembler({ maxJpegBytes: 32 });
const oldStream = mjpeg(JPEG, 41, 8_900_000, 999);
reordered.push(oldStream.subarray(0, oldStream.length - 3));
assert.equal(reordered.noteDetection(detection(42, 9_000_000, 1000)), true);
reordered.push(Buffer.concat([
  oldStream.subarray(oldStream.length - 3),
  mjpeg(JPEG, 42, 9_000_000, 1000),
]));
assert.equal(reordered.latest().frameId, 42);
assert.equal(reordered.latest().frameMonotonicNs, 9_000_000);

const corrupt = Buffer.from(mjpeg(JPEG));
corrupt[corrupt.indexOf(JPEG) + 3] ^= 0xff;
const integrity = new OverlaySnapshotAssembler({ maxJpegBytes: 32 });
assert.equal(integrity.noteDetection(detection()), true);
integrity.push(corrupt);
assert.equal(integrity.latest(), null);

const oversized = new OverlaySnapshotAssembler({ maxJpegBytes: 8 });
assert.equal(oversized.noteDetection(detection()), true);
oversized.push(mjpeg(JPEG));
assert.equal(oversized.latest(), null);

const malformed = new OverlaySnapshotAssembler({ maxJpegBytes: 32 });
assert.equal(malformed.noteDetection({ ...detection(), frame_id: -1 }), false);
assert.equal(malformed.noteDetection({ ...detection(), monotonic_ns: '9000000' }), false);
assert.equal(malformed.noteDetection({ ...detection(), ts: Number.NaN }), false);
assert.equal(malformed.noteDetection({ ...detection(), ts: 1000.5 }), false);

const bridge = new CameraBridge({ overlaySnapshotMaxJpegBytes: 32 });
const xvisioRawStream = Symbol('xvisio-raw-stream');
bridge.child = { stdio: [null, null, null, null, null, xvisioRawStream] };
assert.equal(bridge.getXVisioRawMjpegStream(), xvisioRawStream);
assert.equal(bridge.getD435RawMjpegStream(), xvisioRawStream);
bridge.child = null;
let eventSeen = false;
bridge.on('detection_result', event => {
  eventSeen = event.frame_id === 55;
});
bridge._handleLine(JSON.stringify(detection(55, 12_000_000, 2000)));
bridge.overlaySnapshots.push(mjpeg(JPEG, 55, 12_000_000, 2000));
assert.equal(eventSeen, true);
assert.equal(bridge.getLatestVisionSnapshot().frameId, 55);
bridge.overlaySnapshots.reset();
assert.equal(bridge.getLatestVisionSnapshot(), null);

console.log('PASS camera bridge pairs detection and overlay only by in-band frame provenance');
