'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {TcpCalibrationArtifactStore}=require('../../../apps/web/src/tcp-calibration/artifact-store');
const {buildGraspGeometry,getGripPosition}=require('../../../apps/web/src/grasp/geometry');
const {fixture}=require('./grasp-geometry.test');
const policy='sha256:'+'a'.repeat(64);
const tcp=[[0,-1,0,.09],[1,0,0,.02],[0,0,1,.01],[0,0,0,1]];
function candidate(overrides={}){return {schema:'thirdhand-tcp-calibration-session-v1',sessionId:'calib',revision:20,
 stage:'ready_to_finalize',framePolicyId:policy,solveReport:{accepted:true},validationReport:{accepted:true},
 derivedTcp:{schema:'thirdhand-grasp-tcp-derived-v1',T_flange_grasp_tcp:tcp},...overrides};}
function storeFixture(t){const root=fs.mkdtempSync(path.join(os.tmpdir(),'grasp-active-tcp-'));
 t.after(()=>fs.rmSync(root,{recursive:true,force:true}));return {root,store:new TcpCalibrationArtifactStore({root})};}
test('grasp consumes the active immutable measured transform and refuses stale frame identity',t=>{
 const {store}=storeFixture(t);assert.equal(store.activeTcp(policy),null);
 const saved=store.finalizePending(candidate());store.activate({candidateId:saved.candidateId,expectedActiveId:null});
 const measured=store.activeTcp(policy);assert.equal(measured.id,saved.candidateId);assert.deepEqual(measured.T_flange_grasp_tcp,tcp);
 assert.throws(()=>store.activeTcp('sha256:'+'b'.repeat(64)),/tcp_frame_policy_mismatch/);
 assert.throws(()=>{measured.T_flange_grasp_tcp[0][3]=5;},TypeError);
});
test('corrupt active artifacts and missing accepted fit cannot silently fall back',t=>{
 const {root,store}=storeFixture(t);const saved=store.finalizePending(candidate());
 store.activate({candidateId:saved.candidateId,expectedActiveId:null});fs.writeFileSync(saved.path,'{}');
 assert.throws(()=>store.activeTcp(policy),/artifact_corrupt/);
 fs.writeFileSync(path.join(root,'active-manifest.json'),'not json');assert.throws(()=>store.activeTcp(policy),/artifact_corrupt/);
});
test('full measured TCP retains present tool orientation and off-axis translation without old backoff',()=>{
 const f=fixture();f.config.T_flange_grasp_tcp=tcp;f.config.forwardBackoffM=0;
 const g=buildGraspGeometry(f);assert.deepEqual(g.contact.flangeM,[.31,-.02,.19]);
 assert.deepEqual(g.contact.position,[.48334,-.02,.19]);assert.deepEqual(g.contact.euler,[0,0,0]);
 assert.deepEqual(g.contact.gripM,[.4,0,.2]);assert.deepEqual(getGripPosition(f.robot,f.config),[.21666,.02,.21]);
 f.robot.flange_euler_rad=[0,0,Math.PI/2];const rotated=buildGraspGeometry(f);
 assert.deepEqual(rotated.contact.position,[.42,.08334,.19]);
 assert.ok(Math.abs(rotated.contact.euler[2]-Math.PI/2)<1e-10);
});
