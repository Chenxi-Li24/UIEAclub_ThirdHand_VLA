const PLAN_PROTOCOL = 'thirdhand.plan.v1';
const KNOWN_SERVER_TYPES = new Set([
  'plan.proposed',
  'plan.rejected',
  'proposal.cancelled',
  'authorization.granted',
  'execution.started',
  'skill.result',
]);

function normalizeSource(source) {
  return source === 'text' ? 'text' : 'voice';
}

function validServerMessage(message) {
  if (message.type === 'plan.proposed') {
    const proposal = message.proposal;
    return Boolean(
      proposal
      && typeof proposal.proposalId === 'string'
      && typeof proposal.candidateId === 'string'
      && /^sha256:[0-9a-f]{64}$/.test(proposal.planDigest)
      && typeof proposal.plan?.planId === 'string'
      && Number.isInteger(proposal.plan?.revision)
    );
  }
  if (message.type === 'plan.rejected') return typeof message.code === 'string';
  if (message.type === 'proposal.cancelled') return typeof message.proposalId === 'string';
  if (message.type === 'authorization.granted') return Boolean(message.authorization && typeof message.authorization === 'object');
  if (message.type === 'execution.started') return typeof message.taskId === 'string';
  if (message.type === 'skill.result') {
    return Boolean(message.result && ['completed', 'interrupted', 'failed'].includes(message.result.status));
  }
  return false;
}

export class PlanChannel {
  constructor(wsClient) {
    this.wsClient = wsClient;
    this.connected = Boolean(wsClient?.connected);
    this.pendingCandidateId = null;
    this.proposal = null;
    this.grantSent = false;
    this.cancelOnProposalReason = null;
    this.listeners = new Map();
    wsClient?.on?.('message', message => this._handleMessage(message));
    wsClient?.on?.('ws_connection', state => this._handleConnection(state));
  }

  static get protocol() {
    return PLAN_PROTOCOL;
  }

  on(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  isReady() {
    return Boolean(this.connected && this.wsClient?.connected);
  }

  canConfirm() {
    return Boolean(this.isReady() && this.proposal && !this.grantSent);
  }

  submitCandidate(candidate, source = 'voice') {
    if (!this.isReady() || this.pendingCandidateId || !candidate) return false;
    const normalized = {
      candidateId: candidate.candidateId,
      traceId: candidate.traceId,
      intent: candidate.intent,
      source: normalizeSource(candidate.source || source),
      transcript: candidate.transcript || candidate.sourceText,
    };
    if (Object.values(normalized).some(value => typeof value !== 'string' || value.length === 0)) return false;
    if (!this.wsClient.send({ type: 'candidate.submit', candidate: normalized })) return false;
    this.pendingCandidateId = normalized.candidateId;
    this.proposal = null;
    this.grantSent = false;
    return true;
  }

  grantAuthorization(proposal = this.proposal) {
    if (!this.canConfirm() || !proposal || proposal.proposalId !== this.proposal.proposalId) return false;
    const message = {
      type: 'authorization.grant',
      proposalId: proposal.proposalId,
      planId: proposal.plan?.planId,
      planRevision: proposal.plan?.revision,
      planDigest: proposal.planDigest,
    };
    if (!this.wsClient.send(message)) return false;
    this.grantSent = true;
    return true;
  }

  cancelProposal(reason = 'user_rejected') {
    if (!this.isReady() || !this.pendingCandidateId || this.grantSent) return false;
    if (!this.proposal) {
      this.cancelOnProposalReason = reason;
      return true;
    }
    const sent = this.wsClient.send({
      type: 'proposal.cancel',
      proposalId: this.proposal.proposalId,
      reason,
    });
    if (sent) this._clearPlan();
    return sent;
  }

  _handleConnection(state) {
    this.connected = Boolean(state?.connected);
    if (!this.connected) this._clearPlan();
    this._emit('ws_connection', { connected: this.connected });
  }

  _handleMessage(message) {
    if (!message || typeof message.type !== 'string' || !KNOWN_SERVER_TYPES.has(message.type)) {
      this._emit('channel.error', {
        type: 'channel.error',
        code: 'unsupported_server_message',
        message: 'Plan service returned an unsupported or malformed message',
      });
      return;
    }
    if (!validServerMessage(message)) {
      this._emit('channel.error', {
        type: 'channel.error',
        code: 'malformed_server_message',
        message: 'Plan service returned a malformed message',
      });
      return;
    }
    if (message.type === 'plan.proposed') {
      if (message.proposal?.candidateId !== this.pendingCandidateId) return;
      this.proposal = message.proposal;
      this.grantSent = false;
      if (this.cancelOnProposalReason) {
        const reason = this.cancelOnProposalReason;
        this.cancelOnProposalReason = null;
        this.cancelProposal(reason);
        return;
      }
    } else if (message.type === 'proposal.cancelled') {
      this._clearPlan();
    } else if (message.type === 'plan.rejected' && !this.grantSent) {
      this._clearPlan();
    } else if (message.type === 'skill.result') {
      this._clearPlan();
    }
    this._emit(message.type, message);
    this._emit('message', message);
  }

  _clearPlan() {
    this.pendingCandidateId = null;
    this.proposal = null;
    this.grantSent = false;
    this.cancelOnProposalReason = null;
  }

  _emit(type, message) {
    for (const listener of this.listeners.get(type) || []) listener(message);
  }
}

export { PLAN_PROTOCOL };
