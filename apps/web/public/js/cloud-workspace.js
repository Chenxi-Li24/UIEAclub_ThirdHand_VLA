// No static Three.js or media imports: mount the authenticated shell first.
globalThis.ThirdHandWorkspaceStartup.start({
  document,view:window,loadModel:()=>import('./model-resources.js')
}).catch(()=>{
  const message=document.getElementById('workspace-opening');
  if(message){message.hidden=false;message.textContent='The workspace could not be loaded. Please reload or sign in again.';}
});
