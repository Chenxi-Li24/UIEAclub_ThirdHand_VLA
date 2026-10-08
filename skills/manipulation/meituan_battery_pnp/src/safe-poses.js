'use strict';
const {orientationError,rotateEuler}=require('./sdk-model');
const MAX_TILT=5*Math.PI/180;
const MAX_SHORTFALL_MM=5;
const FLEXIBLE=new Set(['source_post','destination_post','align_destination']);
function safetyPoseAllowed(model,q,step) {
  return model.jointsAllowed(q) && model.matches(q,step,0.005) &&
    (!step.safetyReferenceEuler ||
      orientationError(model.pose(q).euler,step.safetyReferenceEuler)<=MAX_TILT+1e-8);
}
async function resolveSafetyPoses(route,model,preview,guard) {
  // A shared transport plane must be reachable at both ends. Never lower only
  // the destination after accepting a source lift and call that horizontal.
  let failure;
  for(let planeShortfall=0;planeShortfall<=MAX_SHORTFALL_MM;planeShortfall++){
    try{return await resolveAtPlane(route,model,preview,guard,planeShortfall);}
    catch(error){
      if(!['transfer_xy','align_destination'].includes(error.stepId))throw error;
      failure=error;
    }
  }
  throw failure;
}
async function resolveAtPlane(route,model,preview,guard,planeShortfall) {
  const resolved=structuredClone(route),adjustments=[];
  let sourcePost;
  for(const step of resolved.steps) {
    if(step.kind!=='cartesian')continue;
    const nominalZ=step.position[2];
    if(step.id==='source_post')step.position[2]-=planeShortfall/1000;
    if(step.id==='transfer_xy' || step.id==='align_destination')step.position[2]=sourcePost.position[2];
    if(step.id==='transfer_xy'){
      step.euler=[...sourcePost.euler];
      step.safetyReferenceEuler=[...sourcePost.safetyReferenceEuler];
    }
    const flexible=FLEXIBLE.has(step.id),reference=[...step.euler];
    if(flexible)step.safetyReferenceEuler=reference;
    const attempt=async target=>{
      guard(target);
      const ik=await preview(target.position,target.euler);
      return {ik,ok:ik.ok && safetyPoseAllowed(model,ik.jointsDeg,target)};
    };
    const first=await attempt(step);
    let selected=first.ok?step:null;
    if(!selected && flexible) {
      const source=step.id==='source_post';
      const q=source?route.contactJointsDeg.source:route.contactJointsDeg.destination;
      const yaw=q[0]*Math.PI/180,axis=[-Math.sin(yaw),Math.cos(yaw),0];
      const orientations=[];
      if(first.ik.ok && model.jointsAllowed(first.ik.jointsDeg)){
        const hint=model.pose(first.ik.jointsDeg).euler;
        if(orientationError(hint,reference)<=MAX_TILT+1e-8)orientations.push(hint);
      }
      for(let deg=1;deg<=5;deg++)for(const sign of [1,-1])
        orientations.push(rotateEuler(reference,axis,sign*deg*Math.PI/180));
      const shortfallLimit=step.id==='align_destination'?0:
        Math.min(MAX_SHORTFALL_MM-(source?planeShortfall:0),route.parameters.postAboveMm);
      for(let shortfall=0;shortfall<=shortfallLimit && !selected;shortfall++) {
        const candidates=shortfall===0?orientations:[reference,...orientations];
        for(const euler of candidates) {
          if(orientationError(euler,reference)>MAX_TILT+1e-8)continue;
          const target={...step,position:step.position.map((x,i)=>i===2?x-shortfall/1000:x),euler:[...euler]};
          if((await attempt(target)).ok){selected=target;break;}
        }
      }
    }
    if(!selected){
      const error=new Error(step.id+'：'+(first.ik.reason || 'IK 解未满足目标位姿（安全段最多5°、上抬最多缩短5mm）'));
      error.stepId=step.id;throw error;
    }
    const shortfall=((step.id==='source_post'?nominalZ:step.position[2])-selected.position[2])*1000;
    const tiltDeg=orientationError(selected.euler,reference)*180/Math.PI;
    if(shortfall>1e-6 || tiltDeg>1e-5)adjustments.push({
      step:step.id,tiltDeg,shortfallMm:shortfall,
      ...(step.id==='align_destination'?{}:{liftMm:route.parameters.postAboveMm-shortfall}),
    });
    Object.assign(step,selected);
    if(flexible && tiltDeg>1e-5)step.preserveContactOrientation=false;
    if(step.id==='source_post')sourcePost=step;
  }
  resolved.safetyAdjustments=adjustments;
  return resolved;
}
module.exports={resolveSafetyPoses,safetyPoseAllowed};
