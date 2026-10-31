'use strict';
const {createHmac,timingSafeEqual}=require('node:crypto');
const {authorize}=require('../../identity/src/policy');
const {identityError}=require('../../identity/src/errors');
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
// Only operational records are exposed. Never accept a caller-supplied table,
// SQL identifier, field list, or identity/audit join.
const KINDS=Object.freeze({
  samples:{table:'telemetry.robot_samples',time:'captured_at',keys:[['captured_at','timestamptz'],['boot_id','uuid'],['sample_seq','bigint']],text:['sample_seq','monotonic_ns']},
  runs:{table:'ops.runs',time:'started_at',keys:[['started_at','timestamptz'],['id','uuid']]},
  commands:{table:'ops.commands',time:'created_at',keys:[['created_at','timestamptz'],['command_id','uuid']],omit:['session_id','lease_id'],text:['lease_epoch','sequence']},
  command_events:{table:'ops.command_events',time:'captured_at',keys:[['captured_at','timestamptz'],['id','bigint']],text:['id'],join:'JOIN ops.commands c ON c.command_id=t.command_id',device:'c.device_id',boot:'c.boot_id',run:'c.run_id'},
  device_events:{table:'ops.device_events',time:'captured_at',keys:[['captured_at','timestamptz'],['id','bigint']],text:['id']},
  invalid_samples:{table:'telemetry.invalid_samples',time:'received_at',keys:[['received_at','timestamptz'],['id','bigint']],text:['id','sample_seq']},
  raw_batches:{table:'telemetry.ingest_batches',time:'completed_at',keys:[['completed_at','timestamptz'],['id','uuid']],text:['batch_seq','first_seq','last_seq'],join:'JOIN telemetry.ingest_batch_payloads p ON p.batch_id=t.id',extra:", 'payload_base64',replace(encode(p.payload_bytes,'base64'),E'\\n','')"}
});
function normalizeFilter(input){
  if(!input||typeof input!=='object'||Array.isArray(input)||Object.keys(input).some(key=>!['kind','deviceId','bootId','runId','from','to'].includes(key))||!Object.hasOwn(KINDS,input.kind))throw identityError('INVALID_INPUT');
  const value={kind:input.kind};
  for(const field of ['from','to']){
    if(typeof input[field]!=='string'||input[field].length>40||!/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$/.test(input[field])||!Number.isFinite(Date.parse(input[field])))throw identityError('INVALID_INPUT');
    const fraction=(/\.(\d+)/.exec(input[field])?.[1]||'').padEnd(6,'0');
    value[field]=new Date(input[field]).toISOString().replace(/Z$/,fraction.slice(3)+'Z');
  }
  const microseconds=text=>BigInt(Date.parse(text))*1000n+BigInt(/\.(\d{6})Z$/.exec(text)[1].slice(3));
  const span=microseconds(value.to)-microseconds(value.from);if(span<=0n||span>31n*86400000000n)throw identityError('INVALID_INPUT');
  for(const field of ['deviceId','bootId','runId'])if(input[field]!==undefined&&input[field]!==null&&input[field]!==''){
    if(typeof input[field]!=='string'||!UUID.test(input[field]))throw identityError('INVALID_INPUT');value[field]=input[field].toLowerCase();
  }
  if(value.runId&&!['samples','commands','command_events'].includes(value.kind))throw identityError('INVALID_INPUT');
  return value;
}
function createHistoryRepository(pool,{cursorKey,clock={now:()=>Date.now()}}){
  if(!Buffer.isBuffer(cursorKey)||cursorKey.length<32)throw Error('Independent history cursor key required');
  const now=()=>Number(clock.now());
  let activeQueries=0;
  const mac=value=>createHmac('sha256',cursorKey).update(value).digest();
  const pack=value=>{const payload=Buffer.from(JSON.stringify(value)).toString('base64url');return payload+'.'+mac(payload).toString('base64url');};
  function unpack(token,userId,filter){
    try{
      if(typeof token!=='string'||token.length>20000)throw Error();const [payload,signature,...rest]=token.split('.');
      const actual=Buffer.from(signature||'','base64url'),expected=mac(payload);if(rest.length||actual.length!==expected.length||!timingSafeEqual(actual,expected))throw Error();
      const value=JSON.parse(Buffer.from(payload,'base64url'));
      if(value.userId!==userId||JSON.stringify(value.filter)!==JSON.stringify(filter)||value.expiresAt<=now()||!Array.isArray(value.last)||typeof value.snapshot!=='string')throw Error();return value;
    }catch{throw identityError('INVALID_CURSOR');}
  }
  async function queryPage(principal,input,{cursor,limit=200}={}){
    if(!authorize(principal,'history.read').ok)throw identityError('FORBIDDEN');
    const filter=normalizeFilter(input),definition=KINDS[filter.kind];if(!Number.isInteger(limit)||limit<1||limit>500)throw identityError('INVALID_INPUT');
    let state=cursor?unpack(cursor,principal.userId,filter):null;
    if(activeQueries>=2)throw identityError('HISTORY_BUSY');activeQueries++;
    let client;
    try{
      client=await pool.connect();
      await client.query('BEGIN READ ONLY');await client.query("SET LOCAL statement_timeout='5s'");
      if(!state){const row=(await client.query('SELECT pg_current_snapshot()::text AS snapshot,clock_timestamp()::text AS cutoff')).rows[0];state={userId:principal.userId,filter,snapshot:row.snapshot,cutoff:row.cutoff,expiresAt:now()+2*3600000,last:[]};}
      const values=[],bind=(value,type)=>{values.push(value);return '$'+values.length+(type?'::'+type:'');};
      const where=[`t.${definition.time}>=${bind(filter.from,'timestamptz')}`,`t.${definition.time}<${bind(filter.to,'timestamptz')}`];
      // Immutable source rows inserted/backfilled after the first page cannot
      // enter this traversal. Runs/commands can change status; their ordering
      // keys are immutable, and the UI states these statuses are current reads.
      if(['runs','commands'].includes(filter.kind))where.push(`t.${definition.time}<=${bind(state.cutoff,'timestamptz')}`);
      else where.push(`pg_visible_in_snapshot(t.xmin::text::xid8,${bind(state.snapshot,'pg_snapshot')})`);
      for(const [field,column] of [['deviceId',definition.device||'t.device_id'],['bootId',definition.boot||'t.boot_id']])if(filter[field])where.push(`${column}=${bind(filter[field],'uuid')}`);
      if(filter.runId)where.push(`${definition.run||'t.run_id'}=${bind(filter.runId,'uuid')}`);
      if(state.last.length){if(state.last.length!==definition.keys.length)throw identityError('INVALID_CURSOR');where.push(`(${definition.keys.map(([key])=>'t.'+key).join(',')})>(${definition.keys.map(([,type],i)=>bind(state.last[i],type)).join(',')})`);}
      const base=`to_jsonb(t)${(definition.omit||[]).map(key=>`-'${key}'`).join('')}`;
      // bigint counters/nanosecond clocks must never round through JS Number.
      const record=definition.text?`(${base} || jsonb_build_object(${definition.text.map(key=>`'${key}',t.${key}::text`).join(',')}))`:base;
      const select=definition.extra?`(${record} || jsonb_build_object('time_basis','${definition.time}'${definition.extra}))`:record;
      const keys=`jsonb_build_array(${definition.keys.map(([key])=>`t.${key}::text`).join(',')})`;
      const pageLimit=Math.min(limit,filter.kind==='raw_batches'?4:['command_events','device_events','invalid_samples','commands'].includes(filter.kind)?20:50);
      const result=await client.query(`SELECT ${select} AS record,${keys} AS cursor_keys FROM ${definition.table} t ${definition.join||''} WHERE ${where.join(' AND ')} ORDER BY ${definition.keys.map(([key])=>'t.'+key).join(',')} LIMIT ${bind(pageLimit+1,'integer')}`,values);
      await client.query('COMMIT');const selected=[];let bytes=0;
      for(const row of result.rows.slice(0,pageLimit)){const size=Buffer.byteLength(JSON.stringify(row.record));if(bytes+size>2097152&&selected.length)break;selected.push(row);bytes+=size;}
      return {kind:filter.kind,timeBasis:definition.time,from:filter.from,to:filter.to,pageLimit,rows:selected.map(row=>row.record),nextCursor:result.rows.length>selected.length?pack({...state,last:selected.at(-1).cursor_keys}):null,units:{jointPosition:'rad',jointVelocity:'rad/s',tcpPosition:'m',time:'UTC'},statusSemantics:['runs','commands'].includes(filter.kind)?'current_status':'immutable_source'};
    }catch(error){await client?.query('ROLLBACK').catch(()=>{});throw error;}finally{client?.release();activeQueries--;}
  }
  return {queryPage,normalizeFilter,kinds:Object.keys(KINDS)};
}
module.exports={createHistoryRepository,normalizeFilter};
