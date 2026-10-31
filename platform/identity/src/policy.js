'use strict';
const observeActions = new Set(['telemetry.read','history.read','history.export','simulation.use','video.view','preferences.read','preferences.write','profile.read','profile.write']);
const adminActions = new Set(['sdk.connect','sdk.disconnect','control.request','control.command','control.stop','voice.use','grasp.execute','dummy.execute','admin.users','admin.audit']);
function authorize(principal, action) {
  if (!principal?.userId || !principal.sessionId || !['observer','admin'].includes(principal.role) || !['observe','admin'].includes(principal.mode)) return { ok: false, code: 'UNAUTHENTICATED' };
  if (principal.mode === 'admin' && (principal.role !== 'admin' || !principal.mfaVerifiedAt)) return { ok: false, code: 'FORBIDDEN' };
  if (observeActions.has(action)) return { ok: true, code: 'OK' };
  if (adminActions.has(action) && principal.role === 'admin' && principal.mode === 'admin' && principal.mfaVerifiedAt) return { ok: true, code: 'OK' };
  return { ok: false, code: 'FORBIDDEN' };
}
module.exports = { authorize };
