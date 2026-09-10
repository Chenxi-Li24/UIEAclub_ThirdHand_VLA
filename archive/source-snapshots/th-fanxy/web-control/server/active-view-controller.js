'use strict';

const { randomUUID } = require('crypto');
const { authorizeActiveViewMove } = require('./active-view-authorization');

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const CONTENT_ID_PATTERN = /^sha256:[0-9a-f]{64}$/;
const MAX_SOURCE_TO_EXPIRY_NS = 2_000_000_000n;
const MAX_BROWSER_CONFIRMATION_TTL_MS = 200;
const PROPOSAL_EVENT_KEYS = new Set([
  'type', 'session_id', 'proposal_id', 'identity_id', 'kind', 'source_frame_id',
  'source_monotonic_ns', 'expires_ns', 'target_pose_id', 'joints_deg',
  'delta_base_m', 'optical_axis_base', 'rotation_delta_rad', 'evidence_ids',
  'active_view_execution_enabled', 'robot_execution_enabled',
]);
const ACK_EVENT_KEYS = new Set([
  'type', 'session_id', 'proposal_id', 'evidence_ids',
  'active_view_execution_enabled', 'robot_execution_enabled',
]);

function exactKeys(value, keys) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

function validUuid(value) {
  return typeof value === 'string' && UUID_PATTERN.test(value);
}

function evidenceSuperset(candidate, required) {
  if (!Array.isArray(candidate) || !Array.isArray(required) || candidate.length > 32 ||
      candidate.some(value => !CONTENT_ID_PATTERN.test(value)) ||
      new Set(candidate).size !== candidate.length) return false;
  const available = new Set(candidate);
  return required.every(value => available.has(value));
}

function protocolReason(reason) {
  const normalized = String(reason || '')
    .toLowerCase()
    .replace(/[^a-z0-9_.-]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 128);
  return normalized || 'active_view_aborted';
}

class ActiveViewController {
  constructor({
    requested,
    loadApproval,
    limits,
    getRobotState,
    sendRobot,
    sendVision,
    auditLog,
    nowMs = Date.now,
    idFactory = randomUUID,
    motionTimeoutMs = 30_000,
    visionAckTimeoutMs = 2_000,
  }) {
    this.requested = requested === true;
    this.loadApproval = loadApproval;
    this.limits = limits;
    this.getRobotState = getRobotState;
    this.sendRobot = sendRobot;
    this.sendVision = sendVision;
    this.auditLog = auditLog;
    this.nowMs = nowMs;
    this.idFactory = idFactory;
    this.motionTimeoutMs = motionTimeoutMs;
    this.visionAckTimeoutMs = visionAckTimeoutMs;
    this.session = null;
    this.pending = null;
    this.inFlight = null;
    this.awaitingVisionAck = null;
    this.approvalId = null;
  }

  _audit(event) {
    this.auditLog.append(event);
  }

  begin(message) {
    if (!exactKeys(message, new Set(['sessionId', 'identityId'])) ||
        !validUuid(message.sessionId) || !Number.isSafeInteger(message.identityId) || message.identityId < 0) {
      return { accepted: false, reason: 'begin_command_invalid' };
    }
    if (this.session || this.pending || this.awaitingVisionAck || this.inFlight) {
      return { accepted: false, reason: 'session_active' };
    }
    try {
      this._audit({ action: 'session_begin', sessionId: message.sessionId, identityId: message.identityId });
    } catch {
      return { accepted: false, reason: 'audit_write_failed' };
    }
    const command = {
      type: 'active_view_start', session_id: message.sessionId, identity_id: message.identityId,
    };
    if (this.sendVision(command) !== true) return { accepted: false, reason: 'vision_transport_unavailable' };
    this.session = {
      sessionId: message.sessionId,
      identityId: message.identityId,
      proposalId: null,
      evidenceIds: null,
      refinementSteps: 0,
      activeMotion: false,
      operatorConfirmed: false,
    };
    this.approvalId = null;
    return { accepted: true, sessionId: message.sessionId };
  }

