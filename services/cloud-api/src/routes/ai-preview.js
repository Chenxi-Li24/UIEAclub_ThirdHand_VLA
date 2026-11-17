'use strict';
const {json}=require('../http');
const {authorize}=require('../../../../platform/identity/src/policy');
const {identityError}=require('../../../../platform/identity/src/errors');
async function aiPreviewRoute({path,request,response,body,principal,previewAi}){
 if(path!=='/api/v1/ai/preview')return false;
 if(!authorize(principal,'voice.use').ok)throw identityError('FORBIDDEN');
 if(request.method!=='POST'){json(response,405,{error:'METHOD_NOT_ALLOWED'},{Allow:'POST'});return true;}
 try{json(response,200,await previewAi.chat(body,principal.userId));}
 catch(error){const status=[400,429,503].includes(error.status)?error.status:503;json(response,status,{error:status===400?'INVALID_INPUT':status===429?'AI_BUSY':'AI_UNAVAILABLE'},status===429?{'Retry-After':'60'}:{});}
 return true;
}
module.exports={aiPreviewRoute};
