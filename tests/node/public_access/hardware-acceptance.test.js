'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');
const {validateStopEvidence} = require('../../../services/robot/src/stop-evidence');
const modulePath = path.resolve(__dirname, '../../../services/robot/src/hardware-acceptance.js');
let hardware;
try { hardware = require(modulePath); } catch (error) {
  if (error.code !== 'MODULE_NOT_FOUND' || !error.message.includes(modulePath)) throw error;
}
function api(name, args) {
  assert.equal(typeof hardware?.[name], 'function', `hardware commissioning ${name} API must exist`);
  return hardware[name](args);
}

function privateFile(body) {
  const filePath = path.resolve('synthetic-private-hardware/evidence.json');
  const directory = path.dirname(filePath);
  const state = {body, ownerUid: 1000, fileMode: 0o100600, directoryMode: 0o40700,
    fileUid: 1000, directoryUid: 1000, symlink: false, canonical: true, nlink: 1,
    changedDuringRead: false, opened: 0, closed: 0, fstats: 0};
  const bytes = () => Buffer.from(typeof state.body === 'string' ? state.body : JSON.stringify(state.body));
  function fileInfo() {
    return {mode: state.fileMode, uid: state.fileUid, nlink: state.nlink, size: bytes().length,
      dev: 1, ino: state.changedDuringRead && state.fstats > 1 ? 2 : 1, mtimeMs: 100, ctimeMs: 100,
      isFile: () => true, isDirectory: () => false, isSymbolicLink: () => state.symlink};
  }
  // POSIX metadata and file races are injected deliberately; this does not
  // assert that Windows ACLs provide POSIX ownership or O_NOFOLLOW semantics.
  const io = {
    constants: {O_RDONLY: 0, O_NOFOLLOW: 131072},
    realpathSync: value => state.canonical ? value : path.resolve('other/evidence.json'),
    lstatSync(value) {
      if (value === filePath) return fileInfo();
      assert.equal(value, directory);
      return {mode: state.directoryMode, uid: state.directoryUid, dev: 1, ino: 2,
        isDirectory: () => true, isSymbolicLink: () => false};
    },
    openSync(value, flags) { assert.equal(value, filePath); assert.equal(flags & 131072, 131072); state.opened++; state.fstats = 0; return 9; },
    fstatSync(fd) { assert.equal(fd, 9); state.fstats++; return fileInfo(); },
    readSync(fd, buffer, offset, length, position) { assert.equal(fd, 9); return bytes().copy(buffer, offset, position, position + length); },
    closeSync(fd) { assert.equal(fd, 9); state.closed++; },
  };
  const loader = api('createLocalEvidenceLoader', {filePath, ownerUid: state.ownerUid, io});
  return {loader, state, filePath, io};
}

function fixture() {
  const clock = {wall: 1793450000000, mono: 500};
  const binding = {
    deviceId: '11111111-1111-4111-8111-111111111111', bootId: '22222222-2222-4222-8222-222222222222',
    executorEpoch: '33333333-3333-4333-8333-333333333333', connectionId: '44444444-4444-4444-8444-444444444444',
    certificateId: '55555555-5555-4555-8555-555555555555', sessionId: '66666666-6666-4666-8666-666666666666',
    administratorId: '77777777-7777-4777-8777-777777777777', leaseId: '88888888-8888-4888-8888-888888888888',
    leaseEpoch: 3, sdkProcessId: 4123, hardwareFingerprint: 'a'.repeat(64), limitsDigest: 'b'.repeat(64),
    scopeDigest: 'c'.repeat(64),
  };
  const stopProfile = {stop: {maxStopTimeMs: 1000, maxFeedbackAgeMs: 500, maxVelocityRadS: 0.01,
    maxJointDeltaDeg: 0.2, minStableDurationMs: 100, minSamples: 3, requiresDisabled: true, includesGripper: false}};
  stopProfile.digest = hardware?.computeStopProfileDigest?.(stopProfile) || 'd'.repeat(64);
  binding.stopProfileDigest = stopProfile.digest;
  const commandId = '99999999-9999-4999-8999-999999999999';
  const acceptance = {...binding, acceptedBy: binding.administratorId, stopEvidenceId: commandId,
    issuedAt: clock.wall - 10, expiresAt: clock.wall + 60000};
  const stopEvidence = {commandId, executorEpoch: binding.executorEpoch,
    hardwareFingerprint: binding.hardwareFingerprint, requestedAt: clock.wall - 220, observedAt: clock.wall - 20,
    state: 'stopped', reason: 'COMMISSIONING_STOP', measurement: {kind: 'hardware_feedback', sourceMode: 'hardware',
      profileDigest: stopProfile.digest, jointVelocitiesRadS: [0, 0, 0, 0, 0, 0], jointDeltaDeg: [0, 0, 0, 0, 0, 0],
      sampleCount: 5, stableDurationMs: 200, driversDisabled: true}};
  const artifact = {schema: 1, acceptance, stopEvidence};
  const current = {...binding, scopeExpiresAt: clock.wall + 60000, stopProfile,
    stopUnconfirmed: false, commandResultUnknown: false, requiredCoverage: {joints: 6, gripper: false}};
  const file = privateFile(artifact), calls = {stop: 0};
  const options = {getExecutionState: () => current, loadEvidence: file.loader,
    clock: {now: () => clock.wall, monotonic: () => clock.mono},
    stopValidator(evidence, context, profile) { calls.stop++; return validateStopEvidence(evidence, context, profile); }};
  const gate = api('createHardwareAcceptance', options);
  return {clock, binding, current, artifact, file, options, gate, calls};
}

