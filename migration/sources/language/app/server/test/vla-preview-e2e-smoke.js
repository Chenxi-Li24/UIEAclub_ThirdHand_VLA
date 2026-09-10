'use strict';

const assert = require('assert/strict');
const fs = require('fs');
const path = require('path');

const { createGroundingBrowserHandler } = require('../vla/browser-handler');
const { createBrowserCommandRouter } = require('../vla/command-router');
const { validateProviderDecision } = require('../vla/contracts');
const { GroundingService } = require('../vla/grounding');
const { validateAuditEvent } = require('../vla/audit-log');
const { createGroundingUI } = require('../../web/js/grounding-ui.js');

const fixture = JSON.parse(fs.readFileSync(
  path.resolve(__dirname, '../../../tests/fixtures/vla/coke-selection.json'),
  'utf8'
));

class FakeElement {
  constructor() {
    this.value = '';
    this.textContent = '';
    this.disabled = false;
    this.classList = {
      values: new Set(),
      add: value => this.classList.values.add(value),
      remove: value => this.classList.values.delete(value),
      contains: value => this.classList.values.has(value),
    };
    this.listeners = new Map();
  }
  addEventListener(type, listener) { this.listeners.set(type, listener); }
  removeEventListener(type) { this.listeners.delete(type); }
}

function createUI() {
  const ids = [
    'grounding-form', 'grounding-query', 'grounding-submit',
    'grounding-status', 'grounding-result', 'grounding-safety',
  ];
  const elements = Object.fromEntries(ids.map(id => [id, new FakeElement()]));
  const targetElements = new Map(fixture.candidates.map(candidate => [
    candidate.identityId, new FakeElement(),
  ]));
  const root = {
    getElementById: id => elements[id] || null,
    querySelectorAll: selector => selector === '[data-grounding-identity-id]'
      ? [...targetElements.values()] : [],
    querySelector(selector) {
      const match = selector.match(/^\[data-grounding-identity-id="(\d+)"\]$/);
      return match ? targetElements.get(Number(match[1])) || null : null;
    },
  };
  const ui = createGroundingUI({ root, send: () => true });
  ui.handleDetections(fixture.candidates);
  return { ui, targetElements };
}

function evidence() {
  const jpeg = Buffer.from(fixture.jpegBase64, 'base64');
  return {
    vision: {
      frameId: fixture.frameId,
      frameMonotonicNs: fixture.frameMonotonicNs,
      observedAtMs: fixture.observedAtMs,
      candidates: fixture.candidates,
    },
    overlay: {
      frameId: fixture.frameId,
      frameMonotonicNs: fixture.frameMonotonicNs,
      observedAtMs: fixture.observedAtMs,
      imageSha256: fixture.imageSha256,
      jpeg,
    },
  };
}

function providerFor(mode) {
  return {
    providerName: 'fixture',
    modelId: 'fixture-v1',
    select({ evidence: source, signal }) {
      if (mode === 'cancelled') {
        return new Promise((resolve, reject) => {
          signal.addEventListener('abort', () => {
            const error = new Error('request_cancelled');
            error.code = 'request_cancelled';
            reject(error);
          }, { once: true });
        });
      }
      if (mode === 'provider-error') {
        const error = new Error('provider_upstream');
        error.code = 'provider_upstream';
        return Promise.reject(error);
      }
      const raw = mode === 'clarify'
        ? {
          decision: 'clarify', identity_id: null, ambiguous: true,
          explanation: '请说明是瓶装还是罐装可乐。', semantic_score: null,
        }
        : fixture.decision;
      return Promise.resolve({
        decision: validateProviderDecision(raw, new Set(source.allowedIdentityIds)),
        provider: 'fixture', modelId: 'fixture-v1', latencyMs: 5,
        usage: { inputTokens: 10, outputTokens: 5, cachedTokens: 0 },
      });
    },
  };
}

async function runScenario(mode) {
  const motionCounts = {
    robot: 0, gripper: 0, activeView: 0, cameraCommand: 0, graspStart: 0,
  };
  const records = [];
  const source = evidence();
  const nowMs = mode === 'stale' ? fixture.observedAtMs + 2001 : fixture.observedAtMs + 100;
  const service = new GroundingService({
    provider: providerFor(mode),
    auditLog: {
      appendDecision(event) {
        records.push(validateAuditEvent(event));
      },
    },
    getOverlaySnapshot: () => source.overlay,
    getVisionSnapshot: () => source.vision,
    getCurrentVisionSnapshot: () => source.vision,
    nowMs: () => nowMs,
    randomUUID: () => '11111111-1111-4111-8111-111111111111',
    maxAgeMs: 2000,
  });
  const operator = {};
  const events = [];
  const { ui, targetElements } = createUI();
  const handler = createGroundingBrowserHandler({
    grounding: service,
    send: (_target, event) => {
      events.push(event);
      ui.handleState(event);
    },
  });
  const transports = {
    robot: () => { motionCounts.robot += 1; },
    gripper: () => { motionCounts.gripper += 1; },
    activeView: () => { motionCounts.activeView += 1; },
    cameraCommand: () => { motionCounts.cameraCommand += 1; },
    graspStart: () => { motionCounts.graspStart += 1; },
  };
  const router = createBrowserCommandRouter({
    handleGrounding: handler,
    handleLegacy(message) {
      const routes = {
        servo: transports.robot,
        preset: transports.robot,
        gripper: transports.gripper,
        start_active_view: transports.activeView,
        camera_command: transports.cameraCommand,
        grasp_object: transports.graspStart,
      };
      routes[message && message.cmd]?.();
      return { handled: true, accepted: true };
    },
  });
  const command = mode === 'malformed'
    ? { cmd: 'ground_language_target', query: fixture.query, position: [0, 0, 0] }
    : { cmd: 'ground_language_target', query: fixture.query };
  await router(command, operator);
  if (mode === 'cancelled') service.cancel(operator, 'browser_disconnected');
  await new Promise(resolve => setImmediate(resolve));
  return {
    events,
    terminal: events.at(-1),
    audit: records.at(-1) || null,
    highlightedIdentityId: [...targetElements.entries()].find(
      ([, element]) => element.classList.contains('grounding-selected')
    )?.[0] ?? null,
    motionCounts,
  };
}

(async () => {
  const selected = await runScenario('select');
  assert.deepEqual(
    {
      status: selected.terminal.status,
      identityId: selected.terminal.identityId,
      explanation: selected.terminal.explanation,
    },
    { status: 'selected', identityId: 12, explanation: 'ID 12 是可乐瓶。' }
  );
  assert.equal(selected.highlightedIdentityId, 12);
  assert.equal(selected.audit.imageSha256, fixture.imageSha256);
  assert.deepEqual(selected.audit.allowedIdentityIds, [12, 15]);

  const outcomes = [
    selected,
    await runScenario('clarify'),
    await runScenario('malformed'),
    await runScenario('stale'),
    await runScenario('cancelled'),
    await runScenario('provider-error'),
  ];
  assert.deepEqual(outcomes.map(outcome => outcome.terminal.status), [
    'selected', 'clarify', 'rejected', 'error', 'analyzing', 'error',
  ]);
  assert.deepEqual(outcomes[4].audit.decision, 'cancelled');
  for (const outcome of outcomes) {
    assert.deepEqual(outcome.motionCounts, {
      robot: 0, gripper: 0, activeView: 0, cameraCommand: 0, graspStart: 0,
    });
  }

  console.log('PASS VLA preview E2E selects coke ID and keeps every motion path at zero');
})().catch(error => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
