'use strict';

const {
  validContact, validDelete, validRequestId, validSimple, validStart,
} = require('./contracts');

function clone(value) { return structuredClone(value); }

function freeze(value) {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

function stable(value) {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${stable(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

function rotationAngle(first, second) {
  let trace = 0;
  for (let i = 0; i < 3; i += 1) {
    for (let k = 0; k < 3; k += 1) trace += first[k][i] * second[k][i];
  }
  return Math.acos(Math.max(-1, Math.min(1, (trace - 1) / 2)));
}

function validMatrix(value) {
  return Array.isArray(value) && value.length === 4
    && value.every(row => Array.isArray(row) && row.length === 4 && row.every(Number.isFinite));
}

class TcpCalibrationSession {
  constructor({ stateSource, solver, thresholds, idFactory, now, initialState = null } = {}) {
    if (!stateSource || typeof stateSource.snapshot !== 'function' || typeof solver !== 'function'
        || typeof idFactory !== 'function' || typeof now !== 'function') {
      throw new TypeError('tcp_calibration_session_invalid');
    }
    this.stateSource = stateSource;
    this.solver = solver;
    this.thresholds = clone(thresholds);
    this.idFactory = idFactory;
    this.now = now;
    this.replays = new Map();
    const emptyState = {
      schema: 'thirdhand-tcp-calibration-session-v1',
      sessionId: null,
      revision: 0,
      stage: 'idle',
      operator: null,
      measurement: null,
      framePolicyId: null,
      fitSamples: [],
      validationSamples: [],
      solveReport: null,
      validationReport: null,
      derivedTcp: null,
      updatedAt: null,
    };
    if (initialState !== null && (!initialState || initialState.schema !== emptyState.schema
        || !(initialState.stage==='idle'&&initialState.sessionId===null)
          && (typeof initialState.sessionId !== 'string' || !initialState.sessionId)
        || !Number.isSafeInteger(initialState.revision) || initialState.revision < 1
        || !Array.isArray(initialState.fitSamples) || !Array.isArray(initialState.validationSamples))) {
      throw new TypeError('tcp_calibration_session_snapshot_invalid');
    }
    this.emptyState=clone(emptyState);
    this.state = clone(initialState || emptyState);
    const samples = [...this.state.fitSamples, ...this.state.validationSamples];
    const latest=samples.reduce((a,b)=>!a||b.producer_monotonic_ns>a.producer_monotonic_ns?b:a,null);
    this.lastStateSequence = latest?.state_sequence ?? null;
    this.lastStreamId = latest?.state_stream_id ?? null;
    this.lastProducerMonotonicNs = samples.length
      ? Math.max(...samples.map(sample => sample.producer_monotonic_ns)) : null;
  }

  status() { return freeze(clone(this.state)); }

  _failure(error) { return { accepted: false, error }; }

  _commit(mutator) {
    mutator();
    this.state.revision += 1;
    this.state.updatedAt = this.now();
    return { accepted: true, state: this.status() };
  }

  _recordReplay(command, result) {
    this.replays.set(command.requestId, { digest: stable(command), result: clone(result) });
    return result;
  }

  _sample(kind) {
    const snapshot = this.stateSource.snapshot();
    const newStream=typeof snapshot?.streamId==='string' && snapshot.streamId.length>0
      && snapshot.streamId!==this.lastStreamId;
    if (!snapshot || snapshot.locked || snapshot.teachActive === true || snapshot.connected !== true || snapshot.healthy !== true
        || snapshot.stationary !== true || snapshot.stateFresh !== true
        || snapshot.poseFrame !== 'robot_flange' || !validMatrix(snapshot.TBaseFlange)
        || typeof snapshot.framePolicyId !== 'string'
        || (this.state.framePolicyId && snapshot.framePolicyId !== this.state.framePolicyId)
        || !Number.isSafeInteger(snapshot.stateSequence)
        || !Number.isSafeInteger(snapshot.producerMonotonicNs)
        || (!newStream && this.lastStateSequence !== null && snapshot.stateSequence <= this.lastStateSequence)
        || (this.lastProducerMonotonicNs !== null
          && snapshot.producerMonotonicNs <= this.lastProducerMonotonicNs)) {
      const reason=snapshot?.reason || (snapshot?.teachActive?'robot_teaching':null)
        || (!snapshot?.stateFresh?'robot_feedback_stale':!snapshot?.stationary?'pose_not_stable':null)
        || (this.lastProducerMonotonicNs!==null && snapshot?.producerMonotonicNs<=this.lastProducerMonotonicNs
          ?'feedback_time_not_new':!newStream && this.lastStateSequence!==null
          && snapshot?.stateSequence<=this.lastStateSequence?'feedback_sequence_not_new':'robot_frame_or_state_invalid');
      return {...this._failure('robot_state_not_recordable'),reason};
    }
    const all = [...this.state.fitSamples, ...this.state.validationSamples];
    const rotation = snapshot.TBaseFlange.slice(0, 3).map(row => row.slice(0, 3));
    if (all.some(sample => rotationAngle(
      sample.T_base_flange.slice(0, 3).map(row => row.slice(0, 3)), rotation,
    ) < 5 * Math.PI / 180)) return this._failure('duplicate_orientation');
    const sample = {
      id: this.idFactory(),
      kind,
      T_base_flange: clone(snapshot.TBaseFlange),
      state_sequence: snapshot.stateSequence,
      ...(snapshot.streamId?{state_stream_id:snapshot.streamId}:{}),
      producer_monotonic_ns: snapshot.producerMonotonicNs,
      frame_policy_id: snapshot.framePolicyId,
      operator_confirmed_contact: true,
      operator_confirmed_probe_unloaded: true,
    };
    this.lastStateSequence = snapshot.stateSequence;
    this.lastStreamId = snapshot.streamId ?? null;
    this.lastProducerMonotonicNs = snapshot.producerMonotonicNs;
    if (!this.state.framePolicyId) this.state.framePolicyId = snapshot.framePolicyId;
    return sample;
  }

  async handle(command) {
    if (!command || typeof command !== 'object' || !validRequestId(command.requestId)) {
      return this._failure('request_invalid');
    }
    const prior = this.replays.get(command.requestId);
    if (prior) return prior.digest === stable(command)
      ? clone(prior.result) : this._failure('request_id_conflict');
    if (this.state.stage === 'aborted'&&command.type!=='new_session') return this._failure('session_terminal');
    const origin=this.state,revision=origin.revision;
    const unchanged=()=>this.state===origin&&this.state.revision===revision;

    let result;
    if(command.type==='new_session'){
      if(this.state.stage==='idle'||!validSimple(command,'new_session'))result=this._failure('stage_invalid');
      else result=this._commit(()=>{
        this.state={...clone(this.emptyState),revision};
        this.replays.clear();this.lastStateSequence=null;this.lastStreamId=null;this.lastProducerMonotonicNs=null;
      });
    } else if (command.type === 'start') {
      if (this.state.stage !== 'idle') result = this._failure('stage_invalid');
      else if (!validStart(command)) result = this._failure('start_evidence_invalid');
      else result = this._commit(() => {
        this.state.sessionId = this.idFactory();
        this.state.stage = 'collecting_fit';
        this.state.operator = command.operator.trim();
        this.state.measurement = clone(command.measurement);
      });
    } else if (command.type === 'record_fit') {
      if (this.state.stage !== 'collecting_fit') result = this._failure('stage_invalid');
      else if (!validContact(command, 'record_fit')) result = this._failure('contact_evidence_invalid');
      else {
        const sample = this._sample('fit');
        result = sample.accepted === false ? sample : this._commit(() => this.state.fitSamples.push(sample));
      }
    } else if (command.type === 'delete_fit') {
      if (this.state.stage !== 'collecting_fit' || !validDelete(command)) {
        result = this._failure('request_invalid');
      } else {
        const index = this.state.fitSamples.findIndex(sample => sample.id === command.sampleId);
        result = index < 0 ? this._failure('sample_not_found')
          : this._commit(() => this.state.fitSamples.splice(index, 1));
      }
    } else if (command.type === 'solve') {
      if (this.state.stage !== 'collecting_fit' || !validSimple(command, 'solve')) {
        result = this._failure('stage_invalid');
      } else if (this.state.fitSamples.length < 8) result = this._failure('fit_samples_insufficient');
      else {
        try {
          const report = await this.solver({operation:'solve',fit_samples:clone(this.state.fitSamples),
            thresholds:clone(this.thresholds)});
          if(!unchanged())return this._failure('session_revision_conflict');
          result = this._commit(() => {
            this.state.solveReport = clone(report);
            if (report.accepted === true && report.classification !== 'red') {
              this.state.stage = 'collecting_validation';
            }
          });
          if (report.accepted !== true || report.classification === 'red') result.accepted = false;
        } catch { if(!unchanged())return this._failure('session_revision_conflict');result = this._failure('solver_failed'); }
      }
    } else if (command.type === 'record_validation') {
      if (this.state.stage !== 'collecting_validation') result = this._failure('stage_invalid');
      else if (!validContact(command, 'record_validation')) result = this._failure('contact_evidence_invalid');
      else {
        const sample = this._sample('validation');
        result = sample.accepted === false ? sample
          : this._commit(() => this.state.validationSamples.push(sample));
      }
    } else if (command.type === 'derive') {
      if (this.state.stage !== 'collecting_validation' || !validSimple(command, 'derive')) {
        result = this._failure('stage_invalid');
      } else if (this.state.validationSamples.length < 3) {
        result = this._failure('validation_samples_insufficient');
      } else {
        try {
          const validation = await this.solver({operation:'validate',candidate:clone(this.state.solveReport),
            validation_samples:clone(this.state.validationSamples),thresholds:clone(this.thresholds)});
          if(!unchanged())return this._failure('session_revision_conflict');
          if (validation.accepted !== true) {
            result = this._commit(() => { this.state.validationReport = clone(validation); });
            result.accepted = false;
          } else {
            const probe = this.state.solveReport.probe_tip_flange_m;
            const probeTransform = [[1,0,0,probe[0]],[0,1,0,probe[1]],[0,0,1,probe[2]],[0,0,0,1]];
            const derived = await this.solver({operation:'derive',T_flange_probe_tip:probeTransform,
              distance_m:this.state.measurement.distanceM,
              measurement_uncertainty_m:this.state.measurement.uncertaintyM,
              tool_axis_flange:clone(this.state.measurement.toolAxisFlange)});
            if(!unchanged())return this._failure('session_revision_conflict');
            result = this._commit(() => {
              this.state.validationReport = clone(validation);
              this.state.derivedTcp = clone(derived);
              this.state.stage = 'ready_to_finalize';
            });
          }
        } catch { if(!unchanged())return this._failure('session_revision_conflict');result = this._failure('solver_failed'); }
      }
    } else if (command.type === 'abort' && validSimple(command, 'abort')) {
      result = this._commit(() => { this.state.stage = 'aborted'; });
    } else result = this._failure('request_invalid');
    return this._recordReplay(command, result);
  }
}

module.exports = { TcpCalibrationSession };
