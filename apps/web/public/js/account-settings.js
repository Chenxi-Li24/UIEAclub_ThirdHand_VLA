/* Account/settings presentation. Data access is supplied explicitly by a future adapter. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandAccountSettings=api;})(globalThis,function(){
 'use strict';
 function mountAccountSettings(doc,win,{registerPage,go}){
  const byId=id=>doc.getElementById(id),tr=value=>win.ThirdHandI18n?.translate(value,doc.documentElement.lang||'en')||value;
  const el=(tag,attrs={},text='')=>{const n=doc.createElement(tag);for(const [key,value]of Object.entries(attrs))n.setAttribute(key,value);if(text)n.textContent=text;return n;};
  const nav=byId('workspace-nav'),bottom=nav.querySelector('.nav-bottom'),main=byId('workspace-pages');
  const back=el('button',{id:'account-back',type:'button',class:'account-back',title:'Back to workspace','aria-label':'Back to workspace'}),backLabel=el('span',{class:'nav-label'},'Back to workspace');back.append(el('span',{class:'nav-icon','aria-hidden':'true'},'←'),backLabel);nav.insertBefore(back,nav.querySelector('[data-page]'));
  const pages=new Map();
  for(const [id,label,description,symbol]of [
   ['profile','Profile','Your identity and workspace details.','◉'],['preferences','Preferences','Make this workspace feel like yours.','☷'],
   ['connections','Connections','Current services and device feedback.','⌁'],['about','About','A closer look at your robot workspace.','ⓘ'],
  ]){
   const key=`account-${id}`,button=el('button',{type:'button','data-page':key,'aria-label':label,title:label});
   button.append(el('span',{class:'nav-icon','aria-hidden':'true'},symbol),el('span',{class:'nav-label'},label));button.addEventListener('click',()=>go(key));nav.insertBefore(button,bottom);
   const page=el('section',{id:`page-${key}`,class:'workspace-page account-page',hidden:'','aria-labelledby':`heading-${key}`}),heading=el('div',{class:'workspace-heading'});
   heading.append(el('div',{class:'page-eyebrow','aria-hidden':'true'},'ACCOUNT & SETTINGS'),el('h1',{id:`heading-${key}`,tabindex:'-1'},label),el('p',{},description));page.append(heading);main.append(page);registerPage(key,page,button);pages.set(id,page);
  }
  const entry=el('button',{id:'workspace-account',type:'button',class:'account-entry','aria-label':'Account and settings',title:'Account and settings'}),avatar=el('span',{class:'account-avatar','aria-hidden':'true'},'TH'),entryCopy=el('span',{class:'nav-label account-entry-copy'}),entryName=el('strong',{'data-i18n-skip':''}),entryDetail=el('span');entryCopy.append(entryName,entryDetail);entry.append(avatar,entryCopy);bottom.append(entry);
  const profileCard=el('article',{class:'account-card'}),identity=el('div',{class:'account-identity'}),largeAvatar=el('span',{class:'account-avatar account-avatar-large','aria-hidden':'true'},'TH'),identityText=el('div'),profileName=el('h2',{'data-i18n-skip':''}),badge=el('span',{class:'account-badge'});identityText.append(profileName,badge);identity.append(largeAvatar,identityText);profileCard.append(identity);
  const profileNote=el('p',{class:'account-description'},'Profile details will appear when an account data service is connected.');profileCard.append(profileNote);
  const form=el('form',{id:'account-profile-form',class:'account-form'}),fields={};
  for(const [key,id,label,type]of [['displayName','display-name','Display name','text'],['email','email','Email address','email'],['organization','organization','Organization','text']]){
   const row=el('label',{class:'account-field',for:`account-${id}`}),input=el('input',{id:`account-${id}`,type,autocomplete:'off',maxlength:key==='email'?'254':'120',placeholder:label});if(key==='displayName')input.required=true;fields[key]=input;row.append(el('span',{},label),input);form.append(row);
  }
  const profileStatus=el('p',{id:'account-profile-status',class:'account-status',role:'status'}),formActions=el('div',{class:'account-form-actions'}),reload=el('button',{id:'account-reload',type:'button',class:'action-btn action-secondary'},'Reload profile'),save=el('button',{id:'account-save',type:'submit',class:'action-btn action-primary'},'Save changes');formActions.append(reload,save);form.append(profileStatus,formActions);profileCard.append(form);pages.get('profile').append(profileCard);
  const preferences=el('article',{class:'account-card'}),languageRow=el('div',{class:'account-setting-row',id:'account-language-field'}),languageText=el('label',{for:'language-select'});languageText.append(el('strong',{},'Language'),el('span',{},'Choose the language used across the workspace.'));languageRow.append(languageText,byId('language-select'));preferences.append(languageRow);
  const appearanceRow=el('div',{class:'account-setting-row'}),appearanceText=el('div');appearanceText.append(el('strong',{},'Appearance'),el('span',{},'Bright white surfaces with warm orange accents.'));appearanceRow.append(appearanceText);const appearance=doc.querySelector('.workspace-settings');if(appearance)appearanceRow.append(appearance);preferences.append(appearanceRow);
  const learningRow=el('div',{class:'account-setting-row'}),learningText=el('div');learningText.append(el('strong',{},'Learning'),el('span',{},'Explore the interface with the beginner tour.'));const learning=el('button',{id:'account-open-guide',type:'button',class:'action-btn action-secondary'},'Open beginner tour');learningRow.append(learningText,learning);preferences.append(learningRow);pages.get('preferences').append(preferences);
  const connectionCard=el('article',{class:'account-card'}),statuses=[];
  for(const [label,id]of [['Operating mode','workspace-mode'],['Web connection','workspace-web-status'],['Robot connection','conn-ip'],['SDK feedback','hb-label'],['Camera','cam-label'],['Current TCP','grasp-tcp']]){const row=el('div',{class:'account-connection-row'}),value=el('span',{'data-i18n-skip':''});row.append(el('strong',{},label),value);connectionCard.append(row);statuses.push([id,value]);}pages.get('connections').append(connectionCard);
  const about=el('article',{class:'account-card account-about'});about.append(el('span',{class:'account-product-mark','aria-hidden':'true'},'T/H'),el('h2',{},'ThirdHand'),el('p',{},'A shared workspace for robot control, vision and calibration.'),el('span',{class:'account-badge'},'White / orange workspace'));pages.get('about').append(about);
  let provider=null,epoch=0,ready=false,pending=false,profile=null,status='Account data service is not connected.',lastWorkspace='overview';
  const clean=value=>Object.fromEntries(Object.keys(fields).map(key=>[key,typeof value?.[key]==='string'?value[key].slice(0,key==='email'?254:120):'']));
  function render(){
   const name=profile?.displayName||tr('Workspace account'),initials=profile?.displayName?profile.displayName.trim().slice(0,2).toUpperCase():'TH';
   entryName.textContent=name;profileName.textContent=name;avatar.textContent=largeAvatar.textContent=initials;entryDetail.textContent=tr('Account and settings');entry.title=tr('Account and settings');entry.setAttribute('aria-label',tr('Account and settings'));backLabel.textContent=tr('Back to workspace');back.title=tr('Back to workspace');back.setAttribute('aria-label',tr('Back to workspace'));
   badge.textContent=tr(ready?'Profile data available':'Not connected');profileStatus.textContent=tr(status);
   reload.disabled=pending||!provider?.loadProfile;save.disabled=pending||!ready||!provider?.saveProfile;for(const field of Object.values(fields))field.disabled=pending||!ready||!provider?.saveProfile;
  }
  function applyProfile(value){profile=clean(value);for(const [key,input]of Object.entries(fields))input.value=profile[key];}
  async function setDataProvider(next){
   provider=next||null;const token=++epoch;ready=false;pending=Boolean(provider?.loadProfile);applyProfile(null);status=pending?'Loading profile…':'Account data service is not connected.';render();
   if(!pending)return false;
   try{const value=await provider.loadProfile();if(token!==epoch)return false;applyProfile(value);ready=true;status='Profile loaded.';}
   catch{if(token!==epoch)return false;status='Could not load profile. Try again.';}
   if(token===epoch){pending=false;render();}return ready;
  }
  form.addEventListener('submit',async event=>{
   event.preventDefault();if(pending||!ready||!provider?.saveProfile||form.checkValidity?.()===false)return;
   const token=epoch,value=clean(Object.fromEntries(Object.entries(fields).map(([key,input])=>[key,input.value.trim()])));pending=true;status='Saving changes…';render();
   try{const saved=await provider.saveProfile(value);if(token!==epoch)return;applyProfile(saved||value);status='Profile saved.';}
   catch{if(token!==epoch)return;status='Could not save profile. Try again.';}
   if(token===epoch){pending=false;render();}
  });
  reload.addEventListener('click',()=>setDataProvider(provider));entry.addEventListener('click',()=>go('account-profile'));back.addEventListener('click',()=>go(lastWorkspace));
  learning.addEventListener('click',()=>{if(go('overview')!==false)byId('workspace-guide')?.click();});
  function routeChanged(id){
   const account=id.startsWith('account-');if(!account)lastWorkspace=id;
   byId('app').dataset.workspaceGroup=account?'account':'workspace';byId('workspace-model').hidden=account;back.hidden=!account;
   nav.querySelector('.nav-footer').textContent=account?'ACCOUNT & SETTINGS':'CONTROL WORKSPACE';
   for(const node of nav.querySelectorAll('[data-page]'))node.hidden=node.dataset.page.startsWith('account-')!==account;
   const guide=byId('workspace-guide');if(guide)guide.hidden=account;
   entry.classList.toggle('account-active',account);refresh();
  }
  function refresh(){for(const [id,node]of statuses){const source=byId(id),value=source?.textContent||tr('Unknown');if(node.textContent!==value)node.textContent=value;if(source?.dataset.linkState)node.dataset.linkState=source.dataset.linkState;else delete node.dataset.linkState;}}
  new win.MutationObserver(()=>{render();refresh();}).observe(doc.documentElement,{attributes:true,attributeFilter:['lang']});render();refresh();
  return {routeChanged,refresh,setDataProvider};
 }
 return {mountAccountSettings};
});