  onVisionEvent(event) {
    if (event?.type === 'active_view_abort') {
      if (this.session && typeof event.session_id === 'string' &&
          event.session_id !== this.session.sessionId) {
        return { handled: false, reason: 'stale_vision_session' };
      }
      const reason = typeof event.reason === 'string' && event.reason.length <= 128
        ? event.reason : 'vision_abort';
      return this._abort(reason);
    }
    if (event?.type === 'active_view_operator_acknowledged') {
      if (!this.session || !this.awaitingVisionAck) {
        return { handled: false, reason: 'vision_ack_not_expected' };
      }
      if (event.session_id !== this.session.sessionId) {
        return { handled: false, reason: 'stale_vision_session' };
      }
      if (!exactKeys(event, ACK_EVENT_KEYS) || !validUuid(event.session_id) ||
          !validUuid(event.proposal_id) ||
          event.active_view_execution_enabled !== false ||
          event.robot_execution_enabled !== false) {
        return this._abort('vision_ack_schema_invalid');
      }
      if (event.proposal_id !== this.awaitingVisionAck.proposalId) {
        return this._abort('vision_ack_correlation_failed');
      }
      if (!evidenceSuperset(event.evidence_ids, this.awaitingVisionAck.evidenceIds)) {
        return this._abort('evidence_changed');
      }
      return this._dispatchAcknowledgedMotion();
    }
    if (event?.type === 'active_view_state') {
      if (!this.session) return { handled: false, reason: 'session_unavailable' };
      if (event.session_id !== this.session.sessionId) {
        return { handled: false, reason: 'stale_vision_session' };
      }
      // The vision coordinator's state carries the union of fixed foundation
      // evidence and this proposal's evidence.  The actionable proposal is
      // still bound exactly to the approval; a state update is acceptable
      // only while it remains a valid superset of that bound evidence.
      if (Array.isArray(this.session.evidenceIds) &&
          !evidenceSuperset(event.evidence_ids, this.session.evidenceIds)) {
        return this._abort('evidence_changed');
      }
      if (event.phase === 'complete') return this._complete();
      if (['aborted', 'idle'].includes(event.phase)) {
        const reason = Array.isArray(event.reasons) && typeof event.reasons[0] === 'string'
          ? `vision_${event.reasons[0].slice(0, 96)}` : `vision_${event.phase}`;
        return this._abort(reason);
      }
      return { handled: false, reason: 'state_observed' };
    }
    if (event?.type === 'active_view_evidence_changed') {
      const changed = !this.session || !Array.isArray(this.session.evidenceIds) ||
        !evidenceSuperset(event.evidence_ids, this.session.evidenceIds);
      if (!changed) return { handled: false, reason: 'evidence_unchanged' };
      return this._abort('evidence_changed');
    }
    if (event?.type !== 'active_view_move_proposal') return { handled: false, reason: 'event_ignored' };
    if (!this.session) return { accepted: false, reason: 'session_unavailable' };
    if (!exactKeys(event, PROPOSAL_EVENT_KEYS)) return { accepted: false, reason: 'proposal_schema_invalid' };
    if (!validUuid(event.session_id) || !validUuid(event.proposal_id)) {
      return { accepted: false, reason: 'proposal_id_invalid' };
    }
    if (event.session_id !== this.session.sessionId) {
      return { handled: false, reason: 'stale_vision_session' };
    }
    if (event.identity_id !== this.session.identityId) {
      return this._abort('proposal_correlation_failed');
    }
    let sourceNs;
    let expiryNs;
    try {
      sourceNs = BigInt(event.source_monotonic_ns);
      expiryNs = BigInt(event.expires_ns);
    } catch {
      return { accepted: false, reason: 'proposal_timestamp_invalid' };
    }
    const ttlNs = expiryNs - sourceNs;
    // The source stamp belongs to the captured image, while expiry is assigned
    // when inference finishes.  Their difference therefore includes inference
    // latency as well as the configured proposal TTL.  Accept only the
    // vision-side two-second source-to-expiry ceiling, then grant the
    // browser at most 200 ms from receipt for confirmation.
    if (sourceNs < 0n || ttlNs <= 0n || ttlNs > MAX_SOURCE_TO_EXPIRY_NS) {
      return { accepted: false, reason: 'proposal_ttl_invalid' };
    }
    if (this.awaitingVisionAck || this.inFlight) {
      return { accepted: false, reason: 'active_view_motion_active' };
    }
    const receivedAtMs = this.nowMs();
    const normalized = {
      trusted: true,
      sessionId: event.session_id,
      proposalId: event.proposal_id,
      identityId: event.identity_id,
      kind: event.kind === 'coarse_pose' ? 'coarse' : event.kind,
      receivedAtMs,
      expiresAtMs: receivedAtMs + Math.min(
        MAX_BROWSER_CONFIRMATION_TTL_MS,
        Number(ttlNs) / 1e6,
      ),
      targetPoseId: event.target_pose_id,
      jointsDeg: event.joints_deg,
      deltaBaseM: event.delta_base_m,
      opticalAxisBase: event.optical_axis_base,
      rotationDeltaRad: event.rotation_delta_rad,
      evidenceIds: event.evidence_ids,
    };
    try {
      this._audit({
        action: 'proposal_received', sessionId: normalized.sessionId,
        proposalId: normalized.proposalId, identityId: normalized.identityId,
        requestId: null, evidenceIds: normalized.evidenceIds, kind: normalized.kind,
      });
    } catch {
      return { accepted: false, reason: 'audit_write_failed' };
    }
    this.pending = normalized;
    this.session.proposalId = normalized.proposalId;
    this.session.evidenceIds = [...normalized.evidenceIds];
    this.session.operatorConfirmed = false;
    return { accepted: true, proposalId: normalized.proposalId };
  }

