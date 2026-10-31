(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandAdminAccess=api;})(globalThis,function(){
  'use strict';
  function mountAdminAccess({document:doc,view,identity,sessionClient}){
    const parent=doc.getElementById('page-account-profile');
    const tr=text=>view.ThirdHandI18n?.translate(text,doc.documentElement.lang)||text;
    const el=(tag,attrs={},text)=>{const node=doc.createElement(tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,String(value));if(text!==undefined)node.textContent=tr(text);return node;};
    const field=(form,id,label,type='text')=>{const row=el('label',{class:'account-field',for:id},label),input=el('input',{id,type,required:'',maxlength:500,autocomplete:type==='password'?'current-password':'off'});row.append(input);form.append(row);return input;};
    const errorText=error=>({CONFLICT:'This application changed. Reload and try again.',INVALID_STATE:'A verified active Observer account is required.',INVALID_INPUT:'Check the form fields and try again.',RATE_LIMITED:'Too many attempts. Please try again later.',INVALID_CREDENTIALS:'The password is incorrect.',MFA_INVALID:'Check your verification code and try again.',MFA_REQUIRED:'Enter your authenticator code or a recovery code.',FORBIDDEN:'Another administrator must review this application.'}[error?.code]||'Could not complete this request.');
    if(identity.role==='observer'){
      const section=el('article',{id:'admin-application',class:'account-card cloud-security'}),form=el('form',{class:'account-form'}),status=el('p',{id:'admin-application-status',role:'status'});
      section.append(el('h2',{},'Administrator application'));
      const reason=field(form,'admin-application-reason','Application reason'),submit=el('button',{id:'admin-application-submit',type:'submit',class:'action-btn action-primary',disabled:''},'Request administrator access'),reload=el('button',{id:'admin-application-reload',type:'button',class:'action-btn action-secondary'},'Refresh');
      form.append(submit,reload);section.append(form,status);parent.append(section);
      let busy=false,canSubmit=false;
      const statuses={pending:'Pending administrator approval',approved:'Previous application approved',rejected:'Application rejected',superseded:'Previous initial administrator grant'};
      function render(application){
        canSubmit=!application||['approved','rejected','superseded'].includes(application.status);submit.disabled=busy||!canSubmit;reason.disabled=busy||!canSubmit;
        status.textContent=tr(application?statuses[application.status]||'Could not complete this request.':'No application submitted.');
        if(application?.reviewReason)status.append(doc.createTextNode(` · ${application.reviewReason}`));
      }
      async function load(){if(busy)return;busy=true;submit.disabled=reload.disabled=true;try{const result=await sessionClient.request('/api/v1/me/admin-application');busy=false;render(result.application);}catch(error){canSubmit=false;status.textContent=tr(errorText(error));}finally{busy=false;reload.disabled=false;submit.disabled=!canSubmit;}}
      async function submitApplication(){
        if(busy||!canSubmit)return;
        if(!reason.value.trim()||reason.value.length>500){status.textContent=tr('Check the form fields and try again.');return;}
        busy=true;submit.disabled=reload.disabled=reason.disabled=true;
        try{const result=await sessionClient.request('/api/v1/me/admin-application',{reason:reason.value.trim()});busy=false;render(result.application);}
        catch(error){status.textContent=tr(errorText(error));}
        finally{busy=false;reload.disabled=false;submit.disabled=reason.disabled=!canSubmit;}
      }
      form.addEventListener('submit',event=>{event.preventDefault();void submitApplication();});reload.addEventListener('click',()=>void load());
      return {ready:load(),submit:submitApplication,load};
    }
    if(identity.role!=='admin'||identity.mode!=='admin')return {ready:Promise.resolve()};
    const section=el('article',{id:'admin-application-review',class:'account-card cloud-security'}),status=el('p',{role:'status'}),reload=el('button',{type:'button',class:'action-btn action-secondary'},'Refresh'),more=el('button',{type:'button',class:'action-btn action-secondary',hidden:''},'Load more');
    const table=el('table',{class:'cloud-users-table'}),head=el('thead'),heading=el('tr'),body=el('tbody');
    for(const title of ['Username','Email','Application reason','Actions'])heading.append(el('th',{scope:'col'},title));head.append(heading);table.append(head,body);
    const scroll=el('div',{class:'cloud-users-scroll',tabindex:'0'});scroll.append(table);
    section.append(el('h2',{},'Administrator applications'),reload,scroll,more,status);parent.append(section);
    const form=el('form',{class:'account-form',hidden:''}),title=el('h3');form.append(title);
    const reason=field(form,'admin-review-reason','Review reason'),password=field(form,'admin-review-password','Current password','password'),verification=field(form,'admin-review-verification','Authenticator or recovery code');verification.maxLength=128;verification.autocomplete='one-time-code';
    const confirm=el('button',{type:'submit',class:'action-btn action-primary'},'Confirm'),cancel=el('button',{type:'button',class:'action-btn action-secondary'},'Cancel');form.append(confirm,cancel);section.append(form);
    let selection=null,busy=false,cursor=null;
    function clear(){selection=null;reason.value=password.value=verification.value='';form.hidden=true;}
    async function load(append=false){
      if(busy)return;busy=true;reload.disabled=more.disabled=true;
      try{
        const result=await sessionClient.request(`/api/v1/admin/applications${append&&cursor?`?cursor=${encodeURIComponent(cursor)}`:''}`);
        if(!append)body.replaceChildren();
        for(const application of result.applications||[]){
          const row=el('tr');for(const value of [application.username,application.email,application.reason]){const cell=el('td',{'data-i18n-skip':''});cell.textContent=value;row.append(cell);}
          const actions=el('td');for(const [decision,label]of [['approved','Approve'],['rejected','Reject']]){const button=el('button',{type:'button'},label);button.disabled=application.userId===identity.userId;button.addEventListener('click',()=>choose(application,decision));actions.append(button);}row.append(actions);body.append(row);
        }
        cursor=result.nextCursor;more.hidden=!cursor;status.textContent=tr(body.children.length?'Applications loaded.':'No pending applications.');
      }catch(error){status.textContent=tr(errorText(error));}finally{busy=false;reload.disabled=more.disabled=false;}
    }
    function choose(application,decision){if(busy||application.userId===identity.userId||!['approved','rejected'].includes(decision))return;clear();selection={application,decision};title.textContent=`${tr(decision==='approved'?'Approve':'Reject')} · ${application.username}`;form.hidden=false;reason.focus();}
    async function decide(){
      if(!selection||busy)return;
      if(!reason.value.trim()||!password.value||!verification.value.trim()){status.textContent=tr('Check the form fields and try again.');return;}
      const value=verification.value.trim(),payload={decision:selection.decision,reason:reason.value.trim(),password:password.value,[/^\d{6}$/.test(value)?'totp':'recoveryCode']:value},id=selection.application.id;
      busy=true;confirm.disabled=cancel.disabled=reload.disabled=more.disabled=true;
      try{await sessionClient.request(`/api/v1/admin/applications/${id}/decision`,payload);clear();busy=false;await load();}
      catch(error){status.textContent=tr(errorText(error));}
      finally{busy=false;password.value=verification.value='';confirm.disabled=cancel.disabled=reload.disabled=more.disabled=false;}
    }
    cancel.addEventListener('click',clear);view.addEventListener?.('pagehide',clear,{once:true});reload.addEventListener('click',()=>void load());more.addEventListener('click',()=>void load(true));form.addEventListener('submit',event=>{event.preventDefault();void decide();});
    return {ready:load(),load,choose,decide};
  }
  return {mountAdminAccess};
});
