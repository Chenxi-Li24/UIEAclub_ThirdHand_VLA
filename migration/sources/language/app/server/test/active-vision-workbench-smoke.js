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
  'lumos-feed', 'd435-feed', 'system-mode', 'pipeline-stages', 'target-list',
  'global-blockers', 'active-view-state', 'grasp-state', 'event-log',
  'pick-command-form', 'pick-command-query', 'pick-command-status',
]) assert(html.includes(`id="${id}"`), id);

for (const source of [
  '/js/active-vision-store.js', '/js/active-vision-renderer.js',
  '/js/active-vision-actions.js', '/js/active-vision-client.js',
  '/js/pick-command.js',
]) assert(html.includes(source), source);

assert(html.includes('/camera_lumos_vision'));
assert(html.includes('/camera_d435_raw'));
assert(store.includes("fetch('/api/active-vision/status'"));
assert(renderer.includes('graspPointM'));
assert(renderer.includes('identityId'));
assert(actions.includes("cmd: 'start_active_view'"));
assert(actions.includes("cmd: 'confirm_active_view_step'"));
assert(actions.includes("cmd: 'grasp_object'"));
assert(actions.includes('onMoveReady'));
assert(!actions.includes('positionM'));
assert(!actions.includes('joints'));
assert(client.includes('createActiveVisionStore'));
assert(client.includes('createActiveVisionRenderer'));
assert(client.includes('createActiveVisionActions'));
assert(client.includes('createPickCommand'));
assert(pickCommand.includes("cmd: 'start_active_view'"));
assert(pickCommand.includes("cmd: 'grasp_object'"));
assert(pickCommand.includes("cmd: 'confirm_active_view_step'"));

console.log('PASS active-vision workbench is modular, dual-camera, and ID-only');