test('is disabled by default and never treats a browser JSON boolean as commissioning', () => {
  assert.equal(api('createHardwareAcceptance', {}).isAccepted(), false);
  const input = fixture();
  for (const loadEvidence of [() => true, () => ({accepted: true}), () => input.artifact,
    () => ({body: input.artifact, trusted: true})]) {
    assert.equal(api('createHardwareAcceptance', {...input.options, loadEvidence}).isAccepted(), false);
  }
  assert.equal(api('createHardwareAcceptance', {...input.options, stopValidator: undefined}).isAccepted(), false);
});

test('consumes fresh bound physical-stop proof from the controlled file loader', () => {
  const input = fixture();
  assert.equal(input.gate.isAccepted(), true);
  assert.equal(input.calls.stop, 1);
  assert.equal(input.file.state.opened, input.file.state.closed);
});

test('requires the current wall time on first validation rather than replaying a stored verification time', () => {
  const input = fixture(); input.clock.wall += 501; input.clock.mono += 501;
  assert.equal(input.gate.isAccepted(), false);
});

test('retains only bound stop-capability verification, never exposes a cached stopped receipt', () => {
  const input = fixture(); assert.equal(input.gate.isAccepted(), true);
  input.clock.wall += 2000; input.clock.mono += 2000;
  assert.equal(input.gate.isAccepted(), true);
  assert.equal(input.calls.stop, 1);
  assert.equal('stopped' in input.gate, false);
  assert.equal('previousStopEvidence' in input.gate, false);
  input.current.stopUnconfirmed = true;
  assert.equal(input.gate.isAccepted(), false);
  input.current.stopUnconfirmed = false;
  assert.equal(input.gate.isAccepted(), false, 'invalidated consumed proof cannot be reactivated');
});

test('every execution, human, lease, process and configuration binding invalidates cached acceptance', () => {
  for (const key of ['deviceId', 'bootId', 'executorEpoch', 'connectionId', 'certificateId', 'sessionId',
    'administratorId', 'leaseId', 'leaseEpoch', 'sdkProcessId', 'hardwareFingerprint', 'limitsDigest', 'stopProfileDigest', 'scopeDigest']) {
    const input = fixture(); assert.equal(input.gate.isAccepted(), true);
    const original = input.current[key];
    input.current[key] = typeof original === 'number' ? original + 1 : /^[a-f0-9]{64}$/.test(original) ? 'e'.repeat(64) : 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
    assert.equal(input.gate.isAccepted(), false, key);
    input.current[key] = original;
    assert.equal(input.gate.isAccepted(), false, `${key}: restoring fields must not revive old proof`);
  }
});

test('unknown command outcomes revoke capability and require a new stop proof', () => {
  const input = fixture(); assert.equal(input.gate.isAccepted(), true);
  input.current.commandResultUnknown = true; assert.equal(input.gate.isAccepted(), false);
  input.current.commandResultUnknown = false; assert.equal(input.gate.isAccepted(), false);
});

test('acceptance cannot outlive the scope and monotonic time prevents wall-clock extension', () => {
  const input = fixture(); input.artifact.acceptance.expiresAt = input.current.scopeExpiresAt + 1;
  assert.equal(input.gate.isAccepted(), false);
  const expired = fixture(); assert.equal(expired.gate.isAccepted(), true);
  expired.clock.mono += 60001; expired.clock.wall += 1000;
  assert.equal(expired.gate.isAccepted(), false);
  const backward = fixture(); assert.equal(backward.gate.isAccepted(), true);
  backward.clock.mono -= 1;
  assert.equal(backward.gate.isAccepted(), false);
});

