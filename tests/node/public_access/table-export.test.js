'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {csvCell,csvHeader,csvRow,operationalColumns,memberColumns}=require('../../../services/cloud-api/src/table-export');
const {adminRoute}=require('../../../services/cloud-api/src/routes/admin');

test('sample CSV exposes six measured angles with units and blanks for unavailable sensors',()=>{
  const columns=operationalColumns('samples'),record={joint_position_rad:[0,Math.PI/2,-Math.PI/2,0,0,0],extra:{sourceMode:'hardware'}};
  const data=csvHeader(columns)+csvRow(columns,record);
  assert.ok(data.startsWith('\uFEFF"captured_at"'));assert.ok(data.includes('"j6_position_deg"'));
  assert.ok(data.includes('"hardware","","","0","90","-90","0","0","0"'));
  assert.equal(columns.find(([name])=>name==='j1_current_a')[1](record),null);
  assert.equal(columns.find(([name])=>name==='j1_temperature_c')[1](record),null);
  assert.equal(csvCell(-90),'"-90"');assert.equal(csvCell(' -1+2'),'"\' -1+2"');
  assert.equal(csvCell('姓名, "测试"\n第二行'),'"姓名, ""测试""\n第二行"');
  assert.equal(csvCell(undefined),'""');
});

test('member CSV allowlist excludes credentials and safely quotes hostile display names',async()=>{
  const rows=Array.from({length:105},(_,i)=>({id:String(i),username:'member_'+i,displayName:i===0?'=HYPERLINK("https://invalid")':'成员',email:'user@example.invalid',passwordHash:'MUST_NOT_EXPORT',authenticatorSecret:'MUST_NOT_EXPORT',createdAt:new Date('2026-10-31T00:00:00Z')}));
  let output,headers,query;
  const response={writeHead(status,value){assert.equal(status,200);headers=value;},end(value){output=value;}};
  assert.equal(await adminRoute({path:'/api/v1/admin/users/export',request:{method:'GET'},response,principal:{userId:'test-user',sessionId:'test-session',role:'admin',mode:'admin',mfaVerifiedAt:'2026-10-31T00:00:00Z'},pool:{async query(sql){query=sql;return {rows};}}}),true);
  assert.equal(headers['Cache-Control'],'no-store');assert.match(headers['Content-Disposition'],/attachment; filename="thirdhand-members-/);
  const text=output.toString('utf8');assert.ok(text.startsWith(csvHeader(memberColumns)));
  assert.ok(text.includes('"member_104"'));assert.ok(text.includes('"\'=HYPERLINK('));assert.ok(!text.includes('MUST_NOT_EXPORT'));
  assert.ok(!/password|secret/i.test(query));assert.ok(text.includes('2026-10-31T00:00:00.000Z'));
});

test('member download forbids both observers and administrators in observer mode before querying',async()=>{
  for(const principal of [null,{userId:'test-user',sessionId:'test-session',role:'observer',mode:'observe'},{userId:'test-user',sessionId:'test-session',role:'admin',mode:'observe'}]){
    await assert.rejects(adminRoute({path:'/api/v1/admin/users/export',request:{method:'GET'},principal,pool:{query(){assert.fail('unauthorized query');}}}),{code:'FORBIDDEN'});
  }
});

test('member export refuses its size bound explicitly instead of publishing a partial table',async()=>{
  await assert.rejects(adminRoute({path:'/api/v1/admin/users/export',request:{method:'GET'},principal:{userId:'test-user',sessionId:'test-session',role:'admin',mode:'admin',mfaVerifiedAt:'2026-10-31T00:00:00Z'},response:{writeHead(){assert.fail('partial response');}},pool:{async query(){return {rows:Array(10001).fill({})};}}}),{code:'EXPORT_LIMIT_EXCEEDED'});
});
