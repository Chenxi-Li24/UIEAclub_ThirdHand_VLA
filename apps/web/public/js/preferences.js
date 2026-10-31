/* Shared preferences only. Never store session, MFA or device credentials here. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandPreferences=api;})(globalThis,function(){
  'use strict';
  const GUEST='thirdhand.preferences.guest.v1';
  const defaults=()=>({locale:'en',themeId:'light',backgroundConfig:{kind:'soft',color:'#fffcf9'},revision:0});
  const copy=value=>JSON.parse(JSON.stringify(value));
  function normalize(value){
    const next=defaults();if(['en','zh-CN'].includes(value?.locale))next.locale=value.locale;
    if(['light','dark'].includes(value?.themeId))next.themeId=value.themeId;
    if(['soft','plain'].includes(value?.backgroundConfig?.kind)&&/^#[a-f0-9]{6}$/i.test(value.backgroundConfig.color))next.backgroundConfig={kind:value.backgroundConfig.kind,color:value.backgroundConfig.color.toLowerCase()};
    if(Number.isInteger(value?.revision)&&value.revision>=0)next.revision=value.revision;return next;
  }
  async function apiRequest(path,body,session,view){
    const response=await view.fetch(path,{method:body===undefined?'GET':'POST',credentials:'same-origin',headers:{...(body===undefined?{}:{'Content-Type':'application/json'}),...(session?.csrfToken?{'X-CSRF-Token':session.csrfToken}:{})},...(body===undefined?{}:{body:JSON.stringify(body)})});
    const value=await response.json();if(!response.ok)throw Object.assign(new Error(value.error),{code:value.error});return value;
  }
  function createPreferenceClient({view=globalThis,request}={}){
    const listeners=new Set(),explicit=new Set();let session=null,epoch=0,value=defaults();
    const read=key=>{try{return JSON.parse(view.localStorage?.getItem(key)||'null');}catch{return null;}};
    const store=(key,next)=>{try{view.localStorage?.setItem(key,JSON.stringify(next));}catch{/* Session-only preferences still work. */}};
    const guest=read(GUEST);value=normalize(guest);
    if(!guest){try{const legacy=view.localStorage?.getItem('thirdhand.ui-language');if(['en','zh-CN'].includes(legacy))value.locale=legacy;}catch{}}
    const call=(path,body,identity=session)=>request?request(path,body,identity):apiRequest(path,body,identity,view);
    const key=()=>session?`thirdhand.preferences.user.${session.userId}.v1`:GUEST;
    const emit=()=>{for(const fn of listeners)fn(copy(value));};
    const storage=event=>{if(event.key===key()&&event.newValue){try{const next=normalize(JSON.parse(event.newValue));if(!session||next.revision>=value.revision){value=next;emit();}}catch{}}};
    view.addEventListener?.('storage',storage);
    return {
      current:()=>copy(value),
      explicitSelection:()=>({value:copy(value),changed:[...explicit]}),
      subscribe(fn){listeners.add(fn);fn(copy(value));return()=>listeners.delete(fn);},
      async hydrate(identity){
        const selection={value:copy(value),changed:[...explicit]},token=++epoch;session=identity;value=defaults();emit();
        const next=selection.changed.length?await call('/api/v1/me/preferences/resolve',{guestSelection:selection},identity):await call('/api/v1/me/preferences',undefined,identity);
        if(token!==epoch)return false;value=normalize(next);explicit.clear();store(key(),value);emit();return true;
      },
      async choose(change){
        const next=normalize({...value,...change});
        if(!session)for(const name of Object.keys(change))if(['locale','themeId','backgroundConfig'].includes(name))explicit.add(name);
        if(session){const token=epoch,result=await call('/api/v1/me/preferences',{value:next,expectedRevision:value.revision});if(token!==epoch)return false;value=normalize(result);explicit.clear();}
        else value=next;
        store(key(),value);emit();return true;
      },
      logout(){epoch++;session=null;explicit.clear();value=normalize(read(GUEST));emit();},
      apply(document,next=value){
        document.documentElement.lang=next.locale;document.documentElement.dataset.appearance=next.themeId;
        document.documentElement.dataset.background=next.backgroundConfig.kind;
        document.documentElement.style.setProperty('--auth-custom-bg',next.backgroundConfig.color);
        view.ThirdHandI18n?.setLocale(next.locale);
      },
      dispose(){epoch++;listeners.clear();view.removeEventListener?.('storage',storage);}
    };
  }
  return {createPreferenceClient};
});
