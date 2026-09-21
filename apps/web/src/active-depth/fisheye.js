'use strict';

const CAMERA = Object.freeze({
  fx: 392.5984802, fy: 392.4404297,
  cx: 637.3952637, cy: 641.7739868,
  alpha: 0.6799842119, beta: 0.7471178174,
});
const STREAM_WIDTH = 640;
const STREAM_HEIGHT = 480;

function streamPixelToRay(pixel) {
  if (!Array.isArray(pixel) || pixel.length !== 2 || !pixel.every(Number.isFinite)
      || pixel[0] < 0 || pixel[0] >= STREAM_WIDTH
      || pixel[1] < 0 || pixel[1] >= STREAM_HEIGHT) {
    return { ok: false, reason: 'pixel_out_of_frame' };
  }
  const mx = (2 * pixel[0] - CAMERA.cx) / CAMERA.fx;
  const my = (2 * pixel[1] + 160 - CAMERA.cy) / CAMERA.fy;
  const radiusSquared = mx * mx + my * my;
  const root = 1 - (2 * CAMERA.alpha - 1) * CAMERA.beta * radiusSquared;
  if (root < 0) return { ok: false, reason: 'invalid_ray' };
  const denominator = CAMERA.alpha * Math.sqrt(root) + 1 - CAMERA.alpha;
  const mz = (1 - CAMERA.beta * CAMERA.alpha ** 2 * radiusSquared) / denominator;
  const norm = Math.hypot(mx, my, mz);
  if (!Number.isFinite(norm) || norm <= 1e-15) return { ok: false, reason: 'invalid_ray' };
  return { ok: true, ray: [mx / norm, my / norm, mz / norm] };
}

function rayToStreamPixel(ray) {
  if (!Array.isArray(ray) || ray.length !== 3 || !ray.every(Number.isFinite)) {
    return { ok: false, reason: 'invalid_ray' };
  }
  const [x, y, z] = ray;
  const distance = Math.sqrt(CAMERA.beta * (x*x + y*y) + z*z);
  const denominator = CAMERA.alpha * distance + (1 - CAMERA.alpha) * z;
  const domainWeight = (1 - CAMERA.alpha) / CAMERA.alpha;
  if (!Number.isFinite(distance) || distance <= 1e-15 || denominator <= 1e-15
      || z <= -domainWeight * distance) return { ok: false, reason: 'invalid_ray' };
  const nativeU = CAMERA.fx * x / denominator + CAMERA.cx;
  const nativeV = CAMERA.fy * y / denominator + CAMERA.cy;
  if (nativeU < 0 || nativeU >= 1280 || nativeV < 0 || nativeV >= 1280) {
    return { ok: false, reason: 'outside_camera' };
  }
  const pixel = [nativeU / 2, (nativeV - 160) / 2];
  if (pixel[0] < 0 || pixel[0] >= STREAM_WIDTH || pixel[1] < 0 || pixel[1] >= STREAM_HEIGHT) {
    return { ok: false, reason: 'outside_stream' };
  }
  return { ok: true, pixel };
}

module.exports = { CAMERA, streamPixelToRay, rayToStreamPixel };
