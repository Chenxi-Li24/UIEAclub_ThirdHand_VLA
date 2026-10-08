'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const {
  TcpCalibrationSession,
} = require('../../../apps/web/src/tcp-calibration/session');

const ROOT = path.resolve(__dirname, '../../..');
const FIXTURE = JSON.parse(fs.readFileSync(
  path.join(ROOT, 'tests/fixtures/tcp-calibration/reference-pivot.json'), 'utf8',
));
const POLICY = `sha256:${'a'.repeat(64)}`;
const THRESHOLDS = {
  fitRmsGreenM: 0.002, fitMaximumGreenM: 0.004, fitRmsMaximumM: 0.003,
  fitMaximumM: 0.005, validationMaximumM: 0.005,
};

function startCommand(requestId = 'start-1') {
  return {
    type: 'start', requestId, operator: 'operator-a',
    measurement: { distanceM: 0.020, uncertaintyM: 0.001, toolAxisFlange: [1, 0, 0] },
    confirmations: {
      probeCentered: true, pivotFixed: true, estopReady: true, manualTeachOnly: true,
    },
  };
}

function harness({ solveClassification = 'green', validationMaximum = 0.001 } = {}) {
  let snapshot = null;
  let identifier = 0;
  const calls = [];
  const stateSource = { snapshot: () => snapshot };
  const solver = async request => {
    calls.push(structuredClone(request));
    if (request.operation === 'solve') return {
      schema: 'thirdhand-tcp-pivot-solve-v1',
      accepted: solveClassification !== 'red', classification: solveClassification,
      probe_tip_flange_m: FIXTURE.known_probe_tip_flange_m,
      fixed_point_base_m: FIXTURE.known_fixed_point_base_m,
      sample_ids: request.fit_samples.map(sample => sample.id),
      rms_residual_m: solveClassification === 'red' ? 0.004 : 0.001,
      maximum_residual_m: solveClassification === 'red' ? 0.006 : 0.002,
    };
    if (request.operation === 'validate') return {
      schema: 'thirdhand-tcp-pivot-validation-v1',
      accepted: validationMaximum <= 0.005,
      sample_ids: request.validation_samples.map(sample => sample.id),
      maximum_error_m: validationMaximum,
      rms_error_m: validationMaximum,
    };
    if (request.operation === 'derive') return {
      schema: 'thirdhand-grasp-tcp-derived-v1',
      probe_tip_to_grasp_plane_m: request.distance_m,
      measurement_uncertainty_m: request.measurement_uncertainty_m,
      tool_axis_flange: request.tool_axis_flange,
      T_flange_probe_tip: request.T_flange_probe_tip,
      T_flange_grasp_tcp: request.T_flange_probe_tip.map(row => [...row]),
    };
    throw new Error('unexpected_operation');
  };
  const session = new TcpCalibrationSession({
    stateSource, solver, thresholds: THRESHOLDS,
    idFactory: () => `id-${++identifier}`,
    now: () => '2026-10-06T10:00:00.000+08:00',
  });
  return {
    session, calls,
    setSample(sample, sequence) {
      snapshot = {
        connected: true, healthy: true, stationary: true, stateFresh: true, locked: false,
        poseFrame: 'robot_flange', framePolicyId: POLICY,
        stateSequence: sequence, producerMonotonicNs: sequence * 1_000_000,
        TBaseFlange: structuredClone(sample.T_base_flange),
      };
    },
    setSnapshot(value) { snapshot = value; },
    changeSnapshot(change) { snapshot = { ...snapshot, ...change }; },
  };
}

async function collectFit(h) {
  await h.session.handle(startCommand());
  for (const [index, sample] of FIXTURE.fit_samples.entries()) {
    h.setSample(sample, index + 1);
    const result = await h.session.handle({
      type: 'record_fit', requestId: `fit-${index}`, contactConfirmed: true,
      probeUnloaded: true,
    });
    assert.equal(result.accepted, true);
  }
}

async function collectValidation(h) {
  for (const [index, sample] of FIXTURE.validation_samples.entries()) {
    h.setSample(sample, index + 20);
    const result = await h.session.handle({
      type: 'record_validation', requestId: `validation-${index}`,
      contactConfirmed: true, probeUnloaded: true,
    });
    assert.equal(result.accepted, true);
  }
}

test('a validated new stream can reset sequence only with a newer producer timestamp', async () => {
  const h=harness(); await h.session.handle(startCommand());
  const record=requestId=>h.session.handle({type:'record_fit',requestId,contactConfirmed:true,probeUnloaded:true});
  h.setSample(FIXTURE.fit_samples[0],16029);
  assert.equal((await record('legacy')).accepted,true);
  h.setSample(FIXTURE.fit_samples[1],2);
  h.changeSnapshot({streamId:'new-stream',producerMonotonicNs:20e9});
  assert.equal((await record('restarted')).accepted,true);
  h.setSample(FIXTURE.fit_samples[2],1);
  h.changeSnapshot({streamId:'new-stream',producerMonotonicNs:21e9});
  assert.equal((await record('reordered')).accepted,false);
  h.changeSnapshot({streamId:'other-stream',producerMonotonicNs:19e9});
  assert.equal((await record('stale-time')).accepted,false);
  h.changeSnapshot({streamId:'other-stream',producerMonotonicNs:22e9});
  assert.equal((await record('newer-stream')).accepted,true);
});

