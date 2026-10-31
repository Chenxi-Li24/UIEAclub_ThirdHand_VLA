'use strict';
const { json, requireFields } = require('../http');
const { writeAudit }=require('../../../../platform/storage/src/audit');
async function authRoute({ path, request, body, response, accounts, sessions, sourceKey,pool }) {
  if (path === '/api/v1/auth/register') {
    requireFields(body, ['username','email','displayName','password','locale','role']);
    return json(response, 201, await accounts.register({ ...body, sourceKey }));
  }
  if (path === '/api/v1/auth/login') {
    requireFields(body, ['login','password','requestedMode','totp','recoveryCode']);
    const proof = await accounts.authenticate({ ...body, sourceKey });
    const previous = await sessions.resolveSession(request);
    const session = await sessions.issue(proof);
    if (previous) {
      try { await sessions.revokeSession({sessionId:previous.sessionId,reason:'browser_login_replaced'}); }
      catch(error) { await sessions.revokeSession({sessionId:session.sessionId,reason:'login_replacement_failed'}).catch(()=>{}); throw error; }
    }
    await writeAudit(pool,{actorUserId:proof.userId,eventCode:'identity.login.success',outcome:'success',context:{sourceHash:sourceKey}});
    return json(response, 200, { userId:proof.userId, mode: session.mode, csrfToken: session.csrfToken, next: '/control' }, { 'Set-Cookie':session.cookie });
  }
  if (path === '/api/v1/auth/verify-email') {
    requireFields(body, ['token']); return json(response, 200, await accounts.verifyEmail(body));
  }
  if (path === '/api/v1/auth/forgot-password') {
    requireFields(body, ['email']); return json(response, 202, await accounts.requestPasswordReset({ ...body, sourceKey }));
  }
  if (path === '/api/v1/auth/resend-verification') {
    requireFields(body, ['email']); return json(response, 202, await accounts.resendVerification({ ...body, sourceKey }));
  }
  if (path === '/api/v1/auth/reset-password') {
    requireFields(body, ['token','password']); return json(response, 200, await accounts.resetPassword(body));
  }
  return false;
}
module.exports = { authRoute };
