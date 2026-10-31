'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');

const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
const HASH = /^[a-f0-9]{64}$/;
const IDS = ['deviceId', 'bootId', 'executorEpoch', 'connectionId', 'certificateId',
  'sessionId', 'administratorId', 'leaseId'];
const HASHES = ['hardwareFingerprint', 'limitsDigest', 'stopProfileDigest', 'scopeDigest'];
const BINDING = [...IDS, ...HASHES, 'leaseEpoch', 'sdkProcessId'];
const STOP_KEYS = ['maxStopTimeMs', 'maxFeedbackAgeMs', 'maxVelocityRadS', 'maxJointDeltaDeg',
  'minStableDurationMs', 'minSamples', 'requiresDisabled', 'includesGripper',
  'maxGripperVelocityMmS', 'maxGripperDeltaMm'];
const trustedLoaders = new WeakSet(), localReceipts = new WeakSet();
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const time = value => Number.isSafeInteger(value) && value >= 0;
const positiveInteger = value => Number.isSafeInteger(value) && value > 0;
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
function freeze(value) {
  if (object(value) || Array.isArray(value)) { for (const child of Object.values(value)) freeze(child); Object.freeze(value); }
  return value;
}

/** Independent digest for the stop thresholds; not a motion-limits digest. */
function computeStopProfileDigest(profile) {
  if (!object(profile?.stop) || Object.keys(profile.stop).some(key => !STOP_KEYS.includes(key))) {
    throw new TypeError('Known local stop profile required');
  }
  const stop = Object.fromEntries(STOP_KEYS.map(key => [key, profile.stop[key] ?? null]));
  return hash(JSON.stringify({stop}));
}

const privateFile = (info, uid) => info?.isFile() === true && info.uid === uid
  && Number.isInteger(info.mode) && (info.mode & 0o077) === 0 && info.nlink === 1
  && Number.isSafeInteger(info.size) && info.size >= 2 && info.size <= 32768;
const privateDirectory = (info, uid) => info?.isDirectory() === true && info.isSymbolicLink() === false
  && info.uid === uid && Number.isInteger(info.mode) && (info.mode & 0o077) === 0;
const sameFile = (left, right) => ['dev', 'ino', 'size', 'mtimeMs', 'ctimeMs', 'uid', 'mode', 'nlink']
  .every(key => left[key] === right[key]);

/**
 * OS-local capability. There is deliberately no exported "brand this JSON"
 * operation. Production uses real POSIX metadata/O_NOFOLLOW and fails closed
 * where that API is unavailable. `io` is a trusted dependency-injection seam
 * for filesystem/race tests, never a browser-controlled option.
 */
function createLocalEvidenceLoader({filePath, ownerUid, io = fs} = {}) {
  if (typeof filePath !== 'string' || !path.isAbsolute(filePath) || path.resolve(filePath) !== filePath
    || !Number.isSafeInteger(ownerUid) || ownerUid < 0) throw new TypeError('Canonical private file and local owner required');
  const directory = path.dirname(filePath);
  const load = () => {
    let fd;
    try {
      if (!Number.isInteger(io.constants?.O_NOFOLLOW) || io.constants.O_NOFOLLOW <= 0 || !Number.isInteger(io.constants?.O_RDONLY)) return null;
      if (io.realpathSync(directory) !== directory || io.realpathSync(filePath) !== filePath) return null;
      const parent = io.lstatSync(directory), before = io.lstatSync(filePath);
      if (!privateDirectory(parent, ownerUid) || before.isSymbolicLink() !== false || !privateFile(before, ownerUid)) return null;
      fd = io.openSync(filePath, io.constants.O_RDONLY | io.constants.O_NOFOLLOW);
      const opened = io.fstatSync(fd);
      if (!privateFile(opened, ownerUid) || !sameFile(before, opened)) return null;
      const buffer = Buffer.alloc(32769);
      let length = 0;
      while (length < buffer.length) {
        const read = io.readSync(fd, buffer, length, buffer.length - length, length);
        if (!Number.isInteger(read) || read < 0 || read > buffer.length - length) return null;
        if (read === 0) break;
        length += read;
      }
      if (length !== opened.size || length > 32768) return null;
      const after = io.fstatSync(fd), linked = io.lstatSync(filePath), parentAfter = io.lstatSync(directory);
      if (!privateFile(after, ownerUid) || !sameFile(opened, after) || !sameFile(after, linked)
        || linked.isSymbolicLink() !== false || !privateDirectory(parentAfter, ownerUid)
        || parent.dev !== parentAfter.dev || parent.ino !== parentAfter.ino
        || io.realpathSync(filePath) !== filePath) return null;
      const bytes = buffer.subarray(0, length), body = JSON.parse(bytes.toString('utf8'));
      if (!object(body)) return null;
      io.closeSync(fd); fd = undefined;
      const receipt = Object.freeze({body: freeze(body), digest: hash(bytes)});
      localReceipts.add(receipt);
      return receipt;
    } catch { return null; }
    finally { if (Number.isInteger(fd)) { try { io.closeSync(fd); } catch { /* No receipt is returned on a close failure. */ } } }
  };
  trustedLoaders.add(load);
  return load;
}

