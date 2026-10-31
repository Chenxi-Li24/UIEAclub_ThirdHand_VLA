'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {parseHTML}=require('linkedom');
const {mountAdminAccess}=require('../../../apps/web/public/js/admin-access');

test('Observer can submit an application, see its outcome, and cannot request other users data',async()=>{
  const {document}=parseHTML('<section id="page-account-profile"></section>'),calls=[];
  let application=null;
  const api=mountAdminAccess({document,view:{},identity:{userId:'me',role:'observer',mode:'observe'},sessionClient:{async request(path,body){calls.push({path,body});if(body)application={id:'application',status:'pending',reason:body.reason};return {application};}}});
  await api.ready;
  assert.equal(document.querySelector('#admin-application-submit').disabled,false);
  document.querySelector('#admin-application-reason').value='Maintain the lab';
  await api.submit();
  assert.equal(calls[1].path,'/api/v1/me/admin-application');
  assert.deepEqual(calls[1].body,{reason:'Maintain the lab'});
  assert.equal(document.querySelector('#admin-application-submit').disabled,true);
  assert.match(document.querySelector('#admin-application-status').textContent,/Pending/);
  assert.equal(document.querySelector('#admin-application-review'),null);
});

test('application load failure never enables a blind resubmission',async()=>{
  const {document}=parseHTML('<section id="page-account-profile"></section>');
  const api=mountAdminAccess({document,view:{},identity:{role:'observer',mode:'observe'},sessionClient:{async request(){throw {code:'SERVICE_UNAVAILABLE'};}}});
  await api.ready;
  assert.equal(document.querySelector('#admin-application-submit').disabled,true);
  assert.equal(document.querySelector('#admin-application-reload').disabled,false);
});

test('a revoked administrator in Observer mode may reapply despite a past approved or initial-batch application',async()=>{
  for(const status of ['approved','superseded']){
    const {document}=parseHTML('<section id="page-account-profile"></section>');
    const api=mountAdminAccess({document,view:{},identity:{role:'observer',mode:'observe'},sessionClient:{async request(){return {application:{status,reviewReason:'previous grant'}};}}});
    await api.ready;
    assert.equal(document.querySelector('#admin-application-submit').disabled,false);
    assert.equal(document.querySelector('#admin-application-reason').disabled,false);
  }
});

test('administrator decisions require a separate applicant, reason, password and MFA with clearing of credentials',async()=>{
  const {document}=parseHTML('<section id="page-account-profile"></section>'),calls=[];
  const application={id:'id-1',userId:'other',username:'applicant',reason:'Maintain the lab'};
  const api=mountAdminAccess({document,view:{},identity:{userId:'reviewer',role:'admin',mode:'admin'},sessionClient:{async request(path,body){calls.push({path,body});return body?{result:{}}:{applications:[application],nextCursor:null};}}});
  await api.ready;
  assert.equal(document.querySelectorAll('#admin-application-review tbody tr').length,1);
  api.choose(application,'approved');
  document.querySelector('#admin-review-reason').value='Approved by reviewer';
  document.querySelector('#admin-review-password').value='Private test password';
  document.querySelector('#admin-review-verification').value='123456';
  await api.decide();
  assert.deepEqual(calls[1],{path:'/api/v1/admin/applications/id-1/decision',body:{decision:'approved',reason:'Approved by reviewer',password:'Private test password',totp:'123456'}});
  assert.equal(document.querySelector('#admin-review-password').value,'');
  assert.equal(document.querySelector('#admin-review-verification').value,'');
});
