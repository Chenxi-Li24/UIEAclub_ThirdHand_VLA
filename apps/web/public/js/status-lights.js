/* Read-only connection lamps. These states never authorize or block robot commands. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandStatusLights=api;})(globalThis,function(){
 'use strict';
 const mounted=new WeakMap();
 function createSdkSignal({now=()=>Date.now(),staleAfterMs=2500}={}){
  let web=null,sdk=null,lastValidAt=null,awaitingSince=null,invalid=false;
  function receive(type,data={}){
   if(type==='ws_connection'){
    web=typeof data.connected==='boolean'?data.connected:null;sdk=null;lastValidAt=null;awaitingSince=null;invalid=false;return;
   }
   if(web===false)return;
   const connection=type==='config'?data.connection:type==='connection'?data:null;
   if(connection&&typeof connection.connected==='boolean'){
    if(type==='connection'||sdk!==connection.connected){lastValidAt=null;awaitingSince=connection.connected?now():null;invalid=false;}sdk=connection.connected;
   }
   if(type!=='robot_state')return;
   if(data.connected===false){sdk=false;lastValidAt=null;awaitingSince=null;invalid=false;return;}
   if(data.connected===true){if(sdk!==true)awaitingSince=now();sdk=true;}
   const joints=data.joints||data.joints_deg;
   const valid=data.healthy===true&&Array.isArray(joints)&&joints.length===6&&joints.every(Number.isFinite);
   if(valid&&sdk===true){lastValidAt=now();invalid=false;}else invalid=true;
  }
  function snapshot(){
   if(web===false)return {state:'offline',reason:'web_disconnected'};
   if(sdk===false)return {state:'offline',reason:'sdk_disconnected'};
   if(web===null||sdk===null)return {state:'unknown',reason:'unknown'};
   const lastEvidence=lastValidAt??awaitingSince;
   if(invalid||lastEvidence!==null&&now()-lastEvidence>staleAfterMs)return {state:'offline',reason:'feedback_lost'};
   if(lastValidAt===null)return {state:'waiting',reason:'awaiting_feedback'};
   return {state:'online',reason:'current'};
  }
  return {receive,snapshot};
 }
 function mountStatusLights(doc,win,options={}){
  if(mounted.has(doc))return mounted.get(doc);
  const sdkNode=doc.getElementById('hb-label');if(!sdkNode)return null;
  const webNode=doc.createElement('span');webNode.id='workspace-web-status';webNode.className='status-chip';sdkNode.parentElement.insertBefore(webNode,sdkNode);
  let signal=createSdkSignal(options),web=null,channel=null;const bound=new WeakSet();
  const tr=value=>win.ThirdHandI18n?.translate(value,doc.documentElement.lang||'en')||value;
  function chip(node,label,state,value,description){
   const key=JSON.stringify([doc.documentElement.lang,label,state,value,description]);node.classList.add('status-chip');
   if(node.dataset.signalRenderKey===key&&node.querySelector('.service-dot'))return;
   node.dataset.signalRenderKey=key;node.dataset.linkState=state;node.title=tr(description);node.setAttribute('aria-label',tr(description));node.setAttribute('role','status');
   if(!node.querySelector('.service-dot')){
    const dot=doc.createElement('span');dot.className='service-dot';dot.setAttribute('aria-hidden','true');
    const name=doc.createElement('span');name.className='service-name';const status=doc.createElement('span');status.className='service-value';node.replaceChildren(dot,name,status);
   }
   const name=node.querySelector('.service-name'),status=node.querySelector('.service-value');
   if(name.textContent!==tr(label))name.textContent=tr(label);const text=` · ${tr(value)}`;if(status.textContent!==text)status.textContent=text;
  }
  function refresh(){
   const result=signal.snapshot(),details={
    unknown:['Unknown','SDK status unknown'],awaiting_feedback:['Waiting','Waiting for SDK feedback'],
    current:['Online','SDK online'],sdk_disconnected:['Offline','SDK disconnected'],
    web_disconnected:['Offline','SDK connection lost with Web link'],feedback_lost:['No feedback','SDK feedback lost'],
   }[result.reason];
   chip(sdkNode,'SDK',result.state,...details);
   const feedback=doc.querySelector('.overview-card-feedback');if(feedback)feedback.dataset.linkState=result.state;
   chip(webNode,'Web',web===true?'online':web===false?'offline':'unknown',web===true?'Online':web===false?'Offline':'Unknown',web===true?'Web control link online':web===false?'Web control link disconnected':'Web control link status unknown');
  }
  function bind(ws){
   if(channel===ws)return;channel=ws;signal=createSdkSignal(options);web=ws.connected===true?true:null;
   if(web===true)signal.receive('ws_connection',{connected:true});
   if(!bound.has(ws)){
    bound.add(ws);for(const type of ['ws_connection','config','connection','robot_state'])ws.on(type,data=>{if(channel!==ws)return;if(type==='ws_connection')web=typeof data.connected==='boolean'?data.connected:null;signal.receive(type,data);refresh();});
   }
   refresh();
  }
  const timer=win.setInterval?.(refresh,500);timer?.unref?.();
  win.addEventListener('pagehide',event=>{if(!event.persisted)win.clearInterval?.(timer);});doc.addEventListener('visibilitychange',refresh);
  new win.MutationObserver(refresh).observe(doc.documentElement,{attributes:true,attributeFilter:['lang']});
  const view={bind,refresh};mounted.set(doc,view);refresh();return view;
 }
 return {createSdkSignal,mountStatusLights};
});
