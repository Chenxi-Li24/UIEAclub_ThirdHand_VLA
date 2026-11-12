/* Shared preferences only. Never store session, MFA or device credentials here. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandPreferences=api;})(globalThis,function(){
  'use strict';
  const GUEST='thirdhand.preferences.guest.v1';
  const defaults=()=>({locale:'en',themeId:'light',classicThemeId:'deepspace',layoutId:'workspace',backgroundConfig:{kind:'soft',color:'#fffcf9'},revision:0});
  const copy=value=>JSON.parse(JSON.stringify(value));
  function normalize(value){
    const next=defaults();next.locale='en';
    if(['light','dark'].includes(value?.themeId))next.themeId=value.themeId;
    if(['workspace','classic'].includes(value?.layoutId))next.layoutId=value.layoutId;
    if(['deepspace','industrial','cyber','dark','green','blue','purple','orange','light'].includes(value?.classicThemeId))next.classicThemeId=value.classicThemeId;
    if(['soft','plain'].includes(value?.backgroundConfig?.kind)&&/^#[a-f0-9]{6}$/i.test(value.backgroundConfig.color))next.backgroundConfig={kind:value.backgroundConfig.kind,color:value.backgroundConfig.color.toLowerCase()};
    if(Number.isInteger(value?.revision)&&value.revision>=0)next.revision=value.revision;return next;
  }
  async function fetchJson(view,path,options,{timeoutMs=12000}={}){
    const controller=new (view.AbortController||globalThis.AbortController)();
    const setTimer=(view.setTimeout||globalThis.setTimeout).bind(view),clearTimer=(view.clearTimeout||globalThis.clearTimeout).bind(view);let timer;
    try{return await Promise.race([(async()=>{
      const response=await view.fetch(path,{...options,signal:controller.signal});
      const value=await response.json();if(!response.ok)throw Object.assign(new Error(value.error),{code:value.error,status:response.status});return value;
    })(),new Promise((_,reject)=>{timer=setTimer(()=>{reject(Object.assign(Error('REQUEST_TIMEOUT'),{code:'REQUEST_TIMEOUT'}));controller.abort();},timeoutMs);})]);}
    finally{clearTimer(timer);}
  }
  async function apiRequest(path,body,session,view){
    return fetchJson(view,path,{method:body===undefined?'GET':'POST',credentials:'same-origin',headers:{...(body===undefined?{}:{'Content-Type':'application/json'}),...(session?.csrfToken?{'X-CSRF-Token':session.csrfToken}:{})},...(body===undefined?{}:{body:JSON.stringify(body)})});
  }
  function createPreferenceClient({view=globalThis,request}={}){
    const listeners=new Set(),explicit=new Set();let session=null,epoch=0,value=defaults(),saveQueue=null;
    const read=key=>{try{return JSON.parse(view.localStorage?.getItem(key)||'null');}catch{return null;}};
    const store=(key,next)=>{try{view.localStorage?.setItem(key,JSON.stringify(next));}catch{/* Session-only preferences still work. */}};
    const guest=read(GUEST);value=normalize(guest);
    value.locale='en';
    const call=(path,body,identity=session)=>request?request(path,body,identity):apiRequest(path,body,identity,view);
    const key=()=>session?`thirdhand.preferences.user.${session.userId}.v1`:GUEST;
    const emit=()=>{for(const fn of listeners)fn(copy(value));};
    const storage=event=>{if(event.key===key()&&event.newValue){try{const next=normalize(JSON.parse(event.newValue));if(!session||next.revision>=value.revision){value=next;emit();}}catch{}}};
    view.addEventListener?.('storage',storage);
    return {
      current:()=>copy(value),
      explicitSelection:()=>({value:copy(value),changed:[...explicit]}),
      subscribe(fn){listeners.add(fn);fn(copy(value));return()=>listeners.delete(fn);},
      async hydrate(identity,bootstrap){
        const selection={value:copy(value),changed:[...explicit]},token=++epoch;session=identity;saveQueue=null;
        const next=bootstrap|| (selection.changed.length?await call('/api/v1/me/preferences/resolve',{guestSelection:selection},identity):await call('/api/v1/me/preferences',undefined,identity));
        if(token!==epoch)return false;value=normalize(next);explicit.clear();store(key(),value);emit();return true;
      },
      async choose(change){
        if(session){
          const token=epoch,identity=session,selection=copy(change);
          const save=async()=>{
            if(token!==epoch)return false;
            const next=normalize({...value,...selection});
            const result=await call('/api/v1/me/preferences',{value:next,expectedRevision:value.revision},identity);
            if(token!==epoch)return false;
            value=normalize(result);explicit.clear();store(key(),value);emit();return true;
          };
          // Header language and classic palette controls can change back-to-back.
          // Each save must build on the preceding acknowledged revision.
          const operation=saveQueue?saveQueue.then(save):save(),tail=operation.catch(()=>{});
          saveQueue=tail;tail.then(()=>{if(saveQueue===tail)saveQueue=null;});return operation;
        }
        const next=normalize({...value,...change});
        for(const name of Object.keys(change))if(['locale','themeId','classicThemeId','layoutId','backgroundConfig'].includes(name))explicit.add(name);
        value=next;
        store(key(),value);emit();return true;
      },
      logout({silent=false}={}){epoch++;session=null;saveQueue=null;explicit.clear();value=normalize(read(GUEST));if(!silent)emit();},
      apply(document,next=value){
        document.documentElement.lang=next.locale;document.documentElement.dataset.appearance=next.layoutId==='classic'?(next.classicThemeId==='light'?'light':'dark'):next.themeId;
        document.documentElement.dataset.layout=next.layoutId;
        document.documentElement.dataset.theme=next.layoutId==='classic'?next.classicThemeId:'workspace';
        document.documentElement.dataset.background=next.backgroundConfig.kind;
        document.documentElement.style.setProperty('--auth-custom-bg',next.backgroundConfig.color);
        view.ThirdHandI18n?.setLocale(next.locale);
      },
      dispose(){epoch++;listeners.clear();view.removeEventListener?.('storage',storage);}
    };
  }
  return {createPreferenceClient,fetchJson};
});
