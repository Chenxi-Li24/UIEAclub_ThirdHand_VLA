'use strict';
const {json,requireFields}=require('../http');
const {authorize}=require('../../../../platform/identity/src/policy');
const {identityError}=require('../../../../platform/identity/src/errors');
const {createModelWaypoints}=require('../../../../platform/storage/src/model-waypoints');
async function waypointsRoute({path,request,response,body,principal,pool}){
  if(!['/api/v1/me/waypoints','/api/v1/me/waypoints/delete'].includes(path))return false;
  if(!authorize(principal,'simulation.use').ok)throw identityError('FORBIDDEN');
  const waypoints=createModelWaypoints({pool});
  if(request.method==='GET'&&path==='/api/v1/me/waypoints')return json(response,200,await waypoints.list({principal}));
  if(request.method==='POST'&&path.endsWith('/delete')){requireFields(body,['id']);return json(response,200,await waypoints.remove({principal,id:body.id}));}
  if(request.method==='POST'){requireFields(body,['name','joints','gripper']);return json(response,201,await waypoints.save({principal,...body}));}
  return false;
}
module.exports={waypointsRoute};
