/* Original 372ac80 presentation + shared cloud adapters; never import old main.js. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandClassicShell=api;})(globalThis,function(){
  'use strict';
  function mountWorkspace(doc,view){
    const byId=id=>doc.getElementById(id),tr=value=>view.ThirdHandI18n?.translate(value)||value;
    const el=(tag,attrs={},text)=>{const node=doc.createElement(tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,String(value));if(text)node.textContent=tr(text);return node;};
    const app=byId('app');app.classList.remove('workspace');app.classList.add('classic-console');
    const mode=el('span',{id:'workspace-mode'},'Unknown mode');byId('topbar').querySelector('.topbar-status').prepend(mode);
    const panel=el('dialog',{id:'classic-settings',class:'workspace','aria-label':'Account and settings'}),close=el('button',{type:'button',class:'action-btn action-secondary',id:'classic-settings-close'},'Back to model');
    const nav=el('nav',{id:'workspace-nav','aria-label':'Account pages'}),bottom=el('div',{class:'nav-bottom'}),main=el('main',{id:'workspace-pages'}),settings=el('div',{class:'workspace-settings'});
    bottom.append(el('div',{class:'nav-footer'},'ACCOUNT & SETTINGS'));nav.append(bottom);main.append(settings);panel.append(close,nav,main);doc.body.append(panel);
    const notice=el('p',{id:'workspace-notice',role:'status',hidden:''});main.prepend(notice);
    const pages=new Map(),runtime={};let current='control',account;
    function hidePanel(){if(panel.open)panel.close();panel.hidden=true;}
    function go(id){
      if(pages.has(id)){
        if(notice.classList.contains('classic-notice')){notice.classList.remove('classic-notice');notice.hidden=true;main.prepend(notice);}
        current=id;for(const [key,node]of pages)node.hidden=key!==id;
        account?.routeChanged(id);panel.hidden=false;if(panel.showModal&&!panel.open)panel.showModal();
      }else{
        hidePanel();current=['overview','vision','system','calibration'].includes(id)?id:'control';account?.routeChanged('control');
        if(id==='vision'){presentation.expandDrawer();byId('sec-xvision')?.scrollIntoView?.({block:'start'});}
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
    const shell={go,setAccountDataProvider:provider=>account.setDataProvider(provider),
      bindRuntime(value){Object.assign(runtime,value);view.requestAnimationFrame(()=>runtime.scene?._onResize());guide?.bindScene?.(runtime.scene);},
      attachEssentials({preferences}){
        tools.append(byId('workspace-logout'),doc.querySelector('.workspace-history-link'));
        // The compact original header hides text actions on small screens.
        // Keep the same shared logout action reachable inside account settings.
        const logout=el('button',{type:'button',id:'classic-settings-logout'},'Sign out');
        logout.addEventListener('click',()=>byId('workspace-logout').click());nav.append(logout);
        const theme=byId('theme-select'),selectTheme=value=>{for(const option of theme.options)option.selected=option.value===value.classicThemeId;};preferences.subscribe(selectTheme);
        theme.addEventListener('change',()=>preferences.choose({classicThemeId:theme.value}).catch(()=>{selectTheme(preferences.current());go('account-preferences');notice.hidden=false;notice.textContent=tr('Could not save preferences. Please try again.');}));
      },
      installOnboarding(api){
        guide=api?.mountOnboarding?.(doc,view,{go,panelHost:doc.body,checklistHost:byId('page-account-preferences'),resolveTargets:selectors=>selectors.map(selector=>({'#workspace-model':'#viewport','.workspace-tabs':'#sec-joints .sec-header','.workspace-calibration-info':'a[href="tcp-calibration.html"]'}[selector]||selector)),getContext:()=>({page:current,busy:Boolean(runtime.ui?.lastRobotState?.stateName==='MOVING'),statusText:mode.textContent,cameraText:byId('cam-label')?.textContent}),readJointPreview:()=>runtime.ui?.arm?.getJointAngles()});
        if(byId('workspace-guide'))tools.append(byId('workspace-guide'));
        if(runtime.scene)guide?.bindScene?.(runtime.scene);return guide;
      }
    };
    panel.hidden=true;const initial=view.location.hash.slice(1);if(initial)go(initial);
    return shell;
  }
  return {mountWorkspace};
});
