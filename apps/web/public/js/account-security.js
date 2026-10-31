(function(root,factory){const api=factory(root.ThirdHandAdminAccess||(typeof module==='object'&&module.exports?require('./admin-access'):null));if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandAccountSecurity=api;})(globalThis,function(adminAccess){
  'use strict';
  function mountAccountSecurity({document:doc,view,identity,sessionClient}){
    const applications=adminAccess?.mountAdminAccess({document:doc,view,identity,sessionClient});
    if(identity.role!=='admin')return {role:identity.role,applications};
    const tr=text=>view.ThirdHandI18n?.translate(text,doc.documentElement.lang)||text;
    const el=(tag,attrs={},text)=>{const node=doc.createElement(tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,String(value));if(text!==undefined)node.textContent=text;return node;};
    const card=el('article',{id:'account-security',class:'account-card cloud-security'}),status=el('p',{role:'status',class:'account-status'});
    card.append(el('h2',{},'Two-step verification'),el('p',{},'Enable an authenticator before entering Administrator mode.'));
    const form=el('form',{class:'account-form cloud-mfa-form',novalidate:''}),passwordLabel=el('label',{class:'account-field',for:'security-password'},'Current password'),password=el('input',{id:'security-password',type:'password',autocomplete:'current-password',maxlength:512});passwordLabel.append(password);form.append(passwordLabel);
    const setupButton=el('button',{type:'button',class:'action-btn action-secondary'},'Verify password');
    const setup=el('section',{id:'mfa-enrollment',hidden:''}),qrBox=el('div',{id:'mfa-qr',class:'cloud-mfa-qr','data-i18n-skip':'',role:'img','aria-label':'Authenticator QR code'}),secretLabel=el('label',{class:'account-field',for:'mfa-secret'},'Authenticator setup key'),secret=el('input',{id:'mfa-secret',type:'text',readonly:'',autocomplete:'off','data-i18n-skip':''});secretLabel.append(secret);
    setup.append(el('p',{},'Scan this QR code with your authenticator, or enter the setup key manually.'),qrBox,secretLabel);form.append(setup);
    const codeLabel=el('label',{id:'security-code-field',class:'account-field',for:'security-totp',hidden:''},'Authenticator or recovery code'),code=el('input',{id:'security-totp',type:'text',autocomplete:'one-time-code',maxlength:128});codeLabel.append(code);form.append(codeLabel);
    const confirm=el('button',{type:'button',class:'action-btn action-primary',hidden:''},'Confirm authenticator'),modeButton=el('button',{type:'submit',class:'action-btn action-primary',hidden:''},identity.mode==='admin'?'Switch to Observer':'Enter Administrator mode'),backButton=el('button',{id:'security-back',type:'button',class:'action-btn action-secondary',hidden:''},'Back to password');
    const actions=el('div',{class:'cloud-mfa-actions'});actions.append(setupButton,confirm,modeButton,backButton);form.append(actions,status);card.append(form);
    const recovery=el('textarea',{id:'mfa-recovery-codes',rows:10,readonly:'',hidden:'',autocomplete:'off','data-i18n-skip':'','aria-label':'One-time recovery codes'});card.append(recovery);doc.getElementById('page-account-profile').append(card);
    const recoveryContinue=el('button',{id:'mfa-recovery-continue',type:'button',class:'action-btn action-secondary',hidden:''},'Continue');card.append(recoveryContinue);
    let busy=false,verifiedPassword=null,enrolling=false;
    function clearProof(){verifiedPassword=null;enrolling=false;password.value='';code.value='';secret.value='';qrBox.replaceChildren();setup.hidden=codeLabel.hidden=confirm.hidden=backButton.hidden=true;passwordLabel.hidden=identity.mode==='admin';setupButton.hidden=identity.mode==='admin';modeButton.hidden=identity.mode!=='admin';actions.hidden=false;}
    clearProof();passwordLabel.hidden=identity.mode==='admin';
    password.addEventListener('input',()=>{verifiedPassword=null;enrolling=false;code.value='';secret.value='';qrBox.replaceChildren();setup.hidden=codeLabel.hidden=confirm.hidden=true;setupButton.hidden=false;modeButton.hidden=true;});
    backButton.addEventListener('click',()=>{clearProof();report('Enter your current password first.');password.focus();});
    recoveryContinue.addEventListener('click',()=>{recovery.value='';recovery.hidden=recoveryContinue.hidden=true;clearProof();report('Enter your current password first.');password.focus();});
    view.addEventListener?.('pagehide',()=>{clearProof();recovery.value='';recovery.hidden=true;},{once:true});
    const report=(text,error=false)=>{status.textContent=tr(text);status.dataset.error=String(error);};
    const errorText=error=>({INVALID_CREDENTIALS:'The password is incorrect.',MFA_INVALID:'Check your verification code and try again.',MFA_ALREADY_ENABLED:'Two-step verification is already enabled.',MFA_SETUP_EXPIRED:'This setup has expired. Start again.',RATE_LIMITED:'Too many attempts. Please try again later.',MFA_ENROLLMENT_REQUIRED:'Set up an authenticator before entering Administrator mode.',CONFLICT:'This account changed. Reload the user list.'}[error.code]||'Could not complete this request.');
    async function operation(fn){if(busy)return;busy=true;password.disabled=setupButton.disabled=modeButton.disabled=confirm.disabled=backButton.disabled=true;try{await fn();}catch(error){if(['MFA_SETUP_EXPIRED','INVALID_CREDENTIALS'].includes(error.code))clearProof();report(errorText(error),true);}finally{busy=false;password.disabled=setupButton.disabled=modeButton.disabled=confirm.disabled=backButton.disabled=false;}}
    async function beginEnrollment(){return operation(async()=>{
      const proof=password.value;clearProof();
      if(!proof){report('Enter your current password first.',true);password.focus();return;}
      const value=await sessionClient.request('/api/v1/mfa/prepare',{password:proof});
      if(typeof value.enrolled!=='boolean')throw Error('Invalid enrollment response');
      if(!value.enrolled){
        const uri=new URL(value.uri);if(value.uri.length>2048||uri.protocol!=='otpauth:'||uri.hostname!=='totp'||!/^[A-Z2-7]{16,128}$/.test(uri.searchParams.get('secret')||''))throw Error('Invalid enrollment response');
        secret.value=uri.searchParams.get('secret');qrBox.replaceChildren();
        if(view.qrcode){const qr=view.qrcode(0,'M');qr.addData(value.uri,'Byte');qr.make();const count=qr.getModuleCount(),svg=doc.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox',`0 0 ${count+8} ${count+8}`);svg.setAttribute('aria-hidden','true');
          const rect=(x,y,width,height,fill)=>{const cell=doc.createElementNS(svg.namespaceURI,'rect');for(const [name,v]of Object.entries({x,y,width,height,fill}))cell.setAttribute(name,String(v));svg.append(cell);};rect(0,0,count+8,count+8,'#fff');
          for(let row=0;row<count;row++)for(let col=0;col<count;col++)if(qr.isDark(row,col))rect(col+4,row+4,1,1,'#000');qrBox.append(svg);
        }
        enrolling=true;setup.hidden=confirm.hidden=false;report('Scan the QR code, then enter a six-digit authenticator code below.');
      }else report('Password verified. Enter your authenticator or recovery code.');
      verifiedPassword=proof;passwordLabel.hidden=true;codeLabel.hidden=false;setupButton.hidden=true;modeButton.hidden=enrolling;backButton.hidden=false;recovery.hidden=recoveryContinue.hidden=true;recovery.value='';code.focus();
    });}
    async function confirmEnrollment(){return operation(async()=>{
      if(!enrolling||verifiedPassword===null)return;
      const value=await sessionClient.request('/api/v1/mfa/confirm',{totp:code.value.trim()});
      if(!Array.isArray(value.recoveryCodes)||value.recoveryCodes.length!==10||!value.recoveryCodes.every(item=>typeof item==='string'&&/^[a-f0-9]{32}$/.test(item)))throw Error('Invalid recovery response');
      recovery.value=value.recoveryCodes.join('\n');recovery.hidden=recoveryContinue.hidden=false;clearProof();passwordLabel.hidden=true;actions.hidden=true;report('Save these recovery codes privately. They will not be shown again.');
    });}
    setupButton.addEventListener('click',beginEnrollment);confirm.addEventListener('click',confirmEnrollment);
    form.addEventListener('submit',event=>{event.preventDefault();if(identity.mode!=='admin'&&verifiedPassword===null){beginEnrollment();return;}if(enrolling){confirmEnrollment();return;}operation(async()=>{
      const body={requestedMode:identity.mode==='admin'?'observe':'admin'};
      if(body.requestedMode==='admin'){body.password=verifiedPassword;const value=code.value.trim();body[/^\d{6}$/.test(value)?'totp':'recoveryCode']=value;}
      await sessionClient.request('/api/v1/session/mode',body);clearProof();recovery.value='';view.location.reload();
    });});
    let loadUsers;
    if(identity.mode==='admin'){
      const directory=el('article',{id:'admin-user-directory',class:'account-card cloud-security'}),reload=el('button',{type:'button',class:'action-btn action-secondary'},'Load registered users'),more=el('button',{type:'button',class:'action-btn action-secondary',hidden:''},'Load more'),table=el('table',{class:'cloud-users-table'}),body=el('tbody'),directoryStatus=el('p',{role:'status'});
      const download=el('a',{id:'admin-users-export',href:'/api/v1/admin/users/export',class:'action-btn action-secondary',download:''},'Download members (CSV)');
      const head=el('tr');for(const name of ['Username','Display name','Email','Organization','Role','Status','Registered at','Email verified at','Actions'])head.append(el('th',{scope:'col'},name));const heading=el('thead');heading.append(head);table.append(heading,body);const tableScroll=el('div',{class:'cloud-users-scroll',tabindex:'0','aria-label':'Registered users'});tableScroll.append(table);directory.append(el('h2',{},'Registered users'),reload,download,tableScroll,more,directoryStatus);doc.getElementById('page-account-profile').append(directory);
      const dialog=el('dialog',{'aria-labelledby':'admin-confirm-title'}),confirmation=el('form',{class:'account-form'}),dialogTitle=el('h2',{id:'admin-confirm-title'},'Confirm administrator action');
      const inputs={};for(const [key,label,type]of [['reason','Reason','text'],['password','Current password','password'],['verification','Authenticator or recovery code','text']]){const row=el('label',{class:'account-field'},label),input=el('input',{type,required:'',maxlength:key==='reason'?500:128,autocomplete:key==='password'?'current-password':'off'});inputs[key]=input;row.append(input);confirmation.append(row);}
      const apply=el('button',{type:'submit',class:'action-btn action-primary'},'Confirm'),cancel=el('button',{type:'button',class:'action-btn action-secondary'},'Cancel');confirmation.append(apply,cancel);dialog.append(dialogTitle,confirmation);directory.append(dialog);
      let cursor=null,mutation=null,loading=false;
      const clearDialog=()=>{for(const input of Object.values(inputs))input.value='';mutation=null;dialog.close();};cancel.addEventListener('click',clearDialog);dialog.addEventListener('cancel',()=>{for(const input of Object.values(inputs))input.value='';mutation=null;});
      function chooseMutation(user,kind,value){mutation={user,kind,value};dialogTitle.textContent=`${tr('Confirm administrator action')} · ${user.username}`;dialog.showModal();}
      loadUsers=async(append=false)=>{
        if(loading)return;loading=true;reload.disabled=more.disabled=true;directoryStatus.textContent=tr('Loading registered users…');
        try{const result=await sessionClient.request(`/api/v1/admin/users${append&&cursor?`?cursor=${encodeURIComponent(cursor)}`:''}`);if(!append)body.replaceChildren();
          for(const user of result.users){const row=el('tr');for(const value of [user.username,user.displayName,user.email,user.organization,user.role,user.status,user.createdAt?new Date(user.createdAt).toLocaleString(doc.documentElement.lang):'—',user.emailVerifiedAt?new Date(user.emailVerifiedAt).toLocaleString(doc.documentElement.lang):'—'])row.append(el('td',{'data-i18n-skip':''},value));
            const actions=el('td'),role=el('button',{type:'button'},user.role==='admin'?'Revoke administrator':'Grant administrator'),state=el('button',{type:'button'},user.status==='disabled'?'Enable account':'Disable account');
            role.addEventListener('click',()=>chooseMutation(user,'role','observer'));state.addEventListener('click',()=>chooseMutation(user,'status',user.status==='disabled'?'active':'disabled'));if(user.role==='admin')actions.append(role);actions.append(state);row.append(actions);body.append(row);}
          cursor=result.nextCursor;more.hidden=!cursor;directoryStatus.textContent=tr(result.users.length?'User list loaded.':'No registered users.');
        }catch(error){directoryStatus.textContent=tr(errorText(error));}finally{loading=false;reload.disabled=more.disabled=false;}
      };
      reload.addEventListener('click',()=>loadUsers());more.addEventListener('click',()=>loadUsers(true));
      void loadUsers();
      confirmation.addEventListener('submit',async event=>{event.preventDefault();if(!mutation||apply.disabled)return;apply.disabled=true;try{
        const value=inputs.verification.value.trim(),payload={[mutation.kind]:mutation.value,expectedVersion:mutation.user.roleVersion,reason:inputs.reason.value,password:inputs.password.value,[/^\d{6}$/.test(value)?'totp':'recoveryCode']:value};
        await sessionClient.request(`/api/v1/admin/users/${mutation.user.id}/${mutation.kind}`,payload);clearDialog();await loadUsers();
      }catch(error){directoryStatus.textContent=tr(errorText(error));}finally{inputs.password.value='';inputs.verification.value='';apply.disabled=false;}});
    }
    return {role:identity.role,beginEnrollment,confirmEnrollment,loadUsers,applications};
  }
  return {mountAccountSecurity};
});
