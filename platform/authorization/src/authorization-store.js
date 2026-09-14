'use strict';

const { randomUUID } = require('node:crypto');
const { createContractValidator } = require('../../contracts/src/validator');
const { digestPlan } = require('./canonical-json');

function codedError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

class AuthorizationStore {
  constructor({ clock = Date.now, idFactory = randomUUID } = {}) {
    this.clock = clock;
    this.idFactory = idFactory;
    this.records = new Map();
    this.contracts = createContractValidator();
  }

  issue({ plan, planDigest, expiresAt, authorizedOperations }) {
    const actualDigest = digestPlan(plan);
    if (actualDigest !== planDigest) throw codedError('plan_digest_mismatch', 'Plan digest does not match the immutable plan');
    const expiry = Date.parse(expiresAt);
    if (!Number.isFinite(expiry) || expiry <= this.clock()) throw codedError('authorization_expired', 'Authorization expiry is not in the future');
    const grant = Object.freeze({
      schema: 'thirdhand.task-authorization.v2',
      authorizationId: this.idFactory(),
      taskId: plan.taskId,
      planId: plan.planId,
      planRevision: plan.revision,
      targetRef: plan.targetRef,
      planDigest,
      authorizedOperations: Object.freeze([...authorizedOperations]),
      issuedAt: new Date(this.clock()).toISOString(),
      expiresAt: new Date(expiry).toISOString(),
    });
    const validation = this.contracts.validate('thirdhand.task-authorization.v2', grant);
    if (!validation.ok) throw codedError('authorization_invalid', JSON.stringify(validation.errors));
    this.records.set(grant.authorizationId, { grant, consumedAt: null, revokedAt: null, revokeReason: null });
    return grant;
  }

  inspect(authorizationId) {
    return this.records.get(authorizationId) || null;
  }

  consume({ authorizationId, plan, planDigest, operation }) {
    const record = this.records.get(authorizationId);
    if (!record) throw codedError('authorization_unknown', 'Authorization does not exist');
    if (record.revokedAt !== null) throw codedError('authorization_revoked', record.revokeReason || 'Authorization was revoked');
    if (record.consumedAt !== null) throw codedError('authorization_consumed', 'Authorization was already consumed');
    if (this.clock() >= Date.parse(record.grant.expiresAt)) throw codedError('authorization_expired', 'Authorization expired');
    const actualDigest = digestPlan(plan);
    if (actualDigest !== planDigest || record.grant.planDigest !== planDigest) {
      throw codedError('plan_digest_mismatch', 'Plan digest changed');
    }
    if (record.grant.taskId !== plan.taskId
      || record.grant.planId !== plan.planId
      || record.grant.planRevision !== plan.revision
      || record.grant.targetRef !== plan.targetRef) {
      throw codedError('plan_binding_mismatch', 'Plan identity changed');
    }
    if (!record.grant.authorizedOperations.includes(operation)) {
      throw codedError('operation_not_authorized', 'Operation is outside the grant');
    }
    record.consumedAt = new Date(this.clock()).toISOString();
    return record.grant;
  }

  revokeAll(reason) {
    const revokedAt = new Date(this.clock()).toISOString();
    for (const record of this.records.values()) {
      if (record.consumedAt === null && record.revokedAt === null) {
        record.revokedAt = revokedAt;
        record.revokeReason = reason;
      }
    }
  }

  revoke(authorizationId, reason) {
    const record = this.records.get(authorizationId);
    if (!record || record.consumedAt !== null || record.revokedAt !== null) return false;
    record.revokedAt = new Date(this.clock()).toISOString();
    record.revokeReason = reason;
    return true;
  }
}

module.exports = { AuthorizationStore, codedError };
