'use strict';
const fs=require('node:fs/promises');
const path=require('node:path');
const {createPool}=require('../../storage/src/pool');
const {createAdminAccess}=require('../../storage/src/admin-access');

async function main(args=process.argv.slice(2),env=process.env){
  const [filename,confirmation]=args;
  if(args.length!==2||!filename||!path.isAbsolute(filename)||confirmation!=='--confirm-initial-admins')throw Error('Usage: initial-admins <absolute-private-list.json> --confirm-initial-admins');
  const stat=await fs.lstat(filename);
  if(!stat.isFile()||stat.isSymbolicLink()||stat.size>32768||process.platform!=='win32'&&(stat.mode&0o077))throw Error('Private regular list file required (0600 on Linux)');
  const emails=JSON.parse(await fs.readFile(filename,'utf8'));
  const pool=createPool({connectionString:env.MIGRATION_DATABASE_URL,max:1});
  try{
    const result=await createAdminAccess(pool).applyInitialAdmins({emails});
    process.stdout.write(`Initial administrator batch saved: ${result.count}; verified accounts claimed: ${result.promoted}; list sealed. Others must verify their email first. MFA is still required.\n`);
  }finally{await pool.end();}
}
if(require.main===module)main().catch(error=>{process.stderr.write(`Initial administrator import failed: ${['BOOTSTRAP_CLOSED','INVALID_STATE','INVALID_INPUT'].includes(error.code)?error.code:'CHECK_PRIVATE_CONFIGURATION'}\n`);process.exitCode=1;});
module.exports={main};
