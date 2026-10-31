'use strict';
const { json,requireFields }=require('../http');
const { authorize }=require('../../../../platform/identity/src/policy');
const { createPreferences }=require('../../../../platform/identity/src/preferences');
const { identityError }=require('../../../../platform/identity/src/errors');
async function preferencesRoute({path,request,response,body,principal,pool}){
  if(!['/api/v1/me/preferences','/api/v1/me/preferences/resolve'].includes(path))return false;
  if(!authorize(principal,request.method==='GET'?'preferences.read':'preferences.write').ok)throw identityError('FORBIDDEN');
  const preferences=createPreferences({pool});
  if(request.method==='GET'&&path==='/api/v1/me/preferences')return json(response,200,await preferences.load({principal}));
  if(request.method==='POST'&&path.endsWith('/resolve')){requireFields(body,['guestSelection']);return json(response,200,await preferences.load({principal,guestSelection:body.guestSelection}));}
  if(request.method==='POST'){requireFields(body,['value','expectedRevision']);return json(response,200,await preferences.save({principal,...body}));}
  return false;
}
module.exports={preferencesRoute};
