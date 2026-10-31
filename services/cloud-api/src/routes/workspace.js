'use strict';
const { json } = require('../http');
const { authorize } = require('../../../../platform/identity/src/policy');
const { identityError } = require('../../../../platform/identity/src/errors');

async function workspaceRoute({ path, response, principal }) {
  const actions = [
    ['/api/v1/control/', 'control.request'], ['/api/v1/sdk/', 'sdk.connect'],
    ['/api/v1/voice/', 'voice.use'], ['/api/v1/grasp/', 'grasp.execute'], ['/api/v1/dummy/', 'dummy.execute']
  ];
  const entry = actions.find(([prefix]) => path.startsWith(prefix));
  if (!entry) return false;
  if (!authorize(principal, entry[1]).ok) throw identityError('FORBIDDEN');
  return json(response, 503, { error:'DEVICE_CONTROL_UNAVAILABLE' });
}
module.exports = { workspaceRoute };
