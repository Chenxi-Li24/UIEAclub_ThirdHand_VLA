'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const dates=require('../../../apps/web/public/js/history-dates');
test('editable local date and time round-trip to exact UTC without shifting the selected day',()=>{
  const local=new Date(2026,9,31,17,47,20),parts=dates.localParts(local);
  assert.deepEqual(parts,{date:'2026-10-31',time:'17:47:20'});
  assert.equal(dates.toUtc(parts.date,parts.time),local.toISOString());
  assert.equal(dates.toUtc('2026-10-31','17:47'),new Date(2026,9,31,17,47,0).toISOString());
  assert.match(dates.zoneLabel(local),/\(UTC[+-]\d{2}:\d{2}\)$/);
});
test('calendar input rejects impossible dates, missing times and invalid ranges before querying',()=>{
  for(const [date,time]of [['2026-02-30','12:00'],['2026-13-01','12:00'],['2026-10-31','24:00'],['2026-10-31','12:60'],['2026-10-31',''],['10/31/2026','12:00']])assert.throws(()=>dates.toUtc(date,time),{code:'INVALID_INPUT'});
  assert.throws(()=>dates.range('2026-10-31','12:00','2026-10-31','11:00'),{code:'INVALID_INPUT'});
  assert.throws(()=>dates.range('2026-09-01','00:00','2026-10-31','00:00'),{code:'INVALID_INPUT'});
});
test('history query and export share a bounded normalized UTC interval',()=>{
  const result=dates.range('2026-10-30','17:47:00','2026-10-31','17:48:00');
  assert.equal(result.from,new Date(2026,9,30,17,47,0).toISOString());
  assert.equal(result.to,new Date(2026,9,31,17,48,0).toISOString());
  assert.equal(Date.parse(result.to)-Date.parse(result.from),86460000);
});
