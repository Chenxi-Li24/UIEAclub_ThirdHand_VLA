'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
const {createHash,randomBytes,randomUUID}=require('node:crypto');
const {identityFixture}=require('./identity-fixture');
const {createHistoryRepository}=require('../../../platform/storage/src/history');
const {createExportService,csvCell}=require('../../../services/cloud-api/src/jobs/export-worker');

async function fixture(t,options={}){
  const f=await identityFixture(t),user=await f.verified('export_reader'),root=await fs.mkdtemp(path.join(os.tmpdir(),'thirdhand-exports-'));
  t.after(async()=>{const target=path.resolve(root);assert.equal(path.dirname(target),path.resolve(os.tmpdir()));assert.match(path.basename(target),/^thirdhand-exports-/);await fs.rm(target,{recursive:true,force:true,maxRetries:5,retryDelay:100});});
  const principal={userId:user.userId,sessionId:randomUUID(),role:'observer',mode:'observe'},history=createHistoryRepository(f.pool,{cursorKey:randomBytes(32)});
  const deviceId=(await f.pool.query("INSERT INTO ops.devices(name,hardware_serial) VALUES('Export fixture','export-fixture') RETURNING id")).rows[0].id;
  await f.pool.query("INSERT INTO ops.device_events(device_id,edge_event_id,event_code,level,captured_at,details) SELECT $1::uuid,gen_random_uuid(),'fixture','info','2026-10-30T09:00:00Z',jsonb_build_object('value',n) FROM generate_series(1,5) n",[deviceId]);
  return {...f,root,principal,exports:createExportService({pool:f.pool,history,root,...options}),filter:{kind:'device_events',from:'2026-10-30T08:00:00Z',to:'2026-10-30T10:00:00Z'}};
}
test('private asynchronous export includes every row, digest and current-principal ownership checks',async t=>{
  const f=await fixture(t),job=await f.exports.create(f.principal,{filter:f.filter,format:'ndjson'});
  assert.equal(job.status,'queued');assert.equal((await fs.readdir(f.root)).length,0);
  assert.equal((await f.exports.runNext()).status,'completed');
  const ready=await f.exports.status(f.principal,job.id),file=await f.exports.open(f.principal,job.id);
  const bytes=await file.handle.readFile();await file.handle.close();
  const rows=bytes.toString().trim().split('\n').map(JSON.parse);assert.equal(rows.filter(row=>row.type==='record').length,5);assert.equal(rows.at(-1).rowCount,5);
  assert.equal(ready.rowCount,'5');assert.equal(ready.digest,createHash('sha256').update(bytes).digest('hex'));
  await assert.rejects(f.exports.open(null,job.id),{code:'FORBIDDEN'});
  await assert.rejects(f.exports.open({...f.principal,userId:randomUUID()},job.id),{code:'NOT_FOUND'});
  await f.pool.query("UPDATE ops.export_jobs SET expires_at=now()-interval '1 second' WHERE id=$1",[job.id]);
  await assert.rejects(f.exports.open(f.principal,job.id),{code:'EXPORT_EXPIRED'});
});
test('export limits fail explicitly without publishing a truncated download; concurrent jobs claim once',async t=>{
  const f=await fixture(t,{maxRows:3}),job=await f.exports.create(f.principal,{filter:f.filter,format:'csv'});
  const result=await Promise.all([f.exports.runNext(),f.exports.runNext()]);assert.equal(result.filter(Boolean).length,1);
  const state=await f.exports.status(f.principal,job.id);assert.equal(state.status,'failed');assert.equal(state.errorCode,'EXPORT_LIMIT_EXCEEDED');
  assert.deepEqual(await fs.readdir(f.root),[]);await assert.rejects(f.exports.open(f.principal,job.id),{code:'EXPORT_NOT_READY'});
  for(const value of ['=1+1',' +SUM(A1)','\t=HYPERLINK("x")','@evil','-2'])assert.ok(csvCell(value).startsWith('"\''));
  assert.equal(csvCell('normal'),'"normal"');
});

test('CSV job produces UTF-8 spreadsheet columns for every matching operational record',async t=>{
  const f=await fixture(t),job=await f.exports.create(f.principal,{filter:f.filter,format:'csv'});
  assert.equal((await f.exports.runNext()).status,'completed');
  const file=await f.exports.open(f.principal,job.id),bytes=await file.handle.readFile();await file.handle.close();
  const text=bytes.toString('utf8');assert.ok(text.startsWith('\uFEFF"id","device_id","boot_id","captured_at"'));
  assert.ok(text.includes('"event_code","level","details","record_json"'));
  assert.equal(text.trim().split('\r\n').length,6);
  assert.equal((await f.exports.status(f.principal,job.id)).rowCount,'5');
});
