'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  TcpCalibrationArtifactStore,
} = require('../../../apps/web/src/tcp-calibration/artifact-store');

function snapshot(overrides = {}) {
  return {
    schema: 'thirdhand-tcp-calibration-session-v1',
    sessionId: 'session-1', revision: 12, stage: 'ready_to_finalize',
    operator: 'operator-a', framePolicyId: `sha256:${'a'.repeat(64)}`,
    measurement: {distanceM:0.02,uncertaintyM:0.001,toolAxisFlange:[1,0,0]},
    fitSamples: Array.from({length:8},(_,i)=>({id:`fit-${i}`})),
    validationSamples: Array.from({length:3},(_,i)=>({id:`validation-${i}`})),
    solveReport: {schema:'thirdhand-tcp-pivot-solve-v1',accepted:true,classification:'green'},
    validationReport: {schema:'thirdhand-tcp-pivot-validation-v1',accepted:true,maximum_error_m:0.001},
    derivedTcp: {schema:'thirdhand-grasp-tcp-derived-v1',T_flange_grasp_tcp:[[1,0,0,.16],[0,1,0,0],[0,0,1,0],[0,0,0,1]]},
    updatedAt: '2026-10-06T10:00:00.000+08:00',
    ...overrides,
  };
}

function harness(t, options = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'tcp-artifacts-'));
  t.after(() => fs.rmSync(root, {recursive:true,force:true}));
  const store = new TcpCalibrationArtifactStore({
    root, now: () => '2026-10-06T10:30:00.000+08:00', ...options,
  });
  return {root, store};
}

test('session restart restores content-verified immutable snapshot', t => {
  const {root,store}=harness(t);
  const saved=store.saveSession(snapshot({stage:'collecting_fit',revision:3}));
  const restored=new TcpCalibrationArtifactStore({root}).restoreSession();
  assert.equal(restored.stage,'collecting_fit');
  assert.equal(restored.revision,3);
  assert.match(saved.contentHash,/^sha256:[a-f0-9]{64}$/);
  assert.equal(fs.statSync(saved.path).mode & 0o777,0o600);
});

test('truncated pointer and immutable hash mismatch fail closed', t => {
  const {root,store}=harness(t);
  const saved=store.saveSession(snapshot({stage:'collecting_fit'}));
  fs.writeFileSync(path.join(root,'sessions/current.json'),'{');
  assert.throws(()=>store.restoreSession(),error=>error.code==='artifact_corrupt');

  store.saveSession(snapshot({stage:'collecting_validation',revision:13}));
  const current=JSON.parse(fs.readFileSync(path.join(root,'sessions/current.json'),'utf8'));
  const changed=JSON.parse(fs.readFileSync(current.path,'utf8'));
  changed.snapshot.stage='tampered';
  fs.writeFileSync(current.path,JSON.stringify(changed));
  assert.throws(()=>store.restoreSession(),error=>error.code==='artifact_hash_mismatch');
});

test('finalize writes immutable candidate and replaces only pending pointer', t => {
  const {root,store}=harness(t);
  const first=store.finalizePending(snapshot());
  const second=store.finalizePending(snapshot({sessionId:'session-2',revision:14}));
  assert.notEqual(first.candidateId,second.candidateId);
  assert.equal(fs.existsSync(first.path),true);
  assert.equal(fs.existsSync(second.path),true);
  const pending=JSON.parse(fs.readFileSync(path.join(root,'gripper-tcp.pending.json'),'utf8'));
  assert.equal(pending.candidateId,second.candidateId);
  assert.match(first.candidateId,/^sha256:[a-f0-9]{64}$/);
});

test('unverified candidate cannot finalize or activate', t => {
  const {store}=harness(t);
  assert.throws(()=>store.finalizePending(snapshot({validationReport:{accepted:false}})),
    error=>error.code==='candidate_unverified');
  assert.throws(()=>store.activate({candidateId:`sha256:${'0'.repeat(64)}`,expectedActiveId:null}),
    error=>error.code==='candidate_not_found');
});

test('activation preserves previous version and rollback uses compare-and-swap', t => {
  const {root,store}=harness(t);
  const first=store.finalizePending(snapshot());
  const firstManifest=store.activate({candidateId:first.candidateId,expectedActiveId:null});
  assert.equal(firstManifest.activeId,first.candidateId);
  assert.equal(firstManifest.previousActiveId,null);

  const second=store.finalizePending(snapshot({sessionId:'session-2',revision:14}));
  const secondManifest=store.activate({candidateId:second.candidateId,expectedActiveId:first.candidateId});
  assert.equal(secondManifest.previousActiveId,first.candidateId);
  assert.equal(fs.existsSync(first.path),true);
  assert.throws(()=>store.rollback({expectedActiveId:first.candidateId}),
    error=>error.code==='active_version_conflict');
  const rolled=store.rollback({expectedActiveId:second.candidateId});
  assert.equal(rolled.activeId,first.candidateId);
  assert.equal(rolled.previousActiveId,second.candidateId);
  assert.equal(JSON.parse(fs.readFileSync(path.join(root,'active-manifest.json'),'utf8')).activeId,first.candidateId);
});

test('rename failure leaves the previous pointer intact', t => {
  const {root,store}=harness(t);
  store.saveSession(snapshot({stage:'collecting_fit',revision:1}));
  const pointer=path.join(root,'sessions/current.json');
  const before=fs.readFileSync(pointer);
  let failed=false;
  const fsImpl={...fs,renameSync(source,destination){
    if(!failed&&destination===pointer){failed=true;throw Object.assign(new Error('injected'),{code:'EIO'});}
    return fs.renameSync(source,destination);
  }};
  const failing=new TcpCalibrationArtifactStore({root,fsImpl});
  assert.throws(()=>failing.saveSession(snapshot({stage:'collecting_validation',revision:2})),/injected/);
  assert.deepEqual(fs.readFileSync(pointer),before);
  assert.equal(store.restoreSession().revision,1);
});
