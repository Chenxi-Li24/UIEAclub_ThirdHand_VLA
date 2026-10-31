/* Account storage and Three.js playback only. No device transport. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandModelWaypoints=api;})(globalThis,function(){
  'use strict';
  const COPY={
    'My waypoints':'我的点位','Model poses saved to your account.':'模型姿态保存在你的账户中。','Waypoint name':'点位名称','Save current model pose':'保存当前模型姿态','Reload waypoints':'刷新点位','Stop model':'停止模型',
    'Loading waypoints…':'正在加载点位…','No saved waypoints yet.':'尚未保存点位。','Waypoints loaded.':'点位已加载。','Model waypoint saved.':'模型点位已保存。','The waypoint could not be saved. Please try again.':'点位保存失败，请重试。',
    'Waypoints could not be loaded. Please try again.':'点位加载失败，请重试。','Enter a name (1–120 characters).':'请输入1–120个字符的点位名称。','The model is not ready.':'模型尚未就绪。',
    'Playing model waypoint…':'正在调用模型点位…','Model waypoint reached.':'模型已到达点位。','Model stopped.':'模型播放已停止。','The model waypoint could not finish.':'模型点位未能完成。',
    'Recall model':'调用模型','Delete':'删除','Confirm delete':'确认删除','Cancel':'取消','Model simulation':'模型模拟','Saved waypoint unavailable.':'保存的点位不可用。','Waypoint deleted.':'点位已删除。',
    'The waypoint could not be deleted.':'点位删除失败。','Your account already has 100 waypoints. Delete one before saving.':'账户已有100个点位，请删除一个后再保存。',
    'Save result unconfirmed. Reload waypoints before saving again.':'保存结果未确认，请刷新点位核对后再保存。','Delete result unconfirmed. Reload waypoints to check.':'删除结果未确认，请刷新点位核对。'
  };
  function mountModelWaypoints({document:doc,view,sessionClient,arm,simulation,ready=false}){
    const host=doc.getElementById('sec-presets');if(!host)return {setReady(){},dispose(){}};
    let disposed=false,busy=false,needsReload=true,operation=0,playToken=0,recalling=false,items=[],confirmId=null,statusKey='Loading waypoints…';
    async function request(path,body){let timer;try{return await Promise.race([sessionClient.request(path,body),new Promise((_,reject)=>{timer=(view.setTimeout||setTimeout)(()=>reject(Object.assign(Error('WAYPOINT_REQUEST_TIMEOUT'),{code:'WAYPOINT_REQUEST_TIMEOUT'})),10000);timer?.unref?.();})]);}finally{if(timer!==undefined)(view.clearTimeout||clearTimeout)(timer);}}
    const labels=[],tr=key=>doc.documentElement.lang==='zh-CN'?(COPY[key]||key):key;
    const el=(tag,key,attrs={})=>{const n=doc.createElement(tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,String(v));if(key){labels.push([n,key]);n.textContent=tr(key);}return n;};
    const section=el('section',null,{id:'model-waypoints',class:'model-waypoints','data-i18n-skip':'true'}),title=el('h3','My waypoints'),description=el('p','Model poses saved to your account.'),form=el('form'),label=el('label','Waypoint name',{for:'waypoint-name'}),name=el('input',null,{id:'waypoint-name',type:'text',maxlength:240,autocomplete:'off'}),actions=el('div',null,{class:'model-waypoint-actions'}),list=el('ul',null,{class:'model-waypoint-list'}),status=el('p',null,{id:'model-waypoint-status',role:'status'});
    function button(key,id,fn){const n=el('button',key,{type:'button',...(id?{id}:{}),class:'action-btn action-secondary'});n.addEventListener('click',()=>{if(!disposed)void fn();});return n;}
    const save=button('Save current model pose','save-model-waypoint',savePose),reload=button('Reload waypoints','reload-model-waypoints',load),stop=button('Stop model','stop-waypoint-model',()=>{playToken++;recalling=false;simulation.stop();report('Model stopped.');update();});
    actions.append(save,reload,stop);form.append(label,name,actions);form.addEventListener('submit',e=>{e.preventDefault();if(!save.disabled)void savePose();});section.append(title,description,form,list,status);host.after(section);
    function report(key){statusKey=key;if(!disposed)status.textContent=tr(key);}
    function update(){if(disposed)return;save.disabled=busy||needsReload||!ready||simulation.getState().playing;reload.disabled=busy;name.disabled=busy;stop.disabled=!ready||!simulation.getState().playing;
      for(const n of list.querySelectorAll('button'))n.disabled=busy||(n.hasAttribute('data-recall')&&(!ready||n.dataset.available!=='true'))||(needsReload&&(n.hasAttribute('data-delete')||n.hasAttribute('data-confirm-delete')));}
    function usable(p){return p?.available===true&&p.source==='model'&&p.modelVersion==='startouch-v3-model-v1'&&Array.isArray(p.joints)&&p.joints.length===6&&Array.from(p.joints).every(Number.isFinite)&&Number.isFinite(p.gripper)&&p.gripper>=0&&p.gripper<=1;}
    function render(){
      // Drop detached row labels instead of retaining every old refresh in memory.
      for(let i=labels.length-1;i>=0;i--)if(!section.contains(labels[i][0]))labels.splice(i,1);
      list.replaceChildren();
      if(!items.length)list.append(el('li','No saved waypoints yet.'));
      for(const p of items){const row=el('li',null,{'data-waypoint-id':p.id}),strong=el('strong');strong.textContent=p.name;
        const meta=el('small');meta.textContent=`${tr('Model simulation')} · ${new Date(p.updatedAt).toLocaleString(doc.documentElement.lang==='zh-CN'?'zh-CN':'en')}`;
        const buttons=el('div',null,{class:'model-waypoint-actions'}),recall=button('Recall model',null,()=>recallPose(p));recall.setAttribute('data-recall',p.id);recall.dataset.available=String(usable(p));
        buttons.append(recall,button('Delete',null,()=>{confirmId=p.id;render();}));buttons.lastChild.setAttribute('data-delete',p.id);
        if(!usable(p))buttons.append(el('span','Saved waypoint unavailable.'));
        if(confirmId===p.id){const confirm=button('Confirm delete',null,()=>remove(p.id));confirm.setAttribute('data-confirm-delete',p.id);buttons.append(confirm,button('Cancel',null,()=>{confirmId=null;render();}));}
        row.append(strong,meta,buttons);list.append(row);
      }update();
    }
    async function load(){if(disposed||busy)return;const token=++operation;busy=true;report('Loading waypoints…');update();
      try{const r=await request('/api/v1/me/waypoints');if(disposed||token!==operation)return;if(!Array.isArray(r.waypoints)||r.waypoints.length>100)throw Error('Invalid waypoint list');items=r.waypoints;confirmId=null;needsReload=false;render();report('Waypoints loaded.');}
      catch{if(!disposed&&token===operation)report('Waypoints could not be loaded. Please try again.');}
      finally{if(token===operation){busy=false;update();}}
    }
    async function savePose(){if(disposed||busy||needsReload)return;if(!ready){report('The model is not ready.');return;}if(simulation.getState().playing)return;
      const value=name.value.trim();if(!value||[...value].length>120){report('Enter a name (1–120 characters).');return;}
      const body={name:value,joints:[...arm.getJointAngles()],gripper:arm.getGripperPosition()},token=++operation;busy=true;update();
      try{const p=await request('/api/v1/me/waypoints',body);if(disposed||token!==operation)return;if(!usable(p))throw Error('Invalid save result');items=[p,...items.filter(item=>item.id!==p.id)];name.value='';render();report('Model waypoint saved.');}
      catch(error){if(!disposed&&token===operation){if(error?.code==='WAYPOINT_REQUEST_TIMEOUT'){needsReload=true;report('Save result unconfirmed. Reload waypoints before saving again.');}else report(error?.code==='WAYPOINT_LIMIT_REACHED'?'Your account already has 100 waypoints. Delete one before saving.':'The waypoint could not be saved. Please try again.');}}
      finally{if(token===operation){busy=false;update();}}
    }
    async function recallPose(p){if(disposed||busy||!ready||!usable(p))return;const token=++playToken;recalling=true;report('Playing model waypoint…');
      try{const result=await simulation.playSequence([{joints:[...p.joints],gripper:p.gripper,durationMs:800}]);if(!disposed&&token===playToken)report(result.completed?'Model waypoint reached.':'Model stopped.');}
      catch{if(!disposed&&token===playToken)report('The model waypoint could not finish.');}
      finally{if(token===playToken){recalling=false;update();}}
    }
    async function remove(id){if(disposed||busy||needsReload||confirmId!==id)return;const token=++operation;busy=true;update();
      try{const r=await request('/api/v1/me/waypoints/delete',{id});if(disposed||token!==operation)return;if(r.deleted!==true)throw Error('Deletion unconfirmed');items=items.filter(p=>p.id!==id);confirmId=null;render();report('Waypoint deleted.');}
      catch(error){if(!disposed&&token===operation){if(error?.code==='WAYPOINT_REQUEST_TIMEOUT'){needsReload=true;report('Delete result unconfirmed. Reload waypoints to check.');}else report('The waypoint could not be deleted.');}}finally{if(token===operation){busy=false;update();}}
    }
    const unsubscribe=simulation.subscribe?.(state=>{if(disposed)return;if(recalling){if(state.playing)report('Playing model waypoint…');else if(state.outcome==='stopped')report('Model stopped.');}update();});
    const language=new view.MutationObserver(()=>{if(disposed)return;for(const [n,key]of labels)n.textContent=tr(key);render();report(statusKey);});language.observe(doc.documentElement,{attributes:true,attributeFilter:['lang']});
    report(statusKey);update();void load();
    return {setReady(value){ready=value===true;update();},dispose(){disposed=true;operation++;playToken++;unsubscribe?.();language.disconnect();if(recalling)simulation.stop();section.remove();}};
  }
  return {mountModelWaypoints};
});
