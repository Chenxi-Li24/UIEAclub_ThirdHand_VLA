'use strict';
// The cloud process deliberately has no RobotProxy, VisionProxy, VoiceProxy or SDK imports.
const http = require('node:http');
const {isIP}=require('node:net');
const { digestToken } = require('../../../platform/identity/src/tokens');
const { identityError } = require('../../../platform/identity/src/errors');
const { json, readBody } = require('./http');
const { authRoute } = require('./routes/auth');
const { sessionRoute } = require('./routes/session');
const { adminRoute } = require('./routes/admin');
const {adminApplicationsRoute}=require('./routes/admin-applications');
const { workspaceRoute } = require('./routes/workspace');
const { preferencesRoute } = require('./routes/preferences');
const { serveAuthPage } = require('./auth-pages');
const { writeAudit }=require('../../../platform/storage/src/audit');
const {isWorkspacePath,serveWorkspacePage}=require('./workspace-pages');
const {tutorialRoute}=require('./routes/tutorial');
const {profileRoute}=require('./routes/profile');
const {controlRoute}=require('./routes/control');
const {createControlWebSocket}=require('./control/websocket');
const {historyRoute}=require('./routes/history');
const {exportsRoute}=require('./routes/exports');
const {mediaRoute,mediaSignalRoute}=require('./routes/media');

const PUBLIC_AUTH = new Set(['register','login','verify-email','forgot-password','resend-verification','reset-password'].map(name=>`/api/v1/auth/${name}`));
const STATUS = { INVALID_INPUT:400, INVALID_PASSWORD:400, INVALID_TOKEN:400, BODY_TOO_LARGE:413, UNSUPPORTED_MEDIA:415,
  INVALID_CREDENTIALS:401, EMAIL_NOT_VERIFIED:403, ADMIN_PERMISSION_REQUIRED:403, FORBIDDEN:403,
  MFA_REQUIRED:401, MFA_INVALID:401, MFA_ENROLLMENT_REQUIRED:403, MFA_ALREADY_ENABLED:409, MFA_SETUP_EXPIRED:400,
  RATE_LIMITED:429, AUTH_BUSY:503, CONFLICT:409, INVALID_STATE:409, ADMIN_REQUEST_REQUIRED:409, NOT_FOUND:404, MAIL_UNAVAILABLE:503, '23505':409, '23514':409,
  LEASE_BUSY:409,LEASE_CHANGED:409,LEASE_REQUIRED:409,LEASE_UNCONFIRMED:409,TAKEOVER_INVALID:409,STOP_UNCONFIRMED:409,
  DEVICE_UNAVAILABLE:503,CONTROL_READINESS_REQUIRED:409,READ_ONLY_DEVICE:403,BROWSER_STALE:409,COMMAND_ID_CONFLICT:409,
  INVALID_CURSOR:400,HISTORY_UNAVAILABLE:503,HISTORY_BUSY:429,EXPORT_SERVICE_UNAVAILABLE:503,EXPORT_BUSY:429,EXPORT_EXPIRED:410,EXPORT_NOT_READY:409,
  MEDIA_UNAVAILABLE:503,MEDIA_BUSY:429,MEDIA_PUBLISHER_BUSY:409,MEDIA_REVOCATION_PENDING:503,STALE_VIDEO_FRAME:409 };

