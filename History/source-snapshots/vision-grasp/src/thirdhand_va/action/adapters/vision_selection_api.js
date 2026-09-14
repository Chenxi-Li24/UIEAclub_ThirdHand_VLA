'use strict';

const { randomUUID } = require('crypto');

function createVisionSelectionHandler({ cameraBridge, makeRequestId = randomUUID }) {
  if (!cameraBridge || typeof cameraBridge.send !== 'function') {
    throw new TypeError('cameraBridge.send is required');
  }
  return (request, response) => {
    const numericIndex = request.body?.index;
    const usesNumericIndex = numericIndex !== undefined;
    const side = usesNumericIndex ? 'left' : request.body?.side;
    const ordinal = usesNumericIndex ? numericIndex : request.body?.ordinal;
    if (!Number.isSafeInteger(ordinal) || ordinal < 1 || ordinal > 32 ||
        (!usesNumericIndex && !['left', 'right'].includes(side))) {
      response.status(400).json({
        accepted: false,
        reason: usesNumericIndex
          ? 'selection_requires_positive_index'
          : 'selection_requires_side_and_positive_ordinal',
        robot_control_enabled: false,
      });
      return;
    }
    const suppliedId = request.body?.request_id;
    const requestId = typeof suppliedId === 'string' && suppliedId.length > 0 &&
      suppliedId.length <= 128 ? suppliedId : makeRequestId();
    const accepted = cameraBridge.send({
      type: 'select_bottle', side, ordinal, request_id: requestId,
    });
    response.status(accepted ? 202 : 503).json({
      accepted,
      request_id: requestId,
      selection: usesNumericIndex ? { index: ordinal } : { side, ordinal },
      robot_control_enabled: false,
      reason: accepted ? null : 'vision_bridge_unavailable',
    });
  };
}

module.exports = { createVisionSelectionHandler };
