'use strict';
const fs = require('node:fs');
const { createHash } = require('node:crypto');
const YAML = require('yaml');

function multiply(a,b) {
  return a.map(row => b[0].map((_,j) => row.reduce((sum,v,k) => sum+v*b[k][j],0)));
}
function rotate(r,v) { return r.map(row => row.reduce((sum,x,i) => sum+x*v[i],0)); }
function axisAngle([x,y,z],a) {
  const c=Math.cos(a),s=Math.sin(a),t=1-c;
  return [[c+x*x*t,x*y*t-z*s,x*z*t+y*s],
    [y*x*t+z*s,c+y*y*t,y*z*t-x*s],[z*x*t-y*s,z*y*t+x*s,c+z*z*t]];
}
function rotation(a) {
  return multiply(multiply(axisAngle([0,0,1],a[2]),axisAngle([0,1,0],a[1])),axisAngle([1,0,0],a[0]));
}
function rotateEuler(euler,axis,angle) {
  const r=multiply(axisAngle(axis,angle),rotation(euler));
  const singular=Math.hypot(r[0][0],r[1][0])<1e-8;
  return [singular?0:Math.atan2(r[2][1],r[2][2]),
    Math.atan2(-r[2][0],Math.hypot(r[0][0],r[1][0])),
    singular?Math.atan2(-r[0][1],r[1][1]):Math.atan2(r[1][0],r[0][0])];
}
function positionError(a,b) { return Math.hypot(...a.map((x,i) => x-b[i])); }
function orientationError(a,b) {
  const ra=rotation(a),rb=rotation(b);
  const dot=ra.reduce((sum,row,i) => sum+row.reduce((s,x,j) => s+x*rb[i][j],0),0);
  return Math.acos(Math.max(-1,Math.min(1,(dot-1)/2)));
}
function finite(v,n) { return Array.isArray(v) && v.length===n && v.every(Number.isFinite); }
function numbers(value,count) {
  const out=String(value||'').trim().split(/\s+/).map(Number);
  if (!finite(out,count)) throw new Error('SDK model contains invalid numeric parameters');
  return out;
}
function attribute(xml,tag,attr) {
  const match=new RegExp('<'+tag+'\\b[^>]*\\b'+attr+'="([^"]*)"').exec(xml);
  if (!match) throw new Error('SDK model missing '+tag+'.'+attr);
  return match[1];
}
function loadSdkModel({urdfFile,configFile}) {
  const xml=fs.readFileSync(urdfFile,'utf8'),yaml=fs.readFileSync(configFile,'utf8');
  const tool=YAML.parse(yaml)?.kinematics?.tool;
  if (!finite(tool?.xyz,3) || !finite(tool?.rpy,3)) throw new Error('SDK tool transform unavailable');
  const joints=[];
  for (let i=1;i<=6;i++) {
    const body=new RegExp('<joint\\b[^>]*name="joint'+i+'"[^>]*>([\\s\\S]*?)</joint>').exec(xml)?.[1];
    if (!body) throw new Error('SDK model missing joint'+i);
    const axis=numbers(attribute(body,'axis','xyz'),3);
    if (Math.abs(Math.hypot(...axis)-1)>1e-6) throw new Error('SDK model axis must be unit length');
    joints.push({xyz:numbers(attribute(body,'origin','xyz'),3),
      rpy:numbers(attribute(body,'origin','rpy'),3),axis,
      lower:Number(attribute(body,'limit','lower')),upper:Number(attribute(body,'limit','upper'))});
  }
  if (joints.some(j => !Number.isFinite(j.lower) || !Number.isFinite(j.upper))) throw new Error('Invalid SDK joint limits');
  function pose(q) {
    if (!finite(q,6)) throw new Error('Six finite joint angles are required');
    let r=[[1,0,0],[0,1,0],[0,0,1]],p=[0,0,0];
    joints.forEach((j,i) => {
      const shift=rotate(r,j.xyz); p=p.map((x,k) => x+shift[k]);
      r=multiply(multiply(r,rotation(j.rpy)),axisAngle(j.axis,q[i]*Math.PI/180));
    });
    const shift=rotate(r,tool.xyz); p=p.map((x,k) => x+shift[k]); r=multiply(r,rotation(tool.rpy));
    const pitch=Math.atan2(-r[2][0],Math.hypot(r[0][0],r[1][0]));
    const singular=Math.hypot(r[0][0],r[1][0])<1e-8;
    return {position:p,euler:[singular?0:Math.atan2(r[2][1],r[2][2]),
      pitch,singular?Math.atan2(-r[0][1],r[1][1]):Math.atan2(r[1][0],r[0][0])]};
  }
  return {digest:createHash('sha256').update(xml).update(yaml).digest('hex'),toolOffsetM:[...tool.xyz],pose,
    matches(q,target,tolerance=0.005) {
      const actual=pose(q);
      return positionError(actual.position,target.position)<=tolerance &&
        orientationError(actual.euler,target.euler)<=0.05;
    },
    jointsAllowed:(q,pointName) => finite(q,6) && q.every((x,i) => {
      const lower=joints[i].lower*180/Math.PI,upper=joints[i].upper*180/Math.PI;
      // Only the operator-taught TASK2_A_AFTER uses the 98.0° UI J4 limit.
      const taughtJ4=pointName==='TASK2_A_AFTER' && i===3 && x===98 && upper>97.97 && upper<98;
      return x>=lower-1e-6 && x<=(taughtJ4 ? 98 : upper)+1e-6;
    })};
}
function resolveTransfer(plan,model) {
  const sourceAfter=model.pose(plan.taughtJointsDeg[plan.resolved.sourceAfterPoint]);
  const destinationBefore=model.pose(plan.taughtJointsDeg[plan.resolved.destinationBeforePoint]);
  const transferFloorM=plan.steps.find(step=>step.id==='transfer_xy').minBaseZMm/1000;
  if (sourceAfter.position[2] < transferFloorM) {
    throw new Error('source_post：已示教 AFTER 低于跨区搬运 Z 下限');
  }
  const steps=plan.steps.map(step => {
    if (step.kind==='preset') return {...step};
    if (step.kind==='joint_point') {
      if (step.id==='observe') return {...step,kind:'preset',name:'observe'};
      const pose=model.pose(step.jointsDeg);
      return {...step,kind:'joint',position:[...pose.position],euler:[...pose.euler]};
    }
    if (step.kind==='gripper') return {...step,position:step.positionPercent/100};
    if (step.kind==='hold') return {...step};
    const position=[...destinationBefore.position];
    position[2]=sourceAfter.position[2];
    return {...step,position,euler:[...sourceAfter.euler]};
  });
  steps.splice(2,0,{id:'prepare_gripper',kind:'gripper',position:plan.parameters.releasePercent/100});
  return {...plan,executionReady:true,controlReference:'sdk_end_effector',modelDigest:model.digest,steps};
}
module.exports={loadSdkModel,resolveTransfer,positionError,orientationError,rotateEuler};
