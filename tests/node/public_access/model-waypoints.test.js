'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {randomBytes,randomUUID}=require('node:crypto');
const {identityFixture}=require('./identity-fixture');
const pose={name:'Desk position',joints:[10,90,-90,15,0,0],gripper:.35};
const service=pool=>require('../../../platform/storage/src/model-waypoints').createModelWaypoints({pool});

test('personal model waypoints persist across service/session instances and stay owner isolated',async t=>{
  const f=await identityFixture(t),a=await f.verified('way_a'),b=await f.verified('way_b');
  const principal={userId:a.userId};const saved=await service(f.pool).save({principal,...pose});
  assert.equal(saved.source,'model');assert.equal(saved.available,true);assert.deepEqual(saved.joints,pose.joints);assert.equal(saved.gripper,.35);
  assert.deepEqual((await service(f.pool).list({principal})).waypoints,[saved]);
  assert.deepEqual((await service(f.pool).list({principal:{userId:b.userId}})).waypoints,[]);
  await assert.rejects(service(f.pool).remove({principal:{userId:b.userId},id:saved.id}),{code:'NOT_FOUND'});
  assert.equal((await service(f.pool).remove({principal,id:saved.id})).deleted,true);
  assert.equal((await service(f.pool).list({principal})).waypoints.length,0);
});

test('waypoint inputs reject coercion, wrong dimensions, limits, names and gripper values',async t=>{
  const f=await identityFixture(t),a=await f.verified('way_validate'),principal={userId:a.userId},s=service(f.pool);
  for(const changes of [{name:' '},{name:'x'.repeat(121)},{joints:[0,90,-90]},{joints:['10',90,-90,0,0,0]},
    {joints:[null,90,-90,0,0,0]},{joints:Array(6)},{joints:[163,90,-90,0,0,0]},{joints:[0,202,-90,0,0,0]},
    {joints:[0,90,1,0,0,0]},{gripper:null},{gripper:'0.5'},{gripper:1.001},{gripper:-.001}]){
    await assert.rejects(s.save({principal,...pose,...changes}),{code:'INVALID_INPUT'});
  }
  assert.equal((await s.list({principal})).waypoints.length,0);
  const unicode=await s.save({principal,...pose,name:'🦾'.repeat(120)});assert.equal([...unicode.name].length,120);
});

test('concurrent waypoint saves cannot exceed the per-account quota',async t=>{
  const f=await identityFixture(t),a=await f.verified('way_quota'),principal={userId:a.userId},s=service(f.pool);
  const first=await s.save({principal,...pose});
  await f.pool.query(`INSERT INTO simulation.user_programs(user_id,name,model_version,program)
    SELECT $1,'fixture '||n,model_version,program FROM simulation.user_programs CROSS JOIN generate_series(1,98)n WHERE id=$2`,[a.userId,first.id]);
  const results=await Promise.allSettled([s.save({principal,...pose}),s.save({principal,...pose})]);
  assert.equal(results.filter(r=>r.status==='fulfilled').length,1);
  assert.equal(results.find(r=>r.status==='rejected').reason.code,'WAYPOINT_LIMIT_REACHED');
  assert.equal((await s.list({principal})).waypoints.length,100);
});

test('unsupported or corrupt stored model waypoints remain visible but cannot be recalled',async t=>{
  const f=await identityFixture(t),a=await f.verified('way_corrupt'),principal={userId:a.userId},s=service(f.pool);
  const first=await s.save({principal,...pose});
  await f.pool.query(`UPDATE simulation.user_programs SET program=program||'{"gripper":2}'::jsonb WHERE id=$1`,[first.id]);
  const item=(await s.list({principal})).waypoints[0];assert.equal(item.available,false);assert.equal(item.joints,undefined);
  assert.equal((await s.remove({principal,id:first.id})).deleted,true);
});

test('waypoint HTTP API enforces sessions, CSRF, exact fields and cross-login persistence',async t=>{
  const f=await identityFixture(t),a=await f.verified('way_http');
  const {createSessions}=require('../../../platform/identity/src/sessions');
  const {createCloudApi}=require('../../../services/cloud-api/src/server');
  const origin='https://thirdhand.example.invalid',sessions=createSessions({pool:f.pool,csrfKey:randomBytes(32),clock:f.clock});
  const server=createCloudApi({...f,sessions,publicOrigin:origin});await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(()=>new Promise(resolve=>{server.closeAllConnections();server.close(resolve);}));
  const base=`http://127.0.0.1:${server.address().port}`,path='/api/v1/me/waypoints';
  assert.equal((await fetch(base+path)).status,401);
  const session=await sessions.issue({userId:a.userId}),cookie=session.cookie.split(';')[0];
  const identity=await fetch(base+'/api/v1/session',{headers:{cookie}}).then(r=>r.json());
  const post=(body,csrf=true)=>fetch(base+path,{method:'POST',headers:{cookie,origin,'content-type':'application/json',...(csrf?{'x-csrf-token':identity.csrfToken}:{})},body:JSON.stringify(body)});
  assert.equal((await post(pose,false)).status,403);
  assert.equal((await post({...pose,userId:randomUUID()})).status,400);
  assert.equal((await post({...pose,source:'hardware'})).status,400);
  assert.equal((await post(pose)).status,201);
  await sessions.revokeSession({sessionId:session.sessionId,reason:'logout'});
  const again=await sessions.issue({userId:a.userId});
  const result=await fetch(base+path,{headers:{cookie:again.cookie.split(';')[0]}}).then(r=>r.json());
  assert.equal(result.waypoints.length,1);assert.deepEqual(result.waypoints[0].joints,pose.joints);
  for(const endpoint of ['/ws','/execution','/voice'])assert.equal((await fetch(base+endpoint)).status,404);
});
