(function(root,factory){
 const api=factory();
 if(typeof module==='object'&&module.exports)module.exports=api;
 root.ThirdHandAiPreviewChat=api;
})(typeof globalThis==='object'?globalThis:this,function(){
 'use strict';
 const validGripper=value=>value===null||Number.isFinite(value)&&value>=0&&value<=1;
 const validLimits=limits=>Array.isArray(limits)&&limits.length===6&&limits.every(pair=>Array.isArray(pair)&&pair.length===2&&pair.every(Number.isFinite)&&pair[0]<=pair[1]);
 const validPose=(pose,limits)=>validLimits(limits)&&Array.isArray(pose)&&pose.length===6&&pose.every((value,i)=>Number.isFinite(value)&&value>=limits[i][0]&&value<=limits[i][1]);
 function mountAiPreviewChat({document:doc,view,shell,request}){
  const byId=id=>doc.getElementById(id),conversation=byId('voice-conversation'),status=byId('voice-ai-status'),input=byId('voice-text-input'),send=byId('voice-text-send'),form=byId('voice-text-form');
  let model=null,disposed=false,busy=false;const history=[],listeners=[];
  function listen(element,type,handler){if(!element)return;element.addEventListener(type,handler);listeners.push(()=>element.removeEventListener(type,handler));}
  function state(text){if(status)status.textContent=text;}
  function addMessage(role,text){
   const item=doc.createElement('div');item.className='voice-message voice-message--'+role;item.textContent=text;item.style.whiteSpace='pre-wrap';conversation.append(item);
   while(conversation.children.length>40)conversation.firstElementChild.remove();
   if(byId('chat-replies'))byId('chat-replies').hidden=false;item.scrollIntoView?.({block:'nearest'});return item;
  }
  function context(){
   try{const current=model?.read();return {joints:validPose(current?.joints,model?.limits)?current.joints.slice():null,gripper:validGripper(current?.gripper)?current.gripper:null};}
   catch{return {joints:null,gripper:null};}
  }
  function validateResult(result){return result&&result.mode==='preview-only'&&typeof result.reply==='string'&&result.reply.trim()&&result.reply.length<=2000&&!/(?!\p{Script=Latin})\p{Letter}/u.test(result.reply)&&(result.joints===null||Array.isArray(result.joints)&&result.joints.length===6&&result.joints.every(Number.isFinite))&&validGripper(result.gripper);}
  function offerPreview(item,result){
   if(result.joints===null&&result.gripper===null)return;
   const proposal={reply:result.reply,joints:result.joints?.slice()??null,gripper:result.gripper,mode:'preview-only'},button=doc.createElement('button');button.type='button';button.className='action-btn';button.textContent='Preview in model';item.append(doc.createElement('br'),button);
   button.addEventListener('click',()=>{
    if(disposed)return;
    if(!model){button.textContent='Model is loading. Try again.';return;}
    // Reject the complete proposal before either joint or gripper state is touched.
    if(proposal.joints!==null&&!validPose(proposal.joints,model.limits)||!validGripper(proposal.gripper)){button.textContent='Pose exceeds model limits. Please revise.';return;}
    try{
     if(model.apply({...proposal,joints:proposal.joints?.slice()??null})===false){button.textContent='Preview unavailable. Please try again.';return;}
     doc.dispatchEvent(new view.Event('thirdhand:model-preview'));shell?.go('control');button.textContent='Preview applied';
    }catch{button.textContent='Preview unavailable. Please try again.';}
   });
  }
  async function sendMessage(event){
   event.preventDefault();if(disposed||busy)return;
   const message=input.value.trim();if(!message)return;
   if(message.length>2000){state('Message is too long');return;}
   busy=true;send.disabled=true;input.value='';addMessage('user',message);const pending=addMessage('ai','Thinking…');state('Thinking…');
   try{
    const result=await request({message,history:history.map(entry=>({...entry})),...context()});
    if(disposed)return;
    if(!validateResult(result))throw Error('INVALID_REPLY');
    pending.textContent=result.reply;state('AI ready');
    history.push({role:'user',content:message},{role:'assistant',content:result.reply});if(history.length>8)history.splice(0,history.length-8);
    offerPreview(pending,result);doc.dispatchEvent(new view.Event('thirdhand:ai-reply'));
   }catch(error){if(disposed)return;pending.textContent=error?.status===429||error?.code==='AI_BUSY'?'AI is busy. Please wait a minute and try again.':'AI is temporarily unavailable. Please try again.';state('AI unavailable');}
   finally{if(!disposed){busy=false;send.disabled=false;}}
  }
  conversation.replaceChildren();addMessage('ai','Ask a question or describe a model pose. Previews change the model only.');state('AI ready');send.disabled=false;
  if(byId('voice-text-help'))byId('voice-text-help').textContent='AI replies in English. Model previews only.';
  input.placeholder='Message…';input.maxLength=2000;
  for(const selector of ['#voice-intent-card','#voice-preview-indicator','#voice-record-toggle','#voice-record-cancel','#voice-mic-toggle','.voice-config-block','.voice-capture-block','.voice-signal-ribbon','.voice-mock-badge','.voice-kicker'])for(const element of doc.querySelectorAll(selector))element.hidden=true;
  const voiceEntry=byId('chat-voice'),audioDrawer=byId('chat-audio');
  if(voiceEntry){
   voiceEntry.hidden=true;
   voiceEntry.disabled=true;
   voiceEntry.setAttribute('aria-expanded','false');
  }
  if(audioDrawer)audioDrawer.hidden=true;
  listen(form,'submit',sendMessage);
  listen(input,'keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing)void sendMessage(event);});
  listen(byId('voice-ai-reconnect'),'click',()=>{if(!disposed)addMessage('ai','Send a message to retry the AI connection.');});
  return {bindModel(adapterOrNull){if(!disposed)model=adapterOrNull;},dispose(){if(disposed)return;disposed=true;model=null;history.length=0;listeners.splice(0).forEach(remove=>remove());send.disabled=true;}};
 }
 return {mountAiPreviewChat};
});
