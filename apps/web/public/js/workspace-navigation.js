/* Shared information structure; each shell retains its own presentation. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandWorkspaceNavigation=api;})(globalThis,function(){
 'use strict';
 const entries=[['overview','Overview'],['control','Model workspace'],['vision','Camera'],['data','Data'],['system','Devices & diagnostics']];
 function mount({document:doc,view,shell,identity}){
  const tr=s=>view.ThirdHandI18n?.translate(s,doc.documentElement.lang)||s,classic=doc.documentElement.dataset.layout==='classic';
  const nav=doc.getElementById('workspace-nav'),bottom=nav.querySelector('.nav-bottom'),top=doc.querySelector('.classic-user-tools');
  const el=(tag,text,attrs={})=>{const n=doc.createElement(tag);if(text)n.textContent=tr(text);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);return n;};
  const history=el('a',null,{href:'/history',class:'workspace-history-link',title:tr('Data'),'aria-label':tr('Data'),'data-workspace-entry':'data'});
  const icon=doc.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('aria-hidden','true');icon.innerHTML='<path d="M4 4h16v16H4z M4 10h16 M10 4v16" fill="none" stroke="currentColor" stroke-width="1.6"/>';
  const slot=el('span',null,{class:'nav-icon'});slot.append(icon);history.append(slot,el('span','Data',{class:'nav-label'}));
  if(classic){top.prepend(history);const model=el('button','Model',{type:'button',class:'action-btn'});model.addEventListener('click',()=>shell.go('control'));top.prepend(model);}
  else {history.classList.add('nav-data');nav.insertBefore(history,nav.querySelector('[data-page="system"]')||bottom);}
  const toggle=doc.getElementById('workspace-nav-toggle');if(toggle)nav.querySelector('.workspace-brand')?.after(toggle);
  for(const id of ['calibration','assistant']){const node=nav.querySelector(`[data-page="${id}"]`);if(node&&identity.mode!=='admin'){node.hidden=true;node.dataset.permissionHidden='true';}}
  const security=doc.getElementById('page-account-security'),logout=doc.getElementById('workspace-logout');if(logout&&security)security.append(logout);
  if(classic){
   const more=el('details',null,{class:'classic-more'}),summary=el('summary','More'),contents=el('div',null,{class:'classic-more-content'});more.append(summary,contents);top.append(more);
   for(const id of ['theme-select','language-select','btn-log-toggle']){const node=doc.getElementById(id);if(node)contents.append(node);}
   const calibration=doc.querySelector('a[href="tcp-calibration.html"]');if(calibration)contents.append(calibration);
   const camera=el('button','Camera',{type:'button',class:'action-btn'});camera.addEventListener('click',()=>{more.open=false;shell.go('vision');});contents.append(camera);
   more.addEventListener('keydown',event=>{if(event.key==='Escape'){more.open=false;summary.focus();}});
   const about=el('button','About',{type:'button',class:'action-btn'});about.addEventListener('click',()=>{more.open=false;shell.go('account-about');});contents.append(about);
  }
  const note=el('p','Movement is disabled. An unavailable or expired state does not confirm that the robot has stopped.',{id:'device-status-help',class:'device-status-help'});
  const modelDescription=doc.querySelector('#page-control .workspace-heading p');if(modelDescription)modelDescription.textContent=tr('Edit and save model poses. These controls do not move the real robot.');
  const cameraDescription=doc.querySelector('#page-vision .workspace-heading p');if(cameraDescription)cameraDescription.textContent=tr('View an authorized camera stream. Voice and robot motion are unavailable here.');
  (doc.getElementById('page-overview')||doc.getElementById('page-account-connections')).append(note);
  function render(){
   for(const[id,label]of entries){const button=nav.querySelector(`[data-page="${id}"]`);if(button){const copy=button.querySelector('.nav-label');if(copy)copy.textContent=tr(label);button.title=tr(label);button.setAttribute('aria-label',tr(label));}const heading=doc.getElementById('heading-'+id);if(heading)heading.textContent=tr(label);}
   history.title=tr('Data');history.setAttribute('aria-label',tr('Data'));history.querySelector('.nav-label').textContent=tr('Data');
  }
  render();const observer=new view.MutationObserver(render);observer.observe(doc.documentElement,{attributes:true,attributeFilter:['lang']});
  return {dispose(){observer.disconnect();},entries};
 }
 return {entries,mount};
});
