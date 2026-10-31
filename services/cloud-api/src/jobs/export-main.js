'use strict';
const {loadCloudConfig}=require('../config');
const {createPool}=require('../../../../platform/storage/src/pool');
const {createHistoryRepository}=require('../../../../platform/storage/src/history');
const {createExportService}=require('./export-worker');
async function startExportWorker(config=loadCloudConfig()){
  if(!config.exportRoot)throw Error('Private export directory required');
  const pool=createPool({connectionString:config.databaseUrl,max:2}),history=createHistoryRepository(pool,{cursorKey:config.historyCursorKey}),worker=createExportService({pool,history,root:config.exportRoot});let stopping=false;
  const stop=()=>{stopping=true;};process.once('SIGTERM',stop);process.once('SIGINT',stop);
  try{await worker.recoverInterrupted();while(!stopping){const job=await worker.runNext();if(!job)await new Promise(resolve=>setTimeout(resolve,1000));}}finally{process.off('SIGTERM',stop);process.off('SIGINT',stop);await pool.end();}
}
if(require.main===module)startExportWorker().catch(()=>{process.stderr.write('Export worker unavailable.\n');process.exitCode=1;});
module.exports={startExportWorker};