test('start requires exact safety confirmations and finite caliper measurement', async () => {
  const h = harness();
  const invalid = startCommand(); invalid.confirmations.estopReady = false;
  assert.deepEqual(await h.session.handle(invalid), { accepted: false, error: 'start_evidence_invalid' });
  assert.equal(h.session.status().revision, 0);

  const result = await h.session.handle(startCommand('start-2'));
  assert.equal(result.accepted, true);
  assert.equal(result.state.stage, 'collecting_fit');
  assert.equal(result.state.revision, 1);
});

test('fit capture enforces canonical fresh stationary monotonic state', async () => {
  const h = harness();
  await h.session.handle(startCommand());
  h.setSample(FIXTURE.fit_samples[0], 1);
  assert.equal((await h.session.handle({type:'record_fit',requestId:'one',contactConfirmed:true,probeUnloaded:true})).accepted, true);
  const revision = h.session.status().revision;

  for (const [requestId, change] of [
    ['stale', { stateFresh: false }], ['moving', { stationary: false }],
    ['unhealthy', { healthy: false }], ['frame', { poseFrame: 'sdk_tool' }],
    ['policy', { framePolicyId: `sha256:${'b'.repeat(64)}` }],
    ['sequence', { stateSequence: 1 }], ['time', { producerMonotonicNs: 1_000_000 }],
  ]) {
    h.setSample(FIXTURE.fit_samples[1], 2);
    h.changeSnapshot(change);
    const result = await h.session.handle({type:'record_fit',requestId,contactConfirmed:true,probeUnloaded:true});
    assert.equal(result.accepted, false);
    assert.equal(h.session.status().revision, revision);
  }
});

test('eight unique poses solve while delete permits replacement', async () => {
  const h = harness();
  await collectFit(h);
  assert.equal(h.session.status().fitSamples.length, 8);
  const removed = h.session.status().fitSamples[7].id;
  assert.equal((await h.session.handle({type:'delete_fit',requestId:'delete',sampleId:removed})).accepted, true);
  assert.equal(h.session.status().fitSamples.length, 7);
  h.setSample(FIXTURE.fit_samples[7], 12);
  await h.session.handle({type:'record_fit',requestId:'replacement',contactConfirmed:true,probeUnloaded:true});

  const solved = await h.session.handle({type:'solve',requestId:'solve'});
  assert.equal(solved.accepted, true);
  assert.equal(solved.state.stage, 'collecting_validation');
  assert.equal(h.calls[0].fit_samples.length, 8);
});

test('solver failure or red result never advances the session stage', async () => {
  const h = harness({ solveClassification: 'red' });
  await collectFit(h);
  const before = h.session.status().revision;
  const result = await h.session.handle({type:'solve',requestId:'solve-red'});
  assert.equal(result.accepted, false);
  assert.equal(h.session.status().stage, 'collecting_fit');
  assert.equal(h.session.status().revision, before + 1);

  const throwing = harness();
  throwing.session.solver = async () => { throw new Error('solver_failed'); };
  await collectFit(throwing);
  const throwingBefore = throwing.session.status().revision;
  assert.deepEqual(await throwing.session.handle({type:'solve',requestId:'throw'}), {accepted:false,error:'solver_failed'});
  assert.equal(throwing.session.status().revision, throwingBefore);
});

test('three validation poses stay separate and derive applies measurement once', async () => {
  const h = harness();
  await collectFit(h);
  await h.session.handle({type:'solve',requestId:'solve'});
  await collectValidation(h);
  const derived = await h.session.handle({type:'derive',requestId:'derive'});
  assert.equal(derived.accepted, true);
  assert.equal(derived.state.stage, 'ready_to_finalize');
  assert.equal(h.calls[1].validation_samples.length, 3);
  assert.equal(h.calls[2].distance_m, 0.020);
  assert.deepEqual(h.calls[2].tool_axis_flange, [1, 0, 0]);
  assert.equal(new Set([...derived.state.fitSamples.map(x=>x.id), ...derived.state.validationSamples.map(x=>x.id)]).size, 11);
});

test('validation over five millimetres blocks derivation', async () => {
  const h = harness({ validationMaximum: 0.006 });
  await collectFit(h); await h.session.handle({type:'solve',requestId:'solve'}); await collectValidation(h);
  const result = await h.session.handle({type:'derive',requestId:'derive'});
  assert.equal(result.accepted, false);
  assert.equal(h.session.status().stage, 'collecting_validation');
});

test('request replay is idempotent, conflicting reuse fails, and abort is terminal', async () => {
  const h = harness();
  const first = await h.session.handle(startCommand('same'));
  const replay = await h.session.handle(startCommand('same'));
  assert.deepEqual(replay, first);
  const conflict = startCommand('same'); conflict.operator = 'other';
  assert.deepEqual(await h.session.handle(conflict), {accepted:false,error:'request_id_conflict'});
  assert.equal((await h.session.handle({type:'abort',requestId:'abort'})).state.stage, 'aborted');
  assert.deepEqual(await h.session.handle({type:'solve',requestId:'after'}), {accepted:false,error:'session_terminal'});
});
