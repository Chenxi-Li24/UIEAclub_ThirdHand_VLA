'use strict';
const {createPool}=require('./pool');
const {migrate}=require('./migrate');
async function main(){
  if(!process.env.MIGRATION_DATABASE_URL)throw new Error('MIGRATION_DATABASE_URL is required');
  const pool=createPool({connectionString:process.env.MIGRATION_DATABASE_URL,max:1});
  try{await migrate(pool);process.stdout.write('PostgreSQL forward migrations applied successfully.\n');}finally{await pool.end();}
}
if(require.main===module)main().catch(()=>{process.stderr.write('PostgreSQL migration failed; no automatic rollback or history deletion was attempted.\n');process.exitCode=1;});
module.exports={main};
