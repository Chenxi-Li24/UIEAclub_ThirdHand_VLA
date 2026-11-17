/* Original 372ac80 presentation + shared cloud adapters; never import old main.js. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandClassicShell=api;})(globalThis,function(){
  'use strict';
  // Classic reuses the compact typed chat and shared presenter, without legacy voice bindings.
  function mountAssistant(doc,view,options){
    const byId=id=>doc.getElementById(id),entry=byId('btn-voice-toggle'),panel=byId('voice-panel'),input=byId('voice-text-input');
    const allowed=options.canOpenPage?options.canOpenPage('assistant'):doc.documentElement.dataset.accessMode==='admin';
    let available=allowed,disposed=false;const listeners=[];
    function listen(node,type,handler){node.addEventListener(type,handler);listeners.push(()=>node.removeEventListener(type,handler));}
    function setOpen(open,{focus=true}={}){
      if(open&&(!available||disposed))return false;
      const changed=panel.hidden===open;
      panel.hidden=!open;panel.classList.toggle('open',open);panel.setAttribute('aria-hidden',String(!open));entry.setAttribute('aria-expanded',String(open));
      if(focus&&changed)(open?input:entry).focus();return true;
    }
    function setAvailable(value){available=allowed&&value===true&&!disposed;entry.hidden=!available;entry.disabled=!available;if(!available)setOpen(false,{focus:false});}
    panel.hidden=true;panel.setAttribute('aria-label','AI Agent');entry.title='AI Agent';entry.setAttribute('aria-label','AI Agent');entry.querySelector('.voice-toggle-label').textContent='AI Agent';setAvailable(allowed);
    if(allowed){
      // The archived panel is a body sibling; compact rules belong to the Classic app.
      byId('app').append(panel);
      const el=(tag,attrs,text)=>{const node=doc.createElement(tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,value);if(text)node.textContent=text;return node;};
      const body=panel.querySelector('.voice-panel-body'),replies=el('section',{id:'chat-replies',class:'chat-replies','aria-label':'AI replies',hidden:''});
      const toggle=el('button',{type:'button',class:'chat-icon',id:'chat-replies-toggle','aria-controls':'chat-replies'},'✧');
      const close=byId('voice-panel-close');close.setAttribute('aria-label','Close AI Agent');close.classList.add('chat-icon');
      const replyClose=el('button',{type:'button',class:'chat-icon',id:'chat-replies-close','aria-label':'Close replies'},'×');
      replies.append(replyClose,byId('voice-conversation'));const composer=byId('voice-text-form'),rail=composer.querySelector('.voice-text-rail');rail.prepend(toggle);rail.append(close);body.append(replies,composer);panel.classList.add('chat-dock','chat-minimal');
      byId('voice-text-send').setAttribute('aria-label','Send message');doc.querySelector('label[for="voice-text-input"]').textContent='Message AI Agent';
      function showReplies(open){replies.hidden=!open;toggle.setAttribute('aria-expanded',String(open));toggle.setAttribute('aria-label',open?'Hide replies':'Show replies');}
      const repliesObserver=new view.MutationObserver(()=>{toggle.setAttribute('aria-expanded',String(!replies.hidden));toggle.setAttribute('aria-label',replies.hidden?'Show replies':'Hide replies');});
      repliesObserver.observe(replies,{attributes:true,attributeFilter:['hidden']});listeners.push(()=>repliesObserver.disconnect());
      showReplies(false);listen(toggle,'click',()=>showReplies(replies.hidden));listen(replyClose,'click',()=>{showReplies(false);toggle.focus();});
      listen(entry,'click',()=>setOpen(panel.hidden));listen(close,'click',()=>setOpen(false));
      listen(panel,'keydown',event=>{if(event.key==='Escape'){event.preventDefault();setOpen(false);}});
    }
    function dispose(){if(disposed)return;disposed=true;setAvailable(false);listeners.splice(0).forEach(remove=>remove());}
    view.addEventListener('pagehide',dispose,{once:true});
    return {setOpen,setAvailable,dispose};
  }
  function mountWorkspace(doc,view,options={}){
    const byId=id=>doc.getElementById(id),tr=value=>view.ThirdHandI18n?.translate(value)||value;
    const el=(tag,attrs={},text)=>{const node=doc.createElement(tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,String(value));if(text)node.textContent=tr(text);return node;};
    const assistant=mountAssistant(doc,view,options);
    const app=byId('app');app.classList.remove('workspace');app.classList.add('classic-console');
    const mode=el('span',{id:'workspace-mode'},'Unknown mode');byId('topbar').querySelector('.topbar-status').prepend(mode);
    const panel=el('dialog',{id:'classic-settings',class:'workspace','aria-label':'Account and settings'}),close=el('button',{type:'button',class:'action-btn action-secondary',id:'classic-settings-close'},'Back to model');
    const nav=el('nav',{id:'workspace-nav','aria-label':'Account pages'}),bottom=el('div',{class:'nav-bottom'}),main=el('main',{id:'workspace-pages'}),settings=el('div',{class:'workspace-settings'});
    bottom.append(el('div',{class:'nav-footer'},'ACCOUNT & SETTINGS'));nav.append(bottom);main.append(settings);panel.append(close,nav,main);doc.body.append(panel);
    const notice=el('p',{id:'workspace-notice',role:'status',hidden:''});main.prepend(notice);
    const pages=new Map(),runtime={};let current='control',account;
    function hidePanel(){if(panel.open)panel.close();panel.hidden=true;}
    function go(id){
      if(id==='assistant'){if(!assistant.setOpen(true,{focus:false}))return false;hidePanel();byId('voice-text-input').focus();return true;}
      assistant.setOpen(false,{focus:false});
      if(id==='system'||id==='devices')id='account-connections';
      if(pages.has(id)){
        if(notice.classList.contains('classic-notice')){notice.classList.remove('classic-notice');notice.hidden=true;main.prepend(notice);}
        current=id;for(const [key,node]of pages)node.hidden=key!==id;
        account?.routeChanged(id);panel.dataset.section=id==='account-connections'?'devices':'account';nav.hidden=id==='account-connections';panel.hidden=false;if(panel.showModal&&!panel.open)panel.showModal();
      }else{
        hidePanel();current=['overview','vision','system','calibration'].includes(id)?id:'control';account?.routeChanged('control');
        if(id==='vision'){presentation.expandDrawer();byId('sec-xvision')?.classList.remove('collapsed');byId('sec-xvision')?.scrollIntoView?.({block:'start'});}
        if(id==='system'){byId('log-panel').classList.add('open');byId('btn-log-toggle').classList.add('active');}
        if(id==='calibration'){byId('viewport').append(notice);notice.classList.add('classic-notice');notice.hidden=false;notice.textContent=tr('Real robot control is unavailable');}
      }
      view.history.replaceState(null,'','#'+(pages.has(id)?id:id==='vision'?'vision':'control'));
      guide?.routeChanged?.(current);return true;
    }
    account=view.ThirdHandAccountSettings.mountAccountSettings(doc,view,{go,keepLanguageInHeader:true,registerPage(id,page){pages.set(id,page);}});
    byId('account-language-field').hidden=true;
    const top=byId('topbar').querySelector('.topbar-actions'),tools=el('div',{class:'classic-user-tools'});top.prepend(tools);
    const camera=el('button',{type:'button',class:'action-btn'},'Camera');camera.addEventListener('click',()=>go('vision'));tools.append(camera,byId('workspace-account'));
    close.addEventListener('click',()=>go('control'));panel.addEventListener('cancel',event=>{event.preventDefault();go('control');});
    // These drawer methods and section click bodies are reused from the exact
    // UIControls presentation code in 372ac80. No transport/control bindings.
    const presentation={drawer:byId('control-drawer'),_drawerCollapsed:false,
      collapseDrawer(){this.drawer?.classList.add('collapsed');this._drawerCollapsed=true;},
      expandDrawer(){this.drawer?.classList.remove('collapsed');this._drawerCollapsed=false;},
      toggleDrawer(){if(this._drawerCollapsed)this.expandDrawer();else this.collapseDrawer();}
    };
    const handle=byId('drawer-handle'),toggleBtn=byId('btn-drawer-toggle');handle.textContent='◂';
    handle.addEventListener('click',event=>{event.stopPropagation();presentation.toggleDrawer();});
    toggleBtn.addEventListener('click',event=>{event.stopPropagation();presentation.toggleDrawer();});
    doc.querySelectorAll('.sec-header').forEach(header=>{header.addEventListener('click',()=>{const section=header.closest('.drawer-section');section.classList.toggle('collapsed');});});
    handle.setAttribute('role','button');handle.tabIndex=0;handle.setAttribute('aria-label',tr('Control panel'));
    handle.addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();presentation.toggleDrawer();}});
    const log=byId('log-panel');byId('btn-log-toggle').addEventListener('click',()=>go('system'));byId('btn-log-close').addEventListener('click',()=>{log.classList.remove('open');byId('btn-log-toggle').classList.remove('active');});
    doc.querySelector('a[href="tcp-calibration.html"]')?.addEventListener('click',event=>{event.preventDefault();go('calibration');});
    view.ThirdHandStatusLights?.mountStatusLights(doc,view);
    let guide;
    const shell={go,setAssistantAvailable:value=>assistant.setAvailable(value),disposeAssistant:()=>assistant.dispose(),setAccountDataProvider:provider=>account.setDataProvider(provider),
      bindRuntime(value){Object.assign(runtime,value);view.requestAnimationFrame(()=>runtime.scene?._onResize());guide?.bindScene?.(runtime.scene);},
      attachEssentials({preferences}){
        // The compact original header hides text actions on small screens.
        // Keep the same shared logout action reachable inside account settings.
        const theme=byId('theme-select'),selectTheme=value=>{for(const option of theme.options)option.selected=option.value===value.classicThemeId;};preferences.subscribe(selectTheme);
        theme.addEventListener('change',()=>preferences.choose({classicThemeId:theme.value}).catch(()=>{selectTheme(preferences.current());go('account-preferences');notice.hidden=false;notice.textContent=tr('Could not save preferences. Please try again.');}));
      },
      installOnboarding(api){
        guide=api?.mountOnboarding?.(doc,view,{go,panelHost:doc.body,checklistHost:byId('page-account-preferences'),resolveTargets:selectors=>{
          if(selectors.includes('#workspace-model'))presentation.collapseDrawer();
          if(selectors.includes('.workspace-tabs')){presentation.expandDrawer();byId('sec-joints')?.classList.remove('collapsed');byId('sec-joints')?.scrollIntoView?.({block:'start'});}
          return selectors.map(selector=>({'#workspace-model':'#viewport','.workspace-tabs':'#sec-joints .sec-header','.workspace-calibration-info':'#device-status-entry'}[selector]||selector));
        },getContext:()=>({page:current,busy:Boolean(runtime.ui?.lastRobotState?.stateName==='MOVING'),statusText:mode.textContent,cameraText:byId('cam-label')?.textContent}),readJointPreview:()=>runtime.ui?.arm?.getJointAngles()});
        if(byId('workspace-guide'))tools.append(byId('workspace-guide'));
        if(runtime.scene)guide?.bindScene?.(runtime.scene);return guide;
      }
    };
    panel.hidden=true;const initial=view.location.hash.slice(1);if(initial)go(initial);
    return shell;
  }
  return {mountWorkspace};
});
