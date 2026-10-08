'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {CameraProcess}=require('../../../services/vision/src/camera-process');
test('battery events never update bottle detection, selection, or its broadcast channel',()=>{
 const camera=new CameraProcess({});
 const battery=[],bottle=[];
 camera.on('meituan',value=>battery.push(value));
 camera.on('event',value=>bottle.push(value));
 camera._handleEvent(JSON.stringify({type:'detection_result',stableId:1}));
 const saved=camera.lastDetection;
 camera._handleEvent(JSON.stringify({type:'meituan_ready'}));
 camera._handleEvent(JSON.stringify({type:'meituan_result',detections:[{color:'red'}]}));
 assert.equal(battery.length,2);
 assert.equal(bottle.length,1);
 assert.strictEqual(camera.lastDetection,saved);
 assert.equal(camera.meituanReady,true);
});

test('camera error invalidates shared battery hook readiness',()=>{
 const camera=new CameraProcess({});
 camera._handleEvent(JSON.stringify({type:'meituan_ready'}));
 camera._setProcessError(new Error('bridge gone'));
 assert.equal(camera.meituanReady,false);
});
