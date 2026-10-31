'use strict';
const {json,requireFields}=require('../http');
const {identityError}=require('../../../../platform/identity/src/errors');
async function historyRoute({path,request,response,principal,history}){
  if(path!=='/api/v1/history')return false;if(!history)throw identityError('HISTORY_UNAVAILABLE');
  if(request.method!=='GET')return json(response,405,{error:'METHOD_NOT_ALLOWED'});
  const parameters=new URL(request.url,'http://localhost').searchParams;
  for(const key of parameters.keys())if(parameters.getAll(key).length!==1)throw identityError('INVALID_INPUT');
  const values=Object.fromEntries(parameters);requireFields(values,['kind','deviceId','bootId','runId','from','to','cursor','limit']);
  const {cursor,limit,...filter}=values;return json(response,200,await history.queryPage(principal,filter,{cursor,limit:limit===undefined?200:Number(limit)}));
}
module.exports={historyRoute};