const validBinding = value => object(value) && IDS.every(key => UUID.test(value[key] || ''))
  && HASHES.every(key => HASH.test(value[key] || '')) && positiveInteger(value.leaseEpoch) && positiveInteger(value.sdkProcessId);
const sameBinding = (left, right) => BINDING.every(key => left[key] === right[key]);
const validCoverage = value => object(value) && value.joints === 6 && typeof value.gripper === 'boolean';
const covers = (actual, required) => validCoverage(actual) && validCoverage(required)
  && (!required.gripper || actual.gripper);

/**
 * Admission based on locally consumed commissioning evidence. Cached success
 * proves stop CAPABILITY only for this exact scope/executor/lease; it never
 * proves "currently stopped", creates a stop receipt or grants a control lease.
 * Runtime command/stop paths must continue requiring fresh measured outcomes.
 */
function createHardwareAcceptance({getExecutionState, loadEvidence, stopValidator,
  clock = {now: () => Date.now(), monotonic: () => performance.now()}} = {}) {
  let cached = null;
  const consumedStops = new Set();
  const revoke = () => { cached = null; return false; };
  return {isAccepted() {
    try {
      if (typeof getExecutionState !== 'function' || !trustedLoaders.has(loadEvidence)
        || typeof stopValidator !== 'function' || typeof clock?.now !== 'function' || typeof clock?.monotonic !== 'function') return revoke();
      const now = clock.now(), mono = clock.monotonic(), current = getExecutionState();
      if (!time(now) || !Number.isFinite(mono) || mono < 0 || !validBinding(current)
        || !time(current.scopeExpiresAt) || now >= current.scopeExpiresAt
        || current.stopUnconfirmed !== false || current.commandResultUnknown !== false
        || !validCoverage(current.requiredCoverage)) return revoke();
      const receipt = loadEvidence();
      if (!localReceipts.has(receipt)) return revoke();
      const body = receipt.body, accepted = body.acceptance, evidence = body.stopEvidence;
      if (body.schema !== 1 || Object.keys(body).some(key => !['schema', 'acceptance', 'stopEvidence'].includes(key))
        || !validBinding(accepted) || !sameBinding(accepted, current)
        || !UUID.test(accepted.stopEvidenceId || '') || accepted.acceptedBy !== current.administratorId
        || !time(accepted.issuedAt) || !time(accepted.expiresAt) || accepted.expiresAt <= accepted.issuedAt
        || now < accepted.issuedAt || now >= accepted.expiresAt || accepted.expiresAt > current.scopeExpiresAt
        || !object(evidence) || evidence.commandId !== accepted.stopEvidenceId
        || !time(evidence.observedAt) || evidence.observedAt > accepted.issuedAt
        || current.stopProfile?.digest !== current.stopProfileDigest
        || computeStopProfileDigest(current.stopProfile) !== current.stopProfileDigest) return revoke();
      if (cached) {
        if (cached.digest === receipt.digest && sameBinding(cached.binding, current)
          && mono >= cached.verifiedMono && mono < cached.deadline
          && covers(cached.coverage, current.requiredCoverage)) return true;
        revoke();
      }
      // Revocation/expiry/context change may never revive this same stop result,
      // even if fields, permissions or file whitespace are later restored.
      if (consumedStops.has(accepted.stopEvidenceId)) return false;
      const result = stopValidator(evidence, {commandId: accepted.stopEvidenceId,
        executorEpoch: current.executorEpoch, hardwareFingerprint: current.hardwareFingerprint, now}, current.stopProfile);
      if (result?.ok !== true || result.code !== 'STOP_VERIFIED' || !covers(result.coverage, current.requiredCoverage)) return false;
      consumedStops.add(accepted.stopEvidenceId);
      cached = {digest: receipt.digest, binding: Object.fromEntries(BINDING.map(key => [key, current[key]])),
        verifiedMono: mono, deadline: mono + accepted.expiresAt - now, coverage: {...result.coverage}};
      return true;
    } catch { return revoke(); }
  }};
}

module.exports = {createHardwareAcceptance, createLocalEvidenceLoader, computeStopProfileDigest};
