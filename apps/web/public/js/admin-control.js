/* Explicit live-device actions. Model editing never calls this client. */
(function(root,factory){const api=factory(root);if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandAdminControl=api;})(globalThis,function(root){
  'use strict';
  const fail=code=>Object.assign(new Error(code),{code});
  function createAdminControlClient({view=root,identity,sessionClient,onChange=()=>{}}){
    let socket=null,connectionId=null,clientInstanceId=null,lease=null,warning=null,deviceId=null,opening=null,resolveOpen=null,rejectOpen=null,timeout=null,lastChallenge=0,lastResponse=0,lastAck=0,lastFresh=-Infinity,disconnectReason=null;
    const responses=new Map();let acquiring=false;
    const now=()=>view.performance?.now()??Date.now();
    const canAdmin=()=>identity?.role==='admin'&&identity.mode==='admin';
    const connection=()=>{if(!['admin','observer'].includes(identity?.role)||!['observe','admin'].includes(identity?.mode)||identity.mode==='admin'&&!canAdmin())throw fail('FORBIDDEN');};
    const admin=()=>{if(identity?.role!=='admin'||identity.mode!=='admin')throw fail('FORBIDDEN');};
    const state=()=>({connected:!!connectionId,lease:lease?{...lease}:null,deviceId,requiresConfirmation:!!warning,disconnectReason});
    function changed(){onChange(state());}
    function disconnected(reason=null){if(timeout)root.clearTimeout(timeout);timeout=null;socket=null;connectionId=null;lease=null;warning=null;lastFresh=-Infinity;responses.clear();disconnectReason=reason;rejectOpen?.(fail(reason||'CONTROL_DISCONNECTED'));resolveOpen=rejectOpen=null;opening=null;changed();}
    function close(reason=null){const previous=socket;disconnected(reason);previous?.close();}
    function binding(){connection();if(!connectionId||now()-lastFresh>=500)throw fail('BROWSER_STALE');return {clientInstanceId,connectionId};}
    const api={state,
      async open(){
        connection();if(connectionId&&now()-lastFresh<500)return binding();if(opening)return opening;
        if(socket)close();
        const protocol=view.location.protocol==='https:'?'wss:':/^localhost(?::|$)|^127\.0\.0\.1(?::|$)/.test(view.location.host)?'ws:':null;
        if(!protocol)throw fail('HTTPS_REQUIRED');
        clientInstanceId=clientInstanceId||view.crypto.randomUUID();lastChallenge=lastResponse=lastAck=0;responses.clear();disconnectReason=null;
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
              lastChallenge=value.sequence;lastResponse=value.sequence;
              for(const [sequence,sentAt]of responses)if(now()-sentAt>=500)responses.delete(sequence);
              responses.set(value.sequence,now());current.send(JSON.stringify({type:'response',connectionId,sequence:value.sequence,nonce:value.nonce}));
            }else if(value.type==='fresh'&&value.connectionId===connectionId&&Number.isSafeInteger(value.sequence)&&value.sequence>lastAck&&value.sequence<=lastResponse&&responses.has(value.sequence)){
              // Responses can be acknowledged after a later challenge arrives.
              // Accept ordered, actually-sent ACKs without extending their age.
              const sentAt=responses.get(value.sequence);if(now()-sentAt>=500)throw fail('BROWSER_STALE');
              lastAck=value.sequence;for(const sequence of responses.keys())if(sequence<=lastAck)responses.delete(sequence);
              const first=!!resolveOpen;lastFresh=sentAt;if(timeout)root.clearTimeout(timeout);timeout=null;resolveOpen?.(binding());resolveOpen=rejectOpen=null;opening=null;if(first)changed();
            }else throw fail('CONTROL_PROTOCOL_ERROR');
          }catch(error){close(error.code||'CONTROL_PROTOCOL_ERROR');}
        };
        current.onclose=event=>{if(socket===current)disconnected(event?.reason==='Control response expired'?'BROWSER_STALE':'CONTROL_DISCONNECTED');};current.onerror=()=>{if(socket===current)close('CONTROL_DISCONNECTED');};
        return opening;
      },
      async acquire(id){connection();if(acquiring)throw fail('REQUEST_IN_PROGRESS');acquiring=true;try{await api.open();deviceId=id;const requested=binding();const result=await sessionClient.request('/api/v1/control/lease',{deviceId,...requested});if(result.state!=='active')throw fail('LEASE_UNCONFIRMED');if(binding().connectionId!==requested.connectionId)throw fail('CONTROL_DISCONNECTED');lease=result;changed();return result;}catch(error){if(error.code!=='LEASE_BUSY')close(error.code);throw error;}finally{acquiring=false;}},
      async command(opcode,parameters){if(['connect','disconnect'].includes(opcode))connection();else admin();if(!lease)throw fail('LEASE_REQUIRED');try{const context=binding();const result=await sessionClient.request('/api/v1/control/command',{deviceId,...context,leaseId:lease.id,commandId:view.crypto.randomUUID(),opcode,parameters});if(result.state==='unknown')throw fail('COMMAND_RESULT_UNKNOWN');if(opcode==='disconnect'&&result.state==='stopped')close();return result;}catch(error){close();if(['FORBIDDEN','BROWSER_STALE','LEASE_CHANGED','LEASE_REQUIRED','INVALID_INPUT','COMMAND_ID_CONFLICT','CONTROL_READINESS_REQUIRED'].includes(error.code))throw error;throw fail('COMMAND_RESULT_UNKNOWN');}},
      async stop(id=deviceId){admin();if(!id)throw fail('DEVICE_UNAVAILABLE');const result=await sessionClient.request('/api/v1/control/stop',{deviceId:id,...binding()});lease=null;warning=null;changed();return result;},
      async prepareTakeover(id){admin();await api.open();deviceId=id;const status=await sessionClient.request(`/api/v1/control/status?deviceId=${encodeURIComponent(id)}`);if(status.lease?.state!=='active')throw fail('LEASE_CHANGED');warning=await sessionClient.request('/api/v1/control/takeover-request',{deviceId,...binding(),targetEpoch:status.lease.leaseEpoch});changed();return {...warning};},
      cancelTakeover(){warning=null;changed();},
      async confirmTakeover(){admin();if(!warning)throw fail('TAKEOVER_INVALID');const pending=warning;warning=null;try{const result=await sessionClient.request('/api/v1/control/takeover-confirm',{...binding(),requestId:pending.requestId,nonce:pending.nonce});if(result.state!=='active')throw fail('LEASE_UNCONFIRMED');lease=result;changed();return result;}catch(error){close();throw error;}},
      close
    };
    return api;
  }
  function mountAdminControl({document:doc,view=root,identity,sessionClient,stateStore}){
    if(!['admin','observer'].includes(identity?.role)||!['observe','admin'].includes(identity?.mode))return {dispose(){}};
    const isAdmin=identity.role==='admin'&&identity.mode==='admin';
    const tr=text=>view.ThirdHandI18n?.translate(text,doc.documentElement.lang)||text;
    const el=(tag,text,attributes={})=>{const node=doc.createElement(tag);if(text)node.textContent=tr(text);for(const [key,value]of Object.entries(attributes))node.setAttribute(key,value);return node;};
    const section=el('section',null,{class:'cloud-live-control',id:'cloud-live-control'}),title=el('h3','SDK connection'),status=el('p','Real robot control is unavailable',{role:'status'}),select=el('select',null,{'aria-label':tr('Device')}),buttons=[],warningBox=el('div',null,{role:'alertdialog','aria-label':tr('Confirm control takeover')});warningBox.hidden=true;
    const telemetry=el('pre',null,{'aria-live':'polite',class:'cloud-live-telemetry'});let devices=[],telemetryBusy=false,disposed=false,cancelSdkConfirmation=null,requesting=false,requestButton=null;
    section.append(title,el('p','Connecting the SDK enables motors and may close the gripper. Only administrators can send motion commands.'),el('p','Model sliders and sequences remain independent of the live robot.'),status,select,telemetry);
    const isReadOnly=()=>devices.find(value=>value.id===select.value)?.readOnly===true;
    const client=createAdminControlClient({view,identity,sessionClient,onChange:state=>{if(!state.lease)cancelSdkConfirmation?.();for(const button of buttons)button.disabled=button.dataset.pending==='true'||!state.lease||button.dataset.motion==='true'&&isReadOnly();select.disabled=requesting||!!state.lease;if(requestButton)requestButton.disabled=requesting||!!state.lease;if(state.lease)select.value=state.deviceId;status.textContent=tr(requesting&&!state.lease&&!state.disconnectReason?'Request sent. Checking browser and device authorization; the SDK is not being initialized.':state.lease?(isReadOnly()?'SDK authorization is active. Choose Connect SDK to initialize.':'You hold live robot control.'):state.disconnectReason?'Control connection is stale. Request control again.':'No live control lease.');}});
    const message=error=>{status.textContent=tr(({LEASE_UNCONFIRMED:'The device did not accept SDK authorization. The SDK was not initialized. Request again after the connection issue is resolved.',REQUEST_TIMEOUT:'The request timed out. Check device state before retrying.',REQUEST_IN_PROGRESS:'An authorization request is already in progress.',FORBIDDEN:'This session is not allowed to request this operation.',LEASE_BUSY:'Another operator holds control.',STOP_UNCONFIRMED:'Stop is unconfirmed. Control was not transferred.',COMMAND_RESULT_UNKNOWN:'The command result is unknown. Check device state before requesting control again.',CONTROL_READINESS_REQUIRED:'Live video, tutorial and device checks must pass first.',BROWSER_STALE:'Control connection is stale. Request control again.',CONTROL_DISCONNECTED:'Control connection is stale. Request control again.',CONTROL_PROTOCOL_ERROR:'Control connection is stale. Request control again.',LEASE_REQUIRED:'Request control before sending a live command.',DEVICE_UNAVAILABLE:'The device is unavailable.'})[error?.code]||'Real robot control is unavailable');};
    const button=(label,action,{requiresLease=false,progress=null}={})=>{const node=el('button',label,{type:'button',class:'action-btn action-secondary'});node.disabled=requiresLease;let pending=false;
      node.addEventListener('click',()=>{if(pending||node.disabled||disposed)return;pending=true;node.dataset.pending='true';node.disabled=true;node.setAttribute('aria-busy','true');
        if(progress){requesting=true;select.disabled=true;node.textContent=tr('Requesting authorization…');status.textContent=tr(progress);}
        Promise.resolve().then(action).then(result=>{const text=({completed:'Command completed.',accepted:'Command accepted.',started:'Command started.',rejected:'The device rejected the command.',failed:'The command failed.'})[result?.state];if(text)status.textContent=tr(text);}).catch(message).finally(()=>{pending=false;node.dataset.pending='false';node.removeAttribute('aria-busy');node.textContent=tr(label);node.disabled=requiresLease?!client.state().lease:progress?!!client.state().lease:false;if(progress){requesting=false;select.disabled=!!client.state().lease;}});
      });section.append(node);if(requiresLease)buttons.push(node);return node;};
    async function loadTelemetry(){await stateStore?.refresh();}
    button('Load devices',async()=>{if(requesting||client.state().lease)return;const result=await sessionClient.request('/api/v1/devices');stateStore?.updateDevices(result.devices);devices=result.devices.filter(value=>value.controllable===true&&value.readOnly===true);select.replaceChildren();for(const device of devices){const option=el('option',device.name,{value:device.id});select.append(option);}status.textContent=tr(isReadOnly()?'This device permits SDK connection and state reading only.':devices.length?'Select a device, then request control.':'No devices are available.');stateStore?.select(select.value);await loadTelemetry();});
    function selected(){if(!select.value)throw fail('DEVICE_UNAVAILABLE');return select.value;}
    requestButton=button(isAdmin?'Request control':'Request SDK connection',async()=>{if(client.state().lease)return;try{await client.acquire(selected());}catch(error){if(error.code!=='LEASE_BUSY'||!isAdmin)throw error;const warning=await client.prepareTakeover(selected());warningBox.replaceChildren(el('p',`${tr('Continuing will stop the current operator before control can transfer.')} ${warning.holderName||''}`));const confirm=el('button','Confirm takeover',{type:'button',class:'action-btn'}),cancel=el('button','Cancel',{type:'button',class:'action-btn action-secondary'});confirm.addEventListener('click',()=>{warningBox.hidden=true;client.confirmTakeover().catch(message);});cancel.addEventListener('click',()=>{warningBox.hidden=true;client.cancelTakeover();});warningBox.append(confirm,cancel);warningBox.hidden=false;confirm.focus();}},{progress:'Request sent. Checking browser and device authorization; the SDK is not being initialized.'});
    function confirmSdkConnection(){
      // Native confirm() blocks WebSocket callbacks, expiring the safety lease
      // while the user reads it. DOM controls keep the heartbeat running.
      cancelSdkConfirmation?.();
      return new Promise(resolve=>{
        const confirm=el('button','Connect SDK',{type:'button',class:'action-btn'}),cancel=el('button','Cancel',{type:'button',class:'action-btn action-secondary'});
        let done=false;
        const finish=accepted=>{if(done)return;done=true;confirm.disabled=cancel.disabled=true;warningBox.hidden=true;cancelSdkConfirmation=null;resolve(accepted);};
        cancelSdkConfirmation=()=>finish(false);
        warningBox.setAttribute('aria-label',tr('SDK connection'));
        warningBox.replaceChildren(el('p','Connecting the SDK enables motors and closes the configured gripper. Keep the workspace clear. Continue?'),confirm,cancel);
        confirm.addEventListener('click',()=>finish(true));cancel.addEventListener('click',()=>finish(false));
        warningBox.hidden=false;confirm.focus();
      });
    }
    button('Connect SDK',async()=>{if(!await confirmSdkConnection())return;const attempt=stateStore?.connecting();try{return await client.command('connect',{});}finally{stateStore?.connectionSettled(attempt);void stateStore?.refresh();}},{requiresLease:true});
    button('Disconnect SDK',()=>client.command('disconnect',{}),{requiresLease:true});
    if(isAdmin)button('Software stop',async()=>{const id=selected();await client.open();const result=await client.stop(id);status.textContent=tr(result.state==='stopped'?(isReadOnly()?'The SDK connection was released.':'The device confirmed software stop.'):'Stop is unconfirmed. Control was not transferred.');});
    button(isAdmin?'Release control':'Release SDK connection',async()=>{if(!isAdmin)return client.command('disconnect',{});const result=await client.stop();client.close();if(result.state!=='stopped')throw fail('STOP_UNCONFIRMED');},{requiresLease:true});
    section.append(warningBox);
    const page=doc.getElementById('page-system')||doc.getElementById('page-account-connections'),anchor=page.querySelector('#device-real-state')||page.querySelector('#log-panel');
    if(anchor)anchor.before(section);else page.append(section);
    const hidden=()=>{if(doc.visibilityState==='hidden')client.close();};doc.addEventListener('visibilitychange',hidden);
    const unsubscribe=stateStore?.subscribe(state=>{
      if(!requesting&&!client.state().lease){
        const next=state.devices.filter(d=>d.readOnly===true);
        if(JSON.stringify(next)!==JSON.stringify(devices)){devices=next;select.replaceChildren();for(const device of devices)select.append(el('option',device.name,{value:device.id}));}
        if(devices.some(d=>d.id===state.deviceId))select.value=state.deviceId;
      }
      telemetry.textContent=tr('This device permits SDK connection and state reading only.');
    });
    select.addEventListener('change',()=>stateStore?.select(select.value));
    return {client,dispose(){disposed=true;cancelSdkConfirmation?.();unsubscribe?.();doc.removeEventListener('visibilitychange',hidden);client.close();section.remove();}};
  }  return {createAdminControlClient,mountAdminControl};
});
