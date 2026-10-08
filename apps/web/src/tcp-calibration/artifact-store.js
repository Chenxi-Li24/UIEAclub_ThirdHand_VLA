'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {validateRigidTransform}=require('../../../../skills/manipulation/bottlegrasp/src/thirdhand_va/action/grasp/grip_transform');

function codedError(code) {
  const error = new Error(code);
  error.code = code;
  return error;
}

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  const encoded = JSON.stringify(value);
  if (encoded === undefined) throw codedError('artifact_value_invalid');
  return encoded;
}

function contentHash(value) {
  const payload = {...value};
  delete payload.contentHash;
  return `sha256:${crypto.createHash('sha256').update(canonical(payload)).digest('hex')}`;
}

class TcpCalibrationArtifactStore {
  constructor({root, fsImpl = fs, now = () => new Date().toISOString()} = {}) {
    if (typeof root !== 'string' || !path.isAbsolute(root) || typeof now !== 'function') {
      throw new TypeError('artifact_store_invalid');
    }
    this.root = path.resolve(root);
    this.fs = fsImpl;
    this.now = now;
    for (const directory of [this.root, this._path('sessions'), this._path('candidates')]) {
      this.fs.mkdirSync(directory,{recursive:true,mode:0o700});
    }
  }

  _path(...parts) { return path.join(this.root,...parts); }

  _assertInside(filename) {
    const resolved = path.resolve(filename);
    if (resolved !== this.root && !resolved.startsWith(`${this.root}${path.sep}`)) {
      throw codedError('artifact_path_invalid');
    }
    return resolved;
  }

  _atomicWrite(filename, value) {
    const target = this._assertInside(filename);
    const temporary = `${target}.tmp-${process.pid}-${crypto.randomUUID()}`;
    const bytes = Buffer.from(`${canonical(value)}\n`);
    this.fs.writeFileSync(temporary,bytes,{flag:'wx',mode:0o600});
    let descriptor;
    try {
      descriptor=this.fs.openSync(temporary,'r');
      this.fs.fsyncSync(descriptor);
    } finally {
      if(descriptor!==undefined)this.fs.closeSync(descriptor);
    }
    this.fs.renameSync(temporary,target);
    this.fs.chmodSync(target,0o600);
    let directoryDescriptor;
    try {
      directoryDescriptor=this.fs.openSync(path.dirname(target),'r');
      this.fs.fsyncSync(directoryDescriptor);
    } finally {
      if(directoryDescriptor!==undefined)this.fs.closeSync(directoryDescriptor);
    }
    return target;
  }

  _writeImmutable(directory, value) {
    const hash = contentHash(value);
    const document = {...value,contentHash:hash};
    const filename=this._path(directory,`${hash.slice(7)}.json`);
    if(this.fs.existsSync(filename)){
      const existing=this._readDocument(filename);
      if(existing.contentHash!==hash)throw codedError('artifact_hash_mismatch');
    }else this._atomicWrite(filename,document);
    return {document,path:filename,contentHash:hash};
  }

  _readJson(filename) {
    try{return JSON.parse(this.fs.readFileSync(this._assertInside(filename),'utf8'));}
    catch(error){if(error.code==='ENOENT')throw error;throw codedError('artifact_corrupt');}
  }

  _readDocument(filename, expectedHash = null) {
    const document=this._readJson(filename);
    if(!document||typeof document!=='object'||Array.isArray(document)
        ||typeof document.contentHash!=='string')throw codedError('artifact_corrupt');
    const actual=contentHash(document);
    if(actual!==document.contentHash||(expectedHash&&actual!==expectedHash)){
      throw codedError('artifact_hash_mismatch');
    }
    return document;
  }

  saveSession(snapshot) {
    if(!snapshot||snapshot.schema!=='thirdhand-tcp-calibration-session-v1'
        ||typeof snapshot.sessionId!=='string'||!snapshot.sessionId
        ||!Number.isSafeInteger(snapshot.revision))throw codedError('session_snapshot_invalid');
    const saved=this._writeImmutable('sessions',{
      schema:'thirdhand-tcp-session-artifact-v1',snapshot:structuredClone(snapshot),savedAt:this.now(),
    });
    this._atomicWrite(this._path('sessions','current.json'),{
      schema:'thirdhand-tcp-current-session-v1',path:saved.path,contentHash:saved.contentHash,
    });
    return saved;
  }

  restoreSession() {
    const pointer=this._readJson(this._path('sessions','current.json'));
    if(pointer?.schema!=='thirdhand-tcp-current-session-v1'
        ||typeof pointer.path!=='string'||typeof pointer.contentHash!=='string'){
      throw codedError('artifact_corrupt');
    }
    const document=this._readDocument(pointer.path,pointer.contentHash);
    if(document.schema!=='thirdhand-tcp-session-artifact-v1')throw codedError('artifact_corrupt');
    return structuredClone(document.snapshot);
  }