test('file ownership, permissions, links, canonical path, size and read races fail closed', () => {
  for (const change of [
    i => { i.file.state.fileUid = 999; }, i => { i.file.state.directoryUid = 999; },
    i => { i.file.state.fileMode = 0o100644; }, i => { i.file.state.directoryMode = 0o40755; },
    i => { i.file.state.symlink = true; }, i => { i.file.state.canonical = false; },
    i => { i.file.state.nlink = 2; }, i => { i.file.state.body = ' '.repeat(32769); },
    i => { i.file.state.body = '{bad json'; }, i => { i.file.state.changedDuringRead = true; },
  ]) {
    const input = fixture(); change(input); assert.equal(input.gate.isAccepted(), false);
    assert.equal(input.file.state.opened, input.file.state.closed);
  }
});

test('loss of the controlled evidence file revokes a previously accepted capability', () => {
  const input = fixture(); assert.equal(input.gate.isAccepted(), true);
  input.file.state.fileMode = 0o100666; assert.equal(input.gate.isAccepted(), false);
  input.file.state.fileMode = 0o100600; assert.equal(input.gate.isAccepted(), false);
});

test('requires actual stop semantics, command reference, coverage and unchanged stop profile values', () => {
  for (const change of [
    i => { i.artifact.stopEvidence.state = 'unknown'; },
    i => { i.artifact.stopEvidence.measurement.kind = 'cleanup'; },
    i => { i.artifact.acceptance.stopEvidenceId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'; },
    i => { i.artifact.acceptance.acceptedBy = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'; },
    i => { i.current.requiredCoverage.gripper = true; },
    i => { i.current.stopProfile.stop.maxJointDeltaDeg = 20; },
  ]) { const input = fixture(); change(input); assert.equal(input.gate.isAccepted(), false); }
});

test('a new factory cannot inherit a consumed attestation after the stop proof has become stale', () => {
  const input = fixture(); assert.equal(input.gate.isAccepted(), true);
  input.clock.wall += 501; input.clock.mono += 501;
  assert.equal(api('createHardwareAcceptance', input.options).isAccepted(), false);
});

test('a new fresh stop command and artifact is required to establish capability again', () => {
  const input = fixture(); assert.equal(input.gate.isAccepted(), true);
  input.current.commandResultUnknown = true; assert.equal(input.gate.isAccepted(), false);
  input.current.commandResultUnknown = false;
  const next = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
  input.artifact.acceptance.stopEvidenceId = next; input.artifact.stopEvidence.commandId = next;
  assert.equal(input.gate.isAccepted(), true);
  assert.equal(input.calls.stop, 2);
});

test('filesystem cleanup failures cannot return an accepted local receipt', () => {
  const input = fixture();
  input.file.io.closeSync = () => { throw new Error('Synthetic close failure'); };
  assert.equal(input.gate.isAccepted(), false);
});

test('an unsupported zero no-follow flag cannot masquerade as POSIX protection', () => {
  const input = fixture(); input.file.io.constants.O_NOFOLLOW = 0;
  let attemptedOpen = false;
  const open = input.file.io.openSync;
  input.file.io.openSync = (...args) => { attemptedOpen = true; return open(...args); };
  assert.equal(input.gate.isAccepted(), false);
  assert.equal(attemptedOpen, false, 'unsupported protection must reject before attempting a file open');
});

test('native private-file loader uses POSIX guarantees when present and fails closed on Windows', () => {
  const input = fixture();
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'thirdhand-hardware-acceptance-'));
  const filePath = path.join(directory, 'evidence.json');
  try {
    fs.chmodSync(directory, 0o700);
    fs.writeFileSync(filePath, JSON.stringify(input.artifact), {mode: 0o600});
    fs.chmodSync(filePath, 0o600);
    const ownerUid = typeof process.getuid === 'function' ? process.getuid() : 0;
    const loader = api('createLocalEvidenceLoader', {filePath, ownerUid});
    const gate = api('createHardwareAcceptance', {...input.options, loadEvidence: loader});
    const supportsPosix = typeof process.getuid === 'function' && Number.isInteger(fs.constants.O_NOFOLLOW) && fs.constants.O_NOFOLLOW > 0;
    assert.equal(gate.isAccepted(), supportsPosix);
    if (supportsPosix) {
      fs.chmodSync(filePath, 0o644);
      assert.equal(gate.isAccepted(), false);
    }
  } finally {
    // Only remove the exact file and empty temporary directory this test made.
    fs.unlinkSync(filePath); fs.rmdirSync(directory);
  }
});