  confirm(message) {
    if (!exactKeys(message, new Set(['sessionId', 'proposalId']))) {
      return { approved: false, reason: 'browser_coordinates_forbidden' };
    }
    if (!this.pending || message.sessionId !== this.pending.sessionId ||
        message.proposalId !== this.pending.proposalId) {
      return { approved: false, reason: 'proposal_not_pending' };
    }
    if (this.awaitingVisionAck) return { approved: false, reason: 'vision_ack_pending' };
    let approval;
    try { approval = this.loadApproval(); } catch { approval = null; }
    const authorizationSession = { ...this.session, operatorConfirmed: true };
    const decision = authorizeActiveViewMove({
      requested: this.requested,
      approval,
      proposal: this.pending,
      robot: this.getRobotState(),
      session: authorizationSession,
      nowMs: this.nowMs(),
      limits: this.limits,
    });
    if (!decision.approved) {
      try {
        this._audit({
          action: 'motion_rejected', reason: decision.reason,
          sessionId: this.pending.sessionId, proposalId: this.pending.proposalId,
          requestId: null, evidenceIds: this.pending.evidenceIds,
        });
      } catch { return { approved: false, reason: 'audit_write_failed' }; }
      return decision;
    }
    this.approvalId = approval.content_id;
    const requestId = this.idFactory();
    if (!validUuid(requestId)) return { approved: false, reason: 'request_id_invalid' };
    const identifiers = {
      sessionId: this.pending.sessionId,
      proposalId: this.pending.proposalId,
      requestId,
      evidenceIds: this.pending.evidenceIds,
    };
    try {
      this._audit({ action: 'motion_authorized', reason: 'authorized', ...identifiers });
    } catch {
      return { approved: false, reason: 'audit_write_failed' };
    }
    const robotCommand = { ...decision.command, request_id: requestId };
    this.session.operatorConfirmed = true;
    this.awaitingVisionAck = {
      ...identifiers,
      robotCommand,
      startedAtMs: this.nowMs(),
    };
    if (this.sendVision({
      type: 'active_view_operator_confirmed',
      session_id: identifiers.sessionId,
      proposal_id: identifiers.proposalId,
    }) !== true) {
      this._abort('vision_transport_unavailable');
      return { approved: false, reason: 'vision_transport_unavailable' };
    }
    return { ...decision, requestId, status: 'awaiting_vision_ack' };
  }

  _dispatchAcknowledgedMotion() {
    const acknowledged = this.awaitingVisionAck;
    if (!acknowledged || !this.session || !this.pending) {
      return { handled: false, reason: 'vision_ack_not_expected' };
    }
    if (this.sendRobot(acknowledged.robotCommand) !== true) {
      this._abort('robot_transport_unavailable');
      return { handled: true, reason: 'robot_transport_unavailable' };
    }
    const { robotCommand, ...identifiers } = acknowledged;
    this.inFlight = {
      ...identifiers,
      expectedCommand: robotCommand.cmd === 'move_l_delta' ? 'move_l' : 'move_joint',
    };
    this.awaitingVisionAck = null;
    this.pending = null;
    this.session.activeMotion = true;
    if (robotCommand.cmd === 'move_l_delta') this.session.refinementSteps += 1;
    this.sendVision({
      type: 'active_view_motion_started', session_id: acknowledged.sessionId,
      proposal_id: acknowledged.proposalId, request_id: acknowledged.requestId,
    });
    try { this._audit({ action: 'motion_sent', reason: null, ...identifiers }); } catch {
      this._abort('audit_write_failed');
      return { handled: true, reason: 'audit_write_failed' };
    }
    return { handled: true, status: 'motion_sent' };
  }

  cancel(message) {
    if (!exactKeys(message, new Set(['sessionId'])) || !this.session ||
        message.sessionId !== this.session.sessionId) {
      return { accepted: false, reason: 'cancel_command_invalid' };
    }
    return this._abort('operator_cancelled');
  }

