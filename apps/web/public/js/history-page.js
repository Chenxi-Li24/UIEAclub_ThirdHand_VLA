const byId=id=>document.getElementById(id),tr=text=>globalThis.ThirdHandI18n?.translate(text)||text;
async function start(){
  const session=globalThis.ThirdHandWorkspaceSession.createWorkspaceSession();let identity;
  try{identity=await session.load();}catch{location.assign('/login');return;}
  const preferences=globalThis.ThirdHandPreferences.createPreferenceClient({view:window,request:(path,body)=>session.request(path,body)});
  await preferences.hydrate(identity);preferences.apply(document);
  byId('history-language').value=document.documentElement.lang;
  byId('history-language').onchange=event=>preferences.choose({locale:event.target.value}).catch(()=>{});
  byId('history-theme').onclick=()=>preferences.choose({themeId:preferences.current().themeId==='light'?'dark':'light'}).catch(()=>{});
  preferences.subscribe(value=>preferences.apply(document,value));
  const dates=globalThis.ThirdHandHistoryDates;
  byId('history-timezone').textContent=dates.zoneLabel();
  function setRange(begin,end){for(const [prefix,value]of [['from',begin],['to',end]]){const parts=dates.localParts(value);byId(`history-${prefix}-date`).value=parts.date;byId(`history-${prefix}-time`).value=parts.time;}}
  const end=new Date();setRange(new Date(end.getTime()-86400000),end);
  let cursor=null,loadedFilter=null,replay=null,jobId=null,busy=false,arm=null,modelReady=false,loadedSamples=null,active=true;
  const filter=()=>({kind:byId('history-kind').value,...dates.range(byId('history-from-date').value,byId('history-from-time').value,byId('history-to-date').value,byId('history-to-time').value),...(byId('history-device').value.trim()?{deviceId:byId('history-device').value.trim()}:{})});
  const failure=error=>tr(({INVALID_INPUT:'Enter valid dates and times, with the end after the start and a range of up to 31 days.',INVALID_CURSOR:'This query expired. Load records again.',EXPORT_LIMIT_EXCEEDED:'Export limit exceeded. Narrow the date range.',EXPORT_BUSY:'Export queue is busy. Try again later.',EXPORT_SERVICE_UNAVAILABLE:'Export service is not configured.'})[error.code]||'The service is unavailable. Please try again later.');
  function refreshReplay(){
    replay=modelReady&&loadedSamples?globalThis.ThirdHandHistoryReplay.createHistoryReplay({armModel:arm,samples:loadedSamples}):null;
    byId('history-pose').disabled=byId('history-seek').disabled=!replay?.count;
    byId('history-seek').max=String(replay?.durationMs||0);byId('history-seek').value='0';
  }
  async function load(next=false){
    if(busy)return;busy=true;byId('history-status').textContent=tr('Loading records…');
    try{
      if(!next)loadedFilter=filter();
      const params=new URLSearchParams({...loadedFilter,limit:200,...(next&&cursor?{cursor}:{})}),page=await session.request('/api/v1/history?'+params);
      if(!active)return;cursor=page.nextCursor;byId('history-next').disabled=!cursor;byId('history-records').replaceChildren();
      for(const row of page.rows){
        const details=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');
        summary.textContent=`${row[page.timeBasis]||''} · ${row.sample_seq??row.command_id??row.event_code??row.id??''} · ${row.extra?.sourceMode||row.status||row.state||''}`;
        if(page.kind==='samples'&&Array.isArray(row.joint_position_rad))summary.textContent+=' · '+row.joint_position_rad.map((angle,index)=>`J${index+1} ${(angle*180/Math.PI).toFixed(2)}°`).join(' · ');
        pre.textContent=JSON.stringify(row,null,2);details.append(summary,pre);byId('history-records').append(details);
      }
      if(!page.rows.length){const empty=document.createElement('p');empty.className='history-empty';empty.textContent=tr('No records in this time range. Widen the dates or choose another device or record type.');byId('history-records').append(empty);}
      byId('history-status').textContent=`${page.rows.length} · ${tr('Records on this page')} · ${page.timeBasis} · UTC`;
      loadedSamples=page.kind==='samples'?page.rows:null;refreshReplay();
    }catch(error){byId('history-status').textContent=failure(error);}finally{busy=false;}
  }
  byId('history-filter').onsubmit=event=>{event.preventDefault();void load();};byId('history-next').onclick=()=>load(true);
  byId('history-last-day').onclick=()=>{const current=new Date();setRange(new Date(current.getTime()-86400000),current);void load();};
  byId('history-pose').onclick=()=>{
    if(!modelReady||!replay)return;const result=replay.seek(Number(byId('history-seek').value));
    byId('history-replay-status').textContent=`${tr(({measured:'Measured pose',gap:'Data gap · pose held',invalid:'Invalid or out-of-range sample',incompatible:'Version mismatch',end:'End of loaded page',empty:'No samples'})[result.state])}${result.capturedAt?' · '+result.capturedAt:''}${result.sourceMode?' · '+result.sourceMode:''}`;
  };
  byId('history-export').onclick=async()=>{
    byId('history-export').disabled=true;
    try{const job=await session.request('/api/v1/exports',{filter:filter(),format:byId('history-format').value});jobId=job.id;byId('history-export-check').disabled=false;byId('history-download').hidden=true;byId('history-export-status').textContent=tr('Export queued. Check its progress shortly.');}
    catch(error){byId('history-export-status').textContent=failure(error);}finally{byId('history-export').disabled=false;}
  };
  byId('history-export-check').onclick=async()=>{
    if(!jobId)return;
    try{const job=await session.request('/api/v1/exports/'+jobId);byId('history-export-status').textContent=job.errorCode?failure({code:job.errorCode}):`${tr('Export status')}: ${tr(job.status)} · ${job.rowCount??0}`;const link=byId('history-download');link.hidden=job.status!=='completed';if(!link.hidden)link.href='/api/v1/exports/'+jobId+'/download';}
    catch(error){byId('history-export-status').textContent=failure(error);}
  };
  session.startMonitoring();window.addEventListener('pagehide',()=>{active=false;session.close();preferences.dispose();},{once:true});
  // Records and exports are usable before any WebGL or model download succeeds.
  const firstLoad=load();
  void session.request('/api/v1/devices').then(result=>{if(!active)return;for(const device of result.devices){const option=document.createElement('option');option.value=device.id;option.textContent=device.name;byId('history-device').append(option);}}).catch(()=>{});
  void (async()=>{
    try{
      const [THREE,{OrbitControls},{STLLoader},{ColladaLoader}]=await Promise.all([import('three'),import('three/addons/controls/OrbitControls.js'),import('three/addons/loaders/STLLoader.js'),import('three/addons/loaders/ColladaLoader.js')]);
      if(!active)return;
      const {SceneManager,ArmModel}=globalThis.ThirdHandRobotViewer.createRobotViewer({THREE,OrbitControls,STLLoader,ColladaLoader,assetBase:'/control-assets'}),scene=new SceneManager(byId('history-three'));arm=new ArmModel(scene.scene);
      await arm.loadingPromise;await arm.geometryReady;if(!active)return;
      modelReady=true;arm.setJointAngles([0,90,-90,0,0,0]);scene.fitModel(arm.mount);refreshReplay();byId('history-replay-status').textContent=tr('Model replay sends no robot commands.');
    }catch{if(active)byId('history-replay-status').textContent=tr('The robot model could not be loaded.');}
  })();
  await firstLoad;
}
start().catch(()=>{byId('history-status').textContent=tr('The service is unavailable. Please try again later.');});
