'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {createRobotViewer}=require('../../../apps/web/public/js/robot-viewer');
test('creating shared viewer classes and applying a model pose has no transport dependency',()=>{
  const {ArmModel,SceneManager}=createRobotViewer({THREE:{}});assert.equal(typeof SceneManager,'function');
  const arm=Object.create(ArmModel.prototype),values=[];
  Object.assign(arm,{robot:{joints:Object.fromEntries(Array.from({length:6},(_,i)=>[`joint${i+1}`,{setJointValue:value=>values[i]=value}]))},jointNames:['joint1','joint2','joint3','joint4','joint5','joint6'],jointAngles:[0,0,0,0,0,0],jointLimits:[[-162,162],[-12,201],[-183,0],[-98,98],[-98,98],[-164,164]]});
  arm.setJointAngles([0,90,-90,0,0,0]);assert.equal(values[1],Math.PI/2);assert.equal(values[2],-Math.PI/2);
  assert.deepEqual(arm.getJointAngles(),[0,90,-90,0,0,0]);
});
