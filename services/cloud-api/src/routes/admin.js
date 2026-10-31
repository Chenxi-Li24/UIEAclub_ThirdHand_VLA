'use strict';
const { json, requireFields } = require('../http');
const { authorize } = require('../../../../platform/identity/src/policy');
const { createUsersRepository } = require('../../../../platform/storage/src/users');
const { identityError } = require('../../../../platform/identity/src/errors');
const {csvHeader,csvRow,memberColumns}=require('../table-export');
async function adminRoute({ path, request, response, body, principal, pool, accounts, sourceKey }) {
  if (!path.startsWith('/api/v1/admin/')) return false;
  const action = path === '/api/v1/admin/audit' ? 'admin.audit' : 'admin.users';
  if (!authorize(principal, action).ok) throw identityError('FORBIDDEN');
  if(path==='/api/v1/admin/users/export'&&request.method==='GET'){
    const result=await pool.query(`SELECT id,username,email,display_name AS "displayName",organization,role,status,locale,
      created_at AS "createdAt",email_verified_at AS "emailVerifiedAt" FROM auth.users ORDER BY id LIMIT 10001`);
    if(result.rows.length>10000)throw identityError('EXPORT_LIMIT_EXCEEDED');
    const data=Buffer.from(csvHeader(memberColumns)+result.rows.map(row=>csvRow(memberColumns,row)).join(''));
    response.writeHead(200,{'Content-Type':'text/csv; charset=utf-8','Content-Disposition':'attachment; filename="thirdhand-members-'+new Date().toISOString().slice(0,10)+'.csv"','Content-Length':data.length,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});
    response.end(data);return true;
  }
  if (path === '/api/v1/admin/users' && request.method === 'GET') {
    const url = new URL(request.url, 'http://localhost');
    const limit = Math.min(100, Math.max(1, Number(url.searchParams.get('limit')) || 50));
    const cursor = url.searchParams.get('cursor');
    if (cursor && !/^[0-9a-f-]{36}$/i.test(cursor)) throw identityError('INVALID_INPUT');
    const result = await pool.query(`SELECT id,username,email,display_name AS "displayName",organization,role,status,locale,role_version AS "roleVersion",
      created_at AS "createdAt",email_verified_at AS "emailVerifiedAt"
      FROM auth.users WHERE ($1::uuid IS NULL OR id>$1::uuid) ORDER BY id LIMIT $2`, [cursor, limit]);
    return json(response, 200, { users:result.rows,nextCursor:result.rows.length===limit?result.rows.at(-1).id:null });
  }
  const rolePath = /^\/api\/v1\/admin\/users\/([0-9a-f-]{36})\/(role|status)$/i.exec(path);
  if (rolePath && request.method === 'POST') {
    requireFields(body, [rolePath[2],'expectedVersion','reason','password','totp','recoveryCode']);
    const users = createUsersRepository(pool), actor = await users.findById(principal.userId);
    await accounts.authenticate({ login:actor.username,password:body.password,requestedMode:'admin',totp:body.totp,recoveryCode:body.recoveryCode,sourceKey });
    const input={actorId:principal.userId,userId:rolePath[1],role:body.role,status:body.status,expectedVersion:body.expectedVersion,reason:body.reason};
    const changed = rolePath[2]==='role'?await users.setRole(input):await users.setStatus(input);
    return json(response, 200, { userId:changed.id,role:changed.role,status:changed.status,roleVersion:changed.roleVersion });
  }
  if (path === '/api/v1/admin/audit' && request.method === 'GET') {
    const rows = await pool.query('SELECT id,event_code,object_id,outcome,created_at FROM security.audit_events ORDER BY id DESC LIMIT 100');
    return json(response, 200, { events:rows.rows });
  }
  return false;
}
module.exports = { adminRoute };
