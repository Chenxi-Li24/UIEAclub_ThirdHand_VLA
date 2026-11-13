/* Presentation shell: retains the existing controls and never sends robot commands. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.ThirdHandWorkspace = api;
})(globalThis, function () {
  'use strict';
  const mounted = new WeakMap();
  const pages = [
    ['overview', '◫', 'System Check', 'Prepare services and check connection feedback.'],
    ['control', '⌁', 'Digital Twin', 'Preview targets before confirming a movement.'],
    ['vision', '◎', 'Vision tasks', 'Select a detected target and follow depth acquisition and grasp progress.'],
    ['calibration', '⊹', 'Calibration', 'Use the existing TCP wizard and its measured results.'],
    ['assistant', '✧', 'AI Agent', 'Describe a movement, inspect the candidate, then confirm or reject.'],
    ['system', '⚙', 'System', 'Live communication logs and interface settings.'],
  ];
  const iconPaths = {
    overview: ['M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z'],
    control: ['M5 20v-6l5-4 5 3 4-6', 'M2 21h8 M16 6l3-1 2 3', 'M6 12l-2-5 5-3 3 5'],
    vision: ['M8 3H4v4 M16 3h4v4 M4 17v4h4 M20 17v4h-4', 'M7 12s2-4 5-4 5 4 5 4-2 4-5 4-5-4-5-4z', 'M12 10v4'],
    calibration: ['M12 2v5 M12 17v5 M2 12h5 M17 12h5', 'M17 12a5 5 0 1 1-5-5', 'M12 11v2 M11 12h2'],
    assistant: ['M20 11a8 8 0 0 1-8 8H5l-3 3v-9a9 9 0 0 1 15-7', 'M19 1v6 M16 4h6', 'M7 11h7 M7 14h4'],
    system: ['M4 5h16 M4 12h16 M4 19h16', 'M8 3v4 M16 10v4 M10 17v4'],
    grid: ['M4 4h16v16H4z M4 10h16 M4 15h16 M10 4v16 M15 4v16'],
    axes: ['M5 19 19 5 M5 5v14h14 M15 5h4v4 M5 5l-2 3 M19 19l-3-2'],
    reset: ['M4 10a8 8 0 1 1 2 8', 'M4 4v6h6'],
    floor: ['M3 20h18 M7 17h10v-6L12 8l-5 3z M12 8V3 M9 3h6'],
    wall: ['M3 3v18 M6 7v10h6l3-5-3-5z M15 12h6 M21 9v6'],
    sidebar: ['M4 4h16v16H4z M9 4v16 M16 9l-3 3 3 3'],
  };
  function mountWorkspace(doc, win, options = {}) {
    if (mounted.has(doc)) return mounted.get(doc);
    const byId = id => doc.getElementById(id);
    const element = (tag, attrs = {}, text = '') => {
      const node = doc.createElement(tag);
      for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
      if (text) node.textContent = text;
      return node;
    };
    const move = (id, parent) => { const node = byId(id); if (node) parent.appendChild(node); return node; };
    const icon = name => {
      const svg = doc.createElementNS('http://www.w3.org/2000/svg', 'svg');
      for (const [key,value] of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.65','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false'})) svg.setAttribute(key,value);
      for(const d of iconPaths[name] || iconPaths.overview){const path=doc.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',d);svg.appendChild(path);}
      return svg;
    };
    const app = byId('app');
    doc.documentElement.dataset.theme = 'workspace';
    app.classList.add('workspace');
    const nav = element('nav', { id: 'workspace-nav', 'aria-label': 'Workspace pages' });
    const brand = element('div', { class: 'workspace-brand', 'aria-label': 'ThirdHand' });
    brand.append(element('span', {class:'brand-mark','aria-hidden':'true'}, 'T/H'), element('span', {class:'brand-wordmark'}, 'THIRDHAND'));
    nav.appendChild(brand);
    const main = element('main', { id: 'workspace-pages' });
    const workspaceBody = element('div', { id: 'workspace-body' });
    const pageNodes = new Map(), navNodes = new Map();
    const notice = element('div', { id: 'workspace-notice', role: 'status', 'aria-live': 'polite', hidden: '' });
    const task = element('div', { id: 'workspace-task', role: 'status', 'aria-live': 'polite', hidden: '' });
    const mode = element('span', { id: 'workspace-mode' }, 'Unknown mode');
    app.prepend(nav); app.append(workspaceBody, move('statusbar', app)); workspaceBody.appendChild(main);
    const alerts = element('div', { id: 'workspace-alerts' });
    main.appendChild(alerts); alerts.append(notice, task);
    byId('topbar').querySelector('.topbar-status').prepend(mode);
    for (const [index, [id, , label, detail]] of pages.entries()) {
      const button = element('button', { type: 'button', 'data-page': id, 'aria-label': label, title: label });
      const navIcon = element('span', { class: 'nav-icon', 'aria-hidden': 'true' }); navIcon.appendChild(icon(id));
      button.append(navIcon, element('span', { class: 'nav-label' }, label));
      button.addEventListener('click', () => id==='assistant'?setChatOpen(!chatOpen):go(id)); nav.appendChild(button); navNodes.set(id, button);
      const page = element('section', { id: `page-${id}`, class: 'workspace-page', 'aria-labelledby': `heading-${id}`, hidden: '' });
      const heading = element('div', { class: 'workspace-heading' });
      heading.append(element('div',{class:'page-eyebrow','aria-hidden':'true','data-i18n-skip':''},'THIRDHAND'), element('h1', { id: `heading-${id}`, tabindex: '-1' }, label), element('p', {}, detail));
      page.appendChild(heading); main.appendChild(page); pageNodes.set(id, page);
    }
    const navBottom=element('div',{class:'nav-bottom'});
    const navToggle=element('button',{id:'workspace-nav-toggle',class:'nav-toggle',type:'button','aria-controls':'workspace-nav'});
    const toggleIcon=element('span',{class:'nav-icon nav-toggle-icon','aria-hidden':'true'});toggleIcon.appendChild(icon('sidebar'));
    const toggleLabel=element('span',{class:'nav-toggle-label'});
    navToggle.append(toggleIcon,toggleLabel);
    navBottom.append(navToggle,element('div',{class:'nav-footer','aria-hidden':'true'},'CONTROL WORKSPACE'));nav.appendChild(navBottom);
    const control = pageNodes.get('control');
    const layout = element('div', { class: 'control-layout' }); control.appendChild(layout);
    const modelCard = element('section', { id: 'workspace-model', class: 'model-card', 'aria-label': 'Robot model' });
    const modelHeader = element('div', { class: 'model-header' });
    const modelTitle=element('div',{class:'model-title'});
    modelTitle.append(element('span',{class:'model-eyebrow'},'Arm view'),element('strong', {}, '3D workspace'));
    modelHeader.append(modelTitle, move('view-tools', modelHeader));
    modelCard.append(modelHeader, move('viewport', modelCard)); workspaceBody.prepend(modelCard);
    for(const [id,name]of [['btn-tool-grid','grid'],['btn-tool-axes','axes'],['btn-tool-reset','reset'],['btn-tool-floor','floor'],['btn-tool-wall','wall']]){
      const button=byId(id);button.setAttribute('aria-label',button.title);button.replaceChildren(icon(name));
    }
    byId('viewport').appendChild(element('div',{class:'model-hint','aria-hidden':'true'},'Drag to orbit · Scroll to zoom'));
    const modelLoading=element('div',{id:'model-loading',role:'status',style:'position:absolute;inset:0;z-index:3;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:12px;background:#ffffffed'});
    modelLoading.append(element('span',{id:'model-loading-text'},'Loading 3D workspace…'));
    const retryModel=element('button',{type:'button',class:'action-btn'},'Reload model');
    retryModel.addEventListener('click',()=>win.location.reload());modelLoading.append(retryModel);byId('viewport').append(modelLoading);
    const controls = element('section', { class: 'control-card', 'aria-label': 'Manual targets' }); layout.appendChild(controls);
    const tabs = element('div', { class: 'workspace-tabs', role: 'tablist', 'aria-label': 'Control type' }); controls.appendChild(tabs);
    const tabNodes = new Map(), panes = new Map();
    for (const [id, label, sections] of [
      ['joints', 'Joints', ['sec-joints', 'sec-presets']],
      ['tcp', 'TCP', ['sec-tcp']], ['gripper', 'Gripper', ['sec-gripper']],
    ]) {
      const tab = element('button', { type: 'button', role: 'tab', id: `tab-${id}`, 'aria-controls': `pane-${id}` }, label);
      const pane = element('div', { role: 'tabpanel', id: `pane-${id}`, 'aria-labelledby': `tab-${id}` });
      tab.addEventListener('click', () => selectControl(id));
      tab.addEventListener('keydown', event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault(); const keys = [...tabNodes.keys()], current = keys.indexOf(id);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? keys.length - 1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + keys.length) % keys.length;
        selectControl(keys[next]); tabNodes.get(keys[next]).focus();
      });
      tabs.appendChild(tab); controls.appendChild(pane); sections.forEach(section => move(section, pane));
      tabNodes.set(id, tab); panes.set(id, pane);
    }
    move('sec-actions', controls); move('sec-rt-angles', controls);
    const vision = pageNodes.get('vision'); move('sec-xvision', vision);
    const feed=byId('xvision-feed'),feedContainer=feed.parentElement;
    const emptyCamera=element('div',{class:'camera-empty',role:'status'});
    emptyCamera.append(icon('vision'),element('strong',{},'Waiting for camera feed'),element('span',{},'The live image appears here when the camera is ready.'));
    feedContainer.appendChild(emptyCamera);
    const showCameraFrame=ready=>{emptyCamera.hidden=ready;feedContainer.dataset.cameraState=ready?'ready':'waiting';};
    feed.addEventListener('load',()=>showCameraFrame(feed.naturalWidth>0));
    feed.addEventListener('error',()=>showCameraFrame(false));
    showCameraFrame(feed.complete&&feed.naturalWidth>0);
    const following = element('details', { class: 'workspace-following' });
    following.appendChild(element('summary', {}, 'Person following')); vision.appendChild(following); move('sec-dummy', following);
    move('voice-panel', pageNodes.get('assistant')); move('log-panel', pageNodes.get('system'));
    const settings = element('div', { class: 'workspace-settings' }); pageNodes.get('system').appendChild(settings);
    settings.appendChild(element('strong', {}, 'Appearance · White / orange'));
    // Keep legacy IDs for the existing controller's bindings; their floating containers are empty.
    byId('theme-select').hidden = true;
    move('theme-select', settings);
    move('conn-bar', byId('topbar').querySelector('.topbar-actions'));
    byId('conn-bar').querySelector('.conn-input').textContent = 'Robot';
    const overview = element('div', { class: 'overview-grid' }); pageNodes.get('overview').appendChild(overview);
    const summaries = [['connection', 'Robot connection', 'conn-ip'], ['feedback', 'SDK feedback', 'hb-label'],
      ['vision', 'Vision and depth', 'vision-lock-reason'], ['tcp', 'Current TCP', 'grasp-tcp']];
    for (const [id, label] of summaries) {
      const card = element('article', { class: `overview-card overview-card-${id}` });
      const cardIcon=element('span',{class:'summary-icon','aria-hidden':'true'});cardIcon.appendChild(icon({connection:'control',feedback:'system',vision:'vision',tcp:'calibration'}[id]));
      card.append(cardIcon,element('h2', {}, label), element('p', { id: `workspace-summary-${id}` }, 'Unknown'));
      overview.appendChild(card);
    }
    const shortcuts = element('div', { class: 'workspace-shortcuts' }); pageNodes.get('overview').appendChild(shortcuts);
    for (const [id, label] of [['control', 'Open manual control'], ['vision', 'Open vision tasks'], ['calibration', 'Open calibration']]) {
      const button = element('button', { type: 'button', class: 'action-btn' }, label);
      button.addEventListener('click', () => go(id)); shortcuts.appendChild(button);
    }
    const journey = element('section', {class:'workspace-journey'});
    journey.append(element('h2', {}, 'System check'), element('p', {}, 'Seven system checks. One click.'));
    overview.before(journey);shortcuts.hidden=true;
    const readyButton=element('button',{type:'button',class:'action-btn action-primary',id:'system-ready-button'},'Run system check');
    const readyResult=element('p',{role:'status','aria-live':'polite',id:'system-ready-result'},'Ready to check');
    const progress=element('div',{class:'check-progress',role:'progressbar','aria-label':'System check progress','aria-valuemin':'0','aria-valuemax':'100','aria-valuenow':'0'});
    const fill=element('span');progress.append(fill);
    const percentage=element('span',{class:'check-percentage','aria-hidden':'true'},'0%');
    const readyServices=element('ul',{id:'system-ready-services',class:'system-checks'});
    const checks=[['api','Web API'],['sdk','SDK feedback'],['ai','AI service'],['vision','Vision service'],['network','Host network'],['wifi','Host Wi-Fi'],['tcp','TCP calibration']];
    const rows=new Map();
    for(const [id,label] of checks){
      const row=element('li',{'data-status':'pending'});
      const name=element('strong',{},label),badge=element('span',{class:'check-badge'},'Not checked'),detail=element('p',{},'');
      row.append(name,badge,detail);readyServices.append(row);rows.set(id,{row,badge,detail});
    }
    journey.append(percentage,readyResult,progress,readyServices,readyButton);
    const setup=element('details',{class:'check-setup'});setup.append(element('summary',{},'Service setup'));
    setup.append(element('p',{},'To start missing services, run this command on Ubuntu, then run the check again.'),element('code',{tabindex:'0'},'./thirdhand ensure --profile manual-control'));
    journey.append(setup);
    let disposed=false,requesting=false;
    const labels={pending:'Not checked',running:'Checking',passed:'Passed',failed:'Failed',warning:'Warning',unknown:'Unavailable',skipped:'Not applicable'};
    readyButton.addEventListener('click',async()=>{
      if(requesting||disposed)return;
      requesting=true;readyButton.disabled=true;readyButton.textContent='Checking…';journey.setAttribute('aria-busy','true');
      progress.setAttribute('aria-valuenow','0');fill.style.width='0%';percentage.textContent='0%';
      for(const {row,badge,detail} of rows.values()){row.dataset.status='pending';badge.textContent=labels.pending;badge.removeAttribute('title');detail.textContent='';}
      let completed=0,issues=0;
      for(const [id,label] of checks){
        if(disposed)break;
        const {row,badge,detail}=rows.get(id);row.dataset.status='running';badge.textContent=labels.running;
        readyResult.textContent=`Checking ${label} · ${completed} / ${checks.length}`;
        const dwell=win.setTimeout ? new Promise(resolve=>win.setTimeout(resolve,1100)) : Promise.resolve();
        try{
          if(!win.fetch)throw Error('unavailable');
          const clock=()=>win.performance?.now?.() ?? Date.now();
          const started=clock();
          let data;
          if(options.runSystemCheck)data=await options.runSystemCheck(id);
          else {
          const response=await win.fetch((id==='api'||id==='tcp')?'/health':'/api/system-diagnostics?check='+id,{cache:'no-store',signal:win.AbortSignal?.timeout(8000)});
          if(!response.ok)throw Error('unavailable');
          data=await response.json();
          if(id==='tcp'){
            const tcp=data.dependencies?.tcpCalibration;
            data.status=tcp?.ready===true?'passed':tcp?'warning':'unknown';
            data.detail=tcp?.ready===true?'TCP calibration service is ready. Physical calibration accuracy is not verified.':tcp?.reason==='tcp_calibration_disabled'?'TCP calibration is disabled on the host. Enable and configure the calibration service.':'TCP calibration is unavailable or not configured. Check host configuration.';
          }
          }
          const roundTripMs=Math.max(0,clock()-started);
          await dwell;
          if(disposed)break;
          const state=id==='api'&&!options.runSystemCheck?(data.status==='ready'?'passed':'warning'):data.status;
          if(!['passed','failed','warning','unknown','skipped'].includes(state))throw Error('invalid');
          row.dataset.status=state;badge.textContent=labels[state];
          const latency=id==='api'?roundTripMs:data.latencyMs;
          if(state==='passed'&&Number.isFinite(latency)&&latency>=0){
            const kind=id==='api'?'RTT':'TCP';
            badge.textContent+=` · ${kind} ${latency<1?'<1':Math.round(latency)} ms`;
            badge.title=id==='api'?'Browser to Ubuntu HTTP round trip, including response processing. Animation delay excluded.':'Ubuntu to service TCP connection time. Not model inference or browser latency.';
          }
          detail.textContent=id==='api'?(state==='passed'?'Gateway API responded successfully.':'Gateway responded but is not ready.') : data.detail;
          if(['failed','warning','unknown'].includes(state))issues++;
        }catch{await dwell;if(disposed)break;row.dataset.status='failed';badge.textContent=labels.failed;detail.textContent='Check unavailable or timed out. Check your connection and retry.';issues++;}
        completed++;const percent=Math.round(completed/checks.length*100);fill.style.width=percent+'%';percentage.textContent=percent+'%';progress.setAttribute('aria-valuenow',String(percent));
      }
      if(disposed)return;
      readyResult.textContent=issues?`Check complete · ${issues} item${issues===1?'':'s'} need attention`:'Check complete · All applicable checks passed';
      readyResult.textContent+=' · '+new Date().toLocaleTimeString('en-GB');
      requesting=false;readyButton.disabled=false;readyButton.textContent='Run again';journey.setAttribute('aria-busy','false');
    });
    win.addEventListener('pagehide',()=>{disposed=true;},{once:true});
    const sidebarStatus=element('section',{class:'workspace-live-status','aria-label':'Live status'});
    sidebarStatus.append(element('h2',{},'Live status'));
    for(const [label,id] of [['Connection','conn-ip'],['SDK','hb-label'],['Robot','state-badge'],['AI','voice-ai-status']]) {
      const row=element('p');row.append(element('span',{},label+' · '),element('strong',{id:'sidebar-'+id},'Unknown'));sidebarStatus.append(row);
    }
    nav.insertBefore(sidebarStatus,navBottom);
    for(const [index,id] of ['overview','assistant','control','vision','calibration','system'].entries()) {
      nav.insertBefore(navNodes.get(id),sidebarStatus);
    }
    const naturalEntry=navNodes.get('assistant');
    naturalEntry.classList.add('nav-natural-language');
    naturalEntry.querySelector('.nav-label').textContent='AI Agent';
    byId('btn-voice-toggle').querySelector('.voice-toggle-label').textContent='AI Agent';
    byId('btn-voice-toggle').title='AI Agent';
    byId('btn-voice-toggle').setAttribute('aria-label','AI Agent');
    navBottom.prepend(naturalEntry);
    const chat=byId('voice-panel');
    app.append(chat);chat.hidden=true;
    let chatOpen=false;
    function setChatOpen(open){
      if(open&&options.canOpenPage&&!options.canOpenPage('assistant'))return false;
      if(!open&&(runtime.voice?.recording||runtime.voice?.starting)){announce('Stop or cancel recording before closing voice input.','Stop or cancel recording before closing voice input.');return false;}
      chatOpen=open;chat.hidden=!open;
      naturalEntry.setAttribute('aria-expanded',String(open));
      naturalEntry.classList.toggle('active',open);
      if(open)runtime.voice?.openPanel();else runtime.voice?.closePanel();
      if(open)byId('voice-text-input').focus();else naturalEntry.focus();
      return true;
    }
    naturalEntry.setAttribute('aria-controls','voice-panel');naturalEntry.setAttribute('aria-expanded','false');
    chat.classList.add('chat-dock','chat-minimal');
    const chatBody=chat.querySelector('.voice-panel-body');
    const replies=element('section',{id:'chat-replies',class:'chat-replies','aria-label':'AI replies',hidden:''});
    const replyClose=element('button',{type:'button',class:'chat-icon',id:'chat-replies-close','aria-label':'Close replies'},'×');
    replies.append(replyClose,byId('voice-conversation'),byId('voice-intent-card'));
    const composer=byId('voice-text-form');
    const rail=composer.querySelector('.voice-text-rail');
    const replyToggle=element('button',{type:'button',class:'chat-icon',id:'chat-replies-toggle','aria-label':'Show replies','aria-controls':'chat-replies','aria-expanded':'false'});
    replyToggle.append(icon('assistant'));
    const voiceToggle=element('button',{type:'button',class:'chat-icon',id:'chat-voice','aria-label':'Voice input','aria-expanded':'false','aria-controls':'chat-audio'});
    voiceToggle.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="9" y="3" width="6" height="12" rx="3"/><path d="M5 11v1a7 7 0 0 0 14 0v-1M12 19v3M8 22h8"/></svg>';
    rail.prepend(replyToggle);rail.append(voiceToggle);
    byId('voice-text-input').placeholder='Message…';
    byId('voice-text-send').setAttribute('aria-label','Send message');
    const audio=element('section',{id:'chat-audio',class:'chat-audio',hidden:'','aria-label':'Voice input'});
    const audioClose=element('button',{type:'button',class:'chat-icon','aria-label':'Close voice input'},'×');
    const settingsDrawer=element('details',{class:'chat-settings'});
    settingsDrawer.append(element('summary',{},'Settings'));
    chatBody.querySelectorAll('.voice-config-block').forEach(node=>settingsDrawer.append(node));
    audio.append(audioClose,byId('voice-mic-toggle'),chat.querySelector('.voice-capture-block'),settingsDrawer);
    chatBody.append(replies,audio,composer);
    function showReplies(open){replies.hidden=!open;replyToggle.setAttribute('aria-expanded',String(open));replyToggle.setAttribute('aria-label',open?'Hide replies':'Show replies');}
    replyToggle.addEventListener('click',()=>showReplies(replies.hidden));
    replyClose.addEventListener('click',()=>{showReplies(false);replyToggle.focus();});
    function showAudio(open){audio.hidden=!open;voiceToggle.setAttribute('aria-expanded',String(open));}
    voiceToggle.addEventListener('click',()=>showAudio(audio.hidden));
    audioClose.addEventListener('click',()=>{if(runtime.voice?.recording||runtime.voice?.starting)return;showAudio(false);voiceToggle.focus();});
    const candidateObserver=new win.MutationObserver(()=>{if(!byId('voice-intent-card').hidden)showReplies(true);});
    candidateObserver.observe(byId('voice-intent-card'),{attributes:true,attributeFilter:['hidden']});
    const replyObserver=new win.MutationObserver(records=>{
      // Background reconnect notices must not reopen a window the user dismissed.
      if(records.some(record=>Array.from(record.addedNodes||[]).some(node=>node.nodeType===1&&node.matches?.('.voice-message--ai,.voice-message--user'))))showReplies(true);
    });
    replyObserver.observe(byId('voice-conversation'),{childList:true,subtree:true,characterData:true});
    win.addEventListener('pagehide',()=>{candidateObserver.disconnect();replyObserver.disconnect();},{once:true});

    const calibration = pageNodes.get('calibration');
    const calibrationInfo = element('div', { class: 'workspace-calibration-info' });
    calibrationInfo.append(element('p', {}, 'TCP calibration uses the existing service. Hand-eye collection is not exposed by this gateway.'),
      element('p', { id: 'workspace-calibration-tcp', 'data-i18n-skip': '' }, 'TCP: --'));
    calibration.appendChild(calibrationInfo);
    const palette=element('div',{class:'workspace-palette','aria-hidden':'true'});
    for(const color of ['#ffffff','#f97316','#26313b']){const swatch=element('span');swatch.style.backgroundColor=color;palette.appendChild(swatch);}
    settings.appendChild(palette);
    const statusLights=win.ThirdHandStatusLights?.mountStatusLights(doc,win);
    const runtime = {}, scrollPositions = new Map(); let current = null, controlTab = 'joints', frame = null, calibrationSeenKnown = false, lastTeachUnsafe = false, moving = false, robotStateName = null, guide = null;
    const text = (en, zh) => doc.documentElement.lang === 'zh-CN' ? zh : en;
    const navStorageKey='thirdhand.nav-state';
    const navMedia=win.matchMedia?.('(min-width: 1041px)');
    let navPreference=null,navExpanded;
    try{const saved=win.localStorage?.getItem(navStorageKey);if(saved==='collapsed'||saved==='expanded')navPreference=saved;}catch{/* Keep navigation usable when browser storage is blocked. */}
    function setNavigationExpanded(expanded){
      navExpanded=expanded;app.dataset.navState=expanded?'expanded':'collapsed';
      navToggle.setAttribute('aria-expanded',String(expanded));
      const action=expanded?text('Collapse menu','收起菜单'):text('Expand menu','展开菜单');
      navToggle.setAttribute('aria-label',action);navToggle.title=action;toggleLabel.textContent=action;
      win.requestAnimationFrame(()=>runtime.scene?._onResize());
    }
    setNavigationExpanded(navPreference?navPreference==='expanded':navMedia?.matches??true);
    navToggle.addEventListener('click',()=>{
      navPreference=navExpanded?'collapsed':'expanded';setNavigationExpanded(!navExpanded);
      try{win.localStorage?.setItem(navStorageKey,navPreference);}catch{/* The current session still retains the choice. */}
    });
    navMedia?.addEventListener?.('change',event=>{if(navPreference===null)setNavigationExpanded(event.matches);});
    function announce(en, zh) { notice.textContent = text(en, zh); notice.hidden = false; }
    function canLeave() {
      if (current === 'calibration' && frame) {
        try {
          const state = frame.contentWindow?.ThirdHandCalibrationNavigationState?.();
          if (state?.known) { calibrationSeenKnown = true; lastTeachUnsafe = Boolean(state.teachActive || state.teachPending); }
          else if (state?.teachActive || state?.teachPending) lastTeachUnsafe = true;
          else if (state?.loaded) calibrationSeenKnown = true;
          else if (state?.unavailable && !lastTeachUnsafe) calibrationSeenKnown = true;
        } catch { /* Retain the last known teaching state if child feedback is unavailable. */ }
        if (!calibrationSeenKnown && !lastTeachUnsafe) {
          announce('Wait for calibration status before changing pages.', '请等待标定状态载入，再切换页面。'); return false;
        }
        if (lastTeachUnsafe) {
          announce('Lock the current pose in calibration before changing pages.', '请先在标定页面锁定当前姿态，再切换页面。'); return false;
        }
      }
      return true;
    }
    function go(id, { focus = false } = {}) {
      if(id==='assistant'){
        if(!current)go('overview');
        return setChatOpen(true);
      }
      if (id === 'account-connections' && doc.getElementById('workspace-bootstrap')) id = 'system';
      if (!pageNodes.has(id) || options.canOpenPage && !options.canOpenPage(id)) id = 'control';
      if (id !== current && !canLeave()) { win.history.replaceState(null, '', `#${current}`); return false; }
      if (current === id) {
        if (id === 'assistant' && byId('voice-panel').inert) runtime.voice?.openPanel();
        return true;
      }
      if (current === 'assistant') runtime.voice?.closePanel();
      if (current) scrollPositions.set(current, main.scrollTop);
      current = id; notice.hidden = true;
      for (const [key, page] of pageNodes) page.hidden = key !== id;
      main.scrollTop = scrollPositions.get(id) || 0;
      for (const [key, button] of navNodes) {
        button.classList.toggle('active', key === 'assistant' ? chatOpen : key === id);
        if (key === id) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
      }
      if (id === 'calibration' && !frame && options.calibrationEntry !== null) {
        frame = element('iframe', { id: 'workspace-calibration-frame', title: 'TCP calibration', src: options.calibrationEntry || 'tcp-calibration.html?embedded=1' });
        calibration.appendChild(frame);
      }
      if (id === 'assistant') runtime.voice?.openPanel();
      win.history.replaceState(null, '', `#${id}`);
      guide?.routeChanged(id);
      account?.routeChanged(id);
      win.requestAnimationFrame(() => runtime.scene?._onResize());
      if (focus) byId(`heading-${id}`).focus();
      refresh(); return true;
    }
    function selectControl(id) {
      if (!panes.has(id)) return;
      controlTab = id;
      runtime.ui?.selectWorkspaceControl?.(id);
      byId('sec-actions').hidden = id === 'gripper';
      byId('btn-send').textContent = id === 'tcp' ? 'Send TCP target' : 'Send joint target';
      for (const [key, pane] of panes) pane.hidden = key !== id;
      for (const [key, tab] of tabNodes) {
        tab.setAttribute('aria-selected', String(key === id)); tab.tabIndex = key === id ? 0 : -1;
      }
    }
    function refresh() {
      const set = (id, value) => { const node = byId(id); if (node && node.textContent !== value) node.textContent = value; };
      for (const [id, , source] of summaries) set(`workspace-summary-${id}`, byId(source)?.textContent || text('Unknown', '未知'));
      set('workspace-summary-vision', [byId('cam-label')?.textContent, byId('vision-lock-reason')?.textContent].filter(Boolean).join(' · ') || text('Unknown', '未知'));
      set('workspace-calibration-tcp', byId('grasp-tcp')?.textContent || 'TCP: --');
      for(const id of ['conn-ip','hb-label','state-badge','voice-ai-status']) set('sidebar-'+id,byId(id)?.textContent||text('Unknown','未知'));
      const grasp = runtime.ui?.webGraspStatus;
      const depth = runtime.ui?.activeDepthStatus;
      const following = byId('sec-dummy')?.dataset.running === 'true';
      const jobs = [];
      if (grasp?.active) jobs.push(`${text('Grasp in progress', '抓取进行中')} · ${grasp.phase || '--'}`);
      if (depth?.active) jobs.push(`${text('Depth acquisition in progress', '深度获取中')} · ${depth.phase || '--'}`);
      else if (depth?.phase === 'uncertain') jobs.push(text('Depth motion uncertain · inspect the robot', '深度运动状态不确定 · 请现场检查机械臂'));
      if (following) jobs.push(text('Person following in progress', '人物跟随中'));
      if (moving) jobs.push(text('Robot motion in progress', '机械臂运动中'));
      task.hidden = jobs.length === 0;
      if (!task.hidden) set('workspace-task', jobs.join(' / '));
      guide?.refresh();
      account?.refresh();
    }
    function bindRuntime(values) {
      Object.assign(runtime, values);
      if (values.ui) values.ui.selectWorkspaceControl?.(controlTab);
      if (values.ws && !runtime.wsBound) {
        runtime.wsBound = true;
        statusLights?.bind(values.ws);
        values.ws.on('config', config => {
          const connection = config.connection || {};
          mode.textContent = connection.simulated === true ? text('Local simulation', '本地模拟') : connection.dryRun === true ? text('Dry run', '空跑模式') : connection.simulated === false ? text('Hardware', '实机') : text('Unknown mode', '模式未知');
          refresh();
        });
        values.ws.on('robot_state', state => { moving = state.moving === true || state.motionActive === true; robotStateName=state.stateName||null; refresh(); });
      }
      if (values.voice && chatOpen) values.voice.openPanel();
      if (values.scene) guide?.bindScene(values.scene);
      win.requestAnimationFrame(() => runtime.scene?._onResize());
      refresh();
    }
    const redirect = (node, page) => node?.addEventListener('click', event => {
      event.preventDefault(); event.stopImmediatePropagation(); go(page, { focus: true });
    }, true);
    byId('btn-voice-toggle').addEventListener('click',event=>{event.preventDefault();event.stopImmediatePropagation();setChatOpen(!chatOpen);},true);
    byId('voice-panel-close').addEventListener('click',event=>{event.preventDefault();event.stopImmediatePropagation();setChatOpen(false);},true);
    byId('voice-panel').addEventListener('keydown', event => {
      if (event.key !== 'Escape') return;
      event.preventDefault(); event.stopImmediatePropagation(); setChatOpen(false);
    }, true);
    redirect(byId('btn-log-toggle'), 'system'); redirect(byId('btn-log-close'), 'control');
    redirect(doc.querySelector('a[href="tcp-calibration.html"]'), 'calibration');
    win.addEventListener('hashchange', () => go(win.location.hash.slice(1)));
    const observer = new win.MutationObserver(refresh);
    for (const id of [...summaries.map(item => item[2]), 'grasp-phase', 'active-depth-phase', 'cam-label', 'dummy-phase', 'workspace-web-status', 'state-badge', 'voice-ai-status']) {
      if (byId(id)) observer.observe(byId(id), { childList: true, subtree: true, characterData: true });
    }
    observer.observe(byId('sec-dummy'), { attributes: true, attributeFilter: ['data-running'] });
    function onboardingContext(){
      let teachingUnknown=false,teaching=false;
      if(current==='calibration'&&frame){
        try{
          const state=frame.contentWindow?.ThirdHandCalibrationNavigationState?.();
          if(state?.known)lastTeachUnsafe=Boolean(state.teachActive||state.teachPending);
          else if(state?.teachActive||state?.teachPending)lastTeachUnsafe=true;
          teaching=lastTeachUnsafe;teachingUnknown=!state?.known&&!(state?.unavailable&&!state?.bound);
        }catch{teachingUnknown=true;}
      }
      const ui=runtime.ui,voice=runtime.voice;
      const busy=Boolean(moving||robotStateName==='MOVING'||ui?._motionWasActive||ui?.languageRobotState?.motionActive||ui?.lastRobotState?.stateName==='MOVING'||ui?.webGraspStatus?.active||ui?.activeDepthStatus?.active||ui?.activeDepthStatus?.phase==='uncertain'||ui?.fixedTcpDemoRequestId||byId('sec-dummy')?.dataset.running==='true'||voice?.recording||voice?.starting||teaching||teachingUnknown);
      return {page:current,busy,statusText:[mode.textContent,byId('hb-label')?.textContent].filter(Boolean).join(' · '),cameraText:byId('cam-label')?.textContent};
    }
    function installOnboarding(api){
      if(!guide&&api?.mountOnboarding){guide=api.mountOnboarding(doc,win,{go,getContext:onboardingContext,readJointPreview:()=>runtime.ui?.arm?.getJointAngles()});if(runtime.scene)guide.bindScene(runtime.scene);}
      return guide;
    }
    const account=win.ThirdHandAccountSettings?.mountAccountSettings(doc,win,{go,registerPage(id,page,button){pageNodes.set(id,page);navNodes.set(id,button);}});
    const shell = { go, selectControl, bindRuntime, refresh, installOnboarding, setAccountDataProvider:provider=>account?.setDataProvider(provider) };
    mounted.set(doc, shell); selectControl('joints'); go(win.location.hash.slice(1) || 'overview');
    return shell;
  }
  return { mountWorkspace };
});
