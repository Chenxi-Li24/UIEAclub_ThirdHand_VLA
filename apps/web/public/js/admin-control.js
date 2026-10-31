/* Explicit live-device actions. Model editing never calls this client. */
(function(root,factory){const api=factory(root);if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandAdminControl=api;})(globalThis,function(root){
  'use strict';
  const fail=code=>Object.assign(new Error(code),{code});
  function createAdminControlClient({view=root,identity,sessionClient,onChange=()=>{}}){
    let socket=null,connectionId=null,clientInstanceId=null,lease=null,warning=null,deviceId=null,opening=null,resolveOpen=null,rejectOpen=null,timeout=null,lastChallenge=0,lastResponse=0,lastFresh=-Infinity;
    const now=()=>view.performance?.now()??Date.now();
    const admin=()=>{if(identity?.role!=='admin'||identity.mode!=='admin')throw fail('FORBIDDEN');};
    const state=()=>({connected:!!connectionId,lease:lease?{...lease}:null,deviceId,requiresConfirmation:!!warning});
    function changed(){onChange(state());}
    function disconnected(){if(timeout)root.clearTimeout(timeout);timeout=null;socket=null;connectionId=null;lease=null;warning=null;lastFresh=-Infinity;rejectOpen?.(fail('CONTROL_DISCONNECTED'));resolveOpen=rejectOpen=null;opening=null;changed();}
    function close(){const previous=socket;disconnected();previous?.close();}
    function binding(){admin();if(!connectionId||now()-lastFresh>=500)throw fail('BROWSER_STALE');return {clientInstanceId,connectionId};}
    const api={state,
      async open(){
        admin();if(connectionId&&now()-lastFresh<500)return binding();if(opening)return opening;
        if(socket)close();
        const protocol=view.location.protocol==='https:'?'wss:':/^localhost(?::|$)|^127\.0\.0\.1(?::|$)/.test(view.location.host)?'ws:':null;
        if(!protocol)throw fail('HTTPS_REQUIRED');
        clientInstanceId=clientInstanceId||view.crypto.randomUUID();lastChallenge=lastResponse=0;
        opening=new Promise((resolve,reject)=>{resolveOpen=resolve;rejectOpen=reject;});
        socket=new view.WebSocket(`${protocol}//${view.location.host}/stream/v1/control`);
        const current=socket;
        timeout=root.setTimeout(()=>{if(socket===current)close();},4000);timeout.unref?.();
        current.onopen=()=>{if(socket===current)current.send(JSON.stringify({type:'bind',clientInstanceId,csrfToken:identity.csrfToken}));};
        current.onmessage=event=>{
          if(socket!==current)return;
          try{
            const value=JSON.parse(event.data);
            if(value.type==='bound'&&!connectionId&&typeof value.connectionId==='string')connectionId=value.connectionId;
            else if(value.type==='challenge'&&value.connectionId===connectionId&&Number.isSafeInteger(value.sequence)&&value.sequence>lastChallenge&&typeof value.nonce==='string'&&/^[A-Za-z0-9_-]{43}$/.test(value.nonce)){
              lastChallenge=value.sequence;lastResponse=value.sequence;current.send(JSON.stringify({type:'response',connectionId,sequence:value.sequence,nonce:value.nonce}));
            }else if(value.type==='fresh'&&value.connectionId===connectionId&&value.sequence===lastResponse){
              const first=!!resolveOpen;lastFresh=now();if(timeout)root.clearTimeout(timeout);timeout=null;resolveOpen?.(binding());resolveOpen=rejectOpen=null;opening=null;if(first)changed();
            }else throw fail('CONTROL_PROTOCOL_ERROR');
          }catch{close();}
        };
        current.onclose=()=>{if(socket===current)disconnected();};current.onerror=()=>{if(socket===current)close();};
        return opening;
      },
      async acquire(id){admin();await api.open();deviceId=id;try{const result=await sessionClient.request('/api/v1/control/lease',{deviceId,...binding()});if(result.state!=='active')throw fail('LEASE_UNCONFIRMED');lease=result;changed();return result;}catch(error){if(error.code!=='LEASE_BUSY')close();throw error;}},
      async command(opcode,parameters){admin();if(!lease)throw fail('LEASE_REQUIRED');try{const context=binding();const result=await sessionClient.request('/api/v1/control/command',{deviceId,...context,leaseId:lease.id,commandId:view.crypto.randomUUID(),opcode,parameters});if(result.state==='unknown')throw fail('COMMAND_RESULT_UNKNOWN');if(opcode==='disconnect'&&result.state==='stopped')close();return result;}catch(error){close();if(['FORBIDDEN','BROWSER_STALE','LEASE_CHANGED','LEASE_REQUIRED','INVALID_INPUT','COMMAND_ID_CONFLICT','CONTROL_READINESS_REQUIRED'].includes(error.code))throw error;throw fail('COMMAND_RESULT_UNKNOWN');}},
      async stop(id=deviceId){admin();if(!id)throw fail('DEVICE_UNAVAILABLE');const result=await sessionClient.request('/api/v1/control/stop',{deviceId:id,...binding()});lease=null;warning=null;changed();return result;},
      async prepareTakeover(id){admin();await api.open();deviceId=id;const status=await sessionClient.request(`/api/v1/control/status?deviceId=${encodeURIComponent(id)}`);if(status.lease?.state!=='active')throw fail('LEASE_CHANGED');warning=await sessionClient.request('/api/v1/control/takeover-request',{deviceId,...binding(),targetEpoch:status.lease.leaseEpoch});changed();return {...warning};},
      cancelTakeover(){warning=null;changed();},
      async confirmTakeover(){admin();if(!warning)throw fail('TAKEOVER_INVALID');const pending=warning;warning=null;try{const result=await sessionClient.request('/api/v1/control/takeover-confirm',{...binding(),requestId:pending.requestId,nonce:pending.nonce});if(result.state!=='active')throw fail('LEASE_UNCONFIRMED');lease=result;changed();return result;}catch(error){close();throw error;}},
      close
    };
    return api;
  }
  function mountAdminControl({document:doc,view=root,identity,sessionClient,arm}){
    if(identity.role!=='admin'||identity.mode!=='admin')return {dispose(){}};
    const tr=text=>view.ThirdHandI18n?.translate(text,doc.documentElement.lang)||text;
    const el=(tag,text,attributes={})=>{const node=doc.createElement(tag);if(text)node.textContent=tr(text);for(const [key,value]of Object.entries(attributes))node.setAttribute(key,value);return node;};
    const section=el('section',null,{class:'cloud-live-control',id:'cloud-live-control'}),title=el('h3','Live robot control'),status=el('p','Real robot control is unavailable',{role:'status'}),select=el('select',null,{'aria-label':tr('Device')}),buttons=[],warningBox=el('div',null,{role:'alertdialog','aria-label':tr('Confirm control takeover')});warningBox.hidden=true;
    const telemetry=el('pre',null,{'aria-live':'polite',class:'cloud-live-telemetry'});let devices=[],telemetryBusy=false,disposed=false;
    section.append(title,el('p','Model sliders and sequences remain independent of the live robot.'),status,select,telemetry);
    const isReadOnly=()=>devices.find(value=>value.id===select.value)?.readOnly===true;
    const client=createAdminControlClient({view,identity,sessionClient,onChange:state=>{for(const button of buttons)button.disabled=!state.lease||button.dataset.motion==='true'&&isReadOnly();select.disabled=!!state.lease;if(state.lease)select.value=state.deviceId;status.textContent=tr(isReadOnly()?'This device permits SDK connection and state reading only.':state.lease?'You hold live robot control.':'No live control lease.');}});
    const message=error=>{status.textContent=tr(({LEASE_BUSY:'Another operator holds control.',STOP_UNCONFIRMED:'Stop is unconfirmed. Control was not transferred.',COMMAND_RESULT_UNKNOWN:'The command result is unknown. Check device state before requesting control again.',CONTROL_READINESS_REQUIRED:'Live video, tutorial and device checks must pass first.',BROWSER_STALE:'Control connection is stale. Request control again.',LEASE_REQUIRED:'Request control before sending a live command.',DEVICE_UNAVAILABLE:'The device is unavailable.'})[error?.code]||'Real robot control is unavailable');};
    const button=(label,action,{requiresLease=false}={})=>{const node=el('button',label,{type:'button',class:'action-btn action-secondary'});node.disabled=requiresLease;node.addEventListener('click',()=>Promise.resolve().then(action).then(result=>{const text=({completed:'Command completed.',accepted:'Command accepted.',started:'Command started.',rejected:'The device rejected the command.',failed:'The command failed.'})[result?.state];if(text)status.textContent=tr(text);}).catch(message));section.append(node);if(requiresLease)buttons.push(node);return node;};
    async function loadTelemetry(){if(telemetryBusy||disposed||!select.value||doc.visibilityState==='hidden')return;telemetryBusy=true;try{const result=await sessionClient.request('/api/v1/devices/'+encodeURIComponent(select.value)+'/telemetry');if(disposed)return;const s=result.sample;if(!s){telemetry.textContent=tr('No measured samples yet.');return;}const age=Math.max(0,Date.parse(result.serverTime)-Date.parse(s.received_at),Date.parse(result.serverTime)-Date.parse(s.captured_at),s.state_age_ms||0);telemetry.textContent=`${tr(age>3000?'Historical state · not live':'Latest stored state')} · ${s.source_mode||'unknown'}\nSDK: ${s.sdk_connected} · ${tr('Moving')}: ${s.moving}\n${s.joint_position_rad.map((value,index)=>`J${index+1}: ${(value*180/Math.PI).toFixed(2)}°`).join(' · ')}\n${tr('Captured at')}: ${s.captured_at}\n${tr('Stored at')}: ${s.received_at}`;}catch{if(!disposed)telemetry.textContent=tr('Live-state mirroring is unavailable');}finally{telemetryBusy=false;}}
    button('Load devices',async()=>{if(client.state().lease)return;const result=await sessionClient.request('/api/v1/devices');devices=result.devices.filter(value=>value.controllable===true);select.replaceChildren();for(const device of devices){const option=el('option',device.name,{value:device.id});select.append(option);}status.textContent=tr(isReadOnly()?'This device permits SDK connection and state reading only.':devices.length?'Select a device, then request control.':'No devices are available.');await loadTelemetry();});
    function selected(){if(!select.value)throw fail('DEVICE_UNAVAILABLE');return select.value;}
    button('Request control',async()=>{if(client.state().lease)return;try{await client.acquire(selected());}catch(error){if(error.code!=='LEASE_BUSY')throw error;const warning=await client.prepareTakeover(selected());warningBox.replaceChildren(el('p',`${tr('Continuing will stop the current operator before control can transfer.')} ${warning.holderName||''}`));const confirm=el('button','Confirm takeover',{type:'button',class:'action-btn'}),cancel=el('button','Cancel',{type:'button',class:'action-btn action-secondary'});confirm.addEventListener('click',()=>{warningBox.hidden=true;client.confirmTakeover().catch(message);});cancel.addEventListener('click',()=>{warningBox.hidden=true;client.cancelTakeover();});warningBox.append(confirm,cancel);warningBox.hidden=false;confirm.focus();}});
    button('Connect SDK',()=>client.command('connect',{}),{requiresLease:true});
    button('Disconnect SDK',()=>client.command('disconnect',{}),{requiresLease:true});
    const motionButton=button('Send model pose to robot',()=>client.command('move_joint',{joints:arm.getJointAngles()}),{requiresLease:true});motionButton.dataset.motion='true';
    button('Software stop',async()=>{const id=selected();await client.open();const result=await client.stop(id);status.textContent=tr(result.state==='stopped'?(isReadOnly()?'The SDK connection was released.':'The device confirmed software stop.'):'Stop is unconfirmed. Control was not transferred.');});
    button('Release control',async()=>{const result=await client.stop();client.close();if(result.state!=='stopped')throw fail('STOP_UNCONFIRMED');},{requiresLease:true});
    section.append(warningBox);(doc.getElementById('page-control')||doc.getElementById('control-drawer')).append(section);
    const hidden=()=>{if(doc.visibilityState==='hidden')client.close();};doc.addEventListener('visibilitychange',hidden);
    select.addEventListener('change',()=>{telemetry.textContent='';void loadTelemetry();});const telemetryTimer=root.setInterval(()=>void loadTelemetry(),2000);telemetryTimer.unref?.();
    return {client,dispose(){disposed=true;root.clearInterval(telemetryTimer);doc.removeEventListener('visibilitychange',hidden);client.close();section.remove();}};
  }
  return {createAdminControlClient,mountAdminControl};
});
