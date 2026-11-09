'use strict';
// Owned by the one device relay, not by HTTP workers or the archival queue.
const {performance}=require('node:perf_hooks');
const KEYS=['deviceId','bootId','executorEpoch','connectionId','certificateId'];
const same=(a,b)=>!!a&&!!b&&KEYS.every(key=>a[key]===b[key]);
const vector=(v,n)=>Array.isArray(v)&&v.length===n&&v.every(Number.isFinite)?[...v]:null;
const scalar=(v,min=-Infinity,max=Infinity)=>Number.isFinite(v)&&v>=min&&v<=max?v:null;
function sanitizeSample(raw){
  if(!raw||typeof raw!=='object'||Array.isArray(raw))throw Error('INVALID_STATE');
  const fields={};
  for(const key of ['jointPositionRad','jointVelocityRadS','jointCurrentA','jointTorqueNm','jointTemperatureC'])fields[key]=vector(raw[key],6);
  for(const key of ['sdkConnected','moving'])fields[key]=raw.fieldAvailability?.[key]===true&&typeof raw[key]==='boolean'?raw[key]:null;
  fields.gripper={positionRatio:scalar(raw.gripper?.positionRatio,0,1),widthM:scalar(raw.gripper?.widthM,0)};
  fields.flangePositionM=vector(raw.extra?.flangePositionM,3);
  fields.flangeOrientationEulerRad=vector(raw.extra?.flangeOrientationEulerRad,3);
  fields.tcpPositionM=raw.tcpFrameId==='tool_tcp'&&raw.toolVersion&&raw.calibrationVersion?vector(raw.tcpPositionM,3):null;
  fields.tcpOrientationXyzw=fields.tcpPositionM?vector(raw.tcpOrientationXyzw,4):null;
  fields.fieldAvailability=Object.fromEntries(Object.entries(fields).filter(([key])=>key!=='gripper').map(([key,value])=>[key,value!==null]));
  fields.fieldAvailability.gripperPosition=fields.gripper.positionRatio!==null;
  fields.fieldAvailability.gripperWidth=fields.gripper.widthM!==null;
  fields.sourceMode=['hardware','simulation','dummy'].includes(raw.extra?.sourceMode)?raw.extra.sourceMode:'unknown';
  fields.capturedAt=raw.capturedAt;
  fields.clockQuality=['synchronized','estimated','unreliable'].includes(raw.clockQuality)?raw.clockQuality:'unreliable';
  fields.qualityFlags=Array.isArray(raw.qualityFlags)?raw.qualityFlags.filter(v=>typeof v==='string'&&/^[A-Z0-9_]{1,64}$/.test(v)).slice(0,16):[];
  fields.faultCode=typeof raw.faultCode==='string'&&/^[A-Za-z0-9_.-]{1,64}$/.test(raw.faultCode)?raw.faultCode:null;
  return fields;
}
function createLatestState({contextFor,wallNow=Date.now,monoNow=()=>performance.now(),capacity=128}){
  const samples=new Map();
  function accept(context,report){
    if(!same(contextFor(context.deviceId),context)||!context.executorEpoch)throw Error('INVALID_STATE_CONTEXT');
    const now=wallNow(),captured=Date.parse(report.sample?.capturedAt);
    if(report.schema!==1||report.purpose!=='latest_state'||!same(report.context,context)||
      !Number.isSafeInteger(report.sequence)||report.sequence<1||!Number.isSafeInteger(report.producerMonotonicNs)||report.producerMonotonicNs<1||
      !Number.isFinite(report.sourceAgeMs)||report.sourceAgeMs<0||report.sourceAgeMs>3000||
      !Number.isSafeInteger(report.issuedAt)||report.issuedAt>now||now-report.issuedAt>3000||
      !Number.isFinite(captured)||captured>now)throw Error('INVALID_STATE');
    const previous=samples.get(context.deviceId);
    if(previous&&same(previous.context,context)&&(report.sequence<=previous.sequence||report.producerMonotonicNs<=previous.producerMonotonicNs))throw Error('STATE_OUT_OF_ORDER');
    if(!previous&&samples.size>=capacity)throw Error('STATE_CAPACITY');
    const sample=sanitizeSample(report.sample);
    samples.set(context.deviceId,{context:{...context},sequence:report.sequence,producerMonotonicNs:report.producerMonotonicNs,sample,
      ageAtReceive:Math.max(report.sourceAgeMs+now-report.issuedAt,now-captured),receivedAt:new Date(now).toISOString(),receivedMono:monoNow()});
    return {accepted:true,sequence:report.sequence};
  }
  function get(deviceId){
    const context=contextFor(deviceId),entry=samples.get(deviceId),current=!!entry&&same(context,entry.context);
    const ageMs=entry?Math.max(0,entry.ageAtReceive+monoNow()-entry.receivedMono):null;
    return {schema:1,purpose:'display-only',deviceId,gatewayOnline:!!context,epochCurrent:current,
      context:context?Object.fromEntries(['bootId','executorEpoch','connectionId'].map(key=>[key,context[key]])):null,
      sequence:entry?.sequence??null,sample:entry?.sample??null,receivedAt:entry?.receivedAt??null,ageMs,
      fresh:current&&ageMs<=3000&&entry.sample.clockQuality!=='unreliable'&&!entry.sample.qualityFlags.includes('SDK_READ_FAILED'),freshnessLimitMs:3000,serverTime:new Date(wallNow()).toISOString()};
  }
  return {accept,get};
}
module.exports={createLatestState,sanitizeSample,same};
