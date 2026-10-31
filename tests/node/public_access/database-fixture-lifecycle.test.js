'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {isolatedDatabase}=require('./database-fixture');
const {Pool}=require('pg');

test('isolated database cleanup waits for actual client disconnection before dropping its database',async()=>{
  const hooks=[],pool=await isolatedDatabase({after:fn=>hooks.push(fn)});
  const observer=new Pool({connectionString:process.env.TEST_DATABASE_URL,max:1});
  const client=await pool.connect(),name=(await client.query('SELECT current_database() AS name')).rows[0].name;
  const errors=[];client.on('error',error=>errors.push(error.code));
  const end=client.end.bind(client);
  let release,called;
  const hold=new Promise(resolve=>release=resolve),ending=new Promise(resolve=>called=resolve);
  // pg Pool.end can resolve after removing its final client while its TCP
  // termination is still pending. Hold that real transport close deliberately.
  client.end=callback=>{called();hold.then(()=>end(callback));};
  client.release();
  const cleaning=hooks[0]();
  try{
    await ending;
    const exists=await observer.query('SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname=$1) AS alive',[name]);
    assert.equal(exists.rows[0].alive,true,'database dropped while its client transport was still closing');
  }finally{
    release();await cleaning;await observer.end();
  }
  assert.deepEqual(errors,[],'normal cleanup must not force-terminate an idle test client');
});
