/* Subscribe-only camera viewing. No microphone, SDK or robot command adapter. */
(function(root,factory){const api=factory(root);if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandCameraView=api;})(globalThis,function(root){
  'use strict';
  function createCameraClient({view=root,sessionClient,video,onChange=()=>{},createRoom}){
    let room=null,grant=null,worker=null,track=null,frameCallback=null,epoch=0,opening=false,acknowledging=false,lastAck=-Infinity,state='unavailable';
    let intent=null,retryTimer=null,activeAttempt=null,progressAt=null,disposed=false,pendingViews=0,cleanupTail=Promise.resolve(true);
    const pendingRooms=new Set(),pendingGrants=new Map(),delays=[1000,2000,4000,8000,8000,8000];
    const setTimer=(view.setTimeout||root.setTimeout).bind(view),clearTimer=(view.clearTimeout||root.clearTimeout).bind(view);
    const now=()=>view.performance?.now()??Date.now();
    const changed=value=>{state=value;onChange(value);};
    const visible=()=>view.document?.visibilityState!=='hidden';
    const wanted=value=>!disposed&&intent===value&&visible();
    const terminal=error=>['UNAUTHENTICATED','FORBIDDEN','SESSION_CHANGED','INVALID_INPUT','HTTPS_REQUIRED','MEDIA_ORIGIN_INVALID','CAMERA_TIMEOUT'].includes(error?.code);
    const failure=code=>Object.assign(Error(code),{code});
    function timed(promise,milliseconds){let timer;return Promise.race([Promise.resolve(promise),new Promise((_,reject)=>{timer=setTimer(()=>reject(failure('CAMERA_TIMEOUT')),milliseconds);})]).finally(()=>clearTimer(timer));}
    function clearIntent(){intent=null;if(retryTimer!==null)clearTimer(retryTimer);retryTimer=null;}
    function detach(){if(frameCallback!==null)video.cancelVideoFrameCallback?.(frameCallback);frameCallback=null;track?.detach(video);track=null;video.pause?.();video.srcObject=null;}
    function cleanupMedia(){
      // Reserve the epoch before the first await: a concurrent Close must cancel
      // both pending cleanup and a media/view response that has not arrived yet.
      epoch++;if(room)pendingRooms.add(room);if(grant)pendingGrants.set(grant.viewerId,grant);room=grant=null;progressAt=null;acknowledging=false;lastAck=-Infinity;detach();worker?.terminate();worker=null;
      const release=async()=>{
        const results=await Promise.allSettled([
          ...[...pendingRooms].map(async old=>{await timed(Promise.resolve().then(()=>old.disconnect()),5000);pendingRooms.delete(old);}),
          ...[...pendingGrants].map(async([id])=>{const result=await timed(sessionClient.request('/api/v1/media/close',{viewerId:id}),5000);if(result?.closed!==true)throw failure('MEDIA_CLOSE_UNCONFIRMED');pendingGrants.delete(id);})
        ]);
        return results.every(result=>result.status==='fulfilled');
      };
      cleanupTail=cleanupTail.then(release,release);return cleanupTail;
    }
    async function close(){clearIntent();const cleanup=cleanupMedia();changed('unavailable');await cleanup;}
    function recover(value,current){
      if(current!==epoch||!wanted(value))return;
      const oldAttempt=activeAttempt,cleanup=cleanupMedia();
      if(value.retries>=delays.length){clearIntent();changed('unavailable');return;}
      const delay=delays[value.retries++],recoveryEpoch=epoch;changed('connecting');
      retryTimer=setTimer(async()=>{
        retryTimer=null;const released=await cleanup;
        if(!released){if(intent===value){clearIntent();changed('unavailable');}return;}
        await oldAttempt?.catch(()=>{});
        if(!wanted(value)||recoveryEpoch!==epoch)return;
        void begin(value,true).catch(()=>{});
      },delay);
    }
    async function run(value,retrying){
      const cleanup=cleanupMedia(),current=epoch;
      try{
        const released=await cleanup;if(current!==epoch||!wanted(value))return;
        if(!released)throw failure('MEDIA_CLOSE_UNCONFIRMED');
        if(retrying){
          const identity=await timed(sessionClient.load?sessionClient.load():sessionClient.request('/api/v1/session'),12000);
          if(current!==epoch||!wanted(value))return;
          if(value.identity&&['userId','sessionId','mode'].some(key=>identity?.[key]!==value.identity[key]))throw failure('SESSION_CHANGED');
        }
        pendingViews++;
        const issued=await timed(Promise.resolve().then(()=>sessionClient.request('/api/v1/media/view',{deviceId:value.deviceId})).then(async result=>{
          if(current!==epoch||!wanted(value)){pendingGrants.set(result.viewerId,result);await cleanupMedia();return null;}return result;
        }).finally(()=>{pendingViews--;}),12000);
        if(!issued||current!==epoch||!wanted(value))return;
        grant=issued;if(issued.serverUrl!=='/media')throw failure('MEDIA_ORIGIN_INVALID');changed('connecting');progressAt=now();
        const capable=view.RTCRtpScriptTransform||view.RTCRtpReceiver?.prototype?.createEncodedStreams;
        if(capable&&view.Worker)worker=new view.Worker('/control-assets/js/lib/livekit-frame-metadata.worker.mjs',{type:'module'});
        const options={adaptiveStream:true,dynacast:false,...(worker?{frameMetadata:{worker}}:{})};
        room=createRoom?createRoom(options):new view.LivekitClient.Room(options);
        room.on('trackSubscribed',(incoming,publication,participant)=>{
          if(current!==epoch||incoming.kind!=='video'||participant.identity!==issued.publisherIdentity)return;
          detach();track=incoming;track.attach(video);progressAt=video.requestVideoFrameCallback?now():null;changed('timing_unknown');
          function rendered(_time,metadata){
            if(current!==epoch||track!==incoming)return;
            progressAt=now();
            const value=typeof metadata?.rtpTimestamp==='number'?incoming.lookupFrameMetadata?.({rtpTimestamp:metadata.rtpTimestamp}):null;
            if(!acknowledging&&value&&Number.isSafeInteger(value.frameId)&&value.frameId>=0&&typeof value.userTimestamp==='bigint'&&value.userTimestamp>0n){
              acknowledging=true;
              sessionClient.request('/api/v1/media/frame',{viewerId:issued.viewerId,frameId:String(value.frameId),capturedAtUs:String(value.userTimestamp)}).then(result=>{if(current===epoch&&result.accepted===true){lastAck=now();changed('fresh');}}).catch(error=>{if(current===epoch){if(terminal(error))void close();else changed('timing_unknown');}}).finally(()=>{if(current===epoch)acknowledging=false;});
            }
            frameCallback=video.requestVideoFrameCallback?.(rendered)??null;
          }
          frameCallback=video.requestVideoFrameCallback?.(rendered)??null;
        });
        room.on('trackUnsubscribed',incoming=>{if(!incoming||incoming.kind==='video')recover(value,current);});room.on('reconnecting',()=>{if(current===epoch){lastAck=-Infinity;changed('connecting');}});room.on('disconnected',()=>recover(value,current));
        const protocol=view.location.protocol==='https:'?'wss:':/^127\.0\.0\.1(?::|$)|^localhost(?::|$)/.test(view.location.host)?'ws:':null;if(!protocol)throw failure('HTTPS_REQUIRED');
        await timed(room.connect(`${protocol}//${view.location.host}/media`,issued.token,{autoSubscribe:true}),12000);
      }catch(error){if(current===epoch){if(error?.code==='MEDIA_CLOSE_UNCONFIRMED'){clearIntent();changed('unavailable');}else if(terminal(error))await close();else recover(value,current);}throw error;}
    }
    function begin(value,retrying){opening=true;const attempt=run(value,retrying).finally(()=>{if(activeAttempt===attempt){opening=false;activeAttempt=null;}});activeAttempt=attempt;return attempt;}
    function watch(deviceId){if(opening||pendingViews)return Promise.reject(failure('MEDIA_BUSY'));if(disposed||!visible())return Promise.reject(failure('CAMERA_UNAVAILABLE'));clearIntent();intent={deviceId,identity:sessionClient.identity?{...sessionClient.identity}:null,retries:0};return begin(intent,false);}
    const hidden=()=>{if(!visible())void close();},leaving=()=>{void close();};
    view.document?.addEventListener('visibilitychange',hidden);view.addEventListener?.('pagehide',leaving);
    return {watch,close,state:()=>state,dispose(){disposed=true;view.document?.removeEventListener('visibilitychange',hidden);view.removeEventListener?.('pagehide',leaving);return close();},checkFreshness(){if(state==='fresh'&&now()-lastAck>=500)changed('timing_unknown');if(intent&&progressAt!==null&&now()-progressAt>=12000)recover(intent,epoch);}};
  }
  function mountCameraView({document:doc,view=root,sessionClient}){
    const section=doc.getElementById('sec-xvision'),body=section?.querySelector('.sec-body');if(!body)return {dispose(){}};
    const tr=text=>view.ThirdHandI18n?.translate(text)||text,el=(tag,text)=>{const node=doc.createElement(tag);if(text)node.textContent=tr(text);return node;};
    const label=doc.getElementById('cam-label'),dot=doc.getElementById('cam-dot'),container=doc.getElementById('xvision-feed').parentElement,placeholder=container.querySelector('.camera-empty'),video=el('video');video.autoplay=true;video.muted=true;video.playsInline=true;video.className='cloud-camera-video';video.setAttribute('aria-label',tr('Live camera · view only'));doc.getElementById('xvision-feed').hidden=true;container.append(video);
    const panel=el('div'),select=el('select');select.setAttribute('aria-label',tr('Camera device'));panel.className='cloud-camera-controls';body.prepend(panel);panel.append(select);
    const messages={unavailable:'Camera unavailable',connecting:'Connecting camera…',timing_unknown:'Video timing unavailable · view only',fresh:'Live frame verified'};
    const client=createCameraClient({view,sessionClient,video,onChange:state=>{label.textContent=tr(messages[state]);dot.classList.toggle('connected',state==='fresh');if(placeholder)placeholder.hidden=['fresh','timing_unknown'].includes(state);}});
    function button(text,action){const node=el('button',text);node.type='button';node.className='action-btn action-secondary';node.addEventListener('click',async()=>{node.disabled=true;try{await action();}catch{label.textContent=tr('Camera unavailable');}finally{node.disabled=false;}});panel.append(node);}
    button('Load cameras',async()=>{const result=await sessionClient.request('/api/v1/devices');select.replaceChildren();for(const device of result.devices.filter(value=>value.camera===true)){const option=el('option');option.value=device.id;option.textContent=device.name;select.append(option);}});
    button('Watch camera',()=>client.watch(select.value));button('Close camera',()=>client.close());label.textContent=tr('Camera unavailable');
    const logout=doc.getElementById('workspace-logout'),signingOut=()=>{void client.close();};logout?.addEventListener('click',signingOut,{capture:true});
    const timer=view.setInterval(()=>client.checkFreshness(),250);
    return {client,dispose(){view.clearInterval(timer);logout?.removeEventListener('click',signingOut,{capture:true});void client.dispose();panel.remove();}};
  }
  return {createCameraClient,mountCameraView};
});
