(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandHistoryDates=api;})(globalThis,function(){
  'use strict';
  const fail=()=>Object.assign(new Error('INVALID_INPUT'),{code:'INVALID_INPUT'}),pad=value=>String(value).padStart(2,'0');
  function localParts(value){const d=new Date(value);if(!Number.isFinite(d.getTime()))throw fail();return {date:`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`,time:`${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`};}
  function toUtc(date,time){
    if(!/^\d{4}-\d{2}-\d{2}$/.test(date)||!/^\d{2}:\d{2}(?::\d{2})?$/.test(time))throw fail();
    const [year,month,day]=date.split('-').map(Number),[hour,minute,second=0]=time.split(':').map(Number);
    if(year<1000||month<1||month>12||day<1||day>31||hour>23||minute>59||second>59)throw fail();
    const d=new Date(year,month-1,day,hour,minute,second);
    if(d.getFullYear()!==year||d.getMonth()!==month-1||d.getDate()!==day||d.getHours()!==hour||d.getMinutes()!==minute||d.getSeconds()!==second)throw fail();
    return d.toISOString();
  }
  function range(fromDate,fromTime,toDate,toTime){const from=toUtc(fromDate,fromTime),to=toUtc(toDate,toTime),span=Date.parse(to)-Date.parse(from);if(span<=0||span>31*86400000)throw fail();return {from,to};}
  function zoneLabel(value=new Date()){
    const offset=-new Date(value).getTimezoneOffset(),sign=offset>=0?'+':'-',absolute=Math.abs(offset);
    return `${Intl.DateTimeFormat().resolvedOptions().timeZone||'Local time'} (UTC${sign}${pad(Math.floor(absolute/60))}:${pad(absolute%60)})`;
  }
  return {localParts,toUtc,range,zoneLabel};
});
