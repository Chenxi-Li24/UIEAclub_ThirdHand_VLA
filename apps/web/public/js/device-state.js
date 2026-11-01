/* Shared read-only measurements. Never imports the model or sends commands. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandDeviceState=api;})(globalThis,function(){
  'use strict';
  function createDeviceStateStore({request,view,document:doc,now=()=>view.performance.now()}){
    let devices=[],selected=null,value=null,receivedMono=0,baseAge=Infinity,error=null,api='unknown',busy=false,closed=false,timer=null,failures=0,phase=null;
    const listeners=new Set(),validVector=v=>Array.isArray(v)&&v.length===6&&v.every(Number.isFinite);
    function snapshot(){
      const ageMs=Number.isFinite(baseAge)?baseAge+Math.max(0,now()-receivedMono):null,sample=value?.sample??null;
      const fresh=value?.fresh===true&&value.epochCurrent===true&&ageMs!==null&&ageMs<=3000;
      let status='unknown';
      if(error||sample?.qualityFlags?.includes('SDK_READ_FAILED'))status='read_failed';
      else if(value?.gatewayOnline===false)status='disconnected';
      else if(sample&&!fresh)status='stale';
      else if(fresh&&sample.sdkConnected===false)status='disconnected';
      else if(fresh&&sample.sdkConnected===true)status=validVector(sample.jointPositionRad)?'connected':'waiting';
      else if(phase&&now()<phase.deadline)status='connecting';
      return {devices:[...devices],deviceId:selected,api,status,error,ageMs,fresh,sample,value};
    }
    function emit(){const state=snapshot();for(const fn of listeners)fn(state);}
    function receive(next,start){
      if(!next||next.schema!==1||next.purpose!=='display-only'||next.deviceId!==selected||typeof next.gatewayOnline!=='boolean'||typeof next.fresh!=='boolean'||
        (next.sample!==null&&(!Number.isFinite(next.ageMs)||next.ageMs<0||!Number.isSafeInteger(next.sequence))))throw Error('INVALID_DEVICE_STATE');
      const nextAge=next.ageMs===null?Infinity:next.ageMs+Math.max(0,now()-start);
      // A duplicate response, cache or clock adjustment cannot renew a sample.
      const duplicate=value&&value.context?.connectionId===next.context?.connectionId&&value.sequence===next.sequence;
      const older=value&&value.context?.connectionId===next.context?.connectionId&&next.sequence<value.sequence;
      if(older)throw Error('OUT_OF_ORDER_STATE');
      baseAge=duplicate?Math.max(nextAge,baseAge+Math.max(0,now()-receivedMono)):nextAge;
      value=next;receivedMono=now();error=null;api='online';failures=0;
      if(next.fresh&&next.sample?.sdkConnected===true)phase=null;
    }
    async function poll(){
      if(closed||busy||doc.visibilityState==='hidden')return;
      busy=true;view.clearTimeout(timer);
      try{
        if(!selected){const result=await request('/api/v1/devices');if(closed)return;devices=result.devices.filter(d=>d.controllable);selected=devices[0]?.id||null;api='online';}
        if(selected){const id=selected,start=now(),next=await request('/api/v1/devices/'+encodeURIComponent(id)+'/state');if(closed)return;if(id===selected)receive(next,start);}
        else {error=null;failures=0;}
      }catch{if(!closed){error='STATE_UNAVAILABLE';api='offline';failures++;}}
      finally{busy=false;if(!closed){emit();timer=view.setTimeout(poll,failures?Math.min(8000,1000*2**failures):1000);}}
    }
    const tick=view.setInterval(()=>{if(!closed)emit();},250),visible=()=>{if(doc.visibilityState!=='hidden')void poll();else view.clearTimeout(timer);};
    doc.addEventListener('visibilitychange',visible);
    return {snapshot,subscribe(fn){listeners.add(fn);fn(snapshot());return()=>listeners.delete(fn);},start:poll,
      updateDevices(rows){devices=rows.filter(d=>d.controllable);emit();},
      select(id){if(id===selected)return;if(!devices.some(d=>d.id===id))return;selected=id;value=null;baseAge=Infinity;phase=null;emit();void poll();},
      connecting(){phase={deadline:now()+15000};error=null;value=null;baseAge=Infinity;emit();return phase;},
      connectionSettled(attempt){if(phase===attempt){phase=null;emit();}},refresh:poll,
      close(){closed=true;view.clearTimeout(timer);view.clearInterval(tick);doc.removeEventListener('visibilitychange',visible);listeners.clear();}};
  }
  function mountDeviceState({document:doc,view,sessionClient,shell}){
    const tr=text=>view.ThirdHandI18n?.translate(text,doc.documentElement.lang)||text;
    const el=(tag,text,attrs={})=>{const n=doc.createElement(tag);if(text)n.textContent=tr(text);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);return n;};
    const card=el('section',null,{id:'device-real-state',class:'account-card device-real-state'}),heading=el('h2','Real robot state'),note=el('p','Measured feedback only. Model editing stays independent.'),select=el('select',null,{'aria-label':'Device',id:'state-device'}),status=el('p',null,{role:'status',id:'device-state-status'}),details=el('dl',null,{class:'device-state-values'}),stamp=el('p',null,{class:'device-state-time'});
    const labels=['J1','J2','J3','J4','J5','J6','Gripper position','Gripper width','Moving','Source','Gateway','Captured at','Received at','Flange position','Tool TCP','Joint velocity','Joint torque','Joint current','Joint temperature'];
    const fields=labels.map(label=>{const row=el('div'),name=el('dt',label),value=el('dd','--');row.append(name,value);details.append(row);return value;});
    card.append(heading,note,select,status,details,stamp);
    const page=doc.getElementById('page-system')||doc.getElementById('page-account-connections'),log=page.querySelector('#log-panel');
    if(log)log.before(card);else page.append(card);
    const feedback=el('section',null,{id:'model-real-feedback',class:'device-feedback-summary'}),summary=el('p');feedback.append(el('h3','Real robot feedback'),summary);(doc.querySelector('#sec-rt-angles .sec-body')||doc.getElementById('page-control')||doc.querySelector('#control-drawer .drawer-content')).prepend(feedback);
    const link=el('button','Devices',{id:'device-status-entry',type:'button',class:'action-btn action-secondary',title:tr('Devices & diagnostics'),'aria-label':tr('Devices & diagnostics')});link.addEventListener('click',()=>shell.go(doc.getElementById('page-system')?'system':'account-connections'));
    const legacy=doc.getElementById('conn-bar');if(legacy){legacy.hidden=true;legacy.after(link);}
    if(doc.documentElement.dataset.layout==='classic')doc.getElementById('btn-drawer-toggle').before(link);
    const store=createDeviceStateStore({request:(...args)=>sessionClient.request(...args),view,document:doc});
    const text=(node,value)=>{if(node&&node.textContent!==value)node.textContent=value;};
    const labelsByState={unknown:'Unknown',connecting:'Connecting',connected:'Connected · fresh',waiting:'Waiting for measured feedback',stale:'Data expired',disconnected:'Disconnected',read_failed:'State read failed'};
    const value=(number,scale=1,unit='')=>Number.isFinite(number)?(number*scale).toFixed(2)+unit:tr('Not provided');
    const vector=(numbers,scale,unit)=>Array.isArray(numbers)?numbers.map(n=>value(n,scale,unit)).join(' · '):tr('Not provided');
    const lights=view.ThirdHandStatusLights?.mountStatusLights(doc,view);
    function render(s){
      if(select.options.length!==s.devices.length||[...select.options].some((o,i)=>o.value!==s.devices[i]?.id)){select.replaceChildren();for(const d of s.devices)select.append(el('option',d.name,{value:d.id}));}
      select.value=s.deviceId||'';
      const sample=s.sample,measured=s.fresh&&sample?.sourceMode==='hardware',description=tr(labelsByState[s.status]);
      text(heading,tr(sample&&sample.sourceMode!=='hardware'?'Simulation/test feedback':'Real robot state'));
      text(status,description);status.dataset.state=s.status;feedback.dataset.state=s.status;
      text(summary,`${description} · ${tr(sample?.sourceMode==='hardware'?'Real robot':'No verified hardware feedback')}`);
      const joints=sample?.jointPositionRad;
      for(let i=0;i<6;i++){
        const degrees=value(joints?.[i],180/Math.PI,'°');text(fields[i],degrees);
        for(const id of ['sj'+(i+1),'rt-j'+(i+1)]){const node=doc.getElementById(id);text(node,`J${i+1}: ${degrees}${sample&&!s.fresh?' · '+tr('Historical'):''}`);if(node){node.dataset.fresh=String(measured);node.title=description;}}
      }
      const values=[value(sample?.gripper?.positionRatio,100,'%'),value(sample?.gripper?.widthM,1000,' mm'),typeof sample?.moving==='boolean'?tr(sample.moving?'Yes':'No'):tr('Unknown'),tr(sample?.sourceMode||'unknown'),tr(s.value?.gatewayOnline?'Online':'Offline'),sample?.capturedAt?new Date(sample.capturedAt).toLocaleString(doc.documentElement.lang):'--',s.value?.receivedAt?new Date(s.value.receivedAt).toLocaleString(doc.documentElement.lang):'--',vector(sample?.flangePositionM,1000,' mm'),vector(sample?.tcpPositionM,1000,' mm'),vector(sample?.jointVelocityRadS,180/Math.PI,' °/s'),vector(sample?.jointTorqueNm,1,' N·m'),vector(sample?.jointCurrentA,1,' A'),vector(sample?.jointTemperatureC,1,' °C')];
      values.forEach((v,i)=>text(fields[i+6],v));
      text(doc.getElementById('gripper-actual'),`${values[0]} · ${values[1]}${sample&&!s.fresh?' · '+tr('Historical'):''}`);
      text(stamp,s.ageMs===null?tr('No measured samples yet.'):`${tr('Sample age')}: ${(s.ageMs/1000).toFixed(1)} s · ${tr('Local time zone')}: ${Intl.DateTimeFormat().resolvedOptions().timeZone}`);
      lights?.setReadOnlyState?.({status:s.status,api:s.api});text(doc.getElementById('conn-ip'),`${tr('Ubuntu device gateway')} · ${tr(s.value?.gatewayOnline?'Online':s.value?'Offline':'Unknown')}`);
      const dot=doc.getElementById('conn-dot');if(dot){dot.classList.toggle('connected',s.value?.gatewayOnline===true);dot.title=tr(s.value?.gatewayOnline?'Online':'Unknown');}
    }
    const unsubscribe=store.subscribe(render),language=new view.MutationObserver(()=>render(store.snapshot()));language.observe(doc.documentElement,{attributes:true,attributeFilter:['lang']});
    select.addEventListener('change',()=>store.select(select.value));void store.start();
    return {store,dispose(){unsubscribe();language.disconnect();store.close();card.remove();feedback.remove();}};
  }
  return {createDeviceStateStore,mountDeviceState};
});
