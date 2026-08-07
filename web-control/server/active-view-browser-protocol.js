'use strict';

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function exactKeys(value, keys) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

function rejected(reason) {
  return { accepted: false, reason };
}

function parseActiveViewBrowserCommand(message) {
  if (!message || typeof message !== 'object' || Array.isArray(message)) {
    return rejected('browser_command_invalid');
  }
  if (message.cmd === 'start_active_view') {
    if (!exactKeys(message, new Set(['cmd', 'identityId']))) {
      return rejected('browser_command_keys_invalid');
    }
    if (!Number.isSafeInteger(message.identityId) || message.identityId < 0) {
      return rejected('identity_id_invalid');
    }
    return { accepted: true, command: 'start', identityId: message.identityId };
  }
  if (message.cmd === 'confirm_active_view_step') {
    if (!exactKeys(message, new Set(['cmd', 'sessionId', 'proposalId']))) {
      return rejected('browser_command_keys_invalid');
    }
    if (!UUID_PATTERN.test(message.sessionId) || !UUID_PATTERN.test(message.proposalId)) {
      return rejected('active_view_id_invalid');
    }
    return {
      accepted: true,
      command: 'confirm',
      sessionId: message.sessionId,
      proposalId: message.proposalId,
    };
  }
  if (message.cmd === 'cancel_active_view') {
    if (!exactKeys(message, new Set(['cmd', 'sessionId']))) {
      return rejected('browser_command_keys_invalid');
    }
    if (!UUID_PATTERN.test(message.sessionId)) return rejected('active_view_id_invalid');
    return { accepted: true, command: 'cancel', sessionId: message.sessionId };
  }
  return rejected('browser_command_type_invalid');
}

function authorizeActiveViewStart({
  identityId,
  trustedTargets,
  activeViewActive,
  graspActive,
  motionActive,
}) {
  if (activeViewActive === true) return { approved: false, reason: 'active_view_session_active' };
  if (graspActive === true) return { approved: false, reason: 'grasp_active' };
  if (motionActive === true) return { approved: false, reason: 'robot_motion_active' };
  if (!Array.isArray(trustedTargets) ||
      !trustedTargets.some(target => target && target.identityId === identityId)) {
    return { approved: false, reason: 'identity_not_fresh_or_confirmed' };
  }
  return { approved: true, identityId };
}

module.exports = { authorizeActiveViewStart, parseActiveViewBrowserCommand };