function createCloudApi({ pool, accounts, sessions, mfa, publicOrigin, tutorialAdapter, controlService,controlChannels,history,exports,mediaService, trustProxyLoopback=false, clock = { now:()=>new Date() } }) {
  const origin = new URL(publicOrigin).origin;
  if (!publicOrigin.startsWith('https://') || publicOrigin.replace(/\/$/,'') !== origin) throw new Error('Exact HTTPS publicOrigin required');
  const server = http.createServer(async (request, response) => {
    let auditContext=null;
    response.setHeader('X-Content-Type-Options','nosniff'); response.setHeader('Referrer-Policy','no-referrer');
    response.setHeader('X-Frame-Options','DENY'); response.setHeader('Permissions-Policy','camera=(), microphone=()');
    try {
      const path = new URL(request.url, origin).pathname;
      if(await mediaSignalRoute({path,request,response,sessions,mediaService,publicOrigin:origin,trustProxyLoopback}))return;
      // No legacy proxy endpoints and no permissive WebSocket forwarding.
      if (['/ws','/execution','/voice','/vision'].some(prefix=>path===prefix||path.startsWith(`${prefix}/`))) return json(response,404,{error:'NOT_FOUND'});
      if (path === '/healthz' && request.method === 'GET') return json(response,200,{service:'thirdhand-cloud-api',deviceControl:controlService?'explicit-read-only':'unavailable'});
      if (await serveAuthPage(request,response,path)) return;
      if(isWorkspacePath(path)&&['GET','HEAD'].includes(request.method)){
        const authenticated=await sessions?.resolveSession(request);
        if(!authenticated){if(['/control','/history'].includes(path)){response.writeHead(302,{Location:'/login','Cache-Control':'no-store'});response.end();}else json(response,401,{error:'UNAUTHENTICATED'});return;}
        if(await serveWorkspacePage(request,response,path,{publicOrigin:origin}))return;
      }
      if (!path.startsWith('/api/v1/')) return json(response,404,{error:'NOT_FOUND'});
      if (!['GET','POST'].includes(request.method)) return json(response,405,{error:'METHOD_NOT_ALLOWED'});
      const publicAuth = PUBLIC_AUTH.has(path);
      const remote=request.socket.remoteAddress||'unknown';
      // Nginx must overwrite X-Real-IP. Never accept an arbitrary X-Forwarded-For chain.
      const source=trustProxyLoopback&&['127.0.0.1','::1','::ffff:127.0.0.1'].includes(remote)&&isIP(request.headers['x-real-ip']||'')?request.headers['x-real-ip']:remote;
      const sourceKey = digestToken(source);
      if(path==='/api/v1/auth/login')auditContext={eventCode:'identity.login.denied',outcome:'denied',context:{sourceHash:sourceKey}};
      let principal = null;
      if (!publicAuth) {
        principal = await sessions.resolveSession(request);
        if (!principal) return json(response,401,{error:'UNAUTHENTICATED'});
      }
      let body = {};
      if (request.method === 'POST') {
        if (request.headers.origin !== origin || request.headers['sec-fetch-site'] && request.headers['sec-fetch-site'] !== 'same-origin') throw identityError('FORBIDDEN');
        if (!publicAuth && !sessions.verifyCsrf(request,principal)) throw identityError('FORBIDDEN');
        body = await readBody(request);
      }
      const context = { path,request,response,body,principal,pool,accounts,sessions,mfa,sourceKey,clock,tutorialAdapter,controlService,history,exports,mediaService };
      if (publicAuth && request.method === 'POST') await authRoute(context);
      if (!response.writableEnded && !publicAuth) {
        for (const route of [sessionRoute,adminApplicationsRoute,adminRoute,profileRoute,preferencesRoute,tutorialRoute,historyRoute,exportsRoute,mediaRoute,controlRoute,workspaceRoute]) { await route(context); if (response.writableEnded||response.destroyed) break; }
      }
      if (!response.writableEnded) json(response,404,{error:'NOT_FOUND'});
    } catch (error) {
      if (response.writableEnded || response.destroyed) return;
      const status = STATUS[error.code] || 503;
      if(auditContext&&pool)await writeAudit(pool,{...auditContext,context:{...auditContext.context,code:error.code}}).catch(()=>{});
      // Stable error codes only: never serialize DB errors, request bodies, tokens or password hashes.
      json(response,status,{error:STATUS[error.code]?error.code:'SERVICE_UNAVAILABLE'});
    }
  });
  server.requestTimeout = 15000; server.headersTimeout = 10000; server.keepAliveTimeout = 5000;
  const controlChannel=controlService&&controlChannels?createControlWebSocket({sessions,channels:controlChannels,controlService,publicOrigin:origin}):null;
  server.controlChannel=controlChannel;
  server.on('upgrade', async(request,socket,head) => { if(controlChannel&&await controlChannel.upgrade(request,socket,head))return;socket.end('HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n'); });
  return server;
}
module.exports = { createCloudApi };
