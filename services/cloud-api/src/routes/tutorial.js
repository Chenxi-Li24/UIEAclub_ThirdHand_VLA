'use strict';
const {json}=require('../http');
const {createTutorialAdapter}=require('../../../../apps/web/public/js/tutorial-adapter');
const {createPreferences}=require('../../../../platform/identity/src/preferences');
async function tutorialRoute({path,request,response,principal,tutorialAdapter,pool}){
  if(path!=='/api/v1/tutorial'||request.method!=='GET')return false;
  const adapter=tutorialAdapter||createTutorialAdapter();
  const preference=await createPreferences({pool}).load({principal});
  return json(response,200,{state:await adapter.getState({userId:principal.userId}),entry:adapter.getEntry({locale:preference.locale,theme:preference.themeId,returnTo:'/control'})});
}
module.exports={tutorialRoute};
