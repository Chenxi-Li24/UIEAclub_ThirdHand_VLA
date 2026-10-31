'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const os=require('node:os');
const path=require('node:path');
const {randomBytes}=require('node:crypto');
const {createVisionService}=require('../../../services/vision/src/server');
test('private media source requires a loopback transport credential and shares the existing camera once',async t=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'thirdhand-camera-'));t.after(async()=>{const target=path.resolve(dir);assert.equal(path.dirname(target),path.resolve(os.tmpdir()));assert.match(path.basename(target),/^thirdhand-camera-/);await fs.rm(target,{recursive:true,force:true});});
  const clients=new Set(),token=randomBytes(32).toString('hex');let started=0,subscribed=0;
  const camera={start(){started++;},status(){return {camera:{status:'ready'},inference:{status:'unavailable'}};},subscribe(kind,response){assert.equal(kind,'raw');subscribed++;clients.add(response);response.write('--frame\r\nContent-Type: image/jpeg\r\nContent-Length: 4\r\nX-ThirdHand-Sequence: 1\r\n\r\njpeg\r\n');return true;},unsubscribe(kind,response){clients.delete(response);},async close(){for(const response of clients)response.end();}};
  const service=createVisionService({camera,host:'127.0.0.1',port:0,readyFile:path.join(dir,'ready'),edgeMediaToken:token});const address=await service.start();t.after(()=>service.close());
  const url=`http://127.0.0.1:${address.port}/edge-media/v1/raw`;
  assert.equal((await fetch(url)).status,403);assert.equal((await fetch(url,{headers:{'x-thirdhand-media-token':token,origin:'https://other.invalid'}})).status,403);
  const stream=await fetch(url,{headers:{'x-thirdhand-media-token':token}});assert.equal(stream.status,200);assert.equal(subscribed,1);assert.equal(started,1);
  assert.equal((await fetch(url,{headers:{'x-thirdhand-media-token':token}})).status,429);assert.equal(started,1);await stream.body.cancel();
});
