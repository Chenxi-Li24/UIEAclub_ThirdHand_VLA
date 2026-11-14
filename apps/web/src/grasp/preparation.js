'use strict';
const {gripTargetToFlangePose}=require('../../../../skills/manipulation/bottlegrasp/src/thirdhand_va/action/grasp/grip_transform');
const wrap=a=>Math.atan2(Math.sin(a),Math.cos(a));
function quaternion([r,p,y]){
 const [cr,sr,cp,sp,cy,sy]=[Math.cos(r/2),Math.sin(r/2),Math.cos(p/2),Math.sin(p/2),Math.cos(y/2),Math.sin(y/2)];
 return [cr*cp*cy+sr*sp*sy,sr*cp*cy-cr*sp*sy,cr*sp*cy+sr*cp*sy,cr*cp*sy-sr*sp*cy];
}
function euler([w,x,y,z]){return [Math.atan2(2*(w*x+y*z),1-2*(x*x+y*y)),
 Math.asin(Math.max(-1,Math.min(1,2*(w*y-z*x)))),Math.atan2(2*(w*z+x*y),1-2*(y*y+z*z))];}
function slerp(a,b,t){
 let dot=a.reduce((s,x,i)=>s+x*b[i],0);if(dot<0){b=b.map(x=>-x);dot=-dot;}
 const theta=Math.acos(Math.min(1,dot));
 const q=theta<1e-8?a.map((x,i)=>x+(b[i]-x)*t):a.map((x,i)=>(Math.sin((1-t)*theta)*x+Math.sin(t*theta)*b[i])/Math.sin(theta));
 const norm=Math.hypot(...q);return q.map(x=>x/norm);
}
function sampleSdkPath(from,to,config){
 const qa=quaternion(from.euler),qb=quaternion(to.euler);
 const angle=2*Math.acos(Math.min(1,Math.abs(qa.reduce((s,x,i)=>s+x*qb[i],0))));
 const length=Math.hypot(...to.position.map((x,i)=>x-from.position[i]));
 const n=Math.max(1,Math.ceil(length/config.segmentM),Math.ceil(angle/.02));
 if(n>200)throw Object.assign(Error('path_too_long'),{code:'path_too_long'});
 return Array.from({length:n},(_,i)=>({position:from.position.map((x,j)=>Number((x+(to.position[j]-x)*(i+1)/n).toFixed(12))),
  euler:i===n-1?[...to.euler]:angle<1e-8?[...from.euler]:euler(slerp(qa,qb,(i+1)/n))}));
}
function buildPreparation(robot,config){
 const {validateConfig,assertMotionStart,currentGripPose}=require('./geometry');
 validateConfig(config);assertMotionStart(robot,config);
 if(!config.autoLevelBeforeDepth)return [];
 const grip=currentGripPose(robot,config),tol=config.horizontalToleranceRad??.05;
 if(grip.eulerRad.slice(0,2).every(a=>Math.abs(wrap(a))<=tol))return [];
 const flangeToGrip=config.T_flange_grasp_tcp||[[1,0,0,config.gripOffsetM],[0,1,0,0],[0,0,1,0],[0,0,0,1]];
 const target=gripTargetToFlangePose({positionM:grip.positionM,eulerRad:[0,0,grip.eulerRad[2]]},flangeToGrip);
 const from={position:[...robot.flange_position_m],euler:[...robot.flange_euler_rad]};
 const qa=quaternion(from.euler),qb=quaternion(target.eulerRad);
 const angle=2*Math.acos(Math.min(1,Math.abs(qa.reduce((s,x,i)=>s+x*qb[i],0))));
 if(angle>Math.PI/3)throw Object.assign(Error('leveling_angle_limit'),{code:'leveling_angle_limit'});
 // One millimetre of reach-tolerance headroom keeps the minimum safe-height
 // invariant strict even if the native trajectory settles slightly short.
 const raised={position:from.position.map((x,i)=>i===2?Math.max(x,config.safeLevelSdkZM+Math.min(.001,config.positionToleranceM??.001)):x),euler:[...from.euler]};
 // SDK move_l interpolates translation linearly and attitude by quaternion
 // slerp. Level around its fixed endpoint, not an unimplemented TCP pivot.
 const level={position:[...raised.position],euler:[...target.eulerRad]};
 const phases=[];
 if(raised.position[2]>from.position[2]+1e-9)phases.push({phase:'preparing_raise',from,path:sampleSdkPath(from,raised,config)});
 phases.push({phase:'preparing_level',from:raised,path:sampleSdkPath(raised,level,config)});
 for(const {path} of phases)for(const pose of path)assertMotionStart({...robot,flange_position_m:pose.position,flange_euler_rad:pose.euler},config);
 return phases;
}
module.exports={buildPreparation,sampleSdkPath};
