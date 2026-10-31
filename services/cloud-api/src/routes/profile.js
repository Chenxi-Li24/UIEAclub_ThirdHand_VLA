'use strict';
const {json,requireFields}=require('../http');
const {identityError}=require('../../../../platform/identity/src/errors');
const {authorize}=require('../../../../platform/identity/src/policy');
async function profileRoute({path,request,response,body,principal,pool}){
  if(path!=='/api/v1/me/profile')return false;
  if(!authorize(principal,request.method==='GET'?'profile.read':'profile.write').ok)throw identityError('FORBIDDEN');
  if(request.method==='POST'){
    requireFields(body,['displayName','email','organization']);
    if(typeof body.displayName!=='string'||!body.displayName.trim()||body.displayName.trim().length>80||typeof body.organization!=='string'||body.organization.length>120)throw identityError('INVALID_INPUT');
    const current=(await pool.query('SELECT email FROM auth.users WHERE id=$1',[principal.userId])).rows[0];
    if(typeof body.email!=='string'||body.email.trim().toLowerCase()!==current.email)throw identityError('INVALID_INPUT');
    await pool.query('UPDATE auth.users SET display_name=$2,organization=$3,updated_at=now() WHERE id=$1',[principal.userId,body.displayName.trim(),body.organization.trim()]);
  }
  const profile=(await pool.query('SELECT username,email,display_name AS "displayName",organization FROM auth.users WHERE id=$1',[principal.userId])).rows[0];
  return json(response,200,profile);
}
module.exports={profileRoute};
