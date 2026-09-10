'use strict';

const assert = require('assert/strict');
const fs = require('fs');
const path = require('path');

const web = path.resolve(__dirname, '../../web');
const html = fs.readFileSync(path.join(web, 'active-vision.html'), 'utf8');
const client = fs.readFileSync(path.join(web, 'js/active-vision-client.js'), 'utf8');
const store = fs.readFileSync(path.join(web, 'js/active-vision-store.js'), 'utf8');
const renderer = fs.readFileSync(path.join(web, 'js/active-vision-renderer.js'), 'utf8');
const actions = fs.readFileSync(path.join(web, 'js/active-vision-actions.js'), 'utf8');
const pickCommand = fs.readFileSync(path.join(web, 'js/pick-command.js'), 'utf8');

for (const id of [
  'fusion-feed', 'fusion-feed-state', 'system-mode', 'depth-health',
  'depth-source-age', 'depth-readout', 'target-readout',
]) assert(html.includes(`id="${id}"`), id);

for (const source of [
  '/js/active-vision-store.js', '/js/active-vision-renderer.js',
  '/js/active-vision-client.js',
]) assert(html.includes(source), source);

assert(html.includes('/camera_lumos_vision'));
assert.equal((html.match(/<img\b/g) || []).length, 1);
assert(!html.includes('D435'));
assert(!html.includes('双相机'));
assert(store.includes("fetch('/api/active-vision/status'"));
assert(renderer.includes('sourceAgeMs'));
assert(renderer.includes('registeredDepthPoints'));
assert(renderer.includes('graspPointM'));
assert(renderer.includes('identityId'));
assert(client.includes('createActiveVisionStore'));
assert(client.includes('createActiveVisionRenderer'));
assert(client.includes("bindFeed('fusion-feed')"));

console.log('PASS active-vision workbench is one fused RGB-D algorithm view');
