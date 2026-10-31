'use strict';

const {validateStopEvidence}=require('./stop-evidence');
const UUID=/^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i;
const HASH=/^[a-f0-9]{64}$/;

// Local trusted callbacks only, never a remotely supplied SDK method name.
// The shipped SDK has no verified controlled-stop API: its actual releaseSdk
// callback may request cleanup, but this path always reports physical unknown.
function createSoftwareStopAdapter({getExecutionState,releaseSdk,requestControlledStop=null,readStopEvidence=null,
  nativeStopSupported=false,stopProfile=null,clock={now:()=>Date.now(),monotonic:()=>performance.now()},
  timeoutMs=1000,schedule=setTimeout,cancel=clearTimeout}){
  if(typeof getExecutionState!=='function'||typeof releaseSdk!=='function'||typeof clock?.now!=='function'
      ||typeof clock?.monotonic!=='function'||!Number.isSafeInteger(timeoutMs)||timeoutMs<1||timeoutMs>1000)throw Error('INVALID_SOFTWARE_STOP_ADAPTER');
  let profile=null;
  try{profile=structuredClone(stopProfile);}catch{/* Missing/invalid profile stays closed. */}
  // Query only the existing validator's profile precondition; these placeholders
  // are never feedback or returned hardware evidence.
  const profileValid=validateStopEvidence(null,{commandId:'00000000-0000-4000-8000-000000000001',
    executorEpoch:'00000000-0000-4000-8000-000000000001',hardwareFingerprint:'0'.repeat(64),now:0},profile).code==='STOP_UNCONFIRMED';
  const supported=nativeStopSupported===true&&typeof requestControlledStop==='function'
    &&typeof readStopEvidence==='function'&&profileValid;
  let pending=null,last=null,evidence=null;
  const seen=new Set();
  const matches=context=>{try{const actual=getExecutionState();return actual?.executorEpoch===context.executorEpoch&&actual.hardwareFingerprint===context.hardwareFingerprint;}catch{return false;}};
  const unknown=(request,code,sdkReleased=false)=>Object.freeze({commandId:request?.commandId??null,
    state:'unknown',code,sdkReleased,depowered:false});
  function safeEvidence(value){
    const m=value.measurement;
    return {commandId:value.commandId,executorEpoch:value.executorEpoch,hardwareFingerprint:value.hardwareFingerprint,
      requestedAt:value.requestedAt,observedAt:value.observedAt,state:'stopped',reason:value.reason,
      measurement:{kind:m.kind,sourceMode:m.sourceMode,profileDigest:m.profileDigest,
        jointVelocitiesRadS:[...m.jointVelocitiesRadS],jointDeltaDeg:[...m.jointDeltaDeg],sampleCount:m.sampleCount,
        stableDurationMs:m.stableDurationMs,driversDisabled:m.driversDisabled,
        ...(profile.stop.includesGripper?{gripperVelocityMmS:m.gripperVelocityMmS,gripperDeltaMm:m.gripperDeltaMm}:{})}};
  }
  function stop(request){
    if(!request||!UUID.test(request.commandId)||!UUID.test(request.executorEpoch)||!HASH.test(request.hardwareFingerprint)
        ||request.leaseId!==undefined&&request.leaseId!==null&&!UUID.test(request.leaseId)
        ||request.leaseEpoch!==undefined&&(!Number.isSafeInteger(request.leaseEpoch)||request.leaseEpoch<0))return Promise.resolve(unknown(request,'INVALID_STOP_CONTEXT'));
    const context=Object.freeze({...request});
    const sameRequest=other=>['commandId','executorEpoch','hardwareFingerprint','leaseId','leaseEpoch'].every(key=>other[key]===context[key]);
    if(!matches(context))return Promise.resolve(unknown(context,'WRONG_EXECUTOR'));
    if(pending)return pending.commandId===context.commandId?(sameRequest(pending.context)?pending.promise:Promise.resolve(unknown(context,'STOP_REQUEST_CONFLICT'))):Promise.resolve(unknown(context,'STOP_ALREADY_PENDING'));
    if(last?.commandId===context.commandId)return Promise.resolve(sameRequest(last.context)?last.result:unknown(context,'STOP_REQUEST_CONFLICT'));
    if(seen.has(context.commandId))return Promise.resolve(unknown(context,'STOP_REQUEST_REPLAYED'));
    const start=clock.monotonic(),requestedAt=clock.now();
    if(!Number.isFinite(start)||start<0||!Number.isSafeInteger(requestedAt)||requestedAt<0)return Promise.resolve(unknown(context,'STOP_CLOCK_INVALID'));
    const deadline=start+timeoutMs,operation=Object.freeze({...context,requestedAt});
    evidence=null;seen.add(context.commandId);
    let settle,timer,settled=false;
    const promise=new Promise(resolve=>{settle=resolve;});
    pending={commandId:context.commandId,context,promise};
    const clockCurrent=()=>{const value=clock.monotonic();return Number.isFinite(value)&&value>=start&&value<deadline;};
    const finish=result=>{
      if(settled)return;
      settled=true;if(timer!==undefined)cancel(timer);
      if(result.state!=='stopped')evidence=null;
      last={commandId:context.commandId,context,result};pending=null;settle(result);
    };
    const guard=()=>{
      if(settled)return false;
      if(!matches(context)){finish(unknown(context,'WRONG_EXECUTOR'));return false;}
      if(!clockCurrent()){finish(unknown(context,'STOP_RESPONSE_TIMEOUT'));return false;}
      return true;
    };
    const timeout=()=>{
      if(settled)return;
      if(!matches(context)){finish(unknown(context,'WRONG_EXECUTOR'));return;}
      const current=clock.monotonic();
      if(Number.isFinite(current)&&current>=start&&current<deadline){timer=schedule(timeout,deadline-current);timer?.unref?.();return;}
      finish(unknown(context,'STOP_RESPONSE_TIMEOUT'));
    };
    timer=schedule(timeout,timeoutMs);timer?.unref?.();
    Promise.resolve().then(async()=>{
      if(!guard())return;
      if(!supported){
        let released=false;
        try{const value=await releaseSdk(operation);released=value?.sdk_released===true||value?.sdkReleased===true;}catch{/* Never expose SDK error text. */}
        if(guard())finish(unknown(context,'CONTROLLED_STOP_UNSUPPORTED',released));
        return;
      }
      try{
        // Return booleans from an SDK are not stop evidence. Keep the SDK alive
        // for fresh feedback; only the explicitly approved native stop runs.
        await requestControlledStop(operation);
        if(!guard())return;
        const measured=await readStopEvidence(operation);
        if(!guard())return;
        const current={commandId:context.commandId,executorEpoch:context.executorEpoch,
          hardwareFingerprint:context.hardwareFingerprint,now:clock.now()};
        const verified=validateStopEvidence(measured,current,profile);
        if(!verified.ok||measured.requestedAt!==requestedAt){finish(unknown(context,'STOP_UNCONFIRMED'));return;}
        evidence=safeEvidence(measured);
        if(!guard())return;
        finish(Object.freeze({commandId:context.commandId,state:'stopped',code:'HARDWARE_STOP_VERIFIED',
          sdkReleased:false,depowered:verified.depowered,coverage:verified.coverage}));
      }catch{if(guard())finish(unknown(context,'STOP_UNCONFIRMED'));}
    }).catch(()=>finish(unknown(context,'STOP_UNCONFIRMED')));
    return promise;
  }
  return {
    stop,
    capabilities:()=>Object.freeze({softwareCancellation:true,controlledStop:supported,independentHardwareWatchdog:false}),
    getEvidence(context){
      if(!evidence||!context||!matches(context))return null;
      const current={...context,now:clock.now()};
      return validateStopEvidence(evidence,current,profile).ok?structuredClone(evidence):null;
    },
  };
}

module.exports={createSoftwareStopAdapter};
