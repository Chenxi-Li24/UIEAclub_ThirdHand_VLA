'use strict';
async function writeAudit(client,{actorUserId=null,eventCode,objectId=null,outcome,context={}}){
  // Audit context is a closed schema; credential/request objects cannot be serialized.
  const safe={};
  if(typeof context.code==='string'&&/^[A-Z0-9_]{1,64}$/.test(context.code))safe.code=context.code;
  if(typeof context.sourceHash==='string'&&/^[a-f0-9]{64}$/.test(context.sourceHash))safe.sourceHash=context.sourceHash;
  if(eventCode==='identity.user.status_changed'&&typeof context.reason==='string'&&context.reason.trim()&&context.reason.length<=500)safe.reason=context.reason.trim();
  await client.query('INSERT INTO security.audit_events(actor_user_id,event_code,object_id,outcome,context) VALUES($1,$2,$3,$4,$5)',[actorUserId,eventCode,objectId,outcome,safe]);
}
module.exports={writeAudit};
