'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { authorize } = require('../../../platform/identity/src/policy');

test('permissions deny unknown requests and require both administrator mode and MFA for real operations', () => {
  const base = { userId: '6fb92f31-4649-4b2d-a207-798a2470f4fd', sessionId: '9fae81e1-470f-4328-8bd2-4f6b082b589f', roleVersion: 1 };
  const identities = [
    { name: 'observer', ...base, role: 'observer', mode: 'observe', mfaVerifiedAt: null },
    { name: 'admin observing', ...base, role: 'admin', mode: 'observe', mfaVerifiedAt: null },
    { name: 'admin missing MFA', ...base, role: 'admin', mode: 'admin', mfaVerifiedAt: null },
    { name: 'admin authorized', ...base, role: 'admin', mode: 'admin', mfaVerifiedAt: new Date() }
  ];
  const read = ['telemetry.read','history.read','history.export','simulation.use','video.view','preferences.read','preferences.write'];
  const control = ['sdk.connect','sdk.disconnect','control.request','control.command','control.stop','voice.use','grasp.execute','dummy.execute','admin.users','admin.audit'];
  for (const action of [...read, ...control]) {
    assert.equal(authorize(null, action).ok, false, `anonymous ${action}`);
    for (const principal of identities) {
      const want = principal.name === 'admin authorized' || (read.includes(action) && principal.mode === 'observe');
      assert.equal(authorize(principal, action).ok, want, `${principal.name}: ${action}`);
    }
  }
  assert.equal(authorize(identities[3], 'anything.new').ok, false);
  assert.equal(authorize({ ...base, role: 'operator', mode: 'admin', mfaVerifiedAt: new Date() }, 'sdk.connect').ok, false);
});
