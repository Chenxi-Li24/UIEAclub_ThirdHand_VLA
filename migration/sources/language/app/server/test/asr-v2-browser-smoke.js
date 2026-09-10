'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(root, 'web', 'index.html'), 'utf8');
const css = fs.readFileSync(path.join(root, 'web', 'css', 'style.css'), 'utf8');
const js = fs.readFileSync(path.join(root, 'web', 'js', 'voice-control.js'), 'utf8');

test('runtime endpoint card and description are not rendered', () => {
  assert.doesNotMatch(html, /class="voice-route-options"/);
  assert.doesNotMatch(html, /data-voice-endpoint/);
  assert.doesNotMatch(html, /id="voice-route-description"/);
  assert.match(html, /id="voice-ai-reconnect"/);
});

test('ASR V2 renders exactly three approved model buttons and status fields', () => {
  const buttonIds = [...html.matchAll(/data-model-id="([^"]+)"/g)].map(match => match[1]);
  assert.deepEqual(buttonIds, [
    'whisper-small',
    'paraformer-streaming',
    'fun-asr-nano',
  ]);
  for (const id of [
    'voice-asr-state',
    'voice-asr-device',
    'voice-asr-latency',
  ]) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.doesNotMatch(html, /<select[^>]+voice-asr/i);
  assert.match(css, /\.voice-asr-model-options/);
  assert.match(css, /grid-template-columns:\s*repeat\(3/);
  assert.match(html, /Medium/);
  assert.match(html, /Whisper Small/);
  assert.match(html, /Real-time/);
  assert.match(html, /Paraformer CPU/);
  assert.match(html, /High/);
  assert.match(html, /Fun-ASR-Nano/);
});

test('controller requests global status, switches directly, and locks for any recording', () => {
  assert.match(js, /sendJson\('model\.list',\s*null\)/);
  assert.match(js, /sendJson\('model\.select',\s*null,\s*\{\s*modelId/);
  assert.match(js, /case 'model\.list':/);
  assert.match(js, /case 'model\.status':/);
  assert.match(js, /this\.recording\s*\|\|\s*this\.starting/);
  assert.match(js, /Number\(this\.asrModelStatus\.recordingCount\)\s*>\s*0/);
  assert.match(js, /activeModelId/);
  assert.match(js, /lastLatencyMs/);
});

test('streaming partial remains ephemeral and microphone audio is not persisted', () => {
  assert.match(js, /case 'transcript\.partial':/);
  assert.match(js, /case 'transcript\.final':/);
  assert.doesNotMatch(js, /MediaRecorder|indexedDB|localStorage\.setItem\([^)]*audio/i);
});
