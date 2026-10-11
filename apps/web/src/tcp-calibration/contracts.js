'use strict';

const REQUEST_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$/;

function exactKeys(value, keys) {
  return value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).length === keys.length
    && keys.every(key => Object.hasOwn(value, key));
}

function vector(value, length) {
  return Array.isArray(value) && value.length === length && value.every(Number.isFinite);
}

function validRequestId(value) {
  return typeof value === 'string' && REQUEST_ID.test(value);
}

function validStart(command) {
  if (!exactKeys(command, ['type', 'requestId', 'operator', 'measurement', 'confirmations'])
      || command.type !== 'start' || !validRequestId(command.requestId)
      || typeof command.operator !== 'string' || !command.operator.trim()
      || !exactKeys(command.measurement, ['distanceM', 'uncertaintyM', 'toolAxisFlange'])
      || !Number.isFinite(command.measurement.distanceM) || command.measurement.distanceM < 0
      || command.measurement.distanceM > 1
      || !Number.isFinite(command.measurement.uncertaintyM)
      || command.measurement.uncertaintyM <= 0 || command.measurement.uncertaintyM > 0.010
      || !vector(command.measurement.toolAxisFlange, 3)
      || Math.abs(Math.hypot(...command.measurement.toolAxisFlange) - 1) > 1e-9
      || !exactKeys(command.confirmations,
        ['probeCentered', 'pivotFixed', 'estopReady', 'manualTeachOnly'])) return false;
  return Object.values(command.confirmations).every(value => value === true);
}

function validContact(command, type) {
  return exactKeys(command, ['type', 'requestId', 'contactConfirmed', 'probeUnloaded'])
    && command.type === type && validRequestId(command.requestId)
    && command.contactConfirmed === true && command.probeUnloaded === true;
}

function validSimple(command, type) {
  return exactKeys(command, ['type', 'requestId'])
    && command.type === type && validRequestId(command.requestId);
}

function validDelete(command) {
  return exactKeys(command, ['type', 'requestId', 'sampleId'])
    && command.type === 'delete_fit' && validRequestId(command.requestId)
    && typeof command.sampleId === 'string' && command.sampleId.length > 0;
}

module.exports = { exactKeys, validContact, validDelete, validRequestId, validSimple, validStart };
