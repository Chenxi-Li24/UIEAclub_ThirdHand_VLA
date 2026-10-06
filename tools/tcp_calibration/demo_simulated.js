#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { TcpCalibrationArtifactStore } = require('../../apps/web/src/tcp-calibration/artifact-store');
const { TcpCalibrationSession } = require('../../apps/web/src/tcp-calibration/session');
const { runTcpSolver } = require('../../apps/web/src/tcp-calibration/solver-adapter');

const ROOT = path.resolve(__dirname, '../..');
const FIXTURE = JSON.parse(fs.readFileSync(
  path.join(ROOT, 'tests/fixtures/tcp-calibration/reference-pivot.json'), 'utf8',
));
const POLICY = `sha256:${'a'.repeat(64)}`;
const THRESHOLDS = {
  fitRmsGreenM: 0.002, fitMaximumGreenM: 0.004, fitRmsMaximumM: 0.003,
  fitMaximumM: 0.005, validationMaximumM: 0.005,
};

class FakePort3000WebSocket {
  constructor() { this.outbound = []; }
  send(message) { this.outbound.push(JSON.parse(message)); return true; }
}

function makeStateSource(socket) {
  let snapshot = null;
  return {
    snapshot: () => structuredClone(snapshot),
    setSample(sample, sequence) {
      snapshot = {
        connected: true, healthy: true, stationary: true, stateFresh: true, locked: false,
        poseFrame: 'robot_flange', framePolicyId: POLICY, stateSequence: sequence,
        producerMonotonicNs: sequence * 1_000_000,
        TBaseFlange: structuredClone(sample.T_base_flange),
      };
    },
    softwareStop() {
      return socket.send(JSON.stringify({ cmd: 'software_stop', request_id: 'simulation-stop' }));
    },
  };
}

async function runSimulation({ artifactRoot, quiet = false } = {}) {
  if (!artifactRoot) artifactRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-tcp-demo-'));
  const socket = new FakePort3000WebSocket();
  const stateSource = makeStateSource(socket);
  const store = new TcpCalibrationArtifactStore({ root: path.resolve(artifactRoot),
    now: () => '2026-10-06T10:00:00.000+08:00' });
  let identifier = 0;
  const options = {
    stateSource, thresholds: THRESHOLDS, idFactory: () => `simulation-${++identifier}`,
    now: () => '2026-10-06T10:00:00.000+08:00',
    solver: request => runTcpSolver({ python: process.env.PYTHON || 'python',
      script: path.join(ROOT, 'tools/tcp_calibration/solve_tcp.py'), request }),
  };
  const session = new TcpCalibrationSession(options);
  const stages = [0];
  const execute = async command => {
    const result = await session.handle(command);
    if (!result.accepted) throw new Error(result.error);
    store.saveSession(result.state);
    return result.state;
  };

  await execute({ type: 'start', requestId: 'start', operator: 'simulation',
    measurement: { distanceM: 0.020, uncertaintyM: 0.001, toolAxisFlange: [1, 0, 0] },
    confirmations: { probeCentered: true, pivotFixed: true, estopReady: true,
      manualTeachOnly: true } });
  stages.push(1);
  for (const [index, sample] of FIXTURE.fit_samples.entries()) {
    stateSource.setSample(sample, index + 1);
    await execute({ type: 'record_fit', requestId: `fit-${index}`, contactConfirmed: true,
      probeUnloaded: true });
  }
  await execute({ type: 'solve', requestId: 'solve' });
  stages.push(2);
  for (const [index, sample] of FIXTURE.validation_samples.entries()) {
    stateSource.setSample(sample, index + 20);
    await execute({ type: 'record_validation', requestId: `validation-${index}`,
      contactConfirmed: true, probeUnloaded: true });
  }
  stages.push(3);
  const ready = await execute({ type: 'derive', requestId: 'derive' });
  stages.push(4);

  const restored = new TcpCalibrationSession({ ...options, initialState: store.restoreSession() });
  const priorSnapshot = structuredClone(ready);
  priorSnapshot.sessionId = 'simulation-prior';
  priorSnapshot.revision = ready.revision - 1;
  priorSnapshot.derivedTcp.T_flange_grasp_tcp[0][3] += 0.001;
  const previous = store.finalizePending(priorSnapshot);
  store.activate({ candidateId: previous.candidateId, expectedActiveId: null });

  const pending = store.finalizePending(restored.status());
  stages.push(5);
  const active = store.activate({ candidateId: pending.candidateId,
    expectedActiveId: previous.candidateId });
  const rolledBack = store.rollback({ expectedActiveId: active.activeId });
  stateSource.softwareStop();
  stages.push(6);

  const result = {
    stages, fitSampleIds: ready.fitSamples.map(sample => sample.id),
    validationSampleIds: ready.validationSamples.map(sample => sample.id),
    restored: restored.status(), candidateId: pending.candidateId, activeId: active.activeId,
    previousActiveId: previous.candidateId, rollbackActiveId: rolledBack.activeId,
    outbound: socket.outbound,
    motionCommandCount: socket.outbound.filter(message => message.cmd !== 'software_stop').length,
    artifactRoot: path.resolve(artifactRoot),
  };
  if (!quiet) {
    for (const stage of stages) process.stdout.write(`stage ${stage}\n`);
    process.stdout.write(`candidate ${result.candidateId}\nactive ${result.activeId}\n`);
    process.stdout.write(`rollback ${result.rollbackActiveId}\n`);
    process.stdout.write(`motion commands ${result.motionCommandCount}\nartifacts ${result.artifactRoot}\n`);
  }
  return result;
}

function parseArtifactRoot(argv) {
  const index = argv.indexOf('--artifact-root');
  if (index < 0 || !argv[index + 1]) return null;
  return argv[index + 1];
}

if (require.main === module) {
  runSimulation({ artifactRoot: parseArtifactRoot(process.argv.slice(2)) })
    .catch(error => { process.stderr.write(`${error.stack || error}\n`); process.exitCode = 1; });
}

module.exports = { runSimulation };
