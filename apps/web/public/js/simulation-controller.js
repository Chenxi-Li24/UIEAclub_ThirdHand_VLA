/* Model-only operation: intentionally accepts no command transport or SDK adapter. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandSimulation=api;})(globalThis,function(){
  'use strict';
  const PRESETS=Object.freeze({zero:[0,0,0,0,0,0],ready:[0,90,-90,0,0,0],inspect:[30,70,-110,20,0,0]});
  function createSimulationController({armModel,clock={now:()=>performance.now(),sleep:ms=>new Promise(resolve=>setTimeout(resolve,ms))},onChange=()=>{}}){
    let generation=0,followingLive=false,playing=false,outcome='idle';const listeners=new Set();
    const validate=angles=>{
      if(!Array.isArray(angles)||angles.length!==6||!Array.from(angles).every(Number.isFinite))throw new Error('Invalid finite joint angles');
      angles.forEach((value,index)=>{const [min,max]=armModel.jointLimits[index];if(value<min||value>max)throw new Error(`Joint ${index+1} exceeds its range limit`);});
      return Array.from(angles);
    };
    const snapshot=()=>({joints:armModel.getJointAngles(),gripper:armModel.getGripperPosition?.(),playing,followingLive,outcome});
    const notify=()=>{onChange(snapshot());for(const listener of listeners)listener(snapshot());};
    const publish=angles=>{armModel.setJointAngles(angles);notify();};
    function stop(){generation++;playing=false;outcome='stopped';notify();}
    async function playSequence(sequence){
      if(!Array.isArray(sequence)||!sequence.length||sequence.length>256)throw new Error('Invalid simulation sequence');
      const steps=sequence.map(step=>{
        if(!Number.isFinite(step.durationMs)||step.durationMs<16||step.durationMs>30000)throw new Error('Invalid sequence duration');
        if(step.gripper!==undefined&&(!Number.isFinite(step.gripper)||step.gripper<0||step.gripper>1||typeof armModel.getGripperPosition!=='function'||typeof armModel.setGripperPosition!=='function'))throw new Error('Invalid model gripper');
        return {joints:validate(step.joints),durationMs:step.durationMs,gripper:step.gripper};
      });
      if(steps.reduce((sum,step)=>sum+step.durationMs,0)>600000)throw new Error('Simulation sequence too long');
      stop();followingLive=false;playing=true;outcome='playing';const token=generation;
      try{
      for(const step of steps){
        const from=armModel.getJointAngles(),fromGripper=step.gripper===undefined?null:armModel.getGripperPosition(),started=clock.now();let elapsed=0;
        if(step.gripper!==undefined&&(!Number.isFinite(fromGripper)||fromGripper<0||fromGripper>1))throw Error('Invalid current model gripper');
        while(elapsed<step.durationMs){
          if(token!==generation)return {completed:false};
          const fraction=Math.min(1,elapsed/step.durationMs);
          if(step.gripper!==undefined)armModel.setGripperPosition(fromGripper+(step.gripper-fromGripper)*fraction);
          publish(step.joints.map((target,index)=>from[index]+(target-from[index])*fraction));
          await clock.sleep(Math.min(16,step.durationMs-elapsed));elapsed=Math.max(0,clock.now()-started);
        }
        if(token!==generation)return {completed:false};if(step.gripper!==undefined)armModel.setGripperPosition(step.gripper);publish(step.joints);
      }
      playing=false;outcome='completed';notify();return {completed:true};
      }catch(error){if(token===generation){playing=false;outcome='failed';notify();}throw error;}
    }
    return {
      setJoints(angles){const validated=validate(angles);stop();followingLive=false;outcome='idle';publish(validated);},
      playPreset(name){if(!Object.hasOwn(PRESETS,name))throw new Error('Unknown simulation preset');return playSequence([{joints:PRESETS[name],durationMs:400}]);},
      playSequence,stop,
      followLive(enabled){stop();followingLive=enabled===true;},
      receiveLive(angles){if(!followingLive)return false;try{publish(validate(angles));return true;}catch{return false;}},
      getState:snapshot,
      subscribe(listener){listeners.add(listener);return ()=>listeners.delete(listener);}
    };
  }
  return {createSimulationController};
});