  finalizePending(snapshot) {
    if(snapshot?.stage!=='ready_to_finalize'||snapshot.validationReport?.accepted!==true
        ||snapshot.solveReport?.accepted!==true||snapshot.derivedTcp?.schema!=='thirdhand-grasp-tcp-derived-v1'){
      throw codedError('candidate_unverified');
    }
    const saved=this._writeImmutable('candidates',{
      schema:'thirdhand-gripper-tcp-candidate-v1',createdAt:this.now(),session:structuredClone(snapshot),
    });
    const candidateId=saved.contentHash;
    this._atomicWrite(this._path('gripper-tcp.pending.json'),{
      schema:'thirdhand-gripper-tcp-pending-v1',candidateId,path:saved.path,contentHash:saved.contentHash,
    });
    return {...saved,candidateId};
  }

  _candidate(candidateId) {
    if(!/^sha256:[a-f0-9]{64}$/.test(candidateId||''))throw codedError('candidate_not_found');
    const filename=this._path('candidates',`${candidateId.slice(7)}.json`);
    if(!this.fs.existsSync(filename))throw codedError('candidate_not_found');
    const document=this._readDocument(filename,candidateId);
    if(document.schema!=='thirdhand-gripper-tcp-candidate-v1'
        ||document.session?.validationReport?.accepted!==true)throw codedError('candidate_unverified');
    return document;
  }

  _active() {
    const filename=this._path('active-manifest.json');
    if(!this.fs.existsSync(filename))return null;
    const value=this._readJson(filename);
    if(value?.schema!=='thirdhand-gripper-tcp-active-v1')throw codedError('artifact_corrupt');
    return value;
  }

  status() {
    let pending = null;
    try {
      pending = this._readJson(this._path('gripper-tcp.pending.json'));
      if (pending?.schema !== 'thirdhand-gripper-tcp-pending-v1'
          || pending.contentHash !== pending.candidateId) throw codedError('artifact_corrupt');
      this._candidate(pending.candidateId);
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    const active = this._active();
    if (active) {
      this._candidate(active.activeId);
      if (active.previousActiveId) this._candidate(active.previousActiveId);
    }
    return {
      pendingId: pending?.candidateId || null,
      activeId: active?.activeId || null,
      previousActiveId: active?.previousActiveId || null,
    };
  }

  activeTcp(framePolicyId) {
    const active=this._active();if(!active)return null;
    const document=this._candidate(active.activeId),session=document.session;
    if(session.stage!=='ready_to_finalize'||session.solveReport?.accepted!==true
        ||session.derivedTcp?.schema!=='thirdhand-grasp-tcp-derived-v1')throw codedError('candidate_unverified');
    if(session.framePolicyId!==framePolicyId)throw codedError('tcp_frame_policy_mismatch');
    let matrix;
    try{matrix=validateRigidTransform(session.derivedTcp.T_flange_grasp_tcp);}
    catch{throw codedError('tcp_transform_invalid');}
    if(Math.hypot(...matrix.slice(0,3).map(row=>row[3]))>0.3)throw codedError('tcp_transform_invalid');
    matrix.forEach(Object.freeze);Object.freeze(matrix);
    return Object.freeze({id:active.activeId,source:'measured',T_flange_grasp_tcp:matrix,
      activatedAt:active.activatedAt,framePolicyId});
  }

  activate({candidateId,expectedActiveId}) {
    this._candidate(candidateId);
    const active=this._active();
    if((active?.activeId??null)!==expectedActiveId)throw codedError('active_version_conflict');
    const manifest={schema:'thirdhand-gripper-tcp-active-v1',activeId:candidateId,
      previousActiveId:active?.activeId??null,activatedAt:this.now()};
    this._atomicWrite(this._path('active-manifest.json'),manifest);
    return structuredClone(manifest);
  }

  rollback({expectedActiveId}) {
    const active=this._active();
    if(!active||active.activeId!==expectedActiveId)throw codedError('active_version_conflict');
    if(!active.previousActiveId)throw codedError('rollback_unavailable');
    this._candidate(active.previousActiveId);
    const manifest={schema:'thirdhand-gripper-tcp-active-v1',activeId:active.previousActiveId,
      previousActiveId:active.activeId,activatedAt:this.now()};
    this._atomicWrite(this._path('active-manifest.json'),manifest);
    return structuredClone(manifest);
  }
}

module.exports={TcpCalibrationArtifactStore,canonical,contentHash};
