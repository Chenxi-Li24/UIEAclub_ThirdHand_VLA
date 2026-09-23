'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { streamPixelToRay, rayToStreamPixel } = require('../../../apps/web/src/active-depth/fisheye');

test('SEUCM optical center and stream crop round trip', () => {
  const pixel = [637.3952637 / 2, (641.7739868 - 160) / 2];
  const result = streamPixelToRay(pixel);
  assert.equal(result.ok, true);
  assert.ok(Math.abs(result.ray[0]) < 1e-10);
  assert.ok(Math.abs(result.ray[1]) < 1e-10);
  assert.ok(Math.abs(result.ray[2] - 1) < 1e-10);
  assert.deepEqual(rayToStreamPixel(result.ray).pixel.map(Math.round), pixel.map(Math.round));
});

test('SEUCM finite rays round trip across depth ROI and bottle location', () => {
  for (const pixel of [[203,149], [428,149], [203,319], [428,319], [562,327]]) {
    const ray = streamPixelToRay(pixel);
    assert.equal(ray.ok, true, String(pixel));
    const projected = rayToStreamPixel(ray.ray);
    assert.equal(projected.ok, true, String(pixel));
    assert.ok(Math.hypot(projected.pixel[0]-pixel[0], projected.pixel[1]-pixel[1]) < 0.25);
  }
});

test('SEUCM rejects invalid frame pixels and vectors', () => {
  assert.deepEqual(streamPixelToRay([-1, 240]), { ok: false, reason: 'pixel_out_of_frame' });
  assert.deepEqual(streamPixelToRay([NaN, 240]), { ok: false, reason: 'pixel_out_of_frame' });
  assert.deepEqual(rayToStreamPixel([0, 0, 0]), { ok: false, reason: 'invalid_ray' });
});
