'use strict';
const {json,requireFields}=require('../http');
const {createUsersRepository}=require('../../../../platform/storage/src/users');
const {authorize}=require('../../../../platform/identity/src/policy');
const {identityError}=require('../../../../platform/identity/src/errors');

async function adminApplicationsRoute({path,request,response,body,principal,pool,accounts,sourceKey}){
  const own=path==='/api/v1/me/admin-application',list=path==='/api/v1/admin/applications';
  const decisionPath=/^\/api\/v1\/admin\/applications\/([0-9a-f-]{36})\/decision$/i.exec(path);
  if(!own&&!list&&!decisionPath)return false;
  const users=createUsersRepository(pool);
  if(own){
    if(request.method==='GET')return json(response,200,{application:await users.adminRequest({userId:principal.userId})});
    requireFields(body,['reason']);
    return json(response,201,{application:await accounts.requestAdminAccess({userId:principal.userId,reason:body.reason,sourceKey})});
  }
  if(!authorize(principal,'admin.users').ok)throw identityError('FORBIDDEN');
  if(list&&request.method==='GET'){
    const cursor=new URL(request.url,'http://localhost').searchParams.get('cursor');
    if(cursor&&!/^[0-9a-f-]{36}$/i.test(cursor))throw identityError('INVALID_INPUT');
    const applications=await users.pendingAdminRequests({cursor});
    return json(response,200,{applications,nextCursor:applications.length===100?applications.at(-1).id:null});
  }
  if(decisionPath&&request.method==='POST'){
    requireFields(body,['decision','reason','password','totp','recoveryCode']);
    const actor=await users.findById(principal.userId);
    await accounts.authenticate({login:actor.username,password:body.password,requestedMode:'admin',totp:body.totp,recoveryCode:body.recoveryCode,sourceKey});
    const result=await users.decideAdmin({actorId:principal.userId,requestId:decisionPath[1],decision:body.decision,reason:body.reason});
    return json(response,200,{result});
  }
  return false;
}
module.exports={adminApplicationsRoute};
