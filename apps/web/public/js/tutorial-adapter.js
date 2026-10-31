/* The teammate owns tutorial UI and authoritative progress; this is an integration boundary. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandTutorialAdapter=api;})(globalThis,function(){
  'use strict';
  const statuses=new Set(['unavailable','not_started','in_progress','deferred','completed']);
  function localPath(value){
    if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||/[\\\u0000-\u0020]/.test(value))return null;
    try{const decoded=decodeURIComponent(value);if(/[\\\u0000-\u0020]/.test(decoded)||decoded.startsWith('//'))return null;
      const url=new URL(value,'https://thirdhand.invalid');if(url.origin!=='https://thirdhand.invalid')return null;return `${url.pathname}${url.search}${url.hash}`;
    }catch{return null;}
  }
  const controlReturn=value=>{const safe=localPath(value);return safe&&(safe==='/control'||safe.startsWith('/control#')||safe==='/history')?safe:'/control';};
  function createTutorialAdapter({provider=null,allowedPrefixes=['/tutorial','/learn/']}={}){
    return {
      async getState({userId}){try{const state=await provider?.getState({userId});return statuses.has(state?.status)?{status:state.status,...(typeof state.version==='string'?{version:state.version}:{})}:{status:'unavailable'};}catch{return {status:'unavailable'};}},
      getEntry({locale,theme,returnTo}){try{const entry=provider?.getEntry({locale,theme,returnTo:controlReturn(returnTo)}),path=localPath(entry?.path);
        return path&&allowedPrefixes.some(prefix=>path===prefix||path.startsWith(prefix.endsWith('/')?prefix:`${prefix}/`))?{path}:null;
      }catch{return null;}},
      async verifyCompletion({userId,version}){try{const result=await provider?.verifyCompletion({userId,version});
        if(result?.trusted===true&&result.completed===true&&typeof result.version==='string'&&(!version||result.version===version))return {trusted:true,completed:true,version:result.version};
      }catch{}return {trusted:false,completed:false,version:null};}
    };
  }
  function resolveEntry({tutorialState,entry,returnTo}){
    if(['not_started','in_progress'].includes(tutorialState?.status)){const path=localPath(entry?.path);if(path)return path;}
    return controlReturn(returnTo);
  }
  function scopedTutorialView(view,userId){
    const name=key=>key==='thirdhand.onboarding.v1'?`${key}.user.${encodeURIComponent(userId)}`:key;
    const storage={getItem:key=>view.localStorage?.getItem(name(key))||null,setItem:(key,value)=>view.localStorage?.setItem(name(key),value),removeItem:key=>view.localStorage?.removeItem(name(key))};
    return new Proxy(view,{get(target,key){if(key==='localStorage')return storage;const value=Reflect.get(target,key,target);return typeof value==='function'?value.bind(target):value;}});
  }
  return {createTutorialAdapter,resolveEntry,scopedTutorialView};
});
