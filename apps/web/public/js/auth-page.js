(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandAuth=api;
  if(root.document)root.document.addEventListener('DOMContentLoaded',()=>api.mountAuthPage(root.document,root),{once:true});
})(globalThis,function(){
  'use strict';
  const messages={
    INVALID_CREDENTIALS:'The username or password is incorrect.',
    ADMIN_PERMISSION_REQUIRED:'This account does not have administrator access.',
    EMAIL_NOT_VERIFIED:'Verify your email before signing in.',
    MFA_REQUIRED:'Enter your authenticator code or a recovery code.',
    MFA_INVALID:'The verification code is invalid or has already been used.',
    MFA_ENROLLMENT_REQUIRED:'Sign in as Observer and enable two-step verification in account settings.',
    MFA_SETUP_EXPIRED:'The setup has expired. Start a new setup.',
    RATE_LIMITED:'Too many attempts. Please try again later.',
    AUTH_BUSY:'Sign-in is busy. Please try again shortly.',
    INVALID_PASSWORD:'Use 12–128 characters for your password.',
    INVALID_TOKEN:'This link is invalid or expired. Request a new link.',
    INVALID_INPUT:'Check the form fields and try again.',
    '23505':'That username or email is already registered.',
    MAIL_UNAVAILABLE:'Email delivery is not configured. Please contact an administrator.',
    SERVICE_UNAVAILABLE:'The service is unavailable. Please try again later.'
  };
  function mountAuthPage(doc,view,{preferences,request,navigate}={}){
    preferences ||= view.ThirdHandPreferences.createPreferenceClient({view});
    const page=doc.body.dataset.authPage,byId=id=>doc.getElementById(id),fields={},subscriptions=[];
    const tr=text=>view.ThirdHandI18n?.translate(text,doc.documentElement.lang)||text;
    const el=(tag,attrs={},text)=>{const node=doc.createElement(tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,String(value));if(text!==undefined)node.textContent=text;return node;};
    const content=byId('auth-content'),message=el('div',{id:'auth-message',class:'auth-message',role:'alert',hidden:''});content.append(message);
    let linkToken=null;
    if(['verify-email','reset-password'].includes(page)){
      linkToken=new URLSearchParams((view.location?.hash||'').slice(1)).get('token');
      if(linkToken)view.history?.replaceState(null,'',`/${page}`);
    }
    const messageText=el('span',{},''),switchObserver=el('button',{id:'switch-observer',type:'button',hidden:''},'Switch to Observer');message.append(messageText,switchObserver);
    let mode='observe',pending=false,notice='',noticeKind='error',verified=false,disposed=false,redirectTimer;
    const passwordFeedback={},passwordTouched=new Set();
    const form=el('form',{class:'auth-form',id:'auth-form',novalidate:''});content.append(form);
    function field(id,label,{type='text',autocomplete,placeholder=label,minimum,maximum=128,feedback=false}={}){
      const labelNode=el('label',{class:'auth-field',for:id}),text=el('span',{},label),input=el('input',{id,name:id,type,required:'',maxlength:maximum,placeholder,autocomplete:autocomplete||'off'});
      if(minimum)input.setAttribute('minlength',minimum);fields[id]=input;labelNode.append(text);
      if(type==='password'){
        const wrap=el('div',{class:'password-wrap'}),toggle=el('button',{type:'button',id:`toggle-${id}`,class:'password-toggle','aria-label':'Show password','aria-pressed':'false'});
        const svg=doc.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.6');svg.setAttribute('aria-hidden','true');
        for(const d of ['M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z','M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0']){const path=doc.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',d);svg.append(path);}toggle.append(svg);
        toggle.addEventListener('click',()=>{const shown=input.type==='password';input.type=shown?'text':'password';toggle.setAttribute('aria-pressed',String(shown));toggle.setAttribute('aria-label',tr(shown?'Hide password':'Show password'));});wrap.append(input,toggle);labelNode.append(wrap);
      }else labelNode.append(input);
      if(feedback){
        const row=el('div',{class:'auth-password-row'}),hint=el('ul',{id:`${id}-feedback`,class:'auth-field-feedback',role:'status','aria-live':'polite','aria-atomic':'true'});
        input.setAttribute('aria-describedby',`${id}-feedback password-requirements`);passwordFeedback[id]=hint;
        for(const event of ['input','blur','invalid'])input.addEventListener(event,()=>{passwordTouched.add(id);renderPasswordFeedback();});
        row.append(labelNode,hint);form.append(row);
      }else form.append(labelNode);return input;
    }
    function passwordIssues(id){
      const issues=[],length=[...fields[id].value].length;
      if(length<12)issues.push('Use at least 12 characters.');
      if(length>128)issues.push('Use at most 128 characters.');
      if(id==='confirmPassword'&&fields[id].value!==fields.password.value)issues.push('Passwords do not match.');
      return issues;
    }
    function renderPasswordFeedback(){
      for(const [id,hint]of Object.entries(passwordFeedback)){
        hint.replaceChildren();
        if(!passwordTouched.has(id)){fields[id].removeAttribute('aria-invalid');hint.removeAttribute('data-kind');continue;}
        const issues=passwordIssues(id);fields[id].setAttribute('aria-invalid',String(issues.length>0));hint.dataset.kind=issues.length?'error':'success';
        for(const text of issues.length?issues:[id==='confirmPassword'?'Passwords match.':'Password meets requirements.'])hint.append(el('li',{},tr(text)));
      }
    }
    function newPasswordFields(label){
      field('password',label,{type:'password',autocomplete:'new-password',maximum:512,feedback:true});
      field('confirmPassword','Confirm password',{type:'password',autocomplete:'new-password',maximum:512,feedback:true});
      const requirements=el('section',{id:'password-requirements',class:'auth-password-requirements','aria-label':'Password requirements'});
      requirements.append(el('strong',{},'Password requirements'),el('p',{},'Use 12–128 characters.'),el('p',{},'Both passwords must match.'));form.append(requirements);
    }
    let modeHint,mfaFields,remember;
    function setMode(next){
      mode=next;
      for(const name of ['observe','admin']){const tab=byId(`mode-${name}`);tab.setAttribute('aria-selected',String(name===mode));tab.tabIndex=name===mode?0:-1;}
      modeHint.textContent=tr(mode==='observe'?'View cameras, explore the 3D model and review run history.':'Administrator access requires two-step verification.');
      if(mfaFields)mfaFields.hidden=true;notice='';renderMessage();
    }
    if(page==='login'){
      const tabs=el('div',{class:'mode-tabs',role:'tablist','aria-label':'Sign-in mode'});content.insertBefore(tabs,message);
      for(const [name,label]of [['observe','Observer'],['admin','Administrator']]){
        const button=el('button',{id:`mode-${name}`,type:'button',role:'tab','aria-selected':String(name==='observe'),'aria-controls':'auth-form'},label);
        button.tabIndex=name==='observe'?0:-1;button.addEventListener('click',()=>setMode(name));
        button.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const next=event.key==='Home'?'observe':event.key==='End'?'admin':mode==='observe'?'admin':'observe';setMode(next);byId(`mode-${next}`).focus();}});tabs.append(button);
      }
      modeHint=el('p',{class:'mode-description'},'View cameras, explore the 3D model and review run history.');content.insertBefore(modeHint,message);
      field('login','Username or email',{autocomplete:'username',maximum:254});field('password','Password',{type:'password',autocomplete:'current-password',maximum:512});
      mfaFields=el('div',{id:'mfa-fields',class:'auth-mfa',hidden:''});
      const label=el('label',{class:'auth-field',for:'mfa-code'},'Authenticator or recovery code');fields.mfaCode=el('input',{id:'mfa-code',type:'text',autocomplete:'one-time-code',maxlength:128});label.append(fields.mfaCode);mfaFields.append(label);form.append(mfaFields);
      const options=el('div',{class:'auth-options'}),rememberLabel=el('label',{class:'auth-remember',for:'remember-account'});remember=el('input',{id:'remember-account',type:'checkbox'});rememberLabel.append(remember,el('span',{},'Remember account'));options.append(rememberLabel,el('a',{href:'/forgot-password'},'Forgot password?'));form.append(options);
      try{const saved=view.localStorage?.getItem('thirdhand.remembered-login');if(saved){fields.login.value=saved.slice(0,254);remember.checked=true;}}catch{}
      remember.addEventListener('change',()=>{if(!remember.checked){try{view.localStorage?.removeItem('thirdhand.remembered-login');}catch{}}});
    }else if(page==='register'){
      field('username','Username',{autocomplete:'username',minimum:3,maximum:48});field('displayName','Display name',{autocomplete:'name',maximum:80});field('email','Email',{type:'email',autocomplete:'email',maximum:254});
      newPasswordFields('Password');
      form.append(el('p',{class:'auth-note'},'Verify your email to continue.'));
    }else if(page==='forgot-password'||page==='verify-email'&&!linkToken)field('email','Email',{type:'email',autocomplete:'email',maximum:254});
    else if(page==='reset-password')newPasswordFields('New password');
    const labels={login:'Sign in',register:'Create account','forgot-password':'Send reset link','reset-password':'Save new password','verify-email':linkToken?'Verify email':'Resend verification email'};
    const submitButton=el('button',{class:'auth-primary',type:'submit'},labels[page]||'Continue');form.append(submitButton);
    const bottom=el('p',{class:'auth-bottom'},page==='login'?'New to ThirdHand?':page==='register'?'Already registered?':'Back to');bottom.append(el('a',{href:page==='login'?'/register':'/login'},page==='login'?'Create an account':'Sign in'));content.append(bottom);
    if(['login','register'].includes(page))content.append(el('a',{href:'/verify-email',class:'auth-bottom'},'Resend verification email'));
    function renderMessage(){message.hidden=!notice;messageText.textContent=tr(notice);message.dataset.kind=noticeKind;message.setAttribute('role',noticeKind==='success'?'status':'alert');switchObserver.hidden=page!=='login'||!['This account does not have administrator access.','Sign in as Observer and enable two-step verification in account settings.'].includes(notice);}
    switchObserver.addEventListener('click',()=>{setMode('observe');byId('mode-observe').focus();});
    const call=request||(async(path,body)=>{const response=await view.fetch(path,{method:body===undefined?'GET':'POST',credentials:'same-origin',headers:body===undefined?{}:{'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});const value=await response.json();if(!response.ok)throw Object.assign(new Error(),{code:value.error});return value;});
    async function submit(){
      if(pending||verified||disposed)return;
      if(fields.confirmPassword){
        passwordTouched.add('password');passwordTouched.add('confirmPassword');renderPasswordFeedback();
        if(passwordIssues('password').length||passwordIssues('confirmPassword').length){notice=fields.password.value!==fields.confirmPassword.value?'Passwords do not match.':messages.INVALID_PASSWORD;noticeKind='error';renderMessage();return;}
      }
      if(form.checkValidity?.()===false){form.reportValidity?.();return;}
      pending=true;submitButton.disabled=true;form.setAttribute('aria-busy','true');notice='';renderMessage();
      try{
        if(page==='login'){
          const body={login:fields.login.value,password:fields.password.value,requestedMode:mode};
          if(!mfaFields.hidden&&fields.mfaCode.value){const code=fields.mfaCode.value.trim();body[/^\d{6}$/.test(code)?'totp':'recoveryCode']=code;}
          const result=await call('/api/v1/auth/login',body);
          try{if(remember.checked)view.localStorage?.setItem('thirdhand.remembered-login',fields.login.value);else view.localStorage?.removeItem('thirdhand.remembered-login');}catch{}
          fields.password.value='';fields.mfaCode.value='';
          if(result.userId)await preferences.hydrate({userId:result.userId,csrfToken:result.csrfToken});
          (navigate||((path)=>view.location.assign(path)))(result.next==='/control'?result.next:'/control');
        }else if(page==='register'){
          await call('/api/v1/auth/register',{username:fields.username.value,email:fields.email.value,displayName:fields.displayName.value,password:fields.password.value,locale:preferences.current().locale});
          fields.password.value='';fields.confirmPassword.value='';passwordTouched.clear();renderPasswordFeedback();notice='Check your email to verify your account.';noticeKind='success';
        }else if(page==='forgot-password'){
          await call('/api/v1/auth/forgot-password',{email:fields.email.value});notice='If this account is active, a reset link has been sent.';noticeKind='success';
        }else if(page==='reset-password'){
          await call('/api/v1/auth/reset-password',{token:linkToken,password:fields.password.value});fields.password.value='';fields.confirmPassword.value='';passwordTouched.clear();renderPasswordFeedback();notice='Password updated. You can now sign in.';noticeKind='success';
        }else if(page==='verify-email'){
          if(linkToken){
            await call('/api/v1/auth/verify-email',{token:linkToken});verified=true;linkToken=null;notice='Email verified. Redirecting to sign in…';
            if(!disposed)redirectTimer=view.setTimeout(()=>{if(!disposed)(navigate||(path=>view.location.replace(path)))('/login');},2000);
          }
          else{await call('/api/v1/auth/resend-verification',{email:fields.email.value});notice='If this account needs verification, a new link has been sent.';}
          noticeKind='success';
        }
      }catch(error){notice=messages[error.code]||messages.SERVICE_UNAVAILABLE;noticeKind='error';if(page==='login'&&['MFA_REQUIRED','MFA_INVALID'].includes(error.code)){mfaFields.hidden=false;fields.mfaCode.focus();}}
      finally{pending=false;submitButton.disabled=verified;form.removeAttribute('aria-busy');renderMessage();}
    }
    form.addEventListener('submit',event=>{event.preventDefault();submit();});
    const choose=change=>preferences.choose(change).catch(()=>{notice='Could not save preferences. Please try again.';noticeKind='error';renderMessage();});
    byId('locale-en').addEventListener('click',()=>choose({locale:'en'}));byId('locale-zh').addEventListener('click',()=>choose({locale:'zh-CN'}));
    byId('theme-toggle').addEventListener('click',()=>choose({themeId:preferences.current().themeId==='light'?'dark':'light'}));
    const appearance=byId('appearance-options'),appearanceToggle=byId('appearance-toggle');
    const kindLabel=el('label',{for:'background-kind'},'Background'),kind=el('select',{id:'background-kind'});
    for(const [value,label]of [['soft','Soft shapes'],['plain','Plain']])kind.append(el('option',{value},label));kindLabel.append(kind);
    const colorLabel=el('label',{for:'background-color'},'Background color'),color=el('input',{id:'background-color',type:'color'});colorLabel.append(color);appearance.append(kindLabel,colorLabel);
    appearanceToggle.addEventListener('click',()=>{appearance.hidden=!appearance.hidden;appearanceToggle.setAttribute('aria-expanded',String(!appearance.hidden));});
    kind.addEventListener('change',()=>choose({backgroundConfig:{...preferences.current().backgroundConfig,kind:kind.value}}));color.addEventListener('change',()=>choose({backgroundConfig:{...preferences.current().backgroundConfig,color:color.value}}));
    subscriptions.push(preferences.subscribe(value=>{preferences.apply(doc,value);byId('locale-en').setAttribute('aria-pressed',String(value.locale==='en'));byId('locale-zh').setAttribute('aria-pressed',String(value.locale==='zh-CN'));byId('theme-toggle').setAttribute('aria-pressed',String(value.themeId==='dark'));for(const option of kind.querySelectorAll('option'))option.selected=option.getAttribute('value')===value.backgroundConfig.kind;color.value=value.backgroundConfig.color;renderMessage();renderPasswordFeedback();}));
    return {submit,ready:Promise.resolve(),dispose(){disposed=true;if(redirectTimer!==undefined)view.clearTimeout(redirectTimer);for(const unsubscribe of subscriptions)unsubscribe();preferences.dispose();}};
  }
  return {mountAuthPage};
});
