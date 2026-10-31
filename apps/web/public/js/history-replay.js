/* Read-only measured-pose playback. No SDK, command, transport or live adapter. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;root.ThirdHandHistoryReplay=api;})(globalThis,function(){
  'use strict';
  function createHistoryReplay({armModel,samples,versions={},gapMs=500}){
    if(!Array.isArray(samples)||samples.length>500||!Number.isFinite(gapMs)||gapMs<=0)throw Error('Invalid bounded replay page');
    const micros=text=>{if(!Number.isFinite(Date.parse(text)))return null;return BigInt(Date.parse(text))*1000n+BigInt((/\.(\d+)/.exec(text)?.[1]||'').padEnd(6,'0').slice(3,6));};
    const ordered=samples.map(row=>({...row,micros:micros(row.captured_at)})).sort((a,b)=>a.micros===null?1:b.micros===null?-1:a.micros<b.micros?-1:a.micros>b.micros?1:0),start=ordered[0]?.micros;
    const rows=ordered.map(row=>({...row,time:row.micros===null||start===null?NaN:Number(row.micros-start)/1000}));
    function render(row){
      if(!row||!Number.isFinite(row.time))return {state:'invalid'};
      if(versions.expectedTool&&row.tool_version!==versions.expectedTool||versions.expectedCalibration&&row.calibration_version!==versions.expectedCalibration)return {state:'incompatible'};
      const angles=row.joint_position_rad?.map(value=>value*180/Math.PI);
      if(!Array.isArray(angles)||angles.length!==6||angles.some((value,joint)=>!Number.isFinite(value)||!armModel.jointLimits[joint]||value<armModel.jointLimits[joint][0]||value>armModel.jointLimits[joint][1]))return {state:'invalid'};
      armModel.setJointAngles(angles);return {state:'measured',capturedAt:row.captured_at,sampleSequence:row.sample_seq,sourceMode:row.extra?.sourceMode||'unknown'};
    }
    function seek(offsetMs){
      if(!rows.length)return {state:'empty'};if(!Number.isFinite(offsetMs)||offsetMs<0)return {state:'invalid'};
      const time=offsetMs;if(time>rows.at(-1).time)return {state:'end'};
      let index=0;while(index+1<rows.length&&rows[index+1].time<=time)index++;
      const row=rows[index],next=rows[index+1];
      if(next&&next.time-row.time>gapMs&&time>row.time)return {state:'gap',from:row.captured_at,to:next.captured_at};
      return render(row);
    }
    return {seek,showSample:index=>Number.isInteger(index)?render(rows[index]):{state:'invalid'},durationMs:rows.length?rows.at(-1).time:0,count:rows.length};
  }
  return {createHistoryReplay};
});
