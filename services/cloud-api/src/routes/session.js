'use strict';
const { json, requireFields } = require('../http');
const { createUsersRepository } = require('../../../../platform/storage/src/users');
async function sessionRoute({ path, request, response, body, principal, sessions, accounts, mfa, pool, sourceKey }) {
  if (path === '/api/v1/session' && request.method === 'GET') return json(response, 200, {
    userId:principal.userId,sessionId:principal.sessionId,role:principal.role,mode:principal.mode,roleVersion:principal.roleVersion,csrfToken:principal.csrfToken
  });
  if (request.method !== 'POST') return false;
  if (path === '/api/v1/session/logout') {
    requireFields(body, []); await sessions.revokeSession({ sessionId:principal.sessionId,reason:'logout' });
    return json(response, 200, { loggedOut:true }, { 'Set-Cookie':sessions.clearCookie() });
  }
  if (path === '/api/v1/session/activity') {
    requireFields(body, []); await sessions.recordHumanActivity(principal); return json(response, 200, { recorded:true });
  }
  if (path === '/api/v1/session/mode') {
    requireFields(body, ['requestedMode','password','totp','recoveryCode']);
    const user = await createUsersRepository(pool).findById(principal.userId);
    const proof = body.requestedMode === 'observe' ? { userId:principal.userId,mode:'observe' } :
      await accounts.authenticate({ ...body, login:user.username,sourceKey });
    const issued = await sessions.issue(proof);
    await sessions.revokeSession({ sessionId:principal.sessionId,reason:'mode_changed' });
    return json(response, 200, { mode:issued.mode,csrfToken:issued.csrfToken }, { 'Set-Cookie':issued.cookie });
  }
  if (path === '/api/v1/mfa/setup') {
    requireFields(body, ['password']);
    return json(response, 200, await accounts.beginMfaSetup({ userId:principal.userId,password:body.password,sourceKey }));
  }
  if(path==='/api/v1/mfa/prepare'){
    requireFields(body,['password']);
    return json(response,200,await accounts.prepareMfa({userId:principal.userId,password:body.password,sourceKey}));
  }
  if (path === '/api/v1/mfa/confirm') {
    requireFields(body, ['totp']);
    if (principal.role !== 'admin') return json(response, 403, { error:'FORBIDDEN' });
    return json(response, 200, await mfa.confirmEnrollment({ userId:principal.userId,totp:body.totp }));
  }
  return false;
}
module.exports = { sessionRoute };
