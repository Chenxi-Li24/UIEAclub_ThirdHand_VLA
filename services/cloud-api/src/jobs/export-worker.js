'use strict';
// Run workers in a separate process. HTTP only enqueues/authorizes downloads.
const fs=require('node:fs/promises');
const constants=require('node:fs').constants;
const path=require('node:path');
const {createHash}=require('node:crypto');
const {authorize}=require('../../../../platform/identity/src/policy');
const {identityError}=require('../../../../platform/identity/src/errors');
const {normalizeFilter}=require('../../../../platform/storage/src/history');
const {csvCell,csvHeader,csvRow,operationalColumns}=require('../table-export');
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
function createExportService({pool,history,root,maxRows=2000000,maxBytes=536870912,maxDurationMs=120000}){
  if(typeof root!=='string'||!path.isAbsolute(root)||root.includes('\0'))throw Error('Absolute private export directory required');
  root=path.resolve(root);const publicRoot=path.resolve(__dirname,'../../../../apps/web/public');
  if(root===publicRoot||root.startsWith(publicRoot+path.sep))throw Error('Exports cannot be web assets');
  const allowed=principal=>{if(!authorize(principal,'history.export').ok)throw identityError('FORBIDDEN');};
  const publicJob=row=>({id:row.id,status:row.expires_at&&Date.parse(row.expires_at)<=Date.now()?'expired':row.status,format:row.format,filter:row.filter,rowCount:row.row_count,digest:row.digest,expiresAt:row.expires_at,errorCode:row.error_code||null});
  async function transaction(fn){const client=await pool.connect();try{await client.query('BEGIN');await client.query('SELECT pg_advisory_xact_lock(240103,8)');const value=await fn(client);await client.query('COMMIT');return value;}catch(error){await client.query('ROLLBACK').catch(()=>{});throw error;}finally{client.release();}}
  async function find(principal,id){allowed(principal);if(typeof id!=='string'||!UUID.test(id))throw identityError('INVALID_INPUT');const row=(await pool.query('SELECT * FROM ops.export_jobs WHERE id=$1 AND user_id=$2',[id,principal.userId])).rows[0];if(!row)throw identityError('NOT_FOUND');return row;}
  async function prepareRoot(){await fs.mkdir(root,{recursive:true,mode:0o700});const stat=await fs.lstat(root);if(!stat.isDirectory()||stat.isSymbolicLink()||process.platform!=='win32'&&(stat.mode&0o077))throw Error('Private owner-only export directory required');if(await fs.realpath(root)!==root)throw Error('Export directory cannot traverse symlinks');}
  return {
    async create(principal,{filter,format}={}){
      allowed(principal);filter=normalizeFilter(filter);if(!['csv','ndjson'].includes(format))throw identityError('INVALID_INPUT');
      return transaction(async client=>{const rows=(await client.query("SELECT user_id FROM ops.export_jobs WHERE status IN ('queued','running') AND expires_at>now()")).rows;
        if(rows.length>=20||rows.filter(row=>row.user_id===principal.userId).length>=3)throw identityError('EXPORT_BUSY');
        return publicJob((await client.query("INSERT INTO ops.export_jobs(user_id,filter,format,status,expires_at) VALUES($1,$2,$3,'queued',now()+interval '24 hours') RETURNING *",[principal.userId,filter,format])).rows[0]);});
    },
    async status(principal,id){return publicJob(await find(principal,id));},
    async open(principal,id){
      const row=await find(principal,id);if(Date.parse(row.expires_at)<=Date.now())throw identityError('EXPORT_EXPIRED');if(row.status!=='completed'||row.private_object_key!==row.id)throw identityError('EXPORT_NOT_READY');
      await prepareRoot();const filename=path.join(root,row.id),handle=await fs.open(filename,constants.O_RDONLY|(constants.O_NOFOLLOW||0));
      try{const stat=await handle.stat();if(!stat.isFile())throw Error('Invalid export file');return {handle,size:stat.size,format:row.format,digest:row.digest,id:row.id};}catch(error){await handle.close();throw error;}
    },
    async recoverInterrupted(){
      // Never resume an incomplete export with a new snapshot or publish its
      // partial file. Old private artifacts require an explicit cleanup task.
      return pool.query("UPDATE ops.export_jobs SET status='failed',error_code='EXPORT_WORKER_INTERRUPTED' WHERE status='running' AND heartbeat_at<now()-interval '10 minutes'");
    },
    async runNext(){
      const job=await transaction(async client=>{
        if(Number((await client.query("SELECT count(*) FROM ops.export_jobs WHERE status='running'")).rows[0].count)>=2)return null;
        const row=(await client.query("SELECT * FROM ops.export_jobs WHERE status='queued' AND expires_at>now() ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1")).rows[0];if(!row)return null;
        await client.query("UPDATE ops.export_jobs SET status='running',started_at=now(),heartbeat_at=now() WHERE id=$1",[row.id]);return row;
      });
      if(!job)return null;let file,rows=0,bytes=0,cursor=null;const started=performance.now(),digest=createHash('sha256'),temporary=path.join(root,job.id+'.partial'),destination=path.join(root,job.id);
      try{
        await prepareRoot();file=await fs.open(temporary,'wx',0o600);
        const write=async text=>{const chunk=Buffer.from(text);bytes+=chunk.length;if(bytes>maxBytes||performance.now()-started>maxDurationMs)throw identityError('EXPORT_LIMIT_EXCEEDED');digest.update(chunk);await file.writeFile(chunk);};
        const columns=job.format==='csv'?operationalColumns(job.filter.kind):null;
        if(columns)await write(csvHeader(columns));else await write(JSON.stringify({type:'metadata',schema:1,filter:job.filter,units:{jointPosition:'rad',tcpPosition:'m',time:'UTC'}})+'\n');
        const principal={userId:job.user_id,sessionId:'export-worker',role:'observer',mode:'observe'};
        do{
          const page=await history.queryPage(principal,job.filter,{cursor,limit:500});
          for(const record of page.rows){if(++rows>maxRows)throw identityError('EXPORT_LIMIT_EXCEEDED');await write(columns?csvRow(columns,record):JSON.stringify({type:'record',kind:job.filter.kind,record})+'\n');}
          cursor=page.nextCursor;await pool.query("UPDATE ops.export_jobs SET heartbeat_at=now() WHERE id=$1 AND status='running'",[job.id]);
        }while(cursor);
        if(job.format==='ndjson')await write(JSON.stringify({type:'summary',rowCount:rows})+'\n');
        await file.sync();await file.close();file=null;await fs.rename(temporary,destination);
        await pool.query("UPDATE ops.export_jobs SET status='completed',private_object_key=id::text,row_count=$2,digest=$3,completed_at=now() WHERE id=$1 AND status='running'",[job.id,rows,digest.digest('hex')]);
      }catch(error){
        await file?.close().catch(()=>{});await fs.unlink(temporary).catch(()=>{});
        await pool.query("UPDATE ops.export_jobs SET status='failed',error_code=$2,completed_at=now() WHERE id=$1 AND status='running'",[job.id,error.code==='EXPORT_LIMIT_EXCEEDED'?error.code:'EXPORT_WORKER_FAILED']);
      }
      return publicJob((await pool.query('SELECT * FROM ops.export_jobs WHERE id=$1',[job.id])).rows[0]);
    }
  };
}
module.exports={createExportService,csvCell};
