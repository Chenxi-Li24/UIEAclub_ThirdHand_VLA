/* Presentation shell: retains the existing controls and never sends robot commands. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.ThirdHandWorkspace = api;
})(globalThis, function () {
  'use strict';
  const mounted = new WeakMap();
  const pages = [
    ['overview', '◫', 'Overview', 'Connection, tasks and tool state at a glance.'],
    ['control', '⌁', 'Manual control', 'Preview the model, then use the existing controls to send a target.'],
    ['vision', '◎', 'Vision tasks', 'Select a detected target and follow depth acquisition and grasp progress.'],
    ['calibration', '⊹', 'Calibration', 'Use the existing TCP wizard and its measured results.'],
    ['assistant', '✧', 'Assistant', 'Voice and text with the existing confirmation flow.'],
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
  function mountWorkspace(doc, win) {
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
      button.append(navIcon, element('span', { class: 'nav-label' }, label), element('span',{class:'nav-index','aria-hidden':'true'},String(index+1).padStart(2,'0')));
      button.addEventListener('click', () => go(id)); nav.appendChild(button); navNodes.set(id, button);
      const page = element('section', { id: `page-${id}`, class: 'workspace-page', 'aria-labelledby': `heading-${id}`, hidden: '' });
      const heading = element('div', { class: 'workspace-heading' });
      heading.append(element('div',{class:'page-eyebrow','aria-hidden':'true','data-i18n-skip':''},`THIRDHAND / 0${index+1}`), element('h1', { id: `heading-${id}`, tabindex: '-1' }, label), element('p', {}, detail));
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
      if (current === 'assistant' && (runtime.voice?.recording || runtime.voice?.starting)) {
        announce('Stop or cancel recording before changing pages.', '请先停止或取消录音，再切换页面。'); return false;
      }
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
      if (!pageNodes.has(id)) id = 'control';
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
        button.classList.toggle('active', key === id);
        if (key === id) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
      }
      if (id === 'calibration' && !frame) {
        frame = element('iframe', { id: 'workspace-calibration-frame', title: 'TCP calibration', src: 'tcp-calibration.html?embedded=1' });
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
      if (values.voice && current === 'assistant') values.voice.openPanel();
      if (values.scene) guide?.bindScene(values.scene);
      win.requestAnimationFrame(() => runtime.scene?._onResize());
      refresh();
    }
    const redirect = (node, page) => node?.addEventListener('click', event => {
      event.preventDefault(); event.stopImmediatePropagation(); go(page, { focus: true });
    }, true);
    redirect(byId('btn-voice-toggle'), 'assistant'); redirect(byId('voice-panel-close'), 'control');
    byId('voice-panel').addEventListener('keydown', event => {
      if (event.key !== 'Escape') return;
      event.preventDefault(); event.stopImmediatePropagation(); go('control', { focus: true });
    }, true);
    redirect(byId('btn-log-toggle'), 'system'); redirect(byId('btn-log-close'), 'control');
    redirect(doc.querySelector('a[href="tcp-calibration.html"]'), 'calibration');
    win.addEventListener('hashchange', () => go(win.location.hash.slice(1)));
    const observer = new win.MutationObserver(refresh);
    for (const id of [...summaries.map(item => item[2]), 'grasp-phase', 'active-depth-phase', 'cam-label', 'dummy-phase', 'workspace-web-status']) {
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
    mounted.set(doc, shell); selectControl('joints'); go(win.location.hash.slice(1) || 'control');
    return shell;
  }
  return { mountWorkspace };
});
