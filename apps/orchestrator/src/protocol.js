'use strict';

const PLAN_PROTOCOL = 'thirdhand.plan.v1';

function protocolError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

function parseClientMessage(data) {
  if (Buffer.byteLength(data) > 16 * 1024) {
    throw protocolError('message_invalid', 'Plan message exceeds 16 KiB');
  }
  let message;
  try {
    message = JSON.parse(data.toString('utf8'));
  } catch {
    throw protocolError('invalid_json', 'Invalid JSON message');
  }
  if (!message || typeof message !== 'object' || Array.isArray(message)) {
    throw protocolError('message_invalid', 'Plan message must be an object');
  }
  if (!['candidate.submit', 'authorization.grant', 'proposal.cancel'].includes(message.type)) {
    throw protocolError('message_unsupported', 'Unsupported Plan message type');
  }
  const exactKeys = (value, expected) => {
    const keys = Object.keys(value).sort();
    return keys.length === expected.length
      && expected.slice().sort().every((key, index) => key === keys[index]);
  };
  const boundedString = (value, maximum = 256) => (
    typeof value === 'string' && value.length > 0 && value.length <= maximum
  );
  if (message.type === 'candidate.submit') {
    const candidate = message.candidate;
    if (!exactKeys(message, ['type', 'candidate'])
      || !candidate || typeof candidate !== 'object' || Array.isArray(candidate)
      || !exactKeys(candidate, ['candidateId', 'traceId', 'intent', 'source', 'transcript'])
      || !boundedString(candidate.candidateId)
      || !boundedString(candidate.traceId)
      || !boundedString(candidate.intent)
      || !['voice', 'text'].includes(candidate.source)
      || !boundedString(candidate.transcript, 2000)) {
      throw protocolError('message_invalid', 'Candidate message does not match the Plan protocol');
    }
  } else if (message.type === 'authorization.grant') {
    if (!exactKeys(message, ['type', 'proposalId', 'planId', 'planRevision', 'planDigest'])
      || !boundedString(message.proposalId)
      || !boundedString(message.planId)
      || !Number.isInteger(message.planRevision) || message.planRevision < 1
      || !/^sha256:[0-9a-f]{64}$/.test(message.planDigest)) {
      throw protocolError('message_invalid', 'Authorization message does not match the Plan protocol');
    }
  } else if (!exactKeys(message, ['type', 'proposalId', 'reason'])
    || !boundedString(message.proposalId)
    || !boundedString(message.reason, 64)) {
    throw protocolError('message_invalid', 'Cancellation message does not match the Plan protocol');
  }
  return message;
}

module.exports = { PLAN_PROTOCOL, parseClientMessage, protocolError };