  onRobotEvent(event) {
    if (event?.type === 'software_stop') return this._abort('software_stop');
    if (event?.type === 'connection' && event.connected === false) return this._abort('robot_disconnected');
    if (event?.type === 'grasp_started') return this._abort('grasp_started');
    if (!this.inFlight || !['command_complete', 'error'].includes(event?.type)) {
      return { handled: false, reason: 'event_ignored' };
    }
    if (event.request_id !== this.inFlight.requestId) return { handled: false, reason: 'request_mismatch' };
    const current = this.inFlight;
    if (event.type === 'command_complete' && event.command !== current.expectedCommand) {
      return { handled: false, reason: 'command_mismatch' };
    }
    if (event.type === 'command_complete' && current.expectedCommand === 'move_l' &&
        event.reached !== true) {
      return this._abort('cartesian_target_not_reached');
    }
    if (event.type === 'command_complete') {
      this.inFlight = null;
      this.session.activeMotion = false;
      this.sendVision({
        type: 'active_view_motion_completed', session_id: current.sessionId,
        request_id: current.requestId,
      });
      try { this._audit({ action: 'motion_completed', reason: null, ...current }); } catch {
        return this._abort('audit_write_failed');
      }
      return { handled: true, status: 'completed' };
    }
    const reason = typeof event.message === 'string' && event.message.length <= 96
      ? `robot_error:${event.message}` : 'robot_error';
    try { this._audit({ action: 'motion_failed', reason, ...current }); } catch { /* already stopped */ }
    this._abort(reason);
    return { handled: true, status: 'failed' };
  }

  checkTimeout() {
    const now = this.nowMs();
    if (this.awaitingVisionAck &&
        now - this.awaitingVisionAck.startedAtMs > this.visionAckTimeoutMs) {
      return this._abort('vision_ack_timeout');
    }
    if (this.inFlight && now - this.inFlight.startedAtMs > this.motionTimeoutMs) {
      return this._abort('motion_timeout');
    }
    if (!this.awaitingVisionAck && this.pending && now >= this.pending.expiresAtMs) {
      return this._abort('proposal_expired');
    }
    if (this.requested && this.session) {
      let approval;
      try { approval = this.loadApproval(); } catch { approval = null; }
      if (!approval || !Number.isFinite(approval.expires_at_ms) || now >= approval.expires_at_ms) {
        return this._abort('approval_expired');
      }
      if (this.approvalId !== null && approval.content_id !== this.approvalId) {
        return this._abort('approval_changed');
      }
    }
    return { handled: false, reason: 'not_timed_out' };
  }

  _complete() {
    if (!this.session) return { handled: false, reason: 'session_unavailable' };
    const sessionId = this.session.sessionId;
    const proposalId = this.session.proposalId || null;
    const evidenceIds = this.session.evidenceIds || [];
    try {
      this._audit({
        action: 'session_completed', reason: null, sessionId, proposalId,
        requestId: null, evidenceIds,
      });
    } catch {
      return this._abort('audit_write_failed');
    }
    this.pending = null;
    this.awaitingVisionAck = null;
    this.inFlight = null;
    this.session = null;
    this.approvalId = null;
    return { handled: true, status: 'completed' };
  }

  _abort(reason) {
    if (!this.session && !this.pending && !this.awaitingVisionAck && !this.inFlight) {
      return { handled: false, reason: 'session_unavailable' };
    }
    const sessionId = this.session?.sessionId || this.pending?.sessionId ||
      this.awaitingVisionAck?.sessionId || this.inFlight?.sessionId;
    const requestId = this.inFlight?.requestId || this.awaitingVisionAck?.requestId;
    const proposalId = this.pending?.proposalId || this.awaitingVisionAck?.proposalId ||
      this.inFlight?.proposalId || this.session?.proposalId || null;
    const evidenceIds = this.pending?.evidenceIds || this.awaitingVisionAck?.evidenceIds ||
      this.inFlight?.evidenceIds || this.session?.evidenceIds || [];
    if (requestId) {
      this.sendVision({
        type: 'active_view_motion_failed', session_id: sessionId,
        request_id: requestId, reason: protocolReason(reason),
      });
    } else if (sessionId) {
      this.sendVision({ type: 'active_view_cancel', session_id: sessionId });
    }
    this.pending = null;
    this.awaitingVisionAck = null;
    this.inFlight = null;
    this.session = null;
    this.approvalId = null;
    try {
      this._audit({
        action: 'session_aborted', reason, sessionId, proposalId,
        requestId: requestId || null, evidenceIds,
      });
    } catch { /* fail closed: state has already been cleared */ }
    return { handled: true, reason };
  }
}

module.exports = { ActiveViewController };
